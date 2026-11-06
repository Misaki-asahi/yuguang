# -*- coding: utf-8 -*-
"""生成设计方案文档所需的示意图（Pillow 绘制，无 matplotlib 依赖）。"""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "assets")
os.makedirs(OUT, exist_ok=True)

FR = r"C:\Windows\Fonts\msyh.ttc"
FB = r"C:\Windows\Fonts\msyhbd.ttc"

INK    = "#1F2937"
SUB    = "#4B5563"
PRIMARY   = "#1F4E79"
PRIMARY_L = "#DEE9F4"
ACCENT    = "#B45309"
ACCENT_L  = "#FCEEDC"
GREEN     = "#2F6B3C"
GREEN_L   = "#E7F2EA"
GRAY_BG   = "#F3F5F8"
BORDER    = "#C9D2DB"
WHITE     = "#FFFFFF"
RAIL      = "#8899AA"


def F(size, bold=False):
    return ImageFont.truetype(FB if bold else FR, size)


def rrect(d, box, r=14, fill=None, outline=None, w=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)


def ctext(d, box, s, font, fill, lh=None):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    lines = s.split("\n")
    lh = lh or (font.size + 10)
    total = lh * len(lines)
    cy = (y0 + y1) / 2 - total / 2 + lh / 2
    for ln in lines:
        d.text((cx, cy), ln, font=font, fill=fill, anchor="mm")
        cy += lh


def ltext(d, x, y, s, font, fill, anchor="lm"):
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)


def dashed(d, p1, p2, color, w=3, dash=14, gap=10):
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    L = (dx * dx + dy * dy) ** 0.5
    if L == 0:
        return
    ux, uy = dx / L, dy / L
    t = 0.0
    while t < L:
        e = min(t + dash, L)
        d.line([(x1 + ux * t, y1 + uy * t), (x1 + ux * e, y1 + uy * e)], fill=color, width=w)
        t = e + gap


def head(d, tip, direction, color, size=16):
    ux, uy = direction
    L = (ux * ux + uy * uy) ** 0.5
    ux, uy = ux / L, uy / L
    px, py = -uy, ux
    bx, by = tip[0] - ux * size * 1.5, tip[1] - uy * size * 1.5
    d.polygon([tip, (bx + px * size * 0.65, by + py * size * 0.65),
               (bx - px * size * 0.65, by - py * size * 0.65)], fill=color)


def arrow(d, p1, p2, color=RAIL, w=3, size=15, dashed_=False, both=False):
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    L = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / L, dy / L
    hl = size * 1.5 * 0.92
    s = (x1 + ux * hl, y1 + uy * hl) if both else (x1, y1)
    e = (x2 - ux * hl, y2 - uy * hl)
    if dashed_:
        dashed(d, s, e, color, w)
    else:
        d.line([s, e], fill=color, width=w)
    head(d, (x2, y2), (ux, uy), color, size)
    if both:
        head(d, (x1, y1), (-ux, -uy), color, size)


# ----------------------------------------------------------------------------
# 图 1：系统总体架构（分层）
# ----------------------------------------------------------------------------
def fig1():
    W = 1600
    _layers_h = [96, 128, 112, 140, 112, 140, 92]
    _gap = 64
    H = 46 + sum(_layers_h) + _gap * (len(_layers_h) - 1) + 56
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)

    x0, x1 = 40, 1560
    label_w = 132
    cx0, cx1 = x0 + label_w + 18, x1 - 14
    gap = _gap

    layers = [
        ("使用者", 96, "#F7F9FB", [
            ("声明今日目标", "goal"), ("看日报 / 纠错", "goal"),
            ("被桌宠提醒", "goal"), ("拖一拖，关掉", "goal")], "plain"),
        ("交互层", 128, PRIMARY_L, [
            ("托盘图标", "p"), ("桌宠窗口", "p"), ("日报 HTML", "p"),
            ("设置面板", "p"), ("专注面板", "p")], "primary"),
        ("干预层", 112, ACCENT_L, [
            ("触发规则引擎", "a"), ("冷却 / 豁免", "a"), ("分级提醒 L1-L4", "a")], "accent"),
        ("分析层", 140, GREEN_L, [
            ("预过滤 · 规则", "g"), ("批任务调度", "g"), ("视觉大模型", "g"),
            ("结构化解析", "g"), ("聚合与指标", "g")], "green"),
        ("存储层", 112, "#EEF1F4", [
            ("SQLite 元数据", "n"), ("截图目录（本地）", "n"), ("运行日志", "n")], "neutral"),
        ("采集层", 140, PRIMARY_L, [
            ("窗口探针 5s", "p"), ("截图器 600s", "p"),
            ("空闲检测", "p"), ("敏感过滤", "p")], "primary"),
        ("数据来源", 92, "#F7F9FB", [
            ("屏幕画面", "plain"), ("前台窗口 / 进程", "plain"), ("键鼠活动", "plain")], "plain"),
    ]

    styles = {
        "primary": (WHITE, PRIMARY, PRIMARY, F(25)),
        "accent":  (WHITE, ACCENT, ACCENT, F(25)),
        "green":   (WHITE, GREEN, GREEN, F(25)),
        "neutral": (WHITE, SUB, SUB, F(25)),
        "plain":   (WHITE, BORDER, SUB, F(24)),
    }

    y = 46
    bands = []
    for title, h, bg, items, kind in layers:
        bands.append((y, y + h))
        band = (x0, y, x1, y + h)
        rrect(d, band, 16, fill=bg, outline=BORDER, w=2)
        rrect(d, (x0, y, x0 + label_w, y + h), 16, fill=PRIMARY, outline=PRIMARY, w=2)
        d.rectangle((x0 + label_w - 18, y + 1, x0 + label_w, y + h - 1), fill=PRIMARY)
        ctext(d, (x0, y, x0 + label_w, y + h), title, F(26, True), WHITE)
        n = len(items)
        inner_pad = 14
        avail = (cx1 - cx0) - inner_pad * 2
        bw = (avail - 16 * (n - 1)) / n
        for i, (txt, _) in enumerate(items):
            bx = cx0 + inner_pad + i * (bw + 16)
            fill, outline, fg, font = styles[kind]
            rrect(d, (bx, y + 20, bx + bw, y + h - 20), 10, fill=fill, outline=outline, w=2)
            ctext(d, (bx, y + 20, bx + bw, y + h - 20), txt, font, fg)
        y += h + gap

    for i in range(len(bands) - 1):
        for xx in (520, 1080):
            arrow(d, (xx, bands[i][1] + 2), (xx, bands[i + 1][0] - 2), RAIL, 3, 13, both=True)

    ltext(d, 44, H - 22, "↑ 数据上行（采样 → 分析 → 呈现）    ↓ 控制下行（规则 / 配置 / 干预）",
          F(22), SUB)
    im.save(os.path.join(OUT, "fig1_arch.png"))


# ----------------------------------------------------------------------------
# 图 2：系统主运行流程
# ----------------------------------------------------------------------------
def fig2():
    nodes = [
        ("term", "开机自启 · 托盘常驻（pythonw 无窗口）"),
        ("proc", "载入配置 · 恢复昨日状态"),
        ("proc", "打开面板 → 声明今日目标（可跳过 = 仅记录模式）"),
        ("proc", "启动专注会话：目标 + 截止时间写入 goal 表"),
        ("proc", "采集：元数据 5s · 截图 600s 定时触发"),
        ("proc", "落库：哈希去重 · 敏感过滤 · idle 跳过"),
        ("dec", "距上次分析满 15 分钟？"),
        ("proc", "批分析：截图 + 元数据 → VLM → JSON"),
        ("proc", "聚合：合并同类段 · 更新时间轴与指标"),
        ("dec", "当前活动偏离目标？"),
        ("proc", "干预：选档 → 冷却检查 → 提醒"),
        ("dec", "到 22:00 日终？"),
        ("proc", "生成 HTML 日报 → 浏览器打开 → 归档"),
    ]
    W = 1500
    cx = 780
    bw, n_h, d_h = 780, 84, 132
    gap = 44
    y = 54
    pos = []
    for kind, txt in nodes:
        h = d_h if kind == "dec" else n_h
        pos.append((y, h, kind, txt))
        y += h + gap
    H = int(y - gap + 90)

    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)
    rail_x = 250

    for (yy, h, kind, txt) in pos:
        if kind == "dec":
            pts = [(cx, yy), (cx + bw / 2, yy + h / 2), (cx, yy + h), (cx - bw / 2, yy + h / 2)]
            d.polygon(pts, fill=ACCENT_L, outline=ACCENT)
            d.line(pts + [pts[0]], fill=ACCENT, width=3, joint="curve")
            ctext(d, (cx - bw / 2 + 120, yy, cx + bw / 2 - 120, yy + h), txt, F(26, True), ACCENT)
        else:
            fill = PRIMARY_L if kind == "proc" else "#E8EEF4"
            rrect(d, (cx - bw / 2, yy, cx + bw / 2, yy + h), 12,
                  fill=fill, outline=PRIMARY, w=2)
            ctext(d, (cx - bw / 2, yy, cx + bw / 2, yy + h), txt, F(25), PRIMARY)

    for i in range(len(pos) - 1):
        y1, h1, k1, _ = pos[i]
        y2, _, k2, _ = pos[i + 1]
        arrow(d, (cx, y1 + h1), (cx, y2), PRIMARY, 3, 14)
        if k1 == "dec":
            ltext(d, cx + 14, y1 + h1 + 20, "是", F(22), GREEN)

    # 否 → 左侧回流轨
    decs = [(yy, h) for (yy, h, k, _) in pos if k == "dec"]
    rail_top = pos[3][0] + pos[3][1] / 2
    rail_bot = decs[-1][0] + decs[-1][1] / 2
    dashed(d, (rail_x, rail_top), (rail_x, rail_bot), RAIL, 3, 16, 10)
    for (yy, h) in decs:
        my = yy + h / 2
        dashed(d, (cx - bw / 2, my), (rail_x, my), RAIL, 3, 14, 9)
        ltext(d, rail_x + 16, my - 22, "否", F(21), ACCENT)
        arrow(d, (rail_x, my), (cx - bw / 2, my), RAIL, 3, 12)
    arrow(d, (rail_x, rail_top), (cx - bw / 2, rail_top), RAIL, 3, 13)
    ltext(d, rail_x - 16, (rail_top + rail_bot) / 2, "主\n循\n环", F(21, True), RAIL, anchor="rm")

    im.save(os.path.join(OUT, "fig2_flow.png"))


# ----------------------------------------------------------------------------
# 图 3：摸鱼判定决策流程
# ----------------------------------------------------------------------------
def fig3():
    items = [
        ("dec", "当前处于专注会话内？", "不判定，仅记录"),
        ("dec", "命中豁免名单 / 白名单？", "放过，不提醒"),
        ("dec", "判定离题\n（元数据优先，无结论再看截图，置信度 ≥ 0.7）", "记「疑似」，不提醒"),
        ("dec", "离题连续 ≥ 3 分钟？", "继续观察"),
        ("dec", "处于冷却期内？", "只记录，不打扰"),
        ("dec", "当日 L3 提醒已达上限？", "不再升级，改为记录"),
        ("act", "触发干预：按强度选档 L1 / L2 / L3", ""),
        ("dec", "2 分钟后复查：已回到任务？", "升一档重试"),
    ]
    W = 1520
    cx = 570
    bw, dh, ah = 800, 150, 96
    gap = 52
    y = 50
    pos = []
    for kind, txt, alt in items:
        h = ah if kind == "act" else dh
        pos.append((y, h, kind, txt, alt))
        y += h + gap
    H = int(y - gap + 90)

    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)

    for (yy, h, kind, txt, alt) in pos:
        if kind == "act":
            rrect(d, (cx - bw / 2, yy, cx + bw / 2, yy + h), 12, fill=GREEN_L, outline=GREEN, w=3)
            ctext(d, (cx - bw / 2, yy, cx + bw / 2, yy + h), txt, F(26, True), GREEN)
        else:
            pts = [(cx, yy), (cx + bw / 2, yy + h / 2), (cx, yy + h), (cx - bw / 2, yy + h / 2)]
            d.polygon(pts, fill="#FFF9F0", outline=ACCENT)
            d.line(pts + [pts[0]], fill=ACCENT, width=3, joint="curve")
            ctext(d, (cx - bw / 2 + 150, yy + 8, cx + bw / 2 - 150, yy + h - 8), txt, F(25, True), ACCENT)
        if alt:
            oy = yy if kind == "act" else yy + (h - 56) / 2
            rrect(d, (1010, oy, 1010 + 440, oy + 56), 10, fill=GRAY_BG, outline=BORDER, w=2)
            ltext(d, 1030, oy + 28, "→ " + alt, F(22), SUB)

    for i in range(len(pos) - 1):
        y1, h1, k1, _, _ = pos[i]
        y2, _, _, _, _ = pos[i + 1]
        arrow(d, (cx, y1 + h1 + 2), (cx, y2 - 2), PRIMARY, 3, 14)
        ltext(d, cx + 16, (y1 + h1 + y2) / 2, "是" if k1 == "dec" else "", F(21), GREEN)

    # 否 → 右侧结果
    for i, (yy, h, kind, txt, alt) in enumerate(pos):
        if kind == "dec":
            my = yy + h / 2
            d.line([(cx + bw / 2, my), (1002, my)], fill=RAIL, width=3)
            arrow(d, (cx + bw / 2, my), (1010, my), RAIL, 3, 12)
            ltext(d, cx + bw / 2 + 18, my - 34, "否", F(21), ACCENT)

    ltext(d, 40, H - 40, "说明：任一环节判「否」即退出判定链，本次不触发提醒；只有全部为「是」才进入干预。",
          F(21), SUB)
    im.save(os.path.join(OUT, "fig3_decide.png"))


# ----------------------------------------------------------------------------
# 图 4：数据流与数据量级
# ----------------------------------------------------------------------------
def fig4():
    W, H = 1700, 650
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)

    stages = [
        ("Sample", "采样记录\n（元数据 + 截图）", "每 5 秒 1 条\n每天约 1 万条", PRIMARY),
        ("Analysis", "分析结果\n（活动 / 类别）", "每 15 分钟 1 批\n每天约 40 批", GREEN),
        ("Block", "时间块\n（合并后的段）", "每天 30-60 块", ACCENT),
        ("Report", "日报\n（HTML 页面）", "每天 1 页", SUB),
    ]
    n = len(stages)
    bx, by, gapx = 70, 78, 54
    bw = int((W - 2 * bx - (n - 1) * gapx) / n)
    bh = 186
    for i, (tag, name, vl, col) in enumerate(stages):
        x = bx + i * (bw + gapx)
        rrect(d, (x, by, x + bw, by + bh), 14, fill=WHITE, outline=col, w=3)
        rrect(d, (x, by, x + bw, by + 40), 14, fill=col, outline=col, w=3)
        d.rectangle((x + 1, by + 24, x + bw - 1, by + 41), fill=col)
        ctext(d, (x, by, x + bw, by + 40), tag, F(23, True), WHITE)
        ctext(d, (x + 10, by + 50, x + bw - 10, by + 122), name, F(24), INK, lh=34)
        dashed(d, (x + 24, by + 128), (x + bw - 24, by + 128), "#E0E4E9", 2, 6, 6)
        ctext(d, (x + 10, by + 134, x + bw - 10, by + 180), vl, F(20), SUB, lh=27)
        if i < n - 1:
            ax = x + bw + 4
            arrow(d, (ax, by + bh / 2), (ax + gapx - 6, by + bh / 2), RAIL, 4, 14)

    # 存储层
    sy = 392
    rrect(d, (bx, sy, W - bx, sy + 126), 14, fill=GRAY_BG, outline=BORDER, w=2)
    ltext(d, bx + 30, sy + 32, "本地存储（全部不出本机）", F(23, True), PRIMARY)
    ltext(d, bx + 30, sy + 70,
          "· SQLite（WAL）：sample / analysis / block / goal / intervention / correction", F(20), SUB)
    ltext(d, bx + 30, sy + 100,
          "· 截图目录：JPEG 长边 1280，按天分目录，默认保留 7 天　· 日报：reports/YYYY-MM-DD.html",
          F(20), SUB)

    for i in (0, 1, 2):
        x = bx + i * (bw + gapx) + bw / 2
        dashed(d, (x, by + bh + 4), (x, sy - 6), "#9AA5B1", 3, 12, 9)
        head(d, (x, sy - 2), (0, 1), "#9AA5B1", 12)

    ltext(d, bx, H - 40, "每一级都可追溯：点开日报中任一时间块，可回到对应的截图与分析原文。",
          F(20), SUB)
    im.save(os.path.join(OUT, "fig4_data.png"))


# ----------------------------------------------------------------------------
# 图 5：日报页面结构示意
# ----------------------------------------------------------------------------
DEEP = "#1F4E79"
SHALLOW = "#4A7EBB"
LEARN = "#2E7D8F"
ENT = "#C55A11"
AIMLESS = "#E3A76B"
LIFE = "#9AA5B1"
IDLE = "#E8EBEF"


def fig5():
    W, H = 1500, 860
    im = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(im)
    rrect(d, (24, 16, W - 24, H - 16), 18, fill=WHITE, outline="#DCE2E9", w=2)

    ltext(d, 70, 58, "11 月 5 日　星期三", F(23), SUB)
    ltext(d, W - 70, 58, "比昨天 ↑", F(21), GREEN, anchor="rm")
    ltext(d, 70, 104, "今天专注 2 小时 40 分，被切了 37 次。", F(33, True), INK)
    d.line([(70, 160), (W - 70, 160)], fill="#E6EBF0", width=2)

    kpis = [("2:40", "专注时长", DEEP), ("1:55", "消耗时长", ENT),
            ("37 次", "任务切换", INK), ("61%", "有效比", GREEN)]
    for i, (val, lab, col) in enumerate(kpis):
        x = 70 + i * 345
        ltext(d, x, 196, val, F(34, True), col)
        ltext(d, x, 248, lab, F(18), SUB)

    # 时间轴
    x0, x1, ty0, ty1 = 74, W - 74, 322, 420
    span = x1 - x0

    def px(h):
        return x0 + (h - 8) / 14 * span

    for k in range(0, 15, 2):
        if k % 4 == 0:
            d.rectangle((px(8 + k), ty0, px(10 + k), ty1), fill="#F7F9FB")
    blocks = [
        (8.6, 9.0, LIFE, ""),
        (9.0, 10.33, DEEP, "深度工作"),
        (10.33, 10.83, SHALLOW, "沟通"),
        (10.83, 11.5, DEEP, "深度工作"),
        (11.5, 12.17, LEARN, "学习"),
        (12.17, 13.17, LIFE, "生活"),
        (13.17, 13.67, SHALLOW, "沟通"),
        (13.67, 14.0, LEARN, ""),
        (14.0, 15.0, AIMLESS, "无目的浏览"),
        (15.0, 15.5, SHALLOW, "沟通"),
        (15.5, 16.17, DEEP, "深度工作"),
        (16.17, 17.0, LEARN, "学习"),
        (17.0, 18.17, LIFE, "生活"),
        (18.17, 19.08, ENT, "娱乐"),
        (19.08, 20.5, LEARN, "学习"),
        (20.5, 21.67, SHALLOW, "沟通"),
        (21.67, 22.0, IDLE, ""),
    ]
    for s, e, col, lab in blocks:
        a, b = px(s) + 1.5, px(e) - 1.5
        rrect(d, (a, ty0, b, ty1), 5, fill=col, outline=col)
        if lab and (b - a) > 74:
            ctext(d, (a, ty0, b, ty1), lab, F(15), WHITE)

    d.line([(x0, ty1 + 4), (x1, ty1 + 4)], fill="#DCE2E9", width=2)
    for h in range(8, 23, 2):
        d.line([(px(h), ty1 + 4), (px(h), ty1 + 10)], fill="#DCE2E9", width=2)
        ltext(d, px(h), ty1 + 14, f"{h:02d}", F(16), "#7A8699", anchor="ma")

    legend = [("深度工作", DEEP), ("沟通", SHALLOW), ("学习", LEARN),
              ("娱乐", ENT), ("无目的浏览", AIMLESS), ("生活", LIFE)]
    lx = 74
    for lab, col in legend:
        rrect(d, (lx, 478, lx + 15, 493), 3, fill=col, outline=col)
        ltext(d, lx + 23, 485, lab, F(17), SUB)
        lx += 30 + len(lab) * 19

    d.line([(70, 520), (W - 70, 520)], fill="#E6EBF0", width=2)
    ltext(d, 70, 548, "三个发现", F(23, True), PRIMARY)
    items = [
        "① 10:37 开始刷视频，持续 23 分钟——这是今天最长的一次中断。",
        "② 下午的切换次数是上午的 2.3 倍，注意力明显在变碎。",
        "③ 15:00 之后没有再进入过深度工作。",
    ]
    for i, it in enumerate(items):
        ltext(d, 74, 596 + i * 38, it, F(20), INK)

    rrect(d, (70, 720, W - 70, 796), 12, fill="#F1F6FB",
          outline="#DCE6F1", w=2)
    ltext(d, 96, 758, "明天试一件事：把手机放到 30 分钟够不着的地方。", F(21), PRIMARY)

    im.save(os.path.join(OUT, "fig5_report.png"))


if __name__ == "__main__":
    fig1(); fig2(); fig3(); fig4(); fig5()
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f, Image.open(p).size)
