"""Back-matter stripping: references/bibliography/supplementary are removed while
body and appendix are kept, including when the appendix sits AFTER the references.
Failure modes (no candidates, empty/failed classifier) leave the text untouched.
The LLM is injected as a fake so the span logic is tested deterministically.

Run:  python3 tests/test_sectionstrip.py
"""

import sys

from paperfinder.core.sectionstrip import find_candidates, strip_back_matter

DOC = """Title of the Paper
We present a method for studying telomerase in cell lines.
The body discusses results and their significance in detail.

Appendix A
Extended derivations and supporting tables for the body.

References
1. Smith J, et al. Nature 2020;580:1-10.
2. Doe A, et al. Cell 2019;177:200-210.

Supplementary Information
Figure S1 shows additional control experiments.
"""


def fake_classifier(lines, candidates):
    """Type each candidate by its heading text (stands in for the local LLM)."""
    out = []
    for c in candidates:
        t = c["text"].lower()
        if t.startswith("appendix"):
            out.append({"line": c["line"], "type": "appendix"})
        elif t.startswith("reference"):
            out.append({"line": c["line"], "type": "references"})
        elif t.startswith("supplementary"):
            out.append({"line": c["line"], "type": "supplementary"})
        else:
            out.append({"line": c["line"], "type": "body"})
    return out


def main() -> int:
    checks = []

    cands = {c["text"].split()[0].lower() for c in find_candidates(DOC)}
    checks.append(("finds appendix/references/supplementary headings",
                   {"appendix", "references", "supplementary"} <= cands))

    cleaned = strip_back_matter(DOC, classify=fake_classifier)
    checks.append(("body is kept", "method for studying telomerase" in cleaned))
    checks.append(("appendix kept even though it precedes references",
                   "Extended derivations" in cleaned))
    checks.append(("references section removed", "Smith J" not in cleaned and "Nature 2020" not in cleaned))
    checks.append(("supplementary section removed", "Figure S1" not in cleaned))

    # appendix AFTER references must survive (reordered doc)
    reordered = ("Body text about telomerase.\n\nReferences\n1. X et al.\n\n"
                 "Appendix B\nKept appendix content here.\n")
    out2 = strip_back_matter(reordered, classify=fake_classifier)
    checks.append(("appendix after references survives",
                   "Kept appendix content" in out2 and "1. X et al." not in out2))

    # fallback: a classifier that fails (returns nothing) leaves text untouched
    untouched = strip_back_matter(DOC, classify=lambda lines, cands: [])
    checks.append(("empty classifier result -> text unchanged", untouched == DOC))

    # fallback: no candidate headings -> unchanged
    plain = "Just body text with no back matter at all."
    checks.append(("no candidates -> text unchanged",
                   strip_back_matter(plain, classify=fake_classifier) == plain))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
