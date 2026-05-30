#!/usr/bin/env python3
"""
drive_example.py — point the finder at named Google Drive folders, IN PLACE.

Nothing here moves or copies your papers. crawl() reads them where they live and
stores text + an embedding + a link back to the Drive file. Your Drive is untouched.

You complete ONE thing: the OAuth step (get_drive_service). Everything below it is
the same staged pipeline you already run locally — just a Drive source.

Prereqs:
    pip install google-api-python-client google-auth-oauthlib
    # download an OAuth client secret from your Google Cloud project -> credentials.json
"""

import os

from dotenv import load_dotenv

from paperfinder.core.finder import HashingEmbedder, PaperFinder
from paperfinder.core.capture import GoogleDriveSource, find_folder_ids

load_dotenv()

# ---- the names of YOUR Drive folders to index (subfolders are included) ----
FOLDER_NAMES = ["Papers", "Literature", "Reading"]   # <-- edit to your real folder names
DB = os.environ.get("PAPERFINDER_DB", "paperfinder.db")


def get_drive_service():
    """YOU complete this. Standard Drive OAuth — you run the consent flow once;
    Claude never handles your password or tokens."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]  # read-only: we never modify Drive
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def main():
    svc = get_drive_service()

    # names -> ids
    resolved = find_folder_ids(svc, FOLDER_NAMES)
    folder_ids = [fid for ids in resolved.values() for fid in ids]
    print("resolved folders:", resolved)
    if not folder_ids:
        raise SystemExit("no matching folders — check FOLDER_NAMES")

    source = GoogleDriveSource(svc, folder_ids)
    pf = PaperFinder(DB, embedder=HashingEmbedder())   # PAPERFINDER_EMBEDDER=st for real recall

    # one-time, in-place backfill of everything reachable from those folders
    # (follows aliases; reconcile archives anything you've since removed)
    stats = pf.run_backfill(source, source_key="gdrive", reconcile=True)
    pf.run_metadata_pass()        # instant: keyword-findable now
    pf.run_embed_pass()           # background: full text + vectors
    print(f"backfill in place: {stats}; active docs: "
          f"{sum(1 for d in pf.all_documents() if not d['archived'])}")

    # later, run this again (cron / launchd) to pick up only NEW or changed papers:
    #   added = pf.run_capture(source, source_key="gdrive")
    #   pf.run_metadata_pass(); pf.run_embed_pass()

    for r in pf.search("patient sentiment toward AI chatbots", k=5):
        print(f"  {r['title']}  -> {r['source_url']}")


if __name__ == "__main__":
    main()
