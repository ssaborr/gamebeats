"""
playlist_scraper.py — Direct Spotify playlist scraping using Playwright.

Bypasses Jina entirely. Uses headless browser to render the actual page
and extract track URIs from the DOM, avoiding CAPTCHA/incomplete load issues.
"""

import re
import time
import os
import json
import webbrowser

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def get_first_track_uri_from_playlist(playlist_id: str, logger=None) -> str:
    """
    Scrape Spotify playlist page directly using Playwright (headless browser).
    
    ROBUST EXTRACTION:
    1. Loads page headlessly
    2. Waits for track list to render
    3. Extracts track URIs from multiple possible DOM patterns
    4. Returns first track URI
    
    Returns: "spotify:track:ID" or "spotify:episode:ID" or ""
    """
    if not HAS_PLAYWRIGHT:
        if logger:
            logger("ERROR: Playwright not installed. Cannot scrape playlists.")
        return ""
    
    if not playlist_id or not (20 <= len(playlist_id) <= 24):
        return ""
    
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    
    try:
        if logger:
            logger(f"DEBUG: Opening Spotify playlist page (headless): {playlist_id[:8]}...")
        
        with sync_playwright() as p:
            # Launch browser headlessly
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                # Mimic a real browser to avoid detection
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                # Navigate to playlist page with timeout
                if logger:
                    logger(f"DEBUG: Loading page...")
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                
                # Wait for track list to render
                # Look for various selectors that indicate tracks are loaded
                try:
                    if logger:
                        logger(f"DEBUG: Waiting for track list to render...")
                    
                    # Wait for track table or track rows to appear
                    # Spotify uses multiple possible selectors depending on page state
                    page.wait_for_selector(
                        '[data-testid="tracklist-row"], .tracklist-row, [href*="/track/"], a[href*="spotify.com/track"], a[href*="spotify.com/episode"]',
                        timeout=15000
                    )
                    
                    if logger:
                        logger(f"DEBUG: Track list loaded")
                except PlaywrightTimeoutError:
                    if logger:
                        logger(f"DEBUG: Timeout waiting for track list, proceeding with page content anyway")
                
                # Wait for network idle to let React render
                try:
                    page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass

                # Wait for common track link selectors (including internal-track-link)
                try:
                    page.wait_for_selector('a[data-testid="internal-track-link"], [data-testid="tracklist-row"], a[href*="/track/"], a[href*="/episode/"]', timeout=15000)
                except Exception:
                    pass

                # Extract candidate URIs from the live DOM (handles dynamic React pages)
                try:
                    candidates = page.evaluate(r"""
                    () => {
                        const uris = [];
                        function pushFromHref(href){
                            try{
                                const full = href && href.startsWith('/') ? (location.origin + href) : href;
                                const m = (full || '').match(/spotify\.com\/(track|episode)\/([A-Za-z0-9]{22})/);
                                if(m) uris.push('spotify:' + m[1] + ':' + m[2]);
                            }catch(e){}
                        }

                        // Generic anchor hrefs
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.getAttribute('href') || '';
                            if(href && (href.includes('/track/') || href.includes('/episode/'))) pushFromHref(href);
                        });

                        // Specific test-id used in Spotify's DOM
                        document.querySelectorAll('a[data-testid^="internal-track"]').forEach(a=>{
                            const href = a.getAttribute('href') || '';
                            if(href) pushFromHref(href);
                        });

                        // Rows that contain track links
                        document.querySelectorAll('[data-testid="tracklist-row"]').forEach(row=>{
                            const a = row.querySelector('a[href*="/track/"]') || row.querySelector('a[href*="/episode/"]');
                            if(a) pushFromHref(a.getAttribute('href') || '');
                        });

                        // Also check for elements with data-uri attributes
                        document.querySelectorAll('[data-uri]').forEach(el=>{
                            const u = el.getAttribute('data-uri') || '';
                            if(u && (u.startsWith('spotify:track:') || u.startsWith('spotify:episode:'))) uris.push(u);
                        });

                        return Array.from(new Set(uris));
                    }
                    """)
                except Exception as e:
                    candidates = []
                    if logger:
                        logger(f"DEBUG: page.evaluate extraction failed: {e}")

                # Extract page HTML for fallback parsing and debugging
                try:
                    html = page.content()
                except Exception:
                    html = ""

                # Close browser
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

                # Save debug artifacts: HTML and extracted candidates
                try:
                    # Save to repo root (two levels up from this file) to make files easy to find
                    dbg_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
                    short = playlist_id[:8]
                    html_path = os.path.join(dbg_dir, f"_scraper_html_{short}.html")
                    tracks_path = os.path.join(dbg_dir, f"_scraper_tracks_{short}.json")
                    with open(html_path, 'w', encoding='utf-8') as fh:
                        fh.write(html or '')
                    with open(tracks_path, 'w', encoding='utf-8') as fh:
                        json.dump({"candidates": candidates, "playlist": playlist_id}, fh, indent=2)
                    if logger:
                        logger(f"DEBUG: Saved scraper HTML to {html_path} and candidates to {tracks_path}")
                except Exception as e:
                    if logger:
                        logger(f"DEBUG: Failed to save scraper debug files: {e}")

                if logger:
                    logger(f"DEBUG: Page loaded, {len(html)} characters. Candidate URIs found: {len(candidates)}")

                # Prefer candidates from DOM evaluation
                if candidates:
                    if logger:
                        logger(f"DEBUG: Found first candidate: {candidates[0]}")
                    return candidates[0]

                # ROBUST EXTRACTION: Fallback to regex/html parsing
                track_uri = _extract_track_uri_from_html(html, logger=logger)

                if track_uri:
                    if logger:
                        logger(f"DEBUG: Found first track via HTML parse: {track_uri[-22:]}")
                    return track_uri
                else:
                    if logger:
                        logger(f"DEBUG: No tracks found in page")
                    return ""
                    
            except Exception as e:
                if logger:
                    logger(f"DEBUG: Error during page load: {e}")
                context.close()
                browser.close()
                return ""
    
    except Exception as e:
        if logger:
            logger(f"DEBUG: Exception in playlist scraper: {e}")
        return ""


def _extract_track_uri_from_html(html: str, logger=None) -> str:
    """
    Extract first track URI from Spotify playlist HTML.
    
    Tries multiple extraction patterns to handle different page layouts.
    """
    if not html:
        return ""
    
    # PATTERN 1: Direct Spotify URIs in href or data attributes
    # Pattern: href="/track/XXXXXXXXXXXXXXXXXXXXXXXX" or href="/episode/..."
    uri_pattern = r'(?:href="|data-uri="|spotify:)(track|episode)[/:]([a-zA-Z0-9]{22})'
    matches = re.findall(uri_pattern, html)
    if matches:
        uri_type, track_id = matches[0]
        if logger:
            logger(f"DEBUG: Found via URI pattern: {uri_type}")
        return f"spotify:{uri_type}:{track_id}"
    
    # PATTERN 2: Full URLs to tracks/episodes
    # Pattern: https://open.spotify.com/track/XXXX or .../episode/XXXX
    url_pattern = r'https://open\.spotify\.com/(track|episode)/([a-zA-Z0-9]{22})'
    matches = re.findall(url_pattern, html)
    if matches:
        uri_type, track_id = matches[0]
        if logger:
            logger(f"DEBUG: Found via URL pattern: {uri_type}")
        return f"spotify:{uri_type}:{track_id}"
    
    # PATTERN 3: JSON data embedded in page
    # Spotify often embeds track data in JSON within the page
    json_pattern = r'"uri":"(spotify:(?:track|episode):[a-zA-Z0-9]{22})"'
    matches = re.findall(json_pattern, html)
    if matches:
        uri = matches[0]
        if logger:
            logger(f"DEBUG: Found via JSON pattern")
        return uri
    
    # PATTERN 4: Data attributes with IDs
    # Pattern: data-testid="tracklist-row" contains track ID somewhere
    row_pattern = r'<a[^>]*href=["\']?/track/([a-zA-Z0-9]{22})'
    matches = re.findall(row_pattern, html)
    if matches:
        track_id = matches[0]
        if logger:
            logger(f"DEBUG: Found via row pattern")
        return f"spotify:track:{track_id}"
    
    # PATTERN 5: Look for Spotify track IDs in any link (even if not ideal)
    # This is a fallback - captures any 22-char alphanumeric after /track/ or /episode/
    any_pattern = r'/(track|episode)/([a-zA-Z0-9]{22})'
    matches = re.findall(any_pattern, html)
    if matches:
        # Filter out false positives (e.g., image IDs)
        for uri_type, track_id in matches:
            if uri_type in ("track", "episode"):
                if logger:
                    logger(f"DEBUG: Found via fallback pattern: {uri_type}")
                return f"spotify:{uri_type}:{track_id}"
    
    if logger:
        logger(f"DEBUG: No track URIs found in HTML with any pattern")
    return ""


def extract_first_track_from_html(html: str, logger=None) -> str:
    """
    Public wrapper to extract the first playable Spotify URI from raw HTML.

    This function is intended for when you already have the page HTML
    (for example, you saved it locally or received it from a remote
    fetch). It uses the same robust extraction heuristics as the
    headless scraper but does not launch a browser.
    """
    return _extract_track_uri_from_html(html, logger=logger)


def play_first_track_from_playlist(playlist_id: str, logger=None) -> bool:
    """
    Scrape the playlist for the first track URI and attempt to open it in Spotify.

    Returns True if a launch was attempted, False otherwise.
    """
    # First, resolve the final track URI by simulating the desktop client's
    # behaviour in the web: get playlist's first track, open that track page,
    # then extract the first visible track on that page. This yields the
    # track that the desktop client will show/play first for this playlist.
    uri = resolve_final_track_uri_from_playlist(playlist_id, logger=logger)
    if not uri:
        if logger:
            logger(f"DEBUG: No track URI found for playlist {playlist_id}")
        return False

    try:
        # First open the playlist URI so the desktop client shows the playlist context,
        # then open the specific track URI so playback starts for that track.
        playlist_uri = f"spotify:playlist:{playlist_id}"
        # Launch playlist first
        try:
            if os.name == 'nt':
                os.startfile(playlist_uri)
            else:
                webbrowser.open(playlist_uri)
        except Exception:
            # Ignore playlist open errors and still attempt track open
            if logger:
                logger(f"DEBUG: Could not open playlist URI {playlist_uri}")

        # Small delay to give the desktop client time to switch context
        try:
            time.sleep(0.8)
        except Exception:
            pass

        # Now attempt to open the specific track URI
        if os.name == 'nt':
            try:
                os.startfile(uri)
            except Exception:
                # Fallback to webbrowser
                webbrowser.open(uri)
        else:
            try:
                webbrowser.open(uri)
            except Exception:
                parts = uri.split(':')
                if len(parts) >= 3:
                    webbrowser.open(f"https://open.spotify.com/{parts[1]}/{parts[2]}")

        if logger:
            logger(f"DEBUG: Launched Spotify playlist {playlist_id} and track {uri}")
        return True
    except Exception as e:
        if logger:
            logger(f"DEBUG: Failed to launch Spotify URI {uri}: {e}")
        return False


def resolve_final_track_uri_from_playlist(playlist_id: str, logger=None) -> str:
    """
    Given a playlist id, simulate the desktop client's behaviour via scraping:
    1. Scrape the playlist page to find its first track URI (A)
    2. Open the web page for track A and extract the first visible track URI there (B)
    3. Return B if found, otherwise fall back to A.

    This uses Playwright when available and falls back to the HTML regex parser.
    """
    # Step 1: get playlist first track (A)
    first_uri = get_first_track_uri_from_playlist(playlist_id, logger=logger)
    if not first_uri:
        return ""

    # Extract track id from spotify:track:ID or spotify:episode:ID
    m = re.match(r"spotify:(track|episode):([A-Za-z0-9]{22})", first_uri)
    if not m:
        return first_uri
    track_id = m.group(2)

    # Build track page url
    track_url = f"https://open.spotify.com/track/{track_id}"

    # If Playwright available, render the track page and try to extract a
    # first visible track link from the live DOM (this simulates desktop UI).
    if HAS_PLAYWRIGHT:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                page = context.new_page()
                try:
                    page.goto(track_url, wait_until="domcontentloaded", timeout=30000)
                    # Wait for any track link to appear
                    try:
                        page.wait_for_selector('a[data-testid="internal-track-link"][href*="/track/"]', timeout=8000)
                    except Exception:
                        pass

                    # Evaluate the DOM to find the first track href shown on the page
                    candidates = page.evaluate(r"""
                    () => {
                        const uris = [];
                        function pushFromHref(href){
                            try{
                                const full = href && href.startsWith('/') ? (location.origin + href) : href;
                                const m = (full || '').match(/spotify\.com\/(track|episode)\/([A-Za-z0-9]{22})/);
                                if(m) uris.push('spotify:' + m[1] + ':' + m[2]);
                            }catch(e){}
                        }

                        // Primary: internal track links visible on page
                        document.querySelectorAll('a[data-testid="internal-track-link"][href*="/track/"]').forEach(a=>{
                            const href = a.getAttribute('href') || '';
                            if(href) pushFromHref(href);
                        });

                        // Fallback: any anchor to a track
                        if(uris.length === 0){
                            document.querySelectorAll('a[href]').forEach(a=>{
                                const href = a.getAttribute('href') || '';
                                if(href && (href.includes('/track/') || href.includes('/episode/'))) pushFromHref(href);
                            });
                        }

                        return Array.from(new Set(uris));
                    }
                    """)

                except Exception as e:
                    candidates = []
                    if logger:
                        logger(f"DEBUG: Error loading track page {track_id}: {e}")

                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

                if candidates:
                    if logger:
                        logger(f"DEBUG: Resolved final track(s) from track page: {candidates}")
                    # Prefer the first candidate
                    return candidates[0]
        except Exception as e:
            if logger:
                logger(f"DEBUG: Playwright resolution failed for track page {track_id}: {e}")

    # Fallback: try to fetch minimal HTML via requests (non-JS) and parse
    try:
        import requests
        r = requests.get(track_url, headers={"User-Agent": HEADERS.get("User-Agent", "Mozilla/5.0")}, timeout=10)
        if r.status_code == 200 and r.text:
            # Use existing HTML extractor on the track page HTML
            final = _extract_track_uri_from_html(r.text, logger=logger)
            if final:
                if logger:
                    logger(f"DEBUG: Resolved final track via HTML fallback: {final}")
                return final
    except Exception:
        pass

    # Nothing extra found; return original first_uri
    return first_uri


def inspect_track_resolved_playlist(track_id_or_url: str, page=None, context=None, storage_state: str = None, logger=None) -> dict:
    """
    Given a track id or full track URL, navigate the track page in the
    provided Playwright `page` (or create one) and observe whether Spotify
    resolves the track to a playlist/album context. If a context is found,
    navigate to that context (same page) and extract the first track info.

    Returns a dict:
      {
        "input_track_uri": "spotify:track:...",
        "resolved_context_uri": "spotify:playlist:..." or "spotify:album:..." or "",
        "first_track": {"uri":..., "title":..., "artist":...} or None
      }

    This function purposely keeps everything in the same browser session
    (reuses `page`/`context` if provided). It does NOT play anything.
    """
    if not HAS_PLAYWRIGHT:
        if logger:
            logger("Playwright not installed")
        return {"input_track_uri": "", "resolved_context_uri": "", "first_track": None}

    # Normalize input to URL and a spotify:track:... URI
    track_id = None
    if track_id_or_url.startswith("spotify:"):
        m = re.match(r"spotify:(?:track|episode):([A-Za-z0-9]{22})", track_id_or_url)
        if m:
            track_id = m.group(1)
            track_url = f"https://open.spotify.com/track/{track_id}"
        else:
            return {"input_track_uri": track_id_or_url, "resolved_context_uri": "", "first_track": None}
    elif track_id_or_url.startswith("http"):
        track_url = track_id_or_url
        m = re.search(r"/track/([A-Za-z0-9]{22})", track_url)
        track_id = m.group(1) if m else None
    else:
        # assume bare id
        if 20 <= len(track_id_or_url) <= 24:
            track_id = track_id_or_url
            track_url = f"https://open.spotify.com/track/{track_id}"
        else:
            return {"input_track_uri": track_id_or_url, "resolved_context_uri": "", "first_track": None}

    created_browser = False
    browser = None
    created_context = False
    try:
        if page is None:
            # create browser/context/page
            pw = sync_playwright()
            p = pw.start()
            browser = p.chromium.launch(headless=True)
            ctx_args = {"user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            if storage_state:
                ctx_args["storage_state"] = storage_state
            context = browser.new_context(**ctx_args)
            page = context.new_page()
            created_browser = True
            created_context = True

        # Navigate to track page and wait for main content to stabilise
        try:
            page.goto(track_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            # still proceed to evaluate whatever loaded
            pass

        # Wait for likely selectors that indicate page rendered
        try:
            page.wait_for_selector('a[href*="/track/"]', timeout=12000)
        except Exception:
            try:
                page.wait_for_selector('[data-testid="internal-track-link"]', timeout=12000)
            except Exception:
                pass

        # Try to detect a canonical context link on the track page
        ctx = page.evaluate(r"""() => {
            try {
                const out = {context_type: null, href: null, name: null};
                const sel = ['a[href*="/playlist/"]', 'a[href*="/album/"]', 'a[data-testid*="context"]'];
                const anchors = Array.from(document.querySelectorAll(sel.join(',')));
                if (anchors.length) {
                    // prefer the first playlist link
                    let a = anchors.find(x=>x.href && x.href.includes('/playlist/')) || anchors[0];
                    out.href = a.href || null;
                    out.name = (a.textContent||'').trim() || null;
                    if (out.href && out.href.includes('/playlist/')) out.context_type = 'playlist';
                    else if (out.href && out.href.includes('/album/')) out.context_type = 'album';
                }
                return out;
            } catch(e) { return {context_type:null, href:null, name:null}; }
        }""")

        resolved_context_uri = ""
        first_track = None

        if ctx and ctx.get('href'):
            href = ctx.get('href')
            # Normalize to spotify:playlist:ID or spotify:album:ID
            m = re.search(r"/playlist/([A-Za-z0-9]{20,24})", href)
            if m:
                resolved_context_uri = f"spotify:playlist:{m.group(1)}"
                resolved_url = f"https://open.spotify.com/playlist/{m.group(1)}"
            else:
                m = re.search(r"/album/([A-Za-z0-9]{20,24})", href)
                if m:
                    resolved_context_uri = f"spotify:album:{m.group(1)}"
                    resolved_url = f"https://open.spotify.com/album/{m.group(1)}"
                else:
                    resolved_url = href

            # Navigate to the resolved context in the same page and extract first track
            try:
                page.goto(resolved_url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass

            # Wait for track list to render
            try:
                page.wait_for_selector('[data-testid="tracklist-row"], a[href*="/track/"], a[data-testid^="internal-track"]', timeout=15000)
            except Exception:
                pass

            # Extract first track info from the page DOM
            try:
                first = page.evaluate(r"""() => {
                    function findFirst(){
                        // Prefer rows with data-testid
                        const rowSel = '[data-testid="tracklist-row"]';
                        const candidates = [];
                        if (document.querySelectorAll(rowSel).length) {
                            document.querySelectorAll(rowSel).forEach(row=>{
                                const a = row.querySelector('a[href*="/track/"]') || row.querySelector('a[href*="/episode/"]');
                                if (a){
                                    const href = a.getAttribute('href') || '';
                                    const m = href.match(/\/(track|episode)\/([A-Za-z0-9]{22})/);
                                    if (m){
                                        const uri = 'spotify:' + m[1] + ':' + m[2];
                                        const title = (row.querySelector('[data-testid="track-name"]') || a).textContent.trim();
                                        let artist = '';
                                        const art = row.querySelector('[data-testid="tracklist-row__artists"]') || row.querySelector('.artists') || row.querySelector('.tracklist-name') || row.querySelector('span');
                                        if (art) artist = art.textContent.trim();
                                        candidates.push({uri:uri, title:title, artist:artist});
                                    }
                                }
                            });
                            if (candidates.length) return candidates[0];
                        }

                        // Generic anchor fallback
                        const anchors = Array.from(document.querySelectorAll('a[href]'));
                        for (const a of anchors){
                            const href = a.getAttribute('href')||'';
                            const m = href.match(/\/(track|episode)\/([A-Za-z0-9]{22})/);
                            if (m){
                                const uri = 'spotify:' + m[1] + ':' + m[2];
                                const title = (a.textContent||'').trim();
                                return {uri:uri, title:title, artist:''};
                            }
                        }
                        return null;
                    }
                    try { return findFirst(); } catch(e){ return null; }
                """)
                if first:
                    first_track = first
            except Exception:
                first_track = None

        # If no resolved context found, still attempt to extract visible playlist/album on the track page
        if not resolved_context_uri:
            # Try to scrape any embedded playlist panel first track without navigating away
            try:
                first = page.evaluate(r"""() => {
                    try{
                        // Attempt to find any playlist-like container with track anchors
                        const panels = document.querySelectorAll('[data-testid="entity-carousel"] , [data-testid="related-entities"], [data-testid="context-items"]');
                        for (const panel of panels){
                            const a = panel.querySelector('a[href*="/track/"]');
                            if (a){
                                const href = a.getAttribute('href')||'';
                                const m = href.match(/\/(track|episode)\/([A-Za-z0-9]{22})/);
                                if (m) return {uri:'spotify:'+m[1]+':'+m[2], title: (a.textContent||'').trim(), artist: ''};
                            }
                        }
                    }catch(e){}
                    return null;
                """)
                if first:
                    first_track = first
            except Exception:
                pass

        return {
            "input_track_uri": f"spotify:track:{track_id}" if track_id else track_id_or_url,
            "resolved_context_uri": resolved_context_uri,
            "first_track": first_track,
        }

    except Exception as e:
        if logger:
            logger(f"inspect error: {e}")
        return {"input_track_uri": f"spotify:track:{track_id}" if track_id else track_id_or_url, "resolved_context_uri": "", "first_track": None}
    finally:
        # Only close if we created the browser/context
        try:
            if created_context and context:
                try:
                    context.close()
                except Exception:
                    pass
            if created_browser and browser:
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception:
            pass


def launch_desktop_with_resolved_playlist(track_uri: str, logger=None, storage_state: str = None) -> bool:
    """
    Given a `spotify:track:ID` or track URL that was previously picked,
    inspect the track page in headless Chromium to discover the playlist
    or album context Spotify shows for that track, extract the first
    visible track of that resolved context, then launch the desktop
    Spotify app with the resolved playlist and the resolved first track.

    This performs only browser scraping (no Web API) and then opens the
    desktop URIs via `os.startfile` / `webbrowser.open` so the desktop
    client receives the playlist context before the track URI.
    """
    if not track_uri:
        return False

    # Ensure we have a spotify:track:... form for input
    input_uri = track_uri
    if track_uri.startswith('http'):
        m = re.search(r"/track/([A-Za-z0-9]{22})", track_uri)
        if m:
            input_uri = f"spotify:track:{m.group(1)}"
    if track_uri.startswith('spotify:') and not track_uri.startswith('spotify:track:'):
        # normalize
        m = re.match(r"spotify:(?:track|episode):([A-Za-z0-9]{22})", track_uri)
        if m:
            input_uri = f"spotify:track:{m.group(1)}"

    try:
        # Use the inspector to learn the resolved context and first track
        info = inspect_track_resolved_playlist(input_uri, page=None, context=None, storage_state=storage_state, logger=logger)
        if not info:
            if logger:
                logger("No inspection info returned")
            return False

        resolved = info.get('resolved_context_uri') or ''
        first = info.get('first_track') or {}

        # If Spotify resolved to a playlist/album, open that context first
        if resolved and (resolved.startswith('spotify:playlist:') or resolved.startswith('spotify:album:')):
            try:
                # open playlist/album in desktop
                if os.name == 'nt':
                    os.startfile(resolved)
                else:
                    webbrowser.open(resolved)
            except Exception:
                try:
                    # fallback to web URL
                    parts = resolved.split(':')
                    if len(parts) >= 3:
                        web_url = f"https://open.spotify.com/{parts[1]}/{parts[2]}"
                        webbrowser.open(web_url)
                except Exception:
                    pass

            # Give the desktop client time to adopt the context
            time.sleep(1.0)

            # Now open the resolved first track (if found)
            track_to_open = (first.get('uri') if isinstance(first, dict) else None) or input_uri
            try:
                if os.name == 'nt':
                    os.startfile(track_to_open)
                else:
                    webbrowser.open(track_to_open)
                if logger:
                    logger(f"Launched desktop with context {resolved} and track {track_to_open}")
                return True
            except Exception as e:
                if logger:
                    logger(f"Failed to open track {track_to_open}: {e}")
                return False

        # No resolved playlist/album — fallback: open the original track URI
        try:
            if os.name == 'nt':
                os.startfile(input_uri)
            else:
                webbrowser.open(input_uri)
            if logger:
                logger(f"Launched desktop with track {input_uri} (no resolved context)")
            return True
        except Exception as e:
            if logger:
                logger(f"Failed to launch track {input_uri}: {e}")
            return False

    except Exception as e:
        if logger:
            logger(f"launch_desktop_with_resolved_playlist error: {e}")
        return False
