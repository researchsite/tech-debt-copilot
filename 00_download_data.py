#!/usr/bin/env python3
"""
00_download_data.py -- Tech Debt Copilot: Offline Data Cache

Downloads the complete endoflife.date dataset to a local JSON file.
Run this BEFORE the hackathon so you're immune to WiFi issues.

Saved file: data/eol_data_raw.json
  - Does NOT contain embeddings (those are created during ingestion)
  - Safe to re-run -- refreshes the cache
  - ~3-5 MB on disk, ~2-4 minutes on slow WiFi

Usage:
    python 00_download_data.py            # fresh download
    python 00_download_data.py --check    # show cache status only, don't download
    python 00_download_data.py --force    # re-download even if cache exists
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, UTC
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, TimeElapsedColumn, TextColumn
from rich.table import Table

console = Console()
DATA_DIR  = Path("data")
CACHE_FILE = DATA_DIR / "eol_data_raw.json"
META_FILE  = DATA_DIR / "eol_data_meta.json"


# -- Helpers -------------------------------------------------------------------

def parse_date(raw):
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


def build_content(label: str, category: str, tags: list, cycle: str, data: dict) -> str:
    codename    = f" ({data['codename']})" if data.get("codename") else ""
    lts_note    = " [Long-Term Support release]" if data.get("lts") else ""
    release     = data.get("releaseDate", "unknown date")
    _, eol_d    = parse_date(data.get("eol", False))
    _, sup_d    = parse_date(data.get("support", False))
    _, ext_d    = parse_date(data.get("extendedSupport", False))
    latest      = data.get("latest", "")
    latest_date = data.get("latestReleaseDate", "")
    tag_str     = ", ".join(tags) if tags else ""
    cat_str     = f" Category: {category}." if category else ""
    tag_part    = f" Tags: {tag_str}." if tag_str else ""
    latest_part = f" Latest version: {latest} (released {latest_date})." if latest else ""
    ext_part    = (f" Extended/paid support until: {ext_d}."
                   if data.get("extendedSupport") and isinstance(data.get("extendedSupport"), str) else "")
    return (
        f"Product: {label} version {cycle}{codename}{lts_note}."
        f"{cat_str}{tag_part}"
        f" Released: {release}."
        f" Mainstream support ends: {sup_d}."
        f" End of Life (EOL): {eol_d}."
        f"{ext_part}{latest_part}"
    )


def show_cache_status():
    if not CACHE_FILE.exists():
        console.print("[yellow]No local cache found.[/]")
        console.print(f"Run [bold]python 00_download_data.py[/] to create one.")
        return False

    meta = {}
    if META_FILE.exists():
        with open(META_FILE) as f:
            meta = json.load(f)

    records  = meta.get("total_records", "?")
    products = meta.get("total_products", "?")
    skipped  = meta.get("skipped", "?")
    ts       = meta.get("downloaded_at", "unknown")
    size_mb  = CACHE_FILE.stat().st_size / 1_048_576

    table = Table(title="Local EOL Cache Status", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Cache file",     str(CACHE_FILE))
    table.add_row("Downloaded at",  ts)
    table.add_row("File size",      f"{size_mb:.1f} MB")
    table.add_row("Total records",  str(records))
    table.add_row("Total products", str(products))
    table.add_row("Skipped",        str(skipped))
    console.print(table)
    return True


# -- Download pipeline ---------------------------------------------------------

def download_catalog() -> dict[str, dict]:
    console.print("[bold blue]>> Fetching product catalog from v1 API...[/]")
    r = requests.get("https://endoflife.date/api/v1/products", timeout=15)
    r.raise_for_status()
    products = r.json().get("result", [])
    catalog  = {
        p["name"]: {
            "label":    p.get("label", p["name"]),
            "category": p.get("category", ""),
            "tags":     p.get("tags", []),
            "aliases":  p.get("aliases", []),
        }
        for p in products
    }
    console.print(f"  [green]{len(catalog)}[/] products in catalog.")
    return catalog


def download_all_cycles(catalog: dict) -> tuple[list[dict], list[str]]:
    console.print("[bold blue]>> Downloading lifecycle data for all products...[/]")

    standard_keys = {
        "cycle", "releaseDate", "eol", "support", "lts",
        "extendedSupport", "latest", "latestReleaseDate",
        "link", "codename", "releaseLabel", "discontinued",
    }

    documents = []
    skipped   = []
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as bar:
        task = bar.add_task("Downloading", total=len(catalog))

        for product, meta in catalog.items():
            try:
                res = requests.get(
                    f"https://endoflife.date/api/{product}.json", timeout=10
                )
                if res.status_code != 200:
                    skipped.append(f"{product} (HTTP {res.status_code})")
                    bar.advance(task)
                    continue

                for cycle_data in res.json():
                    cycle         = str(cycle_data.get("cycle", "unknown"))
                    eol_q, eol_d  = parse_date(cycle_data.get("eol", False))
                    sup_q, _      = parse_date(cycle_data.get("support", False))
                    ext_q, _      = parse_date(cycle_data.get("extendedSupport", False))
                    custom        = {k: v for k, v in cycle_data.items() if k not in standard_keys}

                    documents.append({
                        "product_name":        product.lower(),
                        "product_label":       meta["label"],
                        "category":            meta["category"],
                        "tags":                meta["tags"],
                        "cycle":               cycle,
                        "codename":            cycle_data.get("codename", ""),
                        "release_label":       cycle_data.get("releaseLabel", ""),
                        "release_date":        str(cycle_data.get("releaseDate", "")),
                        "lts":                 bool(cycle_data.get("lts", False)),
                        "eol":                 eol_q,
                        "eol_display":         eol_d,
                        "support":             sup_q,
                        "extended_support":    ext_q,
                        "discontinued":        parse_date(cycle_data.get("discontinued", False))[0],
                        "latest":              str(cycle_data.get("latest", "")),
                        "latest_release_date": str(cycle_data.get("latestReleaseDate", "")),
                        "link":                str(cycle_data.get("link", "")),
                        "custom_fields":       custom,
                        "content":             build_content(
                                                   meta["label"], meta["category"],
                                                   meta["tags"], cycle, cycle_data
                                               ),
                        "memory_type":         "enterprise_tech_lifecycle",
                        "ingestion_date":      today_str,
                        "source":              "endoflife.date API v1 (local cache)",
                    })

                time.sleep(0.04)

            except Exception as exc:
                skipped.append(f"{product}: {exc}")

            bar.advance(task)

    return documents, skipped


def save_cache(documents: list[dict], skipped: list[str], catalog: dict):
    DATA_DIR.mkdir(exist_ok=True)
    ts = datetime.now(UTC).isoformat()

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(documents, f, ensure_ascii=False)

    meta = {
        "downloaded_at":  ts,
        "total_records":  len(documents),
        "total_products": len(catalog),
        "skipped":        len(skipped),
        "skipped_list":   skipped[:20],
        "schema_version": "2.0",
    }
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)

    size_mb = CACHE_FILE.stat().st_size / 1_048_576
    console.print(
        f"\n  [green]Saved {len(documents):,} records to [bold]{CACHE_FILE}[/] "
        f"({size_mb:.1f} MB)[/]"
    )
    if skipped:
        console.print(f"  [yellow]Skipped {len(skipped)} products: {skipped[:5]}{'...' if len(skipped) > 5 else ''}[/]")


# -- Entry point ---------------------------------------------------------------

if __name__ == "__main__":
    args   = sys.argv[1:]
    check  = "--check" in args
    force  = "--force" in args

    console.rule("[bold]Tech Debt Copilot -- Offline Data Cache[/]")

    if check:
        show_cache_status()
        raise SystemExit(0)

    if CACHE_FILE.exists() and not force:
        console.print(f"[yellow]Cache already exists at {CACHE_FILE}[/]")
        show_cache_status()
        console.print("\n  Use [bold]--force[/] to re-download, or proceed to ingestion.")
        console.print("  -> [bold]python 01b_ingest_local.py[/]   (from local cache)")
        console.print("  -> [bold]python 01_ingest.py[/]          (live from API)")
        raise SystemExit(0)

    try:
        catalog               = download_catalog()
        documents, skipped    = download_all_cycles(catalog)
        save_cache(documents, skipped, catalog)

        console.rule("[bold green]Download Complete[/]")
        console.print(f"  {len(documents):,} records cached locally.")
        console.print("\n  Next -> [bold]python 01b_ingest_local.py[/]  (embed + upload from cache)")
    except requests.exceptions.ConnectionError:
        console.print("[red]Network error -- cannot reach endoflife.date.[/]")
        console.print("If you already have a cache, run [bold]python 01b_ingest_local.py[/].")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Partial download not saved.[/]")
        raise SystemExit(1)
