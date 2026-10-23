# 24H Focus Tracker

A lightweight, privacy-first Windows desktop application that shows how your
laptop time is distributed across study, side-hustle work, personal activity,
entertainment, and unclassified use — and how you're tracking toward your
daily goals.

Built to the MVP baseline in `24H_Focus_Tracker_BRD.docx` (BRD-24HFT-001) and
`24H_Focus_Tracker_FRD.docx` (FRD-24HFT-001).

## What it does

- **Manual session control** — you press Start; the app polls the foreground
  executable every ~2 seconds and records short usage intervals with
  timestamps, application name, window title, category, and duration.
- **Daily plan (todo list)** — a dedicated tab where you write down what
  you're doing today, with checkbox tasks; each day keeps its own list.
  Pressing Start with an empty plan gently offers to write it first.
- **Reset day** — a confirm-guarded button that permanently deletes
  everything tracked today (charts, totals, app table return to zero).
  Past days and your daily plan are not affected.
- **Idle detection** — intervals with no keyboard/mouse input for 60 seconds
  or more are classified as *Idle* and shown separately.
- **Gap protection** — polling gaps longer than 15 seconds (sleep, desktop
  switch, stuck UI) are never counted as app usage.
- **Daily dashboard** — metric cards for Study, Side Hustle, total tracked,
  and Idle; a target-vs-actual bar chart, a category pie chart, and a
  per-application usage table.
- **Weekly report** — the last seven calendar days as a stacked chart and
  table (Study / Side Hustle / Other).
- **Category editor** — every application seen while tracking can be
  re-labelled Study, Side Hustle, Personal, Entertainment, or Unclassified;
  new categories apply from the next recorded interval on.
- **Daily goals** — Study 8h (28,800 s) and Side Hustle 4h (14,400 s) with
  capped-at-100% progress.

## Privacy stance (by design)

- No screenshots, no keystroke capture, no webcam/microphone access.
- No accounts, no cloud, no network transmission — **everything stays local**.
- Window titles are stored locally only; browser tabs and URLs are not
  inspected.
- The app does not auto-start with Windows and stops tracking when closed.

## Setup

1. Install Python 3.11 or newer for Windows (python.org).
2. In the project folder:

   ```
   pip install -r requirements.txt
   ```

3. Run the app:

   ```
   python main.py
   ```

Notes:
- Foreground-window and idle queries use Windows APIs; other operating
  systems are not supported (the UI will still open, but tracking providers
  required Windows).
- First run creates the database folder automatically.

## Data location and backup

Usage records live in a single local SQLite database:

```
%LOCALAPPDATA%\24HFocusTracker\focus_tracker.sqlite3
```

Usage intervals live in `usage_interval`; your per-day plan tasks live in
`daily_task` (a Reset day clears intervals only — plans are kept).

To back up your history, copy this file while the app is not running.
Deleting it resets all statistics and plans.

## Running the tests

```
pytest
```

The suite (95 tests) covers the database layer, the tracking state machine,
report calculations, plan tasks, the main window, and the Daily plan /
Reset day features (headless, offscreen Qt), mapping to the acceptance test
cases in FRD section 11 plus the follow-up feature tests.

## Honest limitations (from the BRD/FRD)

- *Tracked app time is an estimate* — it measures application activity and
  cannot verify cognitive focus or deep work.
- Browsers are tracked as one executable; no website-level detail.
- Totals are approximate (2-second polling).
- Tracking stops when the app is closed or the machine sleeps; such gaps are
  excluded, not inferred.
- Category guesses start as Unclassified — correct them in the App categories
  tab.
- Sleep/lock/unlock transitions are approximated by the long-gap rule.
- An interval that spans midnight is counted on the day it started
  (documented MVP behaviour; more precise handling is future work).

## Project structure

```
main.py                  entry point (python main.py)
focus_tracker/
    config.py            named constants: thresholds, targets, paths
    database.py          SQLite schema, intervals, category rules,
                         plan tasks, day reset, queries
    tracker.py           Start/Pause/Resume/Stop state machine + poll tick,
                         Windows foreground & idle providers
    reporting.py         formatting and calculation helpers
    charts.py            Matplotlib bar / pie / weekly stacked charts
    main_window.py       PySide6 window: header, controls, cards,
                         Today / Weekly / Daily plan / Categories tabs
tests/                   pytest suite (95 tests)
```

## Future considerations (from the BRD)

Signed installer/PyInstaller packaging, Windows lock/suspend event handling,
CSV export and backup/restore, per-day targets, title-redaction privacy mode,
timeline view, and optional opt-in browser domain tracking.
