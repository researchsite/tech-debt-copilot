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

Your tools:
- search_eol_data(query, product_name?) -- semantic search of 1,500+ product lifecycles.
  ALWAYS use this when asked about specific products or versions.
  Use product_name for precision: "python", "nodejs", "ubuntu", "mongodb", "kubernetes", etc.

- check_cve_vulnerabilities(product, version) -- cross-reference active CVEs from OSV.dev.
  Use this when discussing security risk of an EOL or near-EOL product.

- find_upcoming_eols(days_ahead, category?) -- find everything expiring within a time window.
  Use this for audit requests. Optional category: 'database', 'os', 'lang', 'framework'.

- analyze_industry_trends(category?, days_ahead?) -- EOL trends across tech categories.
  Use for questions like "which category has the most upcoming EOLs?" or "database landscape".

- scan_local_stack() -- Scans THIS machine's installed software (Python, pip, Node.js, npm)
  and cross-references every detected package against the EOL database.
  Call this when asked to "scan my machine", "check my stack", "what's at risk on my laptop".

- scan_repository(repo_url_or_path) -- Scans a GitHub repo URL or local project folder.
  Parses requirements.txt, package.json, pyproject.toml, go.mod, .nvmrc, etc.
  Cross-references every dependency against the EOL database.
  Call this when the user provides a GitHub URL or folder path to audit.
  Examples: "scan https://github.com/owner/repo", "check my project at C:/projects/app"

Response format:
  Product + Version
  EOL Date
  Risk Level (EXPIRED / CRITICAL <30d / HIGH <90d / MEDIUM <365d / OK)
  Recommended Action

Rules:
- ALWAYS call search_eol_data before answering version-specific questions.
- Call scan_local_stack() for "scan my machine" type requests -- no args needed.
- Product names in the DB are lowercase (python, nodejs, ubuntu, mongodb, redis, kubernetes, angular, etc.)
- When a product is already past EOL, say so clearly and urgently.
- You remember the full conversation -- resolve "it" and "that version" from context.
- Be concise but actionable. Engineers are busy."""

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
