"""
relationship_graph.py - v0 of the paper-finder relationship layer.

A human-authenticated knowledge graph over documents. Edges are first-class and
carry provenance, so a human-verified relationship is durable ground truth while
embeddings remain a regenerable cache.

Design commitments (from the agreed spec):
  - Edges key off the CANONICAL document identity (Drive id / DOI / path),
    never a transient index row id. Re-embedding never touches edges.
  - `source`  records how an edge originated:  human | inferred | imported
  - `status`  records its trust state:         candidate | authenticated | rejected
    A human authoring an edge -> source=human,  status=authenticated.
    An inferred candidate the human accepts -> status promoted to authenticated.
  - Edges are undirected and stored normalised (min,max) so a pair has one row.
  - Each edge carries the RELATING DESCRIPTORS (the "why"). Those descriptors are
    also the seeds of future idea-nodes - not built here, by design.

Stdlib only. The cosine-NN candidate generator is a v0 stand-in for the finder's
sqlite-vec nearest-neighbour search; swap `propose_candidates`'s scorer later.
"""

import json
import math
import sqlite3
import time
from typing import Iterable, Optional


def _now() -> float:
    return time.time()


def cosine(u: list[float], v: list[float]) -> float:
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    if nu == 0 or nv == 0:
        return 0.0
    return dot / (nu * nv)


class RelationshipGraph:
    def __init__(self, db_path: str = "relationships.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id          TEXT PRIMARY KEY,   -- canonical identity
                title           TEXT,
                source_url      TEXT,
                descriptors     TEXT,               -- JSON array of strings
                embedding       TEXT,               -- JSON array of floats (regenerable)
                embedding_model TEXT,
                updated_at      REAL
            );

            CREATE TABLE IF NOT EXISTS edges (
                edge_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                src_id      TEXT NOT NULL,           -- normalised so src_id < dst_id
                dst_id      TEXT NOT NULL,
                descriptors TEXT,                    -- JSON array: the relating "why"
                evidence    TEXT,                    -- JSON: {src_passage, dst_passage} for inferred edges
                source      TEXT NOT NULL,           -- human | inferred | imported
                status      TEXT NOT NULL,           -- candidate | authenticated | rejected
                confidence  REAL,                    -- candidate score (NULL for human)
                verified_by TEXT,
                verified_at REAL,
                created_at  REAL,
                UNIQUE (src_id, dst_id)
            );

            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges (src_id);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges (dst_id);
            CREATE INDEX IF NOT EXISTS idx_edges_status ON edges (status);
            """
        )
        try:  # migrate pre-existing DBs
            self.conn.execute("ALTER TABLE edges ADD COLUMN evidence TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    # ---- documents -------------------------------------------------------

    def add_document(
        self,
        doc_id: str,
        title: str,
        descriptors: Iterable[str],
        embedding: list[float],
        source_url: Optional[str] = None,
        embedding_model: str = "v0-stub",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO documents (doc_id, title, source_url, descriptors,
                                   embedding, embedding_model, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                title=excluded.title,
                source_url=excluded.source_url,
                descriptors=excluded.descriptors,
                embedding=excluded.embedding,
                embedding_model=excluded.embedding_model,
                updated_at=excluded.updated_at
            """,
            (doc_id, title, source_url, json.dumps(list(descriptors)),
             json.dumps(embedding), embedding_model, _now()),
        )
        self.conn.commit()

    def set_embedding(self, doc_id: str, embedding: list[float], model: str) -> None:
        """Overwrite only the embedding - simulates a re-embed pass. Edges untouched."""
        self.conn.execute(
            "UPDATE documents SET embedding=?, embedding_model=?, updated_at=? WHERE doc_id=?",
            (json.dumps(embedding), model, _now(), doc_id),
        )
        self.conn.commit()

    def get_document(self, doc_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return self._doc_row(row) if row else None

    def _doc_row(self, row: sqlite3.Row) -> dict:
        return {
            "doc_id": row["doc_id"],
            "title": row["title"],
            "source_url": row["source_url"],
            "descriptors": json.loads(row["descriptors"] or "[]"),
            "embedding": json.loads(row["embedding"] or "[]"),
            "embedding_model": row["embedding_model"],
        }

    def all_documents(self) -> list[dict]:
        return [self._doc_row(r) for r in self.conn.execute("SELECT * FROM documents")]

    # ---- edges -----------------------------------------------------------

    @staticmethod
    def _norm(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def get_edge(self, a: str, b: str) -> Optional[sqlite3.Row]:
        s, d = self._norm(a, b)
        return self.conn.execute(
            "SELECT * FROM edges WHERE src_id=? AND dst_id=?", (s, d)
        ).fetchone()

    def authenticate(
        self,
        a: str,
        b: str,
        descriptors: Iterable[str],
        verified_by: str,
    ) -> None:
        """Human action: assert (or promote) an authenticated relationship.

        If a candidate edge already exists for the pair it is promoted in place,
        preserving its origin `source` (e.g. 'inferred') while recording the human
        verification. A brand-new human assertion gets source='human'.
        """
        s, d = self._norm(a, b)
        existing = self.get_edge(s, d)
        desc = json.dumps(list(descriptors))
        if existing:
            self.conn.execute(
                """UPDATE edges SET status='authenticated', descriptors=?,
                       verified_by=?, verified_at=? WHERE src_id=? AND dst_id=?""",
                (desc, verified_by, _now(), s, d),
            )
        else:
            self.conn.execute(
                """INSERT INTO edges (src_id, dst_id, descriptors, source, status,
                                      confidence, verified_by, verified_at, created_at)
                   VALUES (?, ?, ?, 'human', 'authenticated', NULL, ?, ?, ?)""",
                (s, d, desc, verified_by, _now(), _now()),
            )
        self.conn.commit()

    def reject(self, a: str, b: str) -> None:
        s, d = self._norm(a, b)
        self.conn.execute(
            "UPDATE edges SET status='rejected', verified_at=? WHERE src_id=? AND dst_id=?",
            (_now(), s, d),
        )
        self.conn.commit()

    def _insert_candidate(self, a: str, b: str, descriptors: list[str], score: float,
                          evidence: Optional[dict] = None) -> None:
        """Persist an inferred candidate, but never overwrite a human verdict."""
        s, d = self._norm(a, b)
        existing = self.get_edge(s, d)
        if existing and existing["status"] in ("authenticated", "rejected"):
            return  # human has already ruled on this pair
        ev = json.dumps(evidence) if evidence else None
        self.conn.execute(
            """INSERT INTO edges (src_id, dst_id, descriptors, evidence, source, status,
                                  confidence, created_at)
               VALUES (?, ?, ?, ?, 'inferred', 'candidate', ?, ?)
               ON CONFLICT(src_id, dst_id) DO UPDATE SET
                   descriptors=excluded.descriptors, evidence=excluded.evidence,
                   confidence=excluded.confidence
               WHERE edges.status='candidate'""",
            (s, d, json.dumps(descriptors), ev, score, _now()),
        )
        self.conn.commit()

    def record_candidate(self, a: str, b: str, score: float,
                         descriptors: Optional[Iterable[str]] = None,
                         evidence: Optional[dict] = None) -> None:
        """Public entry point for an inferred candidate edge with passage evidence
        (the finder's chunk-neighbour engine calls this). Respects human verdicts."""
        self._insert_candidate(a, b, list(descriptors or []), score, evidence)

    # ---- candidate generation (v0 stand-in for finder's vector NN) -------

    def propose_candidates(
        self,
        doc_id: str,
        k: int = 5,
        min_sim: float = 0.3,
        persist: bool = True,
    ) -> list[dict]:
        """Suggest relationships for a document via embedding cosine similarity,
        with a small boost for shared descriptors. Returns ranked candidates and
        (optionally) persists them as status='candidate' for later verification.
        """
        target = self.get_document(doc_id)
        if not target:
            return []
        t_desc = set(target["descriptors"])
        scored = []
        for other in self.all_documents():
            if other["doc_id"] == doc_id:
                continue
            sim = cosine(target["embedding"], other["embedding"])
            shared = sorted(t_desc & set(other["descriptors"]))
            score = sim + 0.1 * len(shared)  # descriptor overlap nudges ranking
            if sim >= min_sim:
                scored.append({
                    "doc_id": other["doc_id"],
                    "title": other["title"],
                    "similarity": round(sim, 4),
                    "score": round(score, 4),
                    "shared_descriptors": shared,
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:k]
        if persist:
            for c in top:
                self._insert_candidate(doc_id, c["doc_id"], c["shared_descriptors"], c["score"])
        return top

    # ---- traversal -------------------------------------------------------

    def neighbors(self, doc_id: str, status: str = "authenticated") -> list[dict]:
        """Edges incident to doc_id, returning the other endpoint plus the 'why'."""
        rows = self.conn.execute(
            """SELECT * FROM edges
               WHERE (src_id=? OR dst_id=?) AND status=?""",
            (doc_id, doc_id, status),
        ).fetchall()
        out = []
        for r in rows:
            other = r["dst_id"] if r["src_id"] == doc_id else r["src_id"]
            od = self.get_document(other)
            out.append({
                "doc_id": other,
                "title": od["title"] if od else other,
                "descriptors": json.loads(r["descriptors"] or "[]"),
                "source": r["source"],
                "verified_by": r["verified_by"],
            })
        return out

    def edges_snapshot(self) -> list[tuple]:
        """Stable snapshot of (src,dst,status,source,verified_by) - for durability checks."""
        return [
            (r["src_id"], r["dst_id"], r["status"], r["source"], r["verified_by"])
            for r in self.conn.execute(
                "SELECT * FROM edges ORDER BY src_id, dst_id"
            )
        ]

    # ---- export for visualisation ---------------------------------------

    def export_graph(self, include_candidates: bool = True) -> dict:
        statuses = ("authenticated", "candidate") if include_candidates else ("authenticated",)
        nodes = [
            {"id": d["doc_id"], "title": d["title"], "descriptors": d["descriptors"],
             "source_url": d["source_url"]}
            for d in self.all_documents()
        ]
        edges = []
        for r in self.conn.execute(
            "SELECT * FROM edges WHERE status IN (%s)" % ",".join("?" * len(statuses)),
            statuses,
        ):
            edges.append({
                "src": r["src_id"],
                "dst": r["dst_id"],
                "status": r["status"],
                "source": r["source"],
                "descriptors": json.loads(r["descriptors"] or "[]"),
                "evidence": json.loads(r["evidence"]) if r["evidence"] else None,
                "verified_by": r["verified_by"],
                "confidence": r["confidence"],
            })
        return {"nodes": nodes, "edges": edges}
