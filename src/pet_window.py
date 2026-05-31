"""桌宠主窗口：透明、置顶、无边框，委托 CharacterController"""
import os
import sys
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QPixmap, QMouseEvent

from src.character_base import CharacterController
from src.bubble_panel import BubblePanel
from src.settings_window import SettingsWindow
from src.gif_registry import GifRegistry
from src.config import set_auto_start, save as save_config, load as load_config


def _get_assets_base() -> str:
    """获取素材根目录。PyInstaller 打包后素材在 sys._MEIPASS 中"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return _get_assets_base()


class PetWindow(QLabel):
    character_swap_needed = Signal(str, object)  # new_char_type, gif_settings

    def __init__(self, character: CharacterController, parent=None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self.character = character
        self.character.frame_changed.connect(self._on_frame)

        self.pet_height = 500
        self._hovering = False

        # 初始画面
        idle_frame = character.get_current_pixmap()
        if idle_frame is None:
            idle_frame = QPixmap(1, 1)
        self._base_pixmap = idle_frame
        self._set_pixmap(self._base_pixmap)
        self._apply_size()

        # 启动角色
        character.start()

        # 气泡面板
        self.bubble = BubblePanel()
        self.bubble.settings_clicked.connect(self._on_settings)
        self.bubble.clipboard_clicked.connect(self._on_clipboard)
        self.bubble.exit_clicked.connect(self._on_exit)

        # 历史粘贴板窗口（单例，延迟创建）
        self._clipboard_window = None

        # 设置窗口
        self.settings = SettingsWindow()
        self.settings.height_changed.connect(self.set_pet_height)
        self.settings.auto_start_changed.connect(self._on_auto_start_toggle)
        self.settings.language_changed.connect(self._on_language_changed)
        self.settings.animations_changed.connect(self._on_animations_changed)
        self.settings.save_clicked.connect(self._on_save_settings)
        self.settings.close_without_save.connect(self._on_close_without_save)

        self.auto_start = False
        self.language = "zh"

        # 拖拽
        self._dragging = False
        self._drag_start_pos = QPoint()
        self._press_pos = QPoint()

        # 双击检测（仅 GIF 角色使用）
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click_timeout)
        self._click_pending = False

    def _aspect_ratio(self) -> float:
        return self.character.native_aspect_ratio

    def _set_pixmap(self, pixmap: QPixmap):
        w = self.width() if self.width() > 0 else int(self.pet_height * self._aspect_ratio())
        h = self.pet_height
        scaled = pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled)
        self._update_mask()

    def _apply_size(self):
        w = int(self.pet_height * self._aspect_ratio())
        self.setFixedSize(w, self.pet_height)

    def _update_mask(self):
        if self.pixmap():
            self.setMask(self.pixmap().mask())

    def _on_frame(self, pixmap: QPixmap):
        self._base_pixmap = pixmap
        self._set_pixmap(pixmap)

    def set_pet_height(self, h: int):
        self.pet_height = h
        self._apply_size()
        if self._base_pixmap:
            self._set_pixmap(self._base_pixmap)
        else:
            idle = self.character.get_current_pixmap()
            if idle:
                self._base_pixmap = idle
                self._set_pixmap(idle)

    def set_character(self, character: CharacterController):
        """热切换角色（由 main.py 调用）"""
        self.character.frame_changed.disconnect(self._on_frame)
        self.character.stop()
        self.character = character
        self.character.frame_changed.connect(self._on_frame)
        self._hovering = False
        self._click_pending = False
        self._click_timer.stop()
        idle_frame = character.get_current_pixmap()
        if idle_frame:
            self._base_pixmap = idle_frame
            self._set_pixmap(idle_frame)
        self._apply_size()
        character.start()

    def move_to_bottom_right(self):
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 20
        y = screen.bottom() - self.pet_height - 20
        self.move(x, y)

    # ─── 鼠标悬停 / 离开 ───

    def enterEvent(self, event):
        self._hovering = True
        self.character.handle_mouse_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self.character.handle_mouse_leave()
        super().leaveEvent(event)

    # ─── 拖拽与点击 ───

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._press_pos = event.globalPosition().toPoint()
            self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            old_pos = self.pos()
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            self.move(new_pos)
            delta = new_pos - old_pos
            if self.bubble.isVisible():
                self.bubble.move(self.bubble.pos() + delta)
            if self.settings.isVisible():
                self.settings.move(self.settings.pos() + delta)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            delta = event.globalPosition().toPoint() - self._press_pos
            if delta.manhattanLength() < 5:
                if self.character.character_type == "gif":
                    if self._click_pending:
                        self._click_pending = False
                        self._click_timer.stop()
                        self.character.handle_double_click()
                    else:
                        self._click_pending = True
                        self._click_timer.start(400)
                else:
                    # PNG：无双击检测，立即触发单击
                    self.character.handle_single_click()
                    self._toggle_bubble()
            event.accept()

    def _on_single_click_timeout(self):
        """400ms 内未检测到第二次点击 → 确认为单击"""
        if self._click_pending:
            self._click_pending = False
            self.character.handle_single_click()
            self._toggle_bubble()

    def _toggle_bubble(self):
        if self.bubble.isVisible():
            self.bubble.hide_with_anim()
        else:
            self.bubble.popup_at(self.frameGeometry())

    # ─── 设置相关 ───

    def _on_settings(self):
        """打开设置窗口——同步所有当前值"""
        char_type = self.character.character_type
        self.settings.set_character_type(char_type)

        # PNG 动画选项始终从 assets/ 读取，不受当前角色类型影响
        from src.animation import AnimationEngine
        assets_dir = os.path.join(_get_assets_base(), "assets")
        png_engine = AnimationEngine(assets_dir)
        png_animations = png_engine.get_animations()
        if char_type == "png":
            png_idle = self.character.get_idle_key()
            png_hover = self.character.get_hover_key()
        else:
            config = load_config()
            png_idle = config.get("idle_animation", "默认服装/默认待机")
            png_hover = config.get("hover_animation", "默认服装/挥手")
        self.settings.set_animations(png_animations, png_idle, png_hover)

        # 始终填充 GIF 设置页（GifRegistry 扫描 素材库/高木同学Q版gif/）
        gif_dir = os.path.join(_get_assets_base(), "素材库", "高木同学Q版gif")
        gif_registry = GifRegistry(gif_dir)
        gif_actions = gif_registry.list_actions()
        self.settings.set_gif_actions(gif_actions)
        if char_type == "gif":
            self.settings.load_gif_settings(self.character.get_settings())
        else:
            self.settings.load_gif_settings(load_config().get("gif", {}))
        self.settings.set_height(self.pet_height)
        self.settings.set_auto_start(self.auto_start)
        self.settings.set_language(self.language)
        self.settings.popup_at(self.frameGeometry())
        self.character.handle_panel_button_clicked()

    def _on_animations_changed(self, idle_key, hover_key):
        """用户在设置中切换动画"""
        self.character.set_idle_key(idle_key)
        self.character.set_hover_key(hover_key)
        if not self._hovering:
            self.character.stop()
            self.character.start()

    def _on_auto_start_toggle(self, enabled: bool):
        self.auto_start = enabled
        set_auto_start(enabled)

    def _on_language_changed(self, lang: str):
        self.language = lang
        self.bubble.apply_language(lang)

    def _on_save_settings(self):
        """保存并退出 → 点头"""
        new_char_type = self.settings._char_combo.currentData()
        old_char_type = self.character.character_type
        gif_settings = self.settings.get_gif_settings()

        data = {
            "character_type": new_char_type,
            "height": self.pet_height,
            "position": (self.x(), self.y()),
            "idle_animation": self.character.get_idle_key(),
            "hover_animation": self.character.get_hover_key(),
            "auto_start": self.auto_start,
            "language": self.language,
            "gif": gif_settings,
        }
        save_config(data)

        if new_char_type != old_char_type:
            self.character.handle_panel_button_clicked()
            self.character_swap_needed.emit(new_char_type, gif_settings)
            return

        if old_char_type == "gif":
            self.character.apply_settings(gif_settings)
        self.character.handle_panel_button_clicked()

    def _on_close_without_save(self):
        """关闭或放弃更改 → 摇头"""
        self.character.handle_settings_close()

    def _on_clipboard(self):
        """打开历史粘贴板窗口（单例）"""
        if self._clipboard_window is None:
            from src.clipboard_window import ClipboardWindow
            from src.clipboard_store import ClipboardStore
            store = ClipboardStore()
            self._clipboard_window = ClipboardWindow(store)
            # 居中到屏幕
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen().availableGeometry()
            self._clipboard_window.move(
                screen.center().x() - self._clipboard_window.width() // 2,
                screen.center().y() - self._clipboard_window.height() // 2,
            )
        self._clipboard_window.show_with_fade()
        self._clipboard_window.activateWindow()
        self._clipboard_window.refresh()

    def refresh_clipboard_window(self):
        """剪贴板变化时实时刷新历史窗口（若可见）"""
        if self._clipboard_window and self._clipboard_window.isVisible():
            self._clipboard_window.refresh()

    def _on_exit(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
