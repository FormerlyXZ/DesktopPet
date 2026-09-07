"""历史粘贴板窗口——无边框磨砂卡片，正常窗口逻辑（任务栏 + 可缩放 + 可最小化）"""
import os
import shutil
import time
from datetime import datetime

from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtGui import (
    QPainter, QPen, QColor, QPixmap, QIcon, QImage, QMouseEvent, QPainterPath,
    QFont,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QFileDialog,
    QApplication, QSpinBox, QDialog, QListWidget, QListWidgetItem,
    QButtonGroup,
)

from src.clipboard_store import ClipboardStore
from src.config import load as load_config, save as save_config

# 磨砂卡片常量
_CARD_RADIUS = 12
_CARD_BORDER = QColor(187, 222, 251, 120)  # 淡蓝描边

# 可缩放边框宽度（px）
_RESIZE_MARGIN = 8

# 字体大小范围
FONT_MIN = 10
FONT_MAX = 20
FONT_DEFAULT = 13

# 用户上传壁纸的保存目录（与原图解耦，避免原图被删除后壁纸失效）
WALLPAPER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "clipboard_wallpaper",
)


def _make_window_icon() -> QIcon:
    """生成历史粘贴板专属图标：以项目头像为底，叠加一个剪贴板角标。

    返回 QIcon（多尺寸）。素材加载失败时回退到一个手绘的剪贴板图标。
    """
    size = 256  # 高清底图，随后缩到多尺寸
    pm = _render_icon_pixmap(size)
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    return icon


def _render_icon_pixmap(size: int) -> QPixmap:
    """绘制历史粘贴板图标为指定尺寸的 QPixmap（不含缩放）"""
    base = None
    assets_base = os.path.dirname(os.path.dirname(__file__))
    icon_path = os.path.join(assets_base, "素材库", "高木头像.png")
    if os.path.exists(icon_path):
        p = QPixmap(icon_path)
        if not p.isNull():
            base = p

    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)

    # 头像作为圆角底（居中裁剪为方形）
    if base is not None:
        scaled = base.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)
        x = (size - scaled.width()) // 2
        y = (size - scaled.height()) // 2
        clip = QPainterPath()
        clip.addRoundedRect(QRect(0, 0, size, size), size // 5, size // 5)
        painter.setClipPath(clip)
        painter.drawPixmap(x, y, scaled)
        painter.setClipping(False)
    else:
        painter.setBrush(QColor("#E3F2FD"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRect(0, 0, size, size), size // 5, size // 5)

    # 右下角剪贴板角标（相对 size 缩放）
    bw, bh = int(size * 0.53), int(size * 0.63)
    bx, by = size - bw - int(size * 0.03), size - bh - int(size * 0.03)
    r = max(4, int(size * 0.09))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawRoundedRect(QRect(bx, by, bw, bh), r, r)
    # 顶部夹子
    clip_w = int(size * 0.25)
    painter.setBrush(QColor("#42A5F5"))
    painter.drawRoundedRect(
        QRect(bx + bw // 2 - clip_w // 2, by - int(size * 0.06), clip_w, int(size * 0.14)),
        int(size * 0.07), int(size * 0.07),
    )
    # 文字行
    painter.setBrush(QColor(180, 205, 240))
    for i in range(3):
        painter.drawRoundedRect(
            QRect(bx + int(size * 0.11), by + int(size * 0.19) + i * int(size * 0.13),
                  bw - int(size * 0.22), int(size * 0.06)),
            int(size * 0.03), int(size * 0.03),
        )
    painter.end()
    return canvas


def _build_background_pixmap(wallpaper: QPixmap, size: QSize,
                             acrylic_opacity: float) -> QPixmap:
    """渲染亚克力叠底壁纸背景（壁纸透明度固定，仅亚克力叠层可调）。

    分层（自下而上）：
    1. 壁纸图片（若上传），cover 铺满 + 居中裁剪，完整显示（不单独调透明度）
    2. 亚克力磨砂叠层（纯白），不透明度为 acrylic_opacity，保证文字可读
    3. 淡蓝描边
    """
    pm = QPixmap(size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    rect = QRect(0, 0, size.width(), size.height()).adjusted(1, 1, -1, -1)
    clip = QPainterPath()
    clip.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
    painter.setClipPath(clip)

    # 1) 底：壁纸（cover 铺满 + 居中裁剪）
    if wallpaper is not None and not wallpaper.isNull():
        scaled = wallpaper.scaled(
            QSize(rect.width(), rect.height()),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = rect.x() + (rect.width() - scaled.width()) // 2
        y = rect.y() + (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    # 2) 亚克力磨砂叠层
    acrylic = QColor(255, 255, 255)
    acrylic.setAlpha(round(255 * max(0.0, min(1.0, acrylic_opacity))))
    painter.setBrush(acrylic)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

    # 3) 淡蓝描边
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(_CARD_BORDER, 1))
    painter.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

    painter.end()
    return pm


# QSpinBox 样式：显式定义上/下按键子控件，避免原生箭头无法点击
SPINBOX_STYLE = """
QSpinBox {
    background: rgba(245,245,245,0.7);
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
    font-family: "Microsoft YaHei";
    color: #212121;
}
QSpinBox:hover { border: 1px solid #42A5F5; }
QSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border-left: 1px solid #E0E0E0;
    border-top-right-radius: 4px; background: transparent;
}
QSpinBox::up-button:hover { background: #BBDEFB; }
QSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border-left: 1px solid #E0E0E0;
    border-bottom-right-radius: 4px; background: transparent;
}
QSpinBox::down-button:hover { background: #BBDEFB; }
QSpinBox::up-arrow {
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid #757575;
}
QSpinBox::down-arrow {
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #757575;
}
"""


# 基准样式；字体大小（字号）通过 _font_size 动态应用
def _build_style(font_size: int) -> str:
    return f"""
QLineEdit#SearchBox {{
    background: rgba(245, 245, 245, 0.7);
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: {font_size}px;
    font-family: "Microsoft YaHei";
    color: #212121;
}}
QLineEdit#SearchBox:focus {{
    border: 1px solid #42A5F5;
    background: rgba(255, 255, 255, 0.9);
}}
QPushButton#FilterBtn {{
    background: #E0E0E0;
    color: #757575;
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    font-size: {font_size - 1}px;
    font-family: "Microsoft YaHei";
}}
QPushButton#FilterBtn:hover {{
    background: #BBDEFB;
    color: #212121;
}}
QPushButton#FilterBtn:checked {{
    background: #1976D2;
    color: white;
    font-weight: bold;
}}
QPushButton#GearBtn {{
    background: transparent;
    border: none;
    font-size: 16px;
    padding: 2px 4px;
}}
QPushButton#GearBtn:hover {{
    background: rgba(0,0,0,0.06);
    border-radius: 4px;
}}
QLabel#Card {{
    background: rgba(245, 245, 245, 0.6);
    border-radius: 8px;
    padding: 10px 14px;
    font-family: "Microsoft YaHei";
}}
QLabel#TextPreview {{
    font-size: {font_size}px;
    color: #212121;
    font-family: "Microsoft YaHei";
}}
QLabel#Timestamp {{
    font-size: {font_size - 2}px;
    color: #9E9E9E;
    font-family: "Microsoft YaHei";
}}
QLabel#EmptyIcon {{
    font-size: 48px;
    color: #BDBDBD;
}}
QLabel#EmptyText {{
    font-size: {font_size + 1}px;
    color: #9E9E9E;
    font-family: "Microsoft YaHei";
}}
QLabel#EmptySub {{
    font-size: {font_size - 1}px;
    color: #BDBDBD;
    font-family: "Microsoft YaHei";
}}
QToolTip {{
    background: white;
    color: #424242;
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {font_size - 1}px;
    font-family: "Microsoft YaHei";
}}
QLabel#Expander {{
    font-size: {font_size - 1}px;
    color: #42A5F5;
    font-family: "Microsoft YaHei";
}}
QLabel#Expander:hover {{
    color: #1E88E5;
}}
"""


class ClipboardWindow(QWidget):
    def __init__(self, store: ClipboardStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setObjectName("ClipboardWindow")

        # 正常窗口逻辑：无边框卡片 + 任务栏可显示 + 非置顶
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("历史粘贴板")
        self.setWindowIcon(_make_window_icon())
        self.setMinimumSize(480, 400)
        self.resize(560, 620)
        # 开启鼠标追踪：无按键悬停时也能收到 mouseMoveEvent，用于边缘缩放光标提示
        self.setMouseTracking(True)

        self._drag_pos: QPoint | None = None       # 标题栏拖拽位移
        self._resize_edge: str | None = None       # 缩放方向 left/top/right/bottom...
        self._resize_start_geom: QRect | None = None
        self._resize_start_global: QPoint | None = None
        self._filter_buttons: list[QPushButton] = []
        self._current_filter_days = 0  # 0 = 全部
        self._show_relative_time = False

        # 字体大小
        self._font_size = self._load_font_size()

        # 背景：壁纸 + 亚克力叠层
        self._load_background_config()

        self.setStyleSheet(_build_style(self._font_size))
        self._build_ui()
        self._refresh_list()

    # ── 背景配置（壁纸 + 亚克力叠层，无壁纸透明度）──

    def _load_background_config(self):
        """读取 config.json 中的背景设置，加载壁纸图片与亚克力叠层不透明度"""
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        cb = cfg.get("clipboard", {}) if isinstance(cfg, dict) else {}

        self._wallpaper_path = cb.get("wallpaper_path", "") or ""
        # config 存储 0-100 整数，内部换算为 0.0-1.0
        self._acrylic_opacity = (cb.get("acrylic_opacity", 55) or 55) / 100.0

        self._wallpaper = QPixmap()
        if self._wallpaper_path and os.path.exists(self._wallpaper_path):
            loaded = QPixmap(self._wallpaper_path)
            if not loaded.isNull():
                self._wallpaper = loaded

    def apply_background_style(self, wallpaper_path: str,
                               acrylic_opacity_pct: int):
        """由设置对话框调用：更新背景并持久化到 config.json"""
        self._wallpaper_path = wallpaper_path or ""
        self._acrylic_opacity = max(0, min(100, int(acrylic_opacity_pct))) / 100.0

        self._wallpaper = QPixmap()
        if self._wallpaper_path and os.path.exists(self._wallpaper_path):
            loaded = QPixmap(self._wallpaper_path)
            if not loaded.isNull():
                self._wallpaper = loaded

        # 持久化
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        clip = cfg.setdefault("clipboard", {})
        clip["wallpaper_path"] = self._wallpaper_path
        clip["acrylic_opacity"] = round(self._acrylic_opacity * 100)
        try:
            save_config(cfg)
        except Exception:
            pass

        self.update()

    # ── 字体设置 ──

    @staticmethod
    def _load_font_size() -> int:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        cb = cfg.get("clipboard", {}) if isinstance(cfg, dict) else {}
        val = cb.get("font_size", FONT_DEFAULT)
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = FONT_DEFAULT
        return max(FONT_MIN, min(FONT_MAX, val))

    def apply_font_size(self, size: int):
        """设置对话框调用：更新字体大小并持久化"""
        size = max(FONT_MIN, min(FONT_MAX, int(size)))
        self._font_size = size
        self.setStyleSheet(_build_style(size))
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        clip = cfg.setdefault("clipboard", {})
        clip["font_size"] = size
        try:
            save_config(cfg)
        except Exception:
            pass
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
        bg = _build_background_pixmap(
            self._wallpaper, self.size(), self._acrylic_opacity,
        )
        painter.drawPixmap(0, 0, bg)

    # ── 缩放 & 拖拽（无边框窗口需手写）──

    def _resize_direction(self, pos: QPoint) -> str | None:
        """根据鼠标在窗口内的位置，判断应触发的缩放方向"""
        w, h = self.width(), self.height()
        m = _RESIZE_MARGIN
        left = pos.x() <= m
        right = pos.x() >= w - m
        top = pos.y() <= m
        bottom = pos.y() >= h - m

        if top and left:
            return "topleft"
        if top and right:
            return "topright"
        if bottom and left:
            return "bottomleft"
        if bottom and right:
            return "bottomright"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    @staticmethod
    def _cursor_for_edge(edge: str) -> Qt.CursorShape:
        if edge in ("topleft", "bottomright"):
            return Qt.SizeFDiagCursor
        if edge in ("topright", "bottomleft"):
            return Qt.SizeBDiagCursor
        if edge in ("left", "right"):
            return Qt.SizeHorCursor
        if edge in ("top", "bottom"):
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            edge = self._resize_direction(pos)
            if edge is not None:
                self._resize_edge = edge
                self._resize_start_geom = self.geometry()
                self._resize_start_global = event.globalPosition().toPoint()
                return
            # 仅在标题栏区域允许拖拽
            if pos.y() < self._title_bar_height():
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        if self._resize_edge is not None:
            self._perform_resize(event.globalPosition().toPoint())
            return
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            super().mouseMoveEvent(event)
            return
        # 悬停时切换缩放光标（边缘/角落 → 双向箭头）
        edge = self._resize_direction(pos)
        if edge is not None:
            self.setCursor(self._cursor_for_edge(edge))
        else:
            self.unsetCursor()  # 回到默认箭头
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        # 鼠标移出窗口时恢复默认光标，避免残留缩放光标
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._resize_edge = None
        self._resize_start_geom = None
        self._resize_start_global = None
        self._drag_pos = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def _perform_resize(self, global_pos: QPoint):
        start_geom = self._resize_start_geom
        if start_geom is None:
            return
        dx = global_pos.x() - self._resize_start_global.x()
        dy = global_pos.y() - self._resize_start_global.y()

        x, y, w, h = start_geom.x(), start_geom.y(), start_geom.width(), start_geom.height()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        e = self._resize_edge

        if "left" in e:
            nw = max(min_w, w - dx)
            x = start_geom.right() + 1 - nw
            w = nw
        if "right" in e:
            nw = max(min_w, w + dx)
            x = start_geom.x()
            w = nw
        if "top" in e:
            nh = max(min_h, h - dy)
            y = start_geom.bottom() + 1 - nh
            h = nh
        if "bottom" in e:
            nh = max(min_h, h + dy)
            y = start_geom.y()
            h = nh

        self.setGeometry(x, y, w, h)

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
        # 横向策略 Ignored：容器宽度始终等于视口宽度，不被子项 sizeHint 撑大。
        # 否则长文本（如无空格的 URL/API key）会让容器宽度膨胀到 1400px+，
        # 横向滚动条被禁用后卡片右侧（置顶/删除按钮）会被裁掉。
        self._list_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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

        # 最小化
        min_btn = QPushButton("–")
        min_btn.setFixedSize(28, 28)
        min_btn.setStyleSheet(
            "QPushButton { font-size: 14px; color: #9E9E9E; border: none; "
            "border-radius: 4px; background: transparent; }"
            "QPushButton:hover { background: rgba(0,0,0,0.08); color: #424242; }"
        )
        min_btn.clicked.connect(self.showMinimized)
        row.addWidget(min_btn)

        # 关闭
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { font-size: 14px; color: #9E9E9E; border: none; "
            "border-radius: 4px; background: transparent; }"
            "QPushButton:hover { background: rgba(239,83,80,0.12); color: #EF5350; }"
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
        gear_btn.setToolTip("历史粘贴板设置")
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
            # 垂直顶对齐：QLabel 默认 AlignVCenter，内容被限高裁剪时会整块居中绘制，
            # 导致折叠后显示的是中间几行、开头被裁掉。置顶后折叠只露出文字最上面 3 行。
            text_preview.setAlignment(Qt.AlignLeft | Qt.AlignTop)
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
                # 可用宽度 = 卡片内容区宽度（视口 - 卡片左右内边距 12+12），
                # 避免窗口较窄或出现纵向滚动条时图片超出卡片被右侧裁剪。
                avail_w = max(self._scroll.viewport().width() - 24, 100)
                max_w = min(avail_w, 470)
                max_h = 350
                if orig_w > max_w or orig_h > max_h:
                    pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(pix)
                label.setMaximumWidth(max_w)
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
        dialog = SettingsDialog(self._store, self)
        dialog.exec()
        self._store.cleanup_expired(self._store.get_cleanup_days())
        self._refresh_list()


class SettingsDialog(QDialog):
    """历史粘贴板设置：背景样式（壁纸 + 亚克力叠层）+ 字体大小 + 自动清理"""

    def __init__(self, store: ClipboardStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._parent_window = parent
        self.setWindowTitle("历史粘贴板设置")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(460, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("历史粘贴板设置")
        title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        layout.addWidget(title)

        # ── 背景样式（壁纸 + 亚克力叠层，未上传墙纸则不显示壁纸）──
        layout.addLayout(self._build_background_section())

        # 分隔线
        sep1 = QLabel()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background: #E0E0E0;")
        layout.addWidget(sep1)

        # ── 字体大小 ──
        layout.addLayout(self._build_font_section())

        # 分隔线
        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: #E0E0E0;")
        layout.addWidget(sep2)

        # ── 自动清理 ──
        layout.addLayout(self._build_cleanup_section())

        layout.addStretch()

        # 底部按钮
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #757575; "
            "border: 1px solid #E0E0E0; border-radius: 6px; "
            "padding: 7px 18px; font-size: 13px; font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { background: rgba(0,0,0,0.04); color: #424242; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
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

    # ── 背景样式区块（壁纸 + 亚克力叠层，无壁纸透明度）──

    def _build_background_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)

        head = QLabel("背景样式")
        head.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        box.addWidget(head)

        desc = QLabel("上传本地壁纸图片作为背景，亚克力磨砂叠层保证文字清晰可读。")
        desc.setStyleSheet(
            "font-size: 12px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        desc.setWordWrap(True)
        box.addWidget(desc)

        # 壁纸选择行
        img_row = QHBoxLayout()
        self._img_label = QLabel("未选择图片")
        self._img_label.setStyleSheet(
            "font-size: 12px; color: #9E9E9E; font-family: 'Microsoft YaHei';"
        )
        self._img_label.setWordWrap(True)
        img_row.addWidget(self._img_label, 1)

        pick_btn = QPushButton("选择图片")
        pick_btn.setStyleSheet(
            "QPushButton { background: #E3F2FD; color: #1565C0; border: 1px solid #90CAF9; "
            "border-radius: 4px; padding: 4px 10px; font-size: 12px; "
            "font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { background: #BBDEFB; }"
        )
        pick_btn.clicked.connect(self._on_pick_image)
        img_row.addWidget(pick_btn)

        clear_btn = QPushButton("清除")
        clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #757575; "
            "border: 1px solid #E0E0E0; border-radius: 4px; padding: 4px 10px; "
            "font-size: 12px; font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { color: #EF5350; border-color: #EF5350; }"
        )
        clear_btn.clicked.connect(self._on_clear_image)
        img_row.addWidget(clear_btn)
        box.addLayout(img_row)

        # 亚克力叠层透明度滑块（唯一透明度控制）
        box.addLayout(self._build_acrylic_slider())

        # 壁纸库（历史上的上传统一管理）
        box.addLayout(self._build_wallpaper_library())

        # 预览
        prev_label = QLabel("预览：")
        prev_label.setStyleSheet(
            "font-size: 12px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        box.addWidget(prev_label)

        self._prev = QLabel()
        self._prev.setFixedSize(410, 90)
        self._prev.setAlignment(Qt.AlignCenter)
        self._update_preview()
        box.addWidget(self._prev)

        return box

    def _build_acrylic_slider(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("亚克力叠层")
        label.setStyleSheet(
            "font-size: 12px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        label.setFixedWidth(76)
        row.addWidget(label)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setFixedWidth(180)
        slider.setValue(round(self._parent_window._acrylic_opacity * 100))
        slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #E0E0E0; "
            "border-radius: 2px; }"
            "QSlider::handle:horizontal { width: 14px; margin: -5px 0; "
            "background: #42A5F5; border-radius: 7px; }"
            "QSlider::sub-page:horizontal { background: #90CAF9; border-radius: 2px; }"
        )
        self._acrylic_slider = slider
        slider.valueChanged.connect(self._on_acrylic_changed)
        row.addWidget(slider)

        value_label = QLabel(f"{slider.value()}%")
        value_label.setStyleSheet(
            "font-size: 12px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        value_label.setFixedWidth(38)
        self._acrylic_value = value_label
        row.addWidget(value_label)
        row.addStretch()
        return row

    def _build_wallpaper_library(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)

        lib_head = QLabel("壁纸库")
        lib_head.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        box.addWidget(lib_head)

        lib_desc = QLabel("历史上传过的壁纸，单击缩略图设为当前壁纸")
        lib_desc.setStyleSheet(
            "font-size: 11px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        lib_desc.setWordWrap(True)
        box.addWidget(lib_desc)

        # 横向缩略图列表
        self._lib_list = QListWidget()
        self._lib_list.setFlow(QListWidget.LeftToRight)
        self._lib_list.setWrapping(False)
        self._lib_list.setFixedHeight(92)
        self._lib_list.setIconSize(QSize(72, 72))
        self._lib_list.setSpacing(6)
        self._lib_list.setSelectionMode(QListWidget.SingleSelection)
        self._lib_list.setViewMode(QListWidget.IconMode)
        self._lib_list.setStyleSheet(
            "QListWidget { background: rgba(245,245,245,0.5); border: 1px solid #E0E0E0; "
            "border-radius: 6px; padding: 4px; }"
            "QListWidget::item { background: transparent; border-radius: 4px; }"
            "QListWidget::item:selected { background: rgba(66,165,245,0.2); "
            "border: 1px solid #42A5F5; }"
            "QListWidget::item:hover { background: rgba(66,165,245,0.10); }"
        )
        self._lib_list.itemClicked.connect(self._on_library_clicked)
        box.addWidget(self._lib_list)

        # 删除选中
        del_row = QHBoxLayout()
        del_row.addStretch()
        del_lib_btn = QPushButton("删除选中")
        del_lib_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #EF5350; "
            "border: 1px solid #EF5350; border-radius: 4px; padding: 3px 10px; "
            "font-size: 11px; font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { background: rgba(239,83,80,0.08); }"
        )
        del_lib_btn.clicked.connect(self._on_delete_library_item)
        del_row.addWidget(del_lib_btn)
        box.addLayout(del_row)

        self._refresh_library()
        return box

    def _update_preview(self):
        if self._parent_window is not None:
            wp = self._parent_window._wallpaper
        else:
            wp = QPixmap()
        pm = _build_background_pixmap(
            wp,
            self._prev.size(),
            self._acrylic_slider.value() / 100.0,
        )
        self._prev.setPixmap(pm)

    def _on_pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景壁纸图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)",
        )
        if not path:
            return
        stored = self._copy_wallpaper(path)
        self._parent_window._wallpaper_path = stored
        self._parent_window._wallpaper = QPixmap(stored)
        self._img_label.setText(os.path.basename(stored))
        self._img_label.setStyleSheet(
            "font-size: 12px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        self._refresh_library()
        self._update_preview()

    def _copy_wallpaper(self, src: str) -> str:
        os.makedirs(WALLPAPER_DIR, exist_ok=True)
        ext = os.path.splitext(src)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            ext = ".png"
        # 唯一文件名（时间戳 + 随机后缀），避免覆盖，保留壁纸历史
        unique = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}"
        dest = os.path.join(WALLPAPER_DIR, f"wallpaper_{unique}{ext}")
        try:
            shutil.copyfile(src, dest)
            return dest
        except OSError:
            return src

    # ── 壁纸库（历史上传的缩略图统一管理）──

    def _list_wallpapers(self) -> list[str]:
        """扫描壁纸库目录，返回所有壁纸文件路径（按名称排序）"""
        if not os.path.isdir(WALLPAPER_DIR):
            return []
        exts = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
        files = []
        for name in sorted(os.listdir(WALLPAPER_DIR)):
            if name.lower().endswith(exts):
                files.append(os.path.join(WALLPAPER_DIR, name))
        return files

    def _refresh_library(self):
        """刷新壁纸库缩略图列表，并高亮当前选中的壁纸"""
        self._lib_list.clear()
        current = self._parent_window._wallpaper_path if self._parent_window else ""
        for path in self._list_wallpapers():
            pix = QPixmap(path)
            if pix.isNull():
                continue
            thumb = pix.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(QIcon(thumb), os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            # 当前壁纸高亮
            if path == current:
                item.setSelected(True)
            self._lib_list.addItem(item)

    def _on_library_clicked(self, item: QListWidgetItem):
        """单击壁纸库缩略图 → 设为当前壁纸"""
        path = item.data(Qt.UserRole)
        if not path:
            return
        self._parent_window._wallpaper_path = path
        self._parent_window._wallpaper = QPixmap(path)
        self._img_label.setText(os.path.basename(path))
        self._img_label.setStyleSheet(
            "font-size: 12px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        # 高亮切换
        for i in range(self._lib_list.count()):
            it = self._lib_list.item(i)
            it.setSelected(it is item)
        self._update_preview()

    def _on_delete_library_item(self):
        from PySide6.QtWidgets import QMessageBox
        item = self._lib_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        reply = QMessageBox.question(
            self, "确认删除", "确定从壁纸库删除该图片吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(path)
        except OSError:
            pass
        # 若删除的是当前壁纸，则回退到默认磨砂底
        if self._parent_window._wallpaper_path == path:
            self._parent_window._wallpaper_path = ""
            self._parent_window._wallpaper = QPixmap()
            self._img_label.setText("未选择图片")
            self._img_label.setStyleSheet(
                "font-size: 12px; color: #9E9E9E; font-family: 'Microsoft YaHei';"
            )
        self._refresh_library()
        self._update_preview()

    def _on_clear_image(self):
        self._parent_window._wallpaper_path = ""
        self._parent_window._wallpaper = QPixmap()
        self._img_label.setText("未选择图片")
        self._img_label.setStyleSheet(
            "font-size: 12px; color: #9E9E9E; font-family: 'Microsoft YaHei';"
        )
        self._refresh_library()
        self._update_preview()

    def _on_acrylic_changed(self, val: int):
        self._acrylic_value.setText(f"{val}%")
        self._update_preview()

    def _build_font_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)

        head = QLabel("字体大小")
        head.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        box.addWidget(head)

        desc = QLabel("调整粘贴板内所有文字大小（全局缩放）")
        desc.setStyleSheet(
            "font-size: 12px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        desc.setWordWrap(True)
        box.addWidget(desc)

        row = QHBoxLayout()
        label = QLabel("字号:")
        label.setStyleSheet(
            "font-size: 13px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        row.addWidget(label)
        self._font_spin = QSpinBox()
        self._font_spin.setRange(FONT_MIN, FONT_MAX)
        cur = self._parent_window._font_size if self._parent_window else FONT_DEFAULT
        self._font_spin.setValue(cur)
        self._font_spin.setSuffix(" px")
        self._font_spin.setStyleSheet(SPINBOX_STYLE)
        row.addWidget(self._font_spin)
        row.addStretch()
        box.addLayout(row)

        return box

    def _build_cleanup_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)

        head = QLabel("自动清理")
        head.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #212121; "
            "font-family: 'Microsoft YaHei';"
        )
        box.addWidget(head)

        desc = QLabel("超过以下天数的记录将被自动删除（置顶项除外）")
        desc.setStyleSheet(
            "font-size: 12px; color: #757575; font-family: 'Microsoft YaHei';"
        )
        desc.setWordWrap(True)
        box.addWidget(desc)

        spin_row = QHBoxLayout()
        spin_label = QLabel("保留天数:")
        spin_label.setStyleSheet(
            "font-size: 13px; color: #424242; font-family: 'Microsoft YaHei';"
        )
        spin_row.addWidget(spin_label)
        self._spin = QSpinBox()
        self._spin.setRange(1, 365)
        self._spin.setValue(self._store.get_cleanup_days())
        self._spin.setSuffix(" 天")
        self._spin.setStyleSheet(SPINBOX_STYLE)
        spin_row.addWidget(self._spin)
        spin_row.addStretch()
        box.addLayout(spin_row)

        clear_btn = QPushButton("清除全部记录（置顶项除外）")
        clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #EF5350; "
            "border: 1px solid #EF5350; border-radius: 6px; "
            "padding: 7px 16px; font-size: 13px; font-family: 'Microsoft YaHei'; }"
            "QPushButton:hover { background: rgba(239,83,80,0.08); }"
        )
        clear_btn.clicked.connect(self._on_clear_all)
        box.addWidget(clear_btn)

        return box

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(252, 252, 254, 242))
        painter.setPen(QPen(QColor(187, 222, 251, 180), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)

    def _on_save(self):
        if self._parent_window is not None:
            self._parent_window.apply_background_style(
                self._parent_window._wallpaper_path,
                self._acrylic_slider.value(),
            )
            self._parent_window.apply_font_size(self._font_spin.value())
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
