"""
config.py - All project settings live here.

Change MODEL_NAME to try a different local model (e.g. "mistral" or "phi3").
You can also override most settings with an environment variable of the same
name, e.g. in PowerShell:   $env:MODEL_NAME = "mistral"
"""

import os
from pathlib import Path

# --- LLM settings (used by llm_service.py) -----------------------------------
# Name of the model as shown by `ollama list`.
MODEL_NAME = os.getenv("MODEL_NAME", "llama3.2:3b")

# Where the Ollama server is listening (this is Ollama's default address).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Low temperature = more focused, repeatable answers (good for requirements).
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# The model's context window in tokens (prompt + answer must fit in it).
# 4096 fits our prompts and keeps memory use low on an 8 GB laptop.
NUM_CTX = int(os.getenv("NUM_CTX", "4096"))

# Upper limit on how many tokens one agent may write. Stops a model that
# "rambles" from running for ages. The prompts ask for much less than this.
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1500"))

# How long to wait for ONE agent's answer before giving up. On a CPU-only
# laptop a single answer can take over 10 minutes.
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "3600"))

# How long Ollama keeps the model loaded in memory after a request.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")

# Ask Ollama to force the answer to match the agent's JSON schema
# ("structured outputs"). json-repair stays as a safety net either way.
USE_JSON_SCHEMA_FORMAT = True

# --- Context / RAG settings --------------------------------------------------
# Maximum characters of source material put into the Requirements Agent's
# prompt. A document up to this size is used directly (fast); a bigger one
# goes through retrieval (RAG) and only the most relevant chunks are used.
# (~4 characters is roughly 1 token.)
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))

# Longest document we will read at all (~150 pages). Anything beyond this is
# cut off, to keep embedding time and memory reasonable on an 8 GB laptop.
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "400000"))

# Chunking: each chunk is ~900 characters and repeats the last 150 of the
# previous one, so sentences on a border are not lost.
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

# Retrieval: how many chunks each search query returns, and the most chunks
# given to the model in total (6 x 900 = ~5,400 characters, under MAX_CONTEXT_CHARS).
CHUNKS_PER_QUERY = 3
MAX_RETRIEVED_CHUNKS = 6

# Small CPU-friendly embedding model (~90 MB download, first use only).
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# --- Knowledge base (kb/ folder, see kb/README.md) --------------------------
# Version-controlled rules/policies retrieved alongside the user's document
# and cited as [KB-1], [KB-2]... (the document's excerpts are [C1], [C2]...).
KB_ENABLED = os.getenv("KB_ENABLED", "1") == "1"
KB_COLLECTION = "knowledge_base"        # separate ChromaDB collection
KB_CHUNK_SIZE = 600                     # each "## section" is split into pieces of this size
KB_MAX_CHUNKS = int(os.getenv("KB_MAX_CHUNKS", "3"))       # KB excerpts per prompt
KB_CONTEXT_CHARS = int(os.getenv("KB_CONTEXT_CHARS", "1800"))  # KB share of the prompt
# Allowlist: only these item types and these `source` values may be used as
# evidence. Templates are structure, not evidence, so they are not listed.
KB_EVIDENCE_TYPES = ["regulation", "policy", "security_standard", "re_guideline", "sdlc_rule"]
KB_ALLOWED_SOURCES = [s.strip() for s in os.getenv(
    "KB_ALLOWED_SOURCES",
    "SAMPLE internal policy,SAMPLE regulatory summary,SAMPLE security standard,"
    "SAMPLE RE guideline,SAMPLE SDLC guidance").split(",") if s.strip()]
# Which KB types the Requirements Agent retrieves (SDLC rules are for the SDLC step).
KB_TYPES_FOR_REQUIREMENTS = ["regulation", "policy", "security_standard", "re_guideline"]
# Deterministic applicability detection: if any keyword appears in the
# scenario or document, items tagged with that applicability are eligible.
# Items tagged "all" are always eligible.
KB_APPLICABILITY_KEYWORDS = {
    "loan_processing": ["loan", "credit", "underwrit", "borrower", "lending", "emi"],
    "kyc": ["kyc", "know your customer", "onboarding", "aml", "identity", "due diligence"],
    "payments": ["payment", "transfer", "upi", "card", "settlement", "remittance", "wallet"],
}

# --- Requirements generation ---------------------------------------------
# How many requirements the Requirements Agent writes. They are generated in
# batches of REQUIREMENTS_BATCH_SIZE (one model call per batch), so asking for
# more requirements makes the run longer but never overflows the model's
# answer limit (MAX_OUTPUT_TOKENS). ~200 output tokens per requirement.
NUM_FUNCTIONAL_REQUIREMENTS = int(os.getenv("NUM_FUNCTIONAL_REQUIREMENTS", "5"))
NUM_NON_FUNCTIONAL_REQUIREMENTS = int(os.getenv("NUM_NON_FUNCTIONAL_REQUIREMENTS", "4"))
REQUIREMENTS_BATCH_SIZE = int(os.getenv("REQUIREMENTS_BATCH_SIZE", "3"))
# "full": the model writes every field (default). "compact" (experimental): the
# model writes only statement, categories, priority and sources with a much
# shorter prompt; the other fields are filled by code. See docs/progress.md
# (F1 investigation) before changing the default.
REQUIREMENTS_PROMPT_MODE = os.getenv("REQUIREMENTS_PROMPT_MODE", "full")
MAX_REQUIREMENTS_PER_KIND = 15   # upper limit offered in the UI

# The multi-label category set every requirement is tagged with.
REQUIREMENT_CATEGORIES = [
    "business", "stakeholder", "functional", "security", "privacy", "regulatory",
    "performance", "availability/reliability", "usability", "data-management",
    "integration", "audit/reporting", "operational/maintenance",
]

# --- Confidence score (computed in checks/confidence.py) ------------------
# confidence = sum(weight_i * component_i) / sum(weight_i over AVAILABLE components)
#
#   self_rating           the model's own 0-1 rating of the requirement
#   retrieval_similarity  how well the cited excerpts support the requirement:
#                         mean cosine similarity between the requirement's
#                         statement and each cited excerpt ("claim support",
#                         CITATION_SUPPORT_CHECK). If that can't be computed,
#                         the excerpts' retrieval score is used instead (RAG
#                         only). Rescaled from [FLOOR, CEIL] to [0, 1].
#   citation_validity     valid citations / all citations. 0 if a document was
#                         given but nothing was cited. Not available when
#                         there is no document at all.
#   number_grounding      per number in the requirement: 1 if it appears in a
#                         cited excerpt or the typed description, 0.5 if it
#                         only appears in an uncited excerpt, 0 if nowhere.
#                         1.0 when the requirement contains no numbers.
#
# A component that is "not available" is left out and the remaining weights
# are re-normalised, so a run without a document isn't penalised for having
# nothing to cite.
CONFIDENCE_WEIGHTS = {
    "self_rating": 0.25,
    "retrieval_similarity": 0.25,
    "citation_validity": 0.25,
    "number_grounding": 0.25,
}
RETRIEVAL_SIMILARITY_FLOOR = 0.20   # cosine similarity treated as 0
RETRIEVAL_SIMILARITY_CEIL = 0.65    # cosine similarity treated as 1
# Claim support: embed each statement and its cited excerpts (one worker call
# per run). A cited excerpt less similar than CITATION_SUPPORT_MIN to the
# statement is flagged "weak_citation" (valid ID, but probably irrelevant).
CITATION_SUPPORT_CHECK = os.getenv("CITATION_SUPPORT_CHECK", "1") == "1"
CITATION_SUPPORT_MIN = 0.25
# Requirements below this confidence get a "needs human review" flag.
CONFIDENCE_REVIEW_THRESHOLD = float(os.getenv("CONFIDENCE_REVIEW_THRESHOLD", "0.6"))
# Numbers so small/common that they are not checked against the sources.
GROUNDING_IGNORED_NUMBERS = {"0", "1"}

# --- Quality & Clarification Agent ---------------------------------------
QUALITY_BATCH_SIZE = int(os.getenv("QUALITY_BATCH_SIZE", "4"))   # requirements per model call
# Words that make a requirement vague unless a measurable criterion is given.
QUALITY_VAGUE_WORDS = [
    "fast", "quick", "quickly", "secure", "securely", "user-friendly", "user friendly", "easy",
    "appropriate", "adequate", "efficient", "flexible", "robust", "reliable", "seamless",
    "as needed", "as required", "if possible", "etc", "and/or", "sufficient", "timely",
    "minimal", "optimal", "state-of-the-art", "intuitive", "high performance", "scalable",
]
# Near-duplicate detection: "embedding" (MiniLM, in the worker process) or
# "lexical" (word overlap, no model). Falls back to lexical if embedding fails.
QUALITY_DUPLICATE_METHOD = os.getenv("QUALITY_DUPLICATE_METHOD", "embedding")
QUALITY_DUPLICATE_THRESHOLD = 0.88          # cosine similarity for "embedding"
QUALITY_LEXICAL_DUPLICATE_THRESHOLD = 0.75  # word-set overlap (Jaccard) for "lexical"
QUALITY_CONFLICT_SUBJECT_OVERLAP = 0.3      # shared-subject threshold for conflict checks
# Send requirements with High-severity issues back to the Requirements Agent
# once for revision (one extra round of model calls, so off by default).
QUALITY_REVISION_ENABLED = os.getenv("QUALITY_REVISION_ENABLED", "0") == "1"
QUALITY_MAX_REVISIONS = 1

# --- Compliance & Security Agent -----------------------------------------
COMPLIANCE_BATCH_SIZE = int(os.getenv("COMPLIANCE_BATCH_SIZE", "3"))
# The Compliance Agent sees more KB excerpts than the Requirements Agent
# (same retrieval; the Requirements Agent gets the first KB_MAX_CHUNKS).
KB_MAX_CHUNKS_COMPLIANCE = int(os.getenv("KB_MAX_CHUNKS_COMPLIANCE", "6"))
KB_CONTEXT_CHARS_COMPLIANCE = int(os.getenv("KB_CONTEXT_CHARS_COMPLIANCE", "3600"))
# Baseline security/privacy controls. If no requirement mentions any of a
# control's keywords, a "suggested" requirement is proposed from the template.
COMPLIANCE_BASELINE_CONTROLS = {
    "encryption": {
        "keywords": ["encrypt", "tls", "cryptograph"],
        "statement": "The system shall encrypt personal and financial data in transit and at rest.",
        "categories": ["security", "privacy"]},
    "multi_factor_authentication": {
        "keywords": ["multi-factor", "multi factor", "mfa", "two-factor", "2fa", "one-time password", "otp"],
        "statement": "The system shall require multi-factor authentication for privileged and remote access.",
        "categories": ["security"]},
    "access_control": {
        "keywords": ["role-based", "access control", "rbac", "least privilege", "authoris", "authoriz"],
        "statement": "The system shall restrict access to customer data by role, following least privilege.",
        "categories": ["security", "privacy"]},
    "audit_logging": {
        "keywords": ["audit log", "audit trail", "log ", "logged", "logging"],
        "statement": "The system shall record security-relevant events with user, time and action in a tamper-evident audit log.",
        "categories": ["security", "audit/reporting"]},
    "data_minimisation": {
        "keywords": ["minimi", "only the data", "mask", "anonymi", "pseudonymi"],
        "statement": "The system shall collect only the personal data needed for its stated purpose and mask sensitive identifiers in screens and logs.",
        "categories": ["privacy", "data-management"]},
    "data_retention": {
        "keywords": ["retain", "retention", "purge", "delete", "archiv"],
        "statement": "The system shall retain and delete records according to the institution's approved retention schedule.",
        "categories": ["regulatory", "data-management"]},
}

# --- Folder locations -----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DOCUMENTS_DIR = PROJECT_ROOT / "documents"  # sample finance documents (demo only)
KB_DIR = PROJECT_ROOT / "kb"                # knowledge base items (Markdown + front-matter)
SAVED_RUNS_DIR = PROJECT_ROOT / "demo"      # saved runs that can be loaded without the model
# SDLC selection: weight/rule table and per-model workflow templates. (The
# config/ folder holds data files only; it is not a Python package.)
SDLC_RULES_FILE = PROJECT_ROOT / "config" / "sdlc_rules.yaml"
SDLC_WORKFLOWS_DIR = PROJECT_ROOT / "config" / "sdlc_workflows"
# Only factors with valid evidence (requirement or excerpt IDs) are scored.
# With fewer than SDLC_MIN_EVIDENCED_FACTORS, all ratings are used instead and
# the confidence is Low. The confidence is also capped by coverage:
SDLC_MIN_EVIDENCED_FACTORS = 4
SDLC_HIGH_CONFIDENCE_FACTORS = 10     # High needs at least this many of 13 scored
SDLC_MEDIUM_CONFIDENCE_FACTORS = 7    # Medium needs at least this many
PROMPTS_DIR = PROJECT_ROOT / "prompts"      # one editable YAML file per agent
LOGS_DIR = PROJECT_ROOT / "logs"            # audit trail is written here
AUDIT_LOG_FILE = LOGS_DIR / "audit_log.jsonl"
VECTOR_DB_DIR = PROJECT_ROOT / "vector_store"  # ChromaDB database files
MODELS_DIR = PROJECT_ROOT / "models"           # downloaded embedding model
USERS_FILE = PROJECT_ROOT / "auth" / "users.yaml"  # local user accounts (hashed)
DATA_DIR = PROJECT_ROOT / "data"                    # local databases (git-ignored)
APP_DB = DATA_DIR / "app.sqlite"                   # runs, approvals, baselines...
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"    # LangGraph saved run states (pause/resume)

# --- Stakeholder interviews (interview/) ------------------------------------
INTERVIEW_TEMPLATES_DIR = PROMPTS_DIR / "interview_templates"
INTERVIEWS_DIR = PROJECT_ROOT / "interviews"     # saved transcripts (git-ignored)
INTERVIEW_MAX_FOLLOWUPS = int(os.getenv("INTERVIEW_MAX_FOLLOWUPS", "1"))  # per topic
INTERVIEW_MIN_WORDS = 6        # shorter answers always get a follow-up (if allowed)
INTERVIEW_CLEAR_WORDS = 15     # this long AND containing a number = complete, no model call
INTERVIEW_KB_HINTS = 2         # results of the keyword KB search (admin page)
# Interview questions point to the most similar KB section (MiniLM) only if it
# is at least this similar to the topic; otherwise no pointer is shown.
INTERVIEW_KB_HINT_MIN_SIMILARITY = float(os.getenv("INTERVIEW_KB_HINT_MIN_SIMILARITY", "0.40"))

# --- Evaluation (evaluation/, run_eval.py) ----------------------------------
EVAL_GOLD_DIR = PROJECT_ROOT / "evaluation" / "gold"
EVAL_RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
# A generated requirement matches a gold requirement if their statements are at
# least this similar (MiniLM cosine; word-overlap fallback uses EVAL_LEXICAL_MATCH).
EVAL_MATCH_THRESHOLD = float(os.getenv("EVAL_MATCH_THRESHOLD", "0.60"))
EVAL_LEXICAL_MATCH = 0.35
# The single-prompt baseline sees the document's first N characters (no RAG, no KB).
EVAL_BASELINE_MAX_CHARS = MAX_CONTEXT_CHARS

# --- Security (security/) -----------------------------------------------------
# Mask PAN, Aadhaar, card, IFSC, account, phone, email and name values before
# any text is sent to the model (placeholders like <PAN_1>).
MASK_SENSITIVE_DATA = os.getenv("MASK_SENSITIVE_DATA", "1") == "1"
# Leave out document / KB / transcript excerpts that look like prompt injection.
QUARANTINE_INJECTION = os.getenv("QUARANTINE_INJECTION", "1") == "1"
# Data older than this is removed by `python -m security.retention` (admin page button).
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "365"))
# Encryption at rest (security/crypto.py): 2FA secrets, transcripts, approvals,
# baselines, history, artefacts and LangGraph checkpoints. The key file is kept
# OUTSIDE the repository - back it up, encrypted data can't be read without it.
ENCRYPT_AT_REST = os.getenv("ENCRYPT_AT_REST", "1") == "1"
ENCRYPTION_KEY_FILE = Path(os.getenv("FINREQ_KEY_FILE", str(Path.home() / ".finreq_agents" / "secret.key")))
