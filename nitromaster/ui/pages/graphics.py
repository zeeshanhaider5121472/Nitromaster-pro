"""Graphics card switcher page: per-app GPU preference management."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from nitromaster.core.graphics.app_profiles import AppProfile, AppProfileStore
from nitromaster.core.graphics.gpu_switcher import GPU_PREF_NAMES
from nitromaster.ui.theme import ACCENT_CYAN, ACCENT_MAGENTA
from nitromaster.ui.widgets.cards import SectionHeader, StatCard


class GraphicsPage(QWidget):
    """View active render GPUs and assign apps to iGPU / dGPU."""

    profiles_changed = pyqtSignal()

    def __init__(self, store: AppProfileStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.store = store
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(SectionHeader(
            "Graphics Card Switcher",
            "GTX 1650 (dGPU) vs Radeon Vega (iGPU) · no MUX: Optimus copy-forward to panel"))
        lay = QVBoxLayout()
        lay.setSpacing(16)

        info = QHBoxLayout()
        self.dgpu_tile = StatCard("Dedicated GPU", ACCENT_MAGENTA)
        self.dgpu_tile.set_value("GTX 1650", sub="High performance · 4 GB GDDR6")
        self.igpu_tile = StatCard("Integrated GPU", ACCENT_CYAN)
        self.igpu_tile.set_value("Radeon Vega", sub="Power saving · shared memory")
        self.mux_tile = StatCard("MUX switch", ACCENT_CYAN)
        self.mux_tile.set_value("Not available", sub="dGPU renders via Optimus copy-forward")
        for w in (self.dgpu_tile, self.igpu_tile, self.mux_tile):
            info.addWidget(w)
        lay.addLayout(info)

        add_box = QGroupBox("Add / update application profile")
        al = QHBoxLayout(add_box)
        self.exe_edit = QPushButton("Browse…")
        self.exe_edit.clicked.connect(self._browse)
        self.exe_path_label = QLabel("No file selected")
        self.exe_path_label.setObjectName("subtitle")
        self.pref_box = QComboBox()
        for k in sorted(GPU_PREF_NAMES):
            self.pref_box.addItem(GPU_PREF_NAMES[k], k)
        self.add_btn = QPushButton("Save profile")
        self.add_btn.setObjectName("accent")
        self.add_btn.clicked.connect(self._add)
        al.addWidget(self.exe_edit)
        al.addWidget(self.exe_path_label, 1)
        al.addWidget(self.pref_box)
        al.addWidget(self.add_btn)
        lay.addWidget(add_box)

        table_box = QGroupBox("Application profiles")
        tl = QVBoxLayout(table_box)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Application", "Executable", "Preferred GPU"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tl.addWidget(self.table)
        buttons = QHBoxLayout()
        self.apply_all_btn = QPushButton("Apply all to registry")
        self.apply_all_btn.setObjectName("accent")
        self.apply_all_btn.clicked.connect(self._apply_all)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.clicked.connect(self._remove)
        self.refresh_btn = QPushButton("Reload")
        self.refresh_btn.clicked.connect(self.reload)
        buttons.addWidget(self.apply_all_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        tl.addLayout(buttons)
        lay.addWidget(table_box)
        outer.addLayout(lay)
        outer.addStretch(1)
        self._exe_path: Optional[str] = None
        self.reload()

    # --- actions ---------------------------------------------------------------------

    def _browse(self) -> None:
        """Pick an executable via the file dialog."""
        path, _ = QFileDialog.getOpenFileName(self, "Select application", "", "Executables (*.exe)")
        if path:
            self._exe_path = path
            self.exe_path_label.setText(path)

    def _add(self) -> None:
        """Persist the selected exe + preference and write the registry value."""
        if not self._exe_path:
            QMessageBox.warning(self, "NitroMaster", "Select an .exe first.")
            return
        pref = int(self.pref_box.currentData())
        profile = AppProfile(
            exe_path=self._exe_path,
            name=AppProfileStore.detect_name(self._exe_path),
            preferred_gpu=pref,
        )
        if self.store.add(profile):
            self.reload()
            self.profiles_changed.emit()
        else:
            QMessageBox.warning(self, "NitroMaster", "Failed to save the profile.")

    def _remove(self) -> None:
        """Remove the selected row's profile and clear its registry entry."""
        row = self.table.currentRow()
        if row < 0:
            return
        exe = self.table.item(row, 1).text()
        self.store.remove(exe)
        self.reload()
        self.profiles_changed.emit()

    def _apply_all(self) -> None:
        """Re-write every profile into UserGpuPreferences."""
        n = self.store.apply_all()
        QMessageBox.information(self, "NitroMaster",
                                f"{n} preference(s) written.\nRestart target apps for changes to take effect.")

    def reload(self) -> None:
        """Refresh the table from the store."""
        profiles = self.store.list()
        self.table.setRowCount(len(profiles))
        for i, p in enumerate(profiles):
            self.table.setItem(i, 0, QTableWidgetItem(p.name or p.exe_path))
            self.table.setItem(i, 1, QTableWidgetItem(p.exe_path))
            self.table.setItem(i, 2, QTableWidgetItem(GPU_PREF_NAMES.get(p.preferred_gpu, "?")))
