"""수집 + 인덱싱 파이프라인 오케스트레이션.

사용법:
    # 인덱스 빌드 (로컬)
    python -m src.ingestion.pipeline --input data/policies/raw --output data/index

    # GCS 모드
    python -m src.ingestion.pipeline --gcs --bucket rag-qna-eval-data
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import faiss
import numpy as np

from config.settings import settings
from src.ingestion.chunker import Chunk, chunk_documents
from src.ingestion.embedder import embed_texts
from src.ingestion.loader import Document, load_directory
from src.ingestion.utils import save_policies_json as save_policies_json

logger = logging.getLogger(__name__)


def build_index_from_directory(
    input_dir: str | Path,
    output_dir: str | Path,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> dict:
    """디렉토리의 정책 파일 → 청킹 → 임베딩 → FAISS 인덱스 빌드.

    Returns:
        빌드 결과 요약 dict.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    logger.info("문서 로드: %s", input_dir)
    documents = load_directory(input_dir)
    if not documents:
        logger.warning("로드된 문서 없음")
        return {"documents": 0, "chunks": 0, "index_built": False}

    logger.info("청킹: %d문서 → chunk_size=%d, overlap=%d", len(documents), chunk_size, chunk_overlap)
    chunks = chunk_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        logger.warning("청크 생성 실패")
        return {"documents": len(documents), "chunks": 0, "index_built": False}

    logger.info("임베딩: %d청크", len(chunks))
    texts = [c.content for c in chunks]
    embeddings = embed_texts(texts)

    logger.info("FAISS 인덱스 빌드")
    index, metadata = _build_faiss_index(chunks, embeddings)

    index_path = output_dir / "faiss.index"
    metadata_path = output_dir / "metadata.json"

    faiss.write_index(index, str(index_path))
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)

    result = {
        "documents": len(documents),
        "chunks": len(chunks),
        "embedding_dim": len(embeddings[0]) if embeddings else 0,
        "index_path": str(index_path),
        "metadata_path": str(metadata_path),
        "index_built": True,
    }
    logger.info("인덱스 빌드 완료: %s", result)
    return result


def build_index_from_policies(
    policies: list[dict],
    output_dir: str | Path,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> dict:
    """Policy dict 리스트 → Document → 청킹 → 임베딩 → FAISS 인덱스."""
    documents: list[Document] = []
    for p in policies:
        content = p.get("raw_content", "") or p.get("description", "") or p.get("summary", "")
        if not content.strip():
            continue
        metadata = {
            "policy_id": p.get("policy_id", ""),
            "title": p.get("title", ""),
            "category": p.get("category", ""),
            "source": p.get("source_name", ""),
        }
        documents.append(Document(content=content.strip(), metadata=metadata))

    if not documents:
        return {"documents": 0, "chunks": 0, "index_built": False}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    chunks = chunk_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        return {"documents": len(documents), "chunks": 0, "index_built": False}

    texts = [c.content for c in chunks]
    embeddings = embed_texts(texts)

    index, metadata = _build_faiss_index(chunks, embeddings)

    index_path = output_dir / "faiss.index"
    metadata_path = output_dir / "metadata.json"
    faiss.write_index(index, str(index_path))
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)

    return {
        "documents": len(documents),
        "chunks": len(chunks),
        "embedding_dim": len(embeddings[0]),
        "index_path": str(index_path),
        "metadata_path": str(metadata_path),
        "index_built": True,
    }


def _build_faiss_index(
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> tuple[faiss.IndexFlatL2, list[dict]]:
    """FAISS IndexFlatL2 빌드 + 메타데이터 dict 리스트."""
    dim = len(embeddings[0])
    vectors = np.array(embeddings, dtype=np.float32)

    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    metadata = [
        {"content": chunk.content, **chunk.metadata}
        for chunk in chunks
    ]
    return index, metadata


def build_index_from_gcs(
    bucket: str | None = None,
    input_prefix: str = "policies/raw/",
    output_prefix: str = "index/",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> dict:
    """GCS에서 정책 로드 → 인덱스 빌드 → GCS 업로드."""
    from src.ingestion.gcs_client import GCSClient

    bucket = bucket or settings.gcs_bucket
    gcs = GCSClient(bucket)

    blobs = gcs.list_blobs(prefix=input_prefix)
    json_blobs = [b for b in blobs if b.endswith(".json")]
    latest_blobs = [b for b in json_blobs if b.endswith("/latest.json")]
    if latest_blobs:
        json_blobs = latest_blobs
    if not json_blobs:
        logger.error("GCS에 정책 파일 없음: gs://%s/%s*.json", bucket, input_prefix)
        return {"index_built": False}

    policies: list[dict] = []
    for blob_path in json_blobs:
        logger.info("GCS에서 정책 다운로드: gs://%s/%s", bucket, blob_path)
        data = gcs.download_json(blob_path)
        if isinstance(data, list):
            policies.extend(data)
        elif isinstance(data, dict) and "policies" in data:
            policies.extend(data["policies"])
    logger.info("총 %d건 정책 로드 (파일 %d개)", len(policies), len(json_blobs))

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        result = build_index_from_policies(policies, tmp, chunk_size, chunk_overlap)

        if not result.get("index_built"):
            logger.warning("인덱스 빌드 실패")
            return result

        gcs.upload_file(tmp / "faiss.index", f"{output_prefix}faiss.index")
        gcs.upload_file(tmp / "metadata.json", f"{output_prefix}metadata.json")

        result["gcs_index_path"] = f"gs://{bucket}/{output_prefix}faiss.index"
        result["gcs_metadata_path"] = f"gs://{bucket}/{output_prefix}metadata.json"
        logger.info("GCS 인덱스 업로드 완료: %s", result["gcs_index_path"])

        try:
            from src.ingestion.gcs_catalog import sync_gcs_objects_to_mongo

            synced = sync_gcs_objects_to_mongo(
                [f"{output_prefix}faiss.index", f"{output_prefix}metadata.json"],
                bucket=bucket,
                metadata_overrides={
                    f"{output_prefix}faiss.index": {
                        "asset_type": "index_artifact",
                        "record_count": result["chunks"],
                        "extra": {"documents": result["documents"], "chunks": result["chunks"]},
                    },
                    f"{output_prefix}metadata.json": {
                        "asset_type": "index_artifact",
                        "record_count": result["chunks"],
                        "extra": {"documents": result["documents"], "chunks": result["chunks"]},
                    },
                },
            )
            logger.info("GCS index catalog 동기화 완료: %d건", synced)
        except Exception:
            logger.exception("GCS index catalog 동기화 실패 — 인덱스 업로드는 완료됨")

    return result


if __name__ == "__main__":
    import argparse
    from pathlib import Path as _Path

    from dotenv import load_dotenv

    load_dotenv(_Path(__file__).parent.parent.parent / ".env")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="FAISS 인덱스 빌드")
    parser.add_argument("--input", default="data/policies/raw", help="입력 디렉토리 (로컬 모드)")
    parser.add_argument("--output", default="data/index", help="출력 디렉토리 (로컬 모드)")
    parser.add_argument("--gcs", action="store_true", help="GCS 모드 (입출력 모두 GCS)")
    parser.add_argument("--bucket", default=None, help="GCS 버킷명 (기본: settings.gcs_bucket)")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    args = parser.parse_args()

    if args.gcs:
        result = build_index_from_gcs(
            bucket=args.bucket,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
    else:
        result = build_index_from_directory(args.input, args.output, args.chunk_size, args.chunk_overlap)

    print(json.dumps(result, indent=2, ensure_ascii=False))
