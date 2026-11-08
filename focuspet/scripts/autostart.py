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
    """优先用项目自带的 .venv：共享运行时会被宿主程序重置，依赖一夜之间消失过一次。"""
    venv = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return cand if cand.exists() else exe


def _run_ps(script: str) -> None:
    """写成带 BOM 的 .ps1 再执行。

    路径里有中文时，`-Command` 会按系统代码页重新解码，'席' 会变成乱码，
    快捷方式就指向一个不存在的路径。落文件（UTF-8 BOM）可以彻底避开这个坑。
    """
    tmp_dir = PROJECT_ROOT / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ps1 = tmp_dir / "autostart_task.ps1"
    ps1.write_text(script, encoding="utf-8-sig")
    try:
        # 必须捕获输出：继承父进程的 stdio 时，WScript.Shell 的 Save() 会抛
        # UnauthorizedAccess 而且 PowerShell 还返回 0，坑过一次。
        return subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True,
        )
    finally:
        try:
            ps1.unlink()
        except OSError:
            pass


def install() -> Path:
    lnk = startup_dir() / LNK_NAME
    # 已存在时先删：直接覆盖偶发 UnauthorizedAccess（Explorer 可能开着这个文件）
    if lnk.exists():
        try:
            lnk.unlink()
        except OSError:
            pass
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
    before = lnk.stat().st_mtime_ns if lnk.exists() else 0
    res = _run_ps(ps)
    after = lnk.stat().st_mtime_ns if lnk.exists() else 0
    if after <= before:
        # PowerShell 失败时可能仍返回 0，所以只认「文件真的被重写了」
        err = (res.stderr or b"").decode("gbk", "replace").strip() or "未知错误"
        raise RuntimeError(
            "快捷方式没写成。" + err[:300] +
            "\n提示：某些受限环境（沙箱）会禁止子进程写启动文件夹，"
            "换一个普通命令行窗口再执行一次即可。")
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
