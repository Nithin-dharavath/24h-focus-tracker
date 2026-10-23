"""UI tests for the main window (TC-01..TC-05, TC-09, TC-12, TC-13, TC-16).

Runs headless (QT_QPA_PLATFORM=offscreen via conftest) with an injected
controller and fixed today's date, so no real tracking state is used.
"""

import datetime as dt
import sqlite3

import pytest

from PySide6.QtCore import QTimer

from focus_tracker import config
from focus_tracker import database as db
from focus_tracker.main_window import MainWindow
from focus_tracker.tracker import TrackingController


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
    yield window, clock, conn
    window._timer.stop()
    conn.close()


def test_launches_not_tracking(app_window):
    window, clock, conn = app_window
    assert window._status_chip.text() == "Not tracking"
    assert window._start_btn.isEnabled()
    assert not window._pause_btn.isEnabled()
    assert not window._stop_btn.isEnabled()
    assert window._study_card.value.text() == "0m"
    assert conn.execute("SELECT COUNT(*) FROM usage_interval").fetchone() == (0,)


def test_start_updates_status_and_buttons(app_window):
    window, clock, conn = app_window
    window._on_start_clicked()
    assert window._status_chip.text() == "Tracking"
    assert not window._start_btn.isEnabled()
    assert window._pause_btn.isEnabled()
    assert window._pause_btn.text() == "Pause"
    assert window._stop_btn.isEnabled()


def test_dashboard_updates_after_tick(app_window):
    window, clock, conn = app_window
    db.set_category(conn, "chrome.exe", config.CATEGORY_STUDY)
    window._on_start_clicked()
    clock.advance(2)
    window._on_tick()

    assert window._study_card.value.text() == "2s"
    assert window._total_card.value.text() == "2s"
    assert window._idle_card.value.text() == "0m"
    assert window._usage_table.rowCount() == 1
    assert window._usage_table.item(0, 0).text() == "chrome.exe"
    assert window._usage_table.item(0, 1).text() == config.CATEGORY_STUDY
    assert window._usage_table.item(0, 2).text() == "2s"
    assert window._bar_chart.has_data is True
    assert window._pie_chart.has_data is True


def test_tick_with_no_data_still_renders(app_window):
    window, clock, conn = app_window
    window.refresh_dashboard()
    assert window._study_card.value.text() == "0m"
    assert window._pie_chart.has_data is False
    assert window._usage_table.rowCount() == 0


def test_pause_resume_cycle(app_window):
    window, clock, conn = app_window
    window._on_start_clicked()
    window._on_pause_resume_clicked()
    assert window._status_chip.text() == "Paused"
    assert window._pause_btn.text() == "Resume"
    assert not window._timer.isActive()
    window._on_pause_resume_clicked()
    assert window._status_chip.text() == "Tracking"
    assert window._pause_btn.text() == "Pause"
    assert window._timer.isActive()
    assert window._timer.interval() == config.POLL_INTERVAL_MS


def test_pause_when_stopped_shows_message(app_window):
    window, clock, conn = app_window
    window._on_pause_resume_clicked()
    assert "Start" in window.statusBar().currentMessage()
    assert window._status_chip.text() == "Not tracking"


def test_stop_finalizes_pending_interval(app_window):
    window, clock, conn = app_window
    window._on_start_clicked()
    clock.advance(3)
    window._on_stop_clicked()
    assert window._status_chip.text() == "Not tracking"
    assert not window._stop_btn.isEnabled()
    rows = conn.execute("SELECT seconds FROM usage_interval").fetchall()
    assert rows == [(3,)]
    assert window._total_card.value.text() == "3s"


def test_weekly_table_has_seven_chronological_dates(app_window):
    window, clock, conn = app_window
    window.refresh_dashboard()
    assert window._weekly_table.rowCount() == 7
    first = window._weekly_table.item(0, 0).text()
    last = window._weekly_table.item(6, 0).text()
    assert first == "Sat 17 Oct"
    assert last == "Fri 23 Oct"


def test_category_editor_saves_rule(app_window):
    window, clock, conn = app_window
    window._on_start_clicked()
    clock.advance(2)
    window._on_tick()
    window.tabs.setCurrentIndex(2)  # opening the tab refreshes the list
    window._categories_table.setCurrentCell(0, 0)
    assert window._selected_app_name() == "chrome.exe"
    window._category_combo.setCurrentText(config.CATEGORY_STUDY)
    window._on_save_category_clicked()
    assert db.get_category(conn, "chrome.exe") == config.CATEGORY_STUDY


def test_save_category_without_selection_warns(app_window):
    window, clock, conn = app_window
    window._on_save_category_clicked()
    assert "Select an application" in window.statusBar().currentMessage()


def test_empty_day_state(qapp):
    conn = db.open_database(":memory:")
    clock = FakeClock(NOW)
    controller = TrackingController(
        conn, clock=clock, idle_seconds=lambda: 0.0,
        foreground=lambda: ("chrome.exe", "Docs"),
    )
    window = MainWindow(
        conn, controller=controller, today=lambda: dt.date(2026, 11, 2),
    )
    window.refresh_dashboard()
    assert window._study_card.value.text() == "0m"
    assert window._total_card.value.text() == "0m"
    assert window._bar_chart.has_data is True  # targets-only valid empty view
    assert window._pie_chart.has_data is False  # empty-state message shown
    assert window._usage_table.rowCount() == 0
    window._timer.stop()
    conn.close()


def test_close_stops_timer_finalizes_and_closes_db(qapp, tmp_path):
    conn = db.open_database(str(tmp_path / "close.sqlite3"))
    clock = FakeClock(NOW)
    controller = TrackingController(
        conn, clock=clock, idle_seconds=lambda: 0.0,
        foreground=lambda: ("chrome.exe", "Docs"),
    )
    window = MainWindow(conn, controller=controller, today=lambda: TODAY)
    window._on_start_clicked()
    clock.advance(4)
    window.close()

    assert not window._timer.isActive()
    assert window.controller.state == "not_tracking"
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    # Data written at close survives on disk (persisted across restarts, TC-14).
    reopened = db.open_database(str(tmp_path / "close.sqlite3"))
    try:
        rows = reopened.execute("SELECT seconds FROM usage_interval").fetchall()
        assert rows == [(4,)]
    finally:
        reopened.close()
