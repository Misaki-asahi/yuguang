# -*- coding: utf-8 -*-
"""命令行入口：开机自启的安装/卸载（真正的实现在 focuspet/autostart.py）。

用法：
    python focuspet/scripts/autostart.py install
    python focuspet/scripts/autostart.py uninstall
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from focuspet.autostart import install, uninstall  # noqa: E402

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"
    if cmd == "install":
        print("已创建开机自启快捷方式：", install())
    elif cmd == "uninstall":
        print("已移除" if uninstall() else "没有找到自启快捷方式")
    else:
        print("用法：python focuspet/scripts/autostart.py [install|uninstall]")
