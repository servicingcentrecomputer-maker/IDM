"""Download File Info dialog used for manual and browser downloads."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from downloads.location_manager import (
    LocationError,
    check_disk_space,
    ensure_folder,
    safe_join,
    validate_folder_path,
)

from ...constants import CATEGORIES, CATEGORY_GENERAL, PRIORITY_NORMAL
from ...core.categories import (
    category_names,
    describe_file_type,
    detect_category,
    ensure_filename_extension,
    safe_category,
)
from ...core.media_policy import restricted_platform, restriction_message
from ...core.probe import LinkProbe, ProbeResult
from ...core.settings import AppSettings
from ...core.url_utils import (
    InvalidUrlError,
    extension_of,
    format_eta,
    format_progress_size,
    format_size,
    format_speed,
    guess_filename,
    host_of,
    sanitize_filename,
    unique_filename,
    validate_url,
)
from ...models.download_item import DownloadItem, DownloadStatus
from .. import design, icons
from ..theme import ThemeManager
from .categories import CategoryManagerDialog
from .common import (
    BaseDialog,
    make_label,
    secondary_button,
)

logger = logging.getLogger(__name__)

_MAX_DESCRIPTION = 2000


class _ProminentButton(QPushButton):
    """Primary action with a subtle animated elevation on hover."""

    def __init__(self, text: str, shadow_color: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("PrimaryButton")
        self.setProperty("prominent", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(True)
        self.setDefault(True)
        self._shadow: QGraphicsDropShadowEffect | None = None
        self._elevation: QPropertyAnimation | None = None
        if not design.animations_enabled():
            return
        shadow = QGraphicsDropShadowEffect(self)
        colour = QColor(shadow_color)
        colour.setAlpha(64)
        shadow.setColor(colour)
        shadow.setBlurRadius(8.0)
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
        animation = QPropertyAnimation(shadow, b"blurRadius", self)
        animation.setDuration(design.duration("fast"))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shadow = shadow
        self._elevation = animation

    def _animate_elevation(self, target: float) -> None:
        if self._shadow is None or self._elevation is None:
            return
        self._elevation.stop()
        self._elevation.setStartValue(self._shadow.blurRadius())
        self._elevation.setEndValue(target)
        self._elevation.start()

    def enterEvent(self, event) -> None:
        self._animate_elevation(18.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_elevation(8.0)
        super().leaveEvent(event)


class AddDownloadDialog(BaseDialog):
    """Editable file information with server metadata and save options."""

    def __init__(
        self,
        settings: AppSettings,
        theme: ThemeManager,
        parent=None,
        initial_category: str | None = None,
        *,
        initial_url: str = "",
        initial_filename: str = "",
        manager=None,
        submit_callback: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        super().__init__(theme, parent)
        self._settings = settings
        self._manager = manager
        self._submit_callback = submit_callback
        self._initial_category = initial_category
        self._auto_filename = not bool(initial_filename)
        self._auto_category = True
        self._last_probed_url = ""
        self._probe_result: ProbeResult | None = None
        self._result: dict[str, Any] | None = None
        self._restricted_url = ""
        self._restricted_platform = ""
        self.created_item = None
        self._last_icon_category: str | None = None
        self._icon_effect: QGraphicsOpacityEffect | None = None
        self._icon_animation: QPropertyAnimation | None = None
        self._progress_mode = False
        self._progress_item_id: str | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(500)
        self._progress_timer.timeout.connect(self._refresh_progress_from_manager)
        self._progress_close_timer = QTimer(self)
        self._progress_close_timer.setSingleShot(True)
        self._progress_close_timer.setInterval(2800)
        self._progress_close_timer.timeout.connect(self.close)

        self.setWindowTitle("Download File Info")
        self.setMinimumSize(640, 560)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(
            design.SPACING["xl"],
            design.SPACING["xl"],
            design.SPACING["xl"],
            design.SPACING["md"],
        )
        header_layout.addWidget(self._build_header())
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("DialogScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(
            design.SPACING["xl"],
            design.SPACING["xs"],
            design.SPACING["xl"],
            design.SPACING["lg"],
        )
        body_layout.setSpacing(design.SPACING["md"])

        body_layout.addWidget(self._build_url_section())
        body_layout.addWidget(self._build_file_card())
        body_layout.addWidget(self._build_options())
        body_layout.addWidget(self._build_information())
        scroll.setWidget(body)
        self._body_scroll = scroll
        root.addWidget(scroll, 1)

        self._progress_view = self._build_progress_view()
        root.addWidget(self._progress_view, 1)
        self._progress_view.hide()

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(
            design.SPACING["xl"],
            design.SPACING["md"],
            design.SPACING["xl"],
            design.SPACING["lg"],
        )
        footer_layout.setSpacing(design.SPACING["sm"])

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        footer_layout.addWidget(self.error_label)

        actions = QHBoxLayout()
        actions.setSpacing(design.SPACING["sm"])
        self._footer_hint = QLabel(
            "Download Later keeps the file queued until you start it."
        )
        self._footer_hint.setObjectName("FooterHint")
        actions.addWidget(self._footer_hint)
        actions.addStretch(1)
        self.cancel_button = secondary_button("Cancel")
        self.cancel_button.setObjectName("GhostButton")
        self.later_button = secondary_button("Download Later")
        self.later_button.setObjectName("SubtleButton")
        self.start_button = _ProminentButton(
            "Start Download", self._theme.palette.shadow
        )
        self.cancel_button.setMinimumHeight(40)
        self.later_button.setMinimumHeight(40)
        self.later_button.setMinimumWidth(132)
        self.start_button.setMinimumHeight(40)
        self.start_button.setMinimumWidth(158)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.later_button)
        actions.addWidget(self.start_button)
        footer_layout.addLayout(actions)
        root.addWidget(footer)

        self._probe = LinkProbe(self)
        self._probe.finished.connect(self._on_probe_finished)
        self._probe.failed.connect(self._on_probe_failed)
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(650)
        self._probe_timer.timeout.connect(self._request_probe)

        self.url_edit.textChanged.connect(self._on_url_changed)
        self.url_edit.editingFinished.connect(self._request_probe)
        self.filename_edit.textEdited.connect(self._on_filename_edited)
        self.filename_edit.textChanged.connect(self._on_filename_text_changed)
        self.folder_edit.textChanged.connect(lambda _: self._update_folder_hint())
        self.category_combo.activated.connect(self._on_category_activated)
        self.remember_check.toggled.connect(self._update_remember_text)
        self.description_edit.textChanged.connect(self._update_description_hint)
        self.start_button.clicked.connect(lambda: self._validate_and_accept(True))
        self.later_button.clicked.connect(lambda: self._validate_and_accept(False))
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        if settings.start_immediately:
            self.start_button.setDefault(True)
        else:
            self.later_button.setDefault(True)

        self.setTabOrder(self.url_edit, self.copy_button)
        self.setTabOrder(self.copy_button, self.category_combo)
        self.setTabOrder(self.category_combo, self.manage_categories_button)
        self.setTabOrder(self.manage_categories_button, self.filename_edit)
        self.setTabOrder(self.filename_edit, self.folder_edit)
        self.setTabOrder(self.folder_edit, self.browse_button)
        self.setTabOrder(self.browse_button, self.remember_check)
        self.setTabOrder(self.remember_check, self.description_edit)
        self.setTabOrder(self.description_edit, self.later_button)
        self.setTabOrder(self.later_button, self.start_button)
        self.setTabOrder(self.start_button, self.cancel_button)
        self._theme.changed.connect(self._refresh_icons)

        category = initial_category or CATEGORY_GENERAL
        self._refresh_categories(category)
        remembered = settings.remembered_folder(category)
        if remembered:
            self.folder_edit.setText(remembered)
            self.remember_check.setChecked(True)
        if initial_url:
            self.url_edit.setText(initial_url)
            self.url_edit.setCursorPosition(0)
        if initial_filename:
            self.filename_edit.setText(initial_filename)
        self._refresh_icons()
        self._refresh_file_card()
        self._reset_information()
        self._sync_default_size()

    # ------------------------------------------------------------------ construction
    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(design.SPACING["md"])

        self.brand_label = QLabel()
        self.brand_label.setObjectName("DialogBrand")
        self.brand_label.setFixedSize(46, 46)
        self.brand_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.brand_label, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(design.SPACING["xxs"])
        self._header_eyebrow = QLabel("NEW DOWNLOAD")
        self._header_eyebrow.setObjectName("DialogEyebrow")
        self._header_title = QLabel("Download File Info")
        self._header_title.setObjectName("DialogTitle")
        self._header_subtitle = QLabel(
            "Review the file, choose where it goes, then start now or keep it "
            "for later."
        )
        self._header_subtitle.setObjectName("DialogSubtitle")
        self._header_subtitle.setWordWrap(True)
        text.addWidget(self._header_eyebrow)
        text.addWidget(self._header_title)
        text.addWidget(self._header_subtitle)
        layout.addLayout(text, 1)

        transport = QLabel("HTTP · HTTPS")
        transport.setObjectName("DialogMetaBadge")
        layout.addWidget(transport, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_progress_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(
            design.SPACING["xl"],
            design.SPACING["xs"],
            design.SPACING["xl"],
            design.SPACING["lg"],
        )
        layout.setSpacing(design.SPACING["md"])

        card = QFrame()
        card.setObjectName("OptionsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            design.SPACING["lg"],
            design.SPACING["md"],
            design.SPACING["lg"],
            design.SPACING["md"],
        )
        card_layout.setSpacing(design.SPACING["sm"])

        header = QHBoxLayout()
        header.setSpacing(design.SPACING["sm"])
        title = QLabel("Transfer details")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._progress_state = QLabel("Starting…")
        self._progress_state.setObjectName("HintLabel")
        self._progress_state.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        header.addWidget(self._progress_state)
        card_layout.addLayout(header)

        self._progress_name = QLabel()
        self._progress_name.setObjectName("ProgressFile")
        self._progress_name.setWordWrap(True)
        card_layout.addWidget(self._progress_name)

        stats = QHBoxLayout()
        stats.setSpacing(design.SPACING["sm"])
        self._progress_percent = QLabel("0%")
        self._progress_percent.setObjectName("ProgressPercent")
        stats.addWidget(self._progress_percent)
        stats.addStretch(1)
        self._progress_size = QLabel()
        self._progress_size.setObjectName("ProgressMeta")
        self._progress_size.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        stats.addWidget(self._progress_size)
        card_layout.addLayout(stats)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("DownloadProgress")
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        card_layout.addWidget(self._progress_bar)

        self._progress_detail = QLabel()
        self._progress_detail.setObjectName("HintLabel")
        self._progress_detail.setWordWrap(True)
        card_layout.addWidget(self._progress_detail)

        layout.addWidget(card)

        self._progress_folder = QLabel()
        self._progress_folder.setObjectName("FooterHint")
        self._progress_folder.setWordWrap(True)
        layout.addWidget(self._progress_folder)
        layout.addStretch(1)
        return view

    def _build_url_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(design.SPACING["sm"])
        layout.addWidget(make_label("DOWNLOAD URL"))

        row = QHBoxLayout()
        row.setSpacing(design.SPACING["sm"])
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("UrlInput")
        self.url_edit.setPlaceholderText("https://example.com/file.zip")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setMinimumHeight(40)
        self._url_action = self.url_edit.addAction(
            icons.icon("link", self._theme.palette.text_faint, design.ICON_SIZE["md"]),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        row.addWidget(self.url_edit, 1)
        self.copy_button = secondary_button("Copy")
        self.copy_button.setObjectName("SubtleButton")
        self.copy_button.setMinimumHeight(40)
        self.copy_button.setToolTip("Copy the complete URL to the clipboard")
        self.copy_button.clicked.connect(self._copy_url)
        row.addWidget(self.copy_button)
        layout.addLayout(row)

        probe_row = QHBoxLayout()
        probe_row.setSpacing(design.SPACING["sm"])
        self.probe_label = QLabel("Paste a direct HTTP or HTTPS file link.")
        self.probe_label.setObjectName("ProbeLabel")
        self.probe_label.setProperty("state", "")
        self.probe_label.setWordWrap(True)
        probe_row.addWidget(self.probe_label, 1)
        self.open_page_button = secondary_button("Open official page")
        self.open_page_button.setIcon(
            icons.icon("external", self._theme.palette.text_muted, design.ICON_SIZE["sm"])
        )
        self.open_page_button.clicked.connect(self._open_official_page)
        self.open_page_button.hide()
        probe_row.addWidget(self.open_page_button)
        layout.addLayout(probe_row)
        return section

    def _build_file_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("FileHeroCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(
            design.SPACING["lg"],
            design.SPACING["md"],
            design.SPACING["lg"],
            design.SPACING["md"],
        )
        layout.setSpacing(design.SPACING["lg"])

        self.file_icon = QLabel()
        self.file_icon.setObjectName("FileTypeIcon")
        self.file_icon.setFixedSize(56, 56)
        self.file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.file_icon, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(design.SPACING["xs"])
        self.file_name_label = QLabel("Choose a link to begin")
        self.file_name_label.setObjectName("FileNamePreview")
        self.file_name_label.setWordWrap(True)
        text.addWidget(self.file_name_label)
        self.file_type_label = QLabel("The file type is detected from the link.")
        self.file_type_label.setObjectName("HintLabel")
        self.file_type_label.setWordWrap(True)
        text.addWidget(self.file_type_label)

        chips = QHBoxLayout()
        chips.setSpacing(design.SPACING["sm"])
        self.category_pill = QLabel()
        self.category_pill.setObjectName("CategoryPill")
        chips.addWidget(self.category_pill)
        self.extension_label = QLabel("No extension")
        self.extension_label.setObjectName("MetaChip")
        chips.addWidget(self.extension_label)
        chips.addStretch(1)
        text.addLayout(chips)
        layout.addLayout(text, 1)
        return card

    def _build_options(self) -> QWidget:
        card = QFrame()
        card.setObjectName("OptionsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            design.SPACING["md"],
            design.SPACING["md"],
            design.SPACING["md"],
            design.SPACING["md"],
        )
        layout.setSpacing(design.SPACING["sm"])

        title = QLabel("Save options")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        category_field = QVBoxLayout()
        category_field.setSpacing(design.SPACING["xs"])
        category_field.addWidget(make_label("CATEGORY"))
        category_row = QHBoxLayout()
        category_row.setSpacing(design.SPACING["sm"])
        self.category_combo = QComboBox()
        self.category_combo.setObjectName("CategoryCombo")
        self.category_combo.setMinimumHeight(40)
        self.category_combo.setIconSize(
            QSize(design.ICON_SIZE["md"], design.ICON_SIZE["md"])
        )
        self.category_combo.setMinimumContentsLength(12)
        self.category_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        category_row.addWidget(self.category_combo, 1)
        self.manage_categories_button = secondary_button("Manage…")
        self.manage_categories_button.setObjectName("SubtleButton")
        self.manage_categories_button.setMinimumHeight(40)
        self.manage_categories_button.setToolTip(
            "Add custom categories or edit remembered folders"
        )
        self.manage_categories_button.clicked.connect(self._manage_categories)
        category_row.addWidget(self.manage_categories_button)
        category_field.addLayout(category_row)
        layout.addLayout(category_field)

        save_as_field = QVBoxLayout()
        save_as_field.setSpacing(design.SPACING["xs"])
        save_as_field.addWidget(make_label("SAVE AS"))
        self.filename_edit = QLineEdit()
        self.filename_edit.setObjectName("SaveAsInput")
        self.filename_edit.setPlaceholderText("Detected automatically from the link")
        self.filename_edit.setMinimumHeight(40)
        self.filename_edit.setClearButtonEnabled(True)
        self._filename_action = self.filename_edit.addAction(
            icons.icon(
                "file", self._theme.palette.text_faint, design.ICON_SIZE["md"]
            ),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        save_as_field.addWidget(self.filename_edit)
        layout.addLayout(save_as_field)

        save_to_field = QVBoxLayout()
        save_to_field.setSpacing(design.SPACING["xs"])
        save_to_field.addWidget(make_label("SAVE TO"))
        folder_row = QHBoxLayout()
        folder_row.setSpacing(design.SPACING["sm"])
        self.folder_edit = QLineEdit(str(self._settings.download_dir))
        self.folder_edit.setObjectName("FolderInput")
        self.folder_edit.setMinimumHeight(40)
        self.folder_edit.setClearButtonEnabled(True)
        self._folder_action = self.folder_edit.addAction(
            icons.icon(
                "folder", self._theme.palette.text_faint, design.ICON_SIZE["md"]
            ),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        folder_row.addWidget(self.folder_edit, 1)
        self.browse_button = secondary_button("Browse…")
        self.browse_button.setObjectName("SubtleButton")
        self.browse_button.setMinimumHeight(40)
        self.browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.browse_button)
        save_to_field.addLayout(folder_row)
        layout.addLayout(save_to_field)

        self.remember_check = QCheckBox()
        self.remember_check.setObjectName("RememberPath")
        self.remember_check.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.remember_check)

        self.folder_hint = QLabel()
        self.folder_hint.setObjectName("HintLabel")
        self.folder_hint.setWordWrap(True)
        self.folder_hint.hide()
        layout.addWidget(self.folder_hint)

        description_field = QVBoxLayout()
        description_field.setSpacing(design.SPACING["xs"])
        description_row = QHBoxLayout()
        description_row.setSpacing(design.SPACING["sm"])
        description_row.addWidget(make_label("DESCRIPTION"))
        description_row.addStretch(1)
        self.description_hint = QLabel()
        self.description_hint.setObjectName("HintLabel")
        self.description_hint.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        description_row.addWidget(self.description_hint)
        description_field.addLayout(description_row)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("DescriptionEdit")
        self.description_edit.setPlaceholderText(
            "Optional note saved with this download"
        )
        self.description_edit.setFixedHeight(64)
        self.description_edit.setTabChangesFocus(True)
        description_field.addWidget(self.description_edit)
        layout.addLayout(description_field)
        return card

    def _build_information(self) -> QWidget:
        card = QFrame()
        card.setObjectName("InfoCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            design.SPACING["md"],
            design.SPACING["md"],
            design.SPACING["md"],
            design.SPACING["md"],
        )
        layout.setSpacing(design.SPACING["sm"])

        header = QHBoxLayout()
        header.setSpacing(design.SPACING["sm"])
        title = QLabel("File information")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)
        subtitle = QLabel("Reported by the server")
        subtitle.setObjectName("HintLabel")
        header.addWidget(subtitle)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(design.SPACING["lg"])
        grid.setVerticalSpacing(design.SPACING["xs"])
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self._info_labels: dict[str, QLabel] = {}
        fields = (
            ("size", "Size"),
            ("mime", "MIME type"),
            ("source", "Source"),
            ("status", "Server status"),
            ("modified", "Last modified"),
            ("resumable", "Resume support"),
        )
        for index, (key, label) in enumerate(fields):
            row, column = divmod(index, 2)
            grid.addWidget(make_label(label.upper(), "FileInfoKey"), row, column * 2)
            value = QLabel("—")
            value.setObjectName("FileInfoValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(value, row, column * 2 + 1)
            self._info_labels[key] = value
        layout.addLayout(grid)
        return card

    def _refresh_icons(self) -> None:
        palette = self._theme.palette
        brand_size = design.ICON_SIZE["xl"]
        self.brand_label.setPixmap(
            icons.icon("download", palette.on_accent, brand_size).pixmap(
                brand_size, brand_size
            )
        )
        self._url_action.setIcon(
            icons.icon("link", palette.text_faint, design.ICON_SIZE["md"])
        )
        self._filename_action.setIcon(
            icons.icon("file", palette.text_faint, design.ICON_SIZE["md"])
        )
        self._folder_action.setIcon(
            icons.icon("folder", palette.text_faint, design.ICON_SIZE["md"])
        )
        small = design.ICON_SIZE["sm"]
        self.copy_button.setIcon(icons.icon("copy", palette.text_muted, small))
        self.manage_categories_button.setIcon(
            icons.icon("options", palette.text_muted, small)
        )
        self.browse_button.setIcon(
            icons.icon("folder_open", palette.text_muted, small)
        )
        self.open_page_button.setIcon(
            icons.icon("external", palette.text_muted, small)
        )
        self.later_button.setIcon(
            icons.icon("clock", palette.text_muted, design.ICON_SIZE["md"])
        )
        self.start_button.setIcon(
            icons.icon("download", palette.on_accent, design.ICON_SIZE["md"])
        )

    def _fade_file_icon(self, category: str) -> None:
        self.file_icon.setPixmap(
            icons.category_icon(category, size=34).pixmap(34, 34)
        )
        if not design.animations_enabled():
            return
        if self._icon_effect is None:
            self._icon_effect = QGraphicsOpacityEffect(self.file_icon)
            self.file_icon.setGraphicsEffect(self._icon_effect)
        if self._icon_animation is None:
            self._icon_animation = QPropertyAnimation(
                self._icon_effect, b"opacity", self
            )
            self._icon_animation.setDuration(design.duration("normal"))
            self._icon_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._icon_animation.stop()
        self._icon_animation.setStartValue(0.4)
        self._icon_animation.setEndValue(1.0)
        self._icon_animation.start()

    # ------------------------------------------------------------------ public
    def values(self) -> dict[str, Any]:
        if self._result is None:
            raise RuntimeError("The dialog has not been accepted.")
        return dict(self._result)

    @property
    def progress_mode(self) -> bool:
        return self._progress_mode

    def start_progress(self, item: DownloadItem) -> None:
        """Keep this dialog open after Start and show live MB/GB progress."""
        if self._manager is None or item is None:
            return
        self._progress_mode = True
        self._progress_item_id = item.id
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._body_scroll.hide()
        self._progress_view.show()
        self._header_eyebrow.setText("DOWNLOADING")
        self._header_title.setText("Download in progress")
        self._header_subtitle.setText(
            "Progress updates in real time. Closing this window keeps the "
            "download running."
        )
        self.later_button.hide()
        self.start_button.hide()
        self.cancel_button.setText("Cancel download")
        self.error_label.hide()
        self._footer_hint.setText(
            "The download continues in the background after this window closes."
        )
        self.setMinimumSize(560, 380)
        self.resize(640, 430)
        self._center_on_parent()
        self._manager.download_updated.connect(self._on_download_updated)
        self._manager.download_removed.connect(self._on_download_removed)
        self._progress_timer.start()
        self._apply_progress(item)
        self.show()
        self.raise_()
        self.activateWindow()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(parent.frameGeometry().center() - self.rect().center())

    # ------------------------------------------------------------------ live progress
    def _on_download_updated(self, item: DownloadItem) -> None:
        if self._progress_mode and item.id == self._progress_item_id:
            self._apply_progress(item)

    def _on_download_removed(self, download_id: str) -> None:
        if download_id == self._progress_item_id:
            self.close()

    def _refresh_progress_from_manager(self) -> None:
        if self._manager is None or self._progress_item_id is None:
            return
        item = self._manager.get(self._progress_item_id)
        if item is None:
            self.close()
            return
        self._apply_progress(item)

    def _apply_progress(self, item: DownloadItem) -> None:
        self._progress_name.setText(item.filename)
        self._progress_folder.setText(f"Saving to {item.folder}")
        status = item.status
        completed = status == DownloadStatus.COMPLETED
        fraction = 1.0 if completed else item.progress
        if fraction is None and item.is_active:
            self._progress_bar.setRange(0, 0)
            self._progress_percent.setText("…")
        else:
            percent = round((fraction or 0.0) * 100)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(percent)
            self._progress_percent.setText(f"{percent}%")

        size_text = format_progress_size(item.downloaded_bytes, item.total_bytes)
        self._progress_size.setText(size_text or "Size unknown")

        parts: list[str] = []
        if item.speed > 0 and item.is_active:
            parts.append(format_speed(item.speed))
        if item.eta is not None and item.is_active:
            parts.append(f"{format_eta(item.eta)} left")
        self._progress_detail.setText("   ·   ".join(parts))
        self._progress_state.setText(status.value)

        if completed:
            self._progress_percent.setText("100%")
            self._progress_size.setText(
                format_progress_size(item.total_bytes, item.total_bytes)
                or format_size(item.downloaded_bytes)
            )
            self._progress_state.setText("Completed")
            self._progress_detail.setText("Download complete")
            self.cancel_button.setText("Close")
            self._footer_hint.setText(f"Saved to {item.folder}")
            self._progress_timer.stop()
            if not self._progress_close_timer.isActive():
                self._progress_close_timer.start()
        elif status == DownloadStatus.FAILED:
            self._progress_state.setText("Failed")
            self.cancel_button.setText("Close")
            self._progress_timer.stop()
            if item.error:
                self.error_label.setText(item.error)
                self.error_label.show()
            self._footer_hint.setText("The download failed.")
        elif status == DownloadStatus.STOPPED:
            self._progress_state.setText("Stopped")
            self.cancel_button.setText("Close")
            self._progress_timer.stop()
            self._footer_hint.setText(
                "The download was stopped. Resume it from the download list."
            )
        else:
            self.cancel_button.setText("Cancel download")
            self._footer_hint.setText(
                "The download continues in the background after this window closes."
            )

    def _on_cancel_clicked(self) -> None:
        if not self._progress_mode:
            self.reject()
            return
        item = (
            self._manager.get(self._progress_item_id)
            if self._manager is not None and self._progress_item_id
            else None
        )
        if item is not None and item.status not in {
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.STOPPED,
        }:
            self._manager.stop([item.id])
        self.close()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_footer_hint()
        if self._progress_mode:
            return
        QTimer.singleShot(0, self._focus_initial_field)

    def _focus_initial_field(self) -> None:
        if self.url_edit.text().strip():
            self.url_edit.setCursorPosition(0)
            if self.start_button.isEnabled():
                self.start_button.setFocus()
            return
        self.url_edit.setFocus()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_footer_hint()

    def _sync_footer_hint(self) -> None:
        self._footer_hint.setVisible(self._progress_mode or self.width() >= 720)

    def reject(self) -> None:
        self._probe_timer.stop()
        self._probe.abort()
        super().reject()

    def closeEvent(self, event) -> None:
        self._progress_timer.stop()
        self._progress_close_timer.stop()
        if self._progress_mode and self._manager is not None:
            try:
                self._manager.download_updated.disconnect(self._on_download_updated)
                self._manager.download_removed.disconnect(self._on_download_removed)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)

    # ------------------------------------------------------------------ layout
    def _sync_default_size(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(800, max(640, available.width() - 80))
        height = min(920, max(560, available.height() - 80))
        self.resize(width, height)

    # ------------------------------------------------------------------ categories
    def _custom_categories(self) -> list[dict]:
        return list(getattr(self._settings, "custom_categories", []))

    def _refresh_categories(self, selected: str = "") -> None:
        target = selected or str(self.category_combo.currentData() or CATEGORY_GENERAL)
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for name in category_names(self._custom_categories()):
            self.category_combo.addItem(
                icons.category_icon(name, size=design.ICON_SIZE["md"]), name, name
            )
        index = self.category_combo.findData(target)
        if index < 0:
            for fallback in (CATEGORY_GENERAL, CATEGORIES[-1]):
                index = self.category_combo.findData(fallback)
                if index >= 0:
                    break
        self.category_combo.setCurrentIndex(max(0, index))
        self.category_combo.blockSignals(False)
        self._update_remember_text()

    def _on_category_activated(self, _index: int) -> None:
        self._auto_category = False
        category = str(self.category_combo.currentData() or CATEGORY_GENERAL)
        remembered = self._settings.remembered_folder(category)
        if remembered:
            self.folder_edit.setText(remembered)
            self.remember_check.setChecked(True)
        else:
            self.remember_check.setChecked(False)
        self._refresh_file_card()
        self._update_remember_text()
        self._clear_error()

    def _select_category(self, category: str) -> None:
        index = self.category_combo.findData(category)
        if index >= 0:
            with QSignalBlocker(self.category_combo):
                self.category_combo.setCurrentIndex(index)
            self._update_remember_text()

    def _update_remember_text(self, *_args) -> None:
        category = str(self.category_combo.currentData() or CATEGORY_GENERAL)
        self.remember_check.setText(f"Remember this folder for “{category}”")

    def _manage_categories(self) -> None:
        selected = str(self.category_combo.currentData() or CATEGORY_GENERAL)
        dialog = CategoryManagerDialog(self._settings, self._theme, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
        self._refresh_categories(selected)
        self._refresh_file_card()

    # ------------------------------------------------------------------ browsing
    def _browse_folder(self) -> None:
        start = self.folder_edit.text().strip() or self._settings.download_dir
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose download folder", start
        )
        if chosen:
            self.folder_edit.setText(chosen)
            self._update_folder_hint()

    def _copy_url(self) -> None:
        text = self.url_edit.text().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._set_probe("The complete link was copied to the clipboard.", "ok")

    def _open_official_page(self) -> None:
        url = self._restricted_url or self.url_edit.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------------ URL / probe
    def _on_url_changed(self, text: str) -> None:
        self._probe_timer.stop()
        self._probe.abort()
        self._last_probed_url = ""
        self._probe_result = None
        self._clear_error()
        self._set_probe("Paste a direct HTTP or HTTPS file link.", "")

        url = text.strip()
        if self._auto_filename:
            guessed = guess_filename(url) if url else ""
            with QSignalBlocker(self.filename_edit):
                self.filename_edit.setText(guessed)
            if self._auto_category and guessed:
                self._select_category(
                    detect_category(guessed, "", self._custom_categories())
                )
        self._refresh_file_card()
        self._reset_information()
        self._update_folder_hint()
        self._apply_platform_policy(url)

        if url and not self._restricted_url:
            try:
                validate_url(url)
            except InvalidUrlError:
                return
            self._probe_timer.start()

    def _apply_platform_policy(self, url: str) -> None:
        platform = restricted_platform(url) if url else None
        if not platform:
            self._restricted_url = ""
            self._restricted_platform = ""
            self.open_page_button.hide()
            self.start_button.setEnabled(True)
            self.later_button.setEnabled(True)
            return
        self._restricted_url = url
        self._restricted_platform = platform
        self._set_probe(restriction_message(platform), "warn")
        self.open_page_button.show()
        self.start_button.setEnabled(False)
        self.later_button.setEnabled(False)

    def _request_probe(self) -> None:
        url = self.url_edit.text().strip()
        if not url or url == self._last_probed_url or self._restricted_url:
            return
        try:
            validate_url(url)
        except InvalidUrlError:
            return
        self._last_probed_url = url
        self._set_probe("Inspecting link…", "pending")
        self._info_labels["status"].setText("Checking…")
        self._probe.start(url)

    def _on_probe_finished(self, result: ProbeResult) -> None:
        if self.url_edit.text().strip() != self._last_probed_url:
            return
        if self._restricted_url:
            return
        self._probe_result = result

        parts: list[str] = []
        if result.total_bytes is not None:
            parts.append(format_size(result.total_bytes))
        if result.range_supported:
            parts.append("Resumable")
        if result.content_type:
            parts.append(result.content_type)
        self._set_probe("   ·   ".join(parts) if parts else "Link ready.", "ok")

        if self._auto_filename and result.filename:
            name = sanitize_filename(result.filename)
            with QSignalBlocker(self.filename_edit):
                self.filename_edit.setText(name)
            if self._auto_category:
                self._select_category(
                    detect_category(
                        name, result.content_type, self._custom_categories()
                    )
                )
        self._refresh_file_card()
        self._write_information(result)
        self._update_folder_hint()

    def _on_probe_failed(self, message: str) -> None:
        if self.url_edit.text().strip() != self._last_probed_url:
            return
        self._set_probe(f"{message} You can still add the link.", "warn")
        self._info_labels["status"].setText("Not available")
        self._info_labels["size"].setText("Unknown")
        self._info_labels["mime"].setText("Unknown")
        self._info_labels["modified"].setText("Unknown")
        self._info_labels["resumable"].setText("Unknown")

    def _set_probe(self, text: str, state: str) -> None:
        self.probe_label.setText(text)
        self.probe_label.setProperty("state", state)
        style = self.probe_label.style()
        style.unpolish(self.probe_label)
        style.polish(self.probe_label)

    # ------------------------------------------------------------------ file card
    def _current_category(self) -> str:
        return safe_category(
            str(self.category_combo.currentData() or CATEGORY_GENERAL),
            self._custom_categories(),
        )

    def _refresh_file_card(self) -> None:
        filename = self.filename_edit.text().strip()
        mime = self._probe_result.content_type if self._probe_result else ""
        category = self._current_category()
        if category != self._last_icon_category:
            self._last_icon_category = category
            self._fade_file_icon(category)
        self.category_pill.setText(category)
        self.category_pill.setVisible(bool(filename))
        self.file_name_label.setText(filename or "Choose a link to begin")
        if filename:
            description = describe_file_type(filename, mime)
            self.file_type_label.setText(
                f"{category} · {description}" if category else description
            )
            extension = extension_of(filename)
            self.extension_label.setText(
                extension.upper() if extension else "No extension"
            )
            self.extension_label.setToolTip(
                f"File extension: .{extension}"
                if extension
                else "This file has no extension."
            )
            self.extension_label.show()
        else:
            self.file_type_label.setText("The file type is detected from the link.")
            self.extension_label.hide()
            self.extension_label.setToolTip("")

    # ------------------------------------------------------------------ fields
    def _on_filename_edited(self, text: str) -> None:
        self._auto_filename = False
        self._clear_error()
        if self._auto_category:
            category = detect_category(
                text,
                self._probe_result.content_type if self._probe_result else "",
                self._custom_categories(),
            )
            self._select_category(category)

    def _on_filename_text_changed(self, _text: str) -> None:
        self._refresh_file_card()
        self._update_folder_hint()

    def _update_folder_hint(self) -> None:
        filename = self.filename_edit.text().strip()
        folder = self.folder_edit.text().strip()
        if not filename or not folder:
            self.folder_hint.hide()
            return
        try:
            folder_path = Path(folder).expanduser()
        except (OSError, ValueError):
            self.folder_hint.hide()
            return
        try:
            taken = (folder_path / filename).exists() or (
                folder_path / f"{filename}.idm.part"
            ).exists()
            if not taken:
                self.folder_hint.hide()
                return
            unique = unique_filename(folder_path, filename)
        except (OSError, RuntimeError, ValueError):
            self.folder_hint.hide()
            return
        self.folder_hint.setText(
            f"“{filename}” already exists in this folder. "
            f"It will be saved as “{unique}”."
        )
        self.folder_hint.show()

    def _update_description_hint(self) -> None:
        length = len(self.description_edit.toPlainText())
        if length > _MAX_DESCRIPTION:
            self.description_hint.setText(
                f"Shorten the note to {_MAX_DESCRIPTION} characters."
            )
        elif length:
            self.description_hint.setText(f"{length} / {_MAX_DESCRIPTION} characters")
        else:
            self.description_hint.clear()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()

    # ------------------------------------------------------------------ information
    def _reset_information(self) -> None:
        url = self.url_edit.text().strip()
        try:
            host = host_of(validate_url(url)) if url else ""
        except InvalidUrlError:
            host = ""
        self._info_labels["size"].setText("Unknown")
        self._info_labels["mime"].setText("Unknown")
        self._info_labels["source"].setText(host or "—")
        self._info_labels["status"].setText("Not checked" if url else "—")
        self._info_labels["modified"].setText("Unknown")
        self._info_labels["resumable"].setText("Unknown")

    def _write_information(self, result: ProbeResult) -> None:
        self._info_labels["size"].setText(
            format_size(result.total_bytes)
            if result.total_bytes is not None
            else "Unknown"
        )
        self._info_labels["mime"].setText(result.content_type or "Unknown")
        try:
            host = host_of(result.final_url)
        except ValueError:
            host = ""
        self._info_labels["source"].setText(host or "—")
        self._info_labels["status"].setText(result.status_text)
        self._info_labels["modified"].setText(result.last_modified or "Not provided")
        self._info_labels["resumable"].setText(
            "Supported" if result.range_supported else "Not reported"
        )

    # ------------------------------------------------------------------ accept
    def _validate_and_accept(self, start_immediately: bool) -> None:
        self._clear_error()
        try:
            url = validate_url(self.url_edit.text())
        except InvalidUrlError as exc:
            self._show_error(str(exc))
            self.url_edit.setFocus()
            return

        platform = restricted_platform(url)
        if platform:
            self._show_error(restriction_message(platform))
            self.url_edit.setFocus()
            return

        raw_name = self.filename_edit.text().strip()
        if not raw_name:
            self._show_error("Enter a file name for the download.")
            self.filename_edit.setFocus()
            return
        filename = sanitize_filename(raw_name)
        if self._probe_result is not None and self._probe_result.content_type:
            filename = ensure_filename_extension(
                filename, self._probe_result.content_type
            )

        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self._show_error("Choose a folder for the download.")
            self.folder_edit.setFocus()
            return
        try:
            folder = validate_folder_path(folder_text)
            folder = ensure_folder(folder, approve_create=lambda _path: True)
            safe_join(folder, filename)
            total = (
                self._probe_result.total_bytes
                if self._probe_result is not None
                else None
            )
            check_disk_space(folder, total)
        except LocationError as exc:
            self._show_error(str(exc))
            self.folder_edit.setFocus()
            return
        except OSError as exc:
            self._show_error(f"Could not use that folder: {exc}")
            self.folder_edit.setFocus()
            return

        if self._manager is not None:
            existing = self._manager.find_active_by_url(url)
            if existing is not None:
                self._show_error(
                    f"That link is already being downloaded as “{existing.filename}”."
                )
                self.url_edit.setFocus()
                return

        try:
            filename = unique_filename(folder, filename)
        except (RuntimeError, OSError, ValueError) as exc:
            self._show_error(str(exc))
            return

        category = self._current_category()
        description = self.description_edit.toPlainText().strip()
        if len(description) > _MAX_DESCRIPTION:
            self._show_error(
                f"Shorten the description to {_MAX_DESCRIPTION} characters."
            )
            self.description_edit.setFocus()
            return

        values: dict[str, Any] = {
            "url": url,
            "filename": filename,
            "folder": folder,
            "category": category,
            "priority": PRIORITY_NORMAL,
            "start_immediately": bool(start_immediately),
            "download_later": not start_immediately,
            "description": description,
        }

        if self.remember_check.isChecked():
            self._settings.remember_category_folder(category, folder)

        if self._submit_callback is not None:
            try:
                self.created_item = self._submit_callback(dict(values))
            except ValueError as exc:
                self._show_error(str(exc))
                return
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Could not create the download task")
                self._show_error(f"Could not create the download: {exc}")
                return

        self._result = values
        self._probe_timer.stop()
        self._probe.abort()
        self.accept()


__all__ = ["AddDownloadDialog"]
