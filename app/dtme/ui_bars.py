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
    """현재 클립의 전체 길이. 인/아웃 구간을 배속 색으로, 배속 글자, E/C 표시.
    구간 양 끝을 드래그하면 인/아웃 이동, 그 밖은 클릭·드래그로 재생 위치 이동."""
    seekRequested = Signal(int)
    ioDragStarted = Signal()
    ioDragged = Signal(str, int)      # "in" | "out", frame
    ioDragFinished = Signal()
    keyDeleteRequested = Signal(int)   # 세로 크롭 키프레임 우클릭

    GRAB = 7   # 끝 잡는 범위(px)

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
        self.keys: list[int] = []      # 세로 크롭 키프레임(세로 출력일 때만 표시)
        self._drag = False
        self._edge = ""
        self.setMouseTracking(True)

    def set_data(self, frames, io, trimmed, speed, tag, stills, samples):
        self.frames, self.io, self.trimmed, self.speed, self.tag = frames, io, trimmed, speed, tag
        self.stills, self.samples = stills, samples
        self.update()

    def set_playhead(self, f):
        self.playhead = f
        self.update()

    def set_keys(self, keys):
        self.keys = keys
        self.update()

    def _key_at(self, x):
        for f in self.keys:
            if abs(self._x(f) - x) <= 6:
                return f
        return None

    def _x(self, f):
        return f / max(1, self.frames) * self.width()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        p.fillRect(self.rect(), QColor("#202020"))
        if not self.frames:
            return
        a, b = self.io
        r = QRectF(self._x(a), 0, max(2.0, self._x(b) - self._x(a)), h)
        c = QColor(SPEED_COLOR.get(self.speed, QColor("#777")))
        if not self.trimmed:
            c.setAlpha(150)
        p.fillRect(r, c)
        p.setPen(QPen(QColor("#f2f2f2") if self.trimmed else QColor(240, 240, 240, 110), 3))
        p.drawLine(QPointF(r.left() + 1.5, 0), QPointF(r.left() + 1.5, h))
        p.drawLine(QPointF(r.right() - 1.5, 0), QPointF(r.right() - 1.5, h))
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
        for fr in self.keys:          # ◇ 세로 크롭 키프레임
            x = self._x(fr)
            p.setPen(QPen(QColor("#111"), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(QPolygonF([QPointF(x, 1), QPointF(x + 5, 6), QPointF(x, 11), QPointF(x - 5, 6)]))
        x = self._x(self.playhead)
        p.setPen(QPen(QColor("#e5484d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    def _frame_at(self, x):
        return int(max(0, min(self.frames, round(x / max(1, self.width()) * self.frames))))

    def _seek(self, x):
        if self.frames:
            self.seekRequested.emit(min(self.frames - 1, self._frame_at(x)))

    def _edge_at(self, x):
        if not self.frames:
            return ""
        a, b = self.io
        da, db = abs(x - self._x(a)), abs(x - self._x(b))
        if min(da, db) > self.GRAB:
            return ""
        return "in" if da < db or (da == db and x < self._x(a)) else "out"

    def mousePressEvent(self, e):
        x = e.position().x()
        k = self._key_at(x) if e.position().y() <= 14 else None
        if e.button() == Qt.RightButton:
            if k is not None:
                self.keyDeleteRequested.emit(k)
            return
        if k is not None:            # ◇ 클릭 = 그 키프레임 위치로
            self._drag, self._edge = False, ""
            self.seekRequested.emit(k)
            return
        self._edge = self._edge_at(x)
        self._drag = True
        if self._edge:
            self.ioDragStarted.emit()
            self.ioDragged.emit(self._edge, self._frame_at(x))
        else:
            self._seek(x)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag:
            if self._edge:
                self.ioDragged.emit(self._edge, self._frame_at(x))
            else:
                self._seek(x)
        else:
            self.setCursor(Qt.SizeHorCursor if self._edge_at(x) else Qt.ArrowCursor)

    def mouseReleaseEvent(self, _):
        if self._edge:
            self.ioDragFinished.emit()
        self._drag = False
        self._edge = ""


class LayerBar(QWidget):
    """소스 바 위 얇은 스틸 바(이미지 레이어마다 한 줄, 아래 줄 = 먼저 그려지는 레이어).
    끝 드래그 = 레이어 인/아웃, 가운데 드래그 = 통째 이동, 클릭 = 선택, 우클릭 = 레이어 삭제. 소스 바와 같은 가로 비율.
    dragged(id, "in"|"out"|"move", frame) — move 의 frame = 새 시작 프레임."""
    selected = Signal(str)
    dragStarted = Signal(str)
    dragged = Signal(str, str, int)       # layer id, "in" | "out", frame
    dragFinished = Signal()
    removeRequested = Signal(str)

    ROW = 7      # 줄 높이(간격 1 포함)
    GRAB = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = 0
        self.rows = []          # [(id, fin, fout, tip)]
        self.sel = ""
        self.playhead = 0
        self._edge = None       # (id, which)
        self._grab_off = 0
        self.setMouseTracking(True)
        self.setFixedHeight(0)

    def set_data(self, frames, rows, sel):
        self.frames, self.rows, self.sel = frames, rows, sel
        self.setFixedHeight(len(rows) * self.ROW + (1 if rows else 0))
        self.update()

    def set_playhead(self, f):
        self.playhead = f
        if self.rows:
            self.update()

    def _x(self, f):
        return f / max(1, self.frames) * self.width()

    def _frame_at(self, x):
        return int(max(0, min(self.frames, round(x / max(1, self.width()) * self.frames))))

    def _row_rect(self, i):
        y = self.height() - 1 - (i + 1) * self.ROW
        lid, a, b, _t = self.rows[i]
        return QRectF(self._x(a), y + 1, max(3.0, self._x(b) - self._x(a)), self.ROW - 1)

    def paintEvent(self, _):
        if not self.rows:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#202020"))
        for i, (lid, _a, _b, _t) in enumerate(self.rows):
            r = self._row_rect(i)
            p.fillRect(r, QColor("#e6e6e6") if lid == self.sel else QColor("#8f8f8f"))
            p.fillRect(QRectF(r.left(), r.top(), 2, r.height()), QColor("#ffffff"))
            p.fillRect(QRectF(r.right() - 2, r.top(), 2, r.height()), QColor("#ffffff"))
        x = self._x(self.playhead)
        p.setPen(QPen(QColor("#e5484d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))

    def _hit(self, pos):
        """(행 번호, 'in'|'out'|'' ) 또는 (-1, '')"""
        for i in range(len(self.rows)):
            r = self._row_rect(i)
            if r.top() - 1 <= pos.y() <= r.bottom() + 1:
                x = pos.x()
                da, db = abs(x - r.left()), abs(x - r.right())
                if min(da, db) <= self.GRAB:
                    return i, ("in" if da <= db else "out")
                if r.left() <= x <= r.right():
                    return i, ""
                return -1, ""
        return -1, ""

    def mousePressEvent(self, e):
        i, edge = self._hit(e.position())
        if i < 0:
            return
        lid = self.rows[i][0]
        if e.button() == Qt.RightButton:
            self.removeRequested.emit(lid)
            return
        self.selected.emit(lid)
        self._edge = (lid, edge or "move")
        self._grab_off = self._frame_at(e.position().x()) - self.rows[i][1]
        self.dragStarted.emit(lid)

    def mouseMoveEvent(self, e):
        if self._edge and (e.buttons() & Qt.LeftButton):
            f = self._frame_at(e.position().x())
            if self._edge[1] == "move":
                f -= self._grab_off
            self.dragged.emit(self._edge[0], self._edge[1], f)
            return
        i, edge = self._hit(e.position())
        self.setCursor(Qt.SizeHorCursor if edge else Qt.OpenHandCursor if i >= 0 else Qt.ArrowCursor)
        self.setToolTip(self.rows[i][3] if i >= 0 else "")

    def mouseReleaseEvent(self, _):
        if self._edge:
            self.dragFinished.emit()
        self._edge = None


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

    def fit(self):
        self._resize()
        self.update()

    def set_zoom(self, pps):
        self.pps = pps
        self._resize()
        self.update()

    def total(self):
        return sum(it[1] for it in self.items)

    def _resize(self):
        w = int(self.total() * self.pps + 80)
        h = self.height()
        parent = self.parentWidget()
        if parent is not None:          # 스크롤 영역(뷰포트)을 항상 가득 채움
            w = max(w, parent.width())
            h = max(self.minimumHeight(), parent.height())
        self.setMinimumWidth(w)
        self.resize(w, h)

    def _rects(self):
        out, x = [], 4.0
        h = self.height() - self.RULER - 6
        for it in self.items:
            wd = max(6.0, it[1] * self.pps)
            out.append(QRectF(x, 4, wd - 2, h))
            x += wd
        return out

    def tooltip_at(self, x):
        i = self._index_at(x)
        if i >= 0 and len(self.items[i]) > 5 and self.items[i][5]:
            n, d = self.items[i][5]
            return f"{n} {d:.1f}초"
        return ""

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
        f = QFont(self.font())
        for i, (it, r) in enumerate(zip(self.items, rects)):
            sid, sec, label, sp, tag = it[:5]
            trans = it[5] if len(it) > 5 else None
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
            if trans:          # 앞 경계 화면 전환: 경계에 걸친 나비 모양(폭 = 전환 길이)
                tw = max(8.0, min(rr.width(), trans[1] * self.pps))
                x0, y0, y1 = rr.left() - 1, rr.top() + rr.height() * 0.62, rr.bottom() - 2
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(245, 245, 245, 210))
                p.drawPolygon(QPolygonF([QPointF(x0 - tw / 2, y0), QPointF(x0 + tw / 2, y1),
                                         QPointF(x0 + tw / 2, y0), QPointF(x0 - tw / 2, y1)]))
        # 놓일 위치 표시
        if self._press is not None and self._drag_x is not None:
            j = self._drop_index(self._drag_x)
            xs = [r.left() for r in rects] + [rects[-1].right() + 2 if rects else 4]
            x = xs[min(j, len(xs) - 1)] - 1
            p.setPen(QPen(QColor("#f2c94c"), 3))
            p.drawLine(QPointF(x, 2), QPointF(x, h - self.RULER - 2))
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
        if not e.buttons():
            self.setToolTip(self.tooltip_at(e.position().x()))
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
