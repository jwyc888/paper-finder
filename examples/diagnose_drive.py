#!/usr/bin/env python3
"""
diagnose_drive.py — show exactly what the crawl sees, to debug alias following.

Run from the repo root (reuses your token.json from drive_example):
    python3 examples/diagnose_drive.py            # uses folder "MyResearch"
    python3 examples/diagnose_drive.py "My Folder Name"

Prints each child of the folder with its mimeType and shortcutDetails, and for any
folder-shortcut, lists the target both WITHOUT and WITH all-drives flags so we can
tell a recognition failure from a permissions/shared-folder scoping issue.

Output is safe to paste back (names + types, no secrets). Do NOT paste token.json
or credentials.json.
"""

import sys

from dotenv import load_dotenv

from paperfinder.core.capture import find_folder_ids

load_dotenv()
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = ("nextPageToken, files(id,name,mimeType,webViewLink,"
          "shortcutDetails(targetId,targetMimeType))")


def get_drive_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    import os
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def listing(svc, fid, all_drives=False):
    kw = {}
    if all_drives:
        kw = dict(includeItemsFromAllDrives=True, supportsAllDrives=True, corpora="allDrives")
    out, page = [], None
    while True:
        res = svc.files().list(q=f"'{fid}' in parents and trashed=false",
                               fields=FIELDS, pageToken=page, pageSize=200, **kw).execute()
        out += res.get("files", [])
        page = res.get("nextPageToken")
        if not page:
            return out


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "MyResearch"
    svc = get_drive_service()
    ids = find_folder_ids(svc, [folder]).get(folder, [])
    print(f"resolved {folder!r} -> {ids}")
    for fid in ids:
        print(f"\n# direct children of {folder} ({fid}):")
        for f in listing(svc, fid):
            print(f"  - {f.get('name')!r}  [{f.get('mimeType')}]  shortcutDetails={f.get('shortcutDetails')}")
            sd = f.get("shortcutDetails") or {}
            tid = sd.get("targetId")
            if tid and sd.get("targetMimeType") == FOLDER_MIME:
                print(f"    -> alias target folder {tid}")
                plain = listing(svc, tid, all_drives=False)
                alld = listing(svc, tid, all_drives=True)
                print(f"       listing WITHOUT all-drives flags: {len(plain)} items")
                for k in plain:
                    print(f"          * {k.get('name')!r} [{k.get('mimeType')}]")
                print(f"       listing WITH all-drives flags:    {len(alld)} items")
                for k in alld:
                    print(f"          * {k.get('name')!r} [{k.get('mimeType')}]")
                try:
                    meta = svc.files().get(fileId=tid,
                                           fields="id,name,driveId,shared,ownedByMe",
                                           supportsAllDrives=True).execute()
                    print(f"       target meta: driveId={meta.get('driveId')} "
                          f"shared={meta.get('shared')} ownedByMe={meta.get('ownedByMe')}")
                except Exception as e:
                    print(f"       target meta error: {e}")


if __name__ == "__main__":
    main()
