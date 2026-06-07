"""synthesis_to_pdf turns a markdown brief into a real PDF on disk."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paperfinder.studio.export import synthesis_to_pdf


def main():
    md = ("# Cross-paper synthesis\n\n## Shared topic\n\n"
          "These papers examine **telomere** dynamics.\n\n"
          "- first point\n- second point\n\n## Divergences\n\nThey disagree on scope.")
    out = os.path.join(tempfile.mkdtemp(), "syn.pdf")
    synthesis_to_pdf(md, out, "Synthesis of 2 papers", ["Paper A", "Paper B"])

    checks = [
        ("pdf file created", os.path.exists(out)),
        ("pdf is non-trivial in size", os.path.getsize(out) > 800),
        ("pdf has the PDF magic header", open(out, "rb").read(5) == b"%PDF-"),
    ]
    ok = True
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
