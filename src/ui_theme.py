"""全局 UI 主题 —— 暖粉奶白手绘风的**唯一色板与笔触工具箱**。

这套视觉原本只属于养成系统（规范见 `docs/nurture/03-设计规范.md`），色板寄居在
`nurture_icons.py` 里。2026-09-10 用户要求把**左键功能面板 / 右键系统面板 / 设置窗口**
也统一成同一套视觉，于是把它提出来独立成本模块：

- **色板只此一份**。`nurture_icons.py` 仍按老名字把颜色转出去（`CREAM`/`OUTLINE`/…），
  所以四个既有组件（`hover_menu` / `nurture_panel` / `speech_bubble` / `nurture_icons`）
  **一行都不用改**；新面板也从这里取色，两边永远同色。
- **笔触只此一份**。`pen()` / `rounded_path()` / `paint_paper()` / `paint_card()` /
  `paint_row()` / `paint_circle()` 是新旧面板共用的画法。想让新面板"看起来和养成面板是一套"，
  唯一的可靠做法是**共用这些函数**，而不是照着把数字抄一遍 —— 抄的那份迟早会漂。

手绘感的四个手法（规范第 3 节）在这里落地：

1. 2px 暖棕描边 + `RoundCap`/`RoundJoin`
2. 大圆角（面板 20 / 卡片 14 / 行 12 / 正圆）
3. **不对称圆角** —— `paper_radii()` 让四角半径差 1~2px，模仿手绘的不精确（差值**不许超过 2px**，
   否则会像 bug）
4. **描边略微外扩**：描边路径比填充路径大 0.5px，制造"着色溢出线外"的手感

**禁止**：渐变、玻璃拟态、霓虹发光、立体斜面（规范第 3 节）。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)

# ────────────────────────────── 色板 ──────────────────────────────
# 与 `docs/nurture/03-设计规范.md` 1.1 一致；改色板必须同步文档。

CREAM = "#FFF9F6"          # 面板底
CREAM_DEEP = "#FFF1EC"     # 次级底：信息条、圆按钮底、进度条轨道
CARD = "#FFFFFF"           # 卡片底
OUTLINE = "#8D6E63"        # 暖棕描边 —— 手绘感的核心
OUTLINE_LIGHT = "#C9AFA6"  # 次级线、内线
PINK = "#FFB7C5"           # 樱花粉
PINK_DEEP = "#F49AB0"      # hover / 强调
PINK_LIGHT = "#FFE3E9"     # 光圈、选中态底
NAVY = "#2E4A7D"           # 藏青：标题、主按钮文字
RED = "#E5484D"            # 角标 / 红点
HEART_PINK = "#FF8FA3"     # 心形
TEXT = "#5B4A46"           # 文字主色
TEXT_DIM = "#9E8B86"       # 文字次色
GREEN = "#7FB069"          # 成功
GOLD = "#E8B84B"           # 金色

#: 规范 0.2 明令禁止出现在这套 UI 里的冷蓝色值（自检用）
FORBIDDEN_COLORS: tuple[str, ...] = ("#E3F2FD", "#42A5F5", "#BBDEFB")

#: 暖色投影基色（`rgba(141,110,99,·)`）
SHADOW_RGB: tuple[int, int, int] = (141, 110, 99)
#: 面板底色的 alpha（规范 1.2：只有底色带透明，描边与文字不透明）
PANEL_ALPHA = 242
#: 库存为 0 的整卡不透明度
DISABLED_ALPHA = 0.45

#: 圆角基准（规范 0.2 / 5.x）
RADIUS_PANEL = 20
RADIUS_CARD = 14
RADIUS_ROW = 12
RADIUS_SMALL = 8

#: 面板四周留给投影的空间（窗口比可见面板大这么多）
MARGIN = 6


# ────────────────────────── 基础工具 ──────────────────────────


def color(value, alpha: int | None = None) -> QColor:
    """字符串色值 → `QColor`；`alpha` 给了就覆盖透明度。脏值回落暖棕黑。"""
    try:
        result = QColor(str(value))
    except Exception:
        result = QColor(TEXT)
    if not result.isValid():
        result = QColor(TEXT)
    if alpha is not None:
        result.setAlpha(max(0, min(255, int(alpha))))
    return result


def pen(value: str = OUTLINE, width: float = 2.0) -> QPen:
    """统一的圆头圆角描边笔。规范第 3 节第 1 条。"""
    result = QPen(color(value))
    result.setWidthF(float(width))
    result.setCapStyle(Qt.RoundCap)
    result.setJoinStyle(Qt.RoundJoin)
    result.setCosmetic(False)
    return result


def font(size: int = 13, bold: bool = False, letter_spacing: float = 0.0) -> QFont:
    """正文字体。规范第 2 节：微软雅黑 13px，标题 bold 且字距 +0.5。

    **不用手写体**：中文手写/圆体在 Windows 上没有通用字体，强依赖会退化成宋体。
    """
    result = QFont("Microsoft YaHei")
    result.setPixelSize(max(1, int(size)))
    result.setBold(bool(bold))
    try:
        if letter_spacing:
            result.setLetterSpacing(QFont.AbsoluteSpacing, float(letter_spacing))
    except Exception:
        pass
    return result


def elide(text: str, target_font: QFont, width: int) -> str:
    """按**像素**宽度省略。不能按字数估算：中日文与拉丁字母宽度差一倍多。"""
    metrics = QFontMetrics(target_font)
    return metrics.elidedText(str(text or ""), Qt.ElideRight, max(1, int(width)))


def text_width(text: str, target_font: QFont) -> int:
    return QFontMetrics(target_font).horizontalAdvance(str(text or ""))


# ────────────────────────── 造型 ──────────────────────────


def rounded_path(rect, radii) -> QPainterPath:
    """四角半径**各自独立**的圆角矩形路径。

    `QPainter.drawRoundedRect()` 只能给一个半径，而手绘感恰恰来自四角不等
    （规范第 3 节第 3 条）。`radii` 可以是一个数（四角相同）或 `(左上, 右上, 右下, 左下)`。
    """
    if isinstance(radii, (int, float)):
        radii = (radii,) * 4
    try:
        tl, tr, br, bl = (max(0.0, float(r)) for r in radii)
    except Exception:
        tl = tr = br = bl = float(RADIUS_PANEL)

    box = QRectF(rect)
    x1, y1, x2, y2 = box.left(), box.top(), box.right(), box.bottom()
    limit = max(0.0, min(box.width(), box.height()) / 2.0)
    tl, tr, br, bl = (min(v, limit) for v in (tl, tr, br, bl))

    path = QPainterPath()
    path.moveTo(x1 + tl, y1)
    path.lineTo(x2 - tr, y1)
    if tr > 0:
        path.arcTo(x2 - 2 * tr, y1, 2 * tr, 2 * tr, 90, -90)
    path.lineTo(x2, y2 - br)
    if br > 0:
        path.arcTo(x2 - 2 * br, y2 - 2 * br, 2 * br, 2 * br, 0, -90)
    path.lineTo(x1 + bl, y2)
    if bl > 0:
        path.arcTo(x1, y2 - 2 * bl, 2 * bl, 2 * bl, 270, -90)
    path.lineTo(x1, y1 + tl)
    if tl > 0:
        path.arcTo(x1, y1, 2 * tl, 2 * tl, 180, -90)
    path.closeSubpath()
    return path


def paper_radii(base: float = RADIUS_PANEL, spread: float = 2.0) -> tuple[float, ...]:
    """给一个"手画歪了一点"的四角半径：最大差值 = `spread`（默认 2px，规范上限）。"""
    base = max(2.0, float(base))
    return (base + spread * 0.5, base, base + spread, base + spread * 0.5)


def paint_path(painter: QPainter, path: QPainterPath, *,
               fill: str | None = CREAM, fill_alpha: int | None = None,
               outline: str | None = OUTLINE, width: float = 2.0,
               grow: float = 0.5, opacity: float = 1.0) -> None:
    """一次画完填充 + 描边，并把描边**往外挪 `grow` 像素**（手绘溢出感）。

    `fill`/`outline` 传 `None` 表示跳过该步。
    """
    if opacity < 1.0:
        painter.save()
        painter.setOpacity(painter.opacity() * max(0.0, float(opacity)))
    try:
        if fill:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color(fill, fill_alpha))
            painter.drawPath(path)
        if outline and width > 0:
            painter.setPen(pen(outline, width))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(_grow_path(path, grow))
    finally:
        if opacity < 1.0:
            painter.restore()


def _grow_path(path: QPainterPath, grow: float) -> QPainterPath:
    """把路径整体外扩一点（围绕包围盒中心缩放）。

    不用 `QPainterPathStroker` 是有意的：那个会把图形"描粗一圈"变成环形，
    而我们要的是"同一个形状略微放大一些"，让它比填充多出一点点边。
    """
    if grow <= 0:
        return path
    box = path.boundingRect()
    if box.width() <= 0 or box.height() <= 0:
        return path
    ratio_x = (box.width() + 2 * grow) / box.width()
    ratio_y = (box.height() + 2 * grow) / box.height()
    return _scale_about(path, ratio_x, ratio_y, box.center())


def _scale_about(path: QPainterPath, sx: float, sy: float, center) -> QPainterPath:
    from PySide6.QtGui import QTransform

    transform = QTransform()
    transform.translate(center.x(), center.y())
    transform.scale(sx, sy)
    transform.translate(-center.x(), -center.y())
    return transform.map(path)


def paint_shadow(painter: QPainter, rect, radius: float, spread: int = MARGIN) -> None:
    """柔和暖投影：几层递减透明度的圆角矩形（`QPainter` 没有模糊）。

    与 `nurture_panel._paint_panel()` **同一套公式** —— 两边的投影必须一模一样，
    否则新面板一眼就看得出是"另一套 UI"。
    """
    for step in range(int(spread), 0, -1):
        alpha = int(18 / step)
        if alpha <= 0:
            continue
        painter.setPen(Qt.NoPen)
        painter.setBrush(color("#%02X%02X%02X" % SHADOW_RGB, alpha))
        painter.drawRoundedRect(
            QRectF(rect).adjusted(-step, -step + 1, step, step + 1), radius, radius)


def paint_paper(painter: QPainter, rect, *, radius: float | None = None,
                fill: str = CREAM, fill_alpha: int | None = PANEL_ALPHA,
                outline: str = OUTLINE, width: float = 2.0,
                shadow: bool = True, spread: int = MARGIN,
                radii=None) -> None:
    """画一张"贴在屏幕上的纸"：投影 + 奶白底 + 2px 暖棕描边。"""
    radii = radii if radii is not None else paper_radii(
        RADIUS_PANEL if radius is None else radius)
    if shadow:
        paint_shadow(painter, rect, max(radii), spread)
    paint_path(painter, rounded_path(rect, radii), fill=fill, fill_alpha=fill_alpha,
               outline=outline, width=width)


def paint_card(painter: QPainter, rect, *, hovered: bool = False,
               pressed: bool = False, disabled: bool = False,
               radius: float = RADIUS_CARD) -> None:
    """卡片：白底 + 1.5px 次级描边 + 0/2/6 投影；hover 上浮 2px、按下沉 1px。"""
    box = QRectF(rect)
    if hovered:
        box.adjust(0, -2, 0, 2)
    if pressed:
        box.adjust(0, 1, 0, -1)
    if not disabled:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color("#%02X%02X%02X" % SHADOW_RGB, 20))
        painter.drawRoundedRect(box.adjusted(0, 2, 0, 3), radius, radius)
    opacity = DISABLED_ALPHA if disabled else 1.0
    paint_path(painter, rounded_path(box, paper_radii(radius, 1.5)),
               fill=CREAM if hovered else CARD,
               outline=PINK_DEEP if hovered else OUTLINE_LIGHT,
               width=1.5, opacity=opacity)


def paint_row(painter: QPainter, rect, *, hovered: bool = False,
              pressed: bool = False, selected: bool = False,
              disabled: bool = False, radius: float = RADIUS_ROW) -> None:
    """列表行（胶囊）：默认透明无描边，hover 粉底 + 粉描边，选中粉浅底 + 暖棕描边。"""
    if not (hovered or pressed or selected):
        return
    fill = PINK_DEEP if pressed else (PINK_LIGHT if hovered else PINK_LIGHT)
    outline = PINK_DEEP if (hovered or pressed) else OUTLINE_LIGHT
    paint_path(painter, rounded_path(rect, radius), fill=fill, fill_alpha=232,
               outline=outline, width=1.5,
               opacity=DISABLED_ALPHA if disabled else 1.0)


def paint_circle(painter: QPainter, rect, *, fill: str = CREAM_DEEP,
                 outline: str = OUTLINE, width: float = 2.0,
                 hovered: bool = False, pressed: bool = False,
                 glow: bool = False, disabled: bool = False,
                 pressed_fill: str = PINK_DEEP) -> None:
    """正圆按钮（规范 5.1）：默认奶白/浅奶，hover 粉浅 + 外圈粉光圈，按下粉深。"""
    box = QRectF(rect)
    if hovered:
        box.adjust(0, -1, 0, 1)          # 上浮 1px
    if pressed:
        box.adjust(0, 1, 0, -1)          # 下沉 1px
    if glow and not disabled:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color(PINK, 128))
        painter.drawEllipse(box.adjusted(-3, -3, 3, 3))
    if pressed:
        base = pressed_fill
    elif hovered:
        base = PINK_LIGHT
    else:
        base = fill
    paint_path(painter, rounded_path(box, box.height() / 2.0), fill=base,
               outline=PINK_DEEP if hovered else outline, width=width,
               opacity=DISABLED_ALPHA if disabled else 1.0)


def paint_badge(painter: QPainter, center, diameter: float, text: str = "", *,
                fill: str = PINK_DEEP) -> None:
    """圆形角标（规范 5.2：直径 18px，底粉深，1.5px 奶白描边，白字 10px bold）。

    `center` 可以是 `QPointF` 或 `(x, y)`；`diameter` 是**直径**不是半径。
    """
    try:
        cx, cy = float(center[0]), float(center[1])
    except Exception:
        cx, cy = float(center.x()), float(center.y())
    size = max(4.0, float(diameter))
    box = QRectF(cx - size / 2.0, cy - size / 2.0, size, size)
    paint_path(painter, rounded_path(box, size / 2.0), fill=fill,
               outline=CREAM, width=1.5, grow=0.0)
    label = str(text or "")
    if not label:
        return
    painter.setFont(font(10, bold=True))
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(box, Qt.AlignCenter, label)


# ────────────────────────── 标准控件的样式表 ──────────────────────────
#
# 面板/菜单是**全自绘**的（上面那些 paint_* 函数），但设置窗口里有大量标准控件
# （QComboBox / QSpinBox / QSlider / QCheckBox / QListWidget…）。把它们逐个改写成自绘控件
# 是几天的活，而 QSS 能覆盖到 95% 的观感 —— 所以这一层的策略是：
# **自绘负责"造型"，QSS 负责"配色与圆角"**。
#
# 用 `@名字@` 占位再替换，而不是 f-string：QSS 里全是 `{}`，f-string 会把它们当表达式。

_STYLESHEET_TEMPLATE = """
QWidget {
    color: @TEXT@;
    font-family: "Microsoft YaHei";
    font-size: 13px;
}
QLabel { background: transparent; }
QLabel#Title {
    font-size: 15px;
    font-weight: bold;
    color: @NAVY@;
    padding: 2px 0 6px 0;
}
QLabel#SectionLabel {
    font-size: 13px;
    font-weight: bold;
    color: @NAVY@;
}
QLabel#SubLabel {
    font-size: 12px;
    color: @TEXT@;
    min-width: 42px;
    background: transparent;
}
QLabel#ValueLabel {
    font-size: 12px;
    color: @TEXT_DIM@;
    min-width: 50px;
}
QLabel#HintLabel {
    font-size: 11px;
    color: @TEXT_DIM@;
}
QLabel#MapLabel {
    font-size: 12px;
    color: @TEXT@;
    min-width: 72px;
    background: transparent;
}
QLabel#DimLabel {
    font-size: 12px;
    color: @TEXT_DIM@;
    background: transparent;
}

/* 小号按钮（启动序列的 ＋ / － / ▲ / ▼）：保持紧凑，别占满一行 */
QPushButton#SmallBtn {
    padding: 3px 8px;
    border-radius: 10px;
    font-size: 12px;
    min-width: 0;
}

/* ── 纸片分组（规范 5.6：控件底 #FFF1EC、圆角 8px、描边 1.5px #C9AFA6）── */
QGroupBox {
    background: @CREAM_DEEP@;
    border: 1.5px solid @OUTLINE_LIGHT@;
    border-radius: 12px;
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    font-size: 13px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: @NAVY@;
    font-weight: bold;
    /* 用**同 alpha 的奶白**盖住标题处的那一段边框。
       写成不透明的 #FFF9F6 会在半透明纸片上留下一块更亮的补丁（实测可见），
       所以这里必须跟纸片底色一样带 242/255 的透明度。 */
    background: rgba(255, 249, 246, 242);
    border-radius: 6px;
}

/* ── 按钮 ── */
QPushButton {
    background: @CREAM@;
    border: 2px solid @OUTLINE@;
    border-radius: 14px;
    padding: 6px 14px;
    color: @TEXT@;
    font-size: 13px;
}
QPushButton:hover { background: @PINK_LIGHT@; border-color: @PINK_DEEP@; }
QPushButton:pressed { background: @PINK_DEEP@; border-color: @PINK_DEEP@; color: #FFFFFF; }
QPushButton:disabled { color: @TEXT_DIM@; border-color: @OUTLINE_LIGHT@; }
QPushButton#PrimaryBtn {
    background: @PINK@;
    border-color: @PINK_DEEP@;
    color: @NAVY@;
    font-weight: bold;
    padding: 8px 24px;
}
QPushButton#PrimaryBtn:hover { background: @PINK_DEEP@; color: #FFFFFF; }

/* ── 下拉框 / 数字框 ── */
QComboBox, QSpinBox, QLineEdit, QDateEdit {
    background: #FFFFFF;
    border: 1.5px solid @OUTLINE_LIGHT@;
    border-radius: 10px;
    padding: 4px 10px;
    color: @TEXT@;
    min-height: 20px;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover, QDateEdit:hover {
    border-color: @PINK_DEEP@;
}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: @OUTLINE@; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: @CREAM@;
    border: 1.5px solid @OUTLINE_LIGHT@;
    border-radius: 8px;
    selection-background-color: @PINK_LIGHT@;
    selection-color: @NAVY@;
    color: @TEXT@;
    outline: none;
    padding: 2px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 16px;
    background: transparent;
    border: none;
}

/* ── 滑块（轨道奶白、把手樱花粉）── */
QSlider::groove:horizontal {
    background: @CREAM_DEEP@;
    border: 1.5px solid @OUTLINE_LIGHT@;
    height: 8px;
    border-radius: 4px;
}
QSlider::sub-page:horizontal { background: @PINK_LIGHT@; border-radius: 4px; }
QSlider::handle:horizontal {
    background: @PINK@;
    border: 2px solid @OUTLINE@;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover { background: @PINK_DEEP@; }

/* ── 勾选框 ── */
QCheckBox { color: @TEXT@; spacing: 6px; background: transparent; }
QCheckBox#PoolCheck { font-size: 11px; color: @TEXT@; spacing: 4px; }
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1.5px solid @OUTLINE_LIGHT@;
    border-radius: 5px;
    background: #FFFFFF;
}
QCheckBox::indicator:hover { border-color: @PINK_DEEP@; }
QCheckBox::indicator:checked { background: @PINK@; border-color: @OUTLINE@; }

/* ── 列表 ── */
QListWidget {
    background: #FFFFFF;
    border: 1.5px solid @OUTLINE_LIGHT@;
    border-radius: 10px;
    color: @TEXT@;
    outline: none;
    padding: 2px;
}
QListWidget::item { padding: 3px 6px; border-radius: 6px; }
QListWidget::item:selected { background: @PINK_LIGHT@; color: @NAVY@; }
QListWidget::item:hover { background: @PINK_LIGHT@; }

/* ── 滚动区 ──
   `QScrollArea { background: transparent }` **管不到 viewport**：视口是它内部的子控件，
   不显式声明就会用系统默认底色（浅灰蓝），在奶白纸片上糊出一条色带（实测踩过）。
   这两行都要写：一行给滚动区本身，一行给"视口 → 内容容器"。 */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea QWidget#qt_scrollarea_viewport { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical {
    background: @OUTLINE_LIGHT@;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: @PINK_DEEP@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* ── 消息框（保存确认）── */
QMessageBox { background: @CREAM@; }
QMessageBox QLabel { color: @TEXT@; }
"""


def app_stylesheet() -> str:
    """标准控件的暖粉奶白样式表（设置窗口与 Q 版设置页共用）。

    色值全部来自本模块的色板 —— 想改主题只改上面的常量，这里会跟着变。
    """
    tokens = {
        "@CREAM@": CREAM, "@CREAM_DEEP@": CREAM_DEEP, "@OUTLINE@": OUTLINE,
        "@OUTLINE_LIGHT@": OUTLINE_LIGHT, "@PINK@": PINK, "@PINK_DEEP@": PINK_DEEP,
        "@PINK_LIGHT@": PINK_LIGHT, "@NAVY@": NAVY, "@TEXT@": TEXT,
        "@TEXT_DIM@": TEXT_DIM, "@RED@": RED, "@GREEN@": GREEN, "@GOLD@": GOLD,
    }
    text = _STYLESHEET_TEMPLATE
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text
