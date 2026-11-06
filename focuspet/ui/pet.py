# -*- coding: utf-8 -*-
"""桌宠窗口（设计方案 13.3 / 13.4）。

四个标志位缺一不可，尤其是 Qt.Tool——不加的话它会出现在 Alt+Tab 和任务栏里，
用户第一件事就是关掉它。MVP 阶段不做 Live2D，QPainter 画 2～3 帧足够。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

W, H = 220, 210
BODY = QColor("#F6C87A")
BODY_DARK = QColor("#E0A94F")
INK = QColor("#3B3A36")


class Pet(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.setToolTip("余光 · 右键有菜单")

        self.state = "idle"          # idle / watching / alert / rest / sleep
        self.text = ""
        self.phase = 0.0
        self._drag: QPoint | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._clear_text)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.start(90)

        pos = cfg["ui"].get("pet_position") or [1720, 900]
        self.move(int(pos[0]), int(pos[1]))
        self.hide()

    # ---------------------------------------------------------------- 状态
    def _animate(self) -> None:
        self.phase += 0.12
        self.update()

    def set_state(self, state: str) -> None:
        if state == "sleep":
            self.show_idle_pos()
        self.state = state
        self.update()

    def show_idle_pos(self) -> None:
        """把桌宠放到屏幕右下角贴边（首次启动 / 从全屏退出时）。"""
        screen = self.screen().availableGeometry()
        self.move(screen.right() - W + 40, screen.bottom() - H + 10)

    def alert(self, text: str, ms: int = 5000, level: int = 1) -> None:
        self.text = text
        self.state = "alert" if level < 3 else "alert"
        self.show()
        self.raise_()
        if level >= 3:
            screen = self.screen().availableGeometry()
            self.move(screen.center().x() - W // 2, screen.center().y() - H // 2)
        self._hide_timer.start(ms)
        self.update()

    def _clear_text(self) -> None:
        self.text = ""
        self.state = "idle"
        self.show_idle_pos()
        self.update()

    # ---------------------------------------------------------------- 交互
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        self._drag = None
        # 贴边半隐藏：拖到边缘时收进去一半
        screen = self.screen().availableGeometry()
        x, y = self.x(), self.y()
        if x < screen.left() + 20:
            x = screen.left() - W // 2
        elif x + W > screen.right() - 20:
            x = screen.right() - W // 2
        self.move(max(screen.left() - W // 2, min(x, screen.right() - W // 2)), y)
        self.cfg["ui"]["pet_position"] = [self.x(), self.y()]
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self._clear_text()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        breathe = math.sin(self.phase) * 2.0
        cx, cy = W // 2, 150 + breathe * 0.4
        r = 46

        if self.text:
            self._draw_bubble(p)

        # 影子
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawEllipse(QPoint(cx, int(cy + r + 8)), 34, 7)

        # 身体
        grad = QColor(BODY)
        if self.state == "sleep":
            grad = QColor("#D9CDBA")
        p.setBrush(grad)
        p.drawEllipse(QPoint(cx, int(cy)), r, int(r * 0.92))
        p.setBrush(BODY_DARK)
        p.drawEllipse(QPoint(cx, int(cy + 20)), int(r * 0.55), int(r * 0.30))

        # 眼睛
        blink = (int(self.phase * 3) % 37) == 0
        eye_y = int(cy - 6)
        p.setBrush(INK)
        if blink or self.state == "sleep":
            pen = QPen(INK, 3, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(cx - 16, eye_y, cx - 6, eye_y)
            p.drawLine(cx + 6, eye_y, cx + 16, eye_y)
        else:
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(cx - 11, eye_y), 5, 6)
            p.drawEllipse(QPoint(cx + 11, eye_y), 5, 6)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPoint(cx - 9, eye_y - 2), 1.8, 2.0)
            p.drawEllipse(QPoint(cx + 13, eye_y - 2), 1.8, 2.0)

        # 嘴
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(INK, 2, Qt.SolidLine, Qt.RoundCap))
        if self.state == "alert":
            p.setBrush(QColor("#C9705E"))                    # 张嘴说话
            p.drawEllipse(QPoint(cx, int(cy + 12)), 6, 6)
        elif self.state == "watching":
            p.drawArc(QRect(cx - 8, int(cy + 4), 16, 12), 180 * 16, 180 * 16)
        elif self.state == "sleep":
            p.drawLine(cx - 5, int(cy + 10), cx + 5, int(cy + 10))
        else:
            p.drawArc(QRect(cx - 8, int(cy + 6), 16, 10), 180 * 16, 180 * 16)

        # 腮红
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(235, 150, 120, 90))
        p.drawEllipse(QPoint(cx - 26, int(cy + 8)), 6, 4)
        p.drawEllipse(QPoint(cx + 26, int(cy + 8)), 6, 4)

    def _draw_bubble(self, p: QPainter) -> None:
        rect = QRect(6, 6, W - 12, 76)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.setPen(QPen(QColor("#DDE2E8"), 1))
        p.setBrush(QColor(255, 255, 255, 246))
        p.drawPath(path)

        # 小尾巴
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 246))
        tri = QPainterPath()
        tri.moveTo(W / 2 - 8, 82)
        tri.lineTo(W / 2 + 8, 82)
        tri.lineTo(W / 2, 96)
        tri.closeSubpath()
        p.drawPath(tri)

        p.setPen(QColor("#1F2937"))
        f = QFont("Microsoft YaHei", 9)
        p.setFont(f)
        p.drawText(rect.adjusted(10, 6, -10, -6),
                   Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap, self.text)
