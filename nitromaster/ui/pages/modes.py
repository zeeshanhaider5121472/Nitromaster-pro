"""Mode switcher page: five power profiles with per-step apply feedback."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from nitromaster.core.power.power_modes import (
    MODE_BATTERY_SAVER, MODE_GAMING, MODE_NORMAL, MODE_PERFORMANCE, MODE_ULTRA,
    ModeEngine, ModeStepResult,
)
from nitromaster.ui.theme import ACCENT_AMBER, ACCENT_CYAN, ACCENT_GREEN, ACCENT_MAGENTA, DANGER, TEXT_DIM
from nitromaster.ui.widgets.cards import ModeCard, SectionHeader

_ACCENTS = {
    MODE_NORMAL: ACCENT_CYAN,
    MODE_BATTERY_SAVER: ACCENT_GREEN,
    MODE_ULTRA: ACCENT_MAGENTA,
    MODE_PERFORMANCE: ACCENT_AMBER,
    MODE_GAMING: DANGER,
}
_ORDER = [MODE_NORMAL, MODE_BATTERY_SAVER, MODE_ULTRA, MODE_PERFORMANCE, MODE_GAMING]


class ModesPage(QWidget):
    """State-based mode switcher (Normal / Battery / Ultra / Performance / Gaming)."""

    mode_selected = pyqtSignal(str)

    def __init__(self, engine: ModeEngine, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.engine = engine
        self._cards: dict[str, ModeCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(SectionHeader(
            "Core Power Modes",
            "State-based management · Normal Mode restores the exact first-run snapshot"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(14)
        specs = ModeEngine.specs()
        for i, key in enumerate(_ORDER):
            spec = specs[key]
            card = ModeCard(key, spec.title, spec.description, _ACCENTS.get(key, ACCENT_CYAN))
            card.clicked_mode.connect(self._on_card_clicked)
            self._cards[key] = card
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)

        actions = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Selected Mode")
        self.apply_btn.setObjectName("accent")
        self.apply_btn.clicked.connect(self._apply_selected)
        self.normal_btn = QPushButton("Restore Normal Mode")
        self.normal_btn.clicked.connect(lambda: self.mode_selected.emit(MODE_NORMAL))
        actions.addWidget(self.apply_btn)
        actions.addWidget(self.normal_btn)
        actions.addStretch(1)
        self.status = QLabel("Ready.")
        self.status.setObjectName("subtitle")
        actions.addWidget(self.status)
        lay.addLayout(actions)

        self.report_box = QLabel("")
        self.report_box.setObjectName("subtitle")
        self.report_box.setWordWrap(True)
        self.report_box.setTextInteractionFlags(
            self.report_box.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.report_box)
        lay.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _on_card_clicked(self, mode_key: str) -> None:
        """Keep radio-like selection among the tiles."""
        for key, card in self._cards.items():
            card.setChecked(key == mode_key)

    def _apply_selected(self) -> None:
        """Emit the selected mode (the main window runs the engine off-thread)."""
        for key, card in self._cards.items():
            if card.isChecked():
                self.mode_selected.emit(key)
                return
        QMessageBox.information(self, "NitroMaster", "Select a mode tile first.")

    def set_applying(self, busy: bool) -> None:
        """Disable tiles while a mode is being applied."""
        self.apply_btn.setEnabled(not busy)
        self.status.setText("Applying mode…" if busy else "Ready.")

    def show_results(self, mode_key: str, results: list) -> None:
        """Render the per-step report of a finished apply."""
        ok = sum(1 for r in results if isinstance(r, ModeStepResult) and r.ok)
        self.status.setText(f"{mode_key.replace('_', ' ').title()}: {ok}/{len(results)} steps OK")
        lines = []
        for r in results:
            if isinstance(r, ModeStepResult):
                mark = "✓" if r.ok else "✗"
                lines.append(f"{mark} {r.step}" + (f" — {r.detail}" if r.detail else ""))
            else:
                lines.append(str(r))
        self.report_box.setText("\n".join(lines))

    def show_error(self, mode_key: str, message: str) -> None:
        """Render a failed apply."""
        self.status.setText(f"{mode_key}: FAILED")
        self.report_box.setText(message)
