"""OLED pitch-black theme (#000000) with neon accents — Xiaomi Ultra Battery Saver aesthetic.

Palette: background #000000, cards #0A0A0A, borders #1E1E1E,
accents cyan #00E5FF, green #39FF14, magenta #FF2D95.
"""
from __future__ import annotations

BG = "#000000"
CARD = "#0A0A0A"
CARD_HOVER = "#101010"
BORDER = "#1E1E1E"
TEXT = "#FFFFFF"
TEXT_DIM = "#8A8A8A"
ACCENT_CYAN = "#00E5FF"
ACCENT_GREEN = "#39FF14"
ACCENT_MAGENTA = "#FF2D95"
ACCENT_AMBER = "#FFB300"
DANGER = "#FF4757"
RADIUS = 12
FONT_FAMILY = "Segoe UI, Roboto, sans-serif"

QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QWidget#page {{
    background-color: {BG};
}}
QFrame.card, QWidget#card, QGroupBox {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QGroupBox {{
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {ACCENT_CYAN};
}}
QLabel#title {{
    font-size: 22px;
    font-weight: 700;
}}
QLabel#subtitle {{
    font-size: 12px;
    color: {TEXT_DIM};
}}
QLabel#statValue {{
    font-size: 26px;
    font-weight: 700;
}}
QLabel#statLabel {{
    font-size: 11px;
    color: {TEXT_DIM};
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QPushButton {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 10px 18px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {CARD_HOVER};
    border-color: {ACCENT_CYAN};
}}
QPushButton:pressed {{
    background-color: #161616;
}}
QPushButton#accent {{
    background-color: {ACCENT_CYAN};
    color: #001014;
    border: none;
}}
QPushButton#accent:hover {{
    background-color: #56F0FF;
}}
QPushButton#danger {{
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton#navButton {{
    text-align: left;
    padding: 12px 18px;
    border: none;
    border-radius: {RADIUS}px;
    background-color: transparent;
    color: {TEXT_DIM};
    font-size: 14px;
}}
QPushButton#navButton:hover {{
    background-color: {CARD};
    color: {TEXT};
}}
QPushButton#navButton:checked {{
    background-color: {CARD};
    color: {ACCENT_CYAN};
    border-left: 3px solid {ACCENT_CYAN};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {BORDER};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 18px;
    margin: -7px 0;
    border-radius: 9px;
    background: {ACCENT_CYAN};
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_CYAN};
    border-radius: 3px;
}}
QProgressBar {{
    background-color: {BORDER};
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    border-radius: 6px;
    background-color: {ACCENT_CYAN};
}}
QComboBox, QSpinBox, QLineEdit, QDoubleSpinBox {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT_CYAN};
    selection-color: #001014;
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_CYAN};
    selection-color: #001014;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    background: {CARD};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 10px 20px;
    border: none;
}}
QTabBar::tab:selected {{
    color: {ACCENT_CYAN};
    border-bottom: 2px solid {ACCENT_CYAN};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid {BORDER};
    background: {CARD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT_CYAN};
    border-color: {ACCENT_CYAN};
}}
QTableWidget {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {CARD};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px;
    color: {TEXT_DIM};
}}
QStatusBar {{
    background: {CARD};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
QMessageBox {{
    background-color: {CARD};
}}
"""


def apply_theme(app) -> None:
    """Apply the NitroMaster OLED theme to a QApplication."""
    app.setStyleSheet(QSS)
    app.setStyle("Fusion")
