"""`assets/nurture/*.json` 配置一致性测试。

这些文件是**用户可手改**的，所以它们之间的引用关系必须有自动化检查，
否则只会以"某个食物点了没反应"这种形式暴露出来。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

素材库不存在时（例如在没放 GIF 的机器上跑）跳过动画名校验，其余仍会检查。
"""

import json
import os
import re
import sys
import unicodedata
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import dialogue  # noqa: E402
from src import nurture_model as nm  # noqa: E402
from src.gif_registry import GifRegistry  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NURTURE_DIR = os.path.join(PROJECT_DIR, "assets", "nurture")
DIALOGUES_DIR = os.path.join(NURTURE_DIR, "dialogues")
GIF_DIR = os.path.join(PROJECT_DIR, "素材库", "高木同学Q版gif")

#: 台词长度上限（03 设计规范 9 与 `dialogue.MAX_LINE_CHARS` 必须一致）
MAX_LINE_CHARS = 18

#: 「不评判」七禁区的静态句式黑名单（01 文档 7.1 + 12.2 验收）。
#: 这些是**质问 / 抱怨 / 评判**的典型句式 —— 人工审查极易漏掉，必须机器检查。
FORBIDDEN_PATTERNS = (
    # 质问 / 抱怨
    "你怎么", "怎么还", "你去哪", "去哪了", "又不理", "才回来", "这么久",
    "都不理", "等你好久", "终于来了",
    # 评判 / 说教
    "别摸鱼", "偷懒", "不务正业", "整天", "又在玩", "还在玩", "居然不",
    "你应该", "你不该", "快去",
)

#: 系统口吻（03 规范 9：这类信息走 UI 与角标，不走她的嘴）
SYSTEM_TONE_WORDS = ("已保存", "操作成功", "获取失败", "签到成功", "保存成功", "加载失败")

#: 她不用「主人」称呼用户（03 规范 9：避免代入感错位）
FORBIDDEN_ADDRESS = ("主人", "您")

#: 规范 9 允许的标点（「。」「…」「，」为主）。出现表外的标点 → 报错，
#: 用来抓全角/半角混用、误敲的英文标点等。
ALLOWED_PUNCTUATION = set("。，、…—～~·：:？?！!'\"“”‘’《》()（）【】")

#: 颜文字 / emoji 的特征字符
KAOMOJI_MARKERS = ("(*", "(*)", ">_<", "QAQ", "233", "ww", "orz")



def load_json(name: str) -> dict:
    with open(os.path.join(NURTURE_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def assert_line_is_compliant(case: unittest.TestCase, text: str) -> None:
    """单条台词的**可机器检查**部分：长度 / 句式 / 标点 / 称呼。

    这挡不住"语气不好"，但能挡住最常见的翻车。真正的语气审查在暂停点 B 由人来做。
    """
    case.assertLessEqual(len(text), MAX_LINE_CHARS, f"太长（>{MAX_LINE_CHARS} 字）: {text}")
    case.assertTrue(text.strip(), "空台词")
    case.assertEqual(text.strip(), text, f"首尾有空白: {text!r}")

    for bad in FORBIDDEN_PATTERNS:
        case.assertNotIn(bad, text, f"含质问/评判句式「{bad}」: {text}")
    for word in SYSTEM_TONE_WORDS:
        case.assertNotIn(word, text, f"含系统口吻「{word}」: {text}")
    for word in FORBIDDEN_ADDRESS:
        case.assertNotIn(word, text, f"含不该用的称呼「{word}」: {text}")
    for marker in KAOMOJI_MARKERS:
        case.assertNotIn(marker, text, f"含颜文字「{marker}」: {text}")

    # 感叹号：规范 9 明确「不用感叹号堆叠」，这里从严 —— 一条都不允许
    case.assertNotIn("！", text, f"含感叹号: {text}")
    case.assertNotIn("!", text, f"含感叹号: {text}")

    # 标点必须在白名单里（抓全角/半角混用、误敲的英文标点）。
    # 先剥掉 {占位符} —— 花括号是模板语法，不是正文标点。
    prose = re.sub(r"\{[^}]*\}", "", text)
    for ch in prose:
        if unicodedata.category(ch).startswith("P"):
            case.assertIn(ch, ALLOWED_PUNCTUATION, f"出现了表外标点「{ch}」: {text}")


class TestItems(unittest.TestCase):
    """`items.json` 结构与动画名。"""

    @classmethod
    def setUpClass(cls):
        cls.data = load_json("items.json")
        cls.items = cls.data["items"]
        cls.by_name = {i["name"]: i for i in cls.items}
        cls.registry = GifRegistry(GIF_DIR)

    def test_has_thirteen_items(self):
        self.assertEqual(len(self.items), 13)

    def test_names_are_unique_and_non_empty(self):
        names = [i.get("name", "") for i in self.items]
        self.assertTrue(all(names))
        self.assertEqual(len(names), len(set(names)))

    def test_kind_and_tier_are_valid(self):
        for item in self.items:
            with self.subTest(item=item.get("name")):
                self.assertIn(item.get("kind"), nm.KINDS)
                self.assertIn(item.get("tier"), nm.TIERS)

    def test_both_kinds_are_represented(self):
        kinds = {i["kind"] for i in self.items}
        self.assertEqual(kinds, set(nm.KINDS))

    def test_every_tier_has_candidates(self):
        """每个档位都要有物品，否则签到按档位发奖时会静默发空。"""
        tiers = {i["tier"] for i in self.items}
        self.assertEqual(tiers, set(nm.TIERS))

    def test_icon_keys_are_unique(self):
        keys = [i.get("icon_key", "") for i in self.items]
        self.assertTrue(all(keys))
        self.assertEqual(len(keys), len(set(keys)))

    def test_anim_names_exist_in_library(self):
        """动作名写错会走兜底链（不崩），但那就浪费了专属动画 —— 这里主动抓出来。"""
        if len(self.registry) == 0:
            self.skipTest(f"素材库为空或不存在: {GIF_DIR}")
        for item in self.items:
            with self.subTest(item=item["name"]):
                self.assertTrue(self.registry.has(item["anim"]),
                                f"{item['name']} 的 anim「{item['anim']}」在素材库里不存在")

    def test_every_item_resolves_to_some_animation(self):
        for item in self.items:
            with self.subTest(item=item["name"]):
                self.assertIsNotNone(
                    nm.resolve_anim(item, item["kind"], self.registry.has))

    def test_known_defective_assets_are_not_used(self):
        """`冒泡 2` / `睡觉(普通)` 含不透明黑色边缘块，叠桌面会露出黑矩形（01 文档 3.4）。"""
        for item in self.items:
            with self.subTest(item=item["name"]):
                self.assertNotIn(item["anim"], ("冒泡 2", "睡觉(普通)", "睡觉(准备阶段1)"))

    def test_item_lines_are_short_and_non_judgmental(self):
        for item in self.items:
            for line in item.get("lines", []):
                with self.subTest(item=item["name"], line=line):
                    assert_line_is_compliant(self, line)

    def test_reward_pool_covers_all_tiers_with_real_names(self):
        """`nurture_model.resolve_tiers` 需要的 {档位: [名称]} 能从 items.json 直接构建。"""
        pool: dict[str, list[str]] = {}
        for item in self.items:
            pool.setdefault(item["tier"], []).append(item["name"])
        reward = nm.checkin_reward(7, load_json("checkin.json"))
        resolved = nm.resolve_tiers(reward["tiers"], pool)
        self.assertTrue(resolved)
        self.assertTrue(all(name in self.by_name for name in resolved))


class TestDialogues(unittest.TestCase):
    """`assets/nurture/dialogues/*.json` 结构 + 「不评判」静态自查。

    这台机器上的自动化测试只能查"句式与格式"，**语气好不好仍然要人来读**。
    但它能挡住最常见的翻车：质问、抱怨、说教、系统口吻、太长、颜文字。
    """

    @classmethod
    def setUpClass(cls):
        cls.lib = dialogue.DialogueLibrary(DIALOGUES_DIR)
        cls.lib.reload()
        cls.files = sorted(n for n in os.listdir(DIALOGUES_DIR)
                           if n.lower().endswith(".json")) if os.path.isdir(DIALOGUES_DIR) else []

    def test_dialogue_files_exist_and_parse(self):
        self.assertTrue(self.files, f"没有找到任何台词文件: {DIALOGUES_DIR}")
        self.assertEqual(self.lib.errors, {}, f"台词文件解析失败: {self.lib.errors}")

    def test_first_six_scenes_are_present(self):
        for scene in ("feed_done", "checkin_done", "idle_random",
                      "startup_hello", "feed_empty", "detect_typing"):
            with self.subTest(scene=scene):
                self.assertIn(scene, self.lib.scenes())

    def test_every_scene_has_at_least_six_lines(self):
        for scene in self.lib.scenes():
            with self.subTest(scene=scene):
                count = len([1 for sid, _ in self.lib.all_lines() if sid == scene])
                self.assertGreaterEqual(count, 6, f"{scene} 只有 {count} 条台词（要求 ≥6）")

    def test_file_name_matches_inner_scene_id(self):
        for name in self.files:
            with self.subTest(file=name):
                with open(os.path.join(DIALOGUES_DIR, name), "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.assertEqual(raw.get("scene"), os.path.splitext(name)[0],
                                 f"{name} 里的 scene 字段和文件名不一致")

    def test_scene_declares_cooldown_metadata(self):
        for name in self.files:
            with self.subTest(file=name):
                with open(os.path.join(DIALOGUES_DIR, name), "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.assertIn("cooldown_sec", raw)
                self.assertIn("min_gap_sec", raw)
                self.assertGreaterEqual(int(raw["cooldown_sec"]), 0)

    def test_tones_are_valid_and_tease_is_not_used_in_first_batch(self):
        for scene, line in self.lib.all_lines():
            with self.subTest(scene=scene, text=line["text"]):
                self.assertIn(line["tone"], dialogue.TONES)
                # 首批 6 个场景刻意不含 tease（捉弄语气留待后续按需补）
                self.assertNotEqual(line["tone"], "tease")

    def test_weights_and_levels_are_sane(self):
        for scene, line in self.lib.all_lines():
            with self.subTest(scene=scene, text=line["text"]):
                self.assertGreaterEqual(line["weight"], 1)
                self.assertGreaterEqual(line["min_level"], 0)
                self.assertLessEqual(line["min_level"], 700)

    def test_every_line_passes_the_content_rules(self):
        for scene, line in self.lib.all_lines():
            with self.subTest(scene=scene, text=line["text"]):
                assert_line_is_compliant(self, line["text"])

    def test_placeholders_are_whitelisted(self):
        for scene, line in self.lib.all_lines():
            for key in dialogue.placeholders_in(line["text"]):
                with self.subTest(scene=scene, text=line["text"], key=key):
                    self.assertIn(key, dialogue.PLACEHOLDER_KEYS)

    def test_detect_scenes_never_mention_content(self):
        """感知类台词只能到「你在忙」这一抽象层级，不能提具体内容（禁区 1）。"""
        content_words = ("代码", "文档", "游戏", "视频", "电影", "论文", "作业", "报表")
        for scene, line in self.lib.all_lines():
            if not scene.startswith("detect_"):
                continue
            for word in content_words:
                with self.subTest(scene=scene, text=line["text"], word=word):
                    self.assertNotIn(word, line["text"])

    def test_item_lines_pass_the_same_content_rules(self):
        with open(os.path.join(NURTURE_DIR, "items.json"), "r", encoding="utf-8") as f:
            items = json.load(f)["items"]
        for item in items:
            for line in item.get("lines", []):
                with self.subTest(item=item["name"], line=line):
                    assert_line_is_compliant(self, line)


class TestCheckinTable(unittest.TestCase):
    """`checkin.json`。"""

    @classmethod
    def setUpClass(cls):
        cls.table = load_json("checkin.json")

    def test_base_items_use_valid_tiers(self):
        for tier in self.table["base_items"]:
            with self.subTest(tier=tier):
                self.assertIn(tier, nm.TIERS)

    def test_milestones_are_positive_ints_and_sorted(self):
        keys = [int(k) for k in self.table["milestones"]]
        self.assertEqual(keys, sorted(keys))
        self.assertTrue(all(k > 0 for k in keys))

    def test_milestone_items_use_valid_tiers(self):
        for day, conf in self.table["milestones"].items():
            for tier in conf.get("items", {}):
                with self.subTest(day=day, tier=tier):
                    self.assertIn(tier, nm.TIERS)

    def test_reward_for_each_milestone_is_produced(self):
        for day in (1, 3, 7, 14, 30):
            with self.subTest(day=day):
                reward = nm.checkin_reward(day, self.table)
                self.assertTrue(reward["tiers"])
        self.assertEqual(nm.checkin_reward(7, self.table)["milestone"], 7)


class TestLevels(unittest.TestCase):
    """`levels.json`。"""

    @classmethod
    def setUpClass(cls):
        cls.levels = load_json("levels.json")["levels"]

    def test_thresholds_start_at_zero_and_ascend(self):
        thresholds = [lv["threshold"] for lv in self.levels]
        self.assertEqual(thresholds[0], 0)
        self.assertEqual(thresholds, sorted(thresholds))
        self.assertEqual(len(thresholds), len(set(thresholds)))

    def test_titles_are_non_empty(self):
        for lv in self.levels:
            with self.subTest(threshold=lv["threshold"]):
                self.assertTrue(lv["title"])

    def test_documented_thresholds(self):
        """需求文档 2.2 写死的阈值，改了这里也要同步改文档。"""
        self.assertEqual([lv["threshold"] for lv in self.levels],
                         [0, 50, 120, 250, 450, 700])

    def test_unlocks_only_reference_known_features(self):
        known = {"idle_random", "small_talk", "tone_proud", "event_lines",
                 "headpat", "late_talk"}
        for lv in self.levels:
            for feature in lv.get("unlocks", []):
                with self.subTest(threshold=lv["threshold"], feature=feature):
                    self.assertIn(feature, known)

    def test_level_lookup_matches_file(self):
        self.assertEqual(nm.level_of(120, self.levels), 2)
        self.assertEqual(nm.level_info(120, self.levels)["title"], "朋友")
        self.assertEqual(nm.level_of(700, self.levels), 5)


class TestEvents(unittest.TestCase):
    """`events.json`。"""

    @classmethod
    def setUpClass(cls):
        cls.events = load_json("events.json")["events"]
        cls.item_names = {i["name"] for i in load_json("items.json")["items"]}

    def test_ids_are_unique(self):
        ids = [e["id"] for e in self.events]
        self.assertEqual(len(ids), len(set(ids)))

    def test_dates_are_mm_dd_or_birthday_token(self):
        for event in self.events:
            with self.subTest(event=event["id"]):
                raw = event["date"]
                if raw == "birthday":
                    continue
                month, day = (int(x) for x in raw.split("-"))
                self.assertTrue(1 <= month <= 12)
                self.assertTrue(1 <= day <= 31)
                # 用闰年构造，确保 2/29 之类的日期也合法
                self.assertIsInstance(date(2024, month, day), date)

    def test_documented_events_are_present(self):
        self.assertEqual({e["date"] for e in self.events},
                         {"02-14", "07-07", "12-25", "01-01", "birthday"})

    def test_event_items_reference_real_items(self):
        for event in self.events:
            for entry in event.get("items", []):
                with self.subTest(event=event["id"], item=entry["name"]):
                    self.assertIn(entry["name"], self.item_names)
                    self.assertGreaterEqual(int(entry["count"]), 1)

    def test_scenes_are_non_empty_and_unique(self):
        scenes = [e["scene"] for e in self.events]
        self.assertTrue(all(scenes))
        self.assertEqual(len(scenes), len(set(scenes)))


class TestApps(unittest.TestCase):
    """`apps.json`（阶段 G 的前台分类表）。

    这个文件是**用户会自己改**的，所以检查重点不是"内容对不对"，
    而是"改错了会不会静默失效"：分类名拼错、填了完整路径、同一个进程名进两个分类。
    """

    @classmethod
    def setUpClass(cls):
        from src import window_monitor
        cls.wm = window_monitor
        cls.data = load_json("apps.json")
        cls.categories = cls.data.get("categories", {})
        cls.ignore = cls.data.get("ignore", [])
        cls.table, cls.ignored = window_monitor.load_app_table(
            os.path.join(NURTURE_DIR, "apps.json"))

    def test_has_the_documented_categories(self):
        self.assertEqual(set(self.categories), set(self.wm.APP_KEYS))

    def test_categories_are_non_empty_lists_of_strings(self):
        for key, names in self.categories.items():
            with self.subTest(category=key):
                self.assertIsInstance(names, list)
                self.assertTrue(names)
                self.assertTrue(all(isinstance(n, str) and n.strip() for n in names))

    def test_every_entry_looks_like_a_process_name(self):
        """必须是 `xxx.exe` 这样的**文件名** —— 填完整路径是永远不会匹配的。"""
        for key, names in self.categories.items():
            for name in names:
                with self.subTest(category=key, exe=name):
                    self.assertTrue(name.lower().endswith(".exe"), name)
                    self.assertNotIn("\\", name)
                    self.assertNotIn("/", name)
                    self.assertEqual(name, name.strip())

    def test_no_process_name_appears_twice(self):
        """同一个进程名进两个分类 → 只有先写的生效，另一条是**静默失效**的。"""
        all_names = [n.lower() for names in self.categories.values() for n in names]
        duplicates = sorted(n for n in set(all_names) if all_names.count(n) > 1)
        self.assertEqual(duplicates, [])

    def test_ignore_list_is_clean(self):
        self.assertTrue(all(isinstance(n, str) and n.strip().lower().endswith(".exe")
                            for n in self.ignore))
        self.assertEqual(len(self.ignore), len(set(n.lower() for n in self.ignore)))

    def test_ignore_and_categories_do_not_contradict(self):
        """既写进分类又在黑名单里 = 自相矛盾（黑名单会赢，分类那条白写）。"""
        all_names = {n.lower() for names in self.categories.values() for n in names}
        self.assertEqual(all_names & {n.lower() for n in self.ignore}, set())

    def test_documents_how_to_edit(self):
        """用户可编辑的文件必须自带说明（与 items.json 的 `_说明` 同口径）。"""
        self.assertIn("_说明", self.data)

    def test_loads_through_the_real_loader(self):
        """真表必须能被真加载器读出来，且每一条都能查回它自己的分类。

        这条能抓到"分类名写错"这类问题：`load_app_table()` 会跳过不认识的分类。
        """
        for key, names in self.categories.items():
            for name in names:
                with self.subTest(category=key, exe=name):
                    self.assertEqual(self.wm.classify_exe(name, self.table,
                                                          self.ignored), key)

    def test_ignore_entries_classify_as_unknown(self):
        for name in self.ignore:
            with self.subTest(exe=name):
                self.assertEqual(self.wm.classify_exe(name, self.table, self.ignored),
                                 self.wm.UNKNOWN_KEY)

    def test_password_managers_are_ignored_by_default(self):
        """01 文档 8.2 明确要求「会议 / 密码管理器等建议默认在列」。"""
        for name in ("keepassxc.exe", "1password.exe", "bitwarden.exe"):
            with self.subTest(exe=name):
                self.assertIn(name, self.ignored)

    def test_conferencing_apps_are_classified(self):
        for name in ("zoom.exe", "teams.exe", "wemeetapp.exe", "dingtalk.exe"):
            with self.subTest(exe=name):
                self.assertEqual(self.table.get(name), "meeting")


if __name__ == "__main__":
    unittest.main(verbosity=2)
