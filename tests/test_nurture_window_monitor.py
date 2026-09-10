"""`src/window_monitor.py` 单测 —— 前台感知的分类、边沿触发与**隐私红线**。

阶段 G 的三条硬性要求在这里逐条落成测试：

| 要求（01 文档 8.2） | 测试 |
|---------------------|------|
| 默认关闭，连对象都不创建 | `TestCreateMonitor` |
| 不出分类之外的信息 | `TestPolling`（信号 payload 只可能是分类）+ `TestPrivacySourceScan` |
| 不读窗口标题 | `TestPrivacySourceScan`（源码里根本没有那个 API） |

**不依赖真实前台窗口**：`WindowMonitor` 收一个可注入的探针（`probe=`），
测试全都喂假探针，所以结果与"跑测试的人此刻开着什么窗口"无关。
真实 ctypes 探针只在暂停点 G 由人实机验收（`probe_foreground()`）。

运行（项目根目录）：

    python -m unittest discover -s tests -t . -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src import window_monitor as wm  # noqa: E402

_APP = None
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PATH = os.path.join(PROJECT_DIR, "src", "window_monitor.py")
REAL_APPS = os.path.join(PROJECT_DIR, "assets", "nurture", "apps.json")

TABLE = {"code.exe": "code", "chrome.exe": "browser", "steam.exe": "game"}
IGNORE = frozenset({"keepassxc.exe"})


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class TestClassify(unittest.TestCase):
    """进程名 → 归一化分类。"""

    def test_known_processes(self):
        for exe, expected in (("code.exe", "code"), ("chrome.exe", "browser"),
                              ("steam.exe", "game")):
            with self.subTest(exe=exe):
                self.assertEqual(wm.classify_exe(exe, TABLE, IGNORE), expected)

    def test_matching_is_case_insensitive(self):
        """Windows 的文件名不区分大小写，用户手写 `Code.EXE` 也要认。"""
        for exe in ("Code.exe", "CODE.EXE", "  code.exe  "):
            with self.subTest(exe=exe):
                self.assertEqual(wm.classify_exe(exe, TABLE, IGNORE), "code")

    def test_unknown_process_is_unknown(self):
        self.assertEqual(wm.classify_exe("weird.exe", TABLE, IGNORE), "unknown")

    def test_blacklist_is_indistinguishable_from_unknown(self):
        """黑名单命中 → 和"不认识的应用"**完全一样**，不额外暴露任何信息。"""
        self.assertEqual(wm.classify_exe("keepassxc.exe", TABLE, IGNORE), "unknown")
        self.assertEqual(wm.classify_exe("keepassxc.exe", TABLE, IGNORE),
                         wm.classify_exe("whatever.exe", TABLE, IGNORE))

    def test_empty_means_unreadable(self):
        """空串表示"读不到"，返回空串 —— 调用方据此保持上次分类。"""
        for bad in ("", None, "   "):
            with self.subTest(value=bad):
                self.assertEqual(wm.classify_exe(bad, TABLE, IGNORE), "")

    def test_dirty_input_does_not_raise(self):
        """脏数据一律当"读不到"（返回空串），而不是拼出一个 `[]` 这样的假进程名。"""
        for bad in (123, [], {}, 0.5, object()):
            with self.subTest(value=bad):
                self.assertEqual(wm.classify_exe(bad, TABLE, IGNORE), "")

    def test_only_returns_documented_keys(self):
        keys = {wm.classify_exe(name, TABLE, IGNORE)
                for name in ("code.exe", "chrome.exe", "steam.exe", "x.exe", "")}
        self.assertTrue(keys <= set(wm.APP_KEYS) | {wm.UNKNOWN_KEY, ""})


class TestAppTable(unittest.TestCase):
    """`apps.json` 的读取与容错。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_apps_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, data, name="apps.json"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle, ensure_ascii=False)
        return path

    def test_reads_categories_and_ignore(self):
        path = self.write({"categories": {"code": ["Code.exe"], "browser": ["MSEDGE.EXE"]},
                           "ignore": ["KeePassXC.exe"]})
        table, ignore = wm.load_app_table(path)
        self.assertEqual(table, {"code.exe": "code", "msedge.exe": "browser"})
        self.assertEqual(ignore, frozenset({"keepassxc.exe"}))

    def test_missing_file_degrades_to_empty(self):
        table, ignore = wm.load_app_table(os.path.join(self.tmp, "没有这个文件.json"))
        self.assertEqual(table, {})
        self.assertEqual(ignore, frozenset())

    def test_broken_json_degrades_to_empty(self):
        path = self.write("{ 这不是 JSON")
        self.assertEqual(wm.load_app_table(path), ({}, frozenset()))

    def test_unknown_category_is_skipped(self):
        """手误把 `browser` 写成 `brower` → 整组跳过，而不是凭空多出一个分类。"""
        path = self.write({"categories": {"brower": ["chrome.exe"], "code": ["code.exe"]}})
        table, _ = wm.load_app_table(path)
        self.assertEqual(table, {"code.exe": "code"})

    def test_non_list_and_non_string_entries_are_skipped(self):
        path = self.write({"categories": {"code": "code.exe",
                                          "browser": ["chrome.exe", 42, None, "", " ",
                                                      ["nested"]],
                                          "game": None},
                           "ignore": "keepassxc.exe"})
        table, ignore = wm.load_app_table(path)
        self.assertEqual(table, {"chrome.exe": "browser"})
        self.assertEqual(ignore, frozenset())

    def test_first_category_wins_for_a_duplicate(self):
        path = self.write({"categories": {"code": ["dup.exe"], "browser": ["dup.exe"]}})
        table, _ = wm.load_app_table(path)
        self.assertEqual(table, {"dup.exe": "code"})

    def test_default_path_points_at_the_asset(self):
        self.assertTrue(wm.default_apps_path().endswith(
            os.path.join("assets", "nurture", "apps.json")))
        self.assertTrue(os.path.isfile(wm.default_apps_path()))

    def test_real_asset_loads(self):
        table, ignore = wm.load_app_table(REAL_APPS)
        self.assertTrue(table, "真 apps.json 应该能读出东西")
        self.assertTrue(ignore)
        self.assertTrue(set(table.values()) <= set(wm.APP_KEYS))


class TestFullscreenGeometry(unittest.TestCase):
    """全屏判定只用几何：窗口矩形是否盖满它所在那块显示器。"""

    MONITOR = (0, 0, 1920, 1080)

    def test_exact_cover_is_fullscreen(self):
        self.assertTrue(wm.is_fullscreen_rect((0, 0, 1920, 1080), self.MONITOR))

    def test_maximized_window_is_not_fullscreen(self):
        """最大化只盖到工作区（差一条任务栏）—— 这正是用显示器矩形而不是工作区的原因。"""
        self.assertFalse(wm.is_fullscreen_rect((0, 0, 1920, 1040), self.MONITOR))

    def test_tolerance_covers_a_few_pixels(self):
        self.assertTrue(wm.is_fullscreen_rect((2, 1, 1918, 1079), self.MONITOR))
        self.assertTrue(wm.is_fullscreen_rect((-2, -2, 1922, 1082), self.MONITOR))
        self.assertFalse(wm.is_fullscreen_rect((4, 0, 1920, 1080), self.MONITOR))

    def test_secondary_monitor_uses_its_own_rect(self):
        """副屏在左边（负坐标）时，判据是**那块**显示器的矩形。"""
        self.assertTrue(wm.is_fullscreen_rect((-1920, 0, 0, 1080),
                                              (-1920, 0, 0, 1080)))
        self.assertFalse(wm.is_fullscreen_rect((-1920, 0, 0, 1080), self.MONITOR))

    def test_degenerate_rects_are_not_fullscreen(self):
        for window, monitor in (((0, 0, 0, 0), self.MONITOR),
                                (self.MONITOR, (0, 0, 0, 0)),
                                (None, self.MONITOR),
                                ("nonsense", self.MONITOR)):
            with self.subTest(window=window):
                self.assertFalse(wm.is_fullscreen_rect(window, monitor))

    def test_window_smaller_than_screen(self):
        self.assertFalse(wm.is_fullscreen_rect((100, 100, 800, 600), self.MONITOR))


class FakeProbe:
    """可编排的假探针：想让它报什么就报什么。"""

    def __init__(self):
        self.value = ("code.exe", False, 4242)
        self.calls = 0
        self.raise_next = False

    def __call__(self):
        self.calls += 1
        if self.raise_next:
            self.raise_next = False
            raise RuntimeError("探针炸了")
        return self.value


class TestPolling(unittest.TestCase):
    """边沿触发：只在分类真的变了时发信号，且只发归一化分类。"""

    def make(self, probe=None, path=None):
        probe = probe or FakeProbe()
        monitor = wm.WindowMonitor(apps_path=path or REAL_APPS, interval_ms=1000,
                                   probe=probe)
        self.addCleanup(monitor.deleteLater)
        self.apps: list[str] = []
        self.fulls: list[bool] = []
        monitor.app_changed.connect(self.apps.append)
        monitor.fullscreen_changed.connect(self.fulls.append)
        return monitor, probe

    def test_first_poll_only_records_state(self):
        """启动那一刻"你现在开着什么"不是一次切换 —— 她不该一睁眼就开始点评。"""
        monitor, _ = self.make()
        monitor.poll_once()
        self.assertEqual(self.apps, [])
        self.assertEqual(self.fulls, [])

    def test_second_poll_still_silent_when_unchanged(self):
        monitor, _ = self.make()
        monitor.poll_once()
        monitor.poll_once()
        monitor.poll_once()
        self.assertEqual(self.apps, [])

    def test_change_emits_exactly_once(self):
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser"])
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser"], "同一分类不该重复发信号")

    def test_a_single_unreadable_poll_keeps_the_previous_category(self):
        """一次抖动（安全桌面 / 进程刚退出）不该让她"换台"。"""
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()
        probe.value = ("", False, 3)          # 读不到一次
        monitor.poll_once()
        probe.value = ("chrome.exe", False, 4)
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser"])

    def test_persistent_unreadable_degrades_to_unknown(self):
        """**持续**读不到 → `unknown`（管理员进程、反作弊保护的窗口化游戏）。

        这条不能反过来"保持上次分类"：那样她会以为你还在用上一个应用，
        而那恰恰是最不该开口的时候。
        """
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()
        probe.value = ("", False, 3)
        for _ in range(wm.UNREADABLE_POLLS):
            monitor.poll_once()
        self.assertEqual(self.apps, ["browser", "unknown"])
        probe.value = ("", False, 4)
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser", "unknown"], "unknown 不该重复发")
        probe.value = ("code.exe", False, 5)
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser", "unknown", "code"])

    def test_unreadable_counter_resets_on_a_readable_poll(self):
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()
        for _ in range(wm.UNREADABLE_POLLS - 1):        # 差一拍到阈值
            probe.value = ("", False, 3)
            monitor.poll_once()
        probe.value = ("chrome.exe", False, 4)          # 读到了 → 计数归零
        monitor.poll_once()
        for _ in range(wm.UNREADABLE_POLLS - 1):
            probe.value = ("", False, 5)
            monitor.poll_once()
        self.assertEqual(self.apps, ["browser"], "计数没归零的话这里会多出一个 unknown")

    def test_fullscreen_still_reports_while_unreadable(self):
        """读不到进程名时，全屏状态照样要上报（几何判定不依赖进程名）。"""
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("", True, 2)
        monitor.poll_once()
        self.assertEqual(self.fulls, [True])
        self.assertEqual(self.apps, [], "还不到阈值，分类不动")

    def test_unknown_app_is_reported_as_unknown(self):
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("从未见过的.exe", False, 2)
        monitor.poll_once()
        self.assertEqual(self.apps, ["unknown"])

    def test_own_window_is_ignored(self):
        """她自己的窗口拿到焦点不算"你换了应用"，也不算全屏。"""
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("python.exe", False, os.getpid())
        monitor.poll_once()
        probe.value = ("chrome.exe", True, os.getpid())
        monitor.poll_once()
        self.assertEqual(self.apps, [])
        self.assertEqual(self.fulls, [], "自己的窗口也不可能触发全屏")
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser"])
        self.assertEqual(self.fulls, [], "全屏状态没变过，不该补发")
        probe.value = ("chrome.exe", True, 2)
        monitor.poll_once()
        self.assertEqual(self.fulls, [True])
        self.assertEqual(self.apps, ["browser"])

    def test_fullscreen_edges(self):
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("code.exe", True, 1)
        monitor.poll_once()
        probe.value = ("code.exe", True, 1)
        monitor.poll_once()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        self.assertEqual(self.fulls, [True, False])

    def test_fullscreen_and_category_are_independent(self):
        """同一个进程从窗口化变成全屏：分类没变，但全屏信号要发。"""
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("code.exe", True, 1)
        monitor.poll_once()
        self.assertEqual(self.apps, [])
        self.assertEqual(self.fulls, [True])

    def test_probe_exception_is_swallowed(self):
        monitor, probe = self.make()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.raise_next = True
        monitor.poll_once()                    # 不抛异常
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()
        self.assertEqual(self.apps, ["browser"])

    def test_payload_never_leaks_the_process_name(self):
        for exe, key in (("code.exe", "code"), ("绝密.exe", "unknown"),
                         ("chrome.exe", "browser")):
            with self.subTest(exe=exe):
                monitor, probe = self.make()
                probe.value = ("steam.exe", False, 1)
                monitor.poll_once()                    # 第一拍只记状态
                probe.value = (exe, False, 2)
                monitor.poll_once()
                self.assertEqual(self.apps, [key])
                self.assertNotIn(exe.lower(), " ".join(self.apps).lower())

    def test_listener_exception_does_not_break_the_timer(self):
        """接收方抛异常不能让轮询停摆（定时器里抛异常会被 Qt 静默吞掉后续）。"""
        monitor, probe = self.make()
        monitor.app_changed.connect(lambda _k: (_ for _ in ()).throw(RuntimeError("炸")))
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        probe.value = ("chrome.exe", False, 2)
        monitor.poll_once()                   # 不抛出去
        self.assertEqual(len(self.apps), 1)


class TestLifecycle(unittest.TestCase):
    """启停：默认不跑，关掉即停。"""

    def make(self, interval_ms: int = 1000):
        probe = FakeProbe()
        monitor = wm.WindowMonitor(apps_path=REAL_APPS, interval_ms=interval_ms,
                                   probe=probe)
        self.addCleanup(monitor.deleteLater)
        return monitor, probe

    def test_starts_disabled(self):
        monitor, _ = self.make()
        self.assertFalse(monitor.is_enabled())

    def test_start_stop(self):
        monitor, _ = self.make()
        monitor.start()
        self.assertTrue(monitor.is_enabled())
        monitor.stop()
        self.assertFalse(monitor.is_enabled())

    def test_reenabling_resyncs_instead_of_replaying_changes(self):
        """关掉期间你换了应用，重新打开那一刻**不该**补发一句"你换台了"。"""
        monitor, probe = self.make()
        monitor.start()
        probe.value = ("code.exe", False, 1)
        monitor.poll_once()
        monitor.stop()
        probe.value = ("chrome.exe", False, 2)
        monitor.start()
        apps = []
        monitor.app_changed.connect(apps.append)
        monitor.poll_once()
        self.assertEqual(apps, [])
        probe.value = ("code.exe", False, 3)
        monitor.poll_once()
        self.assertEqual(apps, ["code"])

    def test_interval_is_sane(self):
        monitor, _ = self.make()
        self.assertEqual(monitor.interval_ms(), 1000)
        weird, _ = self.make(interval_ms=0)
        self.assertGreaterEqual(weird.interval_ms(), 200, "别把轮询设成 0 去空转 CPU")
        broken, _ = self.make(interval_ms="abc")
        self.assertEqual(broken.interval_ms(), 1000)


class StubController(QObject):
    """假 controller：只记录被喂进来的分类，不做别的。"""

    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = bool(enabled)
        self.seen: list[str] = []
        self.fulls: list[bool] = []
        self.attached = "未调用"

    def foreground_detection_enabled(self) -> bool:
        return self.enabled

    def on_app_changed(self, key):
        self.seen.append(key)
        return None

    def on_fullscreen_changed(self, value):
        self.fulls.append(bool(value))

    def attach_window_monitor(self, monitor):
        """真 `NurtureController.attach_window_monitor()` 会按开关启停，这里照做。"""
        self.attached = monitor
        monitor.set_enabled(self.enabled)


class TestCreateMonitor(unittest.TestCase):
    """唯一创建入口 —— 隐私红线的第一条落在这里：默认关闭时对象都不存在。"""

    def test_disabled_by_default(self):
        self.assertIsNone(wm.create_monitor(StubController(enabled=False), {}))
        self.assertIsNone(wm.create_monitor(StubController(enabled=False)))

    def test_no_controller_and_no_config(self):
        self.assertIsNone(wm.create_monitor(None))
        self.assertIsNone(wm.create_monitor(None, None))

    def test_disabled_by_config_dict(self):
        self.assertIsNone(wm.create_monitor(None, {"allow_foreground_detection": False}))
        self.assertIsNone(wm.create_monitor(None, {"其它设置": 1}))
        self.assertIsNone(wm.create_monitor(None, "不是字典"))
        self.assertIsNone(wm.create_monitor(None, []))

    def test_enabled_by_config_starts_a_standalone_monitor(self):
        monitor = wm.create_monitor(None, {"allow_foreground_detection": True},
                                    apps_path=REAL_APPS)
        self.assertIsNotNone(monitor)
        self.addCleanup(monitor.deleteLater)
        self.assertTrue(monitor.is_enabled())

    def test_controller_decides_start(self):
        controller = StubController(enabled=True)
        monitor = wm.create_monitor(controller, apps_path=REAL_APPS)
        self.assertIsNotNone(monitor)
        self.addCleanup(monitor.deleteLater)
        self.assertIs(controller.attached, monitor, "启停权要交给 controller")
        self.assertTrue(monitor.is_enabled())

    def test_config_cannot_override_a_disabled_controller(self):
        """cfg 说开、活配置说关 → 对象建出来但不启动（以活配置为准）。"""
        controller = StubController(enabled=False)
        monitor = wm.create_monitor(controller, {"allow_foreground_detection": True},
                                    apps_path=REAL_APPS)
        self.assertIsNotNone(monitor)
        self.addCleanup(monitor.deleteLater)
        self.assertFalse(monitor.is_enabled())

    def test_signals_reach_the_controller(self):
        controller = StubController(enabled=True)
        monitor = wm.create_monitor(controller, apps_path=REAL_APPS,
                                    probe=lambda: ("code.exe", False, 1))
        self.addCleanup(monitor.deleteLater)
        monitor.poll_once()
        monitor.poll_once()
        monitor.app_changed.emit("browser")
        monitor.fullscreen_changed.emit(True)
        self.assertEqual(controller.seen, ["browser"])
        self.assertEqual(controller.fulls, [True])

    def test_broken_apps_path_still_creates_a_usable_monitor(self):
        """素材坏了也要能用（降级成"全是 unknown"），不能连带把感知一起废掉。"""
        controller = StubController(enabled=True)
        monitor = wm.create_monitor(controller, apps_path="不存在的目录/apps.json",
                                    probe=lambda: ("code.exe", False, 1))
        self.assertIsNotNone(monitor)
        self.addCleanup(monitor.deleteLater)
        monitor.poll_once()
        monitor.poll_once()
        self.assertEqual(controller.seen, [])


class TestRealProbe(unittest.TestCase):
    """真实探针在本机（Windows）至少要不抛异常、不返回垃圾。"""

    def test_probe_shape(self):
        exe, fullscreen, pid = wm.probe_foreground()
        self.assertIsInstance(exe, str)
        self.assertIsInstance(fullscreen, bool)
        self.assertIsInstance(pid, int)
        self.assertGreaterEqual(pid, 0)

    def test_foreground_window_is_classified_without_raising(self):
        exe, _full, _pid = wm.probe_foreground()
        key = wm.classify_exe(exe, *wm.load_app_table())
        self.assertIn(key, tuple(wm.APP_KEYS) + (wm.UNKNOWN_KEY, ""))


class TestMainWiring(unittest.TestCase):
    """`main._start_foreground_monitor()` —— 暂停点 G 的第一条硬性项就落在这里。

    默认关闭时**连对象都不存在**（不是"创建了但不生效"）。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nurture_main_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_pet(self, cfg):
        from types import SimpleNamespace

        from src import nurture_store as store_mod
        from src.nurture_controller import NurtureController

        store = store_mod.NurtureStore(path=os.path.join(self.tmp, "nurture.json"))
        controller = NurtureController(store, cfg,
                                       assets_dir=os.path.join(self.tmp, "assets"))
        self.addCleanup(controller.deleteLater)
        self.addCleanup(controller.attach_window_monitor, None)
        return SimpleNamespace(nurture=controller), controller

    def test_off_by_default_creates_nothing(self):
        import main

        pet, controller = self.make_pet({})
        self.assertIsNone(main._start_foreground_monitor(pet))      # noqa: SLF001
        self.assertFalse(controller.foreground_detection_active())

    def test_on_creates_a_running_monitor(self):
        import main

        pet, controller = self.make_pet({"allow_foreground_detection": True})
        monitor = main._start_foreground_monitor(pet)               # noqa: SLF001
        self.assertIsInstance(monitor, wm.WindowMonitor)
        self.addCleanup(monitor.stop)
        self.assertTrue(controller.foreground_detection_active())
        # 真正接上了：信号能走到 controller 的判断里
        monitor.app_changed.emit("meeting")
        self.assertEqual(controller.current_app_key(), "meeting")

    def test_without_a_controller_there_is_no_sensing(self):
        from types import SimpleNamespace

        import main

        self.assertIsNone(main._start_foreground_monitor(None))     # noqa: SLF001
        self.assertIsNone(main._start_foreground_monitor(SimpleNamespace()))  # noqa: SLF001

    def test_turning_the_switch_off_stops_it_immediately(self):
        import main

        pet, controller = self.make_pet({"allow_foreground_detection": True})
        monitor = main._start_foreground_monitor(pet)               # noqa: SLF001
        self.assertTrue(monitor.is_enabled())
        controller.set_config({"allow_foreground_detection": False})
        self.assertFalse(monitor.is_enabled())


class TestPrivacySourceScan(unittest.TestCase):
    """**静态**隐私自查（暂停点 G 的硬性项，不过就不算完成）。

    这几条比"运行时没看到日志"更硬：源码里根本不存在那条路径。
    """

    @classmethod
    def setUpClass(cls):
        with open(SOURCE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_never_reads_window_titles(self):
        """连标题都不读 —— 不是"读了不记"，是压根没有这个调用。"""
        for api in ("GetWindowText", "GetWindowTextW", "GetWindowTextLength",
                    "InternalGetWindowText", "RealGetWindowClass"):
            with self.subTest(api=api):
                self.assertNotIn(api, self.source)

    def test_never_reads_clipboard(self):
        for api in ("OpenClipboard", "GetClipboardData"):
            with self.subTest(api=api):
                self.assertNotIn(api, self.source)

    def test_never_writes_files_and_never_logs(self):
        """进程名不进日志、不落盘：这个模块不打印、不写文件、也不 import logging。"""
        self.assertNotIn("print(", self.source)
        self.assertNotIn("logging", self.source)
        for mode in ('"w"', "'w'", '"a"', "'a'"):
            with self.subTest(mode=mode):
                self.assertNotIn(mode, self.source)

    def test_documents_the_privacy_rules(self):
        self.assertIn("隐私红线", self.source)
        self.assertIn("不进日志", self.source)
