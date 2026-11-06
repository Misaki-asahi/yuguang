# -*- coding: utf-8 -*-
"""演示数据：不碰真实屏幕，凭空造一天，用来验证「采集→分类→聚合→日报」整条链。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config
from .capture.store import Store, day_bounds, day_of
from .log import get

log = get("demo")

# (起, 止, 进程, 窗口标题, 是否截图)
PLAN = [
    ("08:05", "08:22", "explorer.exe", "下载", False),
    ("08:22", "08:40", "chrome.exe", "新标签页 - Google Chrome", True),
    ("08:40", "09:00", "WeChat.exe", "张三 - 聊天", False),
    ("09:00", "09:47", "Code.exe", "spider.py - Visual Studio Code", True),
    ("09:47", "09:58", "chrome.exe", "Scrapy 文档 - Google Chrome", True),
    ("09:58", "11:30", "Code.exe", "spider.py - Visual Studio Code", True),
    ("11:30", "11:42", "WeChat.exe", "项目群 - 聊天", False),
    ("11:42", "12:05", "chrome.exe", "哔哩哔哩 (゜-゜)つロ 干杯~", True),
    ("12:05", "13:30", None, "idle", False),
    ("13:30", "13:52", "chrome.exe", "知乎 - 有问题就会有答案", True),
    ("13:52", "15:20", "WINWORD.EXE", "文献综述_v3.docx - Word", True),
    ("15:20", "15:38", "chrome.exe", "淘宝网 - 淘！我喜欢", True),
    ("15:38", "16:35", "Code.exe", "aggregate.py - Visual Studio Code", True),
    ("16:35", "17:02", "chrome.exe", "哔哩哔哩 - 一个视频", True),
    ("17:02", "17:40", "Code.exe", "render.py - Visual Studio Code", True),
    ("17:40", "18:20", "Teams.exe", "组会 - Microsoft Teams", False),
    ("18:20", "18:58", "WeChat.exe", "同事 - 聊天", False),
    ("18:58", "19:26", "cloudmusic.exe", "网易云音乐", False),
    ("19:26", "20:10", "Code.exe", "spider.py - Visual Studio Code", True),
    ("20:10", "21:00", "chrome.exe", "小红书 - 你的生活指南", True),
    ("21:00", "21:38", "Obsidian.exe", "周报 - Obsidian", True),
    ("21:38", "22:00", "chrome.exe", "YouTube - 一个视频", True),
]

SAMPLE_SEC = 20
SHOT_EVERY_SEC = 900
DEMO_REPORT = "demo.html"          # 固定文件名，重复跑覆盖同一份


def _at(day: str, hhmm: str) -> int:
    d = datetime.strptime(day, "%Y-%m-%d")
    h, m = (int(x) for x in hhmm.split(":"))
    return int(d.replace(hour=h, minute=m).timestamp())


def _font(size: int):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except Exception:
            continue
    return ImageFont.load_default()


def _placeholder(path: Path, title: str) -> None:
    """占位图：明确标注「演示占位图」，不冒充真实截图。"""
    w, h = 640, 400
    img = Image.new("RGB", (w, h), "#F7F8FA")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 34], fill="#E7EBF0")
    for i, c in enumerate(("#E06C5A", "#E0B44A", "#6FA96F")):
        d.ellipse([12 + i * 18, 12, 22 + i * 18, 22], fill=c)
    d.rectangle([0, 34, w, h], outline="#DDE2E8")
    d.text((20, 52), title[:34], font=_font(15), fill="#33404E")
    d.line([0, 84, w, 84], fill="#E3E8EE")
    d.text((20, 104), "演示占位图 · 非真实截图", font=_font(22), fill="#94A0AE")
    d.text((20, 140), "真实运行时这里是你的屏幕内容", font=_font(14), fill="#B3BCC7")
    img.save(path, "JPEG", quality=70, optimize=True)


def seed(store: Store, day: str | None = None) -> dict:
    day = day or day_of(time.time())
    store.clear_day(day)
    start, end = day_bounds(day)
    # 演示的占位图也单独放，不能写进真实截图目录（那里按天删除，会误伤真数据）
    folder = config.DATA / "shots-demo" / day
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass

    store.set_goal("写完文献综述第 2 节", _at(day, "08:05"))

    rows = []
    shots = 0
    for a, b, proc, title, want_shot in PLAN:
        t0, t1 = _at(day, a), _at(day, b)
        if proc is None:                      # idle 段：只记 idle，不截图
            for ts in range(t0, t1, SAMPLE_SEC):
                rows.append((ts, "", "", None, None, 1, 0))
            continue

        last_shot = 0
        for ts in range(t0, t1, SAMPLE_SEC):
            shot = None
            if want_shot and shots < 60 and ts - last_shot >= SHOT_EVERY_SEC:
                name = time.strftime("%H%M%S", time.localtime(ts)) + ".jpg"
                p = folder / name
                _placeholder(p, title)
                shot = p.relative_to(config.DATA).as_posix()
                last_shot = ts
                shots += 1
            rows.append((ts, proc, title, shot, None, 0, 0))

    n = store.bulk_insert_samples(rows)
    store.kv_set("poll_sec", SAMPLE_SEC)
    log.info("演示数据写入 %d 条采样、%d 张占位图（%s）", n, shots, day)
    return {"samples": n, "shots": shots, "day": day, "end": int(end)}


def run(cfg: dict, store: Store, day: str | None = None) -> dict:
    """造一天数据 → 跑真实的分析链路 → 出日报。"""
    from .analyze.scheduler import Scheduler
    from .report.render import render_day

    # 铁律：演示数据只能进 demo.db，绝不允许碰真实库（曾经踩过：--demo 用的是当天日期，
    # 一跑就把当天的真实采样清空了）。
    assert Path(store.path).resolve() != Path(config.DB_PATH).resolve(), \
        "演示模式不能使用真实数据库"
    info = seed(store, day)
    day = info["day"]
    sched = Scheduler(cfg, store)
    # 把「现在」推到当天结束，让所有批次都能被处理
    batches = sched.run(now=_at(day, "23:58"))
    path = render_day(cfg, store, day, open_browser=False, out_name=DEMO_REPORT)
    blocks = store.blocks(day)
    return {"day": day, "batches": batches, "blocks": len(blocks),
            "report": str(path), "samples": info["samples"]}


def open_demo_store():
    """演示专用库与目录，和真实数据完全隔离。"""
    return Store(config.DEMO_DB)
