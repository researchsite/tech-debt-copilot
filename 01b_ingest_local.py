#!/usr/bin/env python3
"""
01b_ingest_local.py -- Tech Debt Copilot: Local-Cache Ingestion

Reads the pre-downloaded data/eol_data_raw.json, creates Voyage AI embeddings,
and upserts to MongoDB Atlas -- NO internet required beyond Voyage AI + MongoDB.

Use this instead of 01_ingest.py when:
  - Hackathon WiFi is slow or unreliable
  - You already ran 00_download_data.py at home
  - You want faster iteration (skip the API fetch step)

Prerequisites:
    python 00_download_data.py   <- run this first, once

Run:
    python 01b_ingest_local.py
"""

import os
import time
import json
from datetime import datetime, UTC
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne
import voyageai
from rich.console import Console
from rich.progress import Progress, TimeElapsedColumn, TextColumn
from rich.table import Table

load_dotenv()
console = Console()

MONGO_URI        = os.getenv("MONGO_URI")
MONGO_DB         = os.getenv("MONGO_DB", "techdebt_copilot")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
VOYAGE_API_KEY   = os.getenv("VOYAGE_API_KEY")
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "voyage-3")
BATCH_SIZE       = 80

DATA_DIR   = Path("data")
CACHE_FILE = DATA_DIR / "eol_data_raw.json"
META_FILE  = DATA_DIR / "eol_data_meta.json"


def load_local_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        console.print(f"[red]ERROR: {CACHE_FILE} not found.[/]")
        console.print("Run [bold]python 00_download_data.py[/] first to create it.")
        raise SystemExit(1)

    meta = {}
    if META_FILE.exists():
        with open(META_FILE) as f:
            meta = json.load(f)

    console.print(f"[bold blue]>> Loading local cache: {CACHE_FILE}[/]")
    with open(CACHE_FILE, encoding="utf-8") as f:
        documents = json.load(f)

    table = Table(show_header=False, box=None)
    table.add_column("", style="dim")
    table.add_column("")
    table.add_row("Downloaded at:", meta.get("downloaded_at", "unknown"))
    table.add_row("Records:      ", f"{len(documents):,}")
    table.add_row("Products:     ", str(meta.get("total_products", "?")))
    table.add_row("File size:    ", f"{CACHE_FILE.stat().st_size / 1_048_576:.1f} MB")
    console.print(table)

    # Refresh ingestion_date to today (cache may be days old)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for d in documents:
        d["ingestion_date"] = today

    return documents


def embed_documents(documents: list[dict]) -> list[dict]:
    console.print(
        f"\n[bold blue]>> Embedding {len(documents):,} docs "
        f"with {EMBEDDING_MODEL} (input_type=document)...[/]"
    )
    vo    = voyageai.Client(api_key=VOYAGE_API_KEY)
    texts = [d["content"] for d in documents]

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as bar:
        task = bar.add_task("Embedding", total=len(texts))
        for i in range(0, len(texts), BATCH_SIZE):
            batch  = texts[i : i + BATCH_SIZE]
            result = vo.embed(batch, model=EMBEDDING_MODEL, input_type="document")
            for j, vec in enumerate(result.embeddings):
                documents[i + j]["embedding"] = vec
            bar.advance(task, len(batch))
            if i + BATCH_SIZE < len(texts):
                time.sleep(0.25)

    return documents


def upsert_to_mongodb(documents: list[dict]) -> int:
    console.print(f"\n[bold blue]>> Upserting {len(documents):,} docs to MongoDB Atlas...[/]")

    client     = MongoClient(MONGO_URI)
    collection = client[MONGO_DB][MONGO_COLLECTION]

    ops = [
        ReplaceOne(
            filter={"product_name": d["product_name"], "cycle": d["cycle"]},
            replacement=d,
            upsert=True,
        )
        for d in documents
    ]

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as bar:
        task  = bar.add_task("Writing to Atlas", total=len(ops))
        total = 0
        for i in range(0, len(ops), 500):
            res    = collection.bulk_write(ops[i : i + 500], ordered=False)
            total += res.upserted_count + res.modified_count
            bar.advance(task, min(500, len(ops) - i))

    # Ensure standard indexes exist
    collection.create_index([("product_name", 1), ("cycle", 1)], unique=True, background=True)
    collection.create_index("category", background=True)
    collection.create_index("eol", background=True)

    final_count = collection.count_documents({})
    client.close()
    console.print(
        f"  [green]{total:,} records created/updated.[/] "
        f"Collection total: [bold]{final_count:,}[/]"
    )
    return final_count


if __name__ == "__main__":
    console.rule("[bold]Tech Debt Copilot -- Local Cache Ingestion[/]")
    console.print(f"  Embedding: [cyan]{EMBEDDING_MODEL}[/] (1024d, input_type=document)")
    console.print(f"  MongoDB:   [cyan]{MONGO_DB}.{MONGO_COLLECTION}[/]")
    console.print(f"  Source:    [cyan]{CACHE_FILE}[/] (no API calls for fetch step)\n")

    for var, name in [(MONGO_URI, "MONGO_URI"), (VOYAGE_API_KEY, "VOYAGE_API_KEY")]:
        if not var:
            console.print(f"[red]ERROR: {name} not set in .env[/]")
            raise SystemExit(1)

    docs  = load_local_cache()
    docs  = embed_documents(docs)
    total = upsert_to_mongodb(docs)

    console.rule("[bold green]Ingestion Complete[/]")
    console.print(f"  Total records in MongoDB: [bold]{total:,}[/]")
    console.print("\n  Next -> [bold]python 02_setup_index.py[/]  (if index not yet created)")
    console.print("  Or    -> [bold]streamlit run app.py[/]      (if index already active)")
