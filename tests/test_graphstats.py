"""graph_digest reports exact counts, folders, neighbours, and isolated papers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paperfinder.graph.stats import graph_digest, write_graph_stats, load_graph_stats

EXPORT = {
    "nodes": [
        {"id": "a", "title": "Telomere review", "folder": "BioBank ref"},
        {"id": "b", "title": "Senescence study", "folder": "BioBank ref"},
        {"id": "c", "title": "GWAS methods", "folder": "G-P references"},
        {"id": "d", "title": "Orphan paper", "folder": ""},
    ],
    "edges": [
        {"src": "a", "dst": "b", "status": "authenticated", "confidence": 0.82},
        {"src": "a", "dst": "c", "status": "candidate", "confidence": 0.61},
    ],
}


def main():
    d = graph_digest(EXPORT)
    checks = [
        ("exact node/edge counts", "4 papers (nodes), 2 connections (edges)" in d),
        ("authenticated/candidate split", "1 authenticated, 1 candidate" in d),
        ("folder tally present", "BioBank ref (2)" in d and "(root) (1)" in d),
        ("most-connected is the hub", '"Telomere review" (2)' in d),
        ("isolated paper detected", '"Orphan paper"' in d.split("no connections:")[1].split("\n")[0]),
        ("adjacency lists a neighbour with score+flag", '"Senescence study" 0.82 (a)' in d),
        ("orphan shows none", '"Orphan paper" [(root)]: (none)' in d),
    ]

    tmp = os.path.join(os.path.dirname(__file__), "_stats_tmp.md")
    try:
        write_graph_stats(EXPORT, tmp)
        checks.append(("round-trips through disk", graph_digest(EXPORT) in load_graph_stats(tmp)))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    ok = True
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
