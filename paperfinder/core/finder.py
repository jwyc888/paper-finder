"""
paperfinder.py — Tier A core.

Pipeline:  capture -> queue -> metadata pass (instant) -> embed pass (background)
           -> hybrid index (FTS5 keyword + dense vectors, fused by RRF).

Staged ingestion is the point:
  * metadata pass  = cheap. Title + first-page text indexed to FTS5 immediately,
                     so a just-dropped paper is keyword-findable within seconds.
  * embed pass     = heavier. Full-text parse + embedding, run in the background;
                     adds semantic recall and full-text keyword reach.

doc_id is the CANONICAL identity, shared with the relationship layer. Embeddings
live in their own column and are a regenerable cache — re-embedding never touches
identity or any verified relationship.

Dense search here is brute-force cosine (fine at personal scale, zero extra deps);
swap in sqlite-vec when the corpus grows. The embedder defaults to a dependency-free
hashing embedder; point it at bge-small / PubMedBERT for real semantic recall.
"""

from __future__ import annotations

import io
import json
import math
import re
import sqlite3
import time
from typing import Optional

import pypdf

from paperfinder.core.capture import CaptureSource, DocumentRef
from paperfinder.core.vectorstore import BruteForceStore, VectorStore

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class Parser:
    @staticmethod
    def quick(ref: DocumentRef, data: bytes) -> dict:
        """Cheap metadata-pass extraction: title, first-page text, doi."""
        if ref.kind == "pdf":
            try:
                reader = pypdf.PdfReader(io.BytesIO(data))
                page0 = (reader.pages[0].extract_text() or "") if reader.pages else ""
                meta_title = (reader.metadata.title if reader.metadata else None) or ""
            except Exception:
                page0, meta_title = "", ""
            title = meta_title.strip() or _first_line(page0) or ref.name
            return {"title": title, "first_text": page0[:2000],
                    "doi": _doi(page0), "kind": "pdf"}
        if ref.kind in ("text",):
            txt = _decode(data)
            return {"title": _first_line(txt) or ref.name,
                    "first_text": txt[:2000], "doi": _doi(txt), "kind": "text"}
        # url / other: nothing to parse cheaply
        return {"title": ref.name, "first_text": "", "doi": None, "kind": ref.kind}

    @staticmethod
    def full(ref: DocumentRef, data: bytes) -> str:
        """Embed-pass extraction: full text."""
        if ref.kind == "pdf":
            try:
                reader = pypdf.PdfReader(io.BytesIO(data))
                return "\n".join((p.extract_text() or "") for p in reader.pages)
            except Exception:
                return ""
        if ref.kind == "text":
            return _decode(data)
        return ""


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8", "replace")
    except Exception:
        return ""


def _first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if len(s) > 8:
            return s[:160]
    return ""


def _doi(text: str) -> Optional[str]:
    m = DOI_RE.search(text or "")
    return m.group(0) if m else None


# --------------------------------------------------------------------------- #
# Embedding (pluggable; default is dependency-free)
# --------------------------------------------------------------------------- #
class HashingEmbedder:
    """Deterministic hashed bag-of-words, L2-normalised. A stand-in so the
    pipeline runs with zero model downloads. Lexical, not semantic — swap for a
    real model on the Mac for genuine recall."""
    model_name = "hashing-v0"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", (text or "").lower()):
            vec[hash(tok) % self.dim] += 1.0
        n = math.sqrt(sum(v * v for v in vec))
        return [v / n for v in vec] if n else vec


# To use real semantic embeddings on the Mac, select this via PAPERFINDER_EMBEDDER=st.
class STEmbedder:
    """Real semantic embeddings via sentence-transformers (e.g. bge-small).
    Lazy import so the package is only required if you actually select it.
    UNTESTED in this sandbox (no model downloaded) — verify on the Mac."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer
        self.model_name = model
        self._m = SentenceTransformer(model)

    def embed(self, text: str) -> list[float]:
        return self._m.encode(text or "", normalize_embeddings=True).tolist()


def cosine(u: list[float], v: list[float]) -> float:
    # kept for backwards-compat imports; dense scoring now lives in the VectorStore.
    from paperfinder.core.vectorstore import cosine as _c
    return _c(u, v)


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
class PaperFinder:
    def __init__(self, db_path: str = "paperfinder.db", embedder=None,
                 vector_store=None, vector_store_name: str = "bruteforce"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.embedder = embedder or HashingEmbedder()
        self._init_schema()
        # the pluggable dense backend — pass an instance, or name one to build
        if vector_store is not None:
            self.store: VectorStore = vector_store
        else:
            from paperfinder.core.vectorstore import make_store
            dim = len(self.embedder.embed("dimension probe"))
            self.store = make_store(vector_store_name, self.conn, dim)

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                title TEXT, source_url TEXT, kind TEXT, doi TEXT,
                descriptors TEXT,                 -- JSON; filled by humans/LLM later
                first_text TEXT, full_text TEXT,
                embedding_model TEXT,
                modified REAL, indexed_at REAL, embedded_at REAL,
                archived INTEGER DEFAULT 0
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
                USING fts5(doc_id UNINDEXED, content);
            CREATE TABLE IF NOT EXISTS jobs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT, ref TEXT, stage TEXT, status TEXT, created_at REAL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(stage, status);
            """
        )
        try:  # migrate pre-existing DBs
            self.conn.execute("ALTER TABLE documents ADD COLUMN archived INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    # ---- checkpoint ------------------------------------------------------
    def _get_meta(self, key: str) -> Optional[str]:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def _set_meta(self, key: str, value: Optional[str]) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    # ---- capture ---------------------------------------------------------
    def run_capture(self, source: CaptureSource, source_key: str = "default") -> int:
        ckpt = self._get_meta(f"ckpt:{source_key}")
        refs, new_ckpt = source.poll(ckpt)
        for ref in refs:
            self.conn.execute(
                "INSERT INTO jobs(doc_id,ref,stage,status,created_at) "
                "VALUES(?,?,?,?,?)",
                (ref.doc_id, _ref_json(ref), "metadata", "pending", time.time()))
        self._set_meta(f"ckpt:{source_key}", new_ckpt)
        self.conn.commit()
        # stash refs so passes can fetch bytes without re-polling
        self._refs = getattr(self, "_refs", {})
        for ref in refs:
            self._refs[ref.doc_id] = ref
        return len(refs)

    def run_backfill(self, source, source_key: str = "default",
                     reconcile: bool = False) -> dict:
        """One-time, in-place backfill. crawl() if available (Drive, follows
        aliases), else a full local re-scan. Enqueues only new/returning docs.
        With reconcile=True, papers no longer reachable get archived (see reconcile)."""
        self._refs = getattr(self, "_refs", {})
        if hasattr(source, "crawl"):
            refs = source.crawl()
            prefix, new_ckpt = "gdrive:", source.start_checkpoint()
        else:
            self._set_meta(f"ckpt:{source_key}", None)        # force full re-scan
            refs, new_ckpt = source.poll(None)
            prefix = "local:"
        reachable = set()
        enqueued = 0
        for ref in refs:
            self._refs[ref.doc_id] = ref
            reachable.add(ref.doc_id)
            existing = self.get_document(ref.doc_id)
            if existing and not existing["archived"]:
                continue                                       # already in scope; poll handles edits
            self.conn.execute(
                "INSERT INTO jobs(doc_id,ref,stage,status,created_at) VALUES(?,?,?,?,?)",
                (ref.doc_id, _ref_json(ref), "metadata", "pending", time.time()))
            enqueued += 1
        self._set_meta(f"ckpt:{source_key}", new_ckpt)
        self.conn.commit()
        archived = self.reconcile(reachable, prefix) if reconcile else 0
        return {"reachable": len(reachable), "enqueued": enqueued, "archived": archived}

    def reconcile(self, reachable_ids, source_prefix: str) -> int:
        """Soft-archive indexed docs from this source that are no longer reachable
        (a paper deleted, or a folder/alias removed from scope). Only the LOCAL
        index is touched — never the source. Archived docs drop out of search; the
        document row and any authenticated relationships are preserved, so it's
        reversible: re-indexing the same doc un-archives it."""
        reachable = set(reachable_ids)
        archived = 0
        for d in self.all_documents():
            if not d["doc_id"].startswith(source_prefix):
                continue
            if d["doc_id"] in reachable or d["archived"]:
                continue
            self.conn.execute("UPDATE documents SET archived=1 WHERE doc_id=?", (d["doc_id"],))
            self.conn.execute("DELETE FROM docs_fts WHERE doc_id=?", (d["doc_id"],))
            self.store.delete(d["doc_id"])
            archived += 1
        self.conn.commit()
        return archived

    def _rehydrate(self, job: sqlite3.Row) -> DocumentRef:
        """Reconstruct a fetchable ref for a queued job. Uses the in-process ref
        if present; otherwise rebuilds it from the durable job record (local
        files), so the passes are re-runnable after a crash or across calls."""
        meta = json.loads(job["ref"])
        if meta["doc_id"] in getattr(self, "_refs", {}):
            return self._refs[meta["doc_id"]]
        url = meta.get("source_url", "")
        if url.startswith("file://"):
            path = url[len("file://"):]

            def _fetch(p=path) -> bytes:
                with open(p, "rb") as f:
                    return f.read()

            return DocumentRef(meta["doc_id"], meta["name"], meta["kind"],
                               meta.get("modified", 0.0), url, _fetch)
        raise RuntimeError(
            f"no fetcher for {meta['doc_id']}: non-local sources must be polled in-process")

    # ---- staged passes ---------------------------------------------------
    def run_metadata_pass(self) -> int:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE stage='metadata' AND status='pending'").fetchall()
        done = 0
        for job in rows:
            ref = self._rehydrate(job)
            data = ref.fetch()
            m = Parser.quick(ref, data)
            now = time.time()
            self.conn.execute(
                """INSERT INTO documents
                   (doc_id,title,source_url,kind,doi,descriptors,first_text,modified,indexed_at,archived)
                   VALUES(?,?,?,?,?,?,?,?,?,0)
                   ON CONFLICT(doc_id) DO UPDATE SET
                     title=excluded.title, source_url=excluded.source_url,
                     kind=excluded.kind, doi=excluded.doi,
                     first_text=excluded.first_text, indexed_at=excluded.indexed_at,
                     archived=0""",
                (ref.doc_id, m["title"], ref.source_url, m["kind"], m["doi"],
                 json.dumps([]), m["first_text"], ref.modified, now))
            self._fts_set(ref.doc_id, f"{m['title']}\n{m['first_text']}")
            self.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job["job_id"],))
            self.conn.execute(
                "INSERT INTO jobs(doc_id,ref,stage,status,created_at) VALUES(?,?,?,?,?)",
                (ref.doc_id, job["ref"], "embed", "pending", now))
            done += 1
        self.conn.commit()
        return done

    def run_embed_pass(self) -> int:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE stage='embed' AND status='pending'").fetchall()
        done = 0
        for job in rows:
            ref = self._rehydrate(job)
            data = ref.fetch()
            full = Parser.full(ref, data)
            doc = self.get_document(ref.doc_id)
            text_for_vec = f"{doc['title']}\n{full or doc['first_text']}"
            emb = self.embedder.embed(text_for_vec)
            now = time.time()
            self.store.upsert(ref.doc_id, emb)
            self.conn.execute(
                """UPDATE documents SET full_text=?, embedding_model=?, embedded_at=?
                   WHERE doc_id=?""",
                (full, self.embedder.model_name, now, ref.doc_id))
            # widen keyword reach to the full text now that we have it
            self._fts_set(ref.doc_id, f"{doc['title']}\n{full or doc['first_text']}")
            self.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job["job_id"],))
            done += 1
        self.conn.commit()
        return done

    def reembed_all(self, embedder) -> None:
        """Re-embed every document with a new model. Identity + FTS keys are
        unchanged, so nothing downstream (relationships) is disturbed."""
        self.embedder = embedder
        for d in self.all_documents():
            text = f"{d['title']}\n{d['full_text'] or d['first_text']}"
            self.store.upsert(d["doc_id"], embedder.embed(text))
            self.conn.execute(
                "UPDATE documents SET embedding_model=?, embedded_at=? WHERE doc_id=?",
                (embedder.model_name, time.time(), d["doc_id"]))
        self.conn.commit()

    # ---- fts helper ------------------------------------------------------
    def _fts_set(self, doc_id: str, content: str) -> None:
        self.conn.execute("DELETE FROM docs_fts WHERE doc_id=?", (doc_id,))
        self.conn.execute("INSERT INTO docs_fts(doc_id,content) VALUES(?,?)", (doc_id, content))

    # ---- reads -----------------------------------------------------------
    def get_document(self, doc_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return dict(r) if r else None

    def all_documents(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM documents")]

    # ---- hybrid search ---------------------------------------------------
    def search(self, query: str, k: int = 5, rrf_k: int = 60) -> list[dict]:
        # keyword ranker (BM25 via FTS5)
        terms = re.findall(r"[a-z0-9]+", query.lower())
        kw_rank: dict[str, int] = {}
        if terms:
            match = " OR ".join(f'"{t}"' for t in terms)
            try:
                rows = self.conn.execute(
                    "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? "
                    "ORDER BY bm25(docs_fts) LIMIT 50", (match,)).fetchall()
                for i, r in enumerate(rows):
                    kw_rank[r["doc_id"]] = i
            except sqlite3.OperationalError:
                pass

        # dense ranker (delegated to the pluggable vector store)
        qv = self.embedder.embed(query)
        dense_rank = {doc_id: i for i, (doc_id, _) in enumerate(self.store.query(qv, 50))}

        # reciprocal-rank fusion
        fused: dict[str, float] = {}
        for ranks in (kw_rank, dense_rank):
            for doc_id, rank in ranks.items():
                fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)

        out = []
        for doc_id, score in sorted(fused.items(), key=lambda x: x[1], reverse=True):
            d = self.get_document(doc_id)
            if not d or d["archived"]:
                continue
            out.append({
                "doc_id": doc_id,                     # canonical identity
                "title": d["title"],
                "source_url": d["source_url"],        # the link a human re-opens
                "doi": d["doi"],
                "embedded": d["embedding_model"] is not None,
                "score": round(score, 5),
            })
            if len(out) >= k:
                break
        return out


def _ref_json(ref: DocumentRef) -> str:
    return json.dumps({"doc_id": ref.doc_id, "name": ref.name, "kind": ref.kind,
                       "source_url": ref.source_url, "modified": ref.modified})
