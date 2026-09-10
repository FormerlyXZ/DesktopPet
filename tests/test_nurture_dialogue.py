"""`src/dialogue.py` 单测 —— 权重抽取 / 防重复 / 占位符 / 语气禁区 / 坏文件降级。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

`dialogue.py` 刻意不依赖 PySide6，所以这里除"接真实 NurtureStore"那一组外都不需要 Qt。

对应 04 文档阶段 B 的验证清单：
  * 不存在文件返回 `None` 不抛异常
  * 100 次抽取分布符合权重
  * 连续抽取不重复最近 5 条
  * `tease` 在禁区条件下被整组剔除
  * 占位符：`ctx` 缺键时原文保留且不报错
"""

import json
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import dialogue as dlg  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIALOGUES = os.path.join(PROJECT_DIR, "assets", "nurture", "dialogues")


class FakeStore:
    """只实现 `dialogue` 用到的三个方法的鸭子类型存档。"""

    def __init__(self, keep=5):
        self.keep = keep
        self.used: dict[str, list[str]] = {}
        self.forgotten: list[str] = []
        self.boom = False

    def used_lines(self, scene):
        if self.boom:
            raise OSError("存档坏了")
        return list(self.used.get(str(scene), []))

    def remember_line(self, scene, text):
        if self.boom:
            raise OSError("存档坏了")
        lines = self.used.setdefault(str(scene), [])
        lines.append(str(text))
        del lines[:-self.keep]

    def forget_lines(self, scene):
        self.forgotten.append(str(scene))
        self.used.pop(str(scene), None)


class DialogueTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_dlg_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write_scene(self, scene_id, payload):
        path = os.path.join(self.tmp, f"{scene_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload, f, ensure_ascii=False)
        return path

    def make_lib(self, store=None, seed=1234):
        lib = dlg.DialogueLibrary(self.tmp, store=store, rng=random.Random(seed))
        lib.reload()
        return lib


class TestFormatLine(unittest.TestCase):
    """占位符替换：缺键原样保留、坏模板不抛异常。"""

    def test_known_key_is_replaced(self):
        self.assertEqual(dlg.format_line("连签 {streak} 天了。", {"streak": 5}),
                         "连签 5 天了。")

    def test_missing_key_is_left_as_is(self):
        self.assertEqual(dlg.format_line("连签 {streak} 天了。", {}),
                         "连签 {streak} 天了。")
        self.assertEqual(dlg.format_line("连签 {streak} 天了。", None),
                         "连签 {streak} 天了。")

    def test_unknown_key_is_left_as_is(self):
        self.assertEqual(dlg.format_line("{没有这个键}", {"streak": 1}), "{没有这个键}")

    def test_broken_template_returns_original(self):
        for broken in ("落单的左括号 {", "落单的右括号 }", "{streak"):
            with self.subTest(template=broken):
                self.assertEqual(dlg.format_line(broken, {"streak": 1}), broken)

    def test_text_without_placeholder_passes_through(self):
        self.assertEqual(dlg.format_line("我在呢。", {"streak": 1}), "我在呢。")

    def test_multiple_placeholders(self):
        out = dlg.format_line("{level}，第 {streak} 天。", {"level": "同桌", "streak": 3})
        self.assertEqual(out, "同桌，第 3 天。")

    def test_placeholders_in(self):
        self.assertEqual(dlg.placeholders_in("连签 {streak} 天，{hour} 点"),
                         {"streak", "hour"})
        self.assertEqual(dlg.placeholders_in("没有占位符"), set())
        self.assertEqual(dlg.placeholders_in("坏模板 {"), set())

    def test_placeholder_whitelist_matches_defaults(self):
        for scene, line in dlg.DialogueLibrary(REAL_DIALOGUES).all_lines():
            with self.subTest(scene=scene, text=line["text"]):
                for key in dlg.placeholders_in(line["text"]):
                    self.assertIn(key, dlg.PLACEHOLDER_KEYS)


class TestLoading(DialogueTestCase):
    """加载与降级：目录不存在、文件乱码、根节点非法、空池。"""

    def test_missing_directory_does_not_raise(self):
        lib = dlg.DialogueLibrary(os.path.join(self.tmp, "does_not_exist"))
        lib.reload()
        self.assertEqual(lib.scenes(), [])
        self.assertIsNone(lib.pick("绝对不存在的场景"))
        self.assertIsNone(lib.pick_line("绝对不存在的场景"))

    def test_unknown_scene_falls_back_to_builtin(self):
        """目录不存在时，核心场景仍能说出代码内兜底台词（不是哑巴）。"""
        lib = dlg.DialogueLibrary(os.path.join(self.tmp, "does_not_exist"))
        lib.reload()
        self.assertTrue(lib.has_scene("idle_random"))
        builtin = [l["text"] for l in dlg.DEFAULT_SCENES["idle_random"]["lines"]]
        self.assertIn(lib.pick("idle_random"), builtin)

    def test_totally_unknown_scene_returns_none(self):
        lib = self.make_lib()
        self.assertIsNone(lib.pick("绝对不存在的场景"))
        self.assertIsNone(lib.pick_line("绝对不存在的场景"))

    def test_corrupt_file_is_recorded_and_falls_back(self):
        self.write_scene("idle_random", "{ 这不是 json ]]]")
        lib = self.make_lib()
        self.assertIn("idle_random.json", lib.errors)
        # 坏文件不该让整个场景哑掉 —— 走代码内兜底
        self.assertTrue(lib.has_scene("idle_random"))
        self.assertIsNotNone(lib.pick("idle_random"))

    def test_non_object_root_is_recorded(self):
        self.write_scene("idle_random", "[1, 2, 3]")
        lib = self.make_lib()
        self.assertIn("根节点", lib.errors.get("idle_random.json", ""))
        self.assertIsNotNone(lib.pick("idle_random"))

    def test_one_bad_file_does_not_break_others(self):
        self.write_scene("idle_random", "坏掉的内容")
        self.write_scene("feed_done", {"scene": "feed_done", "lines": [{"text": "……谢谢。"}]})
        lib = self.make_lib()
        self.assertEqual(lib.pick("feed_done"), "……谢谢。")

    def test_empty_pool_is_legal_and_silent(self):
        """03 规范 9：允许沉默 —— 空池不是错误，只是不说话。"""
        self.write_scene("idle_random", {"scene": "idle_random", "lines": []})
        lib = self.make_lib()
        self.assertIsNone(lib.pick("idle_random"))
        self.assertNotIn("idle_random.json", lib.errors)

    def test_scene_meta_and_cooldowns(self):
        self.write_scene("idle_random", {"cooldown_sec": 360, "min_gap_sec": 12,
                                        "lines": [{"text": "我在呢。"}]})
        lib = self.make_lib()
        meta = lib.scene_meta("idle_random")
        self.assertEqual(meta["cooldown_sec"], 360)
        self.assertEqual(meta["min_gap_sec"], 12)
        self.assertIn("idle_random", lib.cooldowns())
        self.assertEqual(lib.cooldowns()["idle_random"], (360, 12))

    def test_line_normalization(self):
        """垃圾字段必须被捏成合法值，而不是让整条台词失效。"""
        self.write_scene("t", {"lines": [
            "纯字符串写法",
            {"text": "权重是字符串", "weight": "3"},
            {"text": "权重是垃圾", "weight": "abc"},
            {"text": "等级是负数", "min_level": -5},
            {"text": "  "},                      # 空白文本 → 丢掉
            {"weight": 2},                       # 没有 text → 丢掉
            12345,                               # 非法条目 → 丢掉
        ]})
        lib = self.make_lib()
        lines = lib.all_lines()
        texts = [line["text"] for scene, line in lines if scene == "t"]
        self.assertIn("纯字符串写法", texts)
        self.assertIn("权重是字符串", texts)
        self.assertIn("权重是垃圾", texts)
        self.assertNotIn("  ", texts)
        self.assertEqual(len(texts), 4)
        for _, line in lines:
            self.assertGreaterEqual(line["weight"], 1)
            self.assertGreaterEqual(line["min_level"], 0)

    def test_tone_is_normalized_to_scene_tone(self):
        self.write_scene("t", {"tone": "proud", "lines": [{"text": "没有 tone"}]})
        lib = self.make_lib()
        line = [ln for scene, ln in lib.all_lines() if scene == "t"][0]
        self.assertEqual(line["tone"], "proud")

    def test_invalid_scene_tone_falls_back_to_gentle(self):
        self.write_scene("t", {"tone": "胡说", "lines": [{"text": "x"}]})
        lib = self.make_lib()
        self.assertEqual(lib.scene_meta("t")["tone"], "gentle")


class TestSelection(DialogueTestCase):
    """抽取：权重分布、min_level 过滤、tone 回传。"""

    def test_weighted_distribution(self):
        """权重 1 : 9 → 2000 次抽取的占比应该贴近 10% / 90%。"""
        self.write_scene("t", {"lines": [
            {"text": "少见", "weight": 1},
            {"text": "常见", "weight": 9},
        ]})
        lib = self.make_lib(seed=7)
        counts = {"少见": 0, "常见": 0}
        for _ in range(2000):
            counts[lib.pick("t")] += 1
        ratio = counts["少见"] / 2000
        self.assertGreater(ratio, 0.07, counts)
        self.assertLess(ratio, 0.13, counts)

    def test_single_line_scene_always_same(self):
        self.write_scene("t", {"lines": [{"text": "只有这一句。"}]})
        lib = self.make_lib()
        for _ in range(5):
            self.assertEqual(lib.pick("t"), "只有这一句。")

    def test_min_level_filters_lines(self):
        """`min_level` 写的是**好感度阈值**（与 levels.json 同刻度），不是等级下标。"""
        self.write_scene("t", {"lines": [
            {"text": "随时可说。"},
            {"text": "要高等级。", "min_level": 250},
        ]})
        lib = self.make_lib(seed=3)
        low = {lib.pick("t", affection=0) for _ in range(60)}
        self.assertEqual(low, {"随时可说。"})
        mid = {lib.pick("t", affection=249) for _ in range(60)}
        self.assertEqual(mid, {"随时可说。"})
        high = {lib.pick("t", affection=250) for _ in range(60)}
        self.assertEqual(high, {"随时可说。", "要高等级。"})

    def test_min_level_tolerates_dirty_affection(self):
        self.write_scene("t", {"lines": [{"text": "随时可说。"}]})
        lib = self.make_lib()
        for bad in (None, "abc", -5, ""):
            with self.subTest(bad=bad):
                self.assertEqual(lib.pick("t", affection=bad), "随时可说。")

    def test_returns_tone_of_chosen_line(self):
        self.write_scene("t", {"lines": [{"text": "小得意。", "tone": "proud"}]})
        lib = self.make_lib()
        self.assertEqual(lib.pick_line("t"), {"text": "小得意。", "tone": "proud"})

    def test_placeholders_are_filled_with_ctx(self):
        self.write_scene("t", {"lines": [{"text": "连签 {streak} 天了。"}]})
        lib = self.make_lib()
        self.assertEqual(lib.pick("t", {"streak": 5}), "连签 5 天了。")
        self.assertEqual(lib.pick("t"), "连签 {streak} 天了。")

    def test_pick_returns_none_never_raises_for_bad_dir(self):
        lib = dlg.DialogueLibrary(None)          # 用默认目录
        self.assertIsNone(lib.pick("不存在的场景"))
        self.assertIsInstance(lib.errors, dict)


class TestTeaseGuard(DialogueTestCase):
    """`tease` 在禁区条件下必须被**整组**剔除（01 文档 7.1 / 验收 12.2）。"""

    def test_pure_tease_scene_returns_none_when_blocked(self):
        self.write_scene("t", {"lines": [
            {"text": "捉弄一。", "tone": "tease"},
            {"text": "捉弄二。", "tone": "tease"},
        ]})
        lib = self.make_lib()
        self.assertIsNotNone(lib.pick_line("t", tease_allowed=True))
        self.assertIsNone(lib.pick_line("t", tease_allowed=False))

    def test_mixed_scene_never_yields_tease_when_blocked(self):
        self.write_scene("t", {"lines": [
            {"text": "温柔的一句。", "weight": 1},
            {"text": "调皮的一句。", "weight": 20, "tone": "tease"},
        ]})
        lib = self.make_lib(seed=11)
        for _ in range(300):
            self.assertEqual(lib.pick("t", tease_allowed=False), "温柔的一句。")

    def test_tease_allowed_does_yield_tease(self):
        self.write_scene("t", {"lines": [{"text": "调皮的一句。", "tone": "tease"}]})
        lib = self.make_lib()
        self.assertEqual(lib.pick_line("t", tease_allowed=True)["tone"], "tease")

    def test_real_assets_have_no_tease_lines_yet(self):
        """首批 6 个场景按设计全是 gentle/proud，一条 tease 都不该有。"""
        lib = dlg.DialogueLibrary(REAL_DIALOGUES)
        for scene, line in lib.all_lines():
            with self.subTest(scene=scene, text=line["text"]):
                self.assertNotEqual(line["tone"], "tease")


class TestAntiRepeat(DialogueTestCase):
    """防重复：最近 5 条不重复；全被用光时清空重来。"""

    LINES = [{"text": f"第{i}句。"} for i in range(5)]

    def test_no_repeat_within_five_draws(self):
        self.write_scene("t", {"lines": self.LINES})
        store = FakeStore()
        lib = self.make_lib(store=store, seed=5)
        drawn = [lib.pick("t") for _ in range(5)]
        self.assertEqual(len(set(drawn)), 5, drawn)

    def test_forgets_and_restarts_when_all_used(self):
        self.write_scene("t", {"lines": self.LINES})
        store = FakeStore()
        lib = self.make_lib(store=store, seed=5)
        for _ in range(5):
            lib.pick("t")
        sixth = lib.pick("t")
        self.assertIsNotNone(sixth)
        self.assertEqual(store.forgotten, ["t"])

    def test_forced_used_lines_are_skipped(self):
        """已用 4 条时，第 5 条必然抽到唯一没说过的那句。"""
        self.write_scene("t", {"lines": self.LINES})
        store = FakeStore()
        store.used["t"] = ["第0句。", "第1句。", "第2句。", "第3句。"]
        lib = self.make_lib(store=store, seed=5)
        self.assertEqual(lib.pick("t"), "第4句。")

    def test_restarts_clean_after_all_used(self):
        """5 条全用光后清空重来，接下来 5 次又是 5 句不重复。"""
        self.write_scene("t", {"lines": self.LINES})
        store = FakeStore()
        lib = self.make_lib(store=store, seed=5)
        for _ in range(5):
            lib.pick("t")
        cycle = [lib.pick("t") for _ in range(5)]
        self.assertEqual(len(set(cycle)), 5, cycle)
        self.assertEqual(store.forgotten, ["t"])

    def test_line_is_remembered(self):
        self.write_scene("t", {"lines": [{"text": "……谢谢。"}]})
        store = FakeStore()
        lib = self.make_lib(store=store)
        lib.pick("t")
        self.assertEqual(store.used["t"], ["……谢谢。"])

    def test_store_failure_does_not_block_speaking(self):
        """存档写不进去也必须能说话 —— 桌宠不能因为存档问题变成哑巴。"""
        self.write_scene("t", {"lines": [{"text": "我在呢。"}]})
        store = FakeStore()
        store.boom = True
        lib = self.make_lib(store=store)
        self.assertEqual(lib.pick("t"), "我在呢。")

    def test_works_without_store(self):
        self.write_scene("t", {"lines": self.LINES})
        lib = self.make_lib(store=None, seed=5)
        for _ in range(10):
            self.assertIsNotNone(lib.pick("t"))


class TestSceneClassification(unittest.TestCase):
    """主动 / 非主动场景分类 —— controller 靠它决定要不要过最小间隔。"""

    def test_proactive_scenes(self):
        for scene in ("idle_random", "detect_typing", "time_morning",
                      "detect_app_code", "event_valentine"):
            with self.subTest(scene=scene):
                self.assertTrue(dlg.is_proactive(scene))

    def test_user_triggered_scenes_are_not_proactive(self):
        for scene in ("feed_done", "checkin_done", "feed_empty", "headpat", "small_talk"):
            with self.subTest(scene=scene):
                self.assertFalse(dlg.is_proactive(scene))

    def test_gap_exempt_classification(self):
        self.assertTrue(dlg.is_gap_exempt("startup_hello"))
        self.assertTrue(dlg.is_gap_exempt("feed_done"))
        self.assertFalse(dlg.is_gap_exempt("idle_random"))
        self.assertFalse(dlg.is_gap_exempt("绝对不存在的场景"))

    def test_builtin_fallback_scenes_are_classified(self):
        """兜底场景也必须有分类，否则 controller 的间隔判断会漏掉它们。"""
        for scene in dlg.DEFAULT_SCENES:
            with self.subTest(scene=scene):
                self.assertTrue(dlg.is_proactive(scene) or dlg.is_gap_exempt(scene))

    def test_all_user_triggered_scenes_are_gap_exempt(self):
        """用户点了却不说话是最糟的体验 —— 非主动场景一律免于最小间隔。"""
        for scene in dlg.GAP_EXEMPT_SCENES:
            with self.subTest(scene=scene):
                self.assertFalse(dlg.is_proactive(scene))


class TestRealAssets(unittest.TestCase):
    """真实 `assets/nurture/dialogues/` 的加载结果。"""

    def test_first_six_scenes_are_present(self):
        lib = dlg.DialogueLibrary(REAL_DIALOGUES)
        loaded = set(lib.scenes())
        for scene in ("feed_done", "checkin_done", "idle_random",
                      "startup_hello", "feed_empty", "detect_typing"):
            with self.subTest(scene=scene):
                self.assertIn(scene, loaded)

    def test_each_scene_has_at_least_six_lines(self):
        lib = dlg.DialogueLibrary(REAL_DIALOGUES)
        for scene in lib.scenes():
            with self.subTest(scene=scene):
                count = len([1 for sid, _ in lib.all_lines() if sid == scene])
                self.assertGreaterEqual(count, 6, f"{scene} 只有 {count} 条台词")

    def test_no_parse_errors_in_real_assets(self):
        lib = dlg.DialogueLibrary(REAL_DIALOGUES)
        self.assertEqual(lib.errors, {})

    def test_real_scene_pools_are_usable(self):
        lib = dlg.DialogueLibrary(REAL_DIALOGUES)
        for scene in lib.scenes():
            with self.subTest(scene=scene):
                self.assertTrue(lib.has_scene(scene))
                self.assertIsNotNone(lib.pick(scene, {"streak": 3}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
