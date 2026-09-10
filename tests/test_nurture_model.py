"""`src/nurture_model.py` 表驱动单测 —— 阶段 A 的核心交付。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

全部是纯函数，不需要 Qt 事件循环、不需要 QApplication。
数值规则是整个养成系统唯一不能被 UI 掩盖的部分，这里必须全绿才能推进阶段 B。
"""

import os
import random
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nurture_model as nm  # noqa: E402


class TestDates(unittest.TestCase):
    """日期解析与跨天判定 —— 存档是用户可手改的 JSON，脏值必须降级。"""

    def test_parse_date_accepts_iso_string_and_date(self):
        self.assertEqual(nm.parse_date("2026-09-10"), date(2026, 9, 10))
        self.assertEqual(nm.parse_date(date(2026, 9, 10)), date(2026, 9, 10))

    def test_parse_date_rejects_garbage(self):
        for bad in ("", "  ", "garbage", "2026/09/10", None, {}, [], 20260910):
            with self.subTest(bad=bad):
                self.assertIsNone(nm.parse_date(bad))

    def test_to_date_str_roundtrip_and_bad_value(self):
        self.assertEqual(nm.to_date_str(date(2026, 1, 2)), "2026-01-02")
        self.assertEqual(nm.to_date_str("nonsense"), "")

    def test_is_new_day(self):
        cases = [
            (None, date(2026, 9, 10), True),                     # 从未签到
            (date(2026, 9, 9), date(2026, 9, 10), True),
            (date(2026, 9, 10), date(2026, 9, 10), False),       # 同一天
            (date(2026, 9, 11), date(2026, 9, 10), True),        # 时钟回退也算"不是同一天"
        ]
        for last, today, expected in cases:
            with self.subTest(last=last, today=today):
                self.assertIs(nm.is_new_day(today, last), expected)

    def test_daily_reset_needed(self):
        cases = [
            ("2026-09-10", date(2026, 9, 10), False),
            ("2026-09-09", date(2026, 9, 10), True),
            ("", date(2026, 9, 10), True),                       # 坏值 → 保守重置
            (None, date(2026, 9, 10), True),
        ]
        for stored, today, expected in cases:
            with self.subTest(stored=stored):
                self.assertIs(nm.daily_reset_needed(stored, today), expected)

    def test_safe_int_never_raises(self):
        cases = [("abc", 0), (None, 0), ("7", 7), (3.9, 3), (True, 1), ({}, 0), (-2, -2)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(nm.safe_int(value), expected)


class TestStreak(unittest.TestCase):
    """连签规则（01 文档 4.1 / 4.4）。"""

    def test_checkin_status_all_branches(self):
        cases = [
            (None, date(2026, 9, 10), nm.STATUS_FIRST),
            (date(2026, 9, 9), date(2026, 9, 10), nm.STATUS_NEW_DAY),
            (date(2026, 9, 10), date(2026, 9, 10), nm.STATUS_SAME_DAY),
            (date(2026, 9, 8), date(2026, 9, 10), nm.STATUS_GAP),
            (date(2026, 9, 20), date(2026, 9, 10), nm.STATUS_CLOCK_BACK),
        ]
        for last, today, expected in cases:
            with self.subTest(last=last, expected=expected):
                self.assertEqual(nm.checkin_status(last, today), expected)

    def test_can_checkin(self):
        self.assertTrue(nm.can_checkin(None, date(2026, 9, 10)))            # 首签
        self.assertTrue(nm.can_checkin(date(2026, 9, 9), date(2026, 9, 10)))  # 连签
        self.assertTrue(nm.can_checkin(date(2026, 9, 1), date(2026, 9, 10)))  # 断签重来
        self.assertFalse(nm.can_checkin(date(2026, 9, 10), date(2026, 9, 10)))  # 今日已签
        self.assertFalse(nm.can_checkin(date(2026, 9, 20), date(2026, 9, 10)))  # 时钟回退

    def test_next_streak_first_checkin(self):
        self.assertEqual(nm.next_streak(None, date(2026, 9, 10), 0), (1, False))

    def test_next_streak_increments(self):
        self.assertEqual(nm.next_streak(date(2026, 9, 9), date(2026, 9, 10), 4), (5, False))

    def test_next_streak_same_day_unchanged(self):
        self.assertEqual(nm.next_streak(date(2026, 9, 10), date(2026, 9, 10), 5), (5, False))

    def test_next_streak_gap_resets(self):
        self.assertEqual(nm.next_streak(date(2026, 9, 7), date(2026, 9, 10), 9), (1, True))

    def test_next_streak_clock_back_keeps_streak(self):
        """时间回退：不发放、不重置 —— 连签原样保留。"""
        self.assertEqual(nm.next_streak(date(2026, 9, 20), date(2026, 9, 10), 9), (9, False))

    def test_next_streak_tolerates_dirty_prev(self):
        for bad in ("abc", None, -5):
            with self.subTest(bad=bad):
                streak, reset = nm.next_streak(None, date(2026, 9, 10), bad)
                self.assertEqual(streak, 1)
                self.assertFalse(reset)


class TestCheckinReward(unittest.TestCase):
    """签到产出与里程碑边界（01 文档 4.1）。"""

    def test_first_day_gets_only_base_plus_intro_affection(self):
        reward = nm.checkin_reward(1)
        self.assertEqual(reward["tiers"], {nm.TIER_COMMON: 2})
        self.assertEqual(reward["affection"], 2)          # first_affection
        self.assertIsNone(reward["milestone"])

    def test_plain_day_has_no_affection(self):
        reward = nm.checkin_reward(2)
        self.assertEqual(reward["tiers"], {nm.TIER_COMMON: 2})
        self.assertEqual(reward["affection"], 0)
        self.assertIsNone(reward["milestone"])

    def test_milestones(self):
        cases = [
            (3, {nm.TIER_COMMON: 2, nm.TIER_RARE: 1}, 5, 3),
            (7, {nm.TIER_COMMON: 2, nm.TIER_PRECIOUS: 1}, 10, 7),
            (14, {nm.TIER_COMMON: 2, nm.TIER_PRECIOUS: 1}, 20, 14),
            (30, {nm.TIER_COMMON: 2, nm.TIER_PRECIOUS: 1}, 50, 30),
        ]
        for streak, tiers, affection, milestone in cases:
            with self.subTest(streak=streak):
                reward = nm.checkin_reward(streak)
                self.assertEqual(reward["tiers"], tiers)
                self.assertEqual(reward["affection"], affection)
                self.assertEqual(reward["milestone"], milestone)

    def test_milestone_edges_are_exact(self):
        """里程碑是"第 N 天那一次"，前后一天都不该给。"""
        for streak in (4, 6, 13, 15, 29, 31, 100):
            with self.subTest(streak=streak):
                self.assertIsNone(nm.checkin_reward(streak)["milestone"])

    def test_custom_table_is_honored(self):
        table = {
            "base_items": {"rare": 1},
            "first_affection": 99,
            "milestones": {2: {"items": {"precious": 3}, "affection": 7}},
        }
        reward = nm.checkin_reward(1, table)
        self.assertEqual(reward["tiers"], {nm.TIER_RARE: 1})
        self.assertEqual(reward["affection"], 99)

        # 里程碑键在 JSON 里是字符串、代码里可能是 int，两种都要认
        reward = nm.checkin_reward(2, {"milestones": {"2": {"items": {"precious": 3}, "affection": 7}}})
        self.assertEqual(reward["tiers"], {nm.TIER_PRECIOUS: 3})
        self.assertEqual(reward["affection"], 7)
        self.assertEqual(reward["milestone"], 2)

    def test_broken_table_falls_back_to_default(self):
        for bad in (None, "oops", 42, []):
            with self.subTest(bad=bad):
                reward = nm.checkin_reward(1, bad)
                self.assertEqual(reward["tiers"], {nm.TIER_COMMON: 2})


class TestResolveTiers(unittest.TestCase):
    """档位 → 具体物品名。"""

    POOL = {"common": ["饭团", "牛奶"], "rare": ["巧克力"], "precious": []}

    def test_resolves_to_item_names(self):
        result = nm.resolve_tiers({"rare": 1}, self.POOL, random.Random(0))
        self.assertEqual(result, {"巧克力": 1})

    def test_missing_tier_is_skipped_without_error(self):
        result = nm.resolve_tiers({"precious": 2}, self.POOL, random.Random(0))
        self.assertEqual(result, {})                      # 该档位没有候选项 → 静默跳过

    def test_count_larger_than_pool_repeats(self):
        result = nm.resolve_tiers({"rare": 3}, self.POOL, random.Random(0))
        self.assertEqual(result, {"巧克力": 3})

    def test_zero_and_negative_counts_ignored(self):
        self.assertEqual(nm.resolve_tiers({"common": 0, "rare": -1}, self.POOL), {})

    def test_broken_input_returns_empty(self):
        for bad in (None, "oops", 5):
            with self.subTest(bad=bad):
                self.assertEqual(nm.resolve_tiers(bad, self.POOL), {})


class TestAffection(unittest.TestCase):
    """好感度入账与每日上限截断（01 文档 2.2）。"""

    def test_normal_gain(self):
        self.assertEqual(nm.apply_affection(100, 4, 6, 20), (104, 4))

    def test_truncated_at_daily_cap(self):
        self.assertEqual(nm.apply_affection(100, 4, 18, 20), (102, 2))

    def test_already_capped_returns_zero_gain(self):
        """已满时仍返回"可送出"：好感度不动，但调用方照常播动画/台词。"""
        self.assertEqual(nm.apply_affection(128, 4, 20, 20), (128, 0))
        self.assertEqual(nm.apply_affection(128, 4, 25, 20), (128, 0))

    def test_zero_cap_blocks_everything(self):
        self.assertEqual(nm.apply_affection(5, 4, 0, 0), (5, 0))

    def test_negative_gain_is_eaten(self):
        """好感度只增不减。"""
        self.assertEqual(nm.apply_affection(5, -3, 0, 20), (5, 0))

    def test_dirty_inputs_are_coerced(self):
        self.assertEqual(nm.apply_affection("10", "2", "abc", "20"), (12, 2))

    def test_tier_affection_gain(self):
        self.assertEqual(nm.tier_affection_gain(nm.TIER_COMMON), 1)
        self.assertEqual(nm.tier_affection_gain(nm.TIER_RARE), 2)
        self.assertEqual(nm.tier_affection_gain(nm.TIER_PRECIOUS), 4)
        self.assertEqual(nm.tier_affection_gain("unknown"), 1)   # 未知档位按最低档

    def test_affection_ratio_is_clamped(self):
        self.assertEqual(nm.affection_ratio(500), 0.5)
        self.assertEqual(nm.affection_ratio(-10), 0.0)
        self.assertEqual(nm.affection_ratio(99999), 1.0)
        self.assertEqual(nm.affection_ratio(10, 0), 0.0)         # 软上限为 0 → 不除零


class TestLevels(unittest.TestCase):
    """等级与解锁（01 文档 2.2 的阈值表）。"""

    def test_level_of_boundaries(self):
        cases = [
            (0, 0), (49, 0), (50, 1), (119, 1), (120, 2),
            (249, 2), (250, 3), (449, 3), (450, 4), (699, 4),
            (700, 5), (99999, 5),
        ]
        for affection, expected in cases:
            with self.subTest(affection=affection):
                self.assertEqual(nm.level_of(affection), expected)

    def test_level_info(self):
        info = nm.level_info(120)
        self.assertEqual(info["index"], 2)
        self.assertEqual(info["title"], "朋友")
        self.assertEqual(info["threshold"], 120)
        self.assertEqual(info["next_threshold"], 250)
        self.assertEqual(info["next_title"], "要好")
        self.assertFalse(info["is_max"])

    def test_level_info_at_top(self):
        info = nm.level_info(99999)
        self.assertTrue(info["is_max"])
        self.assertIsNone(info["next_threshold"])

    def test_level_of_with_custom_and_unsorted_table(self):
        levels = [{"threshold": 200, "title": "B"}, {"threshold": 0, "title": "A"}]
        self.assertEqual(nm.level_of(0, levels), 0)
        self.assertEqual(nm.level_of(150, levels), 0)
        self.assertEqual(nm.level_of(200, levels), 1)

    def test_level_of_with_broken_table_uses_builtin_fallback(self):
        for bad in (None, [], "oops", [{"title": "no threshold"}]):
            with self.subTest(bad=bad):
                self.assertEqual(nm.level_of(700, bad), 5)      # 兜底表生效

    def test_unlocked_features_are_cumulative(self):
        self.assertEqual(nm.unlocked_features(0), set())
        self.assertEqual(nm.unlocked_features(2), {"idle_random", "small_talk"})
        self.assertEqual(nm.unlocked_features(3), {"idle_random", "small_talk",
                                                  "tone_proud", "event_lines"})
        self.assertIn("late_talk", nm.unlocked_features(5))

    def test_unlocked_features_clamps_index(self):
        self.assertEqual(nm.unlocked_features(99), nm.unlocked_features(5))
        self.assertEqual(nm.unlocked_features(-3), set())


class TestResolveAnim(unittest.TestCase):
    """四级兜底链（01 文档 3.3）—— 素材库没有"吃东西"动画，这一条是硬需求。"""

    @staticmethod
    def _has(*names):
        return lambda action: action in names

    def test_level1_item_anim_exists(self):
        item = {"anim": "蛋糕"}
        self.assertEqual(nm.resolve_anim(item, nm.KIND_FOOD, self._has("蛋糕", "笑")), "蛋糕")

    def test_level2_falls_back_to_kind_default(self):
        item = {"anim": "不存在的动作"}
        self.assertEqual(nm.resolve_anim(item, nm.KIND_FOOD, self._has("笑")), "笑")
        self.assertEqual(nm.resolve_anim(item, nm.KIND_GIFT, self._has("点赞")), "点赞")

    def test_level3_falls_back_to_global(self):
        item = {"anim": "不存在的动作"}
        self.assertEqual(nm.resolve_anim(item, nm.KIND_FOOD, self._has("害羞 2")), "害羞 2")

    def test_level4_returns_none_when_everything_missing(self):
        """全缺 → 不播动画，只出对话气泡（绝不可崩溃、绝不可黑屏）。"""
        self.assertIsNone(nm.resolve_anim({"anim": "没有"}, nm.KIND_FOOD, self._has()))

    def test_missing_anim_key_still_falls_back(self):
        self.assertEqual(nm.resolve_anim({}, nm.KIND_GIFT, self._has("点赞")), "点赞")
        self.assertIsNone(nm.resolve_anim(None, nm.KIND_GIFT, self._has()))

    def test_registry_failure_degrades_instead_of_raising(self):
        def boom(action):
            raise OSError("素材库读不了")

        self.assertIsNone(nm.resolve_anim({"anim": "蛋糕"}, nm.KIND_FOOD, boom))

    def test_empty_and_non_string_anim_are_ignored(self):
        for bad in ("", None, 0, [], {}):
            with self.subTest(bad=bad):
                self.assertEqual(
                    nm.resolve_anim({"anim": bad}, nm.KIND_FOOD, self._has("笑")), "笑")


class TestConvertToItems(unittest.TestCase):
    """陪伴时长 / 打字量兑换（01 文档 4.2）。"""

    def test_normal_conversion(self):
        self.assertEqual(nm.convert_to_items(120, 60, 3, 0), (2, 0))     # 2 小时 → 2 个
        self.assertEqual(nm.convert_to_items(119, 60, 3, 0), (1, 59))    # 零头保留

    def test_daily_cap_truncates(self):
        self.assertEqual(nm.convert_to_items(6000, 2000, 2, 0), (2, 0))
        self.assertEqual(nm.convert_to_items(6000, 2000, 2, 1), (1, 0))

    def test_progress_does_not_hoard_when_capped(self):
        """达到上限后不发放，剩余只保留不足一份的零头（避免次日爆一堆）。"""
        self.assertEqual(nm.convert_to_items(5000, 2000, 2, 2), (0, 1000))

    def test_already_rewarded_progress_is_not_paid_twice(self):
        """已兑换过的进度不能再兑一次 —— 心跳是每分钟跑一次的。

        进度 2 份、已兑 1 个、上限 3 → 只能再发 1 个（阶段 F 抓到的真 bug：
        原先只把 `already` 用在"还剩几个额度"上，同一份进度每次心跳都能再兑一个，
        表现是"挂着不动，食物自己一直涨"）。
        """
        self.assertEqual(nm.convert_to_items(120, 60, 3, 1), (1, 0))
        self.assertEqual(nm.convert_to_items(120, 60, 3, 2), (0, 0))
        self.assertEqual(nm.convert_to_items(60, 60, 3, 1), (0, 0))
        self.assertEqual(nm.convert_to_items(180, 60, 5, 1), (2, 0))

    def test_zero_per_guards_against_division_by_zero(self):
        self.assertEqual(nm.convert_to_items(999, 0, 3, 0), (0, 999))
        self.assertEqual(nm.convert_to_items(999, -60, 3, 0), (0, 999))

    def test_below_one_unit(self):
        self.assertEqual(nm.convert_to_items(59, 60, 3, 0), (0, 59))
        self.assertEqual(nm.convert_to_items(0, 60, 3, 0), (0, 0))


class TestTeaseGuard(unittest.TestCase):
    """01 文档 7.1 的七条硬禁区 —— 这是"不评判"验收的可测部分。"""

    def test_in_night_boundaries(self):
        cases = [(23, True), (0, True), (5, True), (6, False), (22, False), (12, False)]
        for hour, expected in cases:
            with self.subTest(hour=hour):
                self.assertIs(nm.in_night(hour), expected)

    def test_in_night_custom_range_and_zero_length(self):
        self.assertTrue(nm.in_night(3, 1, 5))
        self.assertFalse(nm.in_night(23, 1, 5))
        self.assertFalse(nm.in_night(3, 5, 5))          # 零长度 → 视为无深夜时段

    def test_non_tease_tones_always_allowed(self):
        for tone in (nm.TONE_GENTLE, nm.TONE_PROUD, "unknown", "", None):
            with self.subTest(tone=tone):
                self.assertTrue(nm.is_tease_allowed(tone, 3, typing_rate=500,
                                                    continuous_min=500, tease_today=99))

    def test_tease_allowed_in_normal_conditions(self):
        self.assertTrue(nm.is_tease_allowed(nm.TONE_TEASE, 12))

    def test_tease_blocked_at_night(self):
        for hour in (23, 0, 3, 5):
            with self.subTest(hour=hour):
                self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, hour))

    def test_tease_blocked_when_typing_fast(self):
        self.assertTrue(nm.is_tease_allowed(nm.TONE_TEASE, 12, typing_rate=120))
        self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, 12, typing_rate=121))

    def test_tease_blocked_when_working_long(self):
        self.assertTrue(nm.is_tease_allowed(nm.TONE_TEASE, 12, continuous_min=90))
        self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, 12, continuous_min=91))

    def test_tease_blocked_when_quota_exhausted(self):
        self.assertTrue(nm.is_tease_allowed(nm.TONE_TEASE, 12, tease_today=5, tease_cap=6))
        self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, 12, tease_today=6, tease_cap=6))

    def test_tease_blocked_by_mute_switch(self):
        """「今天不要捉弄我」是硬开关，用户也绕不过。"""
        self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, 12, mute_today=True))

    def test_tease_blocked_when_frequency_off(self):
        """捉弄频率设为「关闭」→ 24 小时内 0 条（验收标准 12.2）。"""
        self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, 12, tease_probability=0.0))
        self.assertFalse(nm.is_tease_allowed(nm.TONE_TEASE, 12, tease_probability="bad"))

    def test_tease_probability_of(self):
        self.assertEqual(nm.tease_probability_of("off"), 0.0)
        self.assertEqual(nm.tease_probability_of("sometimes"), 0.15)
        self.assertEqual(nm.tease_probability_of("normal"), 0.35)
        self.assertEqual(nm.tease_probability_of("胡说"), 0.15)     # 未知值走默认档
        self.assertEqual(nm.tease_probability_of(None), 0.15)

    def test_focus_mode(self):
        self.assertFalse(nm.is_focus_mode(0, 0))
        self.assertTrue(nm.is_focus_mode(121, 0))
        self.assertTrue(nm.is_focus_mode(0, 91))
        self.assertTrue(nm.is_focus_mode(0, 0, "meeting"))
        self.assertTrue(nm.is_focus_mode(0, 0, None, fullscreen=True))
        self.assertFalse(nm.is_focus_mode(0, 0, "browser"))

    def test_proactive_allowed(self):
        self.assertTrue(nm.is_proactive_allowed("code"))
        self.assertTrue(nm.is_proactive_allowed(None))
        self.assertFalse(nm.is_proactive_allowed("game"))
        self.assertFalse(nm.is_proactive_allowed("meeting"))
        self.assertFalse(nm.is_proactive_allowed("code", fullscreen=True))


class TestInventoryAndTime(unittest.TestCase):
    """库存上限与时段场景。"""

    def test_tier_cap(self):
        self.assertEqual(nm.tier_cap(nm.TIER_COMMON), 20)
        self.assertEqual(nm.tier_cap(nm.TIER_RARE), 10)
        self.assertEqual(nm.tier_cap(nm.TIER_PRECIOUS), 5)
        self.assertEqual(nm.tier_cap("unknown"), 20)
        self.assertEqual(nm.tier_cap(nm.TIER_RARE, {"rare": 3}), 3)

    def test_can_accept(self):
        self.assertTrue(nm.can_accept(nm.TIER_PRECIOUS, 4))
        self.assertFalse(nm.can_accept(nm.TIER_PRECIOUS, 5))
        self.assertFalse(nm.can_accept(nm.TIER_PRECIOUS, 99))

    def test_time_scene_of(self):
        cases = [(7, "time_morning"), (12, "time_noon"), (23, "time_night"),
                 (3, "time_late"), (15, None), (10, None)]
        for hour, expected in cases:
            with self.subTest(hour=hour):
                self.assertEqual(nm.time_scene_of(hour), expected)

    def test_greeting_for_hour_never_empty(self):
        for hour in range(24):
            with self.subTest(hour=hour):
                self.assertTrue(nm.greeting_for_hour(hour))


if __name__ == "__main__":
    unittest.main(verbosity=2)
