"""GifCharacter——QMovie 播放 + 启动序列 + 交互状态机"""
from enum import Enum, auto

from PySide6.QtCore import QTimer
from PySide6.QtGui import QMovie, QPixmap

from src.character_base import CharacterController
from src.gif_registry import GifRegistry


class State(Enum):
    INACTIVE = auto()
    STARTUP = auto()
    IDLE = auto()
    INTERACTING = auto()
    HOVER_IDLE = auto()


class GifCharacter(CharacterController):
    """Q版高木同学：GIF 动图角色"""

    DEFAULT_STARTUP = ["到达", "PNGTuber 加载", "加油"]
    DEFAULT_IDLE = "加油"
    DEFAULT_HOVER = "害羞 2"
    DEFAULT_LONG_HOVER = "问号"
    DEFAULT_CLICK = "惊吓"
    DBL_CLICK_SEQ = ["生气", "哭 1"]
    DEFAULT_PANEL = "点头"
    DEFAULT_CLOSE = "摇头"
    DEFAULT_KEY_PRESS = "打字(普通)"
    DEFAULT_AUDIO_PLAYING = "唱歌"
    DEFAULT_AUDIO_MUTED = "静音 1"

    LONG_HOVER_MS = 3000

    def __init__(self, gif_dir: str, registry: GifRegistry | None = None):
        super().__init__()
        self._registry = registry or GifRegistry(gif_dir)
        self._movie = QMovie(self)
        self._movie.setCacheMode(QMovie.CacheAll)
        self._movie.frameChanged.connect(self._on_frame_changed)
        self._movie.finished.connect(self._on_movie_finished)

        self._startup_seq: list[str] = list(self.DEFAULT_STARTUP)
        self._idle_key: str = self.DEFAULT_IDLE
        self._hover_key: str = self.DEFAULT_HOVER
        self._long_hover_key: str = self.DEFAULT_LONG_HOVER
        self._click_key: str = self.DEFAULT_CLICK
        self._dbl_click_seq: list[str] = list(self.DBL_CLICK_SEQ)
        self._panel_key: str = self.DEFAULT_PANEL
        self._close_key: str = self.DEFAULT_CLOSE
        self._key_press_action: str = self.DEFAULT_KEY_PRESS
        self._audio_playing_action: str = self.DEFAULT_AUDIO_PLAYING
        self._audio_muted_action: str = self.DEFAULT_AUDIO_MUTED

        # 从待机 GIF 的尺寸计算原生宽高比
        idle_path = self._registry.get_path(self._idle_key)
        if idle_path:
            idle_pix = QPixmap(idle_path)
            if not idle_pix.isNull():
                self._aspect_ratio = idle_pix.width() / max(idle_pix.height(), 1)
            else:
                self._aspect_ratio = 1.0
        else:
            self._aspect_ratio = 1.0

        self._looping = False
        self._once_started = False
        self._state = State.INACTIVE
        self._seq_index = 0
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_long_hover)

        self._interaction_queue: list[str] = []
        self._dbl_click_step = 0
        self._active_action: str = ""  # 当前正在播放的动作名，用于优先级判断

        # AFK
        self._afk_enabled = True
        self._afk_timeout_ms = 30000
        self._afk_min_ms = 60000
        self._afk_max_ms = 180000
        self._afk_pool: list[str] = []
        self._afk_timer = QTimer(self)
        self._afk_timer.setSingleShot(True)
        self._afk_timer.timeout.connect(self._on_afk_tick)

    # ── 身份 ──

    @property
    def character_type(self) -> str:
        return "gif"

    @property
    def character_name(self) -> str:
        return "Q版高木同学"

    @property
    def native_aspect_ratio(self) -> float:
        return self._aspect_ratio

    # ── 生命周期 ──

    def start(self):
        self._state = State.STARTUP
        self._seq_index = 0
        if self._startup_seq:
            self._play_once(self._startup_seq[0])
        else:
            self._enter_idle()

    def stop(self):
        self._movie.stop()
        self._hover_timer.stop()
        self._afk_timer.stop()
        self._state = State.INACTIVE

    def get_current_pixmap(self) -> QPixmap | None:
        path = self._registry.get_path(self._idle_key)
        if path:
            return QPixmap(path)
        return None

    # ── 动画查询 ──

    def get_idle_key(self) -> str:
        return self._idle_key

    def get_hover_key(self) -> str:
        return self._hover_key

    def set_idle_key(self, key: str):
        if self._registry.has(key):
            self._idle_key = key

    def set_hover_key(self, key: str):
        if self._registry.has(key):
            self._hover_key = key

    def get_available_animations(self) -> list[str]:
        return self._registry.list_actions()

    # ── 初始状态导出（供设置窗口用）──

    def get_startup_sequence(self) -> list[str]:
        return list(self._startup_seq)

    def set_startup_sequence(self, seq: list[str]):
        self._startup_seq = [s for s in seq if self._registry.has(s)]

    # ── 内部播放 ──

    def _play_once(self, action: str):
        """播放指定 GIF 一次后自动进入下一状态"""
        self._looping = False
        self._once_started = False
        self._active_action = action
        path = self._registry.get_path(action)
        if not path:
            self._on_movie_finished()
            return
        self._movie.stop()
        self._movie.setFileName(path)
        self._movie.start()

    def _play_loop(self, action: str):
        """循环播放指定 GIF（内部 loop=0 自然循环）"""
        self._looping = True
        self._active_action = action
        path = self._registry.get_path(action)
        if not path:
            return
        self._movie.stop()
        self._movie.setFileName(path)
        self._movie.start()

    def _enter_idle(self):
        self._state = State.IDLE
        self._play_loop(self._idle_key)
        if self._afk_enabled and self._afk_pool:
            self._afk_timer.start(self._afk_timeout_ms)

    def _on_frame_changed(self, frame_num: int):
        pixmap = self._movie.currentPixmap()
        if not pixmap.isNull():
            self.frame_changed.emit(pixmap)

        # GIF 内建 loop=0 导致 QMovie.finished 永不触发。
        # 对一次性动画，检测帧号归零来表示播放完一轮。
        if not self._looping:
            if frame_num == 0 and self._once_started:
                self._movie.stop()
                self._on_movie_finished()
            elif frame_num > 0:
                self._once_started = True

    def _on_movie_finished(self):
        # 无限循环模式：直接重新播放
        if self._looping:
            self._movie.start()
            return

        if self._state == State.STARTUP:
            self._seq_index += 1
            if self._seq_index < len(self._startup_seq):
                self._play_once(self._startup_seq[self._seq_index])
            else:
                self._enter_idle()
        elif self._state == State.INTERACTING:
            if self._dbl_click_step > 0:
                # 双击链式播放中
                self._dbl_click_step += 1
                if self._dbl_click_step <= len(self._dbl_click_seq):
                    self._play_once(self._dbl_click_seq[self._dbl_click_step - 1])
                else:
                    self._dbl_click_step = 0
                    self._enter_idle()
            elif self._interaction_queue:
                next_action = self._interaction_queue.pop(0)
                self._play_once(next_action)
            else:
                self._enter_idle()
        elif self._state == State.HOVER_IDLE:
            # 长悬停问号播完 → 回到悬停循环，重新计时
            self._play_loop(self._hover_key)
            self._hover_timer.start(self.LONG_HOVER_MS)

    # ── 鼠标交互 ──

    def handle_mouse_enter(self):
        if self._state in (State.STARTUP, State.INTERACTING):
            return
        self._state = State.HOVER_IDLE
        self._play_loop(self._hover_key)
        self._hover_timer.start(self.LONG_HOVER_MS)

    def handle_mouse_leave(self):
        self._hover_timer.stop()
        if self._state == State.HOVER_IDLE:
            self._enter_idle()

    def _on_long_hover(self):
        """悬停达到 LONG_HOVER_MS → 问号"""
        if self._state == State.HOVER_IDLE:
            self._play_once(self._long_hover_key)
            # 问号播完后回到悬停
            self._state = State.HOVER_IDLE  # 保持不变，finished 后回到 hover

    def handle_single_click(self):
        if self._state == State.STARTUP:
            return
        self._state = State.INTERACTING
        self._dbl_click_step = 0
        self._hover_timer.stop()
        self._play_once(self._click_key)

    def handle_double_click(self):
        if self._state == State.STARTUP:
            return
        self._state = State.INTERACTING
        self._hover_timer.stop()
        self._dbl_click_step = 1
        self._play_once(self._dbl_click_seq[0])

    def handle_panel_button_clicked(self):
        if self._state == State.STARTUP:
            return
        self._state = State.INTERACTING
        self._play_once(self._panel_key)

    def handle_settings_close(self):
        if self._state == State.STARTUP:
            return
        self._state = State.INTERACTING
        self._play_once(self._close_key)

    def handle_settings_discard(self):
        self.handle_settings_close()

    # ── 行为检测 ──

    def handle_key_press(self):
        if self._state == State.IDLE:
            self._state = State.INTERACTING
            self._play_once(self._key_press_action)
        elif self._state == State.INTERACTING and self._active_action in (
            self._audio_playing_action, self._audio_muted_action,
        ):
            # 打字优先级高于音频，打断正在播放的音频动画
            self._play_once(self._key_press_action)

    def handle_audio_playing(self):
        if self._state == State.IDLE:
            self._state = State.INTERACTING
            self._play_loop(self._audio_playing_action)

    def handle_audio_stopped(self):
        if self._state == State.INTERACTING and self._active_action == self._audio_playing_action:
            self._enter_idle()

    def handle_audio_muted(self):
        if self._state == State.IDLE:
            self._state = State.INTERACTING
            self._play_once(self._audio_muted_action)

    # ── AFK ──

    def reset_afk(self):
        if self._afk_enabled and self._afk_pool:
            self._afk_timer.stop()
            if self._state == State.IDLE:
                self._afk_timer.start(self._afk_timeout_ms)

    def _on_afk_tick(self):
        if self._state != State.IDLE:
            return
        if not self._afk_pool:
            return
        import random
        action = random.choice(self._afk_pool)
        self._state = State.INTERACTING
        self._play_once(action)
        # 设下一次随机间隔
        delay = random.randint(self._afk_min_ms, self._afk_max_ms)
        self._afk_timer.start(delay)

    # ── 配置导入导出 ──

    def get_settings(self) -> dict:
        return {
            "startup_sequence": list(self._startup_seq),
            "idle": self._idle_key,
            "hover": self._hover_key,
            "long_hover": self._long_hover_key,
            "click": self._click_key,
            "dbl_click_seq": list(self._dbl_click_seq),
            "panel": self._panel_key,
            "close": self._close_key,
            "key_press": self._key_press_action,
            "audio_playing": self._audio_playing_action,
            "audio_muted": self._audio_muted_action,
            "afk_enabled": self._afk_enabled,
            "afk_timeout_ms": self._afk_timeout_ms,
            "afk_min_ms": self._afk_min_ms,
            "afk_max_ms": self._afk_max_ms,
            "afk_pool": list(self._afk_pool),
        }

    def apply_settings(self, settings: dict):
        if "startup_sequence" in settings:
            self._startup_seq = [s for s in settings["startup_sequence"] if self._registry.has(s)]
        if "idle" in settings and self._registry.has(settings["idle"]):
            self._idle_key = settings["idle"]
        if "hover" in settings and self._registry.has(settings["hover"]):
            self._hover_key = settings["hover"]
        if "long_hover" in settings and self._registry.has(settings["long_hover"]):
            self._long_hover_key = settings["long_hover"]
        if "click" in settings and self._registry.has(settings["click"]):
            self._click_key = settings["click"]
        if "dbl_click_seq" in settings:
            self._dbl_click_seq = [s for s in settings["dbl_click_seq"] if self._registry.has(s)]
        if "panel" in settings and self._registry.has(settings["panel"]):
            self._panel_key = settings["panel"]
        if "close" in settings and self._registry.has(settings["close"]):
            self._close_key = settings["close"]
        if "key_press" in settings and self._registry.has(settings["key_press"]):
            self._key_press_action = settings["key_press"]
        if "audio_playing" in settings and self._registry.has(settings["audio_playing"]):
            self._audio_playing_action = settings["audio_playing"]
        if "audio_muted" in settings and self._registry.has(settings["audio_muted"]):
            self._audio_muted_action = settings["audio_muted"]
        if "afk_enabled" in settings:
            self._afk_enabled = settings["afk_enabled"]
        if "afk_timeout_ms" in settings:
            self._afk_timeout_ms = settings["afk_timeout_ms"]
        if "afk_min_ms" in settings:
            self._afk_min_ms = settings["afk_min_ms"]
        if "afk_max_ms" in settings:
            self._afk_max_ms = settings["afk_max_ms"]
        if "afk_pool" in settings:
            self._afk_pool = [s for s in settings["afk_pool"] if self._registry.has(s)]
