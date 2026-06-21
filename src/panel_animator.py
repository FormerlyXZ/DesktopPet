"""面板过渡动画：滑入+淡入 / 滑出+淡出"""
from PySide6.QtCore import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QPoint
from PySide6.QtWidgets import QGraphicsOpacityEffect


def animate_panel_show(widget, target_pos: QPoint, direction: str):
    """面板弹出动画——从弹出方向滑入并淡入。
    direction: "left" / "right" / "up" / "down" —— 面板在人物的哪一侧
    """
    _stop_anim(widget)
    offset = 40

    if direction == "left":
        start_pos = target_pos + QPoint(offset, 0)
    elif direction == "right":
        start_pos = target_pos + QPoint(-offset, 0)
    elif direction == "up":
        start_pos = target_pos + QPoint(0, offset)
    else:  # down
        start_pos = target_pos + QPoint(0, -offset)

    widget.move(start_pos)

    effect = QGraphicsOpacityEffect()
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    widget.show()

    pos_anim = QPropertyAnimation(widget, b"pos")
    pos_anim.setStartValue(start_pos)
    pos_anim.setEndValue(target_pos)
    pos_anim.setDuration(220)
    pos_anim.setEasingCurve(QEasingCurve.OutCubic)

    opacity_anim = QPropertyAnimation(effect, b"opacity")
    opacity_anim.setStartValue(0.0)
    opacity_anim.setEndValue(1.0)
    opacity_anim.setDuration(220)
    opacity_anim.setEasingCurve(QEasingCurve.OutCubic)

    group = QParallelAnimationGroup()
    group.addAnimation(pos_anim)
    group.addAnimation(opacity_anim)

    def _cleanup():
        widget.setGraphicsEffect(None)

    group.finished.connect(_cleanup)
    group.start()
    widget._panel_anim = group


def animate_panel_hide(widget, direction: str, on_finished=None):
    """面板关闭动画——向人物方向滑回并淡出
    关闭方向与弹出相反：面板在人物左侧 → 向右滑回，右侧 → 向左滑回
    """
    _stop_anim(widget)
    offset = 40
    current_pos = widget.pos()

    # 关闭时滑回人物方向（与弹出方向相反）
    if direction == "left":
        end_pos = current_pos + QPoint(offset, 0)    # 向右滑回
    elif direction == "right":
        end_pos = current_pos + QPoint(-offset, 0)   # 向左滑回
    elif direction == "up":
        end_pos = current_pos + QPoint(0, offset)    # 向下滑回
    else:  # down
        end_pos = current_pos + QPoint(0, -offset)   # 向上滑回

    effect = QGraphicsOpacityEffect()
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)

    pos_anim = QPropertyAnimation(widget, b"pos")
    pos_anim.setStartValue(current_pos)
    pos_anim.setEndValue(end_pos)
    pos_anim.setDuration(180)
    pos_anim.setEasingCurve(QEasingCurve.InCubic)

    opacity_anim = QPropertyAnimation(effect, b"opacity")
    opacity_anim.setStartValue(1.0)
    opacity_anim.setEndValue(0.0)
    opacity_anim.setDuration(180)
    opacity_anim.setEasingCurve(QEasingCurve.InCubic)

    group = QParallelAnimationGroup()
    group.addAnimation(pos_anim)
    group.addAnimation(opacity_anim)

    def _done():
        widget.hide()
        widget.setGraphicsEffect(None)
        if on_finished:
            on_finished()

    group.finished.connect(_done)
    group.start()
    widget._panel_anim = group


def _stop_anim(widget):
    """停止面板上正在运行的动画，并清理残留的图形效果"""
    anim = getattr(widget, "_panel_anim", None)
    if anim is not None:
        anim.stop()
        if hasattr(anim, 'clear'):
            anim.clear()
    widget.setGraphicsEffect(None)
