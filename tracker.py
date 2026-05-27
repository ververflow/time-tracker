"""Background time tracker: samples the active window + idle state into SQLite,
shows a tray icon, and nudges you when you drift into distractions.

Run:  pythonw tracker.py   (no console window)
"""
import sys
import time
import json
import threading
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception as e:  # pragma: no cover
    print("Missing tray deps (pystray, Pillow):", e)
    sys.exit(1)

CFG = core.load_config()
RULES = core.load_rules()
INTERVAL = int(CFG.get("poll_interval_seconds", 10))
IDLE_THRESHOLD = int(CFG.get("idle_threshold_seconds", 120))
FOCUS = set(CFG.get("focus_categories", []))
DISTRACTION = set(CFG.get("distraction_categories", []))
PORT = int(CFG.get("dashboard_port", 7878))
TAB_PORT = int(CFG.get("tab_port", 7879))
TAB_FRESH = 120  # seconds a reported URL stays valid (extension heartbeats every 30s)
BROWSERS = {"chrome.exe", "msedge.exe", "brave.exe", "opera.exe",
            "vivaldi.exe", "firefox.exe"}

# latest active-tab URL pushed by the browser extension
last_tab = {"url": "", "title": "", "ts": 0.0}
tab_lock = threading.Lock()

# ---- shared state (read by the tray, written by the tracking loop)
state = {
    "running": True,
    "paused": False,
    "current_category": "—",
    "today_focus_s": 0,
    "distraction_streak_s": 0,
    "focus_streak_s": 0,
    "last_nudge": 0.0,
    "last_break_nudge": 0.0,
}
stop_event = threading.Event()


# ---------------------------------------------------------------- URL receiver
class _TabHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            with tab_lock:
                last_tab["url"] = data.get("url", "") or ""
                last_tab["title"] = data.get("title", "") or ""
                last_tab["ts"] = time.time()
        except Exception:
            pass
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b"tracker-up")

    def log_message(self, *args):
        pass


def start_tab_receiver():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", TAB_PORT), _TabHandler)
    except OSError:
        return  # already running
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def current_url(app):
    """The active-tab URL if the foreground app is a browser and it's fresh."""
    if not app or app.lower() not in BROWSERS:
        return ""
    with tab_lock:
        if time.time() - last_tab["ts"] <= TAB_FRESH:
            return last_tab["url"]
    return ""


# ---------------------------------------------------------------- tray icon art
COLORS = {
    "focus": (46, 204, 113),       # green
    "distraction": (231, 76, 60),  # red
    "neutral": (52, 152, 219),     # blue
    "idle": (149, 165, 166),       # grey
    "paused": (127, 140, 141),     # dark grey
}


def _bucket(category, idle):
    if state["paused"]:
        return "paused"
    if idle:
        return "idle"
    if category in FOCUS:
        return "focus"
    if category in DISTRACTION:
        return "distraction"
    return "neutral"


def make_icon_image(bucket):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=COLORS.get(bucket, COLORS["neutral"]))
    return img


# ---------------------------------------------------------------- today's focus
def compute_today_focus():
    import datetime
    conn = core.connect()
    midnight = int(datetime.datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())
    rows = conn.execute(
        "SELECT app, title, url, idle FROM samples WHERE ts >= ?", (midnight,)
    ).fetchall()
    conn.close()
    focus_s = 0
    for app, title, url, idle in rows:
        if idle:
            continue
        cat, _ = core.categorize(app, title, url, RULES)
        if cat in FOCUS:
            focus_s += INTERVAL
    return focus_s


# ---------------------------------------------------------------- tracking loop
def tracking_loop(icon):
    conn = core.connect()
    state["today_focus_s"] = compute_today_focus()
    while not stop_event.is_set():
        if state["paused"]:
            stop_event.wait(INTERVAL)
            continue

        idle = core.get_idle_seconds() >= IDLE_THRESHOLD
        app, title = core.get_active_window()
        url = current_url(app)
        conn.execute(
            "INSERT INTO samples (ts, app, title, url, idle) VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), app, title, url, 1 if idle else 0),
        )
        conn.commit()

        cat, _ = core.categorize(app, title, url, RULES)
        state["current_category"] = "Away" if idle else cat

        # accounting for tray + nudges
        if not idle and cat in FOCUS:
            state["today_focus_s"] += INTERVAL
        if not idle and cat in DISTRACTION:
            state["distraction_streak_s"] += INTERVAL
        else:
            state["distraction_streak_s"] = 0
        # continuous focus streak; a break (idle) resets it
        if idle:
            state["focus_streak_s"] = 0
        elif cat in FOCUS:
            state["focus_streak_s"] += INTERVAL

        _maybe_nudge(icon)
        _maybe_break_nudge(icon)

        # refresh tray
        b = _bucket(cat, idle)
        try:
            icon.icon = make_icon_image(b)
            icon.title = _tray_tooltip()
        except Exception:
            pass

        stop_event.wait(INTERVAL)
    conn.close()


def _tray_tooltip():
    if state["paused"]:
        return "Time Tracker — paused"
    return (f"{state['current_category']}  ·  "
            f"focus today: {core.fmt_duration(state['today_focus_s'])}")


def _maybe_nudge(icon):
    nudge = CFG.get("nudge", {})
    if not nudge.get("enabled", True):
        return
    limit_s = int(nudge.get("distraction_minutes", 10)) * 60
    cooldown_s = int(nudge.get("cooldown_minutes", 15)) * 60
    now = time.time()
    if (state["distraction_streak_s"] >= limit_s
            and now - state["last_nudge"] >= cooldown_s):
        state["last_nudge"] = now
        try:
            icon.notify(
                f"You've been distracted for "
                f"{core.fmt_duration(state['distraction_streak_s'])}. "
                f"Refocus — your hourly rate is watching. 👀",
                "Time Tracker",
            )
        except Exception:
            pass


def _maybe_break_nudge(icon):
    nudge = CFG.get("nudge", {})
    if not nudge.get("enabled", True):
        return
    after_s = int(nudge.get("break_after_minutes", 90)) * 60
    if after_s <= 0:
        return
    cooldown_s = int(nudge.get("cooldown_minutes", 15)) * 60
    now = time.time()
    if (state["focus_streak_s"] >= after_s
            and now - state["last_break_nudge"] >= cooldown_s):
        state["last_break_nudge"] = now
        try:
            icon.notify(
                f"You've focused for "
                f"{core.fmt_duration(state['focus_streak_s'])} straight. "
                f"Take a short break to stay sharp. ☕",
                "Time Tracker",
            )
        except Exception:
            pass


# ---------------------------------------------------------------- tray actions
def on_toggle_pause(icon, item):
    state["paused"] = not state["paused"]
    icon.icon = make_icon_image("paused" if state["paused"] else "neutral")
    icon.title = _tray_tooltip()


def on_open_dashboard(icon, item):
    # launch dashboard server (idempotent-ish) and open browser
    try:
        subprocess.Popen(
            [_pythonw(), "dashboard.py", "--serve"],
            cwd=core.BASE_DIR,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass
    time.sleep(1.0)
    webbrowser.open(f"http://localhost:{PORT}/")


def on_quit(icon, item):
    stop_event.set()
    icon.stop()


def _pythonw():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        return cand
    return exe


def is_paused(item):
    return state["paused"]


def main():
    icon = pystray.Icon(
        "time_tracker",
        icon=make_icon_image("neutral"),
        title="Time Tracker — starting…",
        menu=pystray.Menu(
            pystray.MenuItem(
                lambda item: ("Resume tracking" if state["paused"]
                              else "Pause tracking"),
                on_toggle_pause),
            pystray.MenuItem("Open dashboard", on_open_dashboard,
                             default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    start_tab_receiver()
    t = threading.Thread(target=tracking_loop, args=(icon,), daemon=True)
    t.start()
    icon.run()


if __name__ == "__main__":
    main()
