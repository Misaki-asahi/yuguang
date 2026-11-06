# -*- coding: utf-8 -*-
"""离题判定链（设计方案 3.2 / 3.3）。

整条链是「全否才退出」：任何一环不满足，就只记录、不提醒。
这不是保守，是唯一的活路——误报一次用户就关提醒，关掉提醒产品就死了。

判定模块自身出异常时返回「不判定」（9.2 的安全侧设计）：
宁可什么都不提醒，也不能因为 bug 疯狂弹窗。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..analyze.aggregate import CONSUMING


@dataclass
class Verdict:
    level: int
    reason: str
    rule_id: str = ""
    block_id: int | None = None

    def as_dict(self) -> dict:
        return {"level": self.level, "reason": self.reason,
                "rule_id": self.rule_id, "block_id": self.block_id}


QUIET = Verdict(0, "")


class Judge:
    def __init__(self, cfg: dict, store):
        self.cfg = cfg
        self.store = store
        self.j = cfg["judge"]

    # ---------------------------------------------------------------- 主入口
    def evaluate(self, block, now: int | None = None) -> Verdict:
        try:
            return self._chain(block, int(now or time.time()))
        except Exception:
            return QUIET

    def _chain(self, block, now: int) -> Verdict:
        if not self.j.get("enabled", True):
            return QUIET

        # 1) 会话门控：不在专注会话内，永不提醒
        goal = self.store.active_goal(now)
        if not goal:
            return QUIET

        # 2) 豁免名单：会议、白名单、临时豁免
        if self._exempt(block, now):
            return Verdict(0, "exempt")

        # 3) 元数据判定：只有明确的消耗类才继续
        cat = block["category"]
        if cat not in CONSUMING:
            return QUIET

        # 4) 置信度门槛
        conf = float(block["confidence"] or 0)
        if conf < 0.7:
            return QUIET

        # 5) 持续时长：短于阈值的切换大多是无意识的顺手点击
        dur_min = (int(block["end_ts"]) - int(block["start_ts"])) / 60.0
        if dur_min < float(self.j.get("off_task_minutes", 3)):
            return QUIET

        # 6) 冷却期（状态按天重置，跨零点不串味）。冷却挡的是「新的一次」，
        #    同一段离题的升级不受冷却限制，否则永远升不到 L2（3.5）。
        cooldown = float(self.j.get("cooldown_minutes", 10)) * 60
        state = self.store.kv_get(f"cooldown:{cat}", {}) or {}
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if state.get("day") != today:
            state = {"day": today}

        idle_gap = now - int(state.get("last", 0))
        if idle_gap >= cooldown or idle_gap > 300:
            # 新的一段离题（冷却已过，或中间断过 5 分钟以上——别让重启继承上一次的怒气）
            state["first_ts"] = now
            state["last_level"] = 0
            level = 1
        else:
            level = self._level(block, now, state)       # 同一段，最多升一级
            if level <= int(state.get("last_level", 1)):
                return Verdict(0, "cooldown")

        # 7) 日上限
        cap = int(self.j.get("l3_daily_cap", 5))
        if level >= 3 and int(state.get("l3_today", 0)) >= cap:
            level = 2
        if level <= 0:
            return QUIET

        return Verdict(level, f"{cat} 持续 {dur_min:.0f} 分钟",
                       rule_id=cat, block_id=block.get("id"))

    # ---------------------------------------------------------------- 细节
    def _exempt(self, block, now: int) -> bool:
        # 临时豁免：今天这个应用已被用户点过「我在做正事」
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        exempt = self.store.kv_get(f"exempt:{today}", []) or []
        proc = (block.get("proc") or "").lower()
        words = (block.get("activity") or "").lower()
        return any(e.lower() in (proc + " " + words) for e in exempt)

    def _level(self, block, now: int, state: dict) -> int:
        """升级：L1 先响，2 分钟仍离题到 L2，3 分钟到 L3（3.5）。"""
        first = int(state.get("first_ts", 0))
        if not first:
            return 1
        elapsed_min = (now - first) / 60.0
        e1, e2 = (self.j.get("escalate_after_minutes") or [2, 3])[:2]
        if elapsed_min >= float(e2):
            return 3
        if elapsed_min >= float(e1):
            return 2
        return 1

    # ---------------------------------------------------------------- 记录
    def note_alert(self, verdict: Verdict, now: int | None = None) -> None:
        if verdict.level <= 0:          # 没提醒就不该留记录
            return
        now = int(now or time.time())
        key = f"cooldown:{verdict.rule_id}"
        state = self.store.kv_get(key, {}) or {}
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if state.get("day") != today:
            state = {"day": today}
        state["last"] = now
        state.setdefault("first_ts", now)
        state["last_level"] = max(int(state.get("last_level", 0)), verdict.level)
        if verdict.level >= 3:
            state["l3_today"] = int(state.get("l3_today", 0)) + 1
        self.store.kv_set(key, state)
        self.store.add_intervention(verdict.level, verdict.rule_id, verdict.reason)
