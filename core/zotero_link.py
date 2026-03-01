"""core/zotero_link.py — Fuzzy-match extracted citations against a Zotero library.

Supports three backends (tried in priority order):
1. Local Zotero app API  — http://localhost:23119/api/  (no key needed)
2. Exported BibTeX file  — path set via ZOTERO_BIBTEX env var
3. Zotero Web API        — requires ZOTERO_USER_ID + ZOTERO_API_KEY env vars

Each matched result includes a  zotero://  URI so the user can open it directly.
"""
import difflib
import json
import os
import re
from typing import Optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    """Case-insensitive SequenceMatcher ratio."""
    return difflib.SequenceMatcher(
        None, a.lower().strip(), b.lower().strip()
    ).ratio()


def _best_match(
    query: str,
    candidates: list[dict],
    key: str,
    threshold: float = 0.55,
) -> Optional[dict]:
    """Return the candidate with highest similarity above threshold."""
    best_score = threshold
    best       = None
    for c in candidates:
        score = _similarity(query, c.get(key, ""))
        if score > best_score:
            best_score = score
            best       = c
    if best:
        best = dict(best)
        best["match_score"] = round(best_score, 3)
    return best


def _zotero_uri(item_key: str, library_id: Optional[str] = None) -> str:
    """Build a zotero:// select URI."""
    if library_id:
        return f"zotero://select/library/items/{item_key}"
    return f"zotero://select/items/{item_key}"


# ── Backend 1: Local Zotero API ───────────────────────────────────────────────

def _fetch_local_zotero() -> list[dict]:
    """
    Fetch items from the local Zotero connector API (port 23119).
    Returns list of normalised item dicts.
    """
    try:
        import urllib.request
        url = "http://localhost:23119/api/items?format=json&limit=500"
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read())
        items = []
        for raw in data:
            d = raw.get("data", raw)
            items.append({
                "key":    d.get("key", ""),
                "title":  d.get("title", ""),
                "author": " ".join(
                    c.get("lastName", "") for c in d.get("creators", [])
                    if c.get("creatorType") in ("author", "editor")
                ),
                "year":   str(d.get("date", ""))[:4],
                "source": "local",
            })
        return items
    except Exception:
        return []


# ── Backend 2: BibTeX file ────────────────────────────────────────────────────

_BIBTEX_ENTRY_RE = re.compile(
    r"@\w+\{([^,]+),([^@]*)", re.DOTALL
)
_BIBTEX_FIELD_RE = re.compile(
    r"\b(\w+)\s*=\s*[{\"](.*?)[}\"]", re.DOTALL
)


def _parse_bibtex(path: str) -> list[dict]:
    """Minimal BibTeX parser — good enough for title/author/year extraction."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except FileNotFoundError:
        return []

    items = []
    for m in _BIBTEX_ENTRY_RE.finditer(content):
        key    = m.group(1).strip()
        fields = {k.lower(): v.strip() for k, v in _BIBTEX_FIELD_RE.findall(m.group(2))}
        items.append({
            "key":    key,
            "title":  fields.get("title", ""),
            "author": fields.get("author", "").split(" and ")[0],  # first author
            "year":   fields.get("year", ""),
            "source": "bibtex",
        })
    return items


# ── Backend 3: Zotero Web API ─────────────────────────────────────────────────

def _fetch_web_zotero(user_id: str, api_key: str) -> list[dict]:
    """Fetch up to 100 items from the Zotero Web API."""
    try:
        import urllib.request
        url = (
            f"https://api.zotero.org/users/{user_id}/items"
            f"?format=json&limit=100&key={api_key}"
        )
        req = urllib.request.Request(url, headers={"Zotero-API-Version": "3"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        items = []
        for raw in data:
            d = raw.get("data", raw)
            items.append({
                "key":    d.get("key", ""),
                "title":  d.get("title", ""),
                "author": " ".join(
                    c.get("lastName", "") for c in d.get("creators", [])
                    if c.get("creatorType") in ("author", "editor")
                ),
                "year":   str(d.get("date", ""))[:4],
                "source": "web",
            })
        return items
    except Exception:
        return []


# ── Public API ─────────────────────────────────────────────────────────────────

_cached_library: Optional[list[dict]] = None


def _load_library() -> list[dict]:
    """Load Zotero library from the first available backend."""
    global _cached_library
    if _cached_library is not None:
        return _cached_library

    # 1. Local app
    items = _fetch_local_zotero()
    if items:
        _cached_library = items
        print(f"  ✔ Zotero local API: {len(items)} items", flush=True)
        return items

    # 2. BibTeX file
    bibtex_path = os.getenv("ZOTERO_BIBTEX", "")
    if bibtex_path:
        items = _parse_bibtex(bibtex_path)
        if items:
            _cached_library = items
            print(f"  ✔ Zotero BibTeX ({bibtex_path}): {len(items)} items", flush=True)
            return items

    # 3. Web API
    user_id = os.getenv("ZOTERO_USER_ID", "")
    api_key  = os.getenv("ZOTERO_API_KEY", "")
    if user_id and api_key:
        items = _fetch_web_zotero(user_id, api_key)
        if items:
            _cached_library = items
            print(f"  ✔ Zotero Web API: {len(items)} items", flush=True)
            return items

    _cached_library = []
    print("  ⚠ Zotero: no backend available (local API / BibTeX / Web API)", flush=True)
    return []


def invalidate_cache() -> None:
    """Force reload of the Zotero library on next call."""
    global _cached_library
    _cached_library = None


def match_entities(entities: dict, threshold: float = 0.55) -> dict:
    """
    Fuzzy-match extracted citation entities against the Zotero library.

    For each entity in *books* and *authors*, if a sufficiently similar
    item is found the entity dict gains:
      - zotero_key   (str)  — item key
      - zotero_uri   (str)  — zotero://select/... deep-link
      - zotero_score (float)— match confidence 0–1
      - zotero_source (str) — "local" | "bibtex" | "web"

    Args:
        entities:  dict returned by citation_engine.extract_citations()
        threshold: minimum similarity score (0–1) to accept a match

    Returns:
        Mutated copy of entities with zotero_* fields added where matched.
    """
    library = _load_library()
    if not library:
        return entities

    result = {k: list(v) for k, v in entities.items()}

    # Match books by title
    for book in result.get("books", []):
        m = _best_match(book.get("title", ""), library, "title", threshold)
        if m:
            book["zotero_key"]    = m["key"]
            book["zotero_uri"]    = _zotero_uri(m["key"])
            book["zotero_score"]  = m["match_score"]
            book["zotero_source"] = m["source"]

    # Match authors by last name
    for author in result.get("authors", []):
        name = author.get("name", "")
        # Try matching against "author" field (last name first in BibTeX)
        m = _best_match(name, library, "author", threshold)
        if not m:
            # Also try matching against title (some Zotero items are by one author)
            m = _best_match(name, library, "title", threshold * 1.2)
        if m:
            author["zotero_key"]    = m["key"]
            author["zotero_uri"]    = _zotero_uri(m["key"])
            author["zotero_score"]  = m["match_score"]
            author["zotero_source"] = m["source"]

    return result


def match_single(query: str, entity_type: str = "title", threshold: float = 0.5) -> list[dict]:
    """
    Search the Zotero library for a single query string.

    Args:
        query:       Free-text query (title or author name).
        entity_type: "title" or "author".
        threshold:   Minimum similarity score.

    Returns:
        List of up to 5 matching library items (sorted by score desc),
        each including a zotero_uri.
    """
    library = _load_library()
    scored  = []
    for item in library:
        score = _similarity(query, item.get(entity_type, ""))
        if score >= threshold:
            scored.append({**item, "match_score": round(score, 3),
                           "zotero_uri": _zotero_uri(item["key"])})
    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:5]
