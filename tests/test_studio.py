#!/usr/bin/env python3
"""Studio tests: StudySet assembly + cross-paper synthesis with a stubbed LLM.

No live model is called: a recording stub is injected as `complete`, so we can
assert the synthesis is grounded in the right papers and connection passages.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperfinder.core.finder import PaperFinder, HashingEmbedder
from paperfinder.graph.relationship import RelationshipGraph
from paperfinder.studio.studyset import build_studyset, ids_for_folder
from paperfinder.studio.synthesis import synthesize

DB = "test_studio.db"
REL = "test_studio_rel.db"


def _fresh():
    for p in (DB, REL):
        if os.path.exists(p):
            os.remove(p)


def main():
    _fresh()
    pf = PaperFinder(DB, embedder=HashingEmbedder())
    pf.add_document_text("A", "Telomerase and aging", "telomerase extends replicative lifespan",
                         source_url="file:///A", folder="BioBank ref")
    pf.add_document_text("B", "Senescence markers", "cellular senescence and inflammation markers",
                         source_url="file:///B", folder="BioBank ref")
    pf.add_document_text("C", "Unrelated GWAS methods", "polygenic score blockLASSO methods",
                         source_url="file:///C", folder="G-P references")

    rg = RelationshipGraph(REL)
    for did, title in (("A", "Telomerase and aging"), ("B", "Senescence markers"),
                       ("C", "Unrelated GWAS methods")):
        rg.add_document(did, title, [], [], folder=("BioBank ref" if did != "C" else "G-P references"))
    rg.record_candidate("A", "B", 0.81, ["telomere biology"],
                        {"src_passage": "telomerase extends lifespan",
                         "dst_passage": "senescence drives inflammation"})

    # --- StudySet assembly ---
    ss = build_studyset(pf, rg, ["A", "B"])
    titles = {p.title for p in ss.papers}
    conn_ok = (len(ss.connections) == 1
               and "telomerase" in ss.connections[0].a_passage
               and "senescence" in ss.connections[0].b_passage)

    # connection to C must not appear (C not in the selected set)
    ss_ab_only = all({c.a, c.b} <= {"A", "B"} for c in ss.connections)

    # --- folder selector ---
    biobank = set(ids_for_folder(pf, "BioBank ref"))

    # --- synthesis with a recording stub (no live LLM) ---
    calls = []

    def stub(prompt, system=None, frontier=False, max_tokens=1500):
        calls.append({"prompt": prompt, "system": system, "frontier": frontier})
        # emulate map vs reduce by what the prompt asks for
        return "REDUCED SYNTHESIS" if "cross-paper synthesis" in prompt else "map summary"

    out = synthesize(ss, complete=stub)
    reduce_prompt = next((c["prompt"] for c in calls if "cross-paper synthesis" in c["prompt"]), "")

    checks = [
        ("both selected papers assembled", titles == {"Telomerase and aging", "Senescence markers"}),
        ("paper text is carried into the set", any("telomerase" in p.text for p in ss.papers)),
        ("internal connection assembled with passages", conn_ok),
        ("connections are limited to the selected set", ss_ab_only),
        ("folder selector returns the folder's papers", biobank == {"A", "B"}),
        ("map step runs once per paper", sum(1 for c in calls if "cross-paper synthesis" not in c["prompt"]) == 2),
        ("reduce prompt names the papers", "Telomerase and aging" in reduce_prompt and "Senescence markers" in reduce_prompt),
        ("reduce prompt includes connection evidence", "senescence drives inflammation" in reduce_prompt),
        ("reduce asks the cross-paper questions", "Points of divergence" in reduce_prompt and "Gaps and open questions" in reduce_prompt),
        ("synthesis returns the reduced output", out == "REDUCED SYNTHESIS"),
        ("empty set is handled", synthesize(build_studyset(pf, rg, []), complete=stub).startswith("No papers")),
    ]

    print("=== studio: studyset + cross-paper synthesis ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    _fresh()
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
