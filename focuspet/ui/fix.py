# -*- coding: utf-8 -*-
"""纠错对话框：把今天判错的段改对，并可以顺手固化成规则。

只列今天「未识别」和低置信度（<0.6）的段——高置信度的段默认不动，
免得手滑把已经判对的东西改坏。
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..analyze.aggregate import CATEGORIES, label
from ..capture.store import day_of
from ..judge.learn import Corrections

COL_CATS = [c for c in CATEGORIES if c != "gap"]


class FixDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("纠错 · 把判错的段改对")
        self.resize(860, 540)
        self._blocks: list[dict] = []

        root = QVBoxLayout(self)
        tip = QLabel("只列今天的「未识别」和低置信度（<0.6）的段。改完点保存；"
                     "勾了「加规则」的会写进 config/rules.yaml，下次同类窗口自动认对。")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["时间", "进程", "窗口标题", "现在", "改成", "加规则"])
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 320)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 110)
        root.addWidget(self.table)

        self.lbl = QLabel("")
        root.addWidget(self.lbl)

        row = QHBoxLayout()
        row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        self.btn_save = QPushButton("保存")
        self.btn_save.clicked.connect(self._save)
        row.addWidget(btn_close)
        row.addWidget(self.btn_save)
        root.addLayout(row)

        self._load()

    # ---------------------------------------------------------------- 载入
    def _load(self) -> None:
        day = day_of(time.time())
        blocks = [dict(b) for b in self.app.store.blocks(day)]
        rows = [b for b in blocks
                if b["category"] != "gap"
                and (b["category"] == "unknown" or float(b["confidence"] or 0) < 0.6)]
        self._blocks = rows[:80]
        self.table.setRowCount(len(self._blocks))
        for i, b in enumerate(self._blocks):
            proc, title, _ = self.app.store.dominant_window(b["start_ts"], b["end_ts"])
            self.table.setItem(i, 0, QTableWidgetItem(
                f'{time.strftime("%H:%M", time.localtime(b["start_ts"]))}-'
                f'{time.strftime("%H:%M", time.localtime(b["end_ts"]))}'))
            self.table.setItem(i, 1, QTableWidgetItem(proc))
            self.table.setItem(i, 2, QTableWidgetItem((title or "")[:60]))
            self.table.setItem(i, 3, QTableWidgetItem(label(b["category"])))
            combo = QComboBox()
            for c in COL_CATS:
                combo.addItem(label(c), c)
            idx = combo.findData(b["category"])
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.table.setCellWidget(i, 4, combo)
            chk = QCheckBox("")
            chk.setChecked(True)
            self.table.setCellWidget(i, 5, chk)
        self.lbl.setText(f"共 {len(self._blocks)} 段；没有要改的就直接关掉。")

    # ---------------------------------------------------------------- 保存
    def _save(self) -> None:
        corr = Corrections(self.app.store)
        changed = 0
        rules = getattr(self.app, "rules", None)
        for i, b in enumerate(self._blocks):
            combo = self.table.cellWidget(i, 4)
            chk = self.table.cellWidget(i, 5)
            new_cat = combo.currentData()
            if new_cat == b["category"]:
                continue
            try:
                corr.apply(b["id"], new_cat,
                           make_rule=bool(chk and chk.isChecked()), ruleset=rules)
                changed += 1
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))
                break
        QMessageBox.information(self, "纠错", f"已修改 {changed} 段。")
        self._load()
