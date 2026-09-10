"""Q版专用设置页——启动序列、行为映射、鼠标映射、AFK 池。

2026-09-10 全局换肤：**删掉了这里原有的 ~13 处内联样式表**（全是冷蓝底那套）。
现在配色统一来自 `ui_theme.app_stylesheet()`（由 `SettingsWindow` 设在自己身上，
子控件继承），单靠 `setObjectName` 就能对上样式。

**为什么不全改成自绘控件**：这一页有 9 个下拉框、4 个数字框、若干勾选框与列表，
逐个自绘是天级工作量，而 QSS 能覆盖 95% 的观感。分工是：
**自绘负责"造型"（纸片、圆角、描边、投影），QSS 负责"配色"。**
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QListWidget, QListWidgetItem,
    QCheckBox, QSpinBox, QScrollArea, QGroupBox, QGridLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from src.translations import tr


class GifSettingsPage(QScrollArea):
    """Q版角色完整设置页面，嵌入 SettingsWindow 的 QStackedWidget"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_lang = "zh"
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._all_actions: list[str] = []
        self._mapping_labels: list[tuple[QLabel, str]] = []  # (label, tr_key)

        # 外层容器
        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)

        # ── 启动序列 ──
        self._build_startup_section()

        # ── 待机循环 ──
        self._build_idle_section()

        # ── 行为检测映射 ──
        self._build_behavior_section()

        # ── 鼠标交互映射 ──
        self._build_mouse_section()

        # ── AFK 随机 ──
        self._build_afk_section()

        self._layout.addStretch()
        self.setWidget(container)
        self._apply_language()

    # ── 启动序列 ──

    def _build_startup_section(self):
        self._startup_gb = QGroupBox("")
        self._layout.addWidget(self._startup_gb)
        ly = QVBoxLayout(self._startup_gb)
        ly.setSpacing(4)

        self._startup_list = QListWidget()
        self._startup_list.setMaximumHeight(100)
        ly.addWidget(self._startup_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._startup_add_combo = QComboBox()
        self._startup_add_combo.setMinimumHeight(24)
        btn_row.addWidget(self._startup_add_combo, 1)

        self._add_btn = QPushButton("")
        self._add_btn.setObjectName("SmallBtn")
        self._add_btn.clicked.connect(self._on_startup_add)
        btn_row.addWidget(self._add_btn)

        self._remove_btn = QPushButton("")
        self._remove_btn.setObjectName("SmallBtn")
        self._remove_btn.clicked.connect(self._on_startup_remove)
        btn_row.addWidget(self._remove_btn)

        up_btn = QPushButton("▲")
        up_btn.setObjectName("SmallBtn")
        up_btn.setFixedWidth(30)
        up_btn.clicked.connect(self._on_startup_up)
        btn_row.addWidget(up_btn)

        down_btn = QPushButton("▼")
        down_btn.setObjectName("SmallBtn")
        down_btn.setFixedWidth(30)
        down_btn.clicked.connect(self._on_startup_down)
        btn_row.addWidget(down_btn)

        ly.addLayout(btn_row)

    def _on_startup_add(self):
        action = self._startup_add_combo.currentText()
        if action:
            self._startup_list.addItem(action)

    def _on_startup_remove(self):
        row = self._startup_list.currentRow()
        if row >= 0:
            self._startup_list.takeItem(row)

    def _on_startup_up(self):
        row = self._startup_list.currentRow()
        if row > 0:
            item = self._startup_list.takeItem(row)
            self._startup_list.insertItem(row - 1, item)
            self._startup_list.setCurrentRow(row - 1)

    def _on_startup_down(self):
        row = self._startup_list.currentRow()
        if row < self._startup_list.count() - 1:
            item = self._startup_list.takeItem(row)
            self._startup_list.insertItem(row + 1, item)
            self._startup_list.setCurrentRow(row + 1)

    # ── 待机循环 ──

    def _build_idle_section(self):
        self._idle_gb = QGroupBox("")
        self._layout.addWidget(self._idle_gb)
        ly = QVBoxLayout(self._idle_gb)
        ly.setSpacing(6)
        self._combo_idle = self._add_mapping_row(ly, "idle_action")
        # 夜间睡眠待机仅保留开关（时段固定：23:00-24:00 准备 / 0:00-6:00 睡觉）
        self._chk_sleep_enabled = QCheckBox("")
        ly.addWidget(self._chk_sleep_enabled)

    # ── 行为检测映射（勾选启用，取消禁用）──

    def _build_behavior_section(self):
        self._behavior_gb = QGroupBox("")
        self._layout.addWidget(self._behavior_gb)
        ly = QVBoxLayout(self._behavior_gb)
        ly.setSpacing(6)

        self._chk_key_press = QCheckBox("")
        ly.addWidget(self._chk_key_press)

        self._chk_audio_play = QCheckBox("")
        ly.addWidget(self._chk_audio_play)

        self._chk_audio_muted = QCheckBox("")
        ly.addWidget(self._chk_audio_muted)

        # 保存引用以支持语言切换
        self._behavior_checkboxes = [
            (self._chk_key_press, "key_press"),
            (self._chk_audio_play, "audio_play"),
            (self._chk_audio_muted, "audio_muted"),
        ]

    def _add_mapping_row(self, parent_layout, tr_key):
        row = QHBoxLayout()
        row.setSpacing(6)
        lbl = QLabel("")
        lbl.setObjectName("MapLabel")
        row.addWidget(lbl)
        self._mapping_labels.append((lbl, tr_key))
        combo = QComboBox()
        row.addWidget(combo, 1)
        parent_layout.addLayout(row)
        return combo

    # ── 鼠标交互映射 ──

    def _build_mouse_section(self):
        self._mouse_gb = QGroupBox("")
        self._layout.addWidget(self._mouse_gb)
        ly = QVBoxLayout(self._mouse_gb)
        ly.setSpacing(6)

        self._combo_hover = self._add_mapping_row(ly, "hover_action")
        self._combo_long_hover = self._add_mapping_row(ly, "long_hover")
        self._combo_click = self._add_mapping_row(ly, "click_action")
        self._combo_panel = self._add_mapping_row(ly, "panel_button")
        self._combo_close = self._add_mapping_row(ly, "close_no_save")

        # 双击序列
        dbl_row = QHBoxLayout()
        dbl_row.setSpacing(6)
        self._dbl_label = QLabel("")
        self._dbl_label.setObjectName("MapLabel")
        dbl_row.addWidget(self._dbl_label)
        self._combo_dbl_1 = QComboBox()
        dbl_row.addWidget(self._combo_dbl_1, 1)
        arrow = QLabel("→")
        arrow.setObjectName("DimLabel")
        arrow.setFixedWidth(16)
        dbl_row.addWidget(arrow)
        self._combo_dbl_2 = QComboBox()
        dbl_row.addWidget(self._combo_dbl_2, 1)
        ly.addLayout(dbl_row)

    # ── AFK 随机 ──

    def _build_afk_section(self):
        self._afk_gb = QGroupBox("")
        self._layout.addWidget(self._afk_gb)
        ly = QVBoxLayout(self._afk_gb)
        ly.setSpacing(6)

        self._afk_enabled_check = QCheckBox("")
        ly.addWidget(self._afk_enabled_check)

        # 超时
        tout_row = QHBoxLayout()
        tout_row.setSpacing(6)
        self._afk_timeout_label = QLabel("")
        self._afk_timeout_label.setObjectName("MapLabel")
        tout_row.addWidget(self._afk_timeout_label)
        self._afk_timeout_spin = QSpinBox()
        self._afk_timeout_spin.setRange(5, 300)
        self._afk_timeout_spin.setSuffix("")
        tout_row.addWidget(self._afk_timeout_spin)
        tout_row.addStretch()
        ly.addLayout(tout_row)

        # 随机间隔
        intv_row = QHBoxLayout()
        intv_row.setSpacing(6)
        self._afk_interval_label = QLabel("")
        self._afk_interval_label.setObjectName("MapLabel")
        intv_row.addWidget(self._afk_interval_label)
        self._afk_min_spin = QSpinBox()
        self._afk_min_spin.setRange(10, 600)
        self._afk_min_spin.setSuffix("")
        intv_row.addWidget(self._afk_min_spin)
        intv_row.addWidget(QLabel("~"))
        self._afk_max_spin = QSpinBox()
        self._afk_max_spin.setRange(10, 600)
        self._afk_max_spin.setSuffix("")
        intv_row.addWidget(self._afk_max_spin)
        intv_row.addStretch()
        ly.addLayout(intv_row)

        # 动画池
        self._afk_pool_label = QLabel("")
        self._afk_pool_label.setObjectName("MapLabel")
        ly.addWidget(self._afk_pool_label)

        self._afk_grid = QGridLayout()
        self._afk_grid.setSpacing(2)
        ly.addLayout(self._afk_grid)

        self._afk_checkboxes: dict[str, QCheckBox] = {}

    # ── 国际化 ──

    def apply_language(self, lang: str):
        self._current_lang = lang
        self._apply_language()

    def _apply_language(self):
        lang = self._current_lang
        self._startup_gb.setTitle(tr("startup_group", lang))
        self._idle_gb.setTitle(tr("idle_group", lang))
        self._behavior_gb.setTitle(tr("behavior_group", lang))
        self._mouse_gb.setTitle(tr("mouse_group", lang))
        self._afk_gb.setTitle(tr("afk_group", lang))
        self._add_btn.setText(tr("add_btn", lang))
        self._remove_btn.setText(tr("remove_btn", lang))
        self._dbl_label.setText(tr("dbl_click_seq", lang))
        self._chk_sleep_enabled.setText(tr("sleep_enable", lang))
        self._afk_enabled_check.setText(tr("afk_enable", lang))
        self._afk_timeout_label.setText(tr("afk_timeout", lang))
        self._afk_interval_label.setText(tr("afk_interval", lang))
        self._afk_pool_label.setText(tr("afk_pool", lang))
        sec = tr("seconds_suffix", lang)
        self._afk_timeout_spin.setSuffix(sec)
        self._afk_min_spin.setSuffix(sec)
        self._afk_max_spin.setSuffix(sec)
        for lbl, key in self._mapping_labels:
            lbl.setText(tr(key, lang))
        for chk, key in self._behavior_checkboxes:
            chk.setText(tr(key, lang))

    # ── 公共接口 ──

    def set_actions(self, actions: list[str]):
        """填充所有下拉框和复选框的可选项"""
        self._all_actions = list(actions)
        combos = [
            self._startup_add_combo, self._combo_idle,
            self._combo_hover, self._combo_long_hover, self._combo_click,
            self._combo_panel, self._combo_close,
            self._combo_dbl_1, self._combo_dbl_2,
        ]
        for cb in combos:
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(actions)
            cb.blockSignals(False)

        # AFK 池复选框
        self._afk_checkboxes.clear()
        # 清除旧控件
        for i in reversed(range(self._afk_grid.count())):
            self._afk_grid.itemAt(i).widget().deleteLater()

        cols = 3
        for i, action in enumerate(actions):
            cb = QCheckBox(action)
            cb.setObjectName("PoolCheck")
            self._afk_checkboxes[action] = cb
            self._afk_grid.addWidget(cb, i // cols, i % cols)

    def load_settings(self, settings: dict):
        """从 GifCharacter.get_settings() 加载值"""

        def _select(combo, value):
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        # 启动序列
        self._startup_list.clear()
        for action in settings.get("startup_sequence", []):
            self._startup_list.addItem(action)

        # 待机
        _select(self._combo_idle, settings.get("idle", ""))

        # 行为检测——勾选框（向后兼容：旧格式字符串值视为启用）
        kp = settings.get("key_press", True)
        self._chk_key_press.setChecked(kp if isinstance(kp, bool) else bool(kp))
        ap = settings.get("audio_playing", True)
        self._chk_audio_play.setChecked(ap if isinstance(ap, bool) else bool(ap))
        am = settings.get("audio_muted", True)
        self._chk_audio_muted.setChecked(am if isinstance(am, bool) else bool(am))

        # 鼠标映射
        _select(self._combo_hover, settings.get("hover", ""))
        _select(self._combo_long_hover, settings.get("long_hover", ""))
        _select(self._combo_click, settings.get("click", ""))
        _select(self._combo_panel, settings.get("panel", ""))
        _select(self._combo_close, settings.get("close", ""))

        dbl_seq = settings.get("dbl_click_seq", [])
        if len(dbl_seq) > 0:
            _select(self._combo_dbl_1, dbl_seq[0])
        if len(dbl_seq) > 1:
            _select(self._combo_dbl_2, dbl_seq[1])

        # AFK
        self._afk_enabled_check.setChecked(settings.get("afk_enabled", True))
        self._afk_timeout_spin.setValue(settings.get("afk_timeout_ms", 30000) // 1000)
        self._afk_min_spin.setValue(settings.get("afk_min_ms", 60000) // 1000)
        self._afk_max_spin.setValue(settings.get("afk_max_ms", 180000) // 1000)

        pool = set(settings.get("afk_pool", []))
        for action, cb in self._afk_checkboxes.items():
            cb.setChecked(action in pool)

        # 夜间睡眠（仅开关）
        self._chk_sleep_enabled.setChecked(settings.get("sleep_enabled", False))

    def get_settings(self) -> dict:
        """收集当前 UI 值，返回 settings dict"""
        startup = []
        for i in range(self._startup_list.count()):
            startup.append(self._startup_list.item(i).text())

        dbl1 = self._combo_dbl_1.currentText()
        dbl2 = self._combo_dbl_2.currentText()
        dbl_seq = [dbl1, dbl2] if dbl1 and dbl2 else ([dbl1] if dbl1 else [])

        pool = [a for a, cb in self._afk_checkboxes.items() if cb.isChecked()]

        return {
            "startup_sequence": startup,
            "idle": self._combo_idle.currentText(),
            "hover": self._combo_hover.currentText(),
            "long_hover": self._combo_long_hover.currentText(),
            "click": self._combo_click.currentText(),
            "dbl_click_seq": dbl_seq,
            "panel": self._combo_panel.currentText(),
            "close": self._combo_close.currentText(),
            "key_press": self._chk_key_press.isChecked(),
            "audio_playing": self._chk_audio_play.isChecked(),
            "audio_muted": self._chk_audio_muted.isChecked(),
            "afk_enabled": self._afk_enabled_check.isChecked(),
            "afk_timeout_ms": self._afk_timeout_spin.value() * 1000,
            "afk_min_ms": self._afk_min_spin.value() * 1000,
            "afk_max_ms": self._afk_max_spin.value() * 1000,
            "afk_pool": pool,
            "sleep_enabled": self._chk_sleep_enabled.isChecked(),
        }
