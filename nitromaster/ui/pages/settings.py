"""Settings page: elevation status, startup behavior, service conflicts, about."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from nitromaster import APP_NAME, __version__
from nitromaster.core.power.process_manager import BATTERY_SAVER_SERVICES
from nitromaster.utils.admin import is_admin
from nitromaster.ui.theme import ACCENT_GREEN, ACCENT_MAGENTA, DANGER
from nitromaster.ui.widgets.cards import SectionHeader, StatusPill


class SettingsPage(QWidget):
    """Application settings and diagnostics."""

    relaunch_admin_requested = pyqtSignal()
    restore_baseline_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(SectionHeader("Settings", "Permissions, persistence and diagnostics"))
        lay = QVBoxLayout()
        lay.setSpacing(16)

        perm = QGroupBox("Permissions")
        pl = QVBoxLayout(perm)
        self.admin_pill = StatusPill("checking…")
        pl.addWidget(self.admin_pill)
        hint = QLabel("Fan control, thermal profiles and power-plan writes require Administrator "
                      "rights. Monitoring and per-app GPU preferences work without elevation.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        pl.addWidget(hint)
        self.relaunch_btn = QPushButton("Relaunch as Administrator")
        self.relaunch_btn.setObjectName("accent")
        self.relaunch_btn.clicked.connect(self.relaunch_admin_requested.emit)
        pl.addWidget(self.relaunch_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(perm)

        behavior = QGroupBox("Behavior")
        bl = QVBoxLayout(behavior)
        self.restore_on_start = QCheckBox("Restore baseline / re-apply lighting at startup "
                                          "(firmware resets fan & keyboard state)")
        self.restore_on_start.setChecked(True)
        self.minimize_tray = QCheckBox("Minimize to system tray")
        self.minimize_tray.setChecked(True)
        self.confirm_modes = QCheckBox("Confirm before applying a mode")
        self.confirm_modes.setChecked(True)
        for c in (self.restore_on_start, self.minimize_tray, self.confirm_modes):
            bl.addWidget(c)
        self.restore_btn = QPushButton("Restore Normal Mode (baseline) now")
        self.restore_btn.clicked.connect(self.restore_baseline_requested.emit)
        bl.addWidget(self.restore_btn)
        lay.addWidget(behavior)

        conflicts = QGroupBox("OEM service conflicts")
        cl = QVBoxLayout(conflicts)
        warn = QLabel("NitroSense / AcerAgentService may overwrite fan, profile and lighting "
                      "settings concurrently. Ultra Battery Saver can pause these services "
                      "(fully reversible — they are restored on exit):\n"
                      + ", ".join(BATTERY_SAVER_SERVICES[:6]) + ", …")
        warn.setObjectName("subtitle")
        warn.setWordWrap(True)
        cl.addWidget(warn)
        lay.addWidget(conflicts)

        about = QGroupBox("About")
        al = QHBoxLayout(about)
        al.addWidget(QLabel(f"{APP_NAME} v{__version__} · tailored for Acer Nitro AN515-45"))
        al.addStretch(1)
        lay.addWidget(about)

        lay.addStretch(1)
        outer.addLayout(lay)
        self.refresh_permissions()

    def refresh_permissions(self) -> None:
        """Update the elevation status pill."""
        admin = is_admin()
        self.admin_pill.set_status(
            "Running as Administrator — full control enabled" if admin
            else "Standard user — monitoring only; power/fan writes need elevation",
            ACCENT_GREEN if admin else DANGER)
        self.relaunch_btn.setEnabled(not admin)
