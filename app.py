"""
app.py -- Tech Debt Copilot: Streamlit Chat Interface

Two-panel layout:
  Left sidebar: Thread management + persona quick-starts + repo scanner + TTS toggle
  Right main:   Streaming chat with live tool-call status + optional voice output
"""

import os
import re
import uuid
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv

load_dotenv()

MONGO_URI   = os.getenv("MONGO_URI")
MONGO_DB    = os.getenv("MONGO_DB", "techdebt_copilot")
MAX_INPUT   = 1000  # chars -- increased to allow repo URLs in messages


# -- ElevenLabs TTS ------------------------------------------------------------

def _tts(text: str) -> bytes | None:
    """Generate TTS audio bytes. Returns None if key not set or on error."""
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from elevenlabs.client import ElevenLabs
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM").strip()
        client   = ElevenLabs(api_key=api_key)
        # Trim to ~2000 chars for TTS (summaries, not raw data dumps)
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

# Patterns that indicate prompt injection or jailbreak attempts
_INJECTION_PATTERNS = re.compile(
    r"(ignore (previous|all|prior)|forget (everything|instructions)|"
    r"you are now|act as|disregard|system prompt|jailbreak|"
    r"pretend (you are|to be)|override|bypass|<\|.*?\|>|"
    r"\[INST\]|\[/INST\]|### (Human|Assistant):)",
    re.IGNORECASE,
)


def sanitize_input(text: str) -> tuple[str, str | None]:
    """
    Validate and clean user input.
    Returns (cleaned_text, error_message_or_None).
    """
    text = text.strip()

    if not text:
        return "", "Please enter a question."

    if len(text) > MAX_INPUT:
        return "", f"Query too long ({len(text)} chars). Please keep it under {MAX_INPUT} characters."

    if _INJECTION_PATTERNS.search(text):
        return "", (
            "That query pattern isn't supported. "
            "Ask me about software versions, EOL dates, or CVE risks."
        )

    # Strip null bytes and control characters (keep newlines for multi-line stack pastes)
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
/* Slightly tighten chat bubbles */
.stChatMessage { padding: 0.6rem 1rem; }
/* Sponsor badge strip */
.sponsor-strip { font-size: 0.72rem; color: #888; text-align: center; margin-top: 1rem; }
</style>
""", unsafe_allow_html=True)


# -- Cached resources (created once per Streamlit session) ---------------------

@st.cache_resource(show_spinner="Connecting to MongoDB Atlas & loading agent...")
def _get_graph():
    from agent.graph import build_graph, get_checkpointer
    cp = get_checkpointer()
    return build_graph(checkpointer=cp)


# -- Session state init --------------------------------------------------------

if "thread_id"   not in st.session_state:
    st.session_state.thread_id      = str(uuid.uuid4())
if "messages"    not in st.session_state:
    st.session_state.messages       = []   # [{role, content}]
if "quick_prompt" not in st.session_state:
    st.session_state.quick_prompt   = None
if "tts_enabled" not in st.session_state:
    st.session_state.tts_enabled    = False


# -- Sidebar -------------------------------------------------------------------

with st.sidebar:
    st.title("Tech Debt Copilot")
    st.caption("Persistent context over your entire tech stack")

    st.divider()

    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"Thread `{st.session_state.thread_id[:12]}...`")
    with col2:
        if st.button("New", help="Start a new conversation thread"):
            st.session_state.thread_id = str(uuid.uuid4())
            st.session_state.messages  = []
            st.rerun()

    st.divider()
    st.subheader("Demo Personas")
    st.caption("Click to run a pre-built audit scenario")

    PERSONAS = {
        "[SCAN] My Installed Stack": (
            "Scan my locally installed software and tell me what's expired or at risk. "
            "Show me everything you find, grouped by urgency."
        ),
        "DevOps / Database": (
            "We're running MongoDB 4.4, PostgreSQL 11, and Redis 6 in production. "
            "What are our migration deadlines and risk levels?"
        ),
        "Security + CVE": (
            "Our servers run Ubuntu 18.04 and Ubuntu 20.04. "
            "What's our EOL exposure, and are there active CVEs I should know about?"
        ),
        "Cloud / Containers": (
            "We deploy on Kubernetes 1.22 and Alpine Linux 3.12. "
            "What are our container infrastructure risk factors?"
        ),
        "Industry Trends": (
            "Give me the full industry EOL trend breakdown. "
            "Which technology categories have the most versions expiring this year?"
        ),
        "90-Day Triage": (
            "Run a critical 90-day EOL triage. "
            "What software is expiring in the next 90 days and what's the risk?"
        ),
    }

    for label, prompt in PERSONAS.items():
        if st.button(label, use_container_width=True):
            st.session_state.quick_prompt = prompt
            st.rerun()

    st.divider()
    st.subheader("Scan a Repository")
    st.caption("GitHub URL or local path")
    repo_input = st.text_input(
        "Repo URL or path",
        placeholder="https://github.com/owner/repo",
        label_visibility="collapsed",
        key="repo_input_field",
    )
    if st.button("Scan Repo", use_container_width=True, type="primary"):
        if repo_input.strip():
            st.session_state.quick_prompt = (
                f"Scan this repository for EOL risks and tell me what needs attention: {repo_input.strip()}"
            )
            st.rerun()
        else:
            st.warning("Enter a GitHub URL or local folder path.")

    st.divider()

    # ElevenLabs voice toggle
    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
    tts_label = "Voice Output (ElevenLabs)" if has_elevenlabs else "Voice Output (add API key to .env)"
    st.session_state.tts_enabled = st.toggle(
        tts_label,
        value=st.session_state.tts_enabled,
        disabled=not has_elevenlabs,
        help="Reads the assistant's response aloud using ElevenLabs TTS.",
    )

    st.divider()
    st.markdown(
        '<div class="sponsor-strip">'
        'Powered by<br>'
        '<b>MongoDB Atlas</b> Vector Search + Checkpointer<br>'
        '<b>Voyage AI</b> voyage-3.5 Embeddings<br>'
        '<b>Fireworks AI</b> deepseek-v4-flash<br>'
        '<b>LangGraph</b> + endoflife.date API'
        '</div>',
        unsafe_allow_html=True,
    )


# -- Main area -----------------------------------------------------------------

st.title("Tech Debt Copilot")
st.caption(
    "Ask about EOL dates, CVE risks, or paste your stack for a full audit. "
    "Conversation history persists across sessions via MongoDB."
)

# Render existing conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Resolve input -- either typed or from a persona button
user_input = st.chat_input("Ask about your tech stack, e.g. 'When does Python 3.9 expire?'")
if user_input is None and st.session_state.quick_prompt:
    user_input = st.session_state.quick_prompt
    st.session_state.quick_prompt = None

# Process user turn
if user_input:
    # Sanitize before anything else
    clean_input, error = sanitize_input(user_input)
    if error:
        st.warning(f"(!)️ {error}")
        st.stop()

    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": clean_input})
    with st.chat_message("user"):
        st.markdown(clean_input)
    user_input = clean_input

    # Run agent and stream response
    graph  = _get_graph()
    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    with st.chat_message("assistant"):
        status_box        = st.status("Thinking...", expanded=True)
        response_holder   = st.empty()
        full_response     = ""
        tools_called      = []

        try:
            for chunk in graph.stream(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
                stream_mode="values",
            ):
                msgs = chunk.get("messages", [])
                if not msgs:
                    continue
                last = msgs[-1]

                # Show tool calls in the status box as they happen
                if hasattr(last, "tool_calls") and last.tool_calls:
                    for tc in last.tool_calls:
                        name = tc.get("name", "tool")
                        args = tc.get("args", {})
                        if name not in tools_called:
                            tools_called.append(name)
                            hint = args.get("product_name") or args.get("product") or args.get("query", "")[:40]
                            status_box.write(f"🔍 `{name}` <- {hint}")

                # Update the response as new AI content arrives
                if isinstance(last, AIMessage) and isinstance(last.content, str) and last.content:
                    full_response = last.content
                    response_holder.markdown(full_response + "|")

            response_holder.markdown(full_response)
            status_box.update(label="Done", state="complete", expanded=False)

        except Exception as exc:
            full_response = f"(!)️ Agent error: {exc}\n\nCheck that `.env` is configured and the vector index is active."
            response_holder.error(full_response)
            status_box.update(label="Error", state="error", expanded=False)

        # ElevenLabs TTS -- play response if voice is enabled
        if st.session_state.get("tts_enabled") and full_response and "error" not in full_response.lower()[:20]:
            with st.spinner("Generating audio..."):
                audio_bytes = _tts(full_response)
            if audio_bytes:
                st.audio(audio_bytes, format="audio/mpeg", autoplay=True)

    st.session_state.messages.append({"role": "assistant", "content": full_response})
