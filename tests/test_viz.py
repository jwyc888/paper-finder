"""build_viz / render_html embed the node titles and edge evidence, and the
interactive variant adds the review controls and endpoints while the static one
(used by automation) does not.

Run:  python3 tests/test_viz.py
"""

import os
import sys

from paperfinder.graph.viz import build_viz, render_html

OUT = "test_viz_output.html"

GRAPH = {
    "nodes": [
        {"id": "gdrive:1ABC", "title": "Telomerase paper", "descriptors": [],
         "folder": "Aging/Telomeres",
         "source_url": "https://drive.google.com/file/d/1ABC/view"},
        {"id": "gdrive:2DEF", "title": "Senescence paper", "descriptors": [],
         "source_url": "https://drive.google.com/file/d/2DEF/view"},
    ],
    "edges": [
        {"src": "gdrive:1ABC", "dst": "gdrive:2DEF", "status": "candidate", "source": "inferred",
         "descriptors": [], "confidence": 0.812,
         "evidence": {"src_passage": "telomerase reactivation drives bypass",
                      "dst_passage": "replicative senescence in cell lines"}},
    ],
}


def main() -> int:
    checks = []

    build_viz(GRAPH, OUT)
    try:
        static_html = open(OUT).read()
    finally:
        if os.path.exists(OUT):
            os.remove(OUT)

    checks.append(("static: is a vis-network page", "vis-network" in static_html))
    checks.append(("static: node titles embedded",
                   "Telomerase paper" in static_html and "Senescence paper" in static_html))
    checks.append(("static: edge evidence embedded",
                   "telomerase reactivation drives bypass" in static_html
                   and "replicative senescence in cell lines" in static_html))
    checks.append(("static: score embedded", "0.812" in static_html))
    checks.append(("static: source_url for node-open embedded",
                   "drive.google.com/file/d/1ABC/view" in static_html))
    checks.append(("static: node folder embedded in data",
                   "Aging/Telomeres" in static_html))
    checks.append(("static: top-level-folder label logic present",
                   "topFolder" in static_html))
    checks.append(("static: no review controls (panel/buttons absent, flag off)",
                   'id="rv-auth"' not in static_html and 'id="done"' not in static_html
                   and "INTERACTIVE = false" in static_html))

    interactive_html = render_html(GRAPH, interactive=True)
    checks.append(("interactive: review panel present", 'id="review"' in interactive_html
                   and 'id="rv-auth"' in interactive_html and 'id="rv-reject"' in interactive_html))
    checks.append(("interactive: endpoints wired",
                   "/authenticate" in interactive_html and "/reject" in interactive_html
                   and "/shutdown" in interactive_html))
    checks.append(("interactive: Done button present", 'id="done"' in interactive_html))
    checks.append(("interactive: INTERACTIVE flag true", "INTERACTIVE = true" in interactive_html))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
