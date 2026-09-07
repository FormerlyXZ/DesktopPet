"""侧边气泡面板——亚克力半透明玻璃风格，带过渡动画"""
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QEvent, Signal, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QPen, QColor
from src.panel_animator import animate_panel_show, animate_panel_hide, _stop_anim
from src.translations import tr


def _force_raise_topmost(widget: QWidget):
    """强制将窗口提升到 TOPMOST 层的最顶端（Windows）。

    Qt 的 raise() 在 HWND_TOP 模式下对同属 WS_EX_TOPMOST 的窗口
    无法可靠重排 z-order。这里用 Win32 API 先把窗口从 TOPMOST 层移除、
    再重新插入，确保它排在 TOPMOST 层的最顶部。
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

STYLE = """
QLabel#Item {
    padding: 10px 14px;
    font-size: 13px;
    color: #212121;
    border-radius: 4px;
    font-family: "Microsoft YaHei";
}
QLabel#Item:hover {
    background: rgba(66, 165, 245, 0.15);
}
QLabel#DisabledItem {
    padding: 10px 14px;
    font-size: 13px;
    color: #BDBDBD;
    border-radius: 4px;
    font-family: "Microsoft YaHei";
}
QLabel#CloseLabel {
    font-size: 16px;
    color: #9E9E9E;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: "Microsoft YaHei";
}
QLabel#CloseLabel:hover {
    background: rgba(0, 0, 0, 0.08);
    color: #424242;
}
"""


class BubblePanel(QWidget):
    item_clicked = Signal(str)  # 携带 item_id

    def __init__(self, items: list, parent=None):
        """
        items: [(item_id, translation_key), ...] 或
               [(item_id, translation_key, {"checkable": True}), ...]
        示例: [("clipboard", "bubble_clipboard")]
        """
        super().__init__(parent)
        self._current_lang = "zh"
        self._item_keys = items  # 保留原始定义
        self._checked: dict[str, bool] = {}  # checkable 项的选中状态
        self.setObjectName("BubblePanel")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.setFixedWidth(170)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 8, 6, 8)
        main_layout.setSpacing(2)

        # ── 顶部行：关闭按钮居右 ──
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 2, 0)
        header.addStretch()
        close_label = QLabel("✕")
        close_label.setObjectName("CloseLabel")
        close_label.setCursor(Qt.PointingHandCursor)
        close_label.installEventFilter(self)
        self._close_btn = close_label
        header.addWidget(close_label)
        main_layout.addLayout(header)

        # ── 动态菜单项 ──
        self._item_labels: dict[str, QLabel] = {}
        for entry in items:
            item_id = entry[0]
            _tr_key = entry[1]
            opts = entry[2] if len(entry) >= 3 else {}
            if opts.get("checkable"):
                self._checked[item_id] = False
            label = QLabel("")
            label.setObjectName("Item")
            label.setCursor(Qt.PointingHandCursor)
            label.installEventFilter(self)
            self._item_labels[item_id] = label
            main_layout.addWidget(label)

        self._apply_language()
        self.adjustSize()

    def apply_language(self, lang: str):
        self._current_lang = lang
        self._apply_language()

    def _apply_language(self):
        lang = self._current_lang
        for entry in self._item_keys:
            item_id = entry[0]
            tr_key = entry[1]
            opts = entry[2] if len(entry) >= 3 else {}
            label = self._item_labels.get(item_id)
            if label is None:
                continue
            text = tr(tr_key, lang)
            if opts.get("checkable"):
                checked = self._checked.get(item_id, False)
                text = ("✓ " if checked else "    ") + text
            label.setText(text)
        self.adjustSize()

    def set_item_checked(self, item_id: str, checked: bool):
        """设置 checkable 项的选中状态并刷新文本"""
        if item_id in self._checked:
            self._checked[item_id] = checked
            self._apply_language()

    def is_item_checked(self, item_id: str) -> bool:
        """查询 checkable 项的选中状态"""
        return self._checked.get(item_id, False)

    def paintEvent(self, event):
        """绘制亚克力磨砂玻璃背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(227, 242, 253, 228))
        painter.setPen(QPen(QColor(187, 222, 251, 160), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    def popup_at(self, pet_geometry):
        self.adjustSize()
        direction = "right"
        x = pet_geometry.right() + 8
        y = pet_geometry.center().y() - self.height() // 2

        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        if x + self.width() > screen.right():
            x = pet_geometry.left() - self.width() - 8
            direction = "left"
        if y < screen.top():
            y = screen.top() + 4
        elif y + self.height() > screen.bottom():
            y = screen.bottom() - self.height() - 4

        self._popup_direction = direction
        animate_panel_show(self, QPoint(x, y), direction)
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
        """
        self.adjustSize()

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        # 优先取鼠标所在屏幕（多显示器时用鼠标当前屏幕），否则回落主屏
        screen = app.screenAt(pos) or app.primaryScreen()
        geom = screen.availableGeometry()

        w, h = self.width(), self.height()

        # 默认：左上角对准鼠标
        x = pos.x()
        y = pos.y()

        # 超出右边界 → 翻转到鼠标左侧（右上角对准鼠标）
        if x + w > geom.right() + 1:
            x = pos.x() - w
        # 超出下边界 → 翻转到鼠标上方（左下角对准鼠标）
        if y + h > geom.bottom() + 1:
            y = pos.y() - h

        # 极端越界兜底：夹紧到屏幕可用区域
        x = max(geom.left(), min(x, geom.right() - w + 1))
        y = max(geom.top(), min(y, geom.bottom() - h + 1))

        self._popup_direction = "none"  # 标记为非滑入模式

        _stop_anim(self)
        self.move(QPoint(x, y))
        self.show()
        _force_raise_topmost(self)  # Win32: 强制排到 TOPMOST 层最顶部

    def hide_with_anim(self):
        """带动画隐藏面板"""
        if not self.isVisible():
            return
        direction = getattr(self, "_popup_direction", "right")
        if direction == "none":
            # 无滑入模式 → 直接隐藏（系统菜单风格，无动画）
            _stop_anim(self)
            self.hide()
        else:
            animate_panel_hide(self, direction)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            for item_id, label in self._item_labels.items():
                if obj is label:
                    self.item_clicked.emit(item_id)
                    self.hide_with_anim()
                    return True
            if obj is self._close_btn:
                self.hide_with_anim()
                return True
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        self.hide_with_anim()
        super().focusOutEvent(event)
