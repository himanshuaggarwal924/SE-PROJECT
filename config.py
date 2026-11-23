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

# --- Folder locations -----------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DOCUMENTS_DIR = PROJECT_ROOT / "documents"  # sample finance documents (demo only)
PROMPTS_DIR = PROJECT_ROOT / "prompts"      # one editable YAML file per agent
LOGS_DIR = PROJECT_ROOT / "logs"            # audit trail is written here
AUDIT_LOG_FILE = LOGS_DIR / "audit_log.jsonl"
VECTOR_DB_DIR = PROJECT_ROOT / "vector_store"  # ChromaDB database files
MODELS_DIR = PROJECT_ROOT / "models"           # downloaded embedding model
USERS_FILE = PROJECT_ROOT / "auth" / "users.yaml"  # local user accounts (hashed)
