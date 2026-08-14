# Tech Debt Copilot

> **MongoDB BuildFest SF 2026 · Persistent Context Sprint Hack**

Know your EOL risk before it becomes a CVE. An AI agent that keeps persistent memory of your software lifecycle posture — across restarts, sessions, and teammates.

---

## What It Does

Tech Debt Copilot is a conversational AI agent that answers one question:
**Is the software I'm running still supported?**

It scans your local machine or any GitHub repository, cross-references every detected dependency against a live End-of-Life database (8,300+ product versions), checks for active CVEs, and stores everything in MongoDB Atlas so the context is never lost.

### Key capabilities

| Capability | How |
|---|---|
| Local stack scan | Detects Python, pip, Node.js, npm installs |
| GitHub repo scan | Fetches dependency files over HTTP (no clone needed) |
| EOL lookup | MongoDB Atlas Vector Search · 8,322 product records |
| CVE cross-reference | Live queries to OSV.dev |
| 90-day triage | Aggregation pipeline finds what expires next |
| Industry trends | EOL exposure by tech category |
| Persistent threads | MongoDBSaver checkpointer — survives restarts |
| Voice output | ElevenLabs TTS (optional) |

---

## Architecture

```
User (Streamlit)
      │
      ▼
  LangGraph Agent  ◄──── MongoDBSaver (thread persistence)
      │
      ├── scan_local_stack()      → reads installed packages
      ├── scan_repository()       → fetches GitHub / local deps
      ├── search_eol_data()       → MongoDB Atlas Vector Search (Voyage AI)
      ├── check_cve_vulnerabilities() → OSV.dev REST API
      ├── find_upcoming_eols()    → MongoDB aggregation ($gte/$lte dates)
      └── analyze_industry_trends()  → category-level EOL exposure
              │
              ▼
         MongoDB Atlas
         ├── eol_lifecycle   (8,322 records · vector index · endoflife.date)
         └── checkpoints     (LangGraph thread store)
```

**LLM:** `deepseek-v4-flash` via Fireworks AI  
**Embeddings:** Voyage AI `voyage-3.5` · 1024-dim · asymmetric (`document` at ingest, `query` at search)  
**Vector index:** `vector_index` on `eol_lifecycle.embedding` · cosine similarity · 1024 dimensions

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/researchsite/tech-debt-copilot
cd tech-debt-copilot
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in the keys:
```

```env
MONGO_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/<db>?appName=<app>
FIREWORKS_API_KEY=fw_...
LLM_MODEL=accounts/fireworks/models/deepseek-v4-flash
VOYAGE_API_KEY=pa-...
EMBEDDING_MODEL=voyage-3.5
ELEVENLABS_API_KEY=          # optional — leave blank to disable TTS
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

### 3. Download and ingest EOL data

```bash
python 00_download_data.py   # pulls endoflife.date JSON → data/
python 01_ingest.py          # embeds + upserts into MongoDB Atlas
python 02_setup_index.py     # creates the vector search index
python verify_setup.py       # sanity check — should print record count
```

### 4. Run the app

```bash
streamlit run app.py
```

Open `http://localhost:8501`

---

## Demo Flow

**Step 1 — Scan your machine**  
Click `[ Scan ] My Stack` in the sidebar. The dashboard shows 5 lifecycle metrics instantly (no LLM wait), then the agent narrates the full risk report.

**Step 2 — Scan a GitHub repo**  
Pick a demo repo or paste any GitHub URL. The agent fetches `requirements.txt`, `package.json`, `pyproject.toml`, `go.mod`, `.nvmrc` over HTTP and cross-references every dep.

Good repos for demo:
- `https://github.com/gothinkster/django-realworld-example-app` — Django 1.10, expired 2017
- `https://github.com/gothinkster/react-redux-realworld-example-app` — React 16 era
- `https://github.com/gothinkster/node-express-realworld-example-app` — Node / Express

**Step 3 — Ask follow-up questions**  
The thread is persisted in MongoDB — "check CVEs for what you found" works even after a restart.

---

## MongoDB Atlas Features Used

| Feature | Usage |
|---|---|
| **Vector Search** | `$vectorSearch` on 1024-dim Voyage AI embeddings · cosine similarity · pre-filter by `product_name` |
| **Aggregation Pipeline** | Date range queries for upcoming EOLs; category grouping for trends |
| **MongoDBSaver (LangGraph)** | Checkpointer that persists full conversation graph state per `thread_id` |
| **Atlas Free Tier** | Entire project runs on M0 |

---

## Project Structure

```
tech-debt-copilot/
├── app.py                  # Streamlit UI + dashboard
├── agent/
│   ├── graph.py            # LangGraph agent + system prompt
│   ├── tools.py            # 6 LangChain tools
│   ├── scanner.py          # Local machine package detection
│   └── repo_scanner.py     # GitHub URL / local path dependency parser
├── 00_download_data.py     # Pull endoflife.date data
├── 01_ingest.py            # Embed + upsert to MongoDB Atlas
├── 02_setup_index.py       # Create vector search index
├── verify_setup.py         # Connection + data sanity check
├── .streamlit/config.toml  # Dark theme config
├── .env.example            # Key template (no real values)
└── requirements.txt
```

---

## Hackathon Theme Alignment

**Theme: Persistent Context Sprint Hack**

The core MongoDB angle: this agent is *stateful across time*. Unlike a stateless RAG app:

- **Thread memory** — MongoDBSaver stores the full LangGraph conversation graph. Restart the server; the thread resumes exactly where it left off.
- **Living knowledge base** — The EOL database is in Atlas, queryable by semantic similarity AND by structured aggregation in the same pipeline.
- **Persistent posture** — The dashboard metrics represent the last known scan state, persisted in session and ready to query against.

---

## Tech Stack

- **MongoDB Atlas** — vector store + thread checkpointer
- **Voyage AI** — `voyage-3.5` embeddings (1024-dim)
- **Fireworks AI** — `deepseek-v4-flash` LLM (hackathon sponsor)
- **LangGraph** — agent graph + tool routing + MongoDBSaver
- **Streamlit** — UI + dashboard
- **endoflife.date** — EOL data source (8,322 product lifecycle records)
- **OSV.dev** — live CVE lookup
- **ElevenLabs** — optional voice output

---

*Built for MongoDB BuildFest SF 2026 · Theme: Persistent Context Sprint Hack*
