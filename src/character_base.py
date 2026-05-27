"""CharacterController 抽象基类——定义角色接口"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap


class CharacterController(QObject):
    """所有角色类型必须实现此接口"""

    frame_changed = Signal(QPixmap)
    interaction_finished = Signal()

    @property
    def character_type(self) -> str:
        """返回 "png" 或 "gif" """
        raise NotImplementedError

    @property
    def character_name(self) -> str:
        """返回角色显示名称"""
        raise NotImplementedError

    @property
    def native_aspect_ratio(self) -> float:
        """返回素材原生宽高比 (width/height)，用于窗口尺寸适配"""
        raise NotImplementedError

    # ── 生命周期 ──

    def start(self):
        """开始渲染（启动待机动画或启动序列）"""
        raise NotImplementedError

    def stop(self):
        """停止渲染，释放资源"""
        raise NotImplementedError

    def get_current_pixmap(self) -> QPixmap | None:
        """返回当前帧的 QPixmap"""
        raise NotImplementedError

    # ── 动画查询（供设置窗口使用）──

    def get_idle_key(self) -> str:
        """返回当前待机动画标识"""
        raise NotImplementedError

    def get_hover_key(self) -> str:
        """返回当前悬停动画标识"""
        raise NotImplementedError

    def set_idle_key(self, key: str):
        """设置待机动画"""
        raise NotImplementedError

    def set_hover_key(self, key: str):
        """设置悬停动画"""
        raise NotImplementedError

    def get_available_animations(self) -> list[str]:
        """返回可用动画列表"""
        raise NotImplementedError

    # ── 鼠标交互 ──

    def handle_mouse_enter(self):
        """鼠标进入人物区域"""

    def handle_mouse_leave(self):
        """鼠标离开人物区域"""

    def handle_single_click(self):
        """单击"""

    def handle_double_click(self):
        """双击"""

    # ── 面板/设置交互 ──

    def handle_panel_button_clicked(self):
        """点击面板按钮（设置/退出等）"""

    def handle_settings_close(self):
        """设置窗口关闭（保存并退出）"""

    def handle_settings_discard(self):
        """设置窗口放弃更改"""

    # ── 行为检测 ──

    def handle_key_press(self):
        """用户按下键盘任意键"""

    def handle_audio_playing(self):
        """系统正在播放音频"""

    def handle_audio_stopped(self):
        """系统音频停止播放"""

    def handle_audio_muted(self):
        """系统已静音"""

    # ── AFK ──

    def reset_afk(self):
        """用户有活动，重置AFK计时"""

    # ── 配置 ──

    def get_settings(self) -> dict:
        """返回角色专属的配置字典（用于保存）"""
        return {}

    def apply_settings(self, settings: dict):
        """应用角色专属配置"""
