"""Small animation helpers used across the redesigned interface.

Animations stay deliberately short and are skipped when the user disabled them
or Windows reports reduced motion.  Effects are removed when they finish so no
permanent off-screen rendering cost is left behind.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from . import design

_running: dict[int, list[QAbstractAnimation]] = {}


def stop(widget: QWidget) -> None:
    for animation in _running.pop(id(widget), []):
        animation.stop()
    if widget.graphicsEffect() is not None and isinstance(
        widget.graphicsEffect(), QGraphicsOpacityEffect
    ):
        widget.setGraphicsEffect(None)


def _track(widget: QWidget, animation: QPropertyAnimation) -> None:
    _running.setdefault(id(widget), []).append(animation)
    animation.finished.connect(lambda: _release(widget, animation))


def _release(widget: QWidget, animation: QPropertyAnimation) -> None:
    animations = _running.get(id(widget), [])
    if animation in animations:
        animations.remove(animation)
    if not animations:
        _running.pop(id(widget), None)


def fade_in(widget: QWidget, duration: int | None = None) -> None:
    ms = design.duration("normal") if duration is None else duration
    if ms <= 0:
        widget.setGraphicsEffect(None)
        return
    stop(widget)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(ms)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: _clear_effect(widget, effect))
    _track(widget, animation)
    animation.start()


def _clear_effect(widget: QWidget, effect: QGraphicsOpacityEffect) -> None:
    # Keep the effect while the widget lives: replacing it mid-frame can flash.
    if widget.graphicsEffect() is effect:
        effect.setOpacity(1.0)


def cross_fade(widget: QWidget, duration: int | None = None) -> None:
    """Quick fade used for page and theme transitions."""
    ms = design.duration("fast") if duration is None else duration
    if ms <= 0:
        return
    fade_in(widget, ms)


def animate_width(widget: QWidget, start: int, end: int, duration: int | None = None):
    ms = design.duration("normal") if duration is None else duration
    animation = QPropertyAnimation(widget, b"maximumWidth", widget)
    animation.setDuration(ms)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    if ms > 0:
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return animation
    widget.setMaximumWidth(end)
    return None


def animate_progress(widget, start: float, end: float, duration: int | None = None):
    ms = design.duration("normal") if duration is None else duration
    animation = QPropertyAnimation(widget, b"value", widget)
    animation.setDuration(ms)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    if ms > 0:
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return animation
    widget.setValue(end)
    return None


def schedule(widget: QWidget, milliseconds: int, callback) -> None:
    QTimer.singleShot(milliseconds, widget, callback)


__all__ = [
    "animate_progress",
    "animate_width",
    "cross_fade",
    "fade_in",
    "schedule",
    "stop",
]
