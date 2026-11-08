# -*- coding: utf-8 -*-
"""单实例锁：防止连点快捷方式时开出第二份（内存翻倍、样本重复记录）。

原理就是"独占创建一个锁文件"，里面写自己的 PID。后来者看到锁文件：
- PID 还活着 → 认定已有实例，去唤起它然后自己退出；
- PID 已经不在了（上次崩溃没清理）→ 删掉重来。

比端口探测更早生效：在解析参数之后、创建 App 之前就拿锁，
把"两个进程同时启动"那段窗口也堵上。
"""
from __future__ import annotations

import os
import time

from . import config

LOCK = config.DATA / "instance.lock"


def _read_pid() -> int:
    try:
        return int(LOCK.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:
        # 没有 psutil 时的兜底：进程存在就打不开句柄
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire() -> bool:
    """拿到锁返回 True；已有活实例返回 False。"""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            pid = _read_pid()
            if _alive(pid):
                return False
            # 上次崩溃留下的僵尸锁，清掉再试
            try:
                LOCK.unlink()
            except OSError:
                pass
            time.sleep(0.05)
    return True


def release() -> None:
    try:
        if _read_pid() == os.getpid():
            LOCK.unlink()
    except OSError:
        pass
