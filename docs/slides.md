# Tech Debt Copilot — Pitch Deck
### MongoDB BuildFest SF 2026 · Persistent Context Sprint Hack

---

## Slide 1 — The Problem

### Every engineering team has a ticking clock they can't see.

- **8,300+** software versions reach end-of-life every year
- Most teams discover EOL **after** a CVE hits, not before
- Existing tools are one-shot scanners — no memory, no conversation, no triage

> "We were running Django 1.10 in production for **3,176 days past end-of-life**."
> *(gothinkster/django-realworld-example-app — real public repo, real numbers)*

---

## Slide 2 — The Solution

# Tech Debt Copilot

**An AI agent that knows your software's expiry date — and remembers it.**

```
You:    "Scan our backend repo."
Agent:  🔴 Django 1.10 — EXPIRED 3,176 days ago
        🟡 Python 3.9  — 47 days remaining
        🟢 PostgreSQL 15 — OK (1,204 days)
        Recommended: upgrade Django immediately, plan Python 3.12 migration.

You:    "What CVEs are active on Django 1.10?"
Agent:  CVE-2023-36053 (HIGH) — ReDoS in EmailValidator...
        ← remembers the scan. No re-scanning needed.
```

**The thread persists in MongoDB Atlas. Restart the server. Ask again. It remembers.**

---

## Slide 3 — Live Demo Flow

### Step 1 · Scan Local Machine
One click — detects Python, pip, Node.js, npm installs.
Dashboard shows 5 lifecycle metrics in **< 2 seconds** (MongoDB direct, no LLM wait).

### Step 2 · Scan Any GitHub Repo
Paste a URL — agent fetches `requirements.txt`, `package.json`, `pyproject.toml`, `go.mod` over HTTP.
No clone. No access tokens. Works on any public repo.

### Step 3 · Persistent Conversation
Follow-up questions work across sessions.
"Check CVEs for what you found" → agent recalls the scan from MongoDB.

---

## Slide 4 — Architecture

```
┌─────────────────────────────────────────────────┐
│                 Streamlit UI                    │
│   Dashboard metrics  ·  Chat  ·  Scan buttons  │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              LangGraph Agent                    │
│                                                 │
│  scan_repo()  search_eol()  find_upcoming()     │
│  scan_local() check_cve()   industry_trends()   │
└────────┬──────────────────┬──────────────────────┘
         │                  │
         ▼                  ▼
┌──────────────┐   ┌────────────────────────┐
│  MongoDB     │   │  External APIs         │
│  Atlas       │   │                        │
│              │   │  OSV.dev  (live CVEs)  │
│  eol_lifecycle   │  endoflife.date (ETL)  │
│  $vectorSearch   │  GitHub raw HTTP       │
│              │   └────────────────────────┘
│  checkpoints │
│  (LangGraph) │
└──────────────┘
```

**LLM:** Fireworks AI · `deepseek-v4-flash`  
**Embeddings:** Voyage AI · `voyage-3.5` · 1024-dim

---

## Slide 5 — MongoDB Atlas: The Core

### Why MongoDB is not just storage here

| Challenge | MongoDB Solution |
|---|---|
| Semantic EOL search ("is Python 3.9 still supported?") | `$vectorSearch` · Voyage AI 1024-dim embeddings |
| Structured date queries ("expires in 90 days?") | Aggregation pipeline · `$gte` / `$lte` on date fields |
| Persistent agent memory across restarts | **MongoDBSaver** LangGraph checkpointer |
| Category-level trend analysis | `$group` + `$count` aggregation |

> **One database. Vector + structured + graph state. Zero extra infrastructure.**

---

## Slide 6 — Persistent Context (The Hackathon Theme)

### Stateless RAG vs. Tech Debt Copilot

| | Stateless RAG | Tech Debt Copilot |
|---|---|---|
| Restart server | Context lost | Thread resumes in MongoDB |
| Follow-up questions | Must re-explain | Agent remembers full scan |
| Multi-session audit | Impossible | Thread ID is shareable |
| Knowledge base | Static file | Live Atlas collection |

**MongoDBSaver stores the full LangGraph message graph per `thread_id`.**  
Every tool call, every result, every user message — persisted atomically.

---

## Slide 7 — What We Detected in 2 Minutes

*Results from scanning a real public repo (gothinkster/django-realworld-example-app)*

| Package | Detected Version | Status | Days Overdue |
|---|---|---|---|
| Django | 1.10.5 | 🔴 EXPIRED | 3,176 days |
| Python | 2.7 (implied) | 🔴 EXPIRED | 1,700+ days |

*Results from scanning a developer's local machine (demo)*

| Category | Count |
|---|---|
| Technologies scanned | 18 |
| Unsupported (action required) | 4 |
| Expiring within 1 year | 3 |
| Unknown lifecycle | 6 |
| Healthy | 5 |

---

## Slide 8 — Tech Stack

```
┌──────────────────────────────────────────┐
│  HACKATHON SPONSORS                      │
│  MongoDB Atlas    · Vector + Persistence │
│  Fireworks AI     · deepseek-v4-flash    │
│  Voyage AI        · voyage-3.5 (1024-d)  │
└──────────────────────────────────────────┘
┌──────────────────────────────────────────┐
│  FRAMEWORK                               │
│  LangGraph        · Agent + checkpointer │
│  LangChain        · Tool definitions     │
│  Streamlit        · UI + dashboard       │
└──────────────────────────────────────────┘
┌──────────────────────────────────────────┐
│  DATA SOURCES                            │
│  endoflife.date   · 8,322 product cycles │
│  OSV.dev          · Live CVE database    │
│  GitHub raw HTTP  · Repo dep files       │
└──────────────────────────────────────────┘
```

---

## Slide 9 — What's Next

- **Team scan** — one shared MongoDB thread per squad, not per person
- **CI/CD gate** — GitHub Action that fails PRs introducing EOL deps
- **Slack bot** — `@techdebt scan #backend-repo` in any channel
- **Scheduled triage** — weekly Atlas trigger → EOL digest email
- **Extended support lookup** — Red Hat, Ubuntu ESM, AWS LTS pricing

---

## Slide 10 — Try It

```bash
git clone https://github.com/researchsite/tech-debt-copilot
cp .env.example .env   # add your keys
pip install -r requirements.txt
streamlit run app.py
```

**Ask:**
- `"Scan my installed stack"`
- `"https://github.com/gothinkster/django-realworld-example-app"`
- `"What's expiring in the next 90 days?"`
- `"Check CVEs for Django 1.10"`

---

*MongoDB BuildFest SF 2026 · Persistent Context Sprint Hack*  
*Built with MongoDB Atlas · Fireworks AI · Voyage AI · LangGraph*
