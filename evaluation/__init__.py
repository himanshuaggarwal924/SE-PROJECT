"""
The evaluation package (Phase 10).

  gold.py     - the gold-standard format (evaluation/gold/*.yaml, DRAFT until reviewed)
  matching.py - one-to-one matching of generated to gold requirements (MiniLM / lexical)
  metrics.py  - every metric from the problem statement
  baseline.py - the "single prompt, no RAG" baseline system
  runner.py   - runs full system + baseline per gold document, writes JSON and CSV
"""
