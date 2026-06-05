"""Stage 2: exercise the real QdrantStore through qdrant-client's in-memory mode
(same client code paths as a live server, no network). Confirms chunk search works
on Qdrant and that get/delete behave. The live network path to your 6533 instance is
validated separately on the Mac.

Needs:  pip install -e ".[qdrant]"
Run:    python3 tests/test_qdrant_store.py
"""

import os
import sys

from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.core.vectorstore import QdrantStore

DB = "test_qdrant.db"


def main() -> int:
    if os.path.exists(DB):
        os.remove(DB)

    emb = HashingEmbedder()
    dim = len(emb.embed("probe"))
    store = QdrantStore(dim, location=":memory:")          # in-process Qdrant
    pf = PaperFinder(DB, embedder=emb, vector_store=store)

    filler = ("introduction background methods materials references appendix " * 60)
    needle = ("trastuzumab deruxtecan shows activity in her2-low metastatic "
              "breast cancer after prior therapy")
    pf.add_document_text("d1", "Generic Title", filler + " " + needle,
                         source_url="file:///tmp/d1.txt")
    pf.add_document_text("d2", "Unrelated", "knowledge graph link prediction hetionet",
                         source_url="file:///tmp/d2.txt")

    checks = []

    hits = pf.search("trastuzumab deruxtecan her2-low", k=5)
    top = hits[0] if hits else {}
    checks.append(("Qdrant-backed search finds the buried-content doc first",
                   top.get("doc_id") == "d1"))
    checks.append(("matching passage returned via Qdrant payload",
                   bool(top.get("passage")) and "trastuzumab" in top["passage"].lower()))

    # direct store crud
    n_chunks = pf.conn.execute("SELECT COUNT(*) c FROM chunks WHERE doc_id='d1'").fetchone()["c"]
    cid = f"d1#0"
    checks.append(("get returns a stored chunk vector", store.get(cid) is not None))
    store.delete(cid)
    checks.append(("delete removes the chunk vector", store.get(cid) is None))
    checks.append(("doc had multiple chunks", n_chunks >= 2))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
