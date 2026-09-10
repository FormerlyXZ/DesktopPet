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

    # ── 养成系统扩展（Nurture）──
    #
    # 这四个方法**都带默认实现**，两个角色控制器都不用改就能被 NurtureController 调用：
    # 默认服装（PngCharacter）走默认值即为"不支持养成动作"，由上层走兜底链。

    def play_action(self, action: str, lock: bool = True) -> bool:
        """播一段指定动作（喂食 / 摸头 / 送礼等养成交互用）。

        `lock=True` 表示这段动画期间**不接受任何交互打断**（喂食专用）——
        她正在吃东西的时候不该被按键/悬停/点击切走。
        返回 `True` 表示动作确实开始播了，`False` 表示这个角色不支持或动作不存在。
        """
        return False

    def is_busy(self) -> bool:
        """角色是否正在做"不可打断"的事（启动序列、喂食动画）。

        悬停菜单与对话气泡用**同一个判断**决定要不要弹/要不要说话：
        她正在做开场动作或正在吃东西时，都不要往外冒东西。
        """
        return False

    def release_lock(self) -> None:
        """解除 `play_action(lock=True)` 的锁定。

        只用于兜底（切换角色、退出时），正常路径由动画播完自己解锁。
        """
        return None

    def handle_hover_menu_shown(self):
        """悬停菜单弹出（01 文档 5.4）。

        角色可以借此停掉自己的"长悬停"计时 —— 不停的话，用户正盯着菜单看时
        她会突然冒一个「问号」。默认空实现。
        """
        return None

    def speech_anchor_ratio(self) -> float:
        """对话气泡尾巴应指向的位置，按角色高度的比例表示（0 = 窗口顶端）。

        默认 0.14（头顶略偏下）。角色可按素材留白覆盖 ——
        PNG 帧的头顶留白与 GIF 不同，硬编码会让尾巴指到头发里或飘在头顶上方。
        """
        return 0.14

    # ── 配置 ──

    def get_settings(self) -> dict:
        """返回角色专属的配置字典（用于保存）"""
        return {}

    def apply_settings(self, settings: dict):
        """应用角色专属配置"""
