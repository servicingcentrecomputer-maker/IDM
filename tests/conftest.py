"""Shared pytest fixtures."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tests.http_server import TestFileServer


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setApplicationName("IDM tests")
    yield app


@pytest.fixture(scope="session")
def server():
    instance = TestFileServer().start()
    yield instance
    instance.stop()
