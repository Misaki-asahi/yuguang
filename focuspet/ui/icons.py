# -*- coding: utf-8 -*-
"""应用图标：从 assets/ 加载，找不到就退回代码画的简笔图标。

图标文件随仓库一起发布（focuspet/assets/icon.ico 与 icon.png），
所以别人 clone 下来也是同一张脸，不用另外准备素材。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import Qt

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ICO = ASSETS / "icon.ico"
PNG = ASSETS / "icon.png"


def _painted() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#F6C87A"))
    p.drawEllipse(6, 10, 52, 46)
    p.setBrush(QColor("#3B3A36"))
    p.drawEllipse(21, 28, 7, 8)
    p.drawEllipse(37, 28, 7, 8)
    p.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    for path in (ICO, PNG):
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return _painted()
