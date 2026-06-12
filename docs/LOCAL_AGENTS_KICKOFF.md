# LOCAL AGENTS - SESSION KICKOFF

**Purpose of the next session:** explore and implement *local AI agents* driven by a
*local* LLM, and use the paper-finder platform as the testbed. Two goals at once:
(1) understand how a local-agent implementation works end to end, and (2) exercise it
against real paper-finder capabilities. Frontier models stay as an optional fallback,
not the default.

**Owner:** John Chan / BioRatio. **Stack:** Mac M5 Max 64GB, local Docker + Ollama,
Python 3.12, venv per project. **Conventions:** no em-dashes; minimum code, nothing
speculative; touch only what you must; surface tradeoffs before building; ask one
question at a time; define success criteria and verify in a sandbox copy before delivery;
prefer complete replacement files; deliver via self-installing scripts to import-derived paths.

## 1. Where paper-finder is now (read the memory bank first)
Full detail in `docs/PAPER_FINDER_MEMORY_BANK.md` (v4.0). In short: Tier A ingestion +
a relationship graph + a studio/graph-window layer with chat (ask-to-highlight),
cluster-to-synthesis with background PDF export, and graph-structure reading. Runs live
against a real Google Drive corpus (tens of papers today).

## 2. Why agents next (the motivation)
The graph-reading slice injects a deterministic graph digest into the chat prompt, so the
LLM can answer "how many nodes / what are X's neighbours" accurately. But it is context
injection: the answers are correct yet wooden, with no flexibility and no discovery. The
model cannot decide to look something up, chain steps, run a nearest-neighbour search,
synthesize a cluster, then refine. An agent loop is what turns these fixed capabilities
into flexible, exploratory behavior.

## 3. The tool surface already sitting in the codebase
These are real, tested functions that could become agent tools with thin wrappers. No new
capability is needed to start; the work is the loop and the protocol, not new features.
- Retrieval: `studio/chat.retrieve(finder, query, k, folder)` -> top-k passages.
- Graph stats: `graph/stats.graph_digest(export)`; `RelationshipGraph.export_graph()`;
  per-node neighbours/degree are derivable from the export.
- Study set + synthesis: `studio/studyset.build_studyset(finder, rel, ids)`,
  `studio/synthesis.synthesize(studyset, frontier, complete)`,
  `studio/export.synthesis_to_pdf(md, path, title, titles)`.
- Graph mutation: `RelationshipGraph.authenticate/reject`; candidate proposal
  `PaperFinder.build_graph_candidates(rel, k)`.
- Folder selectors: `studio/studyset.ids_for_folder(finder, folder)`.
- The completion seam every tool/agent should route through: `studio/llm.complete(prompt,
  system, frontier, max_tokens, timeout)` (local by default, Anthropic when frontier=True).

## 4. Local-implementation options to weigh (first session decisions)
- **Native tool/function calling via Ollama** (`/v1/chat/completions` `tools` param). Cleanest
  if the local model is reliable at it. Candidates to test: Qwen2.5/Qwen3 instruct, Llama 3.1.
  Risk: local tool-calling reliability varies; needs evaluation.
- **ReAct-style text protocol** (model emits "Thought / Action / Action Input", we parse and
  execute, feed back "Observation"). More robust on weak tool-callers, fully under our control,
  no dependency on the model's tool schema. More parsing code.
- **Minimal hand-rolled loop vs a framework.** Given the conventions, lean to a small loop in
  a new `studio/agent.py` over pulling in a heavy framework; reuse the `complete` seam.
- **Where the agent runs in the UI.** Easiest testbed is the `--chat` graph window: replace the
  single-shot answer with an agent loop that can call the tools above, then keep the existing
  highlight/synthesis hooks for its actions.

## 5. Candidate first slice (to confirm next session, not pre-decided)
A minimal local "graph agent": given a question, the agent decides among a small tool set
(graph-stats, retrieval, synthesize) using the local model, executes the chosen tool
deterministically, and composes an answer. This directly replaces the wooden injection with
tool use, all local, and reuses the highlight + synthesis plumbing already wired in the window.
Success criteria would include: a structural question routes to the graph tool; a content
question routes to retrieval; a "compare these" routes to synthesis; the loop terminates; and
it degrades to a plain answer if the local model cannot pick a tool.

## 6. Open questions to resolve (one at a time, next session)
- Which local model to standardize on for tool selection, and is its native tool-calling good
  enough or do we use ReAct?
- How many tools to expose in the first loop (start with 2-3?).
- Loop budget / termination (max steps, max tokens) and how to surface intermediate steps in the UI.
- Whether the agent shares `ChatSession` history or runs as a separate mode.
- Evaluation: how do we test agent behavior deterministically (stubbed tools + scripted model
  outputs, mirroring the current dep-light test style)?

## 7. Files to share so the next session has full context
Simplest: upload a fresh repo archive so all code + docs come along. From the repo root:

    git archive --format=zip -o paperfinder_review.zip HEAD

(or zip the working tree). That single zip carries everything below. If sharing individual
files instead, these are the ones the agents work will touch or reference:
- `docs/LOCAL_AGENTS_KICKOFF.md`  (this brief)
- `docs/PAPER_FINDER_MEMORY_BANK.md`  (full platform state, v4.0)
- `paperfinder/studio/llm.py`  (the completion seam agents route through)
- `paperfinder/studio/chat.py`  (RAG engine, ChatSession, graph_text injection)
- `paperfinder/graph/stats.py`  (graph digest / neighbours)
- `paperfinder/graph/relationship.py`  (graph API: export, neighbours, authenticate/reject)
- `paperfinder/studio/studyset.py` and `paperfinder/studio/synthesis.py`  (synthesis tools)
- `paperfinder/core/finder.py`  (search/retrieve, build_graph_candidates)
- `examples/show_graph.py`  (the --chat server: chat, synthesis, graph-reading integration)
- `pyproject.toml`  (deps, entry points, package discovery)
- the test files under `tests/` (the dep-light testing pattern to mirror for agent tests)

## 8. How to open the next session
Start by stating the goal from section "Purpose," point me at the uploaded zip, and ask me
to read `LOCAL_AGENTS_KICKOFF.md` then `PAPER_FINDER_MEMORY_BANK.md`. Then we pick the first
decision from section 6 and proceed one step at a time.
