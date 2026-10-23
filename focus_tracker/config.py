"""Named configuration constants for 24H Focus Tracker (NFR-08).

All tunable tracking thresholds and targets live here, sourced from
BRD-24HFT-001 / FRD-24HFT-001.
"""

import os

APP_NAME = "24H Focus Tracker"
SUBTITLE = "Local-only tracking — no screenshots, no keystrokes, no cloud."
DISCLAIMER = (
    "Tracked app time is an estimate and does not prove cognitive focus."
)

# --- storage (FR-012, NFR-03) -------------------------------------------------
# %LOCALAPPDATA%\24HFocusTracker\focus_tracker.sqlite3 on Windows.
_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
DATA_DIR = os.path.join(_LOCAL_APP_DATA, "24HFocusTracker")
DB_PATH = os.path.join(DATA_DIR, "focus_tracker.sqlite3")

# --- tracking behaviour (FR-007..FR-009, NFR-05, NFR-07) ----------------------
POLL_INTERVAL_MS = 2000            # nominal poll of ~2 seconds (NFR-05)
POLL_INTERVAL_SECONDS = POLL_INTERVAL_MS / 1000
IDLE_THRESHOLD_SECONDS = 60        # FR-008: input idle >= 60s => Idle
LONG_GAP_SECONDS = 15              # FR-009: gaps > 15s are discarded

# --- daily goals (BR-01, BR-02, FR-014..FR-016, FR-024) -----------------------
STUDY_TARGET_SECONDS = 8 * 60 * 60        # 28,800 s
SIDE_HUSTLE_TARGET_SECONDS = 4 * 60 * 60  # 14,400 s

# --- categories (FRD section 8.2) ---------------------------------------------
CATEGORY_STUDY = "Study"
CATEGORY_SIDE_HUSTLE = "Side Hustle"
CATEGORY_PERSONAL = "Personal"
CATEGORY_ENTERTAINMENT = "Entertainment"
CATEGORY_UNCLASSIFIED = "Unclassified"
CATEGORY_IDLE = "Idle"  # reserved for user inactivity, not user-assignable

EDITABLE_CATEGORIES = [
    CATEGORY_STUDY,
    CATEGORY_SIDE_HUSTLE,
    CATEGORY_PERSONAL,
    CATEGORY_ENTERTAINMENT,
    CATEGORY_UNCLASSIFIED,
]

OTHER_CATEGORIES = (
    CATEGORY_PERSONAL,
    CATEGORY_ENTERTAINMENT,
    CATEGORY_UNCLASSIFIED,
)

IDLE_APP_NAME = "idle"       # app_name sentinel for idle intervals
UNKNOWN_APP_NAME = "unknown" # safe fallback when the foreground app is unavailable
