# -*- coding: utf-8 -*-
"""按天分文件的轮转日志（设计方案 15.3 的 log.py）。"""
from __future__ import annotations

import logging
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import config

_FMT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"
_DATEFMT = "%H:%M:%S"
_configured = False


def setup(verbose: bool = False) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    config.ensure_dirs()
    root = logging.getLogger("focuspet")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False

    fh = TimedRotatingFileHandler(
        Path(config.LOGS) / "focuspet.log",
        when="midnight", backupCount=7, encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(sh)


def get(name: str) -> logging.Logger:
    if not _configured:
        setup()
    return logging.getLogger(f"focuspet.{name}")


def heartbeat() -> None:
    """看门狗靠这个文件判断进程是否还活着（每 tick 写一次）。"""
    try:
        config.HEARTBEAT.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass
