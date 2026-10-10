"""Card widgets: stat tiles, mode tiles, section headers, value bars."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from nitromaster.ui.theme import (
    ACCENT_CYAN, ACCENT_MAGENTA, BORDER, CARD, TEXT_DIM,
)


class SectionHeader(QWidget):
    """Title + optional subtitle row."""

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        t = QLabel(title)
        t.setObjectName("title")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("subtitle")
            lay.addWidget(s)


class StatCard(QFrame):
    """OLED card showing a labeled value (optionally with a progress bar)."""

    def __init__(self, label: str, accent: str = ACCENT_CYAN,
                 show_bar: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.accent = accent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        self.label = QLabel(label.upper())
        self.label.setObjectName("statLabel")
        lay.addWidget(self.label)
        self.value = QLabel("--")
        self.value.setObjectName("statValue")
        self.value.setStyleSheet(f"color: {accent};")
        lay.addWidget(self.value)
        self.bar: Optional[QProgressBar] = None
        if show_bar:
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            lay.addWidget(self.bar)
        self.sub = QLabel("")
        self.sub.setObjectName("subtitle")
        lay.addWidget(self.sub)
        glow = QGraphicsDropShadowEffect(self)
        glow.setBlurRadius(24)
        glow.setColor(QColor(accent))
        glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)

    def set_value(self, text: str, bar_value: Optional[float] = None, sub: str = "") -> None:
        """Update value text, optional bar percent and sub-caption."""
        self.value.setText(text)
        if self.bar is not None and bar_value is not None:
            self.bar.setValue(int(max(0, min(100, bar_value))))
        if sub:
            self.sub.setText(sub)


class ValueBar(QWidget):
    """Slim labeled horizontal bar (RAM/VRAM utilization)."""

    def __init__(self, label: str, accent: str = ACCENT_CYAN,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        row = QHBoxLayout()
        self.label = QLabel(label)
        self.label.setObjectName("statLabel")
        self.reading = QLabel("--")
        self.reading.setObjectName("subtitle")
        row.addWidget(self.label)
        row.addStretch(1)
        row.addWidget(self.reading)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {accent}; border-radius: 5px; }}")
        lay.addWidget(self.bar)

    def set_value(self, percent: float, caption: str = "") -> None:
        """Update bar percent and right-side caption."""
        self.bar.setValue(int(max(0, min(100, percent))))
        self.reading.setText(caption or f"{percent:.0f}%")


class ModeCard(QPushButton):
    """Large selectable mode tile (checkable)."""

    clicked_mode = pyqtSignal(str)

    def __init__(self, mode_key: str, title: str, description: str,
                 accent: str = ACCENT_CYAN, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.mode_key = mode_key
        self.accent = accent
        self.setCheckable(True)
        self.setMinimumHeight(110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {accent};")
        self.desc_label = QLabel(description)
        self.desc_label.setObjectName("subtitle")
        self.desc_label.setWordWrap(True)
        lay.addWidget(self.title_label)
        lay.addWidget(self.desc_label)
        self.setStyleSheet(
            f"QPushButton {{ background-color: {CARD}; border: 1px solid {BORDER};"
            f" border-radius: 12px; text-align: left; }}"
            f"QPushButton:checked {{ border: 2px solid {accent}; }}")
        self.clicked.connect(lambda: self.clicked_mode.emit(self.mode_key))


class StatusPill(QFrame):
    """Small colored status indicator with a text label."""

    def __init__(self, text: str, color: str = ACCENT_CYAN,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {color}; font-size: 10px;")
        self.text = QLabel(text)
        self.text.setObjectName("subtitle")
        lay.addWidget(self.dot)
        lay.addWidget(self.text)
        self.setStyleSheet(
            f"QFrame {{ background-color: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}")

    def set_status(self, text: str, color: str = ACCENT_MAGENTA) -> None:
        """Update pill text and color."""
        self.text.setText(text)
        self.dot.setStyleSheet(f"color: {color}; font-size: 10px;")
