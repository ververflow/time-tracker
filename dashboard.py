"""Local dashboard + CLI report for the time tracker (Rize-style).

  python dashboard.py --serve     start the web dashboard (localhost)
  python dashboard.py --today     print today's summary to the terminal
  python dashboard.py --week      print this week's summary
"""
import sys
import csv
import io
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import core

CFG = core.load_config()
RULES = core.load_rules()
INTERVAL = int(CFG.get("poll_interval_seconds", 10))
FOCUS = set(CFG.get("focus_categories", []))
DISTRACTION = set(CFG.get("distraction_categories", []))
PORT = int(CFG.get("dashboard_port", 7878))
PROJECTS = CFG.get("projects", {})

# colour per category — drives the timeline + bars (Rize-like palette)
CAT_COLORS = {
    "Coding": "#2ecc71", "Email": "#27ae60", "Sales": "#16a085",
    "AI Tools": "#1abc9c", "Design": "#9b59b6", "Writing": "#3498db",
    "Meetings": "#e67e22", "Communities": "#f1c40f", "Browsing": "#5b6fb0",
    "Distraction": "#e74c3c", "Uncategorized": "#7f8c8d", "Break": "#3a414c",
}


def cat_color(cat):
    return CAT_COLORS.get(cat, "#5b6470")


def cls_of(category):
    if category in FOCUS:
        return "focus"
    if category in DISTRACTION:
        return "distraction"
    return "neutral"


# ---------------------------------------------------------------- time ranges
def range_bounds(name):
    """Return (start_ts, end_ts, label) as integer epoch seconds."""
    now = datetime.datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = int(now.timestamp())
    if name == "week":
        start = midnight - datetime.timedelta(days=now.weekday())
        return int(start.timestamp()), end, "This week"
    if name == "all":
        return 0, end, "All time"
    return int(midnight.timestamp()), end, "Today"


# ---------------------------------------------------------------- sessions
def build_sessions(rows):
    """Merge consecutive same-category samples into sessions.
    rows: list of (ts, app, title, idle) sorted by ts."""
    gap_tol = INTERVAL * 3
    sessions, cur = [], None
    for ts, app, title, url, idle in rows:
        if idle:
            cat, proj = "Break", None
        else:
            cat, proj = core.categorize(app, title, url, RULES)
        dom = core.get_domain(url)
        if (cur and cat == cur["category"] and proj == cur["project"]
                and ts - cur["end_ts"] <= gap_tol):
            cur["end_ts"] = ts + INTERVAL
            if app:
                cur["apps"][app] = cur["apps"].get(app, 0) + INTERVAL
            if dom:
                cur["domains"][dom] = cur["domains"].get(dom, 0) + INTERVAL
            cur["title"] = title or cur["title"]
        else:
            if cur:
                sessions.append(cur)
            cur = {"start_ts": ts, "end_ts": ts + INTERVAL, "category": cat,
                   "project": proj, "title": title or "",
                   "apps": {app: INTERVAL} if app else {},
                   "domains": {dom: INTERVAL} if dom else {}}
    if cur:
        sessions.append(cur)
    for s in sessions:
        s["duration"] = s["end_ts"] - s["start_ts"]
        s["top_app"] = max(s["apps"], key=s["apps"].get) if s["apps"] else ""
        s["top_domain"] = max(s["domains"], key=s["domains"].get) if s["domains"] else ""
    return sessions


# ---------------------------------------------------------------- stats
def compute_stats(name):
    start_ts, end_ts, label = range_bounds(name)
    conn = core.connect()
    rows = conn.execute(
        "SELECT ts, app, title, url, idle FROM samples WHERE ts >= ? AND ts < ? ORDER BY ts",
        (start_ts, end_ts),
    ).fetchall()
    conn.close()

    by_cat, by_app, by_proj, by_day, by_domain = {}, {}, {}, {}, {}
    by_hour = [0] * 24
    active_s = break_s = focus_s = distraction_s = 0

    for ts, app, title, url, idle in rows:
        if idle:
            break_s += INTERVAL
            by_cat["Break"] = by_cat.get("Break", 0) + INTERVAL
            continue
        active_s += INTERVAL
        cat, proj = core.categorize(app, title, url, RULES)
        by_cat[cat] = by_cat.get(cat, 0) + INTERVAL
        if app:
            by_app[app] = by_app.get(app, 0) + INTERVAL
        if proj:
            by_proj[proj] = by_proj.get(proj, 0) + INTERVAL
        dom = core.get_domain(url)
        if dom:
            by_domain[dom] = by_domain.get(dom, 0) + INTERVAL
        if cat in FOCUS:
            focus_s += INTERVAL
        elif cat in DISTRACTION:
            distraction_s += INTERVAL
        dt = datetime.datetime.fromtimestamp(ts)
        by_hour[dt.hour] += INTERVAL
        day = dt.strftime("%Y-%m-%d")
        d = by_day.setdefault(day, {"focus": 0, "distraction": 0, "other": 0})
        if cat in FOCUS:
            d["focus"] += INTERVAL
        elif cat in DISTRACTION:
            d["distraction"] += INTERVAL
        else:
            d["other"] += INTERVAL

    sessions = build_sessions(rows)
    active_sessions = [s for s in sessions if s["category"] != "Break"]
    switches = sum(1 for a, b in zip(active_sessions, active_sessions[1:])
                   if a["category"] != b["category"])
    focus_sessions = [s for s in sessions if s["category"] in FOCUS]
    longest = max(focus_sessions, key=lambda s: s["duration"], default=None)
    peak_hour = max(range(24), key=lambda h: by_hour[h]) if active_s else None

    return {
        "label": label, "range": name,
        "active_s": active_s, "break_s": break_s,
        "focus_s": focus_s, "distraction_s": distraction_s,
        "focus_pct": (100 * focus_s / active_s) if active_s else 0,
        "by_cat": by_cat, "by_app": by_app, "by_proj": by_proj,
        "by_hour": by_hour, "by_day": by_day, "by_domain": by_domain,
        "sessions": sessions, "switches": switches,
        "longest_focus": longest, "peak_hour": peak_hour,
    }


# ---------------------------------------------------------------- insights (mini coach)
def generate_insights(s):
    f = core.fmt_duration
    out = []
    if s["active_s"] == 0:
        return ["No activity tracked yet — the dot in your tray is collecting data."]
    out.append(f"You tracked {f(s['active_s'])}, {s['focus_pct']:.0f}% of it focused.")
    if s["peak_hour"] is not None:
        out.append(f"🔥 Most active around {s['peak_hour']:02d}:00 — protect that window.")
    if s["longest_focus"]:
        lf = s["longest_focus"]
        out.append(f"💪 Longest focus block: {f(lf['duration'])} on {lf['category']}.")
    if s["distraction_s"] >= 20 * 60:
        out.append(f"⚠️ {f(s['distraction_s'])} on distractions — that's "
                   f"{100*s['distraction_s']/max(s['active_s'],1):.0f}% of active time.")
    if s["switches"] >= 25:
        out.append(f"🔀 {s['switches']} context switches — batch similar work into longer blocks.")
    for proj, secs in sorted(s["by_proj"].items(), key=lambda x: -x[1])[:1]:
        rev = float(PROJECTS.get(proj, {}).get("revenue", 0) or 0)
        hrs = secs / 3600
        if rev and hrs:
            out.append(f"💰 {proj}: {f(secs)} for ${rev:,.0f} = ${rev/hrs:,.0f}/hour.")
    return out


# ---------------------------------------------------------------- CLI report
def print_report(name):
    s = compute_stats(name)
    f = core.fmt_duration
    print(f"\n  {s['label']}")
    print("  " + "-" * 40)
    print(f"  Tracked      {f(s['active_s'])}")
    print(f"  Focus        {f(s['focus_s'])}  ({s['focus_pct']:.0f}%)")
    print(f"  Distraction  {f(s['distraction_s'])}")
    print(f"  Breaks       {f(s['break_s'])}")
    print(f"  Switches     {s['switches']}")
    print("\n  By category")
    for cat, secs in sorted(s["by_cat"].items(), key=lambda x: -x[1]):
        bar = "#" * int(30 * secs / max(s["active_s"], 1))
        print(f"  {cat:<14}{f(secs):>8}  {bar}")
    print("\n  Coach")
    for line in generate_insights(s):
        print(f"  • {line}")
    print()


# ---------------------------------------------------------------- CSV export
def export_csv(name):
    s = compute_stats(name)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "start", "end", "minutes", "category", "project", "app", "site", "title"])
    for ses in s["sessions"]:
        st = datetime.datetime.fromtimestamp(ses["start_ts"])
        en = datetime.datetime.fromtimestamp(ses["end_ts"])
        w.writerow([st.strftime("%Y-%m-%d"), st.strftime("%H:%M"),
                    en.strftime("%H:%M"), round(ses["duration"] / 60, 1),
                    ses["category"], ses["project"] or "",
                    ses["top_app"], ses["top_domain"], ses["title"]])
    return buf.getvalue()


# ---------------------------------------------------------------- HTML
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#0f1216;color:#e6e9ef;padding:28px}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:22px;font-weight:600;margin-bottom:2px}
.sub{color:#8b94a3;font-size:13px;margin-bottom:20px}
.tabs{display:flex;gap:8px;margin-bottom:22px;align-items:center}
.tabs a{padding:6px 14px;border-radius:8px;text-decoration:none;color:#aab2c0;background:#1a1f27;font-size:13px}
.tabs a.on{background:#2e7d5b;color:#fff}
.tabs .csv{margin-left:auto;background:#232a34;color:#aab2c0}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:24px}
.card{background:#1a1f27;border:1px solid #232a34;border-radius:12px;padding:14px}
.card .k{color:#8b94a3;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:24px;font-weight:600;margin-top:6px}
.card.focus .v{color:#2ecc71}.card.dist .v{color:#e74c3c}.card.score .v{color:#f1c40f}
.panel{background:#1a1f27;border:1px solid #232a34;border-radius:12px;padding:18px;margin-bottom:18px}
.panel h2{font-size:14px;color:#aab2c0;margin-bottom:14px;font-weight:600}
.timeline{display:flex;height:34px;border-radius:8px;overflow:hidden;background:#11151b}
.timeline .seg{height:100%}
.tl-axis{display:flex;justify-content:space-between;margin-top:6px;font-size:10px;color:#5d6675}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;font-size:12px;color:#aab2c0}
.legend .dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:middle}
.row{display:flex;align-items:center;gap:10px;margin-bottom:9px}
.row .lbl{width:120px;font-size:13px;color:#cdd3dd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .track{flex:1;background:#11151b;border-radius:6px;height:14px;overflow:hidden}
.row .fill{height:100%;border-radius:6px}
.row .val{width:70px;text-align:right;font-size:12px;color:#8b94a3}
.coach li{margin-bottom:8px;list-style:none;font-size:14px}
.daygrid{display:flex;gap:10px;align-items:flex-end;height:140px}
.daygrid .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.daygrid .stack{width:60%;display:flex;flex-direction:column-reverse;border-radius:4px 4px 0 0;overflow:hidden}
.daygrid .seg{width:100%}
.daygrid .d{font-size:11px;color:#8b94a3;margin-top:6px}
.empty{color:#5d6675;font-size:13px;padding:8px 0}
table{width:100%;border-collapse:collapse}
td{padding:7px 0;font-size:13px;border-bottom:1px solid #232a34}
td.r{text-align:right;color:#8b94a3}
td .rate{color:#2ecc71;font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;color:#0f1216;font-weight:600}
.sess td{color:#cdd3dd}
.sess .time{color:#8b94a3;font-variant-numeric:tabular-nums;width:110px}
.sess .dur{text-align:right;color:#8b94a3;width:70px}
"""


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bar_row(label, secs, total, color):
    pct = (100 * secs / total) if total else 0
    return (f'<div class="row"><div class="lbl">{_esc(label)}</div>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<div class="val">{core.fmt_duration(secs)}</div></div>')


def _timeline(sessions):
    """A single proportional bar from first to last activity, gaps included."""
    if not sessions:
        return "<div class='empty'>No activity yet today.</div>"
    span_start = sessions[0]["start_ts"]
    span_end = sessions[-1]["end_ts"]
    span = max(span_end - span_start, 1)
    segs = []
    cursor = span_start
    for s in sessions:
        if s["start_ts"] > cursor:  # untracked gap
            gw = 100 * (s["start_ts"] - cursor) / span
            segs.append(f"<div class='seg' style='width:{gw:.2f}%;background:#11151b'></div>")
        w = 100 * s["duration"] / span
        st = datetime.datetime.fromtimestamp(s["start_ts"]).strftime("%H:%M")
        en = datetime.datetime.fromtimestamp(s["end_ts"]).strftime("%H:%M")
        tip = f"{st}-{en}  {s['category']}  {core.fmt_duration(s['duration'])}"
        segs.append(f"<div class='seg' style='width:{w:.2f}%;background:{cat_color(s['category'])}' title='{_esc(tip)}'></div>")
        cursor = s["end_ts"]
    axis = (f"<div class='tl-axis'><span>{datetime.datetime.fromtimestamp(span_start):%H:%M}</span>"
            f"<span>{datetime.datetime.fromtimestamp(span_end):%H:%M}</span></div>")
    return "<div class='timeline'>" + "".join(segs) + "</div>" + axis


def render_html(name):
    s = compute_stats(name)
    f = core.fmt_duration
    p = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<meta http-equiv='refresh' content='60'>",
         "<title>Time Tracker</title><style>", CSS, "</style></head><body><div class='wrap'>"]
    p.append("<h1>⏱ Time Tracker</h1>")
    rng = "Vandaag" if name == "today" else "Deze week"
    p.append(f"<div class='sub'>{rng} · {datetime.datetime.now():%a %d %b %H:%M} · lokaal</div>")

    def tab(r, txt):
        return f"<a class='{'on' if r == name else ''}' href='/?range={r}'>{txt}</a>"
    p.append("<div class='tabs'>" + tab("today", "Vandaag") + tab("week", "Week") + "</div>")

    # cards (3, minimaal)
    p.append("<div class='cards' style='grid-template-columns:repeat(3,1fr)'>")
    p.append(f"<div class='card focus'><div class='k'>Focus</div><div class='v'>{f(s['focus_s'])}</div></div>")
    p.append(f"<div class='card score'><div class='k'>Focus %</div><div class='v'>{s['focus_pct']:.0f}</div></div>")
    p.append(f"<div class='card dist'><div class='k'>Afleiding</div><div class='v'>{f(s['distraction_s'])}</div></div>")
    p.append("</div>")

    # waar je tijd heen ging (top 5, excl. Break)
    p.append("<div class='panel'><h2>Waar je tijd heen ging</h2>")
    cats = [(c, sec) for c, sec in s["by_cat"].items() if c != "Break"]
    cat_total = sum(sec for _, sec in cats)
    if cat_total == 0:
        p.append("<div class='empty'>Nog geen activiteit.</div>")
    else:
        for cat, secs in sorted(cats, key=lambda x: -x[1])[:5]:
            p.append(_bar_row(cat, secs, cat_total, cat_color(cat)))
    p.append("</div>")

    # $/uur (alleen als omzet is ingevuld in config.json)
    rate_rows = []
    for proj, secs in sorted(s["by_proj"].items(), key=lambda x: -x[1]):
        rev = float(PROJECTS.get(proj, {}).get("revenue", 0) or 0)
        hrs = secs / 3600
        if rev and hrs:
            rate_rows.append(
                f"<tr><td>{_esc(proj)}</td><td class='r'>{f(secs)}</td>"
                f"<td class='r'><span class='rate'>${rev / hrs:,.0f}/uur</span></td></tr>")
    if rate_rows:
        p.append("<div class='panel'><h2>$ / uur</h2><table>" + "".join(rate_rows) + "</table></div>")

    # deze week (focus per dag) — altijd, om koers te zien
    wk = s if name == "week" else compute_stats("week")
    days = sorted(wk["by_day"].items())
    if days:
        p.append("<div class='panel'><h2>Deze week</h2><div class='daygrid'>")
        mx = max((d["focus"] for _, d in days)) or 1
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        for day, d in days:
            hpct = 100 * d["focus"] / mx
            lbl = datetime.datetime.strptime(day, "%Y-%m-%d").strftime("%a")
            op = "1" if day == today_str else "0.5"
            p.append(
                f"<div class='col'><div class='stack' style='height:{hpct:.0f}%;opacity:{op}' "
                f"title='{f(d['focus'])} focus'>"
                f"<div class='seg' style='height:100%;background:#2ecc71'></div></div>"
                f"<div class='d'>{lbl}</div></div>")
        p.append("</div></div>")

    p.append("</div></body></html>")
    return "".join(p)


# ---------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        name = q.get("range", ["today"])[0]
        if name not in ("today", "week", "all"):
            name = "today"
        if parsed.path == "/export.csv":
            body = export_csv(name).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f"attachment; filename=time-{name}.csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = render_html(name).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve():
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Dashboard already running on http://localhost:{PORT}/")
        return
    print(f"Dashboard on http://localhost:{PORT}/  (Ctrl+C to stop)")
    httpd.serve_forever()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--serve"
    if arg in ("--today", "today"):
        print_report("today")
    elif arg in ("--week", "week"):
        print_report("week")
    elif arg in ("--all", "all"):
        print_report("all")
    else:
        serve()
