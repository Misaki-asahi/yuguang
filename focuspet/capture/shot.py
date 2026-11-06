# -*- coding: utf-8 -*-
"""截图、缩放、去重（设计方案 10.2 / 10.3）。

三个数字是这套设计的性价比所在：
  max_side=1280、quality=70 —— 模型输入侧本来就会缩到 1024~1536，再大纯属浪费 token；
  dHash 汉明距离 <= 6 视为同一画面 —— 打字场景下约一半的帧可以当场丢掉。
"""
from __future__ import annotations

import time

from PIL import Image, ImageStat

from .. import config

try:
    import mss
except Exception:            # pragma: no cover
    mss = None


def dhash(img: Image.Image, size: int = 8) -> int:
    """差分哈希：比 pHash 快约 3 倍，且对打字时的小变化更敏感。"""
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    row = size + 1
    for r in range(size):
        base = r * row
        for c in range(size):
            bits = (bits << 1) | int(px[base + c] < px[base + c + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_black(img: Image.Image, threshold: float = 8.0) -> bool:
    """DRM 视频（Netflix 等）截出来是纯黑，模型看不懂，直接跳过（4 节降级表）。"""
    try:
        return ImageStat.Stat(img.convert("L")).mean[0] < threshold
    except Exception:
        return False


class Capturer:
    """一次采集会话持有同一个 mss 实例：反复创建开销明显。"""

    def __init__(self, cfg: dict):
        cap = cfg["capture"]
        self.max_side = int(cap.get("max_shot_side", 1280))
        self.quality = int(cap.get("jpeg_quality", 70))
        self.screens = cap.get("screens") or [1]
        strip = cfg["privacy"].get("strip_crop") or [0, 0, 1.0, 1.0]
        self.strip = tuple(float(x) for x in strip)
        self._sct = None
        self._last_hash: int | None = None

    # ---------------------------------------------------------------- 底层
    def _ensure(self):
        if self._sct is None:
            if mss is None:
                raise RuntimeError("缺少 mss 依赖：pip install mss")
            self._sct = mss.mss()
        return self._sct

    def grab(self) -> Image.Image | None:
        try:
            sct = self._ensure()
            idx = int(self.screens[0])
            monitors = sct.monitors
            if idx >= len(monitors):
                idx = 1
            raw = sct.grab(monitors[idx])
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception:
            return None

    # ---------------------------------------------------------------- 主路径
    def shot(self, now: float | None = None) -> tuple[str, int] | None:
        """截一张、去个重、存下来，返回 (相对路径, dhash)。

        None 表示这一帧不该存：截图失败 / 全黑 / 与上一帧几乎是同一画面。
        """
        img = self.grab()
        if img is None:
            return None
        if is_black(img):
            return None

        h = dhash(img)
        if self._last_hash is not None and hamming(h, self._last_hash) <= 6:
            return None
        self._last_hash = h

        # 只发送窗口内容区：裁掉任务栏和通知区（16.2 的脱敏定义）
        w, hgt = img.size
        l, t, r, b = self.strip
        box = (int(w * l), int(hgt * t), int(w * r), int(hgt * b))
        if box != (0, 0, w, hgt):
            img = img.crop(box)

        img.thumbnail((self.max_side, self.max_side))

        now = now or time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        folder = config.day_dir(day)
        name = time.strftime("%H%M%S", time.localtime(now)) + f"_{int(now * 1000) % 1000:03d}.jpg"
        path = folder / name
        try:
            img.save(path, "JPEG", quality=self.quality, optimize=True)
        except Exception:
            return None
        rel = path.relative_to(config.DATA).as_posix()
        return rel, h

    def reset(self) -> None:
        """分辨率突变（远程桌面切换）后丢弃旧哈希，重新开始比（4 节降级表）。"""
        self._last_hash = None

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


# 过期清理搬到了 maintenance.py（要同时处理日志和明细，也需要统计释放空间）
