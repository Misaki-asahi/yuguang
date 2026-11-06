# -*- coding: utf-8 -*-
"""纠错回流（设计方案 3.6）。

三类用途按性价比排序：应用级白名单 > 关键词规则 > 提示词样例。
不做在线微调——样本量不够、成本高、可控性差，个人工具完全没必要。
"""
from __future__ import annotations

import time

from ..log import get

log = get("learn")


class Corrections:
    def __init__(self, store):
        self.store = store

    def apply(self, block_id: int, new_cat: str, scope: str = "day") -> dict:
        day = time.strftime("%Y-%m-%d", time.localtime())
        blocks = {b["id"]: b for b in self.store.blocks(day)}
        block = blocks.get(int(block_id))
        old = block["category"] if block else ""

        self.store._exec(
            "INSERT INTO correction(block_id, old_cat, new_cat, scope, created_ts)"
            " VALUES(?,?,?,?,?)",
            (int(block_id), old, new_cat, scope, int(time.time())))

        if block and old and new_cat in ("deep_work", "learning", "shallow_work"):
            # 最有效的一类：把这个应用/关键词记进当日豁免，下次直接不提醒
            key = f"exempt:{day}"
            exempt = self.store.kv_get(key, []) or []
            token = (block["activity"] or "").strip()
            if token and token not in exempt:
                exempt.append(token)
                self.store.kv_set(key, exempt)

        log.info("纠错记录：block=%s %s → %s（%s）", block_id, old, new_cat, scope)
        return {"block_id": int(block_id), "old": old, "new": new_cat, "scope": scope}

    def stats(self) -> dict:
        rows = self.store.conn.execute(
            "SELECT new_cat, COUNT(*) c FROM correction GROUP BY new_cat").fetchall()
        return {r["new_cat"]: r["c"] for r in rows}
