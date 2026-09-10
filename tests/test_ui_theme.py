"""`src/ui_theme.py`（全局主题）+ `src/bubble_panel.py`（左右键面板）单测。

2026-09-10 **全局换肤**：左键功能面板 / 右键系统面板 / 设置窗口从"冷蓝磨砂玻璃"
改成与养成系统同一套"暖粉奶白手绘风"。这一批改动同时动了**最高频的交互**
（默认服装的左键/右键菜单）和**色板的归属**（色板从 `nurture_icons` 提到 `ui_theme`），
所以这里盯着三件事：

| 盯什么 | 为什么 |
|--------|--------|
| 色板只有一份 | `nurture_icons` 转出的名字必须与 `ui_theme` 逐字相同，否则两套 UI 会分叉 |
| 造型工具是对的 | 不对称圆角必须**四角差值 ≤ 2px**（规范第 3 节），否则看起来像 bug |
| 换肤没换行为 | 面板的**对外契约**（信号 / `popup_at` / `show_at` / 勾选状态）与落位口径 |

面板落位用**可见矩形**（窗口四边各留 `MARGIN` 给投影），这是换肤时最容易搞错的地方 ——
拿窗口尺寸去量，面板会离人物多远出 12px，而且这种错**肉眼很难发现**，所以必须钉死。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import bubble_panel as bp  # noqa: E402
from src import nurture_icons as icons  # noqa: E402
from src import ui_theme as theme  # noqa: E402

_APP = None

#: emoji / 符号所在的码位区间（用来断言"文案里不该再有 emoji 前缀"）。
#: **不能写成 `ord(ch) > 0x2000`** —— 汉字从 0x4E00 起，那样连"窗口置顶"都会被判成 emoji。
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # 各种 emoji 区块（📋📏🎬🚪…）
    (0x2600, 0x27BF),     # 杂项符号与装饰符号（⚙✂…）
    (0x2B00, 0x2BFF),     # 杂项符号与箭头
    (0x2190, 0x21FF),     # 箭头（←→↑↓）
    (0xFE0F, 0xFE0F),     # 变体选择符（emoji 呈现）
    (0xFE00, 0xFE0F),
)


def has_emoji(text: str) -> bool:
    return any(any(lo <= ord(ch) <= hi for lo, hi in _EMOJI_RANGES) for ch in str(text))


def wait_until(predicate, timeout_ms: int = 1500) -> bool:
    """轮询等条件成立。

    **弹入/收起动画是异步的**（`panel_animator` 用 `QPropertyAnimation` 跑 180~220ms），
    固定 `qWait` 会随机失败 —— 这是本项目写 UI 测试踩过两次的坑，统一用轮询。
    """
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout_ms:
        if predicate():
            return True
        QApplication.processEvents()
    return bool(predicate())


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class TestPalette(unittest.TestCase):
    """色板与造型常数。"""

    def test_palette_matches_the_nurture_icons_reexport(self):
        names = ("CREAM", "CREAM_DEEP", "CARD", "OUTLINE", "OUTLINE_LIGHT", "PINK",
                 "PINK_DEEP", "PINK_LIGHT", "NAVY", "RED", "HEART_PINK", "TEXT",
                 "TEXT_DIM", "GREEN", "GOLD")
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(getattr(theme, name), getattr(icons, name))

    def test_colors_are_valid_hex(self):
        for name in ("CREAM", "OUTLINE", "PINK", "TEXT"):
            with self.subTest(name=name):
                self.assertTrue(QColor(getattr(theme, name)).isValid())

    def test_no_forbidden_cold_blue(self):
        forbidden = {c.upper() for c in theme.FORBIDDEN_COLORS}
        for name in dir(theme):
            if name.isupper() and isinstance(getattr(theme, name), str):
                with self.subTest(name=name):
                    self.assertNotIn(getattr(theme, name).upper(), forbidden)

    def test_radius_scale(self):
        """面板 20 / 卡片 14 / 行 12 —— 规范 0.2 的圆角基准。"""
        self.assertEqual(theme.RADIUS_PANEL, 20)
        self.assertEqual(theme.RADIUS_CARD, 14)
        self.assertEqual(theme.RADIUS_ROW, 12)


class TestShapeTools(unittest.TestCase):
    """`rounded_path` / `paper_radii`：手绘感的实现手法。"""

    def test_paper_radii_spread_is_within_two(self):
        """规范第 3 节：四角半径差**不许超过 2px**，否则会像 bug 而不是手绘。"""
        for base in (8, 12, 14, 20, 28):
            with self.subTest(base=base):
                radii = theme.paper_radii(base)
                self.assertEqual(len(radii), 4)
                self.assertLessEqual(max(radii) - min(radii), 2.0)
                self.assertGreaterEqual(min(radii), base)

    def test_rounded_path_keeps_the_rect(self):
        rect = QRectF(10, 20, 120, 60)
        path = theme.rounded_path(rect, theme.paper_radii(20))
        box = path.boundingRect()
        self.assertAlmostEqual(box.left(), rect.left(), places=1)
        self.assertAlmostEqual(box.top(), rect.top(), places=1)
        self.assertAlmostEqual(box.right(), rect.right(), places=1)
        self.assertAlmostEqual(box.bottom(), rect.bottom(), places=1)

    def test_rounded_path_accepts_uniform_radius(self):
        path = theme.rounded_path(QRectF(0, 0, 40, 40), 10)
        self.assertFalse(path.isEmpty())

    def test_rounded_path_clamps_px_radius_bigger_than_the_rect(self):
        """半径比矩形还大时不能画出乱七八糟的图形（Qt 会自己截断，我们也要）。"""
        path = theme.rounded_path(QRectF(0, 0, 20, 20), (500, 500, 500, 500))
        box = path.boundingRect()
        self.assertAlmostEqual(box.width(), 20, places=1)
        self.assertAlmostEqual(box.height(), 20, places=1)

    def test_rounded_path_survives_dirty_radii(self):
        for bad in (None, "abc", [], (1, 2)):
            with self.subTest(radii=bad):
                self.assertFalse(theme.rounded_path(QRectF(0, 0, 30, 30), bad).isEmpty())

    def test_zero_radius_is_a_plain_rect(self):
        path = theme.rounded_path(QRectF(0, 0, 30, 30), 0)
        self.assertAlmostEqual(path.boundingRect().width(), 30, places=1)


class TestStylesheet(unittest.TestCase):
    """`app_stylesheet()`：标准控件的配色。"""

    @classmethod
    def setUpClass(cls):
        cls.qss = theme.app_stylesheet()

    def test_has_no_placeholders_left(self):
        self.assertNotIn("@", self.qss, "占位符没替换干净")

    def test_has_no_forbidden_cold_blue(self):
        upper = self.qss.upper()
        for color in theme.FORBIDDEN_COLORS:
            with self.subTest(color=color):
                self.assertNotIn(color.upper(), upper)

    def test_uses_the_palette(self):
        for value in (theme.CREAM, theme.CREAM_DEEP, theme.OUTLINE, theme.PINK,
                      theme.PINK_DEEP, theme.NAVY, theme.TEXT):
            with self.subTest(value=value):
                self.assertIn(value, self.qss)

    def test_covers_the_controls_the_settings_window_uses(self):
        for selector in ("QGroupBox", "QComboBox", "QSpinBox", "QSlider", "QCheckBox",
                         "QListWidget", "QPushButton", "QScrollArea"):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.qss)

    def test_scroll_viewport_is_transparent(self):
        """少了这条，Q 版设置页会在奶白纸片上糊出一条系统灰底色带（实测踩过）。"""
        self.assertIn("QScrollArea > QWidget > QWidget", self.qss)


class TestPanelGeometry(unittest.TestCase):
    """面板落位：可见矩形 vs 窗口矩形。"""

    def make(self, items=None):
        items = items or [("clipboard", "bubble_clipboard")]
        panel = bp.BubblePanel(items)
        self.addCleanup(panel.deleteLater)
        return panel

    def test_window_is_bigger_than_the_visible_panel(self):
        panel = self.make()
        w, h = panel.visible_size()
        self.assertEqual(panel.width(), w + 2 * bp.MARGIN)
        self.assertEqual(panel.height(), h + 2 * bp.MARGIN)
        self.assertEqual(panel.visible_rect(), QRect(bp.MARGIN, bp.MARGIN, w, h))

    def test_height_adds_up_for_every_row(self):
        one = self.make().visible_size()[1]
        five = self.make([("topmost", "sys_topmost", {"checkable": True}),
                          ("desktop_level", "sys_desktop_level", {"checkable": True}),
                          ("minimize_tray", "sys_minimize_tray"),
                          ("settings", "bubble_settings"),
                          ("exit", "bubble_exit")]).visible_size()[1]
        self.assertEqual(five - one, 4 * (bp.ROW_H + bp.ROW_GAP))

    def test_width_follows_the_longest_label(self):
        narrow = self.make().visible_size()[0]
        wide = self.make([("minimize_tray", "sys_minimize_tray")]).visible_size()[0]
        self.assertGreaterEqual(narrow, bp.MIN_WIDTH)
        self.assertLessEqual(wide, bp.MAX_WIDTH)

    def test_popup_at_puts_the_panel_edge_next_to_the_pet(self):
        """间距指的是**面板边缘**到人物边缘，不是窗口边缘。

        弹入是异步动画，所以要等它停稳再量 —— 直接读会拿到动画起点（差 40px）。
        """
        panel = self.make()
        pet = QRect(1000, 400, 500, 500)
        target = pet.right() + 1 + bp.GAP_FROM_PET
        panel.popup_at(pet)
        self.assertTrue(wait_until(lambda: panel.x() + bp.MARGIN == target),
                        f"落位没到位：{panel.x() + bp.MARGIN} != {target}")
        panel.hide_with_anim()

    def test_popup_at_centers_vertically_on_the_pet(self):
        panel = self.make()
        pet = QRect(1000, 400, 500, 500)
        panel.popup_at(pet)
        center = lambda: panel.y() + bp.MARGIN + panel.visible_size()[1] // 2  # noqa: E731
        wait_until(lambda: abs(center() - pet.center().y()) <= 2)
        self.assertLessEqual(abs(center() - pet.center().y()), 2)
        panel.hide_with_anim()

    def test_popup_at_flips_to_the_left_near_the_right_edge(self):
        panel = self.make()
        screen = QApplication.primaryScreen().availableGeometry()
        pet = QRect(screen.right() - 100, 300, 90, 400)
        panel.popup_at(pet)
        self.assertEqual(getattr(panel, "_popup_direction"), "left")
        right_edge = lambda: panel.x() + bp.MARGIN + panel.visible_size()[0]  # noqa: E731
        wait_until(lambda: right_edge() <= pet.left() - bp.GAP_FROM_PET)
        self.assertLessEqual(right_edge(), pet.left() - bp.GAP_FROM_PET)
        panel.hide_with_anim()

    def test_show_at_puts_the_visible_corner_at_the_cursor(self):
        """右键面板是"一角对准光标"—— 对准的是可见角，不是窗口角。"""
        panel = self.make()
        screen = QApplication.primaryScreen().availableGeometry()
        pos = QPoint(screen.left() + 600, screen.top() + 300)
        panel.show_at(pos)
        self.assertEqual(panel.x() + bp.MARGIN, pos.x())
        self.assertEqual(panel.y() + bp.MARGIN, pos.y())
        panel.hide()

    def test_show_at_stays_on_screen(self):
        panel = self.make([("minimize_tray", "sys_minimize_tray"),
                           ("settings", "bubble_settings")])
        screen = QApplication.primaryScreen().availableGeometry()
        for pos in (QPoint(screen.right() - 4, screen.bottom() - 4),
                    QPoint(screen.left() + 2, screen.top() + 2)):
            with self.subTest(pos=pos):
                panel.show_at(pos)
                self.assertGreaterEqual(panel.x() + bp.MARGIN, screen.left())
                self.assertGreaterEqual(panel.y() + bp.MARGIN, screen.top())
                self.assertLessEqual(panel.x() + bp.MARGIN + panel.visible_size()[0],
                                     screen.right() + 1)
                self.assertLessEqual(panel.y() + bp.MARGIN + panel.visible_size()[1],
                                     screen.bottom() + 1)
                panel.hide()


class TestPanelBehaviour(unittest.TestCase):
    """对外契约：信号、勾选状态、点击、三语文案。"""

    SYSTEM = [("topmost", "sys_topmost", {"checkable": True}),
              ("desktop_level", "sys_desktop_level", {"checkable": True}),
              ("minimize_tray", "sys_minimize_tray"),
              ("settings", "bubble_settings"),
              ("exit", "bubble_exit")]

    def make(self, items=None):
        panel = bp.BubblePanel(items if items is not None else self.SYSTEM)
        self.addCleanup(panel.deleteLater)
        return panel

    def test_checked_state_round_trip(self):
        panel = self.make()
        self.assertFalse(panel.is_item_checked("topmost"))
        panel.set_item_checked("topmost", True)
        self.assertTrue(panel.is_item_checked("topmost"))
        panel.set_item_checked("topmost", False)
        self.assertFalse(panel.is_item_checked("topmost"))

    def test_only_checkable_items_keep_state(self):
        panel = self.make()
        panel.set_item_checked("settings", True)      # 非 checkable
        self.assertFalse(panel.is_item_checked("settings"))

    def test_click_emits_the_item_id(self):
        panel = self.make()
        seen: list[str] = []
        panel.item_clicked.connect(seen.append)
        row = panel._row_rect(3)                      # noqa: SLF001  "settings"
        panel.mousePressEvent(_press(row.center()))
        panel.mouseReleaseEvent(_release(row.center()))
        self.assertEqual(seen, ["settings"])

    def test_click_on_another_row_after_press_does_not_emit(self):
        """按下在一行、松手在另一行 —— 不该触发（标准按钮语义）。"""
        panel = self.make()
        seen: list[str] = []
        panel.item_clicked.connect(seen.append)
        panel.mousePressEvent(_press(panel._row_rect(1).center()))   # noqa: SLF001
        panel.mouseReleaseEvent(_release(panel._row_rect(4).center()))  # noqa: SLF001
        self.assertEqual(seen, [])

    def test_click_on_empty_space_does_not_emit(self):
        panel = self.make()
        seen: list[str] = []
        panel.item_clicked.connect(seen.append)
        panel.mousePressEvent(_press(QPointF(2, 2)))
        panel.mouseReleaseEvent(_release(QPointF(2, 2)))
        self.assertEqual(seen, [])

    def test_labels_follow_the_language(self):
        panel = self.make()
        panel.apply_language("zh")
        self.assertIn("窗口置顶", panel.row_labels())
        panel.apply_language("en")
        self.assertIn("Always on Top", panel.row_labels())
        panel.apply_language("ja")
        self.assertIn("常に最前面", panel.row_labels())

    def test_labels_have_no_emoji_prefix(self):
        """换肤后每行左侧是自绘矢量图标，文案里不该再带 emoji（那会变成"图标配 emoji"）。"""
        panel = self.make()
        for lang in ("zh", "en", "ja"):
            panel.apply_language(lang)
            for text in panel.row_labels():
                with self.subTest(lang=lang, text=text):
                    self.assertTrue(text)
                    self.assertEqual(text, text.strip())
                    self.assertFalse(has_emoji(text), f"文案「{text}」里还有 emoji")

    def test_emoji_detector_does_not_misfire_on_cjk(self):
        """反向验证那个检测器本身：汉字/日文假名不该被判成 emoji。"""
        for text in ("窗口置顶", "桌面层级", "最小化到托盘", "設定", "常に最前面"):
            with self.subTest(text=text):
                self.assertFalse(has_emoji(text))
        for text in ("📋 历史粘贴板", "⚙  设置", "🎬  动画设置"):
            with self.subTest(text=text):
                self.assertTrue(has_emoji(text))

    def test_unknown_item_id_falls_back_to_a_glyph(self):
        """`pet_window` 里加新菜单项时不该需要改面板 —— 图标会退化成名称首字。"""
        panel = self.make([("未来功能", "bubble_settings")])
        self.assertEqual(panel.row_labels(), ["设置"])
        icon = icons.pixmap(bp.ITEM_ICONS.get("未来功能", ""), 18, fallback_text="设")
        self.assertFalse(icon.isNull())

    def test_panel_never_paints_outside_the_visible_rect(self):
        """所有绘制都落在可见矩形内（投影除外），否则窗口会截掉自己的描边。"""
        panel = self.make()
        panel.resize(panel.width(), panel.height())
        visible = panel.visible_rect()
        for index in range(len(self.SYSTEM)):
            with self.subTest(index=index):
                row = panel._row_rect(index)          # noqa: SLF001
                self.assertGreaterEqual(row.left(), visible.left() - 6)
                self.assertLessEqual(row.right(), visible.right() + 6)
                self.assertGreaterEqual(row.top(), visible.top())
                self.assertLessEqual(row.bottom(), visible.bottom())
        self.assertLessEqual(panel._close_rect().right(), visible.right())  # noqa: SLF001


def _press(pos):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton,
                       Qt.NoModifier)


def _release(pos):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton,
                       Qt.NoModifier)


if __name__ == "__main__":
    unittest.main(verbosity=2)
