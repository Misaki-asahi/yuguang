# 余光 · focuspet

> 一个"用余光看着你"的桌面小工具：不录屏、不上传、不评判。
> 白天在你跑偏时轻轻戳一下，晚上给你一张诚实的时间账单。

这是设计方案（`../余光_流程_大纲_设计方案_v1.1.docx`）的**实现版本**，
严格按第三部分第 15.3 节的目录结构落地。

---

## 现在做到哪了

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 采集跑通：窗口探针、截图、去重、SQLite | ✅ 已完成并实机验证 |
| M1 | 看懂画面：40 条规则表 + 视觉模型客户端 | ✅ 规则链跑通；模型链路待填 key 实测 |
| M2 | 出时间轴：聚合 + HTML 日报 | ✅ 已完成，日报可看 |
| M3 | 会提醒：目标声明、判定链、桌宠 | ✅ 判定链 + 桌宠窗口已实现（待真实摸鱼场景验证） |
| M4 | 能用一天：自启、托盘、隐私档、纠错、数据清理 | 🟡 除「日报上的纠错入口」外都做了：设置面板含数据与缓存（查看截图/打开目录/保留天数/立即清理） |
| M5 | 长期可用：周报、趋势 | 🟡 周报/月报已做；跨月趋势折线、年度汇总还没做 |

**一句话**：核心链路（采集 → 分类 → 聚合 → 日报/周报/月报 → 提醒）已经跑通并在真实使用，
剩下的是打磨和使用中暴露的问题。

---

## 快速开始

```powershell
# 1) 先看效果：凭空造一天数据，生成一张示例日报（不碰你的屏幕）
#    用的是独立的 data/demo.db 和 reports/demo.html，绝不会动真实数据
python -m focuspet --demo

# 2) 看一下采集能不能读到你的窗口（只采一次，不常驻）
python -m focuspet --once

# 3) 正式跑（托盘 + 桌宠）
python -m focuspet

# 4) 只要后台、不要界面
python -m focuspet --headless

# 5) 生成并打开某天的日报（同一天重复生成会覆盖，只留一份）
python -m focuspet --report              # 今天
python -m focuspet --report 2026-11-05   # 指定日期
python -m focuspet --report --no-open    # 只要文件，不弹浏览器
```

依赖：

```powershell
pip install mss Pillow psutil PyYAML PySide6-Essentials
```

`PySide6` 只用于托盘和桌宠；缺了会自动退回无界面模式。

**默认节奏**：每 5 秒记一次窗口，**每 10 分钟截一张图**（切换窗口不再补拍）。
想更密就改 `config.yaml` 的 `capture.shot_interval_sec`，或在设置面板里调，不用改代码。

**日报规则**：一天一个文件 `data/reports/YYYY-MM-DD.html`，重复生成直接覆盖（先写临时文件
再原子替换，不会读到写了一半的页面）；生成后**用浏览器打开**——不依赖 `.html` 的系统关联，
因为那玩意儿可能被绑到编辑器上（这台机器就是 VSCode）。浏览器按 Edge → Chrome → Firefox
的顺序找，也可以在 `config.yaml` 的 `report.browser` 里写死路径。

**周报与月报**：

| 报表 | 什么时候出 | 文件名 | 手动生成 |
|---|---|---|---|
| 日报 | 每天 22:00 | `reports/2026-11-06.html` | `--report` |
| 周报 | 每周日 21:00 | `reports/weekly-2026-W45.html` | `--weekly` |
| 月报 | 每月最后一天 21:00 | `reports/monthly-2026-11.html` | `--monthly` |

一周按周一到周日算，月按自然月算。同一周/同一月重复生成只会覆盖同一个文件。
汇总只读 `block` 表（永久保留），所以清掉截图和明细也不影响历史周报。

想改时间就改 `config.yaml` 的 `report.weekly_day`（0=周一 … 6=周日）、
`report.weekly_time`、`report.monthly_time`。

**数据与缓存**（托盘右键 → 设置 →「数据与缓存」）：

| 项 | 默认 | 说明 |
|---|---|---|
| 截图保留 | 7 天 | 到点自动删 `data/shots/<日期>/` 整个目录 |
| 明细保留 | 30 天 | 删 `sample` 表里更早的行，`block` 与报表永久保留 |
| 自动清理 | 开 | 启动时 + 每天出完日报后各跑一次；删某天截图前会先把那天日报里的图片引用换成说明文字，避免历史报表断图 |
| 查看截图 | — | 打开今天的截图目录（今天还没有就打开截图根目录） |
| 打开工作区目录 | — | 打开含 `focuspet/` 的项目根目录 |
| 立即清理 | — | 按上面的天数立刻清一遍，并告诉你删了多少、释放多少 |

---

## 目录结构

```text
focuspet/
├─ main.py                 # 入口：DPI → 配置 → 三条线程 → Qt 事件循环
├─ config.py               # 配置加载与默认值合并（配置坏了自动重建）
├─ log.py                  # 按天轮转日志 + 心跳文件
├─ demo.py                 # 演示数据（占位图明确标注「非真实截图」）
├─ config.yaml             # 运行时生成，可直接改
├─ config/rules.yaml       # 40 条分类规则，改规则不用改代码
├─ capture/
│  ├─ win.py               # 前台窗口 / 空闲 / 全屏 / 标题脱敏（纯 ctypes）
│  ├─ shot.py              # mss 截图 + dHash 去重 + 过期清理
│  └─ store.py             # SQLite（WAL）+ jsonl 兜底 + 启动回放
├─ analyze/
│  ├─ rules.py             # 规则表匹配（A 档，零成本）
│  ├─ vlm.py               # 视觉模型客户端（B 档，urllib，OpenAI 协议）
│  ├─ scheduler.py         # 15 分钟批次，规则优先、模型兜底
│  └─ aggregate.py         # 段合并、时间块、五项指标、文案模板
├─ judge/
│  ├─ engine.py            # 离题判定链（全否才退出）
│  ├─ intervene.py         # L1–L4 分级、冷却、文案库
│  └─ learn.py             # 纠错回流
├─ report/
│  ├─ render.py            # 数据 → HTML
│  └─ template.html        # 单文件模板，内联 CSS，无前端框架
├─ ui/
│  ├─ tray.py              # 托盘菜单 + 线程/界面之间的队列
│  ├─ pet.py               # 桌宠窗口（QPainter 画的，无美术资源依赖）
│  └─ settings.py          # 设置面板
├─ scripts/
│  ├─ autostart.py         # 启动文件夹快捷方式（install / uninstall）
│  └─ watchdog.ps1         # 心跳超时自动重启
└─ data/                   # 运行时生成
   ├─ focuspet.db          # 真实数据
   ├─ demo.db              # 演示数据（--demo 专用，与真实库隔离）
   ├─ shots/YYYY-MM-DD/    # 真实截图
   ├─ shots-demo/          # 演示占位图
   └─ reports/             # 一天一份：YYYY-MM-DD.html；示例：demo.html
```

---

## 怎么接视觉模型

规则能覆盖的那 80% 不花钱，剩下 20% 才交给模型。设置环境变量后填配置：

```powershell
$env:FOCUSPET_KEY = "sk-..."
```

```yaml
# config.yaml
analyze:
  mode: cloud
  endpoint: "https://api.xxx.com/v1"   # 任何 OpenAI 协议地址
  model: "your-vision-model"
  daily_budget_cny: 2.0                # 超了自动降级为纯规则
```

本地模型（Ollama）同理，`endpoint` 填 `http://localhost:11434/v1`。
没有配置时程序照常跑，只是所有段落都由规则产出、置信度偏低。

---

## 和设计方案的一处差异

设计方案写的是「元数据优先、截图兜底」，实现时发现一个容易踩的坑并已修正：
**Windows 的最大化窗口，`GetWindowRect` 返回的也是整屏矩形**，如果直接拿它判断
「是否全屏」，日常所有最大化的窗口都会被当成全屏，截图就永远不截。
现在先用 `WS_MAXIMIZE` 样式位排除最大化窗口，再比较矩形。

除此之外，代码与文档的对应关系是逐一落实的，主要章节号在文件头的注释里。

---

## 隐私

- 截图只在本机，按天存 `data/shots/`，默认 7 天清一次。
- 敏感进程（密码管理器等）**连标题都不记**，只留时间戳。
- 标题命中「密码 / 转账 / 工资 / 身份证 / 银行卡」会被替换成 `<sensitive>`。
- 三档模式：`local` / `masked`（默认，裁掉任务栏再发图）/ `meta_only`。
- 如果这台电脑还有别人用，请先给 data 目录加密。

---

## 已知限制（都是刻意的）

1. **只做 Windows**。手机端是 P2，iOS 基本无解。
2. 只截主屏。多屏用户的副屏活动只有元数据，够用。
3. 判定 ≤ 15 分钟的延迟——提醒依赖批次分析，M2 之前不谈提醒是有原因的。
4. 桌宠是 QPainter 画的简笔角色，没有 Live2D；真的用起来了再说。
