"""`src/speech_bubble.py` 单测 —— 落位、断行、穿透、以及"绝不能抢焦点"。

这是养成系统里唯一**直接压在用户输入路径上**的组件，所以除了几何之外，
还专门盯两件事：

| 盯什么 | 怎么盯 |
|--------|--------|
| 绝不抢焦点 | 窗口标志 + 不重写 `focusOutEvent` + `focusPolicy == NoFocus` |
| 鼠标完全穿透 | `WindowTransparentForInput` + `WA_TransparentForMouseEvents` + **不重写任何鼠标事件**（否则就是靠吞事件"假装穿透"） |

几何断言一律**显式传屏幕矩形**（`layout_for(pet, SCREEN)`）：不传的话它会去问
`QApplication.screenAt()`，结果就取决于跑测试的这台机器分辨率 —— 又是"结果取决于环境"的老坑。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src import speech_bubble as sb  # noqa: E402

_APP = None
SCREEN = QRect(0, 0, 1920, 1080)


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


def wait_until(predicate, timeout_ms: int = 1500, step_ms: int = 10) -> bool:
    """轮询等条件成立。**不用固定 sleep** —— 动画时长不是我们能控制的量。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(step_ms / 1000.0)
    return predicate()


class BubbleTestCase(unittest.TestCase):
    def setUp(self):
        self.bubble = sb.SpeechBubble()
        self.addCleanup(self.bubble.deleteLater)
        self.bubble._text = "唔，好吃。"        # noqa: SLF001 - 直接摆文字，避免走动画

    def layout(self, pet, text=None, ratio=None, screen=SCREEN):
        if text is not None:
            self.bubble._text = text            # noqa: SLF001
        if ratio is not None:
            self.bubble._anchor_ratio = ratio   # noqa: SLF001
        return self.bubble.layout_for(pet, screen)


class TestWrapText(unittest.TestCase):
    """断行是纯函数 —— **不能按字数估算**，中日文与拉丁字母宽度差一倍多。"""

    def setUp(self):
        self.font = sb.make_font()

    def test_short_text_is_one_line(self):
        lines = sb.wrap_text("唔，好吃。", self.font, 200)
        self.assertEqual(lines, ["唔，好吃。"])

    def test_long_chinese_text_wraps(self):
        text = "今天的工作看起来很忙呢，我先安静一会儿，等你空下来再一起吃点心吧。"
        lines = sb.wrap_text(text, self.font, 190)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(
                sb.QFontMetrics(self.font).horizontalAdvance(line), 190,
                f"这一行超宽了：{line}")

    def test_respects_max_lines_and_adds_ellipsis(self):
        text = "这个真的特别特别好吃，" * 6
        lines = sb.wrap_text(text, self.font, 190, max_lines=4)
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[-1].endswith("…"), lines[-1])

    def test_no_ellipsis_when_it_fits(self):
        lines = sb.wrap_text("今天天气不错。", self.font, 190, max_lines=4)
        self.assertFalse(any(line.endswith("…") for line in lines))

    def test_explicit_newlines_are_kept(self):
        lines = sb.wrap_text("第一行\n第二行", self.font, 190)
        self.assertEqual(lines, ["第一行", "第二行"])

    def test_blank_text(self):
        self.assertEqual(sb.wrap_text("", self.font, 190), [""])
        self.assertEqual(sb.wrap_text(None, self.font, 190), [""])

    def test_very_narrow_width_does_not_hang(self):
        lines = sb.wrap_text("这是一段比较长的中文台词", self.font, 4)
        self.assertTrue(lines)
        self.assertLessEqual(len(lines), sb.MAX_LINES)

    def test_long_latin_word_is_broken(self):
        lines = sb.wrap_text("supercalifragilisticexpialidocious", self.font, 60)
        self.assertGreater(len(lines), 1)

    def test_latin_break_prefers_a_separator(self):
        lines = sb.wrap_text("hello world foo bar baz", self.font, 80)
        self.assertTrue(all(line == line.strip() for line in lines), lines)


class TestWindowFlags(unittest.TestCase):
    """焦点与鼠标：四条硬约束，破一条就是严重事故。"""

    def setUp(self):
        self.bubble = sb.SpeechBubble()
        self.addCleanup(self.bubble.deleteLater)

    def test_never_takes_focus(self):
        self.assertTrue(bool(self.bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus))
        self.assertTrue(self.bubble.testAttribute(Qt.WA_ShowWithoutActivating))
        self.assertEqual(self.bubble.focusPolicy(), Qt.NoFocus)

    def test_mouse_passes_through(self):
        self.assertTrue(bool(self.bubble.windowFlags() & Qt.WindowTransparentForInput))
        self.assertTrue(self.bubble.testAttribute(Qt.WA_TransparentForMouseEvents))

    def test_does_not_swallow_mouse_events_by_hand(self):
        """鼠标穿透必须靠窗口标志，**不是**靠把事件吞掉。"""
        for name in ("mousePressEvent", "mouseReleaseEvent", "mouseMoveEvent",
                     "enterEvent", "leaveEvent", "focusOutEvent"):
            with self.subTest(name=name):
                self.assertIs(getattr(sb.SpeechBubble, name), getattr(QWidget, name))

    def test_translucent_frameless_topmost(self):
        flags = self.bubble.windowFlags()
        self.assertTrue(bool(flags & Qt.FramelessWindowHint))
        self.assertTrue(bool(flags & Qt.WindowStaysOnTopHint))
        self.assertTrue(bool(flags & Qt.Tool))
        self.assertTrue(self.bubble.testAttribute(Qt.WA_TranslucentBackground))

    def test_window_is_not_shown_at_construction(self):
        self.assertFalse(self.bubble.isVisible())
        self.assertFalse(self.bubble.is_showing())


class TestMeasure(BubbleTestCase):
    """宽度自适应 `[120, 220]`，高度 = 内边距 + 行高 × 行数 + 尾巴 + 投影留白。"""

    def test_short_text_hits_the_minimum_width(self):
        self.layout(QRect(800, 400, 300, 500), text="唔。")
        self.assertEqual(self.bubble.width(), sb.MIN_WIDTH + sb.MARGIN * 2)

    def test_long_text_hits_the_maximum_width(self):
        self.layout(QRect(800, 400, 300, 500), text="这是一段很长的台词。" * 4)
        self.assertEqual(self.bubble.width(), sb.MAX_WIDTH + sb.MARGIN * 2)

    def test_height_follows_line_count(self):
        self.layout(QRect(800, 400, 300, 500), text="唔。")
        one = self.bubble.height()
        self.layout(QRect(800, 400, 300, 500), text="这是一段很长的台词。" * 4)
        self.assertGreater(self.bubble.height(), one)
        line_h = max(1, int(round(sb.FONT_PX * sb.LINE_SPACING)))
        self.assertEqual(
            self.bubble.height(),
            sb.MARGIN * 2 + sb.TAIL_H + sb.PAD_Y * 2 + line_h * len(self.bubble.lines()))

    def test_width_never_exceeds_the_maximum(self):
        for text in ("短。", "中等长度的一句话在这里。", "很长很长的一句话。" * 6):
            with self.subTest(text=text[:8]):
                self.layout(QRect(800, 400, 300, 500), text=text)
                self.assertLessEqual(self.bubble.width(), sb.MAX_WIDTH + sb.MARGIN * 2)
                self.assertGreaterEqual(self.bubble.width(), sb.MIN_WIDTH + sb.MARGIN * 2)


class TestPlacement(BubbleTestCase):
    """落位：常态尾巴朝下对准头顶 14%；上方放不下 → 翻到人物下方、尾巴朝上。"""

    def test_above_with_the_tail_on_the_head(self):
        pet = QRect(800, 400, 300, 500)
        side, rect = self.layout(pet)
        self.assertEqual(side, "bottom")
        tip = self.bubble.tail_tip()
        self.assertEqual(tip.y(), pet.top() + int(pet.height() * 0.14))
        self.assertEqual(rect.center().x(), pet.center().x())
        self.assertTrue(SCREEN.contains(rect), rect)

    def test_body_is_above_the_tail_tip(self):
        pet = QRect(800, 400, 300, 500)
        self.layout(pet)
        body = self.bubble.body_rect()
        global_bottom = self.bubble.y() + body.bottom()
        self.assertLess(global_bottom, pet.top() + int(pet.height() * 0.14))

    def test_custom_anchor_ratio(self):
        pet = QRect(800, 400, 300, 500)
        self.layout(pet, ratio=0.3)
        self.assertEqual(self.bubble.tail_tip().y(), pet.top() + 150)

    def test_flips_below_when_there_is_no_room_above(self):
        pet = QRect(800, 0, 300, 500)
        side, rect = self.layout(pet, text="这是一段比较长的台词。" * 2)
        self.assertEqual(side, "top")
        self.assertEqual(self.bubble.tail_tip().y(), pet.bottom() + 1)
        self.assertGreaterEqual(rect.top(), SCREEN.top())

    def test_flipped_bubble_does_not_cover_the_pet(self):
        """翻到下方时锚点必须改成**人物底边**：还用头顶的 14% 会让气泡压在她身上。"""
        pet = QRect(800, 0, 300, 500)
        self.layout(pet, text="这是一段比较长的台词。" * 2)
        body_top_global = self.bubble.y() + self.bubble.body_rect().top()
        self.assertGreater(body_top_global, pet.bottom())

    def test_clamped_at_the_left_screen_edge(self):
        pet = QRect(0, 400, 300, 500)
        _side, rect = self.layout(pet)
        self.assertGreaterEqual(rect.left(), SCREEN.left())
        self.assertTrue(SCREEN.contains(rect), rect)

    def test_clamped_at_the_right_screen_edge(self):
        pet = QRect(SCREEN.right() - 300, 400, 300, 500)
        _side, rect = self.layout(pet)
        self.assertLessEqual(rect.right(), SCREEN.right())
        self.assertTrue(SCREEN.contains(rect), rect)

    def test_tail_stays_inside_the_body_when_clamped(self):
        """气泡被夹到屏幕边时，尾巴要跟着收进主体内，不能飘到气泡外面。"""
        for x in (0, 60, SCREEN.right() - 300, SCREEN.right() - 120):
            with self.subTest(x=x):
                pet = QRect(x, 400, 300, 500)
                self.layout(pet)
                body = self.bubble.body_rect()
                cx = self.bubble._tail_cx                # noqa: SLF001
                self.assertGreater(cx, body.left())
                self.assertLess(cx, body.right())

    def test_clamped_vertically_when_the_screen_is_short(self):
        short = QRect(0, 0, 1920, 200)
        pet = QRect(800, 0, 300, 200)
        _side, rect = self.layout(pet, text="很长的一句台词。" * 3, screen=short)
        self.assertTrue(short.contains(rect), rect)

    def test_respects_secondary_screen_offset(self):
        second = QRect(1920, 0, 1280, 1024)
        pet = QRect(1920 + 600, 300, 300, 500)
        _side, rect = self.layout(pet, screen=second)
        self.assertTrue(second.contains(rect), rect)

    def test_dirty_pet_geometry_does_not_raise(self):
        for bad in (QRect(), None, "abc"):
            with self.subTest(bad=bad):
                try:
                    self.bubble.layout_for(bad, SCREEN)
                except Exception as exc:            # noqa: BLE001
                    self.fail(f"layout_for({bad!r}) 抛了 {exc!r}")


class TestTailRendering(BubbleTestCase):
    """尾巴必须画在**主体外面**。

    初版把三角画在主体矩形内部（底边 = 主体底边 − 尾巴高、尖 = 主体底边），
    整条尾巴都被圆角矩形盖住了 —— 肉眼看就是"没有尾巴"。这个测试专门盯它。
    """

    def _shot(self):
        self.bubble.setWindowOpacity(1.0)
        return self.bubble.grab().toImage()

    def test_tail_pixels_are_not_transparent(self):
        pet = QRect(800, 400, 300, 500)
        self.layout(pet)
        image = self._shot()
        body = self.bubble.body_rect()
        cx = self.bubble._tail_cx                        # noqa: SLF001
        mid_y = body.bottom() + max(1, sb.TAIL_H // 2)
        color = image.pixelColor(cx, mid_y)
        self.assertGreater(color.alpha(), 0, "尾巴中段是透明的 —— 尾巴没画出来")
        # 再往下一行：尾巴已经收尖，应该基本是空的（证明它是个尖三角而不是矩形）
        tip_y = body.bottom() + sb.TAIL_H - 1
        below = image.pixelColor(cx, min(tip_y + 2, image.height() - 1))
        self.assertLess(below.alpha(), 255)

    def test_body_has_an_opaque_fill(self):
        self.layout(QRect(800, 400, 300, 500))
        image = self._shot()
        body = self.bubble.body_rect()
        # 采样点要避开文字（正文是深色，采到它就只能证明"画了字"）：
        # 取主体右上角内侧 10px，圆角半径 14 → 该点仍在形状内
        color = image.pixelColor(body.right() - 10, body.top() + 10)
        self.assertGreater(color.alpha(), 200)
        # 规范 5.3：底 rgba(255,249,246,·)。只比色相（±3）：`grab()` 出来的位图
        # 会与投影层合成，通道值会有 1~2 的偏差，锁死等于自找假失败
        for name, got, want in (("R", color.red(), 255), ("G", color.green(), 249),
                                ("B", color.blue(), 246)):
            with self.subTest(channel=name):
                self.assertLessEqual(abs(got - want), 3, f"{name}={got} 期望≈{want}")

    def test_flipped_tail_is_above_the_body(self):
        pet = QRect(800, 0, 300, 500)
        self.layout(pet, text="这是一段比较长的台词。" * 2)
        image = self._shot()
        body = self.bubble.body_rect()
        cx = self.bubble._tail_cx                        # noqa: SLF001
        color = image.pixelColor(cx, max(0, body.top() - sb.TAIL_H // 2))
        self.assertGreater(color.alpha(), 0, "翻到下方时尾巴没画在主体上方")

    def test_outline_is_drawn(self):
        """描边色 #8D6E63：主体边缘那一带应该能采到深色像素（一次描边，接缝处不该有内线）。"""
        self.layout(QRect(800, 400, 300, 500))
        image = self._shot()
        body = self.bubble.body_rect()
        darkest = 255
        for y in range(max(0, body.top() - 2), body.top() + 4):
            color = image.pixelColor(body.center().x(), y)
            darkest = min(darkest, color.lightness())
        self.assertLess(darkest, 200, "主体边缘没有描边")


class TestShowAndHide(BubbleTestCase):
    def setUp(self):
        super().setUp()
        self.pet = QRect(800, 400, 300, 500)

    def test_empty_text_does_not_show(self):
        self.assertFalse(self.bubble.show_text("", self.pet))
        self.assertFalse(self.bubble.show_text("   ", self.pet))
        self.assertFalse(self.bubble.show_text(None, self.pet))
        self.assertFalse(self.bubble.is_showing())

    def test_shows_and_reports_state(self):
        self.assertTrue(self.bubble.show_text("唔，好吃。", self.pet))
        self.assertTrue(self.bubble.is_showing())
        self.assertTrue(self.bubble.isVisible())
        self.assertEqual(self.bubble.text(), "唔，好吃。")
        self.bubble.hide_now()

    def test_replaces_text_instead_of_stacking(self):
        """连续触发多条台词 → **只显示 1 个气泡，内容被替换**（规范 5.3）。"""
        self.bubble.show_text("第一句。", self.pet)
        self.bubble.show_text("第二句。", self.pet)
        self.bubble.show_text("第三句。", self.pet)
        self.assertEqual(self.bubble.text(), "第三句。")
        self.assertTrue(self.bubble.is_showing())
        self.bubble.hide_now()

    def test_replacement_does_not_restart_the_entry_animation(self):
        """已经显示着的时候只换内容，不重播入场动画（否则每次都是"抖一下"：
        透明度掉回 0、位置再滑一次）。"""
        self.bubble.show_text("第一句。", self.pet)
        self.assertTrue(wait_until(lambda: self.bubble.windowOpacity() >= 0.999, 1500))
        pos_before = self.bubble.pos()
        self.bubble.show_text("第二句。", self.pet)
        self.assertEqual(self.bubble.pos(), pos_before)          # 没有重新滑入
        self.assertGreater(self.bubble.windowOpacity(), 0.9)     # 没有重新淡入
        self.bubble.hide_now()

    def test_duration_is_clamped_to_the_setting_range(self):
        self.bubble.show_text("唔。", self.pet, duration_ms=1)
        self.assertEqual(self.bubble._duration_ms, sb.MIN_DURATION_MS)   # noqa: SLF001
        self.bubble.show_text("唔。", self.pet, duration_ms=999999)
        self.assertEqual(self.bubble._duration_ms, sb.MAX_DURATION_MS)   # noqa: SLF001
        self.bubble.hide_now()

    def test_dirty_duration_does_not_raise(self):
        self.bubble.show_text("唔。", self.pet, duration_ms="abc")
        self.assertEqual(self.bubble._duration_ms, sb.DEFAULT_DURATION_MS)  # noqa: SLF001
        self.bubble.hide_now()

    def test_auto_hides_when_the_timer_fires(self):
        """停留计时器到点 → 自动收起（`hide_with_anim` 是异步的，必须轮询等）。"""
        self.bubble.show_text("唔。", self.pet)
        self.bubble._timer.start(30)                 # noqa: SLF001 - 不真等 3.5 秒
        self.assertTrue(wait_until(lambda: not self.bubble.isVisible()), "到点没自动收起")
        self.assertFalse(self.bubble.is_showing())

    def test_hide_with_anim_is_a_noop_when_hidden(self):
        self.bubble.hide_with_anim()
        self.assertFalse(self.bubble.isVisible())

    def test_hide_now(self):
        self.bubble.show_text("唔。", self.pet)
        self.bubble.hide_now()
        self.assertFalse(self.bubble.isVisible())
        self.assertFalse(self.bubble.is_showing())
        self.assertAlmostEqual(self.bubble.windowOpacity(), 1.0, places=3)

    def test_show_resizes_for_longer_text(self):
        self.bubble.show_text("唔。", self.pet)
        short = self.bubble.height()
        self.bubble.show_text("这是一段很长很长的台词。" * 3, self.pet)
        self.assertGreater(self.bubble.height(), short)
        self.bubble.hide_now()

    def test_follow_moves_with_the_pet(self):
        pet = QRect(800, 400, 300, 500)
        self.bubble.show_text("唔。", pet)
        moved = QRect(500, 600, 300, 500)
        self.bubble.follow(moved)
        self.assertEqual(self.bubble.tail_tip().y(), moved.top() + int(moved.height() * 0.14))
        self.assertEqual(self.bubble.frameGeometry().center().x(), moved.center().x())
        self.bubble.hide_now()

    def test_follow_does_not_restart_the_stay_timer(self):
        self.bubble.show_text("唔。", self.pet)
        self.bubble._timer.stop()                    # noqa: SLF001
        self.bubble.follow(QRect(500, 600, 300, 500))
        self.assertFalse(self.bubble._timer.isActive())    # noqa: SLF001
        self.assertTrue(self.bubble.is_showing())
        self.bubble.hide_now()

    def test_follow_when_not_showing_is_a_noop(self):
        before = self.bubble.pos()
        self.bubble.follow(QRect(100, 100, 300, 500))
        self.assertEqual(self.bubble.pos(), before)

    def test_follow_accepts_a_ratio(self):
        self.bubble.show_text("唔。", self.pet)
        self.bubble.follow(self.pet, ratio=0.4)
        self.assertEqual(self.bubble.tail_tip().y(), self.pet.top() + 200)
        self.bubble.hide_now()


    def test_entry_slides_up_from_the_pet_side(self):
        """入场必须**从靠近人物的一侧滑出来**（规范 5.3：从下方 8px 滑上）。

        初版写成了 `target - offset`，入场与退场都朝下 ——
        视觉上是"气泡从头顶往下掉"，而且刚弹出的那一刻位置会差 8px。
        """
        pet = QRect(800, 400, 300, 500)
        self.bubble._text = "唔，好吃。"         # noqa: SLF001
        _side, target = self.bubble.layout_for(pet, SCREEN)
        self.bubble.show_text("唔，好吃。", pet)
        self.assertGreater(self.bubble.y(), target.top(), "起点不在人物那一侧")
        self.assertLessEqual(self.bubble.y() - target.top(), sb.SLIDE)
        self.assertTrue(wait_until(lambda: self.bubble.y() <= target.top()), "没滑到目标位置")
        self.bubble.hide_now()

    def test_flipped_entry_slides_down_from_the_pet_side(self):
        pet = QRect(800, 0, 300, 500)
        text = "这是一段比较长的台词。" * 2
        self.bubble._text = text                 # noqa: SLF001
        side, target = self.bubble.layout_for(pet, SCREEN)
        self.assertEqual(side, "top")
        self.bubble.show_text(text, pet)
        self.assertLess(self.bubble.y(), target.top(),
                        "翻到下方时起点应在人物那一侧（更靠上）")
        self.assertTrue(wait_until(lambda: self.bubble.y() >= target.top()))
        self.bubble.hide_now()

    def test_hide_slides_back_toward_the_pet(self):
        pet = QRect(800, 400, 300, 500)
        self.bubble.show_text("唔。", pet)
        self.assertTrue(wait_until(lambda: self.bubble.windowOpacity() >= 0.99))
        settled = self.bubble.y()
        self.bubble.hide_with_anim()
        # 动画要跑几帧才会离开起点，紧跟调用之后断言是一次假失败
        self.assertTrue(wait_until(lambda: self.bubble.y() > settled, 800),
                        "收起时没有往人物方向滑")
        self.assertTrue(wait_until(lambda: not self.bubble.isVisible()))


class TestRendering(BubbleTestCase):
    def test_grab_all_shapes(self):
        cases = [
            ("一行", "唔，好吃。", QRect(800, 400, 300, 500)),
            ("四行", "很长的一句话。" * 4, QRect(800, 400, 300, 500)),
            ("超长", "很长的一句话。" * 12, QRect(800, 400, 300, 500)),
            ("翻转", "很长的一句话。" * 3, QRect(800, 0, 300, 500)),
            ("贴左边", "唔。", QRect(0, 400, 300, 500)),
            ("贴右边", "唔。", QRect(1620, 400, 300, 500)),
        ]
        for label, text, pet in cases:
            with self.subTest(case=label):
                self.layout(pet, text=text)
                self.bubble.setWindowOpacity(1.0)
                shot = self.bubble.grab()
                self.assertFalse(shot.isNull())
                self.assertEqual(shot.width(), self.bubble.width())
                self.assertEqual(shot.height(), self.bubble.height())


if __name__ == "__main__":
    unittest.main(verbosity=2)
