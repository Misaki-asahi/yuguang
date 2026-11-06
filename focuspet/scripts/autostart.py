# -*- coding: utf-8 -*-
"""开机自启：启动文件夹 + pythonw，不改注册表，卸载等于删快捷方式（15.5）。

用法：
    python scripts/autostart.py install
    python scripts/autostart.py uninstall
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]      # 含 focuspet/ 的目录
LNK_NAME = "FocusPet.lnk"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("找不到 %APPDATA%")
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"


def pythonw() -> Path:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return cand if cand.exists() else exe


def _run_ps(script: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


def install() -> Path:
    lnk = startup_dir() / LNK_NAME
    target = pythonw()
    args = "-m focuspet"
    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        f"$s.TargetPath='{target}';"
        f"$s.Arguments='{args}';"
        f"$s.WorkingDirectory='{PROJECT_ROOT}';"
        f"$s.IconLocation='{target}';"
        f"$s.Save()"
    )
    _run_ps(ps)
    return lnk


def uninstall() -> bool:
    lnk = startup_dir() / LNK_NAME
    if lnk.exists():
        lnk.unlink()
        return True
    return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"
    if cmd == "install":
        print("已创建开机自启快捷方式：", install())
    elif cmd == "uninstall":
        print("已移除" if uninstall() else "没有找到自启快捷方式")
    else:
        print("用法：python scripts/autostart.py [install|uninstall]")
