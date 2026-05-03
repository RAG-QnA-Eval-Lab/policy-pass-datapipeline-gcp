# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hybrid RAG 기반 학생/청년 정부 정책 QnA 시스템. 멀티 LLM (GPT-4o, Claude, Gemini, Llama3) 응답 신뢰성을 3단계 평가 (RAGAS v0.4 + LLM Judge + DeepEval)로 비교하는 파이프라인. GCP Cloud Run 배포 대상. 개인 프로젝트 (졸업논문 + PyCon Korea CFP).

## Architecture

```
GCP 인프라:
  Cloud Storage (GCS)       — 실제 데이터 저장소 (정책 원본 JSON/PDF + FAISS 인덱스)
  Compute Engine VM #1      — MongoDB (메타데이터 전용, 34.47.80.98:27017, static IP) + Grafana (:3000)
  Compute Engine VM #2      — Airflow 2.9.3 (http://34.47.107.145:8080)
  Cloud Run #1 (BE, 2Gi)    — FastAPI + FAISS 인메모리 검색
  Cloud Run #2 (FE, 512Mi)  — Streamlit (httpx → BE API 호출)

src/
├── api/                # FastAPI 백엔드 — 6개 엔드포인트 (Health, Search, Generate, Policies, Models, Evaluate)
│   ├── main.py         # lifespan: FAISS 인덱스 로드 + MongoDB 연결. app.state에 저장
│   ├── deps.py         # FastAPI Depends: get_rag_pipeline(), get_mongo()
│   ├── schemas.py      # Pydantic 요청/응답 모델
│   ├── errors.py       # 글로벌 예외 핸들러
│   ├── middleware.py    # 요청 로깅 미들웨어 (log_structured 사용)
│   ├── logging_config.py   # Cloud Run JSON 구조화 로깅 (CloudRunJsonFormatter + log_structured)
│   └── routes/         # search, generate, policies, models, evaluate
├── ingestion/          # 수집 → GCS 원본 저장 + MongoDB 메타데이터 → 청킹 → FAISS 인덱스 빌드
│   ├── collectors/     # 정부 사이트별 크롤러. base.py에 Policy frozen dataclass + BaseCollector ABC
│   ├── chunker.py      # 문장 경계 기반 청킹 (kss 한국어 분리 → tiktoken 토큰 카운트)
│   ├── embedder.py     # LiteLLM embedding API 래퍼 (배치 + 재시도)
│   ├── gcs_client.py   # GCS 업로드/다운로드
│   ├── mongo_client.py # PolicyMetadataStore — MongoDB 메타데이터 CRUD
│   └── pipeline.py     # 오케스트레이션: 로컬/GCS 모드 인덱스 빌드
├── retrieval/          # 4가지 검색 전략: vector_only, bm25_only, hybrid (RRF k=60), hybrid_rerank
│   ├── pipeline.py     # RetrievalPipeline — SearchStrategy enum으로 전략별 분기
│   └── ...             # vector_store, bm25_store, hybrid, reranker
├── generation/         # LiteLLM 래퍼 + 정책 도메인 프롬프트 + RAG 오케스트레이션
│   ├── llm_client.py   # generate() — LiteLLM completion (재시도 + 토큰/레이턴시 추적)
│   ├── prompt.py       # build_rag_prompt(), build_no_rag_prompt()
│   └── pipeline.py     # RAGPipeline.run() / run_no_rag()
├── evaluation/         # 3단계 평가 구현 완료
│   ├── ragas_metrics.py    # evaluate_ragas() — RAGAS v0.4 SingleTurnSample 기반
│   ├── llm_judge.py        # judge_response() — G-Eval 방식, Position Bias 완화 (2회 평가 평균)
│   ├── safety_metrics.py   # evaluate_safety() — DeepEval HallucinationMetric
│   ├── evaluator.py        # RAGEvaluator — 3단계 통합 오케스트레이터
│   └── report.py           # generate_report() — JSON + HTML 리포트
└── ui/                 # Streamlit 프론트엔드 (httpx → BE API 호출)
    ├── app.py              # 메인 엔트리포인트: st.navigation() 멀티페이지, 사이드바 /health 상태
    ├── pages/
    │   ├── chatbot.py      # QnA 챗봇 — RAG/No-RAG 비교, 출처 인용, 모델·전략 선택
    │   ├── policy_explore.py   # 정책 탐색 — 카테고리 탭, 카드 그리드, 상세 14필드
    │   ├── recommend.py    # 맞춤 추천 — 사용자 조건 입력 → generate API 호출
    │   └── dashboard.py    # 평가 대시보드 — RAGAS/Judge/Safety 메트릭 Plotly 차트
    ├── components/
    │   ├── policy_card.py      # 정책 카드·상세 렌더링. 지역 코드→지역명 변환, XSS 방지
    │   ├── chat_message.py     # 챗봇 답변 + 출처 expander + 토큰/레이턴시
    │   └── metrics_display.py  # Plotly gauge + st.metric 시각화
    └── utils/
        ├── api_client.py   # APIClient (httpx) — BE 7개 엔드포인트 래핑, @st.cache_resource 싱글톤
        ├── session_state.py    # init_state() — 채팅 히스토리·모델·전략 세션 상태
        └── style.py        # 커스텀 CSS (카드 그리드, 카테고리 태그, 반응형)

config/
├── settings.py         # pydantic-settings Settings 클래스 (.env 자동 로드). 싱글톤: settings
├── models.py           # MODELS dict — 모델 키 → LiteLLM ID 매핑. resolve_model_key()로 조회
└── policy_sources.py   # POLICY_SOURCES dict — 데이터 소스별 URL/수집방식

dags/                   # Airflow DAGs (VM #2에 배포)
├── dag_collect_index.py    # 수집+인덱싱 (매일 02:00 KST)
├── dag_qa_generation.py    # QA 데이터셋 생성 (수동 트리거)
└── dag_evaluation.py       # 평가 실행 (수동 트리거)

monitoring/grafana/     # Grafana 대시보드 프로비저닝
├── dashboards/rag-pipeline.json    # 5패널: CPU, 메모리, 디스크, 네트워크, VM 상태 (Node Exporter)
└── provisioning/                   # datasources.yml (Prometheus + Cloud Monitoring), dashboards.yml

monitoring/prometheus/  # Prometheus 설정
└── prometheus.yml      # scrape: node-mongo-vm(:9100), node-airflow-vm(10.178.0.4:9100), mongodb(:9216)

scripts/
├── setup_uptime_check.sh   # GCP Uptime Check + 이메일 알림 설정 (gcloud CLI)
├── setup_grafana.sh        # MongoDB VM에서 Node Exporter + Prometheus + Grafana 일체 설치
└── ...                     # 기존 수집/평가 스크립트
```

**핵심 데이터 타입 (frozen dataclass)**:
- `Policy` (`src/ingestion/collectors/base.py`) — 정책 표준 스키마, 모든 수집기가 이 형태로 정규화
- `SearchResult` (`src/retrieval/__init__.py`) — 검색 결과 (content, score, metadata, rank)
- `LLMResponse`, `RAGResponse` (`src/generation/__init__.py`) — LLM 응답 + RAG 통합 응답
- `RagasResult`, `JudgeResult`, `SafetyResult`, `EvalResult` (`src/evaluation/__init__.py`) — 평가 결과

**데이터 흐름**:
1. 수집: 정부사이트 → collectors → GCS (원본 저장) + MongoDB (메타데이터)
2. 인덱싱: GCS/로컬 원본 → loader → chunker → embedder → FAISS index + metadata.pkl
3. 서빙: Cloud Run 기동 → GCS에서 FAISS 다운로드 → RetrievalPipeline → RAGPipeline → LLM 생성
4. 오케스트레이션: Airflow DAGs — 수집+인덱싱 매일 02:00, 평가/QA 생성 수동 트리거

**FastAPI API 라우트**:

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/health` | GET | FAISS/MongoDB 상태 + 업타임 |
| `/api/v1/search` | POST | 검색만 (SearchRequest → SearchResponse) |
| `/api/v1/generate` | POST | RAG 생성 (GenerateRequest → GenerateResponse). no_rag 옵션 |
| `/api/v1/policies` | GET | 정책 목록 (category/page/limit 쿼리 파라미터) |
| `/api/v1/policies/{id}` | GET | 정책 상세 |
| `/api/v1/models` | GET | 사용 가능 모델 + default_model |
| `/api/v1/evaluate` | POST | 3단계 평가 실행 (EvalRequest → EvalResponse) |

## Implementation Progress

`docs/plan.md`에 Phase 0~6 구현 계획이 정의되어 있다.

- Phase 0 (준비): 완료
- Phase 1 (수집+인덱싱): 완료. 정책 2,235건 수집, FAISS 인덱스 빌드
- Phase 2 (검색): 완료. 4가지 전략 + 코드리뷰 + 버그 수정
- Phase 3 (생성): 완료. LiteLLM + Vertex AI 통합. `LLMError` 커스텀 예외 도입 (status_code 기반 HTTP 매핑)
- Phase 4 (평가): 완료. RAGAS v0.4 + LLM Judge + DeepEval 3단계 구현
- FastAPI API: 완료. 6개 엔드포인트 + 미들웨어 + 에러 핸들링. `LLMError` 타입 기반 에러 핸들링
- Phase 5 (UI): 완료. Streamlit 4페이지 (챗봇, 정책 탐색, 맞춤 추천, 평가 대시보드). 정책 상세 14개 필드 표시, 지역 코드→지역명 변환, XSS 방지
- Phase 6 (배포+실험): Dockerfile 4종 + GitHub Actions 5종 작성 완료. 구조화 JSON 로깅 + Uptime Check + Grafana 대시보드 인프라 완료
- QA 데이터셋: 100쌍 생성 완료 (`data/eval/qa_pairs.json`)
- 테스트: 261 passed (API 26 + UI + 평가 + 수집/검색/생성 + Phase 6 유틸리티 20 + 로깅 8)

## Commands

```bash
# Setup
pip install -e ".[dev,api,ingestion,indexer,ko,eval,monitoring,crawl,ui,viz]"

# Tests (253 tests)
pytest                              # 전체
pytest tests/test_api.py            # 단일 모듈
pytest -k "test_chunk_size"         # 패턴 매칭
pytest --cov=src --cov-report=term-missing

# Lint
ruff check .
ruff format .

# Pipelines
python scripts/collect_policies.py --all                                        # 정책 수집
python -m src.ingestion.pipeline --input data/policies/raw --output data/index  # 로컬 인덱스 빌드
python -m src.ingestion.pipeline --gcs --bucket rag-qna-eval-data              # GCS 모드 인덱스 빌드
python -m src.retrieval.pipeline --query "질문" --strategy hybrid_rerank       # 검색 테스트
python -m src.generation.pipeline --query "질문" --model gemini-flash --strategy hybrid_rerank

# BE (로컬 — macOS FAISS OpenMP 충돌 방지 포함)
./run_api.sh                # KMP_DUPLICATE_LIB_OK 등 OpenMP 환경변수 설정 후 uvicorn 실행
uvicorn src.api.main:app --host 0.0.0.0 --port 8000  # 직접 실행 (OpenMP 충돌 발생 가능)

# FE (로컬 — BE 서버 실행 필요)
streamlit run src/ui/app.py

# Docker
docker build -t rag-youth-policy-api .                    # BE
docker build -t rag-youth-policy-ui -f Dockerfile.ui .    # FE
```

## Key Technical Decisions

- **RAGAS v0.4 only** (not v0.3). `ragas>=0.4,<0.5` pinning 필수. `evaluate()` 대신 `metric.single_turn_ascore()` 사용. 온라인 예시 대부분 v0.3이므로 주의.
- **LiteLLM 멀티 프로바이더** 모델 통합. 모델 키를 `config/models.py`의 `MODELS` dict에서 LiteLLM ID로 매핑 (`resolve_model_key()`). 프로바이더별 경로: OpenAI 직접 호출 `openai/gpt-4o-mini`, Vertex AI Model Garden `vertex_ai/gemini-2.5-flash` · `vertex_ai/claude-sonnet-4-5`, HuggingFace `huggingface/meta-llama/Llama-3.3-70B-Instruct`.
- **FAISS (faiss-cpu)** + metadata dict (pickle). Cloud Run stateless에 적합. ChromaDB 대신 선택.
- **GCS** = 실제 데이터 저장소. **MongoDB** = 메타데이터 전용. Cloud Run 기동 시 GCS에서 FAISS 인덱스 다운로드.
- **Hybrid Search**: Vector + BM25 → RRF (k=60) → Cross-Encoder rerank. `SearchStrategy` enum으로 4가지 전략 제어.
- **한국어 처리**: kss (문장 분리, optional import), tiktoken cl100k_base (토큰 카운트), 공백 기반 BM25 토크나이징.
- **Policy 스키마**: `collectors/base.py`의 frozen dataclass. `REQUIRED_FIELDS` + `CATEGORY_MAP`/`VALID_CATEGORIES` 정규화.
- **테스트**: 외부 API (OpenAI, MongoDB, GCS) 모두 mock 처리. `tests/conftest.py`에 공유 fixtures.
- **CI/CD**: GitHub Actions 5종 — `ci.yml` (PR lint+test), `deploy-api.yml` (BE), `deploy-ui.yml` (FE), `deploy-jobs.yml` (수집/인덱싱 Job), `deploy-airflow.yml` (Airflow VM 코드 동기화).
- **FastAPI lifespan**: `app.state.rag_pipeline` (RAGPipeline), `app.state.mongo` (PolicyMetadataStore). 라우트에서 `deps.py`의 `get_rag_pipeline()`, `get_mongo()`로 접근.
- **Airflow DAG 경로**: `_validate_path()`로 `ALLOWED_DATA_DIR = /opt/rag-pipeline/data` 내부로 제한. params의 경로는 `data/` 기준 상대경로.
- **LLMError 예외 체계**: `LLMError(RuntimeError)` 커스텀 예외에 `status_code` 속성. LiteLLM 예외를 HTTP 코드로 매핑 (NotFound→404, Auth→401, BadRequest→400, RateLimit/Connection→502+재시도). generate 라우트에서 `HTTPException(status_code=exc.status_code)`로 전파.
- **Vertex AI 리전 오버라이드**: `_VERTEX_LOCATION_OVERRIDES` dict (`llm_client.py`). 모델별 리전 지정 — Gemini 2.5 Pro는 `us-central1`, Claude Sonnet 4.5는 `us-east5` (Model Garden 가용 리전).
- **UI XSS 방지**: `policy_card.py`에서 `html.escape()`로 사용자 노출 데이터 이스케이프, 출처 URL은 `https://`/`http://` 스킴만 허용.

## Environment Variables (.env)

로컬 개발은 `.env`, GCP 배포 런타임은 Secret Manager를 사용한다.

```
DATA_PORTAL_API_KEY=         # 공공데이터포털 API
MONGODB_URI=mongodb://34.47.80.98:27017
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
- ruff: line-length 120, target Python 3.11+. lint rules: E, F, W, I.
- Dockerfile CMD: `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT` (Cloud Run은 `PORT` 환경변수 주입).
- 크롤링: robots.txt 준수, 요청 간격 2~3초, User-Agent 설정.
