"""`src/nurture_store.py` 单测 —— 原子写 / 防抖 / 坏档隔离 / 跨天重置。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

只用到 `QCoreApplication`（`QTimer` 需要一个 application 实例），不需要窗口系统。
防抖计时器**不会**在测试里真的触发（不跑事件循环），所以写盘时机是确定可断言的。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from src import nurture_model as nm  # noqa: E402
from src.nurture_store import (  # noqa: E402
    DATA_VERSION,
    NurtureStore,
    default_state,
    list_bad_files,
)

_APP = None


def setUpModule():
    """QTimer 需要一个 QCoreApplication 实例；不跑事件循环，因此不会真的写盘。"""
    global _APP
    _APP = QCoreApplication.instance() or QCoreApplication([])


class StoreTestCase(unittest.TestCase):
    """每个测试一个临时目录，互不干扰。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "data", "nurture.json")
        self.today = date.today()

    # ── 工具 ──

    def make_store(self, **kwargs) -> NurtureStore:
        return NurtureStore(path=self.path, **kwargs)

    def write_raw(self, payload):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def read_raw(self) -> dict:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def raw_state(self, **overrides) -> dict:
        state = default_state(self.today)
        state.update(overrides)
        return state


class TestLoad(StoreTestCase):
    """容错读：文件不存在 / 坏档 / 结构非法 / 缺字段 / 脏值。"""

    def test_missing_file_gives_defaults_without_writing(self):
        """首次运行不落盘 —— 等第一次真实变更再写。"""
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.affection, 0)
        self.assertEqual(store.streak, 0)
        self.assertEqual(store.inventory, {})
        self.assertIsNone(store.last_checkin_date)
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(store.is_dirty)

    def test_corrupt_json_is_quarantined_and_defaults_used(self):
        """01 文档 10.3：解析失败 → 坏档改名，用默认档启动，绝不静默删数据。"""
        self.write_raw("{ this is not json ]]]")
        store = self.make_store()
        store.load(today=self.today)

        bad = list_bad_files(self.path)
        self.assertEqual(len(bad), 1)
        self.assertIn("解析失败", store.last_error)
        self.assertEqual(store.affection, 0)

    def test_non_object_root_is_quarantined(self):
        self.write_raw("[1, 2, 3]")
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(len(list_bad_files(self.path)), 1)
        self.assertIn("根节点", store.last_error)

    def test_missing_fields_are_filled_from_defaults(self):
        """老存档（缺字段）平滑升级，不丢已有数据。"""
        self.write_raw({"affection": 77, "streak": 4})
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.affection, 77)
        self.assertEqual(store.streak, 4)
        self.assertEqual(store.inventory, {})
        self.assertEqual(store.stats("total_fed"), 0)
        self.assertFalse(store.flag("first_run_bonus_granted"))

    def test_version_is_bumped_to_current(self):
        self.write_raw({"version": 0, "affection": 7})
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.snapshot()["version"], DATA_VERSION)

    def test_dirty_values_are_coerced_not_raised(self):
        """存档是用户可手改的 JSON，任何脏值都要降级。"""
        self.write_raw({
            "affection": "abc",
            "streak": -5,
            "last_checkin_date": "nope",
            "inventory": {"饭团": -3, "牛奶": "2", "坏值": "x", "": 5},
            "daily": {"date": self.today.isoformat(), "active_minutes": "12"},
            "stats": {"total_fed": "9", "first_run_date": "bad"},
        })
        store = self.make_store()
        store.load(today=self.today)

        self.assertEqual(store.affection, 0)
        self.assertEqual(store.streak, 0)
        self.assertIsNone(store.last_checkin_date)
        self.assertNotIn("饭团", store.inventory)
        self.assertNotIn("坏值", store.inventory)
        self.assertNotIn("", store.inventory)
        self.assertEqual(store.item_count("牛奶"), 2)
        self.assertEqual(store.daily("active_minutes"), 12)
        self.assertEqual(store.stats("total_fed"), 9)

    def test_inventory_and_used_lines_roundtrip(self):
        self.write_raw(self.raw_state(
            inventory={"奶油面包": 3, "玫瑰花": 1},
            used_lines={"feed_done": ["a", "b"]},
        ))
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.item_count("奶油面包"), 3)
        self.assertEqual(store.item_count("玫瑰花"), 1)
        self.assertEqual(store.used_lines("feed_done"), ["a", "b"])
        self.assertEqual(store.used_lines("不存在的场景"), [])


class TestWrite(StoreTestCase):
    """原子写、防抖、脏标记与信号。"""

    def test_debounce_defers_write_until_flush(self):
        store = self.make_store(debounce_ms=2000)
        store.load(today=self.today)
        store.add_item("饭团", 2)

        self.assertTrue(store.is_dirty)
        self.assertFalse(os.path.exists(self.path))     # 还在防抖窗口内
        self.assertTrue(store.flush())
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(store.is_dirty)
        self.assertEqual(self.read_raw()["inventory"]["饭团"], 2)

    def test_atomic_write_leaves_no_tmp_file(self):
        store = self.make_store()
        store.load(today=self.today)
        store.add_item("牛奶", 1)
        store.flush()
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_flush_without_changes_is_a_noop(self):
        store = self.make_store()
        store.load(today=self.today)
        self.assertFalse(store.flush())

    def test_immediate_save_writes_at_once(self):
        store = self.make_store()
        store.load(today=self.today)
        store.set_checkin(streak=3, when=self.today)
        self.assertTrue(os.path.exists(self.path))       # 关键节点不等防抖
        self.assertEqual(self.read_raw()["streak"], 3)
        self.assertEqual(store.stats("total_checkins"), 1)

    def test_changed_signal_is_emitted(self):
        store = self.make_store()
        store.load(today=self.today)
        seen = []
        store.changed.connect(seen.append)
        store.add_item("饭团", 1)
        self.assertTrue(seen)

    def test_survives_write_failure_without_raising(self):
        """写盘失败不能让桌宠本体崩掉（磁盘满 / 路径被占 / 不可序列化）。"""
        store = self.make_store()
        store.load(today=self.today)
        store.add_item("饭团", 1)

        # 把存档路径做成一个目录 → os.replace 必然失败
        os.makedirs(self.path, exist_ok=True)
        self.assertFalse(store.flush())
        self.assertIn("写入失败", store.last_error)
        self.assertTrue(store.is_dirty)          # 保留脏标记，下次变更再试

    def test_unserializable_flag_value_does_not_break_saving(self):
        store = self.make_store()
        store.load(today=self.today)
        store.set_flag("weird", object())
        self.assertTrue(store.flush())
        self.assertIsInstance(self.read_raw()["flags"]["weird"], str)


class TestInventory(StoreTestCase):
    """库存增删与档位上限（01 文档 2.3 / 4.4）。"""

    def test_add_item_respects_cap(self):
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.add_item("草莓蛋糕", 3, cap=5), 3)
        self.assertEqual(store.add_item("草莓蛋糕", 3, cap=5), 2)     # 只塞得下 2 个
        self.assertEqual(store.add_item("草莓蛋糕", 1, cap=5), 0)     # 满了 → 不发放
        self.assertEqual(store.item_count("草莓蛋糕"), 5)

    def test_add_item_without_cap_is_unlimited(self):
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.add_item("饭团", 99), 99)

    def test_add_item_ignores_bad_input(self):
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.add_item("", 1), 0)
        self.assertEqual(store.add_item("饭团", 0), 0)
        self.assertEqual(store.add_item("饭团", -3), 0)
        self.assertEqual(store.inventory, {})

    def test_take_item_success(self):
        store = self.make_store()
        store.load(today=self.today)
        store.add_item("饭团", 2)
        self.assertTrue(store.take_item("饭团", 1))
        self.assertEqual(store.item_count("饭团"), 1)
        self.assertTrue(store.take_item("饭团", 1))
        self.assertEqual(store.item_count("饭团"), 0)       # 归零后从库存移除

    def test_take_item_failure_changes_nothing(self):
        store = self.make_store()
        store.load(today=self.today)
        store.add_item("饭团", 1)
        self.assertFalse(store.take_item("饭团", 5))
        self.assertFalse(store.take_item("不存在的食物", 1))
        self.assertEqual(store.item_count("饭团"), 1)

    def test_inventory_property_returns_a_copy(self):
        store = self.make_store()
        store.load(today=self.today)
        store.add_item("饭团", 2)
        stolen = store.inventory
        stolen["饭团"] = 999
        self.assertEqual(store.item_count("饭团"), 2)

    def test_has_room(self):
        store = self.make_store()
        store.load(today=self.today)
        store.add_item("复活节彩蛋篮", 5)
        self.assertFalse(store.has_room("复活节彩蛋篮", 5))
        self.assertTrue(store.has_room("复活节彩蛋篮", 6))
        self.assertTrue(store.has_room("复活节彩蛋篮", None))    # None = 不限量


class TestCounters(StoreTestCase):
    """每日计数器、累计统计与标记位。"""

    def test_bump_and_set_daily(self):
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.bump_daily("active_minutes", 30), 30)
        self.assertEqual(store.bump_daily("active_minutes", 15), 45)
        store.set_daily("active_minutes", 3)
        self.assertEqual(store.daily("active_minutes"), 3)
        self.assertEqual(store.daily("不存在的键"), 0)

    def test_daily_counter_never_goes_negative(self):
        store = self.make_store()
        store.load(today=self.today)
        store.bump_daily("key_count", 10)
        self.assertEqual(store.bump_daily("key_count", -50), 0)

    def test_unknown_counter_keys_raise(self):
        store = self.make_store()
        store.load(today=self.today)
        with self.assertRaises(KeyError):
            store.bump_daily("nonsense", 1)
        with self.assertRaises(KeyError):
            store.bump_today("nonsense", 1)
        with self.assertRaises(KeyError):
            store.bump_stats("nonsense", 1)

    def test_bump_today_counters(self):
        store = self.make_store()
        store.load(today=self.today)
        store.bump_today("tease_count_today", 2)
        store.bump_today("gifts_sent_today", 1)
        self.assertEqual(store.tease_count_today, 2)
        self.assertEqual(store.gifts_sent_today, 1)

    def test_stats_are_monotonic(self):
        store = self.make_store()
        store.load(today=self.today)
        store.bump_stats("total_fed", 3)
        self.assertEqual(store.bump_stats("total_fed", -10), 0)

    def test_flags_and_mute_tease(self):
        store = self.make_store()
        store.load(today=self.today)
        self.assertFalse(store.mute_tease_today())
        store.set_mute_tease(True)
        self.assertTrue(store.mute_tease_today())
        store.set_mute_tease(False)
        self.assertFalse(store.mute_tease_today())
        self.assertEqual(store.flag("last_hourly_hour"), -1)     # 默认值可读


class TestDailyReset(StoreTestCase):
    """跨天重置（01 文档 10.3）。"""

    def test_reset_on_new_day(self):
        yesterday = self.today - timedelta(days=1)
        self.write_raw(self.raw_state(
            affection=128,
            streak=5,
            last_checkin_date=yesterday.isoformat(),
            affection_gained_today=6,
            gifts_sent_today=1,
            tease_count_today=2,
            inventory={"奶油面包": 3},
            stats={"total_fed": 37, "total_gifts": 6, "total_checkins": 5,
                   "first_run_date": "2026-08-01"},
            daily={"date": yesterday.isoformat(), "active_minutes": 42,
                   "key_count": 1830, "minutes_rewarded": 1,
                   "keys_rewarded": 0, "hourly_bonus_count": 1},
        ))
        store = self.make_store()
        store.load(today=self.today)

        # 重置的
        self.assertEqual(store.daily("active_minutes"), 0)
        self.assertEqual(store.daily("key_count"), 0)
        self.assertEqual(store.daily("minutes_rewarded"), 0)
        self.assertEqual(store.affection_gained_today, 0)
        self.assertEqual(store.gifts_sent_today, 0)
        self.assertEqual(store.tease_count_today, 0)
        self.assertEqual(store.today(), self.today)

        # 不动的
        self.assertEqual(store.affection, 128)
        self.assertEqual(store.streak, 5)
        self.assertEqual(store.item_count("奶油面包"), 3)
        self.assertEqual(store.stats("total_fed"), 37)
        self.assertEqual(store.last_checkin_date, yesterday)

    def test_no_reset_on_same_day(self):
        self.write_raw(self.raw_state(
            affection_gained_today=6,
            daily={"date": self.today.isoformat(), "active_minutes": 42},
        ))
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(store.affection_gained_today, 6)
        self.assertEqual(store.daily("active_minutes"), 42)
        self.assertFalse(store.is_dirty)

    def test_reset_is_persisted(self):
        yesterday = self.today - timedelta(days=1)
        self.write_raw(self.raw_state(daily={"date": yesterday.isoformat(), "key_count": 500}))
        store = self.make_store()
        store.load(today=self.today)
        self.assertTrue(store.is_dirty)          # 重置本身是一次状态变更
        store.flush()
        self.assertEqual(self.read_raw()["daily"]["key_count"], 0)
        self.assertEqual(self.read_raw()["daily"]["date"], self.today.isoformat())

    def test_mute_tease_recovers_next_day(self):
        """「今天不要捉弄我」只在当天有效，次日自动恢复。"""
        yesterday = self.today - timedelta(days=1)
        self.write_raw(self.raw_state(
            daily={"date": yesterday.isoformat()},
            flags={"mute_tease_date": yesterday.isoformat()},
        ))
        store = self.make_store()
        store.load(today=self.today)
        self.assertFalse(store.mute_tease_today())

    def test_mute_tease_survives_same_day(self):
        self.write_raw(self.raw_state(
            daily={"date": self.today.isoformat()},
            flags={"mute_tease_date": self.today.isoformat()},
        ))
        store = self.make_store()
        store.load(today=self.today)
        self.assertTrue(store.mute_tease_today())


class TestLinesAndMisc(StoreTestCase):
    """台词防重复记录、坏档清理、整体替换。"""

    def test_remember_line_keeps_last_five(self):
        store = self.make_store()
        store.load(today=self.today)
        for i in range(7):
            store.remember_line("feed_done", f"第{i}句")
        kept = store.used_lines("feed_done")
        self.assertEqual(len(kept), 5)
        self.assertEqual(kept[0], "第2句")
        self.assertEqual(kept[-1], "第6句")

    def test_forget_lines(self):
        store = self.make_store()
        store.load(today=self.today)
        store.remember_line("feed_done", "……谢谢。")
        store.forget_lines("feed_done")
        self.assertEqual(store.used_lines("feed_done"), [])

    def test_used_lines_are_trimmed_on_load(self):
        self.write_raw(self.raw_state(
            used_lines={"feed_done": [str(i) for i in range(20)]},
        ))
        store = self.make_store()
        store.load(today=self.today)
        self.assertEqual(len(store.used_lines("feed_done")), 5)

    def test_cleanup_bad_files_keeps_newest(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for stamp in (100, 200, 300):
            with open(f"{self.path}.bad-{stamp}", "w", encoding="utf-8") as f:
                f.write("{}")
        store = self.make_store()
        store.cleanup_bad_files(keep=2)
        remaining = list_bad_files(self.path)
        self.assertEqual(remaining, [f"nurture.json.bad-{s}" for s in (200, 300)])

    def test_replace_state_writes_through(self):
        store = self.make_store()
        store.load(today=self.today)
        store.replace_state({"affection": 250, "inventory": {"玫瑰花": 2}}, today=self.today)
        self.assertEqual(store.affection, 250)
        self.assertEqual(store.item_count("玫瑰花"), 2)
        self.assertTrue(os.path.exists(self.path))

    def test_affection_is_never_negative(self):
        store = self.make_store()
        store.load(today=self.today)
        store.set_affection(-100)
        self.assertEqual(store.affection, 0)

    def test_exported_constants_are_consistent(self):
        """`DAILY_KEYS` / `TODAY_KEYS` 必须与默认档一致，否则读档会丢字段。"""
        state = default_state(self.today)
        for key in ("active_minutes", "key_count", "minutes_rewarded",
                    "keys_rewarded", "hourly_bonus_count"):
            self.assertIn(key, state["daily"])
        for key in ("affection_gained_today", "gifts_sent_today", "tease_count_today"):
            self.assertIn(key, state)
        self.assertEqual(nm.safe_int(state["affection"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
