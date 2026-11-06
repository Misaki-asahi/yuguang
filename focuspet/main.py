# -*- coding: utf-8 -*-
"""入口：DPI → 配置 → 线程 → 事件循环（设计方案 15.3 / 15.5）。

三条线程各管一件事，互不阻塞：
  采集循环   5 秒一次，只做 IO，永远不等网络；
  分析线程   每分钟检查一次「有没有攒够一个批次」；
  日报线程   到点生成，失败也不影响主程序。
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback

from . import config, maintenance
from .analyze.aggregate import CONSUMING, fmt_duration
from .analyze.rules import RuleSet
from .analyze.scheduler import Scheduler
from .capture import shot as shotmod
from .capture import win as winmod
from .capture.store import Store, day_of
from .judge.engine import Judge
from .judge.intervene import Intervener
from .log import get, heartbeat, setup

log = get("main")

# 切窗口后标题要多久才算稳定。网页端（B 站这类 SPA）换标题常有 1~3 秒延迟，
# 太短会把上一个页面的标题记到新页面上。
TITLE_SETTLE_SEC = 3.0
# 一段活动结束后超过这个秒数就不再判定——避免拿很久以前的段落来提醒
JUDGE_STALE_SEC = 120


class App:
    def __init__(self, cfg: dict, ui: bool = False):
        self.cfg = cfg
        self.ui = ui
        winmod.enable_dpi_awareness()

        self.store = Store()
        self.rules = RuleSet()
        self.scheduler = Scheduler(cfg, self.store, self.rules)
        self.judge = Judge(cfg, self.store)
        self.intervener = Intervener(cfg, self.store, self.judge, self._notify)

        self.capturer = shotmod.Capturer(cfg)
        self.paused = False
        self._stop = False
        self._last_win: tuple | None = None
        self._key_changed_at = 0.0
        # 从库里续上上一张截图的时间：否则每次重启都会立刻补拍一张，
        # 把「10 分钟一张」变成「每次重启一张」。
        self._last_shot = float(self.store.last_shot_ts())
        self._last_report_day = ""

    # ---------------------------------------------------------------- 通知
    def _notify(self, level: int, text: str) -> None:
        if self.ui and self.bridge is not None:
            self.bridge.push(level, text)
        else:
            log.info("【提醒 L%d】%s", level, text)

    bridge = None

    # ---------------------------------------------------------------- 采集
    def tick(self, now: float | None = None) -> dict:
        now = float(now or time.time())
        cap = self.cfg["capture"]
        poll = int(cap.get("window_poll_sec", 5))
        self.store.kv_set("poll_sec", poll)

        idle = winmod.idle_seconds()
        if idle >= float(cap.get("idle_threshold_sec", 300)):
            self.store.insert_sample(int(now), "", "", None, None, idle=1)
            self._last_win = None
            heartbeat()
            return {"state": "idle", "idle": idle}

        win = winmod.foreground()
        if win is None:
            heartbeat()
            return {"state": "no-window"}

        priv = self.cfg["privacy"]
        if winmod.is_sensitive_proc(win.proc, priv.get("sensitive_procs", [])):
            self.store.insert_sample(int(now), win.proc, "<sensitive>", None, None,
                                     sensitive=1)
            heartbeat()
            return {"state": "sensitive", "proc": win.proc}

        title = winmod.masked_title(win.title, priv.get("sensitive_keywords", []))
        sensitive = 1 if title == "<sensitive>" else 0

        shot_path = None
        dhash = None
        if not sensitive and priv.get("mode") != "meta_only":
            due = (now - self._last_shot) >= float(cap.get("shot_interval_sec", 600))
            changed = (cap.get("shot_on_window_change", True)
                       and self._last_win is not None and win.key() != self._last_win)
            if due or changed:
                self._last_shot = now
                if winmod.is_fullscreen(win.hwnd):
                    log.debug("全屏窗口跳过截图：%s", win.proc)
                else:
                    got = self.capturer.shot(now)
                    if got:
                        shot_path, dhash = got

        # 标题稳定守卫：刚切过去的头几秒，窗口标题可能还是上一个页面的
        # （网页端换标题有延迟），这条采样照记，但标记 unsettled，分类时跳过。
        key = win.key()
        if key != self._last_win:
            self._key_changed_at = now
        settled = 1 if (now - self._key_changed_at) >= TITLE_SETTLE_SEC else 0

        sid = self.store.insert_sample(int(now), win.proc, title, shot_path, dhash,
                                       sensitive=sensitive, settled=settled)
        self._last_win = key
        heartbeat()
        return {"state": "ok", "proc": win.proc, "title": title,
                "shot": shot_path, "id": sid}

    def capture_loop(self) -> None:
        poll = int(self.cfg["capture"].get("window_poll_sec", 5))
        while not self._stop:
            if self.paused:
                self._sleep(2)
                continue
            t0 = time.time()
            try:
                r = self.tick()
                if r.get("state") == "ok" and r.get("shot"):
                    log.info("采样 %s | %s", r["proc"], r["title"][:40])
            except Exception:
                log.error("采集异常：%s", traceback.format_exc(limit=2))
            elapsed = time.time() - t0
            time.sleep(max(0.2, poll - elapsed))

    # ---------------------------------------------------------------- 分析
    def analysis_loop(self) -> None:
        while not self._stop:
            try:
                n = self.scheduler.run()
                if n:
                    log.info("完成 %d 个批次", n)
                self._maybe_judge()
            except Exception:
                log.error("分析异常：%s", traceback.format_exc(limit=2))
            self._sleep(60)

    def _maybe_judge(self) -> None:
        day = day_of(time.time())
        blocks = self.store.blocks(day)
        if not blocks:
            return
        last = dict(blocks[-1])
        now = int(time.time())

        # 只对「还在发生」的段落判定：一段结束两分钟以上就不该再弹提醒
        if now - int(last["end_ts"]) > JUDGE_STALE_SEC:
            return

        if last["category"] not in CONSUMING:
            # 正向反馈：一段够长的深度工作结束，说句好话（不打扰，只是让桌宠别只会骂人）
            if last["category"] == "deep_work":
                try:
                    self.intervener.praise(last, now)
                except Exception:
                    log.debug("正向反馈失败，忽略")
            return

        self.intervener.check(last, now)

    # ---------------------------------------------------------------- 日报
    def report_loop(self) -> None:
        while not self._stop:
            try:
                day = day_of(time.time())
                hh, mm = (int(x) for x in str(self.cfg["report"].get("time", "22:00")).split(":"))
                now = time.localtime()
                if (now.tm_hour, now.tm_min) >= (hh, mm) and self._last_report_day != day:
                    from .report.render import render_day
                    path = render_day(self.cfg, self.store, day)
                    self._last_report_day = day
                    log.info("日报完成：%s", path)
                    self.maintenance()
                self._maybe_period_reports(now)
            except Exception:
                log.error("日报异常：%s", traceback.format_exc(limit=2))
            self._sleep(60)

    def _maybe_period_reports(self, now: time.struct_time) -> None:
        """周末出周报、月末出月报；错过也会在下次启动时补上，同一周期只做一次。"""
        from datetime import date, datetime
        from .report.summary import (month_key, month_range, period_targets,
                                     render_period, week_key, week_range)

        today = date.today()
        weekly_day, monthly_day = period_targets(today, datetime.now(), self.cfg["report"])

        if self.store.kv_get("last_weekly") != week_key(weekly_day):
            s, e = week_range(weekly_day)
            if self._period_has_data(s, e):
                path = render_period(self.cfg, self.store, "weekly", weekly_day)
                log.info("周报完成：%s", path)
            self.store.kv_set("last_weekly", week_key(weekly_day))

        if self.store.kv_get("last_monthly") != month_key(monthly_day):
            s, e = month_range(monthly_day)
            if self._period_has_data(s, e):
                path = render_period(self.cfg, self.store, "monthly", monthly_day)
                log.info("月报完成：%s", path)
            self.store.kv_set("last_monthly", month_key(monthly_day))

    def _period_has_data(self, start, end) -> bool:
        from datetime import timedelta
        d = start
        while d <= end:
            if self.store.blocks(d.isoformat()):
                return True
            d += timedelta(days=1)
        return False

    def _sleep(self, sec: float) -> None:
        end = time.time() + sec
        while not self._stop and time.time() < end:
            time.sleep(min(1.0, end - time.time()))

    # ---------------------------------------------------------------- 维护
    def maintenance(self) -> None:
        """保留策略：截图默认 7 天、明细 30 天（14.4）。启动时和每天出完日报后各跑一次。"""
        if not self.cfg["retention"].get("auto_clean", True):
            return
        try:
            res = maintenance.clean_all(self.cfg, self.store)
            if res["shot_days_removed"] or res["samples_removed"] or res["log_files_removed"]:
                log.info("清理：%d 个截图目录、%d 个日志、%d 条明细，释放 %s",
                         res["shot_days_removed"], res["log_files_removed"],
                         res["samples_removed"], maintenance.human_size(res["freed_bytes"]))
        except Exception as exc:
            log.warning("清理失败（不影响采集）：%s", exc)

    # ---------------------------------------------------------------- 启停
    def start(self) -> None:
        import threading
        self.maintenance()
        self.threads = [
            threading.Thread(target=self.capture_loop, name="capture", daemon=True),
            threading.Thread(target=self.analysis_loop, name="analyze", daemon=True),
            threading.Thread(target=self.report_loop, name="report", daemon=True),
        ]
        for t in self.threads:
            t.start()
        log.info("余光已启动（%d 条规则，采集间隔 %ss）",
                 len(self.rules.rules), self.cfg["capture"]["window_poll_sec"])

    def stop(self) -> None:
        self._stop = True
        self.capturer.close()
        for t in getattr(self, "threads", []):
            t.join(timeout=2)
        self.store.close()
        log.info("余光已退出")


# -------------------------------------------------------------------- CLI
def _parse_hm(text: str) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in str(text).split(":")[:2])
        return hh, mm
    except Exception:
        return 21, 0


def _summary(cfg, store, day: str) -> str:
    from .analyze.aggregate import metrics
    blocks = [dict(b) for b in store.blocks(day)]
    m = metrics(blocks)
    return (f"{day}：{m['block_count']} 段，专注 {fmt_duration(m['focus_minutes'])}，"
            f"消耗 {fmt_duration(m['consumption_minutes'])}，切换 {m['switches']} 次，"
            f"有效比 {m['effective_ratio'] * 100:.0f}%")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="focuspet", description="余光 · 屏幕行为监测与桌宠提醒")
    p.add_argument("--demo", action="store_true", help="造一天演示数据并生成日报")
    p.add_argument("--report", nargs="?", const="today", metavar="YYYY-MM-DD",
                   help="重新生成某天的日报并用浏览器打开（同日旧版会被覆盖）")
    p.add_argument("--weekly", action="store_true", help="生成本周周报并打开")
    p.add_argument("--monthly", action="store_true", help="生成本月月报并打开")
    p.add_argument("--no-open", action="store_true",
                   help="配合 --report/--weekly/--monthly：只生成不打开浏览器")
    p.add_argument("--once", action="store_true", help="只采集一次，用于验证环境")
    p.add_argument("--headless", action="store_true", help="不启动托盘和桌宠")
    p.add_argument("--duration", type=int, default=0,
                   help="跑够这么多秒就退出，用于验证环境")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup(args.verbose)
    cfg = config.load()

    if args.demo:
        from .demo import open_demo_store, run as run_demo
        store = open_demo_store()          # 独立的 demo.db，不碰真实数据
        info = run_demo(cfg, store, None)
        print(f"演示完成：{info['day']} · {info['batches']} 批 · "
              f"{info['blocks']} 段 · {info['samples']} 条采样")
        print(f"日报：{info['report']}")
        print(_summary(cfg, store, info["day"]))
        store.close()
        return 0

    if args.report:
        from .report.render import render_day
        store = Store()
        day = day_of(time.time()) if args.report == "today" else args.report
        path = render_day(cfg, store, day, open_browser=not args.no_open)
        print(_summary(cfg, store, day))
        print(f"日报：{path}")
        store.close()
        return 0

    if args.weekly or args.monthly:
        from .report.summary import render_period
        store = Store()
        kind = "weekly" if args.weekly else "monthly"
        path = render_period(cfg, store, kind, open_browser=not args.no_open)
        print(f"{'周报' if kind == 'weekly' else '月报'}：{path}")
        store.close()
        return 0

    app = App(cfg, ui=not args.headless)

    if args.once:
        r = app.tick()
        print("采样：", r)
        app.store.close()
        return 0

    if args.duration:
        app.ui = False
        app.start()
        log.info("试跑 %d 秒…", args.duration)
        count = 0
        try:
            time.sleep(args.duration)
        finally:
            count = app.store.sample_count(day_of(time.time()))
            app.stop()
        print(f"试跑结束：今日采样 {count} 条")
        return 0

    if args.headless:
        app.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            app.stop()
        return 0

    try:
        from .ui.tray import run_ui
        return run_ui(app)
    except ImportError:
        log.warning("PySide6 不可用，退回无界面模式")
        args.headless = True
        app.ui = False
        app.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            app.stop()
        return 0


if __name__ == "__main__":
    sys.exit(main())
