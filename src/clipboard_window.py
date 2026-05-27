"""历史粘贴板窗口——亚克力磨砂玻璃风格，独立可拖拽"""
import os
import time
from datetime import datetime

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import (
    QPainter, QPen, QColor, QPixmap, QImage, QMouseEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QApplication, QSpinBox, QDialog,
    QButtonGroup,
)

from src.clipboard_store import ClipboardStore

STYLE = """
QLineEdit#SearchBox {
    background: rgba(245, 245, 245, 0.7);
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    font-family: "Microsoft YaHei";
    color: #212121;
}
QLineEdit#SearchBox:focus {
    border: 1px solid #42A5F5;
    background: rgba(255, 255, 255, 0.9);
}
QPushButton#FilterBtn {
    background: #E0E0E0;
    color: #757575;
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    font-size: 12px;
    font-family: "Microsoft YaHei";
}
QPushButton#FilterBtn:hover {
    background: #BBDEFB;
    color: #212121;
}
QPushButton#FilterBtn:checked {
    background: #1976D2;
    color: white;
    font-weight: bold;
}
QPushButton#GearBtn {
    background: transparent;
    border: none;
    font-size: 16px;
    padding: 2px 4px;
}
QPushButton#GearBtn:hover {
    background: rgba(0,0,0,0.06);
    border-radius: 4px;
}
QLabel#Card {
    background: rgba(245, 245, 245, 0.7);
    border-radius: 8px;
    padding: 10px 14px;
    font-family: "Microsoft YaHei";
}
QLabel#TextPreview {
    font-size: 12px;
    color: #212121;
    font-family: "Microsoft YaHei";
}
QLabel#Timestamp {
    font-size: 11px;
    color: #9E9E9E;
    font-family: "Microsoft YaHei";
}
QLabel#EmptyIcon {
    font-size: 48px;
    color: #BDBDBD;
}
QLabel#EmptyText {
    font-size: 14px;
    color: #9E9E9E;
    font-family: "Microsoft YaHei";
}
QLabel#EmptySub {
    font-size: 12px;
    color: #BDBDBD;
    font-family: "Microsoft YaHei";
}
QToolTip {
    background: white;
    color: #424242;
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    font-family: "Microsoft YaHei";
}
QLabel#Expander {
    font-size: 12px;
    color: #42A5F5;
    font-family: "Microsoft YaHei";
}
QLabel#Expander:hover {
    color: #1E88E5;
}
"""


class ClipboardWindow(QWidget):
    def __init__(self, store: ClipboardStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setObjectName("ClipboardWindow")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self.resize(520, 600)
        self.setMinimumSize(480, 400)

        self._drag_pos: QPoint | None = None
        self._filter_buttons: list[QPushButton] = []
        self._current_filter_days = 0  # 0 = 全部
        self._show_relative_time = False

        self._build_ui()
        self._refresh_list()

    # ── 淡入淡出 ──

    def show_with_fade(self):
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        self.setWindowOpacity(0.0)
        self.show()

        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._fade_anim = anim

    def hide_with_fade(self):
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        if not self.isVisible():
            return

        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.InCubic)

        def _done():
            self.hide()
            self.setWindowOpacity(1.0)

        anim.finished.connect(_done)
        anim.start()
        self._fade_anim = anim

    # ── 绘制 ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(255, 255, 255, 237))
        painter.setPen(QPen(QColor(187, 222, 251, 160), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    # ── 拖拽 ──

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            # 仅在标题栏区域允许拖拽
            if event.position().y() < self._title_bar_height():
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _title_bar_height(self) -> int:
        return 48

    # ── 构建 UI ──

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 12)
        main_layout.setSpacing(6)

        # 标题栏
        title_bar = self._build_title_bar()
        main_layout.addLayout(title_bar)

        # 工具栏
        toolbar = self._build_toolbar()
        main_layout.addLayout(toolbar)

        # 滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; } "
            "QScrollBar:vertical { width: 6px; background: transparent; } "
            "QScrollBar::handle:vertical { background: #BDBDBD; border-radius: 3px; min-height: 30px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_container)
        main_layout.addWidget(self._scroll, 1)

    def _build_title_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 0)
        row.setSpacing(6)

        title = QLabel("\U0001F4CB  历史粘贴板")
        title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        row.addWidget(title)
        row.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { font-size: 14px; color: #9E9E9E; border: none; "
            "border-radius: 4px; background: transparent; }"
            "QPushButton:hover { background: rgba(0,0,0,0.08); color: #424242; }"
        )
        close_btn.clicked.connect(self.hide_with_fade)
        row.addWidget(close_btn)

        return row

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 4)
        row.setSpacing(6)

        # 搜索框
        self._search_box = QLineEdit()
        self._search_box.setObjectName("SearchBox")
        self._search_box.setPlaceholderText("\U0001F50D  搜索文字内容...")
        self._search_box.textChanged.connect(self._on_search_changed)
        row.addWidget(self._search_box, 1)

        # 时间筛选按钮（QButtonGroup 互斥，确保单选+视觉反馈）
        self._filter_group = QButtonGroup()
        self._filter_group.setExclusive(True)
        filters = [("1 天", 1), ("3 天", 3), ("5 天", 5), ("全部", 0)]
        for label, days in filters:
            btn = QPushButton(label)
            btn.setObjectName("FilterBtn")
            btn.setCheckable(True)
            self._filter_group.addButton(btn)
            btn.clicked.connect(lambda checked, d=days: self._on_filter_changed(d))
            self._filter_buttons.append(btn)
            row.addWidget(btn)

        # 默认选中"全部"
        self._filter_buttons[-1].setChecked(True)

        # 齿轮按钮
        gear_btn = QPushButton("⚙")
        gear_btn.setObjectName("GearBtn")
        gear_btn.setFixedSize(28, 28)
        gear_btn.setToolTip("自动清理设置")
        gear_btn.clicked.connect(self._on_cleanup_settings)
        row.addWidget(gear_btn)

        return row

    # ── 列表刷新 ──

    def refresh(self):
        self._refresh_list()

    def _refresh_list(self):
        # 清空现有卡片
        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        search = self._search_box.text().strip() if self._search_box else ""
        items = self._store.get_items(days=self._current_filter_days, search=search)

        if not items:
            self._show_empty_state()
        else:
            for item in items:
                card = self._build_card(item)
                self._list_layout.addWidget(card)

        # stretch 始终在末尾，让卡片保持自然高度
        self._list_layout.addStretch()

    def _show_empty_state(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 40, 0, 0)
        layout.setSpacing(8)

        icon = QLabel("\U0001F4CB")
        icon.setObjectName("EmptyIcon")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        text = QLabel("暂无剪贴板记录")
        text.setObjectName("EmptyText")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)

        sub = QLabel("复制文字或图片后会自动出现在这里")
        sub.setObjectName("EmptySub")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        layout.addStretch()
        self._list_layout.insertWidget(0, container)

    # ── 卡片构建 ──

    def _build_card(self, item: dict) -> QWidget:
        pinned = item['pinned']
        card = QWidget()
        card.setObjectName("Card")
        border = "border-left: 3px solid #FFA726; " if pinned else ""
        card.setStyleSheet(
            f"#Card {{ background: rgba(245, 245, 245, 0.7); border-radius: 8px; {border}}}"
            "#Card:hover { background: rgba(227, 242, 253, 0.8); }"
        )
        card.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        # 图片：卡片顶部独占一行
        if item['type'] == 'image':
            image_label = self._build_image_preview(item['image_path'])
            layout.addWidget(image_label)

        # 按钮行
        content_row = QHBoxLayout()
        content_row.setSpacing(8)

        is_long_text = False
        if item['type'] == 'text':
            text = item['text_content']
            text_preview = QLabel(text)
            text_preview.setObjectName("TextPreview")
            text_preview.setWordWrap(True)
            text_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            fm = text_preview.fontMetrics()
            line_h = fm.lineSpacing()
            avail_w = max(self._scroll.viewport().width() - 80, 280)
            text_rect = fm.boundingRect(
                0, 0, avail_w, 9999, Qt.TextWordWrap, text
            )
            is_long_text = text_rect.height() > line_h * 3
            if is_long_text:
                text_preview.setMaximumHeight(line_h * 3)
                text_preview.setProperty("full_text", text)
                text_preview.setProperty("expanded", False)
            content_row.addWidget(text_preview, 1)

        content_row.addStretch()

        # 置顶按钮
        pin_icon = "\U0001F4CC"
        pin_btn = QPushButton(pin_icon)
        pin_btn.setFixedSize(24, 24)
        pin_btn.setStyleSheet(self._pin_style(pinned))
        pin_btn.setToolTip("取消置顶" if pinned else "置顶")
        pin_btn.clicked.connect(lambda: self._toggle_pin(item['id']))
        content_row.addWidget(pin_btn)

        # 删除按钮
        del_btn = QPushButton("\U0001F5D1")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(
            "QPushButton { font-size: 12px; color: #9E9E9E; border: none; "
            "border-radius: 4px; background: transparent; }"
            "QPushButton:hover { background: rgba(239,83,80,0.12); color: #EF5350; }"
        )
        del_btn.setToolTip("删除")
        del_btn.clicked.connect(lambda: self._delete_item(item['id']))
        content_row.addWidget(del_btn)

        layout.addLayout(content_row)

        # 长文本展开/收起
        if is_long_text:
            expander = QLabel("展开 ▼")
            expander.setObjectName("Expander")
            expander.setCursor(Qt.PointingHandCursor)
            expander.mousePressEvent = lambda e, tp=text_preview, exp=expander: self._toggle_expand(tp, exp)
            layout.addWidget(expander)

        # 时间戳（可点击切换格式）
        ts_label = self._build_timestamp(item['created_at'])
        layout.addWidget(ts_label)

        # 点击卡片空白区域 → 复制到剪贴板
        card.mousePressEvent = lambda e, iid=item['id']: self._on_card_click(iid)

        return card

    def _build_timestamp(self, created_at: float):
        """创建可点击的时间戳，切换绝对/相对时间（全局切换）"""
        label = QLabel()
        label.setObjectName("Timestamp")
        label.setCursor(Qt.PointingHandCursor)
        label.setProperty("created_at", created_at)
        self._update_timestamp_text(label)
        label.mousePressEvent = lambda e, lbl=label: self._toggle_all_timestamps()
        return label

    def _update_timestamp_text(self, label: QLabel):
        created_at = label.property("created_at")
        if self._show_relative_time:
            label.setText(self._relative_time(created_at))
        else:
            label.setText(datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S"))

    def _toggle_all_timestamps(self):
        self._show_relative_time = not self._show_relative_time
        # 遍历所有卡片中的时间戳标签，直接更新文本
        for i in range(self._list_layout.count()):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                # 时间戳标签在卡片的子布局中
                card = item.widget()
                cl = card.layout()
                if cl and cl.count() >= 2:
                    # 时间戳在最后一个子项
                    last_item = cl.itemAt(cl.count() - 1)
                    if last_item and last_item.widget():
                        w = last_item.widget()
                        if isinstance(w, QLabel) and w.objectName() == "Timestamp":
                            self._update_timestamp_text(w)

    @staticmethod
    def _relative_time(ts: float) -> str:
        diff = time.time() - ts
        if diff < 60:
            return "刚刚"
        elif diff < 3600:
            return f"{int(diff // 60)} 分钟前"
        elif diff < 86400:
            return f"{int(diff // 3600)} 小时前"
        elif diff < 2592000:
            return f"{int(diff // 86400)} 天前"
        else:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

    def _toggle_expand(self, text_label: QLabel, expander: QLabel):
        expanded = text_label.property("expanded")
        if expanded:
            text_label.setMaximumHeight(text_label.fontMetrics().lineSpacing() * 3)
            text_label.setProperty("expanded", False)
            expander.setText("展开 ▼")
        else:
            text_label.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            text_label.setProperty("expanded", True)
            expander.setText("收起 ▲")

    def _build_image_preview(self, image_path: str) -> QLabel:
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        loaded = False
        if os.path.exists(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                orig_w, orig_h = pix.width(), pix.height()
                max_w = 470
                max_h = 350
                if orig_w <= max_w and orig_h <= max_h:
                    pass  # 小图用原分辨率
                else:
                    pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(pix)
                label.setStyleSheet("background: transparent;")
                loaded = True
        if not loaded:
            label.setText("\U0001F4F7")
            label.setMinimumHeight(80)
            label.setStyleSheet(
                "font-size: 40px; color: #BDBDBD; background: rgba(0,0,0,0.03); "
                "border-radius: 6px;"
            )
        return label

    def _pin_style(self, pinned: bool) -> str:
        if pinned:
            return (
                "QPushButton { font-size: 14px; color: #FFA726; border: none; "
                "border-radius: 4px; background: transparent; }"
                "QPushButton:hover { background: rgba(255,167,38,0.12); }"
            )
        return (
            "QPushButton { font-size: 14px; color: #BDBDBD; border: none; "
            "border-radius: 4px; background: transparent; }"
            "QPushButton:hover { background: rgba(0,0,0,0.06); color: #757575; }"
        )

    # ── 交互 ──

    def _on_card_click(self, item_id: int):
        """点击卡片 → 复制到剪贴板"""
        item = self._store.get_by_id(item_id)
        if item is None:
            return
        clipboard = QApplication.clipboard()
        if item['type'] == 'text':
            clipboard.setText(item['text_content'])
        elif item['type'] == 'image' and os.path.exists(item['image_path']):
            image = QImage(item['image_path'])
            if not image.isNull():
                clipboard.setImage(image)

    def _toggle_pin(self, item_id: int):
        self._store.pin_item(item_id)
        self._refresh_list()

    def _delete_item(self, item_id: int):
        self._store.delete_item(item_id)
        self._refresh_list()

    def _on_search_changed(self, _text: str):
        self._refresh_list()

    def _on_filter_changed(self, days: int):
        self._current_filter_days = days
        self._refresh_list()

    def _on_cleanup_settings(self):
        dialog = CleanupDialog(self._store, self)
        dialog.exec()
        self._store.cleanup_expired(self._store.get_cleanup_days())
        self._refresh_list()


class CleanupDialog(QDialog):
    """自动清理天数设置对话框"""

    def __init__(self, store: ClipboardStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._parent_window = parent
        self.setWindowTitle("自动清理设置")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(300, 230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title = QLabel("自动清理设置")
        title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        layout.addWidget(title)

        desc = QLabel("超过以下天数的记录将被自动删除（置顶项除外）")
        desc.setStyleSheet(
            "font-size: 12px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        spin_row = QHBoxLayout()
        spin_label = QLabel("保留天数:")
        spin_label.setStyleSheet(
            "font-size: 13px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        spin_row.addWidget(spin_label)
        self._spin = QSpinBox()
        self._spin.setRange(1, 365)
        self._spin.setValue(store.get_cleanup_days())
        self._spin.setSuffix(" 天")
        self._spin.setStyleSheet(
            "QSpinBox { background: rgba(245,245,245,0.7); border: 1px solid #E0E0E0; "
            "border-radius: 4px; padding: 4px 8px; font-size: 13px; "
            "font-family: 'Microsoft YaHei'; color: #212121; }"
            "QSpinBox:hover { border: 1px solid #42A5F5; }"
            "QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; "
            "width: 20px; border-left: 1px solid #E0E0E0; "
            "border-top-right-radius: 4px; background: transparent; }"
            "QSpinBox::up-button:hover { background: #BBDEFB; }"
            "QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; "
            "width: 20px; border-left: 1px solid #E0E0E0; "
            "border-bottom-right-radius: 4px; background: transparent; }"
            "QSpinBox::down-button:hover { background: #BBDEFB; }"
            "QSpinBox::up-arrow { image: none; border-left: 4px solid transparent; "
            "border-right: 4px solid transparent; border-bottom: 5px solid #757575; }"
            "QSpinBox::down-arrow { image: none; border-left: 4px solid transparent; "
            "border-right: 4px solid transparent; border-top: 5px solid #757575; }"
        )
        spin_row.addWidget(self._spin)
        spin_row.addStretch()
        layout.addLayout(spin_row)

        # 分隔线
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #E0E0E0;")
        layout.addWidget(sep)

        # 一键清除按钮
        clear_label = QLabel("手动清除：")
        clear_label.setStyleSheet(
            "font-size: 13px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        layout.addWidget(clear_label)

        clear_btn = QPushButton("清除全部记录（置顶项除外）")
        clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #EF5350; "
            "border: 1px solid #EF5350; border-radius: 6px; "
            "padding: 7px 16px; font-size: 13px; font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { background: rgba(239,83,80,0.08); }"
        )
        clear_btn.clicked.connect(self._on_clear_all)
        layout.addWidget(clear_btn)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(
            "QPushButton { background: #42A5F5; color: white; border: none; "
            "border-radius: 6px; padding: 7px 22px; font-size: 13px; "
            "font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { background: #1E88E5; }"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(255, 255, 255, 242))
        painter.setPen(QPen(QColor(187, 222, 251, 180), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)

    def _on_save(self):
        self._store.set_cleanup_days(self._spin.value())
        self.accept()

    def _on_clear_all(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "确认清除",
            "确定要清除所有非置顶的剪贴板记录吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._store.clear_all()
            self._parent_window.refresh()
