# -*- coding: utf-8 -*-
"""批次调度：15 分钟一组，规则优先、模型兜底（设计方案 11.1 / 11.2）。"""
from __future__ import annotations

import time

from .. import config
from ..capture.store import day_of
from ..log import get
from . import aggregate, vlm
from .rules import RuleSet, describe

log = get("scheduler")

MAX_FRAMES = 6


class Scheduler:
    def __init__(self, cfg: dict, store, ruleset: RuleSet | None = None):
        self.cfg = cfg
        self.store = store
        self.rules = ruleset or RuleSet()
        base = int(cfg["analyze"].get("batch_minutes", 15)) * 60
        # 规则的批次窗口：没有配视觉模型时，分析是零成本的，按 1 分钟一批走，
        # 这样「今日概览」和日报不会因为等一个 15 分钟窗口而显示 0。
        # 一旦配了模型，就回到 design 里的 15 分钟一批（成本控制）。
        self.batch_sec = base if vlm.enabled(cfg) else min(60, base)

    # ---------------------------------------------------------------- 主循环
    def run(self, now: int | None = None) -> int:
        """把所有「已经攒够」的批次跑掉，返回处理数量。"""
        now = int(now or time.time())
        day = day_of(now)
        day_start, _ = self._bounds(day)
        anchor = self._anchor(day_start, now)

        done = 0
        guard = 0
        # 停机久了会有大量空窗口要追，按时间跨度放开上限，别一轮只追 96 个
        limit = max(96, int((now - anchor) / max(1, self.batch_sec)) + 2)
        while anchor + self.batch_sec <= now and guard < limit:
            guard += 1
            ws, we = anchor, anchor + self.batch_sec
            try:
                if self.process_window(ws, we):
                    done += 1
            except Exception as exc:                 # 单批失败不能拖垮线程
                log.exception("批次 %s-%s 处理失败：%s", ws, we, exc)
            anchor = we
        if done:
            self.rebuild(day)
        return done

    def _anchor(self, day_start: int, now: int) -> int:
        last = self.store.last_batch_end()
        if last > day_start:
            return last
        rows = self.store.samples(day_start, now)
        if rows:
            first = int(rows[0]["ts"])
            # 对齐到整批次，避免每次都从零散时间点切窗
            return first - (first - day_start) % self.batch_sec
        return now - self.batch_sec

    @staticmethod
    def _bounds(day: str) -> tuple[int, int]:
        import time as _t
        t = _t.strptime(day, "%Y-%m-%d")
        start = int(_t.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
        return start, start + 86400

    # ---------------------------------------------------------------- 单批
    def process_window(self, ws: int, we: int) -> bool:
        samples = self.store.samples(ws, we)
        if not samples:
            return False

        segs = self._rules_segments(samples)
        source = "rules"

        if self._should_use_vlm(samples):
            batch = self._build_batch(ws, we, samples)
            if batch and batch["frames"]:
                spend = float(self.store.kv_get(f"spend:{day_of(ws)}", 0) or 0)
                est = vlm.estimate_cost(self.cfg, len(batch["frames"]))
                budget = float(self.cfg["analyze"].get("daily_budget_cny", 2.0))
                if spend + est <= budget:
                    out, err = vlm.analyze(self.cfg, batch)
                    if out:
                        segs = out
                        source = "vlm"
                        self.store.kv_set(f"spend:{day_of(ws)}", round(spend + est, 4))
                    else:
                        log.warning("本批降级为规则结果：%s", err)
                else:
                    log.warning("今日预算已用完（%.2f/%.2f），本批只用规则", spend, budget)

        rows = [{**s, "source": source} for s in segs]
        self.store.insert_analysis(f"{ws}-{we}", rows)
        return True

    def _on_task(self, cat: str, ts: int):
        """没有目标声明就不判定 on_task（3.1：先有目标，才有摸鱼）。"""
        if not self.store.active_goal(ts):
            return None
        if cat in aggregate.PRODUCTIVE:
            return True
        if cat in aggregate.CONSUMING:
            return False
        return None

    def _should_use_vlm(self, samples: list) -> bool:
        if not vlm.enabled(self.cfg):
            return False
        if self.cfg["privacy"].get("mode") == "meta_only":
            return False
        known = 0
        for r in samples:
            if r["idle"] or r["sensitive"]:
                known += 1
                continue
            hit = self.rules.classify(r["proc"], r["title"])
            if hit.weight >= 0.9 and hit.category != "unknown":
                known += 1
        ratio = known / max(1, len(samples))
        # A 档覆盖率够高就别花钱；低于 75% 才升级到 B 档
        return ratio < 0.75

    def _rules_segments(self, samples: list) -> list[dict]:
        segs: list[dict] = []
        cur: dict | None = None
        for r in samples:
            ts = int(r["ts"])
            if r["idle"]:
                cur = self._close(segs, cur, ts)
                continue
            # 刚切窗口、标题还没稳定的采样：记了，但不参与分类（避免把上个页面的标题算进来）
            if "settled" in r.keys() and not r["settled"]:
                cur = self._close(segs, cur, ts)
                continue
            if r["sensitive"] or (r["title"] or "") == "<sensitive>":
                cat, act, conf = "unknown", "敏感窗口（不记录细节）", 1.0
                evidence = "敏感窗口，只记录时间，不记录内容。"
            else:
                hit = self.rules.classify(r["proc"], r["title"])
                cat, act, conf = hit.category, describe(hit, r["proc"]), hit.weight
                evidence = (f"进程 {r['proc']}，窗口「{(r['title'] or '')[:40]}」，"
                            f"命中规则 {hit.rule_id}（权重 {hit.weight:.2f}）")

            if cur and cur["category"] == cat:
                cur["end_ts"] = ts
                cur["confidence"] = min(cur["confidence"], conf)
                continue
            cur = self._close(segs, cur, ts)
            cur = {"start_ts": ts, "end_ts": ts, "category": cat,
                   "activity": act, "on_task": self._on_task(cat, ts),
                   "confidence": conf, "shot_ref": r["shot"],
                   "evidence": evidence}
            if r["shot"]:
                cur["shot_ref"] = r["shot"]

        if cur:
            cur["end_ts"] = max(cur["end_ts"], int(samples[-1]["ts"]))
            segs.append(cur)
        # 只有一条采样的段长度为零，按一个采样周期补齐，否则会被后续合并整段丢掉
        for s in segs:
            if s["end_ts"] <= s["start_ts"]:
                s["end_ts"] = s["start_ts"] + 60
        return segs

    @staticmethod
    def _close(segs: list, cur: dict | None, ts: int):
        if cur:
            cur["end_ts"] = max(cur["end_ts"], ts)
            segs.append(cur)
        return None

    def _build_batch(self, ws: int, we: int, samples: list) -> dict | None:
        timeline = [(int(r["ts"]), r["proc"], r["title"]) for r in samples]
        shots = [r for r in samples if r["shot"]]
        frames: list[str] = []
        if shots:
            step = max(1, len(shots) // MAX_FRAMES)
            frames = [shots[i]["shot"] for i in range(0, len(shots), step)][:MAX_FRAMES]

        # 用窗口末尾取目标：本批中途才声明目标时，也要让模型看到它
        goal = self.store.active_goal(we)
        prev = self._prev_summary(ws)
        return {
            "start_ts": ws, "end_ts": we, "timeline": timeline,
            "frames": frames, "goal": goal["text"] if goal else "",
            "prev": prev,
        }

    def _prev_summary(self, ws: int) -> str:
        rows = self.store.analyses(day_of(ws - 1))
        rows = [r for r in rows if int(r["end_ts"]) <= ws]
        if not rows:
            return ""
        last = rows[-1]
        return f"上一批结论：{last['activity']}（{aggregate.label(last['category'])}）"

    # ---------------------------------------------------------------- 聚合
    def rebuild(self, day: str) -> list[dict]:
        """把当天的 analysis 重新合并成 block（幂等，随时可重跑）。"""
        rows = self.store.analyses(day)
        segs = [{
            "start_ts": int(r["start_ts"]), "end_ts": int(r["end_ts"]),
            "category": r["category"], "activity": r["activity"],
            "on_task": r["on_task"], "confidence": float(r["confidence"] or 0),
            "shot_ref": None,
        } for r in rows]
        merged = aggregate.merge_segments(segs, gap=180, min_len=60)
        day_start, day_end = self._bounds(day)
        samples = self.store.samples(day_start, day_end)
        aggregate.attach_shots(merged, samples)
        blocks = aggregate.to_blocks(merged)
        # 空白处（idle 或采集断档）补灰段，不猜测，只标出来
        blocks = _fill_gaps(blocks, day_start, day_end)
        self.store.replace_blocks(day, blocks)
        return blocks


def _fill_gaps(blocks: list[dict], day_start: int, day_end: int) -> list[dict]:
    """时间轴上空掉的地方画灰段——「跳过空洞，不插值」（9.2）。"""
    if not blocks:
        return []
    out = []
    prev_end = None
    for b in blocks:
        if prev_end is not None and b["start_ts"] - prev_end > 600:
            out.append({"start_ts": prev_end, "end_ts": b["start_ts"],
                        "category": "gap", "activity": "未采集",
                        "on_task": None, "confidence": 0, "shot_ref": None})
        out.append(b)
        prev_end = b["end_ts"]
    return out
