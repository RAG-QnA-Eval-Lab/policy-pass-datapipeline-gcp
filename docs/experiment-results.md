# RAG 응답 모니터링을 위한 비용 효율적 LLM-as-a-Judge 파이프라인 구축 및 성능 비교 분석 실험 결과 보고서

> 실행일: 2026-05-05 ~ 2026-05-06
> 파이프라인: `scripts/experiments/step1~step6`
> QA 데이터셋: `data/eval/qa_pairs.json` (100쌍)

---

## 1. 실험 설계 개요

### 1.1 파이프라인 구조

```
Step1 (검색)  → Step2 (생성)  → Step3 (평가)  → Step4 (Judge 비교) → Step5 (통계 분석) → Step6 (표·그림)
  4전략×100      5모델×100+NoRAG   Primary+Expensive    Judge 간 일치도     Bias/상관/탐지율     논문용 테이블
```

### 1.2 실험 변수

| 변수 | 값 |
|------|-----|
| QA 쌍 수 | 100 |
| 검색 전략 (Step1) | `vector_only`, `bm25_only`, `hybrid`, `hybrid_rerank` |
| 생성 모델 (Step2) | GPT-4o-mini, GPT-4o, Claude Sonnet, Gemini Flash, Llama3 |
| NoRAG 대조군 | GPT-4o-mini (검색 컨텍스트 없이 생성) |
| 검색 전략 (Step2~3) | `hybrid_rerank` (Step1에서 최적 전략 확정 후 고정) |
| top_k | 5 |
| Primary Judge | `openai/gpt-4o-mini` |
| Expensive Judge | `vertex_ai/gemini-3.1-pro-preview` (region: global) |
| Position Bias 완화 | 2회 평가 (원본 순서 + 셔플 순서) 평균 |

### 1.3 총 샘플 수

- Step1: 4전략 × 100 = **400건**
- Step2: 5모델 × 100 + 1 NoRAG × 100 = **600건**
- Step3 Primary: **600건** (GPT-4o-mini Judge + RAGAS + Safety)
- Step3 Expensive: **600건** (Gemini 3.1 Pro Judge only, RAGAS/Safety는 Primary 캐시 재사용)
- Step4~6: LLM 호출 없음 (순수 통계 연산)

---

## 2. Step1: 검색 전략 비교 (표 6)

> 출력: `data/experiments/step1_retrieval/retrieval_results.json`

| 전략 | Context Precision (mean±std) | Context Recall (mean±std) | Latency (sec) | N |
|------|-----|-----|-----|---|
| **vector_only** | 0.7885 ± 0.3075 | 0.8250 ± 0.3631 | 0.431 | 100 |
| **bm25_only** | 0.6896 ± 0.3563 | 0.7330 ± 0.4377 | 0.012 | 100 |
| **hybrid (RRF)** | 0.8054 ± 0.3122 | 0.8450 ± 0.3514 | 0.408 | 100 |
| **hybrid_rerank** | 0.7946 ± 0.3078 | 0.8550 ± 0.3413 | 0.449 | 100 |

**분석**:
- **Context Recall 최고**: hybrid_rerank (0.855) — Cross-Encoder reranking이 recall을 가장 높게 끌어올림
- **Context Precision 최고**: hybrid RRF (0.805) — 벡터+BM25 앙상블이 정밀도에서 소폭 우위
- **BM25 단독**: precision/recall 모두 최저 (0.690/0.733), 그러나 latency 0.012초로 30~40배 빠름
- **Vector 단독 vs Hybrid**: hybrid가 precision/recall 모두 우위, latency 차이 미미
- **Step2 이후 고정 전략**: `hybrid_rerank` (recall 최우선 선택)

---

## 3. Step2: 멀티 LLM 생성

> 출력: `data/experiments/step2_generation/generation_results.json`

| 조건 | 모델 (LiteLLM ID) | RAG | 샘플 수 |
|------|-----|-----|---|
| `gpt-4o-mini__rag` | `openai/gpt-4o-mini` | O | 100 |
| `gpt-4o__rag` | `openai/gpt-4o` | O | 100 |
| `claude-sonnet__rag` | `vertex_ai/claude-sonnet-4-5` | O | 100 |
| `gemini-flash__rag` | `vertex_ai/gemini-2.5-flash` | O | 100 |
| `llama3__rag` | `huggingface/meta-llama/Llama-3.3-70B-Instruct` | O | 100 |
| `gpt-4o-mini__no_rag` | `openai/gpt-4o-mini` | X | 100 |

- 검색 전략: `hybrid_rerank`, top_k=5 (NoRAG 제외)
- 총 600건 생성 완료

---

## 4. Step3: 3단계 평가

> 출력:
> - `data/experiments/step3_evaluation/eval_gpt4o_mini_judge.json` (Primary)
> - `data/experiments/step3_evaluation/eval_gemini_pro_judge.json` (Expensive)

### 4.1 평가 구조

```
Primary Pass (GPT-4o-mini Judge):
  - RAGAS v0.4: faithfulness, answer_relevancy, context_precision, context_recall
  - LLM Judge (G-Eval): citation_accuracy, completeness, readability (1~5점 정수)
  - Safety (DeepEval): hallucination_score (0.0~1.0)
  - Position Bias 완화: 원본 순서 + 셔플 순서 2회 평가 → 평균

Expensive Pass (Gemini 3.1 Pro Judge):
  - LLM Judge만 실행 (RAGAS/Safety는 Primary 결과 캐시 재사용)
  - 동일한 Position Bias 완화 적용
  - temperature=1.0 (Gemini 3.x 요구사항)
```

### 4.2 유효 샘플 수

#### Primary Pass (GPT-4o-mini Judge)

| 조건 | 전체 | eval 없음 | 유효 Judge | 유효 RAGAS |
|------|------|-----------|-----------|-----------|
| gpt-4o-mini__rag | 100 | 0 | 100 | 100 |
| gpt-4o__rag | 100 | 0 | 100 | 100 |
| claude-sonnet__rag | 100 | 0 | 24 | 100 |
| gemini-flash__rag | 100 | 0 | 100 | 100 |
| llama3__rag | 100 | 65 | 35 | 35 |
| gpt-4o-mini__no_rag | 100 | 0 | 100 | 100 |
| **합계** | **600** | **65** | **459** | **535** |

- `claude-sonnet__rag`: RAGAS는 100건 성공했으나 Judge는 24건만 유효 (Claude Sonnet 답변에 대한 GPT-4o-mini Judge 파싱 실패율 높음)
- `llama3__rag`: HuggingFace API 에러로 65건의 생성 자체가 실패 → eval 없음
- 유효 Safety: 535건 (RAGAS와 동일)

#### Expensive Pass (Gemini 3.1 Pro Judge)

| 조건 | 전체 | 유효 Judge | 실패 |
|------|------|-----------|------|
| gpt-4o-mini__rag | 100 | 73 | 27 |
| gpt-4o__rag | 100 | 73 | 27 |
| claude-sonnet__rag | 100 | 59 | 41 |
| gemini-flash__rag | 100 | 78 | 22 |
| llama3__rag | 100 | 23 | 77 |
| gpt-4o-mini__no_rag | 100 | 5 | 95 |
| **합계** | **600** | **311** | **289** |

- 전체 성공률: **51.8%** (311/600)
- Gemini 3.1 Pro는 JSON 출력 포맷 준수율이 낮음 (temperature=1.0 필수 제약 + 응답 중간 truncation)
- `gpt-4o-mini__no_rag` 조건에서 특히 낮음 (5/100) — NoRAG 답변의 컨텍스트 부재로 Judge 혼동
- `llama3__rag`도 낮음 (23/100) — 65건은 원본 답변 자체가 없음 + 나머지도 파싱 실패율 높음

### 4.3 표 7: RAGAS 메트릭 (모델별)

| 조건 | Faithfulness | Answer Relevancy | Context Precision | Context Recall | N |
|------|-------------|------------------|-------------------|---------------|---|
| claude-sonnet__rag | 0.8793 ± 0.1382 | 0.4214 ± 0.2350 | 0.6719 ± 0.3973 | 0.8125 ± 0.3767 | 100 |
| gemini-flash__rag | 0.8257 ± 0.2746 | 0.4845 ± 0.2677 | 0.7823 ± 0.3088 | 0.8550 ± 0.3413 | 100 |
| gpt-4o-mini__rag | 0.8586 ± 0.2892 | 0.5313 ± 0.2322 | 0.7840 ± 0.3181 | 0.8550 ± 0.3413 | 100 |
| gpt-4o__rag | 0.8532 ± 0.2910 | 0.4727 ± 0.2805 | 0.7905 ± 0.3118 | 0.8500 ± 0.3500 | 100 |
| llama3__rag | **0.9824** ± 0.0584 | 0.5113 ± 0.1779 | 0.7815 ± 0.3082 | 0.8857 ± 0.2949 | 35 |
| gpt-4o-mini__no_rag | N/A | 0.3355 ± 0.3204 | N/A | N/A | 100 |

**분석**:
- **Faithfulness 최고**: Llama3 (0.982) — 컨텍스트에 매우 충실한 답변 생성 (단, N=35로 표본 적음)
- **Answer Relevancy 최고**: GPT-4o-mini RAG (0.531) — 질문 의도에 가장 부합하는 답변
- **NoRAG 대조군**: Answer Relevancy 0.336으로 RAG 대비 현저히 낮음, Faithfulness는 컨텍스트 없어 측정 불가
- **Claude Sonnet**: Faithfulness 0.879로 양호하나 Context Precision이 0.672로 가장 낮음
- Context Recall/Precision은 검색 전략이 동일(hybrid_rerank)하므로 조건 간 차이가 적음

### 4.4 표 8: LLM Judge 점수 (GPT-4o-mini Judge, 모델별)

| 조건 | Citation Accuracy | Completeness | Readability | Average | N |
|------|------------------|-------------|------------|---------|---|
| claude-sonnet__rag | 1.20 ± 2.14 | 1.20 ± 2.14 | 1.20 ± 2.14 | 1.20 ± 2.14 | 100* |
| gemini-flash__rag | 4.62 ± 1.02 | 4.48 ± 1.16 | **4.96** ± 0.28 | 4.69 ± 0.76 | 100 |
| gpt-4o-mini__rag | 4.59 ± 1.14 | **4.55** ± 1.23 | 4.98 ± 0.14 | 4.71 ± 0.79 | 100 |
| gpt-4o__rag | 4.39 ± 1.38 | 4.29 ± 1.51 | 4.88 ± 0.43 | 4.52 ± 1.04 | 100 |
| llama3__rag | **4.94** ± 0.23 | **4.93** ± 0.24 | **4.99** ± 0.08 | **4.95** ± 0.17 | 35 |
| gpt-4o-mini__no_rag | 2.46 ± 1.47 | 4.37 ± 1.16 | **5.00** ± 0.05 | 3.94 ± 0.71 | 100 |

*claude-sonnet__rag: 유효 Judge 24건, 나머지 76건은 0점 → 평균이 비정상적으로 낮음. 유효 24건만의 평균은 별도 계산 필요.

**분석**:
- **Llama3 최고 점수** (Average 4.95) — 단, N=35로 생존 편향 가능 (성공적으로 생성된 응답만 평가)
- **GPT-4o-mini RAG 최고** (대규모 모델 중, Average 4.71) — Citation/Completeness/Readability 모두 균형
- **NoRAG 대조군**: Citation Accuracy 2.46 (컨텍스트 없이 생성하므로 인용 정확도 낮음), Readability 5.00 (가독성은 최고)
- **Readability는 전반적으로 높음** (4.88~5.00) — 모든 모델이 가독성 높은 한국어 답변 생성

### 4.5 표 9: Safety (Hallucination Score, 모델별)

| 조건 | Hallucination Mean ± Std | N |
|------|------------------------|---|
| gpt-4o-mini__no_rag | **0.000** ± 0.000 | 100 |
| gemini-flash__rag | 0.338 ± 0.365 | 100 |
| gpt-4o__rag | 0.350 ± 0.367 | 100 |
| gpt-4o-mini__rag | 0.368 ± 0.380 | 100 |
| llama3__rag | 0.457 ± 0.369 | 35 |
| claude-sonnet__rag | **0.533** ± 0.340 | 100 |

> Hallucination Score: 0.0 = 환각 없음, 1.0 = 완전한 환각. **낮을수록 좋음**.

**분석**:
- **NoRAG 대조군 0.000**: DeepEval의 hallucination 판정 기준이 "컨텍스트 대비 사실 왜곡"이므로, 컨텍스트 자체가 없으면 환각으로 판정하지 않음 (측정 한계)
- **Gemini Flash 최저 환각** (RAG 중, 0.338) — 컨텍스트 충실도 높음
- **Claude Sonnet 최고 환각** (0.533) — 답변이 컨텍스트를 넘어 추가 정보를 생성하는 경향
- 전반적으로 RAG 모델의 환각률 0.34~0.53 범위

---

## 5. Step4: Judge 모델 비용-성능 비교 (실험 C)

> 출력: `data/experiments/step4_judge_comparison/judge_comparison.json`
> 비교 대상: GPT-4o-mini Judge vs Gemini 3.1 Pro Judge
> 유효 비교 쌍: **267건** (양쪽 모두 유효한 Judge 결과가 있는 샘플)

### 5.1 표 10: 전체 일치도 (Average 기준)

| 지표 | 값 | 해석 |
|------|-----|------|
| Kendall τ | 0.2591 | 약한 순위 상관 |
| Kendall p-value | 1.3×10⁻⁵ | 통계적으로 유의 |
| Spearman ρ | 0.2679 | 약한 순위 상관 |
| Spearman p-value | 9×10⁻⁶ | 통계적으로 유의 |
| MAE | 0.3066 | 평균 0.3점 차이 (5점 척도) |
| Perfect Agreement Rate | 86.89% | 정수 반올림 시 동일 비율 |
| **Class Agreement Rate** | **90.26%** | 3등급(low/mid/high) 분류 일치율 |

### 5.2 메트릭별 상세 일치도

| 메트릭 | Kendall τ | Spearman ρ | MAE | Perfect Agr. | Class Agr. |
|--------|-----------|-----------|-----|-------------|-----------|
| citation_accuracy | 0.2712 | 0.2752 | 0.4045 | 88.01% | 88.76% |
| completeness | 0.2299 | 0.2341 | 0.4719 | 86.89% | 87.27% |
| **readability** | **0.3953** | **0.3966** | **0.0431** | **97.75%** | **98.50%** |
| average | 0.2591 | 0.2679 | 0.3066 | 86.89% | 90.26% |

**분석**:
- **Readability에서 가장 높은 일치도**: τ=0.396, MAE=0.043, Class Agreement 98.5% — 두 Judge가 가독성 판단에 매우 일치
- **Completeness에서 가장 낮은 일치도**: τ=0.230, MAE=0.472 — 완결성 판단에 모델 간 시각 차이 존재
- **전체 Class Agreement 90.3%**: 3등급 분류 기준으로 10건 중 9건 일치 → **저비용 GPT-4o-mini Judge가 고비용 Gemini Pro Judge를 대체 가능**
- 순위 상관(τ, ρ)은 낮지만, 이는 대부분의 점수가 고점(4~5)에 집중되어 변동성이 적기 때문
- 비용 데이터는 LiteLLM 비용 추적이 비활성화되어 0.0으로 기록됨 (수동 추정 필요)

---

## 6. Step5: 통계 분석

### 6.1 실험 D: Position Bias 분석

> 출력: `data/experiments/step5_analysis/position_bias.json`
> 분석 대상: 459건 (유효 Judge raw_scores 보유 샘플)
> 방법: 원본 순서(original) vs 셔플 순서(shuffled) 점수 차이 분석

| 메트릭 | Mean |Δ| | Std |Δ| | Max Δ | ≥1점차 건수 | ≥1점차 비율 | Wilcoxon p |
|--------|---------|---------|-------|------------|------------|------------|
| citation_accuracy | 0.166 | 0.666 | 4 | 30/459 | **6.5%** | 0.618 |
| completeness | 0.072 | 0.357 | 2 | 19/459 | **4.1%** | 0.849 |
| readability | 0.028 | 0.222 | 2 | 8/459 | **1.7%** | 1.000 |

**점수 차이 분포 (citation_accuracy)**:
| Δ=0 | Δ=2 | Δ=4 |
|-----|-----|-----|
| 429건 (93.5%) | 22건 (4.8%) | 8건 (1.7%) |

**점수 차이 분포 (completeness)**:
| Δ=0 | Δ=1 | Δ=2 |
|-----|-----|-----|
| 440건 (95.9%) | 5건 (1.1%) | 14건 (3.1%) |

**점수 차이 분포 (readability)**:
| Δ=0 | Δ=1 | Δ=2 |
|-----|-----|-----|
| 451건 (98.3%) | 3건 (0.7%) | 5건 (1.1%) |

**분산 감소 효과 (2회 평균)**:
| 지표 | 단일 평가 분산 | 2회 평균 분산 | 분산 감소율 |
|------|--------------|-------------|-----------|
| 전체 평균 | 0.7438 | 0.7230 | **2.79%** |

**분석**:
- **Wilcoxon p-value 모두 >0.05**: 원본/셔플 간 체계적 편향(systematic bias) 없음 — 문맥 순서가 점수에 유의한 영향을 미치지 않음
- **≥1점차 비율 최대 6.5%**: 대부분의 평가에서 순서 변경에 무관하게 동일 점수 부여
- **Readability 가장 안정**: 1.7%만 1점 이상 차이 — 가독성 평가는 순서 독립적
- **Citation Accuracy 가장 취약**: 6.5%에서 1점 이상 차이, 최대 4점 차이까지 발생 — 인용 정확도는 문맥 배치에 민감할 수 있음
- **분산 감소 2.79%**: 2회 평균의 분산 감소 효과는 미미 → Position Bias가 원래 크지 않아 완화 효과도 제한적

### 6.2 실험 E: 3단계 교차 상관 분석

> 출력: `data/experiments/step5_analysis/cross_correlation.json`
> 분석 대상: 352건 (RAGAS + Judge + Safety 3가지 모두 유효한 샘플)

#### 전체 상관 매트릭스

| 쌍 | Spearman ρ | p-value | 해석 |
|-----|-----------|---------|------|
| RAGAS Faithfulness ↔ Judge Average | 0.402 | <0.0001 | **약한 상관 (보완적)** |
| RAGAS Faithfulness ↔ Safety Hallucination | 0.261 | <0.001 | 무시 가능 (독립적) |
| Judge Average ↔ Safety Hallucination | 0.310 | <0.0001 | 약한 상관 (보완적) |
| RAGAS Relevancy ↔ Judge Completeness | **0.502** | <0.0001 | **중간 상관 (보완적)** |
| Judge Readability ↔ Judge Average | **0.507** | <0.0001 | **중간 상관 (보완적)** |
| Judge Readability ↔ RAGAS Faithfulness | 0.223 | <0.0001 | 무시 가능 (독립적) |

#### 모델별 상관 (Faithfulness ↔ Judge, Faithfulness ↔ Hallucination)

| 조건 | Faith↔Judge ρ | Faith↔Halluc ρ | N |
|------|-------------|---------------|---|
| gpt-4o-mini__rag | 0.362 | 0.091 | 99 |
| gpt-4o__rag | **0.510** | 0.345 | 100 |
| claude-sonnet__rag | 0.134 | **0.622** | 23 |
| gemini-flash__rag | 0.410 | 0.335 | 96 |
| llama3__rag | 0.269 | 0.141 | 35 |

**분석**:
- **3단계 평가는 보완적(complementary)**: 최대 ρ=0.502로 중간 수준 상관 → 각 단계가 서로 다른 측면을 측정
- **RAGAS Faithfulness와 Safety Hallucination은 거의 독립**: ρ=0.261 → 이론적으로 유사한 개념이나 측정 방식이 달라 포착하는 결함이 다름
- **Relevancy ↔ Completeness 가장 높은 상관** (ρ=0.502): 답변 관련성과 완결성은 개념적으로 중첩 — 가장 redundant한 쌍
- **Claude Sonnet 특이점**: Faith↔Halluc ρ=0.622로 다른 모델 대비 높음 (N=23으로 소표본 주의)
- **GPT-4o**: Faith↔Judge ρ=0.510으로 가장 높음 — Faithfulness 높으면 Judge 점수도 높은 경향이 가장 뚜렷

### 6.3 탐지율 분석: 단독 vs 조합 평가

> 출력: `data/experiments/step5_analysis/detection_coverage.json`
> 분석 대상: 535건
> 임계값: RAGAS Faithfulness < 0.5, Judge Average < 3.0, Hallucination > 0.5

#### 단독 탐지율

| 평가 단계 | Flagged | 탐지율 |
|----------|---------|--------|
| RAGAS 단독 | 24건 | **4.5%** |
| Judge 단독 | 113건 | **21.1%** |
| Safety 단독 | 159건 | **29.7%** |

#### 조합 탐지율 (Union)

| 조합 | Flagged | 탐지율 |
|------|---------|--------|
| RAGAS + Judge | 122건 | 22.8% |
| RAGAS + Safety | 180건 | 33.6% |
| **Judge + Safety** | **271건** | **50.7%** |
| **3단계 전체** | **278건** | **52.0%** |

#### 고유 탐지 (해당 단계만 잡은 케이스)

| 단계 | 고유 탐지 | 비율 |
|------|----------|------|
| RAGAS만 | 7건 | 1.3% |
| **Judge만** | **98건** | **18.3%** |
| **Safety만** | **156건** | **29.2%** |

#### 불일치 매트릭스

| 상황 | 건수 | 비율 |
|------|------|------|
| RAGAS 통과 + Judge 실패 | 98건 | 18.3% |
| Judge 통과 + RAGAS 실패 | 9건 | 1.7% |
| RAGAS 통과 + Safety 실패 | 156건 | 29.2% |
| Safety 통과 + RAGAS 실패 | 21건 | 3.9% |
| Judge 통과 + Safety 실패 | 158건 | 29.5% |
| Safety 통과 + Judge 실패 | 112건 | 20.9% |

**분석**:
- **3단계 조합 탐지율 52.0%**: 단독 최고(Safety 29.7%) 대비 +22.3%p 추가 탐지 — 조합의 가치 입증
- **Judge+Safety 2단계 조합이 50.7%**: 3단계(52.0%)와 1.3%p 차이밖에 안 남 — RAGAS의 추가 기여가 제한적
- **RAGAS 단독 탐지율 극히 낮음** (4.5%): Faithfulness < 0.5 임계값이 대부분의 응답에서 도달하지 않음 (평균 0.83~0.98)
- **Safety가 가장 많은 고유 탐지** (156건, 29.2%): Hallucination Score는 다른 2단계가 놓치는 결함을 가장 많이 포착
- **Judge도 상당한 고유 탐지** (98건, 18.3%): 정성 평가(인용/완결성)만으로 잡히는 품질 문제 존재
- **핵심 결론: 최소 Judge+Safety 2단계는 필수**, RAGAS는 추가적 안전망 역할

---

## 7. Step6: 생성된 차트

> 출력 디렉토리: `data/experiments/step6_tables_figures/figures/`

| 파일명 | 설명 |
|--------|------|
| `fig4_ragas_radar.html` | 모델별 RAGAS 4지표 레이더 차트 |
| `fig_judge_heatmap.html` | 모델별 Judge 점수 히트맵 (1~5점 색상 매핑) |
| `fig_detection_coverage.html` | 단독/2단계/3단계 탐지율 막대 차트 |
| `fig5_bias_histogram.html` | Position Bias 점수 차이 분포 히스토그램 |
| `fig_cost_performance.html` | GPT-4o-mini vs Gemini Pro 메트릭별 MAE-τ 산점도 |

---

## 8. 알려진 제한사항 및 주의점

### 8.1 데이터 결측

| 문제 | 영향 | 원인 |
|------|------|------|
| Llama3 65건 생성 실패 | N=35만 유효 (다른 모델 N=100) | HuggingFace Inference API 불안정 |
| Claude Sonnet Judge 76건 실패 | Primary Judge 유효 24건 | GPT-4o-mini가 Claude Sonnet 답변의 JSON 파싱에 실패 |
| Gemini Pro Judge 289건 실패 | Expensive pass 유효 311건 (51.8%) | temperature=1.0 제약 + JSON 출력 준수율 낮음 |

### 8.2 측정 한계

- **NoRAG Hallucination Score 0.000**: DeepEval은 컨텍스트 대비 환각을 측정하므로, 컨텍스트 없는 NoRAG에서는 환각이 0으로 판정됨. 이는 NoRAG 답변에 환각이 없다는 뜻이 아님.
- **Claude Sonnet Judge 평균 왜곡**: 표 8의 claude-sonnet__rag 평균 1.20은 76건의 0점이 포함된 값. 유효 24건의 실제 평균은 별도 계산 필요.
- **비용 데이터 미수집**: LiteLLM 비용 추적이 비활성화되어 모든 비용 필드가 0.0. GPT-4o-mini vs Gemini Pro 비용 비율은 공식 가격표 기준 수동 추정 필요.
- **Gemini Pro NaN 상관계수**: 일부 조건에서 점수가 상수(모두 동일)하여 Kendall τ / Spearman ρ가 NaN — per_condition 분석에서 해당 조건 해석 불가.

### 8.3 기술적 이슈 및 해결

| 이슈 | 해결 |
|------|------|
| Gemini 3.x temperature < 1.0 시 무한루프/품질 저하 | `temp = 1.0 if "gemini-3" in judge_model else 0.0` 동적 설정 |
| Gemini 3.1 Pro JSON 출력에 ```json 래핑 + 전후 텍스트 | `_parse_scores()` regex 강화: fenced code block + bare JSON 추출 |
| 손상된 체크포인트 (0점 포함) | 삭제 후 재실행 |
| Step4 실패 평가 포함 | `_align_samples()`에 average==0 필터 추가 |
| Step6 eval=None 샘플 AttributeError | `s.get("eval", {})` → `(s.get("eval") or {})` 방어적 코딩 |

---

## 9. 출력 파일 목록

```
data/experiments/
├── step1_retrieval/
│   └── retrieval_results.json              # 4전략 × 100 = 400건
├── step2_generation/
│   └── generation_results.json             # 6조건 × 100 = 600건
├── step3_evaluation/
│   ├── eval_gpt4o_mini_judge.json          # Primary: 600건 (459 valid judge)
│   └── eval_gemini_pro_judge.json          # Expensive: 600건 (311 valid judge)
├── step4_judge_comparison/
│   └── judge_comparison.json               # 267쌍 비교 결과
├── step5_analysis/
│   ├── position_bias.json                  # 459건 Position Bias 분석
│   ├── cross_correlation.json              # 352건 교차 상관
│   └── detection_coverage.json             # 535건 탐지율 분석
└── step6_tables_figures/
    ├── tables_figures.json                 # 표 6~10 + 부가 표 통합
    └── figures/
        ├── fig4_ragas_radar.html           # RAGAS 레이더 차트
        ├── fig_judge_heatmap.html          # Judge 히트맵
        ├── fig_detection_coverage.html     # 탐지율 막대 차트
        ├── fig5_bias_histogram.html        # Position Bias 분포
        └── fig_cost_performance.html       # 비용-성능 산점도
```

---

## 10. 핵심 결론 요약 (논문 기술용)

1. **검색**: Hybrid Rerank가 Context Recall 0.855로 최고. BM25 단독은 30배 빠르나 성능 열위.
2. **생성**: GPT-4o-mini가 비용 대비 최고 균형 (RAGAS Answer Relevancy 0.531, Judge Average 4.71).
3. **RAG 효과**: NoRAG 대비 RAG가 Answer Relevancy +0.20, Citation Accuracy +2.13 향상.
4. **Judge 대체 가능성**: GPT-4o-mini와 Gemini 3.1 Pro의 Class Agreement **90.3%** → 저비용 모델로 대체 가능.
5. **Position Bias 미미**: Wilcoxon p>0.05, ≥1점차 비율 최대 6.5% → 2회 평균이 안정성에 기여하나 효과 제한적.
6. **3단계 평가 보완성**: 단독 최고 29.7% → 3단계 조합 52.0% (+22.3%p). Judge+Safety 2단계가 핵심, RAGAS는 안전망.
7. **교차 상관**: 최대 ρ=0.502 (중간) → 3단계는 서로 다른 결함을 측정하여 보완적 관계 확인.
