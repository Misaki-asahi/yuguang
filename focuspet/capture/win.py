# -*- coding: utf-8 -*-
"""前台窗口探针与空闲检测（设计方案 10.1 / 10.4）。

只用 ctypes，不引 pywin32：零依赖，且这几个 API 十年来没变过。
三个已知坑都在这里处理掉了：
  * 管理员权限窗口读不到标题 → 降级用进程名；
  * psutil 每 5 秒查一次进程名会吃 CPU → LRU 缓存；
  * 中文标题乱码 → 全部走 W 版 API + create_unicode_buffer。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from functools import lru_cache

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    _u = ctypes.windll.user32
else:  # pragma: no cover - 仅非 Windows 开发环境兜底
    _u = None


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    proc: str

    def key(self) -> tuple:
        return (self.proc, self.title)


def enable_dpi_awareness() -> None:
    """不声明 DPI 感知的话，125% 缩放下截图会偏移或模糊（10.2）。"""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_AWARE
    except Exception:
        try:
            _u.SetProcessDPIAware()
        except Exception:
            pass


@lru_cache(maxsize=512)
def _proc_name(pid: int) -> str:
    """进程名查询。缓存是必须的——每 5 秒一次 CreateProcess 查询肉眼可见地吃 CPU。"""
    if pid <= 0:
        return ""
    try:
        import psutil
        return psutil.Process(pid).name() or ""
    except Exception:
        return ""


def foreground() -> WindowInfo | None:
    """当前前台窗口。失败返回 None，调用方继续记时间戳即可。"""
    if not IS_WINDOWS:
        return None
    try:
        hwnd = _u.GetForegroundWindow()
        if not hwnd:
            return None
        buf = ctypes.create_unicode_buffer(512)
        _u.GetWindowTextW(hwnd, buf, 512)
        pid = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return WindowInfo(hwnd=hwnd, title=buf.value or "",
                          pid=pid.value, proc=_proc_name(pid.value))
    except Exception:
        return None


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    """键鼠无输入的秒数。用 GetLastInputInfo 而不是装钩子，轻得多。"""
    if not IS_WINDOWS:
        return 0.0
    try:
        li = _LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if not _u.GetLastInputInfo(ctypes.byref(li)):
            return 0.0
        tick = _u.GetTickCount() & 0xFFFFFFFF
        delta = (tick - li.dwTime) & 0xFFFFFFFF
        return delta / 1000.0
    except Exception:
        return 0.0


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def is_fullscreen(hwnd: int) -> bool:
    """窗口外框是否等于所在显示器外框。

    用途只有两个：全屏视频/游戏时跳过截图（DRM 会截出黑屏），
    以及桌宠自动隐藏（13.3）。判错了也只是少截一张，不影响元数据。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        # 关键：最大化窗口的 GetWindowRect 返回的也是整屏矩形（Windows 的隐形边框），
        # 不排除掉的话，日常所有最大化的窗口都会被当成全屏，截图就永远不截了。
        style = _u.GetWindowLongW(hwnd, -16)            # GWL_STYLE
        if style & 0x01000000:                          # WS_MAXIMIZE
            return False
        rect = _RECT()
        if not _u.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        monitor = _u.MonitorFromWindow(hwnd, 2)             # MONITOR_DEFAULTTONEAREST
        if not monitor:
            return False

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                        ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]

        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if not _u.GetMonitorInfoW(monitor, ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return (abs(rect.left - m.left) <= 2 and abs(rect.top - m.top) <= 2
                and abs(rect.right - m.right) <= 2 and abs(rect.bottom - m.bottom) <= 2)
    except Exception:
        return False


def masked_title(title: str, keywords: list[str]) -> str:
    """标题脱敏：命中敏感关键词的标题不落库（10.4）。

    只记元数据还不够——标题本身就是敏感信息，必须替换掉。
    """
    low = (title or "").lower()
    for kw in keywords:
        if kw and kw.lower() in low:
            return "<sensitive>"
    return title


def is_sensitive_proc(proc: str, names: list[str]) -> bool:
    p = (proc or "").lower()
    return any(p == n.lower() for n in names if n)
