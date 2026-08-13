"""
app.py -- Tech Debt Copilot: Streamlit Chat Interface
"""

import os
import re
import uuid
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB  = os.getenv("MONGO_DB", "techdebt_copilot")
MAX_INPUT = 1000


# -- ElevenLabs TTS ------------------------------------------------------------

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
            voice_id=voice_id,
            text=tts_text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_22050_32",
        )
        return b"".join(stream)
    except Exception:
        return None


# -- Input security ------------------------------------------------------------

_INJECTION_PATTERNS = re.compile(
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
    if _INJECTION_PATTERNS.search(text):
        return "", "That query pattern isn't supported. Ask about software versions, EOL dates, or CVE risks."
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text, None


# -- Page config ---------------------------------------------------------------

st.set_page_config(
    page_title="Tech Debt Copilot",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════════
   GLASSMORPHISM THEME — Tech Debt Copilot
═══════════════════════════════════════════════════════════════ */

/* ── Animated deep-space background ─────────────────────────── */
.stApp {
    background:
        radial-gradient(ellipse at 15% 40%, rgba(99,120,255,0.10) 0%, transparent 55%),
        radial-gradient(ellipse at 85% 15%, rgba(168,100,255,0.08) 0%, transparent 45%),
        radial-gradient(ellipse at 50% 85%, rgba(0,200,140,0.06) 0%, transparent 45%),
        linear-gradient(160deg, #06091a 0%, #0b142e 40%, #140824 75%, #060c1e 100%) !important;
    background-attachment: fixed !important;
    min-height: 100vh;
}

[data-testid="stAppViewContainer"] > .main,
.block-container {
    background: transparent !important;
}

/* ── Sidebar — frosted glass panel ──────────────────────────── */
section[data-testid="stSidebar"] {
    background: rgba(8, 12, 35, 0.72) !important;
    backdrop-filter: blur(24px) saturate(1.3) !important;
    -webkit-backdrop-filter: blur(24px) saturate(1.3) !important;
    border-right: 1px solid rgba(255,255,255,0.07) !important;
    box-shadow: 6px 0 40px rgba(0,0,0,0.45) !important;
}
section[data-testid="stSidebar"] > div:first-child {
    background: transparent !important;
}

/* ── Top bar ─────────────────────────────────────────────────── */
[data-testid="stHeader"] {
    background: rgba(6,9,26,0.65) !important;
    backdrop-filter: blur(14px) !important;
    border-bottom: 1px solid rgba(255,255,255,0.05) !important;
}

/* ── Chat message cards ──────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.035) !important;
    backdrop-filter: blur(14px) !important;
    -webkit-backdrop-filter: blur(14px) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 18px !important;
    margin: 0.55rem 0 !important;
    padding: 0.9rem 1.2rem !important;
    box-shadow: 0 4px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04) !important;
    transition: box-shadow 0.2s ease !important;
}

/* User bubble — indigo tint + glow */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: rgba(99,120,255,0.08) !important;
    border-color: rgba(99,120,255,0.18) !important;
    box-shadow: 0 4px 28px rgba(99,120,255,0.10), inset 0 1px 0 rgba(255,255,255,0.05) !important;
}

/* ── Chat input ──────────────────────────────────────────────── */
[data-testid="stChatInput"] {
    background: rgba(255,255,255,0.05) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 32px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.05) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
[data-testid="stChatInput"]:focus-within {
    border-color: rgba(99,120,255,0.40) !important;
    box-shadow: 0 0 28px rgba(99,120,255,0.15), 0 4px 32px rgba(0,0,0,0.30) !important;
}
[data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: rgba(255,255,255,0.88) !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: rgba(255,255,255,0.28) !important;
}

/* ── Buttons — glass with hover glow ─────────────────────────── */
.stButton > button {
    background: rgba(255,255,255,0.055) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid rgba(255,255,255,0.11) !important;
    border-radius: 10px !important;
    color: rgba(220,232,255,0.88) !important;
    font-size: 0.80rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    transition: all 0.18s ease !important;
    box-shadow: 0 2px 10px rgba(0,0,0,0.22) !important;
}
.stButton > button:hover {
    background: rgba(255,255,255,0.10) !important;
    border-color: rgba(99,120,255,0.38) !important;
    box-shadow: 0 0 22px rgba(99,120,255,0.22), 0 4px 14px rgba(0,0,0,0.30) !important;
    transform: translateY(-1px) !important;
    color: white !important;
}
/* Primary / Scan button — vivid indigo glow */
.stButton > button[kind="primary"] {
    background: rgba(99,120,255,0.18) !important;
    border-color: rgba(99,120,255,0.42) !important;
    box-shadow: 0 0 22px rgba(99,120,255,0.18), 0 4px 14px rgba(0,0,0,0.28) !important;
    color: white !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover {
    background: rgba(99,120,255,0.32) !important;
    box-shadow: 0 0 36px rgba(99,120,255,0.36), 0 4px 18px rgba(0,0,0,0.35) !important;
}

/* ── Text input ──────────────────────────────────────────────── */
.stTextInput > div > div {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 10px !important;
    backdrop-filter: blur(10px) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextInput > div > div:focus-within {
    border-color: rgba(99,120,255,0.35) !important;
    box-shadow: 0 0 18px rgba(99,120,255,0.12) !important;
}
.stTextInput input {
    background: transparent !important;
    color: rgba(255,255,255,0.88) !important;
}
.stTextInput input::placeholder { color: rgba(255,255,255,0.28) !important; }

/* ── Status widget ───────────────────────────────────────────── */
[data-testid="stStatusWidget"] {
    background: rgba(8,14,40,0.65) !important;
    backdrop-filter: blur(14px) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 14px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.28) !important;
}
[data-testid="stStatusWidget"][data-state="complete"] {
    border-color: rgba(0,210,120,0.28) !important;
    box-shadow: 0 0 20px rgba(0,210,120,0.10), 0 4px 24px rgba(0,0,0,0.25) !important;
}
[data-testid="stStatusWidget"][data-state="error"] {
    border-color: rgba(255,80,80,0.30) !important;
    box-shadow: 0 0 20px rgba(255,80,80,0.10) !important;
}

/* ── Toggle ──────────────────────────────────────────────────── */
.stToggle { padding: 2px 4px; }

/* ── Dividers ────────────────────────────────────────────────── */
hr { border-color: rgba(255,255,255,0.06) !important; margin: 0.7rem 0 !important; }

/* ── Gradient title ──────────────────────────────────────────── */
h1 {
    background: linear-gradient(110deg, #90b8ff 0%, #c4a3ff 50%, #67e8d4 100%);
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em !important;
}
h2 { color: rgba(200,220,255,0.92) !important; font-weight: 700 !important; }
h3 { color: rgba(180,205,255,0.85) !important; }

.stCaption, [data-testid="stCaptionContainer"] p {
    color: rgba(180,200,255,0.38) !important;
    font-size: 0.78rem !important;
}

/* ── Markdown content ────────────────────────────────────────── */
.stMarkdown strong  { color: rgba(255,255,255,0.96); }
.stMarkdown em      { color: rgba(200,220,255,0.80); }

.stMarkdown code {
    background: rgba(99,120,255,0.13) !important;
    border: 1px solid rgba(99,120,255,0.22) !important;
    border-radius: 5px !important;
    color: rgba(180,205,255,0.92) !important;
    padding: 1px 6px !important;
    font-size: 0.85em !important;
}
.stMarkdown pre {
    background: rgba(0,0,0,0.35) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}
.stMarkdown blockquote {
    border-left: 3px solid rgba(99,120,255,0.55) !important;
    background: rgba(99,120,255,0.06) !important;
    border-radius: 0 10px 10px 0 !important;
    padding: 8px 14px !important;
    color: rgba(200,220,255,0.80) !important;
    margin: 0.5rem 0 !important;
}

/* ── Custom component classes ────────────────────────────────── */
.demo-step-label {
    font-size: 0.60rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(130,165,255,0.55);
    margin-bottom: 6px;
    margin-top: 4px;
}

.repo-badge {
    display: inline-block;
    font-size: 0.67rem;
    padding: 2px 9px;
    border-radius: 20px;
    background: rgba(99,120,255,0.10);
    border: 1px solid rgba(99,120,255,0.22);
    color: rgba(160,190,255,0.75);
    margin-bottom: 4px;
    letter-spacing: 0.02em;
}

.followup-hint {
    font-size: 0.70rem;
    color: rgba(255,255,255,0.28);
    margin-bottom: 6px;
    margin-top: 14px;
    letter-spacing: 0.03em;
    text-transform: uppercase;
}

.sponsor-strip {
    font-size: 0.66rem;
    color: rgba(255,255,255,0.20);
    text-align: center;
    margin-top: 0.5rem;
    line-height: 2;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

/* ── Warning / error boxes ───────────────────────────────────── */
[data-testid="stAlert"] {
    background: rgba(255,160,50,0.08) !important;
    border: 1px solid rgba(255,160,50,0.20) !important;
    border-radius: 12px !important;
    backdrop-filter: blur(10px) !important;
}

/* ── Scrollbar ───────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
::-webkit-scrollbar-thumb {
    background: rgba(99,120,255,0.25);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(99,120,255,0.45); }
</style>
""", unsafe_allow_html=True)


# -- Cached resources ----------------------------------------------------------

@st.cache_resource(show_spinner="Connecting to MongoDB Atlas...")
def _get_graph():
    from agent.graph import build_graph, get_checkpointer
    cp = get_checkpointer()
    return build_graph(checkpointer=cp)


# -- Session state -------------------------------------------------------------

def _init_state():
    defaults = {
        "thread_id":      str(uuid.uuid4()),
        "messages":       [],
        "quick_prompt":   None,   # actual LLM prompt
        "display_prompt": None,   # what the user sees in chat
        "last_tools":     [],     # tools called in last turn
        "tts_enabled":    False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# -- Demo content --------------------------------------------------------------

DEMO_REPOS = [
    (
        "Django Legacy App (2016)",
        "https://github.com/gothinkster/django-realworld-example-app",
        "Django 1.10.5 — expired 2017",
    ),
    (
        "React Redux App",
        "https://github.com/gothinkster/react-redux-realworld-example-app",
        "React 16 era",
    ),
    (
        "Express.js Backend",
        "https://github.com/gothinkster/node-express-realworld-example-app",
        "Node / Express",
    ),
]

QUICK_PERSONAS = {
    "Industry EOL Trends": (
        "Give me the full industry EOL trend breakdown across all tech categories. "
        "Which categories have the most versions expiring this year?",
        "Industry EOL Trends",
    ),
    "90-Day Triage": (
        "Run a critical 90-day EOL triage. What's expiring in the next 90 days?",
        "90-Day Triage",
    ),
    "Ubuntu + CVEs": (
        "Our servers run Ubuntu 18.04 and 20.04. What's our EOL exposure and are there active CVEs?",
        "Ubuntu 18.04 + 20.04 — EOL and CVE check",
    ),
    "MongoDB + Postgres Stack": (
        "We run MongoDB 4.4, PostgreSQL 11, and Redis 6 in production. Migration deadlines?",
        "MongoDB 4.4 / PostgreSQL 11 / Redis 6 — migration deadlines",
    ),
}

FOLLOWUP_AFTER_SCAN = [
    ("Check CVEs for expired packages", "Check CVEs for any expired packages found in the last scan"),
    ("Upgrade path?", "Give me the upgrade path for the highest-risk package in the last scan"),
    ("How long to fix?", "Roughly how long would it take to upgrade the expired dependencies found?"),
]

FOLLOWUP_AFTER_EOL = [
    ("Check CVEs for this", "Check CVEs for the versions we just discussed"),
    ("What expires next 90 days?", "What else is expiring in the next 90 days in the same category?"),
    ("Extended support options?", "Are there extended support options for the products we just discussed?"),
]


def _set_prompt(llm_prompt: str, display: str):
    st.session_state.quick_prompt   = llm_prompt
    st.session_state.display_prompt = display
    st.rerun()


# -- Sidebar -------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        '<h2 style="background:linear-gradient(110deg,#90b8ff,#c4a3ff,#67e8d4);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;font-weight:800;letter-spacing:-0.02em;margin-bottom:2px">'
        'Tech Debt Copilot</h2>',
        unsafe_allow_html=True,
    )
    st.caption("AI agent for software lifecycle intelligence")

    # Thread control
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"Thread `{st.session_state.thread_id[:10]}...`")
    with col2:
        if st.button("New", help="Start a new conversation thread"):
            st.session_state.thread_id    = str(uuid.uuid4())
            st.session_state.messages     = []
            st.session_state.last_tools   = []
            st.rerun()

    st.divider()

    # ── STEP 1: Local scan ────────────────────────────────────────────────
    st.markdown('<div class="demo-step-label">Step 1 — Scan this machine</div>', unsafe_allow_html=True)
    if st.button("Scan My Installed Stack", use_container_width=True, type="primary"):
        _set_prompt(
            "Scan my locally installed software and tell me what's expired or at risk. Show everything grouped by urgency.",
            "Scan my installed stack",
        )

    st.divider()

    # ── STEP 2: Repo scan ────────────────────────────────────────────────
    st.markdown('<div class="demo-step-label">Step 2 — Scan a GitHub repo</div>', unsafe_allow_html=True)

    for label, url, hint in DEMO_REPOS:
        st.markdown(f'<div class="repo-badge">{hint}</div>', unsafe_allow_html=True)
        if st.button(label, use_container_width=True, key=f"repo_{label}"):
            _set_prompt(
                f"Use the scan_repository tool on this target: {url}",
                f"Scan repo: {url}",
            )

    st.caption("or enter a custom URL / local path:")
    repo_input = st.text_input(
        "custom repo",
        placeholder="https://github.com/owner/repo   or   C:/projects/myapp",
        label_visibility="collapsed",
        key="repo_input_field",
    )
    if st.button("Scan", use_container_width=True):
        if repo_input.strip():
            target = repo_input.strip()
            _set_prompt(
                f"Use the scan_repository tool on this target: {target}",
                f"Scan repo: {target}",
            )
        else:
            st.warning("Enter a GitHub URL or local folder path.")

    st.divider()

    # ── STEP 3: Quick questions ───────────────────────────────────────────
    st.markdown('<div class="demo-step-label">Step 3 — Quick questions</div>', unsafe_allow_html=True)
    for label, (llm_prompt, display) in QUICK_PERSONAS.items():
        if st.button(label, use_container_width=True, key=f"persona_{label}"):
            _set_prompt(llm_prompt, display)

    st.divider()

    # ── Settings ──────────────────────────────────────────────────────────
    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
    tts_label = "Voice Output (ElevenLabs)" if has_elevenlabs else "Voice Output (key not set)"
    st.session_state.tts_enabled = st.toggle(
        tts_label,
        value=st.session_state.tts_enabled,
        disabled=not has_elevenlabs,
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


# -- Main area -----------------------------------------------------------------

st.title("Tech Debt Copilot")
st.caption(
    "AI agent that knows your full software lifecycle — "
    "scans machines, repos, and answers EOL / CVE questions. "
    "Memory persists across sessions via MongoDB."
)

# Render existing conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Follow-up quick-action buttons after last response
if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
    last_tools = st.session_state.get("last_tools", [])
    followups  = []
    if "scan_repository" in last_tools or "scan_local_stack" in last_tools:
        followups = FOLLOWUP_AFTER_SCAN
    elif "search_eol_data" in last_tools or "find_upcoming_eols" in last_tools:
        followups = FOLLOWUP_AFTER_EOL

    if followups:
        st.markdown('<div class="followup-hint">Quick follow-ups:</div>', unsafe_allow_html=True)
        cols = st.columns(len(followups))
        for col, (btn_label, llm_prompt) in zip(cols, followups):
            with col:
                if st.button(btn_label, key=f"fu_{btn_label}", use_container_width=True):
                    _set_prompt(llm_prompt, btn_label)

# Resolve input
user_input = st.chat_input("Ask anything — paste a GitHub URL, version question, or 'scan my machine'")
if user_input is None and st.session_state.quick_prompt:
    user_input = st.session_state.quick_prompt
    st.session_state.quick_prompt = None

# Auto-detect raw GitHub URL or path pasted into chat input
if user_input:
    _stripped = user_input.strip()
    _is_repo  = (
        ("github.com/" in _stripped and "scan_repository" not in _stripped) or
        (_stripped.startswith(("C:\\", "D:\\", "/", "./", "~/")) and "scan_repository" not in _stripped)
    )
    if _is_repo:
        st.session_state.display_prompt = f"Scan repo: {_stripped}"
        user_input = f"Use the scan_repository tool on this target: {_stripped}"

# Process user turn
if user_input:
    clean_input, error = sanitize_input(user_input)
    if error:
        st.warning(f" {error}")
        st.stop()

    # Use display_prompt for the chat bubble, internal prompt for LLM
    display_text = st.session_state.display_prompt or clean_input
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
                {"messages": [HumanMessage(content=clean_input)]},
                config=config,
                stream_mode="values",
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
                                repo = args.get("repo_url_or_path", "")
                                label = repo.split("github.com/")[-1] if "github.com" in repo else repo[:50]
                                status_box.write(f"Fetching dependency files from **{label}**...")
                                status_box.write("Checking: requirements.txt, package.json, pyproject.toml, go.mod...")
                            elif name == "scan_local_stack":
                                status_box.write("Scanning installed packages: Python, pip, Node.js, npm...")
                            elif name == "check_cve_vulnerabilities":
                                p = args.get("product", ""); v = args.get("version", "")
                                status_box.write(f"Querying OSV.dev CVEs for **{p} {v}**...")
                            elif name == "find_upcoming_eols":
                                d = args.get("days_ahead", 180)
                                status_box.write(f"Scanning EOL database — next **{d} days**...")
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
