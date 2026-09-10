"""`src/nurture_icons.py` 单测 —— 三级降级链、缓存、色板约束。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

需要 `QGuiApplication`（`QPixmap` 依赖 GUI 后端）。**不显示任何窗口。**
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402

from src import nurture_icons as icons  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS_JSON = os.path.join(PROJECT_DIR, "assets", "nurture", "items.json")

_APP = None

#: 要接受"冷蓝色扫描"的 UI 文件。
#: 2026-09-10 全局换肤之后，这一套视觉不再只属于养成系统 ——
#: 左键功能面板、右键系统面板、设置窗口也统一过来了，所以它们也在清单里。
NURTURE_UI_FILES = (
    "src/ui_theme.py",
    "src/nurture_icons.py",
    "src/hover_menu.py",
    "src/nurture_panel.py",
    "src/speech_bubble.py",
    "src/nurture_settings_page.py",
    "src/bubble_panel.py",
    "src/settings_window.py",
    "src/gif_settings_page.py",
    "src/translations.py",
)

#: 模块里定义的全部色板常量名（与 03-设计规范 1.1 对应）
PALETTE_NAMES = (
    "CREAM", "CREAM_DEEP", "CARD", "OUTLINE", "OUTLINE_LIGHT", "PINK", "PINK_DEEP",
    "PINK_LIGHT", "NAVY", "RED", "HEART_PINK", "TEXT", "TEXT_DIM", "GREEN", "GOLD",
)


def setUpModule():
    global _APP
    _APP = QGuiApplication.instance() or QGuiApplication([])


class TestRegistry(unittest.TestCase):
    """图标注册表完整性。"""

    def test_twenty_seven_icons(self):
        """9 功能 + 5 面板 + 13 食物/礼物 = 27（2026-09-10 全局换肤时 +5 面板图标）。"""
        self.assertEqual(len(icons.known_keys()), 27)

    def test_nine_function_icons(self):
        functions = ("checkin", "feed", "gift", "heart", "chat", "headpat",
                     "settings", "close", "lock")
        for key in functions:
            with self.subTest(key=key):
                self.assertTrue(icons.has_builtin(key))

    def test_five_panel_icons(self):
        """左键功能面板 / 右键系统面板要用的 5 个图标。"""
        panels = ("clipboard", "pin", "monitor", "tray", "power")
        for key in panels:
            with self.subTest(key=key):
                self.assertTrue(icons.has_builtin(key))

    def test_panel_icons_are_all_used(self):
        """面板图标表里的每个键都要真有画法，否则那一行会退化成"名称首字"。"""
        from src import bubble_panel

        for item_id, key in bubble_panel.ITEM_ICONS.items():
            with self.subTest(item_id=item_id, key=key):
                self.assertTrue(icons.has_builtin(key),
                                f"菜单项「{item_id}」指定的图标「{key}」没有内置画法")

    def test_thirteen_item_icons(self):
        with open(ITEMS_JSON, "r", encoding="utf-8") as f:
            items = json.load(f)["items"]
        self.assertEqual(len(items), 13)
        for item in items:
            with self.subTest(item=item["name"]):
                self.assertTrue(icons.has_builtin(item["icon_key"]),
                                f"{item['name']} 的 icon_key「{item['icon_key']}」没有内置画法")

    def test_keys_are_unique(self):
        keys = icons.known_keys()
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_key_has_an_emoji_fallback(self):
        """第 3 级兜底要覆盖全部内置键，否则 emoji 那级形同虚设。"""
        for key in icons.known_keys():
            with self.subTest(key=key):
                self.assertTrue(icons.EMOJI.get(key))


class TestRendering(unittest.TestCase):
    """渲染：任何输入都必须出图，且尺寸/DPR 正确。"""

    def test_all_icons_render_at_both_sizes(self):
        for key in icons.known_keys():
            for size in (20, 44):
                with self.subTest(key=key, size=size):
                    pm = icons.pixmap(key, size)
                    self.assertFalse(pm.isNull())
                    self.assertEqual(pm.width(), size)
                    self.assertEqual(pm.height(), size)

    def test_icons_are_not_blank(self):
        """图标必须有非透明像素 —— 全透明等于没画。"""
        for key in icons.known_keys():
            with self.subTest(key=key):
                image = icons.pixmap(key, 44).toImage().convertToFormat(
                    QImage.Format_ARGB32)
                painted = 0
                for y in range(0, image.height(), 3):
                    for x in range(0, image.width(), 3):
                        if QColor(image.pixel(x, y)).alpha() > 0:
                            painted += 1
                self.assertGreater(painted, 20, f"{key} 几乎是空白的")

    def test_dpr_scales_physical_size(self):
        pm = icons.pixmap("heart", 20, dpr=2.0)
        self.assertEqual(pm.width(), 40)                    # 物理像素
        self.assertEqual(pm.height(), 40)
        self.assertAlmostEqual(pm.devicePixelRatio(), 2.0, places=2)

    def test_dirty_size_and_dpr_are_coerced(self):
        for bad_size in (0, -5, "abc"):
            with self.subTest(size=bad_size):
                pm = icons.pixmap("heart", bad_size)
                self.assertFalse(pm.isNull())
                self.assertGreaterEqual(pm.width(), 4)
        for bad_dpr in (None, 0, -1, "abc"):
            with self.subTest(dpr=bad_dpr):
                pm = icons.pixmap("heart", 20, dpr=bad_dpr)
                self.assertEqual(pm.width(), 20)             # 退化为 1.0 倍

    def test_unknown_key_still_renders(self):
        """用户新加了食物但没配图标 → 必须还有 emoji/首字/空心圆兜底。"""
        cases = [
            ("完全不存在的键", ""),
            ("完全不存在的键", "奶油面包"),
            ("", ""),
            ("", "饭团"),
            (None, None),
        ]
        for key, text in cases:
            with self.subTest(key=key, text=text):
                pm = icons.pixmap(key, 20, fallback_text=text)
                self.assertFalse(pm.isNull())
                self.assertEqual(pm.width(), 20)

    def test_pixmap_for_item(self):
        with open(ITEMS_JSON, "r", encoding="utf-8") as f:
            items = json.load(f)["items"]
        for item in items:
            with self.subTest(item=item["name"]):
                pm = icons.pixmap_for_item(item, 28)
                self.assertFalse(pm.isNull())
                self.assertEqual(pm.width(), 28)

    def test_pixmap_for_item_tolerates_garbage(self):
        for bad in (None, "x", 42, [], {}):
            with self.subTest(bad=bad):
                self.assertFalse(icons.pixmap_for_item(bad, 20).isNull())

    def test_render_sheet_is_produced(self):
        sheet = icons.render_sheet(["heart", "rose"], icon_size=32, cols=2)
        self.assertFalse(sheet.isNull())
        self.assertGreater(sheet.width(), 60)
        self.assertGreater(sheet.height(), 40)


class TestFallbackChain(unittest.TestCase):
    """三级来源的优先级：用户 PNG > 内置矢量 > emoji/首字。"""

    MAGENTA = "#FF00FF"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_icons_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_user_icon(self, key: str) -> str:
        pm = QPixmap(64, 64)
        pm.fill(QColor(self.MAGENTA))
        path = os.path.join(self.tmp, f"{key}.png")
        pm.save(path)
        return path

    @staticmethod
    def _has_color(pixmap: QPixmap, hex_color: str, tolerance: int = 12) -> bool:
        target = QColor(hex_color)
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                c = QColor(image.pixel(x, y))
                if c.alpha() < 200:
                    continue
                if (abs(c.red() - target.red()) <= tolerance
                        and abs(c.green() - target.green()) <= tolerance
                        and abs(c.blue() - target.blue()) <= tolerance):
                    return True
        return False

    def test_user_png_overrides_builtin(self):
        self._write_user_icon("feed")
        user = icons.pixmap("feed", 20, icons_dir=self.tmp)
        builtin = icons.pixmap("feed", 20, icons_dir=os.path.join(self.tmp, "empty"))
        self.assertTrue(self._has_color(user, self.MAGENTA))
        self.assertFalse(self._has_color(builtin, self.MAGENTA))

    def test_cache_key_includes_icons_dir(self):
        """截图缓存不能把"有没有用户 PNG"混淆掉 —— 否则放了图标也不生效。"""
        self._write_user_icon("rose")
        with_user = icons.pixmap("rose", 20, icons_dir=self.tmp)
        without_user = icons.pixmap("rose", 20, icons_dir=os.path.join(self.tmp, "empty"))
        self.assertTrue(self._has_color(with_user, self.MAGENTA))
        self.assertFalse(self._has_color(without_user, self.MAGENTA))

    def test_broken_user_png_falls_through_to_builtin(self):
        with open(os.path.join(self.tmp, "heart.png"), "wb") as f:
            f.write(b"not a png at all")
        pm = icons.pixmap("heart", 20, icons_dir=self.tmp)
        self.assertFalse(pm.isNull())
        self.assertTrue(self._has_color(pm, icons.HEART_PINK))

    def test_cache_returns_same_object(self):
        first = icons.pixmap("heart", 20, icons_dir=self.tmp)
        second = icons.pixmap("heart", 20, icons_dir=self.tmp)
        self.assertIs(first, second)

    def test_clear_cache_forces_rerender(self):
        first = icons.pixmap("heart", 20, icons_dir=self.tmp)
        icons.clear_cache()
        second = icons.pixmap("heart", 20, icons_dir=self.tmp)
        self.assertIsNot(first, second)
        self.assertFalse(second.isNull())

    def test_corrupt_drawer_falls_through_to_emoji(self):
        """某个画法抛异常时，不能让整个界面挂掉 —— 退到第 3 级。"""
        original = icons.DRAWERS["heart"]

        def boom(painter):
            raise RuntimeError("画法坏了")

        icons.DRAWERS["heart"] = boom
        icons.clear_cache()
        try:
            pm = icons.pixmap("heart", 20)
            self.assertFalse(pm.isNull())
        finally:
            icons.DRAWERS["heart"] = original
            icons.clear_cache()


class TestPalette(unittest.TestCase):
    """色板约束（03 规范 0.2 / 11 验收清单）。"""

    def test_palette_constants_are_valid_hex(self):
        for name in PALETTE_NAMES:
            with self.subTest(name=name):
                value = getattr(icons, name)
                self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$")
                self.assertTrue(QColor(value).isValid())

    def test_no_forbidden_cold_blue_in_palette(self):
        forbidden = {c.upper() for c in icons.FORBIDDEN_COLORS}
        for name in PALETTE_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(getattr(icons, name).upper(), forbidden)

    def test_stroke_width_is_two(self):
        self.assertEqual(icons.STROKE, 2.0)

    def test_grid_is_twenty(self):
        self.assertEqual(icons.GRID, 20.0)

    def test_new_ui_files_avoid_forbidden_colors(self):
        """扫描所有 UI 文件的源码，冷蓝色只能出现在 FORBIDDEN_COLORS 定义那一行。

        2026-09-10 起这份清单覆盖**全部**暖粉手绘风的 UI 文件（含设置窗口与左右键面板）。
        """
        forbidden = [c.upper() for c in icons.FORBIDDEN_COLORS]
        checked = 0
        for relative in NURTURE_UI_FILES:
            path = os.path.join(PROJECT_DIR, relative)
            if not os.path.isfile(path):
                continue
            checked += 1
            with open(path, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    upper = line.upper()
                    for hex_color in forbidden:
                        if hex_color in upper:
                            with self.subTest(file=relative, line=lineno):
                                self.assertIn("FORBIDDEN_COLORS", line,
                                              f"{relative}:{lineno} 用了冷蓝色 {hex_color}")
        self.assertGreaterEqual(checked, len(NURTURE_UI_FILES) - 1,
                                "清单里的文件应该基本都在（只有还没创建的允许缺席）")

    def test_palette_has_a_single_source(self):
        """色板只在 `ui_theme.py` 定义一次，`nurture_icons` 转出的必须与之完全一致。

        否则有人往 `nurture_icons.py` 里重新写死一个色值，两套 UI 就会慢慢分叉。
        """
        from src import ui_theme as theme

        for name in PALETTE_NAMES:
            with self.subTest(name=name):
                self.assertEqual(getattr(icons, name), getattr(theme, name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
