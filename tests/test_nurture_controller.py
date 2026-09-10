"""`src/nurture_controller.py` 单测 —— 喂食闭环的**每一条分支**。

这个模块是养成系统里唯一会改存档、扣库存、播动画的地方，所以覆盖策略是
"每个结果码一个测试类"：

| 结果码 | 触发条件 |
|--------|----------|
| `ok` | 正常送出 |
| `empty` | 库存 0（含并发抢库存：`take_item` 返回 False） |
| `unknown` | 物品名不在 `items.json` 里 |
| `capped` | 好感度到今日上限（动画照播，只是不加） |
| `gift_capped` | 今日送礼次数已满 |
| `locked` | 她正忙（启动序列 / 上一个动画没播完） |
| `cooldown` | 连点防护 |
| `no_anim` | 素材全缺：只出台词不播动画 |
| `disabled` | 养成关闭 / 当前不是 Q版 |

用**临时素材目录**（`assets_dir=`）而不是真 `assets/nurture/`：
真素材是用户可编辑的，测试断言"奶油面包 +1 好感度"会在用户改表之后变成假失败。
另有一组 `TestRealAssets` 用真素材做冒烟，只断言"能跑通"不锁数字。

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src import nurture_controller as nc  # noqa: E402
from src import nurture_store as store_mod  # noqa: E402
from src.character_base import CharacterController  # noqa: E402

_APP = None
REAL_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "nurture")

ITEMS = {
    "items": [
        {"name": "奶油面包", "kind": "food", "tier": "common", "anim": "笑",
         "icon_key": "bread", "lines": ["奶油面包，给你留了一个。"]},
        {"name": "草莓蛋糕", "kind": "food", "tier": "rare", "anim": "蛋糕",
         "icon_key": "shortcake", "lines": []},
        {"name": "玫瑰花", "kind": "gift", "tier": "precious", "anim": "玫瑰",
         "icon_key": "rose", "lines": ["这个给你。"]},
        {"name": "没有动画的", "kind": "food", "tier": "common", "anim": "完全不存在",
         "icon_key": "bread", "lines": []},
    ]
}
LEVELS = {
    "levels": [
        {"threshold": 0, "title": "认识", "unlocks": []},
        {"threshold": 50, "title": "同桌", "unlocks": ["idle_random"]},
        {"threshold": 120, "title": "朋友", "unlocks": ["small_talk"]},
        {"threshold": 450, "title": "要好", "unlocks": ["headpat"]},
    ]
}
DIALOGUES = {
    "feed_done.json": {
        "scene": "feed_done",
        "tone": "gentle",
        "lines": [{"text": "唔，好吃。", "weight": 1},
                  {"text": "谢谢你。", "weight": 1}],
    },
    "feed_empty.json": {
        "scene": "feed_empty",
        "tone": "gentle",
        "lines": [{"text": "这个已经吃完了呢。", "weight": 1}],
    },
    "feed_capped.json": {
        "scene": "feed_capped",
        "tone": "gentle",
        "lines": [{"text": "今天已经很开心了。", "weight": 1}],
    },
    "gift_capped.json": {
        "scene": "gift_capped",
        "tone": "gentle",
        "lines": [{"text": "今天收到的已经够多啦。", "weight": 1}],
    },
    "idle_random.json": {
        "scene": "idle_random",
        "tone": "tease",
        "cooldown_sec": 360,
        "lines": [{"text": "又在偷懒吧？", "weight": 1, "tone": "tease"},
                  {"text": "今天的风挺好的。", "weight": 1, "tone": "gentle"}],
    },
    "small_talk.json": {
        "scene": "small_talk", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "嗯，我在听。", "weight": 1}],
    },
    "headpat.json": {
        "scene": "headpat", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "唔……别摸啦。", "weight": 1}],
    },
    "hover_long.json": {
        "scene": "hover_long", "tone": "gentle", "cooldown_sec": 60, "min_gap_sec": 0,
        "lines": [{"text": "怎么一直看着我。", "weight": 1}],
    },
    "detect_typing.json": {
        "scene": "detect_typing", "tone": "gentle", "cooldown_sec": 600, "min_gap_sec": 0,
        "lines": [{"text": "敲得好快呀。", "weight": 1}],
    },
    "detect_audio.json": {
        "scene": "detect_audio", "tone": "gentle", "cooldown_sec": 900, "min_gap_sec": 0,
        "lines": [{"text": "在听歌吗。", "weight": 1}],
    },
    "detect_muted.json": {
        "scene": "detect_muted", "tone": "gentle", "cooldown_sec": 900, "min_gap_sec": 0,
        "lines": [{"text": "怎么没声音了。", "weight": 1}],
    },
    "idle_long_absent.json": {
        "scene": "idle_long_absent", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "我在这儿呢。", "weight": 1}],
    },
    "time_morning.json": {
        "scene": "time_morning", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "早上好。", "weight": 1}],
    },
    "time_noon.json": {
        "scene": "time_noon", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "中午了。", "weight": 1}],
    },
    "time_night.json": {
        "scene": "time_night", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "该睡了。", "weight": 1}],
    },
    "time_late.json": {
        "scene": "time_late", "tone": "gentle", "cooldown_sec": 0, "min_gap_sec": 0,
        "lines": [{"text": "还没睡呀。", "weight": 1}],
    },
    "detect_app_code.json": {
        "scene": "detect_app_code", "tone": "gentle", "cooldown_sec": 1200, "min_gap_sec": 0,
        "lines": [{"text": "又在写代码。", "weight": 1}],
    },
    "detect_app_browser.json": {
        "scene": "detect_app_browser", "tone": "tease", "cooldown_sec": 1200, "min_gap_sec": 0,
        "lines": [{"text": "在查资料吧？", "weight": 1, "tone": "tease"}],
    },
    "detect_app_game.json": {
        "scene": "detect_app_game", "tone": "gentle", "cooldown_sec": 1800, "min_gap_sec": 0,
        "lines": [{"text": "我在旁边陪着。", "weight": 1}],
    },
    "detect_app_meeting.json": {
        "scene": "detect_app_meeting", "tone": "gentle", "cooldown_sec": 1800, "min_gap_sec": 0,
        "lines": [{"text": "在开会呀。", "weight": 1}],
    },
    "detect_app_media.json": {
        "scene": "detect_app_media", "tone": "gentle", "cooldown_sec": 1200, "min_gap_sec": 0,
        "lines": [{"text": "有声音呢。", "weight": 1}],
    },
}


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class FakeCharacter(CharacterController):
    """只记录调用、不播动画的假角色。

    默认动作集合包含**兜底链上面的两级默认**（food=笑 / gift=点赞 / 全局=害羞 2），
    否则"兜底链选出来的动作"会因为"假角色没有这个素材"变成 None，测试就白测了。
    """

    DEFAULT_ACTIONS = ("笑", "蛋糕", "玫瑰", "点赞", "害羞 2")

    def __init__(self, character_type: str = "gif", actions=DEFAULT_ACTIONS,
                 busy: bool = False, play_ok: bool = True, raises: bool = False):
        super().__init__()
        self._type = character_type
        self._actions = set(actions)
        self._busy = busy
        self._play_ok = play_ok
        self._raises = raises
        self.played: list[str] = []

    @property
    def character_type(self) -> str:
        return self._type

    def get_available_animations(self) -> list[str]:
        return sorted(self._actions)

    def is_busy(self) -> bool:
        return self._busy

    def play_action(self, action: str, lock: bool = True) -> bool:
        if self._raises:
            raise RuntimeError("素材坏了")
        if not self._play_ok or action not in self._actions:
            return False
        self.played.append(action)
        return True


class FakeMenu:
    def __init__(self, keys=("feed", "gift", "checkin", "heart", "chat", "headpat",
                             "settings")):
        self._keys = list(keys)
        self.enabled: dict = {}
        self.badges: dict = {}

    def item_keys(self):
        return list(self._keys)

    def set_enabled_map(self, mapping):
        self.enabled.update(mapping)

    def set_badge(self, key, on):
        self.badges[key] = bool(on)


class FakeWindowMonitor:
    """只记录启停的假感知器（真的是 `src/window_monitor.WindowMonitor`）。"""

    def __init__(self):
        self.enabled = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def is_enabled(self):
        return self.enabled


class BrokenWindowMonitor:
    """每个方法都炸 —— 设置页改开关时不该被它带走。"""

    def set_enabled(self, enabled):
        raise RuntimeError("感知器坏了")

    def is_enabled(self):
        raise RuntimeError("感知器坏了")


class ControllerTestCase(unittest.TestCase):
    """公共装置：临时素材目录 + 临时存档。"""

    cfg = {}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_ctrl_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        assets = os.path.join(self.tmp, "nurture")
        os.makedirs(os.path.join(assets, "dialogues"))
        for name, data in (("items.json", ITEMS), ("levels.json", LEVELS)):
            with open(os.path.join(assets, name), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
        for name, data in DIALOGUES.items():
            with open(os.path.join(assets, "dialogues", name), "w",
                      encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
        self.assets = assets

        self.store = store_mod.NurtureStore(
            path=os.path.join(self.tmp, "data", "nurture.json"))
        cfg = dict(self.cfg)
        cfg.setdefault("send_cooldown_ms", 0)      # 测试里默认关掉连点防护
        # **默认关掉深夜禁区**（零长度 = 无深夜时段）：`_tease_allowed()` 读当前小时，
        # 不关的话"23:00 之后跑全量测试"会冒出一批假失败（2026-09-10 实测踩过）。
        # 单个用例若把这几条显式写进 `set_config()`，那就是它自己的选择。
        cfg.setdefault("mute_hours_start", 0)
        cfg.setdefault("mute_hours_end", 0)
        self.controller = nc.NurtureController(self.store, cfg, assets_dir=assets)
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

    def stock(self, name: str, count: int) -> None:
        self.store.add_item(name, count)


class TestBasicSend(ControllerTestCase):
    def test_successful_send(self):
        self.stock("奶油面包", 2)
        result = self.controller.try_send("奶油面包")
        self.assertEqual(result, nc.RESULT_OK)
        self.assertEqual(self.store.item_count("奶油面包"), 1)      # 扣了 1
        self.assertGreater(self.store.affection, 0)               # 加了好感度
        self.assertEqual(self.character.played, ["笑"])              # 播了映射的动作
        self.assertEqual(len(self.speech), 1)                       # 说了专属台词
        self.assertEqual(self.speech[0][0], "奶油面包，给你留了一个。")

    def test_emits_state_changed(self):
        self.stock("奶油面包", 1)
        fired = []
        self.controller.state_changed.connect(lambda: fired.append(1))
        self.controller.try_send("奶油面包")
        self.assertEqual(fired, [1])

    def test_item_without_lines_uses_feed_done_scene(self):
        self.stock("草莓蛋糕", 1)
        self.assertEqual(self.controller.try_send("草莓蛋糕"), nc.RESULT_OK)
        self.assertEqual(len(self.speech), 1)
        self.assertIn(self.speech[0][0], ["唔，好吃。", "谢谢你。"])

    def test_common_tier_gain(self):
        self.stock("奶油面包", 1)
        self.controller.try_send("奶油面包")
        self.assertEqual(self.store.affection, 1)                 # 内置表 common=1

    def test_tier_gain_can_be_overridden_by_config(self):
        self.controller.set_config({"tier_affection": {"common": 5}, "send_cooldown_ms": 0})
        self.stock("奶油面包", 1)
        self.controller.try_send("奶油面包")
        self.assertEqual(self.store.affection, 5)

    def test_gift_counts_towards_the_daily_gift_cap(self):
        self.stock("玫瑰花", 1)
        self.assertEqual(self.controller.try_send("玫瑰花"), nc.RESULT_OK)
        self.assertEqual(self.store.gifts_sent_today, 1)

    def test_food_does_not_count_as_a_gift(self):
        self.stock("奶油面包", 1)
        self.controller.try_send("奶油面包")
        self.assertEqual(self.store.gifts_sent_today, 0)

    def test_cumulative_stats_are_recorded(self):
        """累计统计（`STATS_KEYS`）只增不减，供阶段 H 的状态展示用。"""
        self.stock("奶油面包", 1)
        self.stock("玫瑰花", 1)
        self.controller.try_send("奶油面包")
        self.controller.try_send("玫瑰花")
        self.assertEqual(self.store.stats("total_fed"), 1)
        self.assertEqual(self.store.stats("total_gifts"), 1)

    def test_stats_are_not_recorded_on_failure(self):
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_EMPTY)
        self.assertEqual(self.store.stats("total_fed"), 0)


class TestFailures(ControllerTestCase):
    def test_unknown_item(self):
        self.assertEqual(self.controller.try_send("不存在的食物"), nc.RESULT_UNKNOWN)
        self.assertEqual(self.controller.try_send(""), nc.RESULT_UNKNOWN)
        self.assertEqual(self.controller.try_send(None), nc.RESULT_UNKNOWN)

    def test_empty_stock_does_not_deduct_or_play(self):
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_EMPTY)
        self.assertEqual(self.store.item_count("奶油面包"), 0)
        self.assertEqual(self.store.affection, 0)
        self.assertEqual(self.character.played, [])
        self.assertEqual(self.speech[0][0], "这个已经吃完了呢。")

    def test_take_item_failure_is_treated_as_empty(self):
        """并发下另一次送出把库存抢走了 → 结果码必须是 empty，绝不能扣出负数。"""
        self.stock("奶油面包", 1)
        original = self.store.take_item

        def steal(name, n=1):
            original(name, n)                 # 先被别人抢走
            return False

        self.store.take_item = steal
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_EMPTY)
        self.assertEqual(self.store.item_count("奶油面包"), 0)
        self.assertEqual(self.store.affection, 0)

    def test_gift_daily_cap(self):
        self.controller.set_config({"gift_daily_cap": 1, "send_cooldown_ms": 0})
        self.stock("玫瑰花", 5)
        self.assertEqual(self.controller.try_send("玫瑰花"), nc.RESULT_OK)
        self.assertEqual(self.controller.try_send("玫瑰花"), nc.RESULT_GIFT_CAPPED)
        self.assertEqual(self.store.item_count("玫瑰花"), 4)        # 第二次没扣
        self.assertEqual(self.speech[-1][0], "今天收到的已经够多啦。")

    def test_gift_cap_zero_blocks_everything(self):
        self.controller.set_config({"gift_daily_cap": 0, "send_cooldown_ms": 0})
        self.stock("玫瑰花", 1)
        self.assertEqual(self.controller.try_send("玫瑰花"), nc.RESULT_GIFT_CAPPED)
        self.assertEqual(self.store.item_count("玫瑰花"), 1)

    def test_locked_character(self):
        self.stock("奶油面包", 1)
        self.character._busy = True
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_LOCKED)
        self.assertEqual(self.store.item_count("奶油面包"), 1)      # 没扣

    def test_cooldown(self):
        self.controller.set_config({"send_cooldown_ms": 300})
        self.stock("奶油面包", 5)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_OK)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_COOLDOWN)
        self.assertEqual(self.store.item_count("奶油面包"), 4)

    def test_disabled_by_config(self):
        self.controller.set_config({"enabled": False})
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_DISABLED)
        self.assertEqual(self.store.item_count("奶油面包"), 1)

    def test_disabled_for_png_character(self):
        """养成只作用于 Q版（01 文档 0.2）：默认服装下点了也不该扣库存。"""
        self.controller.attach_character(FakeCharacter(character_type="png"))
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_DISABLED)
        self.assertEqual(self.store.item_count("奶油面包"), 1)

    def test_play_action_returning_false_is_no_anim(self):
        self.controller.attach_character(FakeCharacter(play_ok=False))
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_NO_ANIM)
        # 素材播不了也照扣、照说 —— 送出的是那份点心，不是那段动画
        self.assertEqual(self.store.item_count("奶油面包"), 0)
        self.assertEqual(len(self.speech), 1)

    def test_play_action_raising_does_not_escape(self):
        self.controller.attach_character(FakeCharacter(raises=True))
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_NO_ANIM)

    def test_no_character_attached_is_no_anim(self):
        controller = nc.NurtureController(self.store, {"send_cooldown_ms": 0},
                                          assets_dir=self.assets)
        self.addCleanup(controller.deleteLater)
        self.stock("奶油面包", 1)
        self.assertEqual(controller.try_send("奶油面包"), nc.RESULT_NO_ANIM)


class TestFallbackChain(ControllerTestCase):
    """四级兜底链：本项 anim → 类型默认 → 全局兜底 → 只出台词（01 文档 3.3）。"""

    def test_kind_default_when_item_anim_is_missing(self):
        self.assertEqual(self.controller.animation_for({"name": "没写动作", "kind": "food"},
                                                       "food"), "笑")

    def test_gift_kind_default(self):
        """礼物没写 / 写错 anim → 用类型默认「点赞」（01 文档 3.3 的第二级）。"""
        self.assertEqual(self.controller.animation_for({"kind": "gift", "anim": "不存在"},
                                                       "gift"), "点赞")

    def test_global_fallback(self):
        """类型也认不出来 → 全局兜底「害羞 2」（第三级）。"""
        self.assertEqual(self.controller.animation_for({"kind": "??", "anim": "不存在"},
                                                       "??"), "害羞 2")

    def test_all_missing_returns_none(self):
        self.controller.attach_character(FakeCharacter(actions=()))
        self.assertIsNone(self.controller.animation_for({"anim": "笑"}, "food"))

    def test_config_override_wins(self):
        """设置页的「喂食动画映射」优先于 items.json。"""
        self.controller.set_config({"food_anim_override": {"奶油面包": "蛋糕"}})
        anim = self.controller.animation_for({"name": "奶油面包", "anim": "笑"}, "food")
        self.assertEqual(anim, "蛋糕")

    def test_override_to_a_missing_action_falls_back(self):
        self.controller.set_config({"food_anim_override": {"奶油面包": "根本没有"}})
        anim = self.controller.animation_for({"name": "奶油面包", "anim": "笑"}, "food")
        self.assertEqual(anim, "笑")        # 覆盖项失效后继续走兜底链

    def test_item_with_only_a_bad_anim_still_plays_the_global_fallback(self):
        self.stock("没有动画的", 1)
        self.assertEqual(self.controller.try_send("没有动画的"), nc.RESULT_OK)
        self.assertEqual(self.character.played, ["笑"])     # food 默认动作

    def test_registry_raising_degrades(self):
        """素材库读取失败不该让喂食崩 —— `resolve_anim` 内部吞异常。"""
        self.character.get_available_animations = lambda: (_ for _ in ()).throw(OSError)
        self.assertIsNone(self.controller.animation_for({"anim": "笑"}, "food"))


class TestAffectionCap(ControllerTestCase):
    def test_capped_by_the_daily_limit(self):
        self.controller.set_config({"affection_daily_cap": 1, "send_cooldown_ms": 0})
        self.stock("奶油面包", 5)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_OK)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_CAPPED)
        self.assertEqual(self.store.affection, 1)                 # 没再加
        self.assertEqual(self.store.affection_gained_today, 1)
        # 01 文档 6.4：动画照播、台词照说，额外跟一句（场景是 `feed_full`）
        self.assertEqual(self.character.played, ["笑", "笑"])
        self.assertEqual(self.controller.pick_line(nc.CAPPED_SCENE)["tone"], "gentle")
        self.assertIn(self.speech[-1][0], ["今天已经很开心了。", "够了，真的。"])
        self.assertNotEqual(self.speech[-1][0], self.speech[0][0])

    def test_partial_room_is_capped_too(self):
        """想要 5 点、今日只剩 1 点的额度 → 加 1 点，并按"到上限"处理。"""
        self.controller.set_config({"tier_affection": {"common": 5},
                                    "affection_daily_cap": 1, "send_cooldown_ms": 0})
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_CAPPED)
        self.assertEqual(self.store.affection, 1)
        self.assertEqual(self.store.affection_gained_today, 1)

    def test_zero_cap_blocks_affection_but_still_sends(self):
        self.controller.set_config({"affection_daily_cap": 0, "send_cooldown_ms": 0})
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_CAPPED)
        self.assertEqual(self.store.affection, 0)
        self.assertEqual(self.store.item_count("奶油面包"), 0)      # 库存照扣

    def test_dirty_cap_falls_back(self):
        self.controller.set_config({"affection_daily_cap": "很多"})
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_OK)


class TestMenuState(ControllerTestCase):
    def test_feed_disabled_without_food(self):
        self.stock("玫瑰花", 1)                     # 只有礼物
        self.assertFalse(self.controller.menu_enabled_map()["feed"])

    def test_feed_enabled_with_food(self):
        self.stock("奶油面包", 1)
        self.assertTrue(self.controller.menu_enabled_map()["feed"])

    def test_gift_disabled_without_gifts(self):
        self.stock("奶油面包", 1)
        self.assertFalse(self.controller.menu_enabled_map()["gift"])

    def test_gift_disabled_when_the_daily_cap_is_reached(self):
        self.controller.set_config({"gift_daily_cap": 1, "send_cooldown_ms": 0})
        self.stock("玫瑰花", 5)
        self.assertTrue(self.controller.menu_enabled_map()["gift"])
        self.controller.try_send("玫瑰花")
        self.assertFalse(self.controller.menu_enabled_map()["gift"])

    def test_heart_and_settings_are_always_available(self):
        mapping = self.controller.menu_enabled_map()
        self.assertTrue(mapping["heart"])
        self.assertTrue(mapping["settings"])
        self.assertTrue(mapping["checkin"])

    def test_chat_and_headpat_unlock_with_affection(self):
        self.assertFalse(self.controller.menu_enabled_map()["chat"])
        self.assertFalse(self.controller.menu_enabled_map()["headpat"])
        self.store.set_affection(120)
        self.assertTrue(self.controller.menu_enabled_map()["chat"])
        self.assertFalse(self.controller.menu_enabled_map()["headpat"])
        self.store.set_affection(450)
        self.assertTrue(self.controller.menu_enabled_map()["headpat"])

    def test_checkin_badge_when_never_checked_in(self):
        self.assertTrue(self.controller.menu_badges()["checkin"])

    def test_checkin_badge_clears_after_checkin(self):
        from datetime import date
        self.store.set_checkin(1, date.today())
        self.assertFalse(self.controller.menu_badges()["checkin"])

    def test_refresh_menu_pushes_state(self):
        menu = FakeMenu()
        self.controller.attach_menu(menu)
        self.stock("奶油面包", 1)
        self.controller.refresh_menu()
        self.assertTrue(menu.enabled["feed"])
        self.assertFalse(menu.enabled["gift"])
        self.assertTrue(menu.badges["checkin"])

    def test_refresh_menu_without_a_menu_does_nothing(self):
        self.controller.refresh_menu()              # 不该抛异常

    def test_refresh_menu_survives_a_broken_menu(self):
        class Broken:
            def item_keys(self):
                raise RuntimeError("坏了")

        self.controller.attach_menu(Broken())
        self.controller.refresh_menu()              # 不该抛异常


class TestPanel(ControllerTestCase):
    def test_panel_is_not_created_by_panel_widget(self):
        self.assertIsNone(self.controller.panel_widget())
        self.controller.panel()
        self.assertIsNotNone(self.controller.panel_widget())

    def test_refresh_panel_pushes_store_state(self):
        self.stock("奶油面包", 3)
        self.store.set_affection(80)
        panel = self.controller.panel()
        self.controller.refresh_panel()
        self.assertEqual(panel.count_of("奶油面包"), 3)
        self.assertEqual(panel.affection(), 80)
        self.assertGreater(panel.heart_target(), 0.0)          # 断言目标值，不是补间中间态
        self.assertEqual(len(panel.items_of("food")), 3)
        self.assertEqual(len(panel.items_of("gift")), 1)

    def test_show_panel_selects_the_tab_and_pops_up(self):
        from PySide6.QtCore import QRect

        panel = self.controller.panel()
        self.controller.show_panel(QRect(1200, 400, 300, 400), "gift")
        self.assertEqual(panel.tab(), "gift")
        self.assertTrue(panel.isVisible())
        self.assertEqual(panel._popup_direction, "left")       # noqa: SLF001
        panel.hide_now()

    def test_item_chosen_success_hides_the_panel(self):
        self.stock("奶油面包", 1)
        hidden = []
        self.controller.hide_panel = lambda: hidden.append(1)
        self.controller.on_item_chosen("奶油面包")
        self.assertEqual(hidden, [1])

    def test_item_chosen_failure_keeps_the_panel_open(self):
        """库存 0 时面板留着，用户可以直接换一张卡片。"""
        hidden = []
        self.controller.hide_panel = lambda: hidden.append(1)
        self.controller.on_item_chosen("奶油面包")          # 库存 0
        self.assertEqual(hidden, [])

    def test_hide_panel_without_a_panel_is_a_noop(self):
        self.controller.hide_panel()
        self.assertFalse(self.controller.panel_visible())


class TestMenuActions(ControllerTestCase):
    def test_feed_opens_the_food_tab(self):
        calls = []
        self.controller.show_panel = lambda geo, tab="food": calls.append((geo, tab))
        self.assertTrue(self.controller.on_menu_action("feed", "GEOM"))
        self.assertEqual(calls, [("GEOM", "food")])

    def test_gift_opens_the_gift_tab(self):
        calls = []
        self.controller.show_panel = lambda geo, tab="food": calls.append((geo, tab))
        self.assertTrue(self.controller.on_menu_action("gift", "GEOM"))
        self.assertEqual(calls, [("GEOM", "gift")])

    def test_heart_opens_the_status_tab(self):
        calls = []
        self.controller.show_panel = lambda geo, tab="food": calls.append((geo, tab))
        self.assertTrue(self.controller.on_menu_action("heart", "GEOM"))
        self.assertEqual(calls, [("GEOM", "status")])

    def test_checkin_action_is_handled(self):
        """阶段 F 起「签到」由 controller 处理（`settings` 仍是 PetWindow 自己的事）。"""
        self.assertTrue(self.controller.on_menu_action("checkin", None))

    def test_unimplemented_actions_report_false(self):
        for action in ("settings", "nonsense", ""):
            with self.subTest(action=action):
                self.assertFalse(self.controller.on_menu_action(action, None))

    def test_chat_says_a_line(self):
        self.assertTrue(self.controller.on_menu_action("chat", None))
        self.assertEqual(self.speech[-1][0], "嗯，我在听。")

    def test_headpat_plays_and_says(self):
        self.assertTrue(self.controller.on_menu_action("headpat", None))
        self.assertEqual(self.character.played, ["害羞 2"])
        self.assertEqual(self.speech[-1][0], "唔……别摸啦。")

    def test_unknown_menu_action_is_not_handled(self):
        self.assertFalse(self.controller.on_menu_action(None, None))


class TestDialogueIntegration(ControllerTestCase):
    def test_pick_line_returns_text_and_tone(self):
        line = self.controller.pick_line("feed_done")
        self.assertIn(line["text"], ["唔，好吃。", "谢谢你。"])
        self.assertEqual(line["tone"], "gentle")

    def test_missing_scene_is_silent(self):
        self.assertIsNone(self.controller.pick_line("完全不存在的场景"))

    def test_tease_group_is_removed_when_muted(self):
        self.store.set_mute_tease(True)
        line = self.controller.pick_line("idle_random")
        self.assertIsNotNone(line)
        self.assertNotEqual(line["tone"], "tease")
        self.assertNotEqual(line["text"], "又在偷懒吧？")
        self.assertEqual(line["text"], "今天的风挺好的。")

class TestDialogueIntegration(ControllerTestCase):
    """台词库与 controller 的配合。"""

    #: **把深夜禁区设成零长度**（`in_night()` 约定：start == end 即"无深夜时段"）。
    #:
    #: 为什么每个涉及 `tease` 的用例都要带上它：`_tease_allowed()` 会读**当前小时**，
    #: 而 fixture 里 `set_config()` 是**整体替换**配置 —— 只写 `tease_frequency` 的话，
    #: 深夜区间会落回默认的 23:00~07:00，于是"晚上 11 点之后跑全量测试就会红 3 个"。
    #: 这是 2026-09-10 23:01 那次全量跑抓出来的**假的失败**（代码没问题，测试依赖了时钟）。
    #: 深夜禁区本身的正确性由 `test_nurture_model.py` 的 `in_night` 用例负责。
    NO_NIGHT = {"mute_hours_start": 0, "mute_hours_end": 0}

    def test_tease_allowed_when_nothing_forbids_it(self):
        self.controller.set_config({"tease_frequency": "normal", "send_cooldown_ms": 0,
                                    **self.NO_NIGHT})
        self.assertTrue(self.controller._tease_allowed())          # noqa: SLF001

    def test_tease_off_by_frequency(self):
        self.controller.set_config({"tease_frequency": "off", **self.NO_NIGHT})
        self.assertFalse(self.controller._tease_allowed())         # noqa: SLF001

    def test_tease_off_after_the_daily_cap(self):
        self.controller.set_config({"tease_frequency": "normal", "tease_daily_cap": 1,
                                    **self.NO_NIGHT})
        self.store.bump_today("tease_count_today", 1)
        self.assertFalse(self.controller._tease_allowed())         # noqa: SLF001

    def test_context_contains_name_and_affection(self):
        self.controller.set_config({"user_name": "小明"})
        self.store.set_affection(66)
        ctx = self.controller._ctx({"item": "饭团"})                 # noqa: SLF001
        self.assertEqual(ctx["name"], "小明")
        self.assertEqual(ctx["affection"], 66)
        self.assertEqual(ctx["item"], "饭团")

    def test_placeholder_in_an_item_line_is_kept_literal(self):
        """台词里的未知占位符**原样保留**（`dialogue.format_line` 的约定），不该变成空字符串。"""
        self.controller._items.append({"name": "占位符", "kind": "food", "tier": "common",
                                       "anim": "笑", "lines": ["{unknown}，给你。"]})
        self.stock("占位符", 1)
        self.assertEqual(self.controller.try_send("占位符"), nc.RESULT_OK)
        self.assertEqual(self.speech[0][0], "{unknown}，给你。")

    def test_broken_dialogue_library_does_not_break_sending(self):
        self.controller.dialogue.pick_line = lambda *a, **k: (_ for _ in ()).throw(OSError)
        self.stock("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_OK)


class TestDialogueScheduling(ControllerTestCase):
    """01 文档 7.3「防打扰规则」：场景冷却 / 全局最小间隔 90s / 专注保护。

    默认把全局间隔设成 0，这样每个触发入口可以单独验；
    间隔本身由 `test_proactive_scene_speaks_once_then_hits_the_gap` 专门验。
    """

    cfg = {"proactive_min_gap_sec": 0}

    def test_unknown_scene_cannot_speak(self):
        self.assertFalse(self.controller.can_speak("完全不存在的场景"))
        self.assertIsNone(self.controller.say("完全不存在的场景"))

    def test_proactive_scene_speaks_once_then_hits_the_gap(self):
        self.controller.set_config({"proactive_min_gap_sec": 90})
        first = self.controller.say("idle_random")
        self.assertIsNotNone(first)
        # 同一场景：冷却（台词文件里配了 360s）拦住
        self.assertIsNone(self.controller.say("idle_random"))
        # 换个主动场景：被全局最小间隔拦住
        self.assertIsNone(self.controller.say("detect_audio"))

    def test_gap_blocks_only_proactive_scenes(self):
        self.controller.set_config({"proactive_min_gap_sec": 90})
        self.assertIsNotNone(self.controller.say("idle_random"))
        self.assertIsNone(self.controller.say("detect_audio"))     # 主动 → 被拦
        self.assertIsNotNone(self.controller.say("small_talk"))    # 用户触发 → 放行
        self.assertIsNotNone(self.controller.say("headpat"))

    def test_user_triggered_scenes_ignore_the_gap(self):
        """用户主动触发的台词不该被 90 秒间隔拦掉 —— 那只会让用户觉得"点了没反应"。"""
        self.controller.set_config({"proactive_min_gap_sec": 90})
        self.assertIsNotNone(self.controller.say("small_talk"))
        self.assertIsNotNone(self.controller.say("headpat"))
        self.assertIsNotNone(self.controller.say("small_talk"))

    def test_proactive_disabled_by_config(self):
        self.controller.set_config({"proactive_enabled": False,
                                    "proactive_min_gap_sec": 90})
        self.assertFalse(self.controller.can_speak("idle_random"))
        # 用户触发的照常
        self.assertIsNotNone(self.controller.say("small_talk"))

    def test_focus_mode_blocks_proactive_but_not_user_lines(self):
        self.controller.set_activity(typing_rate=500)
        self.assertTrue(self.controller._focus_mode())                 # noqa: SLF001
        self.assertIsNone(self.controller.say("idle_random"))
        self.assertIsNotNone(self.controller.say("small_talk"))

    def test_focus_mode_from_continuous_minutes(self):
        self.controller.set_activity(continuous_min=200)
        self.assertTrue(self.controller._focus_mode())                 # noqa: SLF001

    def test_focus_mode_from_the_foreground_app(self):
        self.controller.set_activity(app="meeting")
        self.assertTrue(self.controller._focus_mode())                 # noqa: SLF001
        for other in ("code", "browser", "game", "media", "unknown", ""):
            with self.subTest(app=other):
                self.controller.set_activity(app=other)
                self.assertFalse(self.controller._focus_mode())        # noqa: SLF001

    def test_focus_mode_from_fullscreen(self):
        """全屏不再靠 `app_key == "fullscreen"` 这种假分类，而是独立的一个布尔位。"""
        self.controller.on_fullscreen_changed(True)
        self.assertTrue(self.controller.is_fullscreen())
        self.assertTrue(self.controller._focus_mode())                 # noqa: SLF001
        self.controller.on_fullscreen_changed(False)
        self.assertFalse(self.controller._focus_mode())                # noqa: SLF001

    def test_not_focused_by_default(self):
        self.assertFalse(self.controller._focus_mode())                # noqa: SLF001

    def test_gap_timestamp_only_moves_when_a_line_was_said(self):
        self.controller.set_config({"proactive_min_gap_sec": 90})
        self.controller.say("idle_random")
        stamp = self.controller._last_proactive_ts                     # noqa: SLF001
        self.assertIsNone(self.controller.say("detect_audio"))   # 被间隔拦住
        self.assertEqual(self.controller._last_proactive_ts, stamp)     # noqa: SLF001

    def test_cooldown_is_not_consumed_by_a_missing_scene(self):
        """抽不到句子（场景不存在）时不留冷却 —— 否则那一刻的机会被白吃掉。"""
        empty = "完全不存在的场景"
        self.controller.say(empty)
        self.assertNotIn(empty, self.controller._cooldowns)             # noqa: SLF001

    def test_tease_line_is_counted(self):
        # 深夜禁区设成零长度：见 `TestDialogueIntegration.NO_NIGHT` 的说明
        self.controller.set_config({"tease_frequency": "normal",
                                    "proactive_min_gap_sec": 0,
                                    "mute_hours_start": 0, "mute_hours_end": 0})
        self.assertEqual(self.store.tease_count_today, 0)
        said = self.controller.say("detect_app_browser")     # 只有一条 tease 台词
        self.assertEqual(said, "在查资料吧？")
        self.assertEqual(self.speech[-1][1], "tease")
        self.assertEqual(self.store.tease_count_today, 1)

    def test_tease_scene_goes_silent_when_muted(self):
        """整组 `tease` 被剔除后，只有 tease 台词的场景就**没话可说**（而不是改成 gentle）。"""
        self.store.set_mute_tease(True)
        self.assertIsNone(self.controller.say("detect_app_browser"))
        # 混排场景照常，只是不会挑到 tease 那条
        self.assertEqual(self.controller.say("idle_random"), "今天的风挺好的。")

    def test_tease_not_counted_for_gentle_lines(self):
        self.assertEqual(self.controller.say("small_talk"), "嗯，我在听。")
        self.assertEqual(self.store.tease_count_today, 0)

    def test_report_key_press_counts_a_rate(self):
        for _ in range(10):
            rate = self.controller.report_key_press()
        self.assertGreater(rate, 0)
        self.assertEqual(self.controller.typing_rate(), rate)

    def test_key_activity_above_threshold_speaks(self):
        said = self.controller.on_key_activity(500)
        self.assertEqual(said, "敲得好快呀。")

    def test_key_activity_below_threshold_is_silent(self):
        self.assertIsNone(self.controller.on_key_activity(5))

    def test_audio_and_mute_lines(self):
        self.assertEqual(self.controller.on_audio(playing=True), "在听歌吗。")
        self.controller._cooldowns.clear()                              # noqa: SLF001
        self.assertEqual(self.controller.on_audio(muted=True), "怎么没声音了。")

    def test_app_changed_maps_to_a_scene(self):
        self.assertEqual(self.controller.on_app_changed("code"), "又在写代码。")

    def test_every_documented_category_maps_to_its_scene(self):
        # 把深夜禁区设成零长度、捉弄开成 normal：这两条断言就与"跑测试的时间"无关了
        # （browser 那个场景只有一条 tease 台词，深夜会被整组剔除）。
        self.controller.set_config({"proactive_min_gap_sec": 0,
                                    "tease_frequency": "normal",
                                    "mute_hours_start": 0, "mute_hours_end": 0})
        expected = {"code": "又在写代码。", "browser": "在查资料吧？",
                    "game": "我在旁边陪着。", "meeting": "在开会呀。",
                    "media": "有声音呢。"}
        for key, line in expected.items():
            with self.subTest(app=key):
                self.controller._cooldowns.clear()                      # noqa: SLF001
                self.controller._last_proactive_ts = 0.0                # noqa: SLF001
                self.assertEqual(self.controller.on_app_changed(key), line)

    def test_app_category_is_remembered_for_later_judgements(self):
        self.controller.on_app_changed("meeting")
        self.assertEqual(self.controller.current_app_key(), "meeting")
        self.assertFalse(self.controller._proactive_allowed())          # noqa: SLF001

    def test_unknown_app_is_silent(self):
        for bad in ("unknown", "", None, "写代码", 123):
            with self.subTest(value=bad):
                self.assertIsNone(self.controller.on_app_changed(bad))
        # 不认识的分类既不说，也不拦
        self.controller.set_config({"proactive_min_gap_sec": 0})
        self.assertTrue(self.controller._proactive_allowed())           # noqa: SLF001

    def test_game_blocks_chatter_but_not_the_observation_line(self):
        """01 文档 5.2 对游戏的定位是「只陪伴，不评价」：闲聊停发，那句话本身照说。"""
        self.controller.set_config({"proactive_min_gap_sec": 0})
        said = self.controller.on_app_changed("game")
        self.assertIsNone(self.controller.say("idle_random"))
        self.assertIsNone(self.controller.say("time_morning"))
        self.assertEqual(said, "我在旁边陪着。")
        self.assertIsNone(self.controller.on_app_changed("game"),
                          "同一场景 30 分钟冷却，第二次不该再说")

    def test_meeting_blocks_chatter_but_not_the_observation_line(self):
        self.controller.set_config({"proactive_min_gap_sec": 0})
        said = self.controller.on_app_changed("meeting")
        self.assertIsNone(self.controller.say("idle_random"))
        self.assertEqual(said, "在开会呀。")

    def test_code_and_media_allow_chatter(self):
        self.controller.set_config({"proactive_min_gap_sec": 0})
        self.controller.on_app_changed("code")
        self.assertIsNotNone(self.controller.say("idle_random"))

    def test_fullscreen_silences_everything_proactive(self):
        """全屏是第一道硬闸门：**连观察类台词也不发**（气泡会盖在人家的画面上）。"""
        self.controller.set_config({"proactive_min_gap_sec": 0})
        self.controller.on_fullscreen_changed(True)
        for scene in ("idle_random", "detect_app_code", "detect_app_game",
                      "detect_app_meeting", "time_morning", "detect_typing"):
            with self.subTest(scene=scene):
                self.assertFalse(self.controller.can_speak(scene))
                self.assertIsNone(self.controller.say(scene))
        # 用户自己触发的照常（点了就该有反应，哪怕他正在全屏看视频）
        self.assertIsNotNone(self.controller.say("small_talk"))

    def test_fullscreen_does_not_mute_rewards(self):
        """签到/兑换是"有东西到手"的交代，不是她主动找话 —— 全屏也照样说。"""
        self.controller.on_fullscreen_changed(True)
        self.assertIsNotNone(self.controller.say("checkin_done"))

    def test_leaving_fullscreen_restores_speech(self):
        self.controller.set_config({"proactive_min_gap_sec": 0})
        self.controller.on_fullscreen_changed(True)
        self.assertIsNone(self.controller.say("idle_random"))
        self.controller.on_fullscreen_changed(False)
        self.assertIsNotNone(self.controller.say("idle_random"))

    def test_typing_fast_also_disables_tease(self):
        """高频打字时连"捉弄"都不许说 —— 那是最容易踩雷的时刻（01 文档 7.1 第 4 条）。"""
        self.controller.set_config({"tease_frequency": "normal",
                                    "proactive_min_gap_sec": 0,
                                    "mute_hours_start": 0, "mute_hours_end": 0})
        self.assertIsNotNone(self.controller.say("detect_app_browser"))
        self.controller.set_activity(typing_rate=500)
        self.assertFalse(self.controller._tease_allowed())              # noqa: SLF001
        self.controller._cooldowns.clear()                              # noqa: SLF001
        self.assertIsNone(self.controller.say("detect_app_browser"))

    def test_foreground_detection_is_off_by_default(self):
        self.assertFalse(self.controller.foreground_detection_enabled())
        self.assertFalse(self.controller.foreground_detection_active())
        self.assertEqual(self.controller.current_app_key(), "")

    def test_attach_window_monitor_follows_the_switch(self):
        monitor = FakeWindowMonitor()
        self.controller.attach_window_monitor(monitor)
        self.assertFalse(monitor.enabled, "开关关着时不该启动感知")
        self.controller.set_config({"allow_foreground_detection": True})
        self.assertTrue(monitor.enabled)
        self.assertTrue(self.controller.foreground_detection_active())
        self.controller.set_config({"allow_foreground_detection": False})
        self.assertFalse(monitor.enabled, "关掉开关要立即停")

    def test_turning_the_switch_off_forgets_what_you_were_using(self):
        monitor = FakeWindowMonitor()
        self.controller.set_config({"allow_foreground_detection": True})
        self.controller.attach_window_monitor(monitor)
        self.controller.on_app_changed("meeting")
        self.controller.on_fullscreen_changed(True)
        self.controller.set_config({"allow_foreground_detection": False})
        self.assertEqual(self.controller.current_app_key(), "")
        self.assertFalse(self.controller.is_fullscreen())
        self.assertTrue(self.controller._proactive_allowed())           # noqa: SLF001

    def test_detaching_the_monitor_clears_the_state(self):
        monitor = FakeWindowMonitor()
        self.controller.set_config({"allow_foreground_detection": True})
        self.controller.attach_window_monitor(monitor)
        self.controller.on_app_changed("game")
        self.controller.attach_window_monitor(None)
        self.assertEqual(self.controller.current_app_key(), "")
        self.assertFalse(self.controller.foreground_detection_active())

    def test_broken_monitor_does_not_raise(self):
        self.controller.set_config({"allow_foreground_detection": True})
        self.controller.attach_window_monitor(BrokenWindowMonitor())
        self.controller.set_config({"allow_foreground_detection": False})
        self.assertFalse(self.controller.foreground_detection_active())

    def test_hover_long(self):
        said = self.controller.on_hover_long()
        self.assertEqual(said, "怎么一直看着我。")

    def test_idle_tick_greets_once_per_period(self):
        """把"现在几点"钉死，否则这几条测试的成败取决于跑测试的时间。"""
        from datetime import datetime as _dt

        for hour, expected in ((7, "早上好。"), (12, "中午了。"),
                               (23, "该睡了。"), (3, "还没睡呀。")):
            with self.subTest(hour=hour):
                controller = nc.NurtureController(self.store, self.controller._cfg,   # noqa: SLF001
                                                  assets_dir=self.assets)
                self.addCleanup(controller.deleteLater)
                controller.attach_character(self.character)
                said = []
                controller.speech_requested.connect(lambda t, tone: said.append(t))
                controller._now = lambda h=hour: _dt(2026, 9, 10, h, 30)   # noqa: SLF001
                controller._next_idle_ts = time.monotonic() + 3600          # noqa: SLF001
                self.assertEqual(controller.on_idle_tick(), expected)
                self.assertEqual(said, [expected])

    def test_no_greeting_outside_the_greeting_hours(self):
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 16, 0)         # noqa: SLF001
        self.controller._next_idle_ts = time.monotonic() + 3600        # noqa: SLF001
        self.assertIsNone(self.controller.on_idle_tick())

    def test_greeting_is_not_repeated_the_same_day(self):
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 7, 30)         # noqa: SLF001
        self.controller._next_idle_ts = time.monotonic() + 3600        # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "早上好。")
        self.assertIsNone(self.controller.on_idle_tick())

    def test_greeting_comes_back_the_next_day(self):
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 7, 30)         # noqa: SLF001
        self.controller._next_idle_ts = time.monotonic() + 3600        # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "早上好。")
        self.controller._now = lambda: _dt(2026, 9, 11, 7, 30)         # noqa: SLF001
        self.assertEqual(self.controller.on_idle_tick(), "早上好。")

    def test_greeting_flag_survives_a_reload(self):
        """问候标记必须能被存档接住 —— 否则每次重启都会重新问候一遍。"""
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 7, 30)         # noqa: SLF001
        self.controller._next_idle_ts = time.monotonic() + 3600        # noqa: SLF001
        self.controller.on_idle_tick()
        self.assertTrue(self.store.flush())
        other = store_mod.NurtureStore(path=self.store.path)
        other.load()
        self.assertEqual(other.flag("time_morning_date", ""), "2026-09-10")

    def test_idle_tick_speaks_random_when_the_interval_elapsed(self):
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 16, 0)   # 非问候时段
        self.controller._next_idle_ts = 0.0                             # noqa: SLF001
        said = self.controller.on_idle_tick()
        self.assertIsNotNone(said)

    def test_idle_tick_reschedules(self):
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 16, 0)   # 非问候时段
        self.controller._next_idle_ts = 0.0                             # noqa: SLF001
        self.controller.on_idle_tick()
        self.assertGreater(self.controller._next_idle_ts, time.monotonic())  # noqa: SLF001

    def test_idle_tick_afk_line_once_per_idle_period(self):
        from datetime import datetime as _dt

        self.controller._now = lambda: _dt(2026, 9, 10, 16, 0)   # 非问候时段
        self.controller._next_idle_ts = time.monotonic() + 3600          # noqa: SLF001
        self.controller._last_activity_ts = 0.0                         # noqa: SLF001
        said = self.controller.on_idle_tick()
        self.assertEqual(said, "我在这儿呢。")
        self.assertIsNone(self.controller.on_idle_tick())   # 同一段空闲只说一次

    def test_typing_reaction_is_not_blocked_by_focus_mode(self):
        """01 文档 7.2 与 7.3 的冲突裁定：`detect_typing` 的触发条件本身就是"高频打字"，
        若同时又受"专注保护"约束，这条台词永远不会出现。所以它单独放行。"""
        self.controller.set_activity(typing_rate=500)
        self.assertTrue(self.controller._focus_mode())                  # noqa: SLF001
        self.assertEqual(self.controller.on_key_activity(500), "敲得好快呀。")
        # 而同一时刻的闲聊该静默
        self.assertIsNone(self.controller.say("idle_random"))

    def test_scheduler_start_and_stop(self):
        self.controller.start_scheduler(tick_ms=1000)
        self.assertTrue(self.controller.scheduler_running())
        self.controller.start_scheduler(tick_ms=1000)     # 幂等
        self.controller.stop_scheduler()
        self.assertFalse(self.controller.scheduler_running())

    def test_scheduler_stop_without_start_is_a_noop(self):
        self.controller.stop_scheduler()
        self.assertFalse(self.controller.scheduler_running())

    def test_headpat_animation_is_not_locking(self):
        """摸头不该锁住交互（只有喂食动画是不可打断的）。"""
        self.controller.try_play_action("害羞 2", lock=False)
        self.assertEqual(self.character.played, ["害羞 2"])

    def test_try_play_action_refuses_while_busy(self):
        self.character._busy = True
        self.assertFalse(self.controller.try_play_action("害羞 2"))

    def test_try_play_action_refuses_unknown_action(self):
        self.assertFalse(self.controller.try_play_action("根本没有这个动作"))

    def test_try_play_action_swallows_character_errors(self):
        self.controller.attach_character(FakeCharacter(raises=True))
        self.assertFalse(self.controller.try_play_action("害羞 2"))


class TestAssetsReload(ControllerTestCase):
    def test_items_can_be_reloaded_after_an_edit(self):
        self.assertEqual(len(self.controller.items()), 4)
        with open(os.path.join(self.assets, "items.json"), "w", encoding="utf-8") as handle:
            json.dump({"items": [{"name": "新的", "kind": "food", "tier": "common"}]},
                      handle, ensure_ascii=False)
        self.controller.reload_assets()
        self.assertEqual([i["name"] for i in self.controller.items()], ["新的"])

    def test_missing_assets_degrade_to_empty(self):
        controller = nc.NurtureController(self.store, {}, assets_dir=os.path.join(self.tmp, "没有"))
        self.addCleanup(controller.deleteLater)
        self.assertEqual(controller.items(), [])
        self.assertEqual(controller.menu_enabled_map()["feed"], False)

    def test_broken_json_degrades_to_empty(self):
        with open(os.path.join(self.assets, "items.json"), "w", encoding="utf-8") as handle:
            handle.write("{ 这不是 JSON")
        self.controller.reload_assets()
        self.assertEqual(self.controller.items(), [])

    def test_items_without_a_name_are_dropped(self):
        with open(os.path.join(self.assets, "items.json"), "w", encoding="utf-8") as handle:
            json.dump({"items": [{"kind": "food"}, {"name": "  "}, {"name": 3},
                                 {"name": "好的", "kind": "food"}]}, handle,
                      ensure_ascii=False)
        self.controller.reload_assets()
        self.assertEqual([i["name"] for i in self.controller.items()], ["好的"])

    def test_store_survives_a_flush_and_reload(self):
        self.stock("奶油面包", 2)
        self.store.set_affection(33)
        self.assertTrue(self.store.flush())
        other = store_mod.NurtureStore(path=self.store.path)
        other.load()
        self.assertEqual(other.item_count("奶油面包"), 2)
        self.assertEqual(other.affection, 33)

    def test_controller_loads_the_existing_store(self):
        """**`NurtureStore.__init__` 不读盘** —— controller 必须自己 `load()`。

        漏了这一步：程序一启动就是空白存档（好感度 0、库存空），
        而且第一次 `save` 会把用户真正的存档覆盖掉。这个坑是写完 controller 才发现的。
        """
        path = os.path.join(self.tmp, "data", "nurture.json")
        first = store_mod.NurtureStore(path=path)
        first.add_item("奶油面包", 3)
        first.set_affection(17)
        self.assertTrue(first.flush())

        second = store_mod.NurtureStore(path=path)
        controller = nc.NurtureController(second, {}, assets_dir=self.assets)
        self.addCleanup(controller.deleteLater)
        self.assertEqual(second.item_count("奶油面包"), 3)
        self.assertEqual(second.affection, 17)


class TestRealAssets(unittest.TestCase):
    """冒烟：拿真的 `assets/nurture/` 跑一遍，只断言"能跑通"，不锁具体数字。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_real_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = store_mod.NurtureStore(
            path=os.path.join(self.tmp, "nurture.json"))
        self.controller = nc.NurtureController(self.store, {"send_cooldown_ms": 0})
        self.addCleanup(self.controller.deleteLater)
        self.character = FakeCharacter(actions=self._real_actions())
        self.controller.attach_character(self.character)

    @staticmethod
    def _real_actions() -> tuple:
        """素材库里真实存在的动作名。素材库不在就用最小集合。"""
        gif_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "素材库", "高木同学Q版gif")
        try:
            from src.gif_registry import GifRegistry
            actions = tuple(GifRegistry(gif_dir).list_actions())
            return actions or ("笑",)
        except Exception:
            return ("笑",)

    def test_real_items_and_levels_load(self):
        self.assertTrue(self.controller.items())
        self.assertTrue(self.controller.levels())

    def test_real_food_can_be_sent(self):
        food = [i for i in self.controller.items() if i.get("kind") == "food"]
        if not food:
            self.skipTest("真素材里没有食物")
        name = food[0]["name"]
        self.store.add_item(name, 2)
        self.assertEqual(self.controller.try_send(name), nc.RESULT_OK)
        self.assertEqual(self.store.item_count(name), 1)

    def test_real_menu_map_is_complete(self):
        mapping = self.controller.menu_enabled_map()
        for key in ("feed", "gift", "checkin", "heart", "chat", "headpat", "settings"):
            self.assertIn(key, mapping)

    def test_real_cap_scenes_exist(self):
        """真素材里 `feed_full` / `gift_capped` / `feed_empty` 都得能抽到句子 —— 否则
        "到上限"这类分支会静默（不崩，但用户什么都看不到）。"""
        for scene in ("feed_full", "gift_capped", "feed_empty", "feed_done"):
            with self.subTest(scene=scene):
                self.assertIsNotNone(self.controller.pick_line(scene), scene)

    def test_every_real_item_resolves_to_an_animation(self):
        """真素材里每个物品都得能选出动画 —— 选不出说明 `anim` 名写错了。"""
        for item in self.controller.items():
            kind = str(item.get("kind", "food"))
            with self.subTest(item=item.get("name")):
                self.assertIsNotNone(self.controller.animation_for(item, kind))


if __name__ == "__main__":
    unittest.main(verbosity=2)
