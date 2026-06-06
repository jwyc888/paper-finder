"""Multi-turn RAG chat over the paper library.

UI-agnostic engine. A front-end (CLI, a standalone window, or the graph GUI) holds
a ChatSession and calls .ask(question); the engine retrieves passages from the
existing index, rewrites follow-ups into standalone queries so multi-turn works,
answers grounded in the retrieved passages, and returns the answer plus the source
doc_ids (so a GUI can highlight the matching nodes).

The `complete` callable is injectable so tests run without a live model. Answering
honours the frontier flag; the small follow-up rewrite always uses the local model.
"""

from paperfinder.studio import llm as _llm

_REWRITE_SYSTEM = ("You rewrite a follow-up question into a single standalone search query. "
                   "Output only the query, with no preamble or quotation marks.")
_ANSWER_SYSTEM = ("You are a research assistant answering questions about the user's own paper "
                  "library. Use only the provided passages. Cite the papers you rely on by their "
                  "title in square brackets, for example [Some Paper Title]. If the passages do "
                  "not contain the answer, say so plainly and do not speculate.")


def retrieve(finder, query: str, k: int = 8, folder=None) -> list:
    """Top-k passages (chunks) for a query, with source identity. Honours a folder scope."""
    qv = finder.embedder.embed(query)
    hits = sorted(finder.store.query(qv, max(k * 4, k)), key=lambda x: x[1], reverse=True)
    out = []
    for cid, score in hits:
        row = finder.conn.execute(
            "SELECT doc_id, text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if not row:
            continue
        d = finder.get_document(row["doc_id"])
        if not d or d["archived"]:
            continue
        if folder:
            df = d.get("folder") or ""
            if df != folder and not df.startswith(folder + "/"):
                continue
        out.append({
            "doc_id": row["doc_id"],
            "title": d["title"] or row["doc_id"],
            "source_url": d["source_url"] or "",
            "folder": d.get("folder") or "",
            "text": row["text"] or "",
            "score": float(score),
        })
        if len(out) >= k:
            break
    return out


def _rewrite_prompt(history, question: str) -> str:
    convo = "\n".join(f"{role.upper()}: {text}" for role, text in history[-6:])
    return (f"Conversation so far:\n{convo}\n\nFollow-up: {question}\n\n"
            "Rewrite the follow-up as one standalone search query that folds in the needed "
            "context from the conversation. Output only the query.")


def _answer_prompt(passages, history, question: str) -> str:
    parts = []
    if history:
        parts.append("# Conversation so far")
        for role, text in history[-6:]:
            parts.append(f"{role.upper()}: {text}")
        parts.append("")
    parts.append("# Retrieved passages from the library")
    if passages:
        for i, p in enumerate(passages, 1):
            tag = f"  ({p['folder']})" if p["folder"] else ""
            parts.append(f"[{i}] {p['title']}{tag}")
            parts.append((p["text"] or "")[:1200])
            parts.append("")
    else:
        parts.append("(no passages retrieved)\n")
    parts.append(f"# Question\n{question}\n\n"
                 "Answer using only the passages above, citing papers by title.")
    return "\n".join(parts)


def web_sources(sources) -> list:
    """Deduped sources for a web UI: keep doc_id (for node highlighting), title, and a link."""
    seen, out = set(), []
    for p in sources or []:
        did = p.get("doc_id")
        if not did or did in seen:
            continue
        seen.add(did)
        link = p.get("source_url") or (
            "https://drive.google.com/file/d/" + did[7:] + "/view"
            if str(did).startswith("gdrive:") else "")
        out.append({"doc_id": did, "title": p.get("title") or did, "link": link})
    return out


class ChatSession:
    """Holds conversation state for multi-turn chat over the library."""

    def __init__(self, finder, k: int = 8, folder=None, frontier: bool = False, complete=None):
        self.finder = finder
        self.k = k
        self.folder = folder
        self.frontier = frontier
        self._complete = complete or _llm.complete
        self.history = []                       # list[(role, text)]

    def ask(self, question: str) -> dict:
        standalone = question
        if self.history:                        # rewrite follow-ups so retrieval has context
            rewritten = self._complete(_rewrite_prompt(self.history, question),
                                       system=_REWRITE_SYSTEM, frontier=False, max_tokens=80)
            standalone = (rewritten or "").strip() or question
        passages = retrieve(self.finder, standalone, self.k, self.folder)
        answer = self._complete(_answer_prompt(passages, self.history, question),
                                system=_ANSWER_SYSTEM, frontier=self.frontier, max_tokens=1000)
        self.history.append(("user", question))
        self.history.append(("assistant", answer))
        return {"answer": answer, "query": standalone, "sources": passages}
