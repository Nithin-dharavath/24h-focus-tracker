"""Entry point for 24H Focus Tracker (FR-001).

Run with:  python main.py
Requires:  Windows 10/11, Python 3.11+, see README.md for setup.
"""

from focus_tracker import config
from focus_tracker import database as db


def main() -> int:
    try:
        conn = db.open_database(config.DB_PATH)
    except Exception as exc:  # startup error must be visible, never silent
        import tkinter.messagebox as mb

        mb.showerror(
            config.APP_NAME,
            "The local database could not be opened:\n"
            f"{config.DB_PATH}\n\n{exc}",
        )
        return 1

    from PySide6.QtWidgets import QApplication

    from focus_tracker.main_window import MainWindow

    app = QApplication([])
    app.setApplicationName(config.APP_NAME)
    window = MainWindow(conn)
    window.show()
    # The window's closeEvent already stops the timer, finalizes the
    # pending interval and closes the database connection (FR-022).
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
