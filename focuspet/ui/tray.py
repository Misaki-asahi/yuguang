# -*- coding: utf-8 -*-
"""托盘、菜单与界面装配（设计方案 7 节 / 13.3）。

线程与界面之间只走队列：Qt 控件绝不能被后台线程直接碰，
所以采集线程把提醒塞进 UiBridge，界面用 QTimer 每 400ms 取一次。
"""
from __future__ import annotations

import queue
import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QInputDialog, QMenu, QMessageBox,
                               QSystemTrayIcon)

from .. import config
from ..analyze.aggregate import fmt_duration, metrics
from ..capture.store import day_bounds, day_of
from ..log import get
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
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#F6C87A"))
    p.drawEllipse(6, 10, 52, 46)
    p.setBrush(QColor("#3B3A36"))
    p.drawEllipse(21, 28, 7, 8)
    p.drawEllipse(37, 28, 7, 8)
    p.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    def __init__(self, app, pet: Pet, bridge: UiBridge):
        super().__init__(_icon())
        self.app = app
        self.pet = pet
        self.bridge = bridge
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
        self.act_today = QAction("今日概览", m)
        self.act_today.triggered.connect(self._show_today)
        self.act_report = QAction("打开今日日报", m)
        self.act_report.triggered.connect(self._open_report)
        self.act_pet = QAction("显示桌宠", m)
        self.act_pet.setCheckable(True)
        self.act_pet.setChecked(bool(self.app.cfg["ui"].get("pet_enabled", True)))
        self.act_pet.triggered.connect(self._toggle_pet)
        self.act_settings = QAction("设置…", m)
        self.act_settings.triggered.connect(self._open_settings)
        self.act_quit = QAction("退出", m)
        self.act_quit.triggered.connect(self._quit)

        m.addAction(self.act_focus)
        m.addSeparator()
        m.addAction(self.act_pause)
        m.addAction(self.act_today)
        m.addAction(self.act_report)
        m.addAction(self.act_pet)
        m.addAction(self.act_settings)
        m.addSeparator()
        m.addAction(self.act_quit)
        self.menu = m
        self.setContextMenu(m)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show_today()

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

    def _toggle_pet(self, checked: bool):
        self.app.cfg["ui"]["pet_enabled"] = checked
        if checked:
            self.pet.show()
            self.pet.set_state("idle")
        else:
            self.pet.hide()

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
            self.act_pet.setChecked(bool(self.app.cfg["ui"].get("pet_enabled", True)))
            self.message("余光", "设置已保存")

    def _quit(self):
        self.app.stop()
        QApplication.quit()

    # ---------------------------------------------------------------- 队列
    def _drain(self):
        for level, text in self.bridge.drain():
            if level == -1:                 # 来自「第二次启动」的唤起请求
                log.info("收到唤起请求，打开今日概览")
                self._show_today()
                continue
            if self.app.cfg["ui"].get("pet_enabled", True):
                self.pet.alert(text, 5000, level)
            else:
                self.showMessage("余光", text, QSystemTrayIcon.Information, 4000)


def run_ui(app) -> int:
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    bridge = UiBridge()
    app.bridge = bridge
    pet = Pet(app.cfg)
    tray = Tray(app, pet, bridge)
    tray.show()

    if app.cfg["ui"].get("pet_enabled", True):
        pet.show()
        QTimer.singleShot(400, pet.show_idle_pos)

    def _nudge_goal():
        """没声明目标就没有「摸鱼判定」，开机一分钟提醒一次。"""
        try:
            if not app.store.active_goal():
                tray.message("余光", "今天还没声明目标。右键托盘 →「开始专注…」，"
                                    "否则只统计时长，不判定是否跑偏。")
        except Exception:
            pass

    QTimer.singleShot(60_000, _nudge_goal)

    # 托盘图标可能被 Windows 藏进「隐藏图标」，因此再开一条唤起通道：
    # 再启动一次程序（或双击 启动余光.bat）就能把今日概览叫出来。
    from .. import ipc
    ipc.serve(lambda: bridge.push(-1, ""))

    tray.message("余光", "开始记录。右键托盘图标可以声明目标。")
    app.start()
    try:
        return qapp.exec()
    finally:
        ipc.cleanup()
        app.stop()
