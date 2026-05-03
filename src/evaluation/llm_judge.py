"""Stage 2 — LLM-as-a-Judge 정성 평가 (G-Eval 방식)."""

from __future__ import annotations

import json
import logging
import random

from src.evaluation import JudgeResult

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
당신은 RAG(Retrieval-Augmented Generation) 시스템의 응답 품질을 평가하는 전문 심사위원입니다.

아래 3가지 기준으로 1~5점 정수 점수를 매기세요.

## 평가 기준

1. **citation_accuracy** (인용 정확성)
   - 1점: 답변이 제공된 컨텍스트와 완전히 무관하거나 모순됨
   - 3점: 일부 정보는 컨텍스트에 근거하나 부정확한 내용이 섞임
   - 5점: 답변의 모든 정보가 컨텍스트에 정확히 근거함

2. **completeness** (완결성)
   - 1점: 질문의 핵심 사항에 전혀 답하지 못함
   - 3점: 질문의 일부에만 답하고 중요한 정보가 빠짐
   - 5점: 질문의 모든 측면에 빠짐없이 답함

3. **readability** (가독성)
   - 1점: 문장이 비문법적이거나 이해할 수 없음
   - 3점: 이해 가능하나 구조가 산만하거나 불필요한 반복이 있음
   - 5점: 명확하고 논리적으로 잘 구성된 답변

## 출력 형식

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력합니다.

```json
{
  "citation_accuracy": <1-5>,
  "completeness": <1-5>,
  "readability": <1-5>
}
```"""

_JUDGE_USER_TEMPLATE = """\
## 질문
{question}

## 검색된 컨텍스트
{contexts}

## 생성된 답변
{answer}"""

_DEFAULT_JUDGE_MODEL = "vertex_ai/openai/gpt-4o-mini"


def _build_context_block(contexts: list[str], shuffle: bool = False) -> str:
    ordered = list(contexts)
    if shuffle:
        random.shuffle(ordered)
    parts = [f"[문서 {i + 1}]\n{c}" for i, c in enumerate(ordered)]
    return "\n\n".join(parts)


def _parse_scores(raw: str) -> dict[str, int] | None:
    """JSON 블록에서 점수 파싱 — ```json ... ``` 래핑도 처리."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
        required = {"citation_accuracy", "completeness", "readability"}
        if not required.issubset(data.keys()):
            return None
        for key in required:
            val = int(data[key])
            if not 1 <= val <= 5:
                return None
            data[key] = val
        return data
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def judge_response(
    question: str,
    contexts: list[str],
    answer: str,
    judge_model: str = _DEFAULT_JUDGE_MODEL,
) -> JudgeResult:
    """LLM Judge 정성 평가 — Position Bias 완화를 위해 2회 평가 후 평균.

    Args:
        question: 사용자 질문.
        contexts: 검색된 컨텍스트.
        answer: 생성된 답변.
        judge_model: 평가에 사용할 LLM 모델 ID.

    Returns:
        JudgeResult with averaged scores.
    """
    from src.generation.llm_client import generate

    all_scores: list[dict[str, int]] = []

    for shuffle in (False, True):
        ctx_block = _build_context_block(contexts, shuffle=shuffle)
        user_msg = _JUDGE_USER_TEMPLATE.format(
            question=question,
            contexts=ctx_block,
            answer=answer,
        )

        try:
            resp = generate(
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                model=judge_model,
                temperature=0.0,
                max_tokens=256,
            )
            scores = _parse_scores(resp.content)
            if scores is not None:
                all_scores.append(scores)
            else:
                logger.warning("Judge 응답 파싱 실패 (shuffle=%s): %s", shuffle, resp.content[:200])
        except Exception:
            logger.exception("Judge LLM 호출 실패 (shuffle=%s)", shuffle)

    if not all_scores:
        logger.error("Judge 평가 전체 실패")
        return JudgeResult()

    avg_citation = sum(s["citation_accuracy"] for s in all_scores) / len(all_scores)
    avg_completeness = sum(s["completeness"] for s in all_scores) / len(all_scores)
    avg_readability = sum(s["readability"] for s in all_scores) / len(all_scores)
    avg_total = (avg_citation + avg_completeness + avg_readability) / 3.0

    return JudgeResult(
        citation_accuracy=round(avg_citation, 2),
        completeness=round(avg_completeness, 2),
        readability=round(avg_readability, 2),
        average=round(avg_total, 2),
        raw_scores=tuple(all_scores),
    )
