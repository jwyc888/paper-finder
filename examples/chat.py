#!/usr/bin/env python3
"""Multi-turn RAG chat over your paper library (CLI).

  python examples/chat.py                       # whole corpus, local model
  python examples/chat.py --folder "BioBank ref"
  python examples/chat.py --frontier            # answer with Anthropic (needs ANTHROPIC_API_KEY)

Ask a question and press enter. Commands: /reset clears the conversation, /quit exits.
Uses the real embedder and vector store (loads the embedding model on first use).
"""

import argparse
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from paperfinder.cli import open_finder
from paperfinder.studio.chat import ChatSession


def _link(p):
    if p["source_url"]:
        return p["source_url"]
    if p["doc_id"].startswith("gdrive:"):
        return "https://drive.google.com/file/d/" + p["doc_id"][7:] + "/view"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-turn chat over the paper library.")
    ap.add_argument("--folder", help="scope the chat to a folder (or beneath it)")
    ap.add_argument("--frontier", action="store_true", help="answer with the frontier model")
    ap.add_argument("--k", type=int, default=8, help="passages to retrieve per turn")
    args = ap.parse_args()

    finder = open_finder()
    session = ChatSession(finder, k=args.k, folder=args.folder, frontier=args.frontier)
    where = f" [{args.folder}]" if args.folder else ""
    print(f"paper-finder chat{where} | model: {'frontier' if args.frontier else 'local'} | "
          f"/reset to clear, /quit to exit")

    quit_words = {"/quit", "/q", "/exit", "quit", "exit"}
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in quit_words:
            break
        if q == "/reset":
            session.history.clear()
            print("(conversation cleared)")
            continue

        try:
            res = session.ask(q)
        except KeyboardInterrupt:
            print("\n(interrupted; back to the prompt. type /quit to exit)")
            continue
        print("\n" + (res["answer"] or "").strip())

        seen, srcs = set(), []
        for p in res["sources"]:
            if p["doc_id"] in seen:
                continue
            seen.add(p["doc_id"])
            srcs.append(p)
        if srcs:
            print("\nsources:")
            for p in srcs:
                link = _link(p)
                print(f"  - {p['title']}" + (f"  {link}" if link else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
