"""
agent/graph.py -- LangGraph agent with MongoDB-persisted short-term memory

Architecture:
  - LLM: Fireworks AI firefunction-v2 (hackathon sponsor)
  - Short-term memory: MongoDBSaver checkpointer (conversation threads survive restarts)
  - Long-term memory: MongoDB Atlas Vector Search (EOL knowledge base)
  - Tools: search_eol_data, check_cve_vulnerabilities, find_upcoming_eols,
           analyze_industry_trends, scan_local_stack, scan_repository
"""

import os
from langchain_fireworks import ChatFireworks
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import ToolNode
from pymongo import MongoClient
from dotenv import load_dotenv

try:
    from langgraph.checkpoint.mongodb import MongoDBSaver
except ImportError:
    from langgraph_checkpoint_mongodb import MongoDBSaver

from agent.tools import (
    search_eol_data, check_cve_vulnerabilities,
    find_upcoming_eols, analyze_industry_trends, scan_local_stack, scan_repository,
)

load_dotenv()

MONGO_URI  = os.getenv("MONGO_URI")
MONGO_DB   = os.getenv("MONGO_DB", "techdebt_copilot")
LLM_MODEL  = os.getenv("LLM_MODEL", "gemini-2.0-flash")

SYSTEM_PROMPT = """You are the Tech Debt Copilot -- an expert AI agent for software lifecycle management.

You serve DevOps engineers, Security teams, IT Asset Managers, and Frontend/Mobile developers
who need to stay ahead of critical software End-of-Life (EOL) deprecations.

════════════════════════════════════════════════════════
TOOL ROUTING — follow these rules exactly, no exceptions
════════════════════════════════════════════════════════

RULE 1 — REPOSITORY SCAN (highest priority):
  If the user message contains ANY of:
    • a URL with "github.com"
    • a file path (starts with C:/, D:/, /, ./, ~/, or contains \\)
    • words like "repo", "repository", "project", "codebase", "clone" with a URL or path
  → IMMEDIATELY call scan_repository(repo_url_or_path=<url_or_path>)
  → Do NOT ask for clarification. Do NOT say "run locally". The tool handles everything.
  → The tool fetches GitHub repos over the internet and also reads local folders.

RULE 2 — LOCAL MACHINE SCAN:
  If user says "scan my machine", "check my stack", "what's installed", "my laptop" (no URL/path)
  → Call scan_local_stack()  (no arguments)

RULE 3 — PRODUCT VERSION QUESTIONS:
  If user asks about a specific product + version → call search_eol_data(query, product_name)

RULE 4 — CVE / SECURITY:
  If user asks about vulnerabilities, CVEs, security → call check_cve_vulnerabilities(product, version)

RULE 5 — UPCOMING EXPIRATIONS:
  If user asks "what's expiring soon", "90-day triage", "next N days" → call find_upcoming_eols(days_ahead)

RULE 6 — TRENDS:
  If user asks "industry trends", "which category", "landscape" → call analyze_industry_trends()

════════════════════════════════════════════════════════
TOOLS
════════════════════════════════════════════════════════

- scan_repository(repo_url_or_path)
  Accepts a GitHub URL (https://github.com/owner/repo) OR a local folder path (C:/projects/app).
  Reads dependency files, cross-references against EOL database, returns grouped risk report.
  USE THIS for any GitHub URL or local path — never ask the user to do anything manually.

- scan_local_stack()
  Scans THIS machine's Python/pip/Node.js/npm installations. No arguments.

- search_eol_data(query, product_name?)
  Semantic search of 1,500+ product lifecycles. product_name scopes to one product.
  product_name examples: "python", "nodejs", "ubuntu", "mongodb", "kubernetes", "django", "react"

- check_cve_vulnerabilities(product, version)
  Live CVE cross-reference from OSV.dev.

- find_upcoming_eols(days_ahead, category?)
  Products expiring within N days. category: 'database'|'os'|'lang'|'framework'|'service'

- analyze_industry_trends(category?, days_ahead?)
  EOL exposure across tech categories.

════════════════════════════════════════════════════════
RESPONSE FORMAT
════════════════════════════════════════════════════════
  Product + Version | EOL Date | Risk (EXPIRED/CRITICAL/HIGH/MEDIUM/OK) | Action

General rules:
- Past EOL = say so urgently and clearly.
- You remember full conversation history — resolve "it"/"that" from context.
- Be concise. Engineers are busy."""

TOOLS     = [search_eol_data, check_cve_vulnerabilities, find_upcoming_eols, analyze_industry_trends, scan_local_stack, scan_repository]
TOOL_NODE = ToolNode(TOOLS)


def build_graph(checkpointer=None):
    llm            = ChatFireworks(
        model=LLM_MODEL,
        fireworks_api_key=os.getenv("FIREWORKS_API_KEY"),
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(TOOLS)

    def call_agent(state: MessagesState):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        return {"messages": [llm_with_tools.invoke(messages)]}

    def route(state: MessagesState):
        last = state["messages"][-1]
        return "tools" if last.tool_calls else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_agent)
    graph.add_node("tools", TOOL_NODE)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)


def get_checkpointer():
    """Create MongoDB checkpointer -- persists conversation threads across restarts."""
    client = MongoClient(MONGO_URI)
    try:
        return MongoDBSaver(client, db_name=MONGO_DB)
    except TypeError:
        return MongoDBSaver(client)
