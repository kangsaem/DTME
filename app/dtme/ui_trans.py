"""화면 전환 고르기(컷편집): SVG 샘플 그림 격자 + 길이. 글자 없이 그림만, 이름은 툴팁."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout

from .project import FIRST_OK, TRANS_DEFAULT_SEC, TRANS_RANGE, TRANSITIONS

W, H = 120, 68
A, B, ARROW = "#3f6fa8", "#d9822b", "#f2f2f2"


def _frame(x, y, w, h, c, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}" {extra}/>'


def _arrow(x1, y1, x2, y2):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{ARROW}" stroke-width="4" '
            f'marker-end="url(#ah)"/>')


def svg_for(kind: str) -> str:
    """종류별 샘플 그림. A(파랑) = 앞 컷, B(주황) = 뒤 컷."""
    m = 6
    fw, fh = W - 2 * m, H - 2 * m
    body = ""
    if kind == "none":
        body = _frame(m, m, fw / 2, fh, A) + _frame(m + fw / 2, m, fw / 2, fh, B)
    elif kind == "dissolve":
        body = (f'<defs><linearGradient id="g"><stop offset="0" stop-color="{A}"/>'
                f'<stop offset="1" stop-color="{B}"/></linearGradient></defs>' + _frame(m, m, fw, fh, "url(#g)"))
    elif kind.startswith("wipe"):
        d = kind[4:]
        if d in ("left", "right"):
            # wipeleft: 경계선이 오른쪽→왼쪽으로 이동, 오른쪽부터 B
            bx = m + fw * 0.45
            body = (_frame(m, m, fw, fh, A) + (_frame(bx, m, m + fw - bx, fh, B) if d == "left" else
                                              _frame(m, m, fw - (bx - m), fh, B)))
            xb = bx if d == "left" else m + fw - (bx - m)
            body += f'<line x1="{xb}" y1="{m}" x2="{xb}" y2="{m + fh}" stroke="{ARROW}" stroke-width="2"/>'
            body += _arrow(xb + 22, H / 2, xb - 10, H / 2) if d == "left" else _arrow(xb - 22, H / 2, xb + 10, H / 2)
        else:
            by = m + fh * 0.45
            body = (_frame(m, m, fw, fh, A) + (_frame(m, by, fw, m + fh - by, B) if d == "up" else
                                              _frame(m, m, fw, fh - (by - m), B)))
            yb = by if d == "up" else m + fh - (by - m)
            body += f'<line x1="{m}" y1="{yb}" x2="{m + fw}" y2="{yb}" stroke="{ARROW}" stroke-width="2"/>'
            body += _arrow(W / 2, yb + 18, W / 2, yb - 8) if d == "up" else _arrow(W / 2, yb - 18, W / 2, yb + 8)
    elif kind in ("zoomin", "zoomout", "rotzoomin", "rotzoomout"):
        rot = kind.startswith("rot")
        inner_c, outer_c = (A, B) if kind.endswith("in") else (B, A)
        body = _frame(m, m, fw, fh, outer_c)
        tr = f'transform="rotate({-18 if rot else 0} {W / 2} {H / 2})"'
        body += _frame(W / 2 - fw * 0.28, H / 2 - fh * 0.28, fw * 0.56, fh * 0.56, inner_c,
                       f'stroke="{ARROW}" stroke-width="1.5" {tr}')
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            a = (W / 2 + sx * 16, H / 2 + sy * 9)
            b = (W / 2 + sx * 46, H / 2 + sy * 26)
            p, q = (a, b) if kind.endswith("in") else (b, a)
            body += _arrow(p[0], p[1], q[0], q[1])
        if rot:
            body += (f'<path d="M {W / 2 - 14} {H / 2 - 4} A 14 14 0 1 1 {W / 2 + 4} {H / 2 + 13}" fill="none" '
                     f'stroke="{ARROW}" stroke-width="2.5" marker-end="url(#ah)"/>')
    elif kind in ("fadeblack", "fadewhite"):
        mid = "#000000" if kind == "fadeblack" else "#ffffff"
        body = (f'<defs><linearGradient id="g"><stop offset="0" stop-color="{A}"/><stop offset="0.5" '
                f'stop-color="{mid}"/><stop offset="1" stop-color="{B}"/></linearGradient></defs>'
                + _frame(m, m, fw, fh, "url(#g)"))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<defs><marker id="ah" markerWidth="4" markerHeight="4" refX="2" refY="2" orient="auto">'
            f'<path d="M0,0 L4,2 L0,4 z" fill="{ARROW}"/></marker></defs>'
            f'<rect width="{W}" height="{H}" fill="#151515"/>{body}</svg>')


def icon_for(kind: str, scale: float = 1.0) -> QIcon:
    r = QSvgRenderer(QByteArray(svg_for(kind).encode()))
    pm = QPixmap(int(W * scale), int(H * scale))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, pm.width(), pm.height()))
    p.end()
    return QIcon(pm)


class TransitionDialog(QDialog):
    """선택한 컷 앞 경계의 전환을 고름. 그림 클릭 = 바로 적용하고 닫힘."""
    chosen = Signal(str, float)

    def __init__(self, current: dict, first: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("컷편집")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        cur = (current or {}).get("type", "none") or "none"
        dur = float((current or {}).get("dur", TRANS_DEFAULT_SEC))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.buttons = {}
        for i, (kind, name) in enumerate(TRANSITIONS):
            b = QToolButton()
            b.setIcon(icon_for(kind))
            b.setIconSize(QSize(W, H))
            b.setToolTip(name)
            b.setCheckable(True)
            b.setChecked(kind == cur)
            b.setAutoRaise(True)
            b.setStyleSheet("QToolButton{border:2px solid transparent; border-radius:3px;}"
                            "QToolButton:checked{border-color:#4a8fe0;} QToolButton:hover{border-color:#777;}")
            b.setEnabled(kind == "none" or not first or kind in FIRST_OK)
            b.clicked.connect(lambda _=False, k=kind: self._pick(k))
            grid.addWidget(b, i // 4, i % 4)
            self.buttons[kind] = b
        self.dur = QSlider(Qt.Horizontal)
        lo, hi = TRANS_RANGE
        self.dur.setRange(int(lo * 10), int(hi * 10))
        self.dur.setValue(int(round(dur * 10)))
        self.dur_lbl = QLabel()
        self.dur_lbl.setMinimumWidth(48)
        self.dur.valueChanged.connect(lambda v: self.dur_lbl.setText(f"{v / 10:.1f}초"))
        self.dur_lbl.setText(f"{self.dur.value() / 10:.1f}초")
        row = QHBoxLayout()
        row.addWidget(self.dur, 1)
        row.addWidget(self.dur_lbl)
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addLayout(row)

    def _pick(self, kind):
        self.chosen.emit(kind, self.dur.value() / 10)
        self.accept()
