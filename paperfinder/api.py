"""
api.py — the query surface Cortex calls.

  GET /search?q=...&k=5     -> ranked hits (canonical doc_id + link + score)
  GET /document/{doc_id}    -> full record
  GET /graph                -> nodes+edges for the relationship viz

Run:  uvicorn api:app --reload   (DB path via PAPERFINDER_DB env var)
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from paperfinder.core.finder import PaperFinder

load_dotenv()
app = FastAPI(title="paper-finder (Tier A)")
_pf = PaperFinder(os.environ.get("PAPERFINDER_DB", "paperfinder.db"))


@app.get("/search")
def search(q: str, k: int = 5, folder: str = None):
    return {"query": q, "results": _pf.search(q, k=k, folder=folder)}


@app.get("/document/{doc_id}")
def document(doc_id: str):
    d = _pf.get_document(doc_id)
    if not d:
        raise HTTPException(404, "not found")
    return d


@app.get("/graph")
def graph():
    # Tier A has documents but no edges yet; the relationship layer adds edges.
    return {"nodes": [{"id": d["doc_id"], "title": d["title"]}
                      for d in _pf.all_documents()], "edges": []}
