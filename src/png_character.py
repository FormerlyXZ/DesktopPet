"""PngCharacter——包装 AnimationEngine，适配 CharacterController 接口"""
from PySide6.QtGui import QPixmap
from src.character_base import CharacterController
from src.animation import AnimationEngine


class PngCharacter(CharacterController):
    """默认服装角色：PNG帧序列，不改动 AnimationEngine 原有代码"""

    def __init__(self, assets_dir: str, idle_key: str = "默认服装/默认待机",
                 hover_key: str = "默认服装/挥手"):
        super().__init__()
        self._anim = AnimationEngine(assets_dir)
        self._anim.on_frame_changed = self._on_frame
        self._idle_key = idle_key
        self._hover_key = hover_key
        self._hovering = False

    @property
    def character_type(self) -> str:
        return "png"

    @property
    def character_name(self) -> str:
        return "默认服装"

    @property
    def native_aspect_ratio(self) -> float:
        return 9.0 / 16.0

    # ── 生命周期 ──

    def start(self):
        if self._anim.has(self._idle_key):
            self._anim.play(self._idle_key)

    def stop(self):
        self._anim.stop()

    def get_current_pixmap(self) -> QPixmap | None:
        return self._anim.get_first_frame(self._idle_key)

    # ── 动画查询 ──

    def get_idle_key(self) -> str:
        return self._idle_key

    def get_hover_key(self) -> str:
        return self._hover_key

    def set_idle_key(self, key: str):
        if self._anim.has(key):
            self._idle_key = key

    def set_hover_key(self, key: str):
        if self._anim.has(key):
            self._hover_key = key

    def get_available_animations(self) -> list[str]:
        return self._anim.get_animations()

    # ── 鼠标交互 ──

    def handle_mouse_enter(self):
        self._hovering = True
        if self._anim.has(self._hover_key):
            self._anim.play(self._hover_key)

    def handle_mouse_leave(self):
        self._hovering = False
        self._anim.stop()
        if self._anim.has(self._idle_key):
            self._anim.play(self._idle_key)

    # ── 内部 ──

    def _on_frame(self, pixmap: QPixmap):
        """AnimationEngine 帧回调 → 转发为 CharacterController 信号"""
        self.frame_changed.emit(pixmap)
