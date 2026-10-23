"""RED: tests for the persistence layer (database.py).

Covers FR-010..FR-013, FR-019..FR-020, TC-13, TC-14 and the data
requirements in FRD section 8.
"""

import datetime as dt

import pytest

from focus_tracker import config
from focus_tracker import database as db


@pytest.fixture
def conn(tmp_path):
    c = db.open_database(str(tmp_path / "test.sqlite3"))
    yield c
    c.close()


DAY = dt.date(2026, 10, 23)


def _add_interval(
    conn,
    start,
    end,
    app_name="chrome.exe",
    category="Study",
    seconds=600,
    title="Some Page - Google Chrome",
):
    db.record_interval(conn, start, end, app_name, title, category, seconds)


# --- schema -----------------------------------------------------------------

def test_open_database_creates_schema(conn):
    names = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "usage_interval" in names
    assert "app_category" in names


def test_open_database_creates_parent_directory(tmp_path):
    target = tmp_path / "sub" / "folder" / "test.sqlite3"
    conn = db.open_database(str(target))
    try:
        assert target.exists()
    finally:
        conn.close()


# --- category rules (FR-010, FR-011, BR-09) ---------------------------------

def test_unknown_app_defaults_to_unclassified(conn):
    assert db.get_category(conn, "neverseen.exe") == config.CATEGORY_UNCLASSIFIED


def test_saved_category_is_returned(conn):
    db.set_category(conn, "winword.exe", config.CATEGORY_STUDY)
    assert db.get_category(conn, "winword.exe") == config.CATEGORY_STUDY


def test_category_lookup_is_case_insensitive(conn):
    db.set_category(conn, "WINWORD.EXE", config.CATEGORY_STUDY)
    assert db.get_category(conn, "winWord.exe") == config.CATEGORY_STUDY


def test_category_rule_can_be_overwritten(conn):
    db.set_category(conn, "chrome.exe", config.CATEGORY_UNCLASSIFIED)
    db.set_category(conn, "chrome.exe", config.CATEGORY_STUDY)
    assert db.get_category(conn, "chrome.exe") == config.CATEGORY_STUDY


def test_set_category_rejects_invalid_category(conn):
    with pytest.raises(ValueError):
        db.set_category(conn, "chrome.exe", "Not a category")


def test_set_category_stores_app_name_lowercase(conn):
    db.set_category(conn, "PyCharm64.EXE", config.CATEGORY_SIDE_HUSTLE)
    row = conn.execute(
        "SELECT app_name FROM app_category"
    ).fetchone()
    assert row == ("pycharm64.exe",)


# --- intervals (FR-012) ------------------------------------------------------

def test_record_interval_stores_all_fields(conn):
    start = dt.datetime(2026, 10, 23, 9, 0, 0)
    end = dt.datetime(2026, 10, 23, 9, 0, 10)
    db.record_interval(conn, start, end, "chrome.exe", "Docs", config.CATEGORY_STUDY, 10)
    row = conn.execute(
        "SELECT started_at, ended_at, app_name, window_title, category, seconds"
        " FROM usage_interval"
    ).fetchone()
    assert row == (
        "2026-10-23T09:00:00",
        "2026-10-23T09:00:10",
        "chrome.exe",
        "Docs",
        "Study",
        10,
    )


def test_record_interval_accepts_datetime_objects(conn):
    db.record_interval(
        conn,
        dt.datetime(2026, 10, 23, 9, 0, 0),
        dt.datetime(2026, 10, 23, 9, 0, 2),
        "chrome.exe",
        None,
        config.CATEGORY_UNCLASSIFIED,
        2,
    )
    total = conn.execute("SELECT COUNT(*) FROM usage_interval").fetchone()[0]
    assert total == 1


def test_record_interval_rejects_non_positive_seconds(conn):
    start = dt.datetime(2026, 10, 23, 9, 0, 0)
    end = dt.datetime(2026, 10, 23, 9, 0, 2)
    with pytest.raises(ValueError):
        db.record_interval(conn, start, end, "app.exe", None, "Study", 0)
    with pytest.raises(ValueError):
        db.record_interval(conn, start, end, "app.exe", None, "Study", -3)


# --- daily aggregation (FR-013, BR-05) ---------------------------------------

def test_daily_totals_sum_by_category(conn):
    _add_interval(conn, "2026-10-23T09:00:00", "2026-10-23T09:10:00",
                  "chrome.exe", config.CATEGORY_STUDY, 600)
    _add_interval(conn, "2026-10-23T10:00:00", "2026-10-23T10:05:00",
                  "devenv.exe", config.CATEGORY_SIDE_HUSTLE, 300)
    _add_interval(conn, "2026-10-23T11:00:00", "2026-10-23T11:02:00",
                  "chrome.exe", config.CATEGORY_STUDY, 120)
    totals = db.daily_category_seconds(conn, DAY)
    assert totals[config.CATEGORY_STUDY] == 720
    assert totals[config.CATEGORY_SIDE_HUSTLE] == 300


def test_daily_totals_exclude_other_days(conn):
    _add_interval(conn, "2026-10-22T09:00:00", "2026-10-22T09:10:00",
                  "chrome.exe", config.CATEGORY_STUDY, 600)
    _add_interval(conn, "2026-10-24T09:00:00", "2026-10-24T09:10:00",
                  "chrome.exe", config.CATEGORY_STUDY, 600)
    totals = db.daily_category_seconds(conn, DAY)
    assert totals[config.CATEGORY_STUDY] == 0


def test_daily_totals_include_zero_categories(conn):
    totals = db.daily_category_seconds(conn, DAY)
    for category in config.EDITABLE_CATEGORIES:
        assert category in totals
        assert totals[category] == 0
    assert totals[config.CATEGORY_IDLE] == 0


def test_daily_totals_include_idle(conn):
    _add_interval(conn, "2026-10-23T11:00:00", "2026-10-23T11:10:00",
                  config.IDLE_APP_NAME, config.CATEGORY_IDLE, 600)
    totals = db.daily_category_seconds(conn, DAY)
    assert totals[config.CATEGORY_IDLE] == 600


def test_interval_spanning_midnight_counted_on_start_day(conn):
    # Documented behavior: an interval belongs to the day it started.
    _add_interval(conn, "2026-10-23T23:59:58", "2026-10-24T00:00:00",
                  "chrome.exe", config.CATEGORY_STUDY, 2)
    totals = db.daily_category_seconds(conn, DAY)
    assert totals[config.CATEGORY_STUDY] == 2


# --- app usage table (FR-019) -------------------------------------------------

def test_app_usage_for_day_aggregates_by_app_and_is_sorted(conn):
    _add_interval(conn, "2026-10-23T09:00:00", "2026-10-23T09:10:00",
                  "chrome.exe", config.CATEGORY_STUDY, 600)
    _add_interval(conn, "2026-10-23T09:10:00", "2026-10-23T09:12:00",
                  "chrome.exe", config.CATEGORY_STUDY, 120)
    _add_interval(conn, "2026-10-23T10:00:00", "2026-10-23T10:03:00",
                  "devenv.exe", config.CATEGORY_SIDE_HUSTLE, 180)
    rows = db.app_usage_for_day(conn, DAY)
    assert rows == [
        ("chrome.exe", config.CATEGORY_STUDY, 720),
        ("devenv.exe", config.CATEGORY_SIDE_HUSTLE, 180),
    ]


def test_app_usage_for_day_shows_zero_rows_for_empty_day(conn):
    assert db.app_usage_for_day(conn, DAY) == []


# --- weekly report (FR-020, TC-13) ----------------------------------------------

def test_weekly_summary_returns_seven_days_oldest_first(conn):
    _add_interval(conn, "2026-10-20T09:00:00", "2026-10-20T09:10:00",
                  "chrome.exe", config.CATEGORY_STUDY, 600)
    summary = db.weekly_summary(conn, DAY)
    dates = [row["date"] for row in summary]
    assert dates == [dt.date(2026, 10, 17) + dt.timedelta(days=i) for i in range(7)]
    assert summary[3]["categories"][config.CATEGORY_STUDY] == 600


def test_weekly_summary_empty_days_are_zeroes(conn):
    summary = db.weekly_summary(conn, DAY)
    assert len(summary) == 7
    for row in summary:
        for category in config.EDITABLE_CATEGORIES:
            assert row["categories"][category] == 0


# --- known applications list (category editor) -----------------------------------

def test_list_known_apps_merges_rules_and_intervals(conn):
    _add_interval(conn, "2026-10-23T09:00:00", "2026-10-23T09:02:00",
                  "chrome.exe", config.CATEGORY_UNCLASSIFIED, 120)
    _add_interval(conn, "2026-10-23T09:05:00", "2026-10-23T09:07:00",
                  config.IDLE_APP_NAME, config.CATEGORY_IDLE, 120)
    db.set_category(conn, "winword.exe", config.CATEGORY_STUDY)
    apps = {app: cat for app, cat in db.list_known_apps(conn)}
    assert apps["chrome.exe"] == config.CATEGORY_UNCLASSIFIED
    assert apps["winword.exe"] == config.CATEGORY_STUDY
    assert config.IDLE_APP_NAME not in apps


# --- persistence across connections (TC-14, FR-012) --------------------------------

def test_data_persists_across_connections(tmp_path):
    path = str(tmp_path / "persist.sqlite3")
    conn_a = db.open_database(path)
    db.record_interval(
        conn_a,
        dt.datetime(2026, 10, 23, 12, 0, 0),
        dt.datetime(2026, 10, 23, 12, 0, 5),
        "chrome.exe",
        None,
        config.CATEGORY_STUDY,
        5,
    )
    conn_a.close()
    conn_b = db.open_database(path)
    try:
        totals = db.daily_category_seconds(conn_b, DAY)
        assert totals[config.CATEGORY_STUDY] == 5
    finally:
        conn_b.close()
