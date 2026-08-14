"""
app.py -- Tech Debt Copilot
UI design language: github.com/eshan-bhimani/AgentSoftwareLife
"""

import os
import re
import uuid
from datetime import datetime, UTC
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB  = os.getenv("MONGO_DB", "techdebt_copilot")
MONGO_COL = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
MAX_INPUT = 1000


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def _tts(text: str) -> bytes | None:
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from elevenlabs.client import ElevenLabs
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM").strip()
        client   = ElevenLabs(api_key=api_key)
        tts_text = text[:2000].rsplit(" ", 1)[0] if len(text) > 2000 else text
        stream   = client.text_to_speech.convert(
            voice_id=voice_id, text=tts_text,
            model_id="eleven_multilingual_v2", output_format="mp3_22050_32",
        )
        return b"".join(stream)
    except Exception:
        return None


# ── Input security ─────────────────────────────────────────────────────────────

_INJECTION = re.compile(
    r"(ignore (previous|all|prior)|forget (everything|instructions)|"
    r"you are now|act as|disregard|system prompt|jailbreak|"
    r"pretend (you are|to be)|override|bypass|<\|.*?\|>|"
    r"\[INST\]|\[/INST\]|### (Human|Assistant):)",
    re.IGNORECASE,
)

def sanitize_input(text: str) -> tuple[str, str | None]:
    text = text.strip()
    if not text:
        return "", "Please enter a question."
    if len(text) > MAX_INPUT:
        return "", f"Query too long ({len(text)} chars). Keep it under {MAX_INPUT}."
    if _INJECTION.search(text):
        return "", "That query pattern isn't supported."
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text), None


# ── Direct scan (for dashboard, bypasses LLM) ─────────────────────────────────

STATUS_RANK = {"EXPIRED": 0, "CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "UNKNOWN": 4, "OK": 5}
STATUS_CSS  = {"EXPIRED": "unsupported", "CRITICAL": "unsupported",
               "HIGH": "soon", "MEDIUM": "soon", "OK": "healthy", "UNKNOWN": "unknown"}


def _classify(days: int | None) -> str:
    if days is None: return "UNKNOWN"
    if days < 0:     return "EXPIRED"
    if days <= 30:   return "CRITICAL"
    if days <= 90:   return "HIGH"
    if days <= 365:  return "MEDIUM"
    return "OK"


def _eol_lookup(items: list[dict]) -> list[dict]:
    from pymongo import MongoClient
    today  = datetime.now(UTC).date()
    client = MongoClient(MONGO_URI)
    coll   = client[MONGO_DB][MONGO_COL]
    records = []
    for item in items:
        doc = coll.find_one(
            {"product_name": item["eol_product"], "cycle": item["cycle"]},
            {"eol": 1, "eol_display": 1, "extended_support": 1,
             "product_label": 1, "lts": 1, "support": 1, "_id": 0},
        )
        eol_str = doc.get("eol") if doc else None
        days    = None
        if eol_str:
            try:
                days = (datetime.strptime(eol_str, "%Y-%m-%d").date() - today).days
            except ValueError:
                pass
        records.append({
            "name":             (doc.get("product_label") or item["package"]) if doc else item["package"],
            "version":          item["version"],
            "cycle":            item["cycle"],
            "source":           item.get("source", item.get("file", "detected")),
            "provider":         item.get("eol_product", ""),
            "final_eol":        eol_str or "unknown",
            "eol_display":      doc.get("eol_display", "unknown") if doc else "Not tracked",
            "support_end":      doc.get("support", "unknown") if doc else "unknown",
            "extended_support": doc.get("extended_support") if doc else None,
            "standard_eol":     eol_str or "unknown",
            "days":             days,
            "status":           _classify(days),
            "lts":              doc.get("lts", False) if doc else False,
        })
    client.close()
    records.sort(key=lambda r: STATUS_RANK.get(r["status"], 9))
    return records


def run_local_scan() -> dict | None:
    try:
        from agent.scanner import scan_all
        items   = scan_all()
        records = _eol_lookup(items) if items else []
        return {"records": records, "type": "local",
                "label": "Local machine", "scanned_at": datetime.now(UTC).isoformat()}
    except Exception:
        return None


def run_repo_scan(source: str) -> dict | None:
    try:
        from agent.repo_scanner import scan_repo
        items, meta = scan_repo(source)
        records     = _eol_lookup(items) if items else []
        label       = meta.get("repo") or meta.get("path") or source
        return {"records": records, "type": "repo",
                "label": label, "scanned_at": datetime.now(UTC).isoformat()}
    except Exception:
        return None


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Tech Debt Copilot",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
    --bg:     #07111d;
    --panel:  #0e1a29;
    --line:   #27374a;
    --ink:    #e8eef7;
    --muted:  #8e9cae;
    --cyan:   #61dce0;
    --green:  #65da99;
    --yellow: #f7c965;
    --red:    #ff746f;
}

/* ── Background ── */
.stApp {
    background: radial-gradient(circle at 12% 0, #163049 0, #07111d 38%, #06101a 100%) fixed !important;
    font-family: Manrope, sans-serif !important;
}
[data-testid="stAppViewContainer"] > .main, .block-container { background: transparent !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: var(--panel) !important;
    border-right: 1px solid var(--line) !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] > div:first-child { background: transparent !important; }

/* ── Top bar ── */
[data-testid="stHeader"] {
    background: var(--bg) !important;
    border-bottom: 1px solid var(--line) !important;
}

/* ── Typography ── */
* { font-family: Manrope, sans-serif; }
h1 {
    font-size: 2.1rem !important; font-weight: 800 !important;
    letter-spacing: -0.06em !important; color: var(--ink) !important;
    margin: 0.2rem 0 !important;
}
h2 {
    font: 800 0.78rem Manrope, sans-serif !important;
    letter-spacing: 0.09em !important; text-transform: uppercase !important;
    color: var(--ink) !important; margin: 1.8rem 0 0.6rem !important;
}
h3 { font-weight: 700 !important; color: var(--ink) !important; }
.stCaption, [data-testid="stCaptionContainer"] p {
    font: 500 0.62rem 'DM Mono', monospace !important;
    letter-spacing: 0.10em !important; text-transform: uppercase !important;
    color: var(--muted) !important;
}

/* ── Buttons ── */
.stButton > button {
    background: #192b3c !important; color: #cbe0e8 !important;
    font: 800 0.64rem Manrope, sans-serif !important;
    letter-spacing: 0.05em !important; text-transform: uppercase !important;
    border: 1px solid var(--line) !important; border-radius: 5px !important;
    padding: 0.62rem 0.85rem !important;
    transition: background 0.15s, color 0.15s, border-color 0.15s !important;
    box-shadow: none !important;
}
.stButton > button:hover {
    background: var(--cyan) !important; color: #04131c !important;
    border-color: var(--cyan) !important; transform: none !important;
}
.stButton > button[kind="primary"] {
    background: var(--cyan) !important; color: #04131c !important;
    border-color: var(--cyan) !important; font-weight: 800 !important;
}
.stButton > button[kind="primary"]:hover { background: #a1f4f5 !important; }

/* ── Chat messages ── */
[data-testid="stChatMessage"] {
    border-radius: 6px !important; margin: 0.42rem 0 !important;
    padding: 0.68rem 0.85rem !important; font-size: 0.82rem !important;
    line-height: 1.58 !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: #17384c !important; border: none !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
    background: #152030 !important; border: 1px solid #293a4d !important;
}

/* ── Chat input ── */
[data-testid="stChatInput"] {
    background: var(--panel) !important;
    border-top: 1px solid var(--line) !important;
    border-radius: 0 !important; border-left: none !important;
    border-right: none !important; border-bottom: none !important;
}
[data-testid="stChatInput"] textarea {
    background: transparent !important; color: var(--ink) !important;
    font: 400 0.85rem Manrope !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: var(--muted) !important; }

/* ── Text input ── */
.stTextInput > div > div {
    background: #0a1825 !important; border: 1px solid var(--line) !important;
    border-radius: 5px !important;
}
.stTextInput input { background: transparent !important; color: var(--ink) !important; }
.stTextInput input::placeholder { color: var(--muted) !important; }
.stTextInput > div > div:focus-within { border-color: var(--cyan) !important; }

/* ── Status widget ── */
[data-testid="stStatusWidget"] {
    background: var(--panel) !important; border: 1px solid var(--line) !important;
    border-radius: 7px !important;
}
[data-testid="stStatusWidget"][data-state="complete"] { border-color: rgba(101,218,153,0.4) !important; }
[data-testid="stStatusWidget"][data-state="error"]    { border-color: rgba(255,116,111,0.4) !important; }

/* ── Expander (stack rows) ── */
[data-testid="stExpander"] {
    background: rgba(15,28,43,0.76) !important;
    border: 1px solid var(--line) !important; border-radius: 7px !important;
    margin: 0.35rem 0 !important;
}
[data-testid="stExpander"] summary {
    font-size: 0.78rem !important; color: var(--ink) !important;
    font-weight: 600 !important;
}

/* ── Dividers ── */
hr { border-color: var(--line) !important; margin: 0.65rem 0 !important; }

/* ── Markdown ── */
.stMarkdown strong { color: var(--ink) !important; font-weight: 700 !important; }
.stMarkdown code {
    background: #0a1320 !important; color: #9beff0 !important;
    font: 0.72rem 'DM Mono', monospace !important;
    padding: 0.1rem 0.28rem !important; border-radius: 3px !important;
}
.stMarkdown pre {
    background: #07111d !important; border: 1px solid var(--line) !important;
    border-radius: 5px !important; padding: 0.8rem !important;
}
.stMarkdown blockquote {
    border-left: 3px solid var(--cyan) !important;
    background: rgba(97,220,224,0.06) !important;
    border-radius: 0 5px 5px 0 !important;
    padding: 0.5rem 0.9rem !important; margin: 0.4rem 0 !important;
    color: #b9c5d4 !important;
}

/* ── Alert ── */
[data-testid="stAlert"] {
    background: rgba(247,201,101,0.07) !important;
    border: 1px solid rgba(247,201,101,0.28) !important;
    border-radius: 5px !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--line); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #3d5470; }

/* ── Custom dashboard HTML classes ── */
.kicker {
    font: 500 0.63rem 'DM Mono', monospace;
    letter-spacing: 0.10em; text-transform: uppercase; color: var(--cyan);
    display: block; margin-bottom: 4px;
}
.metrics-grid {
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 0.65rem; margin: 0.8rem 0 1.6rem;
}
.metric-card {
    border: 1px solid var(--line); border-radius: 8px;
    background: linear-gradient(130deg, #112033, #0d1724);
    padding: 1rem; min-height: 100px;
}
.metric-card label {
    font: 500 0.60rem 'DM Mono', monospace; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--muted); display: block;
}
.metric-card strong {
    display: block; font-size: 1.8rem; font-weight: 800;
    letter-spacing: -0.08em; margin: 0.25rem 0 0.15rem; color: var(--ink);
}
.metric-card em {
    font-style: normal; color: var(--muted);
    font: 400 0.68rem 'DM Mono', monospace; letter-spacing: 0.04em;
}
.metric-card.bad  strong { color: var(--red); }
.metric-card.warn strong { color: var(--yellow); }
.metric-card.good strong { color: var(--green); }

.stack-head {
    display: grid;
    grid-template-columns: 1.6fr 1fr 1.1fr 0.65fr 1.1fr 0.6fr;
    gap: 1rem; padding: 0 0.9rem 0.5rem;
    font: 500 0.60rem 'DM Mono', monospace;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted);
    border-bottom: 1px solid var(--line); margin-bottom: 0.4rem;
}
.stack-row {
    display: grid;
    grid-template-columns: 1.6fr 1fr 1.1fr 0.65fr 1.1fr 0.6fr;
    gap: 1rem; padding: 0.78rem 0.9rem;
    border: 1px solid var(--line); border-radius: 7px;
    background: rgba(15,28,43,0.76); margin: 0.32rem 0;
    font-size: 0.76rem; align-items: center; cursor: default;
}
.prod-name  { font-weight: 700; font-size: 0.88rem; }
.prod-sub   { font: 400 0.62rem 'DM Mono', monospace; color: var(--muted); margin-top: 2px; }
.badge {
    display: inline-block; padding: 0.18rem 0.38rem; border-radius: 3px;
    font: 700 0.60rem 'DM Mono', monospace; letter-spacing: 0.03em; text-transform: uppercase;
}
.badge.unsupported { color: #ffaaa5; background: #48272d; }
.badge.soon        { color: #ffe18c; background: #483c25; }
.badge.healthy     { color: #93eebd; background: #183b2e; }
.badge.unknown     { color: #b3c0cf; background: #273545; }
.risk-red          { color: var(--red); font-weight: 700; }
.risk-yellow       { color: var(--yellow); font-weight: 700; }
.risk-green        { color: var(--green); font-weight: 700; }
.risk-muted        { color: var(--muted); }
.window-text       { font: 400 0.65rem 'DM Mono', monospace; color: var(--muted); }

.section-head {
    font: 800 0.78rem Manrope, sans-serif; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--ink);
    display: flex; justify-content: space-between; align-items: center;
    margin: 2rem 0 0.7rem; padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--line);
}
.section-sub {
    font: 400 0.62rem 'DM Mono', monospace; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--muted); font-weight: 400;
}

.chat-top {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.75rem 1rem; border-bottom: 1px solid var(--line);
    font: 500 0.62rem 'DM Mono', monospace; letter-spacing: 0.08em;
    text-transform: uppercase; background: var(--panel); border-radius: 8px 8px 0 0;
    color: var(--muted);
}
.chat-top b { color: var(--green); font-weight: 500; }
.tools-bar {
    padding: 0.55rem 0.9rem; border-radius: 4px;
    background: #091320; color: #8392a5;
    font: 400 0.60rem 'DM Mono', monospace; letter-spacing: 0.04em;
    margin-bottom: 0.5rem;
}

.demo-step-label {
    font: 500 0.58rem 'DM Mono', monospace; letter-spacing: 0.13em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 5px; margin-top: 3px;
}
.repo-badge {
    display: inline-block; font: 500 0.57rem 'DM Mono', monospace;
    letter-spacing: 0.06em; text-transform: uppercase;
    padding: 2px 7px; border-radius: 3px;
    background: rgba(97,220,224,0.08); border: 1px solid rgba(97,220,224,0.20);
    color: var(--cyan); margin-bottom: 4px;
}
.followup-hint {
    font: 500 0.56rem 'DM Mono', monospace; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 5px; margin-top: 12px;
}
.sponsor-strip {
    font: 500 0.56rem 'DM Mono', monospace; letter-spacing: 0.08em;
    text-transform: uppercase; color: #3e5468; text-align: center;
    margin-top: 0.5rem; line-height: 2.1;
}
.scan-status-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: var(--green); box-shadow: 0 0 8px var(--green); margin-right: 5px;
}
</style>
""", unsafe_allow_html=True)


# ── Cached resources ───────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Connecting to MongoDB Atlas...")
def _get_graph():
    from agent.graph import build_graph, get_checkpointer
    return build_graph(checkpointer=get_checkpointer())


# ── Session state ──────────────────────────────────────────────────────────────

def _init():
    defaults = {
        "thread_id":       str(uuid.uuid4()),
        "messages":        [],
        "quick_prompt":    None,
        "display_prompt":  None,
        "last_tools":      [],
        "tts_enabled":     False,
        "dashboard":       None,   # {records, type, label, scanned_at}
        "scan_running":    False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── Demo content ───────────────────────────────────────────────────────────────

DEMO_REPOS = [
    ("Django Legacy App (2016)",
     "https://github.com/gothinkster/django-realworld-example-app",
     "Django 1.10 — expired 2017"),
    ("React Redux App",
     "https://github.com/gothinkster/react-redux-realworld-example-app",
     "React 16 era"),
    ("Express.js Backend",
     "https://github.com/gothinkster/node-express-realworld-example-app",
     "Node / Express"),
]

QUICK_PERSONAS = {
    "Industry EOL Trends": (
        "Give me the full industry EOL trend breakdown across all tech categories. "
        "Which categories have the most versions expiring this year?", "Industry EOL Trends"),
    "90-Day Triage": (
        "Run a critical 90-day EOL triage. What's expiring in the next 90 days?", "90-Day Triage"),
    "Ubuntu + CVEs": (
        "Our servers run Ubuntu 18.04 and 20.04. What's our EOL exposure and active CVEs?",
        "Ubuntu 18.04 + 20.04 — EOL and CVE check"),
    "MongoDB / Postgres": (
        "We run MongoDB 4.4, PostgreSQL 11, and Redis 6 in production. Migration deadlines?",
        "MongoDB 4.4 / PostgreSQL 11 / Redis 6"),
}

FOLLOWUP_SCAN = [
    ("Check CVEs", "Check CVEs for any expired packages found in the last scan"),
    ("Upgrade path?", "Give me the upgrade path for the highest-risk package in the last scan"),
    ("How long to fix?", "How long to upgrade the expired dependencies found?"),
]
FOLLOWUP_EOL = [
    ("Check CVEs", "Check CVEs for the versions we just discussed"),
    ("Next 90 days?", "What else expires in the next 90 days in the same category?"),
    ("Extended support?", "Are there extended support options for the products discussed?"),
]


def _set_prompt(llm_prompt: str, display: str):
    st.session_state.quick_prompt  = llm_prompt
    st.session_state.display_prompt = display
    st.rerun()


# ── Dashboard helpers ──────────────────────────────────────────────────────────

def _count(records, *statuses):
    return sum(1 for r in records if r["status"] in statuses)

def _window_text(r):
    d = r.get("days")
    if d is None: return "unknown"
    return f"{abs(d)}d ago" if d < 0 else f"{d}d"

def _risk_class(status):
    return {"EXPIRED": "risk-red", "CRITICAL": "risk-red",
            "HIGH": "risk-yellow", "MEDIUM": "risk-yellow",
            "OK": "risk-green"}.get(status, "risk-muted")


def render_dashboard(data: dict):
    records = data["records"]
    label   = data["label"]
    ts      = data.get("scanned_at", "")[:19].replace("T", " ")

    # ── Section header ────────────────────────────────────────────
    st.markdown(
        f'<div class="section-head">'
        f'Lifecycle Posture'
        f'<span class="section-sub">Last scan · {ts} · {label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Metrics grid ──────────────────────────────────────────────
    total    = len(records)
    bad      = _count(records, "EXPIRED", "CRITICAL")
    warn     = _count(records, "HIGH", "MEDIUM")
    unknown  = _count(records, "UNKNOWN")
    healthy  = _count(records, "OK")

    st.markdown(f"""
    <div class="metrics-grid">
        <div class="metric-card">
            <label>Technologies scanned</label>
            <strong>{total}</strong>
            <em>{data['type']}</em>
        </div>
        <div class="metric-card bad">
            <label>Unsupported</label>
            <strong>{bad}</strong>
            <em>action required</em>
        </div>
        <div class="metric-card warn">
            <label>Expiring soon</label>
            <strong>{warn}</strong>
            <em>within 1 year</em>
        </div>
        <div class="metric-card warn">
            <label>Unknown lifecycle</label>
            <strong>{unknown}</strong>
            <em>no atlas match</em>
        </div>
        <div class="metric-card good">
            <label>Healthy</label>
            <strong>{healthy}</strong>
            <em>normal support</em>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not records:
        st.markdown(
            '<p style="color:var(--muted);font-size:.82rem;padding:.8rem;'
            'border:1px dashed var(--line);border-radius:6px">'
            'No trackable packages found.</p>',
            unsafe_allow_html=True,
        )
        return

    # ── Stack table ───────────────────────────────────────────────
    st.markdown(
        '<div class="section-head">Your Stack'
        '<span class="section-sub">Sorted by final support deadline</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="stack-head">'
        '<span>Technology</span><span>Lifecycle status</span>'
        '<span>Final EOL</span><span>Risk</span><span>Provider</span><span>Window</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    for r in records:
        css   = STATUS_CSS.get(r["status"], "unknown")
        rcls  = _risk_class(r["status"])
        win   = _window_text(r)
        lts   = " · LTS" if r.get("lts") else ""
        ext   = r.get("extended_support") or "None recorded"

        with st.expander(
            f"{r['name']} {r['version']}  ·  {r['status']}  ·  EOL: {r['final_eol']}",
            expanded=False,
        ):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.caption("Standard Support Ends")
                st.markdown(f"**{r['support_end']}**")
            with c2:
                st.caption("Published EOL")
                st.markdown(f"**{r['standard_eol']}**")
            with c3:
                st.caption("Extended Support")
                st.markdown(f"**{ext}**")
            st.caption("Details")
            d = r.get("days")
            if d is None:
                window_detail = "unknown"
            elif d < 0:
                window_detail = "past end-of-life"
            else:
                window_detail = f"{d}d remaining"
            st.markdown(
                f"Detected via `{r['source']}`. "
                f"Risk classification: **{r['status']}** "
                f"({window_detail}){lts}."
            )


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        '<span class="kicker" style="display:block;margin-bottom:2px">Tech Debt Copilot</span>'
        '<span style="font:500 .58rem \'DM Mono\',monospace;letter-spacing:.08em;'
        'text-transform:uppercase;color:#8e9cae">Powered by MongoDB Atlas</span>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"Thread {st.session_state.thread_id[:10]}...")
    with col2:
        if st.button("New", help="Start a new conversation thread"):
            st.session_state.thread_id   = str(uuid.uuid4())
            st.session_state.messages    = []
            st.session_state.last_tools  = []
            st.session_state.dashboard   = None
            st.rerun()

    st.divider()

    # Step 1
    st.markdown('<div class="demo-step-label">Step 1 — Scan this machine</div>', unsafe_allow_html=True)
    if st.button("[ Scan ] My Stack", use_container_width=True, type="primary"):
        with st.spinner("Scanning local machine..."):
            st.session_state.dashboard = run_local_scan()
        _set_prompt(
            "Scan my locally installed software and tell me what's expired or at risk. Show everything grouped by urgency.",
            "Scan my installed stack",
        )

    st.divider()

    # Step 2
    st.markdown('<div class="demo-step-label">Step 2 — Scan a GitHub repo</div>', unsafe_allow_html=True)
    for label, url, hint in DEMO_REPOS:
        st.markdown(f'<div class="repo-badge">{hint}</div>', unsafe_allow_html=True)
        if st.button(label, use_container_width=True, key=f"repo_{label}"):
            with st.spinner(f"Fetching {url.split('github.com/')[-1]}..."):
                st.session_state.dashboard = run_repo_scan(url)
            _set_prompt(
                f"Use the scan_repository tool on this target: {url}",
                f"Scan repo: {url}",
            )

    st.caption("or enter a custom URL / local path:")
    repo_input = st.text_input(
        "custom", placeholder="https://github.com/owner/repo   or   C:/projects/app",
        label_visibility="collapsed", key="repo_field",
    )
    if st.button("Scan Custom Repo", use_container_width=True):
        if repo_input.strip():
            target = repo_input.strip()
            with st.spinner("Fetching repository..."):
                st.session_state.dashboard = run_repo_scan(target)
            _set_prompt(
                f"Use the scan_repository tool on this target: {target}",
                f"Scan repo: {target}",
            )
        else:
            st.warning("Enter a GitHub URL or local folder path.")

    st.divider()

    # Step 3
    st.markdown('<div class="demo-step-label">Step 3 — Quick questions</div>', unsafe_allow_html=True)
    for label, (llm_prompt, display) in QUICK_PERSONAS.items():
        if st.button(label, use_container_width=True, key=f"persona_{label}"):
            _set_prompt(llm_prompt, display)

    st.divider()

    has_el = bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
    st.session_state.tts_enabled = st.toggle(
        "Voice Output (ElevenLabs)" if has_el else "Voice Output (key not set)",
        value=st.session_state.tts_enabled, disabled=not has_el,
    )

    st.divider()
    st.markdown(
        '<div class="sponsor-strip">'
        'MongoDB Atlas &nbsp;|&nbsp; Voyage AI<br>'
        'Fireworks AI &nbsp;|&nbsp; LangGraph<br>'
        'endoflife.date &nbsp;|&nbsp; OSV.dev'
        '</div>',
        unsafe_allow_html=True,
    )


# ── Main area ──────────────────────────────────────────────────────────────────

# Header
st.markdown('<span class="kicker">MongoDB Atlas · Persistent Context</span>', unsafe_allow_html=True)
st.title("Tech Debt Copilot")
st.markdown(
    '<p style="color:#8e9cae;font-size:.90rem;margin:0 0 1rem">'
    'Persistent lifecycle intelligence for your software stack.</p>',
    unsafe_allow_html=True,
)

# Dashboard section (shown when a scan has been run)
if st.session_state.dashboard:
    render_dashboard(st.session_state.dashboard)
    st.markdown("<br>", unsafe_allow_html=True)

# Chat section header
st.markdown(
    '<div class="chat-top">'
    '<span>Ask your copilot &nbsp;·&nbsp; Thread memory enabled</span>'
    f'<b>● MongoDB thread restored</b>'
    '</div>',
    unsafe_allow_html=True,
)

tools_display = " &nbsp; ".join(
    f"✓ {t}" for t in (st.session_state.last_tools or ["scan_local_stack", "MongoDB Vector Search", "persistent thread"])
)
st.markdown(f'<div class="tools-bar">{tools_display}</div>', unsafe_allow_html=True)

# Render existing conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Follow-up buttons
if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
    last_tools = st.session_state.get("last_tools", [])
    followups  = FOLLOWUP_SCAN if ("scan_repository" in last_tools or "scan_local_stack" in last_tools) else FOLLOWUP_EOL if ("search_eol_data" in last_tools or "find_upcoming_eols" in last_tools) else []
    if followups:
        st.markdown('<div class="followup-hint">Quick follow-ups</div>', unsafe_allow_html=True)
        cols = st.columns(len(followups))
        for col, (btn_label, llm_prompt) in zip(cols, followups):
            with col:
                if st.button(btn_label, key=f"fu_{btn_label}", use_container_width=True):
                    _set_prompt(llm_prompt, btn_label)

# Resolve input
user_input = st.chat_input("Ask about your stack… e.g. Why is Python 3.9 risky?")
if user_input is None and st.session_state.quick_prompt:
    user_input = st.session_state.quick_prompt
    st.session_state.quick_prompt = None

# Auto-detect raw URL/path in chat input
if user_input:
    _s = user_input.strip()
    if ("github.com/" in _s or _s.startswith(("C:\\", "D:\\", "/", "./", "~/"))) and "scan_repository" not in _s:
        st.session_state.display_prompt = f"Scan repo: {_s}"
        user_input = f"Use the scan_repository tool on this target: {_s}"

# Process turn
if user_input:
    clean, error = sanitize_input(user_input)
    if error:
        st.warning(error)
        st.stop()

    display_text = st.session_state.display_prompt or clean
    st.session_state.display_prompt = None

    st.session_state.messages.append({"role": "user", "content": display_text})
    with st.chat_message("user"):
        st.markdown(display_text)

    graph  = _get_graph()
    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    with st.chat_message("assistant"):
        status_box      = st.status("Working...", expanded=True)
        response_holder = st.empty()
        full_response   = ""
        tools_called    = []

        try:
            for chunk in graph.stream(
                {"messages": [HumanMessage(content=clean)]},
                config=config, stream_mode="values",
            ):
                msgs = chunk.get("messages", [])
                if not msgs:
                    continue
                last = msgs[-1]

                if hasattr(last, "tool_calls") and last.tool_calls:
                    for tc in last.tool_calls:
                        name = tc.get("name", "tool")
                        args = tc.get("args", {})
                        if name not in tools_called:
                            tools_called.append(name)
                            if name == "scan_repository":
                                repo  = args.get("repo_url_or_path", "")
                                short = repo.split("github.com/")[-1] if "github.com" in repo else repo[:50]
                                status_box.write(f"Fetching dependency files from **{short}**...")
                                status_box.write("Checking: requirements.txt, package.json, pyproject.toml, go.mod...")
                            elif name == "scan_local_stack":
                                status_box.write("Scanning installed packages: Python, pip, Node.js, npm...")
                            elif name == "check_cve_vulnerabilities":
                                p = args.get("product", ""); v = args.get("version", "")
                                status_box.write(f"Querying OSV.dev CVEs for **{p} {v}**...")
                            elif name == "find_upcoming_eols":
                                status_box.write(f"Scanning EOL database — next **{args.get('days_ahead',180)} days**...")
                            else:
                                hint = args.get("product_name") or args.get("product") or args.get("query", "")[:40]
                                status_box.write(f"`{name}` {hint}")

                if isinstance(last, AIMessage) and isinstance(last.content, str) and last.content:
                    full_response = last.content
                    response_holder.markdown(full_response + " |")

            response_holder.markdown(full_response)
            status_box.update(label="Done", state="complete", expanded=False)
            st.session_state.last_tools = tools_called

        except Exception as exc:
            full_response = f"Agent error: {exc}\n\nCheck `.env` is configured and the vector index is active."
            response_holder.error(full_response)
            status_box.update(label="Error", state="error", expanded=False)

        if st.session_state.get("tts_enabled") and full_response and not full_response.startswith("Agent error"):
            with st.spinner("Generating audio..."):
                audio_bytes = _tts(full_response)
            if audio_bytes:
                st.audio(audio_bytes, format="audio/mpeg", autoplay=True)

    st.session_state.messages.append({"role": "assistant", "content": full_response})
