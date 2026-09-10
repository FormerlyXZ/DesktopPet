"""养成控制器 `NurtureController` —— 养成系统的**业务层**。

数据流：

```
HoverMenu.action_triggered ──→ PetWindow._on_hover_menu_action
                                    └─→ NurtureController.on_menu_action()
NurturePanel.item_chosen   ──→ NurtureController.try_send()        ← 送出去（阶段 D）
InputMonitor.key_pressed   ──→ PetWindow.on_key_press()
                                    └─→ NurtureController.on_key_press()   ← 打字量进度
InputMonitor.any_activity  ──→ PetWindow.on_any_activity()
                                    └─→ NurtureController.notify_activity() ← 陪伴时长进度
QTimer(60s)                ──→ NurtureController.on_idle_tick()    ← 获取途径结算（阶段 F）
                                    ├─ 签到产出 / 陪伴兑换 / 打字兑换 / 彩蛋
                                    ├─ 扣库存 / 加好感度（NurtureStore + nurture_model 规则）
                                    ├─ 角色播动画（CharacterController.play_action，锁定不可打断）
                                    ├─ 取一句台词（DialogueLibrary）
                                    └─ speech_requested 信号 ──→ SpeechBubble（阶段 E）
WindowMonitor.app_changed  ──→ NurtureController.on_app_changed()   ← 前台分类（阶段 G）
WindowMonitor.fullscreen_changed ─→ on_fullscreen_changed()          ← 全屏静默（阶段 G）
```

**这一层不含任何几何与绘制**：面板放哪、菜单长什么样都由 UI 组件自己决定，
controller 只回答"这一下点下去，该发生什么"。

阶段 F 的约定：**发放与播报解耦**。物品先到手，台词说不说得出来是另一回事
（被 90 秒间隔或专注保护挡下只是"没说出口"，不该把食物一起吞掉）；
而记日期的 flag 反过来**只在真的说出来了之后才写**，免得被挡一次就整天不再说。
"""

from __future__ import annotations

import json
import os
import random
import time
from collections import deque
from datetime import date, datetime

from PySide6.QtCore import QObject, Signal

from src import nurture_model as model
from src import nurture_store as store_mod
from src.dialogue import DialogueLibrary, format_line, is_gap_exempt, is_proactive

#: 一次送出可能得到的结果。`try_send()` 返回其中之一
RESULT_OK = "ok"                    # 送出去了，动画在播
RESULT_EMPTY = "empty"              # 库存为 0
RESULT_UNKNOWN = "unknown"          # 物品名不在 items.json 里
RESULT_CAPPED = "capped"            # 好感度到今日上限（动画照播，只是不加好感度）
RESULT_GIFT_CAPPED = "gift_capped"  # 今日送礼次数已满
RESULT_LOCKED = "locked"            # 她正忙（启动序列 / 上一个动画还没播完）
RESULT_COOLDOWN = "cooldown"        # 连点防护（刚送过，300ms 内不再受理）
RESULT_NO_ANIM = "no_anim"          # 素材全缺：只出台词，不播动画
RESULT_DISABLED = "disabled"        # 养成关闭，或当前角色不是 Q版
RESULT_ALREADY = "already"          # 签到：今天已经签过了（阶段 F）
RESULT_CLOCK_BACK = "clock_back"    # 签到：系统时间被往回调 → 不发放不重置（阶段 F）

#: 结果码 → 是否算"真的送出去了"（扣了库存、开始播动画）
SUCCESS_RESULTS = frozenset({RESULT_OK, RESULT_CAPPED})

#: 送失败时该出的台词场景（对应 01 文档 6.4 的分支表）
FAIL_SCENE = {
    RESULT_EMPTY: "feed_empty",
    RESULT_GIFT_CAPPED: "gift_capped",
}

#: 「库存满了」的统一提示（01 文档 4.4）。签到 / 兑换 / 彩蛋共用
FULL_SCENE = "inventory_full"

#: 签到相关场景
CHECKIN_SCENE = "checkin_done"
CHECKIN_MILESTONE_SCENE = "checkin_milestone"
CHECKIN_ALREADY_SCENE = "checkin_already"
CHECKIN_CLOCK_BACK_SCENE = "checkin_clock_back"
CHECKIN_REMIND_SCENE = "checkin_remind"

#: 兑换 / 彩蛋场景
CONVERT_MINUTES_SCENE = "convert_minutes"
CONVERT_TYPING_SCENE = "convert_typing"
HOURLY_EGG_SCENE = "egg_hourly"
AFK_EGG_SCENE = "egg_afk"
FIRST_RUN_SCENE = "first_run"

#: 单次活动最多折算多少秒（阶段 F）。
#: `InputMonitor.any_activity` 只告诉我们"刚刚有输入"，两个事件之间隔了多久无从得知 ——
#: 用相邻两次的间隔近似，并**截断到 5 秒**：否则挂机 3 小时后的第一次鼠标移动
#: 会一口气折算出 180 分钟，直接换出 3 份食物（那正是"纯挂机不计入"要防的事）。
ACTIVITY_GAP_CAP_SEC = 5.0

#: 好感度到今日上限时额外跟的一句（01 文档 6.4 / 7.2 的 `feed_full`）。
#: 场景缺失时 `_speak()` 静默 —— 少一句话不算故障。
#:
#: **刻意不用 `error_anim_missing`**：那个场景在 01 文档 7.2 里标注「不出气泡，仅日志」，
#: 是给"素材全缺"做内部标记用的；素材缺失时本来就会正常说 `feed_done`（01 文档 6.4）。
CAPPED_SCENE = "feed_full"

DEFAULT_SEND_COOLDOWN_MS = 300

#: 打字速率的统计窗口（秒）。窗口内按键数 → 每分钟速率
TYPING_WINDOW_SEC = 30.0

#: **不受"专注/全屏保护"约束**的场景（`can_speak()` 里最后一道闸门的例外）。
#: 01 文档 7.2 与 7.3 在这里打了个架：`detect_typing` 的触发条件就是"打字速率超阈值"，
#: 而 7.3 第 2 条又说"高频打字 → 主动台词暂停"。两条都照做的话，
#: **这些台词永远不会出现**。裁定：**就事论事的观察类台词放行**
#: （说的正是"你在做什么"这件事本身，不是另找话题），
#: 其余主动台词（闲聊、报时）在专注模式下依然静默。
#:
#: 阶段 G 把五个 `detect_app_*` 一起放进来了，理由同上：
#: 切到会议软件的那一刻说「在开会呀」正是那句话的**唯一**时机场合。
#: 但**全屏是例外中的例外**：全屏时连观察类也不发（气泡会盖在人家的画面上，
#: 01 文档 7.3 第 3 条），所以那一条闸门写在比这里更早的位置。
FOCUS_EXEMPT_SCENES: frozenset[str] = frozenset({
    "detect_typing", "detect_typing_long",
    "detect_app_code", "detect_app_browser", "detect_app_game",
    "detect_app_meeting", "detect_app_media",
})

#: 前台分类 → 能开口的场景。`unknown` 不在表里 —— 不认识的应用，她没什么好说的。
APP_SCENE_KEYS: tuple[str, ...] = model.APP_KEYS


def _load_json(path: str) -> dict:
    """读一个配置 JSON。**任何异常都降级成空 dict** —— 用户手改坏文件不该让功能崩。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def nurture_dir() -> str:
    """`assets/nurture/` 目录。"""
    return os.path.join(store_mod.project_dir(), "assets", "nurture")


class NurtureController(QObject):
    """养成业务层。UI 只调它，它只碰 store / model / 角色 / 台词库。"""

    #: 该说一句台词了：`(文本, 语气)`。阶段 E 把它接到 `SpeechBubble`
    speech_requested = Signal(str, str)
    #: 库存或好感度变了 → 面板/菜单该刷新了
    state_changed = Signal()

    def __init__(self, store=None, cfg=None, assets_dir: str | None = None,
                 dialogues_dir: str | None = None, parent=None):
        super().__init__(parent)
        self._store = store if store is not None else store_mod.NurtureStore()
        # **`NurtureStore.__init__` 不读盘**，必须显式 load()（它同时负责跨天重置）。
        # 漏了这一步的后果很重：程序一启动就是一份空白存档，
        # 第一次 save 还会把用户真正的存档覆盖掉。
        try:
            self._store.load()
        except Exception:
            pass
        self._cfg = dict(cfg) if isinstance(cfg, dict) else {}
        self._assets_dir = str(assets_dir) if assets_dir else nurture_dir()
        self._character = None
        self._menu = None
        self._panel = None
        self._dialogue = DialogueLibrary(
            dialogues_dir if dialogues_dir is not None
            else os.path.join(self._assets_dir, "dialogues"),
            store=self._store,
        )
        self._items: list[dict] = []
        self._levels: list = []
        self._checkin_table: dict = {}
        self._events: list = []
        self._cooldown_until = 0.0
        # ── 台词调度状态（阶段 E）──
        self._cooldowns: dict[str, float] = {}      # 场景 → 下次可说的 monotonic 时间
        self._last_proactive_ts = 0.0               # 上一条主动台词的时间
        self._next_idle_ts = 0.0                    # 下一次允许闲聊的时间
        self._typing_rate = 0
        self._continuous_min = 0
        self._app_key = ""
        self._fullscreen = False                    # 前台全屏（阶段 G 的 window_monitor 接）
        self._window_monitor = None                 # 感知器引用（只用来启停，不用来读数据）
        self._key_stamps: deque[float] = deque(maxlen=600)
        self._last_activity_ts = time.monotonic()
        self._afk_spoken = False
        # ── 获取途径状态（阶段 F）──
        self._active_seconds = 0.0                  # 今日累计活动秒数（内存值，每分钟回写存档）
        self._keys_today = 0                        # 今日累计按键数（同上）
        self._pending_speech: tuple[str, dict] | None = None   # 被间隔挡下、下次心跳补说的台词
        self._rng = random.Random()
        self._scheduler = None
        self.reload_assets()

    # ────────────────── 装配 ──────────────────

    def reload_assets(self) -> None:
        """重新读 `items.json` / `levels.json` / `checkin.json` / `events.json` / 台词库。

        用户改完素材后调（阶段 H 的设置页会调）。任何一个文件坏掉都只影响它自己。
        """
        items = _load_json(os.path.join(self._assets_dir, "items.json")).get("items", [])
        self._items = [dict(i) for i in items
                       if isinstance(i, dict) and isinstance(i.get("name"), str)
                       and i.get("name", "").strip()]
        levels = _load_json(os.path.join(self._assets_dir, "levels.json")).get("levels", [])
        self._levels = list(levels) if isinstance(levels, list) else []
        self._checkin_table = _load_json(os.path.join(self._assets_dir, "checkin.json"))
        events = _load_json(os.path.join(self._assets_dir, "events.json")).get("events", [])
        self._events = [dict(e) for e in events if isinstance(e, dict)]
        try:
            self._dialogue.reload()
        except Exception:
            pass

    def set_config(self, cfg) -> None:
        """换一份 `config.json` 的 `nurture` 段（设置保存后调）。

        阶段 G 起顺带管**前台感知的开关**：隐私开关一关，感知**立刻停**，
        并且把"你刚才在用什么"一起忘掉（要停就停干净，不留一份内存里的旧状态）。
        """
        self._cfg = dict(cfg) if isinstance(cfg, dict) else {}
        monitor = self._window_monitor
        if monitor is None:
            return
        if self.foreground_detection_enabled():
            try:
                monitor.set_enabled(True)
            except Exception:
                pass
            return
        try:
            monitor.set_enabled(False)
        except Exception:
            pass
        self._app_key = ""
        self._fullscreen = False

    def attach_character(self, character) -> None:
        """绑定当前角色控制器。切角色时重新调一次即可。"""
        self._character = character

    def attach_menu(self, menu) -> None:
        self._menu = menu

    def attach_window_monitor(self, monitor) -> None:
        """接管一个 `window_monitor.WindowMonitor` 的生命周期（阶段 G）。

        连线（信号 → `on_app_changed` / `on_fullscreen_changed`）由 `create_monitor()` 做，
        这里只管**按开关启停**：这样设置页里关掉开关就能立即停下，不用重启。
        传 `None` 表示解绑（切角色/退出时）。
        """
        self._window_monitor = monitor
        if monitor is None:
            self._app_key = ""
            self._fullscreen = False
            return
        enabled = self.foreground_detection_enabled()
        try:
            monitor.set_enabled(enabled)
        except Exception:
            pass
        if not enabled:
            self._app_key = ""
            self._fullscreen = False

    # ────────────────── 查询 ──────────────────

    @property
    def store(self):
        return self._store

    @property
    def dialogue(self) -> DialogueLibrary:
        return self._dialogue

    def foreground_detection_enabled(self) -> bool:
        """隐私开关：`config.json` 的 `nurture.allow_foreground_detection`，**默认关闭**。"""
        return bool(self._cfg.get("allow_foreground_detection", False))

    def foreground_detection_active(self) -> bool:
        """感知是不是真的在跑：开关打开 **且** 监控对象存在（阶段 H 的设置页用它出提示）。"""
        monitor = self._window_monitor
        if monitor is None:
            return False
        try:
            return bool(monitor.is_enabled())
        except Exception:
            return False

    def current_app_key(self) -> str:
        """当前前台分类（`code`/`browser`/... /`unknown`；没开感知就是空串）。"""
        return str(self._app_key or "")

    def is_fullscreen(self) -> bool:
        return bool(self._fullscreen)

    def enabled(self) -> bool:
        """养成系统是否生效：开关打开 **且** 当前角色是 Q版（01 文档 0.2）。"""
        if not bool(self._cfg.get("enabled", True)):
            return False
        character = self._character
        if character is None:
            return True
        try:
            return character.character_type == "gif"
        except Exception:
            return False

    def items(self) -> list[dict]:
        return [dict(item) for item in self._items]

    def levels(self) -> list:
        """`levels.json` 的等级表（设置页与状态页都要用）。"""
        return list(self._levels)

    def item(self, name: str) -> dict | None:
        """按名字取物品（`items.json` 的条目）。"""
        target = str(name or "").strip()
        if not target:
            return None
        for entry in self._items:
            if str(entry.get("name", "")).strip() == target:
                return dict(entry)
        return None

    def animation_for(self, item: dict | None, kind: str) -> str | None:
        """四级兜底链选出实际要播的动作名（`config.json` 的覆盖优先于 `items.json`）。

        返回 `None` 表示素材全缺 —— 调用方**只出台词不播动画**，绝不崩。
        """
        effective = dict(item) if isinstance(item, dict) else {}
        name = str(effective.get("name", ""))
        override = self._cfg.get("food_anim_override")
        if isinstance(override, dict) and name in override:
            effective["anim"] = override[name]
        return model.resolve_anim(effective, kind, self._registry_has)

    def _registry_has(self, action: str) -> bool:
        character = self._character
        if character is None:
            return False
        try:
            return str(action) in set(character.get_available_animations())
        except Exception:
            return False

    # ────────────────── 菜单状态（01 文档 5.2 的"可用条件"表）──────────────────

    def menu_enabled_map(self) -> dict:
        """哪些按钮可用。**不可用项仍是可点的** —— 由 controller 出一句说明台词。"""
        has_food = any(self._stock_of(item) > 0 for item in self._items_of_kind("food"))
        gifts = self._items_of_kind("gift")
        has_gift = any(self._stock_of(item) > 0 for item in gifts)
        gift_room = self._store.gifts_sent_today < self._cap("gift_daily_cap", 3)
        unlocks = self._unlocks()
        return {
            "feed": has_food,
            "gift": has_gift and gift_room,
            "checkin": True,                 # 已签时靠角标提示，不置灰
            "heart": True,
            "chat": "small_talk" in unlocks,
            "headpat": "headpat" in unlocks,
            "settings": True,
        }

    def menu_badges(self) -> dict:
        """红点角标：签到未签时亮。"""
        try:
            can = model.can_checkin(self._store.last_checkin_date, date.today())
        except Exception:
            can = False
        return {"checkin": bool(can)}

    def refresh_menu(self) -> None:
        """把可用状态与角标推给菜单（`PetWindow` 在弹出前调）。"""
        menu = self._menu
        if menu is None:
            return
        try:
            enabled = self.menu_enabled_map()
            badges = self.menu_badges()
            menu.set_enabled_map(enabled)
            for key in menu.item_keys():
                menu.set_badge(key, bool(badges.get(key, False)))
        except Exception:
            pass

    def _unlocks(self) -> set:
        return model.unlocked_features(model.level_of(self._store.affection, self._levels),
                                       self._levels)

    # ────────────────── 面板 ──────────────────

    def panel(self):
        """懒创建养成面板（`QApplication` 必须先存在，所以不在 `__init__` 里建）。"""
        if self._panel is None:
            from src.nurture_panel import NurturePanel

            self._panel = NurturePanel(self._items)
            self._panel.item_chosen.connect(self.on_item_chosen)
            self._panel.close_clicked.connect(self.hide_panel)
            self._panel.set_levels(self._levels)
        return self._panel

    def panel_widget(self):
        """**不创建**面板，只在已创建时返回它。

        `PetWindow._popups()` 每次收弹层都会调一次 —— 如果那里顺手把面板造出来，
        每开一次功能面板就会凭空多一个 268×400 的隐藏窗口。
        """
        return self._panel

    def refresh_panel(self) -> None:
        """把存档里的最新数值推进面板。"""
        panel = self._panel
        if panel is None:
            return
        panel.set_items(self._items)
        panel.set_levels(self._levels)
        panel.set_inventory(self._store.inventory)
        panel.set_affection(self._store.affection, self._soft_cap())
        panel.set_streak(self._store.streak)
        panel.set_today(
            gained=self._store.affection_gained_today,
            cap=self._cap("affection_daily_cap", 20),
            gifts=self._store.gifts_sent_today,
            gift_cap=self._cap("gift_daily_cap", 3),
        )

    def show_panel(self, pet_geometry, tab: str = "food") -> None:
        """刷新数据 → 切到指定页 → 贴人物左侧弹出。"""
        self._maybe_reset_daily()
        panel = self.panel()
        self.refresh_panel()
        panel.set_tab(tab)
        panel.popup_near(pet_geometry)

    def hide_panel(self) -> None:
        if self._panel is not None and self._panel.isVisible():
            self._panel.hide_with_anim()

    def panel_visible(self) -> bool:
        return self._panel is not None and self._panel.isVisible()

    def apply_language(self, lang: str) -> None:
        if self._panel is not None:
            self._panel.apply_language(lang)

    # ────────────────── 业务：送出 ──────────────────

    def on_item_chosen(self, name: str) -> None:
        """面板卡片被点击 → 走完整送出流程。

        **送出去了才收面板**：库存 0 / 今日送礼已满 / 连点防护这些"没送出去"的情况
        面板留着，用户可以直接换一张卡片；一按就收反而像"点了没反应"。
        """
        result = self.try_send(name)
        if result in SUCCESS_RESULTS or result == RESULT_NO_ANIM:
            self.hide_panel()

    def try_send(self, name: str) -> str:
        """送出一件食物/礼物，返回结果码（见模块顶部的 `RESULT_*`）。

        这是本阶段唯一有副作用的入口，**所有分支都有测试**（含库存 0、每日上限、
        素材全缺、连点防护）。任何一步都不允许抛异常出去 —— 桌宠主线程崩了就是桌宠没了。
        """
        if not self.enabled():
            return RESULT_DISABLED

        item = self.item(name)
        if item is None:
            return RESULT_UNKNOWN

        if self._character_busy():
            return RESULT_LOCKED

        now = time.monotonic()
        if now < self._cooldown_until:
            return RESULT_COOLDOWN

        kind = str(item.get("kind", "food"))
        name = str(item.get("name", ""))

        if self._stock_of(item) <= 0:
            self._speak(FAIL_SCENE[RESULT_EMPTY], extra_ctx={"item": name})
            return RESULT_EMPTY

        if kind == "gift" and self._store.gifts_sent_today >= self._cap("gift_daily_cap", 3):
            self._speak(FAIL_SCENE[RESULT_GIFT_CAPPED], extra_ctx={"item": name})
            return RESULT_GIFT_CAPPED

        # 扣库存放在最前面：扣不掉就说明并发的另一次送出已经把它拿走了
        if not self._store.take_item(name, 1):
            self._speak(FAIL_SCENE[RESULT_EMPTY], extra_ctx={"item": name})
            return RESULT_EMPTY

        actual, capped = self._grant_affection(item)

        if kind == "gift":
            # 计数键必须是 store 的 `TODAY_KEYS` 里的名字（跨天由 reset_daily_if_needed 清零），
            # 写成 "gifts_sent" 会直接抛 KeyError —— 单测抓过一次
            self._store.bump_today("gifts_sent_today", 1)
        # 累计统计（只增不减，供阶段 H 的状态展示用；键在 STATS_KEYS 里）
        try:
            self._store.bump_stats("total_gifts" if kind == "gift" else "total_fed", 1)
        except Exception:
            pass

        anim = self.animation_for(item, kind)
        played = False
        if anim:
            try:
                played = bool(self._character.play_action(anim, lock=True))
            except Exception:
                played = False
        # 素材全缺（`anim` 为 None）或播放被拒 → 库存照样扣、台词照样说。
        # 送出的是"这份点心"，不是"那段动画"；把库存退回去反而会让用户困惑。

        self._speak_item(item, kind, capped=capped)
        self._cooldown_until = now + self._cooldown_ms() / 1000.0
        self.state_changed.emit()
        if not played:
            return RESULT_NO_ANIM
        return RESULT_CAPPED if capped else RESULT_OK

    def _grant_affection(self, item: dict) -> tuple[int, bool]:
        """按档位加好感度，受每日上限截断。返回 `(实际增量, 是否被今日上限截断)`。"""
        tier = str(item.get("tier", "common"))
        want = model.tier_affection_gain(tier, self._cfg.get("tier_affection"))
        cur = self._store.affection
        gained_today = self._store.affection_gained_today
        cap = self._cap("affection_daily_cap", 20)
        new_value, actual = model.apply_affection(cur, want, gained_today, cap)
        capped = actual < model.safe_int(want)
        if actual > 0:
            self._store.set_affection(new_value, gained_today=gained_today + actual)
        return actual, capped

    def _speak_item(self, item: dict, kind: str, *, capped: bool = False) -> None:
        """送出成功后的台词：先看物品专属台词，没有就从 `feed_done` 场景抽。"""
        lines = item.get("lines")
        text = ""
        if isinstance(lines, (list, tuple)):
            pool = [str(x) for x in lines if isinstance(x, str) and x.strip()]
            if pool:
                text = format_line(random.choice(pool), self._ctx({"item": str(item.get("name", ""))}))
        if text:
            self._emit_speech(text, "gentle")
        else:
            self._speak("feed_done", extra_ctx={"item": str(item.get("name", ""))})
        if capped:
            # 01 文档 6.4：到上限时动画与台词照旧，只额外跟一句
            self._speak(CAPPED_SCENE)

    # ────────────────── 获取途径（阶段 F）──────────────────
    #
    # 01 文档第 4 节的四条途径都在这一节：**签到 / 陪伴兑换 / 打字兑换 / 彩蛋**。
    # 三条共同约定：
    #   1. 产出统一走 `_grant_items()` —— 它是唯一改库存的地方，顺手统一了档位上限与
    #      「拿不下啦」提示，避免四个入口各写一遍发放逻辑
    #   2. **发放与播报解耦**：物品先到手，台词说不说得出来是另一回事（被间隔/专注挡下
    #      只是"这次没说出口"，不该把食物一起吞掉）
    #   3. 记时间的 flag **只在真的说出来了之后才写**（阶段 E 的教训）—— 否则被挡一次
    #      就等于这一天永远不说了。节日台词走 `_pending_speech` 下次心跳补说。

    def checkin_available(self) -> bool:
        """今天还能不能签到（菜单角标与提醒都问它）。"""
        try:
            return model.can_checkin(self._store.last_checkin_date, date.today())
        except Exception:
            return False

    def try_checkin(self) -> str:
        """每日签到。返回结果码（`RESULT_OK` / `ALREADY` / `CLOCK_BACK` / `DISABLED`）。

        01 文档 4.1 的规则全在 `nurture_model` 里（`checkin_status` / `next_streak` /
        `checkin_reward`），这一层只负责把它们连起来、发东西、说一句。

        **不因"她正忙"而拒绝**：喂食可以等锁，签到不该等 —— 奖励是用户的，动画只是表现。
        素材缺失时照样记签到、照样发东西、照样说话。
        """
        if not self.enabled() or not bool(self._cfg.get("checkin_enabled", True)):
            return RESULT_DISABLED

        today = date.today()
        last = self._store.last_checkin_date
        status = model.checkin_status(last, today)
        if status == model.STATUS_SAME_DAY:
            self._speak(CHECKIN_ALREADY_SCENE, {"streak": self._store.streak})
            return RESULT_ALREADY
        if status == model.STATUS_CLOCK_BACK:
            # 01 文档 4.4：不发放、不重置，只提示「时间好像不太对」
            self._speak(CHECKIN_CLOCK_BACK_SCENE)
            return RESULT_CLOCK_BACK

        streak, _reset = model.next_streak(last, today, self._store.streak)
        reward = model.checkin_reward(streak, self._checkin_table or None)
        items = model.resolve_tiers(reward.get("tiers") or {}, self._tier_pool("food"))

        # 先记账再发放：库存满也要算签到过。反过来的话明天还能再签一次（那才是真 bug）。
        # `set_checkin()` 自己会把 `stats.total_checkins` +1 —— 这里不要再加一次（单测抓到过）
        self._store.set_checkin(streak, today)

        granted, full = self._grant_items(items)
        if granted:
            self.try_play_action(self._cfg.get("checkin_anim", "庆祝"), lock=False)
        # **一次点击只出一个对话气泡**：库存满 > 里程碑 > 普通签到，取第一个有台词的。
        # 挨个说会把前面的顶掉（气泡是替换不是叠放），最后只剩一句无关紧要的。
        ctx = {"streak": streak, "count": sum(granted.values()),
               "name": "、".join(granted)}
        scenes = []
        if full:
            scenes.append(FULL_SCENE)
        if reward.get("milestone"):
            scenes.append(CHECKIN_MILESTONE_SCENE)
        scenes.append(CHECKIN_SCENE)
        said = None
        for scene in scenes:
            said = self._speak(scene, ctx)
            if said:
                break
        self._grant_affection_value(model.safe_int(reward.get("affection")),
                                    ctx={"streak": streak})
        if said is None:
            # 台词库缺文件/空池 → 仍然要给用户一点反馈（点了没反应是最糟的）
            self._emit_speech(f"连签 {streak} 天。", "proud")
        self.state_changed.emit()
        return RESULT_OK

    def on_menu_shown(self) -> str | None:
        """悬停菜单刚弹出来。01 文档 4.1 的第 2 条提醒入口：今天没签就提一句。

        每天最多一次（`checkin_reminded_date`），而且**说出去了才记**。
        """
        if not self.checkin_available():
            return None
        today = date.today().isoformat()
        if str(self._store.flag("checkin_reminded_date", "")) == today:
            return None
        said = self._speak(CHECKIN_REMIND_SCENE)
        if said:
            try:
                self._store.set_flag("checkin_reminded_date", today)
            except Exception:
                pass
        return said

    # ── 进度：陪伴时长与打字量 ──

    def active_minutes(self) -> int:
        """今日累计活动分钟数（陪伴兑换的进度）。"""
        return int(self._active_seconds // 60)

    def keys_today(self) -> int:
        """今日累计按键数（打字兑换的进度）。"""
        return max(0, int(self._keys_today))

    def accrue_activity(self, seconds: float) -> None:
        """记一段活动时长。**只在键鼠有动作时调用**（`notify_activity` 的入口）。

        相邻两次输入的时间差近似"这一段在电脑前"的时长，单次截断到
        `ACTIVITY_GAP_CAP_SEC` 秒 —— 挂机很久之后的第一次输入只算 5 秒。
        """
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            return
        if seconds <= 0:
            return
        self._active_seconds += min(seconds, ACTIVITY_GAP_CAP_SEC)

    def _sync_daily_progress(self) -> None:
        """把内存里的今日进度回写存档（每分钟一次，**值没变就不写**）。

        为什么不在每次按键/鼠标事件里写：`any_activity` 在鼠标移动时每秒能来上百次，
        每次都走 `store.save()`（发 `changed` 信号 + 重启防抖计时器）纯属浪费。
        代价：进程被强杀时最多丢一分钟的进度，可接受。
        """
        try:
            minutes = self.active_minutes()
            keys = self.keys_today()
            if self._store.daily("active_minutes") != minutes:
                self._store.set_daily("active_minutes", minutes)
            if self._store.daily("key_count") != keys:
                self._store.set_daily("key_count", keys)
        except Exception:
            pass

    def _load_daily_progress(self) -> None:
        """从存档恢复今日进度（启动时、以及跨天清零后调）。"""
        try:
            self._active_seconds = max(0, self._store.daily("active_minutes")) * 60.0
            self._keys_today = max(0, self._store.daily("key_count"))
        except Exception:
            self._active_seconds = 0.0
            self._keys_today = 0

    # ── 兑换 ──

    def _check_conversions(self) -> str | None:
        """陪伴时长与打字量的兑换结算。返回说出来的那句话（没有就 `None`）。

        两个兑换都靠 `model.convert_to_items()`：它拿"今日累计进度 + 今日已兑换个数 + 上限"
        算出该发几个。**已兑换个数存在存档里**，所以每次心跳重算也不会重复发放，
        不需要"发完把进度清零"那种容易写漏的做法。
        """
        said = None
        # (场景, 今日进度, 每个产出的进度阈值(键, 默认值), 每日上限(键, 默认值), 已兑换计数键)
        jobs = (
            (CONVERT_MINUTES_SCENE, self.active_minutes(),
             ("companion_minutes_per_item", 60), ("companion_daily_cap", 3),
             "minutes_rewarded"),
            (CONVERT_TYPING_SCENE, self.keys_today(),
             ("typing_keys_per_item", 2000), ("typing_daily_cap", 2),
             "keys_rewarded"),
        )
        for scene, progress, (per_key, per_default), (cap_key, cap_default), done_key in jobs:
            per = self._cap(per_key, per_default)
            cap = self._cap(cap_key, cap_default)
            try:
                already = max(0, self._store.daily(done_key))
            except Exception:
                already = 0
            granted_n, _left = model.convert_to_items(progress, per, cap, already)
            if granted_n <= 0:
                continue
            try:
                self._store.bump_daily(done_key, granted_n)
            except Exception:
                pass
            items = model.resolve_tiers({"common": granted_n}, self._tier_pool("food"))
            text = self._grant_bonus(scene, items, ctx={"count": granted_n})
            if text:
                said = said or text
        return said

    # ── 彩蛋 ──

    def _check_hourly_egg(self, now: datetime) -> str | None:
        """整点彩蛋（01 文档 4.3）：**每个小时只掷一次骰子**。

        文档写的是":00 时 25%"，但心跳是 60 秒一次、起跳时刻由进程启动时间决定，
        卡"分钟数 < 5"会大概率整天掷不到。所以改成"观察到新的一个小时就掷一次"
        —— 玩家感受到的仍然是"每小时可能掉一次"。`hourly_bonus_daily_cap`
        是文档没写的补充上限（否则挂机一整天能白拿十几次）。
        """
        today = now.date().isoformat()
        if not bool(self._cfg.get("hourly_bonus_enabled", True)):
            return None
        try:
            last_hour = model.safe_int(self._store.flag("last_hourly_hour", -1))
            same_day = str(self._store.flag("last_hourly_date", "")) == today
        except Exception:
            return None
        if same_day and last_hour == now.hour:
            return None                      # 这个小时已经掷过了

        # 先记时间戳再掷骰子：掷不中也不该在同一小时里反复掷
        try:
            self._store.set_flag("last_hourly_hour", int(now.hour))
            self._store.set_flag("last_hourly_date", today)
        except Exception:
            pass

        try:
            chance = float(self._cfg.get("hourly_bonus_chance", 0.25))
        except (TypeError, ValueError):
            chance = 0.25
        if chance <= 0 or self._rng.random() >= min(1.0, chance):
            return None
        cap = self._cap("hourly_bonus_daily_cap", 3)
        try:
            if self._store.daily("hourly_bonus_count") >= cap:
                return None
        except Exception:
            return None

        self._store.bump_daily("hourly_bonus_count", 1)
        items = model.resolve_tiers({"common": 1}, self._tier_pool("food"))
        return self._grant_bonus(HOURLY_EGG_SCENE, items)

    def _check_afk_egg(self, minutes: float) -> str | None:
        """长待机彩蛋（01 文档 4.3）：连续 AFK 超过阈值 → 稀有食物 ×1，**每天一次**。

        库存满时**照样把今天标记成已发**（"彩蛋类不补发"，01 文档 4.4）。
        """
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return None
        if minutes < self._afk_minutes():
            return None
        today = date.today().isoformat()
        try:
            if str(self._store.flag("afk_bonus_date", "")) == today:
                return None
            self._store.set_flag("afk_bonus_date", today)
        except Exception:
            return None
        tier = str(self._cfg.get("afk_bonus_tier", model.TIER_RARE) or model.TIER_RARE)
        items = model.resolve_tiers({tier: 1}, self._tier_pool("food"))
        return self._grant_bonus(AFK_EGG_SCENE, items)

    def _check_first_run_egg(self) -> str | None:
        """首次使用彩蛋（01 文档 4.3）：第一次跑养成系统当天送 1 个珍贵食物（引导用）。"""
        try:
            if bool(self._store.flag("first_run_bonus_granted", False)):
                return None
            self._store.set_flag("first_run_bonus_granted", True)
        except Exception:
            return None
        tier = str(self._cfg.get("first_run_bonus_tier", model.TIER_PRECIOUS)
                   or model.TIER_PRECIOUS)
        items = model.resolve_tiers({tier: 1}, self._tier_pool("food"))
        return self._grant_bonus(FIRST_RUN_SCENE, items)

    def _check_event_egg(self, today: date | None = None) -> str | None:
        """节日 / 纪念日（01 文档 4.3 + `events.json`）：每天最多一次。

        节日台词属**主动台词**（在 `dialogue.PROACTIVE_SCENES` 里），所以它可能被
        90 秒间隔或专注保护挡下 —— 那种情况下把场景挂到 `_pending_speech` 上，
        下一次心跳接着试。**物品先到手**，不等台词。
        """
        today = today or date.today()
        stamp = today.isoformat()
        try:
            if str(self._store.flag("last_event_date", "")) == stamp:
                return None
        except Exception:
            return None
        event = model.event_for_date(self._events, today, self._cfg.get("birthday", ""))
        if not event:
            return None
        try:
            self._store.set_flag("last_event_date", stamp)
        except Exception:
            pass

        items = model.event_items(event)
        scene = str(event.get("scene", "") or "")
        anim = str(self._cfg.get("checkin_anim", "庆祝"))
        granted, full = self._grant_items(items)
        self._grant_affection_value(model.safe_int(event.get("affection")))
        if granted:
            self.try_play_action(anim, lock=False)
        ctx = {"name": "、".join(granted), "count": sum(granted.values())}
        said = None
        if scene:
            if self.can_speak(scene):
                said = self.say(scene, ctx)
            if not said:
                self._pending_speech = (scene, ctx)   # 下次心跳补说
        if full:
            self._speak(FULL_SCENE)
        self.state_changed.emit()
        return said

    def flush_pending_speech(self) -> str | None:
        """补说被挡下的台词（节日用）。说出来或场景消失即清空。"""
        pending = self._pending_speech
        if not pending:
            return None
        scene, ctx = pending
        if not self._dialogue.has_scene(scene):
            self._pending_speech = None
            return None
        said = self.say(scene, ctx)
        if said:
            self._pending_speech = None
        return said

    # ── 发放 ──

    def _tier_pool(self, kind: str | None = None) -> dict:
        return model.tier_pool(self._items, kind)

    def _tier_cap(self, tier: str) -> int:
        """该档位的单类库存上限（`config.json` 的 `tier_caps` 优先，缺了用默认表）。"""
        caps = self._cfg.get("tier_caps")
        if isinstance(caps, dict) and tier in caps:
            return max(0, model.safe_int(caps.get(tier)))
        return model.tier_cap(tier, None)

    def _grant_items(self, items) -> tuple[dict, bool]:
        """按档位上限发放一批产出。返回 `(实际发放的 {物品名: 数量}, 是否有东西没放下)`。

        `items.json` 里没有的名字**直接跳过**（用户在 `events.json` 里写错名字不该崩，
        也不该按"库存满"报错）。
        """
        granted: dict[str, int] = {}
        full = False
        if not isinstance(items, dict):
            return granted, full
        for name, count in items.items():
            want = model.safe_int(count)
            if want <= 0:
                continue
            entry = self.item(name)
            if entry is None:
                continue
            added = self._store.add_item(str(name), want, cap=self._tier_cap(
                str(entry.get("tier", model.TIER_COMMON))))
            if added > 0:
                granted[str(name)] = added
            if added < want:
                full = True
        return granted, full

    def _grant_bonus(self, scene: str, items, *, anim_key: str = "convert_anim",
                     ctx: dict | None = None) -> str | None:
        """发放 + 播个动作 + 说一句（库存满再补一句）。返回说出来的那句话。

        产出为空（档位池里没有候选 / 名字不存在）时**什么也不说** —— 没东西到手却道谢
        比沉默更奇怪。发放本身已经由 `_grant_items()` 记过账了。
        """
        granted, full = self._grant_items(items)
        if not granted and not full:
            return None
        extra = dict(ctx or {})
        extra["count"] = sum(granted.values()) or model.safe_int(extra.get("count"))
        extra["name"] = "、".join(granted)
        if granted:
            self.try_play_action(self._cfg.get(anim_key, "点头"), lock=False)
        # 库存满也照说 —— 该报的还是要报，只说「为什么没到手」反而让人以为丢了东西
        said = self._speak(scene, extra)
        if full:
            self._speak(FULL_SCENE)
        self.state_changed.emit()
        return said

    def _grant_affection_value(self, want: int, ctx: dict | None = None) -> int:
        """给一笔固定的好感度（签到 / 节日用），同样受每日上限截断。返回实际增量。"""
        want = model.safe_int(want)
        if want <= 0:
            return 0
        cur = self._store.affection
        gained_today = self._store.affection_gained_today
        new_value, actual = model.apply_affection(cur, want, gained_today,
                                                 self._cap("affection_daily_cap", 20))
        if actual > 0:
            self._store.set_affection(new_value, gained_today=gained_today + actual)
            self.state_changed.emit()
        return actual

    # ────────────────── 台词 ──────────────────

    def _speak(self, scene: str, extra_ctx: dict | None = None) -> str | None:
        """按场景抽一句台词并请求显示。返回说了什么；没说出来 → `None`。

        场景不存在/池子为空 → **静默**（不是报错）。返回值是给阶段 F 的调用方用的
        （"说出来了吗"决定要不要写日期 flag），老调用方忽略它即可。
        """
        line = self.pick_line(scene, extra_ctx)
        if line is None:
            return None
        self._emit_speech(line["text"], line.get("tone", "gentle"))
        return str(line.get("text") or "") or None

    def _ctx(self, extra: dict | None = None) -> dict:
        """台词占位符的上下文。占位符缺键时会原样保留（`dialogue.format_line` 的约定）。"""
        ctx = {
            "name": str(self._cfg.get("user_name", "") or ""),
            "affection": self._store.affection,
            "streak": self._store.streak,
        }
        if extra:
            ctx.update(extra)
        return ctx

    def pick_line(self, scene: str, extra_ctx: dict | None = None) -> dict | None:
        """抽一句台词（`{"text", "tone"}`）。供测试与阶段 E 的调度复用。"""
        try:
            return self._dialogue.pick_line(
                scene, self._ctx(extra_ctx),
                affection=self._store.affection,
                tease_allowed=self._tease_allowed(),
            )
        except Exception:
            return None

    def _emit_speech(self, text: str, tone: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        try:
            self.speech_requested.emit(text, str(tone or "gentle"))
        except Exception:
            pass

    def _tease_allowed(self) -> bool:
        """现在允不允许走「捉弄」语气（01 文档 7.1 的七条硬禁区）。

        `is_tease_allowed()` 是**按句判定**的 —— 拿 `tone="tease"` 去问
        "这样的语气现在能说吗"，答案用作 `pick_line(tease_allowed=...)`，
        为 `False` 时台词库里 `tease` 那一组被整体剔除。

        阶段 G 起打字速率与连续工作时长都是**真数据**了（前面一直传 0 等于"未察觉专注状态"）：
        高频打字时不仅主动台词停发，连"捉弄"都不许 —— 那是最容易踩雷的时刻。
        """
        try:
            return model.is_tease_allowed(
                "tease",
                hour=datetime.now().hour,
                typing_rate=self._typing_rate,
                continuous_min=self._continuous_min,
                tease_today=self._store.tease_count_today,
                tease_cap=model.safe_int(self._cfg.get("tease_daily_cap", 6)),
                mute_today=self._store.mute_tease_today(),
                tease_probability=model.tease_probability_of(
                    str(self._cfg.get("tease_frequency", "sometimes"))),
                typing_rate_threshold=model.safe_int(self._cfg.get(
                    "typing_rate_threshold", model.DEFAULT_TYPING_RATE_THRESHOLD)),
                continuous_min_threshold=model.safe_int(self._cfg.get(
                    "continuous_min_threshold", model.DEFAULT_CONTINUOUS_MIN_THRESHOLD)),
                night_start=model.safe_int(self._cfg.get("mute_hours_start", 23)),
                night_end=model.safe_int(self._cfg.get("mute_hours_end", 7)),
            )
        except Exception:
            return False

    # ────────────────── 台词调度（阶段 E）──────────────────
    #
    # 这一节是 01 文档 7.3「防打扰规则」的落地处。所有**主动**台词都必须走
    # `say()`，它统一过四道闸：场景冷却 → 全屏静默 → 全局最小间隔（90s）→ 专注/免打扰保护。
    # 用户直接触发的台词（喂食、签到、陪聊、摸头）走 `_speak()`，**不受这些闸门约束**
    # —— 那只会让用户觉得"点了没反应"（`dialogue.GAP_EXEMPT_SCENES` 就是这么定的）。

    def can_speak(self, scene: str, tone: str = "") -> bool:
        """现在能不能说这个场景的话。**只判断，不产生副作用**（便于单测）。"""
        if not bool(self._cfg.get("proactive_enabled", True)) and is_proactive(scene):
            return False
        if not self._dialogue.has_scene(scene):
            return False
        now = time.monotonic()
        if now < self._cooldowns.get(scene, 0.0):
            return False
        if is_proactive(scene) and not is_gap_exempt(scene):
            # 全屏是第一道硬闸门：**连观察类台词也不发**。
            # 气泡会浮在人家的全屏画面（游戏/演示/视频）上，那是 01 文档 7.3 第 3 条
            # 明确要避免的"遮挡"，所以这条比 `FOCUS_EXEMPT_SCENES` 的例外更优先。
            if self._fullscreen:
                return False
            if now - self._last_proactive_ts < self._min_gap_sec():
                return False
            if scene not in FOCUS_EXEMPT_SCENES and not self._proactive_allowed():
                return False
        if str(tone) == "tease" and not self._tease_allowed():
            return False
        return True

    def say(self, scene: str, ctx: dict | None = None, *, tone: str = "") -> str | None:
        """说一句台词。返回说了什么；因为冷却/间隔/专注/没句子而没说 → `None`。

        冷却与时间戳只在**真的说出来了**之后才记 —— 先记会让"抽不到句子"的场景
        把下一次机会也一起吃掉。
        """
        if not self.can_speak(scene, tone):
            return None
        line = self.pick_line(scene, ctx)
        if line is None:
            return None

        now = time.monotonic()
        cooldown, scene_gap = self._scene_timing(scene)
        self._cooldowns[scene] = now + max(cooldown, scene_gap)
        if is_proactive(scene) and not is_gap_exempt(scene):
            self._last_proactive_ts = now
        if str(line.get("tone")) == "tease":
            self._count_tease()
        self._emit_speech(line["text"], line.get("tone", "gentle"))
        return line["text"]

    def _scene_timing(self, scene: str) -> tuple[float, float]:
        """场景自带的 (冷却秒, 最小间隔秒)。台词文件里可配，缺省 0。"""
        try:
            cooldown, gap = self._dialogue.cooldowns().get(scene, (0, 0))
            return float(cooldown or 0), float(gap or 0)
        except Exception:
            return 0.0, 0.0

    def _min_gap_sec(self) -> float:
        return max(0.0, float(model.safe_int(self._cfg.get("proactive_min_gap_sec", 90))))

    def _count_tease(self) -> None:
        """记一次「捉弄」—— 用于每日额度与 01 文档 7.1 的硬禁区判定。"""
        try:
            self._store.bump_today("tease_count_today", 1)
        except Exception:
            pass

    def set_activity(self, *, typing_rate: int | None = None,
                     continuous_min: int | None = None, app: str | None = None) -> None:
        """更新"用户现在在干什么"（专注/免打扰判定用）。

        三个数据源都已经接上：打字速率来自 `PetWindow` 喂进来的按键事件、
        `continuous_min` 来自心跳（阶段 F 的活动时长）、`app` 来自阶段 G 的 `window_monitor`。

        `app` 只接受**归一化分类**，不接受任何原始进程名 —— 见 01 文档 8.2 的隐私红线。
        """
        if typing_rate is not None:
            self._typing_rate = max(0, model.safe_int(typing_rate))
        if continuous_min is not None:
            self._continuous_min = max(0, model.safe_int(continuous_min))
        if app is not None:
            self._app_key = str(app)

    def _focus_mode(self) -> bool:
        """用户在专心做事 → 主动台词停发、`tease` 全面禁用（01 文档 7.3 第 2、3 条）。

        判定依据：打字速率超阈值 / 连续工作超时 / 前台是会议软件 / 前台全屏（阶段 G）。
        **"读不到"一律按"没在专注"处理**：宁可多陪一句，也不要因为她以为你在忙而彻底沉默。
        """
        try:
            return model.is_focus_mode(
                self._typing_rate, self._continuous_min, self._app_key,
                typing_rate_threshold=model.safe_int(self._cfg.get(
                    "typing_rate_threshold", model.DEFAULT_TYPING_RATE_THRESHOLD)),
                continuous_min_threshold=model.safe_int(self._cfg.get(
                    "continuous_min_threshold", model.DEFAULT_CONTINUOUS_MIN_THRESHOLD)),
                fullscreen=self._fullscreen,
            )
        except Exception:
            return False

    def _proactive_allowed(self) -> bool:
        """现在允许主动开口吗（01 文档 7.3 第 2、3 条 + 5.2 的「只陪伴，不评价」）。

        - **专注**（高频打字 / 连续工作 / 会议软件）→ 不许
        - **游戏** → 不许：她说不出"你在玩什么"，那就不该在这种时候找话
        - **全屏** → 不许，且这条更硬：`can_speak()` 在更早的位置就拦住了，
          连 `FOCUS_EXEMPT_SCENES` 里的观察类台词也不放行

        `FOCUS_EXEMPT_SCENES` 里的台词**不走这个方法**。
        """
        if not model.is_proactive_allowed(self._app_key):
            return False
        return not self._focus_mode()

    def typing_rate(self) -> int:
        return self._typing_rate

    def report_key_press(self) -> int:
        """收到一次全局按键 → 返回最近 30 秒的打字速率。

        由 `PetWindow` 喂（`InputMonitor.key_pressed`）。**拉模型的计数放在这里**
        而不是 `input_monitor`：这里是唯一要用的地方，放进来就不用动那个既有文件。
        阶段 G 若要把速率给别的功能用，再搬进 monitor 也不迟。

        阶段 F 起同时累计**今日按键总数**（打字兑换的进度）：只加内存里的整数，
        存档由每分钟的心跳回写（按键是每秒几十次的高频事件，不能每次都碰存档）。
        """
        now = time.monotonic()
        self._key_stamps.append(now)
        while self._key_stamps and now - self._key_stamps[0] > TYPING_WINDOW_SEC:
            self._key_stamps.popleft()
        self._keys_today += 1
        self._last_activity_ts = now
        rate = len(self._key_stamps) * (60.0 / TYPING_WINDOW_SEC)
        self.set_activity(typing_rate=int(rate))
        return int(rate)

    # ────────────────── 触发入口 ──────────────────

    def on_idle_tick(self) -> str | None:
        """每分钟一次的心跳（`start_scheduler()` 里的 `QTimer`）。

        顺序即优先级，**一次心跳最多说一句**（多句会互相顶掉，只有最后一句可见）：

        1. 跨天重置 + 今日进度回写存档
        2. 补说上次被间隔挡下的台词（节日）
        3. 节日彩蛋（每天一次）
        4. 首次使用彩蛋（一辈子一次）
        5. 陪伴 / 打字兑换结算
        6. 整点彩蛋（每小时掷一次）
        7. 时段问候（每个时段每天一次）→ 长时间无输入（含长待机彩蛋）→ 空闲闲聊

        前三步里只有 7 走 `say()` 的间隔闸门，2~6 是"有东西到手"的通知，
        走 `_speak()`（不受 90 秒间隔约束）—— 让用户以为自己白干了是最糟的体验。
        """
        now = self._now()
        today = now.date()

        if self._maybe_reset_daily(today):
            self._load_daily_progress()
        self._sync_daily_progress()

        said = self.flush_pending_speech()
        if said:
            return said
        for probe in (lambda: self._check_event_egg(today),
                      self._check_first_run_egg,
                      self._check_conversions,
                      lambda: self._check_hourly_egg(now)):
            said = probe()
            if said:
                return said

        scene = model.time_scene_of(now.hour)
        if scene and self._store.flag(f"{scene}_date", "") != today.isoformat():
            said = self.say(scene)
            if said:
                self._store.set_flag(f"{scene}_date", today.isoformat())
                return said

        # 长时间没有输入（超过阈值）→ 说一句"我在这儿"，每次空闲只说一次
        idle_minutes = (time.monotonic() - self._last_activity_ts) / 60.0
        if idle_minutes >= self._afk_minutes() and not self._afk_spoken:
            self._afk_spoken = True
            said = self._check_afk_egg(idle_minutes)
            if said:
                return said
            return self.say("idle_long_absent")

        if time.monotonic() >= self._next_idle_ts:
            self._schedule_next_idle()
            return self.say("idle_random")
        return None

    def _now(self) -> datetime:
        """当前时间。抽成方法是为了让测试能把"现在几点"钉死 ——
        否则时段问候那几条测试的成败取决于跑测试的时间。"""
        return datetime.now()

    def on_key_press(self) -> str | None:
        """收到一次全局按键：先计数，再按速率决定要不要说一句。"""
        return self.on_key_activity(self.report_key_press())

    def notify_activity(self) -> None:
        """用户有任何输入 → 结束"长时间无输入"状态，并重置空闲阈值。

        阶段 F 起顺带累计"在电脑前"的时长（陪伴兑换的进度）。这个方法会被**鼠标移动**
        触发（每秒可达上百次），所以这里只做浮点加法，不碰存档、不发信号。
        """
        now = time.monotonic()
        self.accrue_activity(now - self._last_activity_ts)
        self._last_activity_ts = now
        self._afk_spoken = False

    def on_key_activity(self, rate: int) -> str | None:
        """打字速率变化（阈值以上才说话，冷却由台词文件控制）。"""
        self.set_activity(typing_rate=rate)
        if rate >= model.safe_int(self._cfg.get("typing_rate_threshold", 120)):
            return self.say("detect_typing")
        return None

    def on_audio(self, playing: bool = False, muted: bool = False) -> str | None:
        """音频开始播放 / 系统静音。"""
        if muted:
            return self.say("detect_muted")
        if playing:
            return self.say("detect_audio")
        return None

    def on_app_changed(self, app_key: str) -> str | None:
        """前台应用分类变化（阶段 G 的 `window_monitor` 接）。

        `app_key` 是**归一化分类**（`code`/`browser`/`game`/`meeting`/`media`/`unknown`）——
        拿不到窗口标题，也拿不到进程名（01 文档 8.2 的隐私红线）。
        所以这里能说的只有"你在用哪一类软件"，说不出别的；`unknown` 干脆不说。

        游戏与会议下这句**照样能说出口**：它是"就事论事的观察"，
        而且"切到会议软件的那一刻"正是那句话唯一的时机场合
        （见 `FOCUS_EXEMPT_SCENES`）；真正被拦住的是"另找话题"
        （闲聊、报时、别的感知），以及**全屏**下的一切台词。
        """
        self.set_activity(app=app_key)
        key = str(app_key or "").strip().lower()
        if key in APP_SCENE_KEYS:
            return self.say(f"detect_app_{key}")
        return None

    def on_fullscreen_changed(self, fullscreen: bool) -> None:
        """前台进入 / 退出全屏（阶段 G 的 `window_monitor` 接）。

        全屏期间**所有主动台词停发**（01 文档 7.3 第 3 条）：
        气泡会浮在人家的游戏/演示/视频画面上。这不是"这句话合不合适"的问题，
        而是"根本不该在这时候出现"的问题 —— 所以她只是安静，不解释。
        """
        self._fullscreen = bool(fullscreen)

    def on_hover_long(self) -> str | None:
        """鼠标在她身上停留超过 5 秒（且悬停菜单没弹出来）。"""
        return self.say("hover_long")

    def on_afk(self, minutes: int = 0) -> str | None:
        """外部（角色侧）报来一段长时间无输入。先看长待机彩蛋，再是那句「我在这儿」。"""
        self._afk_spoken = False
        self.set_activity(continuous_min=0)
        if model.safe_int(minutes) <= 0:
            return None
        return self._check_afk_egg(minutes) or self.say("idle_long_absent")

    def request_small_talk(self) -> str | None:
        """「陪她聊聊」按钮：用户主动触发，不受最小间隔约束。"""
        return self.say("small_talk")

    def request_headpat(self) -> str | None:
        """「摸头」按钮：播 `害羞 2` + 专属台词（动画可被打断，所以 `lock=False`）。"""
        self.try_play_action(self._cfg.get("headpat_anim", "害羞 2"), lock=False)
        return self.say("headpat")

    def try_play_action(self, action, lock: bool = False) -> bool:
        """让角色播个动作（摸头这类不锁交互的用）。失败一律静默。"""
        if not self.enabled() or not action:
            return False
        if self._character_busy():
            return False
        if not self._registry_has(str(action)):
            return False
        try:
            return bool(self._character.play_action(str(action), lock=lock))
        except Exception:
            return False

    # ────────────────── 心跳 ──────────────────

    def start_scheduler(self, tick_ms: int = 60000) -> None:
        """启动每分钟心跳（获取途径结算 / 待机闲聊 / 时段问候 / 长时间无输入）。"""
        self._load_daily_progress()
        if self._scheduler is None:
            from PySide6.QtCore import QTimer

            self._scheduler = QTimer(self)
            self._scheduler.setInterval(max(1000, model.safe_int(tick_ms)))
            self._scheduler.timeout.connect(self._on_scheduler_tick)
        self._schedule_next_idle()
        self._scheduler.start()

    def stop_scheduler(self) -> None:
        if self._scheduler is not None:
            self._scheduler.stop()

    def scheduler_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.isActive()

    def _on_scheduler_tick(self) -> None:
        try:
            self.on_idle_tick()
        except Exception:
            pass

    def _schedule_next_idle(self) -> None:
        lo = max(1, model.safe_int(self._cfg.get("idle_talk_min_minutes", 8)))
        hi = max(lo, model.safe_int(self._cfg.get("idle_talk_max_minutes", 20)))
        self._next_idle_ts = time.monotonic() + random.uniform(lo, hi) * 60.0

    def _afk_minutes(self) -> float:
        return max(1.0, float(model.safe_int(self._cfg.get("afk_bonus_minutes", 10))))

    # ────────────────── 内部小工具 ──────────────────

    def _items_of_kind(self, kind: str) -> list[dict]:
        return [item for item in self._items if str(item.get("kind", "food")) == kind]

    def _stock_of(self, item: dict) -> int:
        return self._store.item_count(str(item.get("name", "")))

    def _cap(self, key: str, default: int) -> int:
        """读一个"每日上限"配置。**脏值回落默认值，不是回落 0**。

        回落 0 会让 `affection_daily_cap: "很多"` 这种手滑直接关闭整个功能，
        而用户的意图显然是"用默认值"。显式写 0 仍然有效（那是有意关掉）。
        """
        raw = self._cfg.get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return max(0, model.safe_int(default))
        return max(0, value)

    def _soft_cap(self) -> int:
        return max(1, model.safe_int(self._cfg.get("soft_affection_cap",
                                                   model.SOFT_AFFECTION_CAP)))

    def _cooldown_ms(self) -> int:
        return max(0, model.safe_int(self._cfg.get("send_cooldown_ms",
                                                   DEFAULT_SEND_COOLDOWN_MS)))

    def _character_busy(self) -> bool:
        character = self._character
        if character is None:
            return False
        probe = getattr(character, "is_busy", None)
        if probe is None:
            return False
        try:
            return bool(probe())
        except Exception:
            return False

    def _maybe_reset_daily(self, today: date | None = None) -> bool:
        """跨天重置（打开面板、每次心跳时顺手检查一次）。返回是否真的重置了。"""
        try:
            return bool(self._store.reset_daily_if_needed(today))
        except Exception:
            return False

    # ────────────────── 菜单接线 ──────────────────

    #: 菜单按钮 → 面板页签
    TAB_OF_ACTION = {"feed": "food", "gift": "gift", "heart": "status"}

    def on_menu_action(self, action: str, pet_geometry) -> bool:
        """处理悬停菜单的一下点击。**返回 `False` 表示本阶段还没接**（由 `PetWindow` 记日志）。

        `pet_geometry` 是人物窗口的全局几何（面板要靠它落位）。
        """
        action = str(action or "")
        if action == "settings":
            return False                 # 设置窗口由 PetWindow 自己开，不经这一层
        if action in self.TAB_OF_ACTION:
            self.show_panel(pet_geometry, self.TAB_OF_ACTION[action])
            return True
        if action == "chat":
            self.request_small_talk()          # 用户主动触发 → 不受 90 秒间隔约束
            return True
        if action == "headpat":
            self.request_headpat()
            return True
        if action == "checkin":
            self.try_checkin()                 # 结果码由台词体现（已签/时间不对都会说话）
            self.refresh_menu()                # 签完把红点角标撤掉
            return True
        return False
