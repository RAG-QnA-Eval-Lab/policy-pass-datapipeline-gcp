"""문서 청킹 — 정책 구조 인식 + 문장 경계 기반 분할."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import tiktoken

from src.ingestion.loader import Document

logger = logging.getLogger(__name__)

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


SECTION_PATTERNS = re.compile(
    r"^(정책명|요약|상세설명|신청자격|지원내용|신청방법|신청기간|주관부처|지역)[:：]",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Chunk:
    """청킹된 문서 조각."""

    content: str
    metadata: dict


def count_tokens(text: str) -> int:
    return len(_get_encoder().encode(text))


def chunk_documents(
    documents: list[Document],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """문서 리스트를 청크 리스트로 변환."""
    chunks: list[Chunk] = []
    for doc in documents:
        doc_chunks = _chunk_single(doc, chunk_size, chunk_overlap)
        chunks.extend(doc_chunks)
    logger.info("청킹 완료: %d문서 → %d청크", len(documents), len(chunks))
    return chunks


def _chunk_single(doc: Document, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    text = doc.content.strip()
    if not text:
        return []

    token_count = count_tokens(text)
    if token_count <= chunk_size:
        return [Chunk(content=text, metadata={**doc.metadata, "chunk_index": 0})]

    sentences = _split_sentences(text)
    return _merge_sentences(sentences, doc.metadata, chunk_size, chunk_overlap)


def _split_sentences(text: str) -> list[str]:
    """한국어 문장 분리. kss mecab → punct → regex 폴백 (pecab은 배치 처리에 너무 느림)."""
    try:
        import kss

        for backend in ("mecab", "punct"):
            try:
                return kss.split_sentences(text, backend=backend)
            except Exception:
                continue
    except ImportError:
        pass

    parts = re.split(r"(?<=[.!?。])\s+", text)
    result: list[str] = []
    for part in parts:
        stripped = part.strip()
        if stripped:
            result.append(stripped)
    return result if result else [text]


def _merge_sentences(
    sentences: list[str],
    base_metadata: dict,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """문장들을 토큰 제한 내에서 청크로 병합."""
    chunks: list[Chunk] = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = count_tokens(sentence)

        if sent_tokens > chunk_size:
            if current_sentences:
                chunks.append(_build_chunk(current_sentences, base_metadata, len(chunks)))
                current_sentences = []
                current_tokens = 0
            chunks.append(_build_chunk([sentence], base_metadata, len(chunks)))
            continue

        if current_tokens + sent_tokens > chunk_size and current_sentences:
            chunks.append(_build_chunk(current_sentences, base_metadata, len(chunks)))
            overlap_sentences = _get_overlap(current_sentences, chunk_overlap)
            current_sentences = overlap_sentences
            current_tokens = count_tokens(" ".join(current_sentences))

        current_sentences.append(sentence)
        current_tokens += sent_tokens

    if current_sentences:
        chunks.append(_build_chunk(current_sentences, base_metadata, len(chunks)))

    return chunks


def _get_overlap(sentences: list[str], overlap_tokens: int) -> list[str]:
    """이전 청크 끝에서 overlap_tokens 분량의 문장을 가져온다."""
    if overlap_tokens <= 0:
        return []
    overlap: list[str] = []
    tokens = 0
    for sent in reversed(sentences):
        tokens += count_tokens(sent)
        overlap.insert(0, sent)
        if tokens >= overlap_tokens:
            break
    return overlap


def _build_chunk(sentences: list[str], base_metadata: dict, index: int) -> Chunk:
    content = " ".join(sentences)
    return Chunk(content=content, metadata={**base_metadata, "chunk_index": index})
