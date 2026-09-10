"""设置窗口——PNG / Q版 双页面，暖粉奶白手绘风（全自绘外壳 + 主题 QSS）。

2026-09-10 **全局换肤**：原本是"冷蓝磨砂玻璃 + 亮蓝强调色"，现在与悬停菜单、
养成面板、左键/右键面板统一成同一套视觉：

- 外壳：奶白纸片 + 2px 暖棕描边 + 20px 圆角（四角不等）+ 暖色投影，全是 `ui_theme` 画的
- 分区：`QGroupBox` 变成"纸片小卡"（奶白-深底 + 1.5px 浅描边 + 12px 圆角 + 藏青粗体标题）
- 控件：下拉/数字框/滑块/勾选框/列表统一由 `ui_theme.app_stylesheet()` 上色
  —— **自绘负责造型，QSS 负责配色**（把标准控件全改写成自绘是天级工作量，收益却很小）

**对外契约一行没变**：所有信号（`height_changed` / `save_clicked` / …）、
`set_animations()` / `set_height()` / `set_auto_start()` / `load_gif_settings()` /
`get_gif_settings()` / `set_character_type()` / `set_language()` / `popup_at()` /
`hide_with_anim()` 全部保持原样，`pet_window.py` 因此零改动。

⚠️ 窗口比"看得见的纸片"四周各多 `MARGIN`（默认 6px，留给投影），
`popup_at()` 里按**可见尺寸**定位，别拿 `self.width()` 直接对着人物摆。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSlider, QPushButton, QComboBox, QSpinBox, QMessageBox,
    QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QPoint, QEvent
from PySide6.QtGui import QPainter
from src import ui_theme as theme
from src.panel_animator import animate_panel_show, animate_panel_hide
from src.gif_settings_page import GifSettingsPage
from src.translations import tr

#: 看得见的纸片尺寸（窗口 = 这个 + 四边各留 `MARGIN` 给投影）
VISIBLE_W = 420
VISIBLE_H = 640
MARGIN = theme.MARGIN


class SettingsWindow(QWidget):
    height_changed = Signal(int)
    auto_start_changed = Signal(bool)
    animations_changed = Signal(str, str)  # idle_key, hover_key (PNG only)
    save_clicked = Signal()
    close_without_save = Signal()
    character_type_changed = Signal(str)  # "png" | "gif"
    language_changed = Signal(str)  # "zh" | "en" | "ja"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_lang = "zh"
        self.setObjectName("SettingsWindow")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(theme.app_stylesheet())
        self.setFixedSize(VISIBLE_W + 2 * MARGIN, VISIBLE_H + 2 * MARGIN)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(MARGIN + 16, MARGIN + 8, MARGIN + 16, MARGIN + 14)
        main_layout.setSpacing(10)

        # ── 标题 ──
        self._title_label = QLabel("")
        self._title_label.setObjectName("Title")
        self._title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self._title_label)

        # ── 角色选择 ──
        char_row = QHBoxLayout()
        char_row.setSpacing(6)
        self._char_label = QLabel("")
        self._char_label.setObjectName("SubLabel")
        char_row.addWidget(self._char_label)
        self._char_combo = QComboBox()
        self._char_combo.addItem("", "png")   # placeholder, _apply_language 会填
        self._char_combo.addItem("", "gif")
        self._char_combo.currentIndexChanged.connect(self._on_char_changed)
        char_row.addWidget(self._char_combo, 1)
        main_layout.addLayout(char_row)

        # ── 桌宠大小（纸片卡）──
        self._size_group = QGroupBox("")
        size_layout = QVBoxLayout(self._size_group)
        size_layout.setSpacing(8)
        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(200, 800)
        self._slider.setValue(500)
        self._slider.valueChanged.connect(self._on_slider_changed)
        size_row.addWidget(self._slider, 1)
        self._spin = QSpinBox()
        self._spin.setRange(200, 800)
        self._spin.setValue(500)
        self._spin.setSuffix(" px")
        self._spin.setSingleStep(10)
        self._spin.valueChanged.connect(self._on_spin_changed)
        size_row.addWidget(self._spin)
        size_layout.addLayout(size_row)
        main_layout.addWidget(self._size_group)

        # ── 通用设置（纸片卡）──
        self._general_group = QGroupBox("")
        general_layout = QVBoxLayout(self._general_group)
        general_layout.setSpacing(8)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        self._lang_label = QLabel("")
        self._lang_label.setObjectName("SubLabel")
        lang_row.addWidget(self._lang_label)
        self._language_combo = QComboBox()
        self._language_combo.addItem("中文", "zh")
        self._language_combo.addItem("English", "en")
        self._language_combo.addItem("日本語", "ja")
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(self._language_combo, 1)
        general_layout.addLayout(lang_row)

        auto_start_row = QHBoxLayout()
        self._auto_start_label = QLabel("")
        self._auto_start_label.setObjectName("SubLabel")
        auto_start_row.addWidget(self._auto_start_label)
        auto_start_row.addStretch()
        self._auto_start_btn = QPushButton("")
        self._auto_start_btn.setCheckable(True)
        self._auto_start_btn.setFixedSize(56, 28)
        self._auto_start_btn.clicked.connect(self._on_auto_start_toggle)
        style_toggle(self._auto_start_btn, False)
        auto_start_row.addWidget(self._auto_start_btn)
        general_layout.addLayout(auto_start_row)
        main_layout.addWidget(self._general_group)

        # ── QStackedWidget ──
        self._stack = QStackedWidget()
        self._png_page = self._build_png_page()
        self._stack.addWidget(self._png_page)
        self._gif_page = GifSettingsPage()
        self._stack.addWidget(self._gif_page)
        main_layout.addWidget(self._stack, 1)

        # 禁止 ComboBox 响应鼠标滚轮（让滚轮只负责滚动面板）
        self._block_combo_wheel(self._png_page)
        self._block_combo_wheel(self._gif_page)

        # ── 底部按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        self._save_btn = QPushButton("")
        self._save_btn.setObjectName("PrimaryBtn")
        self._save_btn.clicked.connect(self._on_save_and_exit)
        btn_row.addWidget(self._save_btn)
        self._close_btn = QPushButton("")
        self._close_btn.clicked.connect(self._try_close)
        btn_row.addWidget(self._close_btn)
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        self._apply_language()

    # ── PNG 页面 ──

    def _build_png_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        self._anim_group = QGroupBox("")
        inner = QVBoxLayout(self._anim_group)
        inner.setSpacing(8)

        idle_row = QHBoxLayout()
        self._idle_sub = QLabel("")
        self._idle_sub.setObjectName("SubLabel")
        idle_row.addWidget(self._idle_sub)
        self._idle_combo = QComboBox()
        self._idle_combo.currentTextChanged.connect(self._on_animations_changed)
        idle_row.addWidget(self._idle_combo, 1)
        inner.addLayout(idle_row)

        hover_row = QHBoxLayout()
        self._hover_sub = QLabel("")
        self._hover_sub.setObjectName("SubLabel")
        hover_row.addWidget(self._hover_sub)
        self._hover_combo = QComboBox()
        self._hover_combo.currentTextChanged.connect(self._on_animations_changed)
        hover_row.addWidget(self._hover_combo, 1)
        inner.addLayout(hover_row)

        layout.addWidget(self._anim_group)
        layout.addStretch()
        return page

    # ── 绘制 ──

    def paintEvent(self, event):
        """奶白纸片 + 2px 暖棕描边 + 暖色投影（与所有弹层同一套笔触）。"""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            theme.paint_paper(painter, self.visible_rect())
        finally:
            painter.end()

    def visible_rect(self):
        """看得见的纸片在本窗口内的矩形。"""
        from PySide6.QtCore import QRect
        return QRect(MARGIN, MARGIN, VISIBLE_W, VISIBLE_H)

    # ── 弹出 ──

    def popup_at(self, pet_geometry):
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        width, height = VISIBLE_W, VISIBLE_H
        direction = "up"
        y = pet_geometry.top() - height - 10 - MARGIN
        if y + MARGIN < screen.top():
            y = pet_geometry.bottom() + 10 - MARGIN
            direction = "down"
        x = pet_geometry.center().x() - width // 2 - MARGIN
        if x + MARGIN < screen.left():
            x = screen.left() - MARGIN + 4
        elif x + MARGIN + width > screen.right() + 1:
            x = screen.right() - width - MARGIN - 3

        self._popup_direction = direction
        self._take_snapshot()
        self.activateWindow()
        animate_panel_show(self, QPoint(int(x), int(y)), direction)

    def hide_with_anim(self):
        if not self.isVisible():
            return
        direction = getattr(self, "_popup_direction", "up")
        animate_panel_hide(self, direction)

    # ── PNG 页面接口 ──

    def set_animations(self, animations, current_idle, current_hover):
        self._idle_combo.blockSignals(True)
        self._hover_combo.blockSignals(True)
        self._idle_combo.clear()
        self._hover_combo.clear()
        for key in animations:
            self._idle_combo.addItem(key)
            self._hover_combo.addItem(key)
        if current_idle in animations:
            self._idle_combo.setCurrentText(current_idle)
        elif animations:
            self._idle_combo.setCurrentIndex(0)
        if current_hover in animations:
            self._hover_combo.setCurrentText(current_hover)
        elif animations:
            self._hover_combo.setCurrentIndex(0)
        self._idle_combo.blockSignals(False)
        self._hover_combo.blockSignals(False)

    def set_height(self, height: int):
        self._slider.blockSignals(True)
        self._spin.blockSignals(True)
        self._slider.setValue(height)
        self._spin.setValue(height)
        self._slider.blockSignals(False)
        self._spin.blockSignals(False)

    def set_auto_start(self, enabled: bool):
        self._auto_start_btn.setChecked(enabled)
        style_toggle(self._auto_start_btn, enabled)
        self._auto_start_btn.setText(
            self._tr("auto_on") if enabled else self._tr("auto_off"))

    # ── 国际化 ──

    def _tr(self, key: str) -> str:
        return tr(key, self._current_lang)

    def _apply_language(self):
        """刷新所有 UI 文字为当前语言"""
        # 标题
        self._title_label.setText(self._tr("title"))
        # 角色
        self._char_label.setText(self._tr("char_label"))
        self._char_combo.setItemText(0, self._tr("char_png"))
        self._char_combo.setItemText(1, self._tr("char_gif"))
        # 分组标题（纸片卡上的藏青粗体）
        self._size_group.setTitle(self._tr("size_label"))
        self._general_group.setTitle(self._tr("general_label"))
        self._lang_label.setText(self._tr("lang_label"))
        self._auto_start_label.setText(self._tr("auto_start_label"))
        self._auto_start_btn.setText(
            self._tr("auto_on") if self._auto_start_btn.isChecked() else self._tr("auto_off"))
        # PNG 页面
        if hasattr(self, '_anim_group'):
            self._anim_group.setTitle(self._tr("anim_label"))
            self._idle_sub.setText(self._tr("idle_label"))
            self._hover_sub.setText(self._tr("hover_label"))
        # 按钮
        self._save_btn.setText(self._tr("save_btn"))
        self._close_btn.setText(self._tr("close_btn"))
        # GIF 设置页
        if hasattr(self, '_gif_page'):
            self._gif_page.apply_language(self._current_lang)

    # ── Q版页面接口 ──

    def set_gif_actions(self, actions: list[str]):
        self._gif_page.set_actions(actions)

    def load_gif_settings(self, settings: dict):
        self._gif_page.load_settings(settings)

    def get_gif_settings(self) -> dict:
        return self._gif_page.get_settings()

    def set_character_type(self, char_type: str):
        """外部设置当前角色类型"""
        idx = self._char_combo.findData(char_type)
        if idx >= 0:
            self._char_combo.blockSignals(True)
            self._char_combo.setCurrentIndex(idx)
            self._char_combo.blockSignals(False)
            self._stack.setCurrentIndex(idx)

    # ── 快照 ──

    def _take_snapshot(self):
        self._snap = {
            "height": self._slider.value(),
            "idle": self._idle_combo.currentText(),
            "hover": self._hover_combo.currentText(),
            "auto_start": self._auto_start_btn.isChecked(),
            "char_type": self._char_combo.currentData(),
            "language": self._language_combo.currentData(),
        }
        if self._char_combo.currentData() == "gif":
            self._snap["gif_settings"] = self._gif_page.get_settings()

    def _has_changes(self):
        snap = getattr(self, "_snap", None)
        if snap is None:
            return False
        if (snap["height"] != self._slider.value()
                or snap["idle"] != self._idle_combo.currentText()
                or snap["hover"] != self._hover_combo.currentText()
                or snap["auto_start"] != self._auto_start_btn.isChecked()
                or snap["char_type"] != self._char_combo.currentData()
                or snap["language"] != self._language_combo.currentData()):
            return True
        if self._char_combo.currentData() == "gif" and "gif_settings" in snap:
            if snap["gif_settings"] != self._gif_page.get_settings():
                return True
        return False

    # ── 内部槽 ──

    def _on_char_changed(self, _idx):
        char_type = self._char_combo.currentData()
        self._stack.setCurrentIndex(1 if char_type == "gif" else 0)
        self.character_type_changed.emit(char_type)

    def _on_save_and_exit(self):
        self.save_clicked.emit()
        self.hide_with_anim()

    def _try_close(self):
        if self._has_changes():
            result = QMessageBox.question(
                self, self._tr("msgbox_title"),
                self._tr("msgbox_text"),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if result == QMessageBox.Save:
                self.save_clicked.emit()
                self.hide_with_anim()
            elif result == QMessageBox.Discard:
                self.close_without_save.emit()
                self.hide_with_anim()
        else:
            self.close_without_save.emit()
            self.hide_with_anim()

    def _on_animations_changed(self):
        idle_key = self._idle_combo.currentText()
        hover_key = self._hover_combo.currentText()
        if idle_key and hover_key:
            self.animations_changed.emit(idle_key, hover_key)

    def _on_slider_changed(self, val):
        self._spin.blockSignals(True)
        self._spin.setValue(val)
        self._spin.blockSignals(False)
        self.height_changed.emit(val)

    def _on_spin_changed(self, val):
        self._slider.blockSignals(True)
        self._slider.setValue(val)
        self._slider.blockSignals(False)
        self.height_changed.emit(val)

    def _on_auto_start_toggle(self, checked):
        style_toggle(self._auto_start_btn, checked)
        self._auto_start_btn.setText(
            self._tr("auto_on") if checked else self._tr("auto_off"))
        self.auto_start_changed.emit(checked)

    def _on_language_changed(self, _idx):
        self._current_lang = self._language_combo.currentData()
        self._apply_language()
        self.language_changed.emit(self._current_lang)

    def set_language(self, lang: str):
        idx = self._language_combo.findData(lang)
        if idx >= 0:
            self._language_combo.blockSignals(True)
            self._language_combo.setCurrentIndex(idx)
            self._language_combo.blockSignals(False)
            self._current_lang = lang
            self._apply_language()

    def _block_combo_wheel(self, widget):
        """递归安装滚轮拦截器到所有 QComboBox"""
        for combo in widget.findChildren(QComboBox):
            combo.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, QComboBox):
            event.ignore()
            return True
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        self._try_close()
        super().focusOutEvent(event)


def style_toggle(btn: QPushButton, active: bool):
    """「开机自启」那类二元按钮的开关配色（规范 1.1：开=樱花粉，关=奶白-深）。"""
    if active:
        btn.setStyleSheet(
            f"QPushButton {{ background: {theme.PINK}; color: {theme.NAVY};"
            f" border: 2px solid {theme.PINK_DEEP}; border-radius: 14px;"
            " font-size: 12px; font-weight: bold; font-family: 'Microsoft YaHei'; }"
            f"QPushButton:hover {{ background: {theme.PINK_DEEP}; color: #FFFFFF; }}"
        )
    else:
        btn.setStyleSheet(
            f"QPushButton {{ background: {theme.CREAM}; color: {theme.TEXT_DIM};"
            f" border: 2px solid {theme.OUTLINE_LIGHT}; border-radius: 14px;"
            " font-size: 12px; font-family: 'Microsoft YaHei'; }"
            f"QPushButton:hover {{ border-color: {theme.PINK_DEEP}; }}"
        )
