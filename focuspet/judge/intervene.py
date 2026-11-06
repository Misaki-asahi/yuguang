# -*- coding: utf-8 -*-
"""分级干预与文案（设计方案 3.4 / 3.5 / 13.2，文案见附录 D）。"""
from __future__ import annotations

import random
import time

from ..analyze.aggregate import fmt_duration, label
from ..log import get

log = get("intervene")

# 文案是这个产品的人格：短、具体、不说教、给台阶
GENTLE = [
    "在忙别的吗？刚才那份文档还开着。",
    "说好的 {goal}，要不要再看一眼？",
    "已经离开 {mins} 分钟了，回来吧。",
    "我帮你记着时间呢，还剩 {left} 分钟。",
    "要不先喝口水，然后继续？",
    "刚刚切了 {n} 次窗口，试试只看一件事？",
    "这个好像不在今天的计划里。",
    "休息可以，说一声我就不吵了。",
]
TEASE = [
    "又见面了，这已经是今天第 {n} 次了。",
    "你和这边的缘分，好像比和目标的关系更近。",
    "这个内容看着真不错，可惜不是今天的任务。",
    "我什么都没说，我只是站在这里。",
    "再刷五分钟？上次的五分钟是 23 分钟。",
    "你的手速比你的专注力快多了。",
    "提醒一下，今天的目标还在原地等你。",
    "摸鱼可以，但别摸成习惯。",
]
SHARP = [
    "这是今天第 {n} 次了，我记着呢。",
    "现在这个时间，本来应该是 {task}。",
    "你可以选择继续，日报上会写清楚。",
    "顺手打开和有意打开，区别很大。",
    "今天的专注时长，还差 {x} 分钟到及格线。",
    "不是不让你玩，是不想你晚上后悔。",
    "我已经提醒过 {n} 次了，接下来交给你。",
    "关掉这个页面的成本，比晚上后悔低。",
]
REPLIES = {
    "back_to_work": "好，我盯着。",
    "rest": "行，{n} 分钟后见。",
    "legit": "明白了，这个记下来，下次不吵你。",
    "closed": "",
}

# 正向反馈：只提醒「你跑偏了」的话，用三周就被无视了。
# 这几条不占提醒配额、不冷却，一段够长的深度工作结束后说一次。
POSITIVE = [
    "专注 {n} 分钟了，这段挺扎实。",
    "已经连着干了 {n} 分钟，稳住。",
    "这一段没被打断，很好。",
    "{goal} 推进得不错，继续保持。",
    "又是 {n} 分钟的深度工作，今天的曲线好看。",
    "我什么都没做，只是站着看你干活。",
    "{n} 分钟，一口气干完的。",
    "这个节奏对，别急着换。",
]
PRAISE_MINUTES = 25       # 和「深度专注」的口径一致
PRAISE_DAILY_CAP = 6      # 一天最多夸 6 次，多了就成噪音


def pick_text(level: int, ctx: dict, rng: random.Random | None = None) -> str:
    pool = GENTLE if level <= 1 else (TEASE if level == 2 else SHARP)
    rng = rng or random
    line = rng.choice(pool)
    try:
        return line.format(**ctx)
    except (KeyError, IndexError):
        return line


class Intervener:
    """判定 → 选文案 → 记一笔 → 交给通知器（桌宠 / 托盘气泡）。"""

    def __init__(self, cfg: dict, store, judge, notifier=None):
        self.cfg = cfg
        self.store = store
        self.judge = judge
        self.notifier = notifier
        self.rng = random.Random()

    def check(self, block, now: int | None = None) -> dict | None:
        now = int(now or time.time())
        verdict = self.judge.evaluate(block, now)
        if verdict.level <= 0:
            return None

        goal = self.store.active_goal(now)
        ctx = {
            "goal": goal["text"] if goal else "今天的目标",
            "mins": max(1, int((now - int(block["start_ts"])) / 60)),
            "left": 25 - max(1, int((now - int(block["start_ts"])) / 60)) % 25,
            "n": self._count_today(now),
            "task": goal["text"] if goal else "手头这件事",
            "x": 25,
        }
        text = pick_text(verdict.level, ctx, self.rng)

        self.judge.note_alert(verdict, now)
        log.info("L%d 提醒：%s（%s，%s）", verdict.level, text,
                 verdict.rule_id, label(block["category"]))
        if self.notifier:
            try:
                self.notifier(verdict.level, text)
            except Exception:
                log.exception("通知器异常，已降级为静默记录")

        return {"level": verdict.level, "text": text,
                "category": block["category"], "activity": block.get("activity", ""),
                "duration": fmt_duration((int(block["end_ts"]) - int(block["start_ts"])) / 60.0)}

    def _count_today(self, now: int) -> int:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        return len(self.store.interventions(day))

    # ---------------------------------------------------------------- 正向反馈
    def praise(self, block, now: int | None = None) -> str | None:
        """一段够长的深度工作结束时夸一句。不占提醒配额、不走冷却。"""
        now = int(now or time.time())
        dur = (int(block["end_ts"]) - int(block["start_ts"])) / 60.0
        if dur < PRAISE_MINUTES:
            return None
        # 同一段只夸一次
        if int(self.store.kv_get("last_praise_ts", 0) or 0) >= int(block["start_ts"]):
            return None
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        key = f"praise:{day}"
        count = int(self.store.kv_get(key, 0) or 0)
        if count >= PRAISE_DAILY_CAP:
            return None

        goal = self.store.active_goal(now)
        ctx = {"n": int(dur), "goal": goal["text"] if goal else "手头这件事"}
        line = self.rng.choice(POSITIVE)
        try:
            text = line.format(**ctx)
        except (KeyError, IndexError):
            text = line

        self.store.kv_set("last_praise_ts", int(block["start_ts"]))
        self.store.kv_set(key, count + 1)
        log.info("正向反馈：%s", text)
        if self.notifier:
            try:
                self.notifier(0, text)
            except Exception:
                log.exception("通知器异常，已跳过正向反馈")
        return text

    # ---------------------------------------------------------------- 用户动作
    def respond(self, level: int, action: str, category: str = "",
                now: int | None = None) -> str:
        """用户点了什么，就回一句什么（附录 D.4），同时把状态写回去。"""
        now = int(now or time.time())
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        self.store.add_intervention(level, category, "user_action", action)

        if action == "rest":
            state = self.store.kv_get(f"cooldown:{category}", {}) or {}
            state["rest_until"] = now + int(self.cfg["judge"].get("rest_minutes", 10)) * 60
            self.store.kv_set(f"cooldown:{category}", state)
        elif action == "legit":
            exempt = self.store.kv_get(f"exempt:{today}", []) or []
            if category and category not in exempt:
                exempt.append(category)
            self.store.kv_set(f"exempt:{today}", exempt)

        return REPLIES.get(action, "").format(n=self.cfg["judge"].get("rest_minutes", 10))
