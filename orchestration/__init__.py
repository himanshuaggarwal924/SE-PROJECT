"""
The orchestration package (LangGraph).

  state.py      - the shared state object passed between nodes
  nodes.py      - context preparation and the generic agent node (permissions, wrapping)
  builder.py    - how the nodes are connected into a graph (review steps, revision loop)
  review.py     - human-review nodes (interrupt / resume), mandatory items
  revision.py   - optional quality-driven revision round
  regenerate.py - re-run one requirement or mapping during review
"""
