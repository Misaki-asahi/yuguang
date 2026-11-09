# -*- coding: utf-8 -*-
"""开机自启：启动文件夹 + pythonw，不改注册表，卸载等于删快捷方式。

放在包里（而不是 scripts/ 下）是为了让设置面板能直接调用。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]      # 含 focuspet/ 的目录
LNK_NAME = "FocusPet.lnk"


def icon_path() -> Path | None:
    """快捷方式能用的图标路径。

    Windows 的 Shell 读不了含非 ASCII 字符的 .ico（实测：同一个文件放在
    `...\\with席\\...` 下快捷方式显示白纸，复制到纯英文路径就正常），
    所以这里把图标复制到 %LOCALAPPDATA%\\FocusPet\\icon.ico 再用。
    如果那个路径本身也含非 ASCII，就退回原始路径（显示不出来也不影响启动）。
    """
    src = PROJECT_ROOT / "focuspet" / "assets" / "icon.ico"
    if not src.exists():
        return None
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FocusPet"
    dst = base / "icon.ico"
    try:
        if str(dst).isascii():
            base.mkdir(parents=True, exist_ok=True)
            if (not dst.exists()) or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dst)
            return dst
    except OSError:
        pass
    return src


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("找不到 %APPDATA%")
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"


def pythonw() -> Path:
    """优先用 %LOCALAPPDATA%\\FocusPet\\venv —— 它必须是纯 ASCII 路径。

    踩过两次同一个坑：
      * 项目目录叫 `with席`，venv 放在项目里 → python 的子进程（Edge）启动即以
        退出码 21 崩溃，日报永远弹不出来；
      * 换成 `C:\\Users\\...\\AppData\\Local\\FocusPet\\venv` 后一切正常。
    所以哪怕项目路径含中文，解释器也要待在英文路径下。
    """
    ascii_venv = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FocusPet" / "venv" / "Scripts" / "pythonw.exe"
    if ascii_venv.exists():
        return ascii_venv
    local_venv = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if local_venv.exists():
        return local_venv
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
    icon = icon_path()
    icon_arg = str(icon) if icon else str(target)
    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        f"$s.TargetPath='{target}';"
        f"$s.Arguments='{args}';"
        f"$s.WorkingDirectory='{PROJECT_ROOT}';"
        f"$s.IconLocation='{icon_arg}';"
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
