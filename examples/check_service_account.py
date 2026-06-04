#!/usr/bin/env python3
"""Verify a service account can read your shared Drive folder (no browser, no token).

Prereqs:
  1. Create a service account in your GCP project; download its JSON key.
  2. Save the key as service_account.json in the repo root (a secret — gitignore it).
  3. In Drive, share your curation folder AND every shortcut-target folder with the
     service account's email (...@....iam.gserviceaccount.com); Viewer is enough.

Run from the repo root:
  python3 examples/check_service_account.py            # folder "MyResearch"
  python3 examples/check_service_account.py "My Folder"

Output is safe to paste back (names + types). Do NOT paste service_account.json.
"""

import sys

from paperfinder.core.capture import find_folder_ids

KEY = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = ("nextPageToken, files(id,name,mimeType,webViewLink,"
          "shortcutDetails(targetId,targetMimeType))")


def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(KEY, scopes=SCOPES)
    return build("drive", "v3", credentials=creds), creds.service_account_email


def listing(svc, fid):
    out, page = [], None
    while True:
        res = svc.files().list(q=f"'{fid}' in parents and trashed=false",
                               fields=FIELDS, pageToken=page, pageSize=200).execute()
        out += res.get("files", [])
        page = res.get("nextPageToken")
        if not page:
            return out


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "MyResearch"
    svc, email = get_service()
    print(f"service account: {email}")
    ids = find_folder_ids(svc, [folder]).get(folder, [])
    if not ids:
        print(f"  !! {folder!r} is not visible to the service account.")
        print(f"     Share that folder with {email} (Viewer) in Drive, then retry.")
        return 1
    print(f"resolved {folder!r} -> {ids}")
    for fid in ids:
        print(f"\n# children of {folder}:")
        for f in listing(svc, fid):
            print(f"  - {f.get('name')!r} [{f.get('mimeType')}]")
            sd = f.get("shortcutDetails") or {}
            tid = sd.get("targetId")
            if tid and sd.get("targetMimeType") == FOLDER_MIME:
                kids = listing(svc, tid)
                if not kids:
                    print(f"    -> shortcut target NOT accessible — "
                          f"share that folder with {email} too")
                for k in kids:
                    print(f"    * {k.get('name')!r} [{k.get('mimeType')}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
