"""화면 전환 고르기(컷편집): 움직이는 샘플 격자 + 길이. 글자 없이 그림만, 이름은 툴팁."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSlider, QWidget

from . import ff
from .project import FIRST_OK, TRANS_DEFAULT_SEC, TRANS_RANGE, TRANSITIONS
from .ui_render import Popup

W, H = 120, 68
ROT_SUBS = 8           # 샘플 그림 모션블러 장수(렌더는 ff.ROT_BLUR)
ROT_ND = 15            # 샘플 기준 전환 프레임 수(0.5초)
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

    def _rot_frame(self, v):
        """회전 줌 한 장: 앞 컷 각도 θ, 뒤 컷 θ∓180°, 가운데 ROT_MIX 만 섞음."""
        from PySide6.QtGui import QImage
        v = max(0.0, min(1.0, v))
        deg, s = ff.rot_state(self.kind, v)
        back = deg - 180 if self.kind == "rotzoomin" else deg + 180
        deg, back = -deg, -back          # 렌더(perspective)와 같은 화면 방향(QPainter 는 + = 시계 방향)
        lo = (1 - ff.ROT_MIX) / 2
        mix = max(0.0, min(1.0, (v - lo) / ff.ROT_MIX))
        im = QImage(W, H, QImage.Format_RGB32)
        im.fill(QColor("black"))
        p = QPainter(im)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if mix < 1:
            self._draw_zoom(p, self.a, s, deg)
        if mix > 0:
            self._draw_zoom(p, self.b, s, back, mix)
        p.end()
        return im

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
        elif k in ("rotzoomin", "rotzoomout"):      # 180° 회전 + 모션블러(렌더와 같은 계산, 서브프레임 겹치기)
            base = p.opacity()
            for j in range(ROT_SUBS):
                v = q + (j / (ROT_SUBS - 1) - 0.5) * ff.ROT_SHUTTER / ROT_ND
                p.setOpacity(base / (j + 1))
                p.drawImage(full, self._rot_frame(v))
        elif k == "zoomin":                          # 앞 컷이 확대되며 뒤 컷으로
            u = q * q
            self._draw_zoom(p, a, 1 + 2 * u, 0)
            p.setOpacity(q * p.opacity())
            p.drawPixmap(full, b, QRectF(b.rect()))
        elif k == "zoomout":                         # 뒤 컷이 확대 상태에서 원래로
            u = (1 - q) ** 2
            p.drawPixmap(full, a, QRectF(a.rect()))
            self._draw_zoom(p, b, 1 + 2 * u, 0, q)
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


class TransitionDialog(Popup):
    """선택한 컷 앞 경계의 전환을 고름. 샘플 클릭 = 바로 적용하고 닫힘. 제목줄 없는 창 + [취소]만(v0.16.19)."""
    chosen = Signal(str, float)

    def __init__(self, current: dict, first: bool, parent=None, frames=None):
        super().__init__(parent)
        cur = (current or {}).get("type", "none") or "none"
        dur = float((current or {}).get("dur", TRANS_DEFAULT_SEC))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.buttons = {}
        pa, pb = frames if frames and frames[0] is not None and frames[1] is not None else sample_pixmaps()
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
        lay = self.body
        lay.addLayout(grid)
        lay.addLayout(row)
        self.add_buttons(ok=None)
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


class TransPreview(QWidget):
    """모니터 위에 덮는 화면 전환 미리보기(작은 렌더 결과 반복 재생, 소리 없음). 클릭·Esc·다른 조작 = 닫힘."""
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.frames = []
        self.i = 0
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setCursor(Qt.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(int(round(1000 / 29.97)))
        self._timer.timeout.connect(self._tick)
        self.hide()

    def play(self, frames):
        self.frames, self.i = frames, 0
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self):
        if not self.isVisible():
            return
        self._timer.stop()
        self.frames = []
        self.hide()
        self.closed.emit()

    def _tick(self):
        if not self.frames:
            return
        self.i = (self.i + 1) % (len(self.frames) + 15)      # 끝에서 0.5초 멈췄다가 다시
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        if self.frames:
            im = self.frames[min(self.i, len(self.frames) - 1)]
            r = QRectF(self.rect())
            sc = min(r.width() / im.width(), r.height() / im.height())
            w, h = im.width() * sc, im.height() * sc
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), im)
            p.fillRect(QRectF(0, r.height() - 3, r.width() * min(self.i, len(self.frames)) / len(self.frames), 3),
                       QColor("#4a8fe0"))
        p.end()

    def mousePressEvent(self, _):
        self.stop()


def decode_frames(path: str):
    """미리보기 mp4 → QImage 목록(rgb24)."""
    from PySide6.QtGui import QImage
    info = ff.probe(path)
    w, h = info["width"], info["height"]
    raw = ff.run([ff.paths.ffmpeg(), "-v", "error", "-i", ff._abs(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    n = len(raw) // (w * h * 3)
    return [QImage(raw[k * w * h * 3:(k + 1) * w * h * 3], w, h, w * 3, QImage.Format_RGB888).copy() for k in range(n)]
