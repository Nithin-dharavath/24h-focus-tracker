"""SQLite persistence for 24H Focus Tracker (FR-012, NFR-03).

Stores usage intervals and application category rules in a local-only
SQLite database. Nothing here performs any network activity.
"""

import datetime as dt
import os
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_interval (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,
    ended_at     TEXT NOT NULL,
    app_name     TEXT NOT NULL,
    window_title TEXT,
    category     TEXT NOT NULL,
    seconds      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS app_category (
    app_name   TEXT PRIMARY KEY,
    category   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_task (
    id         INTEGER PRIMARY KEY,
    day        TEXT NOT NULL,
    text       TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_started_at
    ON usage_interval (started_at);

CREATE INDEX IF NOT EXISTS idx_daily_task_day
    ON daily_task (day);
"""


def open_database(path: str) -> sqlite3.Connection:
    """Open (creating if needed) the database at *path* and ensure the schema."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _to_timestamp(value: dt.datetime | str) -> str:
    """Normalize a datetime or string to a local ISO 8601 text timestamp."""
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


# --- usage intervals ----------------------------------------------------------

def record_interval(
    conn: sqlite3.Connection,
    started_at: dt.datetime | str,
    ended_at: dt.datetime | str,
    app_name: str,
    window_title: str | None,
    category: str,
    seconds: int,
) -> None:
    """Persist one usage interval. Durations must be positive integers."""
    seconds = int(seconds)
    if seconds <= 0:
        raise ValueError(f"interval seconds must be positive, got {seconds}")
    conn.execute(
        """
        INSERT INTO usage_interval
            (started_at, ended_at, app_name, window_title, category, seconds)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            _to_timestamp(started_at),
            _to_timestamp(ended_at),
            app_name,
            window_title,
            category,
            seconds,
        ),
    )
    conn.commit()


# --- category rules (FR-010, FR-011) --------------------------------------------

def get_category(conn: sqlite3.Connection, app_name: str) -> str:
    """Return the saved rule for *app_name* or the Unclassified default."""
    row = conn.execute(
        "SELECT category FROM app_category WHERE app_name = LOWER(?)",
        (app_name,),
    ).fetchone()
    if row:
        return row[0]
    return config.CATEGORY_UNCLASSIFIED


def set_category(conn: sqlite3.Connection, app_name: str, category: str) -> None:
    """Insert or update a category rule for *app_name* (FR-011)."""
    if category not in config.EDITABLE_CATEGORIES:
        raise ValueError(f"{category!r} is not an assignable category")
    clean_name = app_name.strip().lower()
    if not clean_name:
        raise ValueError("app_name must not be empty")
    conn.execute(
        """
        INSERT INTO app_category (app_name, category) VALUES (?, ?)
        ON CONFLICT(app_name) DO UPDATE SET category = excluded.category
        """,
        (clean_name, category),
    )
    conn.commit()


# --- reporting queries (FR-013, FR-019, FR-020) ----------------------------------

def daily_category_seconds(
    conn: sqlite3.Connection, day: dt.date
) -> dict[str, int]:
    """Aggregate seconds recorded *starting* on *day*, per category.

    Day window runs from local midnight to the following local midnight.
    Intervals that span midnight belong to the day they started.
    """
    window_start = dt.datetime.combine(day, dt.time.min).isoformat(timespec="seconds")
    window_end = dt.datetime.combine(
        day + dt.timedelta(days=1), dt.time.min
    ).isoformat(timespec="seconds")
    rows = conn.execute(
        """
        SELECT category, SUM(seconds) FROM usage_interval
        WHERE started_at >= ? AND started_at < ?
        GROUP BY category
        """,
        (window_start, window_end),
    ).fetchall()
    totals = {category: 0 for category in config.EDITABLE_CATEGORIES}
    totals[config.CATEGORY_IDLE] = 0
    for category, seconds in rows:
        if category in totals:
            totals[category] = int(seconds or 0)
    return totals


def app_usage_for_day(
    conn: sqlite3.Connection, day: dt.date
) -> list[tuple[str, str, int]]:
    """Aggregate (app_name, category, seconds) for *day*, longest first."""
    window_start = dt.datetime.combine(day, dt.time.min).isoformat(timespec="seconds")
    window_end = dt.datetime.combine(
        day + dt.timedelta(days=1), dt.time.min
    ).isoformat(timespec="seconds")
    return conn.execute(
        """
        SELECT app_name, category, SUM(seconds)
        FROM usage_interval
        WHERE started_at >= ? AND started_at < ? AND app_name != ?
        GROUP BY app_name, category
        ORDER BY SUM(seconds) DESC, app_name ASC
        """,
        (window_start, window_end, config.IDLE_APP_NAME),
    ).fetchall()


def weekly_summary(
    conn: sqlite3.Connection, end_day: dt.date
) -> list[dict]:
    """Summarize the seven calendar dates ending *end_day*, inclusive.

    Rows are chronological (oldest first); each row carries a full
    per-category seconds map for the day.
    """
    summary = []
    for offset in range(6, -1, -1):
        day = end_day - dt.timedelta(days=offset)
        summary.append(
            {"date": day, "categories": daily_category_seconds(conn, day)}
        )
    return summary


def list_known_apps(
    conn: sqlite3.Connection,
) -> list[tuple[str, str]]:
    """Merge category rules with executables seen in intervals.

    Excludes the reserved 'idle' sentinel. Values are the saved rule or
    Unclassified so unknown executables can be categorized later.
    """
    rows = conn.execute(
        """
        SELECT app_name, NULL AS rule FROM usage_interval WHERE app_name != ?
        UNION
        SELECT app_name, category AS rule FROM app_category
        ORDER BY 1
        """,
        (config.IDLE_APP_NAME,),
    ).fetchall()
    merged = {}
    for app_name, rule in rows:
        merged[app_name] = rule or config.CATEGORY_UNCLASSIFIED
    return sorted(merged.items())


# --- day reset (per-day data reset feature) -----------------------------------

def delete_intervals_for_day(conn: sqlite3.Connection, day: dt.date) -> int:
    """Permanently remove every usage interval starting on *day*.

    Intervening days and all category rules are untouched. Returns the
    number of rows deleted.
    """
    window_start = dt.datetime.combine(day, dt.time.min).isoformat(timespec="seconds")
    window_end = dt.datetime.combine(
        day + dt.timedelta(days=1), dt.time.min
    ).isoformat(timespec="seconds")
    cursor = conn.execute(
        "DELETE FROM usage_interval WHERE started_at >= ? AND started_at < ?",
        (window_start, window_end),
    )
    conn.commit()
    return cursor.rowcount


# --- daily plan / todo tasks (per-day, checkbox list) ---------------------------

def add_plan_task(
    conn: sqlite3.Connection, day: dt.date, text: str
) -> dict:
    """Append a task to *day*'s plan. Blank text is rejected."""
    clean = text.strip()
    if not clean:
        raise ValueError("a plan task needs a description")
    created_at = dt.datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        "INSERT INTO daily_task (day, text, done, created_at) VALUES (?, ?, 0, ?)",
        (day.isoformat(), clean, created_at),
    )
    conn.commit()
    return {
        "id": cursor.lastrowid,
        "day": day,
        "text": clean,
        "done": False,
    }


def list_plan_tasks(conn: sqlite3.Connection, day: dt.date) -> list[dict]:
    """Return *day*'s plan tasks in creation order."""
    rows = conn.execute(
        "SELECT id, text, done FROM daily_task"
        " WHERE day = ? ORDER BY id",
        (day.isoformat(),),
    ).fetchall()
    return [
        {"id": task_id, "text": text, "done": bool(done)}
        for task_id, text, done in rows
    ]


def set_plan_task_done(
    conn: sqlite3.Connection, task_id: int, done: bool
) -> dict | None:
    """Mark one task done/undone. Returns the updated row, or None if unknown."""
    conn.execute(
        "UPDATE daily_task SET done = ? WHERE id = ?",
        (1 if done else 0, task_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT day, text, done FROM daily_task WHERE id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    day_iso, text, state = row
    return {
        "id": task_id,
        "day": dt.date.fromisoformat(day_iso),
        "text": text,
        "done": bool(state),
    }


def delete_plan_task(conn: sqlite3.Connection, task_id: int) -> None:
    """Remove one task; unknown ids are ignored."""
    conn.execute("DELETE FROM daily_task WHERE id = ?", (task_id,))
    conn.commit()


def clear_completed_plan_tasks(conn: sqlite3.Connection, day: dt.date) -> None:
    """Remove every completed task from *day*'s plan."""
    conn.execute("DELETE FROM daily_task WHERE day = ? AND done = 1", (day.isoformat(),))
    conn.commit()
