"""화면 전환 고르기(컷편집): 움직이는 샘플 격자 + 길이. 글자 없이 그림만, 이름은 툴팁."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from .project import FIRST_OK, TRANS_DEFAULT_SEC, TRANS_RANGE, TRANSITIONS

W, H = 120, 68
A, B = "#3f6fa8", "#d9822b"


class TransTile(QWidget):
    """전환 샘플: A(파랑) → B(주황) 전환을 실제와 같은 방식으로 반복 재생(정지 0.35초 · 전환 0.9초 · 정지 0.35초)."""
    clicked = Signal(str)
    CYCLE, HOLD = 1.6, 0.35

    def __init__(self, kind, name, a: QPixmap, b: QPixmap, parent=None):
        super().__init__(parent)
        self.kind, self.a, self.b = kind, a, b
        self.t = 0.0
        self.checked = False
        self.hover = False
        self.setToolTip(name)
        self.setFixedSize(W + 8, H + 8)
        self.setCursor(Qt.PointingHandCursor)

    def tick(self, t):
        self.t = t
        self.update()

    def progress(self):
        x = (self.t % self.CYCLE - self.HOLD) / (self.CYCLE - 2 * self.HOLD)
        return max(0.0, min(1.0, x))

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit(self.kind)

    def _draw_zoom(self, p, pix, s, deg, alpha=1.0):
        p.save()
        p.setOpacity(alpha)
        p.translate(W / 2, H / 2)
        p.rotate(deg)
        p.scale(s, s)
        p.drawPixmap(QRectF(-W / 2, -H / 2, W, H), pix, QRectF(pix.rect()))
        p.restore()

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        border = QColor("#4a8fe0") if self.checked else QColor("#777") if self.hover and self.isEnabled() else None
        if border:
            p.setPen(QPen(border, 2))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 3, 3)
        p.translate(4, 4)
        p.setClipRect(QRectF(0, 0, W, H))
        if not self.isEnabled():
            p.setOpacity(0.25)
        a, b, k = self.a, self.b, self.kind
        q = self.progress()
        full = QRectF(0, 0, W, H)
        if k == "none":
            p.drawPixmap(full, a if q < 0.5 else b, QRectF(a.rect()))
        elif k == "dissolve":
            p.drawPixmap(full, a, QRectF(a.rect()))
            p.setOpacity(q * p.opacity())
            p.drawPixmap(full, b, QRectF(b.rect()))
        elif k.startswith("wipe"):
            p.drawPixmap(full, a, QRectF(a.rect()))
            d = k[4:]
            r = {"left": QRectF(W * (1 - q), 0, W * q, H), "right": QRectF(0, 0, W * q, H),
                 "up": QRectF(0, H * (1 - q), W, H * q), "down": QRectF(0, 0, W, H * q)}[d]
            sr = QRectF(r.x() / W * b.width(), r.y() / H * b.height(), r.width() / W * b.width(),
                        r.height() / H * b.height())
            p.drawPixmap(r, b, sr)
        elif k in ("zoomin", "rotzoomin"):          # 앞 컷이 확대(회전)되며 뒤 컷으로
            u = q * q
            self._draw_zoom(p, a, 1 + 2 * u, (u * 30 if k == "rotzoomin" else 0))
            p.setOpacity(q * p.opacity())
            p.drawPixmap(full, b, QRectF(b.rect()))
        elif k in ("zoomout", "rotzoomout"):        # 뒤 컷이 확대 상태에서 원래로
            u = (1 - q) ** 2
            p.drawPixmap(full, a, QRectF(a.rect()))
            self._draw_zoom(p, b, 1 + 2 * u, (-u * 30 if k == "rotzoomout" else 0), q)
        elif k in ("fadeblack", "fadewhite"):
            c = QColor("black" if k == "fadeblack" else "white")
            p.drawPixmap(full, a if q < 0.5 else b, QRectF(a.rect()))
            c.setAlphaF(1 - abs(q - 0.5) * 2)
            p.fillRect(full, c)
        p.end()


def sample_pixmaps():
    """A = 파랑 + 해(원), B = 주황 + 산(삼각형). 회전·확대가 눈에 보이도록 단순한 모양."""
    def mk(bg, draw):
        pm = QPixmap(W * 2, H * 2)
        pm.fill(QColor(bg))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(2, 2)
        draw(p)
        p.end()
        return pm

    def da(p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f2e3a0"))
        p.drawEllipse(QRectF(W * 0.62, H * 0.18, H * 0.34, H * 0.34))
        p.setBrush(QColor("#2b4f7a"))
        p.drawRect(QRectF(0, H * 0.72, W, H * 0.28))

    def db(p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#7a3f12"))
        p.drawPolygon(QPolygonF([QPointF(W * 0.15, H), QPointF(W * 0.45, H * 0.25), QPointF(W * 0.8, H)]))
        p.setBrush(QColor("#fff3e0"))
        p.drawEllipse(QRectF(W * 0.12, H * 0.14, H * 0.2, H * 0.2))
    return mk(A, da), mk(B, db)


class TransitionDialog(QDialog):
    """선택한 컷 앞 경계의 전환을 고름. 샘플 클릭 = 바로 적용하고 닫힘."""
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
        pa, pb = sample_pixmaps()
        for i, (kind, name) in enumerate(TRANSITIONS):
            t = TransTile(kind, name, pa, pb)
            t.checked = kind == cur
            t.setEnabled(kind == "none" or not first or kind in FIRST_OK)
            t.clicked.connect(self._pick)
            grid.addWidget(t, i // 4, i % 4)
            self.buttons[kind] = t
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
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        t = time.monotonic() - self._t0
        for b in self.buttons.values():
            b.tick(t)

    def _pick(self, kind):
        self.chosen.emit(kind, self.dur.value() / 10)
        self.accept()
