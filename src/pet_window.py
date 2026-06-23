"""桌宠主窗口：透明、置顶、无边框，委托 CharacterController"""
import os
import sys
from PySide6.QtWidgets import QLabel, QSystemTrayIcon, QMenu
from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtGui import QPixmap, QMouseEvent, QIcon, QAction

from src.character_base import CharacterController
from src.bubble_panel import BubblePanel
from src.settings_window import SettingsWindow
from src.gif_registry import GifRegistry
from src.config import set_auto_start, save as save_config, load as load_config
from src.translations import tr


def _get_assets_base() -> str:
    """获取素材根目录。PyInstaller 打包后素材在 sys._MEIPASS 中"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(__file__))


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

        self.auto_start = False
        self.language = "zh"

        # 集成功能面板（左键）——目前只有历史粘贴板
        self.function_panel = BubblePanel([
            ("clipboard", "bubble_clipboard"),
            # 后续可在此处添加更多功能，例如:
            # ("notes", "function_notes"),
        ])
        self.function_panel.item_clicked.connect(self._on_panel_item)

        # 系统面板（右键）——设置 + 托盘 + 层级
        self.system_panel = BubblePanel([
            ("topmost", "sys_topmost", {"checkable": True}),
            ("desktop_level", "sys_desktop_level", {"checkable": True}),
            ("minimize_tray", "sys_minimize_tray"),
            ("settings", "bubble_settings"),
            ("exit", "bubble_exit"),
        ])
        self.system_panel.item_clicked.connect(self._on_panel_item)
        self._topmost = True  # 默认置顶

        # ── 系统托盘图标 ──
        self._tray_icon = self._create_tray_icon()

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
        elif event.button() == Qt.RightButton:
            self._press_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            old_pos = self.pos()
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            self.move(new_pos)
            delta = new_pos - old_pos
            if self.function_panel.isVisible():
                self.function_panel.move(self.function_panel.pos() + delta)
            if self.system_panel.isVisible():
                self.system_panel.move(self.system_panel.pos() + delta)
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
                    self._toggle_function_panel()
            event.accept()
        elif event.button() == Qt.RightButton:
            delta = event.globalPosition().toPoint() - self._press_pos
            if delta.manhattanLength() < 5:
                self.character.handle_single_click()
                self._toggle_system_panel()
            event.accept()

    def _on_single_click_timeout(self):
        """400ms 内未检测到第二次点击 → 确认为单击"""
        if self._click_pending:
            self._click_pending = False
            self.character.handle_single_click()
            self._toggle_function_panel()

    def _on_panel_item(self, item_id: str):
        """统一路由面板项点击"""
        if item_id == "settings":
            self._on_settings()
        elif item_id == "clipboard":
            self._on_clipboard()
        elif item_id == "exit":
            self._on_exit()
        elif item_id == "topmost":
            self._on_toggle_topmost()
        elif item_id == "desktop_level":
            self._on_toggle_desktop_level()
        elif item_id == "minimize_tray":
            self._on_minimize_to_tray()

    def _toggle_function_panel(self):
        """切换集成功能面板（左键）"""
        if self.function_panel.isVisible():
            self.function_panel.hide_with_anim()
        else:
            if self.system_panel.isVisible():
                self.system_panel.hide_with_anim()
            self.function_panel.popup_at(self.frameGeometry())

    def _toggle_system_panel(self):
        """切换系统面板（右键）——在鼠标位置弹出，类系统菜单"""
        if self.system_panel.isVisible():
            self.system_panel.hide_with_anim()
        else:
            if self.function_panel.isVisible():
                self.function_panel.hide_with_anim()
            # 弹出前刷新 checkable 项的选中状态
            self.system_panel.set_item_checked("topmost", self._topmost)
            self.system_panel.set_item_checked("desktop_level", not self._topmost)
            self.system_panel.show_at(QCursor.pos())

    # ─── 系统托盘 ───

    def _create_tray_icon(self) -> QSystemTrayIcon:
        """创建系统托盘图标"""
        # 从素材加载图标（缩放到合适大小）
        assets_base = _get_assets_base()
        icon_path = os.path.join(assets_base, "素材库", "高木头像.png")
        pixmap = QPixmap(icon_path)
        if pixmap.isNull():
            # fallback：创建一个简单的图标
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
        icon = QIcon(pixmap)

        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("DesktopPet")

        # 右键菜单（保存引用以便语言切换）
        menu = QMenu()
        lang = self.language
        self._tray_show_action = QAction(tr("tray_show", lang), menu)
        self._tray_show_action.triggered.connect(self._on_tray_show)
        menu.addAction(self._tray_show_action)

        menu.addSeparator()
        self._tray_exit_action = QAction(tr("tray_exit", lang), menu)
        self._tray_exit_action.triggered.connect(self._on_exit)
        menu.addAction(self._tray_exit_action)

        self._tray_menu = menu
        tray.setContextMenu(menu)
        # 左键点击托盘图标 → 显示桌宠
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """托盘图标被点击"""
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_tray_show()

    def _on_tray_show(self):
        """从托盘恢复显示"""
        self.show()
        self.activateWindow()
        self.character.handle_panel_button_clicked()

    def _on_minimize_to_tray(self):
        """最小化到系统托盘"""
        self.hide()
        self.character.handle_settings_close()

    def set_topmost(self, enabled: bool):
        """设置窗口是否置顶（外部调用，如启动时恢复配置）"""
        self._topmost = enabled
        self._apply_window_level()

    def _on_toggle_topmost(self):
        """切换窗口置顶"""
        self._topmost = True
        self._apply_window_level()
        self._save_topmost()

    def _on_toggle_desktop_level(self):
        """切换到桌面层级（普通窗口，可被遮挡）"""
        self._topmost = False
        self._apply_window_level()
        self._save_topmost()

    def _save_topmost(self):
        """即时保存窗口层级到配置文件"""
        from src.config import load as cfg_load, save as cfg_save
        cfg = cfg_load()
        cfg["topmost"] = self._topmost
        cfg_save(cfg)

    def _apply_window_level(self):
        """应用窗口层级设置"""
        was_visible = self.isVisible()
        flags = self.windowFlags()
        if self._topmost:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if was_visible:
            self.show()  # setWindowFlags 后需重新 show

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
        self.function_panel.apply_language(lang)
        self.system_panel.apply_language(lang)
        # 更新托盘菜单文本
        if hasattr(self, '_tray_show_action'):
            self._tray_show_action.setText(tr("tray_show", lang))
            self._tray_exit_action.setText(tr("tray_exit", lang))

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
            "topmost": self._topmost,
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
