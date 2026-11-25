"""
The artefacts package - requirement documents generated from a run (Phase 8).
Mostly deterministic: no model calls, only the run's (approved) data.

  data.py      - collects the run's items and resolves sources / citations
  document.py  - a tiny document model rendered to Markdown and DOCX
  documents.py - SRS (IEEE 830 structure), user stories, use cases,
                 data and interface requirements
  registers.py - traceability matrix, compliance-control matrix, threat and
                 risk register, assumptions & dependencies, open issues
                 (rows -> XLSX and CSV)
  bundle.py    - every file of a run, and a ZIP of them all
"""
