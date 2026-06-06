# paper-finder

Scoped semantic + keyword recall over your own documents (PDF, Word, PowerPoint,
text/markdown; Google Drive in place), so you can find what you already collected on
a topic and see how it connects. Standalone tool; Cortex orchestrates it and hands
found documents to the literature pipeline for deep reading. Design + decisions:
`docs/PAPER_FINDER_MEMORY_BANK.md`.

## Layout

```
paperfinder/
├── core/            the finder: capture → index → staged ingestion → hybrid search
│   ├── capture.py        LocalFolderSource + GoogleDriveSource (scoped, in place, alias-aware)
│   ├── finder.py         job queue, parser (PDF/Word/PowerPoint/text), embedder, metadata/embed passes, search, reconcile
│   └── vectorstore.py    VectorStore interface + BruteForce / sqlite-vec / Qdrant
├── graph/           the relationship layer
│   ├── relationship.py   provenance-bearing edges (human/inferred × candidate/authenticated/rejected)
│   └── viz.py            interactive graph visualisation
├── api.py           query API Cortex calls (/search, /document, /graph)
├── cli.py           command line (sample / backfill / poll / search / viz / serve)
└── sampledata.py    sample corpus generator
tests/               test_tier_a · test_relationship · test_drive_and_reconcile · test_filetypes
examples/            drive_example.py · diagnose_drive.py (you complete the OAuth step)
docs/                memory bank
```

## Install

```bash
pip install -e .            # core deps + the `paperfinder` command
cp .env.example .env        # then edit if you like (it's gitignored)
```

Optional extras: `pip install -e ".[office]"` (index .docx/.pptx), `".[st]"` (real
embeddings), `".[sqlitevec]"`, `".[qdrant]"`, `".[drive]"`, `".[dev]"` (test-only httpx).

## Verify

```bash
pip install -e ".[office,dev]"     # office enables the filetypes test; dev enables the API check
python3 tests/test_tier_a.py
python3 tests/test_relationship.py
python3 tests/test_drive_and_reconcile.py
python3 tests/test_filetypes.py
```
All four should print `ALL CHECKS PASSED`. (Each test uses its own throwaway DB, so
none of them touch your real index. The API check in `test_tier_a` skips cleanly if
the `dev` extra isn't installed.)

## Use

```bash
paperfinder sample my_inbox          # or drop your own PDFs/text into a folder
paperfinder backfill my_inbox        # index in place (+ reconcile removals)
paperfinder search "patient sentiment toward AI chatbots"
paperfinder viz my_graph.html        # relationship graph from the index
paperfinder poll my_inbox            # later: index only what's new
paperfinder serve                    # query API at http://127.0.0.1:8000
```

## Config (.env or environment)

| var | values | default |
|-----|--------|---------|
| `PAPERFINDER_DB` | path | `paperfinder.db` |
| `PAPERFINDER_REL_DB` | path | `relationships.db` |
| `PAPERFINDER_EMBEDDER` | `hashing` \| `st` | `hashing` |
| `PAPERFINDER_VECTOR_STORE` | `bruteforce` \| `sqlite-vec` \| `qdrant` | `bruteforce` |
| `PAPERFINDER_STRIP_SECTIONS` | `1` to enable | unset (off) |
| `PAPERFINDER_LLM_URL` | OpenAI-compatible base URL | `http://localhost:11434/v1` |
| `PAPERFINDER_LLM_MODEL` | model tag | `llama3.1:8b` |
| `PAPERFINDER_GRAPH_HTML` | path | `paper_graph.html` |
| `PAPERFINDER_REVIEW_PORT` | port | `8765` |

The default embedder is a dependency-free lexical stand-in — fine for plumbing,
not for real semantic search. Set `PAPERFINDER_EMBEDDER=st` (after `pip install -e ".[st]"`)
for bge-small. Vector backend: `bruteforce → sqlite-vec` is a true swap (same file);
`qdrant` adds a separate service. Only `bruteforce` + `hashing` are verified here.

## Google Drive (scoped, in place)

Recommended: one **curation folder** you point the tool at. Put working folders under
it directly *and/or* drop **aliases (shortcuts)** to folders elsewhere — the crawl
follows folder and file aliases to their targets (even outside the curation folder),
keyed to the target so an aliased paper and a physical copy don't double up. **Nothing
is moved or copied;** the index stores text + an embedding + a link. See
`examples/drive_example.py` — you complete only the OAuth step (read-only scope; the
code never handles your password). No-API bridge: point `backfill` at a Drive-desktop
folder set to "available offline".

Change scope by editing the folders/aliases and re-running `backfill`; `poll` keeps
already-scoped folders current. `backfill` also **reconciles**: a paper no longer
reachable (deleted, or its folder/alias removed) is archived — dropped from search but
preserved as a row with its authenticated relationships intact, reversible on re-index.
Reconcile only touches the local index, never your Drive.

## Daily run, review, and automation

Three example scripts cover day-to-day use on top of the library.

`python3 examples/daily_run.py` runs the whole pipeline once: sync new papers from
Drive (stripping references, bibliography, and supplementary sections before
chunking), clear stale inferred candidate edges, rebuild the relationship graph,
and regenerate the static `paper_graph.html`. It reads config from `.env`, so it
behaves the same from a shell or under launchd. A marker at `~/.paperfinder/last_run`
limits it to one real run per day. If Ollama or Qdrant are not up it defers without
marking the day done, so a later run retries rather than indexing papers with
references left in.

`python3 examples/daily_run.py --force` is the manual trigger: the same pipeline,
but it ignores the once-per-day marker. Use it right after dropping new papers in
when you want them indexed now. Readiness is still enforced, so it will not run
against a down service.

`python3 examples/show_graph.py` opens an interactive review session. It stands up
a short-lived local server, opens the graph in your browser, and lets you click an
edge to Authenticate or Reject the connection (written to `relationships.db`) and
click a node to open the source paper. It stops when you click "Done reviewing" or
press Ctrl-C; nothing stays running.

Reference stripping uses a local OpenAI-compatible LLM (for example Ollama). Enable
it with `PAPERFINDER_STRIP_SECTIONS=1` and point `PAPERFINDER_LLM_URL` /
`PAPERFINDER_LLM_MODEL` at your model. A small Qwen (7-8B) is plenty for the task.

### Scheduling (macOS launchd)

A LaunchAgent runs `daily_run.py` at login and every few hours; the once-per-day
gate keeps it to a single real run. This suits a personal machine better than a
fixed clock time, which only fires when you are awake and logged in. Register and
test it with:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bioratio.paperfinder.daily.plist
rm -f ~/.paperfinder/last_run                                         # so the test run does real work
launchctl kickstart -k gui/$(id -u)/com.bioratio.paperfinder.daily   # run once now
tail -n 20 ~/Library/Logs/paperfinder-daily.log
```

To stop or remove it: `launchctl bootout gui/$(id -u)/com.bioratio.paperfinder.daily`
then delete the plist.

## Notes / current limits (deferred by design)

- Verified live against a real Drive: scoped crawl, folder traversal, Drive-shortcut
  following, in-place PDF/Word/PowerPoint extraction, and reconcile. Verified locally:
  `BruteForceStore` + `HashingEmbedder`, staged ingestion, the relationship layer.
  Still to validate against your installed versions: `STEmbedder`, `SqliteVecStore`,
  `QdrantStore` (only `bruteforce` + `hashing` are exercised by the tests).
- Indexes PDF, Word (`.docx`), PowerPoint (`.pptx`), and text/markdown. **Images are
  skipped by choice** (no text to embed) — revisit with OCR or a vision caption if needed.
  Native Google Docs would need an export step (not in v0).
- **Aliases must be Google Drive shortcuts, not macOS Finder aliases.** A Finder alias
  syncs as an opaque `application/drive-fs.osx.alias` the Drive API can't resolve; the
  crawl warns and skips it. Make shortcuts in the Drive web UI (right-click → Organize
  → Add shortcut).
- `credentials.json`, `token.json`, `.env`, and `*.db` are gitignored — never commit them.
- descriptors / idea-nodes are not built yet. Connections are authenticated or
  rejected interactively in the review session (`examples/show_graph.py`), or via
  the relationship layer's function calls; `paper_graph.html` is a read-only view.
- Adding a brand-new alias takes effect on the next `backfill`, not via `poll`.
