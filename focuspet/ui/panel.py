# -*- coding: utf-8 -*-
"""控制面板：托盘图标找不到时的主入口。

一张窗口装下以前散在托盘菜单里的东西：今日数字、目标声明、日报/周报/月报、
暂停、开机自启、日报时间、退出。关闭窗口只是隐藏，程序继续在后台记录。
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog,
                               QLabel, QMessageBox, QPushButton, QTimeEdit,
                               QVBoxLayout, QWidget)

from .. import autostart, config
from ..analyze.aggregate import fmt_duration, metrics
from ..capture.store import day_bounds, day_of
from ..log import get

log = get("panel")

STYLE = """
QWidget { background: #FBFBFC; color: #1F2937;
          font-family: "Microsoft YaHei", "PingFang SC", sans-serif; }
QLabel#title { font-size: 18px; font-weight: 700; color: #1F4E79; }
QLabel#state { color: #8A94A3; font-size: 12px; }
QLabel#goal  { color: #B45309; font-size: 13px; }
QLabel#stats { color: #4B5563; font-size: 12px; line-height: 1.6; }
QPushButton { background: #FFFFFF; border: 1px solid #D9DFE7; border-radius: 6px;
              padding: 7px 12px; font-size: 13px; }
QPushButton:hover { border-color: #1F4E79; color: #1F4E79; }
QPushButton#primary { background: #1F4E79; color: #FFFFFF; border: none; }
QPushButton#primary:hover { background: #2A6296; }
QPushButton#danger:hover { border-color: #B45309; color: #B45309; }
QCheckBox { font-size: 13px; }
QTimeEdit { border: 1px solid #D9DFE7; border-radius: 6px; padding: 4px 8px; }
"""


class ControlPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("余光")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(430)
        self._build()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)

    # ---------------------------------------------------------------- 布局
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("余光")
        title.setObjectName("title")
        self.lbl_state = QLabel("")
        self.lbl_state.setObjectName("state")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.lbl_state)
        root.addLayout(head)

        self.lbl_goal = QLabel("")
        self.lbl_goal.setObjectName("goal")
        self.lbl_goal.setWordWrap(True)
        root.addWidget(self.lbl_goal)

        self.btn_goal = QPushButton("开始专注…")
        self.btn_goal.setObjectName("primary")
        self.btn_goal.clicked.connect(self._set_goal)
        root.addWidget(self.btn_goal)

        # 目标按天记录，新的一天要重新声明；给一个「沿用上次」的快捷入口
        self.btn_carry = QPushButton("")
        self.btn_carry.clicked.connect(self._carry_goal)
        self.btn_carry.hide()
        root.addWidget(self.btn_carry)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("stats")
        self.lbl_stats.setWordWrap(True)
        root.addWidget(self.lbl_stats)

        row1 = QHBoxLayout()
        for text, slot in (("今日日报", self._open_daily),
                           ("本周周报", self._open_weekly),
                           ("本月月报", self._open_monthly)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row1.addWidget(b)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_pause = QPushButton("暂停采集")
        self.btn_pause.clicked.connect(self._toggle_pause)
        b_settings = QPushButton("设置…")
        b_settings.clicked.connect(self._open_settings)
        row2.addWidget(self.btn_pause)
        row2.addWidget(b_settings)
        root.addLayout(row2)

        # 桌宠的显示层级：始终置顶 / 只在桌面显示 / 不显示
        row_pet = QHBoxLayout()
        row_pet.addWidget(QLabel("桌宠"))
        self.pet_mode = QComboBox()
        self.pet_mode.addItem("始终置顶", "top")
        self.pet_mode.addItem("只在桌面显示", "desktop")
        self.pet_mode.addItem("不显示", "hidden")
        self.pet_mode.setCurrentIndex(max(0, self.pet_mode.findData(
            str(self.app.cfg["ui"].get("pet_mode", "top")))))
        self.pet_mode.currentIndexChanged.connect(self._change_pet_mode)
        row_pet.addWidget(self.pet_mode, 1)
        root.addLayout(row_pet)

        row3 = QHBoxLayout()
        self.chk_autostart = QCheckBox("开机自启")
        self.chk_autostart.setChecked(autostart.is_installed())
        self.chk_autostart.clicked.connect(self._toggle_autostart)
        row3.addWidget(self.chk_autostart)
        row3.addStretch()
        row3.addWidget(QLabel("日报时间"))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        hh, mm = self._report_hm()
        self.time_edit.blockSignals(True)          # 初始化不要触发保存
        self.time_edit.setTime(QTime(hh, mm))
        self.time_edit.blockSignals(False)
        self.time_edit.timeChanged.connect(self._save_report_time)
        row3.addWidget(self.time_edit)
        root.addLayout(row3)

        root.addStretch()
        quit_btn = QPushButton("退出余光")
        quit_btn.setObjectName("danger")
        quit_btn.clicked.connect(self._quit)
        root.addWidget(quit_btn)

    # ---------------------------------------------------------------- 数据
    def refresh(self) -> None:
        try:
            day = day_of(time.time())
            blocks = [dict(b) for b in self.app.store.blocks(day)]
            m = metrics(blocks)
            goal = self.app.store.active_goal()

            self.lbl_state.setText("已暂停" if self.app.paused else "正在记录")
            if goal:
                self.lbl_goal.setText(f"今日目标：{goal['text']}")
            else:
                self.lbl_goal.setText("今日目标：未声明 —— 今天只统计时长，不判断是否跑偏")

            # 没有今天的 goal 时，把「沿用上次」提成主按钮：一键就能开工。
            # 「开始专注…」同时存在，但退成次要入口（重新写一句）。
            if goal:
                self.btn_carry.hide()
                self._set_primary(self.btn_goal, True)
            else:
                last = self.app.store.last_goal_before(day)
                if last:
                    short = last if len(last) <= 18 else last[:18] + "…"
                    self.btn_carry.setText(f"沿用上次：{short}")
                    self.btn_carry.show()
                    self._set_primary(self.btn_carry, True)
                    self._set_primary(self.btn_goal, False)
                else:
                    self.btn_carry.hide()
                    self._set_primary(self.btn_goal, True)

            self.btn_goal.setText("点击更换目标" if goal else "开始专注…")
            # 没声明目标时「深度专注 0 分钟」是误导：那是没测量，不是没干活
            focus_txt = (fmt_duration(m["focus_minutes"]) if m.get("goal_tracked")
                         else f"未统计（深度工作 {fmt_duration(m['deep_minutes'])}）")
            self.lbl_stats.setText(
                f"在电脑前 {fmt_duration(m['total_minutes'])}　"
                f"深度专注 {focus_txt}\n"
                f"消耗 {fmt_duration(m['consumption_minutes'])}　"
                f"切换 {m['switches']} 次　有效比 {m['effective_ratio'] * 100:.0f}%")
            self.btn_pause.setText("继续采集" if self.app.paused else "暂停采集")
            if not self.app.paused:
                self.chk_autostart.setChecked(autostart.is_installed())
        except Exception:
            log.debug("刷新面板失败", exc_info=True)

    def _set_primary(self, btn, on: bool) -> None:
        """切换按钮的主/次样式（QSS 按 objectName 命中，改完必须重新 polish）。"""
        name = "primary" if on else ""
        if btn.objectName() == name:
            return
        btn.setObjectName(name)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def focus_goal(self) -> None:
        """把光标放到目标声明上：有「沿用上次」就落它，否则落「开始专注」。"""
        target = self.btn_carry if self.btn_carry.isVisible() else self.btn_goal
        target.setFocus(Qt.OtherFocusReason)
        self.raise_()
        self.activateWindow()

    def _report_hm(self) -> tuple[int, int]:
        try:
            hh, mm = (int(x) for x in str(self.app.cfg["report"].get("time", "22:00")).split(":")[:2])
            return hh, mm
        except Exception:
            return 22, 0

    # ---------------------------------------------------------------- 动作
    def _set_goal(self) -> None:
        goal = self.app.store.active_goal()
        title = "更换目标" if goal else "开始专注"
        text, ok = QInputDialog.getText(self, title, "今天要做什么？（一句话即可）",
                                        text=goal["text"] if goal else "")
        if ok and text.strip():
            self.app.store.set_goal(text.strip())
            self.refresh()

    def _change_pet_mode(self, _index: int) -> None:
        """桌宠显示层级：立即生效并写回 config.yaml。"""
        mode = str(self.pet_mode.currentData() or "top")
        self.app.cfg["ui"]["pet_mode"] = mode
        config.save(self.app.cfg)
        pet = getattr(self.app, "pet", None)
        if pet is not None:
            pet.set_mode(mode)
        log.info("桌宠显示层级改为 %s", mode)

    def _carry_goal(self) -> None:
        text = self.app.store.last_goal_before(day_of(time.time()))
        if text:
            self.app.store.set_goal(text)
            self.refresh()

    def _toggle_pause(self) -> None:
        self.app.paused = not self.app.paused
        self.refresh()

    def _open_daily(self) -> None:
        from ..report.render import open_in_browser, render_day
        try:
            path = render_day(self.app.cfg, self.app.store, day_of(time.time()),
                              open_browser=False)
            self._after_render(path, "日报")
        except Exception as exc:
            QMessageBox.warning(self, "生成失败", str(exc))

    def _after_render(self, path, what: str) -> None:
        """先报告「生成了」，再说清楚浏览器到底开没开——别骗人。"""
        from ..report.render import open_in_browser
        if open_in_browser(path, self.app.cfg):
            QMessageBox.information(self, what, f"已生成并打开：\n{path.name}")
            return
        QMessageBox.warning(
            self, what,
            f"已生成，但浏览器没能自动打开。\n\n文件位置：\n{path}\n\n"
            "可以直接到上面这个路径双击打开；也可以在设置里指定 report.browser。")

    def _open_weekly(self) -> None:
        self._open_period("weekly")

    def _open_monthly(self) -> None:
        self._open_period("monthly")

    def _open_period(self, kind: str) -> None:
        from ..report.summary import render_period
        try:
            path = render_period(self.app.cfg, self.app.store, kind, open_browser=False)
            self._after_render(path, "汇总")
        except Exception as exc:
            QMessageBox.warning(self, "生成失败", str(exc))

    def _open_settings(self) -> None:
        from .settings import SettingsDialog
        dlg = SettingsDialog(self.app.cfg, self)
        if dlg.exec():
            dlg.apply()

    def _toggle_autostart(self) -> None:
        try:
            if self.chk_autostart.isChecked():
                autostart.install()
            else:
                autostart.uninstall()
            self.chk_autostart.setChecked(autostart.is_installed())
        except Exception as exc:
            self.chk_autostart.setChecked(autostart.is_installed())
            QMessageBox.warning(self, "开机自启设置失败", str(exc)[:400])

    def _save_report_time(self, t: QTime) -> None:
        self.app.cfg["report"]["time"] = t.toString("HH:mm")
        config.save(self.app.cfg)
        log.info("日报时间改为 %s", self.app.cfg["report"]["time"])

    def _quit(self) -> None:
        if QMessageBox.question(self, "退出余光", "退出后不再记录，确定吗？") != QMessageBox.Yes:
            return
        self.app.stop()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # 关窗口只是藏起来，后台继续记录
    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
