# -*- coding: utf-8 -*-
"""帧播放器：按状态自己的 fps 换帧，只负责「现在该画哪一张」。

两种收尾方式：
- loop=True  播到最后一帧回到第 0 帧，一直循环（待机/走路/被拖）；
- loop=False 播完停在最后一帧并发 finished 信号（提醒/点击回应），由外面决定
  接下来切回哪个状态。

帧定时用 QTimer 单发重排（每帧间隔可以不同），不用固定 interval，方便以后某
个状态需要变速。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

from .assets import AssetStore


class FramePlayer(QObject):
    frameChanged = Signal()
    finished = Signal(str)          # 参数：刚播完的状态 key

    def __init__(self, store: AssetStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self._key: str | None = None
        self._frames: list[QPixmap] = []
        self._index = 0
        self._loop = True

    # ---------------------------------------------------------------- 状态
    @property
    def key(self) -> str | None:
        return self._key

    def current(self) -> QPixmap | None:
        if not self._frames:
            return None
        return self._frames[self._index % len(self._frames)]

    def is_playing(self, key: str | None = None) -> bool:
        if self._key is None:
            return False
        return key is None or self._key == key

    # ---------------------------------------------------------------- 控制
    def play(self, key: str, loop: bool | None = None) -> bool:
        """切到某个状态。没有这个状态的帧就返回 False（调用方保留原来的画面）。"""
        frames = self._store.frames(key)
        if not frames:
            return False
        state = self._store.pack.state(key)
        self._timer.stop()
        self._key = key
        self._frames = frames
        self._index = 0
        self._loop = bool(state.loop) if loop is None else bool(loop)
        self.frameChanged.emit()
        self._schedule_next()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._key = None
        self._frames = []
        self._index = 0

    # ---------------------------------------------------------------- 内部
    def _schedule_next(self) -> None:
        state = self._store.pack.state(self._key or "")
        if state is None:
            return
        self._timer.start(state.interval_ms)

    def _advance(self) -> None:
        key = self._key
        if not key or not self._frames:
            return
        last = len(self._frames) - 1
        if self._index >= last:
            if self._loop:
                self._index = 0
            else:
                self._timer.stop()
                self.finished.emit(key)
                self._schedule_next_idle_hold()
                return
        else:
            self._index += 1
        self.frameChanged.emit()
        self._schedule_next()

    def _schedule_next_idle_hold(self) -> None:
        """一次性动画播完后画面停在最后一帧，等外面切走时再更新。"""
        self.frameChanged.emit()
