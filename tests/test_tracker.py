"""RED: tests for the tracking controller (tracker.py).

Covers FR-002..FR-011, FR-007..FR-009 and TC-02..TC-08 using an
in-memory database and injected clock / idle / foreground providers so
no real Windows state is needed.
"""

import datetime as dt

import pytest

from focus_tracker import config
from focus_tracker import database as db
from focus_tracker import tracker
from focus_tracker.tracker import TrackingController


class FakeClock:
    """Controllable clock used to script polling sequences."""

    def __init__(self, start):
        self._now = start

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += dt.timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return FakeClock(dt.datetime(2026, 10, 23, 10, 0, 0))


def make_controller(clock, idle_seconds=0.0, foreground=("chrome.exe", "Docs - Chrome")):
    conn = db.open_database(":memory:")
    controller = TrackingController(
        conn,
        clock=clock,
        idle_seconds=lambda: idle_seconds,
        foreground=lambda: foreground,
    )
    return controller, conn


def recorded_intervals(conn):
    rows = conn.execute(
        "SELECT started_at, ended_at, app_name, category, seconds"
        " FROM usage_interval ORDER BY id"
    ).fetchall()
    return rows


# --- state machine (FR-002..FR-005) --------------------------------------------

def test_controller_starts_not_tracking():
    controller, _ = make_controller(FakeClock(dt.datetime(2026, 10, 23, 10, 0, 0)))
    assert controller.state == tracker.NOT_TRACKING


def test_tick_before_start_records_nothing(clock):
    controller, conn = make_controller(clock)
    clock.advance(10)
    controller.tick()
    assert recorded_intervals(conn) == []


def test_start_transitions_to_tracking(clock):
    controller, _ = make_controller(clock)
    assert controller.start() is True
    assert controller.state == tracker.TRACKING


def test_first_tick_after_two_seconds_records_interval(clock):
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    assert len(rows) == 1
    started_at, ended_at, app_name, category, seconds = rows[0]
    assert started_at == "2026-10-23T10:00:00"
    assert ended_at == "2026-10-23T10:00:02"
    assert app_name == "chrome.exe"
    assert category == config.CATEGORY_UNCLASSIFIED
    assert seconds == 2


def test_tick_right_after_start_records_nothing(clock):
    controller, conn = make_controller(clock)
    controller.start()
    controller.tick()
    assert recorded_intervals(conn) == []


def test_start_while_tracking_is_refused(clock):
    controller, _ = make_controller(clock)
    controller.start()
    assert controller.start() is False
    assert controller.state == tracker.TRACKING


def test_start_while_paused_is_refused(clock):
    controller, _ = make_controller(clock)
    controller.start()
    controller.pause()
    assert controller.start() is False
    assert controller.state == tracker.PAUSED


# --- idle detection (FR-008, TC-07) ----------------------------------------------

def test_idle_threshold_makes_interval_idle(clock):
    controller, conn = make_controller(clock, idle_seconds=90.0)
    controller.start()
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    assert len(rows) == 1
    assert rows[0][2] == config.IDLE_APP_NAME
    assert rows[0][3] == config.CATEGORY_IDLE


def test_below_idle_threshold_records_foreground_app(clock):
    controller, conn = make_controller(clock, idle_seconds=10.0)
    controller.start()
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    assert rows[0][2] == "chrome.exe"
    assert rows[0][3] == config.CATEGORY_UNCLASSIFIED


# --- long gap handling (FR-009, TC-08) ----------------------------------------------

def test_long_gap_is_discarded_and_baseline_resets(clock):
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(2)
    controller.tick()          # records 2 s
    clock.advance(120)
    controller.tick()          # 120 s gap: must be discarded, not assigned
    rows = recorded_intervals(conn)
    assert len(rows) == 1      # only the first tick produced a row
    # baseline reset: a normal tick afterwards records a short interval again
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    assert len(rows) == 2
    assert rows[1][4] == 2     # new interval covers only 2 s, not the gap


# --- category rules (FR-010, FR-011, TC-09) -----------------------------------------

def test_saved_rule_is_applied_to_new_intervals(clock):
    controller, conn = make_controller(clock)
    db.set_category(conn, "chrome.exe", config.CATEGORY_STUDY)
    controller.start()
    clock.advance(2)
    controller.tick()
    assert recorded_intervals(conn)[0][3] == config.CATEGORY_STUDY


# --- pause / resume (FR-004, FR-005, TC-03, TC-04) ------------------------------------

def test_pause_sets_paused_state_and_saves_pending_interval(clock):
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(2)
    controller.tick()            # saves the 2 s interval
    clock.advance(1)             # 1 s pending when the user presses pause
    assert controller.pause() is True
    assert controller.state == tracker.PAUSED
    rows = recorded_intervals(conn)
    assert len(rows) == 2
    assert rows[1][4] == 1       # pending interval saved at pause time


def test_tick_while_paused_records_nothing(clock):
    controller, conn = make_controller(clock)
    controller.start()
    controller.pause()
    clock.advance(300)
    controller.tick()
    assert recorded_intervals(conn) == []


def test_resume_continues_without_counting_paused_gap(clock):
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(2)
    controller.tick()            # 2 s recorded
    clock.advance(1)
    controller.pause()           # saves 1 s pending gap-less interval
    clock.advance(600)           # paused gap must never accrue
    controller.resume()
    assert controller.state == tracker.TRACKING
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    # only the 2 s post-resume interval exists; the 600 s pause is excluded
    assert rows[-1][4] == 2
    totals = db.daily_category_seconds(conn, dt.date(2026, 10, 23))
    assert totals[config.CATEGORY_UNCLASSIFIED] == 2 + 1 + 2


def test_pause_while_stopped_is_refused(clock):
    controller, _ = make_controller(clock)
    assert controller.pause() is False
    assert controller.state == tracker.NOT_TRACKING


def test_pause_when_available_categorizes_as_idle(clock):
    # At pause time the pending interval is short but the user has been idle.
    controller, conn = make_controller(clock, idle_seconds=120.0)
    controller.start()
    clock.advance(1)
    controller.pause()
    rows = recorded_intervals(conn)
    assert len(rows) == 1
    assert rows[0][3] == config.CATEGORY_IDLE


# --- stop (FR-006, TC-05) --------------------------------------------------------------

def test_stop_finalizes_pending_interval_and_transitions(clock):
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(3)             # no tick yet: 3 s pending when stopping
    assert controller.stop() is True
    assert controller.state == tracker.NOT_TRACKING
    rows = recorded_intervals(conn)
    assert len(rows) == 1
    assert rows[0][4] == 3


def test_tick_after_stop_records_nothing(clock):
    controller, conn = make_controller(clock)
    controller.start()
    controller.stop()
    clock.advance(10)
    controller.tick()
    assert recorded_intervals(conn) == []


def test_stop_while_paused_records_no_gap(clock):
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(2)
    controller.tick()
    controller.pause()
    clock.advance(500)
    controller.stop()
    rows = recorded_intervals(conn)
    assert len(rows) == 1        # only the pre-pause 2 s interval
    assert controller.state == tracker.NOT_TRACKING


def test_stop_while_stopped_is_refused(clock):
    controller, _ = make_controller(clock)
    assert controller.stop() is False


# --- resilience (edge case table) --------------------------------------------------------

def test_unavailable_foreground_falls_back_to_unknown(clock):
    controller, conn = make_controller(clock, foreground=None)
    controller.start()
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    assert rows[0][2] == config.UNKNOWN_APP_NAME
    assert rows[0][3] == config.CATEGORY_UNCLASSIFIED


def test_controller_uses_injected_state_accross_sequences(clock):
    # TC-06 style sequence: multiple ticks in a row, each its own interval.
    controller, conn = make_controller(clock)
    controller.start()
    clock.advance(2)
    controller.tick()
    clock.advance(2)
    controller.tick()
    rows = recorded_intervals(conn)
    assert len(rows) == 2
    assert rows[0][0] == "2026-10-23T10:00:00"
    assert rows[1][0] == "2026-10-23T10:00:02"
