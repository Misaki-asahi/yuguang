# 「余光」项目交接 Prompt

> 用法：新会话开始时整段贴给模型（或让它先读这个文件）。最后一节写这次要做什么。
> 生成于 2026-11-28，对应提交 `3569375`。

---

## 0. 一句话

我在做一个**个人自用**的 Windows 桌面工具「余光」：后台常驻，每 5 秒记一次前台窗口、按需截屏，用规则＋视觉大模型判断我此刻在干什么；白天用桌宠轻提醒，晚上出一张时间轴日报，让我知道时间被什么吃掉了。

```text
仓库    https://github.com/Misaki-asahi/yuguang   （main，公开）
本地    E:\deepseek-data\workspaces\DeepSeekProjects\with席
运行    python -m focuspet
体量    焦点代码 5.5k 行 / 85 个跟踪文件 / 59 条分类规则
```

**不是**课程作业、不是比赛作品、不追求商业化。MVP 优先，砍冗余。

---

## 1. 文件地图

| 路径 | 是什么 | 能不能改 |
|---|---|---|
| `HANDOFF.md` | 项目交接与状态（36 万字级细节都在这里） | 每次会话结束更新 |
| `PROMPT.md` | 本文件，新会话的启动 Prompt | 大改动后同步 |
| `余光_流程_大纲_设计方案_v1.1.docx` | 40 页设计文档（当前交付物） | 只由 `build_doc.py` 生成 |
| `content/*.md` | 文档源文（改文字改这里） | 可改 |
| `build_doc.py` / `make_diagrams.py` | Markdown→docx 渲染 / 5 张示意图 | 可改 |
| `大纲.docx` | 用户原始构想（11KB） | **只读，不要动** |
| `focuspet/` | 全部代码 | 可改 |
| `focuspet/config/rules.yaml` | 59 条分类规则 + `volatile` 列表 | 最常改的文件 |
| `focuspet/data/` | 运行时数据（db / shots / reports / logs） | **gitignore，绝不提交** |
| `config.yaml`（仓库根） | 用户本机覆盖配置 | **gitignore，绝不提交** |
| `启动余光.bat` / `查看今日日报.bat` | 本机双击启动器 | 已 gitignore，纯 ASCII + CRLF |

代码分成六层：

```text
focuspet/
  capture/   采集：win.py 窗口探针 · shot.py 截图 · store.py SQLite
  analyze/   分析：rules.py 规则 · vlm.py 视觉模型 · aggregate.py 合并 · scheduler.py 调度
  judge/     判定：engine.py 判定链 · intervene.py 提醒 · learn.py 纠错学习
  report/    报表：summary.py 周月报 · render.py 日报 HTML
  ui/        界面：tray.py 托盘 · panel.py 控制面板 · pet.py 桌宠 · settings.py · fix.py 纠错
  main.py    入口与 CLI；config.py 默认配置；goalkind.py 目标类型
```

---

## 2. 运行流程（数据从屏幕到日报）

```text
① 采集（5 秒一次）
   前台窗口 → 进程名 / 标题 / 父进程（psutil 缓存）
   空闲检测（静止 5 分钟 → 记 idle，不出图）
   截图：10 分钟一张 + 切窗口停住 5 秒补拍（最小间隔 120 秒）
         只截前台窗口矩形（crop_to_window），1280 长边、q70
         dHash 去重、黑屏跳过、全屏跳过

② 分类（每批一次，默认 1 分钟 / 配模型时 15 分钟）
   规则优先：rules.yaml 命中 → 类别 + 权重（≥0.9 硬判，0.6~0.9 参考）
   只把两类段交给模型：
     a) unknown（规则认不出）
     b) volatile 列表里的进程（Gemini / WorkBuddy / Cursor / Code / Comfy…）
   模型结论回填这些时间窗，已知段原样保留
   模型若把工作降级成 life/system → 类别保留规则，只借用它的描述文字

③ 合并成块
   段合并（gap 180s / min_len 60s，短段并进邻居）
   证据投票：按「时长 × 置信度」复核类别，新类别需 >1.25 倍才改
   补灰段（未采集的时间，不插值）
   挂截图：优先同窗口的图，并记录 shot_ts / shot_proc

④ 出报表（默认 22:00）
   日报：单文件 HTML，结论 + 指标 + 时间轴 + 证据 + 一条建议
   周报（周日出）/ 月报（月末出）跟日报同一时间一起出，出完弹托盘通知
   出报表前自动跑：低置信度复核 → 规则巡检 → 目标语义匹配

⑤ 判定（提醒链路）
   只在「已声明目标」时生效；判定链全否才退出（宁可漏报）
   2/3 分钟升级 L1→L2→L3，冷却 + 日上限，正向反馈单独计数
```

---

## 3. 已完成

### 3.1 采集
- ctypes 窗口探针：标题 / 进程 / PID / **父进程**（父进程用于认 Steam/Epic 启动的游戏）
- 空闲检测、dHash 去重、DRM 黑屏跳过、全屏跳过
- 截图按前台窗口裁剪（1280 像素全给一个窗口，文字分辨率翻倍）
- 切窗口停住 5 秒补拍；每张图记录「拍的是哪个窗口、什么时候拍的」
- SQLite WAL + 写失败落 jsonl + 启动回放

### 3.2 分类
- **59 条规则**（A 档，零成本），支持四种条件：`proc` / `proc_contains` / `parent_contains` / `title_contains` / `title_regex`
- **视觉模型**（B 档）：智谱 `glm-4v-flash`（免费），OpenAI 兼容协议，三道校验 + 重试 + 预算熔断
- **volatile 机制**：内容不固定的应用（Gemini / WorkBuddy / Cursor / Code / Comfy Desktop / DeepSeek Harness…）每批都让模型看画面
- 模型输出容错：裸数组、中文类别别名、分钟级时间容差、时间线抽稀防截断
- 未识别段自动重试补洞（`fill_unknowns`，带回滚，最多 3 次）
- 纠错对话框：改分类 + 勾「加规则」→ 写 `learned_*` 规则
- 规则巡检、低置信度复核、目标语义匹配（出报前自动跑）

### 3.3 聚合与报表
- 段合并 + **证据投票** + 灰段补洞 + 五项指标（专注 / 消耗 / 切换 / 有效比 / 未识别）
- 日报单文件 HTML（同日覆盖，先写 `.tmp` 再原子替换，显式调浏览器打开）
- 周报 / 月报读 `block` 表本地汇总，零 token
- 置信度按块自身类别取最强判据显示

### 3.4 界面与运维
- 托盘菜单、控制面板（目标声明 + 目标类型 + 今日概览）、设置面板
- 桌宠：动作包 > 静态立绘 > 手画小熊，三级显示层级（top / desktop / hidden）
- 心跳文件、看门狗、开机自启、截图保留策略清理
- `--demo` 完全隔离（独立 db / 截图目录 / 报表），且**强制 rules_only 不出网**

### 3.5 文档
- 40 页设计文档（封面 + 三部分 + 附录 A–E）
- 质量检查：427 段 / 65 表 / 5 图，零 Markdown 残留

---

## 4. 配置流程

### 4.1 环境（这台机器）

```powershell
# 跑 focuspet 只用这个解释器（纯英文路径，换中文路径会 Edge 秒退、托盘注册不上）
$py = "C:\Users\22760\AppData\Local\FocusPet\venv\Scripts\python.exe"
# 依赖：mss Pillow psutil PyYAML PySide6-Essentials
# 生成 docx 用 DSH 运行时（它才有 python-docx），两个解释器别混
```

### 4.2 视觉模型（可选，不配也能跑）

```yaml
analyze:
  mode: rules+vlm          # rules_only 则完全不出网
  endpoint: https://open.bigmodel.cn/api/paas/v4
  model: glm-4v-flash      # 免费；max_tokens 硬上限 1024
```

Key 走环境变量 `FOCUSPET_KEY`（已写入用户环境变量）；也可写进 `config.yaml`。
换别家模型改 `endpoint` / `model` / `max_tokens` 即可。

### 4.3 配置文件

- `focuspet/config.py`：默认值（提交进仓库，改结构改这里）
- `config.yaml`（仓库根，gitignore）：本机覆盖，只写要改的键
- `focuspet/config/rules.yaml`：分类规则 + volatile 列表（**最常改**）

### 4.4 常用命令

```powershell
& $py -m focuspet                    # 正式跑：托盘 + 桌宠
& $py -m focuspet --demo             # 造一天数据出日报，不碰屏幕/真实库/网络
& $py -m focuspet --report [日期] --no-open   # 生成日报
& $py -m focuspet --weekly / --monthly        # 周报 / 月报
& $py -m focuspet --reclassify 2026-11-28     # 用新规则重算某天（会调模型）
& $py -m focuspet --unknown 2                 # 看还有哪些窗口没被识别
& $py -m focuspet --suggest-rules 7           # 从历史未识别归纳候选规则
& $py -m focuspet --fill-unknown 2            # 手动补洞
& $py -m focuspet --review / --rule-check / --match-goal
& $py -m focuspet --duration 25               # 试跑 25 秒（常驻在跑时会变成唤起面板）
& $py -m focuspet --once                      # 采样一次
```

### 4.5 自测（改完代码必跑）

```powershell
& $py -m compileall -q focuspet        # 语法
& $py -m focuspet --demo               # 链路：期望 19 段 / 专注 6h53 / 有效比 70%
```

---

## 5. 未解决的痛点（按严重度）

| # | 痛点 | 现状 | 影响 |
|---|---|---|---|
| 1 | **规则是「进程 → 类别」死映射** | 加了 `volatile`：这些进程每批让模型看画面 | 免费模型对这类窗口大量判成 `life`/`system`，只能做到「描述跟着内容走、类别不跟着」 |
| 2 | **全屏窗口不截图** | 防 DRM 黑屏，全屏直接跳过 | 游戏/视频时段模型没有画面，只能靠进程名和父进程 |
| 3 | **截图与进程粒度不一致** | 已记录 `shot_ts`/`shot_proc` 并在图注标明 | 仍会出现「进程 Qoder、图是 10 分钟前的微信」，只是现在看得见了 |
| 4 | **短段被吞** | `min_len 60s` 把几十秒的段并进邻居 | 快速切换时类别按「邻居」算；1.25 倍投票只能救回一部分 |
| 5 | **没有金标集** | 文档 11.7 提过 100 条本子，一直没做 | 无法量化「改规则是变好还是变坏」，只能凭日报观感 |
| 6 | **模型输出不稳定** | 已修：裸数组 / 中文类别 / 截断 / 时间容差 | 仍偶发「无法通过校验」，整批降级为规则结果 |
| 7 | **未识别仍有残留** | 剩百度网盘、空标题页面等 | 每天几段 1–2 分钟，不影响大局 |
| 8 | **无自动化测试** | 只有 `--demo` 冒烟 | 改聚合/判定链路靠人眼回归 |
| 9 | **截图存储增长** | 补拍后每天约 100–200 张、10–15 MB | 7 天保留策略能挡住，但没测过长期 |
| 10 | **只支持 Windows、未打包** | MVP 决定 | 换机要重装环境 |

---

## 6. 不能推翻的四条判断

1. **元数据优先、截图兜底**——不是「每隔一段截图让 AI 猜」
2. **先有目标声明，才有摸鱼判定**——没目标只做分类，不提醒
3. **宁可漏报，不可误报**——判定链全否才退出；误报一次用户就关提醒
4. **目标外但在学习/工作，不提醒**——算进有效比，不涨深度专注

另有两条硬边界：**只做 Windows**；**专注口径不变**（`deep_work + on_task + 单段 ≥25 分钟`）。

---

## 7. 接手须知

- 推送到 GitHub **不必每次问**；只有重写历史 / 删数据 / 改 `.gitignore` 时才先说明
- **永远不要提交** `focuspet/data/`、`config.yaml`、`*.db`、两个 `.bat`
- 改代码后至少跑 `compileall` + `--demo`，两者都要过
- 改完记得重启常驻进程（`Stop-Process` on `data/instance.lock` 里的 PID，再 `启动余光.bat`）
- 分析类改动先在当天数据上 `--reclassify <今天>` 看效果，再决定要不要推
- 中文路径下的 `.venv` 能起但会连带 Edge 秒退——只用 `%LOCALAPPDATA%\FocusPet\venv`

---

## 8. 下一步候选（按性价比）

1. **攒金标集**：从最近 7 天日报里挑 100 段人工标类别，之后每次改规则都跑一遍比准确率
2. **换更强的视觉模型**（qwen-vl-plus / gpt-4o-mini），验证「volatile 段的类别能否跟着内容走」——一天几分钱
3. **全屏也截图**（配置开关），看游戏/视频时段能否被模型认出来，代价是黑图和隐私
4. **打包 exe**（PyInstaller），换机即用
5. 跨月趋势折线、年度汇总

---

## 9. 这次要做的是

> 在这里写具体需求。动手前先读 `HANDOFF.md` 第 4、7 节，别把踩过的坑再踩一遍。
