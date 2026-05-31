"""剪贴板历史存储——sqlite3 本地数据库"""
import hashlib
import os
import shutil
import sqlite3
import sys
import time


def _get_data_dir() -> str:
    """数据存储目录。PyInstaller 打包后数据保存在 exe 同级目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(__file__))


PROJECT_DIR = _get_data_dir()
DATA_DIR = os.path.join(PROJECT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "clipboard.db")
IMG_DIR = os.path.join(DATA_DIR, "clipboard_images")


def _ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)


class ClipboardStore:
    def __init__(self):
        _ensure_dirs()
        self._conn = sqlite3.connect(DB_PATH)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS clipboard_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                text_content TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                file_hash TEXT DEFAULT '',
                created_at REAL NOT NULL,
                pinned INTEGER DEFAULT 0
            )
        ''')
        self._conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_created_at ON clipboard_history(created_at DESC)'
        )
        self._conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_pinned ON clipboard_history(pinned)'
        )
        try:
            self._conn.execute(
                "ALTER TABLE clipboard_history ADD COLUMN file_hash TEXT DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # 列已存在
        self._conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_file_hash ON clipboard_history(file_hash)'
        )
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        self._conn.commit()

    # ── 写入 ──

    def add_text(self, text: str) -> int:
        cur = self._conn.execute(
            'INSERT INTO clipboard_history (type, text_content, created_at) VALUES (?, ?, ?)',
            ('text', text, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    def add_or_update_text(self, text: str) -> int:
        """文字去重：相同内容更新 created_at，否则新增。返回 item_id"""
        existing = self._conn.execute(
            'SELECT id FROM clipboard_history WHERE type = ? AND text_content = ? LIMIT 1',
            ('text', text),
        ).fetchone()
        if existing:
            self._conn.execute(
                'UPDATE clipboard_history SET created_at = ? WHERE id = ?',
                (time.time(), existing['id']),
            )
            self._conn.commit()
            return existing['id']
        return self.add_text(text)

    def add_image(self, image_path: str, file_hash: str = "") -> int:
        cur = self._conn.execute(
            'INSERT INTO clipboard_history (type, image_path, file_hash, created_at) VALUES (?, ?, ?, ?)',
            ('image', image_path, file_hash, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    def add_or_update_image(self, image_path: str, file_hash: str) -> int:
        """图片去重：5秒内相同哈希视为重复，更新时间戳并删除新文件。返回 item_id"""
        recent_cutoff = time.time() - 5
        existing = self._conn.execute(
            'SELECT id, image_path FROM clipboard_history '
            'WHERE type = ? AND file_hash = ? AND created_at >= ? '
            'ORDER BY created_at DESC LIMIT 1',
            ('image', file_hash, recent_cutoff),
        ).fetchone()
        if existing:
            self._conn.execute(
                'UPDATE clipboard_history SET created_at = ? WHERE id = ?',
                (time.time(), existing['id']),
            )
            self._conn.commit()
            try:
                os.remove(image_path)
            except FileNotFoundError:
                pass
            return existing['id']
        return self.add_image(image_path, file_hash)

    # ── 查询 ──

    def get_items(self, days: int = 0, search: str = "") -> list[dict]:
        """查询记录。days=0 表示全部时间；search 针对文字内容模糊搜索"""
        sql = 'SELECT * FROM clipboard_history WHERE 1=1'
        params: list = []

        if days > 0:
            cutoff = time.time() - days * 86400
            sql += ' AND created_at >= ?'
            params.append(cutoff)

        if search:
            sql += ' AND type = ? AND text_content LIKE ?'
            params.append('text')
            params.append(f'%{search}%')

        sql += ' ORDER BY pinned DESC, created_at DESC'
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, item_id: int) -> dict | None:
        row = self._conn.execute(
            'SELECT * FROM clipboard_history WHERE id = ?', (item_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── 置顶 ──

    def pin_item(self, item_id: int):
        current = self.get_by_id(item_id)
        if current is None:
            return
        new_val = 0 if current['pinned'] else 1
        self._conn.execute(
            'UPDATE clipboard_history SET pinned = ? WHERE id = ?', (new_val, item_id)
        )
        self._conn.commit()

    # ── 删除 ──

    def delete_item(self, item_id: int):
        item = self.get_by_id(item_id)
        if item is None:
            return
        if item['type'] == 'image' and item['image_path']:
            try:
                os.remove(item['image_path'])
            except FileNotFoundError:
                pass
        self._conn.execute('DELETE FROM clipboard_history WHERE id = ?', (item_id,))
        self._conn.commit()

    # ── 清理 ──

    def clear_all(self):
        """清除所有非置顶记录及其图片文件，保留置顶项"""
        items = self._conn.execute(
            'SELECT * FROM clipboard_history WHERE pinned = 0'
        ).fetchall()
        for row in items:
            item = dict(row)
            if item['type'] == 'image' and item['image_path']:
                try:
                    os.remove(item['image_path'])
                except FileNotFoundError:
                    pass
        self._conn.execute('DELETE FROM clipboard_history WHERE pinned = 0')
        self._conn.commit()

    def cleanup_expired(self, days: int):
        """删除超过指定天数的非置顶记录"""
        cutoff = time.time() - days * 86400
        expired = self._conn.execute(
            'SELECT * FROM clipboard_history WHERE pinned = 0 AND created_at < ?',
            (cutoff,),
        ).fetchall()
        for row in expired:
            item = dict(row)
            if item['type'] == 'image' and item['image_path']:
                try:
                    os.remove(item['image_path'])
                except FileNotFoundError:
                    pass
        self._conn.execute(
            'DELETE FROM clipboard_history WHERE pinned = 0 AND created_at < ?',
            (cutoff,),
        )
        self._conn.commit()

    # ── 设置 ──

    def get_cleanup_days(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = 'cleanup_days'"
        ).fetchone()
        return int(row['value']) if row else 7

    def set_cleanup_days(self, days: int):
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('cleanup_days', ?)",
            (str(days),),
        )
        self._conn.commit()

    # ── 图片路径 ──

    @staticmethod
    def make_image_path() -> str:
        """生成新的图片存储路径"""
        _ensure_dirs()
        filename = f"{int(time.time() * 1000)}.png"
        return os.path.join(IMG_DIR, filename)

    def close(self):
        self._conn.close()
