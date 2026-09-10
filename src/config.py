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
    # ── 养成高木同学（Nurture）──
    # 设置写在这里；状态（好感度/库存/连签）在 data/nurture.json，两者刻意分离。
    # 老 config.json 无需迁移：deep_merge 会自动补全缺失键。
    "nurture": {
        # 总开关（四项互相独立，任意一项关掉不影响其余功能与桌宠本体）
        "enabled": True,
        "bubble_enabled": True,             # 对话气泡总开关
        "proactive_enabled": True,          # 主动说话（关掉后仅保留用户触发台词）
        "allow_foreground_detection": False,  # 隐私开关：默认关闭，需用户明确开启

        # 语气（01 文档 7.1）
        "tease_frequency": "sometimes",     # off / sometimes / normal
        "tease_daily_cap": 6,               # tease 台词 24 小时上限
        "tease_scene_cooldown_sec": 1800,   # 同场景 tease 冷却（30 分钟）

        # 数值（01 文档 2.2 / 2.3）
        "affection_daily_cap": 20,
        "gift_daily_cap": 3,
        "tier_caps": {"common": 20, "rare": 10, "precious": 5},

        # 获取途径（01 文档 4）
        "checkin_enabled": True,
        "checkin_anim": "庆祝",             # 签到成功播的动作
        "companion_minutes_per_item": 60,   # 每 N 分钟活动时间 → 1 个普通食物
        "companion_daily_cap": 3,
        "typing_keys_per_item": 2000,       # 每 N 次按键 → 1 个普通食物
        "typing_daily_cap": 2,
        "convert_anim": "点头",             # 兑换达成 / 彩蛋掉落时播的动作
        "afk_bonus_minutes": 10,            # 连续 AFK 超过 N 分钟 → 稀有食物 ×1（每天 1 次）
        "afk_bonus_tier": "rare",           # 长待机彩蛋的档位
        "first_run_bonus_tier": "precious",  # 首次使用彩蛋的档位
        "hourly_bonus_chance": 0.25,        # 整点彩蛋概率
        "hourly_bonus_enabled": True,
        "hourly_bonus_daily_cap": 3,        # 整点彩蛋每天最多触发几次（文档未写，实现补的上限）
        "birthday": "",                     # "MM-DD"，留空则不发生日彩蛋

        # 悬停菜单（01 文档 5）
        "hover_menu_delay_ms": 600,
        "hover_grace_ms": 350,
        "disable_long_hover_when_menu": True,   # 菜单弹出后禁用长悬停「问号」
        "suppress_after_drag_ms": 400,          # 拖拽结束后多久内不弹菜单
        "hover_long_ms": 5000,                  # 悬停多久算「长悬停」（会说一句台词）

        # 对话气泡与台词（01 文档 7）
        "bubble_duration_ms": 3500,
        # 气泡尾巴锚点 = 人物高度 × 该比例。**保持 0.14 表示"用角色自报的比例"**
        # （PNG 与 GIF 的头顶留白不同，角色自己最清楚）；调成别的值才表示用户要覆盖
        "bubble_anchor_ratio": 0.14,
        "bubble_min_width": 120,
        "bubble_max_width": 220,
        "proactive_min_gap_sec": 90,        # 两条主动台词之间的全局最小间隔
        "idle_talk_min_minutes": 8,         # 待机闲聊间隔下限
        "idle_talk_max_minutes": 20,        # 待机闲聊间隔上限
        "mute_hours_enabled": False,        # 免打扰时段
        "mute_hours_start": 23,
        "mute_hours_end": 7,
        "typing_rate_threshold": 120,       # 30 秒内按键数超过此值 = 专注
        "continuous_min_threshold": 90,     # 连续活跃超过此分钟数 = 专注
        "send_cooldown_ms": 300,            # 送出的连点防护（送出瞬间起算）
        "headpat_anim": "害羞 2",            # 「摸头」播的动作（不锁交互）

        # 动画映射的用户覆盖项（运行时与 items.json 合并，override 优先）
        # 刻意不写回 assets/，避免打包后只读
        "food_anim_override": {},
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
