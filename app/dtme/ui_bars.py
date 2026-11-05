"""소스 바(모니터 바로 아래, 현재 클립 전체 길이) + 타임라인(컷 이어붙이기)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

SPEED_COLOR = {2.0: QColor("#d9822b"), 1.0: QColor("#5b7fa6"), 0.5: QColor("#3d9a8b")}
TAG_COLOR = {"E": QColor("#8c939b"), "C": QColor("#f2c94c")}


def speed_text(sp):
    return {2.0: "x2", 1.0: "x1", 0.5: "x1/2"}.get(sp, f"x{sp:g}")


def draw_tag(p: QPainter, r: QRectF, tag: str, size=16):
    """블록 왼쪽 위 모서리 삼각형 + E(기본값)/C(클립 보정)."""
    if not tag or r.width() < 8:
        return
    s = min(size, r.width(), r.height())
    tri = QPolygonF([r.topLeft(), QPointF(r.left() + s, r.top()), QPointF(r.left(), r.top() + s)])
    p.setPen(Qt.NoPen)
    p.setBrush(TAG_COLOR.get(tag, QColor("#888")))
    p.drawPolygon(tri)
    p.setPen(QColor("#111"))
    f = QFont(p.font())
    f.setPointSizeF(max(6.0, s * 0.42))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(r.left() + 1, r.top(), s * 0.6, s * 0.6), Qt.AlignCenter, tag)


class SourceBar(QWidget):
    """현재 클립의 전체 길이. 인/아웃 구간을 배속 색으로, 배속 글자, E/C 표시."""
    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.frames = 0
        self.io = (0, 0)
        self.trimmed = False
        self.speed = 1.0
        self.tag = "E"
        self.playhead = 0
        self.stills: list[int] = []
        self.samples: list[int] = []
        self._drag = False
        self.setToolTip("현재 클립 전체 길이 · 클릭·드래그로 이동 · 색 구간 = 인/아웃 · E 기본값 / C 클립 보정")

    def set_data(self, frames, io, trimmed, speed, tag, stills, samples):
        self.frames, self.io, self.trimmed, self.speed, self.tag = frames, io, trimmed, speed, tag
        self.stills, self.samples = stills, samples
        self.update()

    def set_playhead(self, f):
        self.playhead = f
        self.update()

    def _x(self, f):
        return f / max(1, self.frames) * self.width()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#202020"))
        if not self.frames:
            return
        a, b = self.io
        r = QRectF(self._x(a), 0, max(2.0, self._x(b) - self._x(a)), h)
        c = QColor(SPEED_COLOR.get(self.speed, QColor("#777")))
        if not self.trimmed:
            c.setAlpha(150)
        p.fillRect(r, c)
        if self.trimmed:
            p.setPen(QPen(QColor("#f2f2f2"), 2))
            p.drawLine(QPointF(r.left() + 1, 0), QPointF(r.left() + 1, h))
            p.drawLine(QPointF(r.right() - 1, 0), QPointF(r.right() - 1, h))
        p.setPen(QColor("white"))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        if r.width() > 30:
            p.drawText(r, Qt.AlignCenter, speed_text(self.speed))
        draw_tag(p, r, self.tag)
        p.setPen(Qt.NoPen)
        for fr in self.stills:
            x = self._x(fr)
            p.setBrush(QColor("#f2c94c"))
            p.drawPolygon(QPolygonF([QPointF(x, h - 9), QPointF(x + 4, h - 5), QPointF(x, h - 1), QPointF(x - 4, h - 5)]))
        for fr in self.samples:
            p.setBrush(QColor("#e8e8e8"))
            p.drawEllipse(QPointF(self._x(fr), h - 4), 2.5, 2.5)
        x = self._x(self.playhead)
        p.setPen(QPen(QColor("#e5484d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    def _seek(self, x):
        if self.frames:
            self.seekRequested.emit(int(max(0, min(self.frames - 1, x / max(1, self.width()) * self.frames))))

    def mousePressEvent(self, e):
        self._drag = True
        self._seek(e.position().x())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._seek(e.position().x())

    def mouseReleaseEvent(self, _):
        self._drag = False


class SeqTimeline(QWidget):
    """컷들을 결과 길이(배속 반영) 비율로 이어 그림. 클릭=선택, 드래그=순서 변경, 아래 눈금=결과 시간."""
    selected = Signal(str)
    moved = Signal(int, int)      # from, to
    activated = Signal(str)       # 더블클릭

    RULER = 20
    LIMIT_SEC = 30.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(86)
        self.pps = 30.0           # 1초당 픽셀(확대 슬라이더)
        self.items = []           # [(id, seconds, label, speed, tag)]
        self.sel = ""
        self._press = None        # (index, x)
        self._drag_x = None
        self.setMouseTracking(True)

    def set_items(self, items, sel):
        self.items, self.sel = items, sel
        self._resize()
        self.update()

    def set_zoom(self, pps):
        self.pps = pps
        self._resize()
        self.update()

    def total(self):
        return sum(it[1] for it in self.items)

    def _resize(self):
        w = int(max(self.LIMIT_SEC, self.total()) * self.pps + 60)
        parent = self.parentWidget()
        if parent is not None:
            w = max(w, parent.width())
        self.setMinimumWidth(w)
        self.resize(w, self.height())

    def _rects(self):
        out, x = [], 4.0
        h = self.height() - self.RULER - 6
        for it in self.items:
            wd = max(6.0, it[1] * self.pps)
            out.append(QRectF(x, 4, wd - 2, h))
            x += wd
        return out

    def _index_at(self, x):
        for i, r in enumerate(self._rects()):
            if r.left() <= x <= r.right() + 2:
                return i
        return -1

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#1b1b1b"))
        rects = self._rects()
        if not self.items:
            p.setPen(QColor("#777"))
            p.drawText(QRectF(0, 0, w, h - self.RULER), Qt.AlignCenter,
                       "타임라인이 비어 있습니다 — 소스에서 인/아웃을 잡고 ▼ (↓ 키)로 내려 보내세요")
        f = QFont(self.font())
        for i, (it, r) in enumerate(zip(self.items, rects)):
            sid, sec, label, sp, tag = it
            dragging = self._press is not None and self._drag_x is not None and self._press[0] == i
            rr = QRectF(r)
            if dragging:
                rr.moveLeft(self._drag_x - self._press[1] + r.left())
            c = QColor(SPEED_COLOR.get(sp, QColor("#777")))
            if dragging:
                c.setAlpha(170)
            p.fillRect(rr, c)
            if sid == self.sel:
                p.setPen(QPen(QColor("white"), 2))
                p.drawRect(rr.adjusted(1, 1, -1, -1))
            if rr.width() > 40:
                p.setPen(QColor("white"))
                f.setBold(True)
                p.setFont(f)
                p.drawText(rr.adjusted(4, 2, -4, -2), Qt.AlignHCenter | Qt.AlignVCenter,
                           f"{speed_text(sp)}\n{label}" if rr.width() > 90 else speed_text(sp))
            draw_tag(p, rr, tag)
        # 놓일 위치 표시
        if self._press is not None and self._drag_x is not None:
            j = self._drop_index(self._drag_x)
            xs = [r.left() for r in rects] + [rects[-1].right() + 2 if rects else 4]
            x = xs[min(j, len(xs) - 1)] - 1
            p.setPen(QPen(QColor("#f2c94c"), 3))
            p.drawLine(QPointF(x, 2), QPointF(x, h - self.RULER - 2))
        # 30초 한도 선
        lx = 4 + self.LIMIT_SEC * self.pps
        p.setPen(QPen(QColor("#e5484d"), 1, Qt.DashLine))
        p.drawLine(QPointF(lx, 0), QPointF(lx, h - self.RULER))
        # 눈금
        y0 = h - self.RULER
        p.fillRect(QRectF(0, y0, w, self.RULER), QColor("#151515"))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120) if s * self.pps >= 60)
        minor = step / 5
        f.setBold(False)
        f.setPointSizeF(8)
        p.setFont(f)
        t = 0.0
        end = (w - 4) / self.pps
        while t <= end:
            x = 4 + t * self.pps
            major = abs((t / step) - round(t / step)) < 1e-6
            p.setPen(QColor("#888") if major else QColor("#444"))
            p.drawLine(QPointF(x, y0), QPointF(x, y0 + (8 if major else 4)))
            if major:
                p.drawText(QPointF(x + 2, h - 3), f"{int(t // 60)}:{t % 60:04.1f}" if t >= 60 else f"{t:g}s")
            t = round(t + minor, 6)

    def _drop_index(self, x):
        rects = self._rects()
        for i, r in enumerate(rects):
            if x < r.center().x():
                return i
        return len(rects)

    def mousePressEvent(self, e):
        i = self._index_at(e.position().x())
        if i >= 0:
            self._press = (i, e.position().x())
            self._drag_x = None
            self.selected.emit(self.items[i][0])
        else:
            self._press = None
            self.selected.emit("")

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.buttons() & Qt.LeftButton):
            if self._drag_x is not None or abs(e.position().x() - self._press[1]) > 6:
                self._drag_x = e.position().x()
                self.update()

    def mouseReleaseEvent(self, e):
        if self._press is not None and self._drag_x is not None:
            src = self._press[0]
            dst = self._drop_index(self._drag_x)
            if dst > src:
                dst -= 1
            if dst != src:
                self.moved.emit(src, dst)
        self._press = None
        self._drag_x = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        i = self._index_at(e.position().x())
        if i >= 0:
            self.activated.emit(self.items[i][0])
