import os
import sys
import tempfile
import shutil

sys.path.insert(0, r"E:\AI Program\DesktopPet")
os.chdir(r"E:\AI Program\DesktopPet")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt

app = QApplication([])

import src.clipboard_window as cw
from src.clipboard_store import ClipboardStore

tmp = tempfile.mkdtemp(prefix="wplib_")
cw.WALLPAPER_DIR = tmp

w = cw.ClipboardWindow(ClipboardStore())
d = cw.SettingsDialog(w._store, w)

made = []
for i, (r, g, b) in enumerate([(120, 160, 220), (200, 120, 120), (120, 200, 120)]):
    pm = QPixmap(100, 80)
    pm.fill(QColor(r, g, b))
    p = os.path.join(tmp, f"test_{i}.png")
    pm.save(p)
    made.append(p)

d._refresh_library()
print("lib count (3):", d._lib_list.count())

# apply item 0 (full path via Qt.UserRole)
item0 = d._lib_list.item(0)
d._on_library_clicked(item0)
applied_full = d._parent_window._wallpaper_path
print("applied full path matches item data:",
      applied_full == item0.data(Qt.UserRole))
print("highlight ok (selected item is the applied one):",
      d._lib_list.selectedItems()[0].data(Qt.UserRole) == applied_full)

# delete a NON-current item (item index 1) via the handler, monkeypatching QMessageBox
class FakeMB:
    Yes = 0
    No = 1
    @staticmethod
    def question(*a, **k):
        return FakeMB.Yes
cw.QMessageBox = FakeMB

victim_full = d._lib_list.item(1).data(Qt.UserRole)
d._lib_list.setCurrentItem(d._lib_list.item(1))
d._on_delete_library_item()
cw.QMessageBox = __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox
print("victim removed:", not os.path.exists(victim_full))
print("count after delete (2 files + 0):", d._lib_list.count())
print("current wallpaper preserved (not the victim):",
      d._parent_window._wallpaper_path == applied_full)

shutil.rmtree(tmp, ignore_errors=True)
d.close()
w.close()
w._store.close()
print("SMOKE OK")
