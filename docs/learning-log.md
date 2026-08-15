# Learning Log — Tech Debt Copilot
### MongoDB BuildFest SF 2026 · Persistent Context Sprint Hack

---

## What We Set Out to Build

An AI agent that tells you whether your software is still supported — and remembers the conversation across restarts. The hackathon theme was "Persistent Context" and MongoDB Atlas was the required data layer. We had one day.

---

## Real Learnings (What We Didn't Expect)

### 1. deepseek-v4-flash needs explicit routing rules, not hints

**What we tried first:** Descriptive tool metadata — "call this tool when the user provides a GitHub URL."  
**What happened:** The LLM responded in prose ("please specify your software" / "you need to run this locally") instead of calling the tool.  
**What fixed it:** Rewriting the system prompt as hard `RULE 1-6` blocks with "IMMEDIATELY call" language. Imperative grammar, not descriptive. The model needs to be told *exactly* what to do in *exactly* which condition.

> **Lesson:** Instruction-tuned models follow rules differently than they follow descriptions. When tool routing fails, the prompt is probably the bug, not the model.

---

### 2. Asymmetric embeddings matter more than we thought

Voyage AI's `voyage-3.5` has two `input_type` modes: `"document"` (at index time) and `"query"` (at search time). We initially indexed everything with no `input_type`.

Results were mediocre — semantic queries like "is Python 3.9 still supported?" missed obvious matches.

After switching to asymmetric mode (`document` for EOL records, `query` for user queries), recall improved noticeably on longer natural-language questions.

> **Lesson:** Read the embedding model docs. Asymmetric models need asymmetric usage.

---

### 3. MongoDB Atlas connection pooling and the deployed-mode problem

`MongoClient()` with default settings opens a fresh TCP connection each time. Inside a Streamlit app that runs for hours, the first connection (established by the LangGraph graph builder at startup) stays alive in the pool. But `_eol_lookup()`, called on every dashboard render, was creating a *new* client — which timed out on Atlas when the network was congested.

Fix: `@st.cache_resource` on a shared `MongoClient`. One warm connection, shared across the entire app lifetime. Zero extra latency.

Separately: when the app is deployed, `scan_local_stack()` scans the **server**, not the user's machine. We solved this with paste mode — users run `pip list` locally and paste the output, and the agent parses it.

> **Lesson:** Know which machine your code runs on. And share database connections.

---

### 4. Streamlit session state + st.rerun() has subtle race conditions

The flow was:  
1. Sidebar button click → run scan → set `st.session_state.dashboard` → call `st.rerun()`  
2. On rerun: render dashboard → send prompt to LLM.

At first, the dashboard was rendering before the scan finished. The fix: run the scan *inside* the button's `if` block (blocking), *then* set the prompt and rerun. Streamlit runs the button block synchronously — we had been queuing the scan in the wrong place.

> **Lesson:** In Streamlit, blocking work inside a button `if` block runs before the rerun. Use that.

---

### 5. CSS in Streamlit: Playwright's scroll container is not `window`

When taking automated screenshots with Playwright, `window.scrollTo(0, 0)` had no effect. Streamlit renders inside its own scroll container (`section[data-testid="stMain"]`). The fix was using `element.scroll_into_view_if_needed()` on the specific element we wanted visible, rather than scrolling the window.

> **Lesson:** Headless browser automation of Streamlit apps requires element-level scrolling, not window scrolling.

---

### 6. GitHub Push Protection will block secrets even in squashed commits

We accidentally committed a LangSmith API key. GitHub's push protection blocked the push. Squash + force-push to remove it from history, then re-push. `.env` is now in `.gitignore` from commit 1.

> **Lesson:** Audit `.gitignore` before the first commit. Not after.

---

### 7. LangGraph's MongoDBSaver makes persistence trivial — and surprising

We expected persistence to be hard. It wasn't. `MongoDBSaver(client, db_name=...)` dropped straight in as the `checkpointer` argument to `graph.compile()`. Every conversation turn — including all tool call results — is stored in MongoDB automatically.

The surprise: the full LangGraph `MessagesState` (including tool invocations) is serialized per `thread_id`. This means you can restart the Streamlit server mid-conversation and the agent remembers everything, because the state lives in Atlas, not in the process.

> **Lesson:** When the persistence layer is MongoDB, "persistent context" is genuinely easy. That was the hackathon's point.

---

### 8. Endoflife.date data needs ETL, not just a scrape

The `endoflife.date` API returns per-product JSON with non-uniform schemas — some products have `eol: "2025-01-15"`, others have `eol: false`, others have `lts: true` with no eol field. Naively storing these breaks queries.

We normalized everything: boolean `eol` → null, computed `eol_display` for human-readable output, standardized date strings. The ingest script (`01_ingest.py`) handles this normalization before embedding.

> **Lesson:** Public APIs return data for humans, not databases. Normalize before you store.

---

## What We'd Do Differently

| What | Why |
|---|---|
| Build the `pip list` paste mode from day 1 | The deploy-mode problem is real; scan_local_stack only works on the host |
| Add a `@st.cache_data(ttl=600)` layer on EOL lookups | Reduces Atlas round-trips significantly on repeated scans |
| Test deepseek-v4-flash tool routing earlier | We lost ~3 hours chasing a "model issue" that was a prompt issue |
| Set up `.gitignore` before writing any code | GitHub Push Protection blocked us mid-session |
| Use a fixed seed for demo scans | Randomness in `scan_all()` results made demos less consistent |

---

## Technical Wins

- **8,322 product lifecycle records** indexed in MongoDB Atlas with Voyage AI embeddings
- **6 tools** — scan local, scan repo, EOL search, CVE check, 90-day triage, industry trends
- **Zero infrastructure besides Atlas** — no Redis, no queues, no separate vector DB
- **Full conversation persistence** via MongoDBSaver — restarts are invisible to the user
- **< 2s dashboard render** from MongoDB direct (bypasses LLM for the metrics cards)
- **GitHub URL scanning without clone** — fetches raw dependency files over HTTP

---

## Stack That Worked Well Together

```
MongoDB Atlas     → vector store + graph persistence in one service
Voyage AI         → best in class asymmetric embeddings for EOL queries
Fireworks AI      → fast inference on deepseek-v4-flash
LangGraph         → tool routing + state management (MongoDBSaver drop-in)
Streamlit         → rapid UI with custom CSS, fast enough for a hackathon
endoflife.date    → best freely available EOL dataset (8,300+ product cycles)
```

---

*Built at MongoDB BuildFest SF 2026 — August 13-14*
