"""养成系统台词库 —— 加载 `assets/nurture/dialogues/*.json` 并按场景选句。

对应需求：`docs/nurture/01-需求规格.md` 7.4；对应方案：`02-技术方案.md` 4.3。

**设计约束**：本模块**不 import PySide6**（原方案写的是 `QObject`，但它没有任何信号，
做成普通类比继承 `QObject` 更好：台词库能被单测直接实例化，不需要起 `QApplication`，
也和 `nurture_model` 一样保持"纯逻辑可单测"）。

**选句流程**（严格按 02 文档 4.3 的顺序）：

1. 场景文件不存在/解析失败 → 用代码内 `DEFAULT_SCENES` 兜底 → 仍无 → 返回 `None`（**不抛异常**）
2. 过滤 `min_level` 未达成的台词
3. 过滤 `tone == "tease"` 且禁区判定为假的**整组**
4. 过滤最近已用的（`store.used_lines`）；若全被过滤则清空记录重来一轮
5. 按 `weight` 加权随机
6. 占位符替换（`{level}` / `{streak}` / `{hour}` / `{app}` / `{min}` ...）
7. 记入 `used_lines`

**占位符白名单**：只有 `ctx` 里显式提供的键能替换；缺失键**原样保留**且不报错
（`str.format_map` + `__missing__`，见 `_KeepDict`）。
"""

from __future__ import annotations

import json
import os
import random
from typing import Any, Iterable, Mapping

#: 默认台词目录（与 `nurture_icons.default_icons_dir()` 各自独立，保证模块可单独 import）
_DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "nurture", "dialogues",
)

#: 单条台词长度上限（03 设计规范 9：气泡最大宽 220px，超过两行就显得吵）
MAX_LINE_CHARS = 18

#: 允许出现在台词里的占位符。模板里出现表外的键会被**原样保留**，不会被替换
PLACEHOLDER_KEYS: tuple[str, ...] = (
    "level",     # 称号（如「同桌」）
    "streak",    # 连签天数
    "hour",      # 当前小时
    "app",       # 前台应用的中性称呼（如「浏览器」），拿不到标题原文
    "min",       # 连续活跃分钟数
    "count",     # 数量（库存 / 产出个数）
    "name",      # 物品名
    "days",      # 距上次互动的天数
)

#: 语气档位（与 `nurture_model.TONE_*` 一致；这里重复定义是为了不依赖 model）
TONE_GENTLE = "gentle"
TONE_PROUD = "proud"
TONE_TEASE = "tease"
TONES: tuple[str, ...] = (TONE_GENTLE, TONE_PROUD, TONE_TEASE)

#: **主动**台词场景：受「全局最小间隔」与「专注/全屏保护」约束（01 文档 7.3）
PROACTIVE_SCENES: frozenset[str] = frozenset({
    "idle_random", "idle_long_absent", "hover_long",
    "time_morning", "time_noon", "time_night", "time_late", "time_hourly",
    "detect_typing", "detect_typing_long", "detect_audio", "detect_muted",
    "detect_app_code", "detect_app_browser", "detect_app_game",
    "detect_app_meeting", "detect_app_media",
    "event_valentine", "event_tanabata", "event_christmas", "event_new_year",
    "event_birthday",
})

#: 免于「全局最小间隔」的场景。
#: 启动问候与用户主动触发的台词不该被 90 秒间隔拦掉——那只会让用户觉得"点了没反应"。
#: 阶段 F 补入的是**"有东西到手"的通知**（签到/兑换/彩蛋/库存满）：它们不是她主动找话，
#: 而是对一次状态变化的交代 —— 被 90 秒间隔或专注保护吞掉，用户就只会看到"库存莫名多了"。
#: （所以这些场景**不放进** `PROACTIVE_SCENES`，两个集合的交集必须为空。）
GAP_EXEMPT_SCENES: frozenset[str] = frozenset({
    "startup_hello", "feed_done", "feed_fav", "gift_done", "feed_full",
    "feed_empty", "checkin_done", "checkin_milestone", "level_up",
    "settings_saved", "headpat", "small_talk", "error_anim_missing",
    "checkin_already", "checkin_clock_back", "checkin_remind",
    "inventory_full", "convert_minutes", "convert_typing",
    "egg_hourly", "egg_afk", "first_run",
})

#: 代码内兜底台词。`assets/nurture/dialogues/` 被删掉/改坏时仍能说话。
#: 每条都遵守 01 文档 7.1 的七禁区（≤18 字、不质问、不抱怨、不评判、不说教）
DEFAULT_SCENES: dict[str, dict] = {
    "startup_hello": {
        "scene": "startup_hello", "tone": TONE_GENTLE, "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [
            {"text": "我来了。", "weight": 3},
            {"text": "今天也在。", "weight": 2},
            {"text": "又是新的一天。", "weight": 2},
            {"text": "我坐这里，可以吗。", "weight": 1, "tone": TONE_PROUD},
        ],
    },
    "feed_done": {
        "scene": "feed_done", "tone": TONE_GENTLE, "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [
            {"text": "……谢谢。", "weight": 3},
            {"text": "唔，好吃。", "weight": 2, "tone": TONE_PROUD},
            {"text": "我慢慢吃，你别看着我。", "weight": 2},
            {"text": "这个我收下了。", "weight": 2, "tone": TONE_PROUD},
        ],
    },
    "feed_empty": {
        "scene": "feed_empty", "tone": TONE_GENTLE, "cooldown_sec": 30, "min_gap_sec": 0,
        "lines": [
            {"text": "这个已经吃完了呢。", "weight": 3},
            {"text": "没有了，明天再看看吧。", "weight": 2},
            {"text": "柜子里空空的。", "weight": 1},
        ],
    },
    "checkin_done": {
        "scene": "checkin_done", "tone": TONE_PROUD, "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [
            {"text": "连签 {streak} 天了。", "weight": 3},
            {"text": "这是今天的份。", "weight": 3},
            {"text": "唔，收好了。", "weight": 1},
        ],
    },
    "idle_random": {
        "scene": "idle_random", "tone": TONE_GENTLE, "cooldown_sec": 360, "min_gap_sec": 0,
        "lines": [
            {"text": "我在呢。", "weight": 3},
            {"text": "不用管我，你忙。", "weight": 2},
            {"text": "安静一会儿也不错。", "weight": 2},
            {"text": "要一起发呆吗。", "weight": 1, "tone": TONE_PROUD},
        ],
    },
    "detect_typing": {
        "scene": "detect_typing", "tone": TONE_GENTLE, "cooldown_sec": 600, "min_gap_sec": 0,
        "lines": [
            {"text": "敲得好快。", "weight": 2},
            {"text": "我安静一点。", "weight": 2},
            {"text": "我不打扰你。", "weight": 2},
        ],
    },
    "feed_full": {
        "scene": "feed_full", "tone": TONE_GENTLE, "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [
            {"text": "今天已经很开心了。", "weight": 3},
            {"text": "够了，真的。", "weight": 1},
        ],
    },
    # ── 阶段 F：获取途径的兜底台词 ──
    # 这几个场景**必须**有兜底：用户点了签到却一句话都没有，会被当成"功能没做"。
    "checkin_already": {
        "scene": "checkin_already", "tone": TONE_GENTLE, "cooldown_sec": 60, "min_gap_sec": 0,
        "lines": [
            {"text": "今天已经签过了。", "weight": 3},
            {"text": "唔，一天只有一次。", "weight": 2},
            {"text": "明天还有的。", "weight": 1},
        ],
    },
    "checkin_clock_back": {
        "scene": "checkin_clock_back", "tone": TONE_GENTLE, "cooldown_sec": 60, "min_gap_sec": 0,
        "lines": [
            {"text": "时间好像不太对。", "weight": 3},
            {"text": "这个先不算数。", "weight": 2},
            {"text": "等时间对上了再来吧。", "weight": 1},
        ],
    },
    "inventory_full": {
        "scene": "inventory_full", "tone": TONE_GENTLE, "cooldown_sec": 60, "min_gap_sec": 0,
        "lines": [
            {"text": "拿不下啦，先送掉一些吧。", "weight": 3},
            {"text": "柜子满了。", "weight": 2},
            {"text": "留着下次给你。", "weight": 1},
        ],
    },
    "error_anim_missing": {
        "scene": "error_anim_missing", "tone": TONE_GENTLE, "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [],
    },
}


class _KeepDict(dict):
    """`str.format_map` 用的字典：缺失键原样保留成 `{key}`，不抛 `KeyError`。"""

    def __missing__(self, key):        # noqa: D105
        return "{" + str(key) + "}"


def is_proactive(scene: str) -> bool:
    """该场景是否属于「主动台词」（受最小间隔与专注保护约束）。"""
    return str(scene) in PROACTIVE_SCENES


def is_gap_exempt(scene: str) -> bool:
    """该场景是否免于「全局最小间隔」。"""
    return str(scene) in GAP_EXEMPT_SCENES


def _normalize_tone(value, fallback: str = TONE_GENTLE) -> str:
    tone = str(value or "").strip().lower()
    return tone if tone in TONES else fallback


def _normalize_line(raw, scene_tone: str) -> dict | None:
    """把一条台词捏成合法结构；无法使用时返回 `None`。"""
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, Mapping):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    try:
        weight = max(1, int(raw.get("weight", 1)))
    except (TypeError, ValueError):
        weight = 1
    try:
        min_level = max(0, int(raw.get("min_level", 0)))
    except (TypeError, ValueError):
        min_level = 0
    return {
        "text": text,
        "weight": weight,
        "min_level": min_level,
        "tone": _normalize_tone(raw.get("tone"), scene_tone),
    }


def _normalize_scene(scene: str, raw: Mapping) -> dict:
    tone = _normalize_tone(raw.get("tone"), TONE_GENTLE)
    lines: list[dict] = []
    for item in raw.get("lines") or ():
        line = _normalize_line(item, tone)
        if line is not None:
            lines.append(line)

    def _int(key: str, default: int = 0) -> int:
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "scene": str(raw.get("scene") or scene),
        "tone": tone,
        "cooldown_sec": _int("cooldown_sec"),
        "min_gap_sec": _int("min_gap_sec"),
        "lines": lines,
    }


class DialogueLibrary:
    """场景 → 台词池。用户可随时编辑 JSON，`reload()` 后立即生效（无需重启）。"""

    def __init__(self, dialogues_dir: str | None = None, store=None, parent=None,
                 rng: random.Random | None = None) -> None:
        #: 目录
        self.dir = dialogues_dir or _DEFAULT_DIR
        #: 防重复用的存档（鸭子类型：只要有 `used_lines` / `remember_line` / `forget_lines`）
        self.store = store
        self._parent = parent
        self._rng = rng or random.Random()
        self._scenes: dict[str, dict] = {}
        self._errors: dict[str, str] = {}
        self._loaded = False

    # ────────────────── 加载 ──────────────────

    @property
    def errors(self) -> dict[str, str]:
        """文件名 → 解析失败原因。用于日志排查（**不是**用户可见错误）。"""
        return dict(self._errors)

    def reload(self) -> None:
        """重新扫描目录。文件缺失/损坏只影响对应场景（走代码内兜底），不抛异常。"""
        self._scenes = {}
        self._errors = {}
        self._loaded = True
        if not os.path.isdir(self.dir):
            return
        try:
            names = sorted(n for n in os.listdir(self.dir) if n.lower().endswith(".json"))
        except OSError as exc:
            self._errors["<dir>"] = str(exc)
            return
        for name in names:
            scene_id = os.path.splitext(name)[0]
            path = os.path.join(self.dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._errors[name] = str(exc)
                continue
            if not isinstance(raw, Mapping):
                self._errors[name] = "根节点不是对象"
                continue
            scene = _normalize_scene(scene_id, raw)
            if not scene["lines"]:
                # 空池是合法的（03 规范 9「允许沉默」），不算错误
                pass
            self._scenes[scene_id] = scene

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.reload()

    def scenes(self) -> list[str]:
        """已加载的场景 id（含空池场景）。"""
        self._ensure_loaded()
        return sorted(self._scenes.keys())

    def has_scene(self, scene: str) -> bool:
        """该场景是否**有可用台词**（文件里没有则看代码内兜底）。"""
        return bool(self._scene_of(scene)["lines"])

    def scene_meta(self, scene: str) -> dict:
        """场景元信息 `{tone, cooldown_sec, min_gap_sec}`，供 controller 建冷却表。"""
        meta = self._scene_of(scene)
        return {
            "tone": meta["tone"],
            "cooldown_sec": meta["cooldown_sec"],
            "min_gap_sec": meta["min_gap_sec"],
        }

    def cooldowns(self) -> dict[str, tuple[int, int]]:
        """全部场景的 `{场景: (冷却秒, 最小间隔秒)}`。"""
        self._ensure_loaded()
        ids = set(self._scenes) | set(DEFAULT_SCENES)
        return {s: (self._scene_of(s)["cooldown_sec"], self._scene_of(s)["min_gap_sec"])
                for s in sorted(ids)}

    def all_lines(self) -> list[tuple[str, dict]]:
        """全部 `(场景, 台词)` 对。供配置自检使用（字数、"不评判"句式、占位符白名单）。

        **必须走 `_normalize_scene()`**：代码内兜底台词是"半成品"（大多没写 `tone` /
        `min_level`），直接吐出去会让调用方拿不到这两个键。
        """
        self._ensure_loaded()
        source = dict(DEFAULT_SCENES)
        source.update(self._scenes)
        result: list[tuple[str, dict]] = []
        for sid, raw in source.items():
            for line in _normalize_scene(sid, raw)["lines"]:
                result.append((sid, dict(line)))
        return result

    def _scene_of(self, scene: str) -> dict:
        """取场景（优先用户文件，其次代码内兜底）。永远返回结构完整的 dict。

        **"文件存在但池为空" 与 "没有这个文件" 是两回事**：

        * 用户显式写了 `"lines": []` → 那次就不说话（03 规范 9「允许沉默」），
          此时**不能**悄悄用代码内兜底台词顶上去，否则用户永远关不掉一句话
        * 文件不存在 / 解析失败 → 用代码内兜底，保证功能降级而不是变哑巴
        """
        self._ensure_loaded()
        meta = self._scenes.get(str(scene))
        if meta is not None:
            return meta                     # 有文件 → 以文件为准（空池即沉默）
        fallback = DEFAULT_SCENES.get(str(scene))
        if fallback is not None:
            return _normalize_scene(str(scene), fallback)
        return {"scene": str(scene), "tone": TONE_GENTLE, "cooldown_sec": 0,
                "min_gap_sec": 0, "lines": []}

    # ────────────────── 选句 ──────────────────

    def pick_line(self, scene: str, ctx: Mapping | None = None, *,
                  affection: int = 0, tease_allowed: bool = True) -> dict | None:
        """选一条台词。返回 `{"text", "tone"}`；**没有可用台词时返回 `None`**。

        :param affection: 当前好感度。台词里的 `min_level` 写的是**好感度阈值**
            （与 `levels.json` 的 threshold 同刻度，如 250），不是等级下标 —— 这是
            01 文档 7.4 的示例格式决定的，别传成下标。
        :param tease_allowed: 禁区判定结果（由 `nurture_model.is_tease_allowed()` 算出）。
            为 `False` 时 `tease` 台词被**整组**剔除。

        `tone` 必须回传：controller 靠它决定要不要计 `tease_count_today`。
        """
        meta = self._scene_of(scene)
        pool = meta["lines"]
        if not pool:
            return None

        level = max(0, _as_int(affection))
        candidates = [line for line in pool if line["min_level"] <= level]
        if not tease_allowed:
            candidates = [line for line in candidates if line["tone"] != TONE_TEASE]
        if not candidates:
            return None

        candidates = self._avoid_repeats(scene, candidates)
        chosen = self._weighted_choice(candidates)
        if chosen is None:
            return None

        text = format_line(chosen["text"], ctx)
        if self.store is not None:
            try:
                self.store.remember_line(scene, text)
            except Exception:
                pass                        # 存档写不进去也不能影响说话
        return {"text": text, "tone": chosen["tone"]}

    def pick(self, scene: str, ctx: Mapping | None = None, **kwargs) -> str | None:
        """`pick_line()` 的便捷版，只要文本。"""
        result = self.pick_line(scene, ctx, **kwargs)
        return result["text"] if result else None

    def _avoid_repeats(self, scene: str, candidates: list[dict]) -> list[dict]:
        """剔除最近说过的；若全被剔除则清空记录，重来一轮（否则会永远沉默）。"""
        if self.store is None:
            return candidates
        try:
            used = list(self.store.used_lines(scene))
        except Exception:
            return candidates
        if not used:
            return candidates
        fresh = [line for line in candidates if line["text"] not in used]
        if fresh:
            return fresh
        try:
            self.store.forget_lines(scene)
        except Exception:
            pass
        return candidates

    def _weighted_choice(self, candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        weights = [max(1, _as_int(line.get("weight"), 1)) for line in candidates]
        try:
            return self._rng.choices(candidates, weights=weights, k=1)[0]
        except (ValueError, TypeError):
            return self._rng.choice(candidates)


# ────────────────────────── 占位符 ──────────────────────────


def format_line(text: str, ctx: Mapping | None = None) -> str:
    """替换 `{key}` 占位符。

    * 只有 `ctx` 里有的键会被替换，其余**原样保留**（`{unknown}` 保持原状）
    * 模板本身写坏（比如落单的 `{`）→ 返回原文，**不抛异常**
    """
    if not isinstance(text, str) or "{" not in text:
        return text
    data = ctx if isinstance(ctx, Mapping) else {}
    try:
        return text.format_map(_KeepDict(data))
    except (ValueError, IndexError, KeyError, TypeError):
        return text


def placeholders_in(text: str) -> set[str]:
    """提取模板里出现的占位符名（配置自检用）。"""
    import string

    found: set[str] = set()
    try:
        for _, field, _, _ in string.Formatter().parse(str(text)):
            if field:
                found.add(field.split(".")[0].split("[")[0])
    except ValueError:
        return set()
    return found


def iter_dialogue_files(dialogues_dir: str | None = None) -> Iterable[str]:
    """列出目录下的台词文件（自检用）。"""
    directory = dialogues_dir or _DEFAULT_DIR
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                  if n.lower().endswith(".json"))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
