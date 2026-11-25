# Final real run (saved)

The Phase 12 end-to-end run with the real model, kept so it can be shown without
waiting an hour for the model again.

- **Run:** `20261125-193937-4995e9`, 25 Nov 2026, `llama3.2:3b` (Ollama, CPU laptop), 58 min.
- **Input:** `documents/loan_approval_policy.md`, scenario "Loan approval module for a retail
  bank (Northbridge Bank sample policy)", 5 functional + 4 non-functional requirements, all
  agents on, review steps **auto-approved** (marked "(auto)" everywhere).

| File | What it is |
|---|---|
| `result.json` | the complete run (all agents' outputs, citations, versions) – open it in the app: **Requirements analysis → 📂 Load a saved run** |
| `artefacts/` | the 15 generated files (SRS, RTM, registers…) exactly as produced |
| `metrics.json` | metrics against the DRAFT loan gold file (see `docs/progress.md`, Phase 12) |
| `audit_log.jsonl` | the run's own hash-chained audit log (`python -c "import audit_log; print(audit_log.verify('demo/final_run/audit_log.jsonl'))"`) |

`result.json` was rebuilt from the audit log with `python -m tools.replay_run` (every model
answer is taken from the log, nothing is generated again); its metrics were checked to be
identical to `metrics.json`.
