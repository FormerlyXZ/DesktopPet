"""剪贴板监控——QClipboard 信号 + 防抖"""
import hashlib
import os
from datetime import datetime
from PySide6.QtCore import QTimer, Signal, QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

from src.clipboard_store import ClipboardStore

_DEBUG_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug_img.log")

def _dbg(msg: str):
    try:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


class ClipboardMonitor(QObject):
    """监听系统剪贴板变化，写入 ClipboardStore"""

    content_added = Signal(int)  # item_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = ClipboardStore()
        self._clipboard = QApplication.clipboard()

        # 防抖：dataChanged 可能在一次复制中触发多次
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._on_debounced)

        self._clipboard.dataChanged.connect(self._on_data_changed)
        self._running = False

    @property
    def store(self) -> ClipboardStore:
        return self._store

    def start(self):
        self._running = True

    def stop(self):
        self._running = False
        self._debounce_timer.stop()

    def run_cleanup(self):
        """启动时调用，清理过期记录"""
        days = self._store.get_cleanup_days()
        self._store.cleanup_expired(days)

    # ── 内部 ──

    def _on_data_changed(self):
        if not self._running:
            return
        # 每次 dataChanged 都重启防抖，避免同一次复制触发多次记录
        self._debounce_timer.start()

    def _on_debounced(self):
        if not self._running:
            return

        # 先检查图片（应用同时复制文字+图片时，优先捕获图片）
        image = self._clipboard.image()
        if image and not image.isNull():
            _dbg(f"capture IMAGE: size={image.width()}x{image.height()}")
            path = self._store.make_image_path()
            ok = image.save(path, "PNG")
            _dbg(f"  QImage.save={ok} path={path}")
            if not ok:
                pix = self._clipboard.pixmap()
                if not pix.isNull():
                    ok2 = pix.save(path, "PNG")
                    _dbg(f"  QPixmap fallback save={ok2}")
                else:
                    _dbg("  QPixmap fallback is NULL, giving up")
                    return
            # 计算文件哈希用于图片去重（防止截屏工具产生重复记录）
            with open(path, "rb") as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
            _dbg(f"  file_hash={file_hash[:8]}...")
            item_id = self._store.add_or_update_image(path, file_hash)
            _dbg(f"  store.add_or_update_image id={item_id}")
            self.content_added.emit(item_id)
            return

        # 再检查文字（去重：同内容更新时间戳）
        text = self._clipboard.text()
        if text and text.strip():
            _dbg(f"capture TEXT: len={len(text)} preview={text[:50]}")
            item_id = self._store.add_or_update_text(text)
            self.content_added.emit(item_id)
            return
