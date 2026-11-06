# -*- coding: utf-8 -*-
"""规则表匹配：零成本的那 80%（设计方案 11.1 的 A 档）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import config
from ..log import get

log = get("rules")


@dataclass(frozen=True)
class Hit:
    rule_id: str
    category: str
    weight: float
    activity: str = ""
    exempt: bool = False
    sensitive: bool = False


UNKNOWN = Hit("fallback", "unknown", 0.3, "未识别")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


class RuleSet:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or config.RULES_PATH)
        self.rules: list[dict] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            log.warning("规则表不存在：%s，将全部交给模型判断", self.path)
            self.rules = []
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.rules = [r for r in data.get("rules", []) if r.get("when") and r.get("then")]
            log.info("规则表载入 %d 条", len(self.rules))
        except Exception as exc:
            log.error("规则表解析失败：%s（沿用空表，不阻断采集）", exc)
            self.rules = []

    def classify(self, proc: str, title: str) -> Hit:
        p, t = _norm(proc), _norm(title)
        best: Hit | None = None
        for rule in self.rules:
            w = rule["when"]
            then = rule["then"]

            procs = w.get("proc")
            if procs is not None and p not in {_norm(x) for x in procs}:
                continue

            needles = w.get("title_contains")
            if needles is not None and not any(_title_hit(t, n) for n in needles):
                continue

            regex = w.get("title_regex")
            if regex and not re.search(regex, t, re.I):
                continue

            hit = Hit(
                rule_id=rule.get("id", "?"),
                category=then.get("category", "unknown"),
                weight=float(then.get("weight", 0.5)),
                activity=then.get("activity", ""),
                exempt=bool(then.get("exempt", False)),
                sensitive=bool(then.get("sensitive", False)),
            )
            if best is None or hit.weight > best.weight:
                best = hit
        return best or UNKNOWN


def _title_hit(title_lower: str, needle: str) -> bool:
    n = _norm(needle)
    if not n:                      # 空串代表「标题为空」
        return not title_lower.strip()
    return n in title_lower


def describe(hit: Hit, proc: str) -> str:
    """给规则命中的段一个人类可读的活动名。"""
    if hit.activity:
        return hit.activity
    return f"{proc or '未知程序'} 中操作"
