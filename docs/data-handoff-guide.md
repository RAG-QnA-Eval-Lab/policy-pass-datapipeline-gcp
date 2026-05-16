# 데이터 가이드 — FAISS 인덱스 & 정책 데이터

---

## 1. 전달 파일 목록

### FAISS 인덱스 (RAG 검색에 필수)

| 파일 | 크기 | 설명 |
|------|------|------|
| `data/index/faiss.index` | 16MB | FAISS 벡터 인덱스 |
| `data/index/metadata.pkl` | 2.9MB | 벡터 ID → 문서 메타데이터 매핑 (pickle) |
| `data/index/metadata.json` | 3.3MB | 위와 동일한 데이터의 JSON 버전 |

- `metadata.pkl`과 `metadata.json`은 같은 데이터. 코드에서는 `.pkl`을 쓰고, 사람이 읽을 때는 `.json`을 보면 됨
- **이 3개 파일만 있으면 RAG 검색 + 답변 생성이 가능**

### 정책 원본 데이터

| 파일 | 크기 | 설명 |
|------|------|------|
| `data/policies/raw/data_portal/latest.json` | 6.0MB | 공공데이터포털 수집 원본 |
| `data/policies/raw/youthgo/latest.json` | 291KB | 청년정책 포털 수집 원본 |
| `data/policies/normalized/all_policies.json` | 7.8MB | 정규화된 정책 전체 (2,185건) |
| `data/policies/normalized/by_category/` | - | 카테고리별 분리 (5개 파일) |
| `data/policies/normalized/manifest.json` | 245B | 수집 통계 요약 |

### 평가 데이터

| 파일 | 크기 | 설명 |
|------|------|------|
| `data/eval/qa_pairs.json` | 60KB | 평가용 QA 100쌍 |

---

## 2. FAISS 인덱스 상세

### 스펙

| 항목 | 값 |
|------|-----|
| 임베딩 모델 | `text-embedding-3-small` (OpenAI) |
| 벡터 차원 | 1,536 |
| 총 청크 수 | 2,686개 |
| 원본 정책 수 | 2,185건 |
| 청킹 방식 | 문장 경계 기반 (kss 한국어 분리 + tiktoken 토큰 카운트) |
| 청크 크기 | 512 토큰 (tiktoken `cl100k_base` 기준) |
| 청크 오버랩 | 50 토큰 (이전 청크 끝 문장을 다음 청크에 중복 포함) |
| 문장 분리 | kss (mecab → punct → regex 폴백) |
| 인덱스 타입 | FAISS IndexFlatL2 (L2 거리, **낮을수록 유사**) |

> **거리 해석**: IndexFlatL2는 유클리드 거리를 사용. `distances` 값이 **낮을수록** 쿼리와 유사한 문서. 정렬은 FAISS가 자동으로 오름차순 처리함

### metadata 구조 (청크 1건)

```json
{
  "content": "정책명: (4차) 2026 광주청년 구직활동수당...\n요약: ...\n지원내용: ...",
  "source": "data_portal",
  "policy_id": "20260420005400212772",
  "category": "employment",
  "title": "(4차) 2026 광주청년 구직활동수당 및 활동지원사업",
  "url": null,
  "last_updated": "20260601",
  "chunk_index": null
}
```

- `content` — 검색 결과로 LLM에 넘겨줄 텍스트. **구조화된 형식**으로, `정책명:`, `요약:`, `지원내용:` 등 섹션 헤더가 포함되어 있음. 프롬프트 엔지니어링 시 이 구조를 활용할 수 있음
- `policy_id` — 정책 고유 ID (정책 상세 조회 시 사용)
- `category` — 분류 (employment, welfare, participation, education, housing)

---

## 3. 정책 데이터 상세

### 카테고리 분포 (총 2,185건)

| 카테고리 | 한국어 | 건수 |
|----------|--------|------|
| employment | 취업 | 900건 |
| welfare | 복지 | 521건 |
| participation | 참여 | 299건 |
| education | 교육 | 243건 |
| housing | 주거 | 222건 |

### 정책 1건의 필드 (19개)

| 필드 | 타입 | 설명 |
|------|------|------|
| `policy_id` | string | 고유 ID |
| `title` | string | 정책명 |
| `category` | string | 분류 (5종) |
| `summary` | string | 요약 |
| `description` | string | 상세 설명 |
| `eligibility` | string | 자격 요건 |
| `benefits` | string | 지원 내용 |
| `how_to_apply` | string | 신청 방법 |
| `application_period` | string | 신청 기간 |
| `managing_department` | string | 담당 기관 |
| `target_age` | list | 대상 연령 [min, max] |
| `region` | string | 지역 코드 |
| `source_url` | string | 출처 URL |
| `source_name` | string | 수집 소스 (data_portal, youthgo) |
| `last_updated` | string | 최종 수정일 |
| `raw_content` | string | 원본 텍스트 |
| `raw_path` | string | 원본 파일 경로 |
| `region_codes` | list | 지역 코드 리스트 |
| `scope` | string | 범위 (regional, national) |

---

## 4. 이 데이터로 RAG 만드는 법

### 필요한 것

- **파일 3개**: `faiss.index` + `metadata.pkl` + `metadata.json` (pkl 또는 json 하나만 있어도 됨)
- **OpenAI API 키**: 쿼리 임베딩에 `text-embedding-3-small` 사용 (인덱스 빌드 때와 같은 모델이어야 함)
- **LLM API 키**: 답변 생성용 (OpenAI, Gemini 등 아무거나)

### 최소 설치 패키지

```bash
pip install faiss-cpu openai numpy
```

### 최소 코드 예시

```python
import faiss
import pickle
import numpy as np
from openai import OpenAI

# 1. 인덱스 & 메타데이터 로드
index = faiss.read_index("data/index/faiss.index")
with open("data/index/metadata.pkl", "rb") as f:
    metadata = pickle.load(f)

# 2. 쿼리 임베딩 (반드시 text-embedding-3-small 사용)
client = OpenAI()
query = "청년 월세 지원 조건이 뭐야?"
embedding = client.embeddings.create(
    input=query,
    model="text-embedding-3-small"
).data[0].embedding

# 3. FAISS 검색 (top 5)
query_vector = np.array([embedding], dtype=np.float32)
distances, indices = index.search(query_vector, 5)

# 4. 검색된 문서 텍스트 가져오기
contexts = []
for idx in indices[0]:
    if idx < len(metadata):
        contexts.append(metadata[idx]["content"])

# 5. LLM에 넘겨서 답변 생성
context_text = "\n\n---\n\n".join(contexts)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": f"다음 문서를 참고해서 답변하세요:\n\n{context_text}"},
        {"role": "user", "content": query}
    ]
)
print(response.choices[0].message.content)
```

### 주의사항

- **임베딩 모델 일치 필수**: 인덱스 빌드 시 `text-embedding-3-small`을 사용했으므로, 쿼리 임베딩도 반드시 같은 모델을 써야 함. 다른 모델을 쓰면 벡터 차원이 맞더라도 검색 품질이 망가짐
- **metadata 인덱스 매핑**: `faiss.index`에서 검색한 결과의 ID가 `metadata` 리스트의 인덱스와 1:1 대응됨
- **faiss-cpu 설치**: `pip install faiss-cpu` (GPU 불필요)
- **임베딩 API 비용**: `text-embedding-3-small`은 약 $0.02/1M 토큰. 쿼리 1건당 비용은 거의 무시 가능

---

## 5. QA 데이터셋 (`data/eval/qa_pairs.json`)

평가용 QA 100쌍. GPT-4o-mini로 정책 문서 기반 자동 생성.

### 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `question` | string | 질문 |
| `ground_truth` | string | 정답 (평가 기준) |
| `difficulty` | string | 난이도: easy / medium / hard |
| `qa_type` | string | 유형: factual / reasoning / comparison |
| `category` | string | 정책 카테고리 |
| `policy_title` | string | 출처 정책명 |
| `policy_id` | string | 출처 정책 ID |
| `id` | string | QA 쌍 고유 ID (q001~q100) |

### 난이도/유형 분포

| 난이도 | 건수 | | 유형 | 건수 |
|--------|------|-|------|------|
| easy | 46 | | factual | 84 |
| medium | 36 | | reasoning | 14 |
| hard | 18 | | comparison | 2 |

### 예시 (3건)

**easy / factual**:
```json
{
  "question": "2026년 청년 유네스코 세계유산 지킴이에 신청할 수 있는 기간은 언제인가요?",
  "ground_truth": "신청기간은 2026년 4월 1일부터 2026년 12월 31일까지입니다.",
  "difficulty": "easy",
  "qa_type": "factual",
  "category": "education",
  "policy_title": "2026년 청년 유네스코 세계유산 지킴이",
  "policy_id": "20260316005400112167",
  "id": "q001"
}
```

**hard / reasoning**:
```json
{
  "question": "함안청년 창업가 지속성장 지원사업에서 제공하는 지원내용은 어떤 것들이 있나요?",
  "ground_truth": "지원내용으로는 예비창업자 창업상담, 창업아카데미를 통한 전문경영교육 및 컨설팅 지원, 창업에 필요한 시제품 개발 및 마케팅 비용 지원, 창업관련 행사 및 민간지원 연계 등이 있습니다.",
  "difficulty": "hard",
  "qa_type": "reasoning",
  "category": "employment",
  "policy_id": "20251106005400211805",
  "id": "q028"
}
```

**hard / comparison**:
```json
{
  "question": "청년문화예술패스 지원금은 지역에 따라 어떻게 달라지나요?",
  "ground_truth": "청년문화예술패스 지원금은 지역에 따라 다릅니다. 대구광역시, 대전광역시, 세종특별자치시, 경기도(성남시, 안산시), 전북특별자치도(전주시)는 10만원을 즉시 지급받고, 그 외 지역은 15만원을 지원받습니다.",
  "difficulty": "hard",
  "qa_type": "comparison",
  "category": "welfare",
  "policy_id": "20250228005400110573",
  "id": "q006"
}
```

### 활용 방법

- **RAG 품질 벤치마크**: ground_truth 대비 RAG 답변 비교 (RAGAS faithfulness, answer_relevancy 등)
- **난이도별 분석**: easy 질문에서 낮은 점수면 검색 문제, hard에서만 낮으면 LLM 추론 문제
- **카테고리별 분석**: 특정 카테고리 성능이 떨어지면 해당 분야 청킹/데이터 품질 점검
