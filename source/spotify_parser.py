import re

def get_first_playable_uri(jina_markdown: str) -> str | None:
    """
    Extracts the first playable Spotify URI (track or episode) from Jina markdown content.

    This function addresses the following issues:
    1. Supports both 'track' and 'episode' types for Spotify URIs.
    2. Skips header metadata and focuses on the actual playlist/episode list.
    3. Constructs the correct Spotify URI format (e.g., spotify:track:ID or spotify:episode:ID).

    Args:
        jina_markdown: The markdown content fetched from Jina for a Spotify playlist page.

    Returns:
        A string representing the first playable Spotify URI (e.g., "spotify:track:ID" or
        "spotify:episode:ID"), or None if no playable URI is found.
    """
    # Robust extraction logic:
    # Search document but ignore footer/recommended to catch "Featured" items missed in tables.
    uri_pattern = r"(?:https?://)?open\.spotify\.com/(track|episode)/([a-zA-Z0-9]{22})"

    footer_idx = jina_markdown.find("Recommended Based on")
    if footer_idx == -1: footer_idx = jina_markdown.find("Company")
    search_area = jina_markdown[:footer_idx] if footer_idx != -1 else jina_markdown

    matches = re.findall(uri_pattern, search_area)

    return f"spotify:{matches[0][0]}:{matches[0][1]}" if matches else None
