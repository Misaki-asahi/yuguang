# -*- coding: utf-8 -*-
"""视觉模型客户端（设计方案 11.2–11.5，提示词见附录 A）。

用 urllib 而不是 SDK：少一个依赖，而且兼容任何 OpenAI 协议的地址（云端或本地 Ollama）。
失败策略写死在这里：重试 2 次，仍失败返回 None 由上层决定降级——绝不「尽力猜」。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from datetime import datetime

from .. import config
from ..log import get

log = get("vlm")

VALID = {"deep_work", "shallow_work", "learning", "entertainment",
         "aimless", "life", "system", "unknown"}

SYSTEM_PROMPT = """你是一个屏幕行为分析助手。你的任务是根据用户一段时间内的前台窗口记录和若干张屏幕截图，
判断用户在这段时间里具体在做什么，并把结论整理成结构化数据。

规则：
1. 只描述你在截图和窗口记录里真正看到的内容，不要推测截图中不存在的细节。
2. 每一条结论都必须给出 evidence（证据），写清是截图的哪个部分或哪条窗口记录支撑了这个判断。
3. 如果证据不足，category 填 "unknown"，confidence 填 0.3 以下，不要猜。
4. 时间用 HH:MM 格式，必须落在给定的时间窗内，且 start 小于 end。
5. 一个时间窗内通常有 1~4 段，段与段之间应连续覆盖整个窗口，除非有明显空闲。
6. category 只能从以下取值中选择：
   deep_work / shallow_work / learning / entertainment / aimless / life / system / unknown
7. on_task 表示这段活动是否服务于用户声明的目标；目标无关时填 null。
8. activity 用不超过 20 个字的中文短语，描述"在做什么"，不要写评价。
9. 只输出 JSON，不要输出任何解释文字或 Markdown 代码块标记。

输出格式（严格）：
{"segments":[{"start":"09:30","end":"09:36","activity":"...",
"category":"...","on_task":true,"confidence":0.0,"evidence":"..."}]}"""

USER_TEMPLATE = """【用户今日目标】
{goal}

【时间窗】
{wstart} 到 {wend}

【前台窗口记录】
{timeline}

【屏幕截图（按时间顺序，共 {n} 张）】
{{[附上图片]}}

【上一批结论（仅供参考，可以推翻）】
{prev}

请分析以上内容，输出 JSON。"""


def enabled(cfg: dict) -> bool:
    a = cfg["analyze"]
    if a.get("mode") == "rules_only":
        return False
    return bool(a.get("endpoint") and a.get("model"))


def estimate_cost(cfg: dict, n_images: int) -> float:
    return n_images * float(cfg["analyze"].get("cost_per_image_cny", 0.01))


def _hm(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def build_messages(cfg: dict, batch: dict) -> dict:
    lines = []
    last = None
    for t, proc, title in batch["timeline"]:
        key = (proc, title)
        if key == last:                 # 连续同一窗口只留一条，省 token
            continue
        last = key
        lines.append(f"{_hm(t)}  {proc}  |  {title}")
    if not lines:
        lines.append("（本批次没有可用的窗口记录）")

    text = USER_TEMPLATE.format(
        goal=batch.get("goal") or "（今天没有声明目标，只做分类）",
        wstart=_hm(batch["start_ts"]),
        wend=_hm(batch["end_ts"]),
        timeline="\n".join(lines),
        n=len(batch.get("frames", [])),
        prev=batch.get("prev") or "（无）",
    )

    content = [{"type": "text", "text": text}]
    for rel in batch.get("frames", []):
        path = config.DATA / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    return {
        "model": cfg["analyze"]["model"],
        "temperature": 0,
        "max_tokens": 1200,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }


def _post(cfg: dict, payload: dict) -> tuple[str | None, str | None]:
    a = cfg["analyze"]
    key = config.env_key(cfg)
    if not key and a.get("mode") == "cloud":
        return None, "未设置 API Key（环境变量 %s）" % a.get("api_key_env")

    url = a["endpoint"].rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(req, timeout=float(a.get("timeout_sec", 30))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        return None, f"HTTP {exc.code}: {detail}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def parse_json(text: str) -> dict | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    try:
        return json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                return None
    return None


def validate(data: dict | None, win_start: int, win_end: int,
             min_conf: float = 0.6) -> list[dict]:
    """三道校验，任何一道不过就当解析失败，绝不尽力猜（11.4）。"""
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        return []
    day = datetime.fromtimestamp(win_start).date()
    out = []
    for s in data["segments"]:
        if not isinstance(s, dict):
            continue
        cat = s.get("category")
        if cat not in VALID:
            continue
        try:
            h1, m1 = (int(x) for x in str(s["start"]).split(":")[:2])
            h2, m2 = (int(x) for x in str(s["end"]).split(":")[:2])
        except Exception:
            continue
        st = int(datetime(day.year, day.month, day.day, h1, m1).timestamp())
        et = int(datetime(day.year, day.month, day.day, h2, m2).timestamp())
        if not (win_start <= st < et <= win_end):
            continue
        if not (s.get("evidence") or "").strip():
            continue
        conf = float(s.get("confidence") or 0)
        conf = max(0.0, min(1.0, conf))
        if conf < 0.6:
            cat = "unknown"             # 低置信度归入 unknown，不参与统计
        out.append({
            "start_ts": st, "end_ts": et,
            "activity": str(s.get("activity", ""))[:40],
            "category": cat,
            "on_task": s.get("on_task"),
            "confidence": conf,
            "evidence": str(s.get("evidence", ""))[:200],
            "source": "vlm",
        })
    return out


def analyze(cfg: dict, batch: dict) -> tuple[list[dict] | None, str | None]:
    """返回 (segments, error)。None 表示这一批失败，上层应降级而不是编造。"""
    payload = build_messages(cfg, batch)
    retries = int(cfg["analyze"].get("retry", 2))
    err = None
    for attempt in range(retries + 1):
        text, err = _post(cfg, payload)
        if text is None:
            log.warning("模型调用失败（第 %d 次）：%s", attempt + 1, err)
            time.sleep(min(2 ** attempt, 8))
            continue
        segs = validate(parse_json(text), batch["start_ts"], batch["end_ts"],
                        float(cfg["analyze"].get("min_confidence", 0.6)))
        if segs:
            return segs, None
        err = "模型输出无法通过校验"
        log.warning("%s（第 %d 次），原文前 120 字：%s", err, attempt + 1, text[:120])
    return None, err
