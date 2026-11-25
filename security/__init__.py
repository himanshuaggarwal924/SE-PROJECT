"""
The security package (Phase 9).

  masking.py   - sensitive-data masking before any LLM call (typed placeholders)
  injection.py - prompt-injection defence: data delimiters + quarantine of suspicious text
  versions.py  - model / prompt / KB version fingerprints recorded with every run
  retention.py - retention purge of old logs, transcripts and runs (CLI + admin button)
"""
