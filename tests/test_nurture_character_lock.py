"""`GifCharacter` 的养成锁（`_locked`）单测 —— 阶段 D 暂停点的重点。

背景：喂食动画播放期间必须**完全不可打断**（鼠标进出、单击、双击、面板按钮、
设置关闭、按键、音频、长悬停、AFK、重置 AFK），否则会出现"她一边吃东西一边被吓得跳起来"。
`_locked` 就是那个总开关。

它最容易出的两种错，这里各有一组测试盯着：

| 错误 | 症状 | 对应测试类 |
|------|------|------------|
| 锁不住 | 喂食动画被别的交互切掉 | `TestLockedBlocksEveryEntry` |
| 解不开 | 她**永远卡在**吃东西的动作上（状态机泄漏） | `TestUnlock` |

**怎么做到确定性**：测试自己在临时目录里生成一个**只有 2 帧、共 0.2 秒**的真 GIF，
拿它当假素材。真 GIF 才能让 `QMovie` 停在"正在播"上（用非动图文件当假素材会翻车：
`QMovie.start()` 对无效文件**同步**发 `finished`，锁会立刻被解开）。
不跑事件循环 → 帧不会推进 → 锁稳定停在"播放中"，所有断言都是确定的；
"播放完成"这一步由测试直接调 `_on_movie_finished()`（那正是 `QMovie.finished`
与帧号归零两条真实路径共同的落点）来模拟。
真让 GIF 自己跑完只用 `TestRealGifPlayback` 一个慢测试，素材库缺失时自动跳过。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QMovie  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.character_base import CharacterController  # noqa: E402
from src.gif_character import GifCharacter, State  # noqa: E402

_APP = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIF_DIR = os.path.join(PROJECT_ROOT, "素材库", "高木同学Q版gif")

#: 假素材路径，由 `setUpModule()` 写到临时目录里（模块级状态，`get_path()` 要用）
FAKE_MEDIA = ""


def build_two_frame_gif(delay_cs: int = 10) -> bytes:
    """手搓一个最简 GIF89a：1×1、2 色、2 帧、每帧 0.1 秒。

    66 字节，不含 NETSCAPE 循环扩展（所以播完会正常发 `finished`）。
    `QImageReader` 认得出（`imageCount() == 2`），`QMovie.isValid()` 为 True。
    """
    header = b"GIF89a"
    screen = b"\x01\x00\x01\x00\x80\x00\x00"                  # 1×1，有全局色表，2 色
    palette = b"\xff\xff\xff\x00\x00\x00"                     # 白 / 黑
    delay = bytes([0x21, 0xF9, 0x04, 0x00, delay_cs & 0xFF, delay_cs >> 8, 0x00, 0x00])
    frame = bytes([0x2C, 0, 0, 0, 0, 1, 0, 1, 0, 0]) + bytes([0x02, 0x02, 0x44, 0x01, 0x00])
    return header + screen + palette + delay + frame + delay + frame + b"\x3B"


def setUpModule():
    global _APP, FAKE_MEDIA, _TMP_DIR
    _APP = QApplication.instance() or QApplication([])
    _TMP_DIR = tempfile.mkdtemp(prefix="nurture_lock_test_")
    FAKE_MEDIA = os.path.join(_TMP_DIR, "takagi_蛋糕_0.gif")
    with open(FAKE_MEDIA, "wb") as handle:
        handle.write(build_two_frame_gif())


def tearDownModule():
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


def wait_until(predicate, timeout_ms: int = 8000, step_ms: int = 20) -> bool:
    """轮询等到条件成立。**不用固定 sleep** —— 动画时长不是我们能控制的量。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(step_ms / 1000.0)
    return predicate()


class FakeRegistry:
    """只做 动作名 → 路径 的映射，不扫素材库（单测不该依赖素材库在不在）。"""

    def __init__(self, actions=("加油", "害羞 2", "问号", "惊吓", "生气", "哭 1",
                                "点头", "摇头", "打字(普通)", "唱歌", "静音 1",
                                "笑", "蛋糕", "庆祝")):
        self._actions = list(actions)

    def has(self, action) -> bool:
        return action in self._actions

    def list_actions(self) -> list[str]:
        return list(self._actions)

    def get_path(self, action):
        return FAKE_MEDIA if action in self._actions else None


def make_character(**kwargs) -> GifCharacter:
    return GifCharacter(gif_dir="", registry=FakeRegistry(), **kwargs)


class LockTestCase(unittest.TestCase):
    """公共装置：一个假素材、未启动的角色。"""

    def setUp(self):
        self.character = make_character()

        def cleanup():
            try:
                self.character.stop()
            except RuntimeError:
                pass
            self.character.deleteLater()

        self.addCleanup(cleanup)
        self.character._afk_enabled = True           # noqa: SLF001
        self.character._afk_pool = ["加油"]           # noqa: SLF001

    def feed(self, action: str = "蛋糕", lock: bool = True) -> bool:
        return self.character.play_action(action, lock=lock)

    def finish_animation(self):
        """模拟"这段 GIF 播完了"（`QMovie.finished` 与帧号归零都落到这里）。"""
        self.character._on_movie_finished()          # noqa: SLF001

    # ── 装置自检：假素材必须真的能被 QMovie 认出来 ──
    # 这条很重要：用非动图文件当假素材时 `QMovie.start()` 会**同步**发 finished，
    # 锁当场被解开，下面所有"锁住期间"的测试都会变成假通过/假失败。

    def test_fake_media_is_a_real_animated_gif(self):
        movie = QMovie(FAKE_MEDIA)
        self.assertTrue(movie.isValid(), "假素材不是 QMovie 认得出来的动图")
        self.assertEqual(movie.frameCount(), 2)


class TestPlayAction(LockTestCase):
    """`play_action()` 的入口判断。"""

    def test_plays_and_locks(self):
        self.assertTrue(self.feed())
        self.assertEqual(self.character._state, State.INTERACTING)   # noqa: SLF001
        self.assertTrue(self.character._locked)                      # noqa: SLF001
        self.assertEqual(self.character._active_action, "蛋糕")       # noqa: SLF001

    def test_unknown_action_is_refused(self):
        self.assertFalse(self.feed("完全不存在的动作"))
        self.assertFalse(self.character._locked)                     # noqa: SLF001

    def test_empty_action_is_refused(self):
        self.assertFalse(self.character.play_action(""))
        self.assertFalse(self.character.play_action(None))           # type: ignore[arg-type]

    def test_refused_during_startup(self):
        """开场动画（到达→加载→加油）期间不许喂 —— 她还没"站好"。"""
        self.character._state = State.STARTUP                        # noqa: SLF001
        self.assertFalse(self.feed())
        self.assertEqual(self.character._state, State.STARTUP)       # noqa: SLF001

    def test_refused_while_already_locked(self):
        """喂食中再喂一次 → 拒绝（不是排队）。排队会让库存和动画对不上。"""
        self.assertTrue(self.feed("蛋糕"))
        self.assertFalse(self.feed("笑"))
        self.assertEqual(self.character._active_action, "蛋糕")       # noqa: SLF001

    def test_lock_false_does_not_lock(self):
        """摸头这类**可以**被打断的动作走 `lock=False`。"""
        self.character._state = State.IDLE                           # noqa: SLF001
        self.assertTrue(self.feed("笑", lock=False))
        self.assertFalse(self.character._locked)                     # noqa: SLF001

    def test_clears_pending_interaction_queue(self):
        self.character._interaction_queue.extend(["生气", "哭 1"])     # noqa: SLF001
        self.feed()
        self.assertEqual(self.character._interaction_queue, [])       # noqa: SLF001

    def test_stops_hover_and_afk_timers(self):
        self.character._state = State.IDLE                           # noqa: SLF001
        self.character._hover_timer.start(3000)                      # noqa: SLF001
        self.character._afk_timer.start(3000)                        # noqa: SLF001
        self.feed()
        self.assertFalse(self.character._hover_timer.isActive())      # noqa: SLF001
        self.assertFalse(self.character._afk_timer.isActive())        # noqa: SLF001

    def test_returns_true_only_when_it_really_started(self):
        self.assertTrue(self.feed())
        self.finish_animation()
        self.assertTrue(self.feed("笑"))     # 解锁之后可以再喂


class TestLockedBlocksEveryEntry(LockTestCase):
    """锁住之后，**每一个**交互入口都必须原地返回。"""

    def setUp(self):
        super().setUp()
        self.assertTrue(self.feed())
        self.assertTrue(self.character._locked)                      # noqa: SLF001

    def assert_still_feeding(self):
        self.assertEqual(self.character._state, State.INTERACTING)    # noqa: SLF001
        self.assertEqual(self.character._active_action, "蛋糕")       # noqa: SLF001
        self.assertTrue(self.character._locked)                      # noqa: SLF001

    def test_mouse_enter(self):
        self.character.handle_mouse_enter()
        self.assert_still_feeding()

    def test_mouse_leave(self):
        self.character.handle_mouse_leave()
        self.assert_still_feeding()

    def test_single_click(self):
        self.character.handle_single_click()
        self.assert_still_feeding()

    def test_double_click(self):
        self.character.handle_double_click()
        self.assert_still_feeding()
        self.assertEqual(self.character._dbl_click_step, 0)           # noqa: SLF001

    def test_panel_button(self):
        self.character.handle_panel_button_clicked()
        self.assert_still_feeding()

    def test_settings_close_and_discard(self):
        self.character.handle_settings_close()
        self.character.handle_settings_discard()
        self.assert_still_feeding()

    def test_key_press(self):
        self.character.handle_key_press()
        self.assert_still_feeding()

    def test_audio_playing(self):
        self.character.handle_audio_playing()
        self.assert_still_feeding()
        # `_audio_is_playing` 也不能被置位：否则喂完会直接切去"唱歌"
        self.assertFalse(self.character._audio_is_playing)            # noqa: SLF001

    def test_audio_stopped(self):
        self.character.handle_audio_stopped()
        self.assert_still_feeding()

    def test_audio_muted(self):
        self.character.handle_audio_muted()
        self.assert_still_feeding()

    def test_long_hover(self):
        self.character._on_long_hover()                              # noqa: SLF001
        self.assert_still_feeding()

    def test_afk_tick(self):
        self.character._on_afk_tick()                                # noqa: SLF001
        self.assert_still_feeding()

    def test_reset_afk_does_not_restart_the_timer(self):
        self.character.reset_afk()
        self.assertFalse(self.character._afk_timer.isActive())        # noqa: SLF001
        self.assert_still_feeding()


class TestUnlock(LockTestCase):
    """解锁的两条路：动画播完 / `release_lock()`。**锁不解开就是状态机泄漏。**"""

    def test_finishing_the_action_unlocks_and_returns_to_idle(self):
        self.feed()
        self.finish_animation()
        self.assertFalse(self.character._locked)                     # noqa: SLF001
        self.assertEqual(self.character._state, State.IDLE)           # noqa: SLF001

    def test_unlock_takes_precedence_over_the_click_chain(self):
        """解锁分支必须排在双击链分支**前面**，否则喂完会接着播「生气→哭」。

        （现实里锁定期内 `_dbl_click_step` 一定是 0 —— `play_action()` 会清掉它；
        这里人为制造残留，防的是以后有人挪动分支顺序或让锁能在链式播放中取得。）
        """
        self.feed()
        self.character._dbl_click_step = 1                            # noqa: SLF001
        self.finish_animation()
        self.assertEqual(self.character._state, State.IDLE)           # noqa: SLF001
        self.assertEqual(self.character._dbl_click_step, 0)           # noqa: SLF001

    def test_ten_feeds_in_a_row_never_leak(self):
        """暂停点 D 的核心检查：连喂 10 次，每次都能回到待机。"""
        for index in range(10):
            with self.subTest(round=index):
                self.assertTrue(self.feed("蛋糕"))
                self.finish_animation()
                self.assertEqual(self.character._state, State.IDLE)   # noqa: SLF001
                self.assertFalse(self.character._locked)             # noqa: SLF001
                self.assertFalse(self.character.is_busy())

    def test_release_lock_returns_to_idle(self):
        self.feed()
        self.character.release_lock()
        self.assertFalse(self.character._locked)                     # noqa: SLF001
        self.assertEqual(self.character._state, State.IDLE)           # noqa: SLF001

    def test_release_lock_is_idempotent(self):
        self.feed()
        self.character.release_lock()
        snapshot = self.character._state                              # noqa: SLF001
        self.character.release_lock()
        self.character.release_lock()
        self.assertEqual(self.character._state, snapshot)             # noqa: SLF001

    def test_release_lock_on_a_free_character_does_nothing(self):
        self.character._state = State.HOVER_IDLE                     # noqa: SLF001
        self.character.release_lock()
        self.assertEqual(self.character._state, State.HOVER_IDLE)     # noqa: SLF001

    def test_stop_clears_the_lock(self):
        """切角色/退出时不能留下悬空的锁，否则新角色一上来就不能交互。"""
        self.feed()
        self.character.stop()
        self.assertFalse(self.character._locked)                     # noqa: SLF001
        self.assertEqual(self.character._state, State.INACTIVE)       # noqa: SLF001

    def test_interaction_works_again_after_unlock(self):
        self.feed()
        self.finish_animation()
        self.character.handle_single_click()
        self.assertEqual(self.character._state, State.INTERACTING)    # noqa: SLF001
        self.assertEqual(self.character._active_action, "惊吓")       # noqa: SLF001

    def test_afk_timer_restarts_after_unlock(self):
        self.feed()
        self.finish_animation()
        self.assertTrue(self.character._afk_timer.isActive())         # noqa: SLF001


class TestBusy(LockTestCase):
    """`is_busy()` —— 悬停菜单与对话气泡共用的"她现在忙着吗"。"""

    def test_idle_is_not_busy(self):
        self.character._state = State.IDLE                           # noqa: SLF001
        self.assertFalse(self.character.is_busy())

    def test_startup_is_busy(self):
        """开场序列期间不该弹菜单（阶段 C 的已知缺口之一）。"""
        self.character._state = State.STARTUP                        # noqa: SLF001
        self.assertTrue(self.character.is_busy())

    def test_feeding_is_busy(self):
        self.feed()
        self.assertTrue(self.character.is_busy())

    def test_not_busy_after_feeding(self):
        self.feed()
        self.finish_animation()
        self.assertFalse(self.character.is_busy())

    def test_unlocked_interaction_is_not_busy(self):
        """单击/双击这类既有交互**不算** busy —— 否则悬停菜单会莫名其妙弹不出来。"""
        self.character._state = State.IDLE                           # noqa: SLF001
        self.character.handle_single_click()
        self.assertFalse(self.character.is_busy())


class TestHoverMenuHook(LockTestCase):
    """`handle_hover_menu_shown()` —— 菜单弹出后不该再冒「长悬停问号」。"""

    def test_stops_the_long_hover_timer(self):
        self.character._state = State.HOVER_IDLE                     # noqa: SLF001
        self.character._hover_timer.start(3000)                      # noqa: SLF001
        self.assertTrue(self.character._hover_timer.isActive())        # noqa: SLF001
        self.character.handle_hover_menu_shown()
        self.assertFalse(self.character._hover_timer.isActive())       # noqa: SLF001

    def test_reentering_restarts_it(self):
        """菜单收起后（鼠标离开再进来）长悬停要能重新计时。"""
        self.character._state = State.IDLE                           # noqa: SLF001
        self.character.handle_hover_menu_shown()
        self.character.handle_mouse_enter()
        self.assertTrue(self.character._hover_timer.isActive())        # noqa: SLF001

    def test_animation_keys_are_unchanged(self):
        """这个钩子只能停计时器，**不许**顺手换动画（否则就是"点开菜单她换动作"）。"""
        self.character._state = State.HOVER_IDLE                     # noqa: SLF001
        self.character._play_loop(self.character._hover_key)          # noqa: SLF001
        before = self.character._active_action                        # noqa: SLF001
        self.character.handle_hover_menu_shown()
        self.assertEqual(self.character._active_action, before)       # noqa: SLF001
        self.assertEqual(self.character._state, State.HOVER_IDLE)     # noqa: SLF001


class TestBaseDefaults(unittest.TestCase):
    """基类默认实现：`PngCharacter` 不改一行就能被养成层调用，且默认"不支持"。"""

    def setUp(self):
        self.controller = CharacterController()

    def test_play_action_defaults_to_false(self):
        self.assertFalse(self.controller.play_action("笑"))
        self.assertFalse(self.controller.play_action("笑", lock=False))

    def test_is_busy_defaults_to_false(self):
        self.assertFalse(self.controller.is_busy())

    def test_release_lock_is_a_noop(self):
        self.assertIsNone(self.controller.release_lock())

    def test_speech_anchor_ratio_defaults_to_14_percent(self):
        self.assertAlmostEqual(self.controller.speech_anchor_ratio(), 0.14, places=6)

    def test_hover_menu_hook_is_a_noop(self):
        self.assertIsNone(self.controller.handle_hover_menu_shown())

    def test_gif_character_overrides_them(self):
        character = make_character()
        self.addCleanup(character.deleteLater)
        self.assertEqual(character.speech_anchor_ratio(), 0.14)
        self.assertFalse(character.is_busy())


@unittest.skipUnless(os.path.isdir(GIF_DIR), "素材库/高木同学Q版gif 不存在，跳过真实播放测试")
class TestRealGifPlayback(unittest.TestCase):
    """真让 GIF 跑一遍：喂食 → 播完 → **自动**回到待机。

    其余测试都靠手工调 `_on_movie_finished()` 制造"播完"，这一个证明真实播放路径
    也能解锁 —— 也就是 `QMovie.finished` / 帧号归零那条链接对了。
    """

    @classmethod
    def setUpClass(cls):
        from src.gif_registry import GifRegistry

        registry = GifRegistry(GIF_DIR)
        actions = registry.list_actions()
        if not actions:
            raise unittest.SkipTest("素材库里没有可用 GIF")
        # 挑帧数最少的动作，把测试时间压到最低
        best_action, best_frames = None, None
        for action in actions:
            path = registry.get_path(action)
            if not path:
                continue
            movie = QMovie(path)
            frames = movie.frameCount()
            movie.deleteLater()
            if frames <= 1:
                continue
            if best_frames is None or frames < best_frames:
                best_action, best_frames = action, frames
        if best_action is None:
            raise unittest.SkipTest("素材库里没有多帧 GIF")
        cls.registry = registry
        cls.action = best_action
        cls.frames = best_frames

    def test_feed_plays_and_returns_to_idle_by_itself(self):
        character = GifCharacter(gif_dir=GIF_DIR, registry=self.registry)
        self.addCleanup(character.deleteLater)

        self.assertTrue(character.play_action(self.action, lock=True),
                        f"play_action 拒绝了 {self.action}")
        self.assertTrue(character._locked)                            # noqa: SLF001
        self.assertEqual(character._state, State.INTERACTING)          # noqa: SLF001

        # 帧数 × 最坏帧间隔（Q版素材普遍 ≤ 120ms）→ 给足余量
        timeout = max(6000, self.frames * 200)
        self.assertTrue(
            wait_until(lambda: character._state == State.IDLE, timeout),   # noqa: SLF001
            f"{self.action}（{self.frames} 帧）播完后没回到待机："
            f"state={character._state} locked={character._locked}",        # noqa: SLF001
        )
        self.assertFalse(character._locked)                            # noqa: SLF001
        self.assertFalse(character.is_busy())


if __name__ == "__main__":
    unittest.main(verbosity=2)
