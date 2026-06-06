"""paperfinder.studio: turn a selected set of papers into learning media.

Separation of concerns: a *selector* (anything upstream) produces a plain list
of doc_ids; `studyset.build_studyset` assembles those into a StudySet (paper text
plus the passage-level connections already found between them); a *generator*
(e.g. `synthesis.synthesize`) consumes a StudySet and produces an artifact.
New output media are added as new generators without touching the rest.
"""
