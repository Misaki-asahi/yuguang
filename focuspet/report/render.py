# -*- coding: utf-8 -*-
"""把当天的 block 渲染成一张单文件 HTML 账单（设计方案 7.1 / 12.5）。

三条设计要求写死在这里：
  1. 一句话结论放最上面，不看图也知道今天怎么样；
  2. 每个数字都能点开看证据；
  3. 只给一条建议，且必须是具体动作。
只用 HTML + CSS，不引任何前端框架——十年后还能直接双击打开。
"""
from __future__ import annotations

import html
import os
import subprocess
import time
from pathlib import Path
from string import Template

from .. import config
from ..analyze import aggregate
from ..capture.store import day_of
from ..log import get

log = get("report")

TEMPLATE = Path(__file__).parent / "template.html"


def _hm(ts: int) -> str:
    return time.strftime("%H:%M", time.localtime(int(ts)))


# ---------------------------------------------------------------- 用浏览器打开
# 不能用 os.startfile：.html 的默认关联很可能是编辑器（这台机器就是 VSCode），
# 那样「打开日报」会变成在编辑器里看源码。必须显式点名浏览器。
_BROWSER_CANDIDATES = [
    ("ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe"),
    ("ProgramFiles", "Microsoft/Edge/Application/msedge.exe"),
    ("ProgramFiles", "Google/Chrome/Application/chrome.exe"),
    ("ProgramFiles(x86)", "Google/Chrome/Application/chrome.exe"),
    ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    ("ProgramFiles", "Mozilla Firefox/firefox.exe"),
]


def find_browser() -> str | None:
    """按常见安装路径找浏览器；配置里指定了就用配置的。"""
    env = os.environ.get("FOCUSPET_BROWSER", "").strip()
    if env and Path(env).exists():
        return env
    for var, rel in _BROWSER_CANDIDATES:
        base = os.environ.get(var, "")
        if not base:
            continue
        p = Path(base) / rel
        if p.exists():
            return str(p)
    return None


def open_in_browser(path: Path | str, cfg: dict | None = None) -> bool:
    """在浏览器里打开日报。

    返回的是「真的送到了」而不只是「我调用过了」——浏览器启动器在某些环境里
    会立刻退出（返回码非 0），以前一律返回 True，界面就会骗人说「已打开」。
    """
    path = Path(path)
    configured = ""
    if cfg:
        configured = str(cfg.get("report", {}).get("browser", "") or "").strip()
    exe = configured if configured and Path(configured).exists() else find_browser()

    if exe:
        try:
            proc = subprocess.Popen(
                [exe, path.resolve().as_uri()],
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
            # 启动器正常会继续活着（或转交后台进程）；秒退且非 0 就是没起来
            try:
                code = proc.wait(timeout=1.2)
            except subprocess.TimeoutExpired:
                return True                      # 还在跑，认为成功
            if code == 0:
                return True
            log.warning("浏览器启动器退出码 %s，改走系统关联", code)
        except Exception as exc:
            log.warning("用 %s 打开失败：%s，改走系统关联", exe, exc)

    # 兜底：交给系统关联——但只有关联对象真是浏览器时才这么做，
    # 否则会把日报丢进 VSCode（这台机器的 .html 就关联到了 VSCode）。
    if _assoc_is_browser():
        try:
            os.startfile(str(path))
            return True
        except Exception:
            pass

    log.warning("无法自动打开浏览器，请手动打开 %s", path)
    return False


def _assoc_is_browser() -> bool:
    """`.html` 的默认打开方式是不是浏览器。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.html\UserChoice",
        )
        prog, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return False
    prog = str(prog or "").lower()
    return any(x in prog for x in ("chrome", "edge", "firefox", "browser"))


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _pct(ts: int, day_start: int) -> float:
    return max(0.0, min(100.0, (int(ts) - day_start) / 86400.0 * 100.0))


def _idle_minutes(store, day: str, poll_sec: int) -> float:
    start, end = store_day_bounds(day)
    rows = store.samples(start, end)
    idle = sum(1 for r in rows if r["idle"])
    return idle * poll_sec / 60.0


def store_day_bounds(day: str) -> tuple[int, int]:
    from ..capture.store import day_bounds
    return day_bounds(day)


def _recovery(store, day: str) -> tuple[float | None, int]:
    rows = store.interventions(day)
    alerts = [r for r in rows if r["action"] != "user_action"]
    back = [r for r in rows if r["action"] == "back_to_work"]
    if not alerts:
        return None, 0
    return min(1.0, len(back) / len(alerts)), len(alerts)


def _evidence(block, analyses: list) -> str:
    texts = []
    for a in analyses:
        if int(a["start_ts"]) < int(block["end_ts"]) and int(a["end_ts"]) > int(block["start_ts"]):
            ev = (a["evidence"] or "").strip()
            if ev and ev not in texts:
                texts.append(ev)
    return "；".join(texts[:2])


def collect(store, day: str) -> dict:
    blocks = [dict(b) for b in store.blocks(day)]
    start, end = store_day_bounds(day)
    samples = store.samples(start, end)
    poll = int(store.kv_get("poll_sec", 5) or 5)
    idle_min = _idle_minutes(store, day, poll)

    m = aggregate.metrics(blocks, idle_min)
    prev_day = day_of(start - 86400)
    prev_blocks = [dict(b) for b in store.blocks(prev_day)]
    prev_focus = aggregate.metrics(prev_blocks)["focus_minutes"] if prev_blocks else None

    recovery, alert_count = _recovery(store, day)
    longest = max((int(b["end_ts"]) - int(b["start_ts"]) for b in blocks
                   if b["category"] == "deep_work"), default=0)

    return {
        "day": day, "start": start, "end": end,
        "blocks": blocks, "samples": len(samples),
        "metrics": m, "prev_focus": prev_focus,
        "recovery": recovery, "alerts": alert_count,
        "longest_focus": longest / 60.0,
        "analyses": store.analyses(day),
        "last_goal": store.last_goal_before(day),
    }


def _cards(d: dict) -> str:
    m = d["metrics"]
    ratio = f"{m['effective_ratio'] * 100:.0f}%"
    per_hour = (m["switches"] / (m["awake_minutes"] / 60.0)) if m["awake_minutes"] >= 30 else 0
    rec = "—" if d["recovery"] is None else f"{d['recovery'] * 100:.0f}%"
    if m.get("goal_tracked", True):
        focus_card = (aggregate.fmt_duration(m["focus_minutes"]), "深度专注",
                      "≥ 25 分钟的连续段")
        if m["focus_minutes"] <= 0 and m["deep_minutes"] > 0:
            focus_card = (aggregate.fmt_duration(m["focus_minutes"]), "深度专注",
                          f"没攒出 25 分钟连续段 · 深度工作 "
                          f"{aggregate.fmt_duration(m['deep_minutes'])}")
    else:
        # 没声明目标时不要写「0 分钟」——那不是成绩差，是没测量
        focus_card = ("未统计", "深度专注",
                      f"今天没声明目标 · 深度工作 {aggregate.fmt_duration(m['deep_minutes'])}")
    items = [
        focus_card,
        (aggregate.fmt_duration(m["consumption_minutes"]), "消耗时长", "娱乐 + 无目的浏览"),
        (ratio, "有效比", "生产性 ÷ 在电脑前"),
        (f"{m['switches']} 次", "切换", f"约每小时 {per_hour:.1f} 次"),
        (rec, "恢复力", f"提醒 {d['alerts']} 次"),
    ]
    return "\n".join(
        f'<div class="card"><b>{_esc(v)}</b><span>{_esc(k)}</span>'
        f'<small>{_esc(s)}</small></div>' for v, k, s in items)


def _ruler() -> str:
    return "\n".join(
        f'<i style="left:{h / 24 * 100:.4f}%">{h:02d}:00</i>' for h in range(0, 24, 3))


def _timeline(d: dict) -> str:
    start = d["start"]
    out = []
    for b in d["blocks"]:
        left = _pct(b["start_ts"], start)
        width = max(0.12, _pct(b["end_ts"], start) - left)
        cat = b["category"]
        if cat == "gap":
            out.append(f'<span class="blk gap" style="left:{left:.3f}%;width:{width:.3f}%"'
                       f' title="{_hm(b["start_ts"])}–{_hm(b["end_ts"])} 未采集"></span>')
            continue
        tip = f'{_hm(b["start_ts"])}–{_hm(b["end_ts"])} {aggregate.label(cat)}：{b.get("activity") or ""}'
        out.append(
            f'<a class="blk" href="#blk-{b["id"]}" style="left:{left:.3f}%;width:{width:.3f}%;'
            f'background:{aggregate.color(cat)}" title="{_esc(tip)}"></a>')
    return "\n".join(out)


def _legend(d: dict) -> str:
    by_cat = d["metrics"]["by_category"]
    rows = [(c, v) for c, v in by_cat.items() if v > 0]
    rows.sort(key=lambda x: -x[1])
    return "\n".join(
        f'<div><i class="sw" style="background:{aggregate.color(c)}"></i>'
        f'{aggregate.label(c)}<em>{aggregate.fmt_duration(v)}</em></div>'
        for c, v in rows)


def _blocks(d: dict) -> str:
    out = []
    for b in d["blocks"]:
        cat = b["category"]
        if cat == "gap":
            out.append(
                '<details class="row"><summary>'
                f'<span class="t">{_hm(b["start_ts"])}–{_hm(b["end_ts"])}</span>'
                f'<i class="sw" style="background:{aggregate.color("gap")}"></i>'
                '<span class="what"><b>未采集</b><span>这段时间没有数据（空闲或程序没在跑）</span></span>'
                f'<span class="d">{aggregate.fmt_duration((b["end_ts"] - b["start_ts"]) / 60)}</span>'
                '<span></span></summary></details>')
            continue

        ev_text = _evidence(b, d["analyses"])
        img = ""
        if b.get("shot_ref"):
            img = (f'<img src="../{_esc(b["shot_ref"])}" alt="证据截图" loading="lazy">')
        else:
            img = '<div class="none">这一段没有留下截图</div>'
        ev_body = (
            '<div class="ev">'
            f'<div><p>{_esc(ev_text) if ev_text else "这一段的依据是窗口标题与进程名（元数据档）。"}</p>'
            f'<p style="margin-top:8px;color:#8A94A3;font-size:11.5px">'
            f'置信度 {float(b.get("confidence") or 0):.2f}</p></div>'
            f'<div>{img}</div></div>')

        out.append(
            f'<details class="row" id="blk-{b["id"]}"><summary>'
            f'<span class="t">{_hm(b["start_ts"])}–{_hm(b["end_ts"])}</span>'
            f'<i class="sw" style="background:{aggregate.color(cat)}"></i>'
            f'<span class="what"><b>{aggregate.label(cat)}</b>'
            f'<span>{_esc(b.get("activity") or "")}</span></span>'
            f'<span class="d">{aggregate.fmt_duration((b["end_ts"] - b["start_ts"]) / 60)}</span>'
            '<span class="chev"></span></summary>'
            f'{ev_body}</details>')
    return "\n".join(out) or '<p class="none" style="color:#8A94A3">今天还没有数据。</p>'


def render_day(cfg: dict, store, day: str | None = None,
               open_browser: bool | None = None, out_name: str | None = None) -> Path:
    day = day or day_of(time.time())
    d = collect(store, day)
    m = d["metrics"]

    if not d["blocks"]:
        if d["samples"]:
            summary = "刚开始记录，还没攒够第一批（15 分钟），过一会儿再看。"
            sub = (f"已经记下 {d['samples']} 条采样；第一批分析会在本个 15 分钟窗口结束时完成。")
        else:
            summary = "今天还没有数据——程序可能没在运行。"
            sub = "先让余光跑一天，晚上再来看。"
    else:
        summary = aggregate.summary_line(m, d["prev_focus"], d["last_goal"])
        if m.get("goal_tracked", True):
            sub = (f"识别出 {m['block_count']} 段 · 有效比 {m['effective_ratio'] * 100:.0f}% · "
                   f"最长一段专注 {aggregate.fmt_duration(d['longest_focus'])}")
        else:
            sub = (f"识别出 {m['block_count']} 段 · 有效比 {m['effective_ratio'] * 100:.0f}% · "
                   f"深度工作 {aggregate.fmt_duration(m['deep_minutes'])}"
                   f"（没声明目标，专注不参与统计）")

    date_cn = time.strftime("%Y 年 %m 月 %d 日", time.strptime(day, "%Y-%m-%d"))
    tpl = Template(TEMPLATE.read_text(encoding="utf-8"))
    out = tpl.safe_substitute(
        title=f"余光 · {day} 时间账单",
        date_cn=date_cn,
        tracked=aggregate.fmt_duration(m["total_minutes"]),
        focus=(aggregate.fmt_duration(m["focus_minutes"])
               if m.get("goal_tracked", True) else "未统计"),
        switches=f"{m['switches']} 次",
        summary=_esc(summary),
        sub_line=_esc(sub),
        cards=_cards(d),
        ruler=_ruler(),
        timeline=_timeline(d),
        legend=_legend(d) or '<div style="color:#8A94A3;font-size:12px">暂无分类数据</div>',
        blocks=_blocks(d),
        suggestion=_esc(aggregate.suggestion(m)),
        version=_esc(cfg["app"].get("version", "0.2.0")),
        footer_right=f"生成于 {time.strftime('%H:%M')} · {d['samples']} 条采样",
    )

    # 一天只有一个文件：文件名就是日期，重复生成直接覆盖（先写临时文件再替换，
    # 这样浏览器不会读到写了一半的页面）。
    folder = Path(config.REPORTS)
    folder.mkdir(parents=True, exist_ok=True)
    name = out_name or f"{day}.html"
    path = folder / name
    tmp = folder / f".{name}.tmp"
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
    log.info("日报已生成：%s（%d 字节，覆盖同日旧版）", path, path.stat().st_size)

    if open_browser is None:
        open_browser = bool(cfg["report"].get("open_browser", True))
    if open_browser:
        open_in_browser(path, cfg)
    return path
