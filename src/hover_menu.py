"""悬停菜单 —— 鼠标在人物上停留片刻后弹出的圆形按钮条。

对应需求：`docs/nurture/01-需求规格.md` 第 5 节；对应规范：`03-设计规范.md` 5.1。

**这是整个养成系统里唯一需要"用户把鼠标从人物移到另一个窗口"的组件**，
所以它有两个与 `BubblePanel` 刻意相反的设定（照抄 `BubblePanel` 必然做废）：

| | `BubblePanel`（现有菜单） | `HoverMenu`（本组件） |
|---|---|---|
| 焦点 | 需要能点 → `raise_()` + `activateWindow()` | **`WindowDoesNotAcceptFocus`，绝不 `activateWindow()`** |
| 收起 | `focusOutEvent` 里自动收起 | **不实现 `focusOutEvent`**，靠 `PetWindow` 的 350ms 宽限期收起 |

> 为什么不加 `focusOutEvent`：菜单永远拿不到焦点，`focusOutEvent` 就不会触发；
> 而一旦它真的触发了（比如被别的方式激活），菜单会在用户还没点到时自己消失。
> 收起时机必须由 `PetWindow` 的宽限期统一决定。

**落位**：恒定贴在人物**下方**、与人物水平居中对齐。**不按屏幕位置挑方位**
> （规范 5.1 第二次修订：曾经是"上方优先、上下左右逐级兜底"）。
> 理由：菜单每次都从同一侧冒出来，位置可预期；否则人物一往上拖，菜单就突然改从下面
> 钻出来，同一套按钮在屏幕上跳来跳去，反而更难形成肌肉记忆。
> 只剩两个自由度：横排放不下整块屏幕宽时转竖排、整体夹紧进屏幕可用区。
> 详见 `plan_placement()`。

**动效**：本组件自己实现 12px / 200ms 的滑入淡出，没有复用 `panel_animator`——
后者的位移量硬编码成 40px，对一条 44px 高的胶囊来说太大，会像"飞进来"。
规范 `03-设计规范.md` 第 6 节要求悬停菜单位移 12px、弹出 200ms、收起 160ms，这里照做。

自检预览：`python -m src.hover_menu [输出路径.png]`
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from src import nurture_icons as icons
from src.bubble_panel import _force_raise_topmost

# ────────────────────────── 规格常量（对应 03-设计规范 5.1）──────────────────────────

CREAM = icons.CREAM            # #FFF9F6 胶囊底
CREAM_DEEP = icons.CREAM_DEEP  # #FFF1EC 按钮默认底
PINK = icons.PINK              # #FFB7C5
PINK_DEEP = icons.PINK_DEEP    # #F49AB0 按下态
PINK_LIGHT = icons.PINK_LIGHT  # #FFE3E9 hover 态
OUTLINE = icons.OUTLINE        # #8D6E63 → 2px 暖棕描边
OUTLINE_LIGHT = icons.OUTLINE_LIGHT  # #C9AFA6 不可用描边
RED = icons.RED                # #E5484D 红点角标
TEXT = icons.TEXT              # #5B4A46
SHADOW_RGB = (141, 110, 99)    # 暖色投影基色

PAD = 8            # 胶囊内边距
GAP = 8            # 按钮间距
MARGIN = 6         # 胶囊外留给投影的空间
ICON_SIZE = 20     # 图标逻辑尺寸
TOOLTIP_H = 26     # 提示条预留带高度（始终预留，不用时透明）
TOOLTIP_GAP = 6    # 提示条与胶囊之间的空隙
MIN_BUTTON = 36    # 按钮直径下限（桌宠 250px 时）
MAX_BUTTON = 52    # 按钮直径上限（桌宠 700px 时）
BUTTON_RATIO = 0.11
GAP_FROM_PET = 8   # 与人物窗口的间距（上下左右同值）
DRAG_OUT_OFFSET = 12   # 弹出/收起的位移量（规范第 6 节）
SHOW_MS = 200
HIDE_MS = 160
TOOLTIP_FADE_MS = 150

#: 默认按钮顺序。`NurtureController` 会按好感度解锁情况动态调整
DEFAULT_ITEMS: tuple[str, ...] = (
    "feed", "gift", "checkin", "heart", "chat", "headpat", "settings",
)

#: 按钮文案。**阶段 H 会整体搬进 `src/translations.py`**（那里是三语字典的唯一出处）。
#: 现在放这里是为了让阶段 C 自包含，不必提前改 `translations.py`。
LABELS: dict[str, dict[str, str]] = {
    "feed":     {"zh": "喂食",     "en": "Feed",      "ja": "ごはん"},
    "gift":     {"zh": "送礼",     "en": "Gift",      "ja": "プレゼント"},
    "checkin":  {"zh": "签到",     "en": "Check in",  "ja": "チェックイン"},
    "heart":    {"zh": "好感度",   "en": "Affection", "ja": "好感度"},
    "chat":     {"zh": "陪她聊聊", "en": "Chat",      "ja": "おしゃべり"},
    "headpat":  {"zh": "摸头",     "en": "Head pat",  "ja": "なでなで"},
    "settings": {"zh": "设置",     "en": "Settings",  "ja": "設定"},
}


#: 提示条恒在胶囊**下方**：菜单在人物下方，所以下侧才是背离人物的那一侧。
#: 反过来（提示条朝上）它会挤在胶囊和人物之间 —— 既贴脸，还会让窗口压住人物窗口，
#: 那一块透明区域会吃掉鼠标事件，人物就点不到了。
TOOLTIP_SIDE = "bottom"


def button_size_for(pet_height: int) -> int:
    """按桌宠高度算按钮直径：`clamp(36, 高度 × 0.11, 52)`（规范 5.1 / 第 10 节）。"""
    try:
        raw = int(pet_height) * BUTTON_RATIO
    except (TypeError, ValueError):
        raw = MAX_BUTTON
    return max(MIN_BUTTON, min(MAX_BUTTON, int(raw)))


def _debug_log_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "debug_img.log")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "debug_img.log")


def dbg(msg: str) -> None:
    """降级/兜底路径的轻量日志，沿用项目既有的 `debug_img.log` 约定。

    **不用 `print`**：打包成 exe 后由 pythonw 启动，`sys.stdout` 是 None，
    `print` 在那种环境下不可靠。写文件也更方便事后排查。
    """
    try:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] [nurture/hover_menu] {msg}\n")
    except Exception:
        pass


class HoverMenu(QWidget):
    """圆形按钮条。只负责"显示 + 报告点击"，所有业务判断都在 `NurtureController`。"""

    #: 某个按钮被点击（`"feed"` / `"gift"` / `"checkin"` / ...）
    action_triggered = Signal(str)
    #: 鼠标进入菜单 —— `PetWindow` 用它取消收起宽限期
    menu_entered = Signal()
    #: 鼠标离开菜单 —— `PetWindow` 用它启动收起宽限期
    menu_left = Signal()

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.SubWindow
            | Qt.WindowDoesNotAcceptFocus      # ← 绝不抢焦点（与 BubblePanel 相反）
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._lang = "zh"
        self._items: list[str] = list(items) if items else list(DEFAULT_ITEMS)
        self._enabled: dict[str, bool] = {k: True for k in self._items}
        self._badges: dict[str, bool] = {k: False for k in self._items}
        self._button_size = 44
        self._orientation = "h"
        self._button_rects: dict[str, QRect] = {}
        self._pill_rect = QRect()
        self._hovered_key: str | None = None
        self._pressed_key: str | None = None
        self._tooltip_opacity = 0.0
        self._tooltip_side = TOOLTIP_SIDE  # 提示条在胶囊的哪一侧（恒定背离人物）

        self._tooltip_anim = QPropertyAnimation(self, b"tooltipOpacity", self)
        self._tooltip_anim.setDuration(TOOLTIP_FADE_MS)
        self._tooltip_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._show_anim: QPropertyAnimation | None = None
        self._relayout()

    # ────────────────── 对外配置 ──────────────────

    def apply_language(self, lang: str) -> None:
        self._lang = lang if lang in ("zh", "en", "ja") else "zh"
        self.update()

    def set_items(self, items) -> None:
        """调整显示的按钮与顺序（按好感度解锁动态增减时用）。"""
        keys = [str(k) for k in (items or ())]
        if not keys:
            keys = list(DEFAULT_ITEMS)
        self._items = keys
        for key in keys:
            self._enabled.setdefault(key, True)
            self._badges.setdefault(key, False)
        self._hovered_key = None
        self._relayout()
        self.update()

    def set_enabled_map(self, mapping) -> None:
        """设置各按钮的可用状态。**不可用项置灰但仍可点击**（点击后出说明气泡）。"""
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            if key in self._enabled:
                self._enabled[key] = bool(value)
        self.update()

    def set_badge(self, key: str, on: bool) -> None:
        """显示/隐藏红点角标（签到未签时用）。"""
        if key in self._badges:
            self._badges[key] = bool(on)
            self.update()

    def item_keys(self) -> list[str]:
        return list(self._items)

    def is_enabled(self, key: str) -> bool:
        return bool(self._enabled.get(key, True))

    def label_of(self, key: str) -> str:
        entry = LABELS.get(key) or {}
        return str(entry.get(self._lang) or entry.get("zh") or key)

    def button_size(self) -> int:
        return self._button_size

    def orientation(self) -> str:
        return self._orientation

    def button_rect(self, key: str) -> QRect:
        """按钮在本组件坐标系内的矩形（测试与预览用）。"""
        return QRect(self._button_rects.get(key, QRect()))

    def pill_rect(self) -> QRect:
        return QRect(self._pill_rect)

    # ────────────────── 布局 ──────────────────

    def set_button_size(self, size: int) -> None:
        size = max(MIN_BUTTON, min(MAX_BUTTON, int(size)))
        if size != self._button_size:
            self._button_size = size
            self._relayout()

    def set_orientation(self, orientation: str) -> None:
        orientation = "v" if str(orientation) == "v" else "h"
        if orientation != self._orientation:
            self._orientation = orientation
            self._relayout()

    def set_tooltip_side(self, side: str) -> None:
        """提示条放在胶囊的上方还是下方。

        **只认 `"top"` / `"bottom"`，其他值一律忽略**（不是回退到某一侧）：
        传错值时保持原样，好过悄悄把提示条翻到人物那一侧、连带着窗口压住她。
        """
        if side not in ("top", "bottom"):
            return
        if side != self._tooltip_side:
            self._tooltip_side = side
            self._relayout()

    def tooltip_side(self) -> str:
        return self._tooltip_side

    def _relayout(self) -> None:
        """按当前按钮尺寸、排列方向与提示条朝向重算几何。

        窗口尺寸与提示条朝向**无关**（两侧预留带宽之和固定），只有胶囊的纵向位置会变——
        这样 `plan_placement()` 里"先定朝向、再算落位"的先后顺序就不影响窗口大小。
        """
        count = max(1, len(self._items))
        d = self._button_size
        if self._orientation == "v":
            inner_w = d
            inner_h = count * d + (count - 1) * GAP
        else:
            inner_w = count * d + (count - 1) * GAP
            inner_h = d

        pill_y = MARGIN if self._tooltip_side == "bottom" else MARGIN + TOOLTIP_H
        self._pill_rect = QRect(MARGIN, pill_y, inner_w + PAD * 2, inner_h + PAD * 2)
        self.setFixedSize(self._pill_rect.width() + MARGIN * 2,
                          self._pill_rect.height() + MARGIN * 2 + TOOLTIP_H)

        self._button_rects = {}
        for index, key in enumerate(self._items):
            if self._orientation == "v":
                x = self._pill_rect.x() + PAD
                y = self._pill_rect.y() + PAD + index * (d + GAP)
            else:
                x = self._pill_rect.x() + PAD + index * (d + GAP)
                y = self._pill_rect.y() + PAD
            self._button_rects[key] = QRect(x, y, d, d)

    # ────────────────── 弹出 / 收起 ──────────────────

    def popup_near(self, pet_geometry, pet_height: int = 500) -> None:
        """贴在人物**下方**弹出（落位见 `plan_placement()`）。

        `pet_geometry` 是人物窗口的全局几何矩形（`PetWindow.frameGeometry()`）。
        """
        app = QApplication.instance()
        if app is None:
            return
        screen = app.screenAt(pet_geometry.center()) or app.primaryScreen()
        if screen is None:
            return
        _orientation, rect = self.plan_placement(
            pet_geometry, screen.availableGeometry(), pet_height)

        self._hovered_key = None
        self._pressed_key = None
        self._tooltip_opacity = 0.0
        self._animate_in(rect.topLeft())
        # 不调 activateWindow()：菜单不该抢走用户当前的输入焦点
        _force_raise_topmost(self)

    def plan_placement(self, pet_geometry, screen_geometry, pet_height: int | None = None):
        """**纯几何**：菜单恒定贴人物**下方**、水平居中对齐，返回 `(orientation, QRect)`。

        落位（规范 5.1 第二次修订：取消"上方优先 + 上下左右逐级兜底"）：

        1. 纵向：贴在人物下方，间距恒为 `GAP_FROM_PET`（从**胶囊顶边**量到人物底边）
        2. 水平：与人物水平居中；左右越界即夹紧
        3. 排列方向：横排；横排比整块屏幕还宽（极窄屏）才转竖排
        4. 兜底：整体夹紧进屏幕可用区

        **第 4 步的代价**：人物沉到屏幕底部时，菜单会被屏幕底边顶上去、压在她下半身上。
        这是"恒定下方"的必然结果，取舍是：遮住她还能把她拖上来，掉到屏幕外就是彻底点不到了。

        刻意与 `show()` / 动画分离 —— 动画一跑位置就在动，位置断言会变得不可靠，
        而「菜单会不会跑到屏幕外」这类问题，恰恰是这个组件最需要自动化验证的地方。
        副作用只有 `self._orientation` / `self._tooltip_side` 与窗口尺寸。
        """
        if pet_height is not None:
            self.set_button_size(button_size_for(pet_height))

        geom = screen_geometry
        # 排列方向：横排放不进屏幕宽才转竖排（竖排宽 72px，几乎任何屏幕都放得下）
        self.set_orientation("h")
        if self.width() > geom.width():
            self.set_orientation("v")

        # 朝向必须先于落位定下来：提示条预留带在胶囊下方时，胶囊在窗口内偏上 `TOOLTIP_H`，
        # `_below_y()` 正是按这个口径算的；先算 y 再翻朝向会差整整一个 TOOLTIP_H
        self.set_tooltip_side(TOOLTIP_SIDE)

        y = self._below_y(pet_geometry)
        # `(size - 1) // 2` 而不是 `size // 2`：QRect.center() 的整数除法口径如此，
        # 用后者在尺寸为偶数时会让菜单比人物偏 1px
        x = pet_geometry.center().x() - (self.width() - 1) // 2

        x = max(geom.left(), min(int(x), geom.right() - self.width() + 1))
        y = max(geom.top(), min(int(y), geom.bottom() - self.height() + 1))
        return self._orientation, QRect(x, y, self.width(), self.height())

    def _below_y(self, pet_geometry) -> int:
        """菜单在人物下方时，窗口顶边的 y。

        提示条预留带在胶囊**下方**，所以窗口顶边就是胶囊顶边再往上 `MARGIN`；
        间距要从**胶囊顶边**量到人物底边，因此减掉 `MARGIN`。
        """
        return pet_geometry.bottom() + 1 + GAP_FROM_PET - MARGIN

    def _popup_offset(self) -> QPoint:
        """弹出/收起时沿**背离人物**方向滑动的位移向量。

        菜单恒定在人物下方、提示条也恒定朝下，所以恒定是 `(0, +DRAG_OUT_OFFSET)`：
        弹出时从下方 12px 处滑上来（像是从她脚边冒出来），收起时原路缩回去。
        """
        return QPoint(0, DRAG_OUT_OFFSET)

    def _animate_in(self, target: QPoint) -> None:
        start = target + self._popup_offset()   # 从背离人物的那一侧滑回来
        self._stop_anim()
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        self._run_anim(start, target, 0.0, 1.0, SHOW_MS, QEasingCurve.OutCubic)

    def hide_with_anim(self) -> None:
        """收起。已隐藏时是空操作（`PetWindow` 的宽限期可能重复调用）。"""
        if not self.isVisible():
            return
        end = self.pos() + self._popup_offset()  # 沿背离人物的方向滑出
        self._run_anim(self.pos(), end, self.windowOpacity(), 0.0, HIDE_MS,
                       QEasingCurve.InCubic, hide_after=True)

    def hide_now(self) -> None:
        """立刻隐藏，无动画（切角色/退出等场景用）。"""
        self._stop_anim()
        self._hovered_key = None
        self._pressed_key = None
        self.hide()
        self.setWindowOpacity(1.0)

    def _run_anim(self, start: QPoint, end: QPoint, from_op: float, to_op: float,
                  duration: int, curve, hide_after: bool = False) -> None:
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

        from PySide6.QtCore import QParallelAnimationGroup
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
        self._hovered_key = None
        self._pressed_key = None

    def _stop_anim(self) -> None:
        group = getattr(self, "_show_anim", None)
        if group is not None:
            try:
                group.stop()
            except RuntimeError:
                pass
            self._show_anim = None

    def under_mouse(self) -> bool:
        """鼠标此刻是否在菜单窗口内。宽限期到期时用它做最后一次判断。"""
        if not self.isVisible():
            return False
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    # ────────────────── 鼠标事件 ──────────────────

    def _key_at(self, pos: QPoint) -> str | None:
        for key, rect in self._button_rects.items():
            if rect.contains(pos):
                return key
        return None

    def enterEvent(self, event):
        self.menu_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered_key = None
        self._pressed_key = None
        self._fade_tooltip(0.0)
        self.update()
        self.menu_left.emit()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        key = self._key_at(event.position().toPoint())
        if key != self._hovered_key:
            self._hovered_key = key
            self._fade_tooltip(1.0 if key else 0.0)
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed_key = self._key_at(event.position().toPoint())
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed = self._pressed_key
        self._pressed_key = None
        key = self._key_at(event.position().toPoint())
        self.update()
        # 不可用项也要发出信号：`NurtureController` 会用一句气泡说明原因，
        # 比 setEnabled(False) 那种"点了没反应"友好得多（规范 5.1）
        if event.button() == Qt.LeftButton and key and key == pressed:
            self.action_triggered.emit(key)
        super().mouseReleaseEvent(event)

    # 不实现 focusOutEvent —— 见模块文档

    # ────────────────── 提示条淡入淡出 ──────────────────

    def _get_tooltip_opacity(self) -> float:
        return self._tooltip_opacity

    def _set_tooltip_opacity(self, value: float) -> None:
        self._tooltip_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    tooltipOpacity = Property(float, _get_tooltip_opacity, _set_tooltip_opacity)

    def _fade_tooltip(self, target: float) -> None:
        self._tooltip_anim.stop()
        self._tooltip_anim.setStartValue(self._tooltip_opacity)
        self._tooltip_anim.setEndValue(float(target))
        self._tooltip_anim.start()

    # ────────────────── 绘制 ──────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint_pill(painter)
            for key, rect in self._button_rects.items():
                self._paint_button(painter, key, rect)
            self._paint_tooltip(painter)
        finally:
            painter.end()

    def _pill_path(self) -> QPainterPath:
        path = QPainterPath()
        radius = self._pill_rect.height() / 2.0
        path.addRoundedRect(self._pill_rect, radius, radius)
        return path

    def _paint_pill(self, painter: QPainter) -> None:
        # 柔和暖投影：用几层递减透明度的圆角矩形伪造（QPainter 没有模糊）
        for step in range(MARGIN, 0, -1):
            alpha = int(16 / step)
            if alpha <= 0:
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*SHADOW_RGB, alpha))
            radius = self._pill_rect.height() / 2.0 + step
            painter.drawRoundedRect(
                self._pill_rect.adjusted(-step, -step, step, step), radius, radius)

        painter.setBrush(QColor(255, 249, 246, 240))     # 暖奶白胶囊底
        pen = QPen(QColor(OUTLINE))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(self._pill_path())

    def _paint_button(self, painter: QPainter, key: str, rect: QRect) -> None:
        enabled = self._enabled.get(key, True)
        hovered = (key == self._hovered_key) and enabled
        pressed = (key == self._pressed_key) and enabled

        if hovered and not pressed:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 183, 197, 128))   # 3px 光圈
            painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))

        dy = 1 if pressed else (-1 if hovered else 0)
        scale = 1.04 if hovered else 1.0
        radius = rect.width() / 2.0 * scale
        center = rect.center() + QPoint(0, dy)

        if not enabled:
            fill, stroke = "#F7F2F0", OUTLINE_LIGHT
        elif pressed:
            fill, stroke = PINK_DEEP, PINK_DEEP
        elif hovered:
            fill, stroke = PINK_LIGHT, PINK_DEEP
        else:
            fill, stroke = CREAM_DEEP, OUTLINE

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawEllipse(center, radius, radius)
        pen = QPen(QColor(stroke))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)

        # 图标（带上 dpr：图标模块按物理像素渲染，150% 缩放下才不会糊；
        # dpr=1.0 的机器上输出与不传完全一致，观感不变）
        icon = icons.pixmap(key, ICON_SIZE, dpr=self.devicePixelRatioF())
        target = QRect(0, 0, ICON_SIZE, ICON_SIZE)
        target.moveCenter(center)
        painter.setOpacity(1.0 if enabled else 0.45)
        painter.drawPixmap(target, icon, QRect(icon.rect()))
        painter.setOpacity(1.0)

        if self._badges.get(key):
            self._paint_badge(painter, center, radius)

    def _paint_badge(self, painter: QPainter, center: QPoint, radius: float) -> None:
        """红点角标：直径 9px，位于按钮右上角外侧，带 1.5px 奶白描边。"""
        offset = radius * 0.72
        spot = QPoint(int(center.x() + offset), int(center.y() - offset))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CREAM))
        painter.drawEllipse(spot, 6.0, 6.0)
        painter.setBrush(QColor(RED))
        painter.drawEllipse(spot, 4.5, 4.5)

    def tooltip_rect(self) -> QRect:
        """提示条矩形。绘制与测试共用一份计算，免得两处各算一遍还算岔了。

        纵向随 `_tooltip_side` 翻转（永远背离人物），与胶囊的间距恒为 `TOOLTIP_GAP`；
        横向以悬停按钮为中心，并夹紧在窗口内。
        """
        text = self.label_of(self._hovered_key or "")
        font = QFont("Microsoft YaHei")
        font.setPixelSize(13)
        height = TOOLTIP_H - 4
        width = min(self.width() - MARGIN * 2,
                    QFontMetrics(font).horizontalAdvance(text) + 20)
        anchor = self._button_rects.get(self._hovered_key)
        x = anchor.center().x() - width // 2 if anchor else MARGIN
        x = max(MARGIN, min(x, self.width() - MARGIN - width))
        if self._tooltip_side == "bottom":
            y = self._pill_rect.bottom() + 1 + TOOLTIP_GAP
        else:
            y = self._pill_rect.top() - TOOLTIP_GAP - height
        return QRect(x, y, width, height)

    def _paint_tooltip(self, painter: QPainter) -> None:
        if self._tooltip_opacity <= 0.01 or not self._hovered_key:
            return
        text = self.label_of(self._hovered_key)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(13)
        painter.setFont(font)
        rect = self.tooltip_rect()
        height = rect.height()

        painter.setOpacity(self._tooltip_opacity)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CREAM))
        radius = height / 2.0
        painter.drawRoundedRect(rect, radius, radius)
        pen = QPen(QColor(OUTLINE))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QPen(QColor(TEXT)))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.setOpacity(1.0)


# ────────────────────────── 自检预览 ──────────────────────────


def render_preview(path: str) -> None:
    """把菜单的几种状态渲染到一张图（人工验收用，见 04 文档阶段 C 验证）。"""
    from PySide6.QtGui import QPixmap

    states = [
        ("horizontal / normal", "h", None, False),
        ("horizontal / hover feed", "h", "feed", False),
        ("horizontal / 签到红点+送礼置灰", "h", None, True),
        ("vertical", "v", "heart", False),
    ]
    shots = []
    for _label, orientation, hovered, disabled_demo in states:
        menu = HoverMenu()
        menu.set_button_size(44)
        menu.set_orientation(orientation)
        if disabled_demo:
            menu.set_badge("checkin", True)
            menu.set_enabled_map({"gift": False, "headpat": False})
        if hovered:
            menu._hovered_key = hovered        # noqa: SLF001 - 预览专用
            menu._tooltip_opacity = 1.0        # noqa: SLF001
        menu.ensurePolished()
        shots.append((_label, menu.grab()))

    pad, label_h = 12, 18
    width = max(s.width() for _, s in shots) + pad * 2
    height = sum(s.height() + label_h + pad for _, s in shots) + pad
    sheet = QPixmap(width, height)
    sheet.fill(QColor(icons.CREAM_DEEP))
    painter = QPainter(sheet)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(11)
        painter.setFont(font)
        y = pad
        for label, shot in shots:
            painter.setPen(QPen(QColor(TEXT)))
            painter.drawText(QRect(pad, y, width - pad * 2, label_h),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            y += label_h
            painter.drawPixmap(pad, y, shot)
            y += shot.height() + pad
    finally:
        painter.end()
    sheet.save(path)
    print(f"hover menu preview -> {path}  ({sheet.width()}x{sheet.height()})")


def _main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([])   # noqa: F841
    out = argv[1] if len(argv) > 1 else "_hover_menu_preview.png"
    render_preview(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
