"""Design-system driven themes for IDM 3.5.

Every colour, radius and typography value used by the interface is compiled
from :mod:`idm.ui.design` tokens and the palettes below into one stylesheet.
Components never hardcode colours, so Light, Dark and "Follow Windows" stay
consistent across every page, dialog and custom-painted delegate.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass, fields
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ..core.paths import asset_path
from . import design, icons

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
    sidebar_bg: str
    sidebar_active: str
    nav_hover: str
    toolbar_background: str
    menubar_background: str
    status_background: str
    header_background: str
    row_hover: str
    card_hover: str
    chip_bg: str
    chip_text: str
    focus_ring: str
    accent_gradient: str
    hero_text: str
    on_accent: str
    shadow: str
    radius: str
    control_radius: str
    panel_radius: str
    input_radius: str
    pill_radius: str


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

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
    sidebar_bg="#FFFFFF",
    sidebar_active="#E3F1FB",
    nav_hover="#F0F5FA",
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
    card_hover="#F8FBFE",
    chip_bg="#EEF3F8",
    chip_text="#4A5A6B",
    focus_ring="#9CC8EC",
    accent_gradient=(
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        "stop:0 #1A8FE3, stop:1 #0E64AA)"
    ),
    hero_text="#FFFFFF",
    on_accent="#FFFFFF",
    shadow="#233746",
    radius="3px",
    control_radius="4px",
    panel_radius="4px",
    input_radius="4px",
    pill_radius="14px",
)

LIGHT = Palette(
    bg="#F1F4FA",
    surface="#FFFFFF",
    surface_alt="#F6F8FD",
    card="#FFFFFF",
    border="#DDE4F0",
    border_soft="#E9EEF7",
    text="#0E1726",
    text_muted="#526079",
    text_faint="#7E8AA0",
    accent="#1D5BEA",
    accent_hover="#1749CC",
    accent_pressed="#123AA8",
    accent_soft="#EDF2FF",
    success="#0E9F6E",
    success_soft="#E2F8EF",
    warning="#B26B00",
    warning_soft="#FFF3DE",
    danger="#D64545",
    danger_soft="#FDEDED",
    selection="#E7EEFF",
    track="#E4EAF5",
    scrollbar="#C3CDDE",
    sidebar_bg="#F8FAFE",
    sidebar_active="#E7EEFF",
    nav_hover="#EFF3FB",
    toolbar_background="#FFFFFF",
    menubar_background="#FFFFFF",
    status_background="#F8FAFE",
    header_background="transparent",
    row_hover="#F6F9FF",
    card_hover="#FAFCFF",
    chip_bg="#F0F4FB",
    chip_text="#46536A",
    focus_ring="#B9CDFF",
    accent_gradient=(
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        "stop:0 #3F7DFF, stop:0.55 #1D5BEA, stop:1 #1743C2)"
    ),
    hero_text="#FFFFFF",
    on_accent="#FFFFFF",
    shadow="#0B1B36",
    radius="8px",
    control_radius="10px",
    panel_radius="14px",
    input_radius="10px",
    pill_radius="14px",
)

DARK = Palette(
    bg="#080D18",
    surface="#0E1626",
    surface_alt="#131D30",
    card="#101A2B",
    border="#22314B",
    border_soft="#19243A",
    text="#E9F0FC",
    text_muted="#9DAEC8",
    text_faint="#66788F",
    accent="#4D8DFF",
    accent_hover="#6EA4FF",
    accent_pressed="#3B78EB",
    accent_soft="#14284B",
    success="#3DD6A0",
    success_soft="#0D3429",
    warning="#F2B45E",
    warning_soft="#35280F",
    danger="#FF7B7B",
    danger_soft="#3B1D22",
    selection="#15294A",
    track="#1E2B42",
    scrollbar="#35455F",
    sidebar_bg="#0A1220",
    sidebar_active="#152744",
    nav_hover="#111B2D",
    toolbar_background="#0A1220",
    menubar_background="#0A1220",
    status_background="#090F1A",
    header_background="transparent",
    row_hover="#121D31",
    card_hover="#142039",
    chip_bg="#182338",
    chip_text="#A9B7CD",
    focus_ring="#2C4E88",
    accent_gradient=(
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        "stop:0 #3F7BFF, stop:0.55 #1D5BEA, stop:1 #123A9E)"
    ),
    hero_text="#FFFFFF",
    on_accent="#FFFFFF",
    shadow="#000000",
    radius="8px",
    control_radius="10px",
    panel_radius="14px",
    input_radius="10px",
    pill_radius="14px",
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
    "system": "Follow Windows",
}

# Order used by selectors.  Classic is legacy but still fully supported.
THEME_ORDER = ("classic", "light", "dark", "system")
MODERN_THEMES = ("light", "dark", "system")


def system_prefers_dark() -> bool:
    """Resolve the Windows app theme, falling back to the registry."""
    try:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)
        if scheme is not None:
            value = scheme()
            if value == Qt.ColorScheme.Dark:
                return True
            if value == Qt.ColorScheme.Light:
                return False
    except Exception:
        logger.debug("Qt colour scheme unavailable", exc_info=True)
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            with key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(value) == 0
        except OSError:
            pass
    return False


def resolved_palette(mode: str) -> Palette:
    if mode == "system":
        return DARK if system_prefers_dark() else LIGHT
    return PALETTES.get(mode, CLASSIC)


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

_radius_tokens = {
    "radius": design.RADIUS["sm"],
    "control_radius": design.RADIUS["md"],
    "panel_radius": design.RADIUS["lg"],
    "input_radius": design.RADIUS["md"],
    "pill_radius": design.RADIUS["pill"],
}

QSS_TEMPLATE = Template(
    """
* {
    outline: none;
}
QWidget {
    background-color: transparent;
    color: $text;
    font-family: $font_family;
    font-size: 13px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QMainWindow, QDialog, QMessageBox, QFileDialog {
    background-color: $bg;
}
QLabel {
    background: transparent;
}
QToolTip {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: $radius;
    padding: 6px 10px;
    font-size: 12px;
}

/* ------------------------------------------------------------------ menu bar */
QMenuBar {
    background-color: $menubar_background;
    border-bottom: 1px solid $border_soft;
    padding: 2px 6px;
    spacing: 2px;
}
QMenuBar::item {
    background: transparent;
    color: $text_muted;
    padding: 5px 10px;
    border-radius: $radius;
}
QMenuBar::item:selected {
    background-color: $nav_hover;
    color: $text;
}
QMenuBar::item:pressed {
    background-color: $accent_soft;
    color: $accent;
}

/* ------------------------------------------------------------------- toolbar */
QFrame#Toolbar {
    background: $toolbar_background;
    border-bottom: 1px solid $border_soft;
}
QFrame#Toolbar[floating="true"] {
    border-bottom: 1px solid $border_soft;
}
QLabel#BrandName {
    font-size: 17px;
    font-weight: 700;
    color: $text;
    letter-spacing: 0.4px;
}
QLabel#BrandTagline {
    font-size: 9px;
    font-weight: 600;
    color: $text_faint;
    letter-spacing: 1.8px;
}
QFrame#ToolbarSeparator {
    background-color: $border_soft;
    border: none;
    min-width: 1px;
    max-width: 1px;
}
QFrame#ActionDivider {
    background-color: $border_soft;
    border: none;
    min-width: 1px;
    max-width: 1px;
}
QToolButton#ToolbarButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
    color: $text_muted;
    padding: 2px;
    font-size: 11px;
    font-weight: 500;
}
QToolButton#ToolbarButton:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
    color: $text;
}
QToolButton#ToolbarButton:pressed {
    background-color: $selection;
    border-color: $focus_ring;
}
QToolButton#ToolbarButton:checked {
    background-color: $accent_soft;
    border-color: $focus_ring;
    color: $accent;
}
QToolButton#ToolbarButton:disabled {
    color: $text_faint;
}
QToolButton#ToolbarButton[accent="true"] {
    background: $accent_gradient;
    border-color: $accent_pressed;
    color: $on_accent;
    font-weight: 600;
    padding-left: 14px;
    padding-right: 16px;
}
QToolButton#ToolbarButton[accent="true"]:hover {
    border-color: $accent_hover;
}
QToolButton#ToolbarButton[accent="true"]:pressed {
    background: $accent_pressed;
    border-color: $accent_pressed;
}
QToolButton#ThemeButton {
    border: 1px solid transparent;
    border-radius: $control_radius;
    padding: 4px;
    background: transparent;
}
QToolButton#ThemeButton:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
}
QToolButton#IconButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
    padding: 5px;
}
QToolButton#IconButton:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
}
QToolButton#IconButton:pressed {
    background-color: $selection;
}
QToolButton#IconButton:checked {
    background-color: $accent_soft;
    color: $accent;
}
QToolButton#IconButton:disabled {
    color: $text_faint;
}

/* ------------------------------------------------------------------- sidebar */
QFrame#Sidebar {
    background-color: $sidebar_bg;
    border-right: 1px solid $border_soft;
}
QLabel#SidebarSection {
    color: $text_faint;
    font-size: 9px;
    font-weight: 700;
    padding: 16px 16px 6px 16px;
    letter-spacing: 1.6px;
}
QLabel#SidebarFooter {
    color: $text_faint;
    font-size: 10px;
    padding: 4px 16px 10px 16px;
}
QFrame#SidebarFooterBox {
    border-top: 1px solid $border_soft;
    background: transparent;
}
QPushButton#SidebarSettings {
    background: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
    color: $text_muted;
    font-size: 13px;
    font-weight: 500;
    text-align: left;
    padding: 9px 12px;
}
QPushButton#SidebarSettings:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
    color: $text;
}
QPushButton#SidebarSettings[active="true"] {
    background-color: $sidebar_active;
    color: $accent;
    border-color: $focus_ring;
}
QListWidget#SidebarList {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 0px;
}
QToolButton#SidebarToggle {
    background: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
    padding: 5px;
}
QToolButton#SidebarToggle:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
}
QFrame#SidebarBrand {
    background: transparent;
}

/* ------------------------------------------------------------------- content */
QWidget#ContentArea {
    background-color: $bg;
}
QWidget#ContentHeader {
    background-color: transparent;
}
QLabel#PageTitle {
    font-size: 24px;
    font-weight: 600;
    color: $text;
    letter-spacing: -0.5px;
}
QLabel#PageSubtitle {
    font-size: 13px;
    color: $text_muted;
}
QLabel#PageEyebrow {
    font-size: 10px;
    font-weight: 700;
    color: $accent;
    letter-spacing: 1.4px;
}
QLineEdit#SearchBox {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $input_radius;
    padding: 7px 12px;
    min-height: 22px;
    color: $text;
}
QLineEdit#SearchBox:hover {
    border-color: $border;
}
QLineEdit#SearchBox:focus {
    border-color: $accent;
    background-color: $surface;
}

/* ------------------------------------------------------------- panel / cards */
QFrame#ContentCard, QFrame#PanelCard, QFrame#StatCard, QFrame#DialogCard,
QFrame#SettingCard, QFrame#StatusCard, QFrame#VideoSurface {
    background-color: $card;
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
}
QFrame#PanelCard:hover, QFrame#SettingCard:hover {
    border-color: $border;
}
QFrame#StatCard {
    border-radius: $panel_radius;
}
QFrame#StatCard[accent="true"] {
    border-color: $focus_ring;
    background-color: $card;
}
QLabel#StatValue {
    font-size: 26px;
    font-weight: 700;
    color: $text;
    letter-spacing: -0.6px;
}
QLabel#StatLabel {
    font-size: 10px;
    font-weight: 700;
    color: $text_faint;
    letter-spacing: 1.2px;
}
QLabel#StatDetail {
    font-size: 12px;
    color: $text_muted;
}
QFrame#StatCard[accent="true"] QLabel#StatValue {
    color: $accent;
}
QLabel#PanelTitle {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#PanelCaption {
    font-size: 12px;
    color: $text_faint;
}
QLabel#SectionHeading {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#MutedCaption {
    font-size: 12px;
    color: $text_faint;
}
QFrame#Divider {
    background-color: $border_soft;
    border: none;
    min-height: 1px;
    max-height: 1px;
}
QFrame#VerticalDivider {
    background-color: $border_soft;
    border: none;
    min-width: 1px;
    max-width: 1px;
}

/* ---------------------------------------------------------------- hero panel */
QFrame#HeroCard {
    background: $accent_gradient;
    border: 1px solid transparent;
    border-radius: $panel_radius;
}
QLabel#HeroEyebrow {
    color: rgba(255, 255, 255, 0.80);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.6px;
}
QLabel#HeroTitle {
    color: $hero_text;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.5px;
}
QLabel#HeroText {
    color: rgba(255, 255, 255, 0.82);
    font-size: 13px;
}
QLabel#HeroBadge {
    color: $hero_text;
    background-color: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    padding: 3px 10px;
}
QPushButton#HeroButton {
    background-color: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.32);
    color: $hero_text;
    border-radius: $control_radius;
    padding: 8px 16px;
    min-height: 22px;
    font-weight: 600;
}
QPushButton#HeroButton:hover {
    background-color: rgba(255, 255, 255, 0.24);
}
QPushButton#HeroPrimary {
    background-color: #FFFFFF;
    border: 1px solid #FFFFFF;
    color: $accent_pressed;
    border-radius: $control_radius;
    padding: 8px 18px;
    min-height: 22px;
    font-weight: 700;
}
QPushButton#HeroPrimary:hover {
    background-color: #F2F6FF;
}
QLabel#HeroStatValue {
    color: $hero_text;
    font-size: 19px;
    font-weight: 700;
}
QLabel#HeroStatLabel {
    color: rgba(255, 255, 255, 0.72);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.0px;
}

/* ------------------------------------------------------------- quick actions */
QPushButton#QuickAction {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
    color: $text_muted;
    padding: 8px 10px;
    font-size: 12px;
    text-align: left;
}
QPushButton#QuickAction:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
    color: $text;
}
QPushButton#QuickAction:pressed {
    background-color: $selection;
}
QFrame#TransferRow {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: $control_radius;
}
QFrame#TransferRow:hover {
    background-color: $nav_hover;
    border-color: $border_soft;
}
QLabel#TransferName {
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#TransferMeta {
    font-size: 11px;
    color: $text_muted;
}

/* -------------------------------------------------------------- table / list */
QTableView#DownloadTable, QTableView#VideoTable {
    background-color: transparent;
    alternate-background-color: transparent;
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: $selection;
    selection-color: $text;
}
QTableView#DownloadTable::item, QTableView#VideoTable::item {
    border: none;
    background-color: transparent;
    padding: 0px;
}
QTableView#DownloadTable::item:selected, QTableView#VideoTable::item:selected {
    background-color: $selection;
}
QTableView#DownloadTable::item:hover, QTableView#VideoTable::item:hover {
    background-color: $row_hover;
}
QHeaderView {
    background-color: transparent;
    border: none;
}
QHeaderView::section {
    background: $header_background;
    color: $text_faint;
    border: none;
    border-right: 1px solid transparent;
    border-bottom: 1px solid $border_soft;
    padding: 5px 12px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
QHeaderView::section:hover {
    color: $text;
    background-color: $surface_alt;
}
QTableCornerButton::section {
    background-color: transparent;
    border: none;
}
QListView#VideoCardList {
    background-color: transparent;
    border: none;
    outline: none;
    selection-background-color: transparent;
}
QListWidget#NotificationList {
    background-color: $surface;
    border: none;
    outline: none;
}
QListWidget#NotificationList::item {
    border-bottom: 1px solid $border_soft;
    padding: 11px 14px;
    color: $text;
    border-radius: 0px;
}
QListWidget#NotificationList::item:selected {
    background-color: $selection;
    color: $text;
}
QListWidget#NotificationList::item:hover {
    background-color: $row_hover;
}
QListWidget#ActivityList {
    background-color: transparent;
    border: none;
    outline: none;
}
QListWidget#ActivityList::item {
    border-bottom: 1px solid $border_soft;
    padding: 9px 4px;
    color: $text;
}
QListWidget#ActivityList::item:selected {
    background-color: $selection;
    color: $text;
}
QListWidget#ActivityList::item:hover {
    background-color: $row_hover;
}
QListView#HistoryList {
    background: transparent;
    border: none;
    outline: none;
}

/* --------------------------------------------------------------- scrollbars */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: $scrollbar;
    min-height: 32px;
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
    height: 12px;
    margin: 3px;
}
QScrollBar::handle:horizontal {
    background: $scrollbar;
    min-width: 32px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: transparent;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* -------------------------------------------------------------------- inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $input_radius;
    color: $text;
    padding: 7px 12px;
    min-height: 22px;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateTimeEdit:hover {
    border-color: $border;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus {
    border-color: $accent;
    background-color: $surface;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateTimeEdit:disabled {
    color: $text_faint;
    background-color: $bg;
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
    border-radius: $control_radius;
    padding: 4px;
    outline: none;
    selection-background-color: $accent_soft;
    selection-color: $accent;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 3px 8px;
    border-radius: $radius;
    color: $text;
}
QComboBox QAbstractItemView::item:selected {
    background-color: $accent_soft;
    color: $accent;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 18px;
    background: transparent;
    border: none;
}
QDateTimeEdit::drop-down {
    border: none;
    width: 22px;
    background: transparent;
}

/* ------------------------------------------------------------------- buttons */
QPushButton {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $control_radius;
    color: $text;
    padding: 7px 16px;
    min-height: 22px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: $nav_hover;
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
    background-color: $surface_alt;
    border-color: $border_soft;
}
QPushButton#PrimaryButton {
    background: $accent_gradient;
    border-color: $accent_pressed;
    color: $on_accent;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    border-color: $accent_hover;
}
QPushButton#PrimaryButton:pressed {
    background: $accent_pressed;
    border-color: $accent_pressed;
}
QPushButton#PrimaryButton:disabled {
    background-color: $surface_alt;
    border-color: $border_soft;
    color: $text_faint;
}
QPushButton#SubtleButton {
    background-color: transparent;
    border: 1px solid $border;
    color: $text_muted;
    padding: 6px 13px;
}
QPushButton#SubtleButton:hover {
    background-color: $accent_soft;
    border-color: $focus_ring;
    color: $text;
}
QPushButton#GhostButton {
    background-color: transparent;
    border: 1px solid transparent;
    color: $text_muted;
    padding: 6px 10px;
}
QPushButton#GhostButton:hover {
    background-color: $nav_hover;
    color: $text;
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
    font-weight: 600;
}
QPushButton#LinkButton:hover {
    color: $accent_hover;
}
QPushButton#PillButton {
    background-color: transparent;
    border: 1px solid $border_soft;
    border-radius: $pill_radius;
    color: $text_muted;
    padding: 4px 13px;
    min-height: 20px;
    font-size: 12px;
}
QPushButton#PillButton:hover {
    border-color: $focus_ring;
    color: $text;
}
QPushButton#PillButton:checked {
    background-color: $accent_soft;
    border-color: $focus_ring;
    color: $accent;
    font-weight: 600;
}
QPushButton#EmptyAddButton {
    background: $accent_gradient;
    border: 1px solid $accent_pressed;
    color: $on_accent;
    font-weight: 600;
    border-radius: $control_radius;
    padding: 8px 22px;
}
QPushButton#EmptyAddButton:hover {
    border-color: $accent_hover;
}
QPushButton#ChipButton {
    background-color: $chip_bg;
    border: 1px solid transparent;
    border-radius: $pill_radius;
    color: $chip_text;
    padding: 5px 14px;
    font-size: 12px;
}
QPushButton#ChipButton:hover {
    border-color: $focus_ring;
    color: $text;
}
QPushButton#ChipButton:checked {
    background-color: $accent_soft;
    border-color: $focus_ring;
    color: $accent;
    font-weight: 600;
}

/* ------------------------------------------------------------- check / radio */
QCheckBox, QRadioButton {
    spacing: 8px;
    color: $text;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $border;
    border-radius: 4px;
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
QRadioButton::indicator {
    width: 16px;
    height: 16px;
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

/* ------------------------------------------------------------------- badges */
QLabel#Badge {
    background-color: $accent;
    color: $on_accent;
    border-radius: 8px;
    font-size: 9px;
    font-weight: 700;
    padding: 1px 7px;
}
QLabel#Badge[tone="success"] {
    background-color: $success_soft;
    color: $success;
}
QLabel#Badge[tone="warning"] {
    background-color: $warning_soft;
    color: $warning;
}
QLabel#Badge[tone="danger"] {
    background-color: $danger_soft;
    color: $danger;
}
QLabel#Badge[tone="muted"] {
    background-color: $chip_bg;
    color: $chip_text;
}
QLabel#CountBadge {
    background-color: $accent_soft;
    color: $accent;
    border-radius: 8px;
    font-size: 9px;
    font-weight: 700;
    padding: 1px 7px;
}
QLabel#VerifiedBadge {
    background-color: $success_soft;
    color: $success;
    border: 1px solid $success;
    border-radius: $pill_radius;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 9px;
}
QLabel#LinkLabel {
    color: $accent;
    font-weight: 600;
}

/* ------------------------------------------------------------ notices / hero */
QFrame#NoticeBanner {
    background-color: $accent_soft;
    border: 1px solid $focus_ring;
    border-radius: $control_radius;
}
QFrame#NoticeBanner[kind="warning"] {
    background-color: $warning_soft;
    border-color: $warning;
}
QFrame#NoticeBanner[kind="danger"] {
    background-color: $danger_soft;
    border-color: $danger;
}
QFrame#NoticeBanner[kind="success"] {
    background-color: $success_soft;
    border-color: $success;
}
QLabel#NoticeTitle {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#NoticeText {
    font-size: 11px;
    color: $text_muted;
}
QLabel#InfoTileTitle {
    font-size: 11px;
    font-weight: 600;
    color: $text;
}
QLabel#InfoTileText {
    font-size: 10px;
    color: $text_muted;
}
QFrame#InfoTile {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
}

/* ----------------------------------------------------------------- settings */
QFrame#SettingRow {
    background-color: transparent;
    border-bottom: 1px solid $border_soft;
}
QLabel#SettingTitle {
    color: $text;
    font-size: 13px;
    font-weight: 600;
}
QLabel#SettingHint {
    color: $text_faint;
    font-size: 12px;
}
QFrame#SettingCard {
    background-color: $card;
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
}
QFrame#SettingsCommandBar {
    background-color: $card;
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
}
QLabel#SettingCardTitle {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#SettingCardHint {
    font-size: 12px;
    color: $text_faint;
}
QListWidget#SettingsNav {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#SettingsNav::item {
    padding: 10px 14px;
    border-radius: $control_radius;
    color: $text_muted;
    margin: 2px 0px;
}
QListWidget#SettingsNav::item:hover {
    background-color: $nav_hover;
    color: $text;
}
QListWidget#SettingsNav::item:selected {
    background-color: $accent_soft;
    color: $accent;
    font-weight: 600;
}

/* ---------------------------------------------------------------- dialogs */
QLabel#DialogTitle {
    font-size: 21px;
    font-weight: 600;
    color: $text;
    letter-spacing: -0.3px;
}
QLabel#DialogSubtitle {
    font-size: 13px;
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
    font-size: 11px;
}
QLabel#ErrorLabel {
    color: $danger;
    font-size: 11px;
}
QLabel#ErrorLabel[tone="info"] {
    color: $text_muted;
}
QLabel#ErrorLabel[tone="ok"] {
    color: $success;
}
QLabel#ErrorLabel[tone="warn"] {
    color: $warning;
}
QLabel#ProbeLabel {
    color: $text_faint;
    font-size: 11px;
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
QLabel#CompletionBadge {
    background-color: $success_soft;
    border-radius: 26px;
}
QLabel#CompletionFileName {
    font-size: 13px;
    font-weight: 600;
    color: $text;
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
QFrame#FileInfoCard {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
}
QLabel#FileInfoKey {
    color: $text_faint;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
QLabel#FileInfoValue {
    color: $text;
    font-size: 12px;
}
QLabel#FileNamePreview {
    color: $text;
    font-size: 15px;
    font-weight: 600;
}
QLabel#FileTypeIcon {
    background-color: $card;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
}
QCheckBox#RememberPath {
    color: $text_muted;
    font-size: 12px;
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
    padding: 9px 12px;
}
QCheckBox#RememberPath:hover {
    background-color: $card_hover;
    border-color: $focus_ring;
    color: $text;
}
QCheckBox#RememberPath:checked {
    background-color: $accent_soft;
    border-color: $focus_ring;
    color: $accent;
    font-weight: 600;
}

/* ------------------------------------------- download file info dialog (3.6) */
QLabel#DialogBrand {
    background: $accent_gradient;
    border-radius: 13px;
}
QLabel#DialogEyebrow {
    color: $accent;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
}
QLabel#DialogMetaBadge {
    color: $text_faint;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
    padding: 4px 9px;
    border: 1px solid $border_soft;
    border-radius: $pill_radius;
}
QFrame#FileHeroCard {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 $surface_alt, stop:1 $surface
    );
    border: 1px solid $border;
    border-radius: $panel_radius;
}
QFrame#FileHeroCard:hover {
    border-color: $focus_ring;
}
QLabel#CategoryPill {
    background-color: $accent_soft;
    border: 1px solid $focus_ring;
    border-radius: $pill_radius;
    color: $accent;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
}
QLabel#MetaChip {
    background-color: $chip_bg;
    border: 1px solid transparent;
    border-radius: $pill_radius;
    color: $chip_text;
    font-size: 11px;
    padding: 3px 10px;
}
QFrame#OptionsCard, QFrame#InfoCard {
    background-color: $surface;
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
}
QLabel#CardTitle {
    color: $text;
    font-size: 13px;
    font-weight: 600;
}
QLineEdit#UrlInput {
    font-size: 13px;
    padding: 8px 12px;
    min-height: 24px;
}
QLineEdit#SaveAsInput, QLineEdit#FolderInput {
    padding: 8px 12px;
    min-height: 24px;
}
QComboBox#CategoryCombo {
    padding: 8px 12px;
    padding-right: 30px;
    min-height: 24px;
}
QPlainTextEdit#DescriptionEdit {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $input_radius;
    color: $text;
    padding: 8px 10px;
    selection-background-color: $selection;
    selection-color: $text;
}
QPlainTextEdit#DescriptionEdit:hover {
    border-color: $border;
}
QPlainTextEdit#DescriptionEdit:focus {
    border-color: $accent;
    background-color: $surface;
}
QFrame#DialogFooter {
    background-color: $surface_alt;
    border-top: 1px solid $border_soft;
}
QLabel#FooterHint {
    color: $text_faint;
    font-size: 11px;
}
QPushButton#PrimaryButton[prominent="true"] {
    padding: 9px 26px;
    font-size: 13px;
    min-height: 24px;
}
QPushButton#PrimaryButton[prominent="true"]:hover {
    border-color: $accent_hover;
}

/* --------------------------------------------------------------------- tabs */
$tabs_qss
QTabWidget QWidget#TabPage {
    background-color: transparent;
}
QScrollArea#DialogScroll {
    background: transparent;
    border: none;
}
QScrollArea#DialogScroll > QWidget > QWidget {
    background: transparent;
}
QTableWidget#DialogTable {
    background-color: $surface;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
    gridline-color: transparent;
    outline: none;
}
QTableWidget#DialogTable::item {
    border-bottom: 1px solid $border_soft;
    padding: 5px 8px;
    background-color: transparent;
}
QTableWidget#DialogTable::item:selected {
    background-color: $selection;
    color: $text;
}

/* -------------------------------------------------------------------- menus */
QMenu {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $control_radius;
    padding: 5px;
}
QMenu::item {
    background-color: transparent;
    color: $text;
    padding: 6px 28px 6px 28px;
    border-radius: $radius;
}
QMenu::item:selected {
    background-color: $accent_soft;
    color: $accent;
}
QMenu::item:disabled {
    color: $text_faint;
}
QMenu::separator {
    height: 1px;
    background-color: $border_soft;
    margin: 4px 8px;
}
QMenu::icon {
    padding-left: 8px;
}

/* --------------------------------------------------------------- status bar */
QFrame#StatusBar {
    background-color: $status_background;
    border-top: 1px solid $border_soft;
}
QLabel#StatusText {
    color: $text_muted;
    font-size: 12px;
}
QLabel#StatusValue {
    color: $text;
    font-size: 12px;
    font-weight: 600;
}
QLabel#StatusFaint {
    color: $text_faint;
    font-size: 12px;
}
QLabel#StatusTotal {
    color: $text_faint;
    font-size: 12px;
}
QLabel#StatusMessage {
    color: $accent;
    font-size: 12px;
}
QLabel#StatusVersion {
    color: $text_faint;
    font-size: 11px;
}
QFrame#StatusBar QFrame#StatusDivider {
    background-color: $border_soft;
    min-width: 1px;
    max-width: 1px;
}

/* ---------------------------------------------------------------- progress */
QProgressBar {
    background-color: $track;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: $text;
    min-height: 8px;
    max-height: 8px;
}
QProgressBar::chunk {
    background: $accent_gradient;
    border-radius: 4px;
}
QProgressBar#DownloadProgress {
    min-height: 18px;
    max-height: 18px;
    border-radius: 9px;
    font-weight: 600;
    font-size: 10px;
}
QProgressBar#DownloadProgress::chunk {
    border-radius: 9px;
    background: $accent_gradient;
}
QProgressBar#StorageBar {
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
    background-color: $track;
}
QProgressBar#StorageBar::chunk {
    border-radius: 4px;
    background: $accent_gradient;
}
QProgressBar#MiniProgress {
    min-height: 6px;
    max-height: 6px;
    border: none;
    border-radius: 3px;
    background-color: $track;
}
QProgressBar#MiniProgress::chunk {
    background: $accent_gradient;
    border-radius: 3px;
}
QLabel#ProgressPercent {
    font-size: 24px;
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
    padding: 8px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLabel#PlannedNote {
    color: $warning;
    background-color: $warning_soft;
    border: 1px solid $warning;
    border-radius: $control_radius;
    padding: 6px 9px;
    font-size: 10px;
}

/* --------------------------------------------------------------- v3 elements */
QScrollArea#SidebarScroll, QWidget#SidebarContent,
QWidget#PageArea, QScrollArea#PageScroll, QWidget#PageScrollBody {
    background: transparent;
    border: none;
}
QComboBox#PeriodCombo {
    min-width: 108px;
}
QLabel#EmptyTitle {
    font-size: 19px;
    font-weight: 600;
    color: $text;
    letter-spacing: -0.2px;
}
QLabel#EmptyText {
    font-size: 12px;
    color: $text_muted;
}
QLabel#EmptyHint {
    font-size: 10px;
    color: $text_faint;
}
QLabel#EmptyCaption {
    color: $text_faint;
    font-size: 11px;
}
QFrame#BrowserRow {
    background-color: $surface_alt;
    border: 1px solid $border_soft;
    border-radius: $control_radius;
}
QFrame#VideoCard {
    background-color: $card;
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
}
QFrame#VideoCard:hover {
    border-color: $focus_ring;
    background-color: $card_hover;
}
QFrame#VideoCard:focus {
    border-color: $accent;
}
QLabel#VideoTitle {
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#VideoMeta {
    font-size: 11px;
    color: $text_muted;
}
QLabel#VideoBadge {
    font-size: 10px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 9px;
    background-color: $chip_bg;
    color: $text_faint;
}
QLabel#VideoBadge[state="active"] {
    background-color: $accent_soft;
    color: $accent;
}
QLabel#VideoBadge[state="ok"] {
    background-color: $success_soft;
    color: $success;
}
QLabel#VideoBadge[state="warn"] {
    background-color: $warning_soft;
    color: $warning;
}
QLabel#VideoBadge[state="error"] {
    background-color: $danger_soft;
    color: $danger;
}
QLabel#BrowserName {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#BrowserStatus {
    font-size: 11px;
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
QLabel#BrowserStatus[state="idle"] {
    color: $text_faint;
}
QFrame#StatusDot {
    border-radius: 4px;
}

/* ------------------------------------------------------------------- toasts */
QFrame#Toast {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: $panel_radius;
}
QFrame#Toast[kind="success"] {
    border-left: 3px solid $success;
}
QFrame#Toast[kind="warning"] {
    border-left: 3px solid $warning;
}
QFrame#Toast[kind="error"] {
    border-left: 3px solid $danger;
}
QFrame#Toast[kind="info"] {
    border-left: 3px solid $accent;
}
QLabel#ToastTitle {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#ToastText {
    font-size: 11px;
    color: $text_muted;
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
    border: 1px solid $border_soft;
    border-radius: $panel_radius;
    background-color: $surface;
    margin-top: 8px;
}
QTabBar::tab {
    background: transparent;
    color: $text_muted;
    border: 1px solid transparent;
    border-radius: $control_radius;
    padding: 9px 16px;
    margin-right: 4px;
}
QTabBar::tab:hover {
    background-color: $nav_hover;
    color: $text;
}
QTabBar::tab:selected {
    background-color: $accent_soft;
    border-color: $focus_ring;
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
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(p.on_accent))
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
    """Applies the current theme and reports when it changes."""

    changed = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._mode = "classic"
        self._palette = CLASSIC
        self._system_watch = False
        self._watch_system_theme()

    # ------------------------------------------------------------------ state
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def resolved_mode(self) -> str:
        if self._mode == "system":
            return "dark" if system_prefers_dark() else "light"
        return self._mode

    @property
    def label(self) -> str:
        if self._mode == "system":
            return f"System · {self.resolved_mode.title()}"
        return THEME_LABELS.get(self._mode, THEME_LABELS["classic"])

    @property
    def is_dark(self) -> bool:
        return self.resolved_mode == "dark"

    @property
    def is_classic(self) -> bool:
        return self._mode == "classic"

    @property
    def is_system(self) -> bool:
        return self._mode == "system"

    @property
    def palette(self) -> Palette:
        return self._palette

    @staticmethod
    def palette_for(mode: str) -> Palette:
        return resolved_palette(mode)

    # ------------------------------------------------------------------ apply
    def set_mode(self, mode: str, apply: bool = True) -> None:
        if mode not in THEME_ORDER:
            mode = "classic"
        changed_palette = resolved_palette(mode)
        if mode == self._mode and changed_palette == self._palette:
            if apply:
                self.apply()
            return
        self._mode = mode
        self._palette = changed_palette
        if apply:
            self.apply()

    def cycle(self) -> str:
        """Cycle through the three modern themes (light → dark → system)."""
        order = MODERN_THEMES
        current = self._mode if self._mode in order else "light"
        index = order.index(current)
        mode = order[(index + 1) % len(order)]
        self.set_mode(mode)
        return mode

    def apply(self) -> None:
        self._palette = resolved_palette(self._mode)
        p = self._palette
        icons.clear_icon_cache()
        self._app.setPalette(_make_qpalette(p))
        tokens = {field.name: str(getattr(p, field.name)) for field in fields(p)}
        tokens.update(_radius_tokens)
        tokens["font_family"] = design.FONT_FAMILY
        tokens["check_icon"] = asset_path("check.svg").as_posix()
        tokens["chevron_icon"] = asset_path("chevron-down.svg").as_posix()
        tab_template = _CLASSIC_TABS if self.is_classic else _MODERN_TABS
        tokens["tabs_qss"] = Template(tab_template).substitute(tokens)
        self._app.setStyleSheet(QSS_TEMPLATE.substitute(tokens))
        self.changed.emit()

    def apply_window_chrome(self, window: QWidget) -> None:
        set_dark_title_bar(window, self.is_dark)

    # ------------------------------------------------------------------ system
    def _watch_system_theme(self) -> None:
        if self._system_watch:
            return
        try:
            hints = self._app.styleHints()
            signal = getattr(hints, "colorSchemeChanged", None)
            if signal is not None:
                signal.connect(self._on_system_scheme_changed)
                self._system_watch = True
        except Exception:
            logger.debug("Could not observe the system colour scheme", exc_info=True)

    def _on_system_scheme_changed(self, *_args) -> None:
        if self._mode == "system":
            self.apply()
        else:
            self.changed.emit()


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
