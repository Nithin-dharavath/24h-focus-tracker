"""UI tests for the Daily plan tab, the Start nudge, and Reset day.

Covers the per-day todo checklist with checkboxes, the gentle plan nudge
when Start is pressed with an empty plan, and the confirm-guarded reset
of today's tracked data.
"""

import datetime as dt

import pytest

from focus_tracker import config
from focus_tracker import database as db
from focus_tracker.main_window import MainWindow
from focus_tracker.tracker import TrackingController
from PySide6.QtCore import Qt


class FakeClock:
    def __init__(self, start):
        self._now = start

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += dt.timedelta(seconds=seconds)


TODAY = dt.date(2026, 10, 23)
NOW = dt.datetime(2026, 10, 23, 10, 0, 0)


@pytest.fixture
def app_window(qapp):
    conn = db.open_database(":memory:")
    clock = FakeClock(NOW)
    controller = TrackingController(
        conn,
        clock=clock,
        idle_seconds=lambda: 0.0,
        foreground=lambda: ("chrome.exe", "Docs - Chrome"),
    )
    window = MainWindow(conn, controller=controller, today=lambda: TODAY)
    # Pre-answered dialogs so tests never open a real modal; individual
    # tests override these attributes as needed.
    window._confirm_plan_nudge = lambda: True
    window._confirm_reset = lambda: False
    yield window, clock, conn
    window._timer.stop()
    conn.close()


# --- Daily plan tab -------------------------------------------------------------

def test_daily_plan_tab_exists_with_day_label(app_window):
    window, clock, conn = app_window
    assert window.tabs.tabText(2) == "Daily plan"
    assert "Fri 23 Oct" in window._plan_day_label.text()


def test_add_task_persists_and_appears_in_list(app_window):
    window, clock, conn = app_window
    window._task_input.setText("Physics assignment chapter 4")
    window._on_add_plan_task_clicked()
    tasks = db.list_plan_tasks(conn, TODAY)
    assert [t["text"] for t in tasks] == ["Physics assignment chapter 4"]
    assert tasks[0]["done"] is False
    assert window._plan_list.count() == 1
    assert window._plan_list.item(0).text() == "Physics assignment chapter 4"
    assert window._task_input.text() == ""  # input ready for the next task


def test_add_blank_task_warns_and_stores_nothing(app_window):
    window, clock, conn = app_window
    window._task_input.setText("   ")
    window._on_add_plan_task_clicked()
    assert db.list_plan_tasks(conn, TODAY) == []
    assert "task" in window.statusBar().currentMessage()


def test_checkbox_toggle_persists_and_updates_counter(app_window):
    window, clock, conn = app_window
    db.add_plan_task(conn, TODAY, "Read FRD")
    window._refresh_plan()
    item = window._plan_list.item(0)
    assert window._plan_progress_label.text() == "0 of 1 done"
    item.setCheckState(Qt.CheckState.Checked)
    assert db.list_plan_tasks(conn, TODAY)[0]["done"] is True
    assert window._plan_progress_label.text() == "1 of 1 done"
    item.setCheckState(Qt.CheckState.Unchecked)
    assert db.list_plan_tasks(conn, TODAY)[0]["done"] is False


def test_delete_selected_task_only(app_window):
    window, clock, conn = app_window
    db.add_plan_task(conn, TODAY, "Keep me")
    db.add_plan_task(conn, TODAY, "Delete me")
    window._refresh_plan()
    window._plan_list.setCurrentRow(1)
    window._on_delete_plan_task_clicked()
    assert [t["text"] for t in db.list_plan_tasks(conn, TODAY)] == ["Keep me"]


def test_delete_without_selection_warns(app_window):
    window, clock, conn = app_window
    window._on_delete_plan_task_clicked()
    assert "Select a task" in window.statusBar().currentMessage()


def test_clear_completed_removes_done_only(app_window):
    window, clock, conn = app_window
    done = db.add_plan_task(conn, TODAY, "Finished work")
    db.set_plan_task_done(conn, done["id"], True)
    db.add_plan_task(conn, TODAY, "Open work")
    window._refresh_plan()
    window._on_clear_completed_clicked()
    remaining = db.list_plan_tasks(conn, TODAY)
    assert [t["text"] for t in remaining] == ["Open work"]
    assert window._plan_list.count() == 1


# --- Start nudge -------------------------------------------------------------------

def test_start_with_empty_plan_nudges_and_opens_plan_tab(app_window, monkeypatch):
    window, clock, conn = app_window
    monkeypatch.setattr(window, "_confirm_plan_nudge", lambda: False)
    window._on_start_clicked()
    assert window.controller.state == "not_tracking"
    assert window.tabs.currentIndex() == 2  # on the Daily plan tab


def test_start_proceeds_when_nudge_answered_start_anyway(app_window, monkeypatch):
    window, clock, conn = app_window
    monkeypatch.setattr(window, "_confirm_plan_nudge", lambda: True)
    window._on_start_clicked()
    assert window.controller.state == "tracking"
    assert window._start_btn.isEnabled() is False


def test_start_with_a_planned_task_starts_without_dialog(app_window):
    window, clock, conn = app_window
    db.add_plan_task(conn, TODAY, "Planned work")
    window._on_start_clicked()
    assert window.controller.state == "tracking"


def test_start_blocked_when_already_tracking(app_window):
    window, clock, conn = app_window
    db.add_plan_task(conn, TODAY, "Planned work")
    window._on_start_clicked()
    window._on_start_clicked()  # nudge would pop again if not guarded
    assert window.controller.state == "tracking"


# --- Reset day -----------------------------------------------------------------------

def test_reset_day_deletes_today_after_confirmation(app_window, monkeypatch):
    window, clock, conn = app_window
    window._on_start_clicked()
    clock.advance(2)
    window._on_tick()
    window._on_stop_clicked()
    monkeypatch.setattr(window, "_confirm_reset", lambda: True)
    window._on_reset_day_clicked()
    assert conn.execute("SELECT COUNT(*) FROM usage_interval").fetchone() == (0,)
    assert window._total_card.value.text() == "0m"
    assert "reset" in window.statusBar().currentMessage()


def test_reset_day_keeps_other_days(app_window, monkeypatch):
    window, clock, conn = app_window
    yesterday = TODAY - dt.timedelta(days=1)
    db.record_interval(
        conn,
        dt.datetime(2026, 10, 22, 9, 0, 0),
        dt.datetime(2026, 10, 22, 9, 0, 30),
        "chrome.exe", None, config.CATEGORY_STUDY, 30,
    )
    monkeypatch.setattr(window, "_confirm_reset", lambda: True)
    window._on_reset_day_clicked()
    totals = db.daily_category_seconds(conn, yesterday)
    assert totals[config.CATEGORY_STUDY] == 30


def test_reset_day_cancelled_keeps_data(app_window, monkeypatch):
    window, clock, conn = app_window
    window._on_start_clicked()
    clock.advance(2)
    window._on_tick()
    monkeypatch.setattr(window, "_confirm_reset", lambda: False)
    window._on_reset_day_clicked()
    count = conn.execute("SELECT COUNT(*) FROM usage_interval").fetchone()[0]
    assert count == 1


def test_reset_day_uses_days_current_plan_tasks(app_window, monkeypatch):
    # Plan tasks are the day's plan, not tracked time: a data reset keeps them.
    window, clock, conn = app_window
    db.add_plan_task(conn, TODAY, "Still planned")
    monkeypatch.setattr(window, "_confirm_reset", lambda: True)
    window._on_reset_day_clicked()
    assert len(db.list_plan_tasks(conn, TODAY)) == 1
