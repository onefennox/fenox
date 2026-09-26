"""Logging for the hub and the CLI.

Fenox runs other people's commands, bridges USB, and repairs device connections
in the background. When something goes wrong the console has to be able to
answer "what did Fenox see, and what did it do about it" without the owner
having to reproduce anything, so every connection decision is logged as one
readable line.

Configuration is deliberately narrow: a single stream handler on the `fenox`
logger, `propagate` off so uvicorn's own logging is not duplicated, and no
file handler — `FENOX_LOG_LEVEL` and the service manager own that.
"""
from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def configure(level: str | None = None) -> None:
    """Install the console handler. Safe to call more than once."""
    global _configured
    logger = logging.getLogger("fenox")
    if _configured and level is None:
        return

    resolved = (level or os.environ.get("FENOX_LOG_LEVEL") or "info").strip().lower()
    logger.setLevel(getattr(logging, resolved.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        logger.addHandler(handler)
    logger.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """A namespaced logger, configuring the console on first use."""
    if not _configured:
        configure()
    return logging.getLogger(f"fenox.{name}")
