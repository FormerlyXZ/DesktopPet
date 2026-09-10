"""桌宠主窗口：透明、置顶、无边框，委托 CharacterController"""
import os
import sys
import time
from datetime import datetime
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
from src.hover_menu import HoverMenu, dbg as nurture_dbg
from src.speech_bubble import SpeechBubble


def _get_assets_base() -> str:
    """获取素材根目录。PyInstaller 打包后素材在 sys._MEIPASS 中"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(__file__))


def ensure_position_on_screen(pos_x: int, pos_y: int,
                              window_width: int = 100,
                              window_height: int = 100):
    """校验窗口坐标是否在任一已连接屏幕范围内。

    若坐标落在所有屏幕之外（如拔掉外接显示器后保存的坐标失效），
    则回退到光标当前所在屏幕的右下角。无法获取光标位置时使用主屏幕。
    返回保证可见的 (x, y)。
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRect

    app = QApplication.instance()
    if app is None:
        return (pos_x, pos_y)

    screens = app.screens()
    if not screens:
        return (pos_x, pos_y)

    # 窗口矩形是否与任一屏幕有交集？
    window_rect = QRect(pos_x, pos_y, window_width, window_height)
    for screen in screens:
        if screen.availableGeometry().intersects(window_rect):
            return (pos_x, pos_y)

    # ── 坐标失效：回退到光标所在屏幕右下角 ──
    target_screen = app.screenAt(QCursor.pos())
    if target_screen is None:
        target_screen = app.primaryScreen()

    geom = target_screen.availableGeometry()
    x = geom.right() - window_width - 20
    y = geom.bottom() - window_height - 20
    return (x, y)


class PetWindow(QLabel):
    character_swap_needed = Signal(str, object)  # new_char_type, gif_settings

    def __init__(self, character: CharacterController, parent=None, nurture=None):
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

        # ── 养成：悬停菜单的计时器与状态（阶段 C）──
        # 这里**先只建状态、不建菜单本体**：菜单要等功能面板/系统面板/设置窗口都就绪后再创建，
        # 这样即使 enterEvent 提前触发，_hover_menu_allowed() 也只是返回 False 而不会 AttributeError。
        self._hover_menu = None
        self._hover_menu_timer = QTimer(self)       # 停留延迟后弹出
        self._hover_menu_timer.setSingleShot(True)
        self._hover_menu_timer.timeout.connect(self._show_hover_menu)
        self._hover_grace_timer = QTimer(self)      # 鼠标离开后的收起宽限期
        self._hover_grace_timer.setSingleShot(True)
        self._hover_grace_timer.timeout.connect(self._on_hover_grace_timeout)
        self._hover_leave_deferred = False          # 只延迟、不丢失的 handle_mouse_leave
        self._suppress_hover_until = 0.0            # 拖拽结束后的一小段抑制期
        self._nurture_cfg = load_config().get("nurture", {}) or {}
        self._last_hover_action = ""
        # 长悬停（阶段 E）：5 秒还没走开 → 说一句「怎么一直看着我」。
        # 与 01 文档 5.4 的裁定配套：**菜单已经弹出来时不说**（那时她正在被看着选按钮，
        # 再冒一句会显得聒噪）。所以这个计时器基本只在菜单被抑制时才轮到。
        self._hover_long_timer = QTimer(self)
        self._hover_long_timer.setSingleShot(True)
        self._hover_long_timer.timeout.connect(self._on_hover_long_timeout)

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

        # ── 养成：悬停菜单本体（所有弹层都就绪后才创建）──
        self._hover_menu = HoverMenu()
        self._hover_menu.apply_language(self.language)
        self._hover_menu.action_triggered.connect(self._on_hover_menu_action)
        self._hover_menu.menu_entered.connect(self._on_hover_menu_entered)
        self._hover_menu.menu_left.connect(self._on_hover_menu_left)

        # ── 养成：对话气泡（阶段 E）──
        # **不进仲裁器**：03 规范第 7 节的互斥矩阵里，对话气泡与所有弹层「可共存」，
        # 把它塞进 `_popups()` 会导致"一开功能面板气泡就被收掉"。
        self.speech_bubble = SpeechBubble()

        # ── 养成：业务层（阶段 D）──
        # 传进来就接上；不传（如单元测试）则整套养成退化成阶段 C 的行为：
        # 菜单照弹，但除「设置」外的按钮点了只记日志。**绝不能因为少了 controller 就崩**。
        self.nurture = nurture
        if self.nurture is not None:
            self.nurture.attach_character(self.character)
            self.nurture.attach_menu(self._hover_menu)
            self.nurture.speech_requested.connect(self._on_speech_requested)

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
        # 新增：切角色时把悬停菜单的计时与状态一起清干净（换到 PNG 后不该再弹）
        self._hover_menu_timer.stop()
        self._hover_grace_timer.stop()
        self._hover_long_timer.stop()
        self._hover_leave_deferred = False
        if self._hover_menu is not None:
            self._hover_menu.hide_now()
        self.speech_bubble.hide_now()          # 气泡里说的是上一个角色的事，切角色就收掉
        if self.nurture is not None:
            self.nurture.attach_character(character)   # 换成 PNG 后养成层自动失效
            self.nurture.hide_panel()
        idle_frame = character.get_current_pixmap()
        if idle_frame:
            self._base_pixmap = idle_frame
            self._set_pixmap(idle_frame)
        self._apply_size()
        character.start()

    def move_to_bottom_right(self):
        """将宠物放在光标所在屏幕的右下角（fallback: 主屏）"""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        target_screen = app.screenAt(QCursor.pos()) if app else None
        if target_screen is None:
            target_screen = QApplication.primaryScreen()

        geom = target_screen.availableGeometry()
        x = geom.right() - self.width() - 20
        y = geom.bottom() - self.pet_height - 20
        self.move(x, y)

    # ─── 鼠标悬停 / 离开 ───

    def enterEvent(self, event):
        self._hovering = True
        self._hover_grace_timer.stop()          # 新增：回到人物 → 取消收起宽限
        # 新增：鼠标回到人物 = 悬停恢复，那次被推迟的 leave 不再欠着了。
        # 必须在这里清掉：否则等下次真的离开时（菜单已收起 → 走 else 分支直接调
        # handle_mouse_leave），陈旧的标记会在之后的宽限期到期时**再补发一次** leave。
        self._hover_leave_deferred = False
        self.character.handle_mouse_enter()
        # 新增：开始计"停留多久"，到点才弹悬停菜单
        if self._hover_menu_allowed() and not self._hover_menu.isVisible():
            self._hover_menu_timer.start(self._hover_delay_ms())
        self._hover_long_timer.start(self._hover_long_ms())    # 新增：长悬停台词
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self._hover_menu_timer.stop()           # 新增：走了就别再弹
        self._hover_long_timer.stop()           # 新增：走了就不算长悬停
        if self._hover_menu is not None and self._hover_menu.isVisible():
            # 新增分支：菜单开着 → 鼠标很可能是要移到菜单上去，先进宽限期、**不动角色动画**
            self._hover_leave_deferred = True
            self._hover_grace_timer.start(self._hover_grace_ms())
        else:
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
            if self._hover_menu is not None and self._hover_menu.isVisible():
                self._hover_menu.move(self._hover_menu.pos() + delta)
            # 对话气泡：**重新贴一次**而不是跟着位移 —— 它可能因为拖到屏幕边上
            # 需要从"人物上方"翻到"下方"，直接 move 会让尾巴离人物越来越远
            if self.speech_bubble.is_showing():
                self.speech_bubble.follow(self.frameGeometry(), self._speech_anchor_ratio())
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
            else:
                # 新增：确实是拖拽（不是点击）→ 拖完一小段时间内别再弹悬停菜单
                self._hover_menu_timer.stop()
                self._suppress_hover_until = time.monotonic() + self._drag_suppress_ms() / 1000.0
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
            # 修订（2026-09-10 实机反馈，**取代** 01 文档 5.4 的原裁定）：
            # 悬停菜单不再"吃掉"单击。
            #
            # 原裁定是"菜单开着时单击 = 只收起菜单，不播惊吓、不弹功能面板"，
            # 实机上的表现却是"鼠标一放上去弹出喂养菜单，就再也点不出功能面板了，
            # 必须等菜单自己消失"——而同一个局面下右键是能弹出系统面板的
            # （`_toggle_system_panel()` 走仲裁器），左右键行为不一致本身就是 bug。
            #
            # 现在这里逐字走"菜单没开时"的那条路。收起悬停菜单不用单独写：
            # `_toggle_function_panel()` → `hide_all_popups()` 会顺带收起它，
            # 互斥矩阵（同一时刻只有一个弹层可见）依然成立。
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

    # ─── 弹层仲裁器（所有面板的显示/隐藏都过这一个口子）───
    #
    # 收拢前：互斥判断散在 _toggle_function_panel / _toggle_system_panel 里，各自只判断对方。
    # 收拢后：新增的悬停菜单与养成面板自动纳入同一套互斥规则。
    # **对现有两个面板的行为等价**：原来会收起的，现在照样收起（只是顺带也收悬停菜单/养成面板）。

    def _popups(self) -> dict:
        """当前所有弹层的 {键: 组件}。养成面板阶段 D 加入。"""
        popups = {
            "function": self.function_panel,
            "system": self.system_panel,
        }
        if self._hover_menu is not None:
            popups["hover"] = self._hover_menu
        # 用 panel_widget() 而不是 panel()：**不能为了查可见性就把面板创建出来**
        if self.nurture is not None:
            panel = self.nurture.panel_widget()
            if panel is not None:
                popups["nurture"] = panel
        return popups

    def hide_all_popups(self, except_key: str | None = None):
        """收起全部弹层（可指定一个豁免）。已隐藏的组件是空操作。"""
        for key, widget in self._popups().items():
            if key == except_key or widget is None:
                continue
            if widget.isVisible():
                widget.hide_with_anim()

    def any_popup_visible(self, keys=None) -> bool:
        """是否有弹层可见。`keys` 可限定只查某几个（如 `("hover",)`）。"""
        for key, widget in self._popups().items():
            if keys is not None and key not in keys:
                continue
            if widget is not None and widget.isVisible():
                return True
        return False

    # ─── 养成：悬停菜单（阶段 C）───

    def _nurture_int(self, key: str, default: int) -> int:
        """从 `config.json` 的 `nurture` 段读一个非负整数（脏值回落默认）。"""
        try:
            return max(0, int(self._nurture_cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _hover_delay_ms(self) -> int:
        return self._nurture_int("hover_menu_delay_ms", 600)

    def _hover_grace_ms(self) -> int:
        return self._nurture_int("hover_grace_ms", 350)

    def _drag_suppress_ms(self) -> int:
        return self._nurture_int("suppress_after_drag_ms", 400)

    def _hover_long_ms(self) -> int:
        return self._nurture_int("hover_long_ms", 5000)

    def _on_hover_long_timeout(self):
        """鼠标在她身上停留超过 5 秒 → 「怎么一直看着我」。

        **菜单已经弹出来时不说**（01 文档 5.4 的裁定）：那一刻她正被看着挑按钮，
        再冒一句话只会显得聒噪。所以这条台词基本只在菜单被抑制时才有机会。
        """
        if not self._hovering:
            return
        if self._hover_menu is not None and self._hover_menu.isVisible():
            return
        if self.nurture is None:
            return
        try:
            self.nurture.on_hover_long()
        except Exception as exc:
            nurture_dbg(f"长悬停台词失败：{exc!r}")

    def on_key_press(self) -> None:
        """全局按键（由 `main.py` 的 `InputMonitor` 喂进来）。

        转发给 `NurtureController`：它自己维护 30 秒速率窗口，
        速率过阈值时才考虑说一句「敲得好快呀」（台词文件里配了 10 分钟冷却）。
        """
        if self.nurture is None:
            return
        try:
            self.nurture.on_key_press()
        except Exception:
            pass

    def on_audio(self, playing: bool = False, muted: bool = False) -> None:
        """音频开始播放 / 系统静音（由 `main.py` 的 `AudioMonitor` 喂进来）。"""
        if self.nurture is None:
            return
        try:
            self.nurture.on_audio(playing=playing, muted=muted)
        except Exception:
            pass

    def on_any_activity(self) -> None:
        """用户有任何输入（鼠标/键盘）→ 结束"长时间无输入"状态。"""
        if self.nurture is None:
            return
        try:
            self.nurture.notify_activity()
        except Exception:
            pass

    def _character_busy(self) -> bool:
        """角色是否正在播放不可打断的内容（启动序列 / 喂食动画）。

        `is_busy()` 已在阶段 D 落到 `CharacterController`（默认 `False`，`GifCharacter` 真实现），
        两个角色控制器都吃得到。这里仍保留能力探测：**测试用的假角色可能没继承基类**，
        而"菜单该不该弹"这个判断不该因为一个 `AttributeError` 崩掉整个悬停逻辑。
        """
        probe = getattr(self.character, "is_busy", None)
        if probe is None:
            return False
        try:
            return bool(probe())
        except Exception:
            return False

    def _hover_menu_allowed(self) -> bool:
        """现在允许弹出悬停菜单吗（01 文档 5.1「抑制条件」+ 5.4 的裁定）。"""
        if self._hover_menu is None:
            return False
        if not bool(self._nurture_cfg.get("enabled", True)):
            return False
        if self.character.character_type != "gif":
            return False                # 养成只作用于 Q版，PNG 默认服装零影响
        if self._dragging or self._character_busy():
            return False
        if time.monotonic() < self._suppress_hover_until:
            return False
        if self.settings.isVisible():
            return False
        return not self.any_popup_visible(("function", "system"))

    def _show_hover_menu(self):
        """停留延迟到点 → 弹出菜单。菜单**不抢焦点**（不调 activateWindow）。"""
        if not self._hovering or self._hover_menu is None:
            return
        if self._hover_menu.isVisible() or not self._hover_menu_allowed():
            return
        self._refresh_hover_menu_state()
        self._hover_menu.popup_near(self.frameGeometry(), self.pet_height)
        # 01 文档 5.4：菜单开着的时候不该再触发"长悬停问号"
        # （用户正盯着菜单，她突然冒个问号会让人以为点错了）。阶段 D 补的这一条。
        self.character.handle_hover_menu_shown()
        # 01 文档 4.1 第 2 条：今天还没签到时，第一次弹出菜单顺口提一句（每天一次）
        if self.nurture is not None:
            try:
                self.nurture.on_menu_shown()
            except Exception as exc:
                nurture_dbg(f"签到提醒失败：{exc!r}")

    def _refresh_hover_menu_state(self):
        """刷新按钮可用状态与角标。

        接了 `NurtureController` 就由它按 01 文档 5.2 的"可用条件"表算
        （库存 / 今日送礼次数 / 好感度解锁）；没接则一律显示为可用。
        """
        if self._hover_menu is None:
            return
        if self.nurture is not None:
            self.nurture.refresh_menu()
            return
        self._hover_menu.set_badge("checkin", False)
        self._hover_menu.set_enabled_map({k: True for k in self._hover_menu.item_keys()})

    def _on_hover_menu_entered(self):
        """鼠标进入菜单 → 取消收起宽限（这就是"鼠标能移过去"的关键一半）。"""
        self._hover_grace_timer.stop()

    def _on_hover_menu_left(self):
        """鼠标离开菜单 → 重新开始宽限期（好让人能再移回人物身上）。"""
        self._hover_grace_timer.start(self._hover_grace_ms())

    def _on_hover_grace_timeout(self):
        """宽限期到点：鼠标既不在人物身上、也不在菜单上 → 收起菜单并补上角色动画切换。"""
        if self._hovering:
            self._flush_deferred_leave()        # 又回到人物身上了 → 不需要 leave
            return
        if self._hover_menu is not None and self._hover_menu.under_mouse():
            return                              # 还在菜单上 → 什么都不做
        if self._hover_menu is not None:
            self._hover_menu.hide_with_anim()
        self._flush_deferred_leave()

    def _flush_deferred_leave(self):
        """补发被宽限期推迟的 `handle_mouse_leave()`。

        宽限期期间我们**故意不切**角色动画（否则会出现"她一边害羞一边突然加油"），
        但那次 leave 不能丢 —— 否则角色会永远卡在害羞态。这个方法保证它恰好补发一次。
        """
        if not self._hover_leave_deferred:
            return
        self._hover_leave_deferred = False
        if not self._hovering:
            self.character.handle_mouse_leave()

    def _on_hover_menu_action(self, action: str):
        """菜单按钮点击。

        「设置」由 `PetWindow` 自己开；其余项先问 `NurtureController`（阶段 D 喂食闭环）。
        controller 说"还没接"（返回 `False`）时**收起菜单并记一条日志**，不做假装有反应的空实现。
        """
        self._last_hover_action = action
        if action == "settings":
            self.hide_all_popups(except_key="hover")
            self._on_settings()
            return
        if self.nurture is not None:
            handled = False
            try:
                handled = bool(self.nurture.on_menu_action(action, self.frameGeometry()))
            except Exception as exc:                     # 养成层出错不能连累桌宠本体
                nurture_dbg(f"nurture action '{action}' 抛异常：{exc!r}")
                handled = False
            if handled:
                # controller 打开了养成面板 → 其余弹层（悬停菜单 / 功能面板 / 系统面板）让位。
                # 走仲裁器而不是单独 hide 菜单：03 规范第 7 节的互斥矩阵要求
                # **同一时刻只有一个弹层可见**，将来再加弹层时这里不用改。
                self.hide_all_popups(except_key="nurture")
                self._flush_deferred_leave()
                return
        if self._hover_menu is not None:
            self._hover_menu.hide_with_anim()
        self._flush_deferred_leave()
        nurture_dbg(f"hover menu action '{action}' 尚未接入 NurtureController（阶段 E/F）")

    def _on_speech_requested(self, text: str, tone: str):
        """`NurtureController` 请求说一句台词 → 弹出对话气泡。

        三层抑制都在这里做（都不该往 controller 里塞，因为它们全是"显示"的事）：

        1. `bubble_enabled` 关掉 → 完全不出气泡
        2. 静音时段（`mute_hours_enabled`）→ 深夜不出气泡
        3. 她自己"忙着"（启动序列 / 上一个喂食动画没播完）→ 不出

        `tone` 目前只用于日志：语气筛选（`tease` 禁区）是 controller 的职责，
        它选句时就已经把不该说的滤掉了。
        """
        if not bool(self._nurture_cfg.get("bubble_enabled", True)):
            return
        if self._in_mute_hours():
            nurture_dbg(f"speech[{tone}] 静音时段，不出气泡：{text}")
            return
        self.speech_bubble.show_text(
            text,
            self.frameGeometry(),
            duration_ms=self._nurture_int("bubble_duration_ms", 3500),
            ratio=self._speech_anchor_ratio(),
        )

    def _in_mute_hours(self) -> bool:
        """现在是不是"不出气泡"的静音时段（默认 23:00–07:00，可在设置里关）。"""
        if not bool(self._nurture_cfg.get("mute_hours_enabled", False)):
            return False
        from src import nurture_model as nurture_model

        start = self._nurture_int("mute_hours_start", 23)
        end = self._nurture_int("mute_hours_end", 7)
        try:
            return bool(nurture_model.in_night(datetime.now().hour, start, end))
        except Exception:
            return False

    def _speech_anchor_ratio(self) -> float:
        """气泡尾巴锚点比例。

        优先用 `config.json` 的 `bubble_anchor_ratio`；**它还是默认值 0.14 时改用角色自报的比例**
        （`character.speech_anchor_ratio()`）—— PNG 帧与 Q版 GIF 的头顶留白不同，
        角色自己最清楚，而配置里那个 0.14 只是"未自定义"的标记。
        """
        from src.config import DEFAULTS

        default = 0.14
        try:
            default = float(DEFAULTS["nurture"]["bubble_anchor_ratio"])
        except Exception:
            pass
        try:
            configured = float(self._nurture_cfg.get("bubble_anchor_ratio", default))
        except (TypeError, ValueError):
            configured = default
        if abs(configured - default) > 1e-6:
            return max(0.0, min(1.0, configured))
        probe = getattr(self.character, "speech_anchor_ratio", None)
        if probe is None:
            return default
        try:
            return float(probe())
        except Exception:
            return default

    def _toggle_function_panel(self):
        """切换集成功能面板（左键）"""
        if self.function_panel.isVisible():
            self.function_panel.hide_with_anim()
        else:
            self.hide_all_popups(except_key="function")
            self.function_panel.popup_at(self.frameGeometry())

    def _toggle_system_panel(self):
        """切换系统面板（右键）——在鼠标位置弹出，面板一角对准鼠标，类系统菜单"""
        if self.system_panel.isVisible():
            self.system_panel.hide_with_anim()
        else:
            self.hide_all_popups(except_key="system")
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

        self._tray_clipboard_action = QAction(tr("tray_clipboard", lang), menu)
        self._tray_clipboard_action.triggered.connect(self._on_clipboard)
        menu.addAction(self._tray_clipboard_action)

        # 养成系统入口（阶段 F）。可见性由 `menu.aboutToShow` 每次现算：
        # 养成关闭 / 当前不是 Q版 时藏起来，比"点了没反应"清楚得多。
        self._tray_checkin_action = QAction(tr("tray_checkin", lang), menu)
        self._tray_checkin_action.triggered.connect(self._on_tray_checkin)
        menu.addAction(self._tray_checkin_action)

        self._tray_nurture_action = QAction(tr("tray_nurture_status", lang), menu)
        self._tray_nurture_action.triggered.connect(self._on_tray_nurture_status)
        menu.addAction(self._tray_nurture_action)
        menu.aboutToShow.connect(self._refresh_tray_nurture)

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

    def _nurture_ready(self) -> bool:
        """养成系统此刻是否真的能用（没接 controller / 关掉了 / 不是 Q版 → 否）。"""
        if self.nurture is None:
            return False
        try:
            return bool(self.nurture.enabled())
        except Exception:
            return False

    def _refresh_tray_nurture(self) -> None:
        """托盘菜单弹出前刷新养成两项的可见性与文案（今日已签时勾上）。"""
        for action in (getattr(self, "_tray_checkin_action", None),
                       getattr(self, "_tray_nurture_action", None)):
            if action is not None:
                action.setVisible(self._nurture_ready())
        action = getattr(self, "_tray_checkin_action", None)
        if action is not None and self._nurture_ready():
            try:
                action.setEnabled(bool(self.nurture.checkin_available()))
            except Exception:
                action.setEnabled(True)

    def _on_tray_checkin(self) -> None:
        """托盘「今日签到」——与悬停菜单那颗按钮走同一条路。"""
        if not self._nurture_ready():
            return
        try:
            self.nurture.try_checkin()
            self.nurture.refresh_menu()
        except Exception as exc:
            nurture_dbg(f"托盘签到失败：{exc!r}")

    def _on_tray_nurture_status(self) -> None:
        """托盘「养成状态」——直接开面板的状态页（她不在屏幕上也能看）。"""
        if not self._nurture_ready():
            return
        try:
            self.nurture.show_panel(self.frameGeometry(), "status")
        except Exception as exc:
            nurture_dbg(f"托盘打开养成状态失败：{exc!r}")

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
        # 设置窗口打开期间要抑制悬停菜单（03 规范第 7 节互斥矩阵），先把已开着的收掉
        self._hover_menu_timer.stop()
        self._hover_grace_timer.stop()
        self._hover_long_timer.stop()
        self._hover_leave_deferred = False
        if self._hover_menu is not None and self._hover_menu.isVisible():
            self._hover_menu.hide_with_anim()
        if self.nurture is not None:
            self.nurture.hide_panel()      # 面板同理：设置窗口开着时不该还挂着面板

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
            self._tray_clipboard_action.setText(tr("tray_clipboard", lang))
            self._tray_exit_action.setText(tr("tray_exit", lang))
            self._tray_checkin_action.setText(tr("tray_checkin", lang))
            self._tray_nurture_action.setText(tr("tray_nurture_status", lang))

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
        """打开历史粘贴板窗口（单例，正常窗口逻辑）"""
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
        # 若已最小化（任务栏），先还原
        if self._clipboard_window.isMinimized():
            self._clipboard_window.showNormal()
            self._clipboard_window.setWindowOpacity(1.0)
        else:
            self._clipboard_window.show_with_fade()
        self._clipboard_window.raise_()
        self._clipboard_window.activateWindow()
        self._clipboard_window.refresh()

    def refresh_clipboard_window(self):
        """剪贴板变化时实时刷新历史窗口（若可见）"""
        if self._clipboard_window and self._clipboard_window.isVisible():
            self._clipboard_window.refresh()

    def _on_exit(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
