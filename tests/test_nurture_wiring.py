"""`PetWindow` ⇄ `NurtureController` 接线测试（阶段 D）。

单测各自覆盖了 controller 的规则与面板的几何，这里只测**它们接在一起**的样子：

```
悬停菜单点「喂食」 → controller 开面板（食物页）→ 点卡片 → controller 扣库存 + 播动画
```

以及三条容易接错的地方：

1. **面板要进仲裁器**：开功能面板/系统面板/设置窗口时，养成面板必须一起收起
2. **没接 controller 时不能崩**：`PetWindow(character)` 的老用法（单元测试、阶段 C 行为）照旧
3. **`_popups()` 不能顺手把面板创建出来**：否则每开一次功能面板就凭空多一个隐藏窗口

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import nurture_controller as nc  # noqa: E402
from src import nurture_store as store_mod  # noqa: E402
from src import pet_window as pw  # noqa: E402
from src.character_base import CharacterController  # noqa: E402
from src.translations import tr  # noqa: E402

_APP = None
DELAY_MS = 60
GRACE_MS = 60
ANIM_SETTLE_MS = 260

ITEMS = {
    "items": [
        {"name": "奶油面包", "kind": "food", "tier": "common", "anim": "笑",
         "icon_key": "bread", "lines": ["奶油面包，给你留了一个。"]},
        {"name": "玫瑰花", "kind": "gift", "tier": "precious", "anim": "玫瑰",
         "icon_key": "rose", "lines": []},
    ]
}
DIALOGUES = {
    "feed_done.json": {"scene": "feed_done", "tone": "gentle",
                       "lines": [{"text": "唔，好吃。", "weight": 1}]},
    "feed_empty.json": {"scene": "feed_empty", "tone": "gentle",
                        "lines": [{"text": "这个已经吃完了呢。", "weight": 1}]},
    # 触发类场景：用**fixture 自带**的台词，避免断言依赖 dialogue.py 里的内置兜底
    "detect_typing.json": {"scene": "detect_typing", "tone": "gentle",
                           "cooldown_sec": 600, "min_gap_sec": 0,
                           "lines": [{"text": "敲得好快呀。", "weight": 1}]},
    "detect_audio.json": {"scene": "detect_audio", "tone": "gentle",
                          "cooldown_sec": 900, "min_gap_sec": 0,
                          "lines": [{"text": "在听歌吗。", "weight": 1}]},
    "detect_muted.json": {"scene": "detect_muted", "tone": "gentle",
                          "cooldown_sec": 900, "min_gap_sec": 0,
                          "lines": [{"text": "怎么没声音了。", "weight": 1}]},
    "hover_long.json": {"scene": "hover_long", "tone": "gentle",
                        "cooldown_sec": 60, "min_gap_sec": 0,
                        "lines": [{"text": "怎么一直看着我。", "weight": 1}]},
}


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class FakeCharacter(CharacterController):
    """假角色：记录 `play_action`，其余照 `CharacterController` 的默认实现。"""

    def __init__(self, character_type: str = "gif"):
        super().__init__()
        self._type = character_type
        self.played: list[str] = []
        self.menu_shown = 0
        self._pixmap = QPixmap(60, 100)
        self._pixmap.fill(QColor(255, 183, 197))

    @property
    def character_type(self) -> str:
        return self._type

    @property
    def character_name(self) -> str:
        return "Fake"

    @property
    def native_aspect_ratio(self) -> float:
        return 0.6

    def start(self):
        pass

    def stop(self):
        pass

    def get_current_pixmap(self):
        return self._pixmap

    def get_idle_key(self) -> str:
        return "fake_idle"

    def get_hover_key(self) -> str:
        return "fake_hover"

    def set_idle_key(self, key: str):
        pass

    def set_hover_key(self, key: str):
        pass

    def get_available_animations(self) -> list[str]:
        return ["笑", "玫瑰", "点赞", "害羞 2"]

    def play_action(self, action: str, lock: bool = True) -> bool:
        if action not in self.get_available_animations():
            return False
        self.played.append(action)
        return True

    def handle_hover_menu_shown(self):
        self.menu_shown += 1


def _config(nurture_cfg: dict | None = None) -> dict:
    cfg = {"enabled": True, "hover_menu_delay_ms": DELAY_MS, "hover_grace_ms": GRACE_MS,
           "send_cooldown_ms": 0, "affection_daily_cap": 20, "gift_daily_cap": 3}
    cfg.update(nurture_cfg or {})
    return {"character_type": "gif", "nurture": cfg, "language": "zh",
            "auto_start": False, "height": 500, "topmost": True,
            "position": None, "idle_animation": "x", "hover_animation": "y", "gif": {}}


@contextlib.contextmanager
def wired_window(nurture_cfg: dict | None = None, with_controller: bool = True,
                 character: FakeCharacter | None = None):
    """真实 `PetWindow` + 真实 `NurtureController`（临时素材目录 + 临时存档）。"""
    tmp = tempfile.mkdtemp(prefix="nurture_wiring_")
    assets = os.path.join(tmp, "nurture")
    os.makedirs(os.path.join(assets, "dialogues"))
    with open(os.path.join(assets, "items.json"), "w", encoding="utf-8") as handle:
        json.dump(ITEMS, handle, ensure_ascii=False)
    for name, data in DIALOGUES.items():
        with open(os.path.join(assets, "dialogues", name), "w",
                  encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

    character = character or FakeCharacter()
    config = _config(nurture_cfg)
    store = store_mod.NurtureStore(path=os.path.join(tmp, "data", "nurture.json"))
    controller = (nc.NurtureController(store, config["nurture"], assets_dir=assets)
                  if with_controller else None)

    original = pw.load_config
    pw.load_config = lambda: config
    window = None
    try:
        window = pw.PetWindow(character, nurture=controller)
        yield window, controller, character, store
    finally:
        pw.load_config = original
        if window is not None:
            window.function_panel.deleteLater()
            window.system_panel.deleteLater()
            window.settings.deleteLater()
            if window._hover_menu is not None:               # noqa: SLF001
                window._hover_menu.deleteLater()             # noqa: SLF001
            panel = controller.panel_widget() if controller is not None else None
            if panel is not None:
                panel.deleteLater()
            window.deleteLater()
        if controller is not None:
            controller.deleteLater()
        shutil.rmtree(tmp, ignore_errors=True)


def click(widget, pos) -> None:
    for event_type, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                                (QEvent.MouseButtonRelease, Qt.NoButton)):
        event = QMouseEvent(event_type, QPointF(pos), QPointF(pos),
                            Qt.LeftButton, buttons, Qt.NoModifier)
        QApplication.sendEvent(widget, event)


def enter_pet(window) -> None:
    window.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))


def show_menu(window) -> None:
    """把悬停菜单真正弹出来（走完整延迟 + 弹出动画）。"""
    enter_pet(window)
    QTest.qWait(DELAY_MS + 40)
    QTest.qWait(ANIM_SETTLE_MS)


def settle(ms: int = ANIM_SETTLE_MS) -> None:
    QTest.qWait(ms)


class WiringTestCase(unittest.TestCase):
    def setUp(self):
        self._ctx = wired_window()
        self.window, self.controller, self.character, self.store = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.menu = self.window._hover_menu                 # noqa: SLF001


class TestMenuRouting(WiringTestCase):
    def test_feed_opens_the_food_tab(self):
        show_menu(self.window)
        self.menu.action_triggered.emit("feed")
        panel = self.controller.panel_widget()
        self.assertIsNotNone(panel)
        self.assertEqual(panel.tab(), "food")
        self.assertTrue(panel.isVisible())

    def test_gift_opens_the_gift_tab(self):
        self.menu.action_triggered.emit("gift")
        self.assertEqual(self.controller.panel_widget().tab(), "gift")

    def test_heart_opens_the_status_tab(self):
        self.menu.action_triggered.emit("heart")
        self.assertEqual(self.controller.panel_widget().tab(), "status")

    def test_opening_the_panel_hides_the_menu(self):
        show_menu(self.window)
        self.assertTrue(self.menu.isVisible())
        self.menu.action_triggered.emit("feed")
        settle()
        self.assertFalse(self.menu.isVisible())

    def test_settings_still_works_and_takes_precedence(self):
        """「设置」不经 controller（由 PetWindow 自己开），行为与阶段 C 一致。"""
        opened = []
        self.window._on_settings = lambda: opened.append(1)     # noqa: SLF001
        self.menu.action_triggered.emit("settings")
        self.assertEqual(opened, [1])

    def test_checkin_action_routes_to_the_controller(self):
        """「签到」从阶段 F 起由 controller 处理，不再是"尚未接入"。"""
        checked = []
        self.controller.try_checkin = lambda: checked.append(1) or "ok"
        self.controller.refresh_menu = lambda: None
        show_menu(self.window)
        self.menu.action_triggered.emit("checkin")
        settle()
        self.assertEqual(checked, [1])
        self.assertFalse(self.menu.isVisible())

    def test_unknown_action_hides_the_menu_and_logs(self):
        """controller 不认识的按钮：收起菜单 + 记日志，绝不静默地"点了没反应"。"""
        logged = self._capture_log()
        show_menu(self.window)
        self.menu.action_triggered.emit("还没做的按钮")
        settle()
        self.assertFalse(self.menu.isVisible())
        self.assertTrue(any("还没做的按钮" in line for line in logged))

    def test_controller_exception_does_not_break_the_pet(self):
        """养成层抛异常也不能连累桌宠本体（面板开不出来最多是功能缺失，不该崩）。"""
        logged = self._capture_log()
        self.controller.on_menu_action = lambda *a, **k: (_ for _ in ()).throw(RuntimeError)
        self.menu.action_triggered.emit("feed")
        self.assertTrue(any("抛异常" in line for line in logged))
        self.assertFalse(self.menu.isVisible())

    def _capture_log(self) -> list:
        lines: list[str] = []
        original = pw.nurture_dbg
        pw.nurture_dbg = lines.append
        self.addCleanup(lambda: setattr(pw, "nurture_dbg", original))
        return lines


class TestArbitration(WiringTestCase):
    def open_panel(self):
        self.menu.action_triggered.emit("feed")
        panel = self.controller.panel_widget()
        self.assertTrue(panel.isVisible())
        return panel

    def test_panel_is_registered_in_the_arbiter(self):
        self.open_panel()
        self.assertTrue(self.window.any_popup_visible(("nurture",)))

    def test_function_panel_closes_the_nurture_panel(self):
        panel = self.open_panel()
        self.window._toggle_function_panel()                   # noqa: SLF001
        settle()
        self.assertFalse(panel.isVisible())

    def test_system_panel_closes_the_nurture_panel(self):
        panel = self.open_panel()
        self.window.hide_all_popups(except_key="system")
        settle()
        self.assertFalse(panel.isVisible())

    def test_nurture_panel_closes_the_function_panel(self):
        self.window._toggle_function_panel()                   # noqa: SLF001
        self.assertTrue(self.window.function_panel.isVisible())
        self.menu.action_triggered.emit("feed")
        settle()
        self.assertFalse(self.window.function_panel.isVisible())

    def test_settings_closes_the_nurture_panel(self):
        panel = self.open_panel()
        self.window._on_settings()                             # noqa: SLF001
        settle()
        self.assertFalse(panel.isVisible())

    def test_popups_do_not_create_the_panel(self):
        """查可见性时**不能**把面板造出来，否则每开一次功能面板就多一个隐藏窗口。"""
        self.assertIsNone(self.controller.panel_widget())
        self.window._popups()                                  # noqa: SLF001
        self.window.any_popup_visible()
        self.assertIsNone(self.controller.panel_widget())
        self.assertNotIn("nurture", self.window._popups())      # noqa: SLF001


class TestMenuStateFromController(WiringTestCase):
    def test_feed_is_greyed_out_without_food(self):
        show_menu(self.window)
        self.assertFalse(self.menu.is_enabled("feed"))

    def test_feed_is_available_with_food(self):
        self.store.add_item("奶油面包", 2)
        show_menu(self.window)
        self.assertTrue(self.menu.is_enabled("feed"))

    def test_gift_is_greyed_out_without_gifts(self):
        self.store.add_item("奶油面包", 2)
        show_menu(self.window)
        self.assertFalse(self.menu.is_enabled("gift"))

    def test_checkin_badge_is_on_before_checking_in(self):
        show_menu(self.window)
        self.assertTrue(self.menu._badges["checkin"])           # noqa: SLF001

    def test_heart_and_settings_are_always_available(self):
        show_menu(self.window)
        self.assertTrue(self.menu.is_enabled("heart"))
        self.assertTrue(self.menu.is_enabled("settings"))

    def test_chat_is_greyed_out_at_low_affection(self):
        show_menu(self.window)
        self.assertFalse(self.menu.is_enabled("chat"))

    def test_chat_unlocks_with_affection(self):
        self.store.set_affection(120)
        show_menu(self.window)
        self.assertTrue(self.menu.is_enabled("chat"))


class TestFeedingEndToEnd(WiringTestCase):
    """点卡片 → 扣库存 → 播动画 → 出台词（全程走真实组件）。"""

    def test_clicking_a_card_feeds_her(self):
        self.store.add_item("奶油面包", 2)
        speech: list[tuple[str, str]] = []
        self.controller.speech_requested.connect(
            lambda text, tone: speech.append((text, tone)))

        self.menu.action_triggered.emit("feed")
        panel = self.controller.panel_widget()
        self.assertEqual(panel.count_of("奶油面包"), 2)

        click(panel, panel.card_rect(0).center())
        settle()

        self.assertEqual(self.store.item_count("奶油面包"), 1)
        self.assertEqual(self.character.played, ["笑"])
        self.assertEqual(speech, [("奶油面包，给你留了一个。", "gentle")])
        self.assertFalse(panel.isVisible())                    # 送出去了才收面板
        self.assertEqual(self.store.affection, 1)

    def test_clicking_an_empty_card_keeps_the_panel_open(self):
        self.menu.action_triggered.emit("feed")
        panel = self.controller.panel_widget()
        click(panel, panel.card_rect(0).center())              # 库存 0
        settle()
        self.assertEqual(self.store.affection, 0)
        self.assertEqual(self.character.played, [])
        self.assertTrue(panel.isVisible())

    def test_speech_shows_the_speech_bubble(self):
        """喂食台词走真气泡（阶段 E）：controller 发信号 → `PetWindow` 弹出气泡。"""
        self.store.add_item("奶油面包", 1)
        self.controller.try_send("奶油面包")
        bubble = self.window.speech_bubble
        self.assertTrue(bubble.is_showing())
        self.assertEqual(bubble.text(), "奶油面包，给你留了一个。")
        self.assertTrue(bubble.isVisible())
        bubble.hide_now()


class TestCharacterSwap(WiringTestCase):
    def test_switching_to_png_disables_nurture_and_hides_the_panel(self):
        self.menu.action_triggered.emit("feed")
        panel = self.controller.panel_widget()
        self.assertTrue(panel.isVisible())

        self.window.set_character(FakeCharacter(character_type="png"))
        settle()
        self.assertFalse(panel.isVisible())

        self.store.add_item("奶油面包", 1)
        self.assertEqual(self.controller.try_send("奶油面包"), nc.RESULT_DISABLED)
        self.assertEqual(self.store.item_count("奶油面包"), 1)

    def test_switching_character_detaches_the_old_one(self):
        """换过角色后，喂食动画必须播在**新**角色上。"""
        show_menu(self.window)
        new_character = FakeCharacter()
        self.window.set_character(new_character)
        self.store.add_item("奶油面包", 1)
        self.controller.try_send("奶油面包")
        self.assertEqual(self.character.played, [])            # 旧角色不再收到播放
        self.assertEqual(new_character.played, ["笑"])


class TestSpeechBubbleWiring(WiringTestCase):
    """气泡与桌宠的接线：进出场、跟随拖动、抑制条件、不进仲裁器。"""

    def say(self, text="唔，好吃。", tone="gentle"):
        self.controller.speech_requested.emit(text, tone)

    def test_bubble_shows_and_hides(self):
        self.assertFalse(self.window.speech_bubble.isVisible())
        self.say()
        self.assertTrue(self.window.speech_bubble.isVisible())
        self.window.speech_bubble.hide_now()
        self.assertFalse(self.window.speech_bubble.isVisible())

    def test_bubble_is_not_in_the_arbiter(self):
        """03 规范第 7 节：对话气泡与所有弹层**可共存** —— 不能被面板挤掉。"""
        self.assertNotIn("nurture_bubble", self.window._popups())      # noqa: SLF001
        for widget in self.window._popups().values():                  # noqa: SLF001
            self.assertIsNot(widget, self.window.speech_bubble)

    def test_opening_a_panel_keeps_the_bubble(self):
        self.store.add_item("奶油面包", 1)
        self.say()
        self.window._toggle_function_panel()                          # noqa: SLF001
        settle()
        self.assertTrue(self.window.speech_bubble.isVisible())
        self.window.speech_bubble.hide_now()

    def test_disabled_config_suppresses_the_bubble(self):
        self.window._nurture_cfg = {"bubble_enabled": False}          # noqa: SLF001
        self.say()
        self.assertFalse(self.window.speech_bubble.isVisible())

    def test_mute_hours_suppress_the_bubble(self):
        """把"现在几点"钉死成凌晨 3 点，否则这条测试的成败取决于跑测试的时间。"""
        from datetime import datetime as _dt

        logged = []
        original = pw.nurture_dbg
        pw.nurture_dbg = logged.append
        self.addCleanup(lambda: setattr(pw, "nurture_dbg", original))

        class _FrozenDatetime:
            @staticmethod
            def now():
                return _dt(2026, 9, 10, 3, 0)

        original_dt = pw.datetime
        pw.datetime = _FrozenDatetime
        self.addCleanup(lambda: setattr(pw, "datetime", original_dt))

        self.window._nurture_cfg = {"mute_hours_enabled": True,           # noqa: SLF001
                                    "mute_hours_start": 23, "mute_hours_end": 7}
        self.assertTrue(self.window._in_mute_hours())                     # noqa: SLF001
        self.say()
        self.assertFalse(self.window.speech_bubble.isVisible())
        self.assertTrue(any("静音时段" in line for line in logged))

    def test_mute_hours_disabled_lets_the_bubble_through(self):
        from datetime import datetime as _dt

        class _FrozenDatetime:
            @staticmethod
            def now():
                return _dt(2026, 9, 10, 3, 0)

        original_dt = pw.datetime
        pw.datetime = _FrozenDatetime
        self.addCleanup(lambda: setattr(pw, "datetime", original_dt))

        self.window._nurture_cfg = {"mute_hours_enabled": False}          # noqa: SLF001
        self.assertFalse(self.window._in_mute_hours())                    # noqa: SLF001
        self.say()
        self.assertTrue(self.window.speech_bubble.isVisible())
        self.window.speech_bubble.hide_now()

    def test_anchor_ratio_config_overrides_the_character(self):
        """用户显式调过 `bubble_anchor_ratio` 就听用户的；还是默认 0.14 时用角色自报的。"""
        self.window._nurture_cfg = {"bubble_anchor_ratio": 0.25}          # noqa: SLF001
        self.assertAlmostEqual(self.window._speech_anchor_ratio(), 0.25, places=6)  # noqa: SLF001
        self.window._nurture_cfg = {"bubble_anchor_ratio": 0.14}          # noqa: SLF001
        self.assertAlmostEqual(self.window._speech_anchor_ratio(), 0.14, places=6)  # noqa: SLF001

    def test_drag_makes_the_bubble_follow(self):
        from PySide6.QtGui import QMouseEvent

        self.say()
        self.window.move(600, 400)
        self.say()                       # 重新贴一次，位置基于新的人物位置
        before = self.window.speech_bubble.tail_tip()
        self.window.move(900, 600)
        event = QMouseEvent(QEvent.MouseMove, QPointF(10, 10), QPointF(10, 10),
                            Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        self.window._dragging = True                                     # noqa: SLF001
        self.window.mouseMoveEvent(event)
        self.window._dragging = False                                    # noqa: SLF001
        after = self.window.speech_bubble.tail_tip()
        self.assertNotEqual(before, after)
        self.assertEqual(after.y(),
                         self.window.frameGeometry().top()
                         + int(self.window.frameGeometry().height() * 0.14))
        self.window.speech_bubble.hide_now()

    def test_anchor_comes_from_the_character(self):
        """尾巴锚点取角色的 `speech_anchor_ratio()`，不是写死的 0.14。"""
        class AnchorCharacter(FakeCharacter):
            def speech_anchor_ratio(self):
                return 0.3

        self.window.set_character(AnchorCharacter())
        self.say()
        bubble = self.window.speech_bubble
        self.assertAlmostEqual(bubble._anchor_ratio, 0.3, places=6)     # noqa: SLF001
        # 0.3 的锚点必须明显比默认 0.14 更低（不用等号：`set_character()` 刚 resize 过，
        # `frameGeometry()` 可能比真实窗口晚一拍才更新）
        self.assertGreater(bubble.tail_tip().y(),
                           self.window.frameGeometry().top() + 100)
        bubble.hide_now()

    def test_character_swap_hides_the_bubble(self):
        self.say()
        self.assertTrue(self.window.speech_bubble.isVisible())
        self.window.set_character(FakeCharacter(character_type="png"))
        self.assertFalse(self.window.speech_bubble.isVisible())

    def test_duration_comes_from_config(self):
        self.window._nurture_cfg["bubble_duration_ms"] = 2500            # noqa: SLF001
        self.say()
        self.assertEqual(self.window.speech_bubble._duration_ms, 2500)   # noqa: SLF001
        self.window.speech_bubble.hide_now()


class TestDialogueTriggers(WiringTestCase):
    """事件源接线：按键 / 音频 / 任何活动 / 长悬停 → 台词。"""

    def test_key_press_feeds_the_typing_rate(self):
        for _ in range(5):
            self.window.on_key_press()
        self.assertGreater(self.controller.typing_rate(), 0)

    def test_fast_typing_makes_her_comment_once(self):
        for _ in range(80):                       # 30 秒窗口内累计到阈值以上
            self.window.on_key_press()
        bubble = self.window.speech_bubble
        self.assertTrue(bubble.is_showing())
        self.assertEqual(bubble.text(), "敲得好快呀。")
        bubble.hide_now()

    def test_audio_playing_makes_her_comment(self):
        self.window.on_audio(playing=True)
        self.assertTrue(self.window.speech_bubble.is_showing())
        self.window.speech_bubble.hide_now()

    def test_muted_makes_her_comment(self):
        self.window.on_audio(muted=True)
        self.assertTrue(self.window.speech_bubble.is_showing())
        self.window.speech_bubble.hide_now()

    def test_any_activity_resets_the_idle_state(self):
        self.controller._last_activity_ts = 0.0                         # noqa: SLF001
        self.controller._afk_spoken = True                              # noqa: SLF001
        self.window.on_any_activity()
        self.assertFalse(self.controller._afk_spoken)                   # noqa: SLF001
        self.assertGreater(self.controller._last_activity_ts, 0.0)      # noqa: SLF001

    def test_without_a_controller_triggers_are_noops(self):
        """没有 controller 时（老用法）这些入口必须直接返回，不能崩。"""
        from src.pet_window import PetWindow

        plain = PetWindow(FakeCharacter())
        self.addCleanup(plain.deleteLater)
        plain.on_key_press()
        plain.on_audio(playing=True)
        plain.on_any_activity()
        self.assertIsNone(plain.nurture)

    def test_hover_long_line_when_the_menu_is_not_visible(self):
        self.assertFalse(self.window._hover_menu.isVisible())           # noqa: SLF001
        self.window._hovering = True                                    # noqa: SLF001
        self.window._on_hover_long_timeout()                            # noqa: SLF001
        self.assertTrue(self.window.speech_bubble.is_showing())
        self.assertEqual(self.window.speech_bubble.text(), "怎么一直看着我。")
        self.window.speech_bubble.hide_now()

    def test_hover_long_is_silent_while_the_menu_is_up(self):
        """01 文档 5.4：菜单弹出来时不做长悬停反应（她正被看着挑按钮）。"""
        self.window._hover_menu.show()                                  # noqa: SLF001
        self.window._hovering = True                                    # noqa: SLF001
        self.window._on_hover_long_timeout()                            # noqa: SLF001
        self.assertFalse(self.window.speech_bubble.is_showing())
        self.window._hover_menu.hide_now()                              # noqa: SLF001

    def test_hover_long_timer_runs_on_enter_and_stops_on_leave(self):
        enter_pet(self.window)
        self.assertTrue(self.window._hover_long_timer.isActive())       # noqa: SLF001
        from PySide6.QtCore import QEvent

        self.window.leaveEvent(QEvent(QEvent.Leave))
        self.assertFalse(self.window._hover_long_timer.isActive())      # noqa: SLF001

    def test_character_swap_stops_the_hover_long_timer(self):
        enter_pet(self.window)
        self.window.set_character(FakeCharacter(character_type="png"))
        self.assertFalse(self.window._hover_long_timer.isActive())      # noqa: SLF001


class TestWithoutController(unittest.TestCase):
    """`PetWindow(character)` 的老用法（阶段 C 行为）必须一模一样。"""

    def setUp(self):
        self._ctx = wired_window(with_controller=False)
        self.window, _controller, self.character, _store = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.menu = self.window._hover_menu                     # noqa: SLF001

    def test_no_nurture_key_in_popups(self):
        self.assertNotIn("nurture", self.window._popups())       # noqa: SLF001

    def test_menu_still_pops_up(self):
        show_menu(self.window)
        self.assertTrue(self.menu.isVisible())

    def test_all_buttons_are_available(self):
        """没有 controller 时不该出现一堆灰按钮（阶段 C 的观感）。"""
        show_menu(self.window)
        for key in self.menu.item_keys():
            self.assertTrue(self.menu.is_enabled(key), key)

    def test_action_without_a_controller_does_not_crash(self):
        logged = []
        original = pw.nurture_dbg
        pw.nurture_dbg = logged.append
        self.addCleanup(lambda: setattr(pw, "nurture_dbg", original))
        show_menu(self.window)
        self.menu.action_triggered.emit("feed")
        settle()
        self.assertFalse(self.menu.isVisible())
        self.assertIsNone(self.window.nurture)

    def test_hover_menu_shown_hook_still_called(self):
        show_menu(self.window)
        self.assertGreaterEqual(self.character.menu_shown, 1)


class TestPhaseFEntryPoints(unittest.TestCase):
    """阶段 F 的三个入口：悬停菜单提醒 / 托盘「今日签到」/ 托盘「养成状态」。

    > 断言用的是"controller 的哪个方法被调用了"，而不是"台词说了什么" ——
    > 台词内容由 `test_nurture_rewards.py` 负责，这里只管**接线接对没有**。
    """

    def setUp(self):
        self._ctx = wired_window()
        self.window, self.controller, self.character, self.store = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.speech: list[str] = []
        self.controller.speech_requested.connect(
            lambda text, _tone: self.speech.append(text))

    def _add_dialogue(self, scene: str, text: str) -> None:
        """往临时素材目录里补一个场景（`wired_window` 的 fixture 里没有它）。"""
        assets = os.path.join(os.path.dirname(os.path.dirname(self.store.path)), "nurture")
        with open(os.path.join(assets, "dialogues", f"{scene}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"scene": scene, "tone": "gentle", "cooldown_sec": 0,
                       "min_gap_sec": 0,
                       "lines": [{"text": text, "weight": 1}]}, handle, ensure_ascii=False)
        self.controller.reload_assets()

    # ── 悬停菜单 → 签到提醒（01 文档 4.1 第 2 条）──

    def test_menu_shown_asks_the_controller_for_a_reminder(self):
        self._add_dialogue("checkin_remind", "今天的份还没拿。")
        show_menu(self.window)
        self.assertIn("今天的份还没拿。", self.speech)

    def test_reminder_only_once_a_day(self):
        self._add_dialogue("checkin_remind", "今天的份还没拿。")
        show_menu(self.window)
        # 收起菜单再弹一次
        self.window._hover_menu.hide_now()                          # noqa: SLF001
        settle()
        self.speech.clear()
        show_menu(self.window)
        self.assertNotIn("今天的份还没拿。", self.speech)

    def test_reminder_survives_a_controller_exception(self):
        """提醒失败不能连累菜单弹出（她还在屏幕上，菜单该出来就要出来）。"""
        logged = []
        original = pw.nurture_dbg
        pw.nurture_dbg = logged.append
        self.addCleanup(lambda: setattr(pw, "nurture_dbg", original))
        self.controller.on_menu_shown = lambda: (_ for _ in ()).throw(RuntimeError)
        show_menu(self.window)
        self.assertTrue(self.window._hover_menu.isVisible())        # noqa: SLF001
        self.assertTrue(any("签到提醒失败" in line for line in logged))

    # ── 托盘 ──

    def test_tray_entries_visible_for_gif(self):
        self.window._refresh_tray_nurture()                          # noqa: SLF001
        self.assertTrue(self.window._tray_checkin_action.isVisible())    # noqa: SLF001
        self.assertTrue(self.window._tray_nurture_action.isVisible())    # noqa: SLF001

    def test_tray_entries_hidden_for_png(self):
        self.window.set_character(FakeCharacter(character_type="png"))
        self.window._refresh_tray_nurture()                          # noqa: SLF001
        self.assertFalse(self.window._tray_checkin_action.isVisible())   # noqa: SLF001
        self.assertFalse(self.window._tray_nurture_action.isVisible())   # noqa: SLF001

    def test_tray_entries_hidden_without_a_controller(self):
        with wired_window(with_controller=False) as (window, _c, _ch, _s):
            window._refresh_tray_nurture()                           # noqa: SLF001
            self.assertFalse(window._tray_checkin_action.isVisible())    # noqa: SLF001
            window._on_tray_checkin()                                # noqa: SLF001 - 不应抛
            window._on_tray_nurture_status()                         # noqa: SLF001

    def test_tray_checkin_action_disabled_after_checking_in(self):
        self.window._refresh_tray_nurture()                          # noqa: SLF001
        self.assertTrue(self.window._tray_checkin_action.isEnabled())    # noqa: SLF001
        self.controller.try_checkin()
        self.window._refresh_tray_nurture()                          # noqa: SLF001
        self.assertFalse(self.window._tray_checkin_action.isEnabled())   # noqa: SLF001

    def test_tray_checkin_calls_the_store(self):
        self.window._on_tray_checkin()                               # noqa: SLF001
        self.assertEqual(self.store.last_checkin_date, date.today())

    def test_tray_status_opens_the_status_tab(self):
        shown = []
        self.controller.show_panel = lambda geo, tab="food": shown.append(tab)
        self.window._on_tray_nurture_status()                        # noqa: SLF001
        self.assertEqual(shown, ["status"])

    def test_tray_labels_are_translated(self):
        for lang in ("zh", "en", "ja"):
            with self.subTest(lang=lang):
                self.assertTrue(tr("tray_checkin", lang))
                self.assertTrue(tr("tray_nurture_status", lang))
        self.window._on_language_changed("ja")                       # noqa: SLF001
        self.assertEqual(self.window._tray_checkin_action.text(),     # noqa: SLF001
                         tr("tray_checkin", "ja"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
