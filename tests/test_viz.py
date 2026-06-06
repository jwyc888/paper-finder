"""build_viz emits a self-contained HTML page that embeds the node titles and,
crucially, the edge evidence passages (the 'why' a connection exists). Smoke-level:
we don't render it, we confirm the data made it into the file.

Run:  python3 tests/test_viz.py
"""

import os
import sys

from paperfinder.graph.viz import build_viz

OUT = "test_viz_output.html"


def main() -> int:
    graph = {
        "nodes": [
            {"id": "A", "title": "Telomerase paper", "descriptors": []},
            {"id": "B", "title": "Senescence paper", "descriptors": []},
        ],
        "edges": [
            {"src": "A", "dst": "B", "status": "candidate", "source": "inferred",
             "descriptors": [], "confidence": 0.812,
             "evidence": {"src_passage": "telomerase reactivation drives bypass",
                          "dst_passage": "replicative senescence in cell lines"}},
        ],
    }
    build_viz(graph, OUT)

    checks = []
    try:
        html = open(OUT).read()
    finally:
        if os.path.exists(OUT):
            os.remove(OUT)

    checks.append(("file is a vis-network page", "vis-network" in html))
    checks.append(("node titles embedded", "Telomerase paper" in html and "Senescence paper" in html))
    checks.append(("edge evidence embedded", "telomerase reactivation drives bypass" in html
                   and "replicative senescence in cell lines" in html))
    checks.append(("score embedded", "0.812" in html))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
