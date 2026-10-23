"""Formatting and calculation helpers for reports.

Pure functions only — no database or Qt imports — so they can be unit
tested in isolation (FR-014..FR-020 calculation rules).
"""

from . import config


def progress_percent(actual_seconds: int, target_seconds: int) -> int:
    """Actual / target * 100, capped at 100 for display (FRD section 7)."""
    if target_seconds <= 0 or actual_seconds <= 0:
        return 0
    return min(100, round(actual_seconds / target_seconds * 100))


def format_seconds(seconds: int) -> str:
    """Human duration: 'Hh MMm' for long spans, seconds for short ones."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s" if seconds > 0 else "0m"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def non_idle_total(category_seconds: dict[str, int]) -> int:
    """Total tracked time excluding Idle (pie-chart/card rule, FRD section 7)."""
    return sum(
        seconds
        for category, seconds in category_seconds.items()
        if category != config.CATEGORY_IDLE
    )


def other_seconds(category_seconds: dict[str, int]) -> int:
    """Merged Personal + Entertainment + Unclassified bucket (FR-020)."""
    return sum(category_seconds.get(c, 0) for c in config.OTHER_CATEGORIES)


def goal_summary(
    category: str, actual_seconds: int, target_seconds: int
) -> dict:
    """Values for a daily goal card (BR-01, BR-02)."""
    return {
        "category": category,
        "percent": progress_percent(actual_seconds, target_seconds),
        "actual_seconds": int(actual_seconds),
        "target_seconds": int(target_seconds),
        "actual_display": format_seconds(actual_seconds),
        "target_display": format_seconds(target_seconds),
    }
