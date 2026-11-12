"""버튼 모양 한 곳에서(v0.16.5, 사용자: 버튼 아래 그림자 없음 · 버튼 안 입체감은 모두).

방식: Qt 기본(Fusion) 스타일을 그대로 쓰고 '버튼 바탕 그리기'만 바꿈(BevelStyle) → 버튼 크기 계산은 예전과 같음.
(앱 전체 스타일시트를 쓰면 Fusion 의 '글자 버튼 최소 폭 80px'이 사라지고, min-width 를 넣으면 고정 크기 버튼까지 커져서 버림)
색 있는 버튼은 tone(b, "red") 처럼 이름으로. 왼쪽 정렬이 필요한 버튼 2종(묶음 머리 · 프리셋)만 같은 모양의 스타일시트(bevel()).

모서리 = 사각(라운딩 없음, v0.16.19 사용자). 입체감 = 위 → 아래 밝음 → 어두움 그라데이션 + 위 테두리 밝게 · 아래 테두리 어둡게. 눌림 = 그라데이션 뒤집음.
켜짐 = 파랑(#2f4f78 · 테두리 #4a8fe0). 꺼짐(비활성) = 어둡게.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPalette, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory, QStyleOptionButton

SEL_BLUE, EDGE_BLUE = "#2f4f78", "#4a8fe0"
BASE = "#383838"        # 일반 버튼 바탕

# 이름 → (바탕, 글자, 굵게)
TONES = {
    "red": ("#c0392b", "#ffffff", True),       # 렌더 · AUTO · 렌더리스트로 · 보정+렌더
    "orange": ("#d9822b", "#ffffff", True),    # 샘플
    "light": ("#c9c9c9", "#111111", True),     # 보정+편집
    "blue": (SEL_BLUE, "#ffffff", True),       # 확인
    "navy": ("#2f3b4d", "#e6e6e6", False),     # ▼ 타임라인으로
    "cut": ("#3a3a26", "#e6e6e6", False),      # [ 컷인 · 컷아웃 ]
    "key_on": ("#5a4a1a", "#f2c94c", False),   # ◆ 이 프레임에 키
    "overlay": ("#262626", "#dddddd", False),  # 모니터 위 버튼(반투명)
}


def _rgb(c: str):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def shade(c: str, d: int) -> str:
    """색을 d 만큼 밝게(+)/어둡게(−)."""
    r, g, b = (max(0, min(255, x + d)) for x in _rgb(c))
    return f"#{r:02x}{g:02x}{b:02x}"


def dim(bg: str) -> str:
    """꺼짐(비활성) 바탕: 짙은 회색(#3a3a3a) 쪽으로 55% → 색 있는 버튼도 확실히 꺼져 보이게."""
    a, b = _rgb(bg), _rgb("#3a3a3a")
    r, g, bl = (int(round(x * 0.45 + y * 0.55)) for x, y in zip(a, b))
    return f"#{r:02x}{g:02x}{bl:02x}"


def disabled_fg(fg: str) -> str:
    """꺼짐 글자: 회색(#8a8a8a) 쪽으로 60%."""
    a, b = _rgb(QColor(fg).name()), _rgb("#8a8a8a")
    r, g, bl = (int(round(x * 0.4 + y * 0.6)) for x, y in zip(a, b))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _light(bg: str) -> int:
    return 10 if sum(_rgb(bg)) > 450 else 22           # 밝은 버튼은 위쪽 하이라이트를 덜


def _steps(bg: str, state: str):
    """상태별 (위, 아래) 밝기 차."""
    lt = _light(bg)
    return {"normal": (lt, -16), "hover": (lt + 10, -6), "pressed": (-18, lt // 2), "disabled": (0, -24)}[state]


def _stops(bg: str, top: int, bottom: int):
    return [(0.0, shade(bg, top)), (0.48, shade(bg, top // 3)), (0.52, shade(bg, 0)), (1.0, shade(bg, bottom))]


# ------------------------------------------------------------------ 스타일시트 판 — 그리기와 같은 값
# DTME: 왼쪽 정렬 버튼 2종에만. MOSCO 처럼 버튼이 모두 고정 크기인 프로그램은 이걸로 전체 QSS 를 만들어도 됨(design/BUTTON_UI.md)
def _c(hexc: str, alpha: int) -> str:
    if alpha >= 255:
        return hexc
    r, g, b = _rgb(hexc)
    return f"rgba({r},{g},{b},{alpha})"


def _qgrad(bg: str, top: int, bottom: int, alpha: int = 255) -> str:
    st = ", ".join(f"stop:{pos} {_c(c, alpha)}" for pos, c in _stops(bg, top, bottom))
    return f"qlineargradient(x1:0,y1:0,x2:0,y2:1, {st})"


def _sel(sel: str, pseudo: str) -> str:
    return ", ".join(x.strip() + pseudo for x in sel.split(","))


def bevel(bg: str = BASE, fg: str = "#e6e6e6", bold: bool = False, radius: int = 0, extra: str = "",
          sel: str = "QPushButton", edge: str | None = None, alpha: int = 255, states: bool = True) -> str:
    """BevelStyle 과 같은 모양의 스타일시트. sel = 선택자(쉼표로 여럿), edge = 테두리 한 색(켜짐 #4a8fe0), alpha = 반투명."""
    lt = _light(bg)
    w = "font-weight:700;" if bold else ""
    if edge:
        border = f"border:1px solid {edge}; border-top-color:{shade(edge, 30)};"
    else:
        border = (f"border:1px solid {_c(shade(bg, -28), alpha)}; border-top-color:{_c(shade(bg, lt + 14), alpha)};"
                  f" border-bottom-color:{_c(shade(bg, -42), alpha)};")
    css = (f"{_sel(sel, '')}{{color:{fg}; {w} {border} border-radius:{radius}px; background:{_qgrad(bg, *_steps(bg, 'normal'), alpha)}; {extra}}}")
    if not states:
        return css
    css += f"{_sel(sel, ':hover')}{{background:{_qgrad(bg, *_steps(bg, 'hover'), alpha)};}}"
    css += f"{_sel(sel, ':pressed')}{{background:{_qgrad(bg, *_steps(bg, 'pressed'), alpha)};"
    css += "}" if edge else f" border-top-color:{_c(shade(bg, -42), alpha)}; border-bottom-color:{_c(shade(bg, lt), alpha)};}}"
    css += (f"{_sel(sel, ':disabled')}{{color:{disabled_fg(fg)}; background:{_qgrad(dim(bg), *_steps(dim(bg), 'disabled'), alpha)};"
            f" border-color:{_c(shade(dim(bg), -28), alpha)};}}")
    return css


def bevel_on(sel: str = "QPushButton:checked", alpha: int = 255) -> str:
    """켜짐(파랑) 스타일시트 — sel 에 켜짐 선택자(예: 'QPushButton:checked, QPushButton[on="true"]')."""
    return bevel(SEL_BLUE, "#ffffff", sel=sel, edge=EDGE_BLUE, alpha=alpha)


HEAD = bevel("#2b2b2b", "#e0e0e0", bold=True, extra="text-align:left; padding:0 8px;")   # 접는 묶음 머리
PRESET = (bevel(BASE, extra="text-align:left; padding:0 8px;")                            # [프리셋: 이름 ▾]
          + bevel_on("QPushButton:checked") + "QPushButton:checked{text-align:left; padding:0 8px;}")   # 창 열림 = 파랑


# ------------------------------------------------------------------ 그리기
def _col(c: str, alpha: int) -> QColor:
    q = QColor(c)
    q.setAlpha(alpha)
    return q


def paint_bevel(p: QPainter, r: QRectF, bg: str, state: str, alpha: int = 255, radius: float = 0.0, edge: str | None = None):
    if state == "disabled":
        bg = dim(bg)
    top, bottom = _steps(bg, state)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    for pos, c in _stops(bg, top, bottom):
        g.setColorAt(pos, _col(c, alpha))
    p.setRenderHint(QPainter.Antialiasing, radius > 0)     # 사각(v0.16.19) = 안티앨리어싱 없이 선명한 모서리
    rr = r.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setPen(QPen(_col(edge, 255) if edge else _col(shade(bg, -28), alpha), 1))
    p.setBrush(g)
    p.drawRoundedRect(rr, radius, radius)
    if edge:                                   # 켜짐 · 고른 색 = 파란 테두리(위만 조금 밝게)
        p.setPen(QPen(_col(shade(edge, 30), 255), 1))
        p.drawLine(int(rr.left() + radius), int(rr.top()), int(rr.right() - radius), int(rr.top()))
        return
    lt = _light(bg)
    sunk = state == "pressed"
    p.setPen(QPen(_col(shade(bg, -42 if sunk else lt + 14), alpha), 1))     # 위 테두리
    p.drawLine(int(rr.left() + radius), int(rr.top()), int(rr.right() - radius), int(rr.top()))
    p.setPen(QPen(_col(shade(bg, lt if sunk else -42), alpha), 1))          # 아래 테두리
    p.drawLine(int(rr.left() + radius), int(rr.bottom()), int(rr.right() - radius), int(rr.bottom()))


def _state(opt) -> str:
    st = opt.state
    if not (st & QStyle.State_Enabled):
        return "disabled"
    if st & QStyle.State_Sunken:
        return "pressed"
    if st & QStyle.State_MouseOver:
        return "hover"
    return "normal"


class BevelStyle(QProxyStyle):
    """Fusion 그대로 + 버튼 바탕만 입체 그라데이션(모든 QPushButton · bevel 속성이 있는 QToolButton)."""

    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    def drawPrimitive(self, el, opt, p, w=None):
        if w is not None and (el == QStyle.PE_PanelButtonCommand or (el == QStyle.PE_PanelButtonTool and w.property("bevel"))):
            tone_ = w.property("tone") or ""
            color = w.property("tone_color") or ""
            bg = color or TONES.get(tone_, (BASE,))[0]
            alpha = 225 if tone_ == "overlay" else 255
            on = bool(opt.state & QStyle.State_On) and not color
            st = _state(opt)
            p.save()
            if on:                              # 켜짐 = 파랑
                paint_bevel(p, QRectF(opt.rect), SEL_BLUE, st if st != "disabled" else "normal", alpha, edge=EDGE_BLUE)
            else:
                paint_bevel(p, QRectF(opt.rect), bg, st, alpha, edge=EDGE_BLUE if w.property("tone_sel") else None)
            p.restore()
            return
        return super().drawPrimitive(el, opt, p, w)

    def drawControl(self, el, opt, p, w=None):
        if el == QStyle.CE_PushButtonLabel and w is not None:
            fg = TONES.get(w.property("tone") or "", (None, None))[1]
            if opt.state & QStyle.State_On and not w.property("tone_color"):
                fg = "#ffffff"
            if w.property("fg"):
                fg = w.property("fg")
            if fg:
                o = QStyleOptionButton(opt)
                pal = QPalette(o.palette)
                c = QColor(fg)
                if not (opt.state & QStyle.State_Enabled):
                    c = QColor(disabled_fg(fg))
                pal.setColor(QPalette.ButtonText, c)
                o.palette = pal
                return super().drawControl(el, o, p, w)
        return super().drawControl(el, opt, p, w)


def tone(b, name: str = "", color: str = "", fg: str = "", sel: bool = False):
    """버튼 색 종류(크기 계산은 그대로). name = TONES 키 / color = 임의 바탕(글자 색 칩) / fg = 글자 색만 / sel = 파란 테두리."""
    b.setProperty("tone", name or None)
    b.setProperty("tone_color", color or None)
    b.setProperty("fg", fg or None)
    b.setProperty("tone_sel", bool(sel))
    if name in TONES and TONES[name][2]:
        f = b.font()
        f.setBold(True)
        b.setFont(f)
    b.update()
    return b


# ------------------------------------------------------------------ 확인 창 (MOSCO confirm_save 와 같은 모양, v0.16.8)
TITLE_BG, TITLE_FG = "#232323", "#e6e6e6"      # 윈도우 제목 줄 = 프로그램 바탕과 같은 진회색(MOSCO v0.7.73 과 같은 값)


def tint_title(w) -> bool:
    """윈도우 기본 제목 줄은 그대로 두고 색만 진회색으로(최소화·최대화·닫기·가장자리 붙이기 유지) — MOSCO tint_title 과 같음(v0.16.58).
    윈도우 11: 제목 줄·테두리·글자 색. 윈도우 10: '어두운 제목 줄'만. 그 밖 OS·실패 = 아무 일 없음."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(w.winId()))
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.restype = ctypes.c_long

        def ref(h):
            h = h.lstrip("#")
            return int(h[4:6] + h[2:4] + h[0:2], 16)      # COLORREF = 0x00BBGGRR

        def put(attr, val):
            v = ctypes.c_int(val)
            return dwm(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0
        put(20, 1) or put(19, 1)                    # 어두운 제목 줄(20 = 정식, 19 = 윈도우 10 초기판)
        put(35, ref(TITLE_BG))                      # 제목 줄 색(윈도우 11)
        put(34, ref(TITLE_BG))                      # 창 테두리 1px 색(윈도우 11)
        put(36, ref(TITLE_FG))                      # 제목 글자 색(윈도우 11)
        return True
    except Exception:  # noqa: BLE001
        return False


def _dlg_flags(parent):
    """확인·입력 창: 부모 창이 '항상 위'(프리셋 창)면 이 창도 항상 위 — 안 그러면 그 뒤에 가려져 프로그램이 멈춘 것처럼 보임(v0.16.58)."""
    fl = Qt.Dialog | Qt.FramelessWindowHint
    try:
        if parent is not None and (parent.window().windowFlags() & Qt.WindowStaysOnTopHint):
            fl |= Qt.WindowStaysOnTopHint
    except Exception:  # noqa: BLE001
        pass
    return fl


def _main_center(parent):
    """확인 창을 띄울 자리 = 맨 위 주 창의 가운데(떠 있는 도구 창(프리셋·샘플)에서 불러도 그 창에 겹치지 않게 — v0.16.61:
    프리셋 창 한가운데에 뜨면 겹침 순서가 틀어졌을 때 통째로 가려져 프로그램이 멈춘 것처럼 보였음)."""
    w = parent.window()
    for _ in range(4):
        up = w.parentWidget()
        if up is None:
            break
        w = up.window()
    return w.geometry().center()


def confirm(parent, text: str, buttons) -> str:
    """테두리 없는 어두운 확인 창. buttons = [(값, 글자, 폭, 색 이름|None), ...] 왼→오. Esc·바깥 = 'cancel'."""
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
    dlg = QDialog(parent, _dlg_flags(parent))
    dlg.setModal(True)
    dlg.setObjectName("Confirm")
    dlg.setStyleSheet("#Confirm{background:#262626; border:1px solid #555; border-radius:6px;}"
                      "QLabel{color:#e6e6e6; font-size:13px;}")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(24, 22, 24, 18)
    lay.setSpacing(20)
    lay.addWidget(QLabel(text))
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    res = {"v": "cancel"}
    for val, label, w, t in buttons:
        b = QPushButton(label)
        b.setFixedSize(w, 30)
        b.setFocusPolicy(Qt.NoFocus)
        if t:
            tone(b, t)
        b.clicked.connect(lambda _=False, v=val: (res.__setitem__("v", v), dlg.accept()))
        row.addWidget(b)
    lay.addLayout(row)
    if parent is not None and parent.isVisible():
        dlg.adjustSize()
        c = _main_center(parent)
        dlg.move(c.x() - dlg.width() // 2, c.y() - dlg.height() // 2)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: (dlg.raise_(), dlg.activateWindow()))      # 떠 있는 창들 위로
    dlg.exec()
    return res["v"]


def confirm_save(parent, text: str = "변경 내용을 저장할까요?") -> str:
    """닫기·새 프로젝트·불러오기 전. 반환 save|discard|cancel."""
    return confirm(parent, text, [("cancel", "취소", 72, None), ("discard", "저장 안 함", 92, None),
                                  ("save", "저장", 80, "red")])


def ask(parent, text: str, ok: str = "삭제", red: bool = True) -> bool:
    """[취소][ok] 확인 — 삭제·덮어쓰기."""
    return confirm(parent, text, [("cancel", "취소", 72, None), ("ok", ok, 80, "red" if red else "blue")]) == "ok"


def notice(parent, text: str):
    """알림·오류 [확인] 하나."""
    confirm(parent, text, [("ok", "확인", 80, None)])


def get_text(parent, text: str = "", placeholder: str = "이름") -> tuple[str, bool]:
    """이름 입력 창(QInputDialog 대신, 제목줄·제목 없음, v0.16.19). Enter = 확인, Esc = 취소. 반환 (글자, 확인?)."""
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout
    dlg = QDialog(parent, _dlg_flags(parent))
    dlg.setModal(True)
    dlg.setObjectName("Confirm")
    dlg.setStyleSheet("#Confirm{background:#262626; border:1px solid #555; border-radius:6px;}")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(14)
    ed = QLineEdit(text)
    ed.setPlaceholderText(placeholder)
    ed.setMinimumWidth(260)
    ed.selectAll()
    lay.addWidget(ed)
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    for label, fn, t in (("취소", dlg.reject, None), ("확인", dlg.accept, "blue")):
        b = QPushButton(label)
        b.setFixedSize(72 if t is None else 80, 30)
        b.setFocusPolicy(Qt.NoFocus)
        if t:
            tone(b, t)
        b.clicked.connect(fn)
        row.addWidget(b)
    lay.addLayout(row)
    ed.returnPressed.connect(dlg.accept)
    if parent is not None and parent.isVisible():
        dlg.adjustSize()
        c = parent.window().geometry().center()
        dlg.move(c.x() - dlg.width() // 2, c.y() - dlg.height() // 2)
    ok = dlg.exec() == QDialog.Accepted
    return ed.text(), ok
