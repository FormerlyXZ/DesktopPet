"""`src/nurture_panel.py` 单测 —— 几何、命中、库存展示、页签、落位。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

需要 `QApplication`，但**不显示任何窗口**；鼠标事件用 `QMouseEvent` 手工构造后
`QApplication.sendEvent()` 投递，不依赖真实光标。

> **一条硬规矩**：心形进度条是 600ms 补间的（`QPropertyAnimation`），
> 断言"涨到哪了"必须用 `heart_target()`，**不能**用 `heart_ratio()` ——
> 后者是补间中间态，断言它会随机失败（与 `hide_with_anim()` 同一个坑）。
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src import nurture_model as model  # noqa: E402
from src import nurture_panel as np  # noqa: E402

_APP = None

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS_JSON = os.path.join(PROJECT_DIR, "assets", "nurture", "items.json")
LEVELS_JSON = os.path.join(PROJECT_DIR, "assets", "nurture", "levels.json")

FOOD = [
    {"name": "奶油面包", "kind": "food", "tier": "common", "anim": "笑", "icon_key": "bread"},
    {"name": "饭团", "kind": "food", "tier": "common", "anim": "笑", "icon_key": "onigiri"},
    {"name": "牛奶", "kind": "food", "tier": "common", "anim": "笑", "icon_key": "milk"},
    {"name": "炒面面包", "kind": "food", "tier": "common", "anim": "笑", "icon_key": "yakisoba"},
]
GIFTS = [
    {"name": "玫瑰花", "kind": "gift", "tier": "rare", "anim": "玫瑰", "icon_key": "rose"},
    {"name": "压岁钱", "kind": "gift", "tier": "precious", "anim": "红", "icon_key": "redpacket"},
]


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


def click(widget, pos) -> None:
    """在 `pos` 处投递一次完整的 按下→抬起（不依赖真实光标）。"""
    for event_type, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                                (QEvent.MouseButtonRelease, Qt.NoButton)):
        event = QMouseEvent(event_type, QPointF(pos), QPointF(pos),
                            Qt.LeftButton, buttons, Qt.NoModifier)
        QApplication.sendEvent(widget, event)


def move(widget, pos) -> None:
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


class PanelTestCase(unittest.TestCase):
    def setUp(self):
        self.panel = np.NurturePanel(FOOD + GIFTS)
        self.addCleanup(self.panel.deleteLater)


class TestSpecConstants(PanelTestCase):
    """规范 5.2 的尺寸常量。数字写错会让三列装不下或卡片挤在一起。"""

    def test_three_columns_fit_in_the_fixed_width(self):
        inner = np.WIDTH - np.PAD * 2
        used = np.COLS * np.CARD_W + (np.COLS - 1) * np.GRID_GAP
        self.assertLessEqual(used, inner, f"三列卡片用了 {used}px，内容宽只有 {inner}px")

    def test_window_is_panel_width_plus_shadow_margin(self):
        self.assertEqual(self.panel.width(), np.WIDTH + np.MARGIN * 2)

    def test_height_formula(self):
        rows = 2                      # 4 个食物 → 2 行
        expected = (np.MARGIN * 2 + np.PAD + np.HEADER_H + 10
                    + rows * (np.CARD_H + np.GRID_GAP) - np.GRID_GAP
                    + 10 + np.TAB_H + np.PAD)
        self.assertEqual(self.panel.height(), expected)

    def test_tabs_are_the_three_expected_keys(self):
        self.assertEqual(np.TABS, ("food", "gift", "status"))


class TestGeometry(PanelTestCase):
    """所有矩形都必须落在面板内、互不重叠 —— 这是自绘 UI 最容易画歪的地方。"""

    def test_cards_are_inside_the_panel_and_do_not_overlap(self):
        panel_rect = self.panel._panel_rect()          # noqa: SLF001
        seen = []
        for index in range(len(self.panel.items_of("food"))):
            rect = self.panel.card_rect(index)
            self.assertTrue(rect.isValid(), rect)
            self.assertTrue(panel_rect.contains(rect), rect)
            for other in seen:
                self.assertFalse(rect.intersects(other), f"{rect} 与 {other} 重叠")
            seen.append(rect)

    def test_cards_are_laid_out_left_to_right_then_wrap(self):
        first = self.panel.card_rect(0)
        second = self.panel.card_rect(1)
        fourth = self.panel.card_rect(3)               # 第 2 行第 1 列
        self.assertEqual(second.y(), first.y())
        self.assertGreater(second.x(), first.x())
        self.assertGreater(fourth.y(), first.y())
        self.assertEqual(fourth.x(), first.x())

    def test_card_size_matches_spec(self):
        rect = self.panel.card_rect(0)
        self.assertEqual((rect.width(), rect.height()), (np.CARD_W, np.CARD_H))

    def test_out_of_range_card_rect_is_empty(self):
        self.assertFalse(self.panel.card_rect(99).isValid())
        self.assertFalse(self.panel.card_rect(-1).isValid())

    def test_dirty_card_index_degrades_to_the_first_card(self):
        """`safe_int` 的既定降级口径：脏值当 0。显示用，不必为它抛异常。"""
        self.assertEqual(self.panel.card_rect("abc"), self.panel.card_rect(0))
        self.assertEqual(self.panel.card_rect(None), self.panel.card_rect(0))

    def test_tabs_are_inside_the_panel_and_do_not_overlap(self):
        panel_rect = self.panel._panel_rect()          # noqa: SLF001
        seen = []
        for key in np.TABS:
            rect = self.panel.tab_rect(key)
            self.assertTrue(panel_rect.contains(rect), rect)
            for other in seen:
                self.assertFalse(rect.intersects(other))
            seen.append(rect)

    def test_close_button_is_inside_the_header(self):
        header = self.panel.header_rect()
        close = self.panel.close_rect()
        self.assertTrue(header.contains(close), (header, close))
        self.assertEqual(close.width(), np.CLOSE_D)

    def test_cards_do_not_overlap_the_tabs_or_the_header(self):
        header = self.panel.header_rect()
        tabs = [self.panel.tab_rect(key) for key in np.TABS]
        for index in range(len(self.panel.items_of("food"))):
            rect = self.panel.card_rect(index)
            self.assertFalse(rect.intersects(header))
            for tab in tabs:
                self.assertFalse(rect.intersects(tab))

    def test_height_is_stable_across_tabs(self):
        """切页签**不能**让面板跳高度（食物 9 张 vs 礼物 4 张差距很大）。"""
        before = self.panel.height()
        food_rect = self.panel.card_rect(0)
        self.panel.set_tab("gift")
        self.assertEqual(self.panel.height(), before)
        self.panel.set_tab("status")
        self.assertEqual(self.panel.height(), before)
        self.panel.set_tab("food")
        self.assertEqual(self.panel.card_rect(0), food_rect)

    def test_height_follows_the_longest_page(self):
        """行数最多的那一页决定高度 —— 用真实的 items.json 验一遍。"""
        with open(ITEMS_JSON, "r", encoding="utf-8") as handle:
            items = json.load(handle)["items"]
        real = np.NurturePanel(items)
        self.addCleanup(real.deleteLater)
        longest = max(len(real.items_of(tab)) for tab in np.TABS)
        best_rows = (longest + np.COLS - 1) // np.COLS
        for tab in np.TABS:
            real.set_tab(tab)
            with self.subTest(tab=tab):
                self.assertEqual(real.height(), real.content_height())
        self.assertGreaterEqual(real.height(),
                                np.MARGIN * 2 + np.PAD + np.HEADER_H + 10
                                + best_rows * (np.CARD_H + np.GRID_GAP) - np.GRID_GAP
                                + 10 + np.TAB_H + np.PAD)


class TestPlacement(PanelTestCase):
    """落位：贴人物**左侧**（规范第 7 节），左侧不足 → 翻右 → 夹紧。"""

    SCREEN = QRect(0, 0, 1920, 1080)

    def _bg_left(self, rect):
        return rect.left() + np.MARGIN

    def _bg_right(self, rect):
        return rect.right() - np.MARGIN

    def test_prefers_the_left_side_with_an_eight_pixel_gap(self):
        pet = QRect(1000, 400, 300, 400)
        direction, rect = self.panel.plan_placement(pet, self.SCREEN)
        self.assertEqual(direction, "left")
        # 间距从**背景边缘**量：窗口左边还留着 6px 投影空间
        self.assertEqual(pet.left() - self._bg_right(rect) - 1, np.GAP_FROM_PET)
        self.assertEqual(rect.center().y(), pet.center().y())
        self.assertTrue(self.SCREEN.contains(rect))

    def test_flips_right_when_there_is_no_room_on_the_left(self):
        pet = QRect(120, 400, 300, 400)
        direction, rect = self.panel.plan_placement(pet, self.SCREEN)
        self.assertEqual(direction, "right")
        self.assertEqual(self._bg_left(rect) - pet.right() - 1, np.GAP_FROM_PET)
        self.assertTrue(self.SCREEN.contains(rect))

    def test_never_overlaps_the_pet_and_never_leaves_the_screen(self):
        for x in (0, 60, 400, 900, 1600, 1920 - 300):
            for y in (0, 200, 540, 1080 - 400):
                pet = QRect(x, y, 300, 400)
                with self.subTest(x=x, y=y):
                    _direction, rect = self.panel.plan_placement(pet, self.SCREEN)
                    self.assertTrue(self.SCREEN.contains(rect), rect)
                    self.assertFalse(rect.intersects(pet), rect)

    def test_clamped_when_both_sides_are_too_narrow(self):
        tiny = QRect(0, 0, 400, 900)
        pet = QRect(50, 200, 300, 400)
        _direction, rect = self.panel.plan_placement(pet, tiny)
        self.assertGreaterEqual(rect.left(), tiny.left())
        self.assertLessEqual(rect.right(), tiny.right())
        self.assertGreaterEqual(rect.top(), tiny.top())
        self.assertLessEqual(rect.bottom(), tiny.bottom())

    def test_respects_secondary_screen_offset(self):
        second = QRect(1920, 0, 1280, 1024)
        pet = QRect(1920 + 900, 300, 300, 400)
        _direction, rect = self.panel.plan_placement(pet, second)
        self.assertTrue(second.contains(rect), rect)

    def test_popup_offset_points_away_from_the_pet(self):
        self.panel._popup_direction = "left"           # noqa: SLF001
        offset = self.panel._popup_offset()            # noqa: SLF001
        self.assertEqual((offset.x(), offset.y()), (-np.DRAG_OUT_OFFSET, 0))
        self.panel._popup_direction = "right"          # noqa: SLF001
        offset = self.panel._popup_offset()            # noqa: SLF001
        self.assertEqual((offset.x(), offset.y()), (np.DRAG_OUT_OFFSET, 0))

    def test_popup_near_sets_the_direction(self):
        self.panel.popup_near(QRect(1200, 400, 300, 400))
        self.assertEqual(self.panel._popup_direction, "left")     # noqa: SLF001


class TestWindowFlags(PanelTestCase):
    """与 `HoverMenu` 同一套约束：绝不抢焦点、绝不用 `focusOutEvent` 收起。"""

    def test_does_not_accept_focus(self):
        self.assertTrue(bool(self.panel.windowFlags() & Qt.WindowDoesNotAcceptFocus))

    def test_show_without_activating(self):
        self.assertTrue(self.panel.testAttribute(Qt.WA_ShowWithoutActivating))

    def test_translucent_frameless_topmost(self):
        flags = self.panel.windowFlags()
        self.assertTrue(bool(flags & Qt.FramelessWindowHint))
        self.assertTrue(bool(flags & Qt.WindowStaysOnTopHint))
        self.assertTrue(bool(flags & Qt.Tool))
        self.assertTrue(self.panel.testAttribute(Qt.WA_TranslucentBackground))

    def test_does_not_override_focus_out(self):
        self.assertIs(np.NurturePanel.focusOutEvent, QWidget.focusOutEvent)

    def test_mouse_tracking_enabled(self):
        self.assertTrue(self.panel.hasMouseTracking())

    def test_hide_with_anim_on_a_hidden_panel_is_a_noop(self):
        self.assertFalse(self.panel.isVisible())
        self.panel.hide_with_anim()
        self.assertFalse(self.panel.isVisible())

    def test_hide_now(self):
        self.panel.show()
        self.panel.hide_now()
        self.assertFalse(self.panel.isVisible())


class TestItems(PanelTestCase):
    """`items.json` 是用户可编辑的 —— 脏数据必须降级而不是崩。"""

    def test_groups_by_kind(self):
        self.assertEqual(len(self.panel.items_of("food")), 4)
        self.assertEqual(len(self.panel.items_of("gift")), 2)
        self.assertEqual(self.panel.items_of("status"), [])

    def test_tolerates_garbage(self):
        for bad in (None, "abc", 42, [None, 1, "x"], [{}], [{"name": ""}],
                    [{"name": "   "}], [{"name": 3}]):
            with self.subTest(bad=bad):
                panel = np.NurturePanel(bad)
                self.addCleanup(panel.deleteLater)
                self.assertEqual(panel.items(), [])
                self.assertTrue(panel.card_rect(0).isNull())

    def test_unknown_kind_falls_back_to_food(self):
        panel = np.NurturePanel([{"name": "奇怪的东西", "kind": "垃圾"}])
        self.addCleanup(panel.deleteLater)
        self.assertEqual(len(panel.items_of("food")), 1)
        self.assertEqual(len(panel.items_of("gift")), 0)

    def test_missing_kind_falls_back_to_food(self):
        panel = np.NurturePanel([{"name": "没有类型"}])
        self.addCleanup(panel.deleteLater)
        self.assertEqual(len(panel.items_of("food")), 1)

    def test_name_is_stripped(self):
        panel = np.NurturePanel([{"name": "  饭团  "}])
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.items()[0]["name"], "饭团")

    def test_items_returns_copies(self):
        """改返回值不能污染面板内部状态（否则 controller 一个手滑就改坏了配置）。"""
        got = self.panel.items()
        got[0]["name"] = "被改了"
        self.assertEqual(self.panel.items()[0]["name"], "奶油面包")

    def test_empty_tab_renders_the_empty_hint(self):
        panel = np.NurturePanel(FOOD)                  # 没有礼物
        self.addCleanup(panel.deleteLater)
        panel.set_tab("gift")
        self.assertEqual(panel.items_of("gift"), [])
        self.assertFalse(panel.grab().isNull())

    def test_item_at_hit_testing(self):
        for index in range(len(self.panel.items_of("food"))):
            item = self.panel.item_at(self.panel.card_rect(index).center())
            self.assertIsNotNone(item)
            self.assertEqual(item["name"], self.panel.items_of("food")[index]["name"])
        self.assertIsNone(self.panel.item_at(QPoint(0, 0)))
        self.assertIsNone(self.panel.item_at(self.panel.tab_rect("food").center()))

    def test_card_rect_for_name(self):
        self.assertEqual(self.panel.card_rect_for("牛奶"), self.panel.card_rect(2))
        self.assertFalse(self.panel.card_rect_for("不存在").isValid())


class TestInventory(PanelTestCase):
    def test_count_of(self):
        self.panel.set_inventory({"奶油面包": 3, "饭团": 0})
        self.assertEqual(self.panel.count_of("奶油面包"), 3)
        self.assertEqual(self.panel.count_of("饭团"), 0)
        self.assertEqual(self.panel.count_of("没听说过"), 0)

    def test_dirty_inventory_is_zeroed(self):
        self.panel.set_inventory({"奶油面包": "很多", "饭团": None, "牛奶": -5, "炒面面包": 2.9})
        self.assertEqual(self.panel.count_of("奶油面包"), 0)
        self.assertEqual(self.panel.count_of("饭团"), 0)
        self.assertEqual(self.panel.count_of("牛奶"), 0)
        self.assertEqual(self.panel.count_of("炒面面包"), 2)

    def test_garbage_inventory_is_ignored(self):
        self.panel.set_inventory({"奶油面包": 3})
        self.panel.set_inventory("abc")
        self.panel.set_inventory(None)
        self.panel.set_inventory([1, 2])
        self.assertEqual(self.panel.count_of("奶油面包"), 3)

    def test_zero_stock_card_still_renders(self):
        self.panel.set_inventory({name: 0 for name in ("奶油面包", "饭团")})
        self.assertFalse(self.panel.grab().isNull())


class TestAffectionAndStatus(PanelTestCase):
    def setUp(self):
        super().setUp()
        with open(LEVELS_JSON, "r", encoding="utf-8") as handle:
            self.panel.set_levels(json.load(handle)["levels"])

    def test_heart_target_tracks_the_ratio(self):
        self.panel.set_affection(125, 250)
        self.assertAlmostEqual(self.panel.heart_target(), 0.5, places=6)

    def test_heart_target_is_clamped(self):
        self.panel.set_affection(9999, 250)
        self.assertAlmostEqual(self.panel.heart_target(), 1.0, places=6)
        self.panel.set_affection(-10, 250)
        self.assertAlmostEqual(self.panel.heart_target(), 0.0, places=6)

    def test_dirty_affection_is_zeroed(self):
        for bad in ("abc", None, [], {}):
            with self.subTest(bad=bad):
                self.panel.set_affection(bad, 250)
                self.assertEqual(self.panel.affection(), 0)

    def test_soft_cap_defaults_when_nonsense(self):
        self.panel.set_affection(100, 0)
        self.assertAlmostEqual(self.panel.heart_target(),
                               model.affection_ratio(100, model.SOFT_AFFECTION_CAP), places=6)

    def test_level_title_from_levels_json(self):
        self.panel.set_affection(0)
        first = self.panel.level_title()
        self.panel.set_affection(500)
        self.assertNotEqual(self.panel.level_title(), first)

    def test_level_title_survives_a_broken_levels_table(self):
        self.panel.set_levels("这不是等级表")
        self.assertTrue(self.panel.level_title())

    def test_next_level_text_and_progress(self):
        self.panel.set_affection(0)
        self.assertIn("还差", self.panel._next_level_text())        # noqa: SLF001
        self.assertAlmostEqual(self.panel._level_progress(), 0.0, places=6)  # noqa: SLF001
        self.panel.set_affection(99999)
        self.assertEqual(self.panel._next_level_text(), "—")        # noqa: SLF001
        self.assertAlmostEqual(self.panel._level_progress(), 1.0, places=6)  # noqa: SLF001

    def test_set_today_tolerates_garbage(self):
        self.panel.set_today(gained="x", cap=None, gifts=-3, gift_cap="y")
        self.assertEqual(self.panel._gained_today, 0)               # noqa: SLF001
        self.assertEqual(self.panel._daily_cap, 0)                  # noqa: SLF001
        self.assertEqual(self.panel._gifts_today, 0)                # noqa: SLF001
        self.assertFalse(self.panel.grab().isNull())

    def test_heart_fill_is_clamped(self):
        self.panel.heartFill = 5.0
        self.assertAlmostEqual(self.panel.heart_ratio(), 1.0, places=6)
        self.panel.heartFill = -1.0
        self.assertAlmostEqual(self.panel.heart_ratio(), 0.0, places=6)


class TestInteraction(PanelTestCase):
    def setUp(self):
        super().setUp()
        self.chosen = []
        self.tabs = []
        self.closed = []
        self.panel.item_chosen.connect(self.chosen.append)
        self.panel.tab_changed.connect(self.tabs.append)
        self.panel.close_clicked.connect(lambda: self.closed.append(1))

    def test_clicking_a_card_emits_the_item_name(self):
        for index, item in enumerate(self.panel.items_of("food")):
            self.chosen.clear()
            with self.subTest(index=index):
                click(self.panel, self.panel.card_rect(index).center())
                self.assertEqual(self.chosen, [item["name"]])

    def test_clicking_a_zero_stock_card_still_emits(self):
        """规范 6.1：库存 0 也照发信号 —— controller 用一句气泡说明获取途径，
        比"点了没反应"友好得多。"""
        self.panel.set_inventory({"奶油面包": 0})
        click(self.panel, self.panel.card_rect(0).center())
        self.assertEqual(self.chosen, ["奶油面包"])

    def test_press_and_release_on_different_cards_does_not_emit(self):
        press = QMouseEvent(QEvent.MouseButtonPress,
                            QPointF(self.panel.card_rect(0).center()),
                            QPointF(self.panel.card_rect(0).center()),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        release = QMouseEvent(QEvent.MouseButtonRelease,
                              QPointF(self.panel.card_rect(2).center()),
                              QPointF(self.panel.card_rect(2).center()),
                              Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(self.panel, press)
        QApplication.sendEvent(self.panel, release)
        self.assertEqual(self.chosen, [])

    def test_clicking_a_tab_switches_and_emits(self):
        click(self.panel, self.panel.tab_rect("gift").center())
        self.assertEqual(self.tabs, ["gift"])
        self.assertEqual(self.panel.tab(), "gift")
        self.assertEqual(len(self.panel.items_of("gift")), 2)

    def test_clicking_the_current_tab_does_not_emit(self):
        click(self.panel, self.panel.tab_rect("food").center())
        self.assertEqual(self.tabs, [])

    def test_set_tab_ignores_unknown_names(self):
        self.panel.set_tab("不存在的页")
        self.assertEqual(self.panel.tab(), "food")

    def test_clicking_close_emits_without_hiding(self):
        """面板自己不隐藏 —— 收不收由 `NurtureController` 决定。"""
        click(self.panel, self.panel.close_rect().center())
        self.assertEqual(self.closed, [1])

    def test_clicking_empty_space_does_nothing(self):
        click(self.panel, QPoint(1, 1))
        self.assertEqual((self.chosen, self.tabs, self.closed), ([], [], []))

    def test_tab_hit_testing(self):
        for key in np.TABS:
            self.assertEqual(self.panel.tab_at(self.panel.tab_rect(key).center()), key)
        self.assertIsNone(self.panel.tab_at(self.panel.card_rect(0).center()))

    def test_hover_tracks_the_card_under_the_cursor(self):
        move(self.panel, self.panel.card_rect(1).center())
        self.assertEqual(self.panel._hovered_card, 1)      # noqa: SLF001
        move(self.panel, QPoint(1, 1))
        self.assertIsNone(self.panel._hovered_card)        # noqa: SLF001

    def test_hover_tracks_tab_and_close(self):
        move(self.panel, self.panel.tab_rect("status").center())
        self.assertEqual(self.panel._hovered_tab, "status")   # noqa: SLF001
        move(self.panel, self.panel.close_rect().center())
        self.assertTrue(self.panel._hovered_close)            # noqa: SLF001
        self.assertIsNone(self.panel._hovered_tab)            # noqa: SLF001

    def test_leave_clears_hover_state(self):
        move(self.panel, self.panel.card_rect(0).center())
        QApplication.sendEvent(self.panel, QEvent(QEvent.Leave))
        self.assertIsNone(self.panel._hovered_card)           # noqa: SLF001
        self.assertFalse(self.panel._hovered_close)           # noqa: SLF001


class TestLabels(PanelTestCase):
    def test_every_tab_has_three_languages(self):
        for key in np.TABS:
            with self.subTest(key=key):
                for lang in ("zh", "en", "ja"):
                    self.assertTrue(np.TAB_LABELS[key].get(lang), f"{key}.{lang} 缺失")

    def test_language_switch(self):
        self.panel.apply_language("en")
        self.assertFalse(self.panel.grab().isNull())
        self.panel.apply_language("ja")
        self.assertFalse(self.panel.grab().isNull())

    def test_unknown_language_falls_back_to_zh(self):
        self.panel.apply_language("nonsense")
        self.assertEqual(np._label(np.TAB_LABELS, "food", self.panel._lang), "食物")  # noqa: SLF001


class TestRendering(PanelTestCase):
    """任何状态都要能画出非空位图（图标缺失、库存脏值、空页都不许崩）。"""

    def test_grab_all_tabs(self):
        for tab in np.TABS:
            with self.subTest(tab=tab):
                self.panel.set_tab(tab)
                shot = self.panel.grab()
                self.assertFalse(shot.isNull())
                self.assertEqual(shot.width(), self.panel.width())
                self.assertEqual(shot.height(), self.panel.height())

    def test_grab_with_dirty_state(self):
        self.panel.set_inventory({"奶油面包": "abc"})
        self.panel.set_affection(-5, 0)
        self.panel.set_streak("x")
        self.panel.set_levels([{"bogus": 1}])
        self.panel.set_tab("status")
        self.assertFalse(self.panel.grab().isNull())

    def test_grab_with_unknown_icon_keys(self):
        panel = np.NurturePanel([{"name": "没有图标的", "icon_key": "完全不存在"}])
        self.addCleanup(panel.deleteLater)
        self.assertFalse(panel.grab().isNull())

    def test_grab_with_a_very_long_item_name(self):
        panel = np.NurturePanel([{"name": "名字特别特别长的一个食物" * 2}])
        self.addCleanup(panel.deleteLater)
        self.assertFalse(panel.grab().isNull())

    def test_real_items_json_renders(self):
        with open(ITEMS_JSON, "r", encoding="utf-8") as handle:
            items = json.load(handle)["items"]
        panel = np.NurturePanel(items)
        self.addCleanup(panel.deleteLater)
        panel.set_inventory({str(i["name"]): 2 for i in items})
        for tab in np.TABS:
            panel.set_tab(tab)
            self.assertFalse(panel.grab().isNull())


if __name__ == "__main__":
    unittest.main(verbosity=2)
