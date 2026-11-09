# 桌宠素材说明（focuspet/assets/pet/）

本目录有两类素材，**许可不同，务必分清**：

| 路径 | 内容 | 许可 |
|---|---|---|
| `juyuan/pose.png` | 项目角色「菊鸳」的静态立绘（项目作者绘制） | 项目自有，随仓库 MIT 发布 |
| `juyuan-pack/` | 菊鸳逐帧动画动作包（10 个动作） | **第三方素材衍生：禁止商用 + 须署名，不适用 MIT**，详见 `juyuan-pack/ASSETS-LICENSE.md` |

## 加载优先级

1. `juyuan-pack/manifest.json` 存在 → 逐帧动画（由 `focuspet/anim/` 播放）；
2. 否则用 `juyuan/pose.png` 静态立绘；
3. 再没有 → `focuspet/ui/pet.py` 里 QPainter 手画的占位小熊。

所以把这两个目录删掉，程序也能正常启动（就是变回手画小熊）。

## 新增/更换素材的规矩

1. **必须原创或已获授权**。他人素材即便写着"禁止商用"，也和本仓库的 MIT 再分发不兼容；
   第三方素材一律单独写许可文件（参考 `juyuan-pack/ASSETS-LICENSE.md`），不得混进代码的 MIT。
2. 角色统一 **脚底中心锚点**，跨动作的画布尺寸/缩放必须一致，否则切换动作会跳位。
3. 体积：单动作图集 ≤ 1 MB、整套 ≤ 10 MB；视频源与中间帧不入库。
4. 程序按 `ui.pet_scale` 与屏幕 DPI 预缩放（见 `focuspet/anim/assets.py`），不要在这里塞巨大原图。
