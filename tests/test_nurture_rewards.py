"""`NurtureController` 的**获取途径**（阶段 F）单测：签到 / 陪伴兑换 / 打字兑换 / 彩蛋。

与 `test_nurture_controller.py` 的分工：那个文件覆盖"送出去"（`try_send` 的九个结果码），
这个文件覆盖"东西怎么来"。两者共用同一套思路 —— **临时素材 + 临时存档**，
不依赖真 `assets/nurture/`（那是用户可编辑的，数字会漂）。

这一模块最需要盯住的三件事（都是"看起来能用、其实会静默坏掉"的类型）：

1. **跨天与时间回退**：连签会不会算错、把系统时间往回调会不会白拿一份
2. **重复发放**：同一分钟的心跳跑 100 次，兑换/彩蛋只能发一次（`already` 计数 + flag）
3. **库存满**：产出拿不下时，签到记录**仍然要记**（否则明天还能再签一次）

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src import nurture_controller as nc  # noqa: E402
from src import nurture_model as nm  # noqa: E402
from src import nurture_store as store_mod  # noqa: E402
from src.character_base import CharacterController  # noqa: E402

_APP = None

ITEMS = {
    "items": [
        {"name": "奶油面包", "kind": "food", "tier": "common", "anim": "笑",
         "icon_key": "bread", "lines": []},
        {"name": "饭团", "kind": "food", "tier": "common", "anim": "笑",
         "icon_key": "onigiri", "lines": []},
        {"name": "草莓蛋糕", "kind": "food", "tier": "rare", "anim": "蛋糕",
         "icon_key": "shortcake", "lines": []},
        {"name": "生日蛋糕", "kind": "food", "tier": "precious", "anim": "蛋糕",
         "icon_key": "birthday", "lines": []},
        {"name": "玫瑰花", "kind": "gift", "tier": "precious", "anim": "玫瑰",
         "icon_key": "rose", "lines": []},
    ]
}
LEVELS = {"levels": [{"threshold": 0, "title": "认识", "unlocks": []}]}
CHECKIN = {
    "base_items": {"common": 2},
    "base_affection": 0,
    "first_affection": 2,
    "milestones": {"3": {"items": {"rare": 1}, "affection": 5}},
}
EVENTS = {
    "events": [
        {"id": "valentine", "date": "02-14", "name": "情人节",
         "scene": "event_valentine",
         "items": [{"name": "玫瑰花", "count": 1}], "affection": 4},
        {"id": "birthday", "date": "birthday", "name": "生日",
         "scene": "event_birthday",
         "items": [{"name": "生日蛋糕", "count": 1}], "affection": 10},
    ]
}


def _scene(name: str, text: str, **extra) -> dict:
    data = {"scene": name, "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
            "lines": [{"text": text, "weight": 1}]}
    data.update(extra)
    return data


DIALOGUES = {
    name: _scene(name, text)
    for name, text in (
        ("checkin_done", "这是今天的份。"),
        ("checkin_milestone", "第 3 天了，记一下。"),
        ("checkin_already", "今天已经签过了。"),
        ("checkin_clock_back", "时间好像不太对。"),
        ("checkin_remind", "今天的份还没拿。"),
        ("inventory_full", "拿不下啦，先送掉一些吧。"),
        ("convert_minutes", "你陪我好久了。"),
        ("convert_typing", "敲得真快，这个给你。"),
        ("egg_hourly", "整点了，这个给你。"),
        ("egg_afk", "刚才捡到的，给你留着。"),
        ("first_run", "第一次见面，这个给你。"),
        ("event_valentine", "今天是情人节呢。"),
        ("event_birthday", "生日快乐。"),
        ("idle_random", "我在呢。"),
        ("idle_long_absent", "我在这儿呢。"),
    )
}


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class StubRng:
    """把整点彩蛋的骰子钉死（否则测试的成败取决于随机数）。"""

    def __init__(self, value: float = 0.0):
        self.value = float(value)

    def random(self) -> float:
        return self.value

    def choice(self, seq):           # `resolve_tiers` 可能拿它当 chooser
        return seq[0]


class FakeCharacter(CharacterController):
    DEFAULT_ACTIONS = ("笑", "蛋糕", "玫瑰", "点赞", "害羞 2", "庆祝", "点头")

    def __init__(self, character_type: str = "gif", actions=DEFAULT_ACTIONS, busy=False):
        super().__init__()
        self._type = character_type
        self._actions = set(actions)
        self._busy = busy
        self.played: list[str] = []

    @property
    def character_type(self) -> str:
        return self._type

    def get_available_animations(self) -> list[str]:
        return sorted(self._actions)

    def is_busy(self) -> bool:
        return self._busy

    def play_action(self, action: str, lock: bool = True) -> bool:
        if action not in self._actions:
            return False
        self.played.append(action)
        return True


class RewardTestCase(unittest.TestCase):
    """公共装置：临时素材 + 临时存档 + 钉死的"现在"。"""

    cfg: dict = {"send_cooldown_ms": 0, "hourly_bonus_enabled": False}
    #: 固定"现在"= 2026-09-10 14:30。14 点不属于任何时段问候，
    #: 所以心跳里的 `time_*` 不会插进来抢那句台词。
    NOW = datetime(2026, 9, 10, 14, 30)
    today = NOW.date()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_reward_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        assets = os.path.join(self.tmp, "nurture")
        os.makedirs(os.path.join(assets, "dialogues"))
        blobs = {"items.json": ITEMS, "levels.json": LEVELS, "checkin.json": CHECKIN,
                 "events.json": EVENTS}
        for name, data in blobs.items():
            with open(os.path.join(assets, name), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
        for name, data in DIALOGUES.items():
            with open(os.path.join(assets, "dialogues", f"{name}.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
        self.assets = assets

        self.store = store_mod.NurtureStore(
            path=os.path.join(self.tmp, "data", "nurture.json"))
        self.controller = nc.NurtureController(self.store, dict(self.cfg), assets_dir=assets)
        # 默认把"首次使用彩蛋"标记成已发，免得它抢走每个 tick 测试的那句话。
        # **必须在 controller 构造之后设**：`NurtureController.__init__` 会调 `store.load()`
        # 重新读盘，构造之前设的 flag 会被默认值覆盖掉（这个坑单测抓过一次）。
        self.store.set_flag("first_run_bonus_granted", True)
        self.controller._now = lambda: self.NOW          # noqa: SLF001 - 钉死时钟
        # 把"下一次闲聊"推到一小时后：否则每个 tick 测试最后都会说一句 idle_random，
        # 而它总是抢在断言前面返回（要测 idle_random 本身的用例会自己改这个值）
        self.controller._next_idle_ts = time.monotonic() + 3600    # noqa: SLF001
        self.addCleanup(self._cleanup)
        self.character = FakeCharacter()
        self.controller.attach_character(self.character)
        self.speech: list[tuple[str, str]] = []
        self.controller.speech_requested.connect(
            lambda text, tone: self.speech.append((text, tone)))

    def _cleanup(self):
        panel = self.controller.panel_widget()
        if panel is not None:
            panel.deleteLater()
        self.controller.deleteLater()

    # ── 断言小工具 ──

    def said(self) -> list[str]:
        return [text for text, _tone in self.speech]

    def total_stock(self) -> int:
        return sum(self.store.inventory.values())

    def reload_controller(self):
        """换一份配置重开 controller（沿用同一个存档）。"""
        self.controller.deleteLater()
        self.controller = nc.NurtureController(self.store, dict(self.cfg),
                                              assets_dir=self.assets)
        self.controller._now = lambda: self.NOW          # noqa: SLF001
        self.controller._next_idle_ts = time.monotonic() + 3600    # noqa: SLF001
        self.controller.attach_character(self.character)
        self.controller.speech_requested.connect(
            lambda text, tone: self.speech.append((text, tone)))

    def accrue(self, minutes: int) -> None:
        """累计 N 分钟活动时间。

        **必须一段一段喂**：单次活动超过 `ACTIVITY_GAP_CAP_SEC`（5 秒）的部分会被截断
        —— 这正是"纯挂机不计入"的实现方式，所以一口气 `accrue_activity(600)` 只算 5 秒。
        """
        for _ in range(int(minutes) * 12):
            self.controller.accrue_activity(5)


class TestCheckin(RewardTestCase):
    """每日签到（01 文档 4.1 + 4.4）。"""

    def test_first_checkin_grants_items_and_affection(self):
        result = self.controller.try_checkin()
        self.assertEqual(result, nc.RESULT_OK)
        self.assertEqual(self.store.streak, 1)
        self.assertEqual(self.store.last_checkin_date, self.today)
        self.assertEqual(self.total_stock(), 2)                    # common ×2
        self.assertEqual(self.store.affection, 2)                  # first_affection
        self.assertEqual(self.store.stats("total_checkins"), 1)
        self.assertEqual(self.character.played, ["庆祝"])
        self.assertEqual(self.said(), ["这是今天的份。"])

    def test_second_checkin_same_day_is_rejected(self):
        self.controller.try_checkin()
        self.speech.clear()
        before = self.total_stock()
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_ALREADY)
        self.assertEqual(self.total_stock(), before)               # 没多发
        self.assertEqual(self.store.streak, 1)
        self.assertEqual(self.said(), ["今天已经签过了。"])

    def test_streak_increments_on_the_next_day(self):
        self.store.set_checkin(2, self.today - timedelta(days=1))
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_OK)
        self.assertEqual(self.store.streak, 3)
        self.assertIn("草莓蛋糕", self.store.inventory)             # 第 3 天里程碑：rare ×1
        self.assertEqual(self.store.affection, 5)                  # 里程碑好感度

    def test_streak_resets_after_a_gap(self):
        self.store.set_checkin(9, self.today - timedelta(days=4))
        self.controller.try_checkin()
        self.assertEqual(self.store.streak, 1)
        self.assertEqual(self.store.affection, 2)                  # 回到"首次"待遇

    def test_clock_back_does_not_grant_or_reset(self):
        """系统时间被往回改 → 不发放、不重置（01 文档 4.4）。"""
        future = self.today + timedelta(days=1)
        self.store.set_checkin(7, future)
        before = self.total_stock()
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_CLOCK_BACK)
        self.assertEqual(self.store.streak, 7)                     # 连签原样
        self.assertEqual(self.store.last_checkin_date, future)
        self.assertEqual(self.total_stock(), before)
        self.assertEqual(self.said(), ["时间好像不太对。"])

    def test_disabled_switch(self):
        self.controller.set_config(dict(self.cfg, checkin_enabled=False))
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_DISABLED)
        self.assertEqual(self.speech, [])

    def test_disabled_when_the_character_is_not_gif(self):
        self.controller.attach_character(FakeCharacter(character_type="png"))
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_DISABLED)

    def test_full_inventory_still_records_the_checkin(self):
        """库存满 → 东西拿不下，但**签到记录必须记**：不然明天还能再签一次。"""
        self.controller.set_config(dict(self.cfg, tier_caps={"common": 1}))
        self.store.add_item("奶油面包", 1)
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_OK)
        self.assertEqual(self.store.last_checkin_date, self.today)
        self.assertEqual(self.store.item_count("奶油面包"), 1)      # 没放进去
        self.assertEqual(self.said(), ["拿不下啦，先送掉一些吧。"])

    def test_one_bubble_per_click(self):
        """一次点击只说一句（气泡是替换不是叠放，说三句只会剩最后一句）。"""
        self.store.set_checkin(2, self.today - timedelta(days=1))
        self.controller.try_checkin()
        self.assertEqual(len(self.speech), 1)
        self.assertEqual(self.said(), ["第 3 天了，记一下。"])       # 里程碑优先于普通签到

    def test_missing_dialogue_files_still_say_something(self):
        """台词文件被删了也不能"点了没反应"（`dialogue.DEFAULT_SCENES` 兜底顶上）。"""
        for name in ("checkin_done", "checkin_milestone", "inventory_full"):
            os.remove(os.path.join(self.assets, "dialogues", f"{name}.json"))
        self.controller.reload_assets()
        self.assertEqual(self.controller.try_checkin(), nc.RESULT_OK)
        self.assertEqual(len(self.speech), 1)
        self.assertTrue(self.speech[0][0].strip())

    def test_checkin_available_tracks_the_store(self):
        self.assertTrue(self.controller.checkin_available())
        self.controller.try_checkin()
        self.assertFalse(self.controller.checkin_available())

    def test_menu_badge_goes_out_after_checkin(self):
        """角标由 controller 按存档现算，签完就该灭（悬停菜单那颗红点）。"""
        self.assertTrue(self.controller.menu_badges()["checkin"])
        self.controller.try_checkin()
        self.assertFalse(self.controller.menu_badges()["checkin"])


class TestCheckinReminder(RewardTestCase):
    """01 文档 4.1 的第 2 条入口：首次弹出悬停菜单时提一句（每天一次）。"""

    def test_reminds_once_a_day(self):
        self.assertEqual(self.controller.on_menu_shown(), "今天的份还没拿。")
        self.speech.clear()
        self.assertIsNone(self.controller.on_menu_shown())          # 同一天不再提
        self.assertEqual(self.speech, [])

    def test_no_reminder_after_checking_in(self):
        self.controller.try_checkin()
        self.speech.clear()
        self.assertIsNone(self.controller.on_menu_shown())

    def test_reminder_is_recorded_only_when_spoken(self):
        """说不出来（池子空）就不该记日期 —— 否则这一天永远不再提醒。"""
        os.remove(os.path.join(self.assets, "dialogues", "checkin_remind.json"))
        self.controller.reload_assets()
        self.assertIsNone(self.controller.on_menu_shown())
        self.assertEqual(self.store.flag("checkin_reminded_date", ""), "")


class TestConversions(RewardTestCase):
    """陪伴时长 / 打字量兑换（01 文档 4.2）。"""

    def _grant_and_tick(self, **cfg):
        self.controller.set_config(dict(self.cfg, **cfg))
        return self.controller.on_idle_tick()

    def test_minutes_conversion(self):
        self.controller.accrue_activity(60 * 61)                    # 单次截断到 5 秒！
        self.assertEqual(self.controller.active_minutes(), 0)
        self.accrue(1)                                              # 分 12 段喂满 1 分钟
        self.assertEqual(self.controller.active_minutes(), 1)

    def test_accrual_is_capped_per_event(self):
        """挂机 3 小时后的第一次鼠标移动只能算 5 秒（纯挂机不计入）。"""
        self.controller.accrue_activity(3600 * 3)
        self.assertLessEqual(self.controller._active_seconds,          # noqa: SLF001
                             nc.ACTIVITY_GAP_CAP_SEC)

    def test_minutes_reward_granted_once_per_threshold(self):
        self.accrue(1)
        self.assertEqual(self._grant_and_tick(companion_minutes_per_item=1,
                                              companion_daily_cap=3),
                         "你陪我好久了。")
        self.assertEqual(self.total_stock(), 1)
        self.assertEqual(self.store.daily("minutes_rewarded"), 1)
        self.assertEqual(self.character.played, ["点头"])

        self.speech.clear()
        self.assertIsNone(self.controller.on_idle_tick())           # 同一份进度不再发
        self.assertEqual(self.total_stock(), 1)

    def test_stale_progress_is_not_paid_twice_after_restart(self):
        """重启后从存档恢复进度，已兑换的部分不会被重新结算。"""
        self.controller.set_config(dict(self.cfg, companion_minutes_per_item=1))
        self.accrue(1)
        self.controller.on_idle_tick()
        self.assertEqual(self.total_stock(), 1)
        self.store.flush()
        self.reload_controller()
        self.controller.set_config(dict(self.cfg, companion_minutes_per_item=1))
        self.controller.start_scheduler()
        self.controller.stop_scheduler()
        self.controller.on_idle_tick()
        self.assertEqual(self.total_stock(), 1)                     # 还是 1 份

    def test_daily_cap(self):
        self.controller.set_config(dict(self.cfg, companion_minutes_per_item=1,
                                        companion_daily_cap=2))
        self.accrue(5)
        self.controller.on_idle_tick()
        self.assertEqual(self.store.daily("minutes_rewarded"), 2)    # 上限 2
        self.assertEqual(self.total_stock(), 2)

    def test_typing_conversion(self):
        self.controller.set_config(dict(self.cfg, typing_keys_per_item=10,
                                        typing_daily_cap=2))
        for _ in range(10):
            self.controller.report_key_press()
        self.assertEqual(self.controller.keys_today(), 10)
        self.assertEqual(self.controller.on_idle_tick(), "敲得真快，这个给你。")
        self.assertEqual(self.total_stock(), 1)
        self.assertEqual(self.store.daily("keys_rewarded"), 1)

    def test_zero_threshold_does_not_explode(self):
        """`per = 0` 是配置错误 → 不发放、不除零、不崩。"""
        self.controller.set_config(dict(self.cfg, companion_minutes_per_item=0))
        self.accrue(5)
        self.assertIsNone(self.controller.on_idle_tick())
        self.assertEqual(self.total_stock(), 0)

    def test_progress_is_persisted(self):
        self.accrue(2)
        for _ in range(3):
            self.controller.report_key_press()
        self.controller.on_idle_tick()
        self.assertEqual(self.store.daily("active_minutes"), 2)
        self.assertEqual(self.store.daily("key_count"), 3)

    def test_no_duplicate_write_when_progress_is_unchanged(self):
        """进度没变就不该写存档（`changed` 信号每分钟一次已经够吵了）。"""
        self.accrue(1)
        self.controller.on_idle_tick()
        fired = []
        self.store.changed.connect(lambda _seg: fired.append(1))
        self.controller.on_idle_tick()
        self.assertEqual(fired, [])


class TestEggs(RewardTestCase):
    """彩蛋：整点 / 长待机 / 节日 / 首次使用（01 文档 4.3）。"""

    def test_first_run_grants_precious_food_once(self):
        self.store.set_flag("first_run_bonus_granted", False)
        self.assertEqual(self.controller.on_idle_tick(), "第一次见面，这个给你。")
        self.assertIn("生日蛋糕", self.store.inventory)
        self.assertTrue(self.store.flag("first_run_bonus_granted"))
        self.speech.clear()
        self.assertIsNone(self.controller._check_first_run_egg())     # noqa: SLF001

    def test_hourly_egg_fires_once_per_hour(self):
        self.controller.set_config(dict(self.cfg, hourly_bonus_enabled=True,
                                        hourly_bonus_chance=1.0))
        self.controller._rng = StubRng(0.0)                          # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "整点了，这个给你。")
        self.assertEqual(self.total_stock(), 1)
        self.assertEqual(self.store.daily("hourly_bonus_count"), 1)
        self.speech.clear()
        self.assertIsNone(self.controller._check_hourly_egg(self.NOW))  # noqa: SLF001

        later = self.NOW.replace(hour=15)
        self.assertEqual(self.controller._check_hourly_egg(later),      # noqa: SLF001
                         "整点了，这个给你。")
        self.assertEqual(self.total_stock(), 2)

    def test_hourly_egg_misses_when_the_dice_says_so(self):
        self.controller.set_config(dict(self.cfg, hourly_bonus_enabled=True,
                                        hourly_bonus_chance=0.25))
        self.controller._rng = StubRng(0.99)                         # noqa: SLF001
        self.assertIsNone(self.controller._check_hourly_egg(self.NOW))  # noqa: SLF001
        self.assertEqual(self.store.daily("hourly_bonus_count"), 0)

    def test_hourly_egg_daily_cap(self):
        self.controller.set_config(dict(self.cfg, hourly_bonus_enabled=True,
                                        hourly_bonus_chance=1.0,
                                        hourly_bonus_daily_cap=1))
        self.controller._rng = StubRng(0.0)                          # noqa: SLF001
        self.controller._check_hourly_egg(self.NOW)                  # noqa: SLF001
        self.assertIsNone(self.controller._check_hourly_egg(          # noqa: SLF001
            self.NOW.replace(hour=15)))
        self.assertEqual(self.total_stock(), 1)

    def test_hourly_egg_can_be_disabled(self):
        self.controller.set_config(dict(self.cfg, hourly_bonus_enabled=False))
        self.controller._rng = StubRng(0.0)                          # noqa: SLF001
        self.assertIsNone(self.controller._check_hourly_egg(self.NOW))  # noqa: SLF001

    def test_afk_egg_once_a_day(self):
        self.assertEqual(self.controller._check_afk_egg(11),         # noqa: SLF001
                         "刚才捡到的，给你留着。")
        self.assertIn("草莓蛋糕", self.store.inventory)              # rare 档
        self.speech.clear()
        self.assertIsNone(self.controller._check_afk_egg(60))        # noqa: SLF001
        self.assertEqual(self.speech, [])

    def test_afk_egg_needs_the_threshold(self):
        self.assertIsNone(self.controller._check_afk_egg(3))         # noqa: SLF001
        self.assertEqual(self.total_stock(), 0)

    def test_afk_daily_flag_survives_a_reload(self):
        """`afk_bonus_date` 必须在 `FLAG_DEFAULTS` 里，否则重启后每天能领好几次。"""
        self.controller._check_afk_egg(30)                           # noqa: SLF001
        self.store.flush()
        self.store.load(self.today)
        self.assertEqual(str(self.store.flag("afk_bonus_date", "")),
                         self.today.isoformat())

    def test_event_grants_and_speaks(self):
        self.controller._now = lambda: datetime(2026, 2, 14, 14, 30)  # noqa: SLF001
        self.assertEqual(self.controller._check_event_egg(date(2026, 2, 14)),  # noqa: SLF001
                         "今天是情人节呢。")
        self.assertIn("玫瑰花", self.store.inventory)
        self.assertEqual(self.store.affection, 4)
        self.assertEqual(self.character.played, ["庆祝"])

    def test_event_is_granted_only_once_a_day(self):
        self.controller._check_event_egg(date(2026, 2, 14))           # noqa: SLF001
        self.speech.clear()
        self.assertIsNone(self.controller._check_event_egg(date(2026, 2, 14)))  # noqa: SLF001
        self.assertEqual(len(self.store.inventory), 1)

    def test_event_flag_survives_a_reload(self):
        self.controller._check_event_egg(date(2026, 2, 14))           # noqa: SLF001
        self.store.flush()
        self.store.load(date(2026, 2, 14))
        self.assertEqual(str(self.store.flag("last_event_date", "")), "2026-02-14")

    def test_birthday_uses_the_configured_date(self):
        self.controller.set_config(dict(self.cfg, birthday="09-10"))
        self.assertEqual(self.controller._check_event_egg(self.today),  # noqa: SLF001
                         "生日快乐。")
        self.assertIn("生日蛋糕", self.store.inventory)

    def test_no_birthday_no_event(self):
        self.controller.set_config(dict(self.cfg, birthday=""))
        self.assertIsNone(self.controller._check_event_egg(self.today))  # noqa: SLF001

    def test_blocked_event_line_is_retried_on_the_next_tick(self):
        """节日台词是主动台词，会被 90 秒间隔挡下 —— 那就下次心跳补说。"""
        self.controller._last_proactive_ts = __import__("time").monotonic()  # noqa: SLF001
        self.assertIsNone(self.controller._check_event_egg(date(2026, 2, 14)))  # noqa: SLF001
        self.assertIn("玫瑰花", self.store.inventory)                # 东西先到手
        self.assertIsNotNone(self.controller._pending_speech)        # noqa: SLF001
        self.controller._last_proactive_ts = 0.0                     # noqa: SLF001
        self.assertEqual(self.controller.flush_pending_speech(), "今天是情人节呢。")

    def test_event_with_unknown_item_name_does_not_crash(self):
        events = {"events": [{"id": "x", "date": "09-10", "scene": "event_valentine",
                              "items": [{"name": "不存在的东西", "count": 1}]}]}
        with open(os.path.join(self.assets, "events.json"), "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False)
        self.controller.reload_assets()
        self.controller._check_event_egg(self.today)                  # noqa: SLF001
        self.assertEqual(self.total_stock(), 0)                      # 没发也没崩
        self.assertEqual(self.store.flag("last_event_date", ""),
                         self.today.isoformat())


class TestTickOrder(RewardTestCase):
    """心跳里各条途径的优先级（一次心跳最多说一句）。"""

    def test_first_run_beats_conversions(self):
        self.store.set_flag("first_run_bonus_granted", False)
        self.controller.set_config(dict(self.cfg, companion_minutes_per_item=1))
        self.controller.accrue_activity(60)
        self.assertEqual(self.controller.on_idle_tick(), "第一次见面，这个给你。")

    def test_idle_line_still_works_when_nothing_is_due(self):
        self.controller._next_idle_ts = 0.0                          # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "我在呢。")

    def test_afk_egg_replaces_the_plain_idle_line(self):
        import time as _time
        self.controller._last_activity_ts = _time.monotonic() - 11 * 60  # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "刚才捡到的，给你留着。")
        # 第二次空闲：彩蛋今天已经发过 → 回到平时那句
        self.speech.clear()
        self.controller._last_activity_ts = _time.monotonic() - 12 * 60  # noqa: SLF001
        self.controller._afk_spoken = False                             # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "我在这儿呢。")

    def test_no_duplicate_grant_after_many_ticks(self):
        """心跳跑 20 遍也只发一次（`already` 计数 + flag 双重保险）。"""
        self.controller.set_config(dict(self.cfg, companion_minutes_per_item=1,
                                        hourly_bonus_enabled=True, hourly_bonus_chance=1.0,
                                        typing_keys_per_item=10))
        self.controller._rng = StubRng(0.0)                          # noqa: SLF001
        self.accrue(1)
        for _ in range(10):
            self.controller.report_key_press()
        for _ in range(20):
            self.controller.on_idle_tick()
        self.assertEqual(self.total_stock(), 3)     # 陪伴 1 + 打字 1 + 整点 1
        self.assertEqual(self.store.daily("minutes_rewarded"), 1)
        self.assertEqual(self.store.daily("keys_rewarded"), 1)
        self.assertEqual(self.store.daily("hourly_bonus_count"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
