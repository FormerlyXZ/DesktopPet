"""养成系统规则层 —— 纯函数集合。

设计约束（见 `docs/nurture/02-技术方案.md` 4.1）：

* 本模块 **不 import PySide6**，入参出参全部是基础类型（int / str / date / dict / list）
* 不做任何 I/O、不发信号、不读全局状态 —— 所以可以脱离 Qt 事件循环直接做表驱动单测
* 数值规则的**唯一实现处**：UI 层不得复制这里的任何判断

对应需求：`docs/nurture/01-需求规格.md` 第 2 节（数值）、3.3（兜底链）、4.1（签到）、7.1（语气禁区）。
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime
from typing import Callable, Iterable, Mapping, Sequence

# ────────────────────────────── 常量 ──────────────────────────────

#: 食物档位。顺序即由低到高，用于界面排序与默认上限查表
TIER_COMMON = "common"
TIER_RARE = "rare"
TIER_PRECIOUS = "precious"
TIERS: tuple[str, ...] = (TIER_COMMON, TIER_RARE, TIER_PRECIOUS)

#: 单类库存上限（01 文档 2.3）。"单类"指**每个物品各自计数**，不是档位总量
DEFAULT_TIER_CAPS: dict[str, int] = {
    TIER_COMMON: 20,
    TIER_RARE: 10,
    TIER_PRECIOUS: 5,
}

#: 可送出物类型
KIND_FOOD = "food"
KIND_GIFT = "gift"
KINDS: tuple[str, ...] = (KIND_FOOD, KIND_GIFT)

#: 兜底链第 2 级：类型默认动画（01 文档 3.3）
KIND_FALLBACK_ANIM: dict[str, str] = {
    KIND_FOOD: "笑",
    KIND_GIFT: "点赞",
}

#: 兜底链第 3 级：全局兜底动画。素材库实测存在，改素材文件名时需同步
GLOBAL_FALLBACK_ANIM = "害羞 2"

#: 好感度软上限（仅用于进度条显示比例，**不做硬截断**；硬截断只有每日上限）
SOFT_AFFECTION_CAP = 1000

#: 送出物档位 → 好感度增量（01 文档 2.2）
DEFAULT_AFFECTION_GAIN: dict[str, int] = {
    TIER_COMMON: 1,
    TIER_RARE: 2,
    TIER_PRECIOUS: 4,
}

#: 语气档位（01 文档 7.1 三档语气）
TONE_GENTLE = "gentle"
TONE_PROUD = "proud"
TONE_TEASE = "tease"

#: 设置项「捉弄频率」三档 → 抽取概率。`off` 是**硬禁用**（不是概率 0 的软抽取）
TEASE_PROBABILITY: dict[str, float] = {
    "off": 0.0,
    "sometimes": 0.15,
    "normal": 0.35,
}
DEFAULT_TEASE_FREQUENCY = "sometimes"

#: 语气禁区阈值（01 文档 7.1）
DEFAULT_TYPING_RATE_THRESHOLD = 120   # 30 秒内按键数
DEFAULT_CONTINUOUS_MIN_THRESHOLD = 90  # 连续活跃分钟数
DEFAULT_NIGHT_START = 23              # 含
DEFAULT_NIGHT_END = 6                 # 不含
DEFAULT_TEASE_DAILY_CAP = 6

#: 前台分类的**全部合法取值**（01 文档 8.2）。`window_monitor` 与 `apps.json` 共用这一份，
#: 免得两处各写一份之后慢慢走偏。
APP_KEYS: tuple[str, ...] = ("code", "browser", "game", "meeting", "media")
#: 查不到 / 读不到 / 命中"不要感知"黑名单 → 一律归到这里
UNKNOWN_APP_KEY = "unknown"

#: 判定为"专注/不适合打扰"的前台分类（01 文档 7.3 第 2、3 条）
FOCUS_APP_KEYS: tuple[str, ...] = ("meeting",)
BLOCKING_APP_KEYS: tuple[str, ...] = ("meeting", "game")

#: 代码内兜底等级表。`assets/nurture/levels.json` 缺失/损坏时使用，保证功能降级而非崩溃
DEFAULT_LEVELS: list[dict] = [
    {"threshold": 0, "title": "认识", "unlocks": []},
    {"threshold": 50, "title": "同桌", "unlocks": ["idle_random"]},
    {"threshold": 120, "title": "朋友", "unlocks": ["small_talk"]},
    {"threshold": 250, "title": "要好", "unlocks": ["tone_proud", "event_lines"]},
    {"threshold": 450, "title": "特别", "unlocks": ["headpat"]},
    {"threshold": 700, "title": "最重要的人", "unlocks": ["late_talk"]},
]

#: 代码内兜底签到奖励表。`assets/nurture/checkin.json` 缺失/损坏时使用
DEFAULT_CHECKIN_TABLE: dict = {
    "base_items": {TIER_COMMON: 2},
    "base_affection": 0,
    "first_affection": 2,
    "milestones": {
        "3": {"items": {TIER_RARE: 1}, "affection": 5},
        "7": {"items": {TIER_PRECIOUS: 1}, "affection": 10},
        "14": {"items": {TIER_PRECIOUS: 1}, "affection": 20},
        "30": {"items": {TIER_PRECIOUS: 1}, "affection": 50},
    },
}

# ────────────────────────── 日期与跨天判定 ──────────────────────────

#: `checkin_status()` 的四种返回值
STATUS_FIRST = "first"          # 从未签到过
STATUS_NEW_DAY = "new_day"      # 与上次相差正好 1 天 → 连签 +1
STATUS_SAME_DAY = "same_day"    # 今天已签 → 拒绝
STATUS_GAP = "gap"              # 相差 ≥2 天 → 断签，连签重置
STATUS_CLOCK_BACK = "clock_back"  # 今天 < 上次签到日 → 系统时间被往回改

#: 严格日期格式。`date.fromisoformat()` 在 3.11+ 还接受紧凑形式 `20260910`，
#: 跨版本行为不一致，所以先做格式校验，只认 `YYYY-MM-DD`
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: `MM-DD`（节日表里的日期格式）
_MONTH_DAY_RE = re.compile(r"^\d{2}-\d{2}$")

#: `events.json` 里表示"用户生日"的特殊 date 值
BIRTHDAY_TOKEN = "birthday"


def parse_date(value) -> date | None:
    """把 `"2026-09-10"` / `date` / `None` 统一解析成 `date`；失败返回 `None`。

    存档是用户可手改的 JSON，坏值必须降级成"从未签到"而不是抛异常。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not _DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def to_date_str(value) -> str:
    """序列化用：`date` → `"YYYY-MM-DD"`，无法解析时返回空串。"""
    d = parse_date(value)
    return d.isoformat() if d else ""


def is_new_day(today: date, last: date | None) -> bool:
    """`last` 是否为过去的一天（含"今天早于上次"的时钟回退情形）。

    注意：时钟回退也返回 `True`（确实"不是同一天"）。**能不能发放**由
    `checkin_status()` 决定，两者职责不同，不要混用。
    """
    if last is None:
        return True
    return today != last


def daily_reset_needed(daily_date, today: date) -> bool:
    """`daily` 段是否需要跨天重置。日期坏值 → 需要重置（保守）。"""
    d = parse_date(daily_date)
    if d is None:
        return True
    return d != today


def checkin_status(last: date | None, today: date) -> str:
    """签到资格判定，返回 `STATUS_*` 之一。

    这是"改系统时间"防御的核心：`STATUS_CLOCK_BACK` 时**不发放也不重置**
    （01 文档 4.4），调用方只提示"时间好像不太对"。
    """
    last_d = parse_date(last)
    today_d = parse_date(today)
    if today_d is None:
        return STATUS_CLOCK_BACK       # 连"今天"都解析不出来 → 拒绝发放
    if last_d is None:
        return STATUS_FIRST
    delta = (today_d - last_d).days
    if delta < 0:
        return STATUS_CLOCK_BACK
    if delta == 0:
        return STATUS_SAME_DAY
    if delta == 1:
        return STATUS_NEW_DAY
    return STATUS_GAP


def can_checkin(last: date | None, today: date) -> bool:
    """今天是否可以签到（`STATUS_FIRST` / `STATUS_NEW_DAY` / `STATUS_GAP` 均可）。"""
    return checkin_status(last, today) in (STATUS_FIRST, STATUS_NEW_DAY, STATUS_GAP)


def next_streak(last: date | None, today: date, prev_streak: int) -> tuple[int, bool]:
    """计算签到后的新连签天数。

    返回 `(新连签, 是否发生了重置)`。

    | 情形 | 结果 |
    |------|------|
    | 首次签到 | `(1, False)` —— 开始计数，不算"断签重置" |
    | 相差 1 天 | `(prev + 1, False)` |
    | 同一天重复 | `(prev, False)` —— 调用方应先用 `can_checkin()` 拦掉 |
    | 相差 ≥2 天 | `(1, True)` —— 断签重置 |
    | 时间回退 | `(prev, False)` —— **不发放不重置**，连签原样保留 |
    """
    try:
        prev = max(0, int(prev_streak))
    except (TypeError, ValueError):
        prev = 0

    status = checkin_status(last, today)
    if status == STATUS_NEW_DAY:
        return prev + 1, False
    if status == STATUS_GAP:
        return 1, True
    if status == STATUS_FIRST:
        return 1, False
    if status == STATUS_SAME_DAY:
        return prev, False
    return prev, False                 # STATUS_CLOCK_BACK


# ────────────────────────── 签到奖励 ──────────────────────────


def _milestone_of(streak: int, milestones: Mapping | None) -> dict | None:
    """按连签天数取里程碑配置。JSON 的键是字符串，这里统一成 int 再比。"""
    if not milestones:
        return None
    for key, conf in milestones.items():
        try:
            if int(key) == streak:
                return conf if isinstance(conf, dict) else {}
        except (TypeError, ValueError):
            continue
    return None


def checkin_reward(streak: int, table: Mapping | None = None) -> dict:
    """签到产出。返回 `{"tiers": {档位: 数量}, "affection": int, "milestone": int | None}`。

    * **返回的是"档位"而不是物品名**——具体换成哪个食物属于素材配置问题，
      由调用方用 `resolve_tiers()` + `items.json` 决定。这样用户在 `items.json`
      里改名/增删食物时，本函数与它的单测完全不受影响。
    * `streak == 1`（首次、或断签后重新开始）额外给引导好感度。
    * 里程碑命中时 `milestone` 记为命中的连签天数，调用方据此选 `checkin_milestone` 台词。
    """
    table = table if isinstance(table, Mapping) else DEFAULT_CHECKIN_TABLE
    try:
        streak = max(0, int(streak))
    except (TypeError, ValueError):
        streak = 0

    tiers: dict[str, int] = {}
    base_items = table.get("base_items")
    if isinstance(base_items, Mapping):
        for tier, n in base_items.items():
            tiers[tier] = tiers.get(tier, 0) + safe_int(n)

    affection = safe_int(table.get("base_affection"))
    if streak == 1:
        affection += safe_int(table.get("first_affection"))

    milestone = None
    ms = _milestone_of(streak, table.get("milestones"))
    if ms is not None:
        milestone = streak
        ms_items = ms.get("items")
        if isinstance(ms_items, Mapping):
            for tier, n in ms_items.items():
                tiers[tier] = tiers.get(tier, 0) + safe_int(n)
        affection += safe_int(ms.get("affection"))

    return {"tiers": tiers, "affection": affection, "milestone": milestone}


def resolve_tiers(
    tiers: Mapping[str, int],
    pool: Mapping[str, Sequence[str]],
    rng: random.Random | None = None,
) -> dict[str, int]:
    """把「档位 → 数量」解析成「物品名 → 数量」。

    `pool` 形如 `{"common": ["奶油面包", "饭团"], ...}`（由 `items.json` 按档位归并而来）。
    * 某档位在 `pool` 里没有候选 → 跳过该档位（该次产出作废，**不报错**）
    * 数量超过候选个数 → 允许重复抽取（同一种食物拿两份）
    """
    chooser = rng if rng is not None else random
    result: dict[str, int] = {}
    if not isinstance(tiers, Mapping):
        return result
    for tier, count in tiers.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        candidates = list(pool.get(tier) or []) if isinstance(pool, Mapping) else []
        if not candidates:
            continue
        for _ in range(n):
            name = chooser.choice(candidates)
            result[name] = result.get(name, 0) + 1
    return result


# ────────────────────────── 好感度 ──────────────────────────


def tier_affection_gain(tier: str, table: Mapping | None = None) -> int:
    """档位对应的好感度增量（未知档位按最低档处理）。"""
    src = table if isinstance(table, Mapping) and table else DEFAULT_AFFECTION_GAIN
    try:
        return max(0, int(src.get(tier, src.get(TIER_COMMON, 1))))
    except (TypeError, ValueError):
        return 0


def tier_pool(items: Sequence[Mapping] | None, kind: str | None = None) -> dict[str, list[str]]:
    """把 `items.json` 的条目按**档位**归并成 `{档位: [物品名]}`，供 `resolve_tiers()` 用。

    `kind` 给了就只收该类型（签到/彩蛋只发食物，节日表则直接点名物品、不走这里）。
    同一档位内**保持文件里的顺序**（用户调整 `items.json` 的顺序即可影响抽取偏好）。
    脏值（缺 name / 不在 `TIERS` 里的档位）一律跳过，绝不抛异常。
    """
    pool: dict[str, list[str]] = {}
    if not items:
        return pool
    for entry in items:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", "")).strip()
        tier = str(entry.get("tier", ""))
        if not name or tier not in TIERS:
            continue
        if kind is not None and str(entry.get("kind", KIND_FOOD)) != str(kind):
            continue
        bucket = pool.setdefault(tier, [])
        if name not in bucket:                 # 同名重复条目只算一次
            bucket.append(name)
    return pool


# ────────────────────────── 好感度 ──────────────────────────


def apply_affection(
    cur: int,
    want: int,
    gained_today: int,
    daily_cap: int,
) -> tuple[int, int]:
    """好感度入账。返回 `(新好感度, 实际增量)`。

    * 受**每日上限**截断；`want` 本身不做硬截断（好感度软上限 1000 只影响进度条显示）
    * 已满时返回 `(cur, 0)` —— 调用方据此照常播动画/台词，只额外接一句「今天已经很开心了」
    * 负增量被吃掉（好感度只增不减，01 文档 0.4 原则 2）
    """
    cur = max(0, safe_int(cur))
    want = safe_int(want)
    gained_today = max(0, safe_int(gained_today))
    daily_cap = max(0, safe_int(daily_cap))
    if want <= 0:
        return cur, 0
    room = max(0, daily_cap - gained_today)
    actual = min(want, room)
    return cur + actual, actual


def affection_ratio(affection: int, soft_cap: int = SOFT_AFFECTION_CAP) -> float:
    """好感度进度条比例，夹在 `[0.0, 1.0]`。`soft_cap <= 0` 时返回 0.0。"""
    soft_cap = safe_int(soft_cap)
    if soft_cap <= 0:
        return 0.0
    return max(0.0, min(1.0, safe_int(affection) / soft_cap))


# ────────────────────────── 等级与解锁 ──────────────────────────


def _sorted_levels(levels: Sequence | None) -> list[dict]:
    """规范化等级表：丢掉没有合法 `threshold` 的条目、按阈值升序。

    * 缺 `threshold` 键、或阈值无法解析成整数的条目 → **跳过**（而不是当成 0，
      否则一条手误的条目会把整张表压成单级）
    * 过滤后为空 → 用代码内兜底表，保证 `levels.json` 缺失/损坏时功能降级而非崩溃
    """
    src = levels if isinstance(levels, Sequence) and not isinstance(levels, (str, bytes)) else None
    cleaned: list[dict] = []
    if src:
        for item in src:
            if not isinstance(item, Mapping) or "threshold" not in item:
                continue
            try:
                threshold = int(item["threshold"])
            except (TypeError, ValueError):
                continue
            merged = dict(item)
            merged["threshold"] = max(0, threshold)
            cleaned.append(merged)
    if not cleaned:
        cleaned = [dict(x) for x in DEFAULT_LEVELS]
    cleaned.sort(key=lambda d: d["threshold"])
    return cleaned


def level_of(affection: int, levels: Sequence | None = None) -> int:
    """好感度 → 等级下标（0 起）。低于第一个阈值时返回 0。"""
    table = _sorted_levels(levels)
    value = max(0, safe_int(affection))
    index = 0
    for i, item in enumerate(table):
        if value >= item["threshold"]:
            index = i
        else:
            break
    return index


def level_info(affection: int, levels: Sequence | None = None) -> dict:
    """等级详情，供状态页显示。

    返回 `{"index", "title", "threshold", "next_threshold", "next_title", "is_max"}`。
    """
    table = _sorted_levels(levels)
    index = level_of(affection, table)
    cur = table[index]
    is_max = index >= len(table) - 1
    nxt = table[index + 1] if not is_max else None
    return {
        "index": index,
        "title": str(cur.get("title") or ""),
        "threshold": cur["threshold"],
        "next_threshold": nxt["threshold"] if nxt else None,
        "next_title": str(nxt.get("title") or "") if nxt else "",
        "is_max": is_max,
    }


def unlocked_features(level_index: int, levels: Sequence | None = None) -> set[str]:
    """累计到 `level_index` 为止解锁的全部功能标识。

    等级表里每一级的 `unlocks` 是**增量**（本级新增什么），本函数负责做并集。
    """
    table = _sorted_levels(levels)
    idx = max(0, min(safe_int(level_index), len(table) - 1))
    result: set[str] = set()
    for item in table[: idx + 1]:
        unlocks = item.get("unlocks")
        if isinstance(unlocks, Iterable) and not isinstance(unlocks, (str, bytes)):
            for key in unlocks:
                result.add(str(key))
    return result


# ────────────────────────── 动画兜底链 ──────────────────────────


def resolve_anim(
    item: Mapping | None,
    kind: str,
    registry_has: Callable[[str], bool],
    fallback_all: str = GLOBAL_FALLBACK_ANIM,
) -> str | None:
    """四级兜底链（01 文档 3.3）：

    ```
    食物自身 anim → 类型默认（食物"笑"/礼物"点赞"） → 全局兜底（"害羞 2"） → None
    ```

    返回 `None` 表示"素材全缺"——调用方**只出对话气泡、不播动画**，绝不崩溃、绝不黑屏。
    `registry_has` 抛异常时按"该动作不存在"处理（素材库读取失败不应影响喂食）。
    """

    def exists(action) -> bool:
        if not action or not isinstance(action, str):
            return False
        try:
            return bool(registry_has(action))
        except Exception:
            return False

    candidates: list = []
    if isinstance(item, Mapping):
        candidates.append(item.get("anim"))
    candidates.append(KIND_FALLBACK_ANIM.get(str(kind or "").strip().lower()))
    candidates.append(fallback_all)

    for action in candidates:
        if exists(action):
            return action
    return None


# ────────────────────────── 陪伴兑换 ──────────────────────────


def convert_to_items(
    progress: int,
    per: int,
    cap: int,
    already: int,
) -> tuple[int, int]:
    """把累计进度（分钟 / 按键数）换算成产出。返回 `(本次获得个数, 剩余进度)`。

    * `progress` 是**当日**累计值（跨天清零），`already` 是今日**已经兑换出去的个数**
    * 本次能发几个 = `进度折合的份数 − 已兑换份数`，再受每日上限 `room = cap - already` 约束
    * `cap` 是每日上限；达到上限后本次不发放，且剩余进度只保留不足一份的零头
      （否则会在次日上限重置时爆出一堆产出）
    * `per <= 0` 视为配置错误 → 不发放，进度原样返回（防除零）

    > **`already` 必须真的参与减法**（阶段 F 的教训）：只把它用在"还剩几个额度"上，
    > 同一份进度就会在之后每一次心跳里**反复兑换**（进度 2 份、已兑 1 个、上限 3
    > → 每次都还能再兑 1 个）。表现是"挂着不动，食物自己一直涨"。
    """
    progress = max(0, safe_int(progress))
    per = safe_int(per)
    if per <= 0:
        return 0, progress
    cap = max(0, safe_int(cap))
    already = max(0, safe_int(already))
    room = max(0, cap - already)
    unpaid = max(0, progress // per - already)
    granted = min(unpaid, room)
    return granted, progress % per


# ────────────────────────── 节日 / 彩蛋 ──────────────────────────


def event_for_date(
    events: Sequence[Mapping] | None,
    today: date,
    birthday: str | date | None = None,
) -> dict | None:
    """取今天命中的节日条目（`events.json`）。没有命中返回 `None`。

    * `date` 是 `"MM-DD"`（每年重复）；特殊值 `"birthday"` 表示"用户在设置里填的生日"
    * 生日为空 / 格式不对 → 该条**跳过**（不是报错）—— 没填生日就是不过生日
    * 同一天命中多条 → 取文件里靠前的那条（用户可用顺序表达优先级）
    * 返回**副本**，调用方改它不会污染调用方传进来的表
    """
    if not events:
        return None
    today_d = parse_date(today)
    if today_d is None:
        return None
    mmdd = today_d.strftime("%m-%d")
    birthday_mmdd = ""
    raw_birthday = str(birthday or "").strip()
    if _MONTH_DAY_RE.match(raw_birthday):
        birthday_mmdd = raw_birthday
    elif isinstance(birthday, date):
        birthday_mmdd = birthday.strftime("%m-%d")

    for entry in events:
        if not isinstance(entry, Mapping):
            continue
        raw = str(entry.get("date", "")).strip()
        if raw == BIRTHDAY_TOKEN:
            if birthday_mmdd and birthday_mmdd == mmdd:
                return dict(entry)
            continue
        if raw == mmdd:
            return dict(entry)
    return None


def event_items(event: Mapping | None) -> dict[str, int]:
    """把节日条目的 `items` 解析成 `{物品名: 数量}`（脏值跳过，数量至少 1）。"""
    result: dict[str, int] = {}
    if not isinstance(event, Mapping):
        return result
    entries = event.get("items")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return result
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        count = max(1, safe_int(entry.get("count", 1)))
        result[name] = result.get(name, 0) + count
    return result


# ────────────────────────── 语气禁区 ──────────────────────────


def in_night(hour: int, night_start: int = DEFAULT_NIGHT_START,
             night_end: int = DEFAULT_NIGHT_END) -> bool:
    """`hour` 是否落在深夜时段（默认 23:00–06:00，含 23 点、不含 6 点）。"""
    h = safe_int(hour) % 24
    start = safe_int(night_start) % 24
    end = safe_int(night_end) % 24
    if start == end:
        return False                   # 配置成零长度 → 视为"无深夜时段"
    if start < end:
        return start <= h < end
    return h >= start or h < end


def is_focus_mode(
    typing_rate: int = 0,
    continuous_min: int = 0,
    app_key: str | None = None,
    *,
    typing_rate_threshold: int = DEFAULT_TYPING_RATE_THRESHOLD,
    continuous_min_threshold: int = DEFAULT_CONTINUOUS_MIN_THRESHOLD,
    fullscreen: bool = False,
    focus_app_keys: Sequence[str] = FOCUS_APP_KEYS,
) -> bool:
    """是否处于"别打扰"状态（01 文档 7.3 第 2、3 条 + 02 文档 4.11）。

    命中任一条件即为真：高频打字 / 连续活跃超时 / 前台是会议软件 / 前台全屏。
    """
    if safe_int(typing_rate) > safe_int(typing_rate_threshold):
        return True
    if safe_int(continuous_min) > safe_int(continuous_min_threshold):
        return True
    if fullscreen:
        return True
    if app_key and str(app_key).strip().lower() in {str(k).lower() for k in focus_app_keys}:
        return True
    return False


def is_proactive_allowed(
    app_key: str | None = None,
    *,
    fullscreen: bool = False,
    blocking_app_keys: Sequence[str] = BLOCKING_APP_KEYS,
) -> bool:
    """前台处于"完全不发主动台词"的分类（游戏 / 会议 / 全屏）时返回 `False`。"""
    if fullscreen:
        return False
    if app_key and str(app_key).strip().lower() in {str(k).lower() for k in blocking_app_keys}:
        return False
    return True


def is_tease_allowed(
    tone: str,
    hour: int,
    typing_rate: int = 0,
    continuous_min: int = 0,
    tease_today: int = 0,
    tease_cap: int = DEFAULT_TEASE_DAILY_CAP,
    *,
    mute_today: bool = False,
    tease_probability: float = 1.0,
    typing_rate_threshold: int = DEFAULT_TYPING_RATE_THRESHOLD,
    continuous_min_threshold: int = DEFAULT_CONTINUOUS_MIN_THRESHOLD,
    night_start: int = DEFAULT_NIGHT_START,
    night_end: int = DEFAULT_NIGHT_END,
) -> bool:
    """01 文档 7.1 的**七条硬禁区**落地处。

    非 `tease` 语气一律放行。`tease` 需同时满足：

    1. 用户未开「今天不要捉弄我」(`mute_today`)
    2. 「捉弄频率」不为 `off`（`tease_probability > 0`）
    3. 不在深夜时段
    4. 不是高频打字（专注）
    5. 不是连续工作超时（专注）
    6. 今日额度未耗尽

    > 「不评论工作内容」「不质问不抱怨」「不做评判」属于**文案层**约束，
    > 由台词库自查 + 阶段 H 验收清单保证，无法在数值层判定。
    """
    if str(tone or "").strip().lower() != TONE_TEASE:
        return True
    if mute_today:
        return False
    try:
        if float(tease_probability) <= 0.0:
            return False
    except (TypeError, ValueError):
        return False
    if in_night(hour, night_start, night_end):
        return False
    if safe_int(typing_rate) > safe_int(typing_rate_threshold):
        return False
    if safe_int(continuous_min) > safe_int(continuous_min_threshold):
        return False
    if safe_int(tease_today) >= max(0, safe_int(tease_cap)):
        return False
    return True


def tease_probability_of(frequency: str) -> float:
    """设置项「捉弄频率」→ 概率。未知值按默认档 `sometimes`。"""
    key = str(frequency or "").strip().lower()
    if key in TEASE_PROBABILITY:
        return TEASE_PROBABILITY[key]
    return TEASE_PROBABILITY[DEFAULT_TEASE_FREQUENCY]


# ────────────────────────── 库存上限 ──────────────────────────


def tier_cap(tier: str, caps: Mapping | None = None) -> int:
    """档位单类上限。未知档位按普通档处理。"""
    src = caps if isinstance(caps, Mapping) and caps else DEFAULT_TIER_CAPS
    try:
        return max(0, int(src.get(tier, src.get(TIER_COMMON, 0))))
    except (TypeError, ValueError):
        return 0


def can_accept(tier: str, current_count: int, caps: Mapping | None = None) -> bool:
    """该物品当前还能不能再收一个（01 文档 2.3 / 4.4「库存已满时获得」）。"""
    return max(0, safe_int(current_count)) < tier_cap(tier, caps)


# ────────────────────────── 时间场景 ──────────────────────────


def time_scene_of(hour: int) -> str | None:
    """当前小时对应的"首次时段问候"场景，无对应时段返回 `None`。

    与 01 文档 7.2 的 `time_*` 场景一一对应。
    """
    h = safe_int(hour) % 24
    if 6 <= h < 9:
        return "time_morning"
    if 11 <= h < 13:
        return "time_noon"
    if h == 23:
        return "time_night"
    if 0 <= h < 6:
        return "time_late"
    return None


def greeting_for_hour(hour: int) -> str:
    """按小时给一个中性问候语（仅用于代码内兜底台词）。"""
    h = safe_int(hour) % 24
    if 5 <= h < 11:
        return "早上好"
    if 11 <= h < 14:
        return "中午了"
    if 14 <= h < 18:
        return "下午好"
    if 18 <= h < 23:
        return "晚上好"
    return "还没睡呀"


# ────────────────────────── 内部工具 ──────────────────────────


def safe_int(value) -> int:
    """任何脏值 → 0。存档是用户可手改的 JSON，绝不能因此抛异常。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
