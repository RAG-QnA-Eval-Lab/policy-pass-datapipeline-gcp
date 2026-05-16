# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hybrid RAG 기반 학생/청년 정부 정책 QnA 시스템. 멀티 LLM (GPT-4o, Claude, Gemini, Llama3) 응답 신뢰성을 3단계 평가 (RAGAS v0.4 + LLM Judge + DeepEval)로 비교하는 파이프라인. GCP Cloud Run 배포 대상. 개인 프로젝트 (졸업논문 + PyCon Korea CFP).

## Commands

```bash
# Setup
pip install -e ".[dev,api,ingestion,indexer,ko,eval,monitoring,crawl,ui,viz]"

# Tests
pytest                              # 전체 (261 tests)
pytest tests/test_api.py            # 단일 모듈
pytest -k "test_chunk_size"         # 패턴 매칭
pytest --cov=src --cov-report=term-missing

# Lint
ruff check .
ruff format .

# BE (로컬 — macOS FAISS OpenMP 충돌 방지 포함)
./run_api.sh                # OpenMP 환경변수 설정 후 uvicorn 실행 (추천)
uvicorn src.api.main:app --host 0.0.0.0 --port 8000  # 직접 실행 (OpenMP 충돌 가능)

# FE (로컬 — BE 서버 실행 필요)
streamlit run src/ui/app.py

# Pipelines
python scripts/collect_policies.py --all
python -m src.ingestion.pipeline --input data/policies/raw --output data/index   # 로컬 인덱스
python -m src.ingestion.pipeline --gcs --bucket rag-qna-eval-data                # GCS 모드
python -m src.retrieval.pipeline --query "질문" --strategy hybrid_rerank
python -m src.generation.pipeline --query "질문" --model gemini-flash --strategy hybrid_rerank

# Docker
docker build -t rag-youth-policy-api .                    # BE
docker build -t rag-youth-policy-ui -f Dockerfile.ui .    # FE
```

## Architecture

```
GCP 인프라:
  Cloud Storage (GCS)       — 실제 데이터 저장소 (정책 원본 JSON/PDF + FAISS 인덱스)
  Compute Engine VM #1      — MongoDB (메타데이터 전용) + Grafana
  Compute Engine VM #2      — Airflow 2.9.3
  Cloud Run #1 (BE, 2Gi)    — FastAPI + FAISS 인메모리 검색
  Cloud Run #2 (FE, 512Mi)  — Streamlit (httpx → BE API 호출)

src/
  api/            FastAPI 백엔드 (6 엔드포인트)
  ingestion/      수집 → GCS/MongoDB → 청킹 → FAISS 인덱스 빌드
  retrieval/      4가지 검색 전략 (vector, bm25, hybrid RRF, hybrid_rerank)
  generation/     LiteLLM 래퍼 + 정책 도메인 프롬프트 + RAG 오케스트레이션
  evaluation/     3단계 평가 (RAGAS v0.4 + LLM Judge + DeepEval)
  ui/             Streamlit 4페이지 (챗봇, 정책 탐색, 맞춤 추천, 평가 대시보드)

config/
  settings.py       pydantic-settings 기반 (.env 자동 로드). 싱글톤: settings
  models.py         MODELS dict — 모델 키 → LiteLLM ID 매핑 (resolve_model_key())
  policy_sources.py 데이터 소스별 URL/수집방식

dags/               Airflow DAGs (수집+인덱싱 매일 02:00, 평가/QA 생성 수동)
```

**데이터 흐름**:
1. **수집**: 정부사이트 → collectors → GCS (원본 저장) + MongoDB (메타데이터)
2. **인덱싱**: 원본 → chunker (kss 문장 분리 + tiktoken 토큰 카운트) → embedder → FAISS index + metadata.pkl
3. **서빙**: Cloud Run 기동 → GCS에서 FAISS 다운로드 → RetrievalPipeline → RAGPipeline → LLM 생성
4. **오케스트레이션**: Airflow DAGs — 수집+인덱싱 매일 02:00 KST, 평가/QA 생성 수동 트리거

**핵심 데이터 타입 (frozen dataclass)**:
- `Policy` (`src/ingestion/collectors/base.py`) — 정책 표준 스키마, 모든 수집기가 이 형태로 정규화
- `SearchResult` (`src/retrieval/__init__.py`) — 검색 결과 (content, score, metadata, rank)
- `LLMResponse`, `RAGResponse` (`src/generation/__init__.py`) — LLM 응답 + RAG 통합 응답
- `RagasResult`, `JudgeResult`, `SafetyResult`, `EvalResult` (`src/evaluation/__init__.py`) — 평가 결과

**FastAPI API 라우트**:

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/health` | GET | FAISS/MongoDB 상태 + 업타임 |
| `/api/v1/search` | POST | 검색 (SearchRequest → SearchResponse) |
| `/api/v1/generate` | POST | RAG 생성 (GenerateRequest → GenerateResponse). no_rag 옵션 |
| `/api/v1/policies` | GET | 정책 목록 (category/page/limit 쿼리 파라미터) |
| `/api/v1/policies/{id}` | GET | 정책 상세 |
| `/api/v1/models` | GET | 사용 가능 모델 + default_model |
| `/api/v1/evaluate` | POST | 3단계 평가 실행 (EvalRequest → EvalResponse) |

## Key Technical Decisions

- **RAGAS v0.4 only** (not v0.3). `ragas>=0.4,<0.5` pinning 필수. `evaluate()` 대신 `metric.single_turn_ascore()` 사용. 온라인 예시 대부분 v0.3이므로 주의.
- **LiteLLM 멀티 프로바이더**: 모델 키를 `config/models.py`의 `MODELS` dict에서 LiteLLM ID로 매핑. 프로바이더별 경로: `openai/gpt-4o-mini`, `vertex_ai/gemini-2.5-flash`, `anthropic/claude-sonnet-4-5`, `huggingface/meta-llama/Llama-3.3-70B-Instruct`.
- **FAISS (faiss-cpu)** + metadata dict (pickle). ChromaDB 대신 선택 — Cloud Run stateless에 적합.
- **GCS** = 실제 데이터 저장소, **MongoDB** = 메타데이터 전용. Cloud Run 기동 시 GCS에서 FAISS 인덱스 다운로드.
- **Hybrid Search**: Vector + BM25 → RRF (k=60) → Cross-Encoder rerank. `SearchStrategy` enum으로 4가지 전략 제어.
- **한국어 처리**: kss (문장 분리, optional import), tiktoken cl100k_base (토큰 카운트), 공백 기반 BM25 토크나이징.
- **FastAPI lifespan**: `app.state.rag_pipeline` (RAGPipeline), `app.state.mongo` (PolicyMetadataStore). 라우트에서 `deps.py`의 `get_rag_pipeline()`, `get_mongo()`로 접근.
- **LLMError 예외 체계**: `LLMError(RuntimeError)`에 `status_code` 속성. LiteLLM 예외를 HTTP 코드로 매핑 (NotFound→404, Auth→401, RateLimit→502+재시도). generate 라우트에서 `HTTPException(status_code=exc.status_code)`로 전파.
- **Vertex AI 리전 오버라이드**: `_VERTEX_LOCATION_OVERRIDES` dict (`llm_client.py`). Gemini 2.5 Pro→`us-central1`, Claude Sonnet 4.5→`us-east5` (Model Garden 가용 리전).
- **Airflow DAG 경로 제한**: `_validate_path()`로 `ALLOWED_DATA_DIR = /opt/rag-pipeline/data` 내부로 제한. params의 경로는 `data/` 기준 상대경로.
- **Claude Code 프록시 우회**: `src/api/main.py` 최상단에서 `ANTHROPIC_BASE_URL`이 `api.anthropic.com`이 아닌 경우 제거. Claude Code가 주입하는 프록시 URL이 LiteLLM 라우팅을 오염시키는 것을 방지.
- **OpenMP 충돌 방지**: `src/api/main.py` 최상단에서 `KMP_DUPLICATE_LIB_OK=TRUE` 등 환경변수 설정. macOS에서 FAISS + PyTorch가 각각 OpenMP를 로드하면 충돌. `run_api.sh`로 실행하면 자동 처리.
- **테스트**: 외부 API (OpenAI, MongoDB, GCS) 모두 mock 처리. `tests/conftest.py`에 공유 fixtures (`sample_policy`, `sample_api_response` 등).

## Environment Variables (.env)

로컬 개발은 `.env`, GCP 배포 런타임은 Secret Manager를 사용한다.

```
OPENAI_API_KEY=              # OpenAI 직접 호출용
ANTHROPIC_API_KEY=           # Anthropic 직접 호출용
GOOGLE_API_KEY=              # Google AI 직접 호출용
DATA_PORTAL_API_KEY=         # 공공데이터포털 API
MONGODB_URI=mongodb://...
MONGODB_DB=rag_youth_policy
GCP_PROJECT=rag-qna-eval
GCS_BUCKET=rag-qna-eval-data
VERTEXAI_PROJECT=rag-qna-eval
VERTEXAI_LOCATION=asia-northeast3
API_BASE_URL=                # FE → BE 통신 URL (Cloud Run 배포 시 설정)
```

## Constraints

- GCP 크레딧 ₩786,544 (2026-06-19 만료, 일회성). Region: asia-northeast3 (서울).
- 모든 코드와 UI는 한국어 도메인 (정부 정책).
- Cloud Run: scale-to-zero, max 1 instance, 2Gi memory (Cross-Encoder 로드).
- ruff: line-length 120, target Python 3.11+. lint rules: E, F, W, I. isort known-first-party: `src`, `config`.
- Dockerfile CMD: `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT` (Cloud Run은 `PORT` 환경변수 주입).
- 크롤링: robots.txt 준수, 요청 간격 2~3초, User-Agent 설정.
- CI/CD: GitHub Actions 5종 — `ci.yml` (PR lint+test), `deploy-api.yml` (BE), `deploy-ui.yml` (FE), `deploy-jobs.yml` (수집/인덱싱 Job), `deploy-airflow.yml` (Airflow VM 동기화).
