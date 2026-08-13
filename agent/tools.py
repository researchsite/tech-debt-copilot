"""
agent/tools.py -- LangGraph tools for the Tech Debt Copilot

Five tools the agent can call:
  1. search_eol_data           -- MongoDB $vectorSearch + $eq pre-filter (Voyage AI)
  2. check_cve_vulnerabilities -- OSV.dev API live CVE cross-reference
  3. find_upcoming_eols        -- Products expiring within N days (MongoDB aggregation)
  4. analyze_industry_trends   -- EOL exposure by technology category + trend insights
  5. scan_local_stack          -- Detect installed software and cross-reference against EOL DB
"""

import os
from datetime import datetime, timedelta, UTC
from typing import Optional
import requests
import voyageai
from pymongo import MongoClient
from langchain_core.tools import tool
from dotenv import load_dotenv

load_dotenv()

MONGO_URI        = os.getenv("MONGO_URI")
MONGO_DB         = os.getenv("MONGO_DB", "techdebt_copilot")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "eol_lifecycle")
VOYAGE_API_KEY   = os.getenv("VOYAGE_API_KEY")
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "voyage-3")
INDEX_NAME       = "vector_index"

_mongo_client: MongoClient | None = None
_voyage_client: voyageai.Client | None = None


def _mongo():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI)
    return _mongo_client[MONGO_DB][MONGO_COLLECTION]


def _voyage():
    global _voyage_client
    if _voyage_client is None:
        _voyage_client = voyageai.Client(api_key=VOYAGE_API_KEY)
    return _voyage_client


# -- Tool 1: Semantic EOL search with pre-filtering ----------------------------

@tool
def search_eol_data(query: str, product_name: Optional[str] = None) -> str:
    """
    Search the End-of-Life database (1,500+ records, 464 products) for
    lifecycle information using semantic search with optional pre-filtering.

    Args:
        query: Natural language query, e.g. "When does Python 3.9 reach EOL?"
               or "Ubuntu LTS extended support dates"
        product_name: Optional lowercase product name for precision.
                      Examples: "python", "nodejs", "ubuntu", "mongodb",
                      "kubernetes", "django", "react", "postgresql", "redis",
                      "windows", "android", "alpine-linux", "dotnet".
                      When provided, MongoDB $vectorSearch only searches within
                      that product's semantic space -- preventing cross-product
                      result bleed.

    Returns:
        Lifecycle records with EOL dates, support windows, codenames, and links.
    """
    try:
        collection = _mongo()
        vo         = _voyage()

        # input_type="query" is DIFFERENT from "document" -- Voyage AI uses
        # asymmetric embeddings. Using wrong type degrades retrieval quality.
        result          = vo.embed([query], model=EMBEDDING_MODEL, input_type="query")
        query_embedding = result.embeddings[0]

        vector_stage = {
            "$vectorSearch": {
                "index":         INDEX_NAME,
                "path":          "embedding",
                "queryVector":   query_embedding,
                "numCandidates": 150,
                "limit":         6,
            }
        }

        if product_name:
            vector_stage["$vectorSearch"]["filter"] = {
                "product_name": {"$eq": product_name.lower().strip()}
            }

        pipeline = [
            vector_stage,
            {
                "$project": {
                    "content":           1,
                    "product_name":      1,
                    "product_label":     1,
                    "category":          1,
                    "cycle":             1,
                    "codename":          1,
                    "eol_display":       1,
                    "extended_support":  1,
                    "latest":            1,
                    "latest_release_date": 1,
                    "link":              1,
                    "lts":               1,
                    "score":             {"$meta": "vectorSearchScore"},
                    "_id":               0,
                }
            },
        ]

        results = list(collection.aggregate(pipeline))
        if not results:
            hint = f" for '{product_name}'" if product_name else ""
            return (
                f"No results found{hint}. Check spelling -- the DB uses lowercase "
                "hyphenated names: 'nodejs' not 'node.js', 'dotnet' not '.net', "
                "'alpine-linux' not 'alpine', 'amazon-linux' not 'amzn'."
            )

        lines = [f"Found {len(results)} lifecycle record(s):\n"]
        for i, doc in enumerate(results, 1):
            label     = doc.get("product_label") or doc.get("product_name", "")
            codename  = f" ({doc['codename']})" if doc.get("codename") else ""
            lts_badge = " [LTS]" if doc.get("lts") else ""
            ext       = f"\n   Extended/paid support: {doc['extended_support']}" if doc.get("extended_support") else ""
            latest    = f"\n   Latest version: {doc['latest']} (updated {doc.get('latest_release_date', '?')})" if doc.get("latest") else ""
            link      = f"\n   Release notes: {doc['link']}" if doc.get("link") else ""
            lines.append(
                f"{i}. [{label} v{doc['cycle']}{codename}{lts_badge}]\n"
                f"   {doc['content']}"
                f"{ext}{latest}{link}"
            )
        return "\n\n".join(lines)

    except Exception as exc:
        return (
            f"EOL search error: {exc}. "
            "Ensure MONGO_URI and VOYAGE_API_KEY are set, and the vector index is active."
        )


# -- Tool 2: CVE vulnerability cross-reference ---------------------------------

@tool
def check_cve_vulnerabilities(product: str, version: str) -> str:
    """
    Cross-reference OSV.dev for known CVE vulnerabilities on a product version.
    Use alongside search_eol_data to give the full security picture: EOL + CVEs.

    Args:
        product: Product name, e.g. "python", "log4j", "openssl", "django"
        version: Specific version, e.g. "3.9.0", "4.4", "2.14.1", "3.2.0"

    Returns:
        CVE IDs, severity ratings, and summaries. Empty = no known CVEs in OSV.
    """
    ECOSYSTEM_MAP = {
        "python": "PyPI",   "django": "PyPI",    "flask": "PyPI",    "fastapi": "PyPI",
        "nodejs": "npm",    "node":   "npm",      "express": "npm",   "react": "npm",
                            "angular": "npm",     "vue": "npm",       "next": "npm",
        "ruby":   "RubyGems",
        "php":    "Packagist",
        "go":     "Go",
        "rust":   "crates.io",
        "java":   "Maven",  "spring": "Maven",   "log4j": "Maven",
        "dotnet": "NuGet",  ".net":   "NuGet",
    }

    try:
        ecosystem = ECOSYSTEM_MAP.get(product.lower())
        payload   = {"version": version, "package": {"name": product}}
        if ecosystem:
            payload["package"]["ecosystem"] = ecosystem

        resp = requests.post("https://api.osv.dev/v1/query", json=payload, timeout=10)
        resp.raise_for_status()
        vulns = resp.json().get("vulns", [])

        if not vulns:
            return (
                f"No CVEs found in OSV.dev for {product} v{version}. "
                "(Always verify with vendor advisories -- OSV may not have full coverage.)"
            )

        lines = [f"Found {len(vulns)} CVE(s) for {product} v{version}:\n"]
        for v in vulns[:8]:
            cve_ids  = [a for a in v.get("aliases", []) if a.startswith("CVE-")]
            label    = ", ".join(cve_ids) if cve_ids else v.get("id", "?")
            severity = v.get("database_specific", {}).get("severity", "Unknown")
            summary  = v.get("summary", "No summary")[:160]
            lines.append(f"  - {label} [{severity}]: {summary}")

        if len(vulns) > 8:
            lines.append(f"\n  ...and {len(vulns) - 8} more. See: https://osv.dev")

        return "\n".join(lines)

    except Exception as exc:
        return f"OSV.dev query error: {exc}"


# -- Tool 3: Proactive upcoming EOL scanner ------------------------------------

@tool
def find_upcoming_eols(days_ahead: int = 180, category: Optional[str] = None) -> str:
    """
    Find products reaching End-of-Life within the next N days.
    Optionally filter by technology category for focused audits.

    Args:
        days_ahead: Lookahead window in days (default 180 = 6 months).
                    Use 30 for urgent triage, 90 for quarterly review, 365 for annual planning.
        category:   Optional category filter:
                    'database' | 'os' | 'lang' | 'framework' | 'app' |
                    'service'  | 'device' | 'server-app' | 'standard'

    Returns:
        Products sorted by soonest EOL, with urgency flags and extended support info.
    """
    try:
        collection = _mongo()
        today      = datetime.now(UTC)
        cutoff     = today + timedelta(days=days_ahead)
        today_s    = today.strftime("%Y-%m-%d")
        cutoff_s   = cutoff.strftime("%Y-%m-%d")

        match_filter: dict = {"eol": {"$gte": today_s, "$lte": cutoff_s}}
        if category:
            match_filter["category"] = category.lower()

        pipeline = [
            {"$match": match_filter},
            {"$sort": {"eol": 1}},
            {
                "$group": {
                    "_id":           "$product_name",
                    "product_label": {"$first": "$product_label"},
                    "category":      {"$first": "$category"},
                    "versions": {
                        "$push": {
                            "cycle":            "$cycle",
                            "codename":         "$codename",
                            "eol":              "$eol",
                            "extended_support": "$extended_support",
                            "lts":              "$lts",
                        }
                    },
                }
            },
            {"$sort": {"versions.0.eol": 1}},
            {"$limit": 30},
        ]

        results = list(collection.aggregate(pipeline))
        if not results:
            cat_hint = f" in category '{category}'" if category else ""
            return (
                f"No products reaching EOL in the next {days_ahead} days{cat_hint}. "
                "Stack looks clear for this window."
            )

        cat_label = f" [{category}]" if category else ""
        lines     = [
            f"Products reaching EOL in the next {days_ahead} days{cat_label} "
            f"({today_s} -> {cutoff_s}):\n"
        ]

        for product in results:
            name     = product.get("product_label") or product["_id"].upper()
            cat      = product.get("category", "")
            versions = sorted(product["versions"], key=lambda v: v.get("eol") or "")[:4]
            lines.append(f"\n{name} [{cat}]:")

            for v in versions:
                eol_str   = v.get("eol", "?")
                codename  = f" ({v['codename']})" if v.get("codename") else ""
                lts_badge = " [LTS]" if v.get("lts") else ""
                ext       = f" | extended support -> {v['extended_support']}" if v.get("extended_support") else ""
                try:
                    days_left = (datetime.strptime(eol_str, "%Y-%m-%d") - today).days
                    urgency   = "🔴 CRITICAL" if days_left <= 30 else ("🟠 HIGH" if days_left <= 90 else "🟡 MEDIUM")
                except ValueError:
                    days_left, urgency = "?", ""

                lines.append(
                    f"  - v{v['cycle']}{codename}{lts_badge}: EOL {eol_str} "
                    f"({days_left}d) {urgency}{ext}"
                )

        return "\n".join(lines)

    except Exception as exc:
        return f"Upcoming EOL query error: {exc}"


# -- Tool 4: Industry trend analysis -------------------------------------------

@tool
def analyze_industry_trends(
    category: Optional[str] = None,
    days_ahead: int = 365,
) -> str:
    """
    Analyze End-of-Life trends across technology categories.
    Answers questions like:
    - "Which technology category has the most upcoming EOLs?"
    - "Show me the database EOL landscape for 2025"
    - "How many OS versions are expiring this year vs last year?"
    - "Are LTS releases expiring soon?"

    Args:
        category:   Focus on one category (optional):
                    'database' | 'os' | 'lang' | 'framework' | 'app' |
                    'service'  | 'device' | 'server-app' | 'standard'
                    If omitted, returns a cross-category comparison.
        days_ahead: Time window for analysis in days (default 365 = 1 year).

    Returns:
        Category-level EOL counts, top at-risk products, and trend insights.
    """
    try:
        collection = _mongo()
        today      = datetime.now(UTC)
        cutoff     = today + timedelta(days=days_ahead)
        today_s    = today.strftime("%Y-%m-%d")
        cutoff_s   = cutoff.strftime("%Y-%m-%d")

        if category:
            # Deep dive into one category -- show all products + EOL breakdown
            pipeline = [
                {
                    "$match": {
                        "category": category.lower(),
                        "eol":      {"$gte": today_s, "$lte": cutoff_s},
                    }
                },
                {"$sort": {"eol": 1}},
                {
                    "$group": {
                        "_id":           "$product_name",
                        "product_label": {"$first": "$product_label"},
                        "versions":      {"$push": {"cycle": "$cycle", "eol": "$eol", "lts": "$lts"}},
                        "count":         {"$sum": 1},
                    }
                },
                {"$sort": {"count": -1}},
                {"$limit": 20},
            ]
            results = list(collection.aggregate(pipeline))
            if not results:
                return (
                    f"No EOLs found for category '{category}' in the next {days_ahead} days. "
                    f"This category looks healthy for the next {'year' if days_ahead >= 365 else f'{days_ahead} days'}."
                )

            total_versions = sum(r["count"] for r in results)
            lines = [
                f"Category: [bold]{category.upper()}[/] -- "
                f"{total_versions} versions expiring in {days_ahead}d "
                f"across {len(results)} products:\n"
            ]
            for r in results[:15]:
                name     = r.get("product_label") or r["_id"]
                versions = sorted(r["versions"], key=lambda v: v.get("eol") or "")
                eols     = [v.get("eol", "?") for v in versions[:3]]
                lts_flag = " [has LTS versions]" if any(v.get("lts") for v in versions) else ""
                lines.append(f"  - {name}{lts_flag}: {', '.join(eols)}")

            return "\n".join(lines)

        else:
            # Cross-category breakdown -- the industry trends overview
            pipeline = [
                {
                    "$match": {
                        "eol": {"$gte": today_s, "$lte": cutoff_s},
                    }
                },
                {
                    "$group": {
                        "_id":              "$category",
                        "eol_version_count": {"$sum": 1},
                        "product_count":    {"$addToSet": "$product_name"},
                        "lts_count":        {"$sum": {"$cond": [{"$eq": ["$lts", True]}, 1, 0]}},
                    }
                },
                {
                    "$project": {
                        "category":           "$_id",
                        "eol_version_count":  1,
                        "unique_products":    {"$size": "$product_count"},
                        "lts_count":          1,
                    }
                },
                {"$sort": {"eol_version_count": -1}},
            ]

            results = list(collection.aggregate(pipeline))
            total   = sum(r["eol_version_count"] for r in results)

            lines = [
                f"Industry EOL Trend Analysis -- Next {days_ahead} days "
                f"({today_s} -> {cutoff_s})\n"
                f"Total: {total} versions expiring across {len(results)} categories:\n"
            ]

            for r in results:
                cat      = r.get("category") or "uncategorized"
                count    = r["eol_version_count"]
                products = r["unique_products"]
                lts      = r["lts_count"]
                bar_len  = int((count / max(total, 1)) * 30)
                bar      = "#" * bar_len
                lts_note = f" ({lts} LTS)" if lts else ""
                lines.append(
                    f"  {cat:<15s} {bar:<32s} {count:>4} versions / {products:>3} products{lts_note}"
                )

            lines.append(
                "\nAsk me to drill into any category: "
                "'Show all database EOLs' or 'Which OS versions expire this quarter?'"
            )
            return "\n".join(lines)

    except Exception as exc:
        return f"Industry trends query error: {exc}"


# -- Tool 5: Local machine stack scanner ---------------------------------------

@tool
def scan_local_stack() -> str:
    """
    Scan the software installed on THIS machine (Python runtime, pip packages,
    Node.js runtime, npm globals, PHP, Ruby) and cross-reference each against
    the EOL database. Returns a report grouped by urgency: EXPIRED, CRITICAL,
    HIGH, MEDIUM, OK, and packages not tracked by endoflife.date.

    No arguments needed. Call this when the user says:
    - "scan my machine" / "check my stack" / "what's at risk on my computer"
    - "audit my installed software" / "what do I have that's EOL?"
    - "run a local scan"
    """
    from agent.scanner import scan_all
    from datetime import datetime, UTC

    try:
        items = scan_all()
    except Exception as exc:
        return f"Scanner error: {exc}"

    if not items:
        return "No trackable packages detected on this machine."

    try:
        collection = _mongo()
        today      = datetime.now(UTC).date()
        today_str  = today.isoformat()

        found     = []
        not_found = []

        for item in items:
            doc = collection.find_one(
                {"product_name": item["eol_product"], "cycle": item["cycle"]},
                {
                    "eol": 1, "eol_display": 1, "extended_support": 1,
                    "product_label": 1, "lts": 1, "support": 1,
                    "_id": 0,
                },
            )
            if not doc:
                not_found.append(f"{item['package']} {item['version']}")
                continue

            eol_str     = doc.get("eol")
            eol_display = doc.get("eol_display", "unknown")
            label       = doc.get("product_label") or item["eol_product"]
            lts         = doc.get("lts", False)
            ext         = doc.get("extended_support")

            days = None
            if eol_str:
                try:
                    eol_date = datetime.strptime(eol_str, "%Y-%m-%d").date()
                    days = (eol_date - today).days
                except ValueError:
                    pass

            if days is None:
                urgency = "OK"
            elif days < 0:
                urgency = "EXPIRED"
            elif days <= 30:
                urgency = "CRITICAL"
            elif days <= 90:
                urgency = "HIGH"
            elif days <= 365:
                urgency = "MEDIUM"
            else:
                urgency = "OK"

            found.append({
                "label":            label,
                "version":          item["version"],
                "cycle":            item["cycle"],
                "eol_display":      eol_display,
                "days":             days,
                "urgency":          urgency,
                "lts":              lts,
                "extended_support": ext,
                "source":           item["source"],
            })

        # Sort: worst first, then by days_left
        urgency_rank = {"EXPIRED": 0, "CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "OK": 4}
        found.sort(key=lambda x: (urgency_rank.get(x["urgency"], 5), x.get("days") or 9999))

        lines = [f"LOCAL STACK SCAN -- {today_str}\n"]
        lines.append(f"Detected {len(found) + len(not_found)} trackable packages; "
                     f"{len(found)} matched in EOL database.\n")

        for urgency in ["EXPIRED", "CRITICAL", "HIGH", "MEDIUM", "OK"]:
            group = [f for f in found if f["urgency"] == urgency]
            if not group:
                continue
            lines.append(f"\n[{urgency}]")
            for f in group:
                lts_tag  = " [LTS]" if f["lts"] else ""
                if f["days"] is not None:
                    age = abs(f["days"])
                    day_str = f"{age}d ago" if f["days"] < 0 else f"{age}d remaining"
                else:
                    day_str = "no EOL date"
                ext_note = f" | Extended support until: {f['extended_support']}" if f.get("extended_support") else ""
                lines.append(
                    f"  {f['label']} {f['version']} (cycle {f['cycle']}){lts_tag}"
                    f" -- EOL: {f['eol_display']} ({day_str}){ext_note}"
                )

        if not_found:
            lines.append(f"\n[NOT IN EOL DATABASE] ({len(not_found)} packages -- no EOL tracking needed)")
            lines.append("  " + ", ".join(not_found[:12]))
            if len(not_found) > 12:
                lines.append(f"  ...and {len(not_found) - 12} more")

        lines.append(
            "\nTip: Ask me to dig into any specific finding -- "
            "'Tell me more about the Django risk' or 'Check CVEs for Python 3.9'."
        )
        return "\n".join(lines)

    except Exception as exc:
        return f"EOL lookup error during scan: {exc}"
