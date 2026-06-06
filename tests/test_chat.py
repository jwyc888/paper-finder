#!/usr/bin/env python3
"""Chat engine tests with a stubbed LLM: retrieval grounding, multi-turn rewrite, sources."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperfinder.core.finder import PaperFinder, HashingEmbedder
from paperfinder.studio.chat import ChatSession, retrieve, web_sources

DB = "test_chat.db"


def main():
    if os.path.exists(DB):
        os.remove(DB)
    pf = PaperFinder(DB, embedder=HashingEmbedder())
    pf.add_document_text("gdrive:tel", "Telomerase and lifespan",
                         "telomerase reactivation extends replicative lifespan in human cells",
                         folder="BioBank ref")
    pf.add_document_text("gdrive:sen", "Cellular senescence",
                         "cellular senescence triggers chronic inflammation and tissue decline",
                         folder="BioBank ref")
    pf.add_document_text("gdrive:gwas", "Polygenic scores",
                         "blockLASSO polygenic score estimation across ancestries",
                         folder="G-P references")

    calls = []

    def stub(prompt, system=None, frontier=False, max_tokens=1000):
        calls.append({"prompt": prompt, "system": system, "frontier": frontier})
        if "Rewrite the follow-up" in prompt:
            return "telomerase lifespan in mice"
        return "Per [Telomerase and lifespan], telomerase extends replicative lifespan."

    # direct retrieval grounding
    hits = retrieve(pf, "telomerase replicative lifespan", k=3)

    session = ChatSession(pf, k=3, complete=stub)

    res1 = session.ask("What does my library say about telomerase and lifespan?")
    rewrites_after_t1 = sum(1 for c in calls if "Rewrite the follow-up" in c["prompt"])
    answer_calls_t1 = [c for c in calls if "Answer using only the passages" in c["prompt"]]

    res2 = session.ask("what about in mice?")
    rewrites_after_t2 = sum(1 for c in calls if "Rewrite the follow-up" in c["prompt"])
    last_answer_prompt = [c for c in calls if "Answer using only the passages" in c["prompt"]][-1]["prompt"]

    checks = [
        ("retrieval surfaces the on-topic paper first", hits and hits[0]["doc_id"] == "gdrive:tel"),
        ("retrieval carries passage text and source", hits and "telomerase" in hits[0]["text"]),
        ("turn 1 does not rewrite (no history yet)", rewrites_after_t1 == 0),
        ("turn 1 query is the verbatim question", res1["query"].startswith("What does my library")),
        ("turn 1 sources include the telomerase paper", any(s["doc_id"] == "gdrive:tel" for s in res1["sources"])),
        ("answer prompt embeds retrieved passage text", "extends replicative lifespan" in answer_calls_t1[0]["prompt"]),
        ("grounding instruction present in answer system", "only the provided passages" in (answer_calls_t1[0]["system"] or "")),
        ("turn 2 triggers a follow-up rewrite", rewrites_after_t2 == 1),
        ("turn 2 retrieves on the rewritten standalone query", res2["query"] == "telomerase lifespan in mice"),
        ("turn 2 answer prompt includes prior conversation", "# Conversation so far" in last_answer_prompt and "telomerase and lifespan" in last_answer_prompt.lower()),
        ("rewrite uses the local model regardless of frontier flag",
         all(c["frontier"] is False for c in calls if "Rewrite the follow-up" in c["prompt"])),
        ("structured sources returned for GUI mapping", isinstance(res2["sources"], list)),
        ("folder scope filters retrieval", all(h["doc_id"] != "gdrive:gwas" for h in retrieve(pf, "polygenic blockLASSO", k=3, folder="BioBank ref"))),
    ]

    ws = web_sources([
        {"doc_id": "gdrive:abc", "title": "P1", "source_url": ""},
        {"doc_id": "gdrive:abc", "title": "P1", "source_url": ""},
        {"doc_id": "x", "title": "P2", "source_url": "http://e/p2"},
    ])
    checks += [
        ("web_sources dedupes and keeps doc_id", [s["doc_id"] for s in ws] == ["gdrive:abc", "x"]),
        ("web_sources derives a Drive link", ws[0]["link"] == "https://drive.google.com/file/d/abc/view"),
        ("web_sources keeps an explicit url", ws[1]["link"] == "http://e/p2"),
    ]

    print("=== chat: multi-turn RAG over the library ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    if os.path.exists(DB):
        os.remove(DB)
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
