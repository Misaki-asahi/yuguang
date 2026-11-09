# -*- coding: utf-8 -*-
"""桌宠动作包：manifest 解析 → 图集缓存 → 逐帧播放。

分层：
    anim/manifest.py   读 manifest.json（画布、状态、事件映射）
    anim/assets.py     懒加载 WebP 图集、切片成 QPixmap、LRU 缓存
    anim/player.py     按每状态 fps 的 QTimer 播放，循环/一次性两种

这一层只关心「怎么播」，不关心窗口、鼠标、余光业务；那些在 ui/pet.py 和
后续的 behavior/motion 层里。
"""
