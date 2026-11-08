# -*- coding: utf-8 -*-
"""单实例唤起：托盘图标找不到时，再启动一次就能把窗口叫出来。

做法很土但可靠：运行中的实例在 127.0.0.1 上开一个随机端口，把端口号写进
`data/ipc.port`；后启动的进程读这个文件、连上去发一句话就退出。
不依赖托盘图标是否可见，也不依赖窗口是否被挡住。
"""
from __future__ import annotations

import socket
import threading

from . import config
from .log import get

log = get("ipc")

PORT_FILE = config.DATA / "ipc.port"


def serve(handler) -> threading.Thread:
    """后台线程监听本机端口，收到任意请求就调用 handler()。"""

    def loop() -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", 0))
            srv.listen(5)
            port = srv.getsockname()[1]
            PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            PORT_FILE.write_text(str(port), encoding="utf-8")
            log.info("唤醒端口已就绪：%d", port)
            while True:
                conn, _ = srv.accept()
                try:
                    conn.settimeout(1.0)
                    conn.recv(64)
                    handler()
                except Exception:
                    log.debug("处理唤醒请求失败", exc_info=True)
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
        except Exception as exc:                       # 端口被占用等，不影响主程序
            log.warning("唤醒服务未启动：%s", exc)
        finally:
            try:
                srv.close()
            except OSError:
                pass

    t = threading.Thread(target=loop, name="ipc", daemon=True)
    t.start()
    return t


def request_show(timeout: float = 1.0) -> bool:
    """告诉正在运行的实例「把窗口显示出来」。没有实例在跑就返回 False。"""
    try:
        port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(b"show\n")
        return True
    except OSError:
        return False


def cleanup() -> None:
    try:
        PORT_FILE.unlink()
    except OSError:
        pass
