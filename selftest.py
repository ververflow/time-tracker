"""End-to-end self-test for the time tracker.
Run:  python selftest.py
Tests offline correctness (on a throwaway DB), the live running servers,
and the browser-extension files. Prints a PASS/FAIL report.
"""
import os
import io
import sys
import json
import time
import tempfile
import datetime
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

import core

REAL_DB = core.DB_PATH          # remember the real DB before we redirect
PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [FAIL] {name}  {detail}")


def http_get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def http_post(url, payload, timeout=5):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "text/plain"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


# ============================================================ 1. config files
print("\n1. Config & extension files")
try:
    cfg = core.load_config()
    check("config.json parses", isinstance(cfg, dict))
    check("config has tab_port", cfg.get("tab_port") == 7879)
except Exception as e:
    check("config.json parses", False, str(e))

try:
    rules = core.load_rules()
    check("rules.json parses", isinstance(rules, list) and len(rules) > 5)
    check("rules use url matching", any("url" in r for r in rules))
    check("rules end with catch-all",
          not rules[-1].get("app") and not rules[-1].get("title")
          and not rules[-1].get("url"))
except Exception as e:
    check("rules.json parses", False, str(e))

try:
    with open(os.path.join(core.BASE_DIR, "browser-extension", "manifest.json"),
              encoding="utf-8") as f:
        man = json.load(f)
    check("manifest.json parses", man.get("manifest_version") == 3)
    check("manifest has tabs+alarms perms",
          set(["tabs", "alarms"]).issubset(set(man.get("permissions", []))))
    check("manifest targets receiver port",
          any("7879" in h for h in man.get("host_permissions", [])))
    bg = os.path.join(core.BASE_DIR, "browser-extension", "background.js")
    check("background.js exists", os.path.exists(bg))
except Exception as e:
    check("manifest.json parses", False, str(e))


# ============================================================ 2. categorization
print("\n2. Categorization (app / title / url)")
# Always test against the public template rules.json, not the (gitignored) local override.
with open(os.path.join(core.BASE_DIR, "rules.json"), encoding="utf-8") as f:
    rules = json.load(f)
cat_cases = [
    (("Code.exe", "myproject - Visual Studio Code", ""), "Coding", "myproject"),
    (("msedge.exe", "Find Work", "https://www.upwork.com/x"), "Sales", "sales"),
    (("msedge.exe", "Home", "https://www.youtube.com/feed"), "Distraction", None),
    (("chrome.exe", "Inbox", "https://mail.google.com/"), "Email", None),
    (("chrome.exe", "x", "https://github.com/a/b"), "Coding", None),
    (("chrome.exe", "random blog", "https://example.com/"), "Browsing", None),
    (("weird.exe", "", ""), "Uncategorized", None),
]
for (a, t, u), exp_cat, exp_proj in cat_cases:
    cat, proj = core.categorize(a, t, u, rules)
    check(f"categorize {exp_cat:<12} ({u or t or a})",
          cat == exp_cat and proj == exp_proj, f"got {cat}/{proj}")

dom_cases = [("https://www.upwork.com/nx/find", "upwork.com"),
             ("https://mail.google.com/u/0", "mail.google.com"),
             ("", "")]
for u, exp in dom_cases:
    check(f"domain {exp or '(empty)'}", core.get_domain(u) == exp,
          f"got {core.get_domain(u)}")


# ============================================================ 3. offline pipeline
print("\n3. Dashboard pipeline (throwaway DB)")
import dashboard
tmp = os.path.join(tempfile.gettempdir(), "tt_selftest.db")
if os.path.exists(tmp):
    os.remove(tmp)
core.DB_PATH = tmp
conn = core.connect()
cols = [r[1] for r in conn.execute("PRAGMA table_info(samples)")]
check("schema has url column", "url" in cols)
INT = int(cfg.get("poll_interval_seconds", 10))


def seed(dt, app, title, url, idle, minutes):
    base = int(dt.timestamp())
    conn.executemany(
        "INSERT INTO samples (ts,app,title,url,idle) VALUES (?,?,?,?,?)",
        [(base + i * INT, app, title, url, idle) for i in range(minutes * 60 // INT)])


mid = datetime.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
seed(mid, "msedge.exe", "Find Work", "https://www.upwork.com/find-work", 0, 40)
seed(mid + datetime.timedelta(minutes=40), "msedge.exe", "Home", "https://www.youtube.com/feed", 0, 20)
seed(mid + datetime.timedelta(minutes=60), "Code.exe", "myproject - VS Code", "", 0, 50)
seed(mid + datetime.timedelta(minutes=110), "Code.exe", "idle", "", 1, 15)
# previous days for week view
for d in range(1, 4):
    seed(mid - datetime.timedelta(days=d), "Code.exe", "myproject - VS Code", "", 0, 90)
conn.commit()
conn.close()

s = dashboard.compute_stats("today")
check("focus seconds counted", s["focus_s"] == 90 * 60, f"{s['focus_s']}")
check("distraction counted", s["distraction_s"] == 20 * 60, f"{s['distraction_s']}")
check("break counted", s["break_s"] == 15 * 60, f"{s['break_s']}")
check("top domain = upwork.com",
      max(s["by_domain"], key=s["by_domain"].get) == "upwork.com")
check("sessions built", len(s["sessions"]) >= 4, f"{len(s['sessions'])}")
check("context switches computed", s["switches"] >= 2, f"{s['switches']}")
check("$/hour project tracked", "sales" in s["by_proj"])
check("insights generated", len(dashboard.generate_insights(s)) >= 3)

for r in ("today", "week", "all"):
    html = dashboard.render_html(r)
    check(f"render '{r}' ok", "Time Tracker" in html and len(html) > 1000)
check("'Waar je tijd heen ging' panel", "Waar je tijd heen ging" in dashboard.render_html("today"))
check("week-trend panel", "Deze week" in dashboard.render_html("today"))

csv_txt = dashboard.export_csv("today")
check("csv has site column", "site" in csv_txt.splitlines()[0])
check("csv has data rows", len(csv_txt.splitlines()) > 1)
os.remove(tmp)


# ============================================================ 4. url->sample path
print("\n4. URL gating (real tracker code)")
tmp2 = os.path.join(tempfile.gettempdir(), "tt_selftest2.db")
if os.path.exists(tmp2):
    os.remove(tmp2)
core.DB_PATH = tmp2
conn = core.connect()
import tracker
tracker.last_tab.update({"url": "https://www.upwork.com/find-work",
                         "title": "Find Work", "ts": time.time()})
url_browser = tracker.current_url("msedge.exe")     # browser + fresh -> url
url_other = tracker.current_url("Code.exe")          # non-browser -> ""
check("browser foreground gets url", url_browser.startswith("https://www.upwork.com"))
check("non-browser foreground gets no url", url_other == "")
tracker.last_tab["ts"] = time.time() - 9999
check("stale url is dropped", tracker.current_url("chrome.exe") == "")
# write through and read back categorized
conn.execute("INSERT INTO samples (ts,app,title,url,idle) VALUES (?,?,?,?,?)",
             (int(time.time()) - 30, "msedge.exe", "Find Work", url_browser, 0))
conn.commit()
conn.close()
s2 = dashboard.compute_stats("today")
check("url sample categorized as Sales", s2["by_cat"].get("Sales", 0) > 0)
os.remove(tmp2)
core.DB_PATH = REAL_DB  # restore


# ============================================================ 5. live system
print("\n5. Live running system")
# 5a. real DB is being written recently
try:
    conn = core.connect()
    total = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    recent = conn.execute(
        "SELECT COUNT(*) FROM samples WHERE ts >= ?",
        (int(time.time()) - 180,)).fetchone()[0]
    url_rows = conn.execute(
        "SELECT COUNT(*) FROM samples WHERE url IS NOT NULL AND url != ''"
    ).fetchone()[0]
    conn.close()
    check("real DB has samples", total > 0, f"total={total}")
    check("tracker writing in last 3 min", recent > 0,
          f"recent={recent} (is the tracker running?)")
    print(f"        (info) total={total}, recent={recent}, url-bearing rows={url_rows}")
except Exception as e:
    check("real DB readable", False, str(e))

# 5b. dashboard server
try:
    st, body = http_get("http://127.0.0.1:7878/")
    check("dashboard 200", st == 200)
    for panel in ("Focus", "Afleiding", "Waar je tijd heen ging", "Deze week"):
        check(f"dashboard shows '{panel}'", panel in body)
    st2, body2 = http_get("http://127.0.0.1:7878/?range=week")
    check("dashboard week view 200", st2 == 200 and "Deze week" in body2)
    st3, csv_body = http_get("http://127.0.0.1:7878/export.csv?range=today")
    check("csv export endpoint 200", st3 == 200 and "date,start,end" in csv_body)
except Exception as e:
    check("dashboard reachable", False, f"{e} (is the dashboard running?)")

# 5c. url receiver
try:
    st, body = http_post("http://127.0.0.1:7879/tab",
                         {"url": "https://www.upwork.com/selftest", "title": "t"})
    check("receiver accepts POST /tab", st == 200 and "ok" in body)
    st2, body2 = http_get("http://127.0.0.1:7879/")
    check("receiver alive (GET)", st2 == 200 and "tracker-up" in body2)
except Exception as e:
    check("receiver reachable", False, f"{e} (is the tracker running?)")


# ============================================================ report
print("\n" + "=" * 44)
print(f"  RESULT: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("  Failed: " + ", ".join(FAILURES))
print("=" * 44)
sys.exit(1 if FAIL else 0)
