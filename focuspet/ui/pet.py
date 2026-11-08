# -*- coding: utf-8 -*-
"""桌宠窗口（设计方案 13.3 / 13.4）。

四个标志位缺一不可，尤其是 Qt.Tool——不加的话它会出现在 Alt+Tab 和任务栏里，
用户第一件事就是关掉它。MVP 阶段不做 Live2D，QPainter 画 2～3 帧足够。

2026-11-08（feat/pet-walk）：它不再钉死在右下角——会自己在屏幕上踱步、走累了
停下发呆、碰到屏幕边缘掉头，眼睛还会跟着鼠标转。走路时的腿摆和身体起伏都由
QPainter 现画，不引入任何美术资源；速度与开关走 config.yaml 的 ui.pet_wander /
ui.pet_speed，拖拽时自动停下，松手后歇两秒再继续走。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QWidget

W, H = 220, 210
BODY = QColor("#F6C87A")
BODY_DARK = QColor("#E0A94F")
INK = QColor("#3B3A36")

# 踱步节拍：40ms 一步 ≈ 25 帧/秒，肉眼看起来是连续的
WALK_INTERVAL_MS = 40


class Pet(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.setToolTip("余光 · 右键有菜单")

        self.state = "idle"          # idle / walking / watching / alert / rest / sleep
        self.text = ""
        self.phase = 0.0
        self.gait = 0.0              # 走路节拍，和呼吸的 phase 分开
        self._drag: QPoint | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._clear_text)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.start(90)

        # 自主踱步：速度（像素/秒）、方向、休息到什么时候、下次换向时间
        self._wander = bool(cfg["ui"].get("pet_wander", True))
        self._speed = float(cfg["ui"].get("pet_speed", 60) or 60)
        self._vx = 0.0
        self._vy = 0.0
        self._rest_until = 0.0
        self._turn_at = 0.0
        self._walk = QTimer(self)
        self._walk.timeout.connect(self._step)
        if self._wander:
            self._walk.start(WALK_INTERVAL_MS)

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
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.x() + area.width() - W + 40, area.y() + area.height() - H + 10)

    def alert(self, text: str, ms: int = 5000, level: int = 1) -> None:
        self.text = text
        self.state = "alert" if level < 3 else "alert"
        self.show()
        self.raise_()
        if level >= 3:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.center().x() - W // 2, area.center().y() - H // 2)
        self._hide_timer.start(ms)
        self.update()

    def _clear_text(self) -> None:
        self.text = ""
        self.state = "idle"
        if self._wander:
            # 走动模式下别瞬移回右下角，原地缓一下接着走
            self._vx = self._vy = 0.0
            self._rest_until = time.monotonic() + random.uniform(1.5, 3.5)
        else:
            self.show_idle_pos()
        self.update()

    # ------------------------------------------------------------ 自主踱步
    def _screen_area(self) -> QRect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1280, 800)
        return screen.availableGeometry()

    def _pick_direction(self, now: float) -> None:
        """随机挑方向：主要横向走、纵向轻微飘；四分之一概率原地歇一会儿。"""
        if random.random() < 0.25:
            self._vx = self._vy = 0.0
            self._rest_until = now + random.uniform(1.5, 5.0)
            self.state = "idle"
            return
        speed = self._speed * random.uniform(0.6, 1.2)
        angle = random.uniform(-0.45, 0.45)
        direction = random.choice((-1.0, 1.0))
        self._vx = math.cos(angle) * speed * direction
        self._vy = math.sin(angle) * speed * 0.5
        self._turn_at = now + random.uniform(2.5, 6.0)

    def _step(self) -> None:
        """每 40ms 走一小步；拖动、说话、隐藏、睡觉时都不动。"""
        if not self.isVisible() or self._drag is not None or self.text:
            return
        if self.state == "sleep":
            return
        now = time.monotonic()
        if now < self._rest_until:
            self.state = "idle"
            return
        if now >= self._turn_at or (self._vx == 0.0 and self._vy == 0.0):
            self._pick_direction(now)
            return

        area = self._screen_area()
        step = WALK_INTERVAL_MS / 1000.0
        x = self.x() + self._vx * step
        y = self.y() + self._vy * step

        left, top = area.x(), area.y()
        right, bottom = area.x() + area.width() - W, area.y() + area.height() - H
        if x <= left:
            x = left
            self._vx = abs(self._vx)
        elif x >= right:
            x = right
            self._vx = -abs(self._vx)
        if y <= top:
            y = top
            self._vy = abs(self._vy)
        elif y >= bottom:
            y = bottom
            self._vy = -abs(self._vy)

        self.move(int(round(x)), int(round(y)))
        self.state = "walking"
        self.gait += 0.35
        self.cfg["ui"]["pet_position"] = [self.x(), self.y()]

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
        area = self._screen_area()
        x, y = self.x(), self.y()
        if x < area.left() + 20:
            x = area.left() - W // 2
        elif x + W > area.x() + area.width() - 20:
            x = area.x() + area.width() - W // 2
        self.move(max(area.left() - W // 2, min(x, area.x() + area.width() - W // 2)), y)
        self.cfg["ui"]["pet_position"] = [self.x(), self.y()]
        self._rest_until = time.monotonic() + random.uniform(2.0, 4.0)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self._clear_text()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        walking = self.state == "walking"
        breathe = math.sin(self.phase) * 2.0
        bob = math.sin(self.gait) * 2.2 if walking else breathe * 0.4
        cx, cy = W // 2, 150 + bob
        r = 46

        if self.text:
            self._draw_bubble(p)

        # 影子
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawEllipse(QPoint(cx, int(cy + r + 8)), 34, 7)

        if walking:
            # 两条小短腿交替迈步（画在影子之后、身体之前，露出下沿）
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#D9A45B"))
            for i in (0, 1):
                lift = math.sin(self.gait + i * math.pi) * 7.0
                lx = cx - 24 + i * 36
                ly = cy + r * 0.92 - 8 - lift
                p.drawRoundedRect(int(lx), int(ly), 14, 18, 6, 6)

        # 身体
        grad = QColor(BODY)
        if self.state == "sleep":
            grad = QColor("#D9CDBA")
        p.setBrush(grad)
        p.drawEllipse(QPoint(cx, int(cy)), r, int(r * 0.92))
        p.setBrush(BODY_DARK)
        p.drawEllipse(QPoint(cx, int(cy + 20)), int(r * 0.55), int(r * 0.30))

        # 眼睛（目光跟着鼠标）
        blink = (int(self.phase * 3) % 37) == 0
        eye_y = int(cy - 6)
        look = self.mapFromGlobal(QCursor.pos())
        nx = max(-1.0, min(1.0, (look.x() - cx) / 90.0))
        ny = max(-1.0, min(1.0, (look.y() - cy) / 90.0))
        p.setBrush(INK)
        if blink or self.state == "sleep":
            pen = QPen(INK, 3, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(cx - 16, eye_y, cx - 6, eye_y)
            p.drawLine(cx + 6, eye_y, cx + 16, eye_y)
        else:
            p.setPen(Qt.NoPen)
            ox, oy = nx * 2.4, ny * 2.0
            p.drawEllipse(QPoint(cx - 11 + int(ox), eye_y + int(oy)), 5, 6)
            p.drawEllipse(QPoint(cx + 11 + int(ox), eye_y + int(oy)), 5, 6)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPoint(cx - 9 + int(ox), eye_y - 2 + int(oy)), 1.8, 2.0)
            p.drawEllipse(QPoint(cx + 13 + int(ox), eye_y - 2 + int(oy)), 1.8, 2.0)

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
        elif walking:
            p.drawArc(QRect(cx - 7, int(cy + 6), 14, 9), 200 * 16, 140 * 16)
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
