"""全局输入监听——pynput QThread，键盘/鼠标活动检测"""
from PySide6.QtCore import QThread, Signal


class InputMonitor(QThread):
    """在后台线程中运行 pynput 监听器，检测键盘按下和鼠标活动"""

    key_pressed = Signal()
    any_activity = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def run(self):
        try:
            from pynput import keyboard, mouse
        except ImportError:
            return

        self._running = True

        def on_press(_key):
            if not self._running:
                return False
            self.key_pressed.emit()
            self.any_activity.emit()

        def on_mouse(*_args):
            if not self._running:
                return False
            self.any_activity.emit()

        k_listener = keyboard.Listener(on_press=on_press)
        m_listener = mouse.Listener(on_move=on_mouse, on_click=on_mouse, on_scroll=on_mouse)
        k_listener.start()
        m_listener.start()

        while self._running:
            QThread.msleep(200)

        k_listener.stop()
        m_listener.stop()

    def stop(self):
        self._running = False
        self.quit()
        self.wait(2000)
