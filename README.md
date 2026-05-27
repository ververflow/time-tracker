# ⏱ Time Tracker — your own local Rize

An automatic time tracker that runs in the background, figures out where your
time went, and shows you focus %, distractions, and $/hour — **no input
required** from you. Free, and 100% local: nothing ever leaves your PC.

Windows-only (uses Win32 APIs for foreground-window detection).

## Why this instead of Rize / Toggl
- **Automatic** like Rize — you don't start/stop anything.
- **$0/month** instead of $13–$30.
- **More private than Rize**: it stores only the *window title + app name*
  (never screenshots or keystrokes), and unlike Rize that data stays in a
  local SQLite file on your machine — it is never uploaded anywhere.

## How it works
Every 10 seconds it notes the active window's app + title (and active tab URL,
if the bundled browser extension is installed), plus whether you've been idle.
It buckets that into categories (Coding, Sales, Email, Distraction, …) using
simple rules you can edit. That's it.

## What you see — one glance, no scrolling
The web dashboard (`http://localhost:7878`) is intentionally tight: one screen.
- **Focus · Focus % · Distraction** (3 numbers)
- **Where your time went** — top 5 categories
- **This week** — focus per day (am I on track?)
- **$/hour** appears automatically once you fill in revenue in `config.local.json`
- Toggle **Today / Week**

Want more detail (sessions, timeline, top apps/sites, coach insights)? Those
live in the terminal:
```powershell
.\track.bat today   # or week / all
```
CSV export: `http://localhost:7878/export.csv?range=week`.

## Nudges
- Distracted too long → "refocus" reminder.
- Focused 90 min straight (no break) → "take a short break" reminder.
- Tune both in `config.json` (or your `config.local.json` override) under `nudge`.

## Requirements

- Windows 10/11
- Python 3.11+ with `pywin32`, `psutil`, `pystray`, `Pillow` on PATH

```powershell
pip install pywin32 psutil pystray Pillow
```

## Quick start
```powershell
git clone https://github.com/ververflow/time-tracker.git
cd time-tracker

.\track.bat start    # start tracking (a coloured dot appears in the tray)
.\track.bat          # open the dashboard in your browser
```
Tray dot colours: 🟢 focused · 🔵 neutral · 🔴 distraction · ⚪ idle/paused.
Right-click the dot to pause, open the dashboard, or quit.

> If `python` / `pythonw` are not on your PATH, set `TIMETRACKER_PY` to an
> absolute path before calling `track.bat`:
> ```powershell
> $env:TIMETRACKER_PY = "C:\Python311\python.exe"
> .\track.bat start
> ```

## Start automatically at login (recommended)
```powershell
powershell -ExecutionPolicy Bypass -File .\install-startup.ps1
```
To undo: `.\uninstall-startup.ps1`

## Commands
| Command | What it does |
|---|---|
| `track start` | Start tracking in the background |
| `track stop` | Stop tracker + dashboard |
| `track` or `track dashboard` | Open the web dashboard |
| `track today` / `track week` / `track all` | Quick summary in the terminal |

## Make it yours — local overrides

The repo ships with generic example rules. To customise without polluting git:

- Copy `rules.json` → `rules.local.json` and edit it. If `rules.local.json`
  exists, it overrides `rules.json`.
- Copy `config.json` → `config.local.json` and edit it. Same override behaviour.
- Both `*.local.json` files are gitignored.

### `rules.json` — how windows map to categories/projects

First match wins; edit freely. `app` matches the .exe name, `title` matches
the window title, `url` matches the browser URL (all case-insensitive
substring). Add a `"project": "myproject"` field to tag activity to a project
for $/hour tracking.

### `config.json` — poll, idle, focus mix, project revenue

```json
"projects": {
  "myproject": { "revenue": 1200 }
}
```
Put what you earned per project in `revenue` and the dashboard shows real
**$/hour**.

## Exact browser URLs (optional extension)

By default browser activity is categorised from the window **title**. For exact
sites (and a "Top sites" panel), install the bundled extension once:

1. Open `edge://extensions` (or `chrome://extensions`).
2. Turn on **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `browser-extension/` folder in this repo.
4. Done. It reports the active tab's URL to the tracker on `127.0.0.1:7879`
   only — nothing is sent anywhere else.

To use it in a second Chromium browser, just Load unpacked there too.
Firefox would need a separate port of the extension — not included.

## Privacy / data
- All data lives in `data.db` (SQLite) in this folder. Delete it to wipe history.
- No network calls, no telemetry, no accounts.
- `data.db` is gitignored — your activity history never leaves your machine.

## Self-test
```powershell
python selftest.py
```
Runs offline correctness checks plus probes the live tracker + dashboard
(start them first with `track start` and `track`).

## Notes / limits
- Without the extension, browser activity is categorised from the page **title**
  (~90% accurate). Install the extension (above) for exact URLs.
- Global window reads can't see into apps running **as administrator** while
  they're focused — those windows show up blank/uncategorised.

## License

MIT — see [LICENSE](LICENSE).
