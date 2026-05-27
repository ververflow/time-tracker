"""Shared core for the local time tracker: paths, config, DB and Windows helpers."""
import os
import json
import sqlite3
import ctypes
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
RULES_PATH = os.path.join(BASE_DIR, "rules.json")
CONFIG_LOCAL_PATH = os.path.join(BASE_DIR, "config.local.json")
RULES_LOCAL_PATH = os.path.join(BASE_DIR, "rules.local.json")


# ---------------------------------------------------------------- config / rules
def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config():
    """Load config.json. If config.local.json exists, it overrides (gitignored)."""
    path = CONFIG_LOCAL_PATH if os.path.exists(CONFIG_LOCAL_PATH) else CONFIG_PATH
    return _load_json(path)


def load_rules():
    """Load rules.json. If rules.local.json exists, it overrides (gitignored)."""
    path = RULES_LOCAL_PATH if os.path.exists(RULES_LOCAL_PATH) else RULES_PATH
    return _load_json(path)


# ---------------------------------------------------------------- database
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS samples ("
        "ts INTEGER NOT NULL, app TEXT, title TEXT, url TEXT, idle INTEGER NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts)")
    # migrate older DBs that predate the url column
    cols = [r[1] for r in conn.execute("PRAGMA table_info(samples)")]
    if "url" not in cols:
        conn.execute("ALTER TABLE samples ADD COLUMN url TEXT")
    conn.commit()
    return conn


# ---------------------------------------------------------------- categorization
def categorize(app, title, url, rules):
    """Return (category, project) for an (app, title, url). First matching rule wins."""
    a = (app or "").lower()
    t = (title or "").lower()
    u = (url or "").lower()
    for rule in rules:
        apps = [p.lower() for p in rule.get("app", [])]
        titles = [p.lower() for p in rule.get("title", [])]
        urls = [p.lower() for p in rule.get("url", [])]
        if not apps and not titles and not urls:  # catch-all rule
            return rule.get("category", "Uncategorized"), rule.get("project")
        if (any(p in a for p in apps) or any(p in t for p in titles)
                or any(p in u for p in urls)):
            return rule.get("category", "Uncategorized"), rule.get("project")
    return "Uncategorized", None


def get_domain(url):
    """Bare domain from a URL, e.g. 'https://www.upwork.com/x' -> 'upwork.com'."""
    if not url:
        return ""
    from urllib.parse import urlparse
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


# ---------------------------------------------------------------- Windows helpers
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_idle_seconds():
    """Seconds since the last keyboard/mouse input (system-wide)."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def get_active_window():
    """Return (app_exe_name, window_title) for the foreground window."""
    import win32gui
    import win32process
    import psutil

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return "", ""
    title = win32gui.GetWindowText(hwnd) or ""
    app = ""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = psutil.Process(pid).name()
    except Exception:
        app = ""
    return app, title


# ---------------------------------------------------------------- formatting
def fmt_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    if m:
        return f"{m}m"
    return f"{seconds}s"
