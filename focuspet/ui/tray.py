# -*- coding: utf-8 -*-
"""托盘、菜单与界面装配（设计方案 7 节 / 13.3）。

线程与界面之间只走队列：Qt 控件绝不能被后台线程直接碰，
所以采集线程把提醒塞进 UiBridge，界面用 QTimer 每 400ms 取一次。
"""
from __future__ import annotations

import queue
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QApplication, QInputDialog, QMenu, QMessageBox,
                               QSystemTrayIcon)

from .. import config
from ..analyze.aggregate import fmt_duration, metrics
from ..capture.store import day_bounds, day_of
from ..log import get
from .icons import app_icon
from .panel import ControlPanel
from .pet import Pet
from .settings import SettingsDialog

log = get("tray")


class UiBridge:
    """线程 → 界面的单向队列。"""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()

    def push(self, level: int, text: str) -> None:
        self.q.put((level, text))

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out


def _icon() -> QIcon:
    """图标来自 focuspet/assets/icon.ico，文件缺失时才退回代码画的简笔脸。"""
    return app_icon()


class Tray(QSystemTrayIcon):
    def __init__(self, app, pet: Pet, bridge: UiBridge):
        super().__init__(_icon())
        self.app = app
        self.pet = pet
        self.bridge = bridge
        self.panel = None
        self.setToolTip("余光 · 用余光看着你")
        self._build_menu()
        self.activated.connect(self._on_activated)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._drain)
        self._poll.start(400)

    # ---------------------------------------------------------------- 菜单
    def _build_menu(self) -> None:
        m = QMenu()
        self.act_focus = QAction("开始专注…", m)
        self.act_focus.triggered.connect(self._start_focus)
        self.act_pause = QAction("暂停采集", m)
        self.act_pause.setCheckable(True)
        self.act_pause.triggered.connect(self._toggle_pause)
        self.act_panel = QAction("打开控制面板", m)
        self.act_panel.triggered.connect(self.open_panel)
        self.act_today = QAction("今日概览", m)
        self.act_today.triggered.connect(self._show_today)
        self.act_report = QAction("打开今日日报", m)
        self.act_report.triggered.connect(self._open_report)
        self.act_settings = QAction("设置…", m)
        self.act_settings.triggered.connect(self._open_settings)
        self.act_quit = QAction("退出", m)
        self.act_quit.triggered.connect(self._quit)

        m.addAction(self.act_panel)
        m.addAction(self.act_focus)
        m.addSeparator()
        m.addAction(self.act_pause)
        m.addAction(self.act_today)
        m.addAction(self.act_report)
        m.addAction(self.act_settings)
        m.addSeparator()
        m.addAction(self.act_quit)
        self.menu = m
        self.setContextMenu(m)
        m.aboutToShow.connect(self._refresh_labels)

    def _refresh_labels(self) -> None:
        """菜单文案跟着「今天有没有目标」变：设定 / 更换。"""
        try:
            goal = self.app.store.active_goal()
        except Exception:
            goal = None
        self.act_focus.setText("更换目标…" if goal else "设定目标…")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.open_panel()

    def open_panel(self, focus_goal: bool = False) -> None:
        """控制面板：托盘菜单、第二次启动、--panel 都走这里。

        focus_goal=True 时把光标落在「声明目标」上——启动时没目标就是走这条路。
        """
        if self.panel is None:
            self.panel = ControlPanel(self.app)
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        self.panel.refresh()
        if focus_goal:
            self.panel.focus_goal()

    def message(self, title: str, text: str) -> None:
        self.showMessage(title, text, QSystemTrayIcon.Information, 3000)

    # ---------------------------------------------------------------- 动作
    def _start_focus(self):
        text, ok = QInputDialog.getText(self.parent() or None, "开始专注",
                                        "今天要做什么？（一句话即可）")
        if ok and text.strip():
            self.app.store.set_goal(text.strip())
            self.message("余光", f"记下了：{text.strip()}")

    def _toggle_pause(self, checked: bool):
        self.app.paused = checked
        self.act_pause.setText("继续采集" if checked else "暂停采集")
        self.message("余光", "采集已暂停" if checked else "采集已恢复")

    def _show_today(self):
        day = day_of(time.time())
        blocks = [dict(b) for b in self.app.store.blocks(day)]
        m = metrics(blocks)
        goal = self.app.store.active_goal()

        samples = []
        try:
            samples = self.app.store.samples(*day_bounds(day))
        except Exception:
            pass

        msg = (f"今日目标：{goal['text'] if goal else '未声明'}\n\n"
               f"在电脑前　{fmt_duration(m['total_minutes'])}\n"
               f"深度专注　{fmt_duration(m['focus_minutes'])}\n"
               f"消耗时长　{fmt_duration(m['consumption_minutes'])}\n"
               f"切换次数　{m['switches']} 次\n"
               f"有效比　　{m['effective_ratio'] * 100:.0f}%\n\n"
               f"已采集 {len(samples)} 条 · 每分钟更新")
        if samples:
            first = time.strftime("%H:%M", time.localtime(int(samples[0]["ts"])))
            msg += f" · 从 {first} 开始"
            if m["total_minutes"] <= 0:
                msg += "\n（刚起步或刚重启，下一分钟就会出现第一段）"
        if not goal:
            msg += "\n\n未声明目标：只统计时长和占比，不判定「是否在跑偏」，\n「深度专注」也不会累计。托盘右键 →「开始专注…」即可。"
        QMessageBox.information(None, "今日概览", msg)

    def _open_report(self):
        from ..report.render import render_day
        path = render_day(self.app.cfg, self.app.store, day_of(time.time()))
        self.message("余光", f"日报已生成：{path.name}")

    def _open_settings(self):
        dlg = SettingsDialog(self.app.cfg)
        if dlg.exec():
            dlg.apply()
            self.message("余光", "设置已保存")

    def _quit(self):
        self.app.stop()
        QApplication.quit()

    # ---------------------------------------------------------------- 队列
    def _drain(self):
        for level, text in self.bridge.drain():
            if level == -1:                 # 来自「第二次启动」的唤起请求
                log.info("收到唤起请求，打开控制面板")
                self.open_panel()
                continue
            if level == -2:                 # 系统通知：日报 / 周报 / 月报生成
                self.showMessage("余光", text, QSystemTrayIcon.Information, 6000)
                continue
            if self.pet.mode != "hidden":
                self.pet.alert(text, 5000, level)
            else:
                self.showMessage("余光", text, QSystemTrayIcon.Information, 4000)


def run_ui(app, show_panel: bool = False) -> int:
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName("余光")
    qapp.setApplicationDisplayName("余光")
    qapp.setWindowIcon(app_icon())          # 面板/对话框/任务栏都用同一张脸

    bridge = UiBridge()
    app.bridge = bridge
    pet = Pet(app.cfg)
    app.pet = pet                       # 控制面板要能立刻切换桌宠显示层级
    tray = Tray(app, pet, bridge)
    tray.show()

    # Pet 自己按 ui.pet_mode 决定显示还是藏起来（top / desktop / hidden）
    if pet.mode != "hidden":
        QTimer.singleShot(400, pet.show_idle_pos)

    if show_panel:                       # 快捷方式带 --panel：启动后直接把面板摆出来
        QTimer.singleShot(300, tray.open_panel)

    def _ask_goal_on_start():
        """启动时没声明目标：直接弹面板，光标落在「声明目标」上。

        以前这里只发一条托盘气泡，而托盘图标在 Win11 默认被塞进「隐藏图标」，
        等于没提醒——干脆把面板摆出来，用户关掉就算了。
        """
        try:
            if app.store.active_goal():
                return
            log.info("今天还没声明目标，直接打开控制面板")
            tray.open_panel(focus_goal=True)
        except Exception:
            log.debug("启动时打开面板失败", exc_info=True)

    QTimer.singleShot(1200, _ask_goal_on_start)

    def _nudge_goal():
        """面板被关掉、目标仍然没声明时，再补一条气泡（只补这一次）。"""
        try:
            if app.store.active_goal():
                return
            if tray.panel is not None and tray.panel.isVisible():
                return
            tray.message("余光", "今天还没声明目标。右键托盘 →「开始专注…」，"
                                "否则只统计时长，不判定是否跑偏。")
        except Exception:
            pass

    QTimer.singleShot(60_000, _nudge_goal)

    # 托盘图标可能被 Windows 藏进「隐藏图标」，因此再开一条唤起通道：
    # 再启动一次程序（或双击 启动余光.bat）就能把今日概览叫出来。
    from .. import ipc
    ipc.serve(lambda: bridge.push(-1, ""))

    log.info("托盘状态：系统可用=%s，图标已显示=%s，支持气泡=%s",
             QSystemTrayIcon.isSystemTrayAvailable(), tray.isVisible(),
             QSystemTrayIcon.supportsMessages())

    tray.message("余光", "开始记录。右键托盘图标可以声明目标。")
    app.start()
    try:
        return qapp.exec()
    finally:
        ipc.cleanup()
        app.stop()
