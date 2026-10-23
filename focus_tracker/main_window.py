"""Main window UI (PySide6) for 24H Focus Tracker (FRD section 5)."""

from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import charts
from . import config
from . import database as db
from . import reporting
from .tracker import (
    NOT_TRACKING,
    PAUSED,
    TRACKING,
    TrackingController,
    default_providers,
)

STATUS_TEXT = {
    NOT_TRACKING: "Not tracking",
    TRACKING: "Tracking",
    PAUSED: "Paused",
}

STATUS_CHIP_STYLE = {
    NOT_TRACKING: "background:#e2e8f0; color:#52606d;",
    TRACKING: "background:#dcfce7; color:#166534;",
    PAUSED: "background:#fef3c7; color:#92400e;",
}


class _GoalCard:
    """Daily metric card with a progress bar (BR-01, BR-02)."""

    def __init__(self, category: str, target_seconds: int):
        self.category = category
        self.target_seconds = target_seconds
        self.frame = QFrame(objectName="card")
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        layout.addWidget(QLabel(category, objectName="card_title"))
        self.value = QLabel("0m", objectName="card_value")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.sub = QLabel("", objectName="card_sub")
        layout.addWidget(self.value)
        layout.addWidget(self.progress)
        layout.addWidget(self.sub)
        layout.addStretch(1)

    def update(self, summary: dict) -> None:
        self.value.setText(summary["actual_display"])
        self.progress.setValue(summary["percent"])
        self.sub.setText(
            f"of {summary['target_display']} — {summary['percent']}% of daily goal"
        )


class _ValueCard:
    """Simple daily metric card without a goal (total tracked, idle)."""

    def __init__(self, title: str, sub_text: str):
        self.frame = QFrame(objectName="card")
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        layout.addWidget(QLabel(title, objectName="card_title"))
        self.value = QLabel("0m", objectName="card_value")
        self.sub = QLabel(sub_text, objectName="card_sub")
        layout.addWidget(self.value)
        layout.addWidget(self.sub)
        layout.addStretch(1)

    def update(self, display: str) -> None:
        self.value.setText(display)


class MainWindow(QMainWindow):
    """Single-window MVP presentation layer.

    Layout per FRD section 5: header with tracking status, tracking
    controls, four daily metric cards, and tabs for Today, Weekly
    report, and App categories. Injecting ``controller`` and ``today``
    keeps the window testable without real Windows state or the real
    system clock.
    """

    def __init__(
        self,
        conn,
        controller: Optional[TrackingController] = None,
        today: Callable[[], dt.date] = dt.date.today,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._conn = conn
        self._today = today
        if controller is None:
            idle_seconds, foreground = default_providers()
            controller = TrackingController(
                conn, idle_seconds=idle_seconds, foreground=foreground,
            )
        self._controller = controller
        self.setWindowTitle(config.APP_NAME)
        self.resize(1080, 760)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._apply_state()
        self.refresh_dashboard()
        self._refresh_categories()

        self._timer = QTimer(self)
        self._timer.setInterval(config.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ UI build

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_controls())

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._study_card = _GoalCard(config.CATEGORY_STUDY, config.STUDY_TARGET_SECONDS)
        self._side_card = _GoalCard(
            config.CATEGORY_SIDE_HUSTLE, config.SIDE_HUSTLE_TARGET_SECONDS,
        )
        self._total_card = _ValueCard(
            "Total tracked", "all non-idle categories",
        )
        self._idle_card = _ValueCard(
            "Idle", "no keyboard or mouse input",
        )
        for card in (self._study_card, self._side_card, self._total_card, self._idle_card):
            cards.addWidget(card.frame, 1)
        root.addLayout(cards)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_today_tab(), "Today")
        self.tabs.addTab(self._build_weekly_tab(), "Weekly report")
        self.tabs.addTab(self._build_categories_tab(), "App categories")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        disclaimer = QLabel(config.DISCLAIMER, objectName="disclaimer")
        disclaimer.setWordWrap(True)
        root.addWidget(disclaimer)

        self.statusBar().showMessage("")

    def _build_header(self) -> QWidget:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        layout.addLayout(text)
        text.addWidget(QLabel(config.APP_NAME, objectName="app_title"))
        text.addWidget(QLabel(config.SUBTITLE, objectName="app_subtitle"))
        layout.addStretch(1)
        self._status_chip = QLabel(STATUS_TEXT[NOT_TRACKING], objectName="status_chip")
        self._status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_chip)
        return frame

    def _build_controls(self) -> QWidget:
        bar = QFrame()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._start_btn = QPushButton("Start", objectName="primary")
        self._start_btn.clicked.connect(self._on_start_clicked)
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.clicked.connect(self._on_pause_resume_clicked)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self._start_btn)
        layout.addWidget(self._pause_btn)
        layout.addWidget(self._stop_btn)
        layout.addStretch(1)
        return bar

    def _build_today_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(8)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        study_col = QVBoxLayout()
        study_col.addWidget(QLabel("Daily goals", objectName="section_label"))
        self._bar_chart = charts.DailyGoalBarChart()
        study_col.addWidget(self._bar_chart, 1)
        pie_col = QVBoxLayout()
        pie_col.addWidget(QLabel("Category mix", objectName="section_label"))
        self._pie_chart = charts.CategoryPieChart()
        pie_col.addWidget(self._pie_chart, 1)
        charts_row.addLayout(study_col, 1)
        charts_row.addLayout(pie_col, 1)
        layout.addLayout(charts_row, 5)

        layout.addWidget(
            QLabel("Applications used today", objectName="section_label")
        )
        self._usage_table = QTableWidget(0, 3)
        self._usage_table.setHorizontalHeaderLabels(
            ["Application", "Category", "Duration"]
        )
        header = self._usage_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._usage_table.verticalHeader().setVisible(False)
        self._usage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._usage_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._usage_table.setAlternatingRowColors(True)
        layout.addWidget(self._usage_table, 3)
        return tab

    def _build_weekly_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(8)
        self._weekly_chart = charts.WeeklyStackedChart()
        layout.addWidget(self._weekly_chart, 5)
        self._weekly_table = QTableWidget(0, 4)
        self._weekly_table.setHorizontalHeaderLabels(
            ["Date", "Study", "Side Hustle", "Other (non-idle)"]
        )
        header = self._weekly_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._weekly_table.verticalHeader().setVisible(False)
        self._weekly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._weekly_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._weekly_table.setAlternatingRowColors(True)
        layout.addWidget(self._weekly_table, 3)
        return tab

    def _build_categories_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(14)

        self._categories_table = QTableWidget(0, 2)
        self._categories_table.setHorizontalHeaderLabels(["Application", "Category"])
        header = self._categories_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._categories_table.verticalHeader().setVisible(False)
        self._categories_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._categories_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._categories_table.setAlternatingRowColors(True)
        self._categories_table.itemSelectionChanged.connect(self._sync_category_combo)
        layout.addWidget(self._categories_table, 3)

        side_frame = QFrame(objectName="card")
        side = QVBoxLayout(side_frame)
        side.setContentsMargins(14, 12, 14, 12)
        side.setSpacing(8)
        instructions = QLabel(
            "Applications seen while tracking appear here. Pick a category for "
            "the selected application and save it — future intervals use the "
            "new category.",
            objectName="card_sub",
        )
        instructions.setWordWrap(True)
        side.addWidget(instructions)
        self._category_combo = QComboBox()
        for category in config.EDITABLE_CATEGORIES:
            self._category_combo.addItem(category)
        side.addWidget(self._category_combo)
        save_btn = QPushButton("Save category", objectName="primary")
        save_btn.clicked.connect(self._on_save_category_clicked)
        side.addWidget(save_btn)
        side.addStretch(1)
        layout.addWidget(side_frame, 2)
        return tab

    # ------------------------------------------------------------------ events

    def _on_tick(self) -> None:
        record = self._controller.tick()
        if record:
            self.refresh_dashboard()

    def _on_tab_changed(self, index: int) -> None:
        """Keep the categories editor current with newly seen apps (FR-011)."""
        if index == 2:
            self._refresh_categories()

    def _on_start_clicked(self) -> None:
        if self._controller.start():
            self._timer.start()
            self._apply_state()
        else:
            self._warn("Tracking is already running.")

    def _on_pause_resume_clicked(self) -> None:
        if self._controller.state == TRACKING:
            if self._controller.pause():
                self._timer.stop()  # FR-004: pause stops polling
                self._apply_state()
        elif self._controller.state == PAUSED:
            if self._controller.resume():
                self._timer.start()
                self._apply_state()
        else:
            self._warn("Nothing is being tracked right now — press Start first.")

    def _on_stop_clicked(self) -> None:
        if self._controller.stop():
            self._timer.stop()
            self._apply_state()
            self.refresh_dashboard()
        else:
            self._warn("Tracking is already stopped.")

    def _on_save_category_clicked(self) -> None:
        app_name = self._selected_app_name()
        if not app_name:
            self._warn("Select an application in the table first.")
            return
        category = self._category_combo.currentText()
        try:
            db.set_category(self._conn, app_name, category)
        except ValueError as exc:  # defensive; combo only offers valid values
            self._warn(str(exc))
            return
        self._refresh_categories()
        self.refresh_dashboard()
        self.statusBar().showMessage(
            f"Future {app_name} time will be tracked as {category}.", 6000,
        )

    def _warn(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming convention
        """Stop polling, finalize the pending interval, close the DB (FR-022)."""
        self._timer.stop()
        self._controller.stop()
        self._conn.close()
        event.accept()

    # ------------------------------------------------------------------ helpers

    @property
    def controller(self) -> TrackingController:
        """Exposed for tests and future tooling."""
        return self._controller

    def _apply_state(self) -> None:
        state = self._controller.state
        self._status_chip.setText(STATUS_TEXT[state])
        self._status_chip.setStyleSheet(
            f"QLabel#status_chip {{ {STATUS_CHIP_STYLE[state]} }}"
        )
        tracking = state == TRACKING
        paused = state == PAUSED
        self._start_btn.setEnabled(state == NOT_TRACKING)
        self._pause_btn.setEnabled(tracking or paused)
        self._pause_btn.setText("Resume" if paused else "Pause")
        self._stop_btn.setEnabled(tracking or paused)

    def _selected_app_name(self) -> Optional[str]:
        row = self._categories_table.currentRow()
        if row < 0:
            return None
        item = self._categories_table.item(row, 0)
        return item.text() if item else None

    def _sync_category_combo(self) -> None:
        row = self._categories_table.currentRow()
        if row < 0:
            return
        item = self._categories_table.item(row, 1)
        if item:
            index = self._category_combo.findText(item.text())
            if index >= 0:
                self._category_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------ refresh

    def refresh_dashboard(self) -> None:
        """Re-read today's totals; populate cards, charts and tables (FR-013)."""
        day = self._today()
        totals = db.daily_category_seconds(self._conn, day)

        self._study_card.update(reporting.goal_summary(
            config.CATEGORY_STUDY,
            totals[config.CATEGORY_STUDY],
            config.STUDY_TARGET_SECONDS,
        ))
        self._side_card.update(reporting.goal_summary(
            config.CATEGORY_SIDE_HUSTLE,
            totals[config.CATEGORY_SIDE_HUSTLE],
            config.SIDE_HUSTLE_TARGET_SECONDS,
        ))
        self._total_card.update(
            reporting.format_seconds(reporting.non_idle_total(totals))
        )
        self._idle_card.update(
            reporting.format_seconds(totals[config.CATEGORY_IDLE])
        )

        self._bar_chart.refresh(totals)
        self._pie_chart.refresh(totals)
        self._populate_usage_table(day)
        self._refresh_weekly()

    def _populate_usage_table(self, day: dt.date) -> None:
        rows = db.app_usage_for_day(self._conn, day)
        self._usage_table.setRowCount(len(rows))
        for i, (app_name, category, seconds) in enumerate(rows):
            self._usage_table.setItem(i, 0, QTableWidgetItem(app_name))
            self._usage_table.setItem(i, 1, QTableWidgetItem(category))
            self._usage_table.setItem(
                i, 2, QTableWidgetItem(reporting.format_seconds(seconds))
            )

    def _refresh_weekly(self) -> None:
        summary = db.weekly_summary(self._conn, self._today())
        self._weekly_chart.refresh(summary)
        self._weekly_table.setRowCount(len(summary))
        for i, row in enumerate(summary):
            categories = row["categories"]
            self._weekly_table.setItem(
                i, 0, QTableWidgetItem(row["date"].strftime("%a %d %b"))
            )
            self._weekly_table.setItem(
                i, 1,
                QTableWidgetItem(reporting.format_seconds(
                    categories[config.CATEGORY_STUDY])),
            )
            self._weekly_table.setItem(
                i, 2,
                QTableWidgetItem(reporting.format_seconds(
                    categories[config.CATEGORY_SIDE_HUSTLE])),
            )
            self._weekly_table.setItem(
                i, 3,
                QTableWidgetItem(reporting.format_seconds(
                    reporting.other_seconds(categories))),
            )

    def _refresh_categories(self) -> None:
        apps = db.list_known_apps(self._conn)
        self._categories_table.setRowCount(len(apps))
        for i, (app_name, category) in enumerate(apps):
            app_item = QTableWidgetItem(app_name)
            cat_item = QTableWidgetItem(category)
            selectable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            app_item.setFlags(selectable)
            cat_item.setFlags(selectable)
            self._categories_table.setItem(i, 0, app_item)
            self._categories_table.setItem(i, 1, cat_item)


STYLESHEET = """
QMainWindow { background:#f4f6f9; }
QLabel#app_title { color:#1f2933; font-size:19px; font-weight:700; }
QLabel#app_subtitle { color:#52606d; font-size:12px; }
QLabel#status_chip { border-radius:11px; padding:4px 14px; font-weight:600; font-size:12px; }
QFrame#card { background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; }
QLabel#card_title { color:#52606d; font-size:12px; font-weight:600; }
QLabel#card_value { color:#1f2933; font-size:20px; font-weight:700; }
QLabel#card_sub { color:#52606d; font-size:11px; }
QLabel#section_label { color:#52606d; font-size:12px; font-weight:600; }
QLabel#disclaimer { color:#7b8794; font-size:10px; }
QProgressBar { border:none; background:#eef2f7; border-radius:3px; }
QProgressBar::chunk { background:#4f46e5; border-radius:3px; }
QPushButton { padding:7px 20px; border-radius:8px; border:1px solid #e2e8f0;
  background:#ffffff; color:#1f2933; font-weight:600; }
QPushButton:hover { background:#f1f4f9; }
QPushButton:disabled { color:#9aa5b1; background:#f4f6f9; }
QPushButton#primary { background:#4f46e5; color:#ffffff; border:none; }
QPushButton#primary:hover { background:#4338ca; }
QPushButton#primary:disabled { background:#c7caf8; color:#f1f2ff; }
QTabWidget::pane { border:1px solid #e2e8f0; border-radius:10px; background:#ffffff; top:-1px; }
QTabBar::tab { padding:8px 18px; color:#52606d; background:transparent;
  border:1px solid transparent; border-radius:8px; margin-right:4px; }
QTabBar::tab:selected { color:#1f2933; background:#eef2ff;
  border:1px solid #e2e8f0; font-weight:600; }
QTableWidget { border:none; background:#ffffff; gridline-color:#eef2f7; }
QTableWidget::item { padding:4px 6px; }
QHeaderView::section { background:#f8fafc; color:#52606d; font-weight:600;
  border:none; border-bottom:1px solid #e2e8f0; padding:6px 8px; }
QComboBox { padding:6px 10px; border:1px solid #e2e8f0; border-radius:8px;
  background:#ffffff; color:#1f2933; }
QStatusBar { color:#52606d; }
QToolTip { background:#ffffff; color:#1f2933; border:1px solid #e2e8f0; }
"""

