"""左键功能面板 / 右键系统面板 —— 暖粉奶白手绘风（全自绘）。

2026-09-10 **全局换肤**：这个文件以前是"冷蓝磨砂玻璃 + QSS 文字列表"，现在与养成面板
（`nurture_panel.py`）、悬停菜单（`hover_menu.py`）、对话气泡（`speech_bubble.py`）
共用同一套笔触与色板（`src/ui_theme.py`），内部改成**全自绘**：

| 维度 | 改造前 | 现在 |
|------|--------|------|
| 底 | 冷蓝半透明（`rgba(227,242,253,228)`） | 暖奶白 `#FFF9F6`(242) + 2px 暖棕描边 + 暖色投影 |
| 圆角 | 12px | 20px（四角不等，手绘感） |
| 菜单项 | QLabel 文字条 | 行胶囊：**圆形图标** + 文字 +（可勾选项）右侧圆形勾选指示 |
| Hover | 淡蓝底 | 粉底 + 粉描边 |
| 关闭 | 16px 文字 `✕` | 28px 圆形按钮 + 自绘 `close` 图标 |

**对外契约一行没变**（`pet_window.py` 因此零改动）：
`item_clicked` 信号、`popup_at()` / `show_at()` / `hide_with_anim()` / `apply_language()` /
`set_item_checked()` / `is_item_checked()`，以及"靠 `focusOutEvent` 自动收起"这条既有行为。
模块级的 `_force_raise_topmost()` 也被 `nurture_panel` / `hover_menu` / `speech_bubble` 导入，
**必须原样保留**。

⚠️ **几何口径变了**：窗口比"看得见的面板"四周各多出 `MARGIN=6px`（留给投影，与养成面板同款）。
所有落位都以 `visible_rect()` 为准，间距指的是**面板边缘**到人物边缘 —— 拿窗口尺寸去量会凭空多出 12px。
"""

import sys

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

from src import nurture_icons as icons
from src import ui_theme as theme
from src.panel_animator import animate_panel_hide, animate_panel_show, _stop_anim
from src.translations import tr


def _force_raise_topmost(widget: QWidget):
    """强制将窗口提升到 TOPMOST 层的最顶端（Windows）。

    Qt 的 raise() 在 HWND_TOP 模式下对同属 WS_EX_TOPMOST 的窗口
    无法可靠重排 z-order。这里用 Win32 API 先把窗口从 TOPMOST 层移除、
    再重新插入，确保它排在 TOPMOST 层的最顶部。

    **被 `nurture_panel` / `hover_menu` / `speech_bubble` 三个组件导入**，改动前先看它们。
    """
    if sys.platform != 'win32':
        widget.raise_()
        return
    if not widget.winId():
        return
    import ctypes
    hwnd = int(widget.winId())
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    # 1) 先移出 TOPMOST 层
    ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    # 2) 重新插入 TOPMOST 层 → 自动排到该层最顶部
    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)


# ────────────────────────── 规格常量（与 03 规范 5.1/5.2 同口径）──────────────────────────

MARGIN = theme.MARGIN          # 6：窗口四边留给投影的空间
PAD = 10                       # 内容内边距
HEADER_H = 28                  # 顶部行（只放关闭按钮）
HEADER_GAP = 6                 # 顶部行与列表的间距
ROW_H = 36                     # 菜单行高（比圆形图标高 6px：让 hover 胶囊的描边
                               # 与图标圆之间留出可见的间隙，否则两条线会糊在一起）
ROW_GAP = 4                    # 行距
ICON_D = 30                    # 圆形图标直径
ICON_SIZE = 18                 # 圆内图标像素
CHECK_D = 16                   # 勾选指示直径
CLOSE_D = 28                   # 关闭按钮直径（规范 5.2）
GAP_FROM_PET = 8               # 与人物窗口的间距（指**面板边缘**）
MIN_WIDTH = 168                # 可见宽度下限
MAX_WIDTH = 216                # 可见宽度上限（再宽就显得空）

#: `item_id` → 图标键。**不在表里的 item_id 会自动降级成"名称首字"**（`nurture_icons`
#: 的第 3 级兜底），所以 `pet_window` 里加新菜单项时**不需要**改这个文件。
ITEM_ICONS: dict[str, str] = {
    "clipboard": "clipboard",
    "topmost": "pin",
    "desktop_level": "monitor",
    "minimize_tray": "tray",
    "settings": "settings",
    "exit": "power",
}


class BubblePanel(QWidget):
    """可配置菜单面板。只负责"画出来 + 报告点击"，业务判断都在 `PetWindow`。

    `items`：`[(item_id, 翻译键), ...]`，第三项可选 `{"checkable": True}`。
    """

    item_clicked = Signal(str)  # 携带 item_id

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self._current_lang = "zh"
        self._item_keys = list(items or [])
        self._checked: dict[str, bool] = {}
        self._texts: dict[str, str] = {}
        self._visible_w = MIN_WIDTH
        self._visible_h = HEADER_H + ROW_H + 2 * PAD + HEADER_GAP
        self._hovered_row: int | None = None
        self._pressed_row: int | None = None
        self._hovered_close = False

        for entry in self._item_keys:
            if len(entry) >= 3 and isinstance(entry[2], dict) and entry[2].get("checkable"):
                self._checked[str(entry[0])] = False

        self.setObjectName("BubblePanel")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._apply_language()
        self._resize_to_content()

    # ────────────────── 对外接口（与改造前一致）──────────────────

    def apply_language(self, lang: str):
        self._current_lang = lang
        self._apply_language()
        self._resize_to_content()

    def set_item_checked(self, item_id: str, checked: bool):
        """设置 checkable 项的选中状态并重绘"""
        if item_id in self._checked:
            self._checked[item_id] = bool(checked)
            self.update()

    def is_item_checked(self, item_id: str) -> bool:
        """查询 checkable 项的选中状态"""
        return self._checked.get(item_id, False)

    def adjustSize(self):                                       # noqa: N802
        """`QWidget.adjustSize()` 在本组件里没有意义（全自绘、无布局），转发到自算尺寸。

        保留这个重写是为了兼容外部可能存在的调用：改造前它在这里是真有用的（QLabel 布局）。
        """
        self._resize_to_content()

    # ────────────────── 几何 ──────────────────

    def visible_rect(self) -> QRect:
        """**看得见的面板**在本窗口内的矩形（窗口四边各留 `MARGIN` 给投影）。"""
        return QRect(MARGIN, MARGIN, self._visible_w, self._visible_h)

    def visible_size(self):
        return self._visible_w, self._visible_h

    def _close_rect(self) -> QRectF:
        rect = self.visible_rect()
        return QRectF(rect.right() + 1 - PAD - CLOSE_D, rect.top() + PAD, CLOSE_D, CLOSE_D)

    def _row_rect(self, index: int) -> QRectF:
        rect = self.visible_rect()
        top = rect.top() + PAD + HEADER_H + HEADER_GAP + index * (ROW_H + ROW_GAP)
        return QRectF(rect.left() + PAD - 4, top, rect.width() - 2 * PAD + 8, ROW_H)

    def _icon_rect(self, row: QRectF) -> QRectF:
        """行左侧的圆形图标位（中心对齐行中心，左边距 = 行左 + 4px）。"""
        box = QRectF(0, 0, ICON_D, ICON_D)
        box.moveCenter(QPointF(row.left() + 4 + ICON_D / 2.0, row.center().y()))
        return box

    def _check_rect(self, row: QRectF) -> QRectF:
        """行右侧的勾选指示位。"""
        box = QRectF(0, 0, CHECK_D, CHECK_D)
        box.moveCenter(QPointF(row.right() - 4 - CHECK_D / 2.0, row.center().y()))
        return box

    def row_labels(self) -> list[str]:
        """当前语言下的行文案（预览脚本与测试用）。"""
        return [self._texts.get(str(e[0]), "") for e in self._item_keys]

    def _resize_to_content(self) -> None:
        """按内容算可见宽高，窗口 = 可见 + 2×`MARGIN`。"""
        rows = len(self._item_keys)
        label_font = theme.font(13)
        widest = 0
        for text in self.row_labels():
            widest = max(widest, theme.text_width(text, label_font))
        has_check = bool(self._checked)
        chrome = PAD + 4 + ICON_D + 10 + (CHECK_D + 10 if has_check else 0) + PAD + 4
        width = max(MIN_WIDTH, min(MAX_WIDTH, chrome + widest))
        height = 2 * PAD + HEADER_H + HEADER_GAP
        if rows:
            height += rows * ROW_H + (rows - 1) * ROW_GAP
        self._visible_w = int(width)
        self._visible_h = int(height)
        self.setFixedSize(self._visible_w + 2 * MARGIN, self._visible_h + 2 * MARGIN)
        self.update()

    def _apply_language(self):
        for entry in self._item_keys:
            item_id = str(entry[0])
            self._texts[item_id] = tr(str(entry[1]), self._current_lang)

    # ────────────────── 弹出 / 收起 ──────────────────

    def popup_at(self, pet_geometry):
        """贴人物**右侧**弹出（滑入方向随左右越界翻转）。落位以**面板边缘**为准。"""
        self._resize_to_content()
        direction = "right"
        visible_w, visible_h = self._visible_w, self._visible_h
        x = pet_geometry.right() + 1 + GAP_FROM_PET - MARGIN
        y = pet_geometry.center().y() - visible_h // 2 - MARGIN

        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        if x + MARGIN + visible_w > screen.right() + 1:
            x = pet_geometry.left() - GAP_FROM_PET - visible_w - MARGIN
            direction = "left"
        if y + MARGIN < screen.top():
            y = screen.top() - MARGIN + 4
        elif y + MARGIN + visible_h > screen.bottom() + 1:
            y = screen.bottom() - visible_h - MARGIN - 3

        self._popup_direction = direction
        animate_panel_show(self, QPoint(int(x), int(y)), direction)
        self.raise_()
        self.activateWindow()

    def show_at(self, pos: QPoint):
        """在指定屏幕坐标弹出（类系统菜单——面板一角对准鼠标，无动画，直接出现）。

        pos: 全局屏幕坐标，通常是 QCursor.pos()。

        定位规则（对齐 Windows / 常见软件"面板一角对准光标"的习惯）：
        1. 默认让面板**左上角**对准鼠标；
        2. 面板超出屏幕右边界 → 整体翻转到鼠标**左侧**（右上角对准鼠标）；
        3. 面板超出屏幕下边界 → 整体翻转到鼠标**上方**（左下角对准鼠标）；
        4. 两轴同时翻转时，鼠标位于面板**右下角**；
        5. 极端情况下仍越界 → 夹紧到该屏幕可用区域内。

        支持多显示器：优先使用鼠标所在的屏幕，避免在副屏上弹出错位。
        **对准光标的是看得见的面板角，不是窗口角**（窗口还带着 6px 投影留白）。
        """
        self._resize_to_content()

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        # 优先取鼠标所在屏幕（多显示器时用鼠标当前屏幕），否则回落主屏
        screen = app.screenAt(pos) or app.primaryScreen()
        geom = screen.availableGeometry()

        visible_w, visible_h = self._visible_w, self._visible_h

        # 默认：面板左上角对准鼠标
        x = pos.x() - MARGIN
        y = pos.y() - MARGIN

        # 超出右边界 → 翻转到鼠标左侧（右上角对准鼠标）
        if x + MARGIN + visible_w > geom.right() + 1:
            x = pos.x() - visible_w - MARGIN
        # 超出下边界 → 翻转到鼠标上方（左下角对准鼠标）
        if y + MARGIN + visible_h > geom.bottom() + 1:
            y = pos.y() - visible_h - MARGIN

        # 极端越界兜底：夹紧到屏幕可用区域（按可见面板算）
        x = max(geom.left() - MARGIN, min(x, geom.right() - visible_w - MARGIN + 1))
        y = max(geom.top() - MARGIN, min(y, geom.bottom() - visible_h - MARGIN + 1))

        self._popup_direction = "none"  # 标记为非滑入模式

        _stop_anim(self)
        self.move(QPoint(int(x), int(y)))
        self.show()
        _force_raise_topmost(self)  # Win32: 强制排到 TOPMOST 层最顶部

    def hide_with_anim(self):
        """带动画隐藏面板"""
        if not self.isVisible():
            return
        self._hovered_row = None
        self._pressed_row = None
        self._hovered_close = False
        direction = getattr(self, "_popup_direction", "right")
        if direction == "none":
            # 无滑入模式 → 直接隐藏（系统菜单风格，无动画）
            _stop_anim(self)
            self.hide()
        else:
            animate_panel_hide(self, direction)

    # ────────────────── 绘制 ──────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = self.visible_rect()
            theme.paint_paper(painter, rect)
            self._paint_close(painter)
            self._paint_rows(painter)
        finally:
            painter.end()

    def _paint_close(self, painter: QPainter) -> None:
        rect = self._close_rect()
        theme.paint_circle(painter, rect, fill=theme.CREAM,
                           hovered=self._hovered_close,
                           glow=self._hovered_close)
        icon = icons.pixmap("close", 14, dpr=self.devicePixelRatioF())
        target = QRect(0, 0, 14, 14)
        target.moveCenter(rect.center().toPoint())
        painter.drawPixmap(target, icon, QRect(icon.rect()))

    def _paint_rows(self, painter: QPainter) -> None:
        for index, entry in enumerate(self._item_keys):
            item_id = str(entry[0])
            row = self._row_rect(index)
            hovered = (index == self._hovered_row)
            pressed = (index == self._pressed_row)
            checked = self._checked.get(item_id, False)

            theme.paint_row(painter, row, hovered=hovered, pressed=pressed,
                            selected=checked and not hovered)

            # 圆形图标
            icon_rect = self._icon_rect(row)
            theme.paint_circle(painter, icon_rect, fill=theme.CREAM_DEEP,
                               hovered=hovered, glow=False)
            icon_key = ITEM_ICONS.get(item_id, "")
            glyph = icons.pixmap(icon_key, ICON_SIZE, dpr=self.devicePixelRatioF(),
                                 fallback_text=self._texts.get(item_id, "")[:1])
            target = QRect(0, 0, ICON_SIZE, ICON_SIZE)
            target.moveCenter(icon_rect.center().toPoint())
            painter.drawPixmap(target, glyph, QRect(glyph.rect()))

            # 文案
            label_font = theme.font(13, bold=checked)
            painter.setFont(label_font)
            painter.setPen(QColor(theme.NAVY if checked else theme.TEXT))
            text_left = int(icon_rect.right()) + 10
            text_right = int(self._check_rect(row).left()) - 8 if item_id in self._checked \
                else int(row.right()) - 6
            text_rect = QRect(text_left, int(row.top()),
                              max(8, text_right - text_left), int(row.height()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             theme.elide(self._texts.get(item_id, ""), label_font,
                                         text_rect.width()))

            if item_id in self._checked:
                self._paint_check(painter, self._check_rect(row), checked)

    def _paint_check(self, painter: QPainter, rect: QRectF, checked: bool) -> None:
        """勾选指示：选中 = 粉底 + 暖棕勾；未选 = 空圆 + 浅描边。"""
        theme.paint_circle(painter, rect,
                           fill=theme.PINK if checked else theme.CREAM,
                           outline=theme.OUTLINE if checked else theme.OUTLINE_LIGHT,
                           width=1.8 if checked else 1.5)
        if not checked:
            return
        pen = theme.pen(theme.OUTLINE, 1.8)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cx, cy = rect.center().x(), rect.center().y()
        painter.drawPolyline(QPolygonF([
            QPointF(cx - 3.4, cy - 0.4),
            QPointF(cx - 1.0, cy + 2.2),
            QPointF(cx + 3.6, cy - 2.4),
        ]))

    # ────────────────── 交互 ──────────────────

    def _row_at(self, pos) -> int | None:
        for index in range(len(self._item_keys)):
            if self._row_rect(index).contains(float(pos.x()), float(pos.y())):
                return index
        return None

    def mouseMoveEvent(self, event):
        pos = event.position()
        row = self._row_at(pos)
        close = self._close_rect().contains(pos)
        if row != self._hovered_row or close != self._hovered_close:
            self._hovered_row = row
            self._hovered_close = bool(close)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_row is not None or self._hovered_close:
            self._hovered_row = None
            self._hovered_close = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        if self._close_rect().contains(pos):
            self.hide_with_anim()
            return
        row = self._row_at(pos)
        if row is None:
            return
        self._pressed_row = row
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        row = self._row_at(event.position())
        pressed = self._pressed_row
        self._pressed_row = None
        self.update()
        if row is not None and row == pressed:
            self.item_clicked.emit(str(self._item_keys[row][0]))
            self.hide_with_anim()
        super().mouseReleaseEvent(event)

    def focusOutEvent(self, event):
        """失去了焦点 → 收起。

        **这条是既有行为，不能删**：面板会 `activateWindow()` 拿焦点，
        所以"点别处"靠这里收起（悬停菜单/养成面板刻意相反：它们从不拿焦点）。
        """
        self.hide_with_anim()
        super().focusOutEvent(event)
