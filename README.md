# Finance Requirements Engineering Agents

A local, agentic AI app that automates two steps of requirements engineering for the finance sector:

1. **Requirements Agent** reads your input and writes functional and non-functional requirements, each with a priority and the reasoning behind it. The input is either a typed description of a finance feature or an uploaded document (PDF, DOCX, TXT or MD).
2. **SDLC Agent** reads those requirements and recommends an SDLC model (Agile, Waterfall, V-Model, Spiral, DevSecOps or a hybrid). It justifies the choice using risk, regulatory criticality, change frequency, requirement clarity and security.

Everything runs **on your machine**:
- The model is a pre-trained model served by [Ollama](https://ollama.com) (default `llama3.2:3b`). No cloud APIs and no fine-tuning.
- Document search uses local embeddings and a local vector database.
- Accounts are stored in a local file, and no emails are sent.

```
              ┌───────────────────── LangGraph ──────────────────────┐
 typed text   │                                                      │
 or document ─┼─► prepare_context ─► requirements_agent ─► sdlc_agent ┼─► results
              │   (direct or RAG)                                    │
              └──────────────────────────┬───────────────────────────┘
                                         ▼
                              logs/audit_log.jsonl
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| LLM | Ollama + `llama3.2:3b` (switchable), called only from `llm_service.py` |
| Orchestration | LangGraph: agents are graph nodes sharing one state object |
| Output validation | Pydantic schemas, Ollama structured outputs, json-repair |
| Document input | PyMuPDF (PDF), python-docx (DOCX), plain text (TXT/MD) |
| RAG | Sentence Transformers `all-MiniLM-L6-v2` (CPU) + ChromaDB (persistent, local) |
| Web UI | Streamlit |
| Login | streamlit-authenticator (bcrypt hashes, session cookie), local `users.yaml` |
| Audit trail | JSON Lines file with a timestamp and the user for every event |

---

## Project structure

```
SE Project/
├── app.py                    # Streamlit entry point: arranges the page (streamlit run app.py)
├── run_demo.py               # Run the pipeline from the terminal (no UI, no login)
├── pipeline.py               # run_pipeline(): runs the graph, streams progress, returns results
├── llm_service.py            # The ONLY code that calls Ollama
├── config.py                 # All settings: model, limits, RAG sizes, folders
├── context_loader.py         # Seam between agents and RAG: direct text vs. retrieval
├── document_reader.py        # Text extraction from PDF / DOCX / TXT / MD
├── output_parser.py          # Cleans + validates each agent's JSON
├── audit_log.py              # Timestamped audit trail (logs/audit_log.jsonl)
├── orchestration/            # LangGraph
│   ├── state.py              #   the shared state passed between nodes
│   ├── nodes.py              #   what each node does (prepare context, run an agent)
│   └── builder.py            #   how nodes are connected  ← add branches/approvals here
├── agents/
│   ├── registry.py           # WHICH agents exist, in what order  ← add agents here
│   ├── prompt_builder.py     # HOW a YAML prompt becomes model messages
│   └── schemas.py            # WHAT each agent must return (Pydantic)
├── prompts/                  # Editable prompts, one YAML per agent
├── rag/
│   ├── chunker.py            # overlapping chunks
│   ├── vector_store.py       # embeddings + ChromaDB
│   └── worker.py             # runs retrieval in a separate process (saves RAM)
├── auth/
│   ├── user_store.py         # accounts: sign-up, hashing, security-question reset
│   └── auth_ui.py            # login / sign-up / reset screens
├── ui/                       # Streamlit screens (sidebar, input, progress, results)
├── documents/                # Sample finance documents (demo examples only)
├── .streamlit/config.toml    # Streamlit settings (usage stats off, upload limit, theme)
└── requirements.txt
```

Created automatically at runtime (and git-ignored):
- `logs/`: the audit trail.
- `vector_store/`: the ChromaDB database.
- `models/`: the embedding model, downloaded once.
- `auth/users.yaml`: user accounts.

---

## Setup (Windows; macOS/Linux are almost identical)

### 1. Install Ollama and pull the model
1. Install Ollama from <https://ollama.com/download> (or `winget install Ollama.Ollama`). It then runs in the background; look for the llama icon in the system tray.
2. Pull the model (about 2 GB, one time):
   ```powershell
   ollama pull llama3.2:3b
   ```

### 2. Create the Python environment
CrewAI is gone, but Python **3.10–3.13** is still recommended (tested with 3.12). If you only have Python 3.14, use `uv` to get 3.12:
```powershell
pip install uv
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```
This installs PyTorch (CPU version) for the embedding model, so the first install downloads a few hundred MB.

### 3. Run the app
```powershell
.venv\Scripts\activate
streamlit run app.py
```
Open <http://localhost:8501>. (If PowerShell blocks `activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.)

---

## Using the app

### First time: create an account
1. Open the **📝 Sign up** tab.
2. Enter your name, a username, an email, a password (at least 8 characters, with a letter and a number), and a security question with its answer.
3. Go to **🔑 Log in** and sign in. You stay logged in for 1 day, or until you click **Log out** in the sidebar.

**Forgot your password?** Use the **❓ Forgot password** tab. This is a **local reset**: the app is offline, so it can't send email. Instead, it asks your security question; answer it correctly and you can set a new password. Answers aren't case-sensitive. After 5 wrong answers, the form locks until the app restarts.

### Running the agents
1. Choose an input:
   - **✍️ Describe it**: type the finance feature, e.g. *"Loan approval module for a retail bank…"*.
   - **📄 Use a document**: upload a PDF, DOCX, TXT or MD file, or pick one of the sample documents. You can add an optional **Focus** (e.g. *"Instant payments with fraud screening"*) to say which part of the document to cover. Under the uploader, the app shows the document size and whether it will be used whole or through retrieval.
2. Click **🚀 Run agents**.
3. Watch the live progress: each step shows when it finishes. On a CPU-only laptop a run takes about **5–9 minutes**. Don't refresh the page. Inputs are locked during a run, and only one run can happen at a time.
4. Read the results:
   - Summary numbers at the top.
   - A **Requirements** tab with tables for the two requirement types.
   - An **SDLC** tab with the highlighted recommendation, the rating of each characteristic, the rejected alternatives and recommended practices.
   - A **Source & audit** tab showing how the document was used and this run's audit log.
   - A **Download results (JSON)** button.

The sidebar shows whether Ollama is running and lets you switch between installed models.

### Terminal mode (no login)
```powershell
python run_demo.py                                 # loan-approval demo using the sample documents
python run_demo.py my_spec.pdf                     # requirements for your own document
python run_demo.py my_spec.pdf "KYC onboarding"    # ...focused on one topic
```

---

## How documents are handled (RAG)

`context_loader.py` decides by size:

| Input | What happens |
|---|---|
| Only a typed description | No document; the agent works from the description. |
| Document up to 6,000 characters (`MAX_CONTEXT_CHARS`) | The whole text goes into the prompt. This is fast and nothing is lost. |
| Larger document | **Retrieval**, described in the steps below. |

The retrieval steps are:
1. The text is split into ~900-character chunks that overlap by 150 characters.
2. Each chunk is embedded with `all-MiniLM-L6-v2` on the CPU.
3. The chunks are stored in ChromaDB (`vector_store/`).
4. Five searches run: your focus, business rules, security, compliance and performance. The best **6 chunks** (at most) are given to the agent.

Two more details:
- **Very large documents** are capped at 400,000 characters (`MAX_DOCUMENT_CHARS`, about 150 pages). A document that size takes about 1 minute to index.
- **Re-using a document** is quicker: each document is indexed once and the stored index is reused.

**Memory:** the embedding libraries need about 600 MB of RAM. They run in a separate short-lived process (`rag/worker.py`), so that memory is released as soon as retrieval finishes and Ollama keeps as much RAM as possible. The embedding model (~90 MB) is downloaded into `models/` on first use, then loads offline.

---

## Customising

**Settings:** everything is in [config.py](config.py): model name, context window (`NUM_CTX`), answer length cap, timeouts, and RAG sizes.

**Prompts:** edit the YAML files in [prompts/](prompts/). Changes apply on the next run. Only `{scenario}` and `{reference_context}` may be used in curly braces.

**Add an agent** (e.g. a Compliance Agent):
1. Add `prompts/compliance_agent.yaml`.
2. Add a `ComplianceOutput` class in [agents/schemas.py](agents/schemas.py).
3. Add an `AgentDefinition(..., receives_output_from=["requirements_agent"])` to [agents/registry.py](agents/registry.py).

The builder turns it into a graph node automatically, and it's logged and shown in the UI (as JSON until you add a renderer in `ui/results.py`).

**Branching and approvals:** [orchestration/builder.py](orchestration/builder.py) explains how to replace an edge with `add_conditional_edges()` (e.g. send unclear requirements to a clarification agent), or compile with `interrupt_before=[...]` to pause for human approval. The graph already uses a checkpointer, which is what makes pausing possible.

---

## Audit trail

Every run appends records to `logs/audit_log.jsonl`, one JSON object per line:
- **`pipeline_started`**: the user, model, scenario and source document.
- **`context_prepared`**: the method (none, direct or retrieval), chunk counts and timing.
- **`agent_completed`**: one per agent, with its full system and user prompt (including what it received from the previous agent), its output, token counts, timing and any parse error.
- **`pipeline_finished`** or **`pipeline_failed`**.

---

## Security notes
- Passwords and security answers are stored only as **bcrypt hashes** in `auth/users.yaml`. The file also holds a random secret that signs the login cookie. Don't share or commit it (it's git-ignored).
- To remove a user, delete their entry under `credentials: usernames:` in `auth/users.yaml`.
- Streamlit's usage statistics are switched off in `.streamlit/config.toml`, and Hugging Face and ChromaDB telemetry are switched off in code.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Sidebar says "Ollama is not running" | Start the Ollama app (or `ollama serve`), then refresh. |
| "No models installed" | `ollama pull llama3.2:3b` |
| Very slow runs | On CPU-only laptops, speed depends mostly on **free RAM**. The model needs about 2.6 GB. Close Chrome tabs and extra VS Code windows, and stop services you don't need (e.g. MySQL). |
| First document upload is slow | The embedding model (~90 MB) is downloaded once into `models/`. Later runs are offline. |
| "No text found" for a PDF | It's a scanned image without a text layer. OCR isn't supported. |
| "The model's answer wasn't valid structured JSON" | Rare, because Ollama's structured outputs force valid JSON. Run again; the raw answer is always shown and logged. |
| Locked out of an account | Use **Forgot password**. If the security answer is forgotten too, delete the user from `auth/users.yaml` and sign up again. |
| "Another run is already in progress" | Only one run at a time is allowed (Ollama processes one request at a time). Wait for it to finish. |
