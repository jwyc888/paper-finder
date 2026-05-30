"""paper-finder — scoped semantic + keyword recall over your own documents,
with a human-verified relationship graph on top."""

from paperfinder.core.finder import PaperFinder, HashingEmbedder, STEmbedder
from paperfinder.core.capture import (
    LocalFolderSource, GoogleDriveSource, find_folder_ids,
)
from paperfinder.graph.relationship import RelationshipGraph

__version__ = "0.1.0"
__all__ = [
    "PaperFinder", "HashingEmbedder", "STEmbedder",
    "LocalFolderSource", "GoogleDriveSource", "find_folder_ids",
    "RelationshipGraph",
]
