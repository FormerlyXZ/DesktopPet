"""对话气泡 `SpeechBubble` —— 人物头顶的说话框（阶段 E）。

对应需求：`docs/nurture/01-需求规格.md` 第 7 节；对应规范：`03-设计规范.md` 5.3。

**这是整个养成系统里"最容易被用户骂"的组件** —— 一个桌面宠物如果把输入焦点抢走，
用户正在打的字就没了。所以下面四条是硬约束，任何一条破了都是严重事故：

| 约束 | 实现 |
|------|------|
| 绝不抢焦点 | `WindowDoesNotAcceptFocus` + `WA_ShowWithoutActivating`，**不调 `activateWindow()`** |
| 鼠标完全穿透 | `WindowTransparentForInput` + `WA_TransparentForMouseEvents` |
| 压在人物之上 | `WindowStaysOnTopHint` + `_force_raise_topmost()` |
| 同时只有一个 | 新台词到来时**替换内容**并重启计时器，不叠加窗口 |

**动效自实现，没有复用 `panel_animator`**：后者的位移量硬编码成 40px，
而规范 5.3 要求气泡只滑 8px —— 40px 对一个小气泡来说像"从屏幕外飞进来"。
（与 `HoverMenu`/`NurturePanel` 同一个理由，三个组件的动效参数各自独立。）

**尾巴与主体合并成一个 `QPainterPath` 再一次描边**（规范 5.3 明确要求）：
分两次画会在接缝处露出一条内线，那是手绘风最忌讳的"塑料感"。

自检预览：`python -m src.speech_bubble [输出路径.png]`
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QWidget

from src import nurture_icons as icons
from src.bubble_panel import _force_raise_topmost

# ────────────────────────── 规格常量（对应 03-设计规范 5.3）──────────────────────────

CREAM = icons.CREAM            # #FFF9F6 气泡底
OUTLINE = icons.OUTLINE        # #8D6E63 暖棕描边
TEXT = icons.TEXT              # #5B4A46
SHADOW_RGB = (141, 110, 99)    # 暖色投影基色

MIN_WIDTH = 120        # 气泡宽度下限
MAX_WIDTH = 220        # 上限
PAD_X = 12             # 内边距（左右）
PAD_Y = 10             # 内边距（上下）
RADIUS = 14            # 圆角
TAIL_W = 14            # 尾巴宽（等腰三角的底边）
TAIL_H = 8             # 尾巴高
MARGIN = 6             # 窗口外留给投影的空间
FONT_PX = 13           # 文字字号
LINE_SPACING = 1.55    # 行距（规范 5.3）
MAX_LINES = 4          # 最多 4 行，超出加省略号

SHOW_MS = 180          # 从下方 8px 滑上 + 淡入
HIDE_MS = 220          # 反向滑下 8px + 淡出
SLIDE = 8
DEFAULT_DURATION_MS = 3500
MIN_DURATION_MS = 2000
MAX_DURATION_MS = 8000

#: 断行时愿意回退到哪：只有当最近的分隔点落在这一行 60% 之后才回退，
#: 否则宁可硬断（中日文没有空格，硬断是常态）
_BREAK_BACKTRACK = 0.6
_BREAK_CHARS = " \t、，。！？：；,.!?:;）」』】"


def make_font() -> QFont:
    font = QFont("Microsoft YaHei")
    font.setPixelSize(FONT_PX)
    return font


def wrap_text(text: str, font: QFont, max_width: int, max_lines: int = MAX_LINES) -> list[str]:
    """按像素宽度断行，最多 `max_lines` 行；超出时最后一行加省略号。

    **不能按字数估算**：中日文与拉丁字母宽度差一倍多，按 `len()` 切会在中英混排时忽宽忽窄。
    中日文没有空格，所以按**字符**逐个累加（这是 CJK 排版的常规做法）；
    若这一行里存在分隔符，就回退到最后一个分隔符处，避免把拉丁单词劈成两半。
    """
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    metrics = QFontMetrics(font)
    max_width = max(8, int(max_width))
    lines: list[str] = []

    for paragraph in text.split("\n"):
        if len(lines) >= max_lines:
            break
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            if not current:
                current = char
                continue
            if metrics.horizontalAdvance(current + char) <= max_width:
                current += char
                continue
            # 放不下了：优先在最后一个分隔符处断开
            cut = -1
            for index in range(len(current) - 1, -1, -1):
                if current[index] in _BREAK_CHARS:
                    if metrics.horizontalAdvance(current[:index + 1]) >= max_width * _BREAK_BACKTRACK:
                        cut = index + 1
                    break
            if cut > 0:
                lines.append(current[:cut].rstrip())
                current = current[cut:].lstrip() + char
            else:
                lines.append(current)
                current = char
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)

    if not lines:
        return [""]

    # 被截掉的文字：把最后一行末尾换成省略号（不是新起一行 "…"，那样会多占一行高）
    rendered = "".join(lines)
    if len(rendered) < len(text.replace("\n", "")):
        last = lines[-1]
        while last and metrics.horizontalAdvance(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines[:max_lines]


class SpeechBubble(QWidget):
    """人物头顶的说话框。只负责"显示一段文字"，不做任何调度判断。

    什么时候能说话、说什么，全在 `NurtureController`（冷却表 / 最小间隔 / 禁区）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.SubWindow
            | Qt.WindowDoesNotAcceptFocus        # ← 绝不抢焦点
            | Qt.WindowTransparentForInput       # ← 鼠标完全穿透
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 气泡是不可交互的展示层，不该出现在任务栏，也不该接受任何输入
        self.setFocusPolicy(Qt.NoFocus)

        self._text = ""
        self._lines: list[str] = [""]
        self._tail_side = "bottom"        # 尾巴在主体的哪一侧：bottom（气泡在上方）/ top（翻到下方）
        self._tail_cx = 0
        self._body = QRect()
        self._duration_ms = DEFAULT_DURATION_MS
        self._anchor_ratio = 0.14
        self._showing = False
        self._show_anim = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_with_anim)

        self._font = make_font()
        self.setFixedSize(MIN_WIDTH + MARGIN * 2,
                          (PAD_Y * 2 + FONT_PX) + TAIL_H + MARGIN * 2)

    # ────────────────── 对外接口 ──────────────────

    def show_text(self, text: str, anchor=None, duration_ms: int | None = None,
                  ratio: float | None = None) -> bool:
        """显示一句台词。返回是否真的显示了（空字符串直接返回 `False`）。

        :param anchor: 人物的**全局矩形**（`PetWindow.frameGeometry()`）。不传就只换文字、不动位置。
        :param duration_ms: 停留时长，缺省用 `bubble_duration_ms` 推来的 3500ms（夹在 2000~8000）
        :param ratio: 尾巴尖在人物窗口高度上的比例（来自 `character.speech_anchor_ratio()`）
        """
        text = str(text or "").strip()
        if not text:
            return False

        # 先停旧计时器：连续触发多条台词时**替换内容**而不是排队/叠加（规范 5.3）
        self._timer.stop()
        self._stop_anim()

        if duration_ms is not None:
            try:
                value = int(duration_ms)
            except (TypeError, ValueError):
                value = DEFAULT_DURATION_MS
            self._duration_ms = max(MIN_DURATION_MS, min(MAX_DURATION_MS, value))
        if ratio is not None:
            try:
                self._anchor_ratio = max(0.0, min(1.0, float(ratio)))
            except (TypeError, ValueError):
                pass

        self._text = text
        if anchor is not None:
            self.layout_for(anchor)
        else:
            self._relayout_text()

        if self._showing and self.isVisible():
            # 已经在显示 → 原地换内容（不重播入场动画，否则会"抖一下"）
            self.update()
            _force_raise_topmost(self)
            self._timer.start(self._duration_ms)
            return True

        self._showing = True
        self._animate_in()
        # 必须排在 show() 之后：没有 HWND 时 raise 是空操作
        _force_raise_topmost(self)
        self._timer.start(self._duration_ms)
        return True

    def follow(self, anchor, ratio: float | None = None) -> None:
        """人物被拖动时重新贴住它（不重播动画、不重置停留计时）。"""
        if not self._showing:
            return
        if ratio is not None:
            try:
                self._anchor_ratio = max(0.0, min(1.0, float(ratio)))
            except (TypeError, ValueError):
                pass
        self.layout_for(anchor)

    def hide_with_anim(self) -> None:
        """滑下 8px + 淡出收起。已经在收/没显示时是空操作。"""
        self._timer.stop()
        if not self.isVisible() or not self._showing:
            return
        self._showing = False
        end = self.pos() + self._offset()
        self._run_anim(self.pos(), end, self.windowOpacity(), 0.0, HIDE_MS,
                       QEasingCurve.InCubic, hide_after=True)

    def hide_now(self) -> None:
        """立刻隐藏，无动画（切角色/退出时用）。"""
        self._stop_anim()
        self._timer.stop()
        self._showing = False
        self.hide()
        self.setWindowOpacity(1.0)

    def is_showing(self) -> bool:
        return self._showing

    def text(self) -> str:
        return self._text

    def lines(self) -> list[str]:
        """当前实际画出来的行（断行结果，测试与预览用）。"""
        return list(self._lines)

    def tail_side(self) -> str:
        return self._tail_side

    def body_rect(self) -> QRect:
        """主体矩形（组件坐标系，不含尾巴与投影留白）。"""
        return QRect(self._body)

    def tail_tip(self) -> QPoint:
        """尾巴尖的**全局**坐标（测试用：它必须落在人物头顶的锚点上）。"""
        if self._tail_side == "top":
            local = QPoint(self._tail_cx, self._body.top() - TAIL_H)
        else:
            local = QPoint(self._tail_cx, self._body.bottom() + TAIL_H)
        return self.pos() + local

    # ────────────────── 几何 ──────────────────

    def _content_width(self) -> int:
        return MAX_WIDTH - PAD_X * 2

    def _measure(self, text: str) -> tuple[QSize, list[str]]:
        """算气泡主体的尺寸与断行结果。

        宽度自适应 `[120, 220]`：短句窄一点（像真的贴着人物说话），长句到 220 就换行。
        """
        metrics = QFontMetrics(self._font)
        single = metrics.horizontalAdvance(str(text).replace("\n", " "))
        width = max(MIN_WIDTH, min(MAX_WIDTH, single + PAD_X * 2))
        lines = wrap_text(text, self._font, width - PAD_X * 2, MAX_LINES)
        line_h = max(1, int(round(FONT_PX * LINE_SPACING)))
        height = PAD_Y * 2 + line_h * len(lines)
        return QSize(width, height), lines

    def _relayout_text(self) -> None:
        """只根据当前文字重算窗口尺寸（锚点不变时用）。"""
        size, lines = self._measure(self._text)
        self._lines = lines
        self.setFixedSize(size.width() + MARGIN * 2,
                          size.height() + TAIL_H + MARGIN * 2)
        self._place_body(QSize(size.width(), size.height()))

    def _place_body(self, size: QSize) -> None:
        """按尾巴朝向把主体放在组件内的正确位置。"""
        if self._tail_side == "top":
            self._body = QRect(MARGIN, MARGIN + TAIL_H, size.width(), size.height())
        else:
            self._body = QRect(MARGIN, MARGIN, size.width(), size.height())

    def layout_for(self, pet_geometry, screen_geometry=None):
        """**纯几何**：决定尾巴朝向与窗口位置，返回 `(tail_side, QRect)`。

        位置规则（规范 5.3）：

        1. 常态：气泡在人物**上方**，尾巴尖对准 `人物顶边 + 高度 × ratio`（头顶），水平居中于人物
        2. 上方越界 → 翻到人物**下方**，尾巴朝上；此时尾巴尖改对准**人物底边**
           —— 锚点若还用头顶的 14%，气泡就会压在人物身上（她的头在窗口高 14% 处）
        3. 水平方向越界 → 夹紧到屏幕内（尾巴跟着收进来，不跟着飘到气泡外）

        刻意与动画分离：动画一跑 `pos()` 就在动，位置断言会变得不可靠。
        """
        size, lines = self._measure(self._text)
        self._lines = lines
        self.setFixedSize(size.width() + MARGIN * 2,
                          size.height() + TAIL_H + MARGIN * 2)

        app = QApplication.instance()
        try:
            pet_geometry = QRect(pet_geometry)
        except TypeError:
            # 调用方传了脏值（None / 字符串）也不能让绘制路径崩：
            # 退化成空矩形，锚点落在屏幕左上角，先画出来再说
            pet_geometry = QRect()
        if screen_geometry is None:
            screen = (app.screenAt(pet_geometry.center()) or app.primaryScreen()
                      if app is not None else None)
            screen_geometry = screen.availableGeometry() if screen is not None else QRect(
                0, 0, 1920, 1080)
        geom = QRect(screen_geometry)

        head_tip = QPoint(pet_geometry.center().x(),
                          pet_geometry.top() + int(pet_geometry.height() * self._anchor_ratio))

        width, height = self.width(), self.height()
        body_h = size.height()

        # `QRect.bottom()` 是**闭区间**：主体占 [top, bottom] 共 body_h 行，尾巴紧接在下一行开始，
        # 尾巴尖是尾巴那 TAIL_H 行的**最后一行**。所以这里要 +1，否则尾巴尖会永远差 1px
        # （单测 `test_above_with_the_tail_on_the_head` 盯这个）。
        above_y = head_tip.y() - TAIL_H - body_h - MARGIN + 1
        if above_y >= geom.top():
            tail_side, widget_y = "bottom", above_y
        else:
            # 翻转时尾巴尖是尾巴那几行的**第一行**（朝上），公式里不出现 -1/+1
            below_y = pet_geometry.bottom() + 1 - MARGIN
            if below_y + height <= geom.bottom() + 1:
                tail_side, widget_y = "top", below_y
            else:
                # 上下都放不下（人物几乎占满屏幕高）→ 贴空间大的一侧，交给夹紧
                room_above = head_tip.y() - geom.top()
                room_below = geom.bottom() - pet_geometry.bottom()
                tail_side = "bottom" if room_above >= room_below else "top"
                widget_y = (above_y if tail_side == "bottom" else below_y)

        self._tail_side = tail_side
        self._place_body(size)

        # `(width - 1) // 2` 而不是 `width // 2`：QRect.center() 的整数除法口径如此，
        # 用后者在宽度为偶数时气泡会比人物偏 1px（与菜单/面板同一个坑）
        widget_x = head_tip.x() - (width - 1) // 2
        widget_x = max(geom.left(), min(int(widget_x), geom.right() - width + 1))
        widget_y = max(geom.top(), min(int(widget_y), geom.bottom() - height + 1))

        # 尾巴横向跟着锚点，但夹在主体内（离圆角至少一个小半径），否则尾巴会跑到气泡外面
        inset = int(RADIUS * 0.6) + TAIL_W // 2
        lo = MARGIN + inset
        hi = MARGIN + width - MARGIN * 2 - inset
        if hi < lo:
            hi = lo
        self._tail_cx = max(lo, min(head_tip.x() - widget_x, hi))

        rect = QRect(widget_x, widget_y, width, height)
        self.move(rect.topLeft())
        return tail_side, rect

    def _offset(self) -> QPoint:
        """位移向量，方向**指向人物那一侧**（气泡在人物上方 → 朝下）。

        * 入场：从这一侧滑出来（从下方 8px 滑上）
        * 退场：往这一侧滑回去（反向滑下 8px）
        """
        return QPoint(0, SLIDE if self._tail_side == "bottom" else -SLIDE)

    # ────────────────── 动效 ──────────────────

    def _animate_in(self) -> None:
        target = self.pos()
        # `target + offset`：起点在**靠近人物**的那一侧，向目标滑过去。
        # 写成 `target - offset` 会让入场方向和退场方向相同（都是往下滑），
        # 视觉上变成"气泡从头顶往下掉"，与规范 5.3 的"从下方 8px 滑上"相反。
        start = target + self._offset()
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        self._run_anim(start, target, 0.0, 1.0, SHOW_MS, QEasingCurve.OutCubic)

    def _run_anim(self, start, end, from_op, to_op, duration, curve, hide_after=False):
        from PySide6.QtCore import QParallelAnimationGroup

        self._stop_anim()
        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.setDuration(duration)
        pos_anim.setEasingCurve(curve)
        op_anim = QPropertyAnimation(self, b"windowOpacity", self)
        op_anim.setStartValue(from_op)
        op_anim.setEndValue(to_op)
        op_anim.setDuration(duration)
        op_anim.setEasingCurve(curve)
        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(op_anim)
        if hide_after:
            group.finished.connect(self._on_hide_finished)
        group.start()
        self._show_anim = group

    def _on_hide_finished(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)

    def _stop_anim(self) -> None:
        group = getattr(self, "_show_anim", None)
        if group is not None:
            try:
                group.stop()
            except RuntimeError:
                pass
            self._show_anim = None

    # 不实现 focusOutEvent、不实现任何鼠标事件 —— 见模块文档

    # ────────────────── 绘制 ──────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint_shadow(painter)
            path = self._bubble_path()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 249, 246, 240))
            painter.drawPath(path)
            pen = QPen(QColor(OUTLINE))
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)          # 主体 + 尾巴**一次**描边，接缝处不会露出内线
            self._paint_text(painter)
        finally:
            painter.end()

    def _bubble_path(self) -> QPainterPath:
        """主体圆角矩形与尾巴三角合并成一个路径。"""
        body = self._body
        radius = float(RADIUS)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)

        cx = self._tail_cx
        half = TAIL_W / 2.0
        if self._tail_side == "top":
            # 尾巴在主体**上方**：底边贴着主体上一行，尖朝上
            base_y = body.top() - 1
            tip_y = body.top() - TAIL_H
        else:
            # 尾巴在主体**下方**：底边贴着主体下一行，尖朝下
            base_y = body.bottom() + 1
            tip_y = body.bottom() + TAIL_H
        triangle = QPolygonF([QPoint(int(cx - half), int(base_y)),
                              QPoint(int(cx + half), int(base_y)),
                              QPoint(int(cx), int(tip_y))])
        tail = QPainterPath()
        tail.addPolygon(triangle)
        tail.closeSubpath()
        return path.united(tail)

    def _paint_shadow(self, painter: QPainter) -> None:
        """投影 0/3px：「模糊 10px」用几层递减透明度的圆角矩形伪造（QPainter 没有模糊）。"""
        for step in range(MARGIN, 0, -1):
            alpha = int(20 / step)
            if alpha <= 0:
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*SHADOW_RGB, alpha))
            painter.drawRoundedRect(
                self._body.adjusted(-step, -step + 3, step, step + 3),
                RADIUS + step, RADIUS + step)

    def _paint_text(self, painter: QPainter) -> None:
        if not self._text:
            return
        painter.setFont(self._font)
        painter.setPen(QPen(QColor(TEXT)))
        line_h = max(1, int(round(FONT_PX * LINE_SPACING)))
        text_rect = QRect(self._body.x() + PAD_X, self._body.y() + PAD_Y,
                          self._body.width() - PAD_X * 2, line_h * len(self._lines))
        for index, line in enumerate(self._lines):
            rect = QRect(text_rect.x(), text_rect.y() + index * line_h,
                         text_rect.width(), line_h)
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, line)


# ────────────────────────── 自检预览 ──────────────────────────


def render_preview(path: str) -> None:
    """把气泡的几种形态渲染到一张图（人工验收用）。

    刻意排两种人物位置：**人物在屏幕中间**（气泡在上方、尾巴朝下，常态）与
    **人物贴着屏幕顶部**（上方放不下 → 翻到下方、尾巴朝上）。
    """
    from PySide6.QtGui import QPixmap

    pet_middle = QRect(0, 260, 300, 500)
    pet_top = QRect(0, 0, 300, 500)
    cases = [
        ("一行短句（人物在中间 → 尾巴朝下）", "唔，好吃。", pet_middle),
        ("两行", "奶油面包，给你留了一个。趁热吃比较好吃哦。", pet_middle),
        ("四行上限", "今天的工作看起来很忙呢，我先安静一会儿，"
                     "等你空下来再一起吃点心吧，反正我也不着急。", pet_middle),
        ("超长（省略号）", "这个真的特别特别好吃，是我排了很久的队才买到的，"
                           "你一定要趁热吃掉，凉了口感就完全不一样了，"
                           "而且我还特意多买了一份放在柜子里等你。", pet_middle),
        ("人物贴屏幕顶部 → 翻到下方、尾巴朝上",
         "奶油面包，给你留了一个。趁热吃比较好吃哦。", pet_top),
    ]
    shots = []
    for label, text, pet in cases:
        bubble = SpeechBubble()
        bubble._text = text                       # noqa: SLF001 - 预览专用
        bubble.layout_for(pet)
        bubble.setWindowOpacity(1.0)
        bubble.ensurePolished()
        shots.append((f"{label}  {bubble.width()}x{bubble.height()}  "
                      f"{len(bubble.lines())} 行  尾巴={bubble.tail_side()}", bubble.grab()))

    pad, label_h = 12, 18
    width = max(s.width() for _l, s in shots) + pad * 2
    height = sum(s.height() + label_h + pad for _l, s in shots) + pad
    sheet = QPixmap(width, height)
    sheet.fill(QColor(icons.CREAM_DEEP))
    painter = QPainter(sheet)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QPen(QColor(TEXT)))
        y = pad
        for label, shot in shots:
            painter.drawText(QRect(pad, y, width - pad * 2, label_h),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            y += label_h
            painter.drawPixmap(pad, y, shot)
            y += shot.height() + pad
    finally:
        painter.end()
    sheet.save(path)
    print(f"speech bubble preview -> {path}  ({sheet.width()}x{sheet.height()})")


def _main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([])   # noqa: F841
    out = argv[1] if len(argv) > 1 else "_speech_bubble_preview.png"
    render_preview(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
