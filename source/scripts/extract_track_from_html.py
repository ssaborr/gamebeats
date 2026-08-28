#!/usr/bin/env python3
"""
Small CLI: read HTML from a file or stdin and print first Spotify track URI.
Usage:
  python source/scripts/extract_track_from_html.py path/to/playlist.html
  cat playlist.html | python source/scripts/extract_track_from_html.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.playlist_scraper import extract_first_track_from_html


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, encoding='utf-8') as f:
            html = f.read()
    else:
        html = sys.stdin.read()
    uri = extract_first_track_from_html(html, logger=print)
    if uri:
        print(uri)
        return 0
    print("")
    return 1

if __name__ == '__main__':
    raise SystemExit(main())
