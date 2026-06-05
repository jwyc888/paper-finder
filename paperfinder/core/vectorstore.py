"""
vectorstore.py — the pluggable dense-search seam.

Contract (keyed by an opaque id; the finder keys it by CHUNK id):
  upsert(id, vector)         store/replace a vector by id
  query(vector, k) -> [(id,s)]   nearest neighbours, BEST-FIRST, higher s = closer
  get(id) -> vector | None   retrieve a stored vector
  delete(id)                 remove a vector

PaperFinder.search() and the embed pass only ever call this interface, so switching
the dense backend is one class, never touching core. `name` identifies the backend.

BruteForceStore is the default (single SQLite file, zero deps). QdrantStore targets a
separate Qdrant service and is verified here via qdrant-client's in-memory mode;
validate the network path against your running instance. SqliteVecStore is faithful
but untested (extension not present).
"""

from __future__ import annotations

import json
import math
import os
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
    def upsert(self, id: str, vector: list[float]) -> None: ...
    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]: ...
    def get(self, id: str) -> Optional[list[float]]: ...
    def delete(self, id: str) -> None: ...


class BruteForceStore:
    """Vectors co-located in the same SQLite file; linear cosine scan. Zero extra
    dependencies, single source of truth. Fine at personal scale; for tens of
    thousands of chunk vectors move to Qdrant."""

    name = "bruteforce"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, vector TEXT)")
        self.conn.commit()

    def upsert(self, id: str, vector: list[float]) -> None:
        self.conn.execute(
            "INSERT INTO vectors(id,vector) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET vector=excluded.vector",
            (id, json.dumps(vector)))
        self.conn.commit()

    def get(self, id: str) -> Optional[list[float]]:
        r = self.conn.execute("SELECT vector FROM vectors WHERE id=?", (id,)).fetchone()
        return json.loads(r["vector"]) if r else None

    def delete(self, id: str) -> None:
        self.conn.execute("DELETE FROM vectors WHERE id=?", (id,))
        self.conn.commit()

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        scored = []
        for row in self.conn.execute("SELECT id, vector FROM vectors"):
            scored.append((row["id"], cosine(vector, json.loads(row["vector"]))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


class SqliteVecStore:
    """ANN via the sqlite-vec extension, SAME file/process. UNTESTED here; the vec0
    schema and KNN syntax are version-sensitive — verify against your sqlite-vec."""

    name = "sqlite-vec"

    def __init__(self, conn: sqlite3.Connection, dim: int):
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        self.conn = conn
        self.dim = dim
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs "
            f"USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}])")
        conn.commit()

    def upsert(self, id: str, vector: list[float]) -> None:
        self.conn.execute(
            "INSERT INTO vec_docs(id,embedding) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET embedding=excluded.embedding",
            (id, json.dumps(vector)))
        self.conn.commit()

    def get(self, id: str) -> Optional[list[float]]:
        r = self.conn.execute("SELECT embedding FROM vec_docs WHERE id=?", (id,)).fetchone()
        return json.loads(r["embedding"]) if r else None

    def delete(self, id: str) -> None:
        self.conn.execute("DELETE FROM vec_docs WHERE id=?", (id,))
        self.conn.commit()

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            "SELECT id, distance FROM vec_docs WHERE embedding MATCH ? "
            "ORDER BY distance LIMIT ?", (json.dumps(vector), k)).fetchall()
        return [(r["id"], -float(r["distance"])) for r in rows]  # distance -> higher-better


class QdrantStore:
    """Vectors in a separate Qdrant service. NOT just a code swap: the finder
    dual-stores (chunk text + FTS in SQLite, vectors here), and you run/maintain the
    service. Each id (a chunk id) becomes one point; the id is carried in the payload
    so queries return it. Connects to PAPERFINDER_QDRANT_URL (default localhost:6533)
    and PAPERFINDER_QDRANT_COLLECTION (default paperfinder_chunks). Pass location=
    ':memory:' for an in-process test instance."""

    name = "qdrant"

    def __init__(self, dim: int, url: Optional[str] = None,
                 collection: Optional[str] = None, location: Optional[str] = None):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        url = url or os.environ.get("PAPERFINDER_QDRANT_URL", "http://localhost:6533")
        collection = collection or os.environ.get(
            "PAPERFINDER_QDRANT_COLLECTION", "paperfinder_chunks")
        self.c = QdrantClient(location=location) if location else QdrantClient(url=url)
        self.collection = collection
        if not self.c.collection_exists(collection):
            self.c.create_collection(
                collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    @staticmethod
    def _pid(key: str) -> str:
        import uuid
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))   # deterministic, valid point id

    def upsert(self, id: str, vector: list[float]) -> None:
        from qdrant_client.models import PointStruct
        self.c.upsert(self.collection, points=[
            PointStruct(id=self._pid(id), vector=list(vector), payload={"key": id})])

    def get(self, id: str) -> Optional[list[float]]:
        res = self.c.retrieve(self.collection, ids=[self._pid(id)], with_vectors=True)
        return list(res[0].vector) if res else None

    def delete(self, id: str) -> None:
        from qdrant_client.models import PointIdsList
        self.c.delete(self.collection, points_selector=PointIdsList(points=[self._pid(id)]))

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        try:  # qdrant-client >= 1.10
            pts = self.c.query_points(
                self.collection, query=list(vector), limit=k, with_payload=True).points
        except AttributeError:  # older client
            pts = self.c.search(
                self.collection, query_vector=list(vector), limit=k, with_payload=True)
        return [(p.payload["key"], float(p.score)) for p in pts]  # cosine: higher-better


def make_store(name: str, conn: sqlite3.Connection, dim: int) -> VectorStore:
    """Factory used by PaperFinder and the CLI. Switch backends by name."""
    if name == "bruteforce":
        return BruteForceStore(conn)
    if name == "sqlite-vec":
        return SqliteVecStore(conn, dim)
    if name == "qdrant":
        return QdrantStore(dim)
    raise ValueError(f"unknown vector store: {name!r} (bruteforce | sqlite-vec | qdrant)")
