# 第三部分　设计方案

前面两部分定义了"做什么"和"怎么走"，这一部分给"怎么实现"。所有设计都遵循一个克制原则：**能用标准库解决的不装包，能用规则解决的不调模型，能用配置解决的不写代码。**

## 9 总体架构

### 9.1 分层架构

[[fig:assets/fig1_arch.png|图 4　系统总体架构]]

六层的职责边界必须清楚，否则后期会纠缠成一团：

- **采集层**只负责"看见"，绝不判断"这是什么"。它不知道什么是摸鱼。
- **存储层**只负责"记下来"，不做业务逻辑。
- **分析层**只负责"翻译"——把像素和窗口标题翻译成活动描述和类别。
- **聚合层**只负责"合并与计算"，不调用模型，纯本地计算。
- **干预层**只负责"什么时候、用什么方式说一句话"。
- **交互层**只负责"显示"和"接收点击"。

一条铁律：**采集层永远不阻塞在网络上**。截图和分析必须解耦，否则网络一卡，采集就断，数据就出现空洞。

### 9.2 模块职责与失败处理

| 模块 | 输入 | 输出 | 失败处理 |
|---|---|---|---|
| `capture/win` | 系统 API | 窗口标题 / 进程名 / PID | 返回空，用进程名兜底 |
| `capture/shot` | 屏幕 | JPEG 路径 + 感知哈希 | 失败标记，不影响元数据 |
| `capture/store` | 采样 | SQLite 行 | 写失败落 jsonl 待补 |
| `analyze/rules` | 窗口元数据 | 类别（带置信度） | 无匹配返回 unknown |
| `analyze/vlm` | 批次请求 | JSON | 重试 2 次，仍失败标 pending |
| `analyze/aggregate` | analysis 行 | block 行 | 跳过空洞，不插值 |
| `judge/engine` | block + goal | 判定结果 | 异常则返回"不判定"（安全侧） |
| `judge/intervene` | 判定结果 | 一次提醒 | 桌宠异常降级为气泡 |
| `report/render` | blocks + 指标 | HTML 文件 | 失败退化为 txt |

注意 `judge/engine` 的失败处理写的是"返回不判定"。这是安全侧设计：**判定模块出故障时，宁可什么都不提醒**，也不能因为 bug 疯狂弹窗。

### 9.3 数据流

[[fig:assets/fig4_data.png|图 5　数据流与数据量级]]

四级数据对象的粒度差异很大，这直接决定了存储和查询策略：

- `sample` 一天上万条，只按时间范围查询，索引只需 `(ts)`。
- `analysis` 一天几十条（按批次），用于追溯模型结论。
- `block` 一天几十条，是报表的唯一数据源，查询频次最高。
- `report` 一天一个文件，纯静态，不查库。

## 10 采集层设计

### 10.1 窗口探针

只取三个字段，用 `ctypes` 就够，不必引入 `pywin32`（少一个依赖，少一堆安装问题）：

```python
import ctypes
from ctypes import wintypes

u = ctypes.windll.user32
u.GetForegroundWindow.restype = wintypes.HWND
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

def foreground():
    hwnd = u.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buf, 512)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, buf.value, pid.value      # 进程名交给 psutil 查，结果做 LRU 缓存
```

三个坑：升级权限的窗口（任务管理器、部分安装器）读不到标题，此时降级用进程名；`psutil` 查进程名要加缓存，否则每 5 秒一次查询会明显吃 CPU；中文标题在某些输入法状态下会返回乱码，用 `create_unicode_buffer` 可避免。

### 10.2 截图

用 `mss`（比 `PIL.ImageGrab` 快一个数量级），并且必须缩放：

```python
with mss.mss() as sct:
    raw = sct.grab(sct.monitors[1])            # 只截主屏
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
img.thumbnail((1280, 1280))                    # 长边 1280 足够模型看清
img.save(path, "JPEG", quality=70, optimize=True)
```

为什么是 1280 和 q70：模型输入侧通常会把图缩到 1024～1536 之间，再大纯属浪费 token；q70 在文字可读性和体积之间是甜点，一张 1080p 截图约 90～150KB，一天 50 张不到 8MB。

启动时必须声明 DPI 感知，否则 125% 缩放下截图会偏移或模糊：

```python
ctypes.windll.shcore.SetProcessDpiAwareness(2)    # PER_MONITOR_AWARE
```

### 10.3 去重

用 dHash（差分哈希）而不是 pHash，因为前者计算快 3 倍且对"打字时的小变化"更敏感：

```python
def dhash(img, size=8):
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (px[r * (size + 1) + c] < px[r * (size + 1) + c + 1])
    return bits

# 汉明距离 <= 6 视为同一画面，丢弃新帧
```

这一步在 60 秒采样时是省钱的关键：打字场景下约有 40%～60% 的帧与前一帧几乎相同，去重后送模型的数量能砍掉一半。节奏放宽到 10 分钟一张之后，相邻两帧大多已经不同，收益变小，但这道检查留着不花钱——看视频、挂着不动时依然能挡掉重复帧。

### 10.4 空闲检测与敏感过滤

空闲用 `GetLastInputInfo` + `GetTickCount` 计算，比监听钩子轻得多：

```python
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

def idle_seconds():
    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(li)
    u.GetLastInputInfo(ctypes.byref(li))
    return (u.GetTickCount() - li.dwTime) / 1000.0
```

敏感过滤是两级：**进程级**（密码管理器、网银、银行客户端）在截图前拦截，**标题级**（含"密码""转账""工资"等关键词）在保存前拦截。命中时只记元数据，且元数据里的标题要脱敏成 `<sensitive>`，否则敏感信息依然会留在库里。

默认敏感名单（可在设置里增删）：

| 类型 | 匹配方式 | 示例 |
|---|---|---|
| 密码管理器 | 进程名 | 1Password.exe、KeePass.exe、Bitwarden.exe |
| 金融 | 进程名 + 域名 | 网银客户端、银行域名 |
| 私人通信 | 进程名 + 标题 | 微信/QQ 的聊天窗口（可选，默认只过滤"文件传输"） |
| 用户自定 | 关键词 | 自己加 |

### 10.5 性能预算

| 指标 | 目标 | 说明 |
|---|---|---|
| CPU 平均占用 | < 3% | 5 秒一次窗口查询 + 10 分钟一次截图 |
| 内存 | < 300MB | 主要是 Qt 和 PIL 的缓存 |
| 磁盘/天 | < 10MB | 截图约 50 张，去重后 40 张左右 |
| 磁盘/月 | < 300MB | 配合 7 天截图保留策略，实际 < 60MB |
| 启动耗时 | < 3s | 不做任何网络请求，先起来再说 |

## 11 分析层设计

### 11.1 两档分析策略

这是整个方案里最重要的一个决策：**不是所有样本都值得送给大模型。**

| 档 | 手段 | 成本 | 覆盖率 | 适用 |
|---|---|---|---|---|
| A 档 | 规则表（进程名 / 域名 / 标题关键词） | 零 | 约 80% 的时长 | 明确的场景：写代码、看视频、开会议 |
| B 档 | 视觉大模型 | 有成本 | 剩余约 20% | 模糊场景：浏览器里的某篇文章、某个软件界面 |
| C 档 | 用户纠错沉淀的规则 | 零 | 随时间上升 | 高频误判场景 |

A 档先跑，只有 A 档给不出高置信结论时才升级到 B 档。实测中这能把调用量压到三分之一左右，而准确率反而更高——因为进程名是确定性信号，模型是概率信号。

### 11.2 批次构造

一次请求处理一个 15 分钟的批次，而不是一帧一请求。这样模型能看到"上下文"，判断"在教程和代码之间来回切"远比单帧准确：

```json
{
  "goal": "写完文献综述第 2 节",
  "window": "09:30-09:45",
  "timeline": [
    {"t": "09:30:05", "proc": "Code.exe", "title": "spider.py - Visual Studio Code"},
    {"t": "09:30:50", "proc": "Code.exe", "title": "spider.py - Visual Studio Code"},
    {"t": "09:33:12", "proc": "chrome.exe", "title": "Scrapy 文档 - Google Chrome"},
    {"t": "09:41:30", "proc": "chrome.exe", "title": "Python 异常处理 - 知乎"}
  ],
  "frames": ["09:30", "09:41"],
  "prev": "上一批结论：在调试爬虫的编码问题，任务在轨"
}
```

注意 `prev` 字段：把上一批的结论压缩成一句话带进去，能让模型保持连贯，避免"上一批说在写代码，这一批说在查资料"式的抖動。

### 11.3 输出契约

要求模型输出严格的 JSON，且每个结论必须带证据。证据字段是防幻觉的关键——没有证据的结论直接丢弃：

```json
{
  "segments": [
    {
      "start": "09:30",
      "end": "09:36",
      "activity": "在 VS Code 中编辑爬虫脚本",
      "category": "deep_work",
      "on_task": true,
      "confidence": 0.88,
      "evidence": "编辑器内为 spider.py，底部终端有 Python 报错栈"
    },
    {
      "start": "09:36",
      "end": "09:44",
      "activity": "查阅 Scrapy 官方文档与知乎问答",
      "category": "learning",
      "on_task": true,
      "confidence": 0.72,
      "evidence": "浏览器标签为 Scrapy 文档与知乎问题页"
    }
  ]
}
```

`category` 的取值必须封闭（见 12.1），不接受模型自由发挥。`confidence` 低于 0.6 的段直接归入 `unknown`，在日报里用灰色表示，不参与统计——**宁可承认不知道，也不要瞎猜**。

### 11.4 解析与校验

三道校验，任何一道失败都当解析失败处理，绝不"尽力猜"：

1. JSON 结构校验：必须是 `{"segments": [...]}`。
2. 字段取值校验：`category` 在白名单内，时间格式 `HH:MM`，`confidence` 在 0～1。
3. 时间一致性校验：`start < end`，且段落在批次时间窗内。

```python
VALID = {"deep_work", "shallow_work", "learning", "entertainment",
         "aimless", "life", "system", "unknown"}

def validate(data, win_start, win_end):
    out = []
    for s in data.get("segments", []):
        if s.get("category") not in VALID:           continue
        if not (win_start <= s["start"] < s["end"] <= win_end): continue
        if not s.get("evidence"):                    continue
        out.append(s)
    return out
```

### 11.5 成本控制

先给量级估算，公式很简单：

> 日成本 ≈ 日送模型张数 × 单张成本
> 日送模型张数 = 采样张数 × 去重保留率（约 0.4）× B 档触发率（约 0.3）

按每天 8 小时、10 分钟一张算：48 张 → 去重后约 35 张 → B 档约 10 张。若把节奏调回 60 秒，这张数会变成 480 → 190 → 60，成本差一个数量级。云端视觉模型的单张成本差异很大（不同厂商、不同分辨率、不同计费方式可差 5～10 倍），量级上一天几毛钱、一个月十几到几十块。**具体以你自己的账单为准**，这里只给方法。

五个省钱手段，按收益排序：

| 手段 | 省多少 | 代价 |
|---|---|---|
| 去重（dHash） | 视场景 10～50% | 无 |
| A 档规则先过滤 | 省 60～70% | 规则覆盖率不够时会漏 |
| 降采样（现默认 10 分钟一张） | 省 90% | 短时行为可能漏掉 |
| 批内多帧一次调用 | 省 30～40% | 单次请求变长 |
| 结果缓存（同哈希复用） | 省 10～20% | 需要额外的缓存表 |

再加一道**预算熔断**：配置里设 `daily_budget_cny: 2.0`，当天花费超限就自动切到"只记元数据 + 规则分类"，并弹一次通知说明原因。这条必须有，否则某天忘了关，账单会教做人。

### 11.6 本地模型方案

隐私要求高的话，用 Ollama 跑视觉模型，零边际成本：

| 方案 | 显存要求 | 准确率 | 延迟 | 适用 |
|---|---|---|---|---|
| 云端 API | 无 | 高 | 3～10s | 默认 |
| Ollama + Qwen2.5-VL 7B | 8GB+（量化后约 6GB） | 中（约低 10～15 个百分点） | 5～20s | 隐私优先 |
| Ollama + 同系列 3B | 4GB+ | 中低 | 2～8s | 低配机器 |

本地模型的短板在细粒度判断（区分"写代码"和"看代码教程"容易错），但在大类划分上够用。建议做成可切换：**平时用云端，敏感时段切本地**。

### 11.7 怎么证明它准

不要凭感觉判断准不准。第一天就建一个 100 条的金标集：

1. 随机抽 100 条 sample（覆盖不同时段、不同应用）。
2. 人工标注真实类别。
3. 跑一遍分析，算混淆矩阵。
4. 记下每次调整规则或提示词后的准确率变化。

没有这个基线，后面所有的"好像变准了"都是错觉。这个本子只有 100 条，一小时就能标完，是整个项目里性价比最高的投入。

## 12 聚合与指标

### 12.1 分类体系

两级分类，第一级用于统计，第二级用于展示：

| 一级 | 二级示例 | 颜色 | 是否计入"生产性" |
|---|---|---|---|
| deep_work | 写代码、写文档、做设计 | 深蓝 | 是 |
| shallow_work | 回消息、发邮件、开会 | 中蓝 | 是（单独统计） |
| learning | 看文档、看课程、查资料 | 青 | 是 |
| entertainment | 视频、游戏、刷社交媒体 | 橙 | 否 |
| aimless | 无目的浏览、反复刷首页 | 浅橙 | 否 |
| life | 购物、支付、订票 | 灰绿 | 否（但不算坏事） |
| system | 桌面操作、文件管理 | 浅灰 | 否 |
| unknown | 模型没看懂 | 灰 | 不计入任何比例 |

`aimless` 和 `entertainment` 要分开：前者是"没有目的地划来划去"，恰恰是最容易被忽视、也最值得提醒的那类；后者是"有目的地娱乐"，人有权娱乐，不该被指责。这两种的文案口吻完全不同。

### 12.2 段合并算法

模型输出的段是碎的（一个 15 分钟的批次可能切出 4 段），必须合并成人类可读的时间块：

```python
def merge(segments, gap=180, min_len=60):
    """相邻同类且间隔 < gap 秒则合并；合并后短于 min_len 的段并入邻居。"""
    out = []
    for s in sorted(segments, key=lambda x: x.start):
        if out and s.start - out[-1].end <= gap and same_kind(out[-1], s):
            out[-1].end = s.end                                  # 延伸上一段
            out[-1].confidence = min(out[-1].confidence, s.confidence)
        else:
            out.append(s.copy())
    # 二次清理：过短的孤立段并入时长更接近的邻居
    for i, s in enumerate(out):
        if (s.end - s.start) < min_len and 0 < i < len(out) - 1:
            out[i - 1].end = s.end if similar(out[i - 1], s) else out[i - 1].end
    return out
```

三个参数有讲究：`gap=180` 是因为人切出去看一眼消息再回来，中间那段不该被单独记成一次"中断"；`min_len=60` 是因为小于一分钟的段在时间轴上根本画不出来；`same_kind` 判断时把 `deep_work` 和 `learning` 视为同类（查资料写代码是同一件事的两面）。

### 12.3 指标定义

指标必须定义得足够死，否则每周的口径都不一样，对比就失去意义：

| 指标 | 定义 | 为什么这么定 |
|---|---|---|
| 专注时长 | 连续 `on_task=true` 且 ≥ 25 分钟的 `deep_work` 段累计 | 25 分钟是"进入状态"的经验下限，短于此不算深度工作 |
| 消耗时长 | `entertainment` + `aimless` 的总和 | 只统计明确消耗，生活事务不算罪 |
| 切换次数 | 每小时 block 边界数 | 衡量碎片化，比总时长更能反映问题 |
| 有效比 | 生产性时长 ÷ 在电脑前时长（去掉 idle） | 分母用"在电脑前"而非"一整天"，避免被会议和午休稀释 |
| 恢复力 | 被提醒后 5 分钟内回归任务的次数 ÷ 提醒次数 | 唯一能证明"这个工具真的有用"的指标 |

刻意不做的两个指标：**总分**（会诱发自欺）和**排名/对比他人**（个人工具没有他人）。

### 12.4 日报文案生成

不调用模型，用模板 + 规则拼接，快且可控。三类模板：

| 场景 | 模板 | 示例 |
|---|---|---|
| 好日子 | 今天专注 {focus}，{praise} | 今天专注 3 小时 20 分，是近两周最长的一次。 |
| 一般 | 今天专注 {focus}，被切了 {switches} 次。 | 今天专注 2 小时 40 分，被切了 37 次。 |
| 滑坡 | 今天专注 {focus}，{warn} | 今天专注 48 分钟，下午 3 点后基本没进入状态。 |

三条文案纪律：

1. **陈述事实，不评价人格。** 写"下午切换了 21 次"，不写"你太不专注了"。
2. **不做比较级**（"比 90% 的人差"），只和自己比。
3. **建议只有一条，且是动作**。写"明天把手机放远一点"，不写"要提高自律"。

### 12.5 可视化

纯 HTML + CSS，不用任何前端框架和 JS 库。时间轴用 div 的宽度百分比堆叠即可：

```html
<div class="day">
  <div class="blk deep" style="left:8.3%;width:12.5%"
       data-shot="shots/2026-11-05/0930.jpg" title="09:00-10:00 写代码"></div>
  <div class="blk ent" style="left:43.5%;width:4.2%" ...></div>
</div>
```

一个 300 行的 Jinja 风格模板（或者干脆用 `str.format`）就够。好处是：文件可以单独发给自己、可以打印、十年后还能打开。

## 13 干预与桌宠

### 13.1 规则引擎

规则写在 YAML 里，改规则不用改代码：

```yaml
rules:
  - id: video_site
    when:
      proc: [chrome.exe, msedge.exe, firefox.exe]
      title_contains: [哔哩哔哩, 抖音, YouTube, 爱奇艺]
    then: {category: entertainment, weight: 0.9}

  - id: ide_work
    when: {proc: [Code.exe, pycharm64.exe, idea64.exe, devenv.exe]}
    then: {category: deep_work, weight: 0.95}

  - id: meeting_exempt
    when: {proc: [Teams.exe, Zoom.exe, wemeetapp.exe]}
    then: {exempt: true, note: "会议不算摸鱼"}
```

`weight` 是置信度权重，用于和模型结论融合：规则权重 ≥ 0.9 时直接用规则结论，0.6～0.9 时取规则和模型的交集，低于 0.6 时交给模型。

### 13.2 冷却与豁免的数据结构

```python
cooldown = {
    "video_site": {"last": 1762345678, "count_today": 3},
    "aimless_browse": {"last": 1762340000, "count_today": 1},
}
# 冷却判定：now - last < cooldown_sec(默认 600) → 只记录不提醒
# 日上限：count_today >= daily_cap(按等级不同) → 降级为 L1 或只记录
```

豁免分两级：**临时**（今天、这个网站，当日 24 点失效）和**永久**（加进白名单，写进配置）。用户点"我在做正事"时默认给临时的，避免一次手滑永久关掉提醒。

### 13.3 桌宠窗口实现要点

PySide6 做透明置顶窗口，关键是四个标志位：

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel

class Pet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(160, 160)
```

- `FramelessWindowHint`：无边框。
- `WindowStaysOnTopHint`：置顶。
- `Tool`：**关键**，让窗口不出现在 Alt+Tab 和任务栏里，否则会非常碍眼。
- `WA_TranslucentBackground`：透明背景，只显示角色。

四个必须处理的细节：

1. **全屏应用时自动隐藏**：检测到前台是全屏（游戏、视频、演示）就藏起来，退出全屏再出来。不处理的话，看电影时桌宠会盖在画面上，很扫兴。
2. **贴边半隐藏**：拖到屏幕边缘时自动收进去一半，鼠标移上去才展开。
3. **位置记忆**：保存到配置，下次启动原位。
4. **点击穿透区域**：角色本身可点，周围透明区域不该挡住下面的窗口（用 `setMask` 按 alpha 裁剪）。

### 13.4 状态机

| 状态 | 触发 | 表现 | 持续 |
|---|---|---|---|
| idle | 默认 | 呼吸动画、偶尔眨眼 | 常驻 |
| watching | 检测到窗口切换 | 转头"看"屏幕方向 | 2 秒 |
| alert | 触发提醒 | 滑入 + 气泡 + 说话 | 5 秒或点击 |
| rest | 用户选"歇会儿" | 打哈欠、进入睡眠动画 | 10 分钟 |
| sleep | 无操作 > 20 分钟 | 闭眼 | 直到有输入 |

状态机只在这五个状态之间切换，不做复杂表情系统——**MVP 阶段动画越简单越好**，2～3 帧的精灵图足够，等真的用起来了再考虑 Live2D。

### 13.5 防骚扰的三条硬约束

1. 任何一条提醒，用户都能在 2 秒内关掉（Esc 或点桌宠）。
2. 同一类提醒一天不超过 5 次（L3），超过自动静默到次日。
3. **连续 3 天，如果所有提醒的用户回应都是"我在做正事"，自动进入"静默一周"并向用户报告**。这条是防止工具变成噪音的最后一道保险。

## 14 数据模型

### 14.1 表结构

| 表 | 作用 | 关键字段 | 量级 |
|---|---|---|---|
| `sample` | 每次采样的原始记录 | ts, proc, title, shot_path, hash | 1 万/天 |
| `analysis` | 批次分析结果 | batch_id, segment_start, category, confidence, evidence | 数十/天 |
| `block` | 合并后的时间块 | start, end, category, on_task | 数十/天 |
| `goal` | 目标声明 | date, text, started_at, ended_at | 1～5/天 |
| `intervention` | 提醒记录 | ts, level, rule_id, user_action | 0～10/天 |
| `correction` | 用户纠错 | block_id, old, new, scope | 少量 |
| `kv` | 配置与状态 | key, value | 数十行 |

### 14.2 建表 SQL

```sql
PRAGMA journal_mode = WAL;          -- 读写不互斥，采集不会被报表卡住

CREATE TABLE IF NOT EXISTS sample (
  id        INTEGER PRIMARY KEY,
  ts        INTEGER NOT NULL,       -- unix 秒
  proc      TEXT,
  title     TEXT,
  shot      TEXT,                   -- 相对路径，NULL 表示未截图
  dhash     INTEGER,
  idle      INTEGER DEFAULT 0,
  sensitive INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sample_ts ON sample(ts);

CREATE TABLE IF NOT EXISTS block (
  id        INTEGER PRIMARY KEY,
  date      TEXT NOT NULL,          -- YYYY-MM-DD
  start_ts  INTEGER NOT NULL,
  end_ts    INTEGER NOT NULL,
  category  TEXT NOT NULL,
  activity  TEXT,
  on_task   INTEGER,                -- 1 / 0 / NULL(未知)
  confidence REAL,
  shot_ref  TEXT                    -- 代表性截图，供日报回看
);
CREATE INDEX IF NOT EXISTS idx_block_date ON block(date, start_ts);

CREATE TABLE IF NOT EXISTS intervention (
  id        INTEGER PRIMARY KEY,
  ts        INTEGER NOT NULL,
  level     INTEGER,                -- 1..4
  rule_id   TEXT,
  reason    TEXT,
  action    TEXT                    -- back_to_work / rest / ignore / closed
);
```

`shot` 存相对路径而非绝对路径，这样整个数据目录可以搬家。`dhash` 存成整数（64 位），用于后续查重和缓存命中。

### 14.3 查询模式

日报只需要三条查询，都走索引，300ms 内出结果：

```sql
-- 1) 当天所有块
SELECT * FROM block WHERE date = ? ORDER BY start_ts;
-- 2) 当天某类合计
SELECT category, SUM(end_ts - start_ts) FROM block WHERE date = ? GROUP BY category;
-- 3) 某块的代表截图
SELECT shot_ref FROM block WHERE id = ?;
```

不要写 `SELECT * FROM sample` 做报表——那张表一天上万行，让它只服务采样的写入。

### 14.4 保留策略

| 数据 | 保留 | 理由 |
|---|---|---|
| 截图 | 7 天 | 占空间，且只有近期需要回看证据 |
| sample 明细 | 30 天 | 支撑趋势分析，之后聚合成日统计 |
| block 与指标 | 永久 | 只有几十行/天，是长期趋势的基础 |
| intervention | 90 天 | 用于评估提醒有效性 |
| 日志 | 7 天 | 排障用 |

清理放在每天凌晨，用 `shutil.rmtree` 按日期目录删，删之前校验路径前缀，防止配置写错把整个盘删了（这不是玩笑，有必要加一道 `assert path.startswith(BASE)`）。

## 15 技术选型

### 15.1 选型对比

| 环节 | 候选 | 选择 | 理由 |
|---|---|---|---|
| 语言 | Python / Node / C# / Rust | **Python 3.11+** | 生态最全，开发最快；性能瓶颈在网络 IO 不在计算 |
| 截图 | mss / PIL.ImageGrab / win32 | **mss** | 比 ImageGrab 快 5～10 倍，多屏支持好 |
| 窗口信息 | ctypes / pywin32 / pywinauto | **ctypes** | 零依赖，够用；pywinauto 留给未来读浏览器 URL |
| 存储 | SQLite / JSON 文件 / DuckDB | **SQLite（WAL）** | 单文件、事务、索引齐全，JSON 做不了聚合查询 |
| 界面 | PySide6 / tkinter / Electron / Tauri | **PySide6** | 透明置顶窗口成熟，单语言栈，不用再学 JS |
| 模型 | 云端 API / 本地 Ollama | **云端为主，本地可选** | 云端准确率高、零显卡要求；本地作为隐私备选 |
| 日报 | HTML / Markdown / GUI | **HTML** | 好看、可打印、可归档、改样式不用改代码 |
| 调度 | APScheduler / 自写 tick / schedule | **自写 tick** | 只有两个定时任务，引入框架不值 |
| 打包 | PyInstaller / Nuitka | **PyInstaller** | 成熟，单文件，接受启动慢 1 秒 |
| 自启 | 注册表 / 启动文件夹 / 计划任务 | **启动文件夹 + pythonw** | 最简单，不改注册表，卸载=删快捷方式 |

### 15.2 依赖清单

控制在 8 个包以内，每个都要有明确理由：

```text
mss            # 截图
Pillow         # 图像处理与编码
psutil         # 进程名查询
PySide6        # 托盘、桌宠、设置面板
requests       # HTTP（不引 openai SDK，省依赖）
PyYAML         # 配置与规则
python-dateutil# 时间处理
```

`sqlite3`、`ctypes`、`json`、`logging`、`hashlib` 全用标准库。不引入 `numpy`（Pillow 够用）、不引入 `pandas`（报表只有几十行）。

### 15.3 目录结构

```text
focuspet/
├─ main.py                 # 入口：DPI → 配置 → 线程 → Qt 事件循环
├─ config.py               # 加载 config.yaml + 默认值合并
├─ log.py                  # 轮转日志，按天分文件
├─ capture/
│  ├─ win.py               # 前台窗口 / 空闲检测
│  ├─ shot.py              # 截图 + dhash + 落盘
│  └─ store.py             # 写 SQLite，失败落 jsonl
├─ analyze/
│  ├─ rules.py             # 规则表匹配
│  ├─ vlm.py               # 模型客户端（重试 / 超时 / 校验）
│  ├─ scheduler.py         # 批次调度
│  └─ aggregate.py         # 合并、指标计算
├─ judge/
│  ├─ engine.py            # 判定链
│  ├─ intervene.py         # 分级、冷却、派遣
│  └─ learn.py             # 纠错 → 规则
├─ ui/
│  ├─ tray.py              # 托盘菜单
│  ├─ pet.py               # 桌宠窗口与状态机
│  └─ settings.py          # 设置面板
├─ report/
│  ├─ render.py            # 组装数据 → HTML
│  └─ template.html        # 单文件模板，内联 CSS
├─ assets/                 # 精灵图、图标
├─ data/                   # 运行时生成：db、shots、reports、logs
└─ scripts/
   ├─ autostart.py         # 写启动文件夹快捷方式
   └─ watchdog.ps1         # 计划任务兜底重启
```

### 15.4 配置项

配置项控制在 20 个以内，多了就等于没有：

```yaml
capture:
  window_poll_sec: 5
  shot_interval_sec: 600       # 10 分钟一张
  shot_on_window_change: false # 切窗口不补拍，否则上面的间隔形同虚设
  idle_threshold_sec: 300
  max_shot_side: 1280
  jpeg_quality: 70

analyze:
  batch_minutes: 15
  mode: cloud               # cloud | local | rules_only
  model: ""                 # 留空则在设置面板里填
  min_confidence: 0.6
  daily_budget_cny: 2.0

judge:
  off_task_minutes: 3
  cooldown_minutes: 10
  l3_daily_cap: 5
  rest_minutes: 10

privacy:
  mode: masked              # local | masked | meta_only
  sensitive_procs: [KeePass.exe, 1Password.exe, Bitwarden.exe]
  sensitive_keywords: [密码, 转账, 工资, 身份证]

ui:
  pet_enabled: true
  pet_position: [1720, 900]
  theme: light
```

### 15.5 启动与自启

自启用启动文件夹 + `pythonw.exe`（无控制台窗口），写一个 `.lnk` 即可，比改注册表安全：

```python
shortcut = shell.ShellLink()
shortcut.TargetPath = sys.executable.replace("python.exe", "pythonw.exe")
shortcut.Arguments  = f'"{ROOT / "main.py"}"'
shortcut.WorkingDirectory = str(ROOT)
shortcut.Save(str(startup_dir / "FocusPet.lnk"))
```

再配一个计划任务，每 5 分钟检查一次心跳文件，超过 10 分钟没更新就重启。崩溃是必然的，**自动恢复比追求不崩更现实**。

## 16 隐私与安全

### 16.1 数据地图

先说清楚什么数据去了哪里，这一张表要能被用户直接看到：

| 数据 | 存在哪 | 是否出本机 | 保留 |
|---|---|---|---|
| 窗口标题 / 进程名 | 本地 SQLite | 否 | 30 天 |
| 截图 | 本地磁盘 | 视隐私档：脱敏档会发送压缩后的图给模型 API | 7 天 |
| 分析结论 | 本地 SQLite | 否 | 永久 |
| 日报 | 本地 HTML | 否 | 永久 |
| 纠错记录 | 本地 SQLite | 否 | 永久 |

### 16.2 三档隐私模式

| 模式 | 截图 | 云端 | 准确率 | 适用 |
|---|---|---|---|---|
| `local` | 存本地，不发送 | 只用 Ollama 本地模型 | 中 | 最在意隐私 |
| `masked`（默认） | 存本地；发送前做脱敏 | 发送脱敏图 | 高 | 多数人 |
| `meta_only` | 完全不截 | 只发窗口标题 | 中低 | 极简或低配机器 |

脱敏不是模糊整张图（那样模型也看不懂了），而是**只发送窗口内容区，裁掉任务栏和通知区**，并对配置里指定的应用区域做马赛克。这一步能挡掉大部分意外泄露——通知弹窗里出现的往往是消息内容。

### 16.3 对用户（自己）要说的三句话

1. 如果这台电脑还有别人用，先把截图目录设成加密（BitLocker 或 7z 加密卷），否则等于把日记本摊在桌上。
2. 不要用免费额度会"用于模型改进"的 API 传截图，那是把屏幕内容捐出去。
3. 不要把这个工具装到同事或家人的电脑上。个人自用没问题，一旦沾上"监控他人"，性质就全变了。

## 17 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 误报太多，三天后卸载 | 高 | 致命 | 默认最轻提醒；全否才提醒；一键豁免；连续误报自动降权 |
| API 费用失控 | 中 | 中 | 预算熔断 + 去重 + 规则前置 + 90 秒降频选项 |
| 截图泄露隐私 | 低 | 高 | 三档模式 + 敏感名单 + 本地存储 + 加密目录建议 |
| 挂机崩溃导致数据断档 | 中 | 中 | 看门狗 + 心跳 + 写入队列 + 失败落 jsonl |
| 判定被自己"脱敏"（习惯性忽略提醒） | 高 | 中 | 周报对比 + 恢复力指标 + 静默一周机制 |
| 手机端迟迟做不出来，预期落空 | 高 | 低 | 一开始不承诺，MVP 明说只做 PC |
| 规则表越堆越乱 | 中 | 低 | 规则一律进 YAML，带 id 和注释，三个月不清就清一次 |
| 时间轴分类不准，失去信任 | 中 | 高 | 金标集 + 每块可回看证据 + 用户纠错回流 |

其中第一行是唯一"致命"级别的风险。整个设计里所有"宁可漏报"的选择，都是为了对冲它。

## 18 七天开工清单

不用等到想清楚全部再做。下面这份清单按天拆开，每天结束时都有一样能看见的东西。**如果只有两天时间，只做 Day 1 到 Day 3，就能拿到一张能看的时间轴。**

| 天 | 任务 | 当天可见成果 | 卡住的常见原因 |
|---|---|---|---|
| Day 1 | 建项目骨架；写窗口探针；打印当前前台窗口 | 控制台每秒刷出"Code.exe / spider.py" | 读不到管理员窗口标题 → 用进程名兜底 |
| Day 2 | 接入 mss 截图；加 dhash 去重；写 SQLite；连续录 1 小时 | `data/shots/` 里有图，库里两万行 | DPI 缩放导致截图偏移 → 声明 DPI 感知 |
| Day 3 | 规则表分类（20 条规则）；写聚合；生成最简 HTML 时间轴 | 浏览器里看到今天的时间轴色带 | 段太碎 → 调 gap 到 180 秒 |
| Day 4 | 接入视觉模型；批次构造 + JSON 校验；跑通 20 批 | 每批都有中文活动描述 | JSON 解析失败 → 加 response_format / 严格提示词 |
| Day 5 | 目标声明面板；判定链；托盘菜单 | 能声明目标并看到实时判定标签 | Qt 线程通信崩溃 → 用信号槽，别跨线程碰控件 |
| Day 6 | 桌宠窗口；L1/L2 提醒；冷却与豁免；一键纠错 | 真摸鱼时桌宠会探头 | 置顶遮挡全屏 → 检测全屏自动隐藏 |
| Day 7 | 自启；看门狗；隐私档；配置面板；跑一整天 | 挂机一整天，晚上自动弹日报 | 内存涨 → 检查截图对象是否释放 |

每天收工前做一件小事：**把当天遇到的坑写进 README**。七天之后这份 README 就是最真实的设计文档。

> 最后一句提醒：这个工具最大的失败模式不是"做不出来"，而是"做出来了但你不看"。所以 Day 3 的那张时间轴，比后面所有功能都重要——先让它能看，再让它好看，最后才让它会说话。
