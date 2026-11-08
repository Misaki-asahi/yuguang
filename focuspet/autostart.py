# -*- coding: utf-8 -*-
"""开机自启：启动文件夹 + pythonw，不改注册表，卸载等于删快捷方式。

放在包里（而不是 scripts/ 下）是为了让设置面板能直接调用。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]      # 含 focuspet/ 的目录
LNK_NAME = "FocusPet.lnk"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("找不到 %APPDATA%")
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"


def pythonw() -> Path:
    """优先用项目自带的 .venv：共享运行时会被宿主程序重置，依赖一夜之间消失过一次。"""
    venv = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return cand if cand.exists() else exe


def lnk_path() -> Path:
    return startup_dir() / LNK_NAME


def is_installed() -> bool:
    return lnk_path().exists()


def _run_ps(script: str):
    """写成带 BOM 的 .ps1 再执行（路径含中文时 -Command 会按代码页重新解码）。"""
    tmp_dir = PROJECT_ROOT / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ps1 = tmp_dir / "autostart_task.ps1"
    ps1.write_text(script, encoding="utf-8-sig")
    try:
        # 必须捕获输出：继承父进程 stdio 时 WScript.Shell 的 Save() 会抛 UnauthorizedAccess
        return subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True,
        )
    finally:
        try:
            ps1.unlink()
        except OSError:
            pass


def install(with_panel: bool = False) -> Path:
    """创建/覆盖启动文件夹里的快捷方式。

    with_panel=True 时带 --panel，适合手动双击的那个快捷方式；
    开机自启用 False，不然每次开机都弹面板。
    """
    lnk = lnk_path()
    if lnk.exists():
        try:
            lnk.unlink()
        except OSError:
            pass
    target = pythonw()
    args = "-m focuspet --panel" if with_panel else "-m focuspet"
    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        f"$s.TargetPath='{target}';"
        f"$s.Arguments='{args}';"
        f"$s.WorkingDirectory='{PROJECT_ROOT}';"
        f"$s.IconLocation='{target}';"
        f"$s.Save()"
    )
    before = lnk.stat().st_mtime_ns if lnk.exists() else 0
    res = _run_ps(ps)
    after = lnk.stat().st_mtime_ns if lnk.exists() else 0
    if after <= before:
        err = (res.stderr or b"").decode("gbk", "replace").strip() or "未知错误"
        raise RuntimeError("快捷方式没写成。" + err[:300])
    return lnk


def uninstall() -> bool:
    lnk = lnk_path()
    if lnk.exists():
        try:
            lnk.unlink()
            return True
        except OSError:
            return False
    return False
