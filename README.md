# Finance Requirements Engineering Agents

A **fully local**, multi-agent assistant for requirements engineering in finance. It
interviews stakeholders, extracts and classifies requirements from documents and transcripts,
finds ambiguity, gaps and conflicts, maps requirements to (sample) rules and policies with
citations, recommends a ranked SDLC model and a project-specific workflow, and generates the
SRS, traceability matrix, compliance matrix and risk register. Humans approve every critical
decision, and everything is written to a tamper-evident audit trail.

- **Local only:** a pre-trained model served by [Ollama](https://ollama.com) (default
  `llama3.2:3b`), local MiniLM embeddings, local ChromaDB and SQLite. No cloud APIs and no
  fine-tuning. Sensitive data is masked before any model call.
- **Deterministic where possible:** citation checks, number grounding, quality rules, SDLC
  scoring, artefacts and security checks are plain Python. The model is used only for language
  understanding and generation.

Progress per phase, with decisions and known limitations: [docs/progress.md](docs/progress.md).
A complete real run is saved in [demo/final_run/](demo/final_run/) – open it with
**Requirements analysis → 📂 Load a saved run** (no model needed).
Problem-statement coverage: [docs/problem_statement_coverage.md](docs/problem_statement_coverage.md).

---

## The agents and who does what

| Component | What it does | Kind |
|---|---|---|
| **Stakeholder Interview Agent** | Adaptive chat interview with 9 role templates and 13 topics. Clear answers are judged instantly by rules; only borderline answers go to the model (assessment + follow-up). At most one follow-up per topic; contradictions in amounts are caught. | LLM + rules |
| **Context preparation** | Small documents are split into `[C n]` excerpts; large ones go through retrieval (5 targeted searches). Interview answers become one excerpt each. Plus `[KB-n]` excerpts from the allowlisted knowledge base. | deterministic + embeddings |
| **Requirements Agent** | Requirements in batches (count enforced by the output grammar): statement, 13 multi-label categories, stakeholder, justification, priority, dependencies, assumptions, Given/When/Then, KB rules, risk, sources, confidence. Then Python checks citations, numbers and claim support and computes a confidence score. | LLM + deterministic checks |
| **Quality & Clarification Agent** | Rules first (vague words, unmeasurable NFRs, missing actor or source, duplicates, conflicts), then a model review with questions for the right stakeholder role. Optional single revision round. | LLM + rules |
| **Compliance & Security Agent** | Maps each requirement to KB rules only, with controls, evidence, gaps, checkpoints and retention/reporting duties. High-impact mappings need a compliance officer. Missing baseline controls (encryption, MFA, audit logging…) become *suggested* requirements. Never a legal determination. | LLM + rules |
| **SDLC Agent** | The model rates 13 decision factors with evidence (Python suggests likely evidence IDs). Python scores 7 models from `config/sdlc_rules.yaml` using only evidenced factors. The model then explains the ranking without seeing anything else. | LLM + multi-criteria scoring |
| **Workflow Agent** | Starts from the chosen model's template (`config/sdlc_workflows/`), adds approval gates from earlier agents, and the model adds a few marked, project-specific items. | template + LLM |
| **Human review** | Accept / reject / edit / regenerate each item; mandatory approvals; joint SDLC vote; versioned baselines; change requests. | human-approval UI |
| **Artefacts** | SRS (IEEE 830 structure, DOCX + MD), user stories, use cases, process-workflow flowchart whose boxes are requirement IDs (Mermaid), data and interface requirements, traceability matrix, compliance-control matrix, risk register, assumptions and dependencies, open issues (XLSX + CSV, ZIP). | deterministic |
| **Evaluation** | Gold standard, metrics, single-prompt baseline, dashboard. | deterministic + baseline LLM |

All model calls go through `llm_service.py`. Every agent is a YAML prompt (`prompts/`), a
Pydantic schema (`agents/schemas.py`) and an entry in `agents/registry.py`, which also declares
the state fields the agent may read.

---

## Setup (Windows; macOS/Linux are almost identical)

1. **Ollama:** install from <https://ollama.com/download>, then `ollama pull llama3.2:3b` (≈2 GB).
2. **Python 3.10–3.13** (tested with 3.12). With `uv`:
   ```powershell
   pip install uv
   uv venv --python 3.12 .venv
   uv pip install --python .venv\Scripts\python.exe -r requirements.txt
   ```
   This installs PyTorch (CPU) for the embedding model, a few hundred MB.
3. **Run:**
   ```powershell
   .venv\Scripts\activate
   streamlit run app.py
   ```
   Open <http://localhost:8501>, sign up, and log in.
4. **Make yourself an administrator** (there is deliberately no automatic admin):
   ```powershell
   python -m auth.manage set-roles <your-username> admin analyst project_manager architect security_officer compliance_officer
   ```
   For a realistic demo, give the roles to different accounts instead.

### Roles

| Role | Can |
|---|---|
| Analyst | review requirements, request changes |
| Security officer | + decide high-risk security requirements and suggested security requirements, vote on the SDLC choice |
| Architect | + decide architecture-critical requirements, vote on the SDLC choice |
| Compliance officer | + approve compliance mappings and suggested requirements, vote on the SDLC choice |
| Project manager | + decide conflicting stakeholder requirements, vote on the SDLC choice, lock baselines, approve change requests |
| Admin | knowledge base, users and roles, audit verification, retention purge |

The SDLC choice needs an approving vote from **all four** of project manager, architect,
security officer and compliance officer.

---

## Using the app

1. **Stakeholder interview** (optional): choose a role and start. Answer in the chat, or skip,
   edit, end and resume the interview. You can also import questionnaires, emails or meeting
   notes. Use **Send to analysis** to analyse the transcripts.
2. **Requirements analysis:** describe the feature, upload a document or pick transcripts.
   Under *Advanced* you can choose the number of requirements, turn optional agents off (saves
   time on a CPU) and turn human review on or off. Then click **Run agents**.
3. **Review 1:** decide each requirement, compliance mapping and suggested requirement. 🔒
   marks mandatory items and items your role may not decide.
4. **Review 2:** vote on the SDLC recommendation.
5. **Results:** tabs per agent, **📦 Artefacts** (downloads + ZIP), **Source & audit**
   (citations, masking counts, quarantined excerpts, versions, audit events), then
   **mandatory approvals**, **lock baseline** and **change requests**.
6. **Projects & history:** project selector, runs, baselines, per-requirement history, and a
   diff between any two runs or baselines.
7. **Evaluation:** results of `run_eval.py`. **My account:** roles and optional 2FA.
   **Knowledge base / Administration:** admin only.

**Speed:** on a CPU-only laptop at about 2–3 tokens/s, a full run with 9 requirements and all
agents takes 30 minutes or more. Use fewer requirements or turn optional agents off for demos.

### Command line

```powershell
python run_demo.py --auto-approve --fast --artefacts out\   # non-interactive end-to-end run
python run_eval.py --docs loan_approval_policy --fast       # evaluation vs baseline
python run_eval.py --mock                                   # wiring check, seconds, no Ollama
python -m audit_log verify                                  # check the audit hash chain
python -m security.retention --days 365 --dry-run           # preview the retention purge
python -m storage.migrate                                   # import pre-database transcripts
python -m auth.manage list                                  # users and roles
python -m pytest                                            # test suite (mock LLM, no Ollama)
```

---

## Configuration

Everything is in [config.py](config.py), and most values can be overridden with environment
variables. The main groups:
- **Model:** `MODEL_NAME`, `NUM_CTX`, `MAX_OUTPUT_TOKENS`, `TEMPERATURE`, timeouts.
- **Requirements:** number of requirements, batch size, categories, confidence weights and
  review threshold (the formula is documented in `config.py`).
- **RAG and knowledge base:** chunk sizes, excerpt budgets, allowlist (types + sources),
  applicability keywords.
- **Quality / compliance / SDLC:** vague words, duplicate and conflict thresholds, revision
  loop, baseline controls, evidence minimums. The weight/rule table is
  [config/sdlc_rules.yaml](config/sdlc_rules.yaml); workflow templates are in
  [config/sdlc_workflows/](config/sdlc_workflows/).
- **Interviews, evaluation, security:** follow-up limits, KB-pointer threshold, match
  threshold, masking and quarantine switches, `RETENTION_DAYS`.

Prompts are editable YAML files in [prompts/](prompts/). The knowledge base is Markdown in
[kb/](kb/) (see [kb/README.md](kb/README.md)).

> **The shipped knowledge-base items are SAMPLE content – illustrative, not authoritative.**
> They don't quote any real law or regulator. Replace them with authorised text, and add the
> new sources to `KB_ALLOWED_SOURCES`.

---

## Evaluation

`run_eval.py` runs the full system and a **single-prompt, no-RAG baseline** (same model, one
plain call) on each gold document in `evaluation/gold/`. It reports:
- requirement precision / recall / F1 (MiniLM matching);
- category accuracy and completeness;
- ambiguity- and conflict-detection accuracy on seeded items;
- regulatory-control coverage;
- hallucination rate and citation correctness;
- SDLC top-1 and top-3 accuracy;
- traceability coverage and time per stage.

The human correction rate comes from the audit log, and the Evaluation page also has a short
**stakeholder satisfaction form** (1–5 + comment). Results go to `evaluation/results/` (JSON +
CSV) and the **Evaluation** page.

> The shipped gold files are **drafts** written by the assistant (`status: draft`). Review them
> before treating the scores as more than provisional.

---

## Project structure

```
app.py, run_demo.py, run_eval.py      entry points
pipeline.py                           run / resume / load runs (review modes)
llm_service.py                        the only Ollama call site (+ masking guard)
config.py, config/                    settings; SDLC rules and workflow templates
agents/                               registry, schemas, prompt builder, agent logic
orchestration/                        LangGraph builder, nodes, review, revision, regenerate
checks/                               grounding, confidence, quality rules
rag/, context_loader.py, kb/          retrieval, knowledge base
interview/                            interviews, templates, import
artefacts/                            SRS, stories, use cases, RTM, registers
evaluation/                           gold, metrics, baseline, runner
security/                             masking, injection, versions, retention
storage/                              SQLite app database, baselines, projects, migration
auth/                                 accounts, roles (RBAC), MFA, login screens
ui/                                   Streamlit pages
prompts/                              agent prompts (YAML)
tests/                                pytest suite with a mock LLM
docs/                                 progress log, problem-statement coverage
```


