"""
detector.py — hybrid game registry + process scanner.

Priority:
  1. User-added games (games.json) — full control
  2. Built-in game database — fallback for known titles

Each user entry: { "proc_name": {"name": "...", "mood": "...", "exe_path": "...", "tags": [...]} }
"""

import psutil
import time
import threading
import json
import os

import sys as _sys

def _games_file_path() -> str:
    """Writable path for games.json — works frozen (PyInstaller) and in dev."""
    if getattr(_sys, "frozen", False):
        data_dir = os.path.join(os.path.dirname(_sys.executable), "data")
    else:
        data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "games.json")

GAMES_FILE = _games_file_path()

# ── Non-game processes — never shown in the running-processes picker ──────────
SKIP_PROCS = {
    "explorer.exe","svchost.exe","system","registry","smss.exe",
    "csrss.exe","winlogon.exe","services.exe","lsass.exe",
    "dwm.exe","wininit.exe","sihost.exe","ctfmon.exe",
    "chrome.exe","firefox.exe","msedge.exe","opera.exe","brave.exe",
    "code.exe","pycharm64.exe","idea64.exe","devenv.exe","sublime_text.exe",
    "discord.exe","slack.exe","teams.exe","zoom.exe","skype.exe",
    "spotify.exe","vlc.exe","wmplayer.exe","itunes.exe",
    "taskmgr.exe","regedit.exe","cmd.exe","powershell.exe",
    "steam.exe","steamwebhelper.exe","gameoverlayui.exe","steamservice.exe",
    "epicgameslauncher.exe","galaxyclient.exe","battlenet.exe","gog.exe",
    "nvidia share.exe","nvcontainer.exe","nvdisplay.container.exe","nvcplui.exe",
    "searchapp.exe","runtimebroker.exe","applicationframehost.exe",
    "python.exe","pythonw.exe","python3.exe",
    "conhost.exe","dllhost.exe","fontdrvhost.exe","lsaiso.exe",
    "antimalware service executable","msmpeng.exe","securityhealthservice.exe",
    "audiodg.exe","spoolsv.exe","wuauclt.exe","msiexec.exe",
    "gamebeats.exe","gamebeats",
}

# ── Mood → Spotify search mappings ───────────────────────────────────────────
MOOD_TO_PLAYLIST = {
    "intense":       {"name": "🔥 High Intensity",  "query": "high intensity gaming electronic",    "color": "#FF4444"},
    "energetic":     {"name": "⚡ Energetic Beats",  "query": "energetic upbeat electronic gaming",  "color": "#FF8C00"},
    "epic":          {"name": "🏰 Epic Orchestral",  "query": "epic orchestral cinematic gaming",    "color": "#9B59B6"},
    "dark_epic":     {"name": "⚔️  Dark & Epic",     "query": "dark epic orchestral souls",          "color": "#6C3483"},
    "metal":         {"name": "🤘 Heavy Metal",       "query": "heavy metal instrumental gaming",    "color": "#C0392B"},
    "synthwave":     {"name": "🌆 Synthwave",         "query": "synthwave retrowave neon cyberpunk", "color": "#E91E63"},
    "focus":         {"name": "🧠 Focus Flow",        "query": "focus instrumental concentration",   "color": "#2196F3"},
    "ambient_space": {"name": "🌌 Space Ambient",     "query": "space ambient atmospheric sci-fi",   "color": "#1A237E"},
    "chill":         {"name": "😌 Chill Vibes",       "query": "chill lofi relaxed gaming",          "color": "#4CAF50"},
    "lofi":          {"name": "☕ Lo-Fi Beats",       "query": "lofi hip hop chill beats study",     "color": "#795548"},
    "ambient":       {"name": "🍃 Ambient",            "query": "ambient atmospheric calm peaceful",  "color": "#00BCD4"},
    "horror":        {"name": "👻 Dark Ambient",       "query": "dark ambient horror atmospheric",    "color": "#37474F"},
    "electronic":    {"name": "🎛️  Electronic",       "query": "electronic dance edm racing",        "color": "#00E5FF"},
    "nordic":        {"name": "🪓 Nordic Folk",        "query": "nordic folk viking atmospheric",     "color": "#546E7A"},
    "tense":         {"name": "😰 Tense Thriller",     "query": "tense thriller suspense dark",       "color": "#D32F2F"},
    "hiphop":        {"name": "🎤 Hip Hop",            "query": "hip hop beats rap trap",             "color": "#FF6F00"},
}

MOODS = list(MOOD_TO_PLAYLIST.keys())

# ── Built-in fallback DB ──────────────────────────────────────────────────────
BUILTIN_DB = {
    "cs2.exe":            {"name": "Counter-Strike 2",  "mood": "intense"},
    "csgo.exe":           {"name": "CS:GO",              "mood": "intense"},
    "valorant.exe":       {"name": "Valorant",           "mood": "intense"},
    "r5apex.exe":         {"name": "Apex Legends",       "mood": "intense"},
    "overwatch.exe":      {"name": "Overwatch 2",        "mood": "energetic"},
    "doom.exe":           {"name": "DOOM",               "mood": "metal"},
    "doom_eternal.exe":   {"name": "DOOM Eternal",       "mood": "metal"},
    "witcher3.exe":       {"name": "The Witcher 3",      "mood": "epic"},
    "skyrim.exe":         {"name": "Skyrim",             "mood": "epic"},
    "skyrimse.exe":       {"name": "Skyrim SE",          "mood": "epic"},
    "elden_ring.exe":     {"name": "Elden Ring",         "mood": "dark_epic"},
    "sekiro.exe":         {"name": "Sekiro",             "mood": "dark_epic"},
    "ds3.exe":            {"name": "Dark Souls 3",       "mood": "dark_epic"},
    "baldursgate3.exe":   {"name": "Baldur's Gate 3",    "mood": "epic"},
    "cyberpunk2077.exe":  {"name": "Cyberpunk 2077",     "mood": "synthwave"},
    "civilization6.exe":  {"name": "Civilization VI",    "mood": "focus"},
    "civ6.exe":           {"name": "Civilization VI",    "mood": "focus"},
    "stellaris.exe":      {"name": "Stellaris",          "mood": "ambient_space"},
    "totalwar.exe":       {"name": "Total War",          "mood": "epic"},
    "minecraft.exe":      {"name": "Minecraft",          "mood": "chill"},
    "terraria.exe":       {"name": "Terraria",           "mood": "chill"},
    "valheim.exe":        {"name": "Valheim",            "mood": "nordic"},
    "rust.exe":           {"name": "Rust",               "mood": "tense"},
    "phasmophobia.exe":   {"name": "Phasmophobia",       "mood": "horror"},
    "lethalcompany.exe":  {"name": "Lethal Company",     "mood": "horror"},
    "forza.exe":          {"name": "Forza Horizon",      "mood": "electronic"},
    "f1_2023.exe":        {"name": "F1 2023",            "mood": "electronic"},
    "stardewvalley.exe":  {"name": "Stardew Valley",     "mood": "lofi"},
    "hollowknight.exe":   {"name": "Hollow Knight",      "mood": "ambient"},
    "hades.exe":          {"name": "Hades",              "mood": "intense"},
    "deeprockgalactic.exe": {"name": "Deep Rock Galactic","mood": "metal"},
    "rocketleague.exe":   {"name": "Rocket League",      "mood": "electronic"},
    "nba2k24.exe":        {"name": "NBA 2K24",           "mood": "hiphop"},
    "fc24.exe":           {"name": "EA FC 24",           "mood": "energetic"},
    "minecraft":          {"name": "Minecraft",          "mood": "chill"},
    "csgo":               {"name": "CS:GO",              "mood": "intense"},
}


# ── User game registry ────────────────────────────────────────────────────────

def load_games() -> dict:
    """Returns {proc_name_lower: {name, mood, exe_path, tags?}}"""
    try:
        with open(GAMES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_games(games: dict):
    with open(GAMES_FILE, "w") as f:
        json.dump(games, f, indent=2)


def add_game(proc_name: str, display_name: str, mood: str,
             exe_path: str = "", tags: list = None,
             spotify_playlist_uri: str = "", app_id: str = "") -> dict:
    """Add or update a game entry. Returns updated registry."""
    games = load_games()
    entry = {
        "name":     display_name,
        "mood":     mood,
        "exe_path": exe_path,
        "tags":     tags or [],
    }
    if spotify_playlist_uri:
        entry["spotify_playlist_uri"] = spotify_playlist_uri
    if app_id:
        entry["app_id"] = app_id
    games[proc_name.lower()] = entry
    save_games(games)
    return games


def remove_game(proc_name: str) -> dict:
    games = load_games()
    games.pop(proc_name.lower(), None)
    save_games(games)
    return games


# ── Process scanner ───────────────────────────────────────────────────────────

def get_running_processes() -> list:
    """Returns candidate game processes currently running."""
    seen, results = set(), []
    for proc in psutil.process_iter(["name", "pid", "exe"]):
        try:
            raw   = proc.info["name"] or ""
            pname = raw.lower().strip()
            if not pname or pname in SKIP_PROCS:
                continue
            exe = proc.info.get("exe") or ""
            if any(skip in exe.lower() for skip in [
                "\\windows\\", "\\windowsapps\\", "\\system32\\",
                "\\syswow64\\", "\\microsoft\\", "\\common files\\"
            ]):
                continue
            seen.add(pname)
            display = raw.replace(".exe","").replace("_"," ").replace("-"," ").title()
            results.append({
                "proc_name":    pname,
                "display_name": display,
                "pid":          proc.info["pid"],
                "exe_path":     exe,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(results, key=lambda x: x["display_name"].lower())


# ── Detector ──────────────────────────────────────────────────────────────────

def get_pid_for_proc(proc_name: str):
    """Return PID of a running process matching proc_name, or None."""
    target = proc_name.lower().strip()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info["name"] or "").lower().strip() == target:
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


class GameDetector:
    def __init__(self, on_game_found=None, on_game_lost=None, user_only=True):
        self.on_game_found = on_game_found
        self.on_game_lost  = on_game_lost
        self.user_only     = user_only
        self.current_game  = None
        self.running       = False
        self._thread       = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def scan_once(self):
        """Check processes against saved games (and optionally built-in DB)."""
        user_games = load_games()
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pname = (proc.info["name"] or "").lower().strip()
                if pname in user_games:
                    info = dict(user_games[pname])
                    info["proc"] = pname
                    info["pid"]  = proc.info["pid"]
                    info["source"] = "user"
                    return pname, info
                if not self.user_only and pname in BUILTIN_DB:
                    info = dict(BUILTIN_DB[pname])
                    info["proc"]   = pname
                    info["pid"]    = proc.info["pid"]
                    info["source"] = "builtin"
                    return pname, info
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None, None

    def _loop(self):
        while self.running:
            proc_name, game_info = self.scan_once()
            if game_info:
                if self.current_game != proc_name:
                    self.current_game = proc_name
                    if self.on_game_found:
                        self.on_game_found(game_info)
            else:
                if self.current_game:
                    self.current_game = None
                    if self.on_game_lost:
                        self.on_game_lost()
            time.sleep(3)

    def get_mood_info(self, mood):
        return MOOD_TO_PLAYLIST.get(mood, MOOD_TO_PLAYLIST["chill"])
