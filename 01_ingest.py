#!/usr/bin/env python3
"""
01_ingest.py -- Tech Debt Copilot: Data Ingestion Pipeline

Fetches 464 products from endoflife.date API v1, enriches each record
with category/tags/label from the products catalog, creates Voyage AI
embeddings, and upserts to MongoDB Atlas.

Run: python 01_ingest.py
"""

import os
import time
import json
import requests
from datetime import datetime, UTC
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne
import voyageai
from rich.console import Console
from rich.progress import Progress, TimeElapsedColumn, TextColumn

load_dotenv()
console = Console()

MONGO_URI        = os.getenv("MONGO_URI")
MONGO_DB         = os.getenv("MONGO_DB", "techdebt_copilot")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
VOYAGE_API_KEY   = os.getenv("VOYAGE_API_KEY")
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "voyage-3")
BATCH_SIZE       = 80


# -- Helpers -------------------------------------------------------------------

def parse_date(raw) -> tuple[str | None, str]:
    """Return (queryable_ISO_date_or_None, human_readable_str)."""
    if isinstance(raw, str):
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            return raw, raw
        except ValueError:
            return None, raw
    if raw is True:
        return None, "Already ended"
    if raw is False:
        return None, "Not applicable / actively maintained"
    return None, "Unknown"


def days_until(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        delta = datetime.strptime(date_str, "%Y-%m-%d") - datetime.now(UTC)
        return delta.days
    except ValueError:
        return None


def build_content(label: str, category: str, tags: list, cycle: str, data: dict) -> str:
    """
    Rich natural-language content string for Voyage AI embedding.
    Include all human-useful facts -- specificity drives retrieval quality.
    """
    codename      = f" ({data['codename']})" if data.get("codename") else ""
    lts_note      = " [Long-Term Support release]" if data.get("lts") else ""
    release       = data.get("releaseDate", "unknown date")
    _, eol_d      = parse_date(data.get("eol", False))
    _, sup_d      = parse_date(data.get("support", False))
    _, ext_d      = parse_date(data.get("extendedSupport", False))
    latest        = data.get("latest", "")
    latest_date   = data.get("latestReleaseDate", "")
    tag_str       = ", ".join(tags) if tags else ""
    cat_str       = f" Category: {category}." if category else ""
    tag_part      = f" Tags: {tag_str}." if tag_str else ""
    latest_part   = f" Latest version: {latest} (released {latest_date})." if latest else ""
    ext_part      = f" Extended/paid support available until: {ext_d}." if data.get("extendedSupport") and isinstance(data.get("extendedSupport"), str) else ""

    return (
        f"Product: {label} version {cycle}{codename}{lts_note}."
        f"{cat_str}{tag_part}"
        f" Released: {release}."
        f" Mainstream support ends: {sup_d}."
        f" End of Life (EOL): {eol_d}."
        f"{ext_part}"
        f"{latest_part}"
    )


# -- Pipeline steps ------------------------------------------------------------

def fetch_product_catalog() -> dict[str, dict]:
    """Fetch the /products v1 endpoint to get label, category, tags per product."""
    console.print("[bold blue]>> Step 1a: Fetching product catalog (labels, categories, tags)...[/]")
    r = requests.get("https://endoflife.date/api/v1/products", timeout=15)
    r.raise_for_status()
    data     = r.json()
    products = data.get("result", [])

    catalog = {}
    for p in products:
        catalog[p["name"]] = {
            "label":    p.get("label", p["name"]),
            "category": p.get("category", ""),
            "tags":     p.get("tags", []),
            "aliases":  p.get("aliases", []),
        }
    console.print(f"  Loaded metadata for [cyan]{len(catalog)}[/] products.")
    return catalog


def fetch_all_cycles(catalog: dict[str, dict]) -> list[dict]:
    """Fetch every release cycle for every product in the catalog."""
    console.print("[bold blue]>> Step 1b: Fetching lifecycle cycles for all products...[/]")

    documents  = []
    skipped    = []
    today_str  = datetime.now(UTC).strftime("%Y-%m-%d")
    products   = list(catalog.keys())

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as bar:
        task = bar.add_task("Fetching cycles", total=len(products))

        for product in products:
            meta = catalog[product]
            try:
                res = requests.get(
                    f"https://endoflife.date/api/{product}.json", timeout=10
                )
                if res.status_code != 200:
                    skipped.append(product)
                    bar.advance(task)
                    continue

                for cycle_data in res.json():
                    cycle           = str(cycle_data.get("cycle", "unknown"))
                    eol_q, eol_d    = parse_date(cycle_data.get("eol", False))
                    sup_q, _        = parse_date(cycle_data.get("support", False))
                    ext_q, _        = parse_date(cycle_data.get("extendedSupport", False))
                    disc_q, _       = parse_date(cycle_data.get("discontinued", False))

                    # Collect any product-specific custom fields not in standard schema
                    standard_keys   = {
                        "cycle", "releaseDate", "eol", "support", "lts",
                        "extendedSupport", "latest", "latestReleaseDate",
                        "link", "codename", "releaseLabel", "discontinued",
                    }
                    custom_fields   = {
                        k: v for k, v in cycle_data.items()
                        if k not in standard_keys
                    }

                    documents.append({
                        # -- Product identity -----------------------------
                        "product_name":        product.lower(),
                        "product_label":       meta["label"],
                        "category":            meta["category"],     # framework|database|os|lang|app|service|device|server-app|standard
                        "tags":                meta["tags"],
                        # -- Release cycle --------------------------------
                        "cycle":               cycle,
                        "codename":            cycle_data.get("codename", ""),
                        "release_label":       cycle_data.get("releaseLabel", ""),
                        "release_date":        str(cycle_data.get("releaseDate", "")),
                        "lts":                 bool(cycle_data.get("lts", False)),
                        # -- Support lifecycle (queryable ISO dates or None) --
                        "eol":                 eol_q,
                        "eol_display":         eol_d,
                        "support":             sup_q,
                        "extended_support":    ext_q,    # Ubuntu Pro, RHEL paid, etc.
                        "discontinued":        disc_q,   # hardware devices
                        # -- Latest version info --------------------------
                        "latest":              str(cycle_data.get("latest", "")),
                        "latest_release_date": str(cycle_data.get("latestReleaseDate", "")),
                        # -- Supplementary --------------------------------
                        "link":                str(cycle_data.get("link", "")),
                        "custom_fields":       custom_fields,  # pep, apiVersion, supportedPythonVersions, etc.
                        # -- Embedding content ----------------------------
                        "content":             build_content(
                                                   meta["label"], meta["category"],
                                                   meta["tags"], cycle, cycle_data
                                               ),
                        # -- Meta -----------------------------------------
                        "memory_type":         "enterprise_tech_lifecycle",
                        "ingestion_date":      today_str,
                        "source":              "endoflife.date API v1",
                    })

                time.sleep(0.04)

            except Exception as exc:
                skipped.append(f"{product}: {exc}")

            bar.advance(task)

    console.print(
        f"  [green]Built [bold]{len(documents)}[/] lifecycle records.[/] "
        f"Skipped {len(skipped)} products."
    )
    return documents


def embed_documents(documents: list[dict]) -> list[dict]:
    """Attach Voyage AI vectors to each document."""
    console.print(
        f"\n[bold blue]>> Step 2: Embedding {len(documents)} docs "
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
    """Bulk-upsert all documents keyed on (product_name, cycle)."""
    console.print(f"\n[bold blue]>> Step 3: Upserting {len(documents)} docs to MongoDB Atlas...[/]")

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

    # Create standard indexes for aggregation queries (not vector -- that's 02_setup_index.py)
    collection.create_index([("product_name", 1), ("cycle", 1)], unique=True, background=True)
    collection.create_index("category", background=True)
    collection.create_index("eol", background=True)
    collection.create_index("extended_support", background=True)

    final_count = collection.count_documents({})
    client.close()
    console.print(
        f"  [green]{total} records created/updated.[/] "
        f"Collection total: [bold]{final_count}[/]"
    )
    return final_count


def save_preview(documents: list[dict], path="full_enterprise_memory_bank.json"):
    slim = [{k: v for k, v in d.items() if k != "embedding"} for d in documents]
    with open(path, "w") as f:
        json.dump(slim, f, indent=2)
    console.print(f"  [dim]Preview (no embeddings) -> {path}[/]")


def print_field_stats(documents: list[dict]):
    """Show a quick breakdown of what we ingested."""
    from collections import Counter
    cats    = Counter(d["category"] for d in documents)
    console.print("\n  [bold]Category breakdown:[/]")
    for cat, count in cats.most_common():
        console.print(f"    {cat or 'uncategorized':<20s} {count:>5} records")

    has_ext = sum(1 for d in documents if d.get("extended_support"))
    has_cod = sum(1 for d in documents if d.get("codename"))
    has_lnk = sum(1 for d in documents if d.get("link"))
    console.print(f"\n  extendedSupport date : {has_ext:>5} records")
    console.print(f"  codename             : {has_cod:>5} records")
    console.print(f"  link to release notes: {has_lnk:>5} records")


# -- Entry point ---------------------------------------------------------------

if __name__ == "__main__":
    console.rule("[bold]Tech Debt Copilot -- Enriched Ingestion Pipeline[/]")
    console.print(f"  Embedding: [cyan]{EMBEDDING_MODEL}[/] (1024d, input_type=document)")
    console.print(f"  MongoDB:   [cyan]{MONGO_DB}.{MONGO_COLLECTION}[/]\n")

    if not MONGO_URI:
        console.print("[red]ERROR: MONGO_URI not set in .env[/]")
        raise SystemExit(1)
    if not VOYAGE_API_KEY:
        console.print("[red]ERROR: VOYAGE_API_KEY not set in .env[/]")
        raise SystemExit(1)

    catalog = fetch_product_catalog()
    docs    = fetch_all_cycles(catalog)
    save_preview(docs)
    print_field_stats(docs)
    docs    = embed_documents(docs)
    total   = upsert_to_mongodb(docs)

    console.rule("[bold green]Ingestion Complete[/]")
    console.print(f"  Total records in MongoDB: [bold]{total}[/]")
    console.print("\n  Next -> [bold]python 02_setup_index.py[/]")
