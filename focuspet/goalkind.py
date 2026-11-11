# -*- coding: utf-8 -*-
"""目标类型：决定「哪些类别算在任务上」。

规则模式读不懂语义，所以由用户声明一个类型（工作 / 学习 / 休闲 / 生活）；
没声明（auto）就用关键词猜，猜不出来按「工作」处理——保守，消耗类仍会被判跑偏。
这套判断同时喂两个地方：判定链（要不要提醒）和 on_task（在不在任务上）。
"""
from __future__ import annotations

KINDS = {
    "auto": "自动",
    "work": "工作",
    "study": "学习",
    "leisure": "休闲",
    "life": "生活",
}

_BASE = {"deep_work", "shallow_work", "learning"}

# 目标的类型决定「哪些类别不算跑偏」。看课程视频属于学习，所以娱乐也要放行。
ALLOWED = {
    "work": _BASE,
    "study": _BASE | {"entertainment"},
    "leisure": _BASE | {"entertainment", "aimless", "life"},
    "life": _BASE | {"entertainment", "aimless", "life"},
}

_STUDY_WORDS = ("课程", "网课", "教程", "讲座", "复习", "考试", "学习",
                "论文", "视频课", "刷题", "作业", "看书")
_LEISURE_WORDS = ("放松", "休息", "追剧", "游戏", "娱乐", "看片", "听歌")


def guess(text: str) -> str:
    """从目标文字猜类型；猜不出返回 auto。"""
    t = (text or "").lower()
    if any(w in t for w in _LEISURE_WORDS):
        return "leisure"
    if any(w in t for w in _STUDY_WORDS):
        return "study"
    return "auto"


def effective(kind: str | None, text: str) -> str:
    """显式类型优先；auto 时用关键词；仍猜不出就按工作（保守）。"""
    k = (kind or "auto").strip()
    if k in ALLOWED:
        return k
    g = guess(text)
    return "work" if g == "auto" else g


def allows(kind: str | None, text: str, category: str) -> bool:
    """这个类别算不算「在目标上」。"""
    return category in ALLOWED[effective(kind, text)]


def label(kind: str | None) -> str:
    return KINDS.get((kind or "auto"), "自动")
