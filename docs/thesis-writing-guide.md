# 졸업논문 작성 가이드

**논문 제목**: RAG 응답 모니터링을 위한 비용 효율적 LLM-as-a-Judge 파이프라인 구축 및 성능 비교 분석

---

## 1. 최종 논문 구조

```
1. 서론
   1.1 연구 배경 및 동기
   1.2 연구 목적 및 범위
   1.3 논문 구성

2. 관련 연구
   2.1 RAG(Retrieval-Augmented Generation) 기반 시스템
       2.1.1 Hybrid 검색과 리랭킹
       2.1.2 청크 전략과 한국어 처리
   2.2 LLM 평가 방법론
       2.2.1 참조 기반 자동 평가: RAGAS
       2.2.2 LLM-as-a-Judge 패러다임
       2.2.3 Position Bias 문제와 완화 기법
   2.3 비용 효율적 LLM 평가 연구

3. 시스템 설계 및 구현
   3.1 전체 시스템 아키텍처
   3.2 데이터 수집 및 전처리
       3.2.1 공공 정책 데이터 수집 파이프라인
       3.2.2 한국어 청킹 전략
   3.3 하이브리드 검색 파이프라인
       3.3.1 Dense Retrieval (FAISS)
       3.3.2 BM25 Sparse Retrieval
       3.3.3 Reciprocal Rank Fusion
       3.3.4 Cross-Encoder 리랭킹
   3.4 멀티 LLM 생성 파이프라인
   3.5 3단계 평가 파이프라인
       3.5.1 Stage 1: RAGAS 정량 평가
       3.5.2 Stage 2: LLM-as-a-Judge 정성 평가
       3.5.3 Stage 3: DeepEval 안전성 평가
   3.6 GCP 배포 및 운영 인프라

4. 실험 및 결과 분석
   4.1 실험 설정
       4.1.1 평가 데이터셋 구성
       4.1.2 비교 대상 모델 및 전략
       4.1.3 평가 지표 정의
   4.2 검색 전략별 성능 비교
   4.3 멀티 LLM 응답 품질 비교
       4.3.1 RAGAS 정량 평가 결과
       4.3.2 LLM Judge 정성 평가 결과
       4.3.3 안전성(환각) 평가 결과
   4.4 LLM Judge 비용-성능 분석
   4.5 Position Bias 완화 효과 검증

5. 결론
   5.1 연구 요약
   5.2 학술적 기여
   5.3 한계 및 향후 연구

참고문헌
```

---

## 2. 초록

### 한국어 초록 (≤200단어)

> 본 연구는 대한민국 청년·학생 대상 정부 정책 정보의 접근성 개선을 목적으로, 하이브리드 RAG(Retrieval-Augmented Generation) 기반 질의응답 시스템과 비용 효율적 3단계 응답 품질 평가 파이프라인을 설계·구현하였다. 데이터 수집 단계에서는 공공데이터포털 및 온통청년 API를 통해 2,235건의 청년 정책 문서를 수집하고, 한국어 문장 경계 기반 청킹(512토큰, 50토큰 오버랩)을 적용하였다. 검색 단계에서는 FAISS 기반 Dense Retrieval과 BM25 Sparse Retrieval을 Reciprocal Rank Fusion(k=60)으로 결합한 후 Cross-Encoder 리랭킹을 수행하는 4단계 하이브리드 파이프라인을 구축하였다. 생성 단계에서는 LiteLLM을 통해 GPT-4o, GPT-4o-mini, Claude Sonnet, Gemini Flash, Llama3 다섯 모델을 통합하고, RAG 적용 유무에 따른 응답 품질 변화를 비교하였다. 평가 단계에서는 RAGAS v0.4 정량 지표, G-Eval 방식의 LLM Judge, DeepEval 환각 탐지를 결합한 3단계 파이프라인을 구현하였으며, Position Bias 완화를 위해 컨텍스트 순서를 두 차례 달리한 평균 점수를 사용하였다. 실험 결과, 하이브리드 리랭킹 전략이 단일 검색 대비 [X]% 높은 Context Precision을 달성하였으며, GPT-4o-mini를 Judge 모델로 활용한 경우 Gemini 3.1 Pro 대비 [Y]% 수준의 평가 일관성을 [Z]배 낮은 비용으로 달성함을 확인하였다.

### 핵심어

검색 증강 생성, LLM-as-a-Judge, 하이브리드 검색, 자동 평가, 청년 정책

### English Abstract (~200 words)

> This study designs and implements a hybrid Retrieval-Augmented Generation (RAG) question-answering system for Korean government youth policy information, accompanied by a cost-efficient three-stage response quality evaluation pipeline. We collected 2,235 youth policy documents via the Public Data Portal and Youth Policy APIs, and applied Korean sentence-boundary-aware chunking (512 tokens, 50-token overlap). For retrieval, we constructed a four-strategy hybrid pipeline combining FAISS-based dense retrieval with BM25 sparse retrieval through Reciprocal Rank Fusion (k=60) and Cross-Encoder reranking. Five large language models — GPT-4o, GPT-4o-mini, Claude Sonnet, Gemini Flash, and Llama3 — were unified under LiteLLM and compared with and without RAG augmentation. Evaluation employed a three-stage pipeline: (1) RAGAS v0.4 reference-based metrics (Faithfulness, Answer Relevancy, Context Precision, Context Recall); (2) G-Eval-style LLM-as-a-Judge scoring three dimensions (citation accuracy, completeness, readability) with position bias mitigation via two-pass context shuffling; and (3) DeepEval hallucination detection. Experiments on 100 curated QA pairs show that the hybrid reranking strategy achieves [X]% higher Context Precision than single-modality retrieval, and that GPT-4o-mini as the judge model attains [Y]% of Gemini 3.1 Pro-level evaluation consistency at [Z]x lower cost, demonstrating the viability of cost-efficient LLM-as-a-Judge monitoring for production RAG systems.

### Keywords

Retrieval-Augmented Generation, LLM-as-a-Judge, Hybrid Retrieval, Automated Evaluation, Youth Policy

---

## 3. 섹션별 작성 가이드

### 1장. 서론

#### 1.1 연구 배경 및 동기 (약 0.7페이지)

**첫 번째 단락 — 사회적 문제 정의.**
청년·학생 정부 지원 정책이 매년 수백 건 신설·변경되지만, 각 부처 사이트에 분산되어 접근성이 낮다는 문제. "온통청년" 등 통합 포털이 존재하나 자연어 질의 대응 기능이 없다는 한계. "왜 이 문제를 풀어야 하는가"를 설득.

**두 번째 단락 — 기술적 배경: RAG와 LLM.**
ChatGPT 등 LLM의 등장으로 도메인 특화 QA 비용이 낮아졌으나, 환각(Hallucination) 문제 존재. 정책 정보처럼 자주 업데이트되는 도메인에서는 RAG 필수. Lewis et al. (2020) RAG 논문 인용.

**세 번째 단락 — 핵심 문제: RAG 품질 평가의 어려움.**
전통 BLEU/ROUGE가 RAG에 부적합. RAGAS(Es et al., 2024)와 LLM-as-a-Judge(Zheng et al., 2023) 등장했으나, 상용 모델 Judge 사용 시 평가 비용 > 운영 비용이 될 수 있는 실용적 문제. **이 단락이 논문의 핵심 동기.**

#### 1.2 연구 목적 및 범위 (약 0.3페이지)

번호 목록으로 명확히 제시:
1. 청년 정책 도메인 Hybrid RAG 파이프라인 구축 및 검색 전략 간 성능 비교
2. RAGAS v0.4 + LLM Judge + DeepEval 결합 3단계 자동 평가 설계
3. 경량 Judge 모델(GPT-4o-mini) 비용 효율성 검증
4. Position Bias 완화 기법의 효과 실증

범위: 한국어 텍스트, GCP Cloud Run 배포, 100쌍 QA 데이터셋. 논문이 다루지 않는 것도 명시.

#### 1.3 논문 구성 (2~3문장)

"본 논문은 다음과 같이 구성된다. 2장에서는..."

---

### 2장. 관련 연구

각 절 마지막에 "그러나 본 연구와의 차이점은…" 한두 문장 반드시 추가.

#### 2.1 RAG 기반 시스템 (약 0.8페이지)

- **2.1.1 Hybrid 검색과 리랭킹**: Lewis et al. (2020) → Hybrid 방식 → Cormack et al. (2009) RRF → Nogueira & Cho (2019) Cross-Encoder. 한국어 도메인 특화 Hybrid RAG 연구 부족 지적.
- **2.1.2 청크 전략과 한국어 처리**: 고정 크기 vs 문장 경계 청킹. kss + tiktoken 조합 소개.

#### 2.2 LLM 평가 방법론 (약 1페이지)

- **2.2.1 RAGAS**: Es et al. (2024, EACL). 4개 지표 설명. **v0.3 vs v0.4 API 차이 명시 필수.**
- **2.2.2 LLM-as-a-Judge**: Zheng et al. (2023, NeurIPS) + Liu et al. (2023, EMNLP) G-Eval.
- **2.2.3 Position Bias**: Wang et al. (2024, ACL). 본 연구의 2회 평균 기법과의 차이 기술.

#### 2.3 비용 효율적 LLM 평가 (약 0.4페이지)

Prometheus (Kim et al., ICLR 2024), ARES (Saad-Falcon et al., NAACL 2024). 이들은 파인튜닝 필요. **본 연구는 파인튜닝 없이 상용 경량 모델 활용이라는 점에서 차별화.** (2장 전체의 핵심 결론)

---

### 3장. 시스템 설계 및 구현

목적: 독자가 동일 시스템을 재현할 수 있을 정도의 정보 제공. 코드 대신 알고리즘과 설계 결정의 근거.

#### 3.1 전체 시스템 아키텍처 (0.5p) → **그림 1** 배치
#### 3.2 데이터 수집 및 전처리 (0.6p) → **표 1** (데이터 소스 요약)
#### 3.3 하이브리드 검색 파이프라인 (0.8p) → **그림 2** 배치, RRF 수식 포함
#### 3.4 멀티 LLM 생성 파이프라인 (0.4p) → **표 2** (모델 요약)
#### 3.5 3단계 평가 파이프라인 (1.2p) → **그림 3** 배치, Judge 기준 표 포함
#### 3.6 GCP 배포 및 운영 인프라 (0.4p) → **표 3** (인프라 구성)

---

### 4장. 실험 및 결과 분석

**주장-증거-해석 삼단 구조로 모든 결과 단락 작성:**
1. 주장: "hybrid_rerank가 가장 높은 Context Precision 달성"
2. 증거: "(표 6) 평균 0.XX로, 차순위 0.XX 대비 XX% 높다"
3. 해석: "Cross-Encoder 리랭킹이 낮은 관련성 문서를 후순위로 밀어내기 때문"

#### 4.1 실험 설정 (0.5p)
- **표 4**: QA 데이터셋 카테고리 분포
- **표 5**: 평가 지표 정의 (RAGAS 4 + Judge 3 + Hallucination 1 + 레이턴시)
- 독립 변수: 검색 전략 4종 × 생성 모델 5종 × RAG 유무 2종

#### 4.2 검색 전략별 성능 비교 (0.5p) → **표 6**
#### 4.3 멀티 LLM 응답 품질 비교 (0.8p) → **표 7, 8, 9** + **그림 4** (레이더 차트)
#### 4.4 LLM Judge 비용-성능 분석 (0.5p) → **표 10** (핵심 테이블)
#### 4.5 Position Bias 완화 효과 (0.4p) → **그림 5** (히스토그램)

---

### 5장. 결론

#### 5.1 연구 요약 (3~4문장)
#### 5.2 학술적 기여 (번호 목록 4개)
1. 한국어 정책 도메인 Hybrid RAG + 4가지 검색 전략 실증 비교
2. RAGAS + LLM Judge + DeepEval 상보적 3단계 프레임워크 설계
3. 경량 Judge 모델 비용 효율성 실증
4. Position Bias 완화 2회 평균 기법 효과 검증

#### 5.3 한계 및 향후 연구 (2~3문장)
100쌍 통계적 한계, 한국어 특화 Judge 모델 비교, 실시간 재평가 메커니즘 등

---

## 4. 그림/표 목록

| 번호 | 유형 | 제목 | 배치 절 |
|------|------|------|---------|
| 그림 1 | 아키텍처 | 전체 시스템 아키텍처 | 3.1 |
| 그림 2 | 흐름도 | 하이브리드 검색 파이프라인 | 3.3 |
| 그림 3 | 흐름도 | 3단계 평가 파이프라인 | 3.5 |
| 그림 4 | 레이더/히트맵 | 모델별 RAGAS 지표 분포 | 4.3.1 |
| 그림 5 | 히스토그램 | Position Bias 점수 분포 | 4.5 |
| 표 1 | 데이터 | 데이터 소스 요약 | 3.2.1 |
| 표 2 | 데이터 | 사용 모델 요약 | 3.4 |
| 표 3 | 데이터 | GCP 인프라 구성 | 3.6 |
| 표 4 | 데이터 | QA 데이터셋 카테고리 분포 | 4.1.1 |
| 표 5 | 데이터 | 평가 지표 정의 | 4.1.3 |
| 표 6 | 결과 | 검색 전략별 성능 비교 | 4.2 |
| 표 7 | 결과 | 모델별 RAGAS 지표 | 4.3.1 |
| 표 8 | 결과 | 모델별 Judge 점수 | 4.3.2 |
| 표 9 | 결과 | 모델별 환각 점수 | 4.3.3 |
| 표 10 | 결과 | Judge 모델 비용-성능 비교 | 4.4 |

---

## 5. 참고문헌 (핵심 10편)

```
[1] Lewis, P., Perez, E., Piktus, A., et al. (2020).
    Retrieval-augmented generation for knowledge-intensive NLP tasks.
    NeurIPS 2020, 33, 9459-9474.

[2] Es, S., James, J., Anke, L. E., & Schockaert, S. (2024).
    RAGAS: Automated evaluation of retrieval augmented generation.
    EACL 2024, 150-163.

[3] Zheng, L., Chiang, W. L., Sheng, Y., et al. (2023).
    Judging LLM-as-a-judge with MT-bench and chatbot arena.
    NeurIPS 2023, 36.

[4] Liu, Y., Iter, D., Xu, Y., et al. (2023).
    G-eval: NLG evaluation using GPT-4 with better human alignment.
    EMNLP 2023, 2511-2522.

[5] Wang, P., Li, L., Chen, L., et al. (2024).
    Large language models are not fair evaluators.
    ACL 2024.

[6] Kim, S., Shin, J., Choi, Y., et al. (2024).
    Prometheus: Inducing fine-grained evaluation capability in language models.
    ICLR 2024.

[7] Saad-Falcon, J., Khattab, O., Potts, C., & Zaharia, M. (2024).
    ARES: An automated evaluation framework for RAG systems.
    NAACL 2024.

[8] Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009).
    Reciprocal rank fusion outperforms condorcet and individual rank learning methods.
    SIGIR 2009, 758-759.

[9] Nogueira, R., & Cho, K. (2019).
    Passage re-ranking with BERT.
    arXiv:1901.04085.

[10] RAGAS Documentation. (2024). RAGAS v0.4 API Reference.
     https://docs.ragas.io/en/stable/
```

---

## 6. 페이지 수 배분

| 섹션 | 권장 페이지 |
|------|------------|
| 초록 + 키워드 | 0.5 |
| 1장. 서론 | 1.0 |
| 2장. 관련 연구 | 1.5 |
| 3장. 시스템 설계 및 구현 | 2.5 |
| 4장. 실험 및 결과 분석 | 2.5 |
| 5장. 결론 | 0.5 |
| 참고문헌 | 0.5+ |
| **합계** | **9.0+** |

---

## 7. 논문 작성 순서 (권장)

1. **표 6~10 채우기** — 실험 수치 확정
2. **4장 작성** — 수치를 해석하는 글
3. **3장 작성** — 구현 세부사항 (코드로 이미 존재, 가장 쓰기 쉬움)
4. **2장 작성** — 관련 연구 (P1~P8 논문 읽으며 요약)
5. **1장 + 5장 작성** — 전체 파악 후 서론 동기/결론 기여 확정
6. **초록 가장 마지막** — 논문 전체의 압축

---

## 8. 흔한 실수 7가지

1. **구현 나열 함정**: "FastAPI를 사용했고, Streamlit을 사용했고" → 모든 기술 선택에 "왜"가 필요
2. **결과 없는 기여 주장**: "비용 효율적"은 표 10 수치 없이 무효
3. **한계 숨기기**: 100쌍은 작은 수치 → 언급하면 "객관적 연구자" 인상
4. **수동태/능동태 혼용**: 일관된 시제와 주어 유지
5. **참조 없는 그림/그림 없는 참조**: 모든 그림·표는 본문에서 "(그림 X)" 참조 필수
6. **선행 연구 비교 누락**: 비교 가능한 선행 연구 없으면 "직접 비교 불가, 절대 수치 제시" 명시
7. **RAGAS 버전 미명시**: v0.3 vs v0.4 차이 명시 필수 (재현성)

---

## 9. 최종 품질 체크리스트 (제출 전 필수 검증)

### 서론 4단계 흐름 검증
- [ ] Context: 도메인 중요성 + 현재 시스템 소개
- [ ] Problem: 기존 방식의 치명적 한계 (비용, 신뢰성 등)
- [ ] Solution: 제안 아키텍처/파이프라인 한 문장 요약
- [ ] Contribution: 서론 마지막에 **기여점 3~4개를 번호 목록으로 명시** (예: "첫째, 한국어 정책 도메인 최초의 3단계 평가 파이프라인을 제안한다. 둘째, …")

### 'Why' 중심 기술 (3장 전체)
모든 기술 선택에 대해 아래 패턴으로 작성:
1. 선택한 기술/방법 명시
2. **왜** 이것을 선택했는지 (대안 대비 장점)
3. 어떤 **제약** 하에서 이 결정이 이루어졌는지

예시:
- "FAISS를 선택한 이유는 Cloud Run scale-to-zero 환경에서 인메모리 인덱스가 적합하기 때문이다 (ChromaDB 대비 서버리스 친화적)"
- "Cross-Encoder 모델로 ms-marco-MiniLM-L-6-v2를 선택한 이유는 Cloud Run 2Gi 메모리 제약 하에서 로드 가능한 경량 모델이기 때문이다"

### 한계점 전략
한계를 솔직히 명시하면 **연구 신뢰도가 올라간다**. 숨기면 심사위원이 직접 지적하므로 오히려 불리:
- [ ] 데이터셋 규모 한계 (100쌍 → 통계적 검정력 제한)
- [ ] 한국어 특화 Judge 미비교 (KoGPT, EXAONE 등)
- [ ] Cross-Encoder의 영어 모델 한계 (한국어 의미론적 정밀도)
- [ ] 각 한계에 대해 "향후 연구에서 ~로 보완 가능" 한 문장씩 추가

### 형식 일관성 (제출 직전 최종 검수)
- [ ] **용어 통일**: 같은 개념에 다른 단어 혼용 금지. 아래 용어 매핑을 논문 전체에 일관 적용:
  - 시스템/파이프라인 → 둘 중 하나로 통일 (맥락에 따라 "시스템"=전체, "파이프라인"=데이터 흐름으로 구분 가능)
  - 모델/LLM → "모델"로 통일, 첫 등장 시 "대형 언어 모델(LLM, Large Language Model)"로 정의
  - 환각/Hallucination → "환각(Hallucination)"으로 통일
  - 평가/Judge → "LLM Judge 평가"로 통일
- [ ] **수식 변수 설명**: 수식에 등장하는 모든 변수에 대해 직후에 "여기서 k는 ~, r_i(d)는 ~" 형태로 설명. 단 하나도 누락 불가
- [ ] **참고문헌 포맷 일관성**: 본문 인용 형식 (예: "[1]" 또는 "(Zheng et al., 2023)")과 참고문헌 리스트의 형식이 100% 일치하는지 최종 확인. IEEE/APA 중 하나로 통일
- [ ] **그림/표 참조 완전성**: 모든 그림·표가 본문에서 "(그림 X)", "(표 X)"로 참조됨. 참조 없는 그림·표 또는 그림·표 없는 참조가 없는지 확인

---

## 10. 구현 → 학술적 기여 변환

| 구현 사실 | 학술적 표현 |
|-----------|-------------|
| kss로 문장을 나눴다 | 한국어 문장 경계 인식 청킹이 고정 크기 대비 의미 단위 보존 효과를 확인 |
| Position Bias 피하려고 2번 평가 | 컨텍스트 순서 교체 2회 평균이 단일 평가 대비 분산 X% 감소 |
| GPT-4o-mini를 Judge로 사용 | 경량 Judge가 고비용 모델 대비 Y% 일관성을 Z배 낮은 비용으로 달성 |
| Cross-Encoder 리랭킹 추가 | 리랭킹 단계가 Context Precision을 X% 향상 |

---

## 11. 학술적 차별점 (Novelty) 분석

### 핵심 전제

개별 컴포넌트(Hybrid 검색, RAGAS, LLM-as-a-Judge, DeepEval)는 각각 기존 연구에 존재한다. 본 연구의 기여는 **새로운 알고리즘 발명이 아니라**, 기존 기법의 새로운 조합·도메인 적용·실증적 검증에 있다.

### 차별점 1: 3단계 상보적 평가 프레임워크 ★★★★★ (핵심 기여)

**기존 연구의 한계:**
- RAGAS (Es et al., 2024) → RAGAS 메트릭만 단독 제안
- Zheng et al. (2023) → LLM Judge 패러다임만 단독 제안
- ARES (Saad-Falcon et al., 2024) → 분류기 학습 기반 단일 평가
- Prometheus (Kim et al., 2024) → 파인튜닝된 Judge 모델 단일 접근

**본 연구의 차별점:**
3개 평가 체계를 하나의 파이프라인으로 결합하고, 각 단계가 **다른 RAG 실패 모드**를 탐지한다는 점을 실증:

| 단계 | 프레임워크 | 측정 대상 | 탐지하는 실패 모드 |
|------|-----------|----------|-------------------|
| Stage 1 | RAGAS Faithfulness | 답변이 컨텍스트에 **근거**하는가 | 근거 부족 (unsupported claims) |
| Stage 2 | LLM Judge citation_accuracy | 답변이 컨텍스트를 **정확히 인용**하는가 | 부정확한 인용·왜곡 |
| Stage 3 | DeepEval Hallucination | 답변이 컨텍스트와 **모순**되는가 | 명시적 모순 (contradiction) |

이 셋은 중복이 아니라 상보적이다. RAGAS가 "통과"해도 Judge가 "불합격"할 수 있고, 그 역도 성립한다.
**3개 프레임워크의 교차 상관관계를 실험적으로 분석한 연구는 기존에 없다.**

> 논문 표현: "본 연구는 참조 기반 정량 평가(RAGAS), 참조 비의존 정성 평가(LLM Judge), 안전성 평가(DeepEval)를 단일 파이프라인으로 통합하여, 각 단계가 서로 다른 RAG 실패 모드를 탐지하는 상보적 프레임워크를 제안한다."

### 차별점 2: 파인튜닝 없는 경량 Judge 비용 효율성 실증 ★★★★★

**기존 연구:**
- Prometheus (Kim et al., ICLR 2024) → 오픈소스 LLM을 **파인튜닝**해서 Judge로 사용 (학습 비용 발생)
- ARES (Saad-Falcon et al., NAACL 2024) → **분류기를 학습**시켜 평가 (학습 데이터 필요)

**본 연구:**
- 파인튜닝 비용 0원, 학습 데이터 0건
- 기존 상용 경량 모델(GPT-4o-mini)을 그대로 Judge로 사용
- Gemini 3.1 Pro 대비 비용 절감, 평가 일관성 비율 실측
- 실무에서 Prometheus처럼 모델을 파인튜닝할 여력이 없는 팀을 위한 **실용적** 기여

### 차별점 3: RAG 컨텍스트 순서 기반 Position Bias 완화 ★★★★

**기존 연구 (Wang et al., 2024, ACL):**
- MT-Bench 스타일 **pairwise 비교**(답변 A vs B 순서)에서 position bias 발견
- 해결: calibration 기반 보정 또는 답변 순서 swap

**본 연구 (`src/evaluation/llm_judge.py:111`):**
- RAG 평가에서 **검색 문서 순서**(컨텍스트 순서)에 의한 bias를 완화
- 원래 순서 1회 + 셔플 순서 1회 → 평균 점수 사용
- pairwise가 아닌 **pointwise** 평가에서의 position bias 완화 (다른 문제 설정)
- Wang et al.의 "어떤 답변이 먼저 나오냐"와, 본 연구의 "검색 문서가 어떤 순서로 제시되냐"는 **다른 종류의 position bias**

### 차별점 4: 한국어 정책 도메인 특화 RAG 실증 ★★★

- 한국어 문장 경계 기반 청킹 (`kss` mecab → punct → regex 폴백 + `tiktoken` cl100k_base)
- 한국어 정부 정책 문서에서 4가지 검색 전략 체계적 성능 비교
- 한국어 정책 도메인에서 이런 체계적 비교를 수행한 선행 연구 부재

### 차별점 5: 평가의 프로덕션 모니터링 통합 ★★★

- 대부분의 평가 연구는 오프라인 실험. 본 연구는 `/api/v1/evaluate` API로 온라인 평가 가능
- Airflow DAG으로 자동화된 배치 평가 스케줄링
- 체크포인트 저장으로 장시간 평가 안정성 확보
- JSON + HTML 리포트 자동 생성 + Grafana 모니터링 연동

### 논문에서의 Contribution Statement (5.2절 사용)

1. 한국어 정책 도메인에서 4가지 하이브리드 검색 전략의 체계적 성능 비교
2. RAGAS + LLM Judge + DeepEval 상보적 3단계 평가 프레임워크 설계 및 교차 상관 분석
3. 파인튜닝 없는 경량 Judge 모델(GPT-4o-mini)의 비용 효율성 실증
4. RAG 컨텍스트 순서 기반 Position Bias 완화 기법의 효과 검증

---

## 12. 실험 설계: 필요한 지표와 예상 결과

### 실험 A: 검색 전략별 성능 비교 (4.2절)

**독립변수**: 검색 전략 4종 (vector_only, bm25_only, hybrid, hybrid_rerank)
**종속변수**: RAGAS Context Precision, Context Recall
**통제변수**: 동일 QA 100쌍, 동일 LLM (GPT-4o-mini), top_k=5

**예상 결과 테이블 (표 6):**

| 전략 | Context Precision | Context Recall | 검색 레이턴시(s) |
|------|------------------|----------------|-----------------|
| vector_only | 0.60~0.75 | 0.55~0.70 | ~0.05 |
| bm25_only | 0.50~0.65 | 0.50~0.65 | ~0.02 |
| hybrid (RRF) | 0.70~0.82 | 0.65~0.78 | ~0.07 |
| hybrid_rerank | **0.78~0.90** | **0.70~0.85** | ~0.15 |

**핵심 주장**: hybrid_rerank가 가장 높은 Context Precision 달성. Cross-Encoder 리랭킹이 낮은 관련성 문서를 후순위로 밀어내기 때문.

### 실험 B: 멀티 LLM 응답 품질 비교 (4.3절)

**독립변수**: 생성 모델 5종 × RAG 유무 2종 = 10 조건
**종속변수**: RAGAS 4지표 + Judge 3지표 + Hallucination
**통제변수**: hybrid_rerank 전략, 동일 QA 100쌍

**예상 결과 테이블 (표 7 — RAGAS):**

| 모델 | Faithfulness | Answer Relevancy | Context Precision | Context Recall |
|------|-------------|-----------------|------------------|----------------|
| GPT-4o (RAG) | 0.80~0.92 | 0.82~0.90 | (동일) | (동일) |
| GPT-4o-mini (RAG) | 0.75~0.88 | 0.78~0.86 | (동일) | (동일) |
| Claude Sonnet (RAG) | 0.78~0.90 | 0.80~0.88 | (동일) | (동일) |
| Gemini Flash (RAG) | 0.72~0.85 | 0.75~0.84 | (동일) | (동일) |
| Llama3 (RAG) | 0.65~0.80 | 0.70~0.82 | (동일) | (동일) |
| GPT-4o (No-RAG) | 0.30~0.50 | 0.60~0.75 | N/A | N/A |

**핵심 주장**: RAG 적용 시 Faithfulness가 No-RAG 대비 크게 향상. Context Precision/Recall은 검색 전략에 의존하므로 모델 간 동일.

**예상 결과 테이블 (표 8 — Judge):**

| 모델 | Citation Accuracy | Completeness | Readability | Average |
|------|------------------|-------------|-------------|---------|
| GPT-4o (RAG) | 4.2~4.8 | 4.0~4.6 | 4.3~4.8 | 4.2~4.7 |
| GPT-4o-mini (RAG) | 3.8~4.5 | 3.7~4.3 | 4.0~4.6 | 3.8~4.5 |
| Claude Sonnet (RAG) | 4.0~4.7 | 4.0~4.5 | 4.2~4.7 | 4.1~4.6 |
| Gemini Flash (RAG) | 3.5~4.3 | 3.5~4.2 | 3.8~4.4 | 3.6~4.3 |
| Llama3 (RAG) | 3.2~4.0 | 3.3~4.0 | 3.5~4.2 | 3.3~4.1 |

**예상 결과 테이블 (표 9 — Safety):**

| 모델 | Hallucination Score | 비고 |
|------|-------------------|------|
| GPT-4o (RAG) | 0.05~0.15 | 낮을수록 안전 |
| GPT-4o (No-RAG) | 0.25~0.50 | RAG 없으면 환각 증가 |

### 실험 C: LLM Judge 비용-성능 분석 (4.4절) ★★★★★

**독립변수**: Judge 모델 2종 (Gemini 3.1 Pro, GPT-4o-mini)
**종속변수**: 평가 점수 일관성, 비용, 레이턴시
**통제변수**: 동일 QA 100쌍의 동일 답변을 두 Judge로 각각 평가

**예상 결과 테이블 (표 10 — 핵심 테이블):**

| Judge 모델 | 평가 비용/100쌍 | 레이턴시/건 | Kendall τ (순위 일치) | MAE (점수 차이) |
|-----------|---------------|-----------|---------------------|----------------|
| Gemini 3.1 Pro | GCP 크레딧 | ~2.5s | 1.0 (기준) | 0.0 (기준) |
| GPT-4o-mini | ~$0.10~0.25 | ~0.8s | 0.75~0.90 | 0.3~0.6 |

**핵심 주장**: GPT-4o-mini는 Gemini 3.1 Pro 대비 대폭 낮은 비용으로 Kendall τ 0.8 이상의 순위 일관성 달성.

**측정해야 할 세부 지표:**
1. **Kendall's τ (순위 상관)**: 두 Judge가 100쌍의 답변 품질 순위를 얼마나 동일하게 매기는가
2. **MAE (Mean Absolute Error)**: 두 Judge의 1-5점 점수 차이 평균
3. **Perfect Agreement Rate**: 두 Judge가 정확히 같은 점수를 준 비율
4. **Class Agreement Rate**: 두 Judge가 같은 등급(1-2 나쁨, 3 보통, 4-5 좋음)을 준 비율

### 실험 D: Position Bias 완화 효과 검증 (4.5절)

**독립변수**: 평가 방식 2종 (단일 평가 vs 2회 평균)
**종속변수**: 점수 분산, 순서 의존 점수 차이
**통제변수**: 동일 QA 100쌍, GPT-4o-mini Judge

**측정해야 할 지표:**

| 지표 | 단일 평가 (shuffle=False) | 2회 평균 | 비교 |
|------|------------------------|---------|------|
| 점수 표준편차 | σ₁ | σ₂ | σ₂ < σ₁ 기대 |
| |score(원본순서) - score(셔플순서)| 평균 | 해당없음 | Δ | Δ가 클수록 bias 존재 입증 |
| 1점 이상 차이 나는 비율 | 해당없음 | X% | 높을수록 bias 심각 |

**핵심 주장**: 컨텍스트 순서에 따라 평균 |Δ|=0.3~0.7점 차이 발생하며, 2회 평균이 이를 완화한다.

### 실험 E: 3단계 교차 상관 분석 (4.3절 통합 또는 별도 절)

**목적**: 3개 평가 단계가 정말 "상보적"인지, 아니면 "중복"인지 실증

**측정해야 할 상관계수 (Spearman ρ):**

| 지표 쌍 | 예상 Spearman ρ | 해석 |
|---------|----------------|------|
| RAGAS Faithfulness ↔ Judge Citation Accuracy | 0.5~0.7 (중간) | 관련되지만 동일하지 않음 → 상보적 |
| RAGAS Faithfulness ↔ Hallucination | -0.4~-0.6 (역상관) | 근거 높으면 환각 낮음 → 같은 축의 양끝 |
| Judge Completeness ↔ RAGAS Answer Relevancy | 0.3~0.5 (약~중간) | 완결성과 관련성은 다른 차원 |
| Judge Readability ↔ 나머지 전부 | 0.1~0.3 (약) | 가독성은 독립적 품질 차원 |

**핵심 주장**:
- ρ < 0.7이면 → "두 지표는 서로 다른 것을 측정한다" = 상보적
- ρ > 0.9이면 → "두 지표는 같은 것을 측정한다" = 중복 (하나 제거 가능)
- 예상: 대부분 0.3~0.7 범위 → 3단계 모두 필요하다는 결론

---

## 13. 실험 실행 체크리스트

### Phase 1: 데이터 준비
- [ ] QA 100쌍 (`data/eval/qa_pairs.json`) 카테고리 분포 확인
- [ ] 각 QA 쌍에 ground_truth 정답 포함 여부 확인

### Phase 2: 검색 실험 (실험 A)
- [ ] 4가지 전략으로 100쌍 검색 실행
- [ ] 전략별 Context Precision, Context Recall 측정
- [ ] 전략별 검색 레이턴시 기록

### Phase 3: 생성 실험 (실험 B)
- [ ] 5개 모델 × RAG 모드로 100쌍 답변 생성
- [ ] 대표 모델 1개로 No-RAG 답변도 생성 (비교용)
- [ ] 모든 답변에 토큰 수, 레이턴시 기록

### Phase 4: 3단계 평가 실행 (실험 B + E)
- [ ] 각 답변에 RAGAS 4지표 평가
- [ ] 각 답변에 LLM Judge (GPT-4o-mini) 3지표 평가
- [ ] 각 답변에 DeepEval Hallucination 평가
- [ ] 3단계 교차 상관계수 (Spearman ρ) 계산

### Phase 5: Judge 비교 실험 (실험 C)
- [ ] 동일 100쌍을 Gemini 3.1 Pro Judge로 재평가
- [ ] Gemini 3.1 Pro vs GPT-4o-mini: Kendall τ, MAE, Agreement Rate 계산
- [ ] 비용 산출 (API usage 기록)

### Phase 6: Position Bias 실험 (실험 D)
- [ ] shuffle=False만 점수 vs 2회 평균 점수 비교
- [ ] |Δ| 분포 히스토그램 생성
- [ ] 분산 감소율 계산

### Phase 7: 리포트 생성
- [ ] 표 6~10 수치 채우기
- [ ] 그림 4 (레이더 차트), 그림 5 (히스토그램) 생성
- [ ] 모든 [X], [Y], [Z] 플레이스홀더를 실제 수치로 교체
