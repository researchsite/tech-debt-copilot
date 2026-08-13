"""
agent/scanner.py -- Local stack detection for Tech Debt Copilot

Detects installed software from multiple sources:
  - Python runtime (always available)
  - pip packages (via importlib.metadata, no subprocess)
  - Node.js runtime (subprocess, optional)
  - npm global packages (subprocess, optional)

Returns structured records ready for EOL lookup in MongoDB.
"""

import sys
import json
import subprocess
from importlib.metadata import packages_distributions, version as pkg_version

# Products that endoflife.date actually tracks, mapped to their EOL product slug
# and how to extract the cycle from a semver string (minor = X.Y, major = X)
EOL_PRODUCTS = {
    # Python packages (pip)
    "django":         ("django",      "minor"),  # 4.2.3 -> 4.2
    "flask":          ("flask",       "minor"),  # 3.0.1 -> 3.0
    "fastapi":        ("fastapi",     "minor"),
    "ansible":        ("ansible",     "minor"),
    "ansible-core":   ("ansible",     "minor"),
    "sqlalchemy":     ("sqlalchemy",  "minor"),
    "celery":         ("celery",      "minor"),
    "pydantic":       ("pydantic",    "minor"),
    # npm packages (global or local)
    "react":          ("react",       "major"),  # 18.2.0 -> 18
    "angular":        ("angular",     "major"),
    "@angular/core":  ("angular",     "major"),
    "vue":            ("vue",         "major"),
    "express":        ("express",     "major"),
    "next":           ("nextjs",      "major"),
    "nuxt":           ("nuxtjs",      "major"),
    "gatsby":         ("gatsby",      "major"),
    "svelte":         ("svelte",      "major"),
    "ember-source":   ("ember",       "major"),
    # Detected via subprocess (not pip/npm)
    "python":         ("python",      "minor"),  # 3.9.7 -> 3.9
    "node":           ("nodejs",      "major"),  # 18.12.0 -> 18
    "nodejs":         ("nodejs",      "major"),
    "php":            ("php",         "minor"),
    "ruby":           ("ruby",        "minor"),
    "go":             ("go",          "minor"),
    "dotnet":         ("dotnet",      "major"),
}


def _to_cycle(version: str, mode: str) -> str:
    parts = version.lstrip("v").split(".")
    if mode == "major":
        return parts[0]
    return ".".join(parts[:2])


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.check_output(cmd, timeout=6, stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:
        return None


def detect_python_runtime() -> list[dict]:
    vi = sys.version_info
    ver = f"{vi.major}.{vi.minor}.{vi.micro}"
    return [{
        "source":      "python_runtime",
        "package":     "python",
        "version":     ver,
        "eol_product": "python",
        "cycle":       _to_cycle(ver, "minor"),
    }]


def detect_pip_packages() -> list[dict]:
    results = []
    try:
        # packages_distributions() returns {import_name: [dist_name, ...]}
        dist_map = packages_distributions()
        seen_dist = {}
        for dists in dist_map.values():
            for dist in dists:
                key = dist.lower()
                if key not in seen_dist:
                    try:
                        seen_dist[key] = pkg_version(dist)
                    except Exception:
                        pass
    except Exception:
        return results

    for pkg_lower, ver in seen_dist.items():
        if pkg_lower in EOL_PRODUCTS:
            eol_product, mode = EOL_PRODUCTS[pkg_lower]
            results.append({
                "source":      "pip",
                "package":     pkg_lower,
                "version":     ver,
                "eol_product": eol_product,
                "cycle":       _to_cycle(ver, mode),
            })
    return results


def detect_node_runtime() -> list[dict]:
    raw = _run(["node", "--version"])
    if not raw:
        return []
    ver = raw.lstrip("v")
    return [{
        "source":      "node_runtime",
        "package":     "node",
        "version":     ver,
        "eol_product": "nodejs",
        "cycle":       _to_cycle(ver, "major"),
    }]


def detect_npm_globals() -> list[dict]:
    raw = _run(["npm", "list", "-g", "--json", "--depth=0"])
    if not raw:
        return []
    results = []
    try:
        data = json.loads(raw)
        for pkg_name, info in data.get("dependencies", {}).items():
            key = pkg_name.lower()
            if key in EOL_PRODUCTS:
                eol_product, mode = EOL_PRODUCTS[key]
                ver = info.get("version", "")
                if ver:
                    results.append({
                        "source":      "npm_global",
                        "package":     key,
                        "version":     ver,
                        "eol_product": eol_product,
                        "cycle":       _to_cycle(ver, mode),
                    })
    except Exception:
        pass
    return results


def detect_php() -> list[dict]:
    raw = _run(["php", "--version"])
    if not raw:
        return []
    first_line = raw.splitlines()[0]  # "PHP 8.1.27 (cli)..."
    parts = first_line.split()
    if len(parts) < 2:
        return []
    ver = parts[1]
    return [{
        "source":      "php_runtime",
        "package":     "php",
        "version":     ver,
        "eol_product": "php",
        "cycle":       _to_cycle(ver, "minor"),
    }]


def detect_ruby() -> list[dict]:
    raw = _run(["ruby", "--version"])
    if not raw:
        return []
    # "ruby 3.2.2 (2023-03-30 revision e51014f9c0) [x86_64-linux]"
    parts = raw.split()
    if len(parts) < 2:
        return []
    ver = parts[1]
    return [{
        "source":      "ruby_runtime",
        "package":     "ruby",
        "version":     ver,
        "eol_product": "ruby",
        "cycle":       _to_cycle(ver, "minor"),
    }]


def scan_all() -> list[dict]:
    items = (
        detect_python_runtime()
        + detect_pip_packages()
        + detect_node_runtime()
        + detect_npm_globals()
        + detect_php()
        + detect_ruby()
    )
    # Deduplicate: keep the first seen per eol_product (runtime beats pip)
    seen = {}
    for item in items:
        key = item["eol_product"]
        if key not in seen:
            seen[key] = item
    return list(seen.values())
