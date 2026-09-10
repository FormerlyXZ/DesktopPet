"""`src/hover_menu.py` 单测 —— 几何落位、按钮状态、信号、焦点约束。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

需要 `QApplication`（`QWidget` 依赖 GUI 后端），但**不显示任何窗口**。
鼠标事件用 `QMouseEvent` 手工构造后 `QApplication.sendEvent()` 投递，
不依赖真实光标位置，因此在无人值守的机器上也是确定性的。

> **真正无法自动化的是"鼠标从人物移到菜单上能不能点到"** —— 那涉及真实的鼠标轨迹、
> 窗口 z-order 与 Windows 的消息投递。这一条只能在暂停点 C 由人实机验收
> （`tests/test_nurture_pet_hover.py` 覆盖了它的状态机部分，见那里的说明）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src import hover_menu as hm  # noqa: E402

_APP = None


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


def click(widget, pos: QPoint) -> None:
    """在 `pos` 处投递一次完整的 按下→抬起（不依赖真实光标）。"""
    for event_type, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                                (QEvent.MouseButtonRelease, Qt.NoButton)):
        event = QMouseEvent(event_type, QPointF(pos), QPointF(pos),
                            Qt.LeftButton, buttons, Qt.NoModifier)
        QApplication.sendEvent(widget, event)


class TestButtonSize(unittest.TestCase):
    """按钮直径公式：`clamp(36, 桌宠高度 × 0.11, 52)`（规范 5.1 / 第 10 节）。"""

    def test_clamped_to_bounds(self):
        cases = [(250, 36), (300, 36), (327, 36), (400, 44), (473, 52),
                 (500, 52), (700, 52), (2000, 52)]
        for height, expected in cases:
            with self.subTest(height=height):
                self.assertEqual(hm.button_size_for(height), expected)

    def test_does_not_scale_below_250(self):
        self.assertEqual(hm.button_size_for(0), hm.MIN_BUTTON)
        self.assertEqual(hm.button_size_for(-100), hm.MIN_BUTTON)

    def test_dirty_height_does_not_raise(self):
        for bad in (None, "abc", "", [], {}):
            with self.subTest(bad=bad):
                size = hm.button_size_for(bad)
                self.assertGreaterEqual(size, hm.MIN_BUTTON)
                self.assertLessEqual(size, hm.MAX_BUTTON)


class TestLayout(unittest.TestCase):
    """横向 / 竖向排布与按钮矩形。"""

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)

    def test_default_items(self):
        self.assertEqual(self.menu.item_keys(), list(hm.DEFAULT_ITEMS))
        self.assertEqual(len(self.menu.item_keys()), 7)

    def test_horizontal_geometry(self):
        self.menu.set_button_size(44)
        self.menu.set_orientation("h")
        n = len(self.menu.item_keys())
        d = 44
        self.assertEqual(self.menu.width(), hm.MARGIN * 2 + hm.PAD * 2 + n * d + (n - 1) * hm.GAP)
        self.assertEqual(self.menu.height(), hm.MARGIN * 2 + hm.TOOLTIP_H + hm.PAD * 2 + d)

    def test_vertical_geometry(self):
        self.menu.set_button_size(44)
        self.menu.set_orientation("v")
        n = len(self.menu.item_keys())
        d = 44
        self.assertEqual(self.menu.width(), hm.MARGIN * 2 + hm.PAD * 2 + d)
        self.assertEqual(self.menu.height(),
                         hm.MARGIN * 2 + hm.TOOLTIP_H + hm.PAD * 2 + n * d + (n - 1) * hm.GAP)
        self.assertEqual(self.menu.orientation(), "v")

    def test_buttons_are_circles_inside_the_pill(self):
        self.menu.set_button_size(44)
        for orientation in ("h", "v"):
            with self.subTest(orientation=orientation):
                self.menu.set_orientation(orientation)
                pill = self.menu.pill_rect()
                seen = []
                for key in self.menu.item_keys():
                    rect = self.menu.button_rect(key)
                    self.assertEqual(rect.width(), rect.height())      # 正圆
                    self.assertTrue(pill.contains(rect), f"{key} 超出胶囊")
                    seen.append(rect)
                # 相邻按钮不重叠
                seen.sort(key=lambda r: (r.y(), r.x()))
                for a, b in zip(seen, seen[1:]):
                    self.assertFalse(a.intersects(b), f"{a} 与 {b} 重叠")

    def test_hit_testing(self):
        self.menu.set_button_size(44)
        self.menu.set_orientation("h")
        for key in self.menu.item_keys():
            rect = self.menu.button_rect(key)
            with self.subTest(key=key):
                self.assertEqual(self.menu._key_at(rect.center()), key)      # noqa: SLF001
        self.assertIsNone(self.menu._key_at(QPoint(0, 0)))                   # noqa: SLF001
        self.assertIsNone(self.menu._key_at(self.menu.rect().bottomRight()))  # noqa: SLF001

    def test_set_items_relayouts(self):
        self.menu.set_button_size(44)
        wide = self.menu.width()
        self.menu.set_items(["feed", "settings"])
        self.assertLess(self.menu.width(), wide)
        self.assertEqual(self.menu.item_keys(), ["feed", "settings"])
        self.assertTrue(self.menu.pill_rect().isValid())

    def test_set_items_falls_back_to_defaults_when_empty(self):
        self.menu.set_items([])
        self.assertEqual(self.menu.item_keys(), list(hm.DEFAULT_ITEMS))

    def test_adding_a_new_item_gets_default_state(self):
        self.menu.set_items(["feed", "chat"])
        self.assertTrue(self.menu.is_enabled("feed"))
        self.assertTrue(self.menu.is_enabled("chat"))

    def test_set_button_size_is_clamped(self):
        self.menu.set_button_size(999)
        self.assertEqual(self.menu.button_size(), hm.MAX_BUTTON)
        self.menu.set_button_size(1)
        self.assertEqual(self.menu.button_size(), hm.MIN_BUTTON)


class TestPlacement(unittest.TestCase):
    """落位：**恒定贴人物下方**（水平居中）→ 越界夹紧 → 极窄屏转竖排。

    **这是本组件最需要自动化验证的部分**：菜单会不会跑到屏幕外、会不会压到人物身上，
    肉眼一次只能验一个位置，这里把边界位置全部跑一遍。
    """

    SCREEN = QRect(0, 0, 1920, 1080)

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)
        self.menu.set_button_size(44)

    # ── 断言口径：间距一律从**胶囊边缘**量，而不是窗口边缘 ──
    # 窗口在胶囊外还留了 MARGIN 的投影空间 + TOOLTIP_H 的提示条预留带，
    # 拿窗口边缘去量会出现 6/32px 的"假间距"，那是影子不是空隙。

    def _pill_top(self, rect: QRect) -> int:
        return rect.top() + self.menu.pill_rect().top()

    def test_sits_below_and_centers_on_the_pet(self):
        pet = QRect(800, 400, 300, 500)
        orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
        self.assertEqual(orientation, "h")
        # 胶囊顶边与人物底边之间正好隔 GAP
        self.assertEqual(self._pill_top(rect) - pet.bottom() - 1, hm.GAP_FROM_PET)
        self.assertEqual(rect.center().x(), pet.center().x())     # 水平居中对齐
        self.assertTrue(self.SCREEN.contains(rect))

    def test_stays_below_even_when_the_pet_hugs_the_screen_top(self):
        """人物贴着屏幕顶边时**也**在下方 —— 不再翻到上方（规范 5.1 第二次修订）。"""
        pet = QRect(800, 10, 300, 500)
        orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
        self.assertEqual(orientation, "h")
        self.assertEqual(self._pill_top(rect) - pet.bottom() - 1, hm.GAP_FROM_PET)
        self.assertEqual(rect.center().x(), pet.center().x())
        self.assertFalse(rect.intersects(pet))

    def test_never_leaves_the_screen(self):
        """不变量：人物在屏幕各处（含四角、上下越界）时，菜单都必须完整落在屏幕可用区内。"""
        for x in (0, 100, 800, 1600, 1620):
            for y in (-80, 0, 10, 120, 400, 580, 780, 1000):
                for height in (300, 500):
                    pet = QRect(x, y, 300, height)
                    with self.subTest(x=x, y=y, height=height):
                        _orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
                        self.assertTrue(self.SCREEN.contains(rect), rect)

    def test_does_not_overlap_the_pet_when_there_is_room_below(self):
        """下方放得下时，菜单必须既不压到人物身上也不出屏幕（"贴下方"的常态）。"""
        for y in (0, 10, 120, 400, 580, 680):
            pet = QRect(800, y, 300, 300)
            with self.subTest(y=y):
                bottom = self.menu._below_y(pet)                     # noqa: SLF001
                self.assertLessEqual(bottom + self.menu.height(),
                                     self.SCREEN.bottom() + 1,
                                     "测试前提不成立：这个位置其实放不下")
                _orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
                self.assertFalse(rect.intersects(pet), rect)

    def test_clamped_onto_the_pet_when_there_is_no_room_below(self):
        """人物几乎占满屏幕高 → 下方没地方 → 夹紧进屏幕（会压住她下半身，这是刻意的取舍）。

        取舍理由：遮住她还能把她拖上来，让按钮掉到屏幕外就是彻底点不到了。
        """
        pet = QRect(700, 0, 300, 1080)
        _orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
        self.assertTrue(self.SCREEN.contains(rect), rect)
        self.assertEqual(rect.center().x(), pet.center().x())   # 仍然水平居中
        self.assertTrue(rect.intersects(pet), "这一档本来就该被顶到人物身上")

    def test_tooltip_band_is_always_below_the_pill(self):
        """提示条必须**背离人物**：菜单恒在人物下方 → 提示条恒在胶囊下方。

        反过来（提示条朝上）它会挤在胶囊和人物之间 —— 既贴脸，还会让窗口压住人物窗口，
        那一块透明区域会吃掉鼠标事件，人物就点不到了。
        """
        for pet in (QRect(800, 400, 300, 500), QRect(800, 10, 300, 500),
                    QRect(800, 900, 300, 300)):
            with self.subTest(pet=pet):
                self.menu.plan_placement(pet, self.SCREEN)
                self.assertEqual(self.menu.tooltip_side(), hm.TOOLTIP_SIDE)
                self.assertEqual(self.menu.tooltip_side(), "bottom")
                # 胶囊贴在窗口上沿：窗口顶边 = 胶囊顶边 - MARGIN（MARGIN 是留投影的）
                self.assertEqual(self.menu.pill_rect().top(), hm.MARGIN)
                # 提示条画在胶囊**下方**，且完整落在窗口内
                self.menu._hovered_key = "feed"                  # noqa: SLF001
                tip = self.menu.tooltip_rect()
                self.assertGreater(tip.top(), self.menu.pill_rect().bottom(), tip)
                self.assertTrue(self.menu.rect().contains(tip), tip)

    def test_window_size_does_not_depend_on_tooltip_side(self):
        """窗口尺寸与提示条朝向无关 —— `plan_placement()` 才能先定朝向再算落位。"""
        self.menu.set_tooltip_side("top")
        before = (self.menu.width(), self.menu.height())
        self.menu.set_tooltip_side("bottom")
        self.assertEqual((self.menu.width(), self.menu.height()), before)

    def test_tooltip_side_setter_ignores_garbage(self):
        """传错值不该把提示条翻到人物那一侧（那会让窗口压住人物、吃掉鼠标事件）。"""
        self.assertEqual(self.menu.tooltip_side(), "bottom")
        for bad in ("nonsense", None, "", 0, [], "TOP"):
            with self.subTest(bad=bad):
                self.menu.set_tooltip_side(bad)
                self.assertEqual(self.menu.tooltip_side(), "bottom")
        self.menu.set_tooltip_side("top")           # 合法值仍然生效（预览/测试用）
        self.assertEqual(self.menu.tooltip_side(), "top")

    def test_tooltip_stays_inside_the_window_and_off_the_pill(self):
        """提示条不许画到窗口外，也不许压到胶囊上（否则是「文字糊在按钮上」）。"""
        self.menu.set_button_size(44)
        self.menu.set_orientation("h")
        for side in ("top", "bottom"):
            for key in self.menu.item_keys():
                with self.subTest(side=side, key=key):
                    self.menu.set_tooltip_side(side)
                    self.menu._hovered_key = key            # noqa: SLF001
                    rect = self.menu.tooltip_rect()
                    pill = self.menu.pill_rect()
                    self.assertTrue(self.menu.rect().contains(rect), rect)
                    self.assertFalse(rect.intersects(pill), rect)
                    self.assertGreaterEqual(rect.left(), hm.MARGIN)
                    if side == "top":
                        self.assertLess(rect.bottom(), pill.top())
                    else:
                        self.assertGreater(rect.top(), pill.bottom())

    def test_goes_vertical_when_the_pill_is_wider_than_the_screen(self):
        narrow = QRect(0, 0, 300, 1400)
        pet = QRect(0, 600, 300, 400)
        orientation, rect = self.menu.plan_placement(pet, narrow)
        self.assertEqual(orientation, "v")
        self.assertTrue(narrow.contains(rect), rect)
        # 竖排再高也还是"贴下方"：菜单整体落在人物**下半身之下**（这里被屏幕底边夹紧了一点）
        self.assertGreater(rect.top(), pet.center().y())

    def test_clamped_when_screen_is_absurdly_narrow(self):
        tiny = QRect(0, 0, 120, 900)
        pet = QRect(0, 200, 120, 500)
        orientation, rect = self.menu.plan_placement(pet, tiny)
        self.assertEqual(orientation, "v")
        self.assertGreaterEqual(rect.left(), tiny.left())
        self.assertLessEqual(rect.right(), tiny.right())
        self.assertGreaterEqual(rect.top(), tiny.top())
        self.assertLessEqual(rect.bottom(), tiny.bottom())

    def test_respects_screen_offset(self):
        """副屏（原点不为 0）也要夹紧到那块屏幕的可用区。"""
        second = QRect(1920, 0, 1280, 1024)
        pet = QRect(1920 + 1200, 300, 300, 500)
        _orientation, rect = self.menu.plan_placement(pet, second)
        self.assertTrue(second.contains(rect), rect)
        self.assertFalse(rect.intersects(pet))

    def test_clamped_vertically_at_screen_bottom(self):
        pet = QRect(800, self.SCREEN.bottom() - 200, 300, 200)
        _orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
        self.assertLessEqual(rect.bottom(), self.SCREEN.bottom())
        self.assertGreaterEqual(rect.top(), self.SCREEN.top())

    def test_clamped_vertically_at_screen_top(self):
        pet = QRect(800, -50, 300, 200)
        _orientation, rect = self.menu.plan_placement(pet, self.SCREEN)
        self.assertGreaterEqual(rect.top(), self.SCREEN.top())

    def test_orientation_is_recomputed_from_scratch_each_time(self):
        """上一次弹成竖排后，下一次横排放得下时要能切回横排。"""
        narrow = QRect(0, 0, 300, 1400)
        self.menu.plan_placement(QRect(0, 600, 300, 400), narrow)
        self.assertEqual(self.menu.orientation(), "v")
        self.menu.plan_placement(QRect(800, 400, 300, 500), self.SCREEN)
        self.assertEqual(self.menu.orientation(), "h")

    def test_popup_offset_always_points_down(self):
        """滑动方向必须背离人物：菜单恒在下方 → 恒朝下滑。"""
        offset = self.menu._popup_offset()                          # noqa: SLF001
        self.assertEqual((offset.x(), offset.y()), (0, hm.DRAG_OUT_OFFSET))

    def test_popup_starts_below_the_target_and_slides_up(self):
        """入场位移：从**下方** 12px 处滑上来（从背离人物那一侧滑回来）。

        方向写反的话，入场时菜单会从人物身上"掉"下来，而且弹出瞬间位置差 12px
        —— 这正是阶段 E 在真实素材验证里抓到过的那类 bug。
        """
        pet = QRect(800, 400, 300, 500)
        self.menu.popup_near(pet, pet_height=500)
        group = self.menu._show_anim                                 # noqa: SLF001
        self.assertIsNotNone(group)
        self.menu._stop_anim()                                       # noqa: SLF001
        pos_anim = group.animationAt(0)
        start, end = pos_anim.startValue(), pos_anim.endValue()
        self.assertEqual(start.y() - end.y(), hm.DRAG_OUT_OFFSET)
        self.assertEqual(self.menu.pos().y(), start.y())
        self.menu.hide_now()

    def test_popup_near_uses_button_size_from_pet_height(self):
        self.menu.popup_near(QRect(800, 400, 300, 250), pet_height=250)
        self.assertEqual(self.menu.button_size(), 36)
        self.menu.popup_near(QRect(800, 400, 300, 700), pet_height=700)
        self.assertEqual(self.menu.button_size(), hm.MAX_BUTTON)



class TestWindowFlags(unittest.TestCase):
    """窗口标志：绝不抢焦点、绝不实现 focusOutEvent 收起。"""

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)

    def test_does_not_accept_focus(self):
        self.assertTrue(bool(self.menu.windowFlags() & Qt.WindowDoesNotAcceptFocus))

    def test_show_without_activating(self):
        self.assertTrue(self.menu.testAttribute(Qt.WA_ShowWithoutActivating))

    def test_translucent_and_frameless_and_topmost(self):
        flags = self.menu.windowFlags()
        self.assertTrue(bool(flags & Qt.FramelessWindowHint))
        self.assertTrue(bool(flags & Qt.WindowStaysOnTopHint))
        self.assertTrue(bool(flags & Qt.Tool))
        self.assertTrue(self.menu.testAttribute(Qt.WA_TranslucentBackground))

    def test_does_not_override_focus_out(self):
        """与 `BubblePanel` 相反：菜单靠宽限期收起，不能自己抢焦点后自动关。"""
        self.assertIs(hm.HoverMenu.focusOutEvent, QWidget.focusOutEvent)

    def test_mouse_tracking_enabled(self):
        self.assertTrue(self.menu.hasMouseTracking())


class TestActions(unittest.TestCase):
    """点击 → `action_triggered`；HoverMenu 自身不做任何业务判断。"""

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)
        self.menu.set_button_size(44)
        self.menu.set_orientation("h")
        self.fired = []
        self.menu.action_triggered.connect(self.fired.append)

    def test_click_emits_action(self):
        for key in self.menu.item_keys():
            self.fired.clear()
            with self.subTest(key=key):
                click(self.menu, self.menu.button_rect(key).center())
                self.assertEqual(self.fired, [key])

    def test_disabled_item_still_emits(self):
        """规范 5.1：不可用项置灰但**仍可点击**，由 controller 出说明气泡。"""
        self.menu.set_enabled_map({"gift": False})
        self.assertFalse(self.menu.is_enabled("gift"))
        click(self.menu, self.menu.button_rect("gift").center())
        self.assertEqual(self.fired, ["gift"])

    def test_press_and_release_on_different_buttons_does_not_fire(self):
        press = QMouseEvent(QEvent.MouseButtonPress,
                            QPointF(self.menu.button_rect("feed").center()),
                            QPointF(self.menu.button_rect("feed").center()),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        release = QMouseEvent(QEvent.MouseButtonRelease,
                              QPointF(self.menu.button_rect("heart").center()),
                              QPointF(self.menu.button_rect("heart").center()),
                              Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(self.menu, press)
        QApplication.sendEvent(self.menu, release)
        self.assertEqual(self.fired, [])

    def test_click_on_empty_area_does_not_fire(self):
        click(self.menu, QPoint(1, 1))
        self.assertEqual(self.fired, [])

    def test_enter_and_leave_emit_menu_signals(self):
        entered, left = [], []
        self.menu.menu_entered.connect(lambda: entered.append(1))
        self.menu.menu_left.connect(lambda: left.append(1))
        QApplication.sendEvent(self.menu, QEvent(QEvent.Enter))
        QApplication.sendEvent(self.menu, QEvent(QEvent.Leave))
        self.assertEqual(entered, [1])
        self.assertEqual(left, [1])

    def test_leave_clears_hover_state(self):
        move = QMouseEvent(QEvent.MouseMove,
                           QPointF(self.menu.button_rect("chat").center()),
                           QPointF(self.menu.button_rect("chat").center()),
                           Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(self.menu, move)
        self.assertEqual(self.menu._hovered_key, "chat")        # noqa: SLF001
        QApplication.sendEvent(self.menu, QEvent(QEvent.Leave))
        self.assertIsNone(self.menu._hovered_key)               # noqa: SLF001


class TestLabels(unittest.TestCase):
    """按钮文案与三语切换（阶段 H 会搬进 `translations.py`）。"""

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)

    def test_labels_exist_for_every_default_item(self):
        for key in hm.DEFAULT_ITEMS:
            with self.subTest(key=key):
                self.assertIn(key, hm.LABELS)
                for lang in ("zh", "en", "ja"):
                    self.assertTrue(hm.LABELS[key].get(lang), f"{key}.{lang} 缺失")

    def test_language_switch(self):
        self.menu.apply_language("en")
        self.assertEqual(self.menu.label_of("feed"), "Feed")
        self.menu.apply_language("ja")
        self.assertEqual(self.menu.label_of("feed"), "ごはん")
        self.menu.apply_language("zh")
        self.assertEqual(self.menu.label_of("feed"), "喂食")

    def test_unknown_language_falls_back_to_zh(self):
        self.menu.apply_language("nonsense")
        self.assertEqual(self.menu.label_of("feed"), "喂食")

    def test_unknown_key_falls_back_to_the_key_itself(self):
        self.assertEqual(self.menu.label_of("完全不存在的按钮"), "完全不存在的按钮")


class TestBadgesAndState(unittest.TestCase):
    """红点角标与可用状态。"""

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)

    def test_badge_toggle(self):
        self.menu.set_badge("checkin", True)
        self.assertTrue(self.menu._badges["checkin"])   # noqa: SLF001
        self.menu.set_badge("checkin", False)
        self.assertFalse(self.menu._badges["checkin"])  # noqa: SLF001

    def test_badge_on_unknown_key_is_ignored(self):
        self.menu.set_badge("不存在的按钮", True)       # 不应抛异常
        self.assertNotIn("不存在的按钮", self.menu._badges)  # noqa: SLF001

    def test_enabled_map_ignores_unknown_keys(self):
        self.menu.set_enabled_map({"feed": False, "不存在": False})
        self.assertFalse(self.menu.is_enabled("feed"))
        self.assertNotIn("不存在", self.menu._enabled)  # noqa: SLF001

    def test_enabled_map_tolerates_garbage(self):
        self.menu.set_enabled_map(None)
        self.menu.set_enabled_map("abc")
        self.menu.set_enabled_map([1, 2])
        self.assertTrue(self.menu.is_enabled("feed"))


class TestVisibility(unittest.TestCase):
    """显示 / 收起的幂等性（宽限期可能重复调用 hide_with_anim）。"""

    def setUp(self):
        self.menu = hm.HoverMenu()
        self.addCleanup(self.menu.deleteLater)

    def test_hide_with_anim_on_a_hidden_menu_is_a_noop(self):
        self.assertFalse(self.menu.isVisible())
        self.menu.hide_with_anim()          # 不应抛异常
        self.assertFalse(self.menu.isVisible())

    def test_hide_now(self):
        self.menu.show()
        self.assertTrue(self.menu.isVisible())
        self.menu.hide_now()
        self.assertFalse(self.menu.isVisible())
        self.assertAlmostEqual(self.menu.windowOpacity(), 1.0, places=3)

    def test_under_mouse_false_when_hidden(self):
        self.assertFalse(self.menu.under_mouse())


class TestRendering(unittest.TestCase):
    """绘制：任何状态下都要能出非空位图（图标缺失也不许崩）。"""

    def test_grab_all_states(self):
        menu = hm.HoverMenu()
        self.addCleanup(menu.deleteLater)
        menu.set_button_size(44)
        for orientation in ("h", "v"):
            for hovered in (None, "feed", "headpat"):
                with self.subTest(orientation=orientation, hovered=hovered):
                    menu.set_orientation(orientation)
                    menu._hovered_key = hovered            # noqa: SLF001
                    menu._tooltip_opacity = 1.0 if hovered else 0.0   # noqa: SLF001
                    shot = menu.grab()
                    self.assertFalse(shot.isNull())
                    self.assertGreater(shot.width(), 50)

    def test_grab_with_disabled_and_badges(self):
        menu = hm.HoverMenu()
        self.addCleanup(menu.deleteLater)
        menu.set_enabled_map({k: False for k in menu.item_keys()})
        menu.set_badge("checkin", True)
        menu.set_badge("heart", True)
        self.assertFalse(menu.grab().isNull())

    def test_grab_with_unknown_item_key_falls_back(self):
        """controller 传了个没配图标的按钮键 → emoji/首字兜底，不该崩。"""
        menu = hm.HoverMenu(items=["feed", "完全没这个图标", "settings"])
        self.addCleanup(menu.deleteLater)
        self.assertFalse(menu.grab().isNull())


if __name__ == "__main__":
    unittest.main(verbosity=2)
