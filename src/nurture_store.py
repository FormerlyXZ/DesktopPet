"""养成系统数据层 —— `data/nurture.json` 的容错读写。

对应需求：`docs/nurture/01-需求规格.md` 第 10 节、`docs/nurture/02-技术方案.md` 4.2。

设计要点：

* **状态与设置分离**：本文件只管"状态"（好感度/库存/签到/统计）；设置仍在 `config.json`
* **原子写**：写 `.tmp` → `fsync` → `os.replace()`，避免断电/崩溃写坏存档
* **容错读**：解析失败 → 坏档改名 `nurture.json.bad-{时间戳}` → 用默认档启动，**绝不静默删数据**
* **防抖写**：状态变化后 2 秒合并写一次；退出时 `flush()` 强制落盘
* **跨天重置**：`daily.date != 今天` → 清 `daily` 与各 `*_today` 计数
* **访问器不暴露裸 dict**：外部拿不到内部结构，杜绝绕过规则直接改值
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from datetime import date
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from src import nurture_model as nm

#: 存档结构版本号。日后结构不兼容变更时递增，并在 `_normalize()` 里做迁移
DATA_VERSION = 1

#: 写盘防抖间隔（毫秒）
DEFAULT_DEBOUNCE_MS = 2000

#: 每个场景保留的"最近已用台词"条数（01 文档 7.4 防重复）
USED_LINES_KEEP = 5

#: `daily` 段里的每日计数器（跨天重置）。阶段 F 会用到的都在这里
DAILY_KEYS: tuple[str, ...] = (
    "active_minutes",        # 今日累计活动分钟（陪伴兑换进度）
    "key_count",             # 今日累计按键数（打字兑换进度）
    "minutes_rewarded",      # 今日已因陪伴时长兑换的个数
    "keys_rewarded",         # 今日已因打字量兑换的个数
    "hourly_bonus_count",    # 今日整点彩蛋已触发次数（防整点连刷）
)

#: 顶层每日计数器（跨天重置）
TODAY_KEYS: tuple[str, ...] = (
    "affection_gained_today",
    "gifts_sent_today",
    "tease_count_today",
)

#: `stats` 段里的累计统计（只增不减）
STATS_KEYS: tuple[str, ...] = (
    "total_fed",
    "total_gifts",
    "total_checkins",
)

#: `flags` 段里的杂项标记（键 → 默认值）。默认值的类型决定读档时的强转方式
FLAG_DEFAULTS: dict[str, Any] = {
    "first_run_bonus_granted": False,   # 首次使用彩蛋是否已发放
    "afk_bonus_date": "",               # 长待机彩蛋最近一次发放日期（每天最多 1 次）
    "checkin_reminded_date": "",        # 签到提醒最近一次日期（每天最多 1 次）
    "intro_bubble_date": "",            # 启动问候最近一次日期
    "mute_tease_date": "",              # 「今天不要捉弄我」生效日期（次日自动恢复）
    # 时段问候：每个时段每天只说一次（阶段 E）。键名必须是 `{场景名}_date`，
    # `NurtureController.on_idle_tick()` 就是按这个约定写的。
    # **只认 FLAG_DEFAULTS 里的键**：`_normalize()` 会把不在表里的 flag 丢掉，
    # 所以随便起名字的日期标记活不过一次重启（会变成"每次启动都重新问候"）。
    "time_morning_date": "",
    "time_noon_date": "",
    "time_night_date": "",
    "time_late_date": "",
    "last_hourly_date": "",             # 整点彩蛋最近一次日期
    "last_hourly_hour": -1,             # 整点彩蛋最近一次小时（同小时不重复）
    # 节日彩蛋（阶段 F）。**同理**：`event_valentine_date` 这种按场景动态拼的键
    # 不在表里，会被 `_normalize()` 丢掉 —— 表现是"节日奖励每天都能再领一次"。
    # 一条日期 + 一个 id 就够表达"今天发过了"，不必给每个节日各留一个键。
    "last_event_date": "",              # 节日彩蛋最近一次发放日期
}


def project_dir() -> str:
    """项目根目录。打包后数据保存在 exe 同级目录（与 `config.py` 同口径）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_path() -> str:
    """默认存档路径：`<项目根>/data/nurture.json`。"""
    return os.path.join(project_dir(), "data", "nurture.json")


def default_state(today: date | None = None) -> dict:
    """全新存档。

    首次运行**不播任何"欢迎回来"台词**（01 文档 4.4），连签从 0 开始，
    用户第一次签到才进入 `streak = 1`。
    """
    today_d = today or date.today()
    stamp = today_d.isoformat()
    return {
        "version": DATA_VERSION,
        "affection": 0,
        "streak": 0,
        "last_checkin_date": "",
        "inventory": {},
        "used_lines": {},
        "flags": {k: copy.deepcopy(v) for k, v in FLAG_DEFAULTS.items()},
        "daily": {"date": stamp, **{k: 0 for k in DAILY_KEYS}},
        **{k: 0 for k in TODAY_KEYS},
        "stats": {**{k: 0 for k in STATS_KEYS}, "first_run_date": stamp},
    }


class NurtureStore(QObject):
    """`data/nurture.json` 的读写门面。

    线程约定：**只在主线程使用**（`QTimer` 防抖与信号都依赖主线程事件循环）。
    """

    #: 状态变更通知，参数为变更的段名（`"state"` / `"inventory"` / ...），UI 据此刷新
    changed = Signal(str)

    def __init__(self, path: str | None = None, parent: QObject | None = None,
                 debounce_ms: int = DEFAULT_DEBOUNCE_MS) -> None:
        super().__init__(parent)
        self._path = path or default_path()
        self._data: dict = default_state()
        self._dirty = False
        self._last_error: str = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, int(debounce_ms)))
        self._timer.timeout.connect(self.flush)

    # ────────────────── 生命周期 ──────────────────

    @property
    def path(self) -> str:
        return self._path

    @property
    def last_error(self) -> str:
        """最近一次读/写失败的原因（空串表示没出错）。仅用于日志排查。"""
        return self._last_error

    def load(self, today: date | None = None) -> None:
        """容错读。

        * 文件不存在 → 默认档（不写盘，等第一次真实变更再写）
        * 解析失败 / 结构非法 → 坏档改名 `.bad-{ts}`，用默认档继续
        * 缺字段 → 用默认值补齐（老存档平滑升级）
        * 跨天 → 立即重置每日计数（并安排写盘）
        """
        today_d = today or date.today()
        self._timer.stop()
        self._dirty = False
        self._data = self._read_or_recover(today_d)
        self.reset_daily_if_needed(today_d)     # 可能置脏并安排一次写盘

    def _read_or_recover(self, today: date) -> dict:
        if not os.path.exists(self._path):
            return default_state(today)
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._last_error = f"存档解析失败: {exc}"
            self._quarantine()
            return default_state(today)
        except OSError as exc:
            # 读不了（权限/被占用）——不隔离文件，直接用默认档跑，不阻塞启动
            self._last_error = f"存档读取失败: {exc}"
            return default_state(today)

        if not isinstance(raw, dict):
            self._last_error = "存档根节点不是对象"
            self._quarantine()
            return default_state(today)
        return self._normalize(raw, today)

    def _quarantine(self) -> None:
        """把坏档改名保留，绝不静默删除。改名失败就算了（用户至少没丢文件）。"""
        target = f"{self._path}.bad-{int(time.time())}"
        try:
            os.replace(self._path, target)
            self._last_error += f"（已改名为 {os.path.basename(target)}）"
        except OSError as exc:
            self._last_error += f"（坏档改名失败: {exc}）"

    def _normalize(self, raw: dict, today: date) -> dict:
        """把任意 JSON 结构捏成合法存档。任何脏值都降级，不抛异常。"""
        data = default_state(today)

        version = nm.safe_int(raw.get("version"))
        data["version"] = max(version, DATA_VERSION)
        data["affection"] = max(0, nm.safe_int(raw.get("affection")))
        data["streak"] = max(0, nm.safe_int(raw.get("streak")))

        last = nm.parse_date(raw.get("last_checkin_date"))
        data["last_checkin_date"] = last.isoformat() if last else ""

        inv = raw.get("inventory")
        if isinstance(inv, dict):
            for name, n in inv.items():
                name = str(name).strip()
                count = nm.safe_int(n)
                if name and count > 0:      # 空名字的条目直接丢掉（面板上会是空白卡）
                    data["inventory"][name] = count

        used = raw.get("used_lines")
        if isinstance(used, dict):
            for scene, lines in used.items():
                if isinstance(lines, list):
                    data["used_lines"][str(scene)] = [str(x) for x in lines][-USED_LINES_KEEP:]

        flags = raw.get("flags")
        if isinstance(flags, dict):
            for key, fallback in FLAG_DEFAULTS.items():
                value = flags.get(key, fallback)
                if isinstance(fallback, bool):
                    data["flags"][key] = bool(value)
                elif isinstance(fallback, int):
                    data["flags"][key] = nm.safe_int(value)
                else:
                    data["flags"][key] = str(value if value is not None else "")

        daily = raw.get("daily")
        if isinstance(daily, dict):
            d = nm.parse_date(daily.get("date"))
            data["daily"]["date"] = d.isoformat() if d else ""
            for key in DAILY_KEYS:
                data["daily"][key] = max(0, nm.safe_int(daily.get(key)))

        for key in TODAY_KEYS:
            data[key] = max(0, nm.safe_int(raw.get(key)))

        stats = raw.get("stats")
        if isinstance(stats, dict):
            for key in STATS_KEYS:
                data["stats"][key] = max(0, nm.safe_int(stats.get(key)))
            first = nm.parse_date(stats.get("first_run_date"))
            if first:
                data["stats"]["first_run_date"] = first.isoformat()
        return data

    # ────────────────── 写盘 ──────────────────

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def save(self, immediate: bool = False) -> None:
        """标记脏并安排写盘。`immediate=True` 立即落盘（退出、签到等关键节点）。"""
        self._dirty = True
        self.changed.emit("state")
        if immediate:
            self.flush()
        else:
            self._timer.start()

    def flush(self) -> bool:
        """立即落盘。返回是否真的写了。写失败不影响运行（下次变更再试）。"""
        self._timer.stop()
        if not self._dirty:
            return False
        try:
            self._write_atomic(self._path, self._data)
        except (OSError, TypeError, ValueError) as exc:
            # 磁盘满 / 路径被占 / 数据不可序列化 —— 都不能让桌宠本体崩掉
            self._last_error = f"存档写入失败: {exc}"
            return False
        self._dirty = False
        return True

    @staticmethod
    def _write_atomic(path: str, data: dict) -> None:
        """先写临时文件 + `fsync`，再 `os.replace()` 原子替换。"""
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def cleanup_bad_files(self, keep: int = 3) -> None:
        """清理历史坏档，只保留最近 `keep` 个（避免 `data/` 越积越多）。"""
        names = list_bad_files(self._path)
        names.sort(key=_bad_stamp, reverse=True)
        directory = os.path.dirname(self._path) or "."
        for name in names[max(0, int(keep)):]:
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass

    # ────────────────── 跨天 ──────────────────

    def reset_daily_if_needed(self, today: date | None = None) -> bool:
        """跨天重置。返回是否发生了重置。

        重置内容：`daily` 全部计数器、三个 `*_today`、`mute_tease_date`（捉弄静音次日自动恢复）。
        `affection` / `streak` / `inventory` / `stats` / `used_lines` **不动**。
        """
        today_d = today or date.today()
        daily = self._data.get("daily")
        current = daily.get("date") if isinstance(daily, dict) else None
        if not nm.daily_reset_needed(current, today_d):
            return False
        stamp = today_d.isoformat()
        self._data["daily"] = {"date": stamp, **{k: 0 for k in DAILY_KEYS}}
        for key in TODAY_KEYS:
            self._data[key] = 0
        flags = self._data.setdefault("flags", {})
        if flags.get("mute_tease_date") != stamp:
            flags["mute_tease_date"] = ""
        self.save()
        return True

    def today(self) -> date:
        """存档中记录的"今天"（`daily.date`）。坏值回退到系统日期。"""
        daily = self._data.get("daily")
        stamp = daily.get("date") if isinstance(daily, dict) else None
        return nm.parse_date(stamp) or date.today()

    # ────────────────── 好感度 / 连签 ──────────────────

    @property
    def affection(self) -> int:
        return max(0, nm.safe_int(self._data.get("affection")))

    @property
    def affection_gained_today(self) -> int:
        return max(0, nm.safe_int(self._data.get("affection_gained_today")))

    @property
    def gifts_sent_today(self) -> int:
        return max(0, nm.safe_int(self._data.get("gifts_sent_today")))

    @property
    def tease_count_today(self) -> int:
        return max(0, nm.safe_int(self._data.get("tease_count_today")))

    @property
    def streak(self) -> int:
        return max(0, nm.safe_int(self._data.get("streak")))

    @property
    def last_checkin_date(self) -> date | None:
        return nm.parse_date(self._data.get("last_checkin_date"))

    def set_affection(self, value: int, *, gained_today: int | None = None) -> None:
        self._data["affection"] = max(0, nm.safe_int(value))
        if gained_today is not None:
            self._data["affection_gained_today"] = max(0, nm.safe_int(gained_today))
        self.save()

    def set_checkin(self, streak: int, when: date) -> None:
        """记录一次成功签到（连签天数 + 日期 + 累计签到次数）。"""
        self._data["streak"] = max(0, nm.safe_int(streak))
        self._data["last_checkin_date"] = nm.to_date_str(when)
        stats = self._data.setdefault("stats", {})
        stats["total_checkins"] = max(0, nm.safe_int(stats.get("total_checkins"))) + 1
        self.save(immediate=True)

    # ────────────────── 库存 ──────────────────

    @property
    def inventory(self) -> dict[str, int]:
        """库存**副本**（改它不影响存档，避免绕过规则直接写状态）。"""
        inv = self._data.get("inventory")
        if not isinstance(inv, dict):
            return {}
        return {str(k): nm.safe_int(v) for k, v in inv.items()}

    def item_count(self, name: str) -> int:
        return self.inventory.get(str(name), 0)

    def has_room(self, name: str, cap: int | None = None) -> bool:
        """该物品还能不能再收。`cap is None` 视为不限量。"""
        if cap is None:
            return True
        return self.item_count(name) < max(0, nm.safe_int(cap))

    def add_item(self, name: str, n: int = 1, cap: int | None = None) -> int:
        """加库存。返回**实际**加入的数量（受 `cap` 截断；`cap=None` 表示不限量）。

        库存满时不发放（01 文档 4.4）——返回 0 由调用方出「拿不下啦」气泡。
        """
        name = str(name).strip()
        n = nm.safe_int(n)
        if not name or n <= 0:
            return 0
        current = self.item_count(name)
        if cap is not None:
            n = min(n, max(0, nm.safe_int(cap) - current))
        if n <= 0:
            return 0
        self._data.setdefault("inventory", {})[name] = current + n
        self.save()
        return n

    def take_item(self, name: str, n: int = 1) -> bool:
        """扣库存。库存不足返回 `False` 且**不做任何改动**。"""
        name = str(name).strip()
        n = nm.safe_int(n)
        if not name or n <= 0:
            return False
        current = self.item_count(name)
        if current < n:
            return False
        inv = self._data.setdefault("inventory", {})
        left = current - n
        if left > 0:
            inv[name] = left
        else:
            inv.pop(name, None)
        self.save()
        return True

    # ────────────────── 计数器 ──────────────────

    def bump_today(self, key: str, n: int = 1) -> int:
        """增减顶层每日计数器（好感度/送礼/捉弄）。"""
        if key not in TODAY_KEYS:
            raise KeyError(f"未知的每日计数器: {key}")
        value = max(0, nm.safe_int(self._data.get(key)) + nm.safe_int(n))
        self._data[key] = value
        self.save()
        return value

    def bump_daily(self, key: str, n: int = 1) -> int:
        """增减 `daily` 段计数器（陪伴分钟 / 按键数 / 已兑换数）。"""
        if key not in DAILY_KEYS:
            raise KeyError(f"未知的 daily 计数器: {key}")
        daily = self._data.setdefault("daily", {})
        value = max(0, nm.safe_int(daily.get(key)) + nm.safe_int(n))
        daily[key] = value
        self.save()
        return value

    def set_daily(self, key: str, value: int) -> None:
        """直接设置 `daily` 计数器（兑换成功后写回剩余进度用）。"""
        if key not in DAILY_KEYS:
            raise KeyError(f"未知的 daily 计数器: {key}")
        self._data.setdefault("daily", {})[key] = max(0, nm.safe_int(value))
        self.save()

    def daily(self, key: str, default: int = 0) -> int:
        daily = self._data.get("daily")
        if not isinstance(daily, dict):
            return nm.safe_int(default)
        return max(0, nm.safe_int(daily.get(key, default)))

    def bump_stats(self, key: str, n: int = 1) -> int:
        """增减累计统计（只增；负增量会被吃成 0）。"""
        if key not in STATS_KEYS:
            raise KeyError(f"未知的统计项: {key}")
        stats = self._data.setdefault("stats", {})
        value = max(0, nm.safe_int(stats.get(key)) + nm.safe_int(n))
        stats[key] = value
        self.save()
        return value

    def stats(self, key: str, default: int = 0) -> int:
        stats = self._data.get("stats")
        if not isinstance(stats, dict):
            return nm.safe_int(default)
        return max(0, nm.safe_int(stats.get(key, default)))

    # ────────────────── 标记位 ──────────────────

    def flag(self, key: str, default: Any = None) -> Any:
        flags = self._data.get("flags")
        if not isinstance(flags, dict):
            return FLAG_DEFAULTS.get(key, default)
        return flags.get(key, FLAG_DEFAULTS.get(key, default))

    def set_flag(self, key: str, value: Any) -> None:
        self._data.setdefault("flags", {})[str(key)] = _json_safe(value)
        self.save()

    def mute_tease_today(self) -> bool:
        """用户今天是否开了「今天不要捉弄我」。"""
        return self.flag("mute_tease_date", "") == self.today().isoformat()

    def set_mute_tease(self, muted: bool) -> None:
        self.set_flag("mute_tease_date", self.today().isoformat() if muted else "")

    # ────────────────── 台词防重复 ──────────────────

    def used_lines(self, scene: str) -> list[str]:
        used = self._data.get("used_lines")
        if not isinstance(used, dict):
            return []
        lines = used.get(str(scene))
        return [str(x) for x in lines] if isinstance(lines, list) else []

    def remember_line(self, scene: str, text: str) -> None:
        """记住已用台词，只保留最近 `USED_LINES_KEEP` 条（01 文档 7.4）。"""
        used = self._data.setdefault("used_lines", {})
        lines = used.get(str(scene))
        if not isinstance(lines, list):
            lines = []
        lines.append(str(text))
        used[str(scene)] = lines[-USED_LINES_KEEP:]
        self.save()

    def forget_lines(self, scene: str) -> None:
        """清空某场景的已用记录（该场景台词全被过滤掉时重来一轮）。"""
        used = self._data.get("used_lines")
        if isinstance(used, dict):
            used.pop(str(scene), None)
        self.save()

    # ────────────────── 调试 / 测试用 ──────────────────

    def snapshot(self) -> dict:
        """存档深拷贝。仅供调试与状态显示，**不要**拿它改值。"""
        return copy.deepcopy(self._data)

    def replace_state(self, data: dict, today: date | None = None) -> None:
        """整体替换存档并立即落盘（"重置养成数据"与测试用）。"""
        self._data = self._normalize(data if isinstance(data, dict) else {},
                                     today or date.today())
        self.save(immediate=True)


def _bad_stamp(name: str) -> int:
    """从 `nurture.json.bad-1735689600` 里取出时间戳，取不到返回 0。"""
    try:
        return int(name.rsplit(".bad-", 1)[1])
    except (IndexError, ValueError):
        return 0


def _json_safe(value: Any) -> Any:
    """保证写进存档的值一定可序列化（否则 `json.dump` 会在 flush 时抛 TypeError）。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def list_bad_files(path: str | None = None) -> list[str]:
    """列出已有坏档文件名（测试与排查用）。"""
    target = path or default_path()
    directory = os.path.dirname(target) or "."
    base = os.path.basename(target)
    try:
        return sorted(n for n in os.listdir(directory) if n.startswith(base + ".bad-"))
    except OSError:
        return []


__all__ = [
    "DATA_VERSION",
    "DAILY_KEYS",
    "DEFAULT_DEBOUNCE_MS",
    "FLAG_DEFAULTS",
    "NurtureStore",
    "STATS_KEYS",
    "TODAY_KEYS",
    "default_path",
    "default_state",
    "list_bad_files",
    "project_dir",
]
