# -*- coding: utf-8 -*-
"""图集缓存：把一个状态的 WebP 精灵图集切成逐帧 QPixmap，按需加载、LRU 缓存。

内存账：一个动作 80 帧 × 220×211 ≈ 15 MB。全部预载会吃掉几百 MB，所以只在
播到某个状态时才切它，并且只留最近 3 个状态。
"""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap

from .manifest import Pack


class AssetStore:
    def __init__(self, pack: Pack, scale: float = 1.0, max_cached: int = 3):
        self.pack = pack
        self.scale = max(0.2, min(4.0, float(scale)))
        self.max_cached = max(1, int(max_cached))
        self._cache: OrderedDict[str, list[QPixmap]] = OrderedDict()
        self._dpr = 1.0
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self._dpr = float(screen.devicePixelRatio() or 1.0)

    # ---------------------------------------------------------------- 尺寸
    def canvas_size(self) -> tuple[int, int]:
        """画布的逻辑尺寸（已含 pet_scale；不含 DPI 倍率）。"""
        return (max(1, int(round(self.pack.canvas_w * self.scale))),
                max(1, int(round(self.pack.canvas_h * self.scale))))

    # ---------------------------------------------------------------- 取帧
    def frames(self, key: str) -> list[QPixmap]:
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        state = self.pack.state(key)
        if state is None:
            return []

        atlas = QPixmap(str(state.atlas))
        if atlas.isNull():
            return []

        # 一次性把整张图集缩到目标分辨率（含 DPI + ui.pet_scale），再做切片，
        # 避免每帧单独缩放导致边缘不一致。
        ratio = self._dpr * self.scale
        cw = max(1, int(round(self.pack.canvas_w * ratio)))
        chh = max(1, int(round(self.pack.canvas_h * ratio)))
        if (atlas.width(), atlas.height()) != (cw * state.columns, chh * state.rows):
            atlas = atlas.scaled(cw * state.columns, chh * state.rows,
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            atlas.setDevicePixelRatio(self._dpr)

        out: list[QPixmap] = []
        for i in range(state.frames):
            r, c = divmod(i, state.columns)
            pm = atlas.copy(c * cw, r * chh, cw, chh)
            pm.setDevicePixelRatio(self._dpr)
            out.append(pm)

        self._cache[key] = out
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_cached:
            self._cache.popitem(last=False)
        return out

    def clear(self) -> None:
        self._cache.clear()
