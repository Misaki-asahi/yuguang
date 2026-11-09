# -*- coding: utf-8 -*-
"""段合并、时间块与指标（设计方案 12.2 / 12.3 / 12.4）。

这里不调用任何模型，纯本地计算——聚合层只负责「合并与计算」。
"""
from __future__ import annotations

# 一级分类：用于统计，颜色用于时间轴（12.1）
CATEGORIES = {
    "deep_work":     {"label": "深度工作", "color": "#1F4E79"},
    "shallow_work":  {"label": "浅层工作", "color": "#3B7EA1"},
    "learning":      {"label": "学习",     "color": "#2A9D8F"},
    "entertainment": {"label": "娱乐",     "color": "#E07A28"},
    "aimless":       {"label": "无目的浏览", "color": "#F0A868"},
    "life":          {"label": "生活",     "color": "#8FA88B"},
    "system":        {"label": "系统",     "color": "#C9D2DB"},
    "unknown":       {"label": "未识别",   "color": "#9AA5B1"},
    "gap":           {"label": "未采集",   "color": "#E3E7EC"},
}
PRODUCTIVE = {"deep_work", "shallow_work", "learning"}
CONSUMING = {"entertainment", "aimless"}
# 空白不是「不知道」，是「没数据」：不参与任何比例，只画在时间轴上
EXCLUDED = {"gap"}


def label(cat: str) -> str:
    return CATEGORIES.get(cat, CATEGORIES["unknown"])["label"]


def color(cat: str) -> str:
    return CATEGORIES.get(cat, CATEGORIES["unknown"])["color"]


def same_kind(a: dict, b: dict) -> bool:
    """同类判定：deep_work 与 learning 视为同一件事的两面（查资料写代码）。"""
    if a["category"] == b["category"]:
        return True
    return a["category"] in ("deep_work", "learning") and b["category"] in ("deep_work", "learning")


def _dur(s: dict) -> int:
    return int(s["end_ts"]) - int(s["start_ts"])


def merge_segments(segments: list[dict], gap: int = 180, min_len: int = 60) -> list[dict]:
    """相邻同类且间隔 < gap 秒则合并；合并后短于 min_len 的孤立段并入邻居。"""
    if not segments:
        return []
    items = sorted((dict(s) for s in segments), key=lambda x: x["start_ts"])

    out: list[dict] = []
    for s in items:
        if out and same_kind(out[-1], s) and s["start_ts"] - out[-1]["end_ts"] <= gap:
            last = out[-1]
            last["end_ts"] = max(last["end_ts"], s["end_ts"])
            last["confidence"] = min(float(last.get("confidence") or 0),
                                     float(s.get("confidence") or 0))
            if _dur(s) > _dur(last) and s.get("activity"):
                last["activity"] = s["activity"]
            if not last.get("shot_ref"):
                last["shot_ref"] = s.get("shot_ref")
        else:
            out.append(dict(s))

    # 二次清理：时间轴上画不出来的碎段并进邻居
    i = 0
    while i < len(out):
        s = out[i]
        if _dur(s) >= min_len or len(out) == 1:
            i += 1
            continue
        prev = out[i - 1] if i > 0 else None
        nxt = out[i + 1] if i + 1 < len(out) else None
        if prev is None and nxt is None:
            i += 1
            continue

        pick_prev = None
        if prev and nxt:
            pick_prev = same_kind(prev, s) or (
                not same_kind(nxt, s)
                and abs(_dur(prev) - _dur(s)) <= abs(_dur(nxt) - _dur(s))
            )
        elif prev:
            pick_prev = True
        else:
            pick_prev = False

        if pick_prev:
            prev["end_ts"] = max(prev["end_ts"], s["end_ts"])
            prev["confidence"] = min(float(prev.get("confidence") or 0),
                                     float(s.get("confidence") or 0))
        else:
            nxt["start_ts"] = min(nxt["start_ts"], s["start_ts"])
            nxt["confidence"] = min(float(nxt.get("confidence") or 0),
                                    float(s.get("confidence") or 0))
            if not nxt.get("shot_ref"):
                nxt["shot_ref"] = s.get("shot_ref")
        out.pop(i)
        i = max(0, i - 1)
    return out


def attach_shots(segments: list[dict], samples: list) -> list[dict]:
    """给每个块挂一张代表性截图，供日报回看证据（7.1 的第 2 条要求）。"""
    shots = [(int(r["ts"]), r["shot"]) for r in samples if r["shot"]]
    for seg in segments:
        if seg.get("shot_ref") or not shots:
            continue
        mid = (int(seg["start_ts"]) + int(seg["end_ts"])) // 2
        best = min(shots, key=lambda x: abs(x[0] - mid))
        seg["shot_ref"] = best[1]
    return segments


def to_blocks(segments: list[dict]) -> list[dict]:
    """规范成 block 表字段。"""
    blocks = []
    for s in segments:
        if _dur(s) <= 0:
            continue
        blocks.append({
            "start_ts": int(s["start_ts"]),
            "end_ts": int(s["end_ts"]),
            "category": s["category"],
            "activity": s.get("activity", ""),
            "on_task": s.get("on_task"),
            "confidence": float(s.get("confidence") or 0),
            "shot_ref": s.get("shot_ref"),
        })
    return blocks


def metrics(blocks: list[dict], idle_minutes: float = 0.0) -> dict:
    real = [b for b in blocks if b["category"] not in EXCLUDED]
    total = sum(_dur(b) for b in real) / 60.0
    by_cat: dict[str, float] = {}
    for b in real:
        by_cat[b["category"]] = by_cat.get(b["category"], 0.0) + _dur(b) / 60.0

    productive = sum(by_cat.get(c, 0.0) for c in PRODUCTIVE)
    consumption = sum(by_cat.get(c, 0.0) for c in CONSUMING)

    # 专注：连续 on_task 且 ≥ 25 分钟的 deep_work 段（25 分钟是进入状态的经验下限）
    focus = sum(_dur(b) / 60.0 for b in real
                if b["category"] == "deep_work" and b.get("on_task")
                and _dur(b) >= 25 * 60)

    switches = sum(1 for a, b in zip(real, real[1:]) if a["category"] != b["category"])
    # 空白段（idle / 断档）已经在 real 之外，所以这里不再二次扣减 idle
    awake = total
    ratio = (productive / awake) if awake > 0 else 0.0

    # 当天到底有没有「参照物」：on_task 全为空说明一次判定都没发生（没声明过目标）。
    # 这时候 focus=0 不是「没专注」，而是「没法统计」——展示层必须区分这两件事。
    goal_tracked = any(b.get("on_task") is not None for b in real)

    return {
        "total_minutes": round(total, 1),
        "idle_minutes": round(idle_minutes, 1),
        "awake_minutes": round(awake, 1),
        "focus_minutes": round(focus, 1),
        "deep_minutes": round(by_cat.get("deep_work", 0.0), 1),
        "goal_tracked": goal_tracked,
        "productive_minutes": round(productive, 1),
        "consumption_minutes": round(consumption, 1),
        "switches": switches,
        "effective_ratio": round(ratio, 3),
        "by_category": {k: round(v, 1) for k, v in by_cat.items()},
        "block_count": len(blocks),
    }


def fmt_duration(minutes: float) -> str:
    m = int(round(minutes))
    if m <= 0:
        return "0 分钟"
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h} 小时 {mm} 分"
    if h:
        return f"{h} 小时"
    return f"{mm} 分钟"


def summary_line(m: dict, prev_focus: float | None = None, last_goal: str = "") -> str:
    """一句话结论（12.4）：陈述事实，不评价人格，不做比较级。

    没声明目标时不说「专注 0 分钟」——那是误导，会让人以为当天没干活。
    改成「专注未统计」，并把深度工作的时长如实报出来。
    """
    if not m.get("goal_tracked", True):
        line = (f"今天未声明目标，专注未统计"
                f"（深度工作 {fmt_duration(m.get('deep_minutes', 0))}）")
        if last_goal:
            line += f"　[沿用上次：{last_goal}]"
        return line

    focus = m["focus_minutes"]
    if focus <= 0 and m.get("deep_minutes", 0) > 0:
        # 有深度工作、却一段都没到 25 分钟：说清楚是「被打碎了」，不是「没干活」
        return (f"今天专注 0 分钟——有 {fmt_duration(m['deep_minutes'])}的深度工作，"
                f"但没有一段连续 25 分钟以上。")
    if focus >= 180:
        tail = ""
        if prev_focus is not None:
            delta = int(round(focus - prev_focus))
            tail = f"，比昨天多 {delta} 分钟" if delta > 0 else ""
        return f"今天专注 {fmt_duration(focus)}{tail or '，节奏完整'}。"
    if focus >= 60:
        return f"今天专注 {fmt_duration(focus)}，被切了 {m['switches']} 次。"
    return f"今天专注 {fmt_duration(focus)}，大段时间没有进入状态。"


def suggestion(m: dict) -> str:
    """只给一条建议，且必须是具体动作（12.4 的第 3 条纪律）。"""
    if m["switches"] >= 60:
        return "明天开工时把浏览器标签关到 5 个以内——今天一半的切换都从那里来。"
    if m["consumption_minutes"] >= 90:
        return "明天把手机放到手够不到的地方，先把今天丢掉的那段时间拿回来。"
    if m["focus_minutes"] >= 180:
        return "明天还是这个时段开工，别改——能连续两天比什么都强。"
    if m["focus_minutes"] >= 60:
        return "明天上午先只写一条目标，写完再开浏览器。"
    return "明天开工前先声明目标，哪怕只有一句话，判定才有参照物。"
