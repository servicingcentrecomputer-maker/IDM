"""Shared pytest fixtures."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from tests.http_server import TestFileServer


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setApplicationName("IDM tests")
    yield app


@pytest.fixture(autouse=True)
def _destroy_test_windows():
    """Release windows after each test.

    Tests run without a live event loop, so DeferredDelete is never flushed on
    its own.  Leaked window trees make every later stylesheet application
    re-polish all previous widgets, which slows the suite down quadratically.
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            continue
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(scope="session")
def server():
    instance = TestFileServer().start()
    yield instance
    instance.stop()
