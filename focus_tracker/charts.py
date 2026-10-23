"""Matplotlib chart widgets embedded in PySide6 (FR-016..FR-018, FR-020).

Custom-styled figures shared by the Today and Weekly tabs. Every chart
supports an empty-state message so pages never render blank axes with
data missing (FR-018).
"""

from __future__ import annotations

import matplotlib
matplotlib.use("qtagg", force=True)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from . import config
from . import reporting  # noqa: E402

# Cohesive palette shared with the window stylesheet.
COLOR_STUDY = "#4f46e5"
COLOR_SIDE_HUSTLE = "#0891b2"
COLOR_PERSONAL = "#7c3aed"
COLOR_ENTERTAINMENT = "#f59e0b"
COLOR_UNCLASSIFIED = "#94a3b8"
COLOR_TARGET = "#cbd5e1"
COLOR_OTHER = "#64748b"
COLOR_TEXT = "#1f2933"
COLOR_MUTED = "#52606d"
COLOR_GRID = "#e2e8f0"

CHART_COLORS = {
    config.CATEGORY_STUDY: COLOR_STUDY,
    config.CATEGORY_SIDE_HUSTLE: COLOR_SIDE_HUSTLE,
    config.CATEGORY_PERSONAL: COLOR_PERSONAL,
    config.CATEGORY_ENTERTAINMENT: COLOR_ENTERTAINMENT,
    config.CATEGORY_UNCLASSIFIED: COLOR_UNCLASSIFIED,
}


class BaseChart(FigureCanvasQTAgg):
    """A styled Matplotlib canvas with an empty-state mode (FR-018)."""

    empty_message = "No activity recorded yet."

    def __init__(self, figsize=(4.4, 3.2)):
        self.figure = Figure(figsize=figsize, dpi=100)  # own figure, no pyplot
        super().__init__(self.figure)
        self.has_data = False
        self.figure.patch.set_facecolor("white")

    def draw_empty(self, message: str | None = None) -> None:
        """Render a centered, friendly message instead of an empty chart."""
        self.has_data = False
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor("white")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.text(
            0.5, 0.5, message or self.empty_message,
            ha="center", va="center",
            fontsize=10.5, color=COLOR_MUTED, wrap=True,
        )
        self.draw_idle()


def _style_axes(ax) -> None:
    ax.set_facecolor("white")
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color(COLOR_GRID)
    ax.tick_params(colors=COLOR_MUTED, labelsize=9)


class DailyGoalBarChart(BaseChart):
    """Actual versus daily target for Study and Side Hustle (FR-016)."""

    empty_message = "No activity recorded yet today."

    def __init__(self):
        super().__init__(figsize=(4.6, 3.4))
        self.draw_empty()

    def refresh(self, category_seconds: dict[str, int]) -> None:
        groups = [
            (
                config.CATEGORY_STUDY,
                category_seconds.get(config.CATEGORY_STUDY, 0),
                config.STUDY_TARGET_SECONDS,
                COLOR_STUDY,
            ),
            (
                config.CATEGORY_SIDE_HUSTLE,
                category_seconds.get(config.CATEGORY_SIDE_HUSTLE, 0),
                config.SIDE_HUSTLE_TARGET_SECONDS,
                COLOR_SIDE_HUSTLE,
            ),
        ]
        if all(actual <= 0 for _, actual, _, _ in groups) and all(
            target <= 0 for _, _, target, _ in groups
        ):
            self.draw_empty()
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        _style_axes(ax)
        xs = range(len(groups))
        bar_width = 0.32
        xs_actual = [x - bar_width / 2 for x in xs]
        xs_target = [x + bar_width / 2 for x in xs]
        actual_hours = [actual / 3600 for _, actual, _, _ in groups]
        target_hours = [target / 3600 for _, _, target, _ in groups]

        bars_actual = ax.bar(
            xs_actual, actual_hours, width=bar_width,
            color=[color for _, _, _, color in groups], label="Actual",
        )
        ax.bar(
            xs_target, target_hours, width=bar_width,
            color=COLOR_TARGET, label="Target",
        )

        for plate, (_, actual, _, _) in zip(bars_actual, groups):
            if actual > 0:
                ax.annotate(
                    reporting.format_seconds(actual),
                    (plate.get_x() + plate.get_width() / 2, plate.get_height()),
                    textcoords="offset points", xytext=(0, 3),
                    ha="center", fontsize=8.5, color=COLOR_TEXT,
                )

        peak_hours = max(actual_hours + target_hours)
        ax.set_ylim(0, peak_hours * 1.18)
        y_max = peak_hours * 1.18
        ticks = [t for t in range(0, int(y_max) + 1, 2)]
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"{t}h" for t in ticks])
        ax.set_xticks(list(xs))
        ax.set_xticklabels(
            [config.CATEGORY_STUDY, config.CATEGORY_SIDE_HUSTLE], fontsize=10,
            color=COLOR_TEXT,
        )
        ax.yaxis.grid(True, color=COLOR_GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.legend(loc="upper right", frameon=False, fontsize=9)
        self.has_data = True
        self.draw_idle()


class CategoryPieChart(BaseChart):
    """Non-idle tracked time distribution by category (FR-017)."""

    empty_message = "Nothing to break down yet — no non-idle time today."

    def __init__(self):
        super().__init__(figsize=(4.6, 3.4))
        self.draw_empty()

    def refresh(self, category_seconds: dict[str, int]) -> None:
        values = []
        labels = []
        colors = []
        for category in config.EDITABLE_CATEGORIES:
            seconds = category_seconds.get(category, 0)
            if seconds > 0:
                values.append(seconds)
                labels.append(f"{category}  ({reporting.format_seconds(seconds)})")
                colors.append(CHART_COLORS[category])
        if not values:
            self.draw_empty()
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor("white")
        wedges, _, autotexts = ax.pie(
            values,
            colors=colors,
            startangle=90,
            counterclock=False,
            autopct=lambda pct: f"{pct:.0f}%" if pct >= 6 else "",
            pctdistance=0.78,
            wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
            textprops={"fontsize": 8.5},
        )
        for autotext in autotexts:
            autotext.set_color("white")
            autotext.set_fontweight("bold")
        ax.set_aspect("equal")
        ax.legend(
            wedges, labels, loc="center left",
            bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=9,
        )
        self.figure.subplots_adjust(left=0.0, right=0.62)
        self.has_data = True
        self.draw_idle()


class WeeklyStackedChart(BaseChart):
    """Seven-day stacked view of Study, Side Hustle and Other (FR-020)."""

    empty_message = "No activity recorded in the last seven days."

    def __init__(self):
        super().__init__(figsize=(9.4, 3.2))
        self.draw_empty()

    def refresh(self, weekly_rows: list[dict]) -> None:
        totals = [
            reporting.non_idle_total(row["categories"]) for row in weekly_rows
        ]
        if not any(total > 0 for total in totals):
            self.draw_empty()
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        _style_axes(ax)
        xs = list(range(len(weekly_rows)))
        bar_width = 0.55
        heights = [row["categories"][config.CATEGORY_STUDY] / 3600 for row in weekly_rows]
        labels = [
            row["date"].strftime("%b %d") for row in weekly_rows
        ]
        ax.bar(
            xs, heights, width=bar_width, color=COLOR_STUDY,
            label=config.CATEGORY_STUDY, align="center",
        )

        second_heights = [
            row["categories"][config.CATEGORY_SIDE_HUSTLE] / 3600
            for row in weekly_rows
        ]
        ax.bar(
            xs, second_heights, width=bar_width, bottom=heights,
            color=COLOR_SIDE_HUSTLE, label=config.CATEGORY_SIDE_HUSTLE,
        )
        bottoms_base = [h1 + h2 for h1, h2 in zip(heights, second_heights)]

        other_heights = [reporting.other_seconds(row["categories"]) / 3600 for row in weekly_rows]
        if any(h > 0 for h in other_heights):
            ax.bar(
                xs, other_heights, width=bar_width, bottom=bottoms_base,
                color=COLOR_OTHER, label="Other",
            )

        all_heights = [b + o for b, o in zip(bottoms_base, other_heights)]
        peak = max(all_heights + [1.0])
        ax.set_ylim(0, peak * 1.2)
        ticks = [t for t in range(0, int(peak * 1.2) + 1, 2)]
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"{t}h" for t in ticks])
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=9, color=COLOR_TEXT)
        ax.yaxis.grid(True, color=COLOR_GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.legend(loc="upper left", frameon=False, fontsize=9)
        self.has_data = True
        self.draw_idle()

