# 参与贡献

感谢yv-bai提供的灵感和开发支持
---

## 1. 开发环境

```powershell
git clone <repo-url>
cd focuspet
pip install -r requirements.txt
python -m focuspet --demo      # 造一天数据，验证链路
```

`--demo` 用的是独立的 `data/demo.db` 和 `data/shots-demo/`，不会碰你的真实数据。
正式使用是 `python -m focuspet`（托盘 + 桌宠）。

跑测试式的自检不需要真的在电脑前待一天：

```powershell
python -m focuspet --duration 30   # 采集 30 秒，看日志和库有没有写进去
```

---

## 2. 从哪里改

| 你想改什么 | 改哪里 |
|---|---|
| 某个软件被认错了 | `focuspet/config/rules.yaml`（一条规则一个 id） |
| 提醒太吵 / 太安静 | `focuspet/config.py` 的 `DEFAULTS["judge"]` |
| 判定逻辑本身 | `focuspet/judge/engine.py`（六道门） |
| 提醒文案 | `focuspet/judge/intervene.py`（三档语气 + 正向文案） |
| 报表样式 | `focuspet/report/template.html`、`summary_template.html` |
| 周报/月报口径 | `focuspet/report/summary.py` |
| 设计文档 | `content/*.md`，改完跑 `python build_doc.py` |

代码注释里会标设计文档的章节号（例如「设计方案 10.2」），改逻辑前先读对应章节。

---

## 3. 加一条分类规则

```yaml
  - id: your_tool
    note: 一句话说明为什么这么判
    when: {proc: [YourApp.exe], title_contains: [可选关键字]}
    then: {category: deep_work, weight: 0.85, activity: 在干什么}
```

- `category` 只能是 `deep_work / shallow_work / learning / entertainment / aimless / life / system / unknown`
- `weight` ≥ 0.9 表示「不用看模型，直接采信」；0.6–0.9 表示「和模型交叉验证」；< 0.6 交给模型
- 加完跑一次 `--demo`，或者在设置里看当天的分类结果对不对

---

## 4. 提交与 PR

- 一次 PR 只做一件事，标题写清楚「改了什么、为什么」
- 涉及判定阈值、提醒策略的改动，请在 PR 描述里写：**改之前会怎样、改之后会怎样、你在自己机器上跑了几天的数据**
- 提交前必须跑通：`python -m focuspet --demo`
- 不要提交 `focuspet/data/`、`config.yaml`、任何截图或数据库（`.gitignore` 已覆盖，但请自己 `git status` 确认一遍）

提交信息建议用动词开头的一句话，中文或英文都行：

```
fix(rules): 把 Weixin.exe 归到浅层工作
feat(report): 周报加每日柱状图
docs(handoff): 记录 11-06 的评审加固
```

---

## 5. 绝对不要做的事

1. **不要把项目描述成「监控软件」**。它的定位是「给自己看的镜子」，一旦对外监控，性质和法律风险都变了。
2. **不要提交任何人的屏幕截图、窗口标题、数据库**。哪怕是演示数据，也要用 `--demo` 生成的占位图。
3. **不要为了「更准」把默认值调激进**。误报一次，用户就会关掉提醒——这是这个产品唯一的死法。
4. 不要引入需要常驻网络的依赖；断网必须能用。

---

## 6. 有问题

开 issue 时带上：系统版本、`focuspet/data/logs/` 里对应的日志片段（注意不要贴出私人窗口标题）、
以及复现步骤。如果是不希望公开的隐私相关问题，请私下联系维护者。
