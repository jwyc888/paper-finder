"""Tier A end-to-end self-test (no Drive needed).

backfill -> metadata pass -> query (findable BEFORE embed) -> embed pass ->
query (semantic + full text) -> verify criteria -> API smoke test ->
relationship viz from the live index.

Run:  python3 tests/test_tier_a.py
"""

import json
import os
import sys

from paperfinder.core.capture import LocalFolderSource
from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.graph.viz import build_viz
from paperfinder.sampledata import build_sample_inbox

INBOX = "sample_inbox"
DB = "test_tier_a.db"
HTML = "graph_viz_tier_a.html"
REL_DB = "test_tier_a_rel.db"


def titles(results):
    return [r["title"] for r in results]


def is_sentiment(title):
    t = title.lower()
    return any(w in t for w in ("patient", "chatbot", "symptom", "trust", "conversational", "sentiment"))


def main() -> int:
    for p in (DB, REL_DB):
        if os.path.exists(p):
            os.remove(p)
    n_files = build_sample_inbox(INBOX)

    pf = PaperFinder(DB, embedder=HashingEmbedder())
    source = LocalFolderSource(INBOX)
    captured = pf.run_capture(source)
    print(f"backfill: captured {captured} files  | vector store: {pf.store.name}")

    pf.run_metadata_pass()
    Q = "patient sentiment toward AI chatbots in medicine"
    before = pf.search(Q, k=8)
    pf.run_embed_pass()
    after = pf.search(Q, k=8)

    print("\n" + "=" * 60 + "\nVerifying Tier A success criteria\n" + "=" * 60)
    checks = []

    def fname(doc_id):
        return os.path.basename((pf.get_document(doc_id) or {}).get("source_url", ""))

    checks.append(("backfill indexed all dropped files",
                   len(pf.all_documents()) == n_files == captured))

    checks.append(("findable before embedding (metadata pass)",
                   sum(is_sentiment(t) for t in titles(before)) >= 3
                   and all(not r["embedded"] for r in before)))

    order = [fname(r["doc_id"]) for r in pf.search(Q, k=20)]

    def rank_of(prefix):
        return next((i for i, fn in enumerate(order) if fn.startswith(prefix)), 999)

    checks.append(("relevant ranked above noise",
                   max(rank_of("p1"), rank_of("p2"), rank_of("p3")) < min(rank_of("k1"), rank_of("k2"))))

    nbrs = pf.store.query(pf.embedder.embed(Q), 3)
    checks.append(("vector store interface returns ranked neighbours",
                   len(nbrs) > 0 and all(isinstance(t, tuple) and len(t) == 2 for t in nbrs)))

    checks.append(("results carry canonical id + link",
                   all(r["doc_id"] and r["source_url"] for r in after)))

    tricky_before = any(fname(r["doc_id"]).startswith("supplementary") for r in before)
    tricky_after = any(f.startswith("supplementary") for f in order)
    checks.append(("staged gap: tricky doc hidden pre-embed, found post-embed",
                   (not tricky_before) and tricky_after))

    os.environ["PAPERFINDER_DB"] = DB
    try:
        from fastapi.testclient import TestClient
        from paperfinder import api
        resp = TestClient(api.app).get("/search", params={"q": Q, "k": 3})
        checks.append(("query API returns ranked hits",
                       resp.status_code == 200 and len(resp.json()["results"]) > 0))
    except (ImportError, RuntimeError):
        print('  [skip] query API check needs the dev extra: pip install -e ".[dev]"')

    rg = RelationshipGraph(REL_DB)
    for d in pf.all_documents():
        rg.add_document(d["doc_id"], d["title"], json.loads(d["descriptors"] or "[]"),
                        pf.store.get(d["doc_id"]) or [], source_url=d["source_url"])
    rg.propose_candidates(pf.search(Q, k=1)[0]["doc_id"], k=4)
    build_viz(rg.export_graph(include_candidates=True), HTML,
              title="Paper relationships (from Tier A index)")
    print(f"wrote {HTML} from the live index")

    ids_before = {d["doc_id"] for d in pf.all_documents()}
    pf.reembed_all(HashingEmbedder(dim=128))
    checks.append(("identities stable across re-embed",
                   {d["doc_id"] for d in pf.all_documents()} == ids_before))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
