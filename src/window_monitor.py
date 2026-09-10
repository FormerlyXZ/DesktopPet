"""前台窗口感知 `WindowMonitor`（阶段 G）——ctypes，零第三方依赖。

与 `audio_monitor.py` 同构：`QTimer` 轮询 + **边沿触发**（只在分类真的变了时发信号），
区别是这里没有任何 COM，只有几个 Win32 调用。

隐私红线（01 文档 8.2，硬性）
────────────────────────────

1. **默认关闭**：`config.json` 的 `nurture.allow_foreground_detection` 为 `False` 时，
   监控对象**根本不会被创建**（`create_monitor()` 直接返回 `None`）。
   不是"创建了但不生效"——不存在这个对象，也就不存在感知。
2. **不出原始信息**：`app_changed` 发的是 `assets/nurture/apps.json` 的**查表结果**
   （`code` / `browser` / `game` / `meeting` / `media` / `unknown`）。
   原始进程名只在本模块内部用于查表，**不进日志、不落盘、不出模块**。
3. **连窗口标题都不读**：01 文档设想的做法是"读标题、只在本地匹配"，但本实现按
   **进程名**分类，根本用不到标题 —— 于是连那个 API 都不调：
   `grep` 整个文件也找不到任何取标题的调用。不存在"读到标题"的代码路径，
   比"读到了但不记"更硬。唯一额外读的是窗口**类名**（`GetClassNameW`），
   只用于排除桌面/任务栏这类系统窗口；那也是系统标识，不是用户内容。

全屏判定只用**几何**：前台窗口的可见矩形是否盖满它所在那块显示器的矩形。
用显示器矩形而不是工作区 —— 最大化窗口只盖到工作区（差一个任务栏），
所以不会被误判成"全屏"。
"""

from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import QObject, QTimer, Signal

from src import nurture_model as model
from src.nurture_store import project_dir

#: 归一化分类（01 文档 8.2）。`apps.json` 里的分类名只认这几个
APP_KEYS: tuple[str, ...] = model.APP_KEYS
#: 查不到 / 读不到 / 在黑名单里 → 一律归到这里
UNKNOWN_KEY: str = model.UNKNOWN_APP_KEY

#: 全屏判定的像素容差。窗口边框/缩放边缘会差一两个像素
FULLSCREEN_TOLERANCE = 2

#: 连续多少拍读不到进程名才算"真的读不到"（1 秒一拍 → 3 秒）。
#: 一次性的抖动（安全桌面、进程刚退出）不该让她"换台"；
#: 但**持续**读不到必须降级成 `unknown`：管理员进程、反作弊保护的窗口化游戏都在这类，
#: 而"她还以为你在用上一个应用"恰恰是最不该开口的时候。
#: 同一手法见 `audio_monitor.py` 的防抖计数。
UNREADABLE_POLLS = 3

#: 桌面/任务栏这类**系统外壳窗口**的类名。它们本来就"盖满屏幕"，
#: 但那是桌面而不是全屏应用 —— 不排除的话点一下桌面就会被当成全屏。
_SHELL_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd"})

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MONITOR_DEFAULTTONEAREST = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9


# ────────────────────────── 查表（纯函数，可单测）──────────────────────────


def default_apps_path() -> str:
    """`assets/nurture/apps.json`。"""
    return os.path.join(project_dir(), "assets", "nurture", "apps.json")


def load_app_table(path: str | None = None) -> tuple[dict[str, str], frozenset[str]]:
    """读 `apps.json` → `(进程名小写 → 分类, 黑名单)`。

    任何异常（文件缺失 / 坏 JSON / 结构不对）都返回空表：功能降级成"什么都是 unknown"，
    绝不崩、绝不阻塞桌宠本体。

    三条规则：

    - 进程名统一小写（Windows 文件名不区分大小写），查表时也转小写
    - 分类名不在 `APP_KEYS` 里 → **整组跳过**（防手误把 `browser` 写成 `brower` 后静默生效）
    - 同一进程名出现在多个分类 → **先出现的赢**（顺序即 `apps.json` 的书写顺序）
    """
    import json

    try:
        with open(path if path is not None else default_apps_path(),
                  "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}, frozenset()
    if not isinstance(data, dict):
        return {}, frozenset()

    table: dict[str, str] = {}
    categories = data.get("categories")
    if isinstance(categories, dict):
        for key, names in categories.items():
            category = str(key or "").strip().lower()
            if category not in APP_KEYS or not isinstance(names, (list, tuple)):
                continue
            for name in names:
                if not isinstance(name, str):
                    continue                  # 数字/列表/None 都不是进程名，直接跳过
                exe = name.strip().lower()
                if exe and exe not in table:
                    table[exe] = category

    ignore: set[str] = set()
    raw_ignore = data.get("ignore")
    if isinstance(raw_ignore, (list, tuple)):
        for name in raw_ignore:
            if not isinstance(name, str):
                continue
            exe = name.strip().lower()
            if exe:
                ignore.add(exe)
    return table, frozenset(ignore)


def classify_exe(exe: str, table: dict[str, str],
                 ignore: frozenset[str] | set[str] = frozenset()) -> str:
    """进程名 → 归一化分类。

    空进程名表示"读不到"（权限不足等），返回 `""` —— 调用方据此**保持上次分类**，
    不要发信号，免得权限抖动表现出"她在疯狂换台"。非字符串同理（脏数据当读不到）。
    黑名单命中的进程返回 `unknown`：和"不认识的应用"完全一样，不额外暴露任何信息。
    """
    if not isinstance(exe, str):
        return ""
    name = exe.strip().lower()
    if not name:
        return ""
    if name in ignore:
        return UNKNOWN_KEY
    return table.get(name, UNKNOWN_KEY)


def is_fullscreen_rect(window, monitor, tolerance: int = FULLSCREEN_TOLERANCE) -> bool:
    """窗口矩形是否盖满整块显示器。两个参数都是 `(left, top, right, bottom)`。"""
    values = []
    for rect in (window, monitor):
        try:
            values.append(tuple(int(v) for v in rect))
        except Exception:
            return False
    (wl, wt, wr, wb), (ml, mt, mr, mb) = values[0], values[1]
    if wr - wl <= 0 or wb - wt <= 0 or mr - ml <= 0 or mb - mt <= 0:
        return False
    tol = max(0, int(tolerance))
    return (wl <= ml + tol and wt <= mt + tol
            and wr >= mr - tol and wb >= mb - tol)


# ────────────────────────── Windows 探针 ──────────────────────────
#
# **必须显式声明 argtypes/restype**：64 位下 HWND/HANDLE 是 8 字节指针，
# 不声明会被 ctypes 当成 32 位 int 截断，表现为"随机失败"。

_IS_WINDOWS = sys.platform == "win32"
_user32 = None
_kernel32 = None
_dwmapi = None

if _IS_WINDOWS:
    from ctypes import wintypes

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    try:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        _user32 = None
        _kernel32 = None
    try:
        _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        _dwmapi = None            # 没有 DWM（老系统/服务器核心）→ 退回 GetWindowRect

    if _user32 is not None and _kernel32 is not None:
        _user32.GetForegroundWindow.argtypes = []
        _user32.GetForegroundWindow.restype = wintypes.HWND
        _user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        _user32.GetWindowRect.restype = wintypes.BOOL
        _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _user32.GetClassNameW.restype = ctypes.c_int
        _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        _user32.MonitorFromWindow.restype = wintypes.HANDLE
        _user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
        _user32.GetMonitorInfoW.restype = wintypes.BOOL

        _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _kernel32.OpenProcess.restype = wintypes.HANDLE
        _kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL

    if _dwmapi is not None:
        _dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def _process_name(pid: int) -> str:
    """进程号 → 可执行文件名（如 `Code.exe`）。**返回值不出本模块**。

    权限不足（管理员进程 / 受保护进程）时 `OpenProcess` 失败 → 返回空串，
    由上层当成"读不到"处理（保持上次分类），不报错也不留痕。
    """
    if not pid or _kernel32 is None:
        return ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    except Exception:
        return ""
    finally:
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass


def _window_class(hwnd) -> str:
    """窗口类名。只用来识别桌面/任务栏，不参与分类。"""
    if _user32 is None:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(256)
        if _user32.GetClassNameW(hwnd, buf, len(buf)):
            return buf.value
    except Exception:
        pass
    return ""


def _window_rect(hwnd):
    """窗口的**可见**矩形 `(l, t, r, b)`；失败返回 `None`。

    优先 `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`：它给的是肉眼看到的边框，
    无边框窗口与有边框窗口口径一致（`GetWindowRect` 会把不可见的缩放边缘也算进去）。
    """
    rect = wintypes.RECT()
    if _dwmapi is not None:
        try:
            if _dwmapi.DwmGetWindowAttribute(
                    hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect),
                    ctypes.sizeof(rect)) == 0:
                return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            pass
    try:
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    return None


def _monitor_rect(hwnd):
    """窗口所在那块显示器的矩形（副屏也正确）。失败返回 `None`。"""
    if _user32 is None:
        return None
    try:
        handle = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not handle:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return None
        rect = info.rcMonitor
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def _is_fullscreen(hwnd) -> bool:
    if _window_class(hwnd) in _SHELL_CLASSES:
        return False        # 桌面 / 任务栏：盖满屏幕不等于"全屏应用"
    rect = _window_rect(hwnd)
    if rect is None:
        return False
    monitor = _monitor_rect(hwnd)
    if monitor is None:
        return False
    return is_fullscreen_rect(rect, monitor)


def probe_foreground() -> tuple[str, bool, int]:
    """真实探针：`(前台进程名, 是否全屏, 进程号)`。

    非 Windows / 任何一步失败 → `("", False, 0)`：读不到就"当作没变化"，
    比每秒钟抛一次异常安静得多。
    """
    if not _IS_WINDOWS or _user32 is None:
        return ("", False, 0)
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ("", False, 0)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid_value = int(pid.value)
        return (_process_name(pid_value), _is_fullscreen(hwnd), pid_value)
    except Exception:
        return ("", False, 0)


# ────────────────────────── 监控器 ──────────────────────────


class WindowMonitor(QObject):
    """前台窗口感知。**只发归一化分类，不发任何原始信息。**

    信号：

    - `app_changed(str)`：分类变了（`code`/`browser`/`game`/`meeting`/`media`/`unknown`）
    - `fullscreen_changed(bool)`：前台是否进入/退出全屏

    两者都是**边沿触发**，且第一拍只记状态不发信号 —— 启动那一刻"你现在开着什么"
    不是一次切换，她不该一睁眼就开始点评。
    """

    app_changed = Signal(str)
    fullscreen_changed = Signal(bool)

    def __init__(self, apps_path: str | None = None, interval_ms: int = 1000,
                 probe=None, parent=None):
        super().__init__(parent)
        self._table, self._ignore = load_app_table(apps_path)
        try:
            self._interval = max(200, int(interval_ms))
        except (TypeError, ValueError):
            self._interval = 1000
        self._probe = probe if callable(probe) else probe_foreground
        self._last_key: str | None = None
        self._last_fullscreen = False
        self._first_poll = True
        self._unreadable_polls = 0
        self._enabled = False
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval)
        self._timer.timeout.connect(self.poll_once)

    # ── 查询 ──

    def is_enabled(self) -> bool:
        return bool(self._enabled)

    def interval_ms(self) -> int:
        return int(self._interval)

    # ── 生命周期 ──

    def set_enabled(self, enabled: bool) -> None:
        """开关感知。关掉即**立刻停**，并让下一拍重新同步状态（不补发中间的变化）。"""
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self._first_poll = True
            self._timer.start()
        else:
            self._timer.stop()

    def start(self) -> None:
        self.set_enabled(True)

    def stop(self) -> None:
        self.set_enabled(False)

    # ── 轮询 ──

    def poll_once(self) -> None:
        """立刻探一次。定时器与手工验证脚本都走这里（测试也用它，不必碰私有方法）。"""
        try:
            exe, fullscreen, pid = self._probe()
        except Exception:
            return                      # 探针炸了 → 这一拍当作什么都没发生
        try:
            own = int(pid) == os.getpid()
        except (TypeError, ValueError):
            own = False
        if own:
            return                      # 她自己的窗口拿到焦点不算"你换了应用"

        key = classify_exe(exe, self._table, self._ignore) if exe else ""
        if key:
            self._unreadable_polls = 0
        else:
            self._unreadable_polls += 1
            # 还不到阈值 → `None`：保持上次分类，不发信号（抖动不该让她换台）
            key = (UNKNOWN_KEY if self._unreadable_polls >= UNREADABLE_POLLS else None)
        full = bool(fullscreen)

        if self._first_poll:
            self._first_poll = False
            self._last_fullscreen = full
            if key:
                self._last_key = key
            return

        if key and key != self._last_key:
            self._last_key = key
            self._emit(self.app_changed, key)
        if full != self._last_fullscreen:
            self._last_fullscreen = full
            self._emit(self.fullscreen_changed, full)

    @staticmethod
    def _emit(signal, value) -> None:
        """发信号时不让接收方的异常炸到定时器里（定时器里抛异常会静默吞掉后续轮询）。"""
        try:
            signal.emit(value)
        except Exception:
            pass


def create_monitor(controller=None, cfg=None, *, apps_path: str | None = None,
                   interval_ms: int = 1000, probe=None, parent=None):
    """开关打开时创建并连线一个 `WindowMonitor`；否则返回 `None`。

    **唯一的创建入口**（`main.py` 与阶段 H 的设置页都走这里，免得两条路径走偏）。
    默认关闭时连对象都不存在 —— 这是 01 文档 8.2 隐私红线的第一条。

    `cfg` 不传时直接问 `controller.foreground_detection_enabled()`
    （**活的配置**，设置页改完立刻生效，不会拿着一份启动时的旧快照）。
    没有 controller 又没有 `cfg` → 返回 `None`：没人可连的感知器不该偷偷跑起来。

    连上后会调 `controller.attach_window_monitor()`，把启停权交给它。
    """
    if cfg is None and controller is not None:
        check = getattr(controller, "foreground_detection_enabled", None)
        if callable(check):
            try:
                cfg = {"allow_foreground_detection": bool(check())}
            except Exception:
                cfg = None
    if not (isinstance(cfg, dict) and bool(cfg.get("allow_foreground_detection", False))):
        return None
    try:
        monitor = WindowMonitor(apps_path=apps_path, interval_ms=interval_ms,
                                probe=probe, parent=parent)
    except Exception:
        return None
    if controller is None:
        monitor.start()
        return monitor

    try:
        monitor.app_changed.connect(controller.on_app_changed)
        monitor.fullscreen_changed.connect(controller.on_fullscreen_changed)
    except Exception:
        return None
    attach = getattr(controller, "attach_window_monitor", None)
    if callable(attach):
        try:
            attach(monitor)         # 由 controller 按开关决定启停
            return monitor
        except Exception:
            pass
    monitor.start()
    return monitor
