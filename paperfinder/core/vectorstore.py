"""
vectorstore.py — the pluggable dense-search seam.

Contract:
  upsert(doc_id, vector)         store/replace a vector by canonical doc_id
  query(vector, k) -> [(id,s)]   nearest neighbours, BEST-FIRST, higher s = closer
  get(doc_id) -> vector | None   retrieve a stored vector
  delete(doc_id)                 remove a vector

The whole point of this file: PaperFinder.search() and the embed pass only ever
call this interface, so switching the dense backend is adding ONE class, never
touching core. `name` identifies the active backend.

Only BruteForceStore is exercised in this build. SqliteVecStore and QdrantStore
are faithful but UNTESTED here (the extension / service aren't present) — verify
them against your installed versions before relying on them.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Optional, Protocol


def cosine(u: list[float], v: list[float]) -> float:
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    return dot / (nu * nv) if nu and nv else 0.0


class VectorStore(Protocol):
    name: str
    def upsert(self, doc_id: str, vector: list[float]) -> None: ...
    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]: ...
    def get(self, doc_id: str) -> Optional[list[float]]: ...
    def delete(self, doc_id: str) -> None: ...


class BruteForceStore:
    """Vectors co-located in the same SQLite file; linear cosine scan.
    Single source of truth for vectors, persistent, zero extra dependencies.
    Fine at personal scale (ms over hundreds–low-thousands of docs). Default."""

    name = "bruteforce"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors (doc_id TEXT PRIMARY KEY, vector TEXT)")
        self.conn.commit()

    def upsert(self, doc_id: str, vector: list[float]) -> None:
        self.conn.execute(
            "INSERT INTO vectors(doc_id,vector) VALUES(?,?) "
            "ON CONFLICT(doc_id) DO UPDATE SET vector=excluded.vector",
            (doc_id, json.dumps(vector)))
        self.conn.commit()

    def get(self, doc_id: str) -> Optional[list[float]]:
        r = self.conn.execute("SELECT vector FROM vectors WHERE doc_id=?", (doc_id,)).fetchone()
        return json.loads(r["vector"]) if r else None

    def delete(self, doc_id: str) -> None:
        self.conn.execute("DELETE FROM vectors WHERE doc_id=?", (doc_id,))
        self.conn.commit()

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        scored = []
        for row in self.conn.execute("SELECT doc_id, vector FROM vectors"):
            scored.append((row["doc_id"], cosine(vector, json.loads(row["vector"]))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


class SqliteVecStore:
    """Swap target #1 — ANN via the sqlite-vec extension, SAME file/process.
    Near unplug/plug: same single-file model as BruteForceStore, just an index.
    UNTESTED here (extension not loaded). The vec0 schema and KNN syntax are
    version-sensitive — verify against your sqlite-vec version."""

    name = "sqlite-vec"

    def __init__(self, conn: sqlite3.Connection, dim: int):
        import sqlite_vec  # pip install sqlite-vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        self.conn = conn
        self.dim = dim
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs "
            f"USING vec0(doc_id TEXT PRIMARY KEY, embedding float[{dim}])")
        conn.commit()

    def upsert(self, doc_id: str, vector: list[float]) -> None:
        self.conn.execute(
            "INSERT INTO vec_docs(doc_id,embedding) VALUES(?,?) "
            "ON CONFLICT(doc_id) DO UPDATE SET embedding=excluded.embedding",
            (doc_id, json.dumps(vector)))
        self.conn.commit()

    def get(self, doc_id: str) -> Optional[list[float]]:
        r = self.conn.execute("SELECT embedding FROM vec_docs WHERE doc_id=?", (doc_id,)).fetchone()
        return json.loads(r["embedding"]) if r else None

    def delete(self, doc_id: str) -> None:
        self.conn.execute("DELETE FROM vec_docs WHERE doc_id=?", (doc_id,))
        self.conn.commit()

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            "SELECT doc_id, distance FROM vec_docs WHERE embedding MATCH ? "
            "ORDER BY distance LIMIT ?", (json.dumps(vector), k)).fetchall()
        return [(r["doc_id"], -float(r["distance"])) for r in rows]  # distance -> higher-better


def make_store(name: str, conn: sqlite3.Connection, dim: int) -> VectorStore:
    """Factory used by PaperFinder and the CLI. Switch backends by name."""
    if name == "bruteforce":
        return BruteForceStore(conn)
    if name == "sqlite-vec":
        return SqliteVecStore(conn, dim)
    if name == "qdrant":
        return QdrantStore(dim)
    raise ValueError(f"unknown vector store: {name!r} (bruteforce | sqlite-vec | qdrant)")
    """Swap target #2 — vectors in a SEPARATE Qdrant service.
    Unlike the two above this is NOT just a code swap: it's a separate process,
    so the finder now dual-stores (metadata + FTS in SQLite, vectors here) and
    you manage a service + connection. UNTESTED here — verify against your Qdrant."""

    name = "qdrant"

    def __init__(self, dim: int, url: str = "http://localhost:6333",
                 collection: str = "paperfinder"):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self.c = QdrantClient(url=url)
        self.collection = collection
        if not self.c.collection_exists(collection):
            self.c.create_collection(
                collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    @staticmethod
    def _pid(doc_id: str) -> int:
        import hashlib
        return int(hashlib.sha1(doc_id.encode()).hexdigest()[:15], 16)

    def upsert(self, doc_id: str, vector: list[float]) -> None:
        from qdrant_client.models import PointStruct
        self.c.upsert(self.collection, points=[
            PointStruct(id=self._pid(doc_id), vector=vector, payload={"doc_id": doc_id})])

    def get(self, doc_id: str) -> Optional[list[float]]:
        res = self.c.retrieve(self.collection, ids=[self._pid(doc_id)], with_vectors=True)
        return list(res[0].vector) if res else None

    def delete(self, doc_id: str) -> None:
        self.c.delete(self.collection, points_selector=[self._pid(doc_id)])

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        res = self.c.search(self.collection, query_vector=vector, limit=k, with_payload=True)
        return [(p.payload["doc_id"], float(p.score)) for p in res]  # cosine: higher-better
