# -*- coding: utf-8 -*-
"""周报与月报（设计方案 12.5 的扩展）。

数据来源只有一张表：`block`（永久保留）。所以周报/月报不依赖 `sample` 明细，
清掉明细也不影响历史汇总。

一周的定义：周一到周日。月的定义：1 日到月末。
同一周/同一月重复生成只会覆盖同一个文件。
"""
from __future__ import annotations

import html
import os
import time
from datetime import date, timedelta
from pathlib import Path
from string import Template

from .. import config
from ..analyze import aggregate
from ..log import get
from .render import open_in_browser

log = get("summary")

TEMPLATE = Path(__file__).parent / "summary_template.html"

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


# ------------------------------------------------------------------ 区间
def week_range(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())          # 周一
    return start, start + timedelta(days=6)


def month_range(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def is_last_day_of_month(day: date) -> bool:
    return (day + timedelta(days=1)).month != day.month


def week_key(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def period_targets(today: date, now_dt, cfg: dict) -> tuple[date, date]:
    """最近一个「已经到点」的周报日和月报日。

    周日 21:00 没开机，周一早上也该把上周补出来——所以不判「今天是不是周日」，
    而是找最近一个已经过去的触发点。
    """
    from datetime import datetime as _dt

    wd = int(cfg.get("weekly_day", 6))
    # 周报/月报跟着日报一起出：时间用 report.time 这一个口径
    wh, wm = _hm(cfg.get("time", "22:00"))
    weekly_day = today - timedelta(days=(today.weekday() - wd) % 7)
    if _dt.combine(weekly_day, _time(wh, wm)) > now_dt:
        weekly_day -= timedelta(days=7)

    mh, mm = _hm(cfg.get("time", "22:00"))
    start_m, end_m = month_range(today)
    if _dt.combine(end_m, _time(mh, mm)) <= now_dt:
        monthly_day = end_m
    else:
        monthly_day = month_range(start_m - timedelta(days=1))[1]
    return weekly_day, monthly_day


def _hm(text: str) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in str(text).split(":")[:2])
        return hh, mm
    except Exception:
        return 21, 0


def _time(hh: int, mm: int):
    from datetime import time as _t
    return _t(hh, mm)


# ------------------------------------------------------------------ 汇总
def _metrics_for(store, day: date) -> dict:
    blocks = [dict(b) for b in store.blocks(day.isoformat())]
    return aggregate.metrics(blocks), bool(blocks)


def collect(store, start: date, end: date) -> dict:
    days = []
    d = start
    while d <= end:
        m, has = _metrics_for(store, d)
        days.append({"date": d, "metrics": m, "has": has})
        d += timedelta(days=1)

    def total(key: str) -> float:
        return round(sum(x["metrics"][key] for x in days), 1)

    total_min = total("total_minutes")
    productive = total("productive_minutes")
    focus = total("focus_minutes")
    cons = total("consumption_minutes")
    switches = int(sum(x["metrics"]["switches"] for x in days))
    active = [x for x in days if x["has"]]

    by_cat: dict[str, float] = {}
    for x in days:
        for c, v in x["metrics"]["by_category"].items():
            by_cat[c] = round(by_cat.get(c, 0.0) + v, 1)

    # 上一个等长周期，用于对比
    span = (end - start).days + 1
    p_end = start - timedelta(days=1)
    p_start = p_end - timedelta(days=span - 1)
    prev_focus = 0.0
    d = p_start
    while d <= p_end:
        m, _ = _metrics_for(store, d)
        prev_focus += m["focus_minutes"]
        d += timedelta(days=1)

    best = max(active, key=lambda x: x["metrics"]["focus_minutes"], default=None)
    worst = max(active, key=lambda x: x["metrics"]["consumption_minutes"], default=None)

    elapsed = sum(1 for x in days if x["date"] <= date.today())
    return {
        "start": start, "end": end, "days": days, "active_days": len(active),
        "elapsed_days": elapsed,
        "focus": focus, "consumption": cons, "productive": productive,
        "total": total_min, "switches": switches,
        "ratio": (productive / total_min) if total_min else 0.0,
        "daily_focus": (focus / len(active)) if active else 0.0,
        "by_category": by_cat,
        "prev_focus": round(prev_focus, 1),
        "best": best, "worst": worst,
    }


# ------------------------------------------------------------------ 文案
def _cmp_text(cur: float, prev: float, unit: str) -> str:
    if prev <= 0:
        return f"上一次没有可比数据"
    diff = cur - prev
    if abs(diff) < 10:
        return f"和{unit}基本持平"
    return f"比{unit}{'多' if diff > 0 else '少'} {aggregate.fmt_duration(abs(diff))}"


def summary_line(data: dict, unit: str) -> str:
    return f"这段时间专注 {aggregate.fmt_duration(data['focus'])}，{_cmp_text(data['focus'], data['prev_focus'], unit)}。"


def suggestion(data: dict) -> str:
    days = max(1, data["active_days"])
    if data["ratio"] < 0.4:
        return "下个周期先把每天开工的第一件事写下来——有效比低通常不是不够努力，是目标一直在换。"
    if data["switches"] / days > 50:
        return "把每天最常切进去的两个网站限时，切换次数能掉三分之一，比延长工作时间管用。"
    if data["consumption"] / max(1.0, data["total"]) > 0.25:
        return "消耗占比超过四分之一了，先砍掉最固定的那一段（多半在晚上），别全面开花。"
    return "这个节奏可以保持，下个周期只盯一件事：每天第一段深度工作别晚于开工后一小时。"


# ------------------------------------------------------------------ 渲染
def _cards(data: dict, kind: str) -> str:
    per_day = aggregate.fmt_duration(data["daily_focus"])
    items = [
        (aggregate.fmt_duration(data["focus"]), "总专注", f"日均 {per_day}"),
        (aggregate.fmt_duration(data["consumption"]), "总消耗", "娱乐 + 无目的浏览"),
        (f"{data['ratio'] * 100:.0f}%", "有效比", "生产性 ÷ 在电脑前"),
        (f"{data['switches']} 次", "切换", f"日均 {data['switches'] / max(1, data['active_days']):.0f} 次"),
        (f"{data['active_days']} 天", "有记录", f"共 {data['elapsed_days']} 天"),
    ]
    return "\n".join(
        f'<div class="card"><b>{_esc(v)}</b><span>{_esc(k)}</span>'
        f'<small>{_esc(s)}</small></div>' for v, k, s in items)


def _chart(data: dict, kind: str) -> str:
    peak = max((x["metrics"]["focus_minutes"] + x["metrics"]["consumption_minutes"]
                for x in data["days"]), default=0) or 1.0
    cols = []
    for x in data["days"]:
        m = x["metrics"]
        f = m["focus_minutes"]
        c = m["consumption_minutes"]
        fh = f / peak * 100
        ch = c / peak * 100
        label = WEEKDAY_CN[x["date"].weekday()] if kind == "weekly" else str(x["date"].day)
        cls = "col" + ("" if x["has"] else " empty")
        tip = (f'{x["date"].strftime("%m-%d")} 专注 {aggregate.fmt_duration(f)}，'
               f'消耗 {aggregate.fmt_duration(c)}')
        cols.append(
            f'<div class="{cls}" title="{_esc(tip)}">'
            f'<div class="bar">'
            f'<div class="seg focus" style="height:{fh:.1f}%"></div>'
            f'<div class="seg cons" style="height:{ch:.1f}%"></div>'
            f'</div><div class="lbl">{label}</div></div>')
    return "\n".join(cols)


def _categories(data: dict) -> str:
    rows = sorted(((c, v) for c, v in data["by_category"].items() if v > 0),
                  key=lambda kv: -kv[1])
    if not rows:
        return '<p class="muted">这个周期还没有数据。</p>'
    peak = rows[0][1] or 1
    out = []
    for cat, minutes in rows:
        width = minutes / peak * 100
        out.append(
            f'<div class="cat"><span class="name">{aggregate.label(cat)}</span>'
            f'<span class="track"><i style="width:{width:.1f}%;background:{aggregate.color(cat)}"></i></span>'
            f'<span class="val">{aggregate.fmt_duration(minutes)}</span></div>')
    return "\n".join(out)


def _table(data: dict, kind: str) -> str:
    rows = []
    today = date.today()
    for x in data["days"]:
        m = x["metrics"]
        d = x["date"]
        label = f'{d.strftime("%m-%d")}　周{WEEKDAY_CN[d.weekday()]}'
        if d > today:                     # 还没到的日子不列，免得看着像"零产出"
            continue
        if kind == "monthly" and not x["has"]:
            continue
        rows.append(
            f'<tr><td>{label}</td><td>{aggregate.fmt_duration(m["focus_minutes"])}</td>'
            f'<td>{aggregate.fmt_duration(m["consumption_minutes"])}</td>'
            f'<td>{m["switches"]}</td><td>{m["effective_ratio"] * 100:.0f}%</td></tr>')
    if not rows:
        return '<p class="muted">这个周期还没有数据。</p>'
    return ('<table><thead><tr><th>日期</th><th>专注</th><th>消耗</th>'
            '<th>切换</th><th>有效比</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def render_period(cfg: dict, store, kind: str = "weekly", today: date | None = None,
                  open_browser: bool | None = None) -> Path:
    """kind: weekly | monthly。同周期重复生成会覆盖同一个文件。"""
    today = today or date.today()
    if kind == "weekly":
        start, end = week_range(today)
        name = f"weekly-{week_key(today)}.html"
        title_cn = f"{start.strftime('%Y 年 %m 月 %d 日')} — {end.strftime('%m 月 %d 日')}"
        period_cn = "本周"
        unit = "上周"
    else:
        start, end = month_range(today)
        name = f"monthly-{month_key(today)}.html"
        title_cn = f"{start.strftime('%Y 年 %m 月')}"
        period_cn = "本月"
        unit = "上个月"

    data = collect(store, start, end)
    best = data["best"]
    best_text = ""
    if best:
        best_text = (f'最专注的一天是 {best["date"].strftime("%m-%d")}，'
                     f'{aggregate.fmt_duration(best["metrics"]["focus_minutes"])}。')
    worst = data["worst"]
    if worst and worst["metrics"]["consumption_minutes"] > 0:
        best_text += (f' 消耗最多的是 {worst["date"].strftime("%m-%d")}，'
                      f'{aggregate.fmt_duration(worst["metrics"]["consumption_minutes"])}。')

    tpl = Template(TEMPLATE.read_text(encoding="utf-8"))
    out = tpl.safe_substitute(
        title=f"余光 · {period_cn}汇总",
        period=period_cn,
        range=title_cn,
        summary=_esc(summary_line(data, unit)),
        sub=_esc(best_text or "这个周期还没有可对比的数据。"),
        cards=_cards(data, kind),
        chart=_chart(data, kind),
        categories=_categories(data),
        table=_table(data, kind),
        suggestion=_esc(suggestion(data)),
        version=_esc(cfg["app"].get("version", "0.2.0")),
        footer_right=f"生成于 {time.strftime('%Y-%m-%d %H:%M')}",
    )

    folder = Path(config.REPORTS)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    tmp = folder / f".{name}.tmp"
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
    log.info("汇总已生成：%s（%s → %s）", path, start, end)

    if open_browser is None:
        open_browser = bool(cfg["report"].get("open_browser", True))
    if open_browser:
        open_in_browser(path, cfg)
    return path
