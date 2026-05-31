"""配置管理：读写 config.json，支持版本平滑升级"""
import copy
import json
import os
import sys
import winreg


def _get_project_dir() -> str:
    """项目根目录。PyInstaller 打包后数据保存在 exe 同级目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(__file__))


CONFIG_FILE = os.path.join(_get_project_dir(), "config.json")

DEFAULTS = {
    "character_type": "png",
    "height": 500,
    "position": None,
    "idle_animation": "默认服装/默认待机",
    "hover_animation": "默认服装/挥手",
    "auto_start": False,
    "language": "zh",
    # ── Q版 默认设置 ──
    "gif": {
        "startup_sequence": ["到达", "PNGTuber 加载", "加油"],
        "idle": "加油",
        "hover": "害羞 2",
        "long_hover": "问号",
        "click": "惊吓",
        "dbl_click_seq": ["生气", "哭 1"],
        "panel": "点头",
        "close": "摇头",
        "key_press": "打字(普通)",
        "audio_playing": "唱歌",
        "audio_muted": "静音 1",
        "afk_enabled": True,
        "afk_timeout_ms": 30000,
        "afk_min_ms": 60000,
        "afk_max_ms": 180000,
        "afk_pool": [],
    },
    # ── 历史粘贴板 ──
    "clipboard": {
        "cleanup_days": 7,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base，返回新 dict（不修改原始参数）"""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load() -> dict:
    """加载配置，自动补全新增字段"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
            data = deep_merge(DEFAULTS, stored)
            if data["position"] is not None and isinstance(data["position"], list) and len(data["position"]) == 2:
                data["position"] = tuple(data["position"])
            return data
    return copy.deepcopy(DEFAULTS)


def save(data: dict):
    """保存配置到 JSON 文件"""
    to_save = dict(data)
    if to_save.get("position") is not None:
        to_save["position"] = list(to_save["position"])
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2, ensure_ascii=False)


def set_auto_start(enable: bool):
    """设置或取消开机自启（写入注册表 HKCU Run）"""
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "DesktopPet"
    try:
        if enable:
            if getattr(sys, 'frozen', False):
                cmd = f'"{sys.executable}"'
            else:
                project_dir = _get_project_dir()
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                cmd = f'"{pythonw}" "{os.path.join(project_dir, "main.py")}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as reg:
                winreg.SetValueEx(reg, app_name, 0, winreg.REG_SZ, cmd)
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as reg:
                try:
                    winreg.DeleteValue(reg, app_name)
                except FileNotFoundError:
                    pass
    except OSError:
        pass
