# 附录

## 附录 A　视觉模型提示词全文

分系统提示词和用户消息两部分。系统提示词固定不变（可被缓存降价），用户消息每批一换。

### A.1 系统提示词

```text
你是一个屏幕行为分析助手。你的任务是根据用户一段时间内的前台窗口记录和若干张屏幕截图，
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
"category":"...","on_task":true,"confidence":0.0,"evidence":"..."}]}
```

### A.2 用户消息模板

```text
【用户今日目标】
{goal_text}

【时间窗】
{window_start} 到 {window_end}

【前台窗口记录】
{timeline_lines}

【屏幕截图（按时间顺序，共 {n} 张）】
{[附上图片]}

【上一批结论（仅供参考，可以推翻）】
{prev_summary}

请分析以上内容，输出 JSON。
```

### A.3 提示词调优的五个经验

1. **把"不要猜"写成可执行的规则**（证据不足就填 unknown），比写"请准确判断"有效十倍。
2. **给 category 一个封闭列表**，否则模型会自创 `entertainment_video` 这类值。
3. **时间窗和 prev 必须给**，否则相邻两批的结论会互相矛盾。
4. **不要让它输出评分或建议**，那是模板代码的活儿，模型做不好还浪费 token。
5. **每次改提示词都要重跑金标集**，否则你不知道是变好还是变坏。

## 附录 B　分类规则表（起始版 40 条）

先用这张表覆盖大头，跑一周后再补。`权重` 越高越优先于模型判断。

| 匹配对象 | 匹配方式 | 类别 | 权重 |
|---|---|---|---|
| Code.exe / pycharm64.exe / idea64.exe / devenv.exe | 进程 | deep_work | 0.95 |
| Obsidian.exe / Typora.exe / WINWORD.EXE | 进程 | deep_work | 0.9 |
| Photoshop.exe / Illustrator.exe / Figma | 进程 | deep_work | 0.9 |
| WindowsTerminal.exe / powershell.exe / cmd.exe | 进程 | deep_work | 0.85 |
| Teams.exe / Zoom.exe / wemeetapp.exe / DingTalk.exe | 进程 | shallow_work | 0.85 |
| Outlook.exe / foxmail.exe | 进程 | shallow_work | 0.8 |
| chrome.exe + 标题含"文档""文档中心""语雀""飞书" | 进程+标题 | learning | 0.8 |
| chrome.exe + 标题含"Stack Overflow""GitHub""MDN" | 进程+标题 | learning | 0.85 |
| chrome.exe + 标题含"哔哩哔哩""YouTube""抖音""爱奇艺""腾讯视频" | 进程+标题 | entertainment | 0.9 |
| chrome.exe + 标题含"微博""小红书""知乎" | 进程+标题 | aimless | 0.75 |
| chrome.exe + 标题含"淘宝""京东""拼多多" | 进程+标题 | life | 0.8 |
| Steam.exe / EpicGamesLauncher.exe / WeGame.exe | 进程 | entertainment | 0.95 |
| 游戏进程（标题含 "DirectX" 或全屏独占） | 进程+状态 | entertainment | 0.9 |
| WeChat.exe / QQ.exe + 标题含"聊天" | 进程+标题 | shallow_work | 0.6 |
| explorer.exe + 无标题 | 进程 | system | 0.7 |
| 任务管理器 / 设置 / 控制面板 | 进程+标题 | system | 0.8 |
| 标题含"密码""转账""支付""身份证" | 标题 | sensitive | 1.0 |
| 空闲超过 5 分钟 | 状态 | unknown | 1.0 |
| 进程为未知 + 标题为空 | 兜底 | unknown | 0.3 |
| 锁屏 / 屏保 | 状态 | system | 0.9 |

完整的 40 条建议按"办公 / 学习 / 开发 / 娱乐 / 生活 / 系统"六组各 6～8 条铺开，直接写在 `config/rules.yaml` 里，每条带 id 和一句注释说明为什么这么判。

## 附录 C　完整配置示例

```yaml
# config.yaml
version: 1

capture:
  window_poll_sec: 5           # 前台窗口轮询间隔
  shot_interval_sec: 600       # 定时截图间隔（10 分钟一张）
  shot_on_window_change: false # 窗口切换不补拍，否则间隔形同虚设
  idle_threshold_sec: 300      # 超过即视为离开
  max_shot_side: 1280          # 长边像素
  jpeg_quality: 70
  screens: [1]                 # 1 = 主屏

analyze:
  batch_minutes: 15
  mode: cloud                  # cloud | local | rules_only
  endpoint: ""                 # 兼容 OpenAI 协议的地址
  model: ""
  api_key_env: FOCUSPET_KEY    # 从环境变量读，不写死在文件里
  min_confidence: 0.6
  daily_budget_cny: 2.0
  retry: 2
  timeout_sec: 30

judge:
  enabled: true
  off_task_minutes: 3
  cooldown_minutes: 10
  l2_daily_cap: 12
  l3_daily_cap: 5
  rest_minutes: 10
  escalate_after_minutes: [2, 3]   # L1→L2, L2→L3

privacy:
  mode: masked                 # local | masked | meta_only
  strip_crop: [0, 0, 1.0, 0.94] # 裁掉底部 6%（任务栏/通知区）
  sensitive_procs:
    - KeePass.exe
    - 1Password.exe
    - Bitwarden.exe
  sensitive_keywords: [密码, 转账, 工资, 身份证, 银行卡]

retention:
  shots_days: 7
  samples_days: 30
  logs_days: 7

ui:
  pet_enabled: true
  pet_position: [1720, 900]
  pet_scale: 1.0
  theme: light
  autostart: true
```

## 附录 D　桌宠文案库（24 条）

文案是这个产品的人格。原则：**短、具体、不说教、给台阶**。分三档口吻，在设置里可切换。

### D.1 温和（默认）

1. 在忙别的吗？刚才那份文档还开着。
2. 说好的 {goal}，要不要再看一眼？
3. 已经离开 6 分钟了，回来吧。
4. 我帮你记着时间呢，还剩 {left} 分钟。
5. 要不先喝口水，然后继续？
6. 刚刚切了 5 次窗口，试试只看一件事？
7. 这个好像不在今天的计划里。
8. 休息可以，说一声我就不吵了。

### D.2 调侃

9. 又见面了，这已经是今天第三次了。
10. 你和 B 站的关系，好像比和目标的关系更近。
11. 这个视频讲得真不错，可惜不是今天的任务。
12. 我什么都没说，我只是站在这里。
13. 再刷五分钟？上次的五分钟是 23 分钟。
14. 你的手速比你的专注力快多了。
15. 提醒一下，今天的目标还在原地等你。
16. 摸鱼可以，但别摸成习惯。

### D.3 犀利（需手动开启）

17. 这是今天第 {n} 次了，我记着呢。
18. 现在这个时间，本来应该是 {task}。
19. 你可以选择继续，日报上会写清楚。
20. 顺手打开和有意打开，区别很大。
21. 今天的专注时长，还差 {x} 分钟到及格线。
22. 不是不让你玩，是不想你晚上后悔。
23. 我已经提醒过 {n} 次了，接下来交给你。
24. 关掉这个页面的成本，比晚上后悔低。

### D.4 被提醒后的回应文案

| 用户动作 | 桌宠回应 |
|---|---|
| 点"我去干活" | 好，我盯着。（然后安静 10 分钟） |
| 点"我就歇会儿" | 行，{n} 分钟后见。 |
| 点"我在做正事" | 明白了，这个记下来，下次不吵你。 |
| 直接关掉 | （不说话，只记一笔） |

## 附录 E　术语表

| 术语 | 含义 |
|---|---|
| 采样（sample） | 每 5 秒记录一次前台窗口，按需附带一张截图 |
| 批次（batch） | 每 15 分钟聚合一次采样，作为一个分析单元交给模型 |
| 时间块（block） | 合并后的一段连续同类活动，日报的最小展示单元 |
| 专注会话（session） | 用户声明目标后开启的一段时间，判定只在会话内生效 |
| 离题（off-task） | 当前活动与声明的目标不一致，且持续超过阈值 |
| 豁免（exempt） | 命中白名单或会议场景，不参与离题判定 |
| 冷却（cooldown） | 同一类提醒的最短间隔，防止轰炸 |
| 恢复力 | 被提醒后 5 分钟内回归任务的比例，衡量工具是否有用 |
| 金标集 | 100 条人工标注的样本，用于测准确率和回归验证 |
| 有效比 | 生产性时长除以在电脑前时长，去掉了空闲时间 |
