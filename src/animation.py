"""帧动画引擎：加载、播放、停止"""
import os
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap

ANIMATION_DURATION_MS = 5000  # 每个动画预设时长5秒


class AnimationEngine:
    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        self._frames: dict[str, list[QPixmap]] = {}  # key: "服装/动作"
        self._current_key: str | None = None
        self._current_index: int = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._next_frame)

        # 回调：帧切换时通知外部
        self.on_frame_changed = None  # callable(pixmap)

        self.scan()

    def scan(self):
        """扫描 assets/ 目录，发现所有动画"""
        self._frames.clear()
        if not os.path.isdir(self.assets_dir):
            return
        for outfit in os.listdir(self.assets_dir):
            outfit_path = os.path.join(self.assets_dir, outfit)
            if not os.path.isdir(outfit_path):
                continue
            for action in os.listdir(outfit_path):
                action_path = os.path.join(outfit_path, action)
                if not os.path.isdir(action_path):
                    continue
                key = f"{outfit}/{action}"
                self._frames[key] = self._load_frames(action_path)

    def _load_frames(self, path: str) -> list[QPixmap]:
        """加载目录下所有PNG帧（按文件名排序）"""
        frames = []
        for fname in sorted(os.listdir(path)):
            if fname.lower().endswith(".png"):
                frames.append(QPixmap(os.path.join(path, fname)))
        return frames

    def get_animations(self) -> list[str]:
        """返回所有可用动画的key列表"""
        return sorted(self._frames.keys())

    def has(self, key: str) -> bool:
        return key in self._frames

    def get_first_frame(self, key: str) -> QPixmap | None:
        frames = self._frames.get(key)
        return frames[0] if frames else None

    def play(self, key: str):
        """播放指定动画（循环）"""
        frames = self._frames.get(key)
        if not frames:
            return
        self._current_key = key
        self._current_index = 0
        interval = max(1, ANIMATION_DURATION_MS // len(frames))
        self._timer.start(interval)
        self._emit_frame(frames[0])

    def stop(self):
        """停止播放"""
        self._timer.stop()
        self._current_index = 0

    def _next_frame(self):
        """切换到下一帧"""
        frames = self._frames.get(self._current_key)
        if not frames:
            self.stop()
            return
        self._current_index = (self._current_index + 1) % len(frames)
        self._emit_frame(frames[self._current_index])

    def _emit_frame(self, pixmap: QPixmap):
        if self.on_frame_changed:
            self.on_frame_changed(pixmap)
