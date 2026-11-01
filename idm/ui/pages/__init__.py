"""Workspace pages introduced in IDM 3.0."""

from .analytics import AnalyticsPage
from .browser import BrowserIntegrationPage
from .dashboard import DashboardPage
from .notifications import NotificationsPage
from .performance import PerformancePage
from .settings import AdvancedSettingsPage
from .update_center import UpdateCenterPage
from .videos import VideoDownloadsPage

__all__ = [
    "AdvancedSettingsPage",
    "AnalyticsPage",
    "BrowserIntegrationPage",
    "DashboardPage",
    "NotificationsPage",
    "PerformancePage",
    "UpdateCenterPage",
    "VideoDownloadsPage",
]
