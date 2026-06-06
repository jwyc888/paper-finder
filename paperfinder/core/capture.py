"""
capture.py — the capture-source seam.

A CaptureSource yields documents that are new or changed since a checkpoint.
This is the single interface that makes A->B a relocation: Tier A runs the
source on the Mac; Tier B runs the same interface (GoogleDriveSource) on the
always-on Jetson. The rest of the pipeline never knows which source it has.

  - LocalFolderSource   : runnable now; watches a directory.
  - GoogleDriveSource   : production; Drive changes-API + pageToken checkpoint.
                          You supply OAuth credentials and do the consent flow
                          yourself — this code never handles your password.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


@dataclass
class DocumentRef:
    """A pointer to one document, identified by its CANONICAL id."""
    doc_id: str                      # canonical identity (path hash / Drive file id)
    name: str
    kind: str                        # 'pdf' | 'text' | 'url' | 'other'
    modified: float                  # epoch seconds
    source_url: str                  # where a human re-opens it
    fetch: Callable[[], bytes]       # pull raw bytes on demand
    tag: str = ""                    # full folder path from the source root ("" = root level)


def _kind_for(name: str) -> str:
    n = name.lower()
    if n.endswith(".pdf"):
        return "pdf"
    if n.endswith((".txt", ".md", ".markdown")):
        return "text"
    if n.endswith(".docx"):
        return "docx"
    if n.endswith(".pptx"):
        return "pptx"
    if n.endswith((".url", ".webloc")):
        return "url"
    return "other"


class CaptureSource(Protocol):
    def poll(self, checkpoint: Optional[str]) -> tuple[list[DocumentRef], Optional[str]]:
        """Return (new_or_changed_refs, new_checkpoint)."""
        ...


class LocalFolderSource:
    """Watches a folder. Checkpoint is the high-water modified-time seen so far.

    Canonical id = a stable hash of the absolute path, so re-indexing the same
    file never creates a duplicate node and never disturbs a verified edge.
    """

    def __init__(self, folder: str):
        self.folder = os.path.abspath(folder)

    def poll(self, checkpoint: Optional[str]) -> tuple[list[DocumentRef], Optional[str]]:
        since = float(checkpoint) if checkpoint else 0.0
        refs: list[DocumentRef] = []
        high = since
        for root, _, files in os.walk(self.folder):
            for fn in files:
                if fn.startswith("."):
                    continue
                path = os.path.join(root, fn)
                mtime = os.path.getmtime(path)
                if mtime <= since:
                    continue
                high = max(high, mtime)
                doc_id = "local:" + hashlib.sha1(path.encode()).hexdigest()[:16]

                def _fetch(p=path) -> bytes:
                    with open(p, "rb") as f:
                        return f.read()

                refs.append(DocumentRef(
                    doc_id=doc_id, name=fn, kind=_kind_for(fn),
                    modified=mtime, source_url="file://" + path, fetch=_fetch,
                ))
        return refs, (str(high) if refs else checkpoint)


class GoogleDriveSource:
    """PRODUCTION capture source — scoped to folders you name, INDEXED IN PLACE.

    Nothing is moved or copied. Files are read where they live; the index keeps a
    link (webViewLink) back to the original, plus extracted text + an embedding.

    Two operations:
      crawl()            one-time backfill: walks the named folders + their
                         subfolders and returns every PDF / text file found.
      poll(checkpoint)   ongoing: Drive changes API filtered to the SAME scope;
                         new sub-folders created under scope are tracked too.

    Setup you do once, yourself (Claude never handles your password):
      1. Google Cloud project + Drive API enabled.
      2. OAuth client credentials; run the consent flow to get an authorized service
         (googleapiclient build('drive','v3', credentials=...)).
      3. Resolve the folder names you want with find_folder_ids(service, [...]).
    UNTESTED in this build — verify against your Drive.
    """

    DOC_MIMES = (
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",   # .docx
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    )
    FOLDER_MIME = "application/vnd.google-apps.folder"
    SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
    OSX_ALIAS_MIME = "application/drive-fs.osx.alias"

    def __init__(self, drive_service, folder_ids, mime_types=None):
        self.svc = drive_service
        self.roots = list(folder_ids)
        self.mimes = set(mime_types or self.DOC_MIMES)
        self._scope = set(self.roots)

    def _ref(self, f, tag: str = "") -> DocumentRef:
        fid = f["id"]

        def _fetch(file_id=fid) -> bytes:
            return self.svc.files().get_media(fileId=file_id).execute()

        return DocumentRef(
            doc_id="gdrive:" + fid, name=f.get("name", fid),
            kind=_kind_for(f.get("name", "")), modified=0.0,
            source_url=f.get("webViewLink", ""), fetch=_fetch, tag=tag)

    def _children(self, folder_id) -> list[dict]:
        files, page = [], None
        while True:
            res = self.svc.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields=("nextPageToken, files(id,name,mimeType,webViewLink,"
                        "shortcutDetails(targetId,targetMimeType))"),
                pageToken=page, pageSize=200).execute()
            files.extend(res.get("files", []))
            page = res.get("nextPageToken")
            if not page:
                return files

    def _get_file(self, file_id) -> dict:
        return self.svc.files().get(
            fileId=file_id, fields="id,name,mimeType,webViewLink").execute()

    def crawl(self) -> list[DocumentRef]:
        """BFS over named folders + descendants, following folder/file shortcuts
        (aliases) to their targets even outside the named folders. Docs are keyed
        to the TARGET id, so a paper reached via an alias and a physical copy under
        the root collapse to one node."""
        refs, seen_folders, seen_docs = [], set(), set()
        queue = [(r, "") for r in self.roots]   # (folder_id, path from the source root)
        self._scope = set(self.roots)

        def sub(path, name):                     # extend the path with a child folder name
            return name if not path else path + "/" + name

        def add_doc(meta, tag):
            if meta["id"] in seen_docs:
                return
            seen_docs.add(meta["id"])
            refs.append(self._ref(meta, tag))

        while queue:
            fid, path = queue.pop()
            if fid in seen_folders:
                continue
            seen_folders.add(fid)
            for f in self._children(fid):
                mt = f["mimeType"]
                if mt == self.FOLDER_MIME:
                    self._scope.add(f["id"])
                    queue.append((f["id"], sub(path, f.get("name", ""))))
                elif mt == self.SHORTCUT_MIME:
                    sd = f.get("shortcutDetails") or {}
                    tid, tmt = sd.get("targetId"), sd.get("targetMimeType")
                    if not tid:
                        continue
                    if tmt == self.FOLDER_MIME:          # alias to a folder -> follow it
                        self._scope.add(tid)
                        queue.append((tid, sub(path, f.get("name", ""))))
                    elif tmt in self.mimes:              # alias to a paper -> index target
                        add_doc(self._get_file(tid), path)
                elif mt == self.OSX_ALIAS_MIME:
                    import sys
                    print(f"  [skip] macOS alias {f.get('name')!r} can't be followed via the "
                          f"Drive API — replace it with a Drive shortcut "
                          f"(in Drive: right-click the folder -> Organize -> Add shortcut).",
                          file=sys.stderr)
                elif mt in self.mimes:
                    add_doc(f, path)
        return refs

    def start_checkpoint(self) -> str:
        token = self.svc.changes().getStartPageToken().execute()["startPageToken"]
        return json.dumps({"pageToken": token, "scope": sorted(self._scope)})

    def poll(self, checkpoint):
        if not checkpoint:
            return [], self.start_checkpoint()
        state = json.loads(checkpoint)
        scope = set(state.get("scope", self.roots))
        page = state["pageToken"]
        new_token = page
        refs: list[DocumentRef] = []
        while page:
            resp = self.svc.changes().list(
                pageToken=page, spaces="drive",
                fields="newStartPageToken,nextPageToken,"
                       "changes(file(id,name,mimeType,modifiedTime,webViewLink,parents,trashed))",
            ).execute()
            for ch in resp.get("changes", []):
                f = ch.get("file")
                if not f or f.get("trashed"):
                    continue
                if not (set(f.get("parents") or []) & scope):
                    continue
                if f["mimeType"] == self.FOLDER_MIME:
                    scope.add(f["id"])               # new sub-folder under scope
                elif f["mimeType"] in self.mimes:
                    refs.append(self._ref(f))
            if resp.get("newStartPageToken"):
                new_token = resp["newStartPageToken"]
            page = resp.get("nextPageToken")
        return refs, json.dumps({"pageToken": new_token, "scope": sorted(scope)})


def find_folder_ids(drive_service, names: list[str]) -> dict[str, list[str]]:
    """Resolve folder NAMES to Drive folder IDs (you think in names; the API needs
    ids). Returns {name: [ids]} — a name can match more than one folder."""
    out: dict[str, list[str]] = {}
    for name in names:
        res = drive_service.files().list(
            q=("mimeType='application/vnd.google-apps.folder' and trashed=false "
               f"and name='{name}'"),
            fields="files(id,name)", pageSize=10).execute()
        out[name] = [f["id"] for f in res.get("files", [])]
    return out
