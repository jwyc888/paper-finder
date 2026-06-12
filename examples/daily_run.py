#!/usr/bin/env python3
"""
daily_run.py - the once-a-day (or on-demand) pipeline.

Steps: sync new papers from Drive (which strips references), clear stale inferred
candidates, rebuild the relationship graph, and regenerate the static graph HTML.

Built to be launched by a LaunchAgent at login and on an interval. It only does
real work once per day (a marker file under ~/.paperfinder), and it DEFERS without
marking the day done if Ollama is not up yet, so a later run picks it up rather
than ingesting papers with references left in. Run it by hand with --force to
bypass the once-per-day gate (readiness is still enforced, so it won't run against
a down service).

    python3 examples/daily_run.py            # respects the once-per-day marker
    python3 examples/daily_run.py --force    # run now regardless of the marker
    python3 examples/daily_run.py --folders "MyResearch,Shared"  # target other Drive folders

The synced Drive folder defaults to MyResearch; override it with --folders (comma
separated) here or with PAPERFINDER_DRIVE_FOLDERS in the environment, so the tool
can point at any folder and be reused by others.

Config is read from the repo .env, so it behaves the same under launchd as it does
from a shell where you ran `source .env`.
"""

import os
import subprocess
import sys
import time
import urllib.request
from datetime import date

MARKER = os.path.expanduser("~/.paperfinder/last_run")


def repo_dir() -> str:
    import paperfinder
    return os.path.dirname(os.path.dirname(paperfinder.__file__))


def load_env(repo: str) -> None:
    """Minimal .env loader: KEY=value lines, comments ignored. Does not override
    variables already present in the environment (so launchd or shell wins)."""
    path = os.path.join(repo, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def already_done_today() -> bool:
    try:
        return open(MARKER).read().strip() == date.today().isoformat()
    except FileNotFoundError:
        return False


def mark_done() -> None:
    os.makedirs(os.path.dirname(MARKER), exist_ok=True)
    with open(MARKER, "w") as f:
        f.write(date.today().isoformat())


def ollama_ready() -> bool:
    base = os.environ.get("PAPERFINDER_LLM_URL", "http://localhost:11434/v1").split("/v1")[0]
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def run_sync(repo: str, folders: str = None) -> int:
    """Run the existing sync entry point as a subprocess; it strips references in
    the embed pass and returns 0 on success (4 if Qdrant is not ready, etc.)."""
    script = os.path.join(repo, "examples", "drive_sync.py")
    cmd = [sys.executable, script]
    if folders:
        cmd += ["--folders", folders]
    return subprocess.run(cmd).returncode


def rebuild_graph_and_viz(repo: str):
    from paperfinder.cli import open_finder
    from paperfinder.graph.relationship import RelationshipGraph
    from paperfinder.graph.viz import build_viz
    from paperfinder.graph.stats import write_graph_stats
    rel_db = os.environ.get("PAPERFINDER_REL_DB", "relationships.db")
    out = os.environ.get("PAPERFINDER_GRAPH_HTML", os.path.join(repo, "paper_graph.html"))
    pf = open_finder()
    rg = RelationshipGraph(rel_db)
    removed = rg.clear_candidates()
    proposed = pf.build_graph_candidates(rg, k=5)
    export = rg.export_graph(include_candidates=True)
    build_viz(export, out)
    stats = write_graph_stats(export)
    return removed, proposed, out, stats


def main() -> int:
    argv = sys.argv[1:]
    force = "--force" in argv
    folders = None
    if "--folders" in argv:
        i = argv.index("--folders")
        if i + 1 < len(argv):
            folders = argv[i + 1]
    repo = repo_dir()
    load_env(repo)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    if already_done_today() and not force:
        print(f"[{stamp}] already ran today; skipping (use --force to run now)", flush=True)
        return 0

    # references stripping needs Ollama; defer WITHOUT marking done so a later run
    # retries once it is up, rather than embedding papers with references intact
    if os.environ.get("PAPERFINDER_STRIP_SECTIONS") and not ollama_ready():
        print(f"[{stamp}] Ollama not ready; deferring (will retry on a later run)", flush=True)
        return 0

    rc = run_sync(repo, folders)
    if rc != 0:
        print(f"[{stamp}] sync did not complete (drive_sync rc={rc}); deferring", flush=True)
        return 0

    removed, proposed, out, stats = rebuild_graph_and_viz(repo)
    mark_done()
    print(f"[{stamp}] daily run ok | candidates cleared={removed} proposed={proposed} "
          f"| graph html: {out} | graph stats: {stats}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
