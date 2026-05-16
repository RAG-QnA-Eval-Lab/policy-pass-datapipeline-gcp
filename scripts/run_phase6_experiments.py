"""Phase 6 실험 실행 스크립트.

실험 매트릭스:
1. 모델 비교: 여러 LLM × Hybrid+Rerank
2. 검색 전략 비교: GPT-4o-mini × 4가지 검색 전략
3. RAG vs No-RAG: GPT-4o-mini × 컨텍스트 유무

예시:
    python scripts/run_phase6_experiments.py --experiment model --limit 10 --skip-evaluation
    python scripts/run_phase6_experiments.py --experiment all --limit 100
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config.models import MODELS, resolve_model_key
from src.evaluation.evaluator import RAGEvaluator
from src.evaluation.report import generate_report
from src.generation.pipeline import RAGPipeline
from src.retrieval.pipeline import SearchStrategy

logger = logging.getLogger(__name__)

_DEFAULT_MODELS = ["gpt-4o-mini", "gpt-4o", "claude-sonnet", "gemini-flash", "gemini-pro", "llama3"]
_DEFAULT_STRATEGIES = [s.value for s in SearchStrategy]


def load_qa_samples(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = data.get("samples", data if isinstance(data, list) else [])
    if limit:
        samples = samples[:limit]
    return samples


def _build_groups(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}

    if args.experiment in {"all", "model"}:
        for model_key in args.models:
            groups[f"model:{model_key}"] = {
                "model": resolve_model_key(model_key) or model_key,
                "strategy": args.strategy,
                "no_rag": False,
                "experiment": "model_comparison",
            }

    if args.experiment in {"all", "strategy"}:
        for strategy in args.strategies:
            groups[f"strategy:{strategy}"] = {
                "model": resolve_model_key(args.fixed_model) or args.fixed_model,
                "strategy": strategy,
                "no_rag": False,
                "experiment": "strategy_comparison",
            }

    if args.experiment in {"all", "rag"}:
        model = resolve_model_key(args.fixed_model) or args.fixed_model
        groups["rag:with_context"] = {
            "model": model,
            "strategy": args.strategy,
            "no_rag": False,
            "experiment": "rag_vs_no_rag",
        }
        groups["rag:no_context"] = {
            "model": model,
            "strategy": "no_rag",
            "no_rag": True,
            "experiment": "rag_vs_no_rag",
        }

    return groups


def _generate_group(
    pipeline: RAGPipeline,
    qa_samples: list[dict[str, Any]],
    group_name: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    total = len(qa_samples)

    for idx, sample in enumerate(qa_samples, start=1):
        sample_id = sample.get("id", f"q{idx:03d}")
        logger.info("[%s %d/%d] generating %s", group_name, idx, total, sample_id)
        started = time.monotonic()
        try:
            if config["no_rag"]:
                response = pipeline.run_no_rag(query=sample["question"], model=config["model"])
            else:
                response = pipeline.run(
                    query=sample["question"],
                    model=config["model"],
                    strategy=config["strategy"],
                )

            usage = response.llm_response
            outputs.append(
                {
                    **sample,
                    "model": response.model,
                    "strategy": response.search_strategy,
                    "answer": response.answer,
                    "contexts": [source.get("content", "") for source in response.sources],
                    "sources": response.sources,
                    "generation_latency": response.generation_latency,
                    "retrieval_latency": response.retrieval_latency,
                    "tokens": {
                        "prompt": usage.prompt_tokens if usage else 0,
                        "completion": usage.completion_tokens if usage else 0,
                        "total": usage.total_tokens if usage else 0,
                    },
                    "elapsed": round(time.monotonic() - started, 3),
                }
            )
        except Exception as exc:
            logger.exception("[%s] generation failed: %s", group_name, sample_id)
            outputs.append(
                {
                    **sample,
                    "model": config["model"],
                    "strategy": config["strategy"],
                    "answer": "",
                    "contexts": [],
                    "sources": [],
                    "error": str(exc),
                }
            )

    return outputs


def run(args: argparse.Namespace) -> Path:
    load_dotenv(args.env_file)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    qa_samples = load_qa_samples(args.qa_path, args.limit)
    groups = _build_groups(args)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("phase6_%Y%m%dT%H%M%S")
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pipeline = RAGPipeline(index_dir=args.index_dir)
    generated: dict[str, list[dict[str, Any]]] = {}

    for group_name, config in groups.items():
        generated[group_name] = _generate_group(pipeline, qa_samples, group_name, config)
        checkpoint = run_dir / f"{group_name.replace(':', '_')}_generations.json"
        checkpoint.write_text(json.dumps(generated[group_name], ensure_ascii=False, indent=2, default=str))
        logger.info("generation checkpoint saved: %s", checkpoint)

    generation_path = run_dir / "generations_all.json"
    generation_path.write_text(json.dumps(generated, ensure_ascii=False, indent=2, default=str))

    if args.skip_evaluation:
        logger.info("evaluation skipped; generations saved to %s", generation_path)
        return generation_path

    evaluator = RAGEvaluator(judge_model=args.judge_model)
    evaluated: dict[str, list[dict[str, Any]]] = {}
    for group_name, samples in generated.items():
        evaluated[group_name] = evaluator.evaluate_batch(samples, checkpoint_dir=run_dir / "checkpoints" / group_name)

    metadata = {
        "experiment": args.experiment,
        "models": args.models,
        "fixed_model": args.fixed_model,
        "strategies": args.strategies,
        "sample_count": len(qa_samples),
        "qa_path": str(args.qa_path),
    }
    return generate_report(evaluated, run_dir, run_id=run_id, metadata=metadata)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6 RAG evaluation experiments")
    parser.add_argument("--experiment", choices=["all", "model", "strategy", "rag"], default="all")
    parser.add_argument("--qa-path", type=Path, default=Path("data/eval/qa_pairs.json"))
    parser.add_argument("--index-dir", type=Path, default=Path("data/index"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/results/phase6"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--models", nargs="+", default=[m for m in _DEFAULT_MODELS if m in MODELS])
    parser.add_argument("--fixed-model", default="gpt-4o-mini")
    parser.add_argument("--strategy", default=SearchStrategy.HYBRID_RERANK.value)
    parser.add_argument("--strategies", nargs="+", default=_DEFAULT_STRATEGIES)
    parser.add_argument("--judge-model", default="vertex_ai/openai/gpt-4o-mini")
    parser.add_argument("--skip-evaluation", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    result_path = run(parse_args())
    print(f"Phase 6 output: {result_path}")
