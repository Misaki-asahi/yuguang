# -*- coding: utf-8 -*-
"""批次调度：15 分钟一组，规则优先、模型兜底（设计方案 11.1 / 11.2）。"""
from __future__ import annotations

import time

from .. import config, goalkind
from ..capture.store import day_of
from ..log import get
from . import aggregate, vlm
from .rules import RuleSet, describe

log = get("scheduler")

MAX_FRAMES = 6


def _hm(ts: int) -> str:
    return time.strftime("%H:%M", time.localtime(int(ts)))


def _in_ranges(ts: int, ranges: list[dict]) -> bool:
    return any(int(r["start_ts"]) <= ts < int(r["end_ts"]) for r in ranges)


def _unknown_minutes(rows: list) -> float:
    """一批分析行里「unknown」占多少分钟——补洞前后比这个，比数段数靠谱。"""
    return sum(int(r["end_ts"]) - int(r["start_ts"])
               for r in rows if r["category"] == "unknown") / 60.0


def _overlap(seg: dict, block: dict) -> int:
    return max(0, min(int(seg["end_ts"]), int(block["end_ts"]))
               - max(int(seg["start_ts"]), int(block["start_ts"])))


def _overlap_ratio(seg: dict, block: dict) -> float:
    dur = max(1, int(block["end_ts"]) - int(block["start_ts"]))
    return _overlap(seg, block) / dur


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
        for s in segs:
            s["source"] = "rules"

        # 只把「规则认不出来」的段交给模型：按段升级，不是整批重算。
        # 规则已经认对的段原样保留，模型只负责填洞。
        if self._vlm_allowed():
            holes = [s for s in segs if s["category"] == "unknown"]
            if holes:
                sub = [r for r in samples if _in_ranges(int(r["ts"]), holes)]
                batch = self._build_batch(ws, we, sub, focus=holes)
                if batch and batch["frames"]:
                    spend = float(self.store.kv_get(f"spend:{day_of(ws)}", 0) or 0)
                    est = vlm.estimate_cost(self.cfg, len(batch["frames"]))
                    budget = float(self.cfg["analyze"].get("daily_budget_cny", 2.0))
                    if spend + est <= budget:
                        out, err = vlm.analyze(self.cfg, batch)
                        if out:
                            segs = self._fill_holes(segs, out)
                            try:
                                self._record_unknowns(out, samples)
                            except Exception:
                                log.debug("记录未知段失败", exc_info=True)
                            self.store.kv_set(f"spend:{day_of(ws)}",
                                              round(spend + est, 4))
                        else:
                            log.warning("补未知段失败，本批保留规则结果：%s", err)
                    else:
                        log.warning("今日预算已用完（%.2f/%.2f），本批只用规则", spend, budget)

        self.store.insert_analysis(f"{ws}-{we}", segs)
        return True

    # ---------------------------------------------------------------- 补洞
    def fill_unknowns(self, hours: int = 2, max_attempts: int = 3,
                      force: bool = False) -> int:
        """把最近 hours 小时里仍是 unknown 的窗口重跑一遍（会再调一次模型）。

        为什么要重试：批次里网络抖一下、模型答非所问一次，那个洞就永久留着了。
        每个窗口最多试 max_attempts 次（记在 kv 表），避免反复烧调用；
        force=True 给手动 `--fill-unknown` 用，不受次数限制。
        """
        if not self._vlm_allowed():
            return 0

        now = int(time.time())
        day = day_of(now)
        day_start, _ = self._bounds(day)
        since = now - max(1, int(hours)) * 3600
        # 只碰已经结束、且落在重试窗口内的未知段；正在跑的那一批不动
        unknown = [b for b in self.store.blocks(day)
                   if b["category"] == "unknown"
                   and since <= int(b["end_ts"]) <= now - self.batch_sec]
        if not unknown:
            return 0

        windows = sorted({
            day_start + ((int(b["start_ts"]) - day_start) // self.batch_sec) * self.batch_sec
            for b in unknown
        })
        done = 0
        for ws in windows:
            we = ws + self.batch_sec
            key = f"filltry:{ws}"
            tries = int(self.store.kv_get(key, 0) or 0)
            if not force and tries >= max_attempts:
                continue
            # 先留一份旧的：重跑如果没变好（unknown 没减少），就回滚，
            # 不能因为这次模型又抽风，把上次补对的结果冲掉
            before = self.store.analysis_window(ws, we)
            before_unknown = _unknown_minutes(before)
            self.store.kv_set(key, tries + 1)
            self.store._exec(
                "DELETE FROM analysis WHERE start_ts >= ? AND start_ts < ?", (ws, we))
            if not self.process_window(ws, we):
                continue
            after = self.store.analysis_window(ws, we)
            after_unknown = _unknown_minutes(after)
            if before and after_unknown >= before_unknown:
                self.store.restore_analysis(ws, we, before)
                log.info("补洞没变好（unknown %.0f→%.0f 分钟），保留原结果",
                         before_unknown, after_unknown)
                continue
            done += 1

        if done:
            self.rebuild(day)
            log.info("补洞：重跑 %d 个窗口（最近 %d 小时）", done, hours)
        return done

    # ---------------------------------------------------------------- 复核
    def review_low_confidence(self, day: str, limit: int = 12) -> int:
        """把今天低置信度（<0.6）的段送模型重判，有把握就改。

        只影响统计与日报——已经弹过的提醒不会因此回头改。
        unknown 不在这里处理，那是 fill_unknowns 的活。
        """
        if not self._vlm_allowed():
            return 0
        rows = [dict(b) for b in self.store.blocks(day)
                if b["category"] not in ("gap", "unknown")
                and float(b["confidence"] or 0) < 0.6]
        changed = 0
        for b in rows[:max(1, int(limit))]:
            samples = self.store.samples(b["start_ts"], b["end_ts"])
            if not samples:
                continue
            batch = self._build_batch(b["start_ts"], b["end_ts"], samples)
            if not batch or not batch["frames"]:
                continue
            out, err = vlm.analyze(self.cfg, batch)
            if not out:
                log.debug("复核失败（%s），跳过", err)
                continue
            best = max(out, key=lambda s: _overlap(s, b))
            if _overlap_ratio(best, b) < 0.5 or float(best["confidence"]) < 0.7:
                continue
            if best["category"] == b["category"]:
                continue
            # 不让模型把「工作/学习」降级成「生活/系统」：那两个类别信息量最低，
            # 模型看不清截图时就爱填它们，会把好好的工作段吃掉（实测踩过）
            if b["category"] in ("deep_work", "shallow_work", "learning") \
                    and best["category"] in ("life", "system"):
                log.debug("复核忽略降级：%s → %s", b["category"], best["category"])
                continue
            self.store.set_block_category(b["id"], best["category"])
            self.store._exec(
                "INSERT INTO vlm_review(day, block_id, old_cat, new_cat, confidence, ts)"
                " VALUES(?,?,?,?,?,?)",
                (day, b["id"], b["category"], best["category"],
                 float(best["confidence"]), int(time.time())))
            changed += 1
            time.sleep(1.2)             # 别把免费额度打满
        if changed:
            log.info("低置信度复核：改了 %d 段", changed)
        return changed

    def inspect_rules(self, day: str, samples: int = 3) -> int:
        """抽几段「规则很自信」的段让模型复核，冲突只记录、不自动改。"""
        if not self._vlm_allowed():
            return 0
        rows = [dict(b) for b in self.store.blocks(day)
                if b["category"] not in ("gap", "unknown")
                and float(b["confidence"] or 0) >= 0.9]
        if not rows:
            return 0
        step = max(1, len(rows) // max(1, int(samples)))
        picked = rows[::step][:max(1, int(samples))]
        found = 0
        for b in picked:
            segs = self.store.samples(b["start_ts"], b["end_ts"])
            if not segs:
                continue
            batch = self._build_batch(b["start_ts"], b["end_ts"], segs)
            if not batch or not batch["frames"]:
                continue
            out, err = vlm.analyze(self.cfg, batch)
            if not out:
                continue
            best = max(out, key=lambda s: _overlap(s, b))
            if _overlap_ratio(best, b) < 0.5 or float(best["confidence"]) < 0.8:
                continue
            if best["category"] == b["category"]:
                continue
            proc, title, _ = self.store.dominant_window(b["start_ts"], b["end_ts"])
            self.store._exec(
                "INSERT INTO rule_conflict(day, block_id, rule_cat, model_cat, proc, title,"
                " confidence, ts) VALUES(?,?,?,?,?,?,?,?)",
                (day, b["id"], b["category"], best["category"], proc, title,
                 float(best["confidence"]), int(time.time())))
            found += 1
            time.sleep(1.2)
        if found:
            log.info("规则巡检：发现 %d 处规则与模型结论不一致", found)
        return found

    # ---------------------------------------------------------------- 目标匹配
    def match_goal(self, day: str) -> int:
        """让模型按「今天的目标」重新判断各时间块的 on_task。

        规则模式的 on_task 是按类别推断的，读不懂语义；这一步用纯文本补上。
        只改统计口径，不影响已经发生的提醒。
        """
        if not self._vlm_allowed():
            return 0
        from datetime import datetime
        goal = self.store.goal_of_day(day)
        if not goal:
            log.info("目标匹配跳过：当天没有声明目标")
            return 0
        blocks = [dict(b) for b in self.store.blocks(day) if b["category"] != "gap"]
        if not blocks:
            return 0
        # 一次只发十几块：免费模型的 max_tokens=1024，块多了 JSON 会被截断
        chunk = max(4, int(self.cfg["analyze"].get("goal_chunk", 12)))
        n = 0
        for i in range(0, len(blocks), chunk):
            part = blocks[i:i + chunk]
            out, err = vlm.match_goal(self.cfg, day, goal["text"], part)
            if not out:
                continue
            for s in out:
                n += self.store.set_block_on_task(s["start_ts"], s["end_ts"], s["on_task"])
            time.sleep(1.0)
        if n:
            log.info("目标匹配：更新 %d 个时间块的 on_task", n)
        return n

    # ---------------------------------------------------------------- 段级合并
    @staticmethod
    def _fill_holes(segs: list[dict], out: list[dict]) -> list[dict]:
        """把模型段填进 unknown 段覆盖的时间里，其余规则段原样保留。

        模型可能返回跨出未知窗口的段，这里按未知窗口裁剪；没被模型覆盖到的
        残余时间仍然算 unknown，绝不让模型替我们把已知段改写掉。
        """
        filled: list[dict] = []
        for s in segs:
            if s["category"] != "unknown":
                filled.append(s)
                continue
            covered = sorted((m for m in out
                              if m["end_ts"] > s["start_ts"] and m["start_ts"] < s["end_ts"]),
                             key=lambda x: x["start_ts"])
            if not covered:
                filled.append(s)
                continue
            cursor = s["start_ts"]
            for m in covered:
                ms = max(m["start_ts"], s["start_ts"])
                me = min(m["end_ts"], s["end_ts"])
                if ms >= me:
                    continue
                if ms > cursor:
                    filled.append({**s, "start_ts": cursor, "end_ts": ms})
                filled.append({**m, "start_ts": ms, "end_ts": me, "source": "vlm"})
                cursor = max(cursor, me)
            if cursor < s["end_ts"]:
                filled.append({**s, "start_ts": cursor, "end_ts": s["end_ts"]})
        filled.sort(key=lambda x: x["start_ts"])
        return filled

    def _record_unknowns(self, out: list[dict], samples: list) -> None:
        """把模型对这些未知窗口的判断落库，`--suggest-rules` 用它归纳候选规则。"""
        rows = []
        for s in out:
            inside = [r for r in samples
                      if s["start_ts"] <= int(r["ts"]) < s["end_ts"]
                      and not r["idle"] and (r["proc"] or "")]
            if not inside:
                continue
            counter: dict[tuple[str, str], int] = {}
            for r in inside:
                key = ((r["proc"] or "").lower(), (r["title"] or "")[:80])
                counter[key] = counter.get(key, 0) + 1
            (proc, title) = max(counter, key=counter.get)
            rows.append({"ts": s["start_ts"], "proc": proc, "title": title,
                         "category": s["category"], "confidence": s["confidence"],
                         "activity": s.get("activity", "")})
        self.store.record_vlm_unknown(rows)

    def _on_task(self, cat: str, ts: int):
        """没有目标声明就不判定 on_task（3.1：先有目标，才有摸鱼）。

        目标类型（工作/学习/休闲/生活）决定消耗类算不算在任务上：
        目标是「看课程视频」时，娱乐类也是任务内的事。
        """
        goal = self.store.active_goal(ts)
        if not goal:
            return None
        if cat not in aggregate.PRODUCTIVE and cat not in aggregate.CONSUMING:
            return None                     # system / unknown 不参与判定
        kind = goal["kind"] if "kind" in goal.keys() else "auto"
        return goalkind.allows(kind, goal["text"], cat)

    def _vlm_allowed(self) -> bool:
        """能不能调模型：没配模型、或隐私档是「只发元数据」时都不调。"""
        if not vlm.enabled(self.cfg):
            return False
        return self.cfg["privacy"].get("mode") != "meta_only"

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

    def _build_batch(self, ws: int, we: int, samples: list,
                     focus: list[dict] | None = None) -> dict | None:
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
            "focus": "、".join(f"{_hm(s['start_ts'])}-{_hm(s['end_ts'])}" for s in focus)
                     if focus else "",
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
