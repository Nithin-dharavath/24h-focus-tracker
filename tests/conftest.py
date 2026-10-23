"""Shared pytest fixtures for 24H Focus Tracker tests."""

import os

# Headless Qt for test runs; must be set before PySide6 is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
