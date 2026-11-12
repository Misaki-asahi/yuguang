# -*- coding: utf-8 -*-
"""SQLite 落库（设计方案 14.2）。

一条硬约定：写失败不能丢数据。所有写入都有 jsonl 兜底，下次启动补跑。
另一条：采集线程永远不阻塞在网络或报表上——这里没有长事务，WAL 模式保证读写不互斥。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .. import config
from ..log import get

log = get("store")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS sample (
  id        INTEGER PRIMARY KEY,
  ts        INTEGER NOT NULL,
  proc      TEXT,
  title     TEXT,
  shot      TEXT,
  dhash     INTEGER,
  idle      INTEGER DEFAULT 0,
  sensitive INTEGER DEFAULT 0,
  settled   INTEGER DEFAULT 1   -- 0 = 刚切过去、标题可能还没更新，只记不用
);
CREATE INDEX IF NOT EXISTS idx_sample_ts ON sample(ts);

CREATE TABLE IF NOT EXISTS analysis (
  id          INTEGER PRIMARY KEY,
  batch_id    TEXT NOT NULL,
  date        TEXT NOT NULL,
  start_ts    INTEGER NOT NULL,
  end_ts      INTEGER NOT NULL,
  activity    TEXT,
  category    TEXT NOT NULL,
  on_task     INTEGER,
  confidence  REAL,
  evidence    TEXT,
  source      TEXT,
  created_ts  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_date ON analysis(date, start_ts);

CREATE TABLE IF NOT EXISTS block (
  id         INTEGER PRIMARY KEY,
  date       TEXT NOT NULL,
  start_ts   INTEGER NOT NULL,
  end_ts     INTEGER NOT NULL,
  category   TEXT NOT NULL,
  activity   TEXT,
  on_task    INTEGER,
  confidence REAL,
  shot_ref   TEXT
);
CREATE INDEX IF NOT EXISTS idx_block_date ON block(date, start_ts);

CREATE TABLE IF NOT EXISTS goal (
  id         INTEGER PRIMARY KEY,
  date       TEXT NOT NULL,
  text       TEXT NOT NULL,
  kind       TEXT DEFAULT 'auto',   -- work / study / leisure / life / auto
  started_ts INTEGER NOT NULL,
  ended_ts   INTEGER,
  status     TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS intervention (
  id       INTEGER PRIMARY KEY,
  ts       INTEGER NOT NULL,
  level    INTEGER,
  rule_id  TEXT,
  reason   TEXT,
  action   TEXT
);
CREATE INDEX IF NOT EXISTS idx_intervention_ts ON intervention(ts);

CREATE TABLE IF NOT EXISTS correction (
  id         INTEGER PRIMARY KEY,
  block_id   INTEGER,
  old_cat    TEXT,
  new_cat    TEXT,
  scope      TEXT,
  created_ts INTEGER
);

CREATE TABLE IF NOT EXISTS kv (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS vlm_unknown (
  id         INTEGER PRIMARY KEY,
  day        TEXT NOT NULL,
  ts         INTEGER NOT NULL,
  proc       TEXT,
  title      TEXT,
  category   TEXT,
  confidence REAL,
  activity   TEXT
);
CREATE INDEX IF NOT EXISTS idx_vlm_unknown_day ON vlm_unknown(day);

CREATE TABLE IF NOT EXISTS vlm_review (
  id         INTEGER PRIMARY KEY,
  day        TEXT NOT NULL,
  block_id   INTEGER,
  old_cat    TEXT,
  new_cat    TEXT,
  confidence REAL,
  ts         INTEGER
);

CREATE TABLE IF NOT EXISTS rule_conflict (
  id         INTEGER PRIMARY KEY,
  day        TEXT NOT NULL,
  block_id   INTEGER,
  rule_cat   TEXT,
  model_cat  TEXT,
  proc       TEXT,
  title      TEXT,
  confidence REAL,
  ts         INTEGER
);
"""


def day_of(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def day_bounds(day: str) -> tuple[int, int]:
    t = time.strptime(day, "%Y-%m-%d")
    start = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return start, start + 86400


class Store:
    def __init__(self, path: Path | str | None = None):
        config.ensure_dirs()
        self.path = Path(path or config.DB_PATH)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()
            # 老库补列：settled 是后加的，没有就加上，不影响已有行
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(sample)")}
            if "settled" not in cols:
                try:
                    self.conn.execute("ALTER TABLE sample ADD COLUMN settled INTEGER DEFAULT 1")
                    self.conn.commit()
                    log.info("sample 表补上 settled 列")
                except sqlite3.Error:
                    pass
            # 老库补列：目标类型 kind 是后加的
            gcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(goal)")}
            if "kind" not in gcols:
                try:
                    self.conn.execute("ALTER TABLE goal ADD COLUMN kind TEXT DEFAULT 'auto'")
                    self.conn.commit()
                    log.info("goal 表补上 kind 列")
                except sqlite3.Error:
                    pass
        try:
            n = self.replay_pending()
            if n:
                log.info("补回上次写失败的采样 %d 条", n)
        except Exception:
            log.warning("兜底数据回放失败，已跳过")

    # ------------------------------------------------------------ 通用
    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------ sample
    @staticmethod
    def _s64(v):
        """dHash 是 64 位无符号数，SQLite 的 INTEGER 只有 63 位可用，必须折成有符号。"""
        if v is None:
            return None
        v &= 0xFFFFFFFFFFFFFFFF
        return v - (1 << 64) if v >= (1 << 63) else v

    def insert_sample(self, ts: int, proc: str, title: str, shot: str | None,
                      dhash: int | None, idle: int = 0,
                      sensitive: int = 0, settled: int = 1) -> int | None:
        try:
            cur = self._exec(
                "INSERT INTO sample(ts, proc, title, shot, dhash, idle, sensitive, settled)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (int(ts), proc, title, shot, self._s64(dhash), int(idle),
                 int(sensitive), int(settled)),
            )
            return cur.lastrowid
        except Exception as exc:
            self._spill({"kind": "sample", "ts": int(ts), "proc": proc, "title": title,
                         "shot": shot, "dhash": dhash, "idle": idle,
                         "sensitive": sensitive, "settled": settled, "error": str(exc)})
            return None

    def replay_pending(self) -> int:
        """把上次写失败落到 jsonl 的采样补回来，恢复后不丢数据（4 节降级表）。"""
        path = Path(config.PENDING_JSONL)
        if not path.exists():
            return 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        left, ok = [], 0
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") != "sample":
                left.append(line)
                continue
            got = self.insert_sample(row.get("ts", 0), row.get("proc", ""),
                                     row.get("title", ""), row.get("shot"),
                                     row.get("dhash"), row.get("idle", 0),
                                     row.get("sensitive", 0), row.get("settled", 1))
            if got:
                ok += 1
            else:
                left.append(line)
        if left:
            path.write_text("\n".join(left) + "\n", encoding="utf-8")
        elif path.exists():
            path.unlink()
        return ok

    def _spill(self, obj: dict) -> None:
        try:
            with open(config.PENDING_JSONL, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            log.error("写入兜底 jsonl 失败，本条数据丢失")

    def bulk_insert_samples(self, rows: list[tuple]) -> int:
        """演示数据与补跑用：一次事务写多行，避免逐条 commit。"""
        if not rows:
            return 0
        fixed = [tuple(r) + (1,) * (8 - len(r)) for r in rows]   # 补齐 settled 列
        with self._lock:
            self.conn.executemany(
                "INSERT INTO sample(ts, proc, title, shot, dhash, idle, sensitive, settled)"
                " VALUES(?,?,?,?,?,?,?,?)", fixed)
            self.conn.commit()
        return len(rows)

    def clear_day(self, day: str) -> None:
        s, e = day_bounds(day)
        with self._lock:
            self.conn.execute("DELETE FROM sample WHERE ts >= ? AND ts < ?", (s, e))
            self.conn.execute("DELETE FROM analysis WHERE date = ?", (day,))
            self.conn.execute("DELETE FROM block WHERE date = ?", (day,))
            self.conn.execute("DELETE FROM goal WHERE date = ?", (day,))
            self.conn.execute("DELETE FROM intervention WHERE ts >= ? AND ts < ?", (s, e))
            self.conn.commit()

    def samples(self, start_ts: int, end_ts: int) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(
                "SELECT * FROM sample WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start_ts, end_ts),
            ))

    def last_shot_ts(self) -> int:
        """最近一张截图的时刻。重启时用它续上节奏，避免每次启动都补拍一张。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT MAX(ts) m FROM sample WHERE shot IS NOT NULL").fetchone()
        return int(row["m"] or 0) if row else 0

    def sample_count(self, day: str) -> int:
        s, e = day_bounds(day)
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM sample WHERE ts >= ? AND ts < ?", (s, e)
            ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------ analysis
    def insert_analysis(self, batch_id: str, rows: list[dict]) -> None:
        now = int(time.time())
        with self._lock:
            for r in rows:
                self.conn.execute(
                    "INSERT INTO analysis(batch_id, date, start_ts, end_ts, activity,"
                    " category, on_task, confidence, evidence, source, created_ts)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (batch_id, day_of(r["start_ts"]), int(r["start_ts"]),
                     int(r["end_ts"]), r.get("activity", ""), r["category"],
                     r.get("on_task"), float(r.get("confidence", 0)),
                     r.get("evidence", ""), r.get("source", "rules"), now),
                )
            self.conn.commit()

    def analyses(self, day: str) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(
                "SELECT * FROM analysis WHERE date = ? ORDER BY start_ts", (day,)
            ))

    def analysis_window(self, ws: int, we: int) -> list[sqlite3.Row]:
        """某个批次窗口里的分析行（补洞前后对比用）。"""
        with self._lock:
            return list(self.conn.execute(
                "SELECT * FROM analysis WHERE start_ts >= ? AND start_ts < ?"
                " ORDER BY start_ts", (int(ws), int(we))))

    def restore_analysis(self, ws: int, we: int, rows: list) -> None:
        """把窗口里的分析行整体换回旧的那份（补洞没变好时回滚）。"""
        with self._lock:
            self.conn.execute(
                "DELETE FROM analysis WHERE start_ts >= ? AND start_ts < ?",
                (int(ws), int(we)))
            for r in rows:
                self.conn.execute(
                    "INSERT INTO analysis(batch_id, date, start_ts, end_ts, activity, category,"
                    " on_task, confidence, evidence, source, created_ts)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (r["batch_id"], r["date"], r["start_ts"], r["end_ts"], r["activity"],
                     r["category"], r["on_task"], r["confidence"], r["evidence"],
                     r["source"], r["created_ts"]))
            self.conn.commit()

    def last_batch_end(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT MAX(end_ts) m FROM analysis").fetchone()
        return int(row["m"] or 0)

    # ------------------------------------------------------------ block
    def replace_blocks(self, day: str, blocks: list[dict]) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM block WHERE date = ?", (day,))
            for b in blocks:
                self.conn.execute(
                    "INSERT INTO block(date, start_ts, end_ts, category, activity,"
                    " on_task, confidence, shot_ref) VALUES(?,?,?,?,?,?,?,?)",
                    (day, int(b["start_ts"]), int(b["end_ts"]), b["category"],
                     b.get("activity", ""), b.get("on_task"),
                     float(b.get("confidence", 0) or 0), b.get("shot_ref")),
                )
            self.conn.commit()

    def blocks(self, day: str) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(
                "SELECT * FROM block WHERE date = ? ORDER BY start_ts", (day,)
            ))

    def set_block_category(self, block_id: int, category: str) -> None:
        """改一个时间块的分类（同时把它覆盖的 analysis 行一起改，否则下次 rebuild 会抹掉）。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT start_ts, end_ts FROM block WHERE id=?", (int(block_id),)).fetchone()
            if row is None:
                return
            self.conn.execute("UPDATE block SET category=? WHERE id=?",
                              (category, int(block_id)))
            self.conn.execute(
                "UPDATE analysis SET category=? WHERE start_ts>=? AND start_ts<?",
                (category, int(row["start_ts"]), int(row["end_ts"])))
            self.conn.commit()

    def set_analysis_category(self, start_ts: int, end_ts: int, category: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE analysis SET category=? WHERE start_ts>=? AND start_ts<?",
                (category, int(start_ts), int(end_ts)))
            self.conn.commit()

    def set_block_on_task(self, start_ts: int, end_ts: int, on_task: bool) -> int:
        """目标语义匹配用：把某段时间块的 on_task 改成模型判断的结果。"""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE block SET on_task=? WHERE start_ts>=? AND start_ts<?",
                (1 if on_task else 0, int(start_ts), int(end_ts)))
            self.conn.execute(
                "UPDATE analysis SET on_task=? WHERE start_ts>=? AND start_ts<?",
                (1 if on_task else 0, int(start_ts), int(end_ts)))
            self.conn.commit()
            return cur.rowcount

    def dominant_window(self, start_ts: int, end_ts: int) -> tuple[str, str, int]:
        """这段时间里出现最多的 (进程, 标题, 次数)——纠错生成规则用。"""
        with self._lock:
            rows = list(self.conn.execute(
                "SELECT proc, title, COUNT(*) c FROM sample"
                " WHERE ts>=? AND ts<? AND proc IS NOT NULL AND proc<>''"
                " GROUP BY proc, title ORDER BY c DESC LIMIT 1",
                (int(start_ts), int(end_ts))))
        if not rows:
            return "", "", 0
        r = rows[0]
        return (r["proc"] or ""), (r["title"] or ""), int(r["c"])

    # ------------------------------------------------------------ goal
    def set_goal(self, text: str, ts: int | None = None, kind: str = "auto") -> int:
        ts = int(ts or time.time())
        day = day_of(ts)
        with self._lock:
            self.conn.execute(
                "UPDATE goal SET status='done', ended_ts=? WHERE date=? AND status='active'",
                (ts, day))
            cur = self.conn.execute(
                "INSERT INTO goal(date, text, kind, started_ts, status) VALUES(?,?,?,?,'active')",
                (day, text, (kind or "auto"), ts))
            self.conn.commit()
            return cur.lastrowid

    def last_goal_before(self, day: str) -> str:
        """今天之前最近一次声明过的目标，用于「沿用上次」。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT text FROM goal WHERE date < ? ORDER BY id DESC LIMIT 1",
                (day,)).fetchone()
        return row["text"] if row else ""

    def goal_of_day(self, day: str) -> sqlite3.Row | None:
        """当天最后声明的那条目标（不管几点声明）——目标语义匹配用它。"""
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM goal WHERE date=? ORDER BY started_ts DESC, id DESC LIMIT 1",
                (day,)).fetchone()

    def active_goal(self, ts: int | None = None) -> sqlite3.Row | None:
        """ts 这一刻生效的目标；不给 ts 就是「现在」。

        必须比较 started_ts：目标声明之前的那几段，不能事后被算成「在任务上」。
        —— `--reclassify` 一个历史日期时，下午才写的目标不该套到上午去。
        （status 只表示「被后一条目标取代」，所以这里不按 status 过滤，
         而是取 started_ts 最新的那一条。）
        """
        when = int(ts or time.time())
        day = day_of(when)
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM goal WHERE date=? AND started_ts <= ?"
                " ORDER BY started_ts DESC, id DESC LIMIT 1", (day, when)).fetchone()

    # ------------------------------------------------------------ 模型补洞记录
    def record_vlm_unknown(self, rows: list[dict]) -> None:
        """记下「规则没认出来、由模型补上」的窗口，`--suggest-rules` 用它归纳规则。"""
        if not rows:
            return
        with self._lock:
            for r in rows:
                self.conn.execute(
                    "INSERT INTO vlm_unknown(day, ts, proc, title, category,"
                    " confidence, activity) VALUES(?,?,?,?,?,?,?)",
                    (day_of(r["ts"]), int(r["ts"]), r.get("proc", ""),
                     r.get("title", ""), r.get("category", ""),
                     float(r.get("confidence") or 0), r.get("activity", "")))
            self.conn.commit()

    def vlm_unknowns(self, days: int = 7) -> list[sqlite3.Row]:
        since = day_of(time.time() - max(1, days) * 86400)
        with self._lock:
            return list(self.conn.execute(
                "SELECT * FROM vlm_unknown WHERE day >= ? ORDER BY ts", (since,)))

    # ------------------------------------------------------------ intervention
    def add_intervention(self, level: int, rule_id: str, reason: str,
                         action: str = "") -> None:
        self._exec(
            "INSERT INTO intervention(ts, level, rule_id, reason, action)"
            " VALUES(?,?,?,?,?)",
            (int(time.time()), int(level), rule_id, reason, action))

    def interventions(self, day: str) -> list[sqlite3.Row]:
        s, e = day_bounds(day)
        with self._lock:
            return list(self.conn.execute(
                "SELECT * FROM intervention WHERE ts >= ? AND ts < ? ORDER BY ts",
                (s, e)))

    # ------------------------------------------------------------ kv
    def kv_get(self, key: str, default=None):
        with self._lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def kv_set(self, key: str, value) -> None:
        self._exec("INSERT INTO kv(key, value) VALUES(?,?)"
                   " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False)))

    # ------------------------------------------------------------ 维护
    def prune(self, samples_days: int = 30) -> int:
        cutoff = int(time.time()) - samples_days * 86400
        cur = self._exec("DELETE FROM sample WHERE ts < ?", (cutoff,))
        return cur.rowcount or 0
