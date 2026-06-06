#!/usr/bin/env python3
"""
build_graph.py — rebuild the relationship graph from the embedded corpus.

Reads the same env-configured finder as everything else (DB + embedder + store),
asks the chunk-neighbour engine to propose candidate edges across the active
corpus, persists them to the relationship DB, and prints the ranked connections
with the passage that justified each one. Human verdicts (authenticated/rejected)
are never overwritten, so this is safe to re-run after every sync.

Run it by hand after a sync:
    python3 examples/build_graph.py

Config (via .env or environment):
    PAPERFINDER_REL_DB   relationship graph DB        (default relationships.db)
    PAPERFINDER_DB / _EMBEDDER / _VECTOR_STORE / _QDRANT_*   as everywhere else
"""

import os
import re
import sys
import time

from paperfinder.cli import open_finder   # env-configured finder (DB + embedder + store)
from paperfinder.graph.relationship import RelationshipGraph

REL_DB = os.environ.get("PAPERFINDER_REL_DB", "relationships.db")
K = 5            # max candidate connections proposed per document
MIN_SCORE = 0.0  # floor on passage similarity; raise to prune weak ties

_STOP = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
         "into", "than", "then", "these", "those", "which", "such", "have", "has"}


def _why(src_passage: str, dst_passage: str, width: int = 160) -> str:
    """Show the part of the matched passage that overlaps the other one, so the
    'why' is the shared content rather than whatever happens to start the chunk."""
    text = " ".join((dst_passage or "").split())
    src_tok = {t for t in re.findall(r"[a-z0-9]+", (src_passage or "").lower())
               if len(t) > 3 and t not in _STOP}
    low = text.lower()
    pos = min((low.find(t) for t in src_tok if t in low), default=-1)
    if pos < 0:
        return text[:width]
    start = max(0, pos - width // 4)
    return ("…" if start else "") + text[start:start + width]


def main() -> int:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        pf = open_finder()
        rg = RelationshipGraph(REL_DB)
        proposed = pf.build_graph_candidates(rg, k=K, min_score=MIN_SCORE)
    except Exception as e:
        print(f"[{stamp}] GRAPH BUILD FAILED: {e}", flush=True)
        return 1

    g = rg.export_graph(include_candidates=True)
    titles = {n["id"]: n["title"] for n in g["nodes"]}
    candidates = sorted(
        (e for e in g["edges"] if e["status"] == "candidate"),
        key=lambda e: -(e["confidence"] or 0.0),
    )

    print(f"[{stamp}] graph built | docs={len(g['nodes'])} "
          f"candidates={proposed} store={pf.store.name}", flush=True)
    for e in candidates:
        a = titles.get(e["src"], e["src"])
        b = titles.get(e["dst"], e["dst"])
        print(f"\n  {e['confidence']:.3f}  {a}  <->  {b}")
        ev = e.get("evidence") or {}
        if ev.get("dst_passage"):
            print(f"        why: {_why(ev.get('src_passage', ''), ev['dst_passage'])}…")
    if not candidates:
        print("  (no candidate connections — corpus may be too small or too disjoint)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
