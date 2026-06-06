#!/usr/bin/env python3
"""Cross-paper synthesis over a manual study set.

The study set is just a list of papers. Two zero-setup ways to supply it:

  # explicit doc_ids
  python examples/synthesize.py --ids gdrive:AAA gdrive:BBB gdrive:CCC

  # everything in a folder (reuses the folder tags; prefix-matched)
  python examples/synthesize.py --folder "BioBank ref"

Add --frontier to route the model calls to Anthropic (needs ANTHROPIC_API_KEY)
instead of the local model. Writes a Markdown file and prints its path.
"""

import argparse
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from paperfinder.core.finder import PaperFinder
from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.studio.studyset import build_studyset, ids_for_folder
from paperfinder.studio.synthesis import synthesize, compare_models


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-paper synthesis over a study set.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ids", nargs="+", help="explicit doc_ids")
    g.add_argument("--folder", help="all active papers in this folder (or beneath it)")
    ap.add_argument("--frontier", action="store_true", help="use the frontier model (Anthropic)")
    ap.add_argument("--compare", action="store_true",
                    help="run both the local and frontier models on the same set, side by side")
    ap.add_argument("--out", help="output .md path (default studysets/synthesis-<time>.md)")
    args = ap.parse_args()

    # Light finder: we only read the documents table, so no embedder/vector store is loaded.
    pf = PaperFinder(os.environ.get("PAPERFINDER_DB", "paperfinder.db"))
    rg = RelationshipGraph(os.environ.get("PAPERFINDER_REL_DB", "relationships.db"))

    ids = args.ids if args.ids else ids_for_folder(pf, args.folder)
    if not ids:
        print("No papers matched the selection.", file=sys.stderr)
        return 1

    studyset = build_studyset(pf, rg, ids)
    if not studyset.papers:
        print("None of the requested doc_ids resolved to active documents.", file=sys.stderr)
        return 1

    papers_header = "".join(f"- {p.title}\n" for p in studyset.papers)

    if args.compare:
        print(f"{len(studyset.papers)} papers, {len(studyset.connections)} internal connections | "
              f"comparing local vs frontier", file=sys.stderr)
        runs = compare_models(studyset)
        for r in runs:
            print(f"  {r['label']} ({r['model']}): {r['seconds']:.1f}s", file=sys.stderr)
        out = args.out
        if not out:
            os.makedirs("studysets", exist_ok=True)
            out = os.path.join("studysets", f"compare-{time.strftime('%Y%m%d-%H%M%S')}.md")
        parts = ["# Cross-paper synthesis: local vs frontier\n", papers_header, "\n"]
        for r in runs:
            parts.append(f"\n---\n\n## {r['label']}: {r['model']}  ({r['seconds']:.1f}s)\n\n")
            parts.append(r["text"].strip() + "\n")
        with open(out, "w", encoding="utf-8") as f:
            f.write("".join(parts))
        print(out)
        return 0

    print(f"{len(studyset.papers)} papers, {len(studyset.connections)} internal connections | "
          f"model: {'frontier' if args.frontier else 'local'}", file=sys.stderr)
    md = synthesize(studyset, frontier=args.frontier)

    out = args.out
    if not out:
        os.makedirs("studysets", exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = os.path.join("studysets", f"synthesis-{stamp}.md")
    header = "# Cross-paper synthesis\n\n" + papers_header + "\n---\n\n"
    with open(out, "w", encoding="utf-8") as f:
        f.write(header + md + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
