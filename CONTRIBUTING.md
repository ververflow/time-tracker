# Contributing

Thanks for your interest. PRs and issues are welcome.

## Local setup

```powershell
git clone https://github.com/ververflow/time-tracker.git
cd time-tracker

pip install pywin32 psutil pystray Pillow

.\track.bat start   # tracker in background (tray dot)
.\track.bat         # dashboard at http://localhost:7878
```

To customise rules/config without affecting git, copy `rules.json` →
`rules.local.json` and `config.json` → `config.local.json`. The
`*.local.json` files are gitignored and override the templates if present.

## Running the self-test

```powershell
python selftest.py
```

The offline parts always pass. The live-system parts require the tracker +
dashboard to be running first (`track start` then `track`).

## Code style

- Python 3.11+
- 4-space indent, ~100-char lines
- Match the existing single-purpose-module structure (`core.py`, `tracker.py`,
  `dashboard.py`) rather than introducing packages or class hierarchies

## Submitting changes

1. For non-trivial changes, open an issue first.
2. Fork, branch, make the change.
3. Run `python selftest.py` — all offline checks must pass.
4. Open a PR explaining what changed and why.

## Out of scope

- Cloud sync / accounts — this is intentionally local-only
- Linux/macOS support (uses Win32 APIs for foreground-window detection)
- Replacing SQLite with another store
