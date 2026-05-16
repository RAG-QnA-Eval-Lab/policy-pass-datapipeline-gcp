"""Stage 1 — RAGAS v0.4.3 정량 평가."""

from __future__ import annotations

import asyncio
import logging
import os

from src.evaluation import RagasResult

logger = logging.getLogger(__name__)

_ragas_llm = None
_ragas_embeddings = None


def _make_llm():
    global _ragas_llm  # noqa: PLW0603
    if _ragas_llm is not None:
        return _ragas_llm

    from openai import AsyncOpenAI

    try:
        from ragas.llms import llm_factory
    except Exception as e:  # pragma: no cover
        raise RuntimeError("RAGAS LLM factory import failed") from e

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=60.0)
    _ragas_llm = llm_factory("gpt-4o-mini", client=client)
    return _ragas_llm


def _make_embeddings():
    global _ragas_embeddings  # noqa: PLW0603
    if _ragas_embeddings is not None:
        return _ragas_embeddings

    from openai import AsyncOpenAI

    try:
        from ragas.embeddings import OpenAIEmbeddings
    except Exception as e:  # pragma: no cover
        raise RuntimeError("RAGAS embeddings import failed") from e

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=60.0)
    _ragas_embeddings = OpenAIEmbeddings(client=client)
    return _ragas_embeddings


def evaluate_ragas(
    question: str,
    contexts: list[str],
    answer: str,
    ground_truth: str,
) -> RagasResult:
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    async def _run_all() -> dict[str, float | None]:
        llm = _make_llm()
        embeddings = _make_embeddings()
        scores: dict[str, float | None] = {}

        faithfulness = Faithfulness(llm=llm)
        try:
            r = await faithfulness.ascore(user_input=question, response=answer, retrieved_contexts=contexts)
            scores["faithfulness"] = float(r.value)
        except Exception:
            logger.exception("Faithfulness 평가 실패")
            scores["faithfulness"] = None

        relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)
        try:
            r = await relevancy.ascore(user_input=question, response=answer)
            scores["answer_relevancy"] = float(r.value)
        except Exception:
            logger.exception("AnswerRelevancy 평가 실패")
            scores["answer_relevancy"] = None

        precision = ContextPrecision(llm=llm)
        try:
            r = await precision.ascore(user_input=question, reference=ground_truth, retrieved_contexts=contexts)
            scores["context_precision"] = float(r.value)
        except Exception:
            logger.exception("ContextPrecision 평가 실패")
            scores["context_precision"] = None

        recall = ContextRecall(llm=llm)
        try:
            r = await recall.ascore(user_input=question, retrieved_contexts=contexts, reference=ground_truth)
            scores["context_recall"] = float(r.value)
        except Exception:
            logger.exception("ContextRecall 평가 실패")
            scores["context_recall"] = None

        return scores

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            scores = pool.submit(asyncio.run, _run_all()).result()
    else:
        scores = asyncio.run(_run_all())

    return RagasResult(
        faithfulness=scores["faithfulness"],
        answer_relevancy=scores["answer_relevancy"],
        context_precision=scores["context_precision"],
        context_recall=scores["context_recall"],
    )
