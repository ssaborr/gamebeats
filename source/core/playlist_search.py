"""
playlist_search.py — find Spotify playlists by search query (from game tags).

Uses a rendered Spotify search page (no Premium Web API) and validates each
playlist with an HTTP 200 check before use.
"""

import json
import os
import re
import time
import urllib.parse
import random
import requests

try:
    # Use the resolver that simulates desktop behaviour (playlist -> track page -> final track)
    from core.playlist_scraper import resolve_final_track_uri_from_playlist as _scrape_first_track
    HAS_PLAYWRIGHT_SCRAPER = True
except Exception:
    _scrape_first_track = None
    HAS_PLAYWRIGHT_SCRAPER = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

JINA_SEARCH_PREFIX = "https://r.jina.ai/https://open.spotify.com/search/"
JINA_PLAYLIST_PREFIX = "https://r.jina.ai/https://open.spotify.com/playlist/"
CACHE_TTL_SEC = 24 * 3600
DEFAULT_TOP_PLAYLIST_PICKS = 5
MAX_TOP_PLAYLIST_PICKS = 20
TOP_PLAYLIST_PICKS = DEFAULT_TOP_PLAYLIST_PICKS
MAX_VALIDATE_IDS = MAX_TOP_PLAYLIST_PICKS


def _clean_game_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9 ]", " ", (name or "").strip()).strip()


def _clean_tag_text(tag: str) -> str:
    if not tag or str(tag).startswith("_"):
        return ""
    clean = re.sub(r"[^a-zA-Z0-9 ]", " ", str(tag)).strip()
    return " ".join(clean.split())


def _extract_tag_list(tags: list) -> list:
    """Steam API tags or user-visible tags only (not internal _custom_query)."""
    out = []
    seen = set()
    for tag in tags or []:
        clean = _clean_tag_text(tag)
        if len(clean) < 2:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _custom_query_from_tags(tags: list) -> str:
    for tag in tags or []:
        if str(tag).startswith("_custom_query:"):
            return str(tag)[len("_custom_query:"):].strip()
    return ""


def _mood_extra_words(query_hint: str, max_words: int = 2) -> list:
    """A few genre words from mood — only when tags are thin."""
    skip = {
        "gaming", "music", "playlist", "beats", "study", "the", "and", "for",
        "relaxed", "concentration", "atmospheric", "instrumental", "peaceful",
    }
    out = []
    for word in (query_hint or "").split():
        wl = word.lower()
        if wl in skip or len(wl) < 3:
            continue
        if wl not in {w.lower() for w in out}:
            out.append(word)
        if len(out) >= max_words:
            break
    return out


def build_search_query(game_name: str = "", tags: list = None, query_hint: str = "") -> str:
    """
    Spotify search query: game name first, then Steam/user tags (always).
    Optional text from the user's search box is extra words only — never replaces tags.
    """
    tags = tags or []
    name = _clean_game_name(game_name)
    tag_parts = _extract_tag_list(tags)
    custom = _custom_query_from_tags(tags)

    parts = []
    if name:
        parts.append(name)

    for tag in tag_parts[:8]:
        if tag.lower() not in {p.lower() for p in parts}:
            parts.append(tag)

    if custom:
        custom_clean = re.sub(r"[^a-zA-Z0-9 ]", " ", custom).strip()
        for word in custom_clean.split():
            wl = word.lower()
            if len(word) < 2 or wl in {p.lower() for p in parts}:
                continue
            if wl == name.lower():
                continue
            parts.append(word)

    # The mood hint must actually influence the search.  Previously it was
    # only used when the game name + tags produced fewer than three words,
    # which meant a user-picked mood was silently ignored for almost every
    # Steam game (they always have tags).
    if query_hint:
        for word in _mood_extra_words(query_hint, max_words=3):
            if word.lower() not in {p.lower() for p in parts}:
                parts.append(word)

    if not parts:
        return f"{name or 'gaming'} music playlist".strip()
    return " ".join(parts[:12])


def _cache_path(data_dir: str) -> str:
    return os.path.join(data_dir, "playlist_search_cache.json")


def _blocked_path(data_dir: str) -> str:
    return os.path.join(data_dir, "blocked_playlists.json")


def _normalize_pick_count(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_TOP_PLAYLIST_PICKS
    return max(1, min(MAX_TOP_PLAYLIST_PICKS, value))


def _normalize_playlist_uri(uri: str) -> str:
    uri = (uri or "").strip()
    if uri.startswith("https://open.spotify.com/playlist/"):
        match = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{20,24})", uri)
        if match:
            uri = f"spotify:playlist:{match.group(1)}"
    if not uri.startswith("spotify:playlist:"):
        return ""
    pid = uri.split(":")[-1]
    return uri if _is_plausible_playlist_id(pid) else ""


def load_blocked_playlists(data_dir: str = "") -> list:
    if not data_dir:
        return []
    try:
        with open(_blocked_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("playlists", [])
    if not isinstance(data, list):
        return []
    out = []
    seen = set()
    for item in data:
        if isinstance(item, str):
            uri = _normalize_playlist_uri(item)
            record = {"uri": uri}
        elif isinstance(item, dict):
            uri = _normalize_playlist_uri(item.get("uri", ""))
            record = dict(item)
            record["uri"] = uri
        else:
            continue
        if uri and uri not in seen:
            seen.add(uri)
            out.append(record)
    return out


def load_blocked_playlist_uris(data_dir: str = "") -> set:
    return {p["uri"] for p in load_blocked_playlists(data_dir) if p.get("uri")}


def save_blocked_playlists(data_dir: str, playlists: list):
    if not data_dir:
        return
    try:
        with open(_blocked_path(data_dir), "w", encoding="utf-8") as f:
            json.dump({"playlists": playlists}, f, indent=2)
    except Exception:
        pass


def block_playlist_uri(data_dir: str, uri: str, name: str = "", query: str = "") -> bool:
    uri = _normalize_playlist_uri(uri)
    if not data_dir or not uri:
        return False
    playlists = load_blocked_playlists(data_dir)
    for item in playlists:
        if item.get("uri") == uri:
            item["name"] = name or item.get("name", "")
            item["query"] = query or item.get("query", "")
            item["blocked_at"] = item.get("blocked_at", int(time.time()))
            save_blocked_playlists(data_dir, playlists)
            return True
    playlists.append({
        "uri": uri,
        "name": name or uri.split(":")[-1],
        "query": query or "",
        "blocked_at": int(time.time()),
    })
    save_blocked_playlists(data_dir, playlists)
    return True


def unblock_playlist_uri(data_dir: str, uri: str) -> bool:
    uri = _normalize_playlist_uri(uri)
    if not data_dir or not uri:
        return False
    playlists = load_blocked_playlists(data_dir)
    kept = [p for p in playlists if p.get("uri") != uri]
    if len(kept) == len(playlists):
        return False
    save_blocked_playlists(data_dir, kept)
    return True


def clear_playlist_cache(data_dir: str = ""):
    """Remove cached search results so the next play uses a fresh search."""
    if not data_dir:
        return
    try:
        os.remove(_cache_path(data_dir))
    except OSError:
        pass


def clear_playlist_cache_for_query(data_dir: str, query: str):
    """Remove a single cache entry so the next search re-fetches that query."""
    if not data_dir or not query:
        return
    try:
        cache = _load_cache(data_dir)
        key = query.lower()
        if key in cache:
            del cache[key]
            _save_cache(data_dir, cache)
    except Exception:
        pass


def _load_cache(data_dir: str) -> dict:
    try:
        with open(_cache_path(data_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data_dir: str, cache: dict):
    try:
        with open(_cache_path(data_dir), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _is_plausible_playlist_id(playlist_id: str) -> bool:
    return bool(playlist_id) and 20 <= len(playlist_id) <= 24 and playlist_id.isalnum()


def _extract_playlist_info(text: str) -> list:
    """Extract IDs and names from Jina-rendered Spotify search/playlist pages."""
    # Pattern for Jina Markdown links: [Name](https://open.spotify.com/playlist/ID)
    md_pattern = r"\[([^\]\n]+)\]\(https://open\.spotify\.com/playlist/([a-zA-Z0-9]{22})\)"
    
    seen, out = set(), []
    for name, pid in re.findall(md_pattern, text):
        if _is_plausible_playlist_id(pid) and pid not in seen:
            seen.add(pid)
            # Remove Markdown escape backslashes if present
            clean_name = name.strip().replace('\\', '')
            # Avoid names that are just generic UI text
            if clean_name.lower() not in ("playlist", "spotify", "search", "open"):
                out.append({"id": pid, "name": clean_name})
            
    # Secondary attempt for names that are not in brackets (e.g. plain text lists)
    # Pattern: Title - URL or Title: URL
    backup_pattern = r"(?m)^([^-\n\t]{3,60})\s*[-:]\s*https?://open\.spotify\.com/playlist/([a-zA-Z0-9]{22})"
    for name, pid in re.findall(backup_pattern, text):
        if _is_plausible_playlist_id(pid) and pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "name": name.strip()})

    # Fallback for plain IDs (less descriptive)
    plain_patterns = (
        r"open\.spotify\.com/playlist/([a-zA-Z0-9]{22})",
        r"spotify:playlist:([a-zA-Z0-9]{22})",
    )
    for pat in plain_patterns:
        for pid in re.findall(pat, text, re.IGNORECASE):
            if _is_plausible_playlist_id(pid) and pid not in seen:
                seen.add(pid)
                out.append({"id": pid, "name": ""})
    return out


def validate_playlist_id(playlist_id: str) -> bool:
    """True if playlist exists (HTTP only — never opens a browser)."""
    if not _is_plausible_playlist_id(playlist_id):
        return False
    try:
        r = requests.get(
            f"{JINA_PLAYLIST_PREFIX}{playlist_id}",
            headers={"Accept": "text/plain"},
            timeout=22,
        )
        if r.status_code == 200:
            low = r.text.lower()
            if playlist_id.lower() in low or "spotify" in low:
                return True
    except Exception:
        pass
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    for method in ("head", "get"):
        try:
            fn = requests.head if method == "head" else requests.get
            r = fn(url, headers=HEADERS, timeout=14, allow_redirects=True)
            if r.status_code == 200:
                return True
        except Exception:
            pass
    return False


def first_track_uri_from_playlist(playlist_id: str, logger=None) -> str:
    """
    Fetch the first track URI from a playlist page using the local Playwright scraper.

    This uses a headless browser capable of rendering dynamic React pages
    and extracts the first `spotify:track:` or `spotify:episode:` URI.
    """
    if not _is_plausible_playlist_id(playlist_id):
        return ""

    if HAS_PLAYWRIGHT_SCRAPER and _scrape_first_track:
        try:
            if logger:
                logger(f"DEBUG: Using Playwright scraper for {playlist_id}")
            uri = _scrape_first_track(playlist_id, logger=logger)
            if uri:
                return uri
            if logger:
                logger(f"DEBUG: Scraper returned no URI for {playlist_id}")
        except Exception as e:
            if logger:
                logger(f"DEBUG: Scraper exception for {playlist_id}: {e}")

    if logger:
        logger(f"DEBUG: Playwright scraper unavailable or failed for {playlist_id}; no fallback available.")
    return ""


def search_playlist_ids(query: str, max_results: int = TOP_PLAYLIST_PICKS) -> list:
    """
    Search Spotify playlists for a text query. Returns raw IDs (not validated).
    """
    q = (query or "").strip()
    if not q:
        return []

    urls = [
        f"{JINA_SEARCH_PREFIX}{urllib.parse.quote(q)}/playlists",
        f"{JINA_SEARCH_PREFIX}{urllib.parse.quote(q + ' playlist')}/playlists",
    ]
    for url in urls:
        for attempt in range(2):
            try:
                r = requests.get(
                    url,
                    headers={"Accept": "text/plain"},
                    timeout=12,
                )
                if r.status_code == 200:
                    info = _extract_playlist_info(r.text)
                    if info:
                        return info[:max_results]
                if r.status_code in (429, 503) and attempt == 0:
                    time.sleep(2)
                    continue
            except Exception:
                if attempt == 0:
                    time.sleep(1)
    return []


def find_valid_playlists(
    query: str,
    data_dir: str = "",
    max_results: int = TOP_PLAYLIST_PICKS,
    use_cache: bool = True,
    blocked_uris=None,
) -> list:
    """
    Search by query; validate only the first N Spotify results (most relevant).
    Returns up to max_results playlists in search order.
    """
    q = (query or "").strip()
    if not q:
        return []

    max_results = _normalize_pick_count(max_results)
    blocked = set(blocked_uris or [])
    if data_dir:
        blocked.update(load_blocked_playlist_uris(data_dir))

    cache_key = q.lower()
    if use_cache and data_dir:
        cache = _load_cache(data_dir)
        entry = cache.get(cache_key)
        if entry and time.time() - entry.get("ts", 0) < CACHE_TTL_SEC:
            cached = entry.get("playlists") or []
            if cached:
                unblocked = [p for p in cached if p.get("uri") not in blocked]
                if unblocked and (len(cached) >= max_results or len(unblocked) >= max_results):
                    return unblocked[:max_results]

    raw_results = search_playlist_ids(q, max_results=MAX_TOP_PLAYLIST_PICKS)
    # Filter out blocked playlists early — before building candidates — so they
    # never occupy a slot and are skipped as cheaply as possible.
    blocked_ids = {uri.split(":")[-1] for uri in blocked if uri}
    raw_results = [item for item in raw_results if item["id"] not in blocked_ids]

    candidates = []
    for item in raw_results[:MAX_TOP_PLAYLIST_PICKS]:
        pid = item["id"]
        name = item["name"]
        if not _is_plausible_playlist_id(pid):
            continue
        candidates.append({
            "id": pid,
            "uri": f"spotify:playlist:{pid}",
            "name": name or q[:60],
            "rank": len(candidates) + 1,
        })

    if use_cache and data_dir and candidates:
        cache = _load_cache(data_dir)
        cache[cache_key] = {"ts": time.time(), "playlists": candidates}
        _save_cache(data_dir, cache)

    return candidates[:max_results]


def pick_random_playlist_uri(
    game_name: str = "",
    tags: list = None,
    query_hint: str = "",
    data_dir: str = "",
    max_results: int = TOP_PLAYLIST_PICKS,
    blocked_uris=None,
    exclude_uris=None,
) -> dict:
    """
    Search with game name + tags, keep the top N Spotify results, pick one at random.
    """
    name = _clean_game_name(game_name)
    tag_parts = _extract_tag_list(tags)
    if not name and not tag_parts:
        return {"error": "No game name or tags for playlist search"}

    max_results = _normalize_pick_count(max_results)
    blocked = set(blocked_uris or [])
    blocked.update(exclude_uris or [])
    if data_dir:
        blocked.update(load_blocked_playlist_uris(data_dir))

    query = build_search_query(game_name, tags, query_hint)
    tried = [query]
    playlists = find_valid_playlists(
        query,
        data_dir=data_dir,
        max_results=max_results,
        use_cache=True,
        blocked_uris=blocked,
    )

    if not playlists and name:
        q2 = f"{name} playlist"
        playlists = find_valid_playlists(
                q2,
                data_dir=data_dir,
                max_results=max_results,
                use_cache=True,
                blocked_uris=blocked,
            )

    if not playlists and name:
        q3 = f"{name} soundtrack playlist"
        if q3.lower() not in {t.lower() for t in tried}:
            tried.append(q3)
            playlists = find_valid_playlists(
                q3,
                data_dir=data_dir,
                max_results=max_results,
                use_cache=True,
                blocked_uris=blocked,
            )

    if not playlists:
        return {"error": f"No playlists for: {tried[0][:50]}"}

    top = playlists[:max_results]
    pick = random.choice(top)
    return {
        "uri": pick["uri"],
        "name": pick.get("name", query),
        "query": query,
        "pick_rank": pick.get("rank", 0),
        "top_count": len(top),
        "pool": top,
    }
