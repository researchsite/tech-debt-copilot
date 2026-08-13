#!/usr/bin/env python3
"""
03_evaluate.py -- Tech Debt Copilot: Retrieval Quality Evaluation

Tests the vector search pipeline against ground-truth Q&A pairs.
Run AFTER ingestion + index setup to confirm everything is working.

Metrics reported:
  Precision@1  -- top result is the right product + cycle
  Precision@3  -- right answer appears in top 3 results
  Latency      -- average query time per question

Usage:
    python 03_evaluate.py              # full eval (requires MongoDB + Voyage AI)
    python 03_evaluate.py --quick      # first 5 tests only
    python 03_evaluate.py --verbose    # show full results for each query

Good score: P@1 >= 0.75, P@3 >= 0.90
"""

import os
import sys
import time
from dotenv import load_dotenv
from pymongo import MongoClient
import voyageai
from rich.console import Console
from rich.table import Table
from rich import box

load_dotenv()
console = Console()

MONGO_URI        = os.getenv("MONGO_URI")
MONGO_DB         = os.getenv("MONGO_DB", "techdebt_copilot")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
VOYAGE_API_KEY   = os.getenv("VOYAGE_API_KEY")
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "voyage-3")
INDEX_NAME       = "vector_index"


# -- Ground-truth test cases ---------------------------------------------------
# Each case tests that a realistic user query retrieves the right product+cycle.
# expected_product: the product_name stored in MongoDB (lowercase)
# expected_cycle:   the cycle field value (or substring of it)
# known_eol:        optional -- verified EOL date from endoflife.date, for content check

EVAL_CASES = [
    {
        "query":            "When does Python 3.9 reach end of life?",
        "product_name":     "python",
        "expected_product": "python",
        "expected_cycle":   "3.9",
        "known_eol":        "2025-10-05",
    },
    {
        "query":            "Ubuntu 20.04 LTS end of support date",
        "product_name":     "ubuntu",
        "expected_product": "ubuntu",
        "expected_cycle":   "20.04",
        "known_eol":        "2025-04-30",
    },
    {
        "query":            "Node.js 14 when does it expire?",
        "product_name":     "nodejs",
        "expected_product": "nodejs",
        "expected_cycle":   "14",
        "known_eol":        "2023-04-30",
    },
    {
        "query":            "MongoDB 4.4 end of life date",
        "product_name":     "mongodb",
        "expected_product": "mongodb",
        "expected_cycle":   "4.4",
        "known_eol":        "2024-02-29",
    },
    {
        "query":            "Kubernetes 1.22 end of support",
        "product_name":     "kubernetes",
        "expected_product": "kubernetes",
        "expected_cycle":   "1.22",
        "known_eol":        "2022-10-28",
    },
    {
        "query":            "Django 3.2 LTS security support end date",
        "product_name":     "django",
        "expected_product": "django",
        "expected_cycle":   "3.2",
        "known_eol":        "2024-04-01",
    },
    {
        "query":            "PostgreSQL 11 end of life",
        "product_name":     "postgresql",
        "expected_product": "postgresql",
        "expected_cycle":   "11",
        "known_eol":        "2023-11-09",
    },
    {
        "query":            "Redis 6 end of life and upgrade path",
        "product_name":     "redis",
        "expected_product": "redis",
        "expected_cycle":   "6",
        "known_eol":        None,  # varies by edition
    },
    {
        "query":            "Alpine Linux 3.12 end of support",
        "product_name":     "alpine-linux",
        "expected_product": "alpine-linux",
        "expected_cycle":   "3.12",
        "known_eol":        "2022-05-01",
    },
    {
        "query":            "Angular 12 framework end of life date",
        "product_name":     "angular",
        "expected_product": "angular",
        "expected_cycle":   "12",
        "known_eol":        "2022-11-12",
    },
    {
        "query":            "Ubuntu 22.04 extended support with Ubuntu Pro",
        "product_name":     "ubuntu",
        "expected_product": "ubuntu",
        "expected_cycle":   "22.04",
        "known_eol":        None,
    },
    {
        "query":            "Java 8 LTS end of life Oracle JDK",
        "product_name":     "java",
        "expected_product": "java",
        "expected_cycle":   "8",
        "known_eol":        None,
    },
    {
        "query":            "Debian 10 Buster end of life",
        "product_name":     "debian",
        "expected_product": "debian",
        "expected_cycle":   "10",
        "known_eol":        "2022-09-10",
    },
    {
        "query":            "MySQL 5.7 end of support date",
        "product_name":     "mysql",
        "expected_product": "mysql",
        "expected_cycle":   "5.7",
        "known_eol":        "2023-10-31",
    },
    {
        "query":            "Which database versions are expiring soon?",
        "product_name":     None,   # no pre-filter -- tests open-ended retrieval
        "expected_product": None,   # any database product is a pass
        "expected_cycle":   None,
        "known_eol":        None,
        "check_category":   "database",  # top result should be category=database
    },
]


# -- Retrieval function --------------------------------------------------------

def retrieve(
    collection,
    vo: voyageai.Client,
    query: str,
    product_name: str | None,
    k: int = 5,
) -> list[dict]:
    result     = vo.embed([query], model=EMBEDDING_MODEL, input_type="query")
    q_vec      = result.embeddings[0]

    vector_stage = {
        "$vectorSearch": {
            "index":         INDEX_NAME,
            "path":          "embedding",
            "queryVector":   q_vec,
            "numCandidates": 100,
            "limit":         k,
        }
    }
    if product_name:
        vector_stage["$vectorSearch"]["filter"] = {
            "product_name": {"$eq": product_name.lower()}
        }

    pipeline = [
        vector_stage,
        {
            "$project": {
                "product_name": 1,
                "cycle":        1,
                "content":      1,
                "category":     1,
                "eol":          1,
                "score":        {"$meta": "vectorSearchScore"},
                "_id":          0,
            }
        },
    ]
    return list(collection.aggregate(pipeline))


def score_result(results: list[dict], case: dict) -> tuple[bool, bool, str]:
    """
    Returns (hit@1, hit@3, reason).
    hit@1: top result matches expected product + cycle
    hit@3: any of top 3 results match
    """
    expected_product  = case.get("expected_product")
    expected_cycle    = case.get("expected_cycle")
    check_category    = case.get("check_category")

    if not results:
        return False, False, "No results returned"

    def is_match(doc: dict) -> bool:
        if check_category:
            return doc.get("category") == check_category
        prod_ok  = (expected_product is None) or (doc.get("product_name") == expected_product)
        cycle_ok = (expected_cycle is None) or (expected_cycle in str(doc.get("cycle", "")))
        return prod_ok and cycle_ok

    hit1 = is_match(results[0])
    hit3 = any(is_match(r) for r in results[:3])

    top = results[0]
    reason = (
        f"top={top.get('product_name')} v{top.get('cycle')} "
        f"(score={top.get('score', 0):.3f})"
    )
    return hit1, hit3, reason


# -- Entry point ---------------------------------------------------------------

if __name__ == "__main__":
    args    = sys.argv[1:]
    quick   = "--quick" in args
    verbose = "--verbose" in args

    console.rule("[bold]Tech Debt Copilot -- Retrieval Evaluation[/]")

    for var, name in [(MONGO_URI, "MONGO_URI"), (VOYAGE_API_KEY, "VOYAGE_API_KEY")]:
        if not var:
            console.print(f"[red]ERROR: {name} not set in .env[/]")
            raise SystemExit(1)

    client     = MongoClient(MONGO_URI)
    collection = client[MONGO_DB][MONGO_COLLECTION]
    vo         = voyageai.Client(api_key=VOYAGE_API_KEY)

    doc_count = collection.count_documents({})
    console.print(f"  Collection: [cyan]{MONGO_DB}.{MONGO_COLLECTION}[/] ({doc_count:,} docs)\n")

    if doc_count == 0:
        console.print("[red]No documents found. Run ingestion + index setup first.[/]")
        raise SystemExit(1)

    cases  = EVAL_CASES[:5] if quick else EVAL_CASES
    rows   = []
    hits1  = 0
    hits3  = 0
    total_ms = 0.0

    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        try:
            results = retrieve(collection, vo, case["query"], case.get("product_name"))
        except Exception as exc:
            rows.append((str(i), case["query"][:45], "ERROR", "ERROR", "--", str(exc)[:40]))
            continue
        elapsed_ms = (time.perf_counter() - t0) * 1000
        total_ms  += elapsed_ms

        hit1, hit3, reason = score_result(results, case)
        hits1 += int(hit1)
        hits3 += int(hit3)

        status1 = "[green]ok[/]" if hit1 else "[red]x[/]"
        status3 = "[green]ok[/]" if hit3 else "[yellow]~[/]"
        rows.append((
            str(i),
            case["query"][:50],
            status1,
            status3,
            f"{elapsed_ms:.0f}ms",
            reason,
        ))

        if verbose:
            console.print(f"\n[bold]Q{i}:[/] {case['query']}")
            for j, r in enumerate(results[:3], 1):
                mark = "ok" if (j == 1 and hit1) else "~" if hit3 and j <= 3 else " "
                console.print(
                    f"  [{mark}] #{j}: {r.get('product_name')} v{r.get('cycle')} "
                    f"(score={r.get('score',0):.3f}) | {r.get('content','')[:80]}..."
                )

    # Summary table
    table = Table(
        title=f"Evaluation Results ({len(cases)} test cases)",
        box=box.SIMPLE_HEAD,
        show_lines=False,
    )
    table.add_column("#",       width=3)
    table.add_column("Query",   width=52)
    table.add_column("P@1",     width=4,  justify="center")
    table.add_column("P@3",     width=4,  justify="center")
    table.add_column("Latency", width=8,  justify="right")
    table.add_column("Top result")

    for row in rows:
        table.add_row(*row)

    console.print()
    console.print(table)

    p1  = hits1 / len(cases) if cases else 0
    p3  = hits3 / len(cases) if cases else 0
    avg = total_ms / len(cases) if cases else 0

    console.print()
    console.print(f"  Precision@1:    [bold {'green' if p1 >= 0.75 else 'yellow'}]{p1:.0%}[/]  (target >= 75%)")
    console.print(f"  Precision@3:    [bold {'green' if p3 >= 0.90 else 'yellow'}]{p3:.0%}[/]  (target >= 90%)")
    console.print(f"  Avg latency:    [bold]{avg:.0f}ms[/] per query")

    if p1 < 0.75:
        console.print("\n  [yellow]Tips to improve P@1:[/]")
        console.print("    - Re-run ingestion -- content strings may need refreshing")
        console.print("    - Check EMBEDDING_DIM matches the index (1024 for voyage-3)")
        console.print("    - Ensure index status is READY in Atlas")
    else:
        console.print("\n  [bold green]Retrieval quality looks good -- ready for the demo![/]")

    client.close()
