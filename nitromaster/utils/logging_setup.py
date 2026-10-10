"""Application logging: rotating file handler + console, under the state directory."""
from __future__ import annotations

import logging
import logging.handlers

from .state_store import state_dir

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root 'nitromaster' logging once and return the logger."""
    global _configured
    logger = logging.getLogger("nitromaster")
    if _configured:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(
            state_dir() / "nitromaster.log", maxBytes=512_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the application logger."""
    return logging.getLogger(f"nitromaster.{name}")
