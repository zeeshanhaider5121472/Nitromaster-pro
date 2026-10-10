"""Circular gauge widget (CPU/GPU temperature, usage, fan duty)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QSizePolicy, QWidget

from nitromaster.ui.theme import ACCENT_CYAN, ACCENT_GREEN, ACCENT_AMBER, BORDER, DANGER, TEXT_DIM


class CircularGauge(QWidget):
    """A neon-styled arc gauge with a center value label and threshold coloring."""

    def __init__(self, title: str = "", unit: str = "%", maximum: float = 100.0,
                 accent: str = ACCENT_CYAN, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.maximum = max(1.0, float(maximum))
        self.accent = QColor(accent)
        self.value: Optional[float] = None
        self.warn_at = 0.75
        self.danger_at = 0.90
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_value(self, value: Optional[float]) -> None:
        """Update the displayed value (None renders as '--')."""
        self.value = value
        self.update()

    def set_thresholds(self, warn_at: float, danger_at: float) -> None:
        """Set warn/danger fractions of the gauge maximum (0..1)."""
        self.warn_at, self.danger_at = warn_at, danger_at

    def _value_color(self) -> QColor:
        if self.value is None:
            return QColor(self.accent)
        frac = min(1.0, self.value / self.maximum)
        if frac >= self.danger_at:
            return QColor(DANGER)
        if frac >= self.warn_at:
            return QColor(ACCENT_AMBER)
        return QColor(self.accent) if self.accent != QColor(ACCENT_GREEN) else QColor(ACCENT_GREEN)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Draw the gauge arc, ticks and center text."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        margin = size * 0.08
        rect = QRectF((self.width() - size) / 2 + margin, (self.height() - size) / 2 + margin,
                      size - 2 * margin, size - 2 * margin)

        # background arc
        pen = QPen(QColor(BORDER), size * 0.07, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 225 * 16, -270 * 16)

        # value arc
        if self.value is not None:
            frac = max(0.0, min(1.0, self.value / self.maximum))
            pen.setColor(self._value_color())
            painter.setPen(pen)
            painter.drawArc(rect, 225 * 16, int(-270 * 16 * frac))

        # center text
        painter.setPen(QColor(self._value_color()))
        font = QFont()
        font.setPixelSize(int(size * 0.20))
        font.setBold(True)
        painter.setFont(font)
        text = "--" if self.value is None else f"{self.value:.0f}{self.unit}"
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

        painter.setPen(QColor(TEXT_DIM))
        font.setPixelSize(int(size * 0.075))
        font.setBold(False)
        painter.setFont(font)
        label_rect = QRectF(rect.left(), rect.bottom() - size * 0.02, rect.width(), size * 0.16)
        painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter), self.title)
