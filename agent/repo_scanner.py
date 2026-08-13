"""
agent/repo_scanner.py -- Dependency file parser for git repositories

Supports:
  - GitHub URLs  : https://github.com/owner/repo
  - Local paths  : C:/projects/myapp  or  /home/user/myapp

Parses:
  - requirements.txt  (Python)
  - pyproject.toml    (Python - PEP 517/518)
  - Pipfile           (Python - pipenv)
  - package.json      (Node.js)
  - .nvmrc / .node-version (Node.js runtime)
  - Gemfile.lock      (Ruby)
  - go.mod            (Go)
"""

import re
import json
import sys
import requests
from pathlib import Path


# Maps dependency file package name (lowercased) -> EOL product slug
# Only packages that endoflife.date actually tracks
EOL_MAP = {
    # Python frameworks / libraries
    "django":          ("django",      "minor"),
    "flask":           ("flask",       "minor"),
    "fastapi":         ("fastapi",     "minor"),
    "ansible":         ("ansible",     "minor"),
    "ansible-core":    ("ansible",     "minor"),
    "sqlalchemy":      ("sqlalchemy",  "minor"),
    "celery":          ("celery",      "minor"),
    "pydantic":        ("pydantic",    "minor"),
    # Node packages
    "react":           ("react",       "major"),
    "react-dom":       ("react",       "major"),
    "@angular/core":   ("angular",     "major"),
    "angular":         ("angular",     "major"),
    "vue":             ("vue",         "major"),
    "express":         ("express",     "major"),
    "next":            ("nextjs",      "major"),
    "nuxt":            ("nuxtjs",      "major"),
    "gatsby":          ("gatsby",      "major"),
    "svelte":          ("svelte",      "major"),
    "ember-source":    ("ember",       "major"),
    # Runtimes (detected from special files)
    "python":          ("python",      "minor"),
    "node":            ("nodejs",      "major"),
    "ruby":            ("ruby",        "minor"),
    "go":              ("go",          "minor"),
    "php":             ("php",         "minor"),
    "dotnet":          ("dotnet",      "major"),
}

DEPENDENCY_FILES = [
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "package.json",
    ".nvmrc",
    ".node-version",
    "Gemfile",
    "go.mod",
]


def _to_cycle(version: str, mode: str) -> str:
    version = version.strip().lstrip("v~^>=<!=")
    parts = version.split(".")
    if not parts or not parts[0].isdigit():
        return version
    if mode == "major":
        return parts[0]
    return ".".join(parts[:2])


# ── GitHub fetcher ─────────────────────────────────────────────────────────────

def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL."""
    m = re.search(r"github\.com[/:]([^/]+)/([^/\s.]+)", url)
    if not m:
        return None
    return m.group(1), m.group(2).removesuffix(".git")


def _fetch_github_file(owner: str, repo: str, filename: str, token: str = "") -> str | None:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{filename}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def _fetch_github_tree(owner: str, repo: str, token: str = "") -> list[str]:
    """Get list of files at root level of the repo."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            return [item["path"] for item in r.json().get("tree", [])]
    except Exception:
        pass
    return []


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_requirements_txt(content: str) -> list[dict]:
    deps = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Remove extras like package[extra]==version
        line = re.sub(r"\[.*?\]", "", line)
        m = re.match(r"([A-Za-z0-9_\-\.]+)\s*([=<>!~]+)\s*([\d\.]+)", line)
        if m:
            pkg  = m.group(1).lower().replace("_", "-")
            ver  = m.group(3)
            if pkg in EOL_MAP:
                eol_product, mode = EOL_MAP[pkg]
                deps.append({"package": pkg, "version": ver,
                             "eol_product": eol_product, "cycle": _to_cycle(ver, mode),
                             "file": "requirements.txt"})
    return deps


def parse_package_json(content: str) -> list[dict]:
    deps = []
    try:
        data = json.loads(content)
    except Exception:
        return deps
    all_deps = {}
    all_deps.update(data.get("dependencies", {}))
    all_deps.update(data.get("devDependencies", {}))

    # Node engine version
    engines = data.get("engines", {})
    node_ver = engines.get("node", "")
    if node_ver:
        ver_clean = re.sub(r"[^0-9.]", "", node_ver.split(" ")[0])
        if ver_clean and ver_clean[0].isdigit():
            deps.append({"package": "node", "version": ver_clean,
                         "eol_product": "nodejs", "cycle": _to_cycle(ver_clean, "major"),
                         "file": "package.json (engines.node)"})

    for pkg, ver_range in all_deps.items():
        pkg_lower = pkg.lower()
        if pkg_lower not in EOL_MAP:
            continue
        ver_clean = re.sub(r"[^0-9.]", "", ver_range.lstrip("^~>=<").split(" ")[0])
        if not ver_clean or not ver_clean[0].isdigit():
            continue
        eol_product, mode = EOL_MAP[pkg_lower]
        deps.append({"package": pkg_lower, "version": ver_clean,
                     "eol_product": eol_product, "cycle": _to_cycle(ver_clean, mode),
                     "file": "package.json"})
    return deps


def parse_pyproject_toml(content: str) -> list[dict]:
    deps = []
    # Use stdlib tomllib (Python 3.11+) or fall back to regex
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            data = tomllib.loads(content)
            requires = (data.get("project", {}).get("dependencies", []) +
                        data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
        else:
            raise ImportError
    except Exception:
        # Fallback: regex extract package==version lines
        requires = re.findall(r'["\']([A-Za-z0-9_\-\.]+[>=<!\~][^"\']+)["\']', content)

    for dep in requires:
        dep = str(dep).strip()
        m = re.match(r"([A-Za-z0-9_\-\.]+)\s*[>=<!\~]+\s*([\d\.]+)", dep)
        if m:
            pkg = m.group(1).lower().replace("_", "-")
            ver = m.group(2)
            if pkg in EOL_MAP:
                eol_product, mode = EOL_MAP[pkg]
                deps.append({"package": pkg, "version": ver,
                             "eol_product": eol_product, "cycle": _to_cycle(ver, mode),
                             "file": "pyproject.toml"})
    return deps


def parse_nvmrc(content: str) -> list[dict]:
    ver = content.strip().lstrip("v")
    if ver and ver[0].isdigit():
        return [{"package": "node", "version": ver,
                 "eol_product": "nodejs", "cycle": _to_cycle(ver, "major"),
                 "file": ".nvmrc"}]
    return []


def parse_go_mod(content: str) -> list[dict]:
    m = re.search(r"^go\s+([\d\.]+)", content, re.MULTILINE)
    if m:
        ver = m.group(1)
        return [{"package": "go", "version": ver,
                 "eol_product": "go", "cycle": _to_cycle(ver, "minor"),
                 "file": "go.mod"}]
    return []


PARSERS = {
    "requirements.txt": parse_requirements_txt,
    "pyproject.toml":   parse_pyproject_toml,
    "package.json":     parse_package_json,
    ".nvmrc":           parse_nvmrc,
    ".node-version":    parse_nvmrc,
    "go.mod":           parse_go_mod,
}


# ── Main scanner ──────────────────────────────────────────────────────────────

def scan_repo(source: str, github_token: str = "") -> tuple[list[dict], dict]:
    """
    Scan a repository for tracked dependencies.

    Args:
        source: GitHub URL (https://github.com/owner/repo)
                OR local path (C:/projects/myapp)
        github_token: optional GitHub PAT for private repos

    Returns:
        (deps, meta) where deps is list of parsed dependency records
        and meta has source info.
    """
    deps = []
    meta = {"source": source, "files_found": [], "files_missing": [], "files_with_matches": []}

    github = _parse_github_url(source)

    if github:
        owner, repo = github
        meta["repo"] = f"{owner}/{repo}"
        meta["url"]  = f"https://github.com/{owner}/{repo}"

        for filename in DEPENDENCY_FILES:
            content = _fetch_github_file(owner, repo, filename, github_token)
            if content is not None:
                meta["files_found"].append(filename)
                if filename in PARSERS:
                    found = PARSERS[filename](content)
                    deps.extend(found)
                    if found:
                        meta["files_with_matches"].append(filename)
            else:
                meta["files_missing"].append(filename)

    else:
        # Local path
        path = Path(source)
        if not path.exists():
            raise ValueError(f"Path not found: {source}")
        meta["path"] = str(path.resolve())

        for filename in DEPENDENCY_FILES:
            fpath = path / filename
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                meta["files_found"].append(filename)
                if filename in PARSERS:
                    found = PARSERS[filename](content)
                    deps.extend(found)
                    if found:
                        meta["files_with_matches"].append(filename)
            else:
                meta["files_missing"].append(filename)

    # Deduplicate by eol_product (keep first seen)
    seen = {}
    deduped = []
    for d in deps:
        if d["eol_product"] not in seen:
            seen[d["eol_product"]] = True
            deduped.append(d)

    return deduped, meta
