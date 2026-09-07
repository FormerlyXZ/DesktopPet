import sqlite3
c = sqlite3.connect("data/clipboard.db")
ids = [r[0] for r in c.execute("SELECT id FROM clipboard_history ORDER BY id")]
print("count:", len(ids))
print("min:", ids[0], "max:", ids[-1])
print("ids tail:", ids[-12:])
tests = (
    "修复了右键系统面板定位，面板一角现在能对准鼠标了，类似 Windows 系统菜单。",
    "https://github.com/FormerlyXZ/DesktopPet/blob/main/src/clipboard_window.py",
    "明天记得提交代码、更新开发日志，并重新打包 EXE。",
)
for t in tests:
    n = c.execute(
        "SELECT COUNT(*) FROM clipboard_history WHERE text_content = ?", (t,)
    ).fetchone()[0]
    print("test-content row count:", n)
c.close()
