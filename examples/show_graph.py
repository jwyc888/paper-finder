#!/usr/bin/env python3
"""
show_graph.py - render the current relationship graph to an interactive HTML
file and open it in your browser.

Reads the relationship DB, exports nodes + candidate/authenticated edges (with
their passage evidence), and writes a self-contained vis-network page. Hovering
an edge shows the two passages that linked the papers.

Run:
    python3 examples/show_graph.py

Config (env):
    PAPERFINDER_REL_DB     relationship DB        (default relationships.db)
    PAPERFINDER_GRAPH_HTML output html path        (default paper_graph.html)
"""

import os
import subprocess
import sys

from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.graph.viz import build_viz

REL_DB = os.environ.get("PAPERFINDER_REL_DB", "relationships.db")
OUT = os.environ.get("PAPERFINDER_GRAPH_HTML", "paper_graph.html")


def main() -> int:
    rg = RelationshipGraph(REL_DB)
    graph = rg.export_graph(include_candidates=True)
    if not graph["nodes"]:
        print("graph is empty - run examples/build_graph.py first")
        return 1
    build_viz(graph, OUT)
    path = os.path.abspath(OUT)
    n_cand = sum(1 for e in graph["edges"] if e["status"] == "candidate")
    n_auth = sum(1 for e in graph["edges"] if e["status"] == "authenticated")
    print(f"wrote {path} | nodes={len(graph['nodes'])} "
          f"candidates={n_cand} authenticated={n_auth}")

    # best-effort open in the default browser (mac: open, linux: xdg-open)
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run([opener, path], check=False)
    except FileNotFoundError:
        print(f"open it manually: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
