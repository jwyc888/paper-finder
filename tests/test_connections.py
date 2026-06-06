"""Stage 3: the knowledge-graph candidate edges come from cross-document chunk
neighbours, so a connection surfaces when two papers share a PASSAGE even if their
overall topics differ (which a whole-doc average would miss), and the edge carries
both passages as evidence. Human verdicts still win. Brute-force + HashingEmbedder.

Run:  python3 tests/test_connections.py
"""

import os
import sys

from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.graph.relationship import RelationshipGraph

DB = "test_connections.db"
RELDB = "test_connections_rel.db"

# A distinctive niche passage shared by A and B; each doc's bulk is a different topic.
SHARED = ("we find that telomerase reverse transcriptase reactivation drives "
          "replicative senescence bypass in the studied cell lines")
IMMUNO = "t cell receptor antigen presentation mhc class immune tolerance " * 50
CRYSTAL = "x-ray crystallography diffraction lattice unit cell refinement " * 50
LOGISTICS = "supply chain inventory logistics warehouse routing forecast demand " * 60


def main() -> int:
    for p in (DB, RELDB):
        if os.path.exists(p):
            os.remove(p)

    pf = PaperFinder(DB, embedder=HashingEmbedder())
    pf.add_document_text("A", "Immunology paper", IMMUNO + " " + SHARED,
                         source_url="file:///tmp/A.txt")
    pf.add_document_text("B", "Crystallography paper", CRYSTAL + " " + SHARED,
                         source_url="file:///tmp/B.txt")
    pf.add_document_text("C", "Logistics paper", LOGISTICS,
                         source_url="file:///tmp/C.txt")

    checks = []

    # whole-doc centroids: A and B are dominated by different topics, so a single-vector
    # comparison should rank them as NOT each other's strongest tie.
    from paperfinder.core.vectorstore import cosine
    ab_doc = cosine(pf.doc_vector("A"), pf.doc_vector("B"))

    cands = pf.propose_connections("A", k=5)
    top = cands[0] if cands else {}
    checks.append(("A's top connection is B (via the shared passage)",
                   top.get("doc_id") == "B"))
    checks.append(("the connection beats the whole-doc similarity",
                   top.get("score", 0) > ab_doc))
    checks.append(("both evidence passages contain the shared topic",
                   "telomerase" in top.get("src_passage", "").lower()
                   and "telomerase" in top.get("dst_passage", "").lower()))

    # record into the graph and confirm the candidate edge carries evidence
    rg = RelationshipGraph(RELDB)
    n = pf.build_graph_candidates(rg, k=5)
    checks.append(("candidate edges were written to the graph", n >= 1))
    g = rg.export_graph(include_candidates=True)
    ab = next((e for e in g["edges"]
               if {e["src"], e["dst"]} == {"A", "B"} and e["status"] == "candidate"), None)
    checks.append(("A-B candidate edge exists with passage evidence",
                   ab is not None and ab["evidence"]
                   and "telomerase" in ab["evidence"]["dst_passage"].lower()))

    # human verdict wins: reject A-B, re-propose, it stays rejected
    rg.reject("A", "B")
    pf.build_graph_candidates(rg, k=5)
    edge = rg.get_edge("A", "B")
    checks.append(("a human rejection survives re-proposing",
                   edge is not None and edge["status"] == "rejected"))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
