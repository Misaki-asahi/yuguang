# HANDOFF · 「余光」AI 屏幕行为监测与桌宠提醒工具

> **项目级交接文档。** 上下文快满、或换一个新会话来继续时，先读这一份，再按需读设计文档。
> 版本 v1.2 ｜ 最后更新 2026-11-09 21:25 ｜ 维护方式见文末第 10 节。

---

## 0. 一句话现状

**项目已开源并在用**：代码 v0.3.1 正在用户机器上真实运行（每天持续记录），
设计文档 v1.1 已交付，仓库推到了 GitHub 公开仓库，协作者的桌宠动作包已并入 main。

```text
仓库  https://github.com/Misaki-asahi/yuguang    （main 分支，公开）
本地  E:\deepseek-data\workspaces\DeepSeekProjects\with席（git 已初始化，工作区干净）
同步  2026-11-09 21:01 从 3651994 快进到 8e0e0e5（PR #2 合并），此后 0 ahead / 0 behind
```

代码在 `focuspet/`，四条命令覆盖日常：

```powershell
python -m focuspet --demo        # 造一天数据出日报，不碰屏幕、不碰真实库
python -m focuspet               # 正式跑：托盘 + 桌宠
python -m focuspet --report      # 生成并打开今日日报（同日覆盖）
python -m focuspet --weekly      # 周报；--monthly 月报
```

**当前没有被指派的待办。** 下一步候选见第 8 节。
接着干之前先确认：用户要改的是「文档」「代码」还是「仓库/协作配置」——三块都别凭喜好重写。

---

## 1. 项目是什么

用户（`大纲.docx` 的作者）想做一个自用工具：后台常驻，每 5 秒记一次前台窗口、定时截一张图（**现默认 10 分钟一张**），用视觉大模型判断"此刻在干什么"，白天用桌宠轻提醒，晚上出一张时间轴日报，让人知道时间被什么吃掉了。

已由用户明确选择的定位，**不要擅自更改**：

- **个人自用工具** —— 不是课程作业、不是比赛作品、不是要商业化落地的产品
- **MVP 优先** —— 先跑起来，砍掉一切冗余设计
- **交付形态：Word 设计方案文档**（用户在两选一中选了"生成 Word 设计文档"）

原始构想只有 3 段文字（见 `大纲.docx`：目的、想法、桌宠化）。方案里所有结构性内容都是在此之上推导的，不是用户给定的。

---

## 2. 工作区文件地图

| 路径 | 是什么 | 能不能改 |
|---|---|---|
| `HANDOFF.md` | 本文件，项目状态与交接 | 每次会话结束时更新 |
| `余光_流程_大纲_设计方案_v1.1.docx` | **当前交付物**，40 页设计方案 | 只由脚本生成，不手改 |
| `余光_流程_大纲_设计方案_v1.0.docx` | 上一版存档（截图 60 秒版），只留作对比 | 不要再改，也不要再引用 |
| `content/part1.md` | 第一部分 流程设计（约 6.9k 字符） | 改文字改这里 |
| `content/part2.md` | 第二部分 项目大纲（约 4.1k 字符） | 同上 |
| `content/part3.md` | 第三部分 设计方案（最长，约 2 万字符） | 同上 |
| `content/appendix.md` | 附录 A–E（提示词 / 规则表 / 配置 / 文案 / 术语） | 同上 |
| `build_doc.py` | Markdown → docx 渲染器（排版、样式、目录、页眉页脚） | 改排版改这里 |
| `make_diagrams.py` | Pillow 画 5 张示意图（无 matplotlib 依赖） | 改图改这里 |
| `assets/fig*.png` | 生成的插图，被 docx 引用 | 由脚本覆盖，不手改 |
| `大纲.docx` | 用户原始构想，11KB | **只读，不要动** |
| `focuspet/` | **代码实现**（M0–M4 大部分），入口 `python -m focuspet` | 改代码改这里 |
| `focuspet/README.md` | 代码侧的说明：跑法、目录、限制 | 随代码更新 |
| `focuspet/docs/*.png` | 日报/周报/月报截图，GitHub 首页在用 | 由 `--demo` 后重截 |
| `focuspet/data/` | 运行时数据：db / shots / reports / logs | 可随时删掉重建；**已 gitignore，绝不入库** |
| `README.md` / `LICENSE` | 仓库门面（MIT 协议） | 对外口径改这里 |
| `CONTRIBUTING.md` | 贡献约定，**用户要求不公开**：已从 git 历史里抹掉并入 gitignore，只在本地保留 | 需要时私下发给协作者，不要提交 |
| `.github/` | issue 模板（bug / 功能）+ PR 模板 | 协作规则改这里 |
| `.gitignore` / `.gitattributes` | 排除数据与密钥；docx/图片按二进制处理 | 加新运行时目录时要同步 |
| `启动余光.bat` / `查看今日日报.bat` | 本机双击启动器（路径写死在用户机器上） | **已 gitignore**，别提交 |

---

## 3. 已完成（v1.2）

### 3.1 交付物结构

40 页，封面 + 摘要 + 目录 + 三个部分 + 附录：

- **第一部分　流程设计**（第 1–4 章）：用户旅程、系统主运行流程、采集/分析/日终子流程、离题判定决策流程、干预分级、纠错回流、异常降级
- **第二部分　项目大纲**（第 5–8 章）：一句话定位、P0/P1/P2 功能地图、16 个模块工时表（约 80h）、界面清单、M0–M5 里程碑、验收清单
- **第三部分　设计方案**（第 9–18 章）：六层架构、各层详细设计、SQLite 建表、技术选型对比、隐私三档、风险表、七天开工清单
- **附录**：A 提示词全文 / B 40 条分类规则 / C 完整 config.yaml / D 24 条桌宠文案 / E 术语表

### 3.2 质量检查（已通过）

- `python-docx` 重新打开：**427 段 / 65 表 / 5 图**，可稳定复现
- 正文与表格：**零 Markdown 残留**（无 `**`、反引号、裸 `|`），无乱码
- LibreOffice 渲染 40 页，逐页目视检查过封面、摘要、目录、流程图页、代码页、表格页
- 目录只收 H1/H2；早期版本曾被代码块里的 `# 注释` 污染，已修（`collect_entries` 跳过围栏）
- 中文弯引号已统一（ASCII `"` 自动转 “ ”，代码块内不转）

**v1.1（2026-11-06）复核**：仍 40 页 / 427 段 / 65 表 / 5 图，零 Markdown 残留；
抽查渲染页 7、8、18、22、24、32，图 1 与图 4 的新文案、10.5 性能表、11.5 成本表、
15.4 配置块均排版正常，无溢出。

### 3.3 代码实现（v0.3.1，2026-11-09）

按设计文档 15.3 的目录结构落地。Python 3.12，依赖 `mss / Pillow / psutil / PyYAML / PySide6-Essentials`。

**已完成并实机验证：**

- **采集**：ctypes 窗口探针（标题 / 进程 / PID，LRU 缓存）、`GetLastInputInfo` 空闲检测、mss 截图 1280 长边 + q70、dHash 汉明 ≤6 去重、黑屏（DRM）检测、SQLite WAL + 写失败落 jsonl + 启动回放
- **分析**：46 条 YAML 规则（A 档，零成本）——浏览器教育站 / GitHub 仓库页与中文界面 / 余光自己的报表都单独成规则、OpenAI 协议视觉客户端（B 档，三道校验 + 重试 + 预算熔断）。**B 档只补 A 档认不出的段**：每批先跑规则，挑出 `unknown` 段，只把这些段的采样/截图发给模型，回来的结论只填这些时间窗，已知段原样保留（不再整批替换）。模型判过的未知窗口落 `vlm_unknown` 表，`--suggest-rules` 归纳成候选规则（weight 固定 0.7，人工确认后再进 `config/rules.yaml`）。**批次窗口分两种**：没配模型时按 1 分钟一批（纯规则零成本，概览/日报才不至于等 15 分钟还是 0）；配了模型才是 15 分钟一批
- **聚合**：段合并（gap 180s / min_len 60s，deep_work 与 learning 视为同类）、灰段补洞、五项指标、文案模板
- **判定**：全否才退出的判定链；L1→L2→L3 按 2/3 分钟升级；冷却与日上限；同一段离题的升级不被冷却挡住
- **周报/月报**（`report/summary.py`）：每周日 21:00、每月最后一天 21:00 自动出，读 `block` 表汇总（清明细/截图不影响历史）；含每日柱状图、分类占比、逐日明细、与上周期对比；`--weekly` / `--monthly` 可手动生成，同周期覆盖同一文件
- **日报**：单文件 HTML，一句话结论 + 指标卡 + 时间轴 + 可点开的证据 + 一条建议。**一天只有一个文件**（`reports/YYYY-MM-DD.html`，先写 `.tmp` 再原子替换，重复生成即覆盖）；生成后**显式调用浏览器打开**（Edge/Chrome/Firefox 依次探测，可用 `report.browser` 指定），不走 `.html` 的系统关联
- **界面**：托盘菜单、设置面板（隐私档 / 截图间隔 / 批次 / 阈值 / 预算 / 数据与缓存）、QPainter 画的桌宠（不依赖美术资源）。设置里的「数据与缓存」可查看截图、打开工作区、调保留天数、立即清理（`maintenance.py`）。桌宠显示层级在控制面板里选三档：`ui.pet_mode` = `top`（始终置顶）/ `desktop`（只在桌面显示，沉到普通窗口下面）/ `hidden`（不显示，提醒退回托盘气泡）；托盘菜单里原来那个「显示桌宠」开关已删掉。声明过目标后，面板上的「开始专注…」变成「点击更换目标」
- **桌宠素材**（v0.3.1，协作者 `yv-bai` 的 PR #2）：手画小熊 → 静态立绘 → 逐帧动作包。`assets/pet/juyuan-pack/` 是 10 个状态、78–80 帧、220×211 画布的 webp 图集（约 6.8 MB，占了仓库大半体积）；`anim/` 负责 manifest 解析、图集切帧、按状态 fps 播放（`AssetStore` 只缓存最近 3 个状态，全预载要几百 MB）；`ui/pet.py` 只做窗口层。素材缺失时逐级回退，clone 下来没素材也能跑。会自己踱步、碰到屏幕边缘掉头、眼睛跟鼠标，`ui.pet_wander` / `ui.pet_speed` 控制
- **没声明目标时不再说谎**（2026-11-09）：日报和面板都改说「专注未统计（深度工作 X 小时 Y 分）」并附 `[沿用上次：…]`，不再出现「深度工作 4 小时 / 专注 0 分钟」；有目标但没攒出 25 分钟连续段时，写「有 X 的深度工作，但没有一段连续 25 分钟以上」。面板把「沿用上次」提成主按钮、`开始专注…` 降为次要；**启动时当天没目标就直接弹控制面板**并把焦点放到目标声明上（以前只发一条托盘气泡，图标被 Win11 塞进隐藏区就等于没提醒）。判断依据是 `aggregate.metrics` 新增的 `goal_tracked` / `deep_minutes`
- **运维**：心跳文件、`watchdog.ps1` 看门狗、`autostart.py` 自启（快捷方式放启动文件夹）、截图保留策略清理。2026-11-09 起自启优先指向 `%LOCALAPPDATA%\FocusPet\venv\Scripts\pythonw.exe`（纯英文路径），没有才回退项目 `.venv`；已装好 `Startup\FocusPet.lnk` → 该 pythonw `-m focuspet`，工作目录为仓库根（已实测 `autostart.pythonw()` 解析到 ASCII 路径且存在）
- **演示隔离**：`--demo` 用独立的 `data/demo.db` + `data/shots-demo/` + `reports/demo.html`，绝不会碰真实数据（有 `assert` 兜底）
- **离线可用**：除视觉模型外全链路不联网；没配模型时断网无感，配了模型断网则当批降级为规则结果（实测见第 7 节）

> **截图节奏是用户改过的（2026-11-06）**：默认 **600 秒一张**，并关掉「切窗口补拍」
> （`shot_on_window_change: false`）——不关的话，频繁切窗口会让「每 10 分钟一张」形同虚设。
> 文档已在 **v1.1** 同步：第一部分 1.1/2.3/2.4、第三部分 10.2/10.3/10.5/11.2/11.5/15.4、
> 附录 C、图 1、图 4 全部改成 10 分钟口径，代码与文档现在是一致的。
> 要再调节奏只动 `focuspet/config.yaml` 的 `capture.shot_interval_sec`，不用改代码。
> 代价要知道：15 分钟一批里通常只剩 1～2 张图，B 档画面信息变少、规则占比变高，
> 日报里「这一段没有留下截图」的段落会变多——这是少截图换来的，不是 bug。

**验证方式（都可复跑）：**

- `python -m focuspet --demo` → 19 段 / 专注 6h55 / 消耗 2h41 / 切换 17 次 / 有效比 70%
- 实机 `--once` 与 25 秒试跑：读到 `Weixin.exe`，截图 1280×752、53KB、约 230ms
- 假 API 端到端跑通 B 档：JSON 校验、时间窗裁剪、低置信度降级为 unknown 均符合 11.4
- 桌宠与设置面板在 offscreen 平台构造并渲染过（见 `focuspet/docs/preview.png`）

**刻意简化（不是遗漏）**：跨月趋势折线、年度汇总、Android、日历集成没做；判定依赖批次，提醒延迟 ≤ 1 分钟（未配模型时）。

### 3.4 按评审意见加固（2026-11-06 下午）

外部评审提了 5 条，逐条核过：

| # | 评审意见 | 结论 | 处理 |
|---|---|---|---|
| 1 | 自动清理截图可能让旧日报断链 | 真问题 | `maintenance.detach_shot_refs()`：删某天截图前，先把那天日报里的 `<img>` 换成「截图已按保留策略清理」，再删 |
| 2 | 周报/月报接入 AI 后 token 会指数累积 | 现在不成立 | 周报/月报**完全不调模型**，只读 `block` 表本地汇总，零 token。将来接模型时按评审建议走「结构化摘要」，别喂全文 |
| 3 | 网页标题更新有延迟，切过去的头几秒可能拿到旧标题 | 真问题 | 新增 `sample.settled` 列：切窗口后 3 秒内的采样照记但标 0，分类时跳过；老库自动 `ALTER TABLE` 补列，旧数据默认 1 |
| 4 | 切屏横跳会不会反复触发 | 基本已防 | 3 分钟门槛 + 段合并（gap 180s / min_len 60s）+ 10 分钟冷却已能挡住；另补一个真漏洞：只对「2 分钟内还在发生」的段落判定，避免拿几小时前的段落弹提醒 |
| 5 | 文案全在骂人，三周就被无视 | 真问题 | `intervene.POSITIVE` 加了 8 条正向文案，一段 ≥25 分钟的深度工作结束说一句，不占提醒配额、不走冷却、每天最多 6 次 |

### 3.5 GitHub 发布与协作（2026-11-06）

仓库：**https://github.com/Misaki-asahi/yuguang**（公开，`main` 分支，本地已 `remote add origin`）

- **59 个文件 / 1.7 MB**，提交历史干净（初始版本 → 模板 → 交接文档）；`.gitignore` 已排除 `focuspet/data/`、`*.db`、`config.yaml`、日志、两个本机 `.bat`、旧版 v1.0 文档
- 已从远端重新 clone 验证：**不含任何截图 / 数据库 / 配置**；README 配图、规则表、LICENSE 的 raw 链接均 200
- 发现过的坑：**GitHub 用户名是 `Misaki-asahi`，写成 `Misaki` 会报 `Repository not found`**（不是权限问题，是 URL 错了）
- 用户知情：仓库当前公开；改 private 不影响已加协作者，但已有的 fork 不会跟着变私有；免费版私有仓库协作者上限约 3 人
- 未做：分支保护规则（用户自己在 Settings → Rules 建）、GitHub Actions 冒烟测试

**CONTRIBUTING.md 不公开（2026-11-06，用户要求）**

已从仓库移除、写进 `.gitignore`、并重写历史强推（`cc0c033` → `4176164`）。
但 GitHub 不回收不可达对象：**旧提交 `cc0c033` / `987748a` 仍可凭 SHA 打开该文件**。
用户评估后选择接受（方案 A），不做删库重建——所以：

- 不要再为这个文件重写历史，也不要把它加回仓库
- 文件留在本地 3.4 KB，需要给协作者时私下发
- 如果哪天要求 100% 抹除，唯一办法是删库重建（步骤见本次会话记录）

---

## 4. 四条必须守住的判断

论证都写在 docx 里了，这里只记结论和位置，避免新会话把它们当成"可以优化掉的设计"：

| # | 判断 | 位置 | 如果被推翻会怎样 |
|---|---|---|---|
| 1 | **元数据优先、截图兜底**（不是"每隔一段截张图让 AI 看"） | 三部分 11.1 | 调用量 ×3，成本失控，准确率反而下降 |
| 2 | **先有目标声明，才有摸鱼判定** | 一部分 3.1 | 只能做分类，做不了提醒，整个桌宠功能失去依据 |
| 3 | **宁可漏报，不可误报**（判定链"全否才退出"） | 一部分 3.2 / 图 2 | 误报一次用户就关提醒，产品直接死亡 |
| 4 | **目标外但在学习/工作，不提醒**：算进有效比，不涨深度专注 | 2026-11-06 用户拍板 | 提醒「你在学习」是最招人烦的误报；而且规则模式判不准"这段和目标的语义关系"，配了模型也只在日报里体现，不弹窗 |

两条硬边界：**MVP 只做 Windows**（手机端 P2，iOS 基本无解）；**M2 之前不谈提醒**（没有时间轴就没有证据）。

> 第 4 条的实现口径（别好心改回去）：判定链第 3 道门只看 `category` 是否属于
> 消耗类（`CONSUMING`），学习/工作一律放行；`on_task` 在规则模式下是**按类别推断**
> 的，不是语义比对——只有配了视觉模型，模型才会真的读目标再判 `on_task`。
>
> 目标按**时刻**生效：`store.active_goal(ts)` 会比对 `started_ts`，声明之前的那几段
> 不补判（`on_task` 为 NULL）。所以 `--reclassify` 历史日期时，下午才写的目标
> 不会套到上午去——2026-11-09 修的就是这个。

---

## 5. 图号对照（最容易踩的坑）

文档里图的编号是**按出现顺序**排的，和文件名**不一致**。改图或增删图时必须同步维护：

| 文档内编号 | 对应文件 | 出现位置 |
|---|---|---|
| 图 1 | `assets/fig2_flow.png` | 第一部分 2.2 系统主运行流程 |
| 图 2 | `assets/fig3_decide.png` | 第一部分 3.2 离题判定决策流程 |
| 图 3 | `assets/fig5_report.png` | 第二部分 7.1 日报页结构示意 |
| 图 4 | `assets/fig1_arch.png` | 第三部分 9.1 系统总体架构 |
| 图 5 | `assets/fig4_data.png` | 第三部分 9.3 数据流与数据量级 |

引用方式：`content/*.md` 里写 `[[fig:assets/xxx.png|图 N　标题]]`，正文里还有"图 2 是…"这类文字引用，两处都要改。

---

## 6. 怎么改、怎么重新生成

### 6.1 只要改文字

编辑 `content/part1.md` / `part2.md` / `part3.md` / `appendix.md`，然后重新生成。

### 6.2 生成 docx

```powershell
$py = "E:\deepseek-data\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"   # 缺失时用 load_workspace_dependencies 重新取
& $py build_doc.py
```

> 两个解释器别混：**生成文档**用上面这个 DSH 运行时（它才有 python-docx）；
> **跑 focuspet** 一律用 `C:\Users\22760\AppData\Local\FocusPet\venv\Scripts\python.exe`
> ——必须在纯英文路径，项目内 `.venv` 虽然能起，但 Python 再拉 Edge 会退出码 21 秒退、托盘注册不上。

### 6.3 改了插图

```powershell
& $py make_diagrams.py     # 覆盖 assets/fig*.png（5 张）
& $py build_doc.py
```

### 6.4 视觉验收（必做）

用 `office-render` 技能里的 LibreOffice Kit CLI，渲染到工作区临时目录后逐页看图，检查完删掉临时目录：

```powershell
$node = "E:\deepseek harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
$cli  = "E:\deepseek harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js"
& $node $cli render --input "<docx 绝对路径>" --output-dir "<新建临时目录>/render" --pages "1,2,4,9"
```

### 6.5 内容规格

- 中文正文：宋体 10.5pt / 行距 1.4；标题：微软雅黑、深蓝 `#1F4E79`；强调色 `#B45309`
- A4，页边距 2.4/2.2/2.5/2.5cm；正文宽度 16cm
- 表格：首行深蓝底白字、隔行浅灰、≤22 行自动"整表不拆页"
- `build_doc.py` 支持的 Markdown 子集：`#/##/###`、`- `、`N. `、`> ` 引用块（含裸 `>` 空行）、```` ``` ````代码块、管道表格、`[[fig:path|caption]]`、`**粗体**`、`` `代码` ``

---

## 7. 已知坑（都踩过，别再踩）

| 现象 | 真相 | 怎么办 |
|---|---|---|
| 渲染图里每张插图都带一圈细边框 | **LibreOffice 的渲染行为**，docx 里没有边框（已显式加 `a:ln noFill`） | 不要追，Word 打开是干净的 |
| PowerShell 里 `-c` 拼 Python 报语法错 | 双引号 here-string 会吃掉反引号 | 用 `write` 落一个临时 `.py` 再执行 |
| 控制台中文显示成乱码 | GBK 终端，文件本身正常 | 用 `read` / `read_image` 验证，不要当成文件损坏 |
| 小表格被拆到两页 | LibreOffice 对 `keep_with_next` 支持不完整 | Word 里正常；真在意就把表格挪到页首 |
| Word 里中文变成默认字体 | 只设了 `run.font.name` 没设 `w:eastAsia` | `set_run()` 已经同时设 ascii/hAnsi/eastAsia，新代码照抄 |
| 日常窗口全被判定成「全屏」，截图一张不落 | 最大化窗口的 `GetWindowRect` 返回的也是整屏矩形（隐形边框） | 先看 `WS_MAXIMIZE` 样式位，再看矩形；`win.is_fullscreen` 已修 |
| 采样偶发写库失败，落在 `pending.jsonl` | dHash 是 64 位无符号数，SQLite INTEGER 只有 63 位 | `Store._s64()` 折成有符号；启动时 `replay_pending()` 补回 |
| 视觉模型的用户消息 `format` 抛 IndexError | 模板里的 `{[附上图片]}` 被当成占位符 | 转义成 `{{...}}`，改模板时注意花括号 |
| 日报 12 小时「在电脑前」偏大 | 空闲灰段被算进统计和「未识别」 | 灰段用独立 `gap` 分类，不参与任何比例（`aggregate.EXCLUDED`） |
| 点「打开今日日报」弹出的是 VSCode | 这台机器 `.html` 关联到了 VSCode，`os.startfile` 吃的是系统关联 | 改为显式找 Edge/Chrome/Firefox 并 `Popen` 打开；`report.browser` 可写死 |
| 跑 `--demo` 把当天真实数据清空了 | 演示默认用「今天」，且 `seed()` 会 `clear_day` + 删当天截图 | **已修**：`--demo` 改用 `demo.db`/`shots-demo`/`demo.html`，并加 `assert` 禁止打开真实库 |
| 「今日概览」全是 0，但日志明明在采样 | 概览读的是 `block`，而 block 只在批次结束时生成；原来不分模式一律 15 分钟一批，重启后要等满一个窗口 | **已修**：没配视觉模型时批次改 1 分钟（零成本），概览里同时显示采样条数与起点 |
| 自己的主窗口被记成「未识别」，有效比 0 | 规则表里没有这个进程（如 `DeepSeek Harness.exe`、`BongoCat.exe`） | 补 `config/rules.yaml`；已加 AI 工作台 / AI 站点 / 桌面挂件三条，现在 40 条 |
| 程序突然起不来，报 `No module named 'yaml'` | 依赖原来装在 DSH 的共享运行时里，那个环境被重置过（2026-11-08 早上发现 yaml/mss/psutil/PySide6 全没了） | 依赖装在 `C:\Users\22760\AppData\Local\FocusPet\venv`（**纯英文路径**）；项目里的 `.venv` 现在只作回退，在中文目录下它会连带出 Edge 秒退、托盘不显示 |
| 开机后托盘里找不到图标，以为没启动 | Windows 11 默认把新图标塞进「隐藏图标」；这台机器的注册表里 `pythonw.exe` 那条 **InitialTooltip 是空的**，所以在列表里可能只显示 pythonw | 加 `ipc.py`：再启动一次会连上已有实例并弹出「今日概览」（实测日志 `收到唤起请求`）。也可以在 设置→个性化→任务栏→其他系统托盘图标 里把「余光/pythonw」设为常显 |
| 浏览器里很多窗口判成「未识别」，日报一片灰 | 浏览器规则只认标题关键词，`browser_generic` 兜底就是 unknown；没有模型时没人来补 | 已补 `browser_edu`（课程/错题/作业）、`browser_github[_ui]`（仓库页 + 中文界面）、`browser_own_report`（看自己的账单）等 6 条，11-06 当天未识别从 ~176 分钟降到 77 分钟。日常用 `--unknown N` 看还缺什么，`--reclassify <日期>` 让历史数据用上新规则 |
| 声明了目标，但「深度专注」还是 0 | 专注只累计 `on_task=true` 且 ≥25 分钟的 deep_work 段；没目标时 `on_task` 是 null | 先声明目标；概览底部现在会直接提示这一点，启动 1 分钟也会弹一次提醒 |
| `git push` 报 `Repository not found` | 大概率是 **URL 里的 GitHub 用户名写错**（这次写成了 `Misaki`，实际是 `Misaki-asahi`），不是权限问题 | 先去网页确认仓库地址，再 `git remote set-url origin <正确地址>` |
| 担心把截图/数据库推上去 | `focuspet/data/` 与 `config.yaml` 已在 `.gitignore`，误用 `git add -f` 会进历史，删除需要 `git filter-repo` | 提交前 `git status` 扫一眼；永不对 data 目录用 `-f` |
| 在 DSH 会话里跑 `--demo` 报 `PermissionError: ...\data\logs\focuspet.log` | 不是代码问题：这个会话的文件写权限只授到工作区根，`focuspet/` 没继承到，pwsh 子进程写不进去 | 会话切到「完全权限」(full access)；`write`/`edit` 工具本身不受影响，只有启动子进程写文件才会撞上 |
| 会话里 `git fetch/push` 报 `schannel: SEC_E_NO_CREDENTIALS` | 这个 shell 拿不到 GitHub 凭据，不是仓库地址写错（`Repository not found` 才是地址错） | 推送在用户自己的终端做，或切完全权限后重试；拉取同理，别误判成远端有问题 |
| 程序已经在跑时 `--once` / `--duration` 不采集，只弹面板 | `main()` 里单实例锁在 `--once` 之前就抢了，抢不到就 `ipc.request_show()` 然后退出 | 想验采集：先退出常驻实例，或直接看 `data/logs/focuspet.log` 里「完成 N 个批次」有没有在走 |
| 报错里的路径显示成 `withϯ` | GBK 控制台的显示问题，文件本身正常 | 用 `read` / `read_image` 验证，别当成路径损坏 |
| 双击 `启动余光.bat` 毫无反应，程序不起来 | `.bat` 被存成了 UTF-8（含中文注释、LF 换行），cmd 按 GBK 解析时整行错位，`start` 直接失败；pythonw 又没有控制台，看不到任何报错 | `.bat` 必须**纯 ASCII + CRLF**，注释也只写英文；工作目录用 `pushd` 传，别写 `start /d "路径\"`（结尾反斜杠会吃掉引号）。两个 bat 已按此重写 |
| 配好模型后每批都报 `HTTP 400 ... max_tokens 超出范围 [1,1024]` | 智谱 GLM-4V 系列把 `max_tokens` 硬限在 1024，代码原来写死 1200 | 已改成读 `analyze.max_tokens`（默认 1024）；换别家模型可以调大 |
| 模型返回的 JSON 明明合法，却报「输出无法通过校验」 | 模型只精确到分钟，段起点会比窗口起点早几十秒，旧校验要求 `st >= win_start` 直接把整段丢掉 | 已给 1 分钟容差并裁回窗口（`vlm.validate`）；改时间窗逻辑时别再收紧回去 |

---

## 8. 未完成 / 可选的下一步

**文档侧没有半成品；代码侧 M0–M4 已可日常用，M5 做了一半。** 按性价比排序：

1. **继续跑，用真实数据打磨规则**（最该做的）—— 每天看日报，分类错了补 `config/rules.yaml`，指标口径不对改 `aggregate.py`
2. ~~**配视觉模型**~~ —— **2026-11-11 已配**：智谱 `glm-4v-flash`（免费），`FOCUSPET_KEY` 已写进用户环境变量，配置见 `analyze.endpoint/model`。`max_tokens` 只能 ≤1024（写大会被 400）。现在模型只补规则认不出的段，规则越准调用越少；攒几天后用 `--suggest-rules 7` 看候选规则
3. **GitHub 协作铺开** —— 分支保护规则、加协作者、GitHub Actions 跑 `--demo` 冒烟测试（Linux runner 上可行，demo 不依赖 Windows）
4. **金标集 100 条** —— 11.7 说的那个本子，是判断「改规则后变好还是变坏」的唯一依据
5. **M4 收尾** —— 托盘里「开始专注 / 休息」的闭环、日报上的纠错入口（`judge/learn.py` 已有能力，缺 UI）
6. **M5 剩下的趋势** —— 周报/月报已做；还差跨月趋势折线、年度汇总
7. **打包成 exe** —— PyInstaller，单文件，启动慢 1 秒可以接受
8. **精简版 15 页 / 评审 PPT / 成本测算表** —— 只有在要拿去汇报时才做

---

## 9. 新会话 Prompt（直接复制）

```text
我在做一个个人自用的桌面工具「余光」：后台常驻，定时采集前台窗口和截图，用视觉大模型判断我在干什么，白天用小桌宠轻提醒，晚上出一张时间轴日报。

工作区：就是含有 HANDOFF.md 的这个目录（工作区可以整体移动，本文不写死盘符）

现状：代码 v0.3.1 正在我机器上真实运行（每天 22:00 出日报、周日 21:00 周报、月末月报），
仓库已推到 GitHub：https://github.com/Misaki-asahi/yuguang

动手前按顺序读：
1) HANDOFF.md —— 项目交接与当前状态（必读，读了再动手）
2) focuspet/README.md —— 代码侧怎么跑、目录、限制
3) 余光_流程_大纲_设计方案_v1.1.docx —— 当前交付的 40 页设计文档（v1.0 是存档，别引用）
4) content/*.md —— 文档源文；focuspet/ —— 代码

必须守住的约束：
- 定位是「个人自用工具、MVP 优先」，不要往商业化或课程作品上靠
- 四条核心判断不要推翻：元数据优先截图兜底；先有目标声明才有摸鱼判定；宁可漏报不可误报；目标外但在学习/工作不提醒（详见第 4 节）
- MVP 只做 Windows，手机端是 P2
- 改文字改 content/*.md 后跑 build_doc.py；改代码改 focuspet/ 下的文件，用 --demo 自测
- 不要手改 docx，也不要动 大纲.docx（那是原始构想，只读）
- **永远不要把 focuspet/data/ 或 config.yaml 提交上去**（里面有截图和窗口标题）

这次要做的是：<在这里写具体需求>
```

### 建议下一个会话加载的技能

| 技能 | 什么时候用 |
|---|---|
| `office-docx` | 任何改 docx 的活（必备） |
| `office-render` | 改完必须看图验收 |
| `pptx` | 要做评审版幻灯片时 |
| `office-xlsx` | 要做成本测算表时 |
| `grill-me` | 用户想拷问方案、挑设计漏洞时 |
| `diagnose` | 代码侧出 bug、行为不符合预期时 |

### 代码侧自测（写进肌肉记忆）

```powershell
$py = "C:\Users\22760\AppData\Local\FocusPet\venv\Scripts\python.exe"   # 跑 focuspet 只用这个（纯英文路径）
Set-Location <工作区根>
& $py -m focuspet --demo                       # 链路自测，出日报（用 demo.db，不碰真实数据）
& $py -m focuspet --duration 25                # 试跑 25 秒，验采集线程（常驻实例在跑时会变成唤起面板）
# 看日报：用 headless Edge 截图，比肉眼开浏览器快
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --disable-gpu --window-size=1080,1180 --virtual-time-budget=4000 `
  --screenshot="<工作区>\focuspet\docs\preview.png" "file:///<工作区>/focuspet/data/reports/<日期>.html"
```

---

## 10. 维护约定

- **推送前必须先问用户**（2026-11-09 用户明确要求）：`git push` 一律先说明要推什么、得到同意再执行
- **每次会话结束前**：更新第 0 节（现状）和第 8 节（未完成），刷新顶部日期
- **交付物有变更时**：同步第 3 节和第 5 节的图号表，版本号 +0.1
- **代码有变更时**：同步第 3.3 节和 `focuspet/README.md` 的「现在做到哪了」
- **代码提交后**：`git add -A && git commit && git push`，让远端和本地一致（远端 = 交接的一部分）
- **不要把设计内容抄回本文件**：指到 docx 的章节号即可，抄了就会两份不同步
- 本文件是"给下一个会话看的"，不是"给用户看的产品文档"，语气可以直白，省略客套
