# -*- coding: utf-8 -*-
"""动作包 manifest 的读取与校验（纯数据，不碰 Qt）。

manifest 结构见 focuspet/assets/pet/juyuan-pack/manifest.json：
    canvas   画布逻辑尺寸与锚点（anchor [0.5, 1.0] = 脚底中心）
    states   状态 -> 图集文件、列数/行数/帧数、fps、是否循环
    events   余光事件 -> 可选状态列表（随机挑一个，避免每次都同一张脸）
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

# 默认动作包位置（和静态立绘 pose.png 同级目录下的 juyuan-pack/）
DEFAULT_PACK = Path(__file__).resolve().parents[1] / "assets" / "pet" / "juyuan-pack"


@dataclass
class State:
    key: str
    name: str
    atlas: Path
    columns: int
    rows: int
    frames: int
    fps: int
    loop: bool = True
    mirror: bool = True

    @property
    def interval_ms(self) -> int:
        return max(20, int(round(1000.0 / max(1, self.fps))))


@dataclass
class Pack:
    root: Path
    canvas_w: int
    canvas_h: int
    anchor: tuple[float, float] = (0.5, 1.0)
    states: dict[str, State] = field(default_factory=dict)
    events: dict[str, list[str]] = field(default_factory=dict)
    source: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- 查询
    def state(self, key: str) -> State | None:
        return self.states.get(key)

    def for_event(self, event: str) -> list[str]:
        """事件能播的状态列表；过滤掉 manifest 里没有的键，避免配错直接崩。"""
        return [k for k in self.events.get(event, []) if k in self.states]

    def pick_event(self, event: str) -> str | None:
        """从事件映射里随机挑一个能播的状态。"""
        keys = self.for_event(event)
        return random.choice(keys) if keys else None


def load_pack(root: Path | str | None = None) -> Pack | None:
    """读动作包；文件缺失/格式不对时返回 None（桌宠会回退到静态图或手画占位）。"""
    root = Path(root) if root else DEFAULT_PACK
    man_file = root / "manifest.json"
    if not man_file.is_file():
        return None
    try:
        data = json.loads(man_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    canvas = data.get("canvas") or {}
    try:
        cw = int(canvas.get("w") or 0)
        ch = int(canvas.get("h") or 0)
    except (TypeError, ValueError):
        return None
    if cw <= 0 or ch <= 0:
        return None

    anchor = canvas.get("anchor") or [0.5, 1.0]
    try:
        anchor_t = (float(anchor[0]), float(anchor[1]))
    except (TypeError, ValueError, IndexError):
        anchor_t = (0.5, 1.0)

    states: dict[str, State] = {}
    for key, raw in (data.get("states") or {}).items():
        if not isinstance(raw, dict):
            continue
        atlas = raw.get("atlas")
        if not atlas:
            continue
        atlas_path = root / str(atlas)
        if not atlas_path.is_file():
            continue
        try:
            states[key] = State(
                key=key,
                name=str(raw.get("name") or key),
                atlas=atlas_path,
                columns=max(1, int(raw.get("columns") or 1)),
                rows=max(1, int(raw.get("rows") or 1)),
                frames=max(1, int(raw.get("frames") or 1)),
                fps=max(1, int(raw.get("fps") or 10)),
                loop=bool(raw.get("loop", True)),
                mirror=bool(raw.get("mirror", True)),
            )
        except (TypeError, ValueError):
            continue
    if not states:
        return None

    events = {}
    for name, keys in (data.get("events") or {}).items():
        if isinstance(keys, str):
            keys = [keys]
        events[name] = [str(k) for k in keys if str(k) in states]

    return Pack(
        root=root,
        canvas_w=cw,
        canvas_h=ch,
        anchor=anchor_t,
        states=states,
        events=events,
        source=data.get("source") or {},
    )
