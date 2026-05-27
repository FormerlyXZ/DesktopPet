"""侧边气泡面板——亚克力半透明玻璃风格，带过渡动画"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel
)
from PySide6.QtCore import Qt, QEvent, Signal, QPoint
from PySide6.QtGui import QPainter, QPen, QColor
from src.panel_animator import animate_panel_show, animate_panel_hide
from src.translations import tr

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
    settings_clicked = Signal()
    clipboard_clicked = Signal()
    exit_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_lang = "zh"
        self.setObjectName("BubblePanel")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
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

        # ── 菜单项 ──
        self._settings = QLabel("")
        self._settings.setObjectName("Item")
        self._settings.setCursor(Qt.PointingHandCursor)
        self._settings.installEventFilter(self)
        main_layout.addWidget(self._settings)

        self._clipboard = QLabel("")
        self._clipboard.setObjectName("Item")
        self._clipboard.setCursor(Qt.PointingHandCursor)
        self._clipboard.installEventFilter(self)
        main_layout.addWidget(self._clipboard)

        self._exit = QLabel("")
        self._exit.setObjectName("Item")
        self._exit.setCursor(Qt.PointingHandCursor)
        self._exit.installEventFilter(self)
        main_layout.addWidget(self._exit)

        self._apply_language()
        self.adjustSize()

    def apply_language(self, lang: str):
        self._current_lang = lang
        self._apply_language()

    def _apply_language(self):
        lang = self._current_lang
        self._settings.setText(tr("bubble_settings", lang))
        self._clipboard.setText(tr("bubble_clipboard", lang))
        self._exit.setText(tr("bubble_exit", lang))
        self.adjustSize()

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
        self.activateWindow()
        animate_panel_show(self, QPoint(x, y), direction)

    def hide_with_anim(self):
        """带动画隐藏面板"""
        if not self.isVisible():
            return
        direction = getattr(self, "_popup_direction", "right")
        animate_panel_hide(self, direction)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            if obj is self._settings:
                self.settings_clicked.emit()
                self.hide_with_anim()
                return True
            elif obj is self._clipboard:
                self.clipboard_clicked.emit()
                self.hide_with_anim()
                return True
            elif obj is self._exit:
                self.exit_clicked.emit()
                return True
            elif obj is self._close_btn:
                self.hide_with_anim()
                return True
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        self.hide_with_anim()
        super().focusOutEvent(event)
