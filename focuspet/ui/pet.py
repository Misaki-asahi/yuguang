# -*- coding: utf-8 -*-
"""桌宠窗口（设计方案 13.3 / 13.4）。

四个标志位缺一不可，尤其是 Qt.Tool——不加的话它会出现在 Alt+Tab 和任务栏里，
用户第一件事就是关掉它。MVP 阶段不做 Live2D，QPainter 画 2～3 帧足够。

2026-11-08（feat/pet-walk）：它不再钉死在右下角——会自己在屏幕上踱步、走累了
停下发呆、碰到屏幕边缘掉头，眼睛还会跟着鼠标转。走路时的腿摆和身体起伏都由
QPainter 现画，不引入任何美术资源；速度与开关走 config.yaml 的 ui.pet_wander /
ui.pet_speed，拖拽时自动停下，松手后歇两秒再继续走。

2026-11-08 晚：接入第一版真素材 focuspet/assets/pet/juyuan/pose.png（菊鸳静态立绘）。
有立绘时窗口按立绘尺寸撑开、脚底贴底边居中、气泡留在头顶；没立绘自动回退到上面
那套手画的小熊。ui.pet_wander=false 时它就不自己走了（钉在原地）。

2026-11-09：接入动作包 focuspet/assets/pet/juyuan-pack/（菊鸳的逐帧动画，来自已获
授权的 aboutme-pets claude 包，见同目录 ASSETS-LICENSE.md）。素材优先级：
**动作包 > 静态立绘 > 手画小熊**。动作包由 focuspet/anim/ 负责解析、切图、播放；
本文件只做窗口层：把当前帧画在脚底锚点上、接鼠标事件、切状态。
"""
from __future__ import annotations

import math
import random
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QPainter,
                           QPainterPath, QPen, QPixmap, QRegion)
from PySide6.QtWidgets import QWidget

from ..anim.assets import AssetStore
from ..anim.manifest import load_pack
from ..anim.player import FramePlayer

W, H = 220, 210
BODY = QColor("#F6C87A")
BODY_DARK = QColor("#E0A94F")
INK = QColor("#3B3A36")

# 美术素材：有立绘就用立绘，没有就回退到下面这套 QPainter 手画的小熊，
# 保证把仓库 clone 下来、素材还没到的时候程序照样能跑。
ART_DIR = Path(__file__).resolve().parents[1] / "assets" / "pet" / "juyuan"
ART_FILE = ART_DIR / "pose.png"
ART_HEIGHT = 180          # 角色在窗口里的基准高度；ui.pet_scale 再乘上去
ART_TOP_MIN = 100         # 气泡占掉的高度，角色头顶不能高过这条线

# 踱步节拍：40ms 一步 ≈ 25 帧/秒，肉眼看起来是连续的
WALK_INTERVAL_MS = 40


class Pet(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip("余光 · 右键有菜单")

        # 素材优先级：动作包（逐帧） > 静态立绘 > 手画小熊
        self._pack = load_pack()
        self._store = None
        self._player = None
        if self._pack is not None:
            scale = float(cfg["ui"].get("pet_scale", 1.0) or 1.0)
            self._store = AssetStore(self._pack, scale=scale)
            self._player = FramePlayer(self._store, self)
            self._player.frameChanged.connect(self.update)
            self._player.finished.connect(self._on_anim_finished)

        self._art = self._load_art()
        cw, chh = self._content_size()
        self.setFixedSize(max(W, cw + 20), ART_TOP_MIN + chh + 8)

        self.state = "idle"          # idle / walking / watching / alert / rest / sleep
        self.text = ""
        self.phase = 0.0
        self.gait = 0.0              # 走路节拍，和呼吸的 phase 分开
        self._drag: QPoint | None = None
        self._press_pos: QPoint | None = None
        self._moved = 0
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._clear_text)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.start(90)

        # 自主踱步：速度（像素/秒）、方向、休息到什么时候、下次换向时间
        self._wander = bool(cfg["ui"].get("pet_wander", False))
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
        self._mode = "top"
        self.set_mode(cfg["ui"].get("pet_mode", "top"))

    # ---------------------------------------------------------------- 显示层级
    MODES = ("top", "desktop", "hidden")

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """切换桌宠的显示层级（控制面板上那三档）。

        top      始终置顶：压在所有窗口上面
        desktop  只在桌面显示：沉到普通窗口下面，桌面看得见、一开窗口就藏起来
        hidden   不显示：提醒改走托盘气泡
        """
        mode = mode if mode in self.MODES else "top"
        self._mode = mode
        pos = self.pos()
        flags = Qt.FramelessWindowHint | Qt.Tool
        if mode == "top":
            flags |= Qt.WindowStaysOnTopHint
        elif mode == "desktop":
            flags |= Qt.WindowStaysOnBottomHint
        self.setWindowFlags(flags)      # 这个调用会把窗口藏起来
        if mode == "hidden":
            self.hide()
            return
        self.move(pos)                  # 重建窗口后位置会丢，放回去
        self.show()
        self._apply_mask()

    # ---------------------------------------------------------------- 立绘
    def _load_art(self):
        """读静态立绘并按 ui.pet_scale / 屏幕 DPI 预缩放好；缺文件返回 None。"""
        if not ART_FILE.exists():
            return None
        pm = QPixmap(str(ART_FILE))
        if pm.isNull():
            return None
        dpr = self.devicePixelRatioF() or 1.0
        scale = float(self.cfg["ui"].get("pet_scale", 1.0) or 1.0) * dpr
        target_h = max(1, int(round(ART_HEIGHT * scale)))
        target_w = max(1, int(round(pm.width() * target_h / pm.height())))
        pm = pm.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        return pm

    def _art_size(self) -> tuple[int, int]:
        """立绘的逻辑尺寸（除以 devicePixelRatio，才是窗口里的像素）。"""
        dpr = self._art.devicePixelRatio() or 1.0
        return (max(1, int(round(self._art.width() / dpr))),
                max(1, int(round(self._art.height() / dpr))))

    def _content_size(self) -> tuple[int, int]:
        """当前素材内容的逻辑尺寸：动作包画布 > 静态立绘 > 手画小熊。"""
        if self._store is not None:
            return self._store.canvas_size()
        if self._art is not None:
            return self._art_size()
        return (W, 140)

    def _apply_mask(self) -> None:
        """只在角色身体那一块接收鼠标：窗口是透明的，但不用遮罩的话上方空白
        区域会挡住桌面点击。气泡显示期间取消遮罩，否则气泡会被裁掉。"""
        if self.text:
            self.clearMask()
            return
        cw, ch = self._content_size()
        x = (self.width() - cw) // 2 - 2
        y = self.height() - ch - 2
        self.setMask(QRegion(x, y, cw + 4, ch + 2))

    # ---------------------------------------------------------------- 状态
    def _animate(self) -> None:
        self.phase += 0.12
        # 动作包由自己的 QTimer 换帧并触发 update()；静态立绘也不用重绘；
        # 只有手画小熊需要 90ms 一次呼吸/眨眼
        if self._player is None and self._art is None:
            self.update()

    # ---------------------------------------------------------------- 动画
    def _play(self, state: str, loop: bool | None = None) -> bool:
        if self._player is None:
            return False
        return self._player.play(state, loop)

    def _play_idle(self) -> None:
        """待机：从 manifest 的 idle 列表里随机挑一个（避免每次启动都同一张脸）。"""
        if self._player is None:
            return
        key = self._pack.pick_event("idle") if self._pack is not None else None
        if key is None:
            key = "idle_a"
        self._play(key)

    def _on_anim_finished(self, key: str) -> None:
        """一次性动作播完 → 回到待机（气泡文字由 _hide_timer 自己清）。"""
        self.state = "alert" if self.text else "idle"
        self._play_idle()

    def showEvent(self, e):
        super().showEvent(e)
        if self._player is not None and not self._player.is_playing():
            self._play_idle()

    def set_state(self, state: str) -> None:
        if state == "sleep":
            self.show_idle_pos()
        self.state = state
        if self._player is not None:
            if state == "sleep":
                self._play(self._pack.pick_event("sleep") or "idle_doze")
            elif state == "walking":
                self._play(self._pack.pick_event("walk") or "walk")
            elif state in ("idle", "rest"):
                self._play_idle()
        self.update()

    def show_idle_pos(self) -> None:
        """把桌宠放到屏幕右下角贴边（首次启动 / 从全屏退出时）。"""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.x() + area.width() - self.width() + 40,
                  area.y() + area.height() - self.height() + 10)

    def alert(self, text: str, ms: int = 5000, level: int = 1) -> None:
        self.text = text
        self.state = "alert" if level < 3 else "alert"
        self.show()
        self.raise_()
        if level >= 3:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.center().x() - self.width() // 2,
                          area.center().y() - self.height() // 2)
        self._hide_timer.start(ms)
        if self._player is not None:
            self.state = "alert"
            self._play(self._pack.pick_event("alert") or "alert_tired")
        self._apply_mask()
        self.update()

    def _clear_text(self) -> None:
        self.text = ""
        self.state = "idle"
        if self._wander:
            # 走动模式下别瞬移回右下角，原地缓一下接着走
            self._vx = self._vy = 0.0
            self._rest_until = time.monotonic() + random.uniform(1.5, 3.5)
        # 不走动模式（ui.pet_wander=false）就待在原地，别把用户拖好的位置挪走
        self._play_idle()
        self._apply_mask()
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
            self._play_idle()
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
            if self._player is not None and self._player.key != "idle_a":
                self._play_idle()
            return
        if now >= self._turn_at or (self._vx == 0.0 and self._vy == 0.0):
            self._pick_direction(now)
            return

        area = self._screen_area()
        step = WALK_INTERVAL_MS / 1000.0
        x = self.x() + self._vx * step
        y = self.y() + self._vy * step

        left, top = area.x(), area.y()
        right, bottom = (area.x() + area.width() - self.width(),
                         area.y() + area.height() - self.height())
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
        if self._player is not None and not self._player.is_playing("walk"):
            self._play(self._pack.pick_event("walk") or "walk")
        self.cfg["ui"]["pet_position"] = [self.x(), self.y()]

    # ---------------------------------------------------------------- 交互
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = e.globalPosition().toPoint()
            self._moved = 0
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
            if self._press_pos is not None:
                delta = e.globalPosition().toPoint() - self._press_pos
                self._moved = max(self._moved, abs(delta.x()) + abs(delta.y()))
            # 被拎起来时切「悬空」动画（只切一次，别每帧都重播）
            if self._moved > 6 and self._player is not None and not self._player.is_playing("drag"):
                self.state = "dragging"
                self._play(self._pack.pick_event("drag") or "drag", loop=True)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        self._drag = None
        # 贴边半隐藏：拖到边缘时收进去一半
        area = self._screen_area()
        x, y = self.x(), self.y()
        w = self.width()
        if x < area.left() + 20:
            x = area.left() - w // 2
        elif x + w > area.x() + area.width() - 20:
            x = area.x() + area.width() - w // 2
        self.move(max(area.left() - w // 2,
                      min(x, area.x() + area.width() - w // 2)), y)
        self.cfg["ui"]["pet_position"] = [self.x(), self.y()]
        self._rest_until = time.monotonic() + random.uniform(2.0, 4.0)

        # 没怎么动 = 点一下：播一个点击回应；真拖过就回待机
        if self._moved <= 6:
            key = self._pack.pick_event("click") if self._pack is not None else None
            if key is not None:
                self.state = "click"
                self._play(key, loop=False)
            else:
                self._play_idle()
        else:
            self._play_idle()
        self._press_pos = None
        self._moved = 0
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self._clear_text()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        if self.text:
            self._draw_bubble(p)

        # 动作包优先：画当前帧（脚底贴窗口底边、水平居中）
        if self._player is not None:
            pm = self._player.current()
            if pm is not None:
                self._draw_frame(p, pm)
                return

        if self._art is not None:
            self._draw_art(p)
            return

        walking = self.state == "walking"
        breathe = math.sin(self.phase) * 2.0
        bob = math.sin(self.gait) * 2.2 if walking else breathe * 0.4
        cx, cy = W // 2, 150 + bob
        r = 46

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

    def _draw_frame(self, p: QPainter, pm: QPixmap) -> None:
        """动作包的一帧：脚底贴窗口底边、水平居中，脚下垫一点影子。"""
        size = pm.deviceIndependentSize()
        w = int(round(size.width()))
        h = int(round(size.height()))
        x = (self.width() - w) // 2
        y = self.height() - h

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawEllipse(QPoint(self.width() // 2, y + h - 4), max(14, w // 4), 6)

        dest = QRect(x, y, w, h)
        p.drawPixmap(dest, pm)

    def _draw_art(self, p: QPainter) -> None:
        """静态立绘：脚底贴窗口底边中心，脚下垫一点影子。"""
        aw, ah = self._art_size()
        x = (self.width() - aw) // 2
        y = self.height() - ah - 2

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawEllipse(QPoint(self.width() // 2, y + ah - 2), max(18, aw // 3), 7)

        p.drawPixmap(x, y, self._art)

    def _draw_bubble(self, p: QPainter) -> None:
        w = self.width()
        rect = QRect(6, 6, w - 12, 76)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.setPen(QPen(QColor("#DDE2E8"), 1))
        p.setBrush(QColor(255, 255, 255, 246))
        p.drawPath(path)

        # 小尾巴
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 246))
        tri = QPainterPath()
        tri.moveTo(w / 2 - 8, 82)
        tri.lineTo(w / 2 + 8, 82)
        tri.lineTo(w / 2, 96)
        tri.closeSubpath()
        p.drawPath(tri)

        p.setPen(QColor("#1F2937"))
        f = QFont("Microsoft YaHei", 9)
        p.setFont(f)
        p.drawText(rect.adjusted(10, 6, -10, -6),
                   Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap, self.text)
