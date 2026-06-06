# PAPER FINDER - MEMORY BANK

**Version:** 3.0
**Status:** Tier A complete and running live against a real Google Drive corpus, end to end: scoped crawl, reference stripping, chunked semantic embeddings in Qdrant, a cross-passage relationship graph with human review, and a self-maintaining daily run on macOS launchd. bge-small (`STEmbedder`) and Qdrant are the live defaults now, not pending wire-up.
**Working name:** `paper-finder` (standalone; rename at will)
**Owner:** John Chan / BioRatio
**Relationship to Cortex:** Standalone tool. Cortex orchestrates and calls it; the finder does not live inside Cortex. The integration seam is a shared canonical document identity (Drive file id / path / source URL / DOI).

---

## 0. Implementation status (what exists today)

Installed as an editable package (`pip install -e .`, `paperfinder` command), so the repo is the live source Python imports. Test suites under `tests/`, each using throwaway DBs so the real index is never touched: `test_tier_a`, `test_relationship`, `test_drive_and_reconcile`, `test_filetypes`, `test_chunking`, `test_qdrant_store`, `test_connections`, `test_sectionstrip`, `test_viz`.

Layout: `paperfinder/core/` (capture, finder, sectionstrip, vectorstore), `paperfinder/graph/` (relationship, viz), plus `api.py`, `cli.py`, `sampledata.py`. Day-to-day operation runs through scripts in `examples/`.

Live and verified on the real corpus:

- **Capture** (`core/capture.py`): `LocalFolderSource` + `GoogleDriveSource`, scoped and in place over a curation folder. `crawl()` follows Google Drive shortcuts (folder and file) to their targets, keyed to target id for dedup. Authenticated live via a **service account** (unattended, no token expiry), not interactive OAuth. Reconcile archives papers no longer reachable (row and authenticated edges preserved, reversible). Local index only, never writes to Drive.
- **Core** (`core/finder.py`): SQLite job queue with durable rehydrate; parser (PDF via pypdf, Word via python-docx, PowerPoint via python-pptx, text/markdown); staged metadata pass (instant, FTS) then embed pass; hybrid search (FTS5 BM25 + dense, fused by RRF). `doc_id` is canonical identity. Embeddings are **chunk-level** (sliding window, roughly 350 words with overlap), stored per chunk and aggregated to documents by best passage. Images skipped by choice.
- **Reference stripping** (`core/sectionstrip.py`): before chunking, references / bibliography / supplementary sections are removed while the body and appendix are kept. A regex finds candidate headings; a local OpenAI-compatible LLM (Ollama) adjudicates each candidate's type; removal is section-aware (an appendix that follows the references is preserved). Opt-in via `PAPERFINDER_STRIP_SECTIONS`. Safe fallbacks: no candidates, an unreachable endpoint, or unparseable output leave the text untouched, so body is never lost. Cleaned text is persisted to `full_text` so it is not re-stripped on later passes.
- **Vector store** (`core/vectorstore.py`): `VectorStore` interface + `make_store`. `BruteForceStore` (dev default, verified); `QdrantStore` is the live backend, keyed by opaque chunk id; `SqliteVecStore` written but unverified. The live deployment uses a dedicated Qdrant container on host port 6533.
- **Embedder**: `STEmbedder` (bge-small via sentence-transformers) is the live default, selected by `PAPERFINDER_EMBEDDER=st`. `HashingEmbedder` is the dependency-free fallback; it uses a stable hash (blake2b), not Python's salted `hash()`, so its vectors are reproducible across processes.
- **Relationship graph** (`graph/relationship.py`): provenance-bearing edges (human / inferred x candidate / authenticated / rejected). Candidate edges come from **cross-document chunk neighbours**: the nearest passage in another paper, carrying both passages as `evidence`. `record_candidate`, `authenticate`, `reject`, and `clear_candidates` (drops inferred candidates while preserving human verdicts, so a rejected pair stays suppressed). Keyed by `doc_id`; survives re-embed and rebuild.
- **Connection engine** (`finder.propose_connections`, `finder.build_graph_candidates`): for each document, find the nearest passages in other documents, keep each other document's best passage pair, and record candidate edges. Decoupled from the graph module by duck typing.
- **Visualization + review** (`graph/viz.py`, `examples/show_graph.py`): `render_html` produces an interactive vis-network page; `build_viz` writes the static file used by the automation. Edge tooltips show the connecting passages; a score-threshold slider hides weak links; labels are compacted and wrapped; clicking a node opens its source. `show_graph.py` stands up an ephemeral local stdlib HTTP server (no Flask dependency) so edges can be Authenticated or Rejected by click, writing to the relationship DB, then stops itself on "Done" or Ctrl-C.
- **Query API** (`api.py`): `/search`, `/document/{id}`, `/graph` for Cortex.
- **CLI** (`cli.py`): `sample | backfill | poll | search | viz | serve`. Reads `.env`.

Verified properties: backfill indexes a folder in one pass; just-dropped docs are findable from the metadata pass before embedding; chunking finds content buried past the single-vector truncation horizon; reference stripping removes bibliography-driven edges from the graph while preserving genuine content ties (a spurious IBD / IL-1a link became one grounded in shared NF-kB / MAPK / TNFa content); human-verified edges survive a full re-embed and rebuild; the live Drive crawl follows a real shortcut and indexes the target in place.

---

## 1. Purpose

Semantic + metadata recall over a personal document repository so already-collected material on a topic can be found fast, even when scattered across many project folders and a Google Drive. Secondary payoff: surfacing connections across papers. Driving example: "I researched patient sentiment toward AI chatbots a few days ago and found good papers, but I do not know which folder they are in." The tool answers "what do I already have on X, and where is it," and "which of my papers connect."

## 2. Scope boundary (what this is NOT)

- A find / recall / connect tool, not a deep-reading tool. Deep reading is the literature pipeline's job; the finder hands a document identity to the pipeline (via Cortex) when depth is wanted.
- The finder and the literature pipeline keep separate indexes (different embedding models, different jobs). They agree only on canonical document identity, which is the integration seam.

## 3. Core architecture decisions

1. **Three separate concerns.** Finder (recall / connect), literature pipeline (deep read), Cortex (orchestration). Linked on demand, not merged.
2. **Staged ingestion.** Metadata pass now (findable within minutes), embed pass after (full semantic recall).
3. **Deterministic pipeline, with one local-LLM step.** Detection, parsing, chunking, embedding, upsert are a plain pipeline. The only LLM in the path is reference-section adjudication during ingest, run locally (Ollama) so the pipeline stays offline, free, and reproducible. Connection suggestion is geometric (chunk neighbours), not an LLM.
4. **Chunking over whole-document vectors.** A single 512-token-truncated vector missed buried content and produced weak connections. Chunk-level embeddings find the matching passage and power passage-level connection evidence. Chosen because connections and serendipitous recall are the goal and the corpus is heading toward thousands of papers.
5. **Qdrant as the live dense store.** Matches the rest of the stack (always-on container). Brute-force remains the dev/test scaffold.
6. **Reference stripping before chunking.** Bibliographies look alike across papers (shared citations, formatting) and manufactured high-similarity edges. Stripping them, while keeping the appendix, makes connections content-driven. A small local model (Qwen 7-8B) is enough; the task is easy.
7. **Graph from chunk neighbours with passage evidence.** Candidate edges are the nearest cross-document passage pair, stored with both passages so a human can see why two papers connect before authenticating.
8. **Ephemeral review server.** The interactive graph is served by a short-lived local stdlib server only during a review session, not an always-on service, and not a separate terminal step.
9. **Two pluggable interfaces** (capture-source, vector-store) keep Tier A to Tier B additive rather than a rewrite.

## 4. Pipeline (current, live)

```
Drive (curation folder)
  -> sync (service account crawl + reconcile)
  -> metadata pass (instant, FTS)
  -> reference strip (local LLM, opt-in)        [core/sectionstrip.py]
  -> chunk (sliding window) + embed (bge-small) [core/finder.py]
  -> Qdrant (per-chunk vectors, port 6533)      [core/vectorstore.py]
  -> connection engine (cross-doc chunk neighbours)
  -> relationship graph (candidate edges + passage evidence)
  -> human review (authenticate / reject)       [examples/show_graph.py]
  -> static graph HTML (regenerated daily)       [graph/viz.py]
```

## 5. Operations

- **`examples/daily_run.py`**: the once-a-day pipeline. Sync (with stripping), clear stale inferred candidates, rebuild the graph, regenerate `paper_graph.html`. Loads `.env` itself so it runs the same under launchd. A marker at `~/.paperfinder/last_run` limits it to one real run per day. Defers without marking done if Ollama or Qdrant are not up, so a later run retries rather than ingesting unstripped papers.
- **`examples/daily_run.py --force`**: manual trigger. Same pipeline, ignores the daily marker (use after adding papers). Readiness still enforced.
- **`examples/show_graph.py`**: interactive review session (ephemeral server, click to authenticate / reject, click a node to open the source, "Done reviewing" to stop).
- **`examples/build_graph.py`**: rebuild and print the candidate graph with evidence, for manual inspection.
- **`examples/drive_sync.py`**: sync only (called by `daily_run` as a subprocess).
- **Scheduling**: LaunchAgent `com.bioratio.paperfinder.daily` (RunAtLoad + 3h StartInterval; the daily gate keeps it to one real run). Log at `~/Library/Logs/paperfinder-daily.log`. Template in `examples/com.bioratio.paperfinder.daily.plist`; `install_automation.sh` generates the filled-in copy. This replaced the old fixed 2:30am `...sync` agent, which only fired when awake and logged in.
- **Qdrant**: dedicated container, e.g. `docker run -d --name paperfinder-qdrant --restart unless-stopped -p 6533:6333 -p 6534:6334 -v paperfinder_qdrant_storage:/qdrant/storage qdrant/qdrant`.
- **Ollama** (for stripping): a small Qwen (the architecture the MLX backend accelerates). Enable MLX with `OLLAMA_USE_MLX=1` set for the process that runs the server; for the menu-bar app use `launchctl setenv OLLAMA_USE_MLX 1` then relaunch. MLX support is per-architecture (Qwen yes, Llama falls back to Metal).

## 6. Config (.env or environment)

| var | values | default |
|-----|--------|---------|
| `PAPERFINDER_DB` | path | `paperfinder.db` |
| `PAPERFINDER_REL_DB` | path | `relationships.db` |
| `PAPERFINDER_EMBEDDER` | `hashing` \| `st` | `hashing` (live: `st`) |
| `PAPERFINDER_VECTOR_STORE` | `bruteforce` \| `sqlite-vec` \| `qdrant` | `bruteforce` (live: `qdrant`) |
| `PAPERFINDER_QDRANT_URL` | URL | `http://localhost:6533` |
| `PAPERFINDER_QDRANT_COLLECTION` | name | `paperfinder_chunks` |
| `PAPERFINDER_SA_KEY` | path | `service_account.json` |
| `PAPERFINDER_DRIVE_FOLDERS` | comma list | `MyResearch` |
| `PAPERFINDER_STRIP_SECTIONS` | `1` to enable | unset (off; live: on) |
| `PAPERFINDER_LLM_URL` | OpenAI-compatible base URL | `http://localhost:11434/v1` |
| `PAPERFINDER_LLM_MODEL` | model tag | `llama3.1:8b` (live: a small Qwen) |
| `PAPERFINDER_GRAPH_HTML` | path | `paper_graph.html` |
| `PAPERFINDER_REVIEW_PORT` | port | `8765` |
| `HF_HUB_OFFLINE` | `1` to avoid network model lookups | unset |

## 7. Tiers

- **Tier A (built, live).** Everything above, on the Mac, self-maintaining via launchd when the machine is on and the services are up. The 2:30am idea was dropped in favour of run-at-login plus interval with a once-per-day gate, since a personal laptop is not a server.
- **Tier B (later).** Relocate the cheap always-on parts (poller, queue, metadata pass, index, query API) to the Jetson; Mac stays the embed worker; AWS optional on-demand batch. A to B is relocation behind the two interfaces, not a rewrite.
- **Tier C (rejected).** Always-on real-time cloud embedding. The queue already guarantees "eventually," and recall does not need sub-minute latency.

## 8. Hardware notes

- Mac: M5 Max, 64GB. Runs bge-small and the small Qwen comfortably (the 27B is fine as a one-off but overkill for stripping). Ollama 0.19+ uses the MLX backend on Apple Silicon (32GB+), which the M5 Max accelerates via its GPU neural accelerators.
- Jetson (reComputer J1020 v2, 4GB, JetPack 4.6.1): poller / queue / metadata / index host only. Never the embedder.

## 9. Success criteria (Tier A / v0) - status

1. Topic query returns the right documents above noise. **Met** (with bge-small + chunking).
2. A just-dropped item is findable via the metadata pass within minutes. **Met.**
3. Results return a Drive link + canonical identity for hand-off. **Met.**
4. Backfill indexes the existing corpus with no manual per-file work. **Met.**
5. (Added) Connections are content-driven, not bibliography artifacts, and reviewable. **Met** (stripping + chunk-neighbour graph + review).

## 10. Deferred / open (by design)

- Embedding model upgrade beyond bge-small given 64GB headroom (bge-large / mxbai / nomic): measure on the real corpus first.
- `sqlite-vec` validation; batch-upsert optimization for large Qdrant backfills.
- Image OCR / vision captions; native Google Docs export.
- Citation extraction from references for the graph (would require capturing references before stripping rather than after).
- Idea / concept nodes; descriptors on edges; section-aware chunking.
- Tier B relocation; AWS on-demand batch worker.
- Cross-domain weak ties (non-biomedical papers linking on generic ML vocabulary) are accepted as honest low signal, not pruned.

## 11. Hard-won lessons / gotchas

- Aliases must be Google Drive **shortcuts**, not macOS Finder aliases (the latter sync as opaque `drive-fs.osx.alias` the API cannot resolve).
- Sharing a folder with the service account from a normal browser can hang on extension interference; an incognito window works.
- `daily_run.py` loads `.env` itself, so the LaunchAgent does not need to replicate config.
- Stripping silently no-ops if Ollama is down, so `daily_run` defers (does not mark the day done) when it is not ready.
- `reembed_all` deletes a document's old chunks from Qdrant before re-adding, so a re-embed does not leave orphaned (un-stripped) vectors.
- Editable install: the repo is the imported source. A stray copy in the wrong directory (for example a top-level `graph/`) is an orphan and should be removed.
- Repo hygiene: `paper_graph.html`, `install_*.sh`, `*.db`, `graph_viz*.html`, caches, and secrets are gitignored or removed; only the package, examples, tests, docs, and config templates are tracked.

## 12. Repo layout

```
paperfinder/        core/ (capture, finder, sectionstrip, vectorstore)
                    graph/ (relationship, viz)
                    api.py, cli.py, sampledata.py
examples/           daily_run, drive_sync, show_graph, build_graph,
                    drive_example, diagnose_drive, check_service_account,
                    com.bioratio.paperfinder.daily.plist (template)
tests/              one suite per concern, throwaway DBs
docs/               this memory bank, RUNBOOK.md
scripts/            paperfinder-status.sh
pyproject.toml, requirements.txt, .env.example, .gitignore, README.md
```
