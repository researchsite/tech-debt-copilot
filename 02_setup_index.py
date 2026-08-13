#!/usr/bin/env python3
"""
02_setup_index.py -- Create MongoDB Atlas Vector Search Index

Run AFTER 01_ingest.py. Creates the vector index that enables:
  1. Semantic similarity search via voyage-3 embeddings
  2. Deterministic pre-filtering via $eq on product_name (the killer feature)

Run: python 02_setup_index.py
"""

import os
import time
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel
from rich.console import Console

load_dotenv()
console = Console()

MONGO_URI        = os.getenv("MONGO_URI")
MONGO_DB         = os.getenv("MONGO_DB", "techdebt_copilot")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
EMBEDDING_DIM    = int(os.getenv("EMBEDDING_DIM", "1024"))
INDEX_NAME       = "vector_index"


def create_vector_index(collection) -> bool:
    # Drop existing index with same name if present
    try:
        existing = [idx.get("name") for idx in collection.list_search_indexes()]
        if INDEX_NAME in existing:
            console.print(f"  [yellow]Index '{INDEX_NAME}' exists -- dropping and recreating...[/]")
            collection.drop_search_index(INDEX_NAME)
            time.sleep(5)
    except Exception:
        pass  # list_search_indexes may fail on unsupported tiers -- proceed anyway

    model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": EMBEDDING_DIM,
                    "similarity": "cosine",
                },
                {
                    # Enables $eq pre-filter on product_name -- prevents cross-product bleed
                    "type": "filter",
                    "path": "product_name",
                },
                {
                    # Enables date-range queries in find_upcoming_eols tool
                    "type": "filter",
                    "path": "eol",
                },
                {
                    # Enables category-scoped trend queries (database, os, lang, etc.)
                    "type": "filter",
                    "path": "category",
                },
                {
                    # Enables extended support date range queries
                    "type": "filter",
                    "path": "extended_support",
                },
            ]
        },
        name=INDEX_NAME,
        type="vectorSearch",
    )

    collection.create_search_index(model=model)
    console.print("  Index creation submitted. Waiting for READY status...")

    for attempt in range(36):   # poll up to 6 minutes
        time.sleep(10)
        try:
            for idx in collection.list_search_indexes():
                if idx.get("name") == INDEX_NAME:
                    status = idx.get("status", "UNKNOWN")
                    console.print(f"  [{attempt+1}] Status: [cyan]{status}[/]")
                    if status == "READY":
                        return True
        except Exception:
            pass

    return False


if __name__ == "__main__":
    console.rule("[bold]Tech Debt Copilot -- Vector Index Setup[/]")

    if not MONGO_URI:
        console.print("[red]ERROR: MONGO_URI not set in .env[/]")
        raise SystemExit(1)

    client     = MongoClient(MONGO_URI)
    collection = client[MONGO_DB][MONGO_COLLECTION]

    doc_count = collection.count_documents({})
    console.print(f"  Collection [cyan]{MONGO_DB}.{MONGO_COLLECTION}[/]: {doc_count} documents")
    console.print(f"  Creating vector index ({EMBEDDING_DIM}d, cosine similarity)...\n")

    if doc_count == 0:
        console.print("[red]ERROR: No documents found. Run 01_ingest.py first.[/]")
        raise SystemExit(1)

    ready = create_vector_index(collection)
    client.close()

    if ready:
        console.rule("[bold green]Index Ready -- Vector Search Active[/]")
        console.print("  Next -> [bold]streamlit run app.py[/]")
    else:
        console.print("[yellow]Index may still be initializing in Atlas.[/]")
        console.print("  Check: [link]https://cloud.mongodb.com[/link] -> Atlas Search -> Indexes")
        console.print("  Once READY, run: [bold]streamlit run app.py[/]")
