"""RED: tests for the per-day daily plan (todo list) persistence.

Covers adding, listing (in creation order), ticking and unticking,
deleting, and clearing completed tasks, all scoped to a calendar day.
"""

import datetime as dt

import pytest

from focus_tracker import database as db


@pytest.fixture
def conn(tmp_path):
    c = db.open_database(str(tmp_path / "test.sqlite3"))
    yield c
    c.close()


TODAY = dt.date(2026, 10, 23)

"""
Schema: daily_task(id INTEGER PRIMARY KEY, day TEXT NOT NULL, text TEXT NOT
NULL, done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)
"""


def test_add_task_creates_row(conn):
    task = db.add_plan_task(conn, TODAY, "Write FRD gap analysis")
    assert task["text"] == "Write FRD gap analysis"
    assert task["done"] is False
    assert task["day"] == TODAY


def test_add_task_trims_text(conn):
    task = db.add_plan_task(conn, TODAY, "  Review charts  ")
    assert task["text"] == "Review charts"


def test_add_task_rejects_blank_text(conn):
    with pytest.raises(ValueError):
        db.add_plan_task(conn, TODAY, "   ")
    with pytest.raises(ValueError):
        db.add_plan_task(conn, TODAY, "")


def test_list_tasks_returns_creation_order_and_nothing_after(conn):
    first = db.add_plan_task(conn, TODAY, "Task one")
    second = db.add_plan_task(conn, TODAY, "Task two")
    tasks = db.list_plan_tasks(conn, TODAY)
    names = [t["text"] for t in tasks]
    assert names == ["Task one", "Task two"]
    assert [t["id"] for t in tasks] == [first["id"], second["id"]]
    assert all(t["done"] is False for t in tasks)


def test_list_tasks_isolated_by_day(conn):
    db.add_plan_task(conn, TODAY, "Today only")
    db.add_plan_task(conn, TODAY - dt.timedelta(days=3), "Yesterday thing")
    assert [t["text"] for t in db.list_plan_tasks(conn, TODAY)] == ["Today only"]


def test_set_task_done_toggles(conn):
    task = db.add_plan_task(conn, TODAY, "Deep work block")
    changed = db.set_plan_task_done(conn, task["id"], True)
    assert changed["done"] is True
    tasks = db.list_plan_tasks(conn, TODAY)
    assert tasks[0]["done"] is True
    db.set_plan_task_done(conn, task["id"], False)
    assert db.list_plan_tasks(conn, TODAY)[0]["done"] is False


def test_set_task_done_accepts_already_matching_state(conn):
    task = db.add_plan_task(conn, TODAY, "Idle reading")
    db.set_plan_task_done(conn, task["id"], True)
    db.set_plan_task_done(conn, task["id"], True)  # idempotent, no error
    assert db.list_plan_tasks(conn, TODAY)[0]["done"] is True


def test_delete_task_removes_only_that_row(conn):
    first = db.add_plan_task(conn, TODAY, "Keep me")
    second = db.add_plan_task(conn, TODAY, "Delete me")
    db.delete_plan_task(conn, second["id"])
    remaining = db.list_plan_tasks(conn, TODAY)
    assert [t["text"] for t in remaining] == ["Keep me"]
    assert first["id"] != second["id"]


def test_delete_task_of_unknown_id_is_safe(conn):
    db.delete_plan_task(conn, 9999)  # no error
    assert db.list_plan_tasks(conn, TODAY) == []


def test_clear_completed_removes_only_done_tasks(conn):
    a = db.add_plan_task(conn, TODAY, "Done thing")
    db.add_plan_task(conn, TODAY, "Open thing")
    db.set_plan_task_done(conn, a["id"], True)
    db.clear_completed_plan_tasks(conn, TODAY)
    assert [t["text"] for t in db.list_plan_tasks(conn, TODAY)] == ["Open thing"]


def test_clear_completed_other_days_untouched(conn):
    other = TODAY - dt.timedelta(days=1)
    a = db.add_plan_task(conn, other, "Old done task")
    db.set_plan_task_done(conn, a["id"], True)
    db.add_plan_task(conn, TODAY, "Today open task")
    db.clear_completed_plan_tasks(conn, TODAY)
    assert len(db.list_plan_tasks(conn, other)) == 1
    assert len(db.list_plan_tasks(conn, TODAY)) == 1
