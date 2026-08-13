#!/usr/bin/env python3
"""
verify_setup.py -- Pre-hackathon sanity checker

Run this before the demo to confirm every connection works.
It checks env vars, MongoDB connectivity, vector index status,
Voyage AI API, and Fireworks AI API.

Run: python verify_setup.py
"""

import os
import sys
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()

PASS = "[bold green]ok[/]"
FAIL = "[bold red]x[/]"
WARN = "[bold yellow]?[/]"

results = []

def check(label: str, fn) -> bool:
    try:
        msg = fn()
        results.append((PASS, label, msg or "OK"))
        return True
    except Exception as exc:
        results.append((FAIL, label, str(exc)[:80]))
        return False


# -- 1. Environment variables --------------------------------------------------

def check_env():
    required = ["MONGO_URI", "FIREWORKS_API_KEY", "VOYAGE_API_KEY"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"Missing env vars: {', '.join(missing)}")
    return "MONGO_URI, FIREWORKS_API_KEY, VOYAGE_API_KEY all set"

check("Environment variables", check_env)


# -- 2. MongoDB connection + document count ------------------------------------

def check_mongo():
    from pymongo import MongoClient
    MONGO_URI  = os.getenv("MONGO_URI")
    MONGO_DB   = os.getenv("MONGO_DB", "techdebt_copilot")
    MONGO_COLL = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
    client     = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    count = client[MONGO_DB][MONGO_COLL].count_documents({})
    client.close()
    if count == 0:
        raise ValueError("Collection is empty -- run 01_ingest.py first")
    return f"{count:,} documents in {MONGO_DB}.{MONGO_COLL}"

check("MongoDB Atlas connection", check_mongo)


# -- 3. Vector Search index status --------------------------------------------

def check_index():
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
    coll   = client[os.getenv("MONGO_DB", "techdebt_copilot")][os.getenv("MONGO_COLLECTION", "eol_lifecycle")]
    idxs   = list(coll.list_search_indexes())
    client.close()
    ready  = [i for i in idxs if i.get("name") == "vector_index" and i.get("status") == "READY"]
    if not ready:
        pending = [i for i in idxs if i.get("name") == "vector_index"]
        if pending:
            raise ValueError(f"Index exists but status = {pending[0].get('status')} -- wait a few minutes")
        raise ValueError("vector_index not found -- run 02_setup_index.py")
    return "vector_index READY"

check("MongoDB Vector Search index", check_index)


# -- 4. Voyage AI embedding ----------------------------------------------------

def check_voyage():
    import voyageai
    vo     = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))
    model  = os.getenv("EMBEDDING_MODEL", "voyage-3.5")
    result = vo.embed(["test embedding for Tech Debt Copilot"], model=model, input_type="query")
    dims   = len(result.embeddings[0])
    return f"{model} -> {dims}d vector"

check("Voyage AI API", check_voyage)


# -- 5. Fireworks AI API -------------------------------------------------------

def check_fireworks():
    from langchain_fireworks import ChatFireworks
    from langchain_core.messages import HumanMessage
    llm  = ChatFireworks(
        model=os.getenv("LLM_MODEL", "accounts/fireworks/models/firefunction-v2"),
        fireworks_api_key=os.getenv("FIREWORKS_API_KEY"),
        temperature=0,
    )
    resp = llm.invoke([HumanMessage(content="Reply with exactly: OK")])
    return f"Fireworks responded: {resp.content[:30]}"

check("Fireworks AI API", check_fireworks)


# -- 6. MongoDBSaver checkpointer ----------------------------------------------

def check_checkpointer():
    from pymongo import MongoClient
    try:
        from langgraph.checkpoint.mongodb import MongoDBSaver
    except ImportError:
        from langgraph_checkpoint_mongodb import MongoDBSaver
    client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
    try:
        saver = MongoDBSaver(client, db_name=os.getenv("MONGO_DB", "techdebt_copilot"))
    except TypeError:
        saver = MongoDBSaver(client)
    client.close()
    return "MongoDBSaver initialized"

check("LangGraph MongoDBSaver", check_checkpointer)


# -- 7. Quick end-to-end tool test ---------------------------------------------

def check_tool():
    from agent.tools import search_eol_data
    result = search_eol_data.invoke({"query": "python 3.9 end of life", "product_name": "python"})
    if "Error" in result or "error" in result:
        raise ValueError(result[:80])
    return "search_eol_data returned results"

check("End-to-end vector search tool", check_tool)


# -- Print results table -------------------------------------------------------

table = Table(title="Tech Debt Copilot -- Setup Verification", show_header=True)
table.add_column("", width=3)
table.add_column("Check", style="bold")
table.add_column("Result")

for status, label, msg in results:
    table.add_row(status, label, msg)

console.print()
console.print(table)

failed = sum(1 for s, _, _ in results if "x" in s)
if failed == 0:
    console.print("\n[bold green]All checks passed -- ready for the demo![/]")
    console.print("Run: [bold]streamlit run app.py[/]")
else:
    console.print(f"\n[bold red]{failed} check(s) failed. Fix above before the hackathon.[/]")
    sys.exit(1)
