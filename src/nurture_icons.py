"""UI 矢量图标库 —— `QPainter` 矢量绘制 + 三级降级链 + 缓存。

> 这里原本只服务养成系统（悬停菜单 / 养成面板），2026-09-10 起左键功能面板、
> 右键系统面板、设置窗口也统一用这套视觉，于是它事实上成了**全局 UI 的图标库**。
> 模块名保留原样（改名会牵动 4 个既有组件与 2 份文档，收益只是好看一点）。

对应规范：`docs/nurture/03-设计规范.md` 第 4 节。

**三级来源**（保证"先能跑，后期可无痛替换"）：

| 级别 | 来源 | 何时命中 |
|------|------|----------|
| 1 | `assets/nurture/icons/{icon_key}.png` | 用户/后期美术自备的 PNG（含 alpha），同名自动覆盖内置矢量 |
| 2 | 本模块 `QPainter` 矢量绘制 | 默认路径，27 个图标各画一版简笔图形 |
| 3 | emoji / 首字 | 连内置画法都没有的未知 key（用户新加了食物但没配套图标） |

**画法约定**（照规范执行，换图标时也要守住）：

* 在 **20×20 逻辑网格**内作画，统一按 `size / 20` 缩放 → 任意尺寸线条比例一致
* 线宽 **2px**、`RoundCap` + `RoundJoin`、描边一律暖棕 `#8D6E63`
* **平涂填充，不画渐变、不画高光**（渐变会把界面拉回"科技感"）
* 图形控制在 `[1.5, 18.5]` 内，避免 2px 描边被画布裁掉

**色板不在这里**：真正的定义在 `src/ui_theme.py`，本模块只把老名字转出去。
`tests/test_nurture_icons.py` 会扫描源码，禁止冷蓝色值出现在这套 UI 里。

自检预览：`python -m src.nurture_icons [输出路径.png]`
"""

from __future__ import annotations

import math
import os
import sys
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

# ────────────────────────────── 色板 ──────────────────────────────
# **真正的定义在 `src/ui_theme.py`**（2026-09-10 起左键功能面板 / 右键系统面板 / 设置窗口
# 也统一成这套视觉，色板必须只有一份）。这里把老名字转出去，
# 是为了 `hover_menu` / `nurture_panel` / `speech_bubble` 三个既有组件一行都不用改。

from src.ui_theme import (  # noqa: E402  （色板转出，见上）
    CARD,
    CREAM,
    CREAM_DEEP,
    FORBIDDEN_COLORS,
    GOLD,
    GREEN,
    HEART_PINK,
    NAVY,
    OUTLINE,
    OUTLINE_LIGHT,
    PINK,
    PINK_DEEP,
    PINK_LIGHT,
    RED,
    TEXT,
    TEXT_DIM,
)
from src.ui_theme import SHADOW_RGB  # noqa: E402,F401  （部分组件会顺手用到）

#: 设计网格边长（所有画法都按这个坐标系写，再整体缩放）
GRID = 20.0

#: 线宽（设计网格单位）
STROKE = 2.0

#: 默认图标尺寸（逻辑像素）。规范 4.2：20×20，在 44px 圆按钮内居中
DEFAULT_SIZE = 20


# ────────────────────────── 基础绘制工具 ──────────────────────────


def _c(color: str) -> QColor:
    return QColor(color)


def _pen(color: str = OUTLINE, width: float = STROKE) -> QPen:
    """统一的圆头圆角描边笔。"""
    pen = QPen(_c(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCosmetic(False)
    return pen


def _begin(painter: QPainter) -> None:
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(Qt.NoBrush)


def _shape(painter: QPainter, path: QPainterPath, fill: str | None = CREAM,
           stroke: str | None = OUTLINE, width: float = STROKE) -> None:
    """一次画完填充 + 描边。`fill`/`stroke` 传 `None` 表示跳过该步。"""
    if fill:
        painter.setPen(Qt.NoPen)
        painter.setBrush(_c(fill))
        painter.drawPath(path)
    if stroke:
        painter.setPen(_pen(stroke, width))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


def _ellipse_rect(cx: float, cy: float, rx: float, ry: float) -> QRectF:
    return QRectF(cx - rx, cy - ry, rx * 2, ry * 2)


def _ellipse(cx: float, cy: float, rx: float, ry: float, fill: str | None = CREAM,
             stroke: str | None = OUTLINE, width: float = STROKE) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(_ellipse_rect(cx, cy, rx, ry))
    return path


def _line(painter: QPainter, x1: float, y1: float, x2: float, y2: float,
          color: str = OUTLINE, width: float = STROKE) -> None:
    painter.setPen(_pen(color, width))
    painter.setBrush(Qt.NoBrush)
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(points: list[tuple[float, float]], close: bool = True) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*points[0])
    for x, y in points[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    return path


def _rounded(x1: float, y1: float, x2: float, y2: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x1, y1, x2 - x1, y2 - y1), r, r)
    return path


def _heart_path(cx: float, cy: float, w: float, h: float) -> QPainterPath:
    """标准心形：两段三次曲线在底部汇成尖角。"""
    path = QPainterPath()
    top = cy - h / 2
    bottom = cy + h / 2
    left = cx - w / 2
    right = cx + w / 2
    path.moveTo(cx, bottom)
    path.cubicTo(cx - w * 0.62, cy + h * 0.08, left, cy - h * 0.30, cx - w * 0.25, top)
    path.cubicTo(cx - w * 0.06, top - h * 0.06, cx, top + h * 0.12, cx, top + h * 0.16)
    path.cubicTo(cx, top + h * 0.12, cx + w * 0.06, top - h * 0.06, cx + w * 0.25, top)
    path.cubicTo(right, cy - h * 0.30, cx + w * 0.62, cy + h * 0.08, cx, bottom)
    path.closeSubpath()
    return path


def _gear_path(cx: float, cy: float, r_out: float, r_in: float, teeth: int = 8,
               tooth_ratio: float = 0.55) -> QPainterPath:
    """齿轮外轮廓：在内外半径之间交替生成齿与槽。

    `tooth_ratio` 是单齿占一个齿距的比例（0.55 → 齿略宽于槽，看着更敦实）。
    每个齿的前后各插一个中间点，让齿顶与齿根之间形成梯形而不是直上直下。
    """
    path = QPainterPath()
    step = 2 * math.pi / teeth
    half = step / 2 * tooth_ratio
    for i in range(teeth):
        centre = i * step
        pts = (
            (centre - half * 0.72, r_out),
            (centre + half * 0.72, r_out),
            (centre + half, r_in),
            (centre + step - half, r_in),
        )
        for j, (angle, radius) in enumerate(pts):
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            if i == 0 and j == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    return path


# ────────────────────────── 功能图标（9 个）──────────────────────────
# 供悬停菜单使用


def _draw_checkin(p: QPainter) -> None:
    """签到：圆角日历页 + 顶部两个小环 + 右下圆形图章（含勾）。"""
    _shape(p, _rounded(2.6, 4.4, 17.4, 18.2, 2.6), CREAM)
    # 顶部粉色页眉
    head = QPainterPath()
    head.addRoundedRect(QRectF(2.6, 4.4, 14.8, 4.2), 2.6, 2.6)
    clip = QPainterPath()
    clip.addRect(QRectF(2.6, 6.4, 14.8, 2.2))
    _shape(p, head.intersected(clip), PINK, None)
    _line(p, 2.6, 8.6, 17.4, 8.6, OUTLINE, 1.6)
    # 两个挂环
    _line(p, 6.6, 2.4, 6.6, 5.4, OUTLINE, 1.8)
    _line(p, 13.4, 2.4, 13.4, 5.4, OUTLINE, 1.8)
    # 右下图章
    _shape(p, _ellipse(13.6, 14.4, 3.6, 3.6), RED)
    p.setPen(_pen(CARD, 1.8))
    p.drawPolyline(QPolygonF([QPointF(12.1, 14.4), QPointF(13.2, 15.6), QPointF(15.2, 13.2)]))


def _draw_feed(p: QPainter) -> None:
    """喂食：饭碗（米饭 + 粉色碗身 + 底座）+ 一双筷子。

    **对规范 4.2 的一处修正**：规范原写「三角饭团 + 底部小方形海苔」，但那与食物图标
    `onigiri` 完全同形，20px 下两者无法区分（实测三张预览图确认）。改为语义更准、
    外形也更独特的「碗筷」，同时把三样东西在卡片上的可辨识度拉开。
    """
    # 米饭
    rice = QPainterPath()
    rice.moveTo(5.6, 11.4)
    rice.cubicTo(5.6, 7.4, 14.4, 7.4, 14.4, 11.4)
    rice.closeSubpath()
    _shape(p, rice, CARD)
    # 碗身
    bowl = QPainterPath()
    bowl.moveTo(2.6, 11.4)
    bowl.cubicTo(2.6, 18.6, 17.4, 18.6, 17.4, 11.4)
    bowl.closeSubpath()
    _shape(p, bowl, PINK)
    # 底座
    _line(p, 8.0, 17.8, 12.0, 17.8, OUTLINE, 1.8)
    # 筷子（斜插在碗右后方）
    _line(p, 11.0, 3.0, 15.4, 9.6, OUTLINE, 1.8)
    _line(p, 13.8, 2.4, 16.8, 8.6, OUTLINE, 1.8)


def _draw_gift(p: QPainter) -> None:
    """送礼：方盒 + 十字丝带 + 顶部双环蝴蝶结。"""
    _shape(p, _rounded(2.8, 8.4, 17.2, 18.2, 2.0), PINK)
    _shape(p, _rounded(2.2, 6.6, 17.8, 10.4, 1.4), CREAM)
    box = _rounded(8.6, 6.6, 11.4, 18.2, 0.8)
    _shape(p, box, RED, OUTLINE, 1.4)
    # 双环蝴蝶结
    _shape(p, _ellipse(7.4, 4.6, 2.9, 2.1), PINK)
    _shape(p, _ellipse(12.6, 4.6, 2.9, 2.1), PINK)
    _shape(p, _ellipse(10.0, 5.6, 1.2, 1.2), RED)


def _draw_heart(p: QPainter) -> None:
    """好感度：心形。"""
    _shape(p, _heart_path(10.0, 10.4, 16.0, 15.0), HEART_PINK)


def _draw_chat(p: QPainter) -> None:
    """陪她聊聊：圆角对话泡 + 底部小三角 + 内部三个圆点。"""
    bubble = _rounded(1.8, 3.2, 18.2, 14.0, 3.6)
    tail = _poly([(6.0, 13.6), (10.4, 13.6), (6.6, 17.6)])
    _shape(p, bubble.united(tail), CREAM)
    for x in (6.4, 10.0, 13.6):
        _shape(p, _ellipse(x, 8.6, 1.05, 1.05), OUTLINE, None)


def _draw_headpat(p: QPainter) -> None:
    """摸头：一手掌（掌心 + 四指合并成一个轮廓）+ 顶部三条"擦擦"弧线。

    四指与掌心**合并成单一路径再描边**，否则手指与掌心的接缝处会留下一圈内线。
    掌心用浅粉而不是奶白：它要贴在悬停菜单的 `#FFF1EC` 按钮底上，纯奶白填充几乎看不见
    （实测预览图确认），浅粉既保住柔和感又有足够对比。
    """
    hand = _ellipse(10.0, 14.4, 6.4, 4.0)
    for i, x in enumerate((5.9, 8.6, 11.4, 14.1)):
        top = 7.4 - (1.0 if i in (1, 2) else 0.0)
        hand = hand.united(_rounded(x - 1.35, top, x + 1.35, 14.0, 1.35))
    _shape(p, hand, PINK_LIGHT)
    # 顶部动效弧线（用粉深色，浅棕在奶白底上看不清）
    for x1, x2, dy in ((6.2, 8.2, 0.4), (9.0, 11.0, -0.6), (11.8, 13.8, 0.4)):
        _line(p, x1, 3.4 + dy, x2, 2.2 + dy, PINK_DEEP, 1.7)


def _draw_settings(p: QPainter) -> None:
    """设置：八齿齿轮 + 中心圆。"""
    _shape(p, _gear_path(10.0, 10.0, 8.2, 6.0), CREAM, OUTLINE, 1.8)
    _shape(p, _ellipse(10.0, 10.0, 2.5, 2.5), CREAM, OUTLINE, 1.6)


def _draw_close(p: QPainter) -> None:
    """关闭：两条圆头交叉线。"""
    _line(p, 5.4, 5.4, 14.6, 14.6, OUTLINE, 2.6)
    _line(p, 14.6, 5.4, 5.4, 14.6, OUTLINE, 2.6)


def _draw_lock(p: QPainter) -> None:
    """未解锁：半圆环锁梁 + 方形锁体 + 中心锁孔。"""
    shackle = QPainterPath()
    shackle.moveTo(6.0, 9.6)
    shackle.lineTo(6.0, 7.4)
    shackle.arcTo(_ellipse_rect(10.0, 7.4, 4.0, 4.0), 180.0, -180.0)
    shackle.lineTo(14.0, 9.6)
    p.setPen(_pen(OUTLINE, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(shackle)
    _shape(p, _rounded(4.6, 9.4, 15.4, 18.0, 2.2), CREAM)
    _shape(p, _ellipse(10.0, 12.6, 1.25, 1.25), OUTLINE, None)
    _line(p, 10.0, 13.6, 10.0, 15.8, OUTLINE, 1.6)


# ────────────── 面板图标（5 个，2026-09-10 全局换肤时新增）──────────────
# 供左键功能面板 / 右键系统面板使用。画法与上面 9 个功能图标完全同口径。


def _draw_clipboard(p: QPainter) -> None:
    """历史粘贴板：写字板 + 顶部夹子 + 两行横线。"""
    _shape(p, _rounded(3.6, 3.4, 16.4, 18.0, 2.4), CREAM)
    # 顶部夹子
    _shape(p, _rounded(7.2, 1.6, 12.8, 4.8, 1.4), PINK)
    # 两行"内容"
    _line(p, 6.6, 9.0, 13.4, 9.0, OUTLINE_LIGHT, 1.6)
    _line(p, 6.6, 12.2, 13.4, 12.2, OUTLINE_LIGHT, 1.6)
    _line(p, 6.6, 15.4, 11.0, 15.4, OUTLINE_LIGHT, 1.6)


def _draw_pin(p: QPainter) -> None:
    """置顶：顶栏 + 向上箭头（"顶到最上层"）。

    **这个图标改了三版**，记一笔免得后人再走一遍：
    1. "圆头 + 竖线" → 20px 下是**气球/棒棒糖**
    2. 经典图钉"帽 + 梯形身 + 针" → 读成**铲子**（帽太宽、针太短）
    3. 定稿"顶栏 + 上箭头"：语义直白，且与「最小化到托盘」的下箭头正好成对，
       两个"层级类"操作在图标上就分得开。
    """
    _shape(p, _rounded(4.4, 2.6, 15.6, 5.2, 1.3), PINK)
    _line(p, 10.0, 17.4, 10.0, 8.8, OUTLINE, 2.0)
    p.setPen(_pen(OUTLINE, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(6.6, 11.6), QPointF(10.0, 8.0), QPointF(13.4, 11.6)]))


def _draw_monitor(p: QPainter) -> None:
    """桌面层级：显示器 + 底座（"放在桌面上"）。"""
    _shape(p, _rounded(2.4, 3.6, 17.6, 14.0, 2.2), CREAM)
    _shape(p, _rounded(4.6, 5.6, 15.4, 12.0, 1.4), PINK, None)
    _line(p, 10.0, 14.0, 10.0, 16.6, OUTLINE, 1.8)
    _line(p, 6.2, 17.4, 13.8, 17.4, OUTLINE, 2.0)


def _draw_tray(p: QPainter) -> None:
    """最小化到托盘：托盘（带内沿）+ 向下箭头。

    内沿那条横线是关键：没有它，"托盘"与"下载框"在 20px 下同形。
    """
    tray = QPainterPath()
    tray.moveTo(2.6, 10.8)
    tray.lineTo(2.6, 16.4)
    tray.lineTo(17.4, 16.4)
    tray.lineTo(17.4, 10.8)
    p.setPen(_pen(OUTLINE, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(tray)
    _line(p, 5.6, 13.0, 14.4, 13.0, OUTLINE_LIGHT, 1.4)
    _line(p, 10.0, 2.4, 10.0, 10.4, OUTLINE, 2.0)
    p.setPen(_pen(OUTLINE, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(6.6, 7.0), QPointF(10.0, 10.6), QPointF(13.4, 7.0)]))


def _draw_power(p: QPainter) -> None:
    """退出：电源符号（缺口圆环 + 竖直短线）。"""
    arc = QPainterPath()
    arc.arcMoveTo(_ellipse_rect(10.0, 11.4, 6.0, 6.0), 105.0)
    arc.arcTo(_ellipse_rect(10.0, 11.4, 6.0, 6.0), 105.0, -390.0)
    p.setPen(_pen(OUTLINE, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(arc)
    _line(p, 10.0, 2.6, 10.0, 9.4, OUTLINE, 2.2)


# ────────────────────────── 食物 / 礼物图标（13 个）──────────────────────────


def _draw_bread(p: QPainter) -> None:
    """奶油面包：半圆面包体 + 中间奶油条 + 两条斜纹。"""
    dome = QPainterPath()
    dome.moveTo(2.4, 15.0)
    dome.cubicTo(2.4, 4.4, 17.6, 4.4, 17.6, 15.0)
    dome.closeSubpath()
    _shape(p, dome, CREAM)
    # 奶油条
    _shape(p, _rounded(4.0, 10.6, 16.0, 13.6, 1.4), PINK, OUTLINE, 1.4)
    _line(p, 6.6, 7.0, 8.2, 9.4, OUTLINE_LIGHT, 1.5)
    _line(p, 11.8, 7.0, 13.4, 9.4, OUTLINE_LIGHT, 1.5)


def _draw_onigiri(p: QPainter) -> None:
    """饭团：圆角三角 + 底部海苔矩形。"""
    _shape(p, _poly([(10.0, 2.6), (17.8, 15.4), (2.2, 15.4)]), CREAM)
    _shape(p, _rounded(6.4, 12.4, 13.6, 18.2, 1.2), NAVY)


def _draw_milk(p: QPainter) -> None:
    """牛奶：纸盒 + 顶部折角 + 藏青标签带（规范禁止冷蓝，故用领巾色）。"""
    body = _rounded(5.0, 6.8, 15.0, 18.2, 1.4)
    roof = _poly([(5.0, 6.8), (10.0, 2.4), (15.0, 6.8)])
    _shape(p, body.united(roof), CREAM)
    _shape(p, _rounded(5.0, 11.0, 15.0, 14.2, 0.8), NAVY, OUTLINE, 1.4)
    _line(p, 10.0, 2.6, 10.0, 6.8, OUTLINE_LIGHT, 1.4)


def _draw_yakisoba(p: QPainter) -> None:
    """炒面面包：长条面包 + 中间波浪面条 + 顶上红姜丝。"""
    _shape(p, _rounded(2.0, 6.6, 18.0, 15.4, 4.4), CREAM)
    wave = QPainterPath()
    wave.moveTo(4.4, 11.0)
    wave.cubicTo(6.6, 8.6, 8.4, 13.4, 10.6, 11.0)
    wave.cubicTo(12.8, 8.6, 14.6, 13.4, 16.4, 11.0)
    p.setPen(_pen(OUTLINE, 1.8))
    p.setBrush(Qt.NoBrush)
    p.drawPath(wave)
    # 红姜丝
    _line(p, 8.6, 6.6, 9.6, 4.8, RED, 1.6)
    _line(p, 11.4, 6.6, 10.4, 4.8, RED, 1.6)


def _draw_shortcake(p: QPainter) -> None:
    """草莓蛋糕：三角蛋糕 + 明显的粉色奶油夹层 + 顶部大草莓。

    奶油层做成**梯形填充**（跟随三角形斜边）而不是两条细线——细线在 20px 下看不见，
    整个图标会退化成"一个白三角"，和 `onigiri` 撞形。
    """
    _shape(p, _poly([(10.0, 5.6), (17.8, 17.6), (2.2, 17.6)]), CREAM)
    cream = _poly([(6.0, 11.8), (14.0, 11.8), (15.2, 14.0), (4.8, 14.0)])
    _shape(p, cream, PINK, OUTLINE, 1.4)
    # 顶部草莓（放大到 20px 下仍认得出）
    _shape(p, _ellipse(10.0, 3.6, 2.5, 2.5), RED)
    _line(p, 10.0, 0.9, 10.0, 2.0, GREEN, 1.6)


def _draw_icecream(p: QPainter) -> None:
    """冰淇淋：甜筒网格三角 + 三个球。"""
    _shape(p, _poly([(5.6, 12.2), (14.4, 12.2), (10.0, 18.6)]), CREAM)
    _line(p, 7.4, 13.8, 11.6, 16.8, OUTLINE_LIGHT, 1.3)
    _line(p, 12.6, 13.8, 8.4, 16.8, OUTLINE_LIGHT, 1.3)
    _shape(p, _ellipse(7.0, 9.8, 2.9, 2.9), PINK)
    _shape(p, _ellipse(13.0, 9.8, 2.9, 2.9), PINK)
    _shape(p, _ellipse(10.0, 6.6, 3.2, 3.2), PINK)


def _draw_candyapple(p: QPainter) -> None:
    """苹果糖：正圆 + 顶部木签 + 底部糖层色带。"""
    _line(p, 10.0, 7.0, 10.0, 2.2, OUTLINE, 2.0)
    _shape(p, _ellipse(10.0, 12.2, 5.6, 5.6), PINK_DEEP)
    sugar = QPainterPath()
    sugar.moveTo(4.6, 11.4)
    sugar.cubicTo(7.2, 15.6, 12.8, 15.6, 15.4, 11.4)
    p.setPen(_pen(OUTLINE, 1.5))
    p.setBrush(Qt.NoBrush)
    p.drawPath(sugar)


def _draw_chocolate(p: QPainter) -> None:
    """巧克力：圆角矩形 + 九宫格凹槽 + 右上被咬的缺口。"""
    bar = _rounded(2.4, 4.4, 17.6, 17.8, 2.4)
    bite = QPainterPath()
    bite.addEllipse(_ellipse_rect(16.4, 3.2, 3.6, 3.6))
    _shape(p, bar.subtracted(bite), OUTLINE, OUTLINE, 1.6)
    for x in (7.4, 12.6):
        _line(p, x, 6.4, x, 15.8, CREAM, 1.3)
    for y in (8.8, 13.4):
        _line(p, 4.4, y, 15.6, y, CREAM, 1.3)


def _draw_birthday(p: QPainter) -> None:
    """生日蛋糕：圆柱 + 三根蜡烛 + 烛焰。"""
    _shape(p, _rounded(2.6, 10.4, 17.4, 18.2, 2.0), CREAM)
    _line(p, 3.2, 12.6, 16.8, 12.6, OUTLINE_LIGHT, 1.4)
    for x in (6.6, 10.0, 13.4):
        _line(p, x, 10.4, x, 6.2, PINK, 1.8)
        _shape(p, _ellipse(x, 4.2, 1.15, 1.7), PINK_DEEP, OUTLINE, 1.2)


def _draw_easterbasket(p: QPainter) -> None:
    """彩蛋篮：三颗彩蛋 + 梯形篮子 + 编织斜线。"""
    _shape(p, _ellipse(6.6, 8.0, 2.5, 3.2), PINK)
    _shape(p, _ellipse(13.4, 8.0, 2.5, 3.2), GREEN)
    _shape(p, _ellipse(10.0, 6.6, 2.6, 3.4), GOLD)
    _shape(p, _poly([(3.0, 10.6), (17.0, 10.6), (14.4, 18.2), (5.6, 18.2)]), CREAM)
    _line(p, 3.6, 13.4, 16.4, 13.4, OUTLINE_LIGHT, 1.3)
    _line(p, 4.6, 16.0, 15.4, 16.0, OUTLINE_LIGHT, 1.3)
    for x in (7.4, 10.0, 12.6):
        _line(p, x, 11.0, x - 0.8, 17.8, OUTLINE_LIGHT, 1.2)


def _draw_redpacket(p: QPainter) -> None:
    """压岁钱：竖长红包 + 金色封口 + 中心金色圆。"""
    _shape(p, _rounded(4.8, 2.4, 15.2, 18.2, 2.2), RED)
    _shape(p, _rounded(4.8, 2.4, 15.2, 8.0, 2.2), GOLD, OUTLINE, 1.5)
    _shape(p, _ellipse(10.0, 12.4, 2.6, 2.6), GOLD, OUTLINE, 1.5)


def _draw_rose(p: QPainter) -> None:
    """玫瑰花：螺旋花心 + 两片叶 + 茎。"""
    _line(p, 10.0, 11.0, 10.0, 18.4, GREEN, 2.0)
    _shape(p, _ellipse(6.0, 14.0, 3.2, 1.9), GREEN)
    _shape(p, _ellipse(14.0, 16.2, 3.2, 1.9), GREEN)
    _shape(p, _ellipse(10.0, 6.4, 5.2, 5.2), PINK)
    spiral = QPainterPath()
    spiral.moveTo(7.8, 5.6)
    spiral.cubicTo(10.6, 3.4, 14.0, 6.2, 11.8, 8.6)
    spiral.cubicTo(10.2, 10.2, 7.6, 9.0, 8.6, 7.2)
    p.setPen(_pen(OUTLINE, 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawPath(spiral)


def _draw_festivalbag(p: QPainter) -> None:
    """夏日祭礼包：布袋 + 束口 + 顶上露出的荧光棒。"""
    _line(p, 6.6, 9.2, 5.2, 2.6, PINK_DEEP, 2.4)
    _line(p, 13.4, 9.2, 14.8, 2.6, GREEN, 2.4)
    _shape(p, _rounded(3.4, 7.6, 16.6, 18.2, 3.4), PINK)
    _line(p, 4.2, 9.6, 15.8, 9.6, OUTLINE, 1.8)
    _shape(p, _ellipse(7.0, 9.6, 1.2, 1.2), OUTLINE, None)
    _shape(p, _ellipse(13.0, 9.6, 1.2, 1.2), OUTLINE, None)


# ────────────────────────── 图标注册表 ──────────────────────────

#: `icon_key` → 画法。顺序即预览图的排列顺序
DRAWERS: dict[str, Callable[[QPainter], None]] = {
    # 功能（悬停菜单）
    "checkin": _draw_checkin,
    "feed": _draw_feed,
    "gift": _draw_gift,
    "heart": _draw_heart,
    "chat": _draw_chat,
    "headpat": _draw_headpat,
    "settings": _draw_settings,
    "close": _draw_close,
    "lock": _draw_lock,
    # 面板（左键功能面板 / 右键系统面板）
    "clipboard": _draw_clipboard,
    "pin": _draw_pin,
    "monitor": _draw_monitor,
    "tray": _draw_tray,
    "power": _draw_power,
    # 食物 / 礼物（卡片）
    "bread": _draw_bread,
    "onigiri": _draw_onigiri,
    "milk": _draw_milk,
    "yakisoba": _draw_yakisoba,
    "shortcake": _draw_shortcake,
    "icecream": _draw_icecream,
    "candyapple": _draw_candyapple,
    "chocolate": _draw_chocolate,
    "birthday": _draw_birthday,
    "easterbasket": _draw_easterbasket,
    "redpacket": _draw_redpacket,
    "rose": _draw_rose,
    "festivalbag": _draw_festivalbag,
}

#: 第 3 级兜底用的 emoji（`Segoe UI Emoji` 渲染）
EMOJI: dict[str, str] = {
    "checkin": "📅", "feed": "🍙", "gift": "🎁", "heart": "💗", "chat": "💬",
    "headpat": "🤚", "settings": "⚙", "close": "✕", "lock": "🔒",
    "clipboard": "📋", "pin": "📌", "monitor": "🖥", "tray": "🗕", "power": "⏻",
    "bread": "🍞", "onigiri": "🍙", "milk": "🥛", "yakisoba": "🍜",
    "shortcake": "🍰", "icecream": "🍦", "candyapple": "🍎", "chocolate": "🍫",
    "birthday": "🎂", "easterbasket": "🧺", "redpacket": "🧧", "rose": "🌹",
    "festivalbag": "🛍",
}

#: 未知 key 时按名称首字兜底（用于用户新加的食物）
_FALLBACK_CHAR = "?"

_CACHE: dict[tuple[str, int, int], QPixmap] = {}
_USER_DIR_LOGGED: set[str] = set()


def project_dir() -> str:
    """项目根目录。与 `config.py` / `nurture_store.py` 同口径（各自独立以便单独 import）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_icons_dir() -> str:
    """用户自备图标的目录：`assets/nurture/icons/`。"""
    return os.path.join(project_dir(), "assets", "nurture", "icons")


def known_keys() -> list[str]:
    """全部内置图标键（预览与自检用）。"""
    return list(DRAWERS.keys())


def has_builtin(key: str) -> bool:
    """该 key 是否有内置矢量画法。"""
    return str(key) in DRAWERS


# ────────────────────────── 渲染 ──────────────────────────


def clear_cache() -> None:
    """清空图标缓存（改过用户 PNG 或改过画法后调用）。"""
    _CACHE.clear()


def pixmap(key: str, size: int = DEFAULT_SIZE, dpr: float = 1.0,
           icons_dir: str | None = None, fallback_text: str = "") -> QPixmap:
    """取图标位图。**永不抛异常、永不返回空图** —— 三级降级最后一定画得出东西。

    :param key: `items.json` 的 `icon_key` 或功能图标名
    :param size: 逻辑像素尺寸（规范 4.2：20）
    :param dpr: `devicePixelRatio`（高 DPI 下按物理像素渲染，避免糊）
    :param icons_dir: 用户图标目录，缺省 `assets/nurture/icons/`
    :param fallback_text: 第 3 级兜底用的文字（一般传食物名，取首字）
    """
    try:
        size = max(4, int(size))
    except (TypeError, ValueError):
        size = DEFAULT_SIZE          # 配置里写了脏值也不能让绘制路径抛异常
    try:
        ratio = max(1.0, float(dpr))
    except (TypeError, ValueError):
        ratio = 1.0
    key = str(key or "")
    directory = icons_dir or default_icons_dir()
    # 缓存键必须带上 icons_dir：否则用户在 assets/nurture/icons/ 放进自备 PNG 之后，
    # 会一直命中旧的内置矢量缓存，表现为"放了图标没生效"。
    cache_key = (key, size, int(ratio * 100), directory)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    px = int(round(size * ratio))
    canvas = QPixmap(px, px)
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.transparent)

    painter = QPainter(canvas)
    try:
        _begin(painter)
        painter.scale(px / GRID, px / GRID)
        if not _paint(painter, key, icons_dir, fallback_text):
            # 连兜底文字都没得画 —— 至少给个空心圆，不要留空白
            _shape(painter, _ellipse(10.0, 10.0, 6.6, 6.6), CREAM)
    finally:
        painter.end()

    _CACHE[cache_key] = canvas
    return canvas


def _paint(painter: QPainter, key: str, icons_dir: str | None,
           fallback_text: str) -> bool:
    """依次尝试三级来源，命中即返回 `True`。"""
    if _paint_user(painter, key, icons_dir):
        return True
    drawer = DRAWERS.get(key)
    if drawer is not None:
        try:
            drawer(painter)
            return True
        except Exception:
            # 画法出错不该让整个界面挂掉 —— 退到第 3 级
            pass
    return _paint_fallback(painter, key, fallback_text)


def _paint_user(painter: QPainter, key: str, icons_dir: str | None) -> bool:
    """第 1 级：用户自备 PNG。"""
    if not key:
        return False
    path = os.path.join(icons_dir or default_icons_dir(), f"{key}.png")
    if not os.path.isfile(path):
        return False
    source = QPixmap(path)
    if source.isNull():
        return False
    painter.drawPixmap(QRectF(0, 0, GRID, GRID), source, QRectF(source.rect()))
    return True


def _paint_fallback(painter: QPainter, key: str, fallback_text: str) -> bool:
    """第 3 级：emoji → 首字 → 空心圆。"""
    text = EMOJI.get(key, "")
    if not text:
        for candidate in (fallback_text, key):
            candidate = str(candidate or "").strip()
            if candidate:
                text = candidate[0]
                break
    if not text:
        return False

    font = QFont("Segoe UI Emoji")
    font.setPixelSize(15)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(_pen(OUTLINE, 1.0))
    painter.setBrush(Qt.NoBrush)
    painter.drawText(QRectF(0, 0, GRID, GRID), Qt.AlignCenter, text)
    return True


def pixmap_for_item(item, size: int = DEFAULT_SIZE, dpr: float = 1.0,
                    icons_dir: str | None = None) -> QPixmap:
    """按 `items.json` 的一个条目取图标（自动带上"名称首字"作兜底）。"""
    if not isinstance(item, dict):
        return pixmap("", size, dpr, icons_dir)
    return pixmap(item.get("icon_key", ""), size, dpr, icons_dir,
                  fallback_text=item.get("name", ""))


# ────────────────────────── 自检预览 ──────────────────────────


def render_sheet(keys: list[str] | None = None, icon_size: int = 44, cols: int = 8,
                 icons_dir: str | None = None, labels: bool = True) -> QPixmap:
    """把全部图标渲染成一张对照图（人工验收用，见 04 文档阶段 B 验证）。

    `icon_size` 就是图标实际渲染尺寸：验收时分别用 44 和 20 各出一张，
    确认"大图好看"之外还"小尺寸认得出"。
    """
    keys = keys or known_keys()
    rows = (len(keys) + cols - 1) // cols
    pad = 10
    cell = icon_size + 12
    label_h = 15 if labels else 0
    width = cols * (cell + pad) + pad
    height = rows * (cell + label_h + pad) + pad
    sheet = QPixmap(width, height)
    sheet.fill(QColor(CREAM_DEEP))

    painter = QPainter(sheet)
    try:
        _begin(painter)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(10)
        painter.setFont(font)
        for index, key in enumerate(keys):
            row, col = divmod(index, cols)
            x = pad + col * (cell + pad)
            y = pad + row * (cell + label_h + pad)
            card = QPainterPath()
            card.addRoundedRect(QRectF(x, y, cell, cell + label_h), 8, 8)
            _shape(painter, card, CARD, OUTLINE_LIGHT, 1.2)

            icon = pixmap(key, icon_size, 1.0, icons_dir)
            painter.drawPixmap(
                QRectF(x + (cell - icon_size) / 2, y + 6, icon_size, icon_size),
                icon, QRectF(icon.rect()))
            if labels:
                painter.setPen(QPen(QColor(TEXT)))
                painter.drawText(QRectF(x, y + cell - 2, cell, label_h),
                                 Qt.AlignHCenter | Qt.AlignTop, key)
    finally:
        painter.end()
    return sheet


def _main(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841
    out = argv[1] if len(argv) > 1 else "_icons_preview.png"
    keys = known_keys()

    big = render_sheet(keys, icon_size=44, cols=8, labels=True)
    ok = big.save(out)
    print(f"icons : {len(keys)}  ->  {out}  ({'saved' if ok else 'SAVE FAILED'})  {big.width()}x{big.height()}")

    # 20px 真实尺寸，无标签 —— 检查"小尺寸下认不认得出"
    small = render_sheet(keys, icon_size=20, cols=len(keys), labels=False)
    small_out = out.replace(".png", "_20px.png")
    small.save(small_out)
    print(f"20px  : {small.width()}x{small.height()}  ->  {small_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
