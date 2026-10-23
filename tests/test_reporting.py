"""RED: tests for formatting and calculation helpers (reporting.py).

Covers FR-014..FR-015 calculation rules (percent cap), display
formatting (minutes/hours) and the "other non-idle" bucket used by the
weekly report (FR-020).
"""

import pytest

from focus_tracker import config
from focus_tracker import reporting


def catmap(**overrides):
    """A zeroed per-category map, optionally overridden with seconds."""
    totals = {c: 0 for c in config.EDITABLE_CATEGORIES}
    totals[config.CATEGORY_IDLE] = 0
    for key, value in overrides.items():
        totals[key] = value
    return totals


# --- progress percentage (FR-014, FR-015) ---------------------------------------

def test_progress_percent_scales_against_target():
    assert reporting.progress_percent(7200, config.STUDY_TARGET_SECONDS) == 25


def test_progress_percent_caps_at_100():
    assert reporting.progress_percent(40000, config.STUDY_TARGET_SECONDS) == 100
    assert reporting.progress_percent(14400, config.SIDE_HUSTLE_TARGET_SECONDS) == 100


def test_progress_percent_zero_target_is_safe():
    assert reporting.progress_percent(10, 0) == 0


def test_progress_percent_no_data_is_zero():
    assert reporting.progress_percent(0, config.STUDY_TARGET_SECONDS) == 0


# --- formatting (duration as hours and minutes) -----------------------------------

def test_format_seconds_hours_and_minutes():
    assert reporting.format_seconds(3660) == "1h 01m"


def test_format_seconds_exact_hour():
    assert reporting.format_seconds(28800) == "8h 00m"


def test_format_seconds_under_an_hour():
    assert reporting.format_seconds(2700) == "45m"


def test_format_seconds_under_a_minute():
    assert reporting.format_seconds(45) == "45s"


def test_format_seconds_zero():
    assert reporting.format_seconds(0) == "0m"


# --- category buckets (FR-020) ------------------------------------------------------

def test_non_idle_total_excludes_idle():
    seconds = catmap(
        **{config.CATEGORY_STUDY: 100, config.CATEGORY_IDLE: 999}
    )
    assert reporting.non_idle_total(seconds) == 100


def test_other_seconds_merges_other_categories():
    seconds = catmap(
        **{config.CATEGORY_PERSONAL: 10,
           config.CATEGORY_ENTERTAINMENT: 20,
           config.CATEGORY_UNCLASSIFIED: 30,
           config.CATEGORY_STUDY: 999,
           config.CATEGORY_IDLE: 999}
    )
    assert reporting.other_seconds(seconds) == 60


# --- goal card helpers (BR-01, BR-02) --------------------------------------------------

def test_goal_summary_for_card():
    card = reporting.goal_summary(
        config.CATEGORY_STUDY,
        actual_seconds=7200,
        target_seconds=config.STUDY_TARGET_SECONDS,
    )
    assert card["percent"] == 25
    assert card["actual_display"] == "2h 00m"
    assert card["target_display"] == "8h 00m"


def test_goal_summary_with_no_data():
    card = reporting.goal_summary(
        config.CATEGORY_SIDE_HUSTLE,
        actual_seconds=0,
        target_seconds=config.SIDE_HUSTLE_TARGET_SECONDS,
    )
    assert card["percent"] == 0
    assert card["actual_display"] == "0m"
    assert card["target_display"] == "4h 00m"
