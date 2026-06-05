#!/usr/bin/env python3
"""
drive_sync.py — unattended nightly Drive sync via a service account.

No browser, no token, no expiry. Authenticates with service_account.json, runs the
in-place backfill (new files enqueued + embedded, existing skipped, removed archived),
logs one summary line, and exits non-zero on failure so launchd logs show why.

Designed to be run by launchd. Test it by hand first:
    python3 examples/drive_sync.py

Config (via .env or environment):
    PAPERFINDER_SA_KEY         path to the service-account JSON  (default service_account.json)
    PAPERFINDER_DRIVE_FOLDERS  comma-separated folder names      (default MyResearch)
    PAPERFINDER_DB / _EMBEDDER / _VECTOR_STORE   as everywhere else
"""

import os
import sys
import time

from paperfinder.core.capture import GoogleDriveSource, find_folder_ids
from paperfinder.cli import open_finder   # env-configured finder (DB + embedder + store)

KEY = os.environ.get("PAPERFINDER_SA_KEY", "service_account.json")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDERS = [f.strip() for f in
           os.environ.get("PAPERFINDER_DRIVE_FOLDERS", "MyResearch").split(",") if f.strip()]


def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(KEY, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _qdrant_problem():
    """If the vector store is Qdrant, return an error string when it's unreachable,
    else None. Keeps the nightly log readable instead of dumping a stack trace."""
    if os.environ.get("PAPERFINDER_VECTOR_STORE", "bruteforce") != "qdrant":
        return None
    url = os.environ.get("PAPERFINDER_QDRANT_URL", "http://localhost:6533")
    try:
        from qdrant_client import QdrantClient
        QdrantClient(url=url, timeout=5).get_collections()
        return None
    except Exception as e:
        return (f"Qdrant not reachable at {url} ({e}); "
                f"is the container up?  docker start paperfinder-qdrant")


def main() -> int:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        svc = drive_service()
    except Exception as e:
        print(f"[{stamp}] AUTH FAILED ({KEY}): {e}", flush=True)
        return 2

    resolved = find_folder_ids(svc, FOLDERS)
    ids = [i for v in resolved.values() for i in v]
    missing = [name for name, v in resolved.items() if not v]
    if missing:
        print(f"[{stamp}] WARNING not visible to the service account: {missing} "
              f"-- share them with the SA email", flush=True)
    if not ids:
        print(f"[{stamp}] nothing to sync (no folders resolved)", flush=True)
        return 1

    problem = _qdrant_problem()
    if problem:
        print(f"[{stamp}] QDRANT NOT READY: {problem}", flush=True)
        return 4

    try:
        pf = open_finder()
        stats = pf.run_backfill(GoogleDriveSource(svc, ids), source_key="gdrive", reconcile=True)
        pf.run_metadata_pass()
        pf.run_embed_pass()
        docs = pf.all_documents()
        active = sum(1 for d in docs if not d["archived"])
        archived = len(docs) - active
    except Exception as e:
        print(f"[{stamp}] SYNC FAILED: {e}", flush=True)
        return 3

    print(f"[{stamp}] sync ok | folders={FOLDERS} | {stats} "
          f"| active: {active} archived: {archived} "
          f"| embedder={pf.embedder.model_name} | store={pf.store.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
