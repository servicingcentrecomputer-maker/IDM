"""Classic and modern themes plus Windows title-bar integration."""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass, fields
from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ..core.paths import asset_path
from . import icons

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    card: str
    border: str
    border_soft: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    selection: str
    track: str
    scrollbar: str
    sidebar_active: str
    toolbar_background: str
    menubar_background: str
    status_background: str
    header_background: str
    row_hover: str
    radius: str
    control_radius: str
    panel_radius: str


CLASSIC = Palette(
    bg="#F2F2F2",
    surface="#FFFFFF",
    surface_alt="#F7F7F7",
    card="#FFFFFF",
    border="#D5DDE5",
    border_soft="#E8EDF2",
    text="#202020",
    text_muted="#586571",
    text_faint="#8A96A2",
    accent="#1683D8",
    accent_hover="#1274C4",
    accent_pressed="#0E64AA",
    accent_soft="#E7F2FB",
    success="#1C8F5A",
    success_soft="#E6F5EE",
    warning="#B9791A",
    warning_soft="#FCF2E3",
    danger="#C94343",
    danger_soft="#FBEDED",
    selection="#D8EBF9",
    track="#E8EEF3",
    scrollbar="#BFC9D3",
    sidebar_active="#E3F1FB",
    toolbar_background=(
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #FCFCFC, stop:1 #F2F2F2)"
    ),
    menubar_background="#F5F5F5",
    status_background="#F0F3F6",
    header_background=(
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #FBFCFD, stop:1 #F1F4F7)"
    ),
    row_hover="#F2F8FD",
    radius="2px",
    control_radius="3px",
    panel_radius="2px",
)

LIGHT = Palette(
    bg="#F3F5F9",
    surface="#FFFFFF",
    surface_alt="#F1F4F9",
    card="#FFFFFF",
    border="#DFE5EF",
    border_soft="#EDF1F6",
    text="#1A2230",
    text_muted="#5C687B",
    text_faint="#8B96A8",
    accent="#2F6BFF",
    accent_hover="#4A81FF",
    accent_pressed="#2259E0",
    accent_soft="#E9F0FF",
    success="#16A36A",
    success_soft="#E5F7EF",
    warning="#C97B11",
    warning_soft="#FDF3E2",
    danger="#D64545",
    danger_soft="#FBEAEA",
    selection="#E8EFFF",
    track="#E7ECF4",
    scrollbar="#C6CFDC",
    sidebar_active="#EAF1FF",
    toolbar_background="#FFFFFF",
    menubar_background="#FFFFFF",
    status_background="#FFFFFF",
    header_background="transparent",
    row_hover="#F7F9FD",
    radius="6px",
    control_radius="8px",
    panel_radius="10px",
)

DARK = Palette(
    bg="#0D1015",
    surface="#141821",
    surface_alt="#1B212C",
    card="#131821",
    border="#252D3A",
    border_soft="#1D242F",
    text="#E9EDF5",
    text_muted="#9AA6B8",
    text_faint="#667287",
    accent="#4F8CFF",
    accent_hover="#6B9EFF",
    accent_pressed="#3C78EC",
    accent_soft="#1B2A44",
    success="#3DDC97",
    success_soft="#14352B",
    warning="#F5AE3D",
    warning_soft="#362A17",
    danger="#F27373",
    danger_soft="#3A2025",
    selection="#1C2A40",
    track="#272F3D",
    scrollbar="#394456",
    sidebar_active="#1B2537",
    toolbar_background="#141821",
    menubar_background="#141821",
    status_background="#141821",
    header_background="transparent",
    row_hover="#1A202B",
    radius="6px",
    control_radius="8px",
    panel_radius="10px",
)

PALETTES = {
    "classic": CLASSIC,
    "light": LIGHT,
    "dark": DARK,
}

THEME_LABELS = {
    "classic": "Classic Light",
    "light": "Modern Light",
    "dark": "Modern Dark",
}

THEME_ORDER = ("classic", "light", "dark")


QSS_TEMPLATE = Template(
    """
QWidget {
    background-color: transparent;
    color: $text;
    font-family: "Segoe UI";
    font-size: 12px;
    selection-background-color: $accent;
    selection-color: #FFFFFF;
}
QMainWindow, QDialog, QMessageBox {
    background-color: $bg;
}
QToolTip {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: $control_radius;
    padding: 5px 8px;
    font-size: 11px;
}

/* ---------------------------------------------------------------- menu bar */
QMenuBar {
    background-color: $menubar_background;
    border-bottom: 1px solid $border;
    padding: 0px 4px;
    spacing: 0px;
}
QMenuBar::item {
    background: transparent;
    color: $text;
    padding: 5px 10px;
    border: none;
}
QMenuBar::item:selected {
    background-color: $sidebar_active;
    color: $text;
}
QMenuBar::item:pressed {
    background-color: $accent;
    color: #FFFFFF;
}

/* ----------------------------------------------------------------- toolbar */
QFrame#Toolbar {
    background: $toolbar_background;
    border-bottom: 1px solid $border;
}
QLabel#BrandName {
    font-size: 15px;
    font-weight: 700;
    color: $text;
    letter-spacing: 1px;
}
QLabel#BrandTagline {
    font-size: 9px;
    color: $text_faint;
    letter-spacing: 1px;
}
QFrame#ToolbarSeparator {
    background-color: $border;
    border: none;
    min-width: 1px;
    max-width: 1px;
}
QToolButton#ToolbarButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
    color: $text;
    padding: 3px 2px 2px 2px;
    font-size: 10px;
}
QToolButton#ToolbarButton:hover {
    background-color: $accent_soft;
    border-color: $border;
}
QToolButton#ToolbarButton:pressed {
    background-color: $selection;
    border-color: $accent;
}
QToolButton#ToolbarButton:disabled {
    color: $text_faint;
}
QToolButton#ThemeButton {
    border: 1px solid transparent;
    border-radius: $control_radius;
    padding: 5px;
}
QToolButton#ThemeButton:hover {
    background-color: $accent_soft;
    border-color: $border;
}

/* ----------------------------------------------------------------- sidebar */
QFrame#Sidebar {
    background-color: $surface;
    border-right: 1px solid $border;
}
QLabel#SidebarSection {
    color: $text_faint;
    font-size: 9px;
    font-weight: 700;
    padding: 9px 14px 3px 14px;
    letter-spacing: 1px;
}
QLabel#SidebarFooter {
    color: $text_faint;
    font-size: 10px;
    padding: 8px 14px;
}
QListWidget#SidebarList {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 0px;
}

/* ----------------------------------------------------------------- content */
QWidget#ContentArea {
    background-color: $bg;
}
QWidget#ContentHeader {
    background-color: transparent;
}
QLabel#PageTitle {
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel#PageSubtitle {
    font-size: 11px;
    color: $text_muted;
}
QLineEdit#SearchBox {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $control_radius;
    padding: 5px 9px;
    min-height: 20px;
    color: $text;
}
QLineEdit#SearchBox:focus {
    border-color: $accent;
}

/* ------------------------------------------------------------ table / card */
QFrame#ContentCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $panel_radius;
}
QLabel#EmptyTitle {
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel#EmptyText {
    font-size: 12px;
    color: $text_muted;
}
QLabel#EmptyHint {
    font-size: 10px;
    color: $text_faint;
}
QPushButton#EmptyAddButton {
    background-color: $accent;
    border: 1px solid $accent;
    color: #FFFFFF;
    font-weight: 600;
    border-radius: $control_radius;
    padding: 6px 18px;
}
QPushButton#EmptyAddButton:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}
QTableView#DownloadTable {
    background-color: $surface;
    alternate-background-color: $surface;
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: $selection;
    selection-color: $text;
}
QTableView#DownloadTable::item {
    border: none;
    border-bottom: 1px solid $border_soft;
    background-color: transparent;
    padding: 0px;
}
QTableView#DownloadTable::item:selected {
    background-color: $selection;
}
QTableView#DownloadTable::item:hover {
    background-color: $row_hover;
}
QHeaderView {
    background-color: transparent;
    border: none;
}
QHeaderView::section {
    background: $header_background;
    color: $text_muted;
    border: none;
    border-right: 1px solid $border_soft;
    border-bottom: 1px solid $border;
    padding: 5px 10px;
    font-size: 10px;
    font-weight: 700;
}
QHeaderView::section:hover {
    background-color: $surface_alt;
}
QTableCornerButton::section {
    background-color: $header_background;
    border: none;
}

/* --------------------------------------------------------------- scrollbars */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 1px;
}
QScrollBar::handle:vertical {
    background: $scrollbar;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: $text_faint;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 1px;
}
QScrollBar::handle:horizontal {
    background: $scrollbar;
    min-width: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: transparent;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ----------------------------------------------------------------- inputs */
QLineEdit, QComboBox, QSpinBox, QDateTimeEdit {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $control_radius;
    color: $text;
    padding: 4px 8px;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus {
    border-color: $accent;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateTimeEdit:disabled {
    color: $text_faint;
    background-color: $surface_alt;
}
QComboBox {
    padding-right: 26px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url("$chevron_icon");
    width: 11px;
    height: 11px;
}
QComboBox QAbstractItemView {
    background-color: $surface;
    border: 1px solid $border;
    padding: 3px;
    outline: none;
    selection-background-color: $sidebar_active;
    selection-color: $text;
}
QComboBox QAbstractItemView::item {
    min-height: 22px;
    padding: 2px 7px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 17px;
    background: transparent;
    border: none;
}
QDateTimeEdit::drop-down {
    border: none;
    width: 22px;
    background: transparent;
}

/* ---------------------------------------------------------------- buttons */
QPushButton {
    background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: $control_radius;
    color: $text;
    padding: 5px 14px;
    min-height: 20px;
}
QPushButton:hover {
    background-color: $accent_soft;
    border-color: $border;
}
QPushButton:pressed {
    background-color: $selection;
}
QPushButton:focus {
    border-color: $accent;
}
QPushButton:disabled {
    color: $text_faint;
}
QPushButton#PrimaryButton {
    background-color: $accent;
    border-color: $accent;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}
QPushButton#PrimaryButton:pressed {
    background-color: $accent_pressed;
}
QPushButton#DangerButton {
    background-color: transparent;
    border-color: $danger;
    color: $danger;
}
QPushButton#DangerButton:hover {
    background-color: $danger_soft;
}
QPushButton#LinkButton {
    background-color: transparent;
    border: none;
    color: $accent;
    padding: 2px 4px;
}

/* ------------------------------------------------------------- check / radio */
QCheckBox {
    spacing: 7px;
    color: $text;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid $border;
    border-radius: 3px;
    background-color: $surface;
}
QCheckBox::indicator:hover {
    border-color: $accent;
}
QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
    image: url("$check_icon");
}
QCheckBox::indicator:disabled {
    background-color: $surface_alt;
    border-color: $border_soft;
}
QRadioButton {
    spacing: 7px;
    color: $text;
}
QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid $border;
    border-radius: 8px;
    background-color: $surface;
}
QRadioButton::indicator:hover {
    border-color: $accent;
}
QRadioButton::indicator:checked {
    border: 4px solid $accent;
    background-color: $surface;
}

/* ---------------------------------------------------------------- dialogs */
QLabel#DialogTitle {
    font-size: 17px;
    font-weight: 600;
    color: $text;
}
QLabel#DialogSubtitle {
    font-size: 11px;
    color: $text_muted;
}
QLabel#FieldLabel {
    color: $text_muted;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#HintLabel {
    color: $text_faint;
    font-size: 10px;
}
QLabel#ErrorLabel {
    color: $danger;
    font-size: 11px;
}
QLabel#ProbeLabel {
    color: $text_faint;
    font-size: 10px;
}
QLabel#ProbeLabel[state="pending"] {
    color: $accent;
}
QLabel#ProbeLabel[state="ok"] {
    color: $success;
}
QLabel#ProbeLabel[state="warn"] {
    color: $warning;
}
QLabel#SectionTitle {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QFrame#Divider {
    background-color: $border;
    border: none;
    min-height: 1px;
    max-height: 1px;
}
QFrame#DialogCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $panel_radius;
}
QFrame#ThemeCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $control_radius;
}
QFrame#ThemeCard[selected="true"] {
    border: 2px solid $accent;
    background-color: $accent_soft;
}
QLabel#ThemeTitle {
    color: $text;
    font-size: 11px;
}
QLabel#ThemeDescription {
    color: $text_muted;
    font-size: 10px;
}
QFrame#ConnectionRow {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
}
QLabel#ConnectionName {
    color: $text;
    font-size: 11px;
    font-weight: 600;
}

/* ------------------------------------------------------------------- tabs */
$tabs_qss
QTabWidget QWidget#TabPage {
    background-color: transparent;
}

/* -------------------------------------------------------------- dialog table */
QTableWidget#DialogTable {
    background-color: $surface;
    border: 1px solid $border;
    gridline-color: transparent;
    outline: none;
}
QTableWidget#DialogTable::item {
    border-bottom: 1px solid $border_soft;
    padding: 4px 8px;
    background-color: transparent;
}
QTableWidget#DialogTable::item:selected {
    background-color: $selection;
    color: $text;
}

/* ------------------------------------------------------------------- menus */
QMenu {
    background-color: $surface;
    border: 1px solid $border;
    padding: 3px;
}
QMenu::item {
    background-color: transparent;
    color: $text;
    padding: 4px 26px 4px 26px;
}
QMenu::item:selected {
    background-color: $sidebar_active;
    color: $text;
}
QMenu::item:disabled {
    color: $text_faint;
}
QMenu::separator {
    height: 1px;
    background-color: $border_soft;
    margin: 3px 6px;
}
QMenu::icon {
    padding-left: 7px;
}

/* --------------------------------------------------------------- status bar */
QFrame#StatusBar {
    background-color: $status_background;
    border-top: 1px solid $border;
}
QLabel#StatusText {
    color: $text_muted;
    font-size: 11px;
}
QLabel#StatusValue {
    color: $text;
    font-size: 11px;
    font-weight: 600;
}
QLabel#StatusFaint {
    color: $text_faint;
    font-size: 11px;
}
QLabel#StatusMessage {
    color: $accent;
    font-size: 11px;
}
QLabel#StatusVersion {
    color: $text_faint;
    font-size: 10px;
}
QFrame#StatusBar QFrame#StatusDivider {
    background-color: $border;
    min-width: 1px;
    max-width: 1px;
}

/* ---------------------------------------------------------------- progress */
QProgressBar {
    background-color: $track;
    border: 1px solid $border;
    border-radius: 3px;
    text-align: center;
    color: $text;
    min-height: 12px;
}
QProgressBar::chunk {
    background-color: $accent;
    border-radius: 2px;
}
QProgressBar#DownloadProgress {
    min-height: 20px;
    font-weight: 600;
    border-radius: 4px;
}
QLabel#ProgressPercent {
    font-size: 22px;
    font-weight: 700;
    color: $accent;
}
QLabel#ProgressFile {
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#ProgressMeta {
    font-size: 10px;
    color: $text_faint;
}
QLabel#ProgressValue {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#ProgressKey {
    font-size: 10px;
    color: $text_faint;
}

/* ------------------------------------------------------------------ updates */
QLabel#UpdateValue {
    color: $text;
    font-weight: 600;
}
QLabel#LinkLabel {
    color: $accent;
    font-weight: 600;
}
QLabel#UpdateStatus {
    font-size: 11px;
    color: $text_muted;
}
QLabel#UpdateStatus[state="busy"] {
    color: $accent;
}
QLabel#UpdateStatus[state="ok"] {
    color: $success;
}
QLabel#UpdateStatus[state="warn"] {
    color: $warning;
}
QLabel#UpdateStatus[state="error"] {
    color: $danger;
}
QLabel#UpdateMandatory {
    color: $warning;
    font-size: 11px;
    font-weight: 600;
}
QPlainTextEdit#ReleaseNotes {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
    color: $text;
    padding: 6px;
    selection-background-color: $accent;
    selection-color: #FFFFFF;
}
QLabel#PlannedNote {
    color: $warning;
    background-color: $warning_soft;
    border: 1px solid $border;
    border-radius: $control_radius;
    padding: 5px 8px;
    font-size: 10px;
}

/* ------------------------------------------------------------ v3 workspace */
QScrollArea#SidebarScroll,
QWidget#SidebarContent {
    background: transparent;
    border: none;
}
QWidget#PageArea {
    background-color: transparent;
}
QScrollArea#PageScroll {
    background: transparent;
    border: none;
}
QWidget#PageScrollBody {
    background: transparent;
}
QFrame#StatCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $panel_radius;
}
QFrame#PanelCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $panel_radius;
}
QFrame#PanelCard:hover {
    border-color: $border;
}
QLabel#PanelTitle {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#PanelCaption {
    font-size: 10px;
    color: $text_faint;
}
QLabel#StatValue {
    font-size: 21px;
    font-weight: 700;
    color: $text;
}
QLabel#StatLabel {
    font-size: 10px;
    font-weight: 700;
    color: $text_faint;
    letter-spacing: 1px;
}
QLabel#StatDetail {
    font-size: 10px;
    color: $text_muted;
}
QFrame#StatCard[accent="true"] QLabel#StatValue {
    color: $accent;
}
QFrame#StatCard[accent="true"] {
    border-color: $accent;
}
QFrame#NoticeBanner {
    background-color: $accent_soft;
    border: 1px solid $border;
    border-radius: $control_radius;
}
QFrame#NoticeBanner[kind="warning"] {
    background-color: $warning_soft;
}
QFrame#NoticeBanner[kind="danger"] {
    background-color: $danger_soft;
}
QFrame#NoticeBanner[kind="success"] {
    background-color: $success_soft;
}
QLabel#NoticeTitle {
    font-size: 11px;
    font-weight: 600;
    color: $text;
}
QLabel#NoticeText {
    font-size: 10px;
    color: $text_muted;
}
QLabel#SectionHeading {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QPushButton#SubtleButton {
    background-color: transparent;
    border: 1px solid $border;
    color: $text_muted;
    padding: 4px 10px;
}
QPushButton#SubtleButton:hover {
    background-color: $accent_soft;
    border-color: $accent;
    color: $text;
}
QPushButton#PillButton {
    background-color: transparent;
    border: 1px solid $border;
    border-radius: 11px;
    color: $text_muted;
    padding: 2px 11px;
    min-height: 18px;
}
QPushButton#PillButton:hover {
    border-color: $accent;
    color: $accent;
}
QPushButton#PillButton:checked {
    background-color: $accent_soft;
    border-color: $accent;
    color: $accent;
    font-weight: 600;
}
QComboBox#PeriodCombo {
    min-width: 108px;
}
QTableView#VideoTable {
    background-color: $surface;
    alternate-background-color: $surface;
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: $selection;
    selection-color: $text;
}
QTableView#VideoTable::item {
    border: none;
    border-bottom: 1px solid $border_soft;
    background-color: transparent;
    padding: 0px;
}
QTableView#VideoTable::item:selected {
    background-color: $selection;
}
QTableView#VideoTable::item:hover {
    background-color: $row_hover;
}
QListWidget#NotificationList {
    background-color: $surface;
    border: none;
    outline: none;
}
QListWidget#NotificationList::item {
    border-bottom: 1px solid $border_soft;
    padding: 7px 10px;
    color: $text;
}
QListWidget#NotificationList::item:selected {
    background-color: $selection;
    color: $text;
}
QListWidget#ActivityList {
    background-color: transparent;
    border: none;
    outline: none;
}
QListWidget#ActivityList::item {
    border-bottom: 1px solid $border_soft;
    padding: 6px 2px;
    color: $text;
}
QListWidget#ActivityList::item:selected {
    background-color: $selection;
    color: $text;
}
QFrame#SettingRow {
    background-color: transparent;
    border-bottom: 1px solid $border_soft;
}
QLabel#SettingTitle {
    color: $text;
    font-size: 11px;
    font-weight: 600;
}
QLabel#SettingHint {
    color: $text_faint;
    font-size: 10px;
}
QLabel#Badge {
    background-color: $accent;
    color: #FFFFFF;
    border-radius: 8px;
    font-size: 9px;
    font-weight: 700;
    padding: 1px 6px;
}
QLabel#EmptyCaption {
    color: $text_faint;
    font-size: 11px;
}
QFrame#BrowserRow {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $control_radius;
}
QLabel#BrowserName {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#BrowserStatus {
    font-size: 10px;
    color: $text_muted;
}
QLabel#BrowserStatus[state="ok"] {
    color: $success;
}
QLabel#BrowserStatus[state="warn"] {
    color: $warning;
}
QLabel#BrowserStatus[state="error"] {
    color: $danger;
}
QProgressBar#MiniProgress {
    min-height: 5px;
    max-height: 5px;
    border: none;
    border-radius: 2px;
    background-color: $track;
}
QProgressBar#MiniProgress::chunk {
    background-color: $accent;
    border-radius: 2px;
}
"""
)

_CLASSIC_TABS = """
QTabWidget::pane {
    border: 1px solid $border;
    background-color: $surface;
    top: -1px;
}
QTabBar::tab {
    background: $toolbar_background;
    color: $text;
    border: 1px solid $border;
    border-bottom: none;
    padding: 5px 14px;
    margin-right: 2px;
    min-width: 62px;
}
QTabBar::tab:selected {
    background-color: $surface;
    border-bottom: 1px solid $surface;
    padding-bottom: 6px;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: $accent_soft;
}
"""

_MODERN_TABS = """
QTabWidget::pane {
    border: 1px solid $border;
    border-radius: $panel_radius;
    background-color: $surface;
    margin-top: 6px;
}
QTabBar::tab {
    background: transparent;
    color: $text_muted;
    border: none;
    border-radius: $control_radius;
    padding: 6px 14px;
    margin-right: 4px;
}
QTabBar::tab:hover {
    background-color: $surface_alt;
    color: $text;
}
QTabBar::tab:selected {
    background-color: $accent_soft;
    color: $accent;
    font-weight: 600;
}
"""


def _make_qpalette(p: Palette) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(p.bg))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(p.card))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface_alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(p.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(p.surface_alt))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(p.danger))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(p.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_faint))
    palette.setColor(QPalette.ColorRole.Link, QColor(p.accent))
    palette.setColor(QPalette.ColorRole.Mid, QColor(p.border))
    palette.setColor(QPalette.ColorRole.Dark, QColor(p.border))
    palette.setColor(QPalette.ColorRole.Light, QColor(p.border_soft))

    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(disabled, role, QColor(p.text_faint))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(p.card))
    palette.setColor(disabled, QPalette.ColorRole.Button, QColor(p.surface_alt))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor(p.accent_soft))
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, QColor(p.text_muted))
    return palette


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._mode = "classic"
        self._palette = CLASSIC

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def label(self) -> str:
        return THEME_LABELS.get(self._mode, THEME_LABELS["classic"])

    @property
    def is_dark(self) -> bool:
        return self._mode == "dark"

    @property
    def is_classic(self) -> bool:
        return self._mode == "classic"

    @property
    def palette(self) -> Palette:
        return self._palette

    @staticmethod
    def palette_for(mode: str) -> Palette:
        return PALETTES.get(mode, CLASSIC)

    def set_mode(self, mode: str, apply: bool = True) -> None:
        if mode not in PALETTES:
            mode = "classic"
        if mode == self._mode:
            if apply:
                self.apply()
            return
        self._mode = mode
        self._palette = PALETTES[mode]
        if apply:
            self.apply()

    def cycle(self) -> str:
        index = THEME_ORDER.index(self._mode) if self._mode in THEME_ORDER else 0
        mode = THEME_ORDER[(index + 1) % len(THEME_ORDER)]
        self.set_mode(mode)
        return mode

    def apply(self) -> None:
        p = self._palette
        icons.clear_icon_cache()
        self._app.setPalette(_make_qpalette(p))
        tokens = {field.name: str(getattr(p, field.name)) for field in fields(p)}
        tokens["check_icon"] = asset_path("check.svg").as_posix()
        tokens["chevron_icon"] = asset_path("chevron-down.svg").as_posix()
        tab_template = _CLASSIC_TABS if self.is_classic else _MODERN_TABS
        tokens["tabs_qss"] = Template(tab_template).substitute(tokens)
        self._app.setStyleSheet(QSS_TEMPLATE.substitute(tokens))
        self.changed.emit()

    def apply_window_chrome(self, window: QWidget) -> None:
        set_dark_title_bar(window, self.is_dark)


def set_dark_title_bar(window: QWidget, dark: bool) -> None:
    if sys.platform != "win32" or not window.isVisible():
        return
    try:
        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        for attribute in (20, 19):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        logger.debug("Could not set the Windows title bar appearance", exc_info=True)
