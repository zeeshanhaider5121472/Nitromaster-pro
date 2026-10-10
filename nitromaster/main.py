"""NitroMaster Pro Control Center — entry point.

Run elevated (Administrator) for fan control, thermal profiles and power-plan writes.
"""
from __future__ import annotations

import sys


def main() -> int:
    """Launch the application; surfaces a clear message when elevation is missing."""
    from nitromaster.app import run_gui
    from nitromaster.utils.admin import is_admin
    from nitromaster.utils.logging_setup import setup_logging

    setup_logging()
    if sys.platform == "win32" and not is_admin():
        # Not fatal: monitoring works, write-features show their own prompts.
        print("Running without Administrator rights: control features will be limited.")
    return run_gui(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
