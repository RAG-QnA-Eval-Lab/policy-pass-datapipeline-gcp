# RAG-QA-pipeline-GCP

Hybrid RAG 기반 학생/청년 정부 정책 QnA 시스템. 멀티 LLM (GPT-4o, Claude, Gemini, Llama3) 응답 신뢰성을 3단계 자동 평가 (RAGAS v0.4 + LLM Judge + DeepEval)로 비교하는 파이프라인.

> **구현 현황** (2026-05-03): 수집/검색/생성/평가/FastAPI API/Streamlit UI 전체 완료 (261 tests passed). 정책 2,235건 수집, QA 100쌍 생성, FAISS 인덱스 빌드 완료. UI 4페이지 구현 완료 (챗봇, 정책 탐색, 맞춤 추천, 평가 대시보드). 논문용 실험 파이프라인 (`scripts/experiments/`) 구현 완료.

---

## 주요 기능

- **Hybrid 검색**: Vector (FAISS) + BM25 + Cross-Encoder Reranker (RRF k=60)
- **멀티 LLM 비교**: GPT-4o, Claude Sonnet 4.5, Gemini 2.5 Flash/Pro, Llama 3.3 70B — LiteLLM 멀티 프로바이더
- **3단계 신뢰성 평가**: RAGAS v0.4 정량 / LLM Judge (G-Eval) 정성 / DeepEval 안전성 자동화
- **FastAPI 백엔드 API**: 6개 엔드포인트 (Health, Search, Generate, Policies, Models, Evaluate)
- **정책 도메인 특화**: 온통청년, 공공데이터포털, 한국장학재단, 정부 PDF 보고서 수집
- **QA 데이터셋 자동 생성**: 정책 원본 → GPT-4o-mini로 100쌍 자동 생성 (`scripts/generate_qa.py`)
- **GCP 배포**: Cloud Run scale-to-zero (BE FastAPI 2Gi / FE Streamlit 512Mi)
- **CI/CD**: GitHub Actions 5개 워크플로 (lint+test, BE/FE/Jobs/Airflow VM 자동 배포)
- **Airflow 오케스트레이션**: 수집+인덱싱 DAG (매일 02:00 KST), 평가/QA 생성 DAG (수동)
- **Streamlit UI**: 4페이지 구현 완료 (QnA 챗봇 / 정책 탐색 / 맞춤 추천 / 평가 대시보드)

---

## 아키텍처

![RAG-QA Pipeline Architecture](docs/rag-qa-architecture.jpg)

> 📎 [draw.io 원본 파일](docs/rag-qa-pipeline.drawio) — 다이어그램 편집 가능

**데이터 흐름**

1. **수집**: 정부사이트 → collectors → GCS (원본 JSON/PDF) + MongoDB (`policies`, `ingestion_logs`, `gcs_assets`)
2. **인덱싱**: GCS 원본 → chunker (kss 문장 분리 + tiktoken 토큰 카운트) → embedder → FAISS index + metadata.pkl → GCS 업로드 + MongoDB catalog 동기화
3. **서빙**: Cloud Run 기동 시 GCS에서 FAISS 인덱스 다운로드 → 인메모리 검색
4. **오케스트레이션**: Airflow DAGs — 수집+인덱싱 (매일 02:00 KST), 평가/QA 생성 (수동 트리거)
5. **QA 생성**: 정책 원본 → GPT-4o-mini 자동 생성 → `data/eval/qa_pairs.json` + GCS 업로드 + MongoDB (`qa_datasets`, `gcs_assets`) 동기화
6. **평가**: QA 데이터셋 × 모델 × 전략 → 3단계 평가 (RAGAS + Judge + DeepEval) → JSON/HTML 리포트

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| LLM 통합 | LiteLLM 멀티 프로바이더 (OpenAI 직접 / Vertex AI Model Garden / HuggingFace) |
| 임베딩 | OpenAI `text-embedding-3-small` (1536차원, LiteLLM 경유) |
| 벡터 검색 | FAISS (faiss-cpu) + pickle 직렬화 |
| 키워드 검색 | rank-bm25 |
| 리랭킹 | sentence-transformers Cross-Encoder |
| 평가 (정량) | RAGAS v0.4 (Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall) |
| 평가 (정성) | 커스텀 LLM Judge (G-Eval 방식, Position Bias 완화) |
| 평가 (안전성) | DeepEval HallucinationMetric |
| 데이터 수집 | httpx + BeautifulSoup4, PyMuPDF |
| 한국어 처리 | kss (문장 분리), tiktoken cl100k_base (토큰 카운트) |
| 백엔드 | FastAPI + uvicorn |
| 프론트엔드 | Streamlit (4페이지 구현 완료) |
| 데이터 저장 | GCS (원본/정규화/QA/프롬프트/인덱스 source of truth), MongoDB (Compass 조회용 메타데이터/catalog) |
| 워크플로 오케스트레이션 | Apache Airflow 2.9.3 (self-hosted VM) |
| 배포 | GCP Cloud Run, Artifact Registry |
| 모니터링 | Grafana + GCP Cloud Monitoring + Cloud Logging |
| CI/CD | GitHub Actions (경로 필터 기반 자동 배포) |
| 린터/포매터 | ruff |
| 테스트 | pytest (261 tests) |

### LLM 모델 라우팅

모든 LLM 호출은 LiteLLM을 통해 **프로바이더별로 분산** 라우팅된다:

| 모델 | LiteLLM ID | 프로바이더 | 인증 |
|------|-----------|----------|------|
| GPT-4o-mini | `openai/gpt-4o-mini` | OpenAI API 직접 | `OPENAI_API_KEY` |
| GPT-4o | `openai/gpt-4o` | OpenAI API 직접 | `OPENAI_API_KEY` |
| Claude Sonnet 4.5 | `vertex_ai/claude-sonnet-4-5` | Vertex AI Model Garden (us-east5) | GCP 서비스 계정 |
| Gemini 2.5 Flash | `vertex_ai/gemini-2.5-flash` | Vertex AI Model Garden | GCP 서비스 계정 |
| Gemini 2.5 Pro | `vertex_ai/gemini-2.5-pro` | Vertex AI Model Garden (us-central1) | GCP 서비스 계정 |
| Llama 3.3 70B | `huggingface/meta-llama/Llama-3.3-70B-Instruct` | HuggingFace Inference API | `HUGGINGFACE_API_KEY` |

임베딩은 OpenAI `text-embedding-3-small` (1536차원)을 LiteLLM `litellm.embedding()` 경유로 호출.

---

## 데이터 적재 및 관리 파이프라인

### 1. 수집 (Collection)

정부 청년정책 사이트에서 데이터를 수집하여 `Policy` frozen dataclass로 정규화한다.

```
청년센터 API (youthcenter.go.kr)        공공데이터포털 API (data.go.kr)
        │                                       │
        ▼                                       ▼
  YouthGoCollector                      DataPortalCollector
        │            페이지네이션 (100건/page)     │
        │            요청 간 2초 sleep              │
        │            robots.txt 준수               │
        └──────────────┬───────────────────────────┘
                       ▼
              list[Policy]  ← frozen dataclass (16개 필드)
                │
                │  validate_policy(): 필수 필드 검증
                │  normalize_category(): 한국어 → 영문 표준 카테고리
                │  build_raw_content(): 검색용 원문 텍스트 생성
                ▼
```

`Policy` 스키마 (`src/ingestion/collectors/base.py`): `policy_id`, `title`, `category`, `description`, `eligibility`, `benefits`, `how_to_apply`, `application_period`, `managing_department`, `target_age`, `region`, `source_url`, `source_name`, `last_updated`, `raw_content` 등 16개 필드.

### 2. 이중 저장 (Dual Storage)

수집된 데이터와 산출물은 **GCS(source of truth)** + **MongoDB(Compass 조회용 catalog/metadata)** 구조로 관리한다. 실제 JSON, 프롬프트, 인덱스 파일은 GCS에 두고, MongoDB에는 운영자가 Compass에서 확인할 수 있는 목록/상태/참조 경로를 저장한다.

```
list[Policy]
    │
    ├──→ GCS (gs://rag-qna-eval-data/policies/raw/)
    │       ├─ <source>/latest.json         ← 전체 원본 데이터
    │       └─ <source>/snapshots/<ts>.json  ← 시점별 스냅샷
    │
    └──→ MongoDB (rag_youth_policy.policies)
            └─ 메타데이터만 (policy_id, title, category, source_name, updated_at)
```

| 저장소 | 역할 | 예시 |
|--------|------|------|
| **GCS** | 실제 데이터 저장소 | 정책 raw/processed JSON, QA dataset, QA prompt, FAISS index, metadata.pkl |
| **MongoDB** | 운영 조회용 메타데이터/catalog | 정책 목록, 수집 이력, GCS 객체 목록, QA dataset 요약, QA 샘플 |

MongoDB 컬렉션:

| 컬렉션 | 내용 | 대표 필드 |
|--------|------|-----------|
| `policies` | 정책 메타데이터 (14개 필드) | `policy_id`, `title`, `category`, `summary`, `description`, `eligibility`, `benefits`, `how_to_apply`, `application_period`, `managing_department`, `region`, `source_url`, `source_name`, `last_updated`, `gcs_path`, `status` |
| `ingestion_logs` | 수집 실행 이력 | `source`, `collected_count`, `valid_count`, `gcs_paths`, `created_at` |
| `gcs_assets` | GCS 객체 catalog | `asset_type`, `gcs_uri`, `object_name`, `size`, `md5_hash`, `updated`, `synced_at` |
| `qa_datasets` | QA 데이터셋 버전/요약 | `dataset_id`, `gcs_uri`, `model`, `total_count`, `difficulty_distribution` |
| `qa_pairs` | QA 샘플 복사본 | `_type`, `id`, `question`, `ground_truth`, `difficulty`, `policy_id` |

`gcs_assets.asset_type`은 `raw_policy`, `processed_policy`, `qa_dataset`, `qa_prompt`, `index_artifact`, `eval_result` 등으로 구분한다.

### 3. 청킹 → 임베딩 → 인덱싱

```
GCS 원본 JSON
    │
    ▼
  loader.py: load_directory() — PDF/TXT/JSON 로드
    │
    ▼
  chunker.py: chunk_documents()
    │  ① kss.split_sentences() — 한국어 문장 경계 분리
    │  ② tiktoken cl100k_base — 토큰 수 계산
    │  ③ 슬라이딩 윈도우 머지 (chunk_size=512, overlap=50 토큰)
    │
    ▼
  embedder.py: embed_texts()
    │  ① 100개씩 배치 분할
    │  ② LiteLLM → OpenAI text-embedding-3-small 호출 (1536차원)
    │  ③ 실패 시 3회 재시도 (exponential backoff)
    │
    ▼
  pipeline.py: _build_faiss_index()
    │  FAISS IndexFlatL2(1536) + metadata dict 리스트
    │
    ▼
  faiss.index (바이너리) + metadata.pkl (pickle)
    │
    └──→ GCS 업로드 (gs://bucket/index/)
```

두 가지 빌드 모드 지원:
- **로컬**: `python -m src.ingestion.pipeline --input data/policies/raw --output data/index`
- **GCS**: `python -m src.ingestion.pipeline --gcs --bucket rag-qna-eval-data`

### 4. 서빙 시 인덱스 로드

Cloud Run 기동 시 (FastAPI lifespan):
1. GCS에서 `faiss.index` + `metadata.pkl` 다운로드
2. FAISS 인덱스 메모리 로드 → `app.state.rag_pipeline`
3. MongoDB 연결 → `app.state.mongo`
4. 라우트에서 `deps.py`의 `get_rag_pipeline()`, `get_mongo()`로 접근

Cloud Run은 scale-to-zero이므로 콜드 스타트마다 GCS에서 최신 인덱스를 가져온다.

### 5. Airflow 오케스트레이션

```
Airflow VM (e2-standard-2)
  │
  ├── DAG 1: 수집+인덱싱 (매일 02:00 KST)
  │     collect → index_build → cloud_run_restart
  │
  ├── DAG 2: 평가 (수동 트리거)
  │     load_qa → run_rag → evaluate_3stage → save_report
  │
  └── DAG 3: QA 생성 (수동 트리거)
        load_policies → generate_qa → save_dataset
```

### GCS 버킷 구조

```
gs://rag-qna-eval-data/
├── policies/
│   ├── raw/
│   │   ├── data_portal/
│   │   │   ├── latest.json
│   │   │   └── snapshots/<timestamp>.json
│   │   └── youthgo/
│   │       ├── latest.json
│   │       └── snapshots/<timestamp>.json
│   └── processed/
│       ├── all_policies.json
│       ├── manifest.json
│       ├── by_source/
│       │   └── data_portal.json
│       └── by_category/
│           ├── education.json
│           ├── employment.json
│           ├── housing.json
│           ├── participation.json
│           └── welfare.json
├── eval/
│   └── qa_pairs.json           # 평가 QA 데이터셋
├── prompts/
│   └── qa_generation_system.txt
├── index/
│   ├── faiss.index             # FAISS 벡터 인덱스
│   └── metadata.pkl            # 청크 메타데이터
└── results/                    # 평가 JSON/HTML 리포트
```

위 파일들이 GCS의 실제 데이터 포맷이며, MongoDB `gcs_assets`는 이 객체들의 catalog를 동기화해서 Compass에서 조회하는 용도다.

---

## 프로젝트 구조

```
src/
├── api/                  # ✅ FastAPI 백엔드 (Cloud Run #1) — 6개 엔드포인트
│   ├── main.py           # lifespan: FAISS 인덱스 로드 + MongoDB 연결
│   ├── deps.py           # FastAPI Depends: get_rag_pipeline(), get_mongo()
│   ├── schemas.py        # Pydantic 요청/응답 모델
│   ├── errors.py         # 글로벌 예외 핸들러
│   ├── middleware.py      # 요청 로깅 미들웨어
│   └── routes/           # search, generate, policies, models, evaluate
├── ingestion/            # ✅ 수집 → GCS + MongoDB → FAISS 인덱스 빌드
│   ├── collectors/       # data_portal (✅ 2,185건), youthgo (✅ 50건)
│   ├── chunker.py        # kss 한국어 문장 분리 + tiktoken 토큰 카운트
│   ├── embedder.py       # LiteLLM embedding API 래퍼 (배치+재시도)
│   ├── gcs_client.py     # GCS 업로드/다운로드 클라이언트
│   ├── mongo_client.py   # PolicyMetadataStore (4컬렉션 CRUD)
│   ├── loader.py         # PDF/TXT/JSON 로더
│   └── pipeline.py       # 인덱스 빌드 오케스트레이션 (로컬/GCS 모드)
├── retrieval/            # ✅ 4가지 검색 전략
│   ├── vector_store.py   # FAISS 래퍼
│   ├── bm25_store.py     # BM25 키워드 검색
│   ├── hybrid.py         # RRF (k=60)
│   ├── reranker.py       # Cross-Encoder
│   └── pipeline.py       # RetrievalPipeline (SearchStrategy enum)
├── generation/           # ✅ LiteLLM 래퍼 + 정책 도메인 프롬프트 + RAG 오케스트레이션
│   ├── llm_client.py     # LiteLLM 통합 클라이언트 (재시도 + 토큰/레이턴시 추적)
│   ├── prompt.py         # 한국어 정책 도메인 프롬프트
│   └── pipeline.py       # RAGPipeline.run() / run_no_rag()
├── evaluation/           # ✅ 3단계 평가 구현 완료
│   ├── ragas_metrics.py  # RAGAS v0.4 SingleTurnSample 기반
│   ├── llm_judge.py      # G-Eval 방식 LLM Judge (Position Bias 완화)
│   ├── safety_metrics.py # DeepEval HallucinationMetric
│   ├── evaluator.py      # RAGEvaluator 통합 오케스트레이터
│   └── report.py         # JSON + HTML 리포트 생성
└── ui/                   # ✅ Streamlit 4페이지 (Cloud Run #2) — 챗봇, 정책 탐색, 맞춤 추천, 평가 대시보드

config/                   # ✅ pydantic-settings, 모델 목록, 데이터 소스 설정
dags/                     # ✅ Airflow DAGs (수집+인덱싱, 평가, QA 생성)
scripts/
├── experiments/          # ✅ 논문용 실험 파이프라인 (6단계)
│   ├── _common.py        # 공유 유틸 (CostTracker, Timer, 체크포인트, JSON I/O)
│   ├── step1_retrieval.py
│   ├── step2_generation.py
│   ├── step3_evaluation.py
│   ├── step4_judge_comparison.py
│   ├── step5_analysis.py
│   ├── step6_tables_figures.py
│   └── run_all.py        # 오케스트레이터 (--start, --only, --resume, --dry-run)
└── ...                   # 기존 수집/평가 스크립트
data/
├── policies/raw/         # 수집 데이터 (data_portal 2,185건 + youthgo 50건)
├── index/                # FAISS 인덱스 (faiss.index 16.5MB + metadata.pkl 3MB)
├── eval/qa_pairs.json    # ✅ 평가 QA 데이터셋 (100쌍 생성 완료)
├── experiments/          # 실험 파이프라인 step별 JSON 결과
└── results/              # 평가 결과 JSON
tests/                    # 261 tests passed
```

---

## 시작하기

### 요구사항

- Python 3.11+
- GCP 계정 (Cloud Run, GCS, Compute Engine 사용)
- MongoDB (GCP VM 또는 로컬)

### 설치

```bash
git clone https://github.com/Daehyun-Bigbread/RAG-QA-pipeline-GCP.git
cd RAG-QA-pipeline-GCP

pip install -e ".[dev,ui,ko,crawl,viz]"
```

### 환경변수

`.env.example`을 복사하여 `.env`를 생성하고 각 값을 채운다.
이 파일은 로컬 개발용이다. GCP 배포 런타임은 Secret Manager를 사용한다.

```bash
cp .env.example .env
```

```
OPENAI_API_KEY=              # GPT-4o/GPT-4o-mini (OpenAI API 직접)
ANTHROPIC_API_KEY=           # (선택) Claude Sonnet 4.5 — Vertex AI Model Garden 경유 시 불필요
HUGGINGFACE_API_KEY=         # Llama 3.3 70B (HuggingFace Inference API)
DATA_PORTAL_API_KEY=         # 공공데이터포털 API 키
MONGODB_URI=mongodb://admin:<password>@<MONGO_VM_IP>:27017/rag_youth_policy?authSource=admin
MONGODB_DB=rag_youth_policy
GCP_PROJECT=rag-qna-eval     # Vertex AI (Gemini, Claude) + GCS + Cloud Run
GCS_BUCKET=rag-qna-eval-data
VERTEXAI_PROJECT=rag-qna-eval
VERTEXAI_LOCATION=asia-northeast3
API_BASE_URL=                # FE -> BE 통신 URL (Cloud Run 배포 시 설정)
```

### 실행

```bash
# 1. 정책 수집 (GCS 원본 저장 + MongoDB 메타데이터)
python scripts/collect_policies.py --all

# 2. GCS 원본 -> FAISS 인덱스 빌드
python -m src.ingestion.pipeline --output data/index/

# 3. GCS에 인덱스 업로드
gsutil cp data/index/* gs://rag-qna-eval-data/index/

# 4. 기존 GCS 객체 catalog를 MongoDB에 동기화 (Compass 조회용)
python scripts/sync_gcs_assets_to_mongo.py

# 5. 검색 테스트
python -m src.retrieval.pipeline --query "청년 월세 지원 신청 자격은?" --strategy hybrid_rerank

# 6. 답변 생성 테스트
python -m src.generation.pipeline \
  --query "청년 월세 지원 신청 자격은?" \
  --model openai/gpt-4o-mini \
  --strategy hybrid_rerank

# 7. UI 실행
streamlit run src/ui/app.py
```

### 테스트 및 린트

```bash
pytest                           # 전체 테스트 (261 passed)
pytest tests/test_api.py         # 단일 모듈
pytest -k "test_chunk_size"      # 패턴 매칭
pytest --cov=src --cov-report=term-missing  # 커버리지
ruff check .
ruff format .
```

---

## 검색 전략

| 전략 | 파이프라인 |
|------|----------|
| `vector_only` | FAISS 벡터 검색 -> Top-K |
| `bm25_only` | BM25 키워드 검색 -> Top-K |
| `hybrid` | Vector + BM25 -> RRF (k=60) -> Top-K |
| `hybrid_rerank` | Vector + BM25 -> RRF -> Cross-Encoder -> Top-K |

---

## 평가 파이프라인 (3단계) — 구현 완료

이 프로젝트의 핵심 차별화 포인트는 RAG 응답을 3가지 관점에서 자동 평가하는 것이다.

### Stage 1: RAGAS v0.4 — 정량 평가

검색 품질과 생성 품질을 수치로 측정한다.

| 메트릭 | 측정 대상 | 목표 |
|--------|----------|------|
| Faithfulness | 답변이 컨텍스트에 근거하는가 (claim 분해 후 NLI) | >= 0.85 |
| AnswerRelevancy | 답변이 질문과 관련 있는가 (역질문 유사도) | >= 0.80 |
| ContextPrecision | 검색 문서가 정답 생성에 기여하는가 (AP) | >= 0.75 |
| ContextRecall | 정답의 근거가 컨텍스트에 있는가 | >= 0.80 |

`ragas>=0.4,<0.5` 버전 고정 필수. `evaluate()` 대신 `metric.ascore()` 사용.

### Stage 2: LLM-as-a-Judge — 정성 평가

G-Eval 방식으로 3가지 항목을 1-5점으로 평가한다.

| 평가 항목 | 기준 |
|----------|------|
| 인용 정확성 | 답변 인용이 컨텍스트와 일치하는가 |
| 답변 완결성 | 질문에 빠짐없이 답했는가 |
| 가독성 | 읽기 쉽고 구조적인가 |

Position Bias 완화를 위해 순서를 바꿔 2회 평가한 후 평균한다. 생성 모델과 Judge 모델은 다른 모델을 사용한다.

### Stage 3: DeepEval — 안전성 평가 (Hallucination)

RAGAS Faithfulness와 구분되는 보완적 관점이다.

```
RAGAS Faithfulness:     "증거 없음" = 불충실
DeepEval Hallucination: "명시적 모순" = hallucination
```

두 메트릭을 함께 사용해야 응답 오류의 성격을 정확히 진단할 수 있다.

### 실험 매트릭스

```
실험 1: 모델 비교 (검색 전략 고정: hybrid_rerank)
  GPT-4o / GPT-4o-mini / Claude Sonnet 4.5 / Gemini 2.5 Flash / Gemini 2.5 Pro / Llama 3.3 70B

실험 2: 검색 전략 비교 (모델 고정: GPT-4o-mini)
  vector_only / bm25_only / hybrid / hybrid_rerank

실험 3: RAG vs No-RAG (모델 고정: GPT-4o-mini)
  컨텍스트 있음 vs 없음
```

---

## 실험 파이프라인 (논문용)

`scripts/experiments/`는 논문 실험을 재현하기 위한 일회성 파이프라인이다. Airflow DAG(운영용 배치 평가)과 별도로 관리된다.

### 파일 구조

```
scripts/experiments/
├── __init__.py
├── _common.py              # 공유 유틸 (CostTracker, Timer, 체크포인트, JSON I/O)
├── step1_retrieval.py      # 실험 A: 검색 전략 4종 비교 (Context Precision/Recall)
├── step2_generation.py     # 실험 B: 5모델 × RAG + 1 No-RAG 답변 생성
├── step3_evaluation.py     # 실험 B+C+D: 3단계 평가 (GPT-4o / GPT-4o-mini 2종 Judge)
├── step4_judge_comparison.py  # 실험 C: Judge 비용-성능 통계 분석 (Kendall τ, MAE)
├── step5_analysis.py       # 실험 D+E: Position Bias + 교차 상관 + 탐지율 분석
├── step6_tables_figures.py # 논문 표 6~10 + Plotly 차트 자동 생성
└── run_all.py              # 오케스트레이터 (--start, --only, --resume, --dry-run)
```

### 실험 내용

| 실험 | 내용 | 주요 지표 |
|------|------|----------|
| A: 검색 전략 비교 | `vector_only`, `bm25_only`, `hybrid`, `hybrid_rerank` 4종 비교 | ContextPrecision, ContextRecall |
| B: 모델 응답 품질 비교 | 5 LLM × RAG + 1 No-RAG 조합 | RAGAS + Judge + Safety 3단계 |
| C: Judge 비용-성능 분석 | GPT-4o vs GPT-4o-mini Judge 상관관계 분석 | Kendall τ, Spearman ρ, MAE, Agreement Rate |
| D: Position Bias 완화 검증 | 2회 평가 평균 기법 효과 측정 | Wilcoxon signed-rank test |
| E: 3단계 평가 교차 상관 | RAGAS / Judge / Safety 상보성 실증 | Spearman ρ, 탐지율 비교 |

탐지율 분석: 단독 vs 2단계 조합 vs 3단계 조합 문제 탐지율을 비교해 3단계 평가의 상보성을 정량화한다.

### 실행 방법

```bash
# 실행 계획 확인 (실제 API 호출 없음)
python -m scripts.experiments.run_all --dry-run

# 전체 실행 (step1 → step6 순차 실행)
python -m scripts.experiments.run_all

# step3부터 이어서 실행 (체크포인트 활용)
python -m scripts.experiments.run_all --start step3 --resume

# 특정 단계만 실행
python -m scripts.experiments.run_all --only step4 step5 step6
```

결과물은 `data/experiments/` 하위에 step별 JSON으로 저장되고, `step6_tables_figures/figures/`에 Plotly 차트 HTML이 생성된다.

---

## 배포 (GCP Cloud Run)

BE(FastAPI)와 FE(Streamlit)를 별도 Cloud Run 서비스로 분리 배포한다.

```bash
# BE (FastAPI, 2Gi) 이미지 빌드 및 배포
docker build -t rag-youth-policy-api .
gcloud run deploy rag-youth-policy-api \
  --image ... \
  --region asia-northeast3 \
  --memory 2Gi \
  --min-instances 0 \
  --max-instances 1

# FE (Streamlit, 512Mi) 이미지 빌드 및 배포
docker build -t rag-youth-policy-ui -f Dockerfile.ui .
gcloud run deploy rag-youth-policy-ui \
  --image ... \
  --region asia-northeast3 \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 1
```

| 서비스 | 메모리 | 이유 |
|--------|--------|------|
| BE (FastAPI) | 2Gi | Cross-Encoder 모델 로드 |
| FE (Streamlit) | 512Mi | UI 전용, 경량 |

Cold start는 5~15초이므로 발표 전 사전 호출을 권장한다.

### CI/CD

GitHub Actions 5개 워크플로로 모노레포 경로 필터를 적용해 변경된 서비스만 배포한다.

| 워크플로 | 트리거 | 동작 |
|----------|--------|------|
| `ci.yml` | PR -> main | ruff lint + pytest |
| `deploy-api.yml` | main push (`src/api`, `src/retrieval` 등 변경 시) | BE 빌드 + 배포 |
| `deploy-ui.yml` | main push (`src/ui` 변경 시) | FE 빌드 + 배포 |
| `deploy-jobs.yml` | main push (`src/ingestion`, `scripts/` 변경 시) | Collector/Indexer Job 빌드 + 배포 |
| `deploy-airflow.yml` | main push (`dags/`, `scripts/`, `src/` 등 변경 시) | Airflow VM 코드 동기화 (IAP SSH) |

GitHub Secrets에 `GCP_SA_KEY` (서비스 계정 JSON 키) 설정이 필요하다.

### 인프라 구성

| 구성 요소 | 사양 | 역할 |
|----------|------|------|
| Cloud Run #1 (BE) | 2Gi, max 1 instance | FastAPI + FAISS 인메모리 검색 |
| Cloud Run #2 (FE) | 512Mi, max 1 instance | Streamlit UI |
| Compute Engine VM #1 | e2-small, 서울 | MongoDB (`34.47.80.98:27017`) + Grafana (`http://34.47.80.98:3000`) |
| Compute Engine VM #2 | e2-standard-2, 서울 | Airflow 2.9.3 (`http://34.47.107.145:8080`) |
| Cloud Storage | — | 정책 원본 JSON/PDF + FAISS 인덱스 |
| Cloud Monitoring | — | Cloud Run 메트릭 + FastAPI 커스텀 메트릭 |
| Cloud Logging | — | RAG 요청별 구조화 JSON 로그 |

### GCP 서비스 전체 목록

| # | 서비스 | 역할 |
|---|--------|------|
| 1 | Cloud Run (2개) | BE FastAPI + FE Streamlit 서빙 |
| 2 | Compute Engine (2개 VM) | MongoDB + Grafana / Airflow 2.9.3 |
| 3 | Cloud Storage (GCS) | 정책 원본, FAISS 인덱스, QA 데이터셋, 평가 결과 (source of truth) |
| 4 | Artifact Registry | Docker 이미지 저장소 |
| 5 | Vertex AI (Model Garden) | Gemini, Claude LLM 호출 (LiteLLM 경유) |
| 6 | Cloud Monitoring | Cloud Run 메트릭 + 커스텀 메트릭 |
| 7 | Cloud Logging | 구조화 JSON 로그 수집 |
| 8 | Secret Manager | Airflow VM 시크릿 (DB 비밀번호, API 키) |
| 9 | IAP | GitHub Actions → Airflow VM SSH 인증 |
| 10 | VPC 네트워킹 | 방화벽 규칙 (MongoDB, Airflow, Grafana 포트) |

> **오케스트레이션 전환**: 초기 Cloud Run Jobs + Cloud Scheduler 설계에서 Apache Airflow(self-hosted VM)로 전환했다. 태스크 체이닝, 데이터 전달(XCom), 실패 재시도, Web UI 모니터링에서 Airflow가 우위이며, Cloud Composer 대비 82% 비용 절감 (~₩67K/월 vs ~₩367K/월). 상세 전환 배경은 [`docs/plan.md`](docs/plan.md)를 참조.

---

## 데이터 소스

| 소스 | 데이터 유형 | 수집 방법 | 상태 |
|------|------------|---------|------|
| 공공데이터포털 (data.go.kr) | 청년정책 구조화 JSON | REST API | ✅ 2,185건 |
| 온통청년 (youth.go.kr) | 청년 정책 목록 + 상세 | httpx + BeautifulSoup | ✅ 50건 (샘플) |
| 한국장학재단 (kosaf.go.kr) | 장학금/학자금 정보 | httpx + BeautifulSoup | 예정 |
| 정부 PDF 보고서 | 고용/주거 정책 | PyMuPDF | 예정 |

크롤링 규칙: robots.txt 준수, 요청 간격 2~3초, User-Agent 설정.

---

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).
