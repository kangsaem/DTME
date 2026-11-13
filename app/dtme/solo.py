"""작업 중 창 하나만(v0.16.74, 사용자 2026-11-13): 자동 편집·AUTO 작업이 도는 동안 편집 창을 숨기고 그 작업 창만
작업 표시줄의 DTME 아이콘 하나로(진행 막대). 작업 창 오른쪽 위 [−] = 내림, 아이콘 누르면 작업 창만 뜸.
끝나거나 [취소]하면 편집 창을 원래대로(최대화였으면 최대화) 띄움.

Windows 에서 창 두 개가 아이콘 하나를 나눠 쓰며 '누르면 한쪽만' 뜨게 하기 어려워서 = 편집 창을 숨기고(아이콘에서도 빠짐)
작업 창을 주인 없는 창으로 바꿔 그 창이 아이콘이 되게 함. 제목줄 없는 창은 Windows 가 작업 표시줄에서 다시 못 띄울 수 있어
최소화 상자 스타일(WS_MINIMIZEBOX)을 직접 붙임."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from . import taskbar


def _allow_minimize(w) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        h = int(w.winId())
        GWL_STYLE, WS_MINIMIZEBOX, WS_SYSMENU = -16, 0x00020000, 0x00080000
        u = ctypes.windll.user32
        st = u.GetWindowLongW(h, GWL_STYLE)
        u.SetWindowLongW(h, GWL_STYLE, st | WS_MINIMIZEBOX | WS_SYSMENU)
    except Exception:  # noqa: BLE001
        pass


def min_button(dlg) -> QPushButton:
    """작업 창 오른쪽 위 [−](작업 중에만 보임)."""
    b = QPushButton("−")
    b.setToolTip("내리기")
    b.setFocusPolicy(Qt.NoFocus)
    b.setFixedSize(26, 22)
    b.setStyleSheet("QPushButton{color:#ddd; background:transparent; border:none; font-size:16px;}"
                    "QPushButton:hover{background:#3a3a3a;}")
    b.clicked.connect(dlg.showMinimized)
    b.setVisible(False)
    return b


def enter(dlg, main) -> bool:
    """편집 창 숨김 + 작업 창 = 주인 없는 창(작업 표시줄 아이콘). 이미 들어가 있거나 편집 창이 안 보이면 False."""
    if getattr(dlg, "_solo", None) is not None or main is None or not main.isVisible():
        return False
    dlg._solo = (main, main.windowState())
    pos = dlg.pos()
    mod = dlg.windowModality()
    dlg.setParent(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint)
    dlg.setWindowModality(mod)
    dlg.setWindowTitle(main.windowTitle() or "DTME")
    dlg.setWindowIcon(main.windowIcon())
    main.hide()
    dlg.move(pos)
    dlg.show()
    _allow_minimize(dlg)
    dlg.raise_()
    dlg.activateWindow()
    b = getattr(dlg, "b_min", None)
    if b is not None:
        b.setVisible(True)
    return True


def progress(dlg, v: float) -> None:
    if getattr(dlg, "_solo", None) is not None:
        taskbar.set_progress(dlg, v)


def leave(dlg, keep_dialog: bool = False) -> None:
    """편집 창을 원래대로. keep_dialog = 작업 창은 남김(AUTO 창 작업 중 [취소] — 다시 편집 창 위에)."""
    s = getattr(dlg, "_solo", None)
    if s is None:
        return
    dlg._solo = None
    main, state = s
    taskbar.clear(dlg)
    b = getattr(dlg, "b_min", None)
    if b is not None:
        b.setVisible(False)
    if state & Qt.WindowMaximized:
        main.showMaximized()
    else:
        main.showNormal()
    main.raise_()
    main.activateWindow()
    if keep_dialog and dlg.isVisible():
        if dlg.isMinimized():
            dlg.showNormal()
        dlg.raise_()
        dlg.activateWindow()
    if not main.isActiveWindow():
        QApplication.alert(main, 0)
