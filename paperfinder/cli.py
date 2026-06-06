#!/usr/bin/env python3
"""
cli.py — drive the paper-finder from the command line.

After `pip install -e .` you can use the `paperfinder` command (or `python -m paperfinder.cli`):

  paperfinder sample [DIR]          generate a sample inbox to play with
  paperfinder backfill DIR          index everything in DIR (+ reconcile removals)
  paperfinder poll DIR              index only what's new/changed since last run
  paperfinder search "your query"   ranked hits (canonical id + link)
  paperfinder viz [OUT.html]        build the relationship graph from the index
  paperfinder serve                 run the query API (uvicorn)

Config via .env or environment:
  PAPERFINDER_DB             sqlite path            (default paperfinder.db)
  PAPERFINDER_EMBEDDER       hashing | st           (default hashing)
  PAPERFINDER_VECTOR_STORE   bruteforce | sqlite-vec | qdrant   (default bruteforce)
"""

import json
import os
import sys

from dotenv import load_dotenv

from paperfinder.core.capture import LocalFolderSource
from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.sampledata import build_sample_inbox

load_dotenv()  # read .env if present, before config below

DB = os.environ.get("PAPERFINDER_DB", "paperfinder.db")
STORE = os.environ.get("PAPERFINDER_VECTOR_STORE", "bruteforce")


def make_embedder():
    if os.environ.get("PAPERFINDER_EMBEDDER", "hashing") == "st":
        from paperfinder.core.finder import STEmbedder
        return STEmbedder()
    return HashingEmbedder()


def open_finder() -> PaperFinder:
    return PaperFinder(DB, embedder=make_embedder(), vector_store_name=STORE)


def ingest(folder: str, incremental: bool):
    pf = open_finder()
    src = LocalFolderSource(folder)
    key = "local:" + os.path.abspath(folder)
    if incremental:
        reachable = pf.run_capture(src, source_key=key)
        stats = {"reachable": reachable, "archived": 0}
    else:
        stats = pf.run_backfill(src, source_key=key, reconcile=True)
    pf.run_metadata_pass()
    e = pf.run_embed_pass()
    active = sum(1 for d in pf.all_documents() if not d["archived"])
    print(f"[{pf.store.name} / {pf.embedder.model_name}] "
          f"reachable {stats['reachable']}, embedded {e}, archived {stats['archived']}  "
          f"(active docs: {active})")


def search(query: str, k: int = 8):
    pf = open_finder()
    hits = pf.search(query, k=k)
    if not hits:
        print("no results"); return
    for i, r in enumerate(hits, 1):
        flag = "" if r["embedded"] else "  (metadata-only)"
        print(f"{i:>2}. {r['title']}{flag}")
        print(f"    {r['source_url']}")
        if r.get("folder"):
            print(f"    folder: {r['folder']}")
        print(f"    id={r['doc_id']}  score={r['score']}")


def viz(out: str = "graph_viz.html"):
    from paperfinder.graph.viz import build_viz
    from paperfinder.graph.relationship import RelationshipGraph
    pf = open_finder()
    rel_db = os.environ.get("PAPERFINDER_REL_DB", "relationships.db")
    rg = RelationshipGraph(rel_db)
    for d in pf.all_documents():
        rg.add_document(d["doc_id"], d["title"], json.loads(d["descriptors"] or "[]"),
                        pf.store.get(d["doc_id"]) or [], source_url=d["source_url"])
        rg.propose_candidates(d["doc_id"], k=3)   # candidate edges; verdicts preserved
    build_viz(rg.export_graph(include_candidates=True), out,
              title="Paper relationships")
    print(f"wrote {out}  (authenticated edges solid, candidates dashed)")


def serve():
    import uvicorn
    print(f"serving query API on http://127.0.0.1:8000  (db={DB})")
    uvicorn.run("paperfinder.api:app", host="127.0.0.1", port=8000)


def sample(folder: str = "sample_inbox"):
    n = build_sample_inbox(folder)
    print(f"wrote {n} sample documents to {folder}/")


def main(argv):
    if not argv:
        print(__doc__); return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "sample":
        sample(*(rest[:1] or []))
    elif cmd == "backfill":
        ingest(rest[0], incremental=False)
    elif cmd == "poll":
        ingest(rest[0], incremental=True)
    elif cmd == "search":
        search(" ".join(rest))
    elif cmd == "viz":
        viz(*(rest[:1] or []))
    elif cmd == "serve":
        serve()
    else:
        print(__doc__); return 1
    return 0


def _console():
    """Entry point for the installed `paperfinder` command."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
