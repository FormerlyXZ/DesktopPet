"""DesktopPet 程序入口"""
import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from src.pet_window import PetWindow, ensure_position_on_screen
from src.config import load, save


def _create_character(config, project_dir):
    """根据配置创建角色"""
    character_type = config.get("character_type", "png")
    if character_type == "gif":
        from src.gif_character import GifCharacter
        gif_dir = os.path.join(project_dir, "素材库", "高木同学Q版gif")
        character = GifCharacter(gif_dir)
        character.apply_settings(config.get("gif", {}))
    else:
        from src.png_character import PngCharacter
        assets_dir = os.path.join(project_dir, "assets")
        character = PngCharacter(assets_dir)
        idle = config.get("idle_animation", "默认服装/默认待机")
        hover = config.get("hover_animation", "默认服装/挥手")
        character.set_idle_key(idle)
        character.set_hover_key(hover)
    return character


def _start_monitors(character):
    """启动行为检测监控器，返回 monitor 列表"""
    monitors = []
    try:
        from src.input_monitor import InputMonitor
        im = InputMonitor()
        im.key_pressed.connect(character.handle_key_press)
        im.any_activity.connect(character.reset_afk)
        im.start()
        monitors.append(im)
    except Exception:
        pass

    try:
        from src.audio_monitor import AudioMonitor
        am = AudioMonitor()
        am.audio_playing.connect(character.handle_audio_playing)
        am.audio_stopped.connect(character.handle_audio_stopped)
        am.audio_muted.connect(character.handle_audio_muted)
        am.start()
        monitors.append(am)
    except Exception:
        pass

    try:
        from src.clipboard_monitor import ClipboardMonitor
        cm = ClipboardMonitor()
        cm.run_cleanup()
        cm.start()
        monitors.append(cm)
    except Exception:
        pass
    return monitors


def _stop_monitors(monitors):
    """停止所有监控器"""
    for m in monitors:
        try:
            m.stop()
        except Exception:
            pass


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    font = QFont()
    font.setFamilies(["Microsoft YaHei", "Segoe UI Emoji", "sans-serif"])
    app.setFont(font)

    # ── 应用级图标 + Windows AppUserModelID ──
    # Windows 任务栏图标通常取自应用级图标 / AppUserModelID，
    # 单独对窗口 setWindowIcon 在无边框窗口上可能不生效。
    try:
        from src.clipboard_window import _make_window_icon
        app.setWindowIcon(_make_window_icon())
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "FormerlyXZ.DesktopPet"
            )
        except Exception:
            pass

    config = load()
    if getattr(sys, 'frozen', False):
        project_dir = sys._MEIPASS
    else:
        project_dir = os.path.dirname(__file__)

    character = _create_character(config, project_dir)
    pet = PetWindow(character)

    # 恢复设置
    pet.set_pet_height(config.get("height", 500))
    pet.auto_start = config.get("auto_start", False)
    pet.language = config.get("language", "zh")
    pet.function_panel.apply_language(pet.language)
    pet.system_panel.apply_language(pet.language)
    pet.set_topmost(config.get("topmost", True))

    saved_pos = config.get("position")
    if saved_pos:
        x, y = ensure_position_on_screen(
            saved_pos[0], saved_pos[1],
            pet.width(), pet.pet_height,
        )
        pet.move(x, y)
    else:
        pet.move_to_bottom_right()

    pet.show()

    monitors = _start_monitors(character)

    # 连线：剪贴板监控 → 历史窗口实时刷新
    for m in monitors:
        if hasattr(m, 'content_added'):
            m.content_added.connect(lambda _id: pet.refresh_clipboard_window())

    # ── 角色热切换 ──
    def on_character_swap(new_char_type, gif_settings):
        nonlocal character, monitors
        _stop_monitors(monitors)
        monitors.clear()

        new_config = {"character_type": new_char_type, "gif": gif_settings}
        character = _create_character(new_config, project_dir)
        pet.set_character(character)
        monitors = _start_monitors(character)

        # 重新连线剪贴板监控
        for m in monitors:
            if hasattr(m, 'content_added'):
                m.content_added.connect(lambda _id: pet.refresh_clipboard_window())

    pet.character_swap_needed.connect(on_character_swap)

    # 退出时保存
    def on_quit():
        data = {
            "character_type": pet.character.character_type,
            "height": pet.pet_height,
            "position": (pet.x(), pet.y()),
            "idle_animation": pet.character.get_idle_key(),
            "hover_animation": pet.character.get_hover_key(),
            "auto_start": pet.auto_start,
            "language": pet.language,
            "topmost": pet._topmost,
        }
        if pet.character.character_type == "gif":
            data["gif"] = pet.character.get_settings()
        save(data)
        _stop_monitors(monitors)

    app.aboutToQuit.connect(on_quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
