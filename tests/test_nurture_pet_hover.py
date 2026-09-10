"""`src/pet_window.py` 悬停菜单改造的**集成测试** —— 宽限期状态机。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v

这一组测的是阶段 C 的**成败标准的一半**："鼠标从人物移到菜单时菜单不能消失"。
它用真实的 `PetWindow` + 真实的 `QTimer`（靠 `QTest.qWait()` 驱动事件循环）+ 一个
**假角色**（避免加载 GIF 与启动序列，让状态机变成确定性的）。

**测不到的那一半**：真实的鼠标轨迹、窗口 z-order、Windows 往哪个 HWND 投递消息、
菜单会不会真的抢走输入焦点。这些必须在暂停点 C 实机验收 —— 见 04 文档阶段 C 的验证清单。

关键不变量（都在下面有对应测试）：
1. 菜单开着时鼠标离开人物 → **不立刻**切角色动画，进宽限期
2. 宽限期内鼠标进入菜单 → 取消收起，菜单保持
3. 宽限期到期仍不在菜单上 → 收起菜单，并**恰好补发一次** `handle_mouse_leave()`
4. 窄扫（没停留够延迟）→ 菜单不弹
5. 轮询的抑制条件（PNG 角色 / 养成关闭 / 设置窗口开着 / 不可打断动画中）→ 不弹
"""

import contextlib
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QEnterEvent, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import pet_window as pw  # noqa: E402
from src.character_base import CharacterController  # noqa: E402

_APP = None
#: 测试里用的短计时（毫秒），避免每个用例等好几百毫秒
DELAY_MS = 60
GRACE_MS = 60
SETTLE_MS = 40          # 收起动画 160ms，等它跑完
ANIM_SETTLE_MS = 260


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class FakeCharacter(CharacterController):
    """只记录调用、不播动画的假角色。`character_type` 可控，便于测抑制条件。"""

    def __init__(self, character_type: str = "gif", busy: bool = False):
        super().__init__()
        self._type = character_type
        self._busy = busy
        self.calls: list[str] = []
        self._pixmap = QPixmap(60, 100)
        self._pixmap.fill(QColor(255, 183, 197))

    # 接口实现
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
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def get_current_pixmap(self):
        return self._pixmap

    def get_idle_key(self) -> str:
        return "fake_idle"

    def get_hover_key(self) -> str:
        return "fake_hover"

    def set_idle_key(self, key: str):
        self.calls.append(f"set_idle:{key}")

    def set_hover_key(self, key: str):
        self.calls.append(f"set_hover:{key}")

    def get_available_animations(self) -> list[str]:
        return ["fake_idle", "fake_hover"]

    def handle_mouse_enter(self):
        self.calls.append("enter")

    def handle_mouse_leave(self):
        self.calls.append("leave")

    def handle_single_click(self):
        self.calls.append("single")

    def handle_double_click(self):
        self.calls.append("double")

    def handle_panel_button_clicked(self):
        self.calls.append("panel")

    def handle_settings_close(self):
        self.calls.append("settings_close")

    def handle_key_press(self):
        self.calls.append("key")

    def reset_afk(self):
        self.calls.append("afk_reset")

    def get_settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict):
        pass

    # 阶段 D 才会加进基类的方法，这里先提供，用于测"不可打断时不弹菜单"
    def is_busy(self) -> bool:
        return self._busy

    def count(self, name: str) -> int:
        return self.calls.count(name)


def _nurture_cfg(**overrides) -> dict:
    cfg = {
        "enabled": True,
        "hover_menu_delay_ms": DELAY_MS,
        "hover_grace_ms": GRACE_MS,
        "suppress_after_drag_ms": 60,
        "disable_long_hover_when_menu": True,
    }
    cfg.update(overrides)
    return {"character_type": "gif", "nurture": cfg, "language": "zh",
            "auto_start": False, "height": 500, "topmost": True,
            "position": None, "idle_animation": "x", "hover_animation": "y",
            "gif": {}}


@contextlib.contextmanager
def pet_window_with(config: dict, character: FakeCharacter):
    """构造一个真实 `PetWindow`，但把 `load_config()` 替换成测试配置。

    替换 `load_config` 而不是直接改 `config.json`，是为了让测试与用户的真实配置无关，
    同时也能方便地测"养成总开关关掉"这类分支。
    """
    original = pw.load_config
    pw.load_config = lambda: config
    window = None
    try:
        window = pw.PetWindow(character)
        yield window
    finally:
        pw.load_config = original
        if window is not None:
            window.function_panel.deleteLater()
            window.system_panel.deleteLater()
            window.settings.deleteLater()
            if window._hover_menu is not None:            # noqa: SLF001
                window._hover_menu.deleteLater()          # noqa: SLF001
            window.deleteLater()


def _enter_pet(window) -> None:
    """模拟鼠标进入人物窗口。"""
    window.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))


def _leave_pet(window) -> None:
    """模拟鼠标离开人物窗口（不走真实光标，直接调处理函数）。"""
    from PySide6.QtCore import QEvent
    window.leaveEvent(QEvent(QEvent.Leave))


def _click_pet(window) -> None:
    """在人物窗口正中投递一次完整的 按下→抬起（不依赖真实光标位置）。

    走的是**真实** `mousePressEvent` / `mouseReleaseEvent`，因此会经过
    "400ms 内没有第二次点击才算单击"的 `_click_timer` 那道门。
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    pos = QPointF(window.width() / 2, window.height() / 2)
    for event_type, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                                (QEvent.MouseButtonRelease, Qt.NoButton)):
        event = QMouseEvent(event_type, pos, pos, Qt.LeftButton, buttons,
                            Qt.NoModifier)
        QApplication.sendEvent(window, event)


def _enter_menu(window) -> None:
    from PySide6.QtCore import QEvent
    QApplication.sendEvent(window._hover_menu, QEvent(QEvent.Enter))   # noqa: SLF001


def _leave_menu(window) -> None:
    from PySide6.QtCore import QEvent
    QApplication.sendEvent(window._hover_menu, QEvent(QEvent.Leave))   # noqa: SLF001


class HoverMenuTestCase(unittest.TestCase):
    """共同前置：一个 GIF 假角色的 PetWindow。"""

    character_type = "gif"
    busy = False
    cfg_overrides: dict = {}

    def setUp(self):
        self.character = FakeCharacter(self.character_type, busy=self.busy)
        self.config = _nurture_cfg(**self.cfg_overrides)
        self._ctx = pet_window_with(self.config, self.character)
        self.window = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.menu = self.window._hover_menu                     # noqa: SLF001
        # `HoverMenu.under_mouse()` 读的是**真实全局光标位置**。在自动化测试里它取决于
        # 运行测试的人鼠标恰好停在哪 —— 会让"宽限期到期该不该收起菜单"变成随机结果
        # （实测：光标恰好落在菜单矩形内时，收菜单的断言会失败）。
        # 所以这里换成可控桩；两个分支都有专门的用例覆盖。
        self._under_mouse = False
        self.menu.under_mouse = lambda: self._under_mouse

    def wait_for_menu(self):
        """等到菜单**完全弹出来**（延迟计时器 + 200ms 弹出动画都跑完）。

        只等计时器是不够的：弹出动画跑完之前 `pos()` 还在动，位置断言必然是错的。
        """
        QTest.qWait(DELAY_MS + 40)
        QTest.qWait(ANIM_SETTLE_MS)
        return self.menu

    def wait_past_grace(self):
        """等到宽限期过期、并且收起动画也跑完。

        `hide_with_anim()` 是异步的（160ms 动画结束后才真正 `hide()`），
        所以 `isVisible()` 不能紧跟调用之后断言 —— 这是 `BubblePanel` 既有行为，
        不是本次改动引入的。
        """
        QTest.qWait(GRACE_MS + ANIM_SETTLE_MS)

    def settle(self, ms: int = ANIM_SETTLE_MS):
        """等面板的收起/弹出动画跑完。"""
        QTest.qWait(ms)

    def wait_until(self, predicate, timeout_ms: int = 2500, step_ms: int = 25) -> bool:
        """轮询等待条件成立，返回是否在超时前成立。

        **不要用固定 `qWait` 去等动画**：`hide_with_anim()` 是 160/180ms 的
        `QPropertyAnimation`，跑在事件循环里，整套测试并发跑时偶尔会晚几十毫秒 ——
        实测固定 sleep 会让用例约 20% 概率随机失败。等"条件成立"而不是"等一段时间"，
        才能把这个失败类别整体消掉。返回 `bool` 便于直接断言。
        """
        waited = 0
        while waited < timeout_ms:
            if predicate():
                return True
            QTest.qWait(step_ms)
            waited += step_ms
        return bool(predicate())


class TestHoverMenuAppears(HoverMenuTestCase):
    """弹出：需要"停留够久"，窄扫不弹。"""

    def test_menu_appears_after_delay(self):
        self.assertFalse(self.menu.isVisible())
        _enter_pet(self.window)
        QTest.qWait(10)
        self.assertFalse(self.menu.isVisible(), "延迟未到就弹了")
        self.wait_for_menu()
        self.assertTrue(self.menu.isVisible())
        self.assertEqual(self.character.count("enter"), 1)

    def test_quick_sweep_does_not_pop_the_menu(self):
        """鼠标快速扫过人物 → 不弹菜单（否则桌面会一直闪菜单）。"""
        _enter_pet(self.window)
        QTest.qWait(10)
        _leave_pet(self.window)
        QTest.qWait(DELAY_MS + 150)
        self.assertFalse(self.menu.isVisible())
        self.assertEqual(self.character.count("leave"), 1)

    def test_reenter_restarts_the_delay(self):
        _enter_pet(self.window)
        QTest.qWait(10)
        _leave_pet(self.window)
        _enter_pet(self.window)
        QTest.qWait(10)
        self.assertFalse(self.menu.isVisible())
        QTest.qWait(DELAY_MS + 90)
        self.assertTrue(self.menu.isVisible())

    def test_menu_is_shown_only_once_per_hover(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        self.assertTrue(self.menu.isVisible())
        first = self.menu.pos()
        QTest.qWait(DELAY_MS + 150)     # 继续停在人物上
        self.assertTrue(self.menu.isVisible())
        self.assertEqual(self.menu.pos(), first, "菜单被重复弹出/移位了")

    def test_menu_does_not_steal_activation(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        self.assertTrue(bool(self.menu.windowFlags() & Qt.WindowDoesNotAcceptFocus))


class TestGracePeriod(HoverMenuTestCase):
    """宽限期：鼠标从人物移到菜单的生死线。"""

    def test_menu_survives_leaving_the_pet(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)
        # 宽限期内：菜单还在，且**没有**切角色动画
        self.assertTrue(self.menu.isVisible())
        self.assertEqual(self.character.count("leave"), 0,
                         "宽限期内不该切角色动画（会出现'一边害羞一边加油'）")

    def test_entering_the_menu_cancels_the_grace(self):
        """**本阶段最关键的一条**：鼠标移到菜单上 → 菜单不消失，能点到按钮。"""
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)
        _enter_menu(self.window)
        self.wait_past_grace()
        self.assertTrue(self.menu.isVisible(), "鼠标移到菜单上后菜单消失了")
        self.assertEqual(self.character.count("leave"), 0)

    def test_leaving_both_closes_the_menu_and_restores_the_character(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)
        _enter_menu(self.window)
        _leave_menu(self.window)
        closed = self.wait_until(lambda: not self.menu.isVisible())
        self.assertTrue(closed, "宽限期过后菜单没有收起")
        self.assertEqual(self.character.count("leave"), 1,
                         "那次 leave 必须恰好补发一次，否则角色会永远卡在害羞态")

    def test_moving_back_to_the_pet_keeps_the_menu(self):
        """鼠标从菜单移回人物 → 都还活着。"""
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)
        _enter_menu(self.window)
        _leave_menu(self.window)
        _enter_pet(self.window)
        self.wait_past_grace()
        self.assertTrue(self.menu.isVisible())
        self.assertEqual(self.character.count("leave"), 0)

    def test_leaving_the_pet_without_menu_closes_nothing_extra(self):
        """菜单没弹出来时，离开人物的行为必须与改动前逐字一致。"""
        _enter_pet(self.window)
        QTest.qWait(10)
        _leave_pet(self.window)
        self.assertEqual(self.character.count("leave"), 1)
        self.assertFalse(self.window._hover_leave_deferred)     # noqa: SLF001

    def test_deferred_leave_is_never_lost(self):
        """反复在人物与菜单之间穿梭，最终 leave 必须且只能补发一次。"""
        _enter_pet(self.window)
        self.wait_for_menu()
        for _ in range(3):
            _leave_pet(self.window)
            _enter_menu(self.window)
            _leave_menu(self.window)
            _enter_pet(self.window)
        self.assertEqual(self.character.count("leave"), 0)
        # 鼠标已经回到人物身上 → 悬停恢复，那次被推迟的 leave 不再欠着
        self.assertFalse(self.window._hover_leave_deferred)     # noqa: SLF001
        _leave_pet(self.window)
        self.assertTrue(self.wait_until(lambda: self.character.count("leave") == 1))
        self.assertFalse(self.window._hover_leave_deferred)     # noqa: SLF001

    def test_no_double_leave_after_hover_resumes(self):
        """回归：鼠标回来过之后，陈旧的 deferred 标记不能导致补发两次 leave。"""
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)                 # 菜单开着 → 推迟一次 leave
        self.assertTrue(self.window._hover_leave_deferred)      # noqa: SLF001
        _enter_pet(self.window)                 # 回到人物 → 取消欠账
        self.assertFalse(self.window._hover_leave_deferred)     # noqa: SLF001
        self.menu.hide_now()                    # 菜单被点击关闭（等价效果）
        _leave_pet(self.window)                 # 菜单已不在 → 走原有分支，立刻 leave 一次
        self.assertEqual(self.character.count("leave"), 1)
        self.window._on_hover_grace_timeout()   # 手动走一次兜底路径
        self.assertEqual(self.character.count("leave"), 1, "leave 被补发了两次")

    def test_grace_timeout_without_ever_entering_the_menu(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))
        self.assertEqual(self.character.count("leave"), 1)

    def test_grace_timeout_keeps_the_menu_if_the_cursor_is_on_it(self):
        """兜底：`menu_entered` 万一没收到，只要光标确实在菜单上就不收（双保险）。"""
        _enter_pet(self.window)
        self.wait_for_menu()
        _leave_pet(self.window)
        self._under_mouse = True                # 光标确实在菜单矩形内
        self.wait_past_grace()
        self.assertTrue(self.menu.isVisible())
        self.assertEqual(self.character.count("leave"), 0)
        # 光标离开后（真正触发 menu_left）才收起
        self._under_mouse = False
        _leave_menu(self.window)
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))
        self.assertEqual(self.character.count("leave"), 1)


class TestSuppression(HoverMenuTestCase):
    """抑制条件（01 文档 5.1）。"""

    def test_png_character_never_gets_a_menu(self):
        """回归红线：默认服装（PNG）连函数都不该被调用到弹出菜单。"""
        self.character._type = "png"            # noqa: SLF001
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertFalse(self.menu.isVisible())
        self.assertFalse(self.window._hover_menu_allowed())     # noqa: SLF001

    def test_busy_character_suppresses_the_menu(self):
        self.character._busy = True             # noqa: SLF001
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertFalse(self.menu.isVisible())

    def test_unknown_is_busy_is_tolerated(self):
        """`is_busy()` 是阶段 D 才加进基类的方法 —— 没有它也不能崩。"""
        def boom():
            raise RuntimeError("对角色的探测失败")
        self.character.is_busy = boom
        self.assertFalse(self.window._character_busy())          # noqa: SLF001
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertTrue(self.menu.isVisible())

    def test_open_function_panel_suppresses_the_menu(self):
        self.window.function_panel.show()
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertFalse(self.menu.isVisible())
        self.window.function_panel.hide()

    def test_settings_window_suppresses_the_menu(self):
        self.window.settings.show()
        self.addCleanup(self.window.settings.hide)
        QTest.qWait(20)
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertFalse(self.menu.isVisible())


class TestNurtureDisabled(HoverMenuTestCase):
    """养成总开关关掉 → 悬停菜单完全不出现（数据仍保留，只是不参与交互）。"""

    cfg_overrides = {"enabled": False}

    def test_menu_never_appears(self):
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertFalse(self.menu.isVisible())
        self.assertFalse(self.window._hover_menu_allowed())     # noqa: SLF001

    def test_character_interaction_still_works(self):
        _enter_pet(self.window)
        self.assertEqual(self.character.count("enter"), 1)
        _leave_pet(self.window)
        self.assertEqual(self.character.count("leave"), 1)


class TestExistingBehaviourKept(HoverMenuTestCase):
    """回归：单击 / 右键的裁定与原有行为。

    2026-09-10 修订了其中一条：悬停菜单不再"吃掉"单击（详见下面第一条用例）。
    """

    def test_single_click_with_menu_open_also_opens_the_panel(self):
        """**2026-09-10 修订**：悬停菜单不再"吃掉"单击。

        原裁定（01 文档 5.4）是"菜单开着时单击 = 只收起菜单，不播惊吓、不弹功能面板"，
        实机上的表现却是"鼠标一放上去弹出喂养菜单，就再也点不出功能面板了，
        必须等菜单自己消失"。同一个局面下右键是能弹出系统面板的，左右键不一致本身就是 bug。

        现在的行为与"菜单没开时"逐字一致；收起悬停菜单由仲裁器顺带完成。
        """
        _enter_pet(self.window)
        self.wait_for_menu()
        self.assertTrue(self.menu.isVisible())
        self.window._click_pending = True                        # noqa: SLF001
        self.window._on_single_click_timeout()                   # noqa: SLF001
        self.assertEqual(self.character.count("single"), 1)
        self.assertTrue(self.window.function_panel.isVisible())
        # 互斥矩阵仍然成立：菜单被收起（`hide_with_anim()` 是异步的，必须轮询）
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))

    def test_real_click_with_menu_open_opens_the_panel(self):
        """同一件事走**真实鼠标事件**：按下→抬起→400ms 单击裁定→弹功能面板。

        上面那条用例直接调 `_on_single_click_timeout()`，测不到"事件真的进得来"
        （菜单不抢焦点、不吞鼠标）。这条把整条路补齐。
        """
        _enter_pet(self.window)
        self.wait_for_menu()
        _click_pet(self.window)
        self.assertTrue(self.wait_until(
            lambda: self.window.function_panel.isVisible()))
        self.assertEqual(self.character.count("single"), 1)
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))

    def test_single_click_without_menu_keeps_original_behaviour(self):
        """菜单没弹出时，单击仍是"惊吓 + 弹功能面板"。"""
        self.window._click_pending = True                        # noqa: SLF001
        self.window._on_single_click_timeout()                   # noqa: SLF001
        self.assertEqual(self.character.count("single"), 1)
        self.assertTrue(self.window.function_panel.isVisible())

    def test_right_click_closes_the_hover_menu(self):
        """菜单开着 → 右键弹系统面板时先收起菜单。"""
        _enter_pet(self.window)
        self.wait_for_menu()
        self.window._toggle_system_panel()                       # noqa: SLF001
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))
        self.assertTrue(self.window.system_panel.isVisible())

    def test_opening_the_function_panel_closes_the_hover_menu(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        self.window._toggle_function_panel()                     # noqa: SLF001
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))
        self.assertTrue(self.window.function_panel.isVisible())

    def test_two_existing_panels_remain_mutually_exclusive(self):
        self.window._toggle_function_panel()                     # noqa: SLF001
        self.assertTrue(self.window.function_panel.isVisible())
        self.window._toggle_system_panel()                       # noqa: SLF001
        self.assertTrue(self.wait_until(
            lambda: not self.window.function_panel.isVisible()))
        self.assertTrue(self.window.system_panel.isVisible())


class TestArbiter(HoverMenuTestCase):
    """面板仲裁器：收拢后对现有两个面板的行为必须等价。"""

    def test_popups_registry_contains_the_three_popups(self):
        self.assertEqual(set(self.window._popups()), {"function", "system", "hover"})  # noqa: SLF001

    def test_any_popup_visible(self):
        self.assertFalse(self.window.any_popup_visible())
        self.window.system_panel.show()
        self.assertTrue(self.window.any_popup_visible())
        self.assertTrue(self.window.any_popup_visible(("system",)))
        self.assertFalse(self.window.any_popup_visible(("function",)))
        self.window.system_panel.hide()
        self.assertFalse(self.window.any_popup_visible())

    def test_hide_all_popups_with_exception(self):
        self.window.function_panel.show()
        self.window.system_panel.show()
        self.window.hide_all_popups(except_key="system")
        self.assertTrue(self.wait_until(
            lambda: not self.window.function_panel.isVisible()))
        self.assertTrue(self.window.system_panel.isVisible())
        self.window.hide_all_popups()
        self.assertTrue(self.wait_until(
            lambda: not self.window.system_panel.isVisible()))

    def test_hide_all_popups_is_safe_when_nothing_is_visible(self):
        self.window.hide_all_popups()          # 不应抛异常
        self.assertFalse(self.window.any_popup_visible())


class TestHoverMenuActions(HoverMenuTestCase):
    """菜单按钮点击的路由（阶段 C 只有「设置」真接通）。"""

    def test_settings_action_opens_settings_and_closes_the_menu(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        self.addCleanup(self.window.settings.hide)
        self.window._on_hover_menu_action("settings")            # noqa: SLF001
        self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))
        self.assertTrue(self.window.settings.isVisible())

    def test_unwired_action_closes_the_menu_without_crashing(self):
        """阶段 D/F 之前，未接通的按钮只收起菜单并记日志，不做假装有反应的空实现。"""
        for action in ("feed", "gift", "checkin", "heart", "chat", "headpat"):
            with self.subTest(action=action):
                _enter_pet(self.window)
                self.wait_for_menu()
                self.window._on_hover_menu_action(action)        # noqa: SLF001
                self.assertEqual(self.window._last_hover_action, action)  # noqa: SLF001
                self.assertTrue(self.wait_until(lambda: not self.menu.isVisible()))


class TestDragSuppression(HoverMenuTestCase):
    """拖拽：拖动期间与结束后一小段时间内不弹菜单。"""

    def test_suppress_window_is_respected(self):
        import time
        self.window._suppress_hover_until = time.monotonic() + 0.3   # noqa: SLF001
        self.assertFalse(self.window._hover_menu_allowed())          # noqa: SLF001
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 60)
        self.assertFalse(self.menu.isVisible())
        QTest.qWait(320)
        _leave_pet(self.window)
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 90)
        self.assertTrue(self.menu.isVisible())

    def test_dragging_flag_suppresses(self):
        self.window._dragging = True                             # noqa: SLF001
        self.assertFalse(self.window._hover_menu_allowed())      # noqa: SLF001
        self.window._dragging = False                            # noqa: SLF001
        self.assertTrue(self.window._hover_menu_allowed())       # noqa: SLF001


class TestConfigReading(HoverMenuTestCase):
    """配置读取：脏值一律回落默认，不能让桌宠启动不了。"""

    def test_dirty_values_fall_back(self):
        self.window._nurture_cfg = {"hover_menu_delay_ms": "abc",       # noqa: SLF001
                                    "hover_grace_ms": None,
                                    "suppress_after_drag_ms": -5}
        self.assertEqual(self.window._hover_delay_ms(), 600)            # noqa: SLF001
        self.assertEqual(self.window._hover_grace_ms(), 350)            # noqa: SLF001
        self.assertEqual(self.window._drag_suppress_ms(), 0)            # noqa: SLF001

    def test_missing_keys_fall_back(self):
        self.window._nurture_cfg = {}                                   # noqa: SLF001
        self.assertEqual(self.window._hover_delay_ms(), 600)            # noqa: SLF001
        self.assertEqual(self.window._hover_grace_ms(), 350)            # noqa: SLF001


class TestCharacterSwap(HoverMenuTestCase):
    """热切换角色：换到 PNG 后菜单必须立刻消失且不再弹。"""

    def test_swap_to_png_hides_the_menu(self):
        _enter_pet(self.window)
        self.wait_for_menu()
        self.assertTrue(self.menu.isVisible())
        png = FakeCharacter("png")
        self.window.set_character(png)
        self.assertFalse(self.menu.isVisible())
        self.assertFalse(self.window._hover_menu_allowed())      # noqa: SLF001
        _enter_pet(self.window)
        QTest.qWait(DELAY_MS + 120)
        self.assertFalse(self.menu.isVisible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
