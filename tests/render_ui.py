"""Render native Windows screenshots for a manual visual review."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "ui-check"
os.environ["APPDATA"] = str(OUT / "appdata")

sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from idm.core.settings import AppSettings
from idm.models.download_item import DownloadStatus
from idm.ui.dialogs.about import AboutDialog
from idm.ui.dialogs.add_download import AddDownloadDialog
from idm.ui.dialogs.options import OptionsDialog
from idm.ui.dialogs.progress import DownloadProgressDialog
from idm.ui.dialogs.queue import QueueDialog
from idm.ui.dialogs.scheduler import SchedulerDialog
from idm.ui.main_window import MainWindow
from idm.ui.theme import ThemeManager
from tests.http_server import TestFileServer


def wait_until(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    app.processEvents()
    return bool(predicate())


def capture(widget, name: str) -> None:
    QApplication.processEvents()
    time.sleep(0.08)
    QApplication.processEvents()
    path = OUT / name
    widget.grab().save(str(path))
    print("saved", path, path.stat().st_size)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OUT / "downloads", ignore_errors=True)
    shutil.rmtree(OUT / "appdata", ignore_errors=True)
    (OUT / "downloads").mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))

    server = TestFileServer().start()
    settings = AppSettings()
    settings.theme = "classic"
    settings.download_dir = str(OUT / "downloads")
    settings.max_concurrent = 2
    theme = ThemeManager(app)
    theme.set_mode("classic")

    window = MainWindow(settings, theme)
    window.resize(1240, 770)
    window.show()
    app.processEvents()
    capture(window, "native-empty-classic.png")

    downloads = str(OUT / "downloads")
    manager = window._manager
    manager.max_concurrent = 2

    completed = manager.add_download(
        server.url("/file/131072"), "brand-guidelines.pdf", downloads
    )
    wait_until(app, lambda: completed.status == DownloadStatus.COMPLETED)

    failed = manager.add_download(
        server.url("/missing"), "legacy-installer.exe", downloads
    )
    wait_until(app, lambda: failed.status == DownloadStatus.FAILED)

    active = manager.add_download(
        server.url("/slow/16777216"), "launch-video.mp4", downloads
    )
    paused_candidate = manager.add_download(
        server.url("/slow/4194304"), "podcast-episode.mp3", downloads
    )
    wait_until(app, lambda: paused_candidate.downloaded_bytes >= 128 * 1024)
    manager.pause([paused_candidate.id])
    wait_until(
        app,
        lambda: paused_candidate.status == DownloadStatus.PAUSED
        and paused_candidate.id not in manager._workers,
    )

    archive_one = manager.add_download(
        server.url("/slow/262144"), "photo-pack.zip", downloads
    )
    archive_two = manager.add_download(
        server.url("/slow/262144"), "project-assets.7z", downloads
    )
    wait_until(app, lambda: archive_one.status in {
        DownloadStatus.DOWNLOADING,
        DownloadStatus.COMPLETED,
    })
    wait_until(app, lambda: archive_two.status == DownloadStatus.QUEUED)
    wait_until(app, lambda: active.downloaded_bytes >= 700 * 1024)

    theme.set_mode("classic")
    app.processEvents()
    capture(window, "native-dashboard-classic.png")

    theme.set_mode("light")
    app.processEvents()
    capture(window, "native-dashboard-light.png")

    theme.set_mode("dark")
    app.processEvents()
    capture(window, "native-dashboard-dark.png")

    progress = DownloadProgressDialog(manager, active.id, theme, window)
    progress.show()
    progress.raise_()
    app.processEvents()
    capture(progress, "native-progress-dark.png")
    progress.close()
    progress.deleteLater()
    app.processEvents()

    theme.set_mode("classic")
    add_dialog = AddDownloadDialog(settings, theme, window)
    add_dialog.folder_edit.setText(downloads)
    add_dialog.url_edit.setText(server.url("/disposition/65536?name=manual.pdf"))
    add_dialog.show()
    add_dialog.raise_()
    wait_until(app, lambda: add_dialog.probe_label.property("state") == "ok")
    capture(add_dialog, "native-add-dialog.png")
    add_dialog.reject()
    app.processEvents()

    options = OptionsDialog(settings, theme, window)
    options.show()
    options.raise_()
    capture(options, "native-options.png")
    options._tabs.setCurrentIndex(5)
    app.processEvents()
    capture(options, "native-options-themes.png")
    options.reject()
    app.processEvents()

    about = AboutDialog(theme, window)
    about.show()
    about.raise_()
    capture(about, "native-about.png")
    about.reject()
    app.processEvents()

    manager.max_concurrent = 1
    manager.add_download(server.url("/slow/262144"), "queued-third.zip", downloads)
    manager.add_download(server.url("/slow/262144"), "queued-fourth.zip", downloads)
    queue_dialog = QueueDialog(manager, theme, window)
    queue_dialog.show()
    queue_dialog.raise_()
    queue_dialog._table.selectRow(0)
    capture(queue_dialog, "native-queue.png")
    queue_dialog.reject()
    app.processEvents()

    scheduler_dialog = SchedulerDialog(window._scheduler, theme, window)
    scheduler_dialog.show()
    scheduler_dialog.raise_()
    scheduler_dialog._add_schedule()
    app.processEvents()
    scheduler_dialog._table.selectRow(0)
    capture(scheduler_dialog, "native-scheduler.png")
    scheduler_dialog.reject()

    window._shutdown()
    window.hide()
    server.stop()
    settings.save()
    settings.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
