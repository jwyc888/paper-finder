"""Cross-paper synthesis generator.

Map-reduce so it fits a small local-model context window and works the same on a
frontier model: summarize each paper (map), then synthesize the summaries plus the
already-found connection passages into a structured cross-paper synthesis (reduce).

The `complete` callable is injectable so tests can run without a live model.
"""

from paperfinder.studio import llm as _llm

PER_PAPER_CHARS = 12000          # trim each paper for the map step (bounds local context)

_MAP_SYSTEM = "You are a careful research assistant. Summarize a single paper factually."
_REDUCE_SYSTEM = (
    "You are a research librarian writing a cross-paper synthesis for a domain expert. "
    "Ground every statement in the provided summaries and connecting passages. Do not "
    "invent findings. Refer to specific works by their title.")


def _map_prompt(paper) -> str:
    return ("Summarize this paper in 6 to 10 bullet points covering its problem, methods, "
            "key results, and stated limitations. Be specific and factual; no preamble.\n\n"
            f"Title: {paper.title}\n\n{paper.text[:PER_PAPER_CHARS]}")


def _reduce_prompt(studyset, summaries) -> str:
    parts = ["# Papers in this set"]
    for p in studyset.papers:
        parts.append(f"- {p.title}" + (f"  [{p.folder}]" if p.folder else ""))

    parts.append("\n# Per-paper summaries")
    for p in studyset.papers:
        parts.append(f"## {p.title}\n{(summaries.get(p.doc_id) or '').strip()}")

    if studyset.connections:
        parts.append("\n# Connections already detected between these papers "
                     "(passage-level overlaps)")
        for c in studyset.connections:
            tag = f" (via: {', '.join(c.descriptors)})" if c.descriptors else ""
            parts.append(f"- {c.a_title}  <->  {c.b_title}{tag}")
            if c.a_passage:
                parts.append(f"    from {c.a_title}: {c.a_passage[:400]}")
            if c.b_passage:
                parts.append(f"    from {c.b_title}: {c.b_passage[:400]}")
    else:
        parts.append("\n# Connections already detected between these papers\n(none recorded)")

    parts.append(
        "\n# Task\n"
        "Write a cross-paper synthesis as Markdown with these sections:\n"
        "1. Shared topic and scope: the problem space these papers jointly address.\n"
        "2. Shared themes and common ground: methods, framings, or findings in common.\n"
        "3. Points of agreement: where findings or conclusions reinforce one another.\n"
        "4. Points of divergence: where they disagree, use contrasting approaches, or "
        "reach different results.\n"
        "5. Gaps and open questions: what is missing across the set or worth investigating next.\n"
        "6. How they fit together: a short suggested grouping or reading order.\n"
        "Cite specific papers by title. If a section has no support in the material, say so briefly.")
    return "\n".join(parts)


def synthesize(studyset, frontier: bool = False, complete=None, max_tokens: int = 2000) -> str:
    """Produce the cross-paper synthesis (Markdown). complete defaults to the live LLM seam."""
    complete = complete or _llm.complete
    if not studyset.papers:
        return "No papers in the study set."
    summaries = {}
    for p in studyset.papers:
        summaries[p.doc_id] = complete(_map_prompt(p), system=_MAP_SYSTEM,
                                       frontier=frontier, max_tokens=700)
    return complete(_reduce_prompt(studyset, summaries), system=_REDUCE_SYSTEM,
                    frontier=frontier, max_tokens=max_tokens)
