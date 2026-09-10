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
    "topmost": True,
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
        # ── 夜间睡眠待机 ──
        "sleep_enabled": False,
        "sleep_prep_action": "睡觉(准备阶段1)",   # 23:00-24:00
        "sleep_normal_action": "睡觉(普通)",       # 0:00-6:00
    },
    # ── 历史粘贴板 ──
    "clipboard": {
        "cleanup_days": 7,
        "font_size": 13,            # 粘贴板全局字体大小（10-20）
        "wallpaper_path": "",       # 用户上传的背景壁纸图片路径（空=纯白磨砂底）
        "acrylic_opacity": 55,      # 亚克力磨砂叠层不透明度（0-100，越小越透）
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
    """保存配置到 JSON 文件。

    传入的 data 可能与已有配置是「部分更新」（如只含角色/窗口信息，不含 clipboard）。
    为避免覆盖未传入的键（如历史粘贴板的 wallpaper/font 设置），
    先将 data 合并到已有配置之上，再写盘。
    """
    merged = dict(data)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                merged = deep_merge(existing, data)
        except Exception:
            pass

    to_save = dict(merged)
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
