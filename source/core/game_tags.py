"""
game_tags.py — fetch genre/mood tags for a game by name.

Uses Steam store pages (no API key). Falls back to name-based mood on failure.
"""

import re
import json
import urllib.parse

import requests

from core.detector import MOOD_TO_PLAYLIST

TAG_TO_MOOD = {
    "fps": "intense", "first-person shooter": "intense", "tactical shooter": "intense",
    "battle royale": "intense", "action": "energetic", "action-adventure": "energetic",
    "hack and slash": "intense", "fighting": "intense", "beat 'em up": "energetic",
    "rpg": "epic", "role-playing game": "epic", "open world": "epic",
    "adventure": "epic", "souls-like": "dark_epic", "dark fantasy": "dark_epic",
    "souls": "dark_epic", "fantasy": "epic", "medieval": "epic",
    "strategy": "focus", "turn-based strategy": "focus", "real-time strategy": "focus",
    "rts": "focus", "4x": "focus", "grand strategy": "focus",
    "city builder": "focus", "tower defense": "focus",
    "horror": "horror", "survival horror": "horror", "psychological horror": "horror",
    "dark": "horror", "survival": "tense", "sandbox": "chill", "crafting": "chill",
    "base building": "chill", "racing": "electronic", "sports": "energetic",
    "football": "energetic", "soccer": "energetic", "basketball": "hiphop",
    "indie": "chill", "casual": "lofi", "puzzle": "lofi", "platformer": "chill",
    "metroidvania": "ambient", "exploration": "ambient",
    "sci-fi": "ambient_space", "space": "ambient_space", "cyberpunk": "synthwave",
    "vikings": "nordic", "norse": "nordic", "viking": "nordic",
    "rhythm": "energetic", "music": "chill", "stealth": "tense", "thriller": "tense",
    "metal": "metal", "doom": "metal",
}

NAME_HINTS = [
    (r"football|soccer|fifa|efootball|nba|sport", "energetic"),
    (r"horror|phasmo|resident|evil|dead space", "horror"),
    (r"elden|souls|sekiro|dark souls|bloodborne", "dark_epic"),
    (r"witcher|skyrim|baldur|fantasy|rpg", "epic"),
    (r"civilization|civ|stellaris|strategy", "focus"),
    (r"cyberpunk|neon|synth", "synthwave"),
    (r"minecraft|stardew|terraria|chill", "chill"),
    (r"valorant|counter|csgo|cs2|apex|fps|shooter", "intense"),
    (r"forza|racing|f1|need for speed", "electronic"),
    (r"valheim|viking|norse", "nordic"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 8


def _fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def _extract_json_array(html: str, marker: str):
    idx = html.find(marker)
    if idx < 0:
        return None
    start = html.find("[", idx)
    if start < 0:
        return None
    depth = 0
    for i in range(start, min(start + 50000, len(html))):
        c = html[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _mood_from_name(game_name: str) -> str:
    name = game_name.lower()
    for pattern, mood in NAME_HINTS:
        if re.search(pattern, name):
            return mood
    return "chill"


def tags_to_mood(tags: list) -> str:
    for tag in tags:
        if tag in TAG_TO_MOOD:
            return TAG_TO_MOOD[tag]
    for tag in tags:
        for key, mood in TAG_TO_MOOD.items():
            if key in tag or tag in key:
                return mood
    return "chill"


def tags_to_spotify_query(game_name: str, tags: list) -> str:
    from core.playlist_search import build_search_query
    mood = tags_to_mood(tags) if tags else _mood_from_name(game_name)
    mood_hint = MOOD_TO_PLAYLIST.get(mood, {}).get("query", "")
    return build_search_query(game_name, tags, mood_hint)


def fallback_game_info(game_name: str) -> dict:
    mood = _mood_from_name(game_name)
    return {
        "app_id": "",
        "tags":   [],
        "mood":   mood,
        "query":  tags_to_spotify_query(game_name, []),
    }


def _steam_search(game_name: str):
    q = urllib.parse.quote(game_name)
    url = f"https://store.steampowered.com/search/?term={q}&category1=998"
    try:
        html = _fetch(url)
        m = re.search(r'data-ds-appid="(\d+)"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def _steam_tags(app_id: str):
    url = f"https://store.steampowered.com/app/{app_id}/"
    try:
        html = _fetch(url)
        tags_data = _extract_json_array(html, "InitAppTagModal(")
        if tags_data:
            return [t["name"].lower() for t in tags_data if isinstance(t, dict) and "name" in t]
        tags = re.findall(r'class="app_tag"[^>]*>\s*([^<]+?)\s*<', html)
        return [t.lower() for t in tags if t.strip()]
    except Exception:
        return []


def fetch_game_info(game_name: str) -> dict:
    """Always returns a dict (never None). Safe from background threads."""
    try:
        app_id = _steam_search(game_name)
        tags = _steam_tags(app_id) if app_id else []
        mood = tags_to_mood(tags) if tags else _mood_from_name(game_name)
        return {
            "app_id": app_id or "",
            "tags":   tags[:12],
            "mood":   mood,
            "query":  tags_to_spotify_query(game_name, tags),
        }
    except Exception:
        return fallback_game_info(game_name)
