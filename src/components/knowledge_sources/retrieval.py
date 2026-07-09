"""ChromaDB vector store: build, query, and metadata filtering.

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1):
store and query vectors in a persistent local ChromaDB directory
(``PersistentClient`` only, never client/server mode — README.md §3 hard rule,
offline-architecture §3.1). Provides the single source of truth for
``retrieve_context_chunks`` (engineering-principles §2.1.3).

Chunking logic is NOT re-implemented here — ``build_chroma_collection`` accepts
already-chunked :class:`src.ingestion.Chunk` objects (DRY,
engineering-principles §2.1.1). Embeddings are produced by an injected
:class:`src.embeddings.EmbeddingAdapter` (DIP, engineering-principles §1.5) so
deterministic CI tests can pass a mock embedder with no Ollama daemon.

Implemented in Phase 2 (tasks 2.3.2, 2.3.3).
"""
from __future__ import annotations

import gc
import shutil
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.client import SharedSystemClient
from chromadb.config import Settings

from src.components.knowledge_sources.models import Chunk, ContextChunk
from src.components.translation_pipeline.exceptions import (
    ChromaDBCorruptionError,
    RetrievalError,
)
from src.config import AppConfig, load_config
from src.embeddings import EmbeddingAdapter, Embedder, embed_text

# Default collection name (DATA_SPEC §4 / offline-architecture §3.1).
DEFAULT_COLLECTION: str = "iraqi_laws"

# ChromaDB add batch size (offline-architecture §1.4 / §3.3: flush every 64).
DEFAULT_ADD_BATCH: int = 64

# Telemetry disabled: the background telemetry thread holds file handles on
# Windows and blocks the atomic-rebuild rename (offline-architecture §3.4).
_TELEMETRY_SETTINGS: Settings = Settings(anonymized_telemetry=False)


def _hnsw_metadata(cfg: AppConfig) -> dict[str, Any]:
    """Build the HNSW collection metadata from config (offline-architecture §3.2).

    ``nomic-embed-text`` is cosine-normalized, so ``cosine`` space is correct.
    Smaller M / construction_ef suit a ~2k-vector corpus and reduce memory.
    """
    return {
        "hnsw:space": cfg.chroma.space,
        "hnsw:M": cfg.chroma.hnsw_M,
        "hnsw:construction_ef": cfg.chroma.construction_ef,
    }


def _chunk_metadata(chunk: Chunk) -> dict[str, Any]:
    """Project a :class:`Chunk` into the ChromaDB metadata dict.

    All values are ChromaDB-primitive (str/int). ``char_start`` / ``char_end``
    are kept so the application can cite the exact source span (DATA_SPEC §5).
    """
    return {
        "law": chunk.law,
        "article": chunk.article,
        "lang": chunk.lang,
        "law_slug": chunk.law_slug,
        "chunk_idx": chunk.chunk_idx,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
    }


def _translate_chroma_error(err: BaseException, persist_dir: Path) -> RetrievalError:
    """Map a ChromaDB exception to a domain :class:`RetrievalError` subclass."""
    if isinstance(err, (chromadb.errors.InvalidCollectionException,)):
        return ChromaDBCorruptionError(
            f"ChromaDB collection missing or invalid at {persist_dir}: {err}"
        )
    return ChromaDBCorruptionError(
        f"ChromaDB error at {persist_dir}: {err}"
    )


class ChromaStore:
    """Stateful adapter over a ChromaDB persistent collection (clean-code §2.4).

    Manages a single :class:`chromadb.PersistentClient` and the named
    collection. ``build`` ingests chunks (batched adds, atomic rebuild);
    ``query`` runs a similarity search with optional ``where`` metadata filter.
    """

    __slots__ = ("_persist_dir", "_collection_name", "_client", "_collection",
                 "_embedder", "_cfg")

    def __init__(
        self,
        persist_dir: Path,
        *,
        collection_name: str = DEFAULT_COLLECTION,
        embedder: EmbeddingAdapter | None = None,
        cfg: AppConfig | None = None,
    ) -> None:
        self._persist_dir: Path = persist_dir
        self._collection_name: str = collection_name
        self._cfg: AppConfig = cfg if cfg is not None else load_config()
        self._embedder: EmbeddingAdapter = (
            embedder if embedder is not None else Embedder()
        )
        self._client: chromadb.api.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    # -- build / ingest -----------------------------------------------------

    def build(self, chunks: list[Chunk]) -> int:
        """Atomically (re)build the collection at ``persist_dir`` from ``chunks``.

        Writes to a sibling temp directory, embeds chunk texts in bounded
        batches, adds them in batches of 64 (offline-architecture §3.3), then
        atomically swaps the temp dir into place (§3.4). On any error the temp
        dir is removed and the live store is left untouched (no partial state,
        DATA_SPEC §4). Returns the number of embeddings written.
        """
        temp_dir: Path = self._persist_dir.parent / f"{self._persist_dir.name}_new"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._write_collection(temp_dir, chunks)
        except Exception:
            # Release handles before removing (Windows: file in use).
            self._close_handles()
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        self._close_handles()
        self._atomic_swap(temp_dir)
        return len(chunks)

    def _write_collection(self, target_dir: Path, chunks: list[Chunk]) -> None:
        """Create the collection in ``target_dir`` and add all chunks batched."""
        client = chromadb.PersistentClient(
            path=str(target_dir), settings=_TELEMETRY_SETTINGS
        )
        collection = client.create_collection(
            name=self._collection_name,
            metadata=_hnsw_metadata(self._cfg),
        )
        self._client = client
        self._collection = collection

        if not chunks:
            return

        # Embed all chunk texts in bounded batches (offline-architecture §1.4).
        texts: list[str] = [c.text for c in chunks]
        embeddings: list[list[float]] = self._embedder.embed_batch(
            texts, batch_size=self._cfg.embedding_batch_size
        )

        # Add in batches of 64 to minimize persistence fsync count (§3.3).
        for start in range(0, len(chunks), DEFAULT_ADD_BATCH):
            end: int = start + DEFAULT_ADD_BATCH
            batch_chunks: list[Chunk] = chunks[start:end]
            collection.add(
                ids=[c.chunk_id for c in batch_chunks],
                documents=[c.text for c in batch_chunks],
                embeddings=embeddings[start:end],
                metadatas=[_chunk_metadata(c) for c in batch_chunks],
            )

    def _atomic_swap(self, temp_dir: Path) -> None:
        """Swap ``temp_dir`` into ``persist_dir`` (offline-architecture §3.4).

        Windows-safe: handles are already released by ``_close_handles``; the
        existing store is renamed to a backup before the temp dir is renamed
        into place, then the backup is removed.
        """
        backup: Path = self._persist_dir.parent / f"{self._persist_dir.name}_old"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if self._persist_dir.exists():
            self._persist_dir.rename(backup)
        temp_dir.rename(self._persist_dir)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    def _close_handles(self) -> None:
        """Release ChromaDB client/collection handles (critical on Windows).

        ChromaDB caches the system/client by path (``SharedSystemClient``);
        that cache plus the telemetry thread keep SQLite file handles open and
        block the atomic-rebuild ``rename`` on Windows (offline-architecture
        §3.4). Clearing the system cache after dropping our references and
        running a collection releases those handles.
        """
        self._collection = None
        self._client = None
        gc.collect()
        try:
            SharedSystemClient.clear_system_cache()
        except Exception:  # cache already empty / not initialized
            pass
        gc.collect()

    # -- query --------------------------------------------------------------

    def add_chunks(self, chunks: list[Chunk]) -> int:
        """Add ``chunks`` to the existing collection (incremental, non-destructive).

        Unlike :meth:`build`, this opens the existing collection and adds chunks
        without dropping what's already there. Used by external corpus importers
        (e.g. MultiUN RAG import) to augment the live store. Embeds in bounded
        batches and adds in batches of 64 (same as ``build``). Returns the number
        of embeddings added.
        """
        if not chunks:
            return 0
        collection = self._open()
        texts: list[str] = [c.text for c in chunks]
        embeddings: list[list[float]] = self._embedder.embed_batch(
            texts, batch_size=self._cfg.embedding_batch_size
        )
        for start in range(0, len(chunks), DEFAULT_ADD_BATCH):
            end: int = start + DEFAULT_ADD_BATCH
            batch_chunks: list[Chunk] = chunks[start:end]
            collection.add(
                ids=[c.chunk_id for c in batch_chunks],
                documents=[c.text for c in batch_chunks],
                embeddings=embeddings[start:end],
                metadatas=[_chunk_metadata(c) for c in batch_chunks],
            )
        return len(chunks)

    def _open(self) -> chromadb.Collection:
        """Open the existing collection at ``persist_dir`` (lazy, cached)."""
        if self._collection is not None:
            return self._collection
        if not self._persist_dir.is_dir():
            raise ChromaDBCorruptionError(
                f"ChromaDB directory not found: {self._persist_dir} "
                f"(run `python -m src.ingestion --rebuild`)"
            )
        try:
            client = chromadb.PersistentClient(
                path=str(self._persist_dir), settings=_TELEMETRY_SETTINGS
            )
            collection = client.get_collection(name=self._collection_name)
        except Exception as err:
            raise _translate_chroma_error(err, self._persist_dir) from err
        self._client = client
        self._collection = collection
        return collection

    def query(
        self,
        query_text: str,
        n_results: int = 8,
        where: dict[str, Any] | None = None,
    ) -> list[ContextChunk]:
        """Return the top-``n_results`` chunks most similar to ``query_text``.

        ``where`` is a ChromaDB metadata filter (e.g. ``{"law": "Civil Code"}``)
        applied before the HNSW search (offline-architecture §3.5). An empty
        query returns an empty list without contacting the engine. Only
        documents, metadatas, and distances are requested — never embeddings
        (§3.5).
        """
        if not query_text.strip():
            return []
        collection = self._open()
        query_embedding: list[float] = self._embedder.embed(query_text)
        try:
            raw = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as err:
            raise _translate_chroma_error(err, self._persist_dir) from err
        return _parse_query_result(raw)

    def count(self) -> int:
        """Return the number of items in the collection (0 if unopenable)."""
        try:
            return self._open().count()
        except RetrievalError:
            return 0


def _parse_query_result(raw: dict[str, Any]) -> list[ContextChunk]:
    """Flatten a single-query ChromaDB result into :class:`ContextChunk` list.

    ChromaDB returns one row of results per query embedding; we issue exactly
    one query, so the outer list has one element.
    """
    ids_rows: list[list[str]] = raw.get("ids", [[]])
    docs_rows: list[list[str]] = raw.get("documents", [[]])
    meta_rows: list[list[dict[str, Any]]] = raw.get("metadatas", [[]])
    dist_rows: list[list[float]] = raw.get("distances", [[]])

    if not ids_rows:
        return []
    ids: list[str] = ids_rows[0]
    docs: list[str] = docs_rows[0] if docs_rows else []
    metas: list[dict[str, Any]] = meta_rows[0] if meta_rows else []
    dists: list[float] = dist_rows[0] if dist_rows else []

    results: list[ContextChunk] = []
    for idx, chunk_id in enumerate(ids):
        meta: dict[str, Any] = metas[idx] if idx < len(metas) else {}
        results.append(
            ContextChunk(
                chunk_id=chunk_id,
                text=docs[idx] if idx < len(docs) else "",
                law=str(meta.get("law", "")),
                article=str(meta.get("article", "")),
                lang=str(meta.get("lang", "")),
                law_slug=str(meta.get("law_slug", "")),
                chunk_idx=int(meta.get("chunk_idx", 0)),
                char_start=int(meta.get("char_start", 0)),
                char_end=int(meta.get("char_end", 0)),
                distance=float(dists[idx]) if idx < len(dists) else 0.0,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Module-level convenience functions (TODO 2.3.2 signatures)
# ---------------------------------------------------------------------------


def _default_persist_dir(cfg: AppConfig | None = None) -> Path:
    """Resolve the default ChromaDB persist dir from config (project-relative)."""
    resolved_cfg: AppConfig = cfg if cfg is not None else load_config()
    project_root: Path = Path(__file__).resolve().parent.parent
    return project_root / resolved_cfg.paths.chroma_dir


def build_chroma_collection(
    chunks: list[Chunk],
    persist_dir: str | Path,
    *,
    embedder: EmbeddingAdapter | None = None,
    collection_name: str = DEFAULT_COLLECTION,
    cfg: AppConfig | None = None,
) -> int:
    """Build (atomically rebuild) the ChromaDB collection at ``persist_dir``.

    Embeds each chunk text with ``embedder`` (default: the real Ollama
    :class:`Embedder`) and adds them in batches of 64. The write is atomic
    (offline-architecture §3.4): a sibling temp dir is populated, then swapped
    into place, so a failure never leaves a partial store. Returns the number
    of embeddings written.
    """
    store = ChromaStore(
        persist_dir=Path(persist_dir),
        collection_name=collection_name,
        embedder=embedder,
        cfg=cfg,
    )
    return store.build(chunks)


def add_chunks_to_collection(
    chunks: list[Chunk],
    persist_dir: str | Path,
    *,
    embedder: EmbeddingAdapter | None = None,
    collection_name: str = DEFAULT_COLLECTION,
    cfg: AppConfig | None = None,
) -> int:
    """Add ``chunks`` to an existing ChromaDB collection (incremental).

    Thin wrapper around :meth:`ChromaStore.add_chunks` — the incremental,
    non-destructive counterpart to :func:`build_chroma_collection`. Used by
    external corpus importers (e.g. MultiUN RAG import).
    """
    store = ChromaStore(
        persist_dir=Path(persist_dir),
        collection_name=collection_name,
        embedder=embedder,
        cfg=cfg,
    )
    return store.add_chunks(chunks)


def query_chroma(
    query_text: str,
    n_results: int = 8,
    where: dict[str, Any] | None = None,
    *,
    persist_dir: str | Path | None = None,
    embedder: EmbeddingAdapter | None = None,
    collection_name: str = DEFAULT_COLLECTION,
    cfg: AppConfig | None = None,
) -> list[ContextChunk]:
    """Query the ChromaDB collection for the top-``n_results`` similar chunks.

    ``persist_dir`` defaults to the config ``chroma_dir`` (project-relative).
    ``embedder`` defaults to the real Ollama :class:`Embedder`; tests inject a
    deterministic mock. ``where`` is an optional ChromaDB metadata filter.
    An empty query returns an empty list.
    """
    resolved_dir: Path = (
        Path(persist_dir) if persist_dir is not None else _default_persist_dir(cfg)
    )
    store = ChromaStore(
        persist_dir=resolved_dir,
        collection_name=collection_name,
        embedder=embedder,
        cfg=cfg,
    )
    return store.query(query_text, n_results=n_results, where=where)


def retrieve_context_chunks(
    query_text: str,
    n_results: int | None = None,
    where: dict[str, Any] | None = None,
    *,
    persist_dir: str | Path | None = None,
    embedder: EmbeddingAdapter | None = None,
    cfg: AppConfig | None = None,
) -> list[ContextChunk]:
    """Single source of truth for context retrieval (engineering-principles §2.1.3).

    Thin wrapper around :func:`query_chroma` that defaults ``n_results`` to the
    config ``top_k``. All retrieval in nodes must go through this function.
    """
    resolved_cfg: AppConfig = cfg if cfg is not None else load_config()
    return query_chroma(
        query_text,
        n_results=resolved_cfg.top_k if n_results is None else n_results,
        where=where,
        persist_dir=persist_dir,
        embedder=embedder,
        cfg=resolved_cfg,
    )
