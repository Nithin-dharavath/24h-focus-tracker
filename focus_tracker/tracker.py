"""Foreground tracking state machine (FR-002..FR-009, NFR-07).

The controller owns Start / Pause / Resume / Stop semantics and the
short-interval logic executed on each poll tick. It depends on three
injected callables so it is fully testable without Windows:

    clock()          -> datetime.datetime  (current local time)
    idle_seconds()   -> float              (Windows input idle seconds)
    foreground()     -> (app_name, window_title) or None

The UI layer drives ``tick()`` from a QTimer; tests call it directly
with a fake clock so behavior is deterministic.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from . import config
from . import database as db

NOT_TRACKING = "not_tracking"
TRACKING = "tracking"
PAUSED = "paused"


class TrackingController:
    """Records short usage intervals between Start and Stop."""

    def __init__(
        self,
        conn,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
        idle_seconds: Callable[[], float] = lambda: 0.0,
        foreground: Callable[[], Optional[tuple[str, str]]] = lambda: (config.UNKNOWN_APP_NAME, ""),
    ):
        self._conn = conn
        self._clock = clock
        self._idle_seconds = idle_seconds
        self._foreground = foreground
        self._state = NOT_TRACKING
        self._baseline: dt.datetime | None = None

    # --- state -------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    # --- tracking control (FR-003..FR-006) -----------------------------------------

    def start(self) -> bool:
        """Begin tracking from a fresh baseline. Refuses if already active."""
        if self._state != NOT_TRACKING:
            return False
        self._baseline = self._clock()
        self._state = TRACKING
        return True

    def pause(self) -> bool:
        """Save any eligible pending interval, stop accrual, mark paused."""
        if self._state != TRACKING:
            return False
        self._finalize()
        self._baseline = None
        self._state = PAUSED
        return True

    def resume(self) -> bool:
        """Continue tracking from a fresh baseline without the paused gap."""
        if self._state != PAUSED:
            return False
        self._baseline = self._clock()
        self._state = TRACKING
        return True

    def stop(self) -> bool:
        """Finalize the pending interval (if any) and stop tracking."""
        if self._state == NOT_TRACKING:
            return False
        if self._state == TRACKING:
            self._finalize()
        self._baseline = None
        self._state = NOT_TRACKING
        return True

    # --- polling (FR-007..FR-009) ----------------------------------------------------

    def tick(self) -> dict | None:
        """Record one short interval. Returns the stored record, or None."""
        if self._state != TRACKING:  # FR-002: nothing before Start or after Stop
            return None
        now = self._clock()
        assert self._baseline is not None
        elapsed = (now - self._baseline).total_seconds()
        if elapsed < 1:  # nothing meaningful yet; avoid zero-second rows
            self._baseline = now
            return None
        if elapsed > config.LONG_GAP_SECONDS:  # FR-009: discard long gaps
            self._baseline = now
            return None
        record = self._classify_and_record(self._baseline, now)
        self._baseline = now
        return record

    # --- internals ----------------------------------------------------------------------

    def _finalize(self) -> dict | None:
        """Save the pending interval at Pause/Stop if it is still eligible."""
        if self._baseline is None:
            return None
        now = self._clock()
        elapsed = (now - self._baseline).total_seconds()
        if elapsed < 1:
            return None
        if elapsed > config.LONG_GAP_SECONDS:
            return None  # a long lapse is never saved as app usage
        return self._classify_and_record(self._baseline, now)

    def _classify_and_record(
        self, started_at: dt.datetime, ended_at: dt.datetime
    ) -> dict:
        """Categorize and persist the interval, per FR-008 and FR-010."""
        if self._idle_seconds() >= config.IDLE_THRESHOLD_SECONDS:
            app_name = config.IDLE_APP_NAME
            window_title = None
            category = config.CATEGORY_IDLE
        else:
            observed = self._foreground() or (config.UNKNOWN_APP_NAME, "")
            app_name, window_title = observed
            category = db.get_category(self._conn, app_name)
        seconds = int((ended_at - started_at).total_seconds())
        db.record_interval(
            self._conn,
            started_at,
            ended_at,
            app_name,
            window_title,
            category,
            seconds,
        )
        return {
            "started_at": started_at,
            "ended_at": ended_at,
            "app_name": app_name,
            "window_title": window_title,
            "category": category,
            "seconds": seconds,
        }


# --- Windows providers ---------------------------------------------------------------


def _windows_idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input (Windows API)."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("dwTime", ctypes.c_uint),  # tick count in ms
        ]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    current_tick = ctypes.windll.kernel32.GetTickCount()
    elapsed_ms = (current_tick - info.dwTime) & 0xFFFFFFFF  # wraparound-safe
    return elapsed_ms / 1000.0


def _windows_foreground() -> Optional[tuple[str, str]]:
    """Current foreground executable name and window title, or None.

    Uses ctypes for the window handle and psutil for the process name.
    Returns None when no foreground window is available, so callers can
    apply the safe fallback (edge-case table, FRD section 10).
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    # Window title (may contain private text; stays in the local DB only).
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    title = buffer.value

    # Owning process name.
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return (config.UNKNOWN_APP_NAME, title)
    try:
        import psutil

        app_name = psutil.Process(pid.value).name().lower()
    except Exception:  # noqa: BLE001 - access denied / gone process
        app_name = config.UNKNOWN_APP_NAME
    if not app_name:
        app_name = config.UNKNOWN_APP_NAME
    return (app_name, title)


def default_providers():
    """Windows-backed provider callables for production use (NFR-01)."""
    return _windows_idle_seconds, _windows_foreground
