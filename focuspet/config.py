# -*- coding: utf-8 -*-
"""配置加载与路径约定。

设计原则（见设计方案 15.4）：配置项控制在 20 项量级，全部有内置默认值；
config.yaml 缺失或损坏时用默认值重建，旧文件改名备份，绝不让程序起不来。
"""
from __future__ import annotations

import copy
import os
import shutil
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent          # focuspet/
CONFIG_PATH = ROOT / "config.yaml"
RULES_PATH = ROOT / "config" / "rules.yaml"

DATA = ROOT / "data"
SHOTS = DATA / "shots"
REPORTS = DATA / "reports"
LOGS = DATA / "logs"
DB_PATH = DATA / "focuspet.db"
DEMO_DB = DATA / "demo.db"          # 演示数据单独一个库，绝不碰真实数据
HEARTBEAT = DATA / "heartbeat.txt"
PENDING_JSONL = DATA / "pending.jsonl"

DEFAULTS = {
    "app": {
        "name": "余光",
        "version": "0.3.0",
    },
    "capture": {
        "window_poll_sec": 5,
        "shot_interval_sec": 600,      # 10 分钟一张（2026-11-06 从 60 秒放宽）
        "shot_on_window_change": False,  # 切窗口不再补拍，否则上面那个间隔形同虚设
        "idle_threshold_sec": 300,
        "max_shot_side": 1280,
        "jpeg_quality": 70,
        "screens": [1],
    },
    "analyze": {
        "batch_minutes": 15,
        "mode": "cloud",            # cloud | local | rules_only
        "endpoint": "",             # 兼容 OpenAI 协议的地址
        "model": "",
        "api_key_env": "FOCUSPET_KEY",
        "min_confidence": 0.6,
        "daily_budget_cny": 2.0,
        "retry": 2,
        "timeout_sec": 30,
    },
    "judge": {
        "enabled": True,
        "off_task_minutes": 3,
        "cooldown_minutes": 10,
        "l2_daily_cap": 12,
        "l3_daily_cap": 5,
        "rest_minutes": 10,
        "escalate_after_minutes": [2, 3],
    },
    "privacy": {
        "mode": "masked",           # local | masked | meta_only
        "strip_crop": [0, 0, 1.0, 0.94],
        "sensitive_procs": [
            "KeePass.exe", "1Password.exe", "Bitwarden.exe", "KeePassXC.exe",
        ],
        "sensitive_keywords": ["密码", "转账", "工资", "身份证", "银行卡"],
    },
    "retention": {
        "shots_days": 7,          # 截图只留一周（磁盘大头）
        "samples_days": 30,       # 明细留久一点，几 MB 而已
        "logs_days": 7,
        "auto_clean": True,       # 启动时 + 每天出完日报后自动清
    },
    "ui": {
        "pet_enabled": True,
        "pet_position": [1720, 900],
        "pet_scale": 1.0,
        "theme": "light",
        "autostart": True,
    },
    "report": {
        "time": "22:00",
        "weekly_day": 6,           # 0=周一 … 6=周日，默认周日晚上出周报
        "weekly_time": "21:00",
        "monthly_time": "21:00",   # 每月最后一天这个点出月报
        "open_browser": True,
        "browser": "",             # 留空则自动找 Edge / Chrome / Firefox
    },
}


def _merge(base: dict, override: dict) -> dict:
    """递归合并，override 覆盖 base；只认 base 里已有的键，防止配置膨胀。"""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def ensure_dirs() -> None:
    for d in (DATA, SHOTS, REPORTS, LOGS, RULES_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)


def load(path: Path | str | None = None) -> dict:
    """读取配置；文件损坏时备份并回退默认值。"""
    ensure_dirs()
    path = Path(path) if path else CONFIG_PATH
    if not path.exists():
        cfg = copy.deepcopy(DEFAULTS)
        save(cfg, path)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raise ValueError("配置文件顶层必须是映射")
        return _merge(DEFAULTS, raw)
    except Exception:
        backup = path.with_suffix(f".broken-{time.strftime('%Y%m%d-%H%M%S')}.yaml")
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass
        cfg = copy.deepcopy(DEFAULTS)
        save(cfg, path)
        return cfg


def save(cfg: dict, path: Path | str | None = None) -> None:
    path = Path(path) if path else CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def env_key(cfg: dict) -> str:
    """API Key 只从环境变量读，不写进配置文件（附录 C 的约定）。"""
    return os.environ.get(cfg["analyze"].get("api_key_env", "FOCUSPET_KEY"), "").strip()


def day_dir(day: str) -> Path:
    """截图按天归档：data/shots/YYYY-MM-DD/。"""
    p = SHOTS / day
    p.mkdir(parents=True, exist_ok=True)
    return p
