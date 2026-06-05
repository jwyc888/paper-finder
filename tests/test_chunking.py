"""Stage 1 chunking: a paper is findable by content buried deep in its body
(which a single truncated vector would miss), the matching passage is returned,
and a long doc produces multiple chunks. Uses HashingEmbedder + brute-force.

Run:  python3 tests/test_chunking.py
"""

import os
import sys

from paperfinder.core.finder import HashingEmbedder, PaperFinder, _chunk_text

DB = "test_chunking.db"


def main() -> int:
    if os.path.exists(DB):
        os.remove(DB)

    # A document whose distinctive content sits well past the first ~350 words:
    # generic boilerplate up front, the real topic only near the end.
    filler = ("introduction background methods materials acknowledgements references "
              "appendix supplementary figure table " * 60)              # ~600 words of noise
    buried = ("we report that palbociclib synergizes with fulvestrant in "
              "hormone-receptor-positive breast cancer organoids")        # the needle
    long_text = filler + " " + buried

    pf = PaperFinder(DB, embedder=HashingEmbedder())
    pf.add_document_text("doc_long", "Generic Supplementary Title", long_text,
                         source_url="file:///tmp/long.txt")
    pf.add_document_text("doc_other", "Unrelated KG paper",
                         "knowledge graph embeddings link prediction hetionet drkg",
                         source_url="file:///tmp/other.txt")

    checks = []

    n_chunks = pf.conn.execute(
        "SELECT COUNT(*) c FROM chunks WHERE doc_id='doc_long'").fetchone()["c"]
    checks.append(("long doc split into multiple chunks", n_chunks >= 2))

    hits = pf.search("palbociclib fulvestrant organoids", k=5)
    top = hits[0] if hits else {}
    checks.append(("buried-content query finds the right doc first",
                   top.get("doc_id") == "doc_long"))
    checks.append(("matching passage is returned and contains the needle",
                   bool(top.get("passage")) and "palbociclib" in top["passage"].lower()))

    # the needle sits past the truncation horizon, so a single-vector embed of just
    # the first 350 words would NOT contain it — chunking is what surfaces it.
    head = " ".join(long_text.split()[:350])
    checks.append(("needle is beyond the single-vector truncation horizon",
                   "palbociclib" not in head.lower()))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
