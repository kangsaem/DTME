"""마스터 커브 편집기. 양 끝점은 세로로만 이동, 중간 포인트 최대 5개.
곡선 모양은 FFmpeg curves 필터와 같은 자연 3차 스플라인으로 그린다."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .project import MAX_CURVE_POINTS


def natural_spline(pts, n=128):
    """FFmpeg curves(기본 natural) 와 같은 방식."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    k = len(pts)
    if k < 2:
        return [(i / (n - 1), i / (n - 1)) for i in range(n)]
    if k == 2:
        return [(xs[0] + (xs[1] - xs[0]) * t / (n - 1), ys[0] + (ys[1] - ys[0]) * t / (n - 1)) for t in range(n)]
    h = [xs[i + 1] - xs[i] for i in range(k - 1)]
    # 삼중대각 시스템 (자연 경계: 양 끝 2차 미분 0)
    a = [0.0] * k
    b = [1.0] * k
    c = [0.0] * k
    d = [0.0] * k
    for i in range(1, k - 1):
        a[i] = h[i - 1]
        b[i] = 2 * (h[i - 1] + h[i])
        c[i] = h[i]
        d[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
    for i in range(1, k):
        m = a[i] / b[i - 1]
        b[i] -= m * c[i - 1]
        d[i] -= m * d[i - 1]
    M = [0.0] * k
    M[-1] = d[-1] / b[-1]
    for i in range(k - 2, -1, -1):
        M[i] = (d[i] - c[i] * M[i + 1]) / b[i]
    out = []
    for t in range(n):
        x = xs[0] + (xs[-1] - xs[0]) * t / (n - 1)
        i = min(k - 2, max(0, next((j for j in range(k - 1) if x <= xs[j + 1]), k - 2)))
        dx = x - xs[i]
        hi = h[i]
        A = (M[i + 1] - M[i]) / (6 * hi)
        B = M[i] / 2
        C = (ys[i + 1] - ys[i]) / hi - hi * (2 * M[i] + M[i + 1]) / 6
        y = ys[i] + C * dx + B * dx * dx + A * dx * dx * dx
        out.append((x, max(0.0, min(1.0, y))))
    return out


class CurveEditor(QWidget):
    changed = Signal(list)       # 드래그 종료/추가/삭제 시
    editing = Signal(list)       # 드래그 중

    R = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 56)
        self.setMaximumHeight(260)
        self.pts = [[0.0, 0.0], [1.0, 1.0]]
        self._drag = -1
        self.setToolTip("클릭: 포인트 추가(최대 5개) · 드래그: 이동 · 더블클릭/우클릭: 삭제 · 양 끝점은 위아래만")

    def set_points(self, pts):
        self.pts = sorted([list(map(float, p)) for p in pts]) or [[0.0, 0.0], [1.0, 1.0]]
        if self.pts[0][0] != 0.0:
            self.pts.insert(0, [0.0, 0.0])
        if self.pts[-1][0] != 1.0:
            self.pts.append([1.0, 1.0])
        self.update()

    def reset(self):
        self.set_points([[0, 0], [1, 1]])
        self.changed.emit(self.points())

    def points(self):
        return [[round(x, 4), round(y, 4)] for x, y in self.pts]

    # ------------------------------------------------------------ 좌표
    def _area(self):
        # 폭 전체 사용(높이가 낮은 노트북 화면에서도 조작하기 쉽게)
        h = self.height() - 2 * self.R - 2
        w = self.width() - 2 * self.R - 2
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_px(self, x, y):
        a = self._area()
        return QPointF(a.left() + x * a.width(), a.bottom() - y * a.height())

    def _to_val(self, pos):
        a = self._area()
        return (max(0.0, min(1.0, (pos.x() - a.left()) / a.width())),
                max(0.0, min(1.0, (a.bottom() - pos.y()) / a.height())))

    def _hit(self, pos):
        for i, (x, y) in enumerate(self.pts):
            q = self._to_px(x, y)
            if (q - pos).manhattanLength() <= self.R * 2:
                return i
        return -1

    # ------------------------------------------------------------ 그리기
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        a = self._area()
        p.fillRect(a, QColor("#1e1e1e"))
        p.setPen(QPen(QColor("#333"), 1))
        for i in range(1, 4):
            x = a.left() + a.width() * i / 4
            y = a.top() + a.height() * i / 4
            p.drawLine(QPointF(x, a.top()), QPointF(x, a.bottom()))
            p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
        p.setPen(QPen(QColor("#444"), 1, Qt.DashLine))
        p.drawLine(a.bottomLeft(), a.topRight())
        path = QPainterPath()
        for i, (x, y) in enumerate(natural_spline(self.pts)):
            q = self._to_px(x, y)
            path.moveTo(q) if i == 0 else path.lineTo(q)
        p.setPen(QPen(QColor("#eaeaea"), 2))
        p.drawPath(path)
        for i, (x, y) in enumerate(self.pts):
            q = self._to_px(x, y)
            p.setPen(QPen(QColor("#eaeaea"), 1.5))
            p.setBrush(QColor("#e5484d") if i == self._drag else QColor("#1e1e1e"))
            p.drawEllipse(q, self.R - 1, self.R - 1)
        p.setPen(QColor("#888"))
        p.drawText(a.adjusted(4, 2, -4, -2), Qt.AlignTop | Qt.AlignLeft,
                   f"포인트 {len(self.pts) - 2}/{MAX_CURVE_POINTS}")

    # ------------------------------------------------------------ 마우스
    def mousePressEvent(self, e):
        pos = e.position()
        i = self._hit(pos)
        if e.button() == Qt.RightButton:
            self._remove(i)
            return
        if i < 0:
            if len(self.pts) - 2 >= MAX_CURVE_POINTS:
                return
            x, y = self._to_val(pos)
            if x <= 0.01 or x >= 0.99:
                return
            self.pts.append([x, y])
            self.pts.sort()
            i = next(j for j, p in enumerate(self.pts) if p == [x, y])
            self.changed.emit(self.points())
        self._drag = i
        self.update()

    def mouseMoveEvent(self, e):
        i = self._drag
        if i < 0:
            return
        x, y = self._to_val(e.position())
        if i == 0:
            x = 0.0
        elif i == len(self.pts) - 1:
            x = 1.0
        else:
            x = max(self.pts[i - 1][0] + 0.02, min(self.pts[i + 1][0] - 0.02, x))
        self.pts[i] = [x, y]
        self.update()
        self.editing.emit(self.points())

    def mouseReleaseEvent(self, _):
        if self._drag >= 0:
            self._drag = -1
            self.update()
            self.changed.emit(self.points())

    def mouseDoubleClickEvent(self, e):
        self._remove(self._hit(e.position()))

    def _remove(self, i):
        if 0 < i < len(self.pts) - 1:
            del self.pts[i]
            self._drag = -1
            self.update()
            self.changed.emit(self.points())
