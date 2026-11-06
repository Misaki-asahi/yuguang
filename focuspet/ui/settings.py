# -*- coding: utf-8 -*-
"""设置面板（设计方案 7 节：只有四个界面，配置项控制在 20 项内）。"""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSpinBox, QVBoxLayout)

from .. import config, maintenance

PRIVACY = [("masked", "脱敏上云（默认：裁掉任务栏再发送）"),
           ("local", "全本地（只送本地模型，不联网）"),
           ("meta_only", "只记元数据（完全不截图）")]


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("余光 · 设置")
        self.setMinimumWidth(520)

        form = QFormLayout()
        form.setSpacing(10)

        self.privacy = QComboBox()
        for key, text in PRIVACY:
            self.privacy.addItem(text, key)
        idx = max(0, self.privacy.findData(cfg["privacy"].get("mode", "masked")))
        self.privacy.setCurrentIndex(idx)
        form.addRow("隐私档", self.privacy)

        self.interval = QSpinBox()
        self.interval.setRange(15, 3600)
        self.interval.setSingleStep(30)
        self.interval.setSuffix(" 秒")
        self.interval.setValue(int(cfg["capture"].get("shot_interval_sec", 600)))
        form.addRow("截图间隔", self.interval)

        self.on_change = QCheckBox("切换窗口时补一张（会突破上面的间隔）")
        self.on_change.setChecked(bool(cfg["capture"].get("shot_on_window_change", False)))
        form.addRow("", self.on_change)

        self.batch = QComboBox()
        for m in (5, 10, 15, 30):
            self.batch.addItem(f"{m} 分钟", m)
        self.batch.setCurrentIndex(max(0, self.batch.findData(
            int(cfg["analyze"].get("batch_minutes", 15)))))
        form.addRow("分析批次", self.batch)

        self.off_task = QSpinBox()
        self.off_task.setRange(1, 30)
        self.off_task.setSuffix(" 分钟")
        self.off_task.setValue(int(cfg["judge"].get("off_task_minutes", 3)))
        form.addRow("离题判定阈值", self.off_task)

        self.cooldown = QSpinBox()
        self.cooldown.setRange(5, 120)
        self.cooldown.setSuffix(" 分钟")
        self.cooldown.setValue(int(cfg["judge"].get("cooldown_minutes", 10)))
        form.addRow("提醒冷却", self.cooldown)

        self.budget = QDoubleSpinBox()
        self.budget.setRange(0.0, 50.0)
        self.budget.setSingleStep(0.5)
        self.budget.setPrefix("¥ ")
        self.budget.setValue(float(cfg["analyze"].get("daily_budget_cny", 2.0)))
        form.addRow("每日预算", self.budget)

        self.pet = QCheckBox("显示桌宠")
        self.pet.setChecked(bool(cfg["ui"].get("pet_enabled", True)))
        form.addRow("", self.pet)

        # ---------------------------------------------------------- 数据与缓存
        data_box = QGroupBox("数据与缓存")
        dform = QFormLayout(data_box)
        dform.setSpacing(10)

        self.shot_days = QSpinBox()
        self.shot_days.setRange(1, 365)
        self.shot_days.setSuffix(" 天")
        self.shot_days.setValue(int(cfg["retention"].get("shots_days", 7)))
        dform.addRow("截图保留", self.shot_days)

        self.sample_days = QSpinBox()
        self.sample_days.setRange(1, 3650)
        self.sample_days.setSuffix(" 天")
        self.sample_days.setValue(int(cfg["retention"].get("samples_days", 30)))
        dform.addRow("明细保留", self.sample_days)

        self.auto_clean = QCheckBox("启动时和每天出日报后自动清理")
        self.auto_clean.setChecked(bool(cfg["retention"].get("auto_clean", True)))
        dform.addRow("", self.auto_clean)

        row = QHBoxLayout()
        btn_shots = QPushButton("查看截图")
        btn_shots.clicked.connect(self._open_shots)
        btn_data = QPushButton("打开工作区目录")
        btn_data.clicked.connect(self._open_workspace)
        btn_clean = QPushButton("立即清理")
        btn_clean.clicked.connect(self._cleanup_now)
        for b in (btn_shots, btn_data, btn_clean):
            row.addWidget(b)
        dform.addRow(row)

        hint = QLabel("改完点「保存」生效；配置文件在 focuspet/config.yaml。")
        hint.setStyleSheet("color:#8A94A3;font-size:12px")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(data_box)
        box.addWidget(hint)
        box.addWidget(buttons)

    # ------------------------------------------------------------ 数据按钮
    def _open_shots(self) -> None:
        day = time.strftime("%Y-%m-%d")
        today = Path(config.SHOTS) / day
        target = today if today.exists() else Path(config.SHOTS)
        if not target.exists():
            QMessageBox.information(self, "还没有截图",
                                    "这个时间点还没有截图，先让余光跑一会儿。")
            return
        try:
            os.startfile(str(target))
        except Exception as exc:
            QMessageBox.warning(self, "打不开", f"{target}\n{exc}")

    def _open_workspace(self) -> None:
        root = Path(config.ROOT).parent           # 含 focuspet/ 的那一层
        try:
            os.startfile(str(root))
        except Exception as exc:
            QMessageBox.warning(self, "打不开", f"{root}\n{exc}")

    def _cleanup_now(self) -> None:
        self._sync_retention()
        try:
            res = maintenance.clean_all(self.cfg)
        except Exception as exc:
            QMessageBox.warning(self, "清理失败", str(exc))
            return
        QMessageBox.information(
            self, "清理完成",
            f"删除截图目录 {res['shot_days_removed']} 个、"
            f"日志 {res['log_files_removed']} 个、明细 {res['samples_removed']} 条\n"
            f"释放 {maintenance.human_size(res['freed_bytes'])}，"
            f"保留最近 {res['kept_days']} 天。")

    # ------------------------------------------------------------ 保存
    def _sync_retention(self) -> None:
        self.cfg["retention"]["shots_days"] = self.shot_days.value()
        self.cfg["retention"]["samples_days"] = self.sample_days.value()
        self.cfg["retention"]["auto_clean"] = self.auto_clean.isChecked()

    def apply(self) -> None:
        self.cfg["privacy"]["mode"] = self.privacy.currentData()
        self.cfg["capture"]["shot_interval_sec"] = self.interval.value()
        self.cfg["capture"]["shot_on_window_change"] = self.on_change.isChecked()
        self.cfg["analyze"]["batch_minutes"] = self.batch.currentData()
        self.cfg["judge"]["off_task_minutes"] = self.off_task.value()
        self.cfg["judge"]["cooldown_minutes"] = self.cooldown.value()
        self.cfg["analyze"]["daily_budget_cny"] = self.budget.value()
        self.cfg["ui"]["pet_enabled"] = self.pet.isChecked()
        self._sync_retention()
        config.save(self.cfg)
