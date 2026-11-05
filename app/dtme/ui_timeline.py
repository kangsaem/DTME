"""소스 1개의 타임라인: 구간 블록(배속별 색), 스틸 ◆, 샘플 ●, 재생 위치."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

SPEED_COLOR = {2.0: QColor("#d9822b"), 1.0: QColor("#5b7fa6"), 0.5: QColor("#3d9a8b")}
SPEED_TEXT = {2.0: "2x", 1.0: "1x", 0.5: "½x"}


class Timeline(QWidget):
    seekRequested = Signal(int)
    segmentClicked = Signal(str)   # 세그먼트 id ("" = 선택 해제)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.setMouseTracking(True)
        self.frames = 1
        self.playhead = 0
        self.pending_in: int | None = None
        self.segments = []       # Segment 목록
        self.stills = []         # frame 목록
        self.samples = []
        self.selected = ""
        self.v0, self.v1 = 0, 1  # 보이는 범위(확대)
        self._drag = False

    def set_data(self, frames, segments, stills, samples, selected, pending_in):
        if frames != self.frames:
            self.frames = max(1, frames)
            self.v0, self.v1 = 0, self.frames
        self.segments, self.stills, self.samples = segments, stills, samples
        self.selected, self.pending_in = selected, pending_in
        self.update()

    def set_playhead(self, f):
        self.playhead = f
        # 확대 상태에서 재생 위치가 화면 밖이면 따라감
        span = self.v1 - self.v0
        if span < self.frames and not (self.v0 <= f <= self.v1):
            self.v0 = max(0, min(self.frames - span, f - span // 2))
            self.v1 = self.v0 + span
        self.update()

    # ------------------------------------------------------------ 좌표
    def _x(self, f):
        return (f - self.v0) / max(1, self.v1 - self.v0) * self.width()

    def _f(self, x):
        return int(self.v0 + x / max(1, self.width()) * (self.v1 - self.v0))

    # ------------------------------------------------------------ 그리기
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#1b1b1b"))
        bar = QRectF(0, 18, w, h - 36)
        p.fillRect(bar, QColor("#2a2a2a"))
        p.setFont(QFont(self.font().family(), 8))

        for seg in self.segments:
            x0, x1 = self._x(seg.fin), self._x(seg.fout)
            r = QRectF(x0, bar.top(), max(2.0, x1 - x0), bar.height())
            c = QColor(SPEED_COLOR.get(seg.speed, QColor("#888")))
            p.fillRect(r, c)
            if seg.id == self.selected:
                p.setPen(QPen(QColor("white"), 2))
                p.drawRect(r.adjusted(1, 1, -1, -1))
            if r.width() > 22:
                p.setPen(QColor("white"))
                p.drawText(r, Qt.AlignCenter, SPEED_TEXT.get(seg.speed, ""))

        if self.pending_in is not None:
            x = self._x(self.pending_in)
            p.setPen(QPen(QColor("#e0c341"), 2, Qt.DashLine))
            p.drawLine(QPointF(x, bar.top()), QPointF(x, bar.bottom()))
            p.drawText(QPointF(x + 3, bar.top() + 11), "IN")

        p.setPen(Qt.NoPen)
        for f in self.samples:          # 샘플 ● (아래)
            x = self._x(f)
            p.setBrush(QColor("#f0f0f0"))
            p.drawEllipse(QPointF(x, h - 9), 4.5, 4.5)
        for f in self.stills:           # 스틸 ◆ (위)
            x = self._x(f)
            p.setBrush(QColor("#f2c94c"))
            p.drawPolygon(QPolygonF([QPointF(x, 3), QPointF(x + 6, 9), QPointF(x, 15), QPointF(x - 6, 9)]))

        x = self._x(self.playhead)
        p.setPen(QPen(QColor("#e5484d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    # ------------------------------------------------------------ 마우스
    def mousePressEvent(self, e):
        f = self._f(e.position().x())
        y = e.position().y()
        if 18 <= y <= self.height() - 18:
            hit = next((s for s in self.segments if s.fin <= f < s.fout), None)
            if hit is not None and e.modifiers() & Qt.ControlModifier:
                self.segmentClicked.emit(hit.id)
                return
            self.segmentClicked.emit(hit.id if hit else "")
        self._drag = True
        self.seekRequested.emit(max(0, min(self.frames - 1, f)))

    def mouseMoveEvent(self, e):
        if self._drag:
            self.seekRequested.emit(max(0, min(self.frames - 1, self._f(e.position().x()))))

    def mouseReleaseEvent(self, _):
        self._drag = False

    def wheelEvent(self, e):
        """휠 = 확대/축소 (마우스 위치 기준)"""
        f = self._f(e.position().x())
        span = self.v1 - self.v0
        k = 0.8 if e.angleDelta().y() > 0 else 1.25
        new = int(max(120, min(self.frames, span * k)))
        ratio = (f - self.v0) / max(1, span)
        self.v0 = int(max(0, min(self.frames - new, f - ratio * new)))
        self.v1 = self.v0 + new
        self.update()
