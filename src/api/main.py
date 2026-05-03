"""FastAPI 애플리케이션 — lifespan 기반 초기화."""

from __future__ import annotations

import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # noqa: E402 — macOS FAISS + PyTorch OpenMP 충돌 방지
os.environ.setdefault("OMP_NUM_THREADS", "1")  # noqa: E402
os.environ.setdefault("MKL_NUM_THREADS", "1")  # noqa: E402
os.environ.setdefault("MKL_THREADING_LAYER", "sequential")  # noqa: E402 — MKL이 OpenMP 대신 순차 실행
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # noqa: E402
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")  # noqa: E402 — macOS Accelerate
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")  # noqa: E402

# Claude Code가 자체 프록시용 ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY를 프로세스 환경에  # noqa: E402
# 주입하는데, LiteLLM이 이걸 읽으면 실제 Anthropic API 대신 프록시로 라우팅됨.  # noqa: E402
# api.anthropic.com이 아닌 BASE_URL이 감지되면 둘 다 제거한다.  # noqa: E402
_anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "")  # noqa: E402
if _anthropic_base and "api.anthropic.com" not in _anthropic_base:  # noqa: E402
    os.environ.pop("ANTHROPIC_BASE_URL", None)  # noqa: E402
    os.environ.pop("ANTHROPIC_API_KEY", None)  # noqa: E402

import logging  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import AsyncIterator  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

from src.api.logging_config import setup_json_logging  # noqa: E402

setup_json_logging()  # Cloud Run stdout → Cloud Logging 구조화 JSON

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from config.settings import settings  # noqa: E402
from src.api.cloud_run import check_gcs_access, ensure_index_files, get_index_last_updated  # noqa: E402
from src.api.errors import generic_exception_handler  # noqa: E402
from src.api.middleware import RequestLoggingMiddleware  # noqa: E402
from src.api.rate_limit import limiter  # noqa: E402
from src.api.routes import evaluate, generate, models, policies, search  # noqa: E402
from src.api.schemas import DataPipelineStatus, HealthResponse, SourceStatus  # noqa: E402

logger = logging.getLogger(__name__)

_APP_VERSION = "0.2.0"
_PIPELINE_STATUS_TTL = 60
_pipeline_status_cache: dict | None = None
_pipeline_status_ts: float = 0.0
_pipeline_status_lock = threading.Lock()
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INDEX_DIR = Path(os.getenv("INDEX_DIR", str(_REPO_ROOT / "data" / "index")))


def _redact_mongo_target(uri: str) -> str:
    if not uri:
        return "<unset>"
    parsed = urlsplit(uri)
    host = parsed.hostname or "<unknown>"
    database = parsed.path.lstrip("/") or "<default>"
    return f"{host}/{database}"


def _build_cors_origins() -> list[str]:
    origins: list[str] = []
    if settings.api_base_url:
        origins.append(settings.api_base_url)
    if settings.environment != "production":
        origins.append("http://localhost:8501")
        origins.append("http://localhost:8000")
    extra = os.getenv("ALLOWED_ORIGINS", "")
    if extra:
        origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.boot_time = time.monotonic()

    from config.env_bootstrap import apply_litellm_env

    apply_litellm_env()

    try:
        from src.generation.pipeline import RAGPipeline

        app.state.index_status = ensure_index_files(_INDEX_DIR)
        logger.info("Loading FAISS index from %s ...", _INDEX_DIR)
        app.state.rag_pipeline = RAGPipeline(index_dir=_INDEX_DIR)
        doc_count = app.state.rag_pipeline.retrieval.index.ntotal
        logger.info("FAISS loaded: %d vectors", doc_count)
    except Exception:
        logger.exception("FAISS index load failed — search/generate endpoints will return 503")
        app.state.rag_pipeline = None
        app.state.index_status = getattr(app.state, "index_status", {"available": False})

    mongo = None
    try:
        from src.ingestion.mongo_client import PolicyMetadataStore

        mongo = PolicyMetadataStore()
        mongo.client.admin.command("ping")
        mongo.ensure_indexes()
        app.state.mongo = mongo
        logger.info("MongoDB connected: %s", _redact_mongo_target(settings.mongodb_uri))
    except Exception:
        logger.warning("MongoDB unavailable — policies endpoints disabled")
        app.state.mongo = None

    yield

    if mongo:
        mongo.close()
        logger.info("MongoDB connection closed")


app = FastAPI(
    title="RAG Youth Policy API",
    version=_APP_VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(search.router)
app.include_router(generate.router)
app.include_router(policies.router)
app.include_router(models.router)
app.include_router(evaluate.router)


@app.get("/health", tags=["health"])
def health() -> JSONResponse:
    pipeline = getattr(app.state, "rag_pipeline", None)
    faiss_loaded = pipeline is not None
    doc_count = pipeline.retrieval.index.ntotal if pipeline is not None else 0
    faiss_dim = pipeline.retrieval.index.d if pipeline is not None else None

    mongo = getattr(app.state, "mongo", None)
    mongo_ok = False
    data_pipeline = None
    if mongo:
        try:
            mongo.client.admin.command("ping", maxTimeMS=500)
            mongo_ok = True
            try:
                global _pipeline_status_cache, _pipeline_status_ts  # noqa: PLW0603
                now = time.monotonic()
                with _pipeline_status_lock:
                    if _pipeline_status_cache is None or (now - _pipeline_status_ts) > _PIPELINE_STATUS_TTL:
                        raw = mongo.get_data_pipeline_status()
                        _pipeline_status_cache = DataPipelineStatus(
                            last_ingestion=raw.get("last_ingestion"),
                            total_policies=raw.get("total_policies", 0),
                            index_sync_status=raw.get("index_sync_status", "unknown"),
                            sources={k: SourceStatus(**v) for k, v in raw.get("sources", {}).items()},
                        )
                        _pipeline_status_ts = now
                    data_pipeline = _pipeline_status_cache
            except Exception as exc:
                logger.debug("Data pipeline status lookup failed: %s", exc)
        except Exception as exc:
            logger.debug("MongoDB health check failed: %s", exc)

    uptime = round(time.monotonic() - getattr(app.state, "boot_time", time.monotonic()), 1)
    gcs_ok, gcs_error = check_gcs_access()
    if gcs_error is not None:
        logger.debug("GCS health check failed: %s", gcs_error)

    status = "ok" if faiss_loaded else "degraded"
    status_code = 200 if faiss_loaded else 503

    body = HealthResponse(
        status=status,
        faiss_loaded=faiss_loaded,
        faiss_doc_count=doc_count,
        faiss_dim=faiss_dim,
        faiss_last_updated=get_index_last_updated(_INDEX_DIR),
        mongodb_connected=mongo_ok,
        gcs_accessible=gcs_ok,
        uptime_seconds=uptime,
        version=_APP_VERSION,
        data_pipeline=data_pipeline,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())
