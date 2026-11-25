# Problem statement coverage

Follows the structure of the official problem statement,
[Problem_Statement_1.docx](Problem_Statement_1.docx): its 20 numbered sections, the research
challenges named in the introduction, the agent table and the SDLC-conditions table.

Status: **done** = implemented and tested · **partial** = implemented with the stated gap ·
**future** = not implemented.

## The 20 sections

| # | Section (problem statement) | How it is covered | Main files | Status |
|---|---|---|---|---|
| 1 | **Define the system scope** – services (digital banking, loans, payments, fraud, insurance/investment, regulatory reporting, onboarding/KYC, analytics); outputs (SRS, user stories, use cases, acceptance criteria, compliance mappings, risk register, RTM, SDLC model) | Every listed output is generated. Domain-neutral pipeline, started with **loan processing** (as section 18 advises); sample documents and KB for loans, KYC onboarding and payments. | `artefacts/`, `documents/`, `kb/` | **partial** – fraud, insurance/investment, regulatory reporting and analytics have no sample documents / KB items yet |
| 2 | **Identify stakeholders** + role-specific interview templates | Templates for all nine listed roles (customer, business analyst, product owner, architect/developer, information security, compliance/legal, risk management, operations, auditor/regulator) | `prompts/interview_templates/` | done |
| 3 | **Define input sources** (conversations, transcripts, questionnaires, emails, meeting notes, requirement documents, policies, regulations, API/DB specs, legacy docs, incident reports) + classify, mask and protect sensitive data before the LLM | Live interviews; import of questionnaires / emails / meeting notes; PDF/DOCX/TXT/MD documents (any of the listed document types as text); policies/regulations via the KB. Masking of PAN, Aadhaar, card (Luhn), IFSC, account, phone, email and names before any model call | `interview/`, `document_reader.py`, `security/masking.py`, `llm_service.py` | **partial** – API/DB specs, legacy docs and incident reports are read as plain text (no format-specific parsing, e.g. OpenAPI) |
| 4 | **Design the multi-agent architecture** – central orchestrator managing communication, execution order, shared context and approval gates | LangGraph graph with shared state, registry-defined agents, review interrupts (approval gates) and a persistent checkpointer. See the agent table below | `orchestration/`, `agents/registry.py`, `pipeline.py` | done |
| 5 | **Build the financial knowledge base** – authorised, version-controlled; terminology, processes, policies, regulations, security standards, RE guidelines, SDLC rules, templates, previously approved documents; each item with source, jurisdiction, effective date, version, applicability | Markdown items with exactly those metadata fields, versioned (superseded items kept), hash-based re-indexing, allowlist, applicability filter, admin page. Types: regulation, policy, security standard, RE guideline, SDLC rule, template | `kb/`, `rag/knowledge_base.py` | **partial** – shipped content is SAMPLE (not authorised); no terminology / business-process items yet; approved baselines are stored but not fed back into the KB |
| 6 | **Retrieval-grounded generation** – classify, retrieve, provide evidence, generate, attach citations and confidence, escalate unsupported / low-confidence output | Applicability detection → retrieval of document + KB excerpts → `[C n]` / `[KB-n]` citations → citation validation, number grounding, claim support → documented confidence score → `needs_human_review` + human review | `context_loader.py`, `rag/`, `checks/`, `agents/requirements_agent.py` | done |
| 7 | **Requirement-gathering conversations** – adaptive (not fixed) interviews on 13 topics; follow-ups when vague, incomplete or inconsistent | All 13 topics; rules-first assessment (length, missing numbers, vague words, contradictions incl. rupee amounts), model only for borderline answers, ≤1 follow-up per topic, MiniLM KB pointers | `interview/engine.py`, `prompts/interview_templates/topics.yaml` | done |
| 8 | **Extract and structure requirements** – ID, statement, category, source stakeholder, justification, priority, dependencies, assumptions, acceptance criteria, applicable regulations, risk level, confidence, approval status | Every listed field (plus sources, flags, version, reviewer). IDs are `FR-01` / `NFR-01` / `SEC-01` (not domain-prefixed like `FR-PAY-001`) | `agents/schemas.py` | done |
| 9 | **Classify the requirements** – 13 classes, multi-label | Exactly those 13 classes, 1–3 per requirement, enforced by the output grammar | `config.REQUIREMENT_CATEGORIES` | done |
| 10 | **Analyse requirement quality** – ambiguity, incompleteness, inconsistency, duplication, infeasibility, lack of testability, missing source, undefined terminology, conflicting expectations, missing controls; failing requirements return to the clarification agent | All ten checks (rules + model review) with clarification questions per stakeholder role; optional revision round sends High-severity items back | `checks/quality.py`, `agents/quality_agent.py`, `orchestration/revision.py` | done (the automatic return loop is **off by default** to save time on CPU; the questions and human review always apply) |
| 11 | **Compliance and security analysis** – jurisdiction/regulation, required controls, evidence, gaps, mandatory approval/audit checkpoints, retention/reporting obligations; no final legal determinations; high-impact interpretations approved by compliance/legal | All listed outputs, KB-only rules, disclaimer, `requires_compliance_officer_approval`, compliance-officer-only approval (RBAC) | `agents/compliance_agent.py`, `auth/rbac.py` | **partial** – jurisdiction is available through the cited KB item's metadata but not output as a separate field |
| 12 | **Generate requirement artefacts** – SRS, user stories + acceptance criteria, use cases, process workflows, data requirements, interface requirements, threat and risk register, compliance-control matrix, RTM, assumptions and dependency register, open issues; each linked to its stakeholder statement and document | All eleven, including a process-workflow flowchart whose boxes are requirement IDs; RTM columns link source stakeholder, exact source statement and citations | `artefacts/` | done |
| 13 | **Extract SDLC decision factors** – the 13 listed characteristics | Exactly those 13, rated with evidence IDs; Python suggests candidate evidence; factors without evidence are not scored | `agents/sdlc_agent.py`, `agents/sdlc_evidence.py` | done |
| 14 | **SDLC selection engine** – deterministic rules + multi-criteria analysis + LLM explanation; ranked percentages; final choice approved by PM, architect, security team and compliance officer | Weight/rule table, ranked percentages (e.g. DevSecOps 97.8 %, Agile + DevSecOps 97.1 %, Agile + V-Model 88.2 % in the final run), explanation constrained to the ranking, joint vote of exactly those four roles | `agents/sdlc_scoring.py`, `config/sdlc_rules.yaml`, `storage/projects.py` | done |
| 15 | **Project-specific SDLC workflow** – phases, activities, roles, deliverables, security activities, testing, compliance checkpoints, human-approval gates, entry/exit criteria, traceability (e.g. threat modelling, SAST, transaction-integrity testing, compliance approval before deployment) | Seven templates with all ten elements (incl. those four examples) + bounded AI tailoring and approval gates from earlier agents | `config/sdlc_workflows/`, `agents/workflow_agent.py` | done |
| 16 | **Human-in-the-loop controls** – mandatory approval for baselines, regulatory interpretations, high-risk security, conflicting decisions, architecture-critical requirements, SDLC selection, changes to approved requirements, production-readiness; accept / reject / modify / regenerate | Interrupt-based review with accept / reject / edit / regenerate; the first seven mandatory types enforced (baseline lock blocked until decided; change requests need re-approval) | `orchestration/review.py`, `ui/review_panel.py`, `storage/baselines.py` | **partial** – no explicit **production-readiness** approval step (the tool stops at requirements, SDLC and workflow) |
| 17 | **Secure the platform** – RBAC, MFA, encryption in transit and at rest, masking, prompt/output filtering, agent-level permissions, retrieval-source allowlisting, prompt-injection protection, session isolation, audit logging, retention, model/KB versioning; least privilege for agents | RBAC (6 roles), optional TOTP MFA, Fernet encryption at rest (key outside the repo), masking + LLM guard, delimiters + quarantine, schema-validated outputs, per-agent read/write permissions, KB allowlist, per-user session state, hash-chained audit log, retention purge, model/prompt/KB versions per run | `security/`, `auth/`, `orchestration/nodes.py`, `audit_log.py` | **partial** – no TLS: Streamlit and Ollama talk over local HTTP (`localhost`); put a TLS reverse proxy in front for any non-local deployment |
| 18 | **Develop the prototype** – LLM, orchestration framework, vector DB, relational DB, rule engine, workflow engine for approvals, web UI, document generation, identity and access management, monitoring and audit platform; start with one use case | Ollama `llama3.2:3b`; LangGraph; ChromaDB; SQLite; Python rule tables (`checks/`, `sdlc_rules.yaml`); LangGraph interrupts + checkpointer for approvals; Streamlit; python-docx / openpyxl; local accounts + RBAC + MFA; audit log + Evaluation page. Started with loan processing | whole repo | **partial** – monitoring is limited to the audit log, admin verification and the Evaluation page (no live monitoring / alerting) |
| 19 | **Test and evaluate** – real or anonymised case studies; precision/recall/F1, completeness, ambiguity and conflict detection, control coverage, hallucination rate, citation correctness, SDLC accuracy (vs architects / PMs), human correction rate, time saved vs manual analysis, stakeholder satisfaction, traceability coverage | All metrics except time saved are computed (`run_eval.py`, Evaluation page, satisfaction form); comparison with a single-prompt baseline; stage times recorded | `evaluation/`, `run_eval.py`, `ui/page_evaluation.py`, `storage/feedback.py` | **partial** – gold files are assistant-written drafts (not architects' decisions); **time saved vs manual analysis** needs manual timings (only system time is measured); the baseline is a single LLM prompt, not a conventional manual RE process |
| 20 | **Deploy, monitor and improve** – advisory mode, comparison with analysts, human-approved generation, monitoring of wrong recommendations and gaps, KB and rule updates, re-evaluation, expansion; record prompts, evidence, decisions, changes, approvals and artefacts | Human-approved generation; everything listed is recorded (audit log + approvals + versioned history + stored artefacts); KB and rules are versioned files; `run_eval.py` supports re-evaluation | `audit_log.py`, `storage/`, `kb/`, `config/` | **partial** – advisory mode and monitoring are **future work** (see below) |

## Research challenges named in the introduction

| Challenge | How it is addressed | Status |
|---|---|---|
| LLM hallucinations | RAG with citations, citation validation, number grounding, claim-support similarity, KB-only rules, confidence + human review; hallucination rate measured | done |
| Explainability | Cited excerpts per requirement, confidence breakdown, SDLC factor evidence + score breakdown + constrained explanation, quality issue explanations | done |
| Handling sensitive financial data | Masking before any model call, encryption at rest, local-only processing, retention purge | done (no TLS, see §17) |
| Bias | — | **future** (fair-lending / protected-attribute checks) |
| Prompt injection | Data delimiters + security rule, pattern scan and quarantine, schema-constrained outputs | done (pattern-based) |
| Access control | RBAC, MFA, agent-level permissions, session isolation | done |
| Regulatory change | KB versioning with superseded items, hash-based re-indexing, KB version recorded per run | **partial** – no automatic impact analysis when a rule changes (future) |
| Interoperability | Exports in DOCX, Markdown, XLSX, CSV, JSON, Mermaid; saved-run JSON | **partial** – no API / integration with ALM tools |
| Human oversight | Mandatory approvals, joint SDLC vote, baselines, change requests, audit trail | done (production-readiness approval missing, see §16) |

## The agent table (problem statement) and how each is realised

| Agent (problem statement) | Responsibility | Realised as | Kind |
|---|---|---|---|
| Coordinator agent | Controls the workflow and assigns tasks | LangGraph graph + `pipeline.py` (execution order, shared state, approval gates, checkpoints) | orchestrator |
| Stakeholder interaction agent | Conducts interviews and asks questions | Stakeholder Interview Agent (`interview/engine.py`) | LLM agent + rules |
| Requirement extraction agent | Extracts requirements from conversations and documents | Requirements Agent | LLM agent |
| Clarification agent | Detects missing or ambiguous information | Quality & Clarification Agent (questions per stakeholder role) + optional revision round | LLM agent + rules |
| Classification agent | Classifies functional and non-functional requirements | Inside the Requirements Agent: FR/NFR kinds + 13-class multi-label grammar | LLM + deterministic |
| Conflict-detection agent | Identifies contradictions and duplication | `checks/quality.py` (numeric, rupee and negation conflicts; embedding duplicates) inside the Quality Agent | deterministic |
| Compliance agent | Maps requirements to regulations and policies | Compliance & Security Agent | LLM agent + checks |
| Security and privacy agent | Identifies cybersecurity and privacy requirements | Same agent's security controls + deterministic baseline-control checklist (suggested SEC requirements) | LLM + deterministic |
| Risk-analysis agent | Assesses business, technical and compliance risks | Per-requirement risk level, threat and risk register, SDLC risk factors | **partial** – deterministic, no dedicated LLM risk agent |
| SDLC selection agent | Recommends an SDLC model | SDLC Agent (rate → score → explain) | LLM + multi-criteria scoring |
| Documentation agent | Generates SRS, user stories, traceability records | `artefacts/` | deterministic |
| Validation agent | Verifies completeness, consistency and evidence | Deterministic checks (citations, numbers, claim support, confidence), quality rules, mandatory-item checks | deterministic |
| Human-approval agent | Routes critical decisions to authorised personnel | Review nodes + review UI + RBAC routing (owning roles, compliance officer, joint SDLC vote, PM for baselines) | human-approval UI |

## SDLC conditions table (problem statement) vs the rule table

| Project condition | Suitable approach | In `config/sdlc_rules.yaml` |
|---|---|---|
| Stable requirements and extensive approvals | Waterfall | Waterfall prefers high stability, low change, high documentation, low continuous delivery |
| Strict verification and validation | V-Model | V-Model prefers high formal verification and testing/documentation (×2), high regulation |
| High uncertainty or technical risk | Spiral | Spiral prefers high complexity (×2), low stability; +5 when stability is Low and complexity High |
| Frequently changing requirements | Agile | Agile prefers high change (×2), low stability (×2); −15 for Waterfall when change is High |
| Continuous secure deployment | DevSecOps | DevSecOps prefers high security risk and continuous delivery (×2); +3 when both are High |
| High regulation with evolving requirements | Agile–V-Model or DevSecOps hybrid | Agile + V-Model and Agile + DevSecOps hybrids (high change + high regulation + verification / security) |

## Future work (not implemented)

| Item | Problem-statement link | What it would add |
|---|---|---|
| Legacy-constraint checks | §3, §5 (legacy-system constraints) | Check requirements against an inventory of legacy systems / interfaces (batch windows, core-banking limits) and flag ones that are infeasible without changes. |
| Regulatory-change handling | Introduction, §20 | When a KB item is superseded, list the requirements, mappings and baselines that cite it and open change requests automatically. |
| Bias check | Introduction | Fair-lending checks on requirements and decision rules (protected attributes, proxy variables) with reviewer sign-off. |
| Advisory mode + monitoring | §18, §20 | A suggest-only mode, comparison with analysts' outputs, and monitoring of confidence, flags, correction rates and compliance gaps over time with alerts. |
| Production-readiness approval | §16 | A final mandatory approval gate before deployment (e.g. as part of the workflow's release phase). |
| Time saved vs manual analysis | §19 | Record analysts' manual timings for the same case studies and report the difference. |
