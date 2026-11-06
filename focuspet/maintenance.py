# -*- coding: utf-8 -*-
"""数据清理：截图、日志、采样明细（设计方案 14.4 保留策略）。

默认只留一周的截图——那是磁盘大头。明细留在库里更久（几十 MB 而已），
但都可以在设置面板里改。删之前一律校验路径前缀，防止配置写错删到别处。
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from . import config
from .log import get

log = get("maint")


def _tree_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def detach_shot_refs(day: str) -> int:
    """删截图前先把当天日报里的 <img> 换成占位说明，避免历史报表里一堆断图。

    报告是自包含 HTML，只替换我们自己生成的 img 标签，别的一概不动。
    """
    report = Path(config.REPORTS) / f"{day}.html"
    if not report.exists():
        return 0
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return 0
    pattern = re.compile(r'<img src="\.\./shots/' + re.escape(day) + r'/[^"]*"[^>]*>')
    new, n = pattern.subn('<div class="none">截图已按保留策略清理</div>', text)
    if n:
        tmp = report.with_suffix(".html.tmp")
        tmp.write_text(new, encoding="utf-8")
        os.replace(tmp, report)
        log.info("%s 的日报里有 %d 张截图被清理，已替换为说明", day, n)
    return n


def clean_shots(days: int, base: Path | None = None) -> tuple[int, int]:
    """删掉超过 days 天的截图目录，返回 (目录数, 释放字节)。"""
    base = Path(base or config.SHOTS)
    if not base.exists():
        return 0, 0
    cutoff = time.time() - days * 86400
    dirs = 0
    freed = 0
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        try:
            if d.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        if not str(d.resolve()).startswith(str(base.resolve())):
            log.warning("拒绝删除越界路径：%s", d)
            continue
        detach_shot_refs(d.name)          # 先断开日报引用，再删
        freed += _tree_size(d)
        shutil.rmtree(d, ignore_errors=True)
        dirs += 1
    return dirs, freed


def clean_logs(days: int) -> tuple[int, int]:
    """轮转日志由 handler 自己按 7 份滚动，这里兜底清更老的残档。"""
    base = Path(config.LOGS)
    if not base.exists():
        return 0, 0
    cutoff = time.time() - days * 86400
    files = 0
    freed = 0
    for f in base.glob("focuspet.log.*"):
        try:
            if f.stat().st_mtime >= cutoff:
                continue
            freed += f.stat().st_size
            f.unlink()
            files += 1
        except OSError:
            continue
    return files, freed


def clean_all(cfg: dict, store=None) -> dict:
    """按配置清理一遍，返回可读的结果。"""
    r = cfg["retention"]
    shots_days = int(r.get("shots_days", 7))
    logs_days = int(r.get("logs_days", 7))
    samples_days = int(r.get("samples_days", 30))

    d_shots, b_shots = clean_shots(shots_days)
    d_logs, b_logs = clean_logs(logs_days)
    samples = store.prune(samples_days) if store is not None else 0

    res = {
        "shot_days_removed": d_shots,
        "log_files_removed": d_logs,
        "samples_removed": samples,
        "freed_bytes": b_shots + b_logs,
        "kept_days": shots_days,
    }
    log.info("清理完成：%s", res)
    return res


def human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"
