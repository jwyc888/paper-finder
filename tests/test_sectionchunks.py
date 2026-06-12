"""Section-aware chunking (hybrid labels) + section-scoped search.

The local LLM is injected as a fake so span logic and retrieval are deterministic
and need no network. Verifies: chunks carry verbatim section_text and a normalized
section_type; back-matter (references) is dropped; numbered non-IMRaD headings are
detected and labelled "other" with faithful heading text; search(section=...)
restricts to chunks of that type. Also confirms the default (flag off) path is
unchanged: no section labels are attached.

Run:  python3 tests/test_sectionchunks.py
"""

import os
import sys

from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.core.sectionstrip import find_candidates, segment, normalize_type

DB = "test_sectionchunks.db"

DOC = """A Trial of Widgetinib in Sprockets
We summarize the study and its motivation here in the abstract.

Introduction
Sprocket disease is common and motivates this widgetinib trial overview.

Methods
Participants received zanzibarine titration under a blinded crossover protocol.

Results
The quoxibollin endpoint improved markedly in the treatment arm versus control.

Discussion
We interpret the quoxibollin findings and their limitations for sprocket care.

4.1 Lifestyle Considerations
General lifestyle guidance that does not map to a standard IMRaD section.

References
1. Smith J, et al. Journal of Sprockets 2024;1:1-9
2. Doe A, et al. Widget Reports 2023;7:3-8
"""


def fake_classifier(lines, candidates):
    """Type each candidate by its heading text (stands in for the local LLM)."""
    out = []
    for c in candidates:
        t = c["text"].lower()
        if t.startswith("introduction"):
            ty = "introduction"
        elif t.startswith("method"):
            ty = "methods"
        elif t.startswith("result"):
            ty = "results"
        elif t.startswith("discussion"):
            ty = "discussion"
        elif t.startswith("reference"):
            ty = "references"
        elif t.startswith("abstract"):
            ty = "abstract"
        elif t[:1].isdigit():            # numbered non-IMRaD heading: real, but "other"
            ty = "other"
        else:
            ty = "body"
        out.append({"line": c["line"], "type": ty})
    return out


def main() -> int:
    checks = []

    # --- candidate detection unit checks (no model) -----------------------
    assert normalize_type("Materials and Methods") == "methods"
    assert normalize_type("body") == "body"
    heads = {c["text"] for c in find_candidates(DOC)}
    checks.append(("IMRaD headings detected",
                   {"Introduction", "Methods", "Results", "Discussion"} <= heads))
    checks.append(("numbered non-IMRaD heading detected", "4.1 Lifestyle Considerations" in heads))
    checks.append(("numbered citation line NOT detected as a heading",
                   not any(h.startswith("1. Smith") for h in heads)))

    # --- segment() span labelling -----------------------------------------
    spans = segment(DOC, classify=fake_classifier)
    by_type = {s["section_type"]: s for s in spans}
    checks.append(("methods span carries verbatim heading text",
                   by_type.get("methods", {}).get("section_text") == "Methods"))
    checks.append(("numbered section kept as 'other' with faithful heading",
                   by_type.get("other", {}).get("section_text") == "4.1 Lifestyle Considerations"))

    # --- section-aware chunking through PaperFinder ------------------------
    if os.path.exists(DB):
        os.remove(DB)
    pf = PaperFinder(DB, embedder=HashingEmbedder())
    pf.section_chunks = True               # flip the flag for this finder
    pf._segment_classify = fake_classifier  # inject the fake (no network)
    pf.add_document_text("trial", "A Trial of Widgetinib in Sprockets", DOC,
                         source_url="file:///tmp/trial.txt")

    rows = pf.conn.execute(
        "SELECT DISTINCT section_type FROM chunks WHERE doc_id='trial'").fetchall()
    types = {r["section_type"] for r in rows}
    checks.append(("chunks carry normalized section types",
                   {"methods", "results", "discussion"} <= types))
    checks.append(("references section dropped (no references chunk)",
                   "references" not in types))
    checks.append(("references body text not embedded",
                   pf.conn.execute(
                       "SELECT COUNT(*) c FROM chunks WHERE doc_id='trial' AND text LIKE '%Journal of Sprockets%'"
                   ).fetchone()["c"] == 0))

    # --- section-scoped search --------------------------------------------
    hit_any = pf.search("zanzibarine", k=5)
    checks.append(("unscoped search finds the methods needle",
                   bool(hit_any) and hit_any[0]["doc_id"] == "trial"))

    hit_methods = pf.search("zanzibarine", k=5, section="methods")
    checks.append(("section='methods' returns the methods chunk",
                   bool(hit_methods) and hit_methods[0].get("section_type") == "methods"))

    hit_results = pf.search("zanzibarine", k=5, section="results")
    checks.append(("section='results' is scoped to results chunks, not the methods needle",
                   bool(hit_results)
                   and all(h.get("section_type") == "results" for h in hit_results)
                   and all("zanzibarine" not in (h.get("passage") or "").lower() for h in hit_results)))

    # --- default path (flag off) is unchanged -----------------------------
    DB2 = "test_sectionchunks_flat.db"
    if os.path.exists(DB2):
        os.remove(DB2)
    flat = PaperFinder(DB2, embedder=HashingEmbedder())   # section_chunks stays off
    flat.add_document_text("flat", "Flat Doc", "alpha beta gamma delta methods results")
    frow = flat.conn.execute(
        "SELECT section_type FROM chunks WHERE doc_id='flat' LIMIT 1").fetchone()
    checks.append(("flag off: chunks have no section label", frow["section_type"] is None))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
