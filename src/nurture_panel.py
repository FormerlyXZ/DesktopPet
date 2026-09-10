"""养成面板 `NurturePanel` —— 三页（食物 / 礼物 / 状态）的暖粉奶白卡片面板。

对应需求：`docs/nurture/01-需求规格.md` 第 6 节；对应规范：`03-设计规范.md` 5.2 / 5.4。

**全自绘，不用 QSS**（规范 5.2 明确要求）：手绘感来自 2px 暖棕描边 + 平涂色块 + 柔和投影，
QSS 做不出圆角描边加角标，硬拼出来会是"系统控件刷了层粉漆"，与作品气质不符。
所以卡片、页签、关闭按钮、心形进度条全部在 `paintEvent` 里画，命中测试自己算
（`card_rect()` / `tab_rect()` / `close_rect()` / `item_at()` / `tab_at()`），
与 `HoverMenu` 同一套路数 —— 这样几何与命中都是**纯函数**，可以直接单测。

与 `HoverMenu` 一致的三条硬约束（照抄 `BubblePanel` 必然做废）：

| | `BubblePanel`（现有菜单） | `NurturePanel`（本组件） |
|---|---|---|
| 焦点 | `raise_()` + `activateWindow()` | **`WindowDoesNotAcceptFocus`，绝不 `activateWindow()`** |
| 收起 | `focusOutEvent` 里自动收起 | **不实现 `focusOutEvent`**，由 `PetWindow` 仲裁器收起 |
| 位置 | 贴人物右侧 | **贴人物左侧**（规范第 7 节优先级表第 4 行），左侧不足翻右 |

> 为什么不实现 `focusOutEvent`：面板根本不拿焦点，那个事件永远不会触发；
> 而一旦它以别的方式触发，用户还没点到卡片面板就自己关了。

**落位间距从"背景边缘"量起**（不是窗口边缘）：窗口四边留了 6px 给投影，
拿窗口边缘去量会凭空多出 6px 的空隙，看起来像面板没贴住人物。

自检预览：`python -m src.nurture_panel [输出路径.png]`
"""

from __future__ import annotations

import math
import os
import sys

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from src import nurture_icons as icons
from src import nurture_model as model
from src.bubble_panel import _force_raise_topmost

# ────────────────────────── 规格常量（对应 03-设计规范 5.2 / 5.4）──────────────────────────

CREAM = icons.CREAM                 # #FFF9F6 面板底
CREAM_DEEP = icons.CREAM_DEEP       # #FFF1EC 信息条底 / 轨道
CARD = icons.CARD                   # #FFFFFF 卡片底
OUTLINE = icons.OUTLINE             # #8D6E63 暖棕描边
OUTLINE_LIGHT = icons.OUTLINE_LIGHT  # #C9AFA6 次级描边
PINK = icons.PINK                   # #FFB7C5
PINK_DEEP = icons.PINK_DEEP         # #F49AB0 hover / 角标
PINK_LIGHT = icons.PINK_LIGHT       # #FFE3E9 选中态底
NAVY = icons.NAVY                   # #2E4A7D 标题（藏青）
RED = icons.RED                     # #E5484D 数值 / 红点
HEART_PINK = icons.HEART_PINK       # #FF8FA3 心形进度条填充
TEXT = icons.TEXT                   # #5B4A46
TEXT_DIM = icons.TEXT_DIM           # #9E8B86
SHADOW_RGB = (141, 110, 99)         # 暖色投影基色

WIDTH = 268          # 面板内容宽（规范 5.2 固定值）
MARGIN = 6           # 窗口四边留给投影的空间
PAD = 14             # 内容内边距
HEADER_H = 34        # 信息条高
CLOSE_D = 28         # 关闭按钮直径
ICON_SIZE = 28       # 卡片图标
CARD_W = 74          # 卡片宽（见下方"三列装不下"的说明）
CARD_H = 92          # 卡片高
GRID_GAP = 8         # 格距
COLS = 3             # 网格列数
TAB_H = 30           # 页签高
TAB_GAP = 6          # 页签间距
GAP_FROM_PET = 8     # 与人物窗口的间距
DRAG_OUT_OFFSET = 16  # 弹出/收起位移（规范第 6 节：面板用 16px，菜单用 12px）
SHOW_MS = 220
HIDE_MS = 180
HEART_MS = 600       # 心形进度条补间（规范 5.4）
EMPTY_STOCK_ALPHA = 0.45

#: 页签。`status` 不是物品页，只是第三页的名字
TABS: tuple[str, ...] = ("food", "gift", "status")

#: 页签文案。**阶段 H 会整体搬进 `src/translations.py`**（与 `hover_menu.LABELS` 一起）
TAB_LABELS: dict[str, dict[str, str]] = {
    "food":   {"zh": "食物", "en": "Food",   "ja": "たべもの"},
    "gift":   {"zh": "礼物", "en": "Gifts",  "ja": "プレゼント"},
    "status": {"zh": "状态", "en": "Status", "ja": "ステータス"},
}

#: 状态页那几行的文案。同上，阶段 H 统一搬迁
STATUS_LABELS: dict[str, dict[str, str]] = {
    "streak":  {"zh": "连签",       "en": "Streak",     "ja": "連続"},
    "next":    {"zh": "下一称号",   "en": "Next title", "ja": "次の称号"},
    "gained":  {"zh": "今日好感度", "en": "Affection today", "ja": "今日の好感度"},
    "gifts":   {"zh": "今日送礼",   "en": "Gifts today", "ja": "今日のプレゼント"},
    "empty":   {"zh": "还没有可以送的东西", "en": "Nothing to give yet",
                "ja": "まだ渡せるものがない"},
}


def _label(table: dict, key: str, lang: str) -> str:
    entry = table.get(key) or {}
    return str(entry.get(lang) or entry.get("zh") or key)


def _elide(text: str, font: QFont, width: int) -> str:
    """按像素宽度省略。**不能用 `len(text)` 估算**：中日文与拉丁字母宽度差一倍。"""
    metrics = QFontMetrics(font)
    return metrics.elidedText(str(text), Qt.ElideRight, max(1, int(width)))


class NurturePanel(QWidget):
    """三页卡片面板。只负责"显示 + 报告点击"，所有业务判断都在 `NurtureController`。"""

    #: 点了某个物品（传物品名）。**库存 0 也照发** —— 由 controller 出说明气泡
    item_chosen = Signal(str)
    #: 切换了页签（`"food"` / `"gift"` / `"status"`）
    tab_changed = Signal(str)
    #: 点了右上角关闭按钮。面板自己不隐藏，由 `NurtureController` 决定
    close_clicked = Signal()

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.SubWindow
            | Qt.WindowDoesNotAcceptFocus      # ← 绝不抢焦点（红线）
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._lang = "zh"
        self._items: list[dict] = []
        self._inventory: dict[str, int] = {}
        self._tab = "food"
        self._hovered_card: int | None = None
        self._pressed_card: int | None = None
        self._hovered_tab: str | None = None
        self._hovered_close = False
        self._rows = 1

        self._affection = 0
        self._soft_cap = model.SOFT_AFFECTION_CAP
        self._streak = 0
        self._levels: list = []
        self._gained_today = 0
        self._daily_cap = 0
        self._gifts_today = 0
        self._gift_cap = 0

        self._heart_value = 0.0        # 屏幕上真正画出来的比例（可能正被补间）
        self._heart_target = 0.0       # 目标比例（测试断言这个，别断言补间中间态）
        self._heart_anim = QPropertyAnimation(self, b"heartFill", self)
        self._heart_anim.setDuration(HEART_MS)
        self._heart_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._popup_direction = "left"
        self._show_anim = None

        self._card_rects: list[QRect] = []
        self._tab_rects: dict[str, QRect] = {}
        self._header_rect = QRect()
        self._close_rect = QRect()

        self.set_items(items or [])
        self._relayout()

    # ────────────────── 对外配置 ──────────────────

    def apply_language(self, lang: str) -> None:
        self._lang = lang if lang in ("zh", "en", "ja") else "zh"
        self.update()

    def set_items(self, items) -> None:
        """设置可送出物清单（`items.json` 的 `items` 数组）。

        脏值一律丢掉而不是崩：`items.json` 是**用户可编辑**的，
        少一个 `name` 或 `name` 写成数字都不该让面板打不开。
        """
        cleaned: list[dict] = []
        for raw in items if isinstance(items, (list, tuple)) else ():
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                continue          # 没有名字的条目无法显示也无法送出，直接丢
            entry = dict(raw)
            entry["name"] = name.strip()
            if entry.get("kind") not in ("food", "gift"):
                entry["kind"] = "food"
            cleaned.append(entry)
        self._items = cleaned

        # 面板高度按"行数最多的那一页"算，切页签时高度不变（否则面板会跳一下）
        self._rows = max(1, max(
            (math.ceil(len(self.items_of(tab)) / COLS) for tab in TABS), default=1))
        self._relayout()
        self.update()

    def items(self) -> list[dict]:
        return [dict(item) for item in self._items]

    def items_of(self, tab: str) -> list[dict]:
        kind = "gift" if tab == "gift" else "food"
        if tab == "status":
            return []
        return [dict(item) for item in self._items if item.get("kind") == kind]

    def set_inventory(self, mapping) -> None:
        """设置库存（`{物品名: 数量}`）。脏值降级成 0。"""
        if not isinstance(mapping, dict):
            return
        self._inventory = {str(k): model.safe_int(v) for k, v in mapping.items()}
        self.update()

    def count_of(self, name: str) -> int:
        return max(0, model.safe_int(self._inventory.get(str(name), 0)))

    def set_affection(self, value: int, soft_cap: int | None = None) -> None:
        """设置好感度。进度条按规范 5.4 用 600ms 补间，**不瞬移**。

        注意：`heart_ratio()` 是补间中的显示值，测试请断言 `heart_target()`，
        否则会遇到"动画还没跑完"的随机失败（与 `hide_with_anim()` 同一个坑）。
        """
        if soft_cap is not None:
            cap = model.safe_int(soft_cap)
            self._soft_cap = cap if cap > 0 else model.SOFT_AFFECTION_CAP
        self._affection = max(0, model.safe_int(value))
        self._heart_target = model.affection_ratio(self._affection, self._soft_cap)
        self._heart_anim.stop()
        self._heart_anim.setStartValue(self._heart_value)
        self._heart_anim.setEndValue(self._heart_target)
        self._heart_anim.start()
        self.update()

    def set_soft_cap(self, value: int) -> None:
        self._soft_cap = max(1, model.safe_int(value))
        self._heart_target = model.affection_ratio(self._affection, self._soft_cap)
        self._heart_value = self._heart_target
        self.update()

    def set_streak(self, days: int) -> None:
        self._streak = max(0, model.safe_int(days))
        self.update()

    def set_levels(self, levels) -> None:
        """设置等级表（`levels.json` 的 `levels` 数组），用于状态页的称号。"""
        self._levels = list(levels) if isinstance(levels, (list, tuple)) else []
        self.update()

    def set_today(self, *, gained: int = 0, cap: int = 0,
                  gifts: int = 0, gift_cap: int = 0) -> None:
        """设置"今日已获好感度 / 上限"与"今日送礼数 / 上限"（状态页用）。"""
        self._gained_today = max(0, model.safe_int(gained))
        self._daily_cap = max(0, model.safe_int(cap))
        self._gifts_today = max(0, model.safe_int(gifts))
        self._gift_cap = max(0, model.safe_int(gift_cap))
        self.update()

    def set_tab(self, tab: str) -> None:
        tab = str(tab)
        if tab not in TABS:
            tab = "food"
        if tab != self._tab:
            self._tab = tab
            self._hovered_card = None
            self._pressed_card = None
            self._relayout()
            self.tab_changed.emit(tab)
        self.update()

    def tab(self) -> str:
        return self._tab

    def affection(self) -> int:
        return self._affection

    def level_title(self) -> str:
        """当前称号（状态页显示，也用于气泡文案）。"""
        return str(model.level_info(self._affection, self._levels).get("title", ""))

    def next_level_title(self) -> str:
        return str(model.level_info(self._affection, self._levels).get("next_title", ""))

    def _next_level_text(self) -> str:
        """状态页"下一称号"那一行的右半边文案。"""
        info = model.level_info(self._affection, self._levels)
        if info.get("is_max"):
            return "—"
        gap = max(0, model.safe_int(info.get("next_threshold")) - self._affection)
        return f"{info.get('next_title', '')} · 还差 {gap}"

    def _level_progress(self) -> float | None:
        """当前等级内的进度（0~1）。已满级返回 1.0，没有下一级返回 None。"""
        info = model.level_info(self._affection, self._levels)
        if info.get("is_max"):
            return 1.0
        lo = model.safe_int(info.get("threshold"))
        hi = model.safe_int(info.get("next_threshold"))
        if hi <= lo:
            return None
        return max(0.0, min(1.0, (self._affection - lo) / (hi - lo)))

    # ────────────────── 几何 ──────────────────

    def _panel_rect(self) -> QRect:
        """背景（可见的圆角矩形）在窗口内的矩形。**落位与命中都以它为准。**"""
        return QRect(MARGIN, MARGIN, WIDTH, self.height() - MARGIN * 2)

    def _content_rows(self) -> int:
        return self._rows

    def content_height(self) -> int:
        """窗口高度：按行数最多的那一页算，切页签时不跳动。"""
        grid = self._content_rows() * (CARD_H + GRID_GAP) - GRID_GAP
        return MARGIN * 2 + PAD + HEADER_H + 10 + grid + 10 + TAB_H + PAD

    def _relayout(self) -> None:
        """重算窗口尺寸与所有命中矩形（纯几何，可单测）。"""
        height = self.content_height()
        self.setFixedSize(WIDTH + MARGIN * 2, height)
        bg = self._panel_rect()

        self._header_rect = QRect(bg.x() + PAD, bg.y() + PAD,
                                  bg.width() - PAD * 2, HEADER_H)
        self._close_rect = QRect(self._header_rect.right() - CLOSE_D + 1,
                                 self._header_rect.y() + (HEADER_H - CLOSE_D) // 2,
                                 CLOSE_D, CLOSE_D)

        x0 = bg.x() + PAD
        y0 = self._header_rect.bottom() + 1 + 10
        self._card_rects = []
        for index in range(len(self.items_of(self._tab))):
            row, col = divmod(index, COLS)
            self._card_rects.append(QRect(
                x0 + col * (CARD_W + GRID_GAP),
                y0 + row * (CARD_H + GRID_GAP),
                CARD_W, CARD_H))

        tab_w = (bg.width() - PAD * 2 - TAB_GAP * (len(TABS) - 1)) // len(TABS)
        tab_y = bg.bottom() + 1 - PAD - TAB_H
        self._tab_rects = {}
        for index, key in enumerate(TABS):
            self._tab_rects[key] = QRect(x0 + index * (tab_w + TAB_GAP), tab_y,
                                         tab_w, TAB_H)

    def card_rect(self, index: int) -> QRect:
        """第 `index` 张卡片的矩形（当前页）。越界返回空矩形。"""
        index = model.safe_int(index)
        if 0 <= index < len(self._card_rects):
            return QRect(self._card_rects[index])
        return QRect()

    def card_rect_for(self, name: str) -> QRect:
        for index, item in enumerate(self.items_of(self._tab)):
            if item.get("name") == name:
                return self.card_rect(index)
        return QRect()

    def tab_rect(self, key: str) -> QRect:
        return QRect(self._tab_rects.get(str(key), QRect()))

    def close_rect(self) -> QRect:
        return QRect(self._close_rect)

    def header_rect(self) -> QRect:
        return QRect(self._header_rect)

    def item_at(self, pos: QPoint):
        """命中测试：返回被点到的物品 dict（不是下标），没命中返回 `None`。"""
        for index, item in enumerate(self.items_of(self._tab)):
            if self.card_rect(index).contains(pos):
                return item
        return None

    def tab_at(self, pos: QPoint):
        """命中测试：返回被点到的页签名，没命中返回 `None`。"""
        for key in TABS:
            if self.tab_rect(key).contains(pos):
                return key
        return None

    # ────────────────── 心形进度条 ──────────────────

    def _get_heart_fill(self) -> float:
        return self._heart_value

    def _set_heart_fill(self, value) -> None:
        try:
            self._heart_value = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._heart_value = 0.0
        self.update()

    heartFill = Property(float, _get_heart_fill, _set_heart_fill)

    def heart_ratio(self) -> float:
        """**显示中**的比例（补间中间态）。"""
        return self._heart_value

    def heart_target(self) -> float:
        """目标比例。测试断言这个。"""
        return self._heart_target

    # ────────────────── 弹出 / 收起 ──────────────────

    def plan_placement(self, pet_geometry, screen_geometry):
        """**纯几何**：贴人物**左侧**、垂直居中；左侧放不下 → 翻右；仍放不下 → 夹紧。

        间距从**背景边缘**量到人物边缘：窗口左边留了 `MARGIN` 给投影，
        直接用窗口左边去对会让面板与人物之间凭空多出 6px。
        返回 `(direction, QRect)`。
        """
        geom = screen_geometry
        width, height = self.width(), self.height()

        left_x = pet_geometry.left() - GAP_FROM_PET - width + MARGIN
        if left_x + MARGIN >= geom.left():
            direction, x = "left", left_x
        else:
            right_x = pet_geometry.right() + 1 + GAP_FROM_PET - MARGIN
            if right_x + width - MARGIN <= geom.right() + 1:
                direction, x = "right", right_x
            else:
                direction, x = "left", left_x      # 两侧都放不下 → 交给夹紧

        y = pet_geometry.center().y() - (height - 1) // 2
        x = max(geom.left(), min(int(x), geom.right() - width + 1))
        y = max(geom.top(), min(int(y), geom.bottom() - height + 1))
        self._popup_direction = direction
        return direction, QRect(x, y, width, height)

    def popup_near(self, pet_geometry) -> None:
        """在人物旁边弹出。`pet_geometry` 是 `PetWindow.frameGeometry()`。"""
        app = QApplication.instance()
        if app is None:
            return
        screen = app.screenAt(pet_geometry.center()) or app.primaryScreen()
        if screen is None:
            return
        _direction, rect = self.plan_placement(pet_geometry, screen.availableGeometry())
        self._hovered_card = None
        self._pressed_card = None
        self._hovered_close = False
        self._animate_in(rect.topLeft())
        # 不调 activateWindow()：面板不该抢走用户当前的输入焦点
        _force_raise_topmost(self)

    def _popup_offset(self) -> QPoint:
        """弹出/收起时沿**背离人物**方向滑动的位移向量。"""
        if self._popup_direction == "right":
            return QPoint(DRAG_OUT_OFFSET, 0)
        return QPoint(-DRAG_OUT_OFFSET, 0)

    def _animate_in(self, target: QPoint) -> None:
        start = target + self._popup_offset()
        self._stop_anim()
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        self._run_anim(start, target, 0.0, 1.0, SHOW_MS, QEasingCurve.OutCubic)

    def hide_with_anim(self) -> None:
        """收起。已隐藏时是空操作（仲裁器可能重复调用）。"""
        if not self.isVisible():
            return
        end = self.pos() + self._popup_offset()
        self._run_anim(self.pos(), end, self.windowOpacity(), 0.0, HIDE_MS,
                       QEasingCurve.InCubic, hide_after=True)

    def hide_now(self) -> None:
        """立刻隐藏，无动画（切角色/退出等场景用）。"""
        self._stop_anim()
        self._hovered_card = None
        self._pressed_card = None
        self.hide()
        self.setWindowOpacity(1.0)

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
        self._hovered_card = None
        self._pressed_card = None

    def _stop_anim(self) -> None:
        group = getattr(self, "_show_anim", None)
        if group is not None:
            try:
                group.stop()
            except RuntimeError:
                pass
            self._show_anim = None

    # ────────────────── 鼠标事件 ──────────────────

    def _card_index_at(self, pos: QPoint):
        for index in range(len(self._card_rects)):
            if self.card_rect(index).contains(pos):
                return index
        return None

    def leaveEvent(self, event):
        self._hovered_card = None
        self._pressed_card = None
        self._hovered_tab = None
        self._hovered_close = False
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        card = self._card_index_at(pos)
        tab = self.tab_at(pos)
        close = self.close_rect().contains(pos)
        if (card, tab, close) != (self._hovered_card, self._hovered_tab, self._hovered_close):
            self._hovered_card = card
            self._hovered_tab = tab
            self._hovered_close = close
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed_card = self._card_index_at(event.position().toPoint())
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        pressed = self._pressed_card
        self._pressed_card = None
        self.update()
        if event.button() == Qt.LeftButton:
            tab = self.tab_at(pos)
            if tab is not None:
                self.set_tab(tab)
            elif self.close_rect().contains(pos):
                self.close_clicked.emit()
            else:
                index = self._card_index_at(pos)
                # 按下与抬起必须在同一张卡片上，避免"拖过去松手"误触发
                # 库存 0 也要发信号：controller 会用一句气泡说明获取途径
                if index is not None and index == pressed:
                    item = self.item_at(pos)
                    if item is not None:
                        self.item_chosen.emit(str(item.get("name", "")))
        super().mouseReleaseEvent(event)

    # 不实现 focusOutEvent —— 见模块文档

    # ────────────────── 绘制 ──────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint_panel(painter)
            self._paint_header(painter)
            if self._tab == "status":
                self._paint_status(painter)
            else:
                self._paint_cards(painter)
                if not self.items_of(self._tab):
                    self._paint_empty(painter)
            self._paint_tabs(painter)
        finally:
            painter.end()

    def _paint_panel(self, painter: QPainter) -> None:
        rect = self._panel_rect()
        # 柔和暖投影：几层递减透明度的圆角矩形（QPainter 没有模糊）
        for step in range(MARGIN, 0, -1):
            alpha = int(18 / step)
            if alpha <= 0:
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*SHADOW_RGB, alpha))
            painter.drawRoundedRect(rect.adjusted(-step, -step + 1, step, step + 1), 20, 20)
        painter.setBrush(QColor(255, 249, 246, 242))
        painter.setPen(self._pen(OUTLINE, 2.0))
        painter.drawRoundedRect(rect, 20, 20)

    def _pen(self, color: str, width: float = 2.0) -> QPen:
        pen = QPen(QColor(color))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _paint_header(self, painter: QPainter) -> None:
        rect = self._header_rect
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CREAM_DEEP))
        painter.drawRoundedRect(rect, 12, 12)

        text_rect = QRect(rect.x() + 10, rect.y(), rect.width() - 10 - CLOSE_D - 6,
                          rect.height())
        font = QFont("Microsoft YaHei")
        font.setPixelSize(13)
        painter.setFont(font)
        x = text_rect.x()
        baseline_rect = QRect(x, text_rect.y(), text_rect.width(), text_rect.height())

        # ♥ 数值（红 bold 15）
        heart_font = QFont("Microsoft YaHei")
        heart_font.setPixelSize(15)
        heart_font.setBold(True)
        painter.setFont(heart_font)
        painter.setPen(QPen(QColor(RED)))
        heart_text = f"♥ {self._affection}"
        painter.drawText(baseline_rect, Qt.AlignLeft | Qt.AlignVCenter, heart_text)
        x += QFontMetrics(heart_font).horizontalAdvance(heart_text) + 8

        # 称号（藏青 bold 12）
        title_font = QFont("Microsoft YaHei")
        title_font.setPixelSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QPen(QColor(NAVY)))
        title = self.level_title()
        painter.drawText(QRect(x, text_rect.y(), text_rect.width(), text_rect.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, title)
        x += QFontMetrics(title_font).horizontalAdvance(title) + 10

        # 连签 + 今日进度（次要色）
        dim_font = QFont("Microsoft YaHei")
        dim_font.setPixelSize(11)
        painter.setFont(dim_font)
        painter.setPen(QPen(QColor(TEXT_DIM)))
        info = f"{_label(STATUS_LABELS, 'streak', self._lang)} {self._streak}"
        if self._daily_cap > 0:
            info += f"   +{self._gained_today}/{self._daily_cap}"
        rest = QRect(x, text_rect.y(), max(0, text_rect.right() - x + 1), text_rect.height())
        painter.drawText(rest, Qt.AlignLeft | Qt.AlignVCenter,
                         _elide(info, dim_font, rest.width()))

        self._paint_close(painter)

    def _paint_close(self, painter: QPainter) -> None:
        rect = self._close_rect
        hovered = self._hovered_close
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(PINK_LIGHT if hovered else CREAM))
        painter.drawEllipse(rect)
        painter.setPen(self._pen(OUTLINE, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)
        icon = icons.pixmap("close", 14, dpr=self.devicePixelRatioF())
        target = QRect(0, 0, 14, 14)
        target.moveCenter(rect.center())
        painter.drawPixmap(target, icon, QRect(icon.rect()))

    def _paint_cards(self, painter: QPainter) -> None:
        for index, item in enumerate(self.items_of(self._tab)):
            rect = self.card_rect(index)
            hovered = (index == self._hovered_card)
            pressed = (index == self._pressed_card)
            count = self.count_of(str(item.get("name", "")))
            empty = count <= 0

            if hovered:
                rect = rect.adjusted(0, -2, 0, -2)      # 上浮 2px
            if pressed:
                rect = rect.adjusted(0, 1, 0, 1)        # 下沉 1px

            painter.setOpacity(EMPTY_STOCK_ALPHA if empty else 1.0)

            # 投影 0/2/6
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*SHADOW_RGB, 26))
            painter.drawRoundedRect(rect.adjusted(1, 3, -1, 3), 14, 14)

            painter.setBrush(QColor(CREAM if hovered else CARD))
            painter.setPen(self._pen(PINK_DEEP if hovered else OUTLINE_LIGHT, 1.5))
            painter.drawRoundedRect(rect, 14, 14)

            # 带上 dpr：图标模块按物理像素渲染，150% 缩放下才不会糊
            # （dpr=1.0 的机器上输出与不传完全一致）
            icon = icons.pixmap_for_item(item, ICON_SIZE, dpr=self.devicePixelRatioF())
            target = QRect(0, 0, ICON_SIZE, ICON_SIZE)
            target.moveCenter(QPoint(rect.center().x(), rect.y() + 36))
            painter.drawPixmap(target, icon, QRect(icon.rect()))

            name_font = QFont("Microsoft YaHei")
            name_font.setPixelSize(11)
            painter.setFont(name_font)
            painter.setPen(QPen(QColor(TEXT)))
            name_rect = QRect(rect.x() + 4, rect.y() + 58, rect.width() - 8, 16)
            painter.drawText(name_rect, Qt.AlignCenter,
                             _elide(str(item.get("name", "")), name_font, name_rect.width()))

            self._paint_badge(painter, rect, count, empty)
            painter.setOpacity(1.0)

    def _paint_badge(self, painter: QPainter, card: QRect, count: int, empty: bool) -> None:
        """库存角标：直径 18px 正圆，卡片右上角内缩 4px。"""
        size = 18
        spot = QRect(card.right() - size - 4 + 1, card.y() + 4, size, size)
        painter.setPen(self._pen(CREAM, 1.5))
        painter.setBrush(QColor(OUTLINE_LIGHT if empty else PINK_DEEP))
        painter.drawEllipse(spot)
        painter.setPen(QPen(QColor("#FFFFFF")))
        font = QFont("Microsoft YaHei")
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(spot, Qt.AlignCenter, str(min(99, max(0, count))))

    def _paint_empty(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor(TEXT_DIM)))
        font = QFont("Microsoft YaHei")
        font.setPixelSize(12)
        painter.setFont(font)
        top = self._header_rect.bottom() + 1 + 10
        area = QRect(self._panel_rect().x() + PAD, top,
                     self._panel_rect().width() - PAD * 2,
                     self._content_rows() * (CARD_H + GRID_GAP) - GRID_GAP)
        painter.drawText(area, Qt.AlignCenter, _label(STATUS_LABELS, "empty", self._lang))

    def _paint_tabs(self, painter: QPainter) -> None:
        font = QFont("Microsoft YaHei")
        font.setPixelSize(12)
        for key in TABS:
            rect = self.tab_rect(key)
            selected = (key == self._tab)
            hovered = (key == self._hovered_tab) and not selected
            painter.setPen(Qt.NoPen)
            if selected:
                painter.setBrush(QColor(PINK_LIGHT))
                painter.drawRoundedRect(rect, 8, 8)
            elif hovered:
                painter.setBrush(QColor(CREAM_DEEP))
                painter.drawRoundedRect(rect, 8, 8)
            tab_font = QFont(font)
            tab_font.setBold(selected)
            painter.setFont(tab_font)
            painter.setPen(QPen(QColor(NAVY if selected else TEXT_DIM)))
            painter.drawText(rect, Qt.AlignCenter, _label(TAB_LABELS, key, self._lang))
            if selected:
                underline = QRect(rect.center().x() - 14, rect.bottom() - 4, 28, 3)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(PINK_DEEP))
                painter.drawRoundedRect(underline, 1.5, 1.5)

    def _paint_status(self, painter: QPainter) -> None:
        bg = self._panel_rect()
        left = bg.x() + PAD
        width = bg.width() - PAD * 2
        y = self._header_rect.bottom() + 1 + 14

        info = model.level_info(self._affection, self._levels)
        title_font = QFont("Microsoft YaHei")
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QPen(QColor(TEXT)))
        painter.drawText(QRect(left, y, width, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         f"♥ {self._affection} / {self._soft_cap}")
        next_title = str(info.get("next_title") or "")
        if next_title and not info.get("is_max"):
            painter.setPen(QPen(QColor(TEXT_DIM)))
            dim = QFont("Microsoft YaHei")
            dim.setPixelSize(11)
            painter.setFont(dim)
            painter.drawText(QRect(left, y, width, 18), Qt.AlignRight | Qt.AlignVCenter,
                             f"{info.get('title', '')} → {next_title}")
        y += 24

        self._paint_bar(painter, QRect(left, y, width, 10), self._heart_value, radius=5.0)
        y += 26

        rows = [
            (_label(STATUS_LABELS, "next", self._lang), self._next_level_text(),
             self._level_progress()),
            (_label(STATUS_LABELS, "streak", self._lang), f"{self._streak}",
             None),
            (_label(STATUS_LABELS, "gained", self._lang),
             f"+{self._gained_today} / {self._daily_cap}",
             None if self._daily_cap <= 0
             else min(1.0, self._gained_today / max(1, self._daily_cap))),
            (_label(STATUS_LABELS, "gifts", self._lang),
             f"{self._gifts_today} / {self._gift_cap}",
             None if self._gift_cap <= 0
             else min(1.0, self._gifts_today / max(1, self._gift_cap))),
        ]
        row_font = QFont("Microsoft YaHei")
        row_font.setPixelSize(12)
        for label, value, ratio in rows:
            painter.setFont(row_font)
            painter.setPen(QPen(QColor(TEXT)))
            painter.drawText(QRect(left, y, width // 2, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setPen(QPen(QColor(TEXT_DIM)))
            painter.drawText(QRect(left + width // 2, y, width - width // 2, 18),
                             Qt.AlignRight | Qt.AlignVCenter, value)
            y += 20
            if ratio is not None:
                self._paint_bar(painter, QRect(left, y, width, 8), ratio, radius=4.0)
                y += 14
            y += 4

    def _paint_bar(self, painter: QPainter, rect: QRect, ratio: float, radius: float) -> None:
        """轨道 + 粉色填充；填充右端画一个 6px 圆头，模拟手绘笔触收尾（规范 5.4）。"""
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CREAM_DEEP))
        painter.drawRoundedRect(rect, radius, radius)
        try:
            ratio = max(0.0, min(1.0, float(ratio)))
        except (TypeError, ValueError):
            ratio = 0.0
        fill_w = int(rect.width() * ratio)
        if fill_w > 0:
            fill = QRect(rect.x(), rect.y(), max(int(radius * 2), fill_w), rect.height())
            fill = fill.intersected(rect)
            painter.setBrush(QColor(HEART_PINK))
            painter.drawRoundedRect(fill, radius, radius)
            if fill_w > radius * 2:
                head = QRect(0, 0, 6, 6)
                head.moveCenter(QPoint(fill.right() - 1, fill.center().y()))
                painter.drawEllipse(head)
        painter.setPen(self._pen(OUTLINE, 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)


# ────────────────────────── 自检预览 ──────────────────────────


def _demo_panel(tab: str = "food", inventory=None, hovered: int | None = None) -> NurturePanel:
    import json

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "nurture", "items.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            items = json.load(handle).get("items", [])
    except Exception:
        items = []
    panel = NurturePanel(items)
    panel.set_inventory(inventory if inventory is not None
                        else {str(i.get("name")): 3 for i in items})
    panel.set_affection(128, 250)
    panel.set_streak(5)
    panel.set_today(gained=6, cap=20, gifts=1, gift_cap=3)
    panel.set_tab(tab)
    panel.set_soft_cap(250)
    if hovered is not None:
        panel._hovered_card = hovered       # noqa: SLF001 - 预览专用
    return panel


def render_preview(path: str) -> None:
    """把面板的几种状态渲染到一张图（人工验收用，见 04 文档阶段 D 验证）。"""
    from PySide6.QtGui import QPixmap

    panel = _demo_panel("food")
    names = [str(i.get("name")) for i in panel.items()]
    shots = []
    shots.append(("食物页 / 库存充足", _demo_panel("food")))
    shots.append(("食物页 / 有库存为 0 的卡片 + hover", _demo_panel(
        "food", {n: (0 if idx % 3 == 1 else 4) for idx, n in enumerate(names)}, hovered=0)))
    shots.append(("礼物页", _demo_panel("gift")))
    shots.append(("状态页", _demo_panel("status")))

    pad, label_h = 14, 18
    width = max(p.width() for _l, p in shots) + pad * 2
    height = sum(p.height() + label_h + pad for _l, p in shots) + pad
    sheet = QPixmap(width, height)
    sheet.fill(QColor(icons.CREAM_DEEP))
    painter = QPainter(sheet)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(11)
        painter.setFont(font)
        y = pad
        for label, panel in shots:
            panel.ensurePolished()
            painter.setPen(QPen(QColor(TEXT)))
            painter.drawText(QRect(pad, y, width - pad * 2, label_h),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            y += label_h
            painter.drawPixmap(pad, y, panel.grab())
            y += panel.height() + pad
    finally:
        painter.end()
    sheet.save(path)
    print(f"nurture panel preview -> {path}  ({sheet.width()}x{sheet.height()})")


def _main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([])   # noqa: F841
    out = argv[1] if len(argv) > 1 else "_nurture_panel_preview.png"
    render_preview(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
