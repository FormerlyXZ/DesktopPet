"""GIF 注册表——扫描素材库，正则解析文件名提取动作名"""
import os
import re


class GifRegistry:
    """扫描 GIF 目录，提供 动作名→文件路径 映射"""

    _PATTERN = re.compile(r'^takagi_(.+)_\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.gif$')

    def __init__(self, gif_dir: str):
        self._gif_dir = gif_dir
        self._actions: dict[str, str] = {}  # action_name → file_path
        self._scan()

    def _scan(self):
        self._actions.clear()
        if not os.path.isdir(self._gif_dir):
            return
        for fname in os.listdir(self._gif_dir):
            m = self._PATTERN.match(fname)
            if m:
                action = m.group(1)
                self._actions[action] = os.path.join(self._gif_dir, fname)

    # ── 查询接口 ──

    def list_actions(self) -> list[str]:
        """返回所有动作名（排序）"""
        return sorted(self._actions.keys())

    def get_path(self, action: str) -> str | None:
        """根据动作名获取 GIF 文件路径"""
        return self._actions.get(action)

    def has(self, action: str) -> bool:
        """检查动作是否存在"""
        return action in self._actions

    def __len__(self) -> int:
        return len(self._actions)
