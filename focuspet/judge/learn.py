# -*- coding: utf-8 -*-
"""纠错回流（设计方案 3.6）。

三类用途按性价比排序：应用级白名单 > 关键词规则 > 提示词样例。
不做在线微调——样本量不够、成本高、可控性差，个人工具完全没必要。

2026-11-12：以前只写 correction 表、不改 block，等于改了也不显示。
现在真正改分类，并且可以把这次纠正固化成一条规则，避免同样的窗口天天错。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .. import config
from ..log import get

log = get("learn")


def _rule_keyword(title: str) -> str:
    """从窗口标题里取一个能当 title_contains 的片段。

    浏览器标题里的「和另外 N 个页面」「- 个人 - Microsoft Edge」都是会变的，
    带上就会永远匹配不上，所以先剥掉再取站点/文档名。
    """
    t = (title or "").strip()
    t = re.sub(r"\s*和另外\s*\d+\s*个页面", "", t)
    for sep in (" - ", " · ", " — ", " | "):
        if sep in t:
            t = t.split(sep)[0].strip()
            break
    return t.strip()[:16]


class Corrections:
    def __init__(self, store):
        self.store = store

    def apply(self, block_id: int, new_cat: str, scope: str = "day",
              make_rule: bool = False, ruleset=None) -> dict:
        """改一个时间块的分类；make_rule=True 时顺手把它固化成规则。"""
        day = time.strftime("%Y-%m-%d", time.localtime())
        blocks = {int(b["id"]): dict(b) for b in self.store.blocks(day)}
        block = blocks.get(int(block_id))
        if block is None:
            raise ValueError(f"找不到时间块 #{block_id}（只支持改今天的）")
        old = block["category"]

        self.store.set_block_category(int(block_id), new_cat)
        self.store._exec(
            "INSERT INTO correction(block_id, old_cat, new_cat, scope, created_ts)"
            " VALUES(?,?,?,?,?)",
            (int(block_id), old, new_cat, scope, int(time.time())))

        rule = None
        if make_rule:
            rule = self._append_rule(block, new_cat)
            if rule and ruleset is not None:
                ruleset.load()          # 立即生效，不用重启

        log.info("纠错：block=%s %s → %s%s", block_id, old, new_cat,
                 "（已加规则）" if rule else "")
        return {"block_id": int(block_id), "old": old, "new": new_cat,
                "scope": scope, "rule": rule}

    def _append_rule(self, block: dict, cat: str) -> dict | None:
        """按这段时间里出现最多的进程/标题生成一条规则，追加到 rules.yaml。"""
        proc, title, n = self.store.dominant_window(block["start_ts"], block["end_ts"])
        if not proc:
            return None
        kw = _rule_keyword(title)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        rid = f"learned_{stamp}"
        when = f'{{proc: ["{proc}"]'
        if kw:
            when += f', title_contains: ["{kw}"]'
        when += "}"
        activity = "（手动纠正）"
        block_text = (
            f"\n  # {time.strftime('%Y-%m-%d')} 手动纠错（block {block['id']}）\n"
            f"  - id: {rid}\n"
            f"    note: 手动纠错：{proc}{('「' + kw + '」') if kw else ''}\n"
            f"    when: {when}\n"
            f"    then: {{category: {cat}, weight: 0.85, activity: {activity}}}\n")
        path = Path(config.RULES_PATH)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(block_text)
        except OSError as exc:
            log.warning("写规则失败：%s", exc)
            return None
        return {"id": rid, "proc": proc, "keyword": kw, "category": cat}

    def stats(self) -> dict:
        rows = self.store.conn.execute(
            "SELECT new_cat, COUNT(*) c FROM correction GROUP BY new_cat").fetchall()
        return {r["new_cat"]: r["c"] for r in rows}
