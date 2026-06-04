"""Relationship-layer self-test: seed a small corpus, run the verification loop
(propose -> authenticate -> reject -> traverse), check the success criteria
including re-embed durability, and emit a graph viz.

Run:  python3 tests/test_relationship.py
"""

import os
import random
import sys

from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.graph.viz import build_viz

DB = "test_relationship.db"
HTML = "graph_viz_relationship.html"

# 6 latent axes: [sentiment, chatbot, clinical, kg, drug, trust]
CORPUS = [
    ("d1", "Patient attitudes toward AI chatbots in primary care",
     ["patient sentiment", "medical chatbot", "primary care"], [0.90, 0.90, 0.70, 0.0, 0.0, 0.30]),
    ("d2", "Trust and acceptance of conversational agents in mental health",
     ["patient trust", "conversational agent", "mental health"], [0.80, 0.85, 0.60, 0.0, 0.0, 0.60]),
    ("d3", "User perceptions of symptom-checker apps",
     ["user perception", "symptom checker", "patient sentiment"], [0.85, 0.70, 0.65, 0.0, 0.0, 0.25]),
    ("d4", "Measuring patient trust in clinical decision support",
     ["patient trust", "clinical decision support"], [0.40, 0.10, 0.80, 0.0, 0.0, 0.90]),
    ("d5", "RotatE knowledge-graph embeddings for drug repurposing",
     ["knowledge graph embedding", "drug repurposing"], [0.0, 0.0, 0.20, 0.90, 0.90, 0.10]),
    ("d6", "Link prediction over biomedical knowledge graphs",
     ["link prediction", "biomedical knowledge graph"], [0.0, 0.0, 0.20, 0.95, 0.70, 0.15]),
    ("d7", "Human verification as a trust signal in AI systems",
     ["human verification", "trust signal", "AI evaluation"], [0.30, 0.20, 0.20, 0.40, 0.10, 0.90]),
]


def main() -> int:
    if os.path.exists(DB):
        os.remove(DB)
    g = RelationshipGraph(DB)
    for doc_id, title, desc, emb in CORPUS:
        g.add_document(doc_id, title, desc, emb, source_url=f"https://example.org/{doc_id}")

    g.propose_candidates("d1", k=5)
    g.authenticate("d1", "d3", ["patient sentiment", "symptom perception"], "john")
    g.authenticate("d2", "d4", ["patient trust"], "john")
    g.authenticate("d5", "d6", ["knowledge graph embedding", "link prediction"], "john")
    g.propose_candidates("d7", k=5)
    g.authenticate("d4", "d7", ["trust signal", "clinical AI trust"], "john")
    g.reject("d1", "d4")

    checks = []
    n1 = {x["doc_id"]: x for x in g.neighbors("d1", "authenticated")}
    checks.append(("authenticated edge traversable with 'why'",
                   "d3" in n1 and n1["d3"]["descriptors"] == ["patient sentiment", "symptom perception"]))

    auth = {(e["src"], e["dst"]) for e in g.export_graph()["edges"] if e["status"] == "authenticated"}
    cand = {(e["src"], e["dst"]) for e in g.export_graph()["edges"] if e["status"] == "candidate"}
    checks.append(("candidate and authenticated kept distinct",
                   len(auth) >= 4 and len(cand) >= 1 and not (auth & cand)))

    g.propose_candidates("d1", k=5)
    edge = g.get_edge("d1", "d4")
    checks.append(("rejected pair stays rejected after re-proposing",
                   edge is not None and edge["status"] == "rejected"))

    before = [e for e in g.edges_snapshot() if e[2] in ("authenticated", "rejected")]
    rng = random.Random(7)
    for doc_id, *_ in CORPUS:
        g.set_embedding(doc_id, [rng.random() for _ in range(6)], "v1-new-model")
    g.propose_candidates("d1", k=5)
    after = [e for e in g.edges_snapshot() if e[2] in ("authenticated", "rejected")]
    checks.append(("human-verified edges unchanged after re-embed", before == after))

    build_viz(g.export_graph(include_candidates=True), HTML, title="Paper relationships")

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
