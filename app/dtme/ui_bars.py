"""소스 바(모니터 바로 아래, 현재 클립 전체 길이) + 타임라인(컷 이어붙이기)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

SPEED_COLOR = {2.0: QColor("#d9822b"), 1.0: QColor("#5b7fa6"), 0.5: QColor("#3d9a8b")}
WING_DUR = QColor(242, 201, 76, 225)      # v0.16.67 나비 위 = 전환 길이(노랑)
WING_CUT = QColor(124, 200, 240, 225)     # 나비 아래 = 컷 아웃·인(하늘색)
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
    gkeyDeleteRequested = Signal(int)  # 색 키프레임 우클릭(그 프레임의 색 키 모두)
    gkeyClicked = Signal(int)          # v0.16.35 ◆ 클릭(그 프레임 종류 → 보정 줄 활성)
    activeCleared = Signal()           # v0.16.35 칩 X = 전체 ◆ 보기

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
        self.gkeys: list[int] = []     # 색 키프레임 프레임(종류 합침)
        self.gtypes: dict = {}         # v0.16.35 {종류: [프레임]} — 종류별 색
        self.active: list = []         # 활성 종류(진하게, 나머지 흐리게). [] = 전체
        self.stars: list[int] = []     # ★ 장면 표시
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

    def set_marks(self, gkeys, stars):
        """gkeys = {종류: [프레임]}(v0.16.35) 또는 프레임 목록(예전)."""
        if isinstance(gkeys, dict):
            self.gtypes = {k: sorted(set(v)) for k, v in gkeys.items() if v}
            self.gkeys = sorted({f for v in self.gtypes.values() for f in v})
        else:
            self.gtypes, self.gkeys = {}, list(gkeys)
        self.stars = stars
        self.update()

    def set_active(self, types):
        self.active = list(types or [])
        self.update()

    def _gx(self, f):
        """◆ 그리는 x(양 끝에서 잘리지 않게, v0.16.35)."""
        return max(6.0, min(self.width() - 6.0, self._x(f)))

    def _chip_rect(self):
        if not self.active:
            return None
        from .project import GKEY_STYLE
        fm = self.fontMetrics()
        t = "·".join(GKEY_STYLE.get(k, (k, ""))[0] for k in self.active)
        w = 18 + fm.horizontalAdvance(t) + 8          # v0.16.38 X 없음(지우기로 오해) — 누르면 전체 ◆ 보기
        return QRectF(self.width() - w - 4, 4, w, self.height() - 8), t

    def _key_at(self, x):
        for f in self.keys:
            if abs(self._x(f) - x) <= 6:
                return f
        return None

    def _gkey_at(self, x):
        best = None
        for f in self.gkeys:
            d = abs(self._gx(f) - x)
            if d <= 6 and (best is None or d < best[0]):
                best = (d, f)
        return best[1] if best else None

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
        self._paint_gkeys(p, h)
        f2 = QFont(self.font())
        f2.setPointSizeF(9)
        p.setFont(f2)
        for fr in self.stars:         # ★
            x = self._x(fr)
            p.setPen(QColor("#ffd84a"))
            p.drawText(QRectF(x - 7, h - 15, 14, 14), Qt.AlignCenter, "★")
        for fr in self.keys:          # ◇ 세로 크롭 키프레임
            x = self._x(fr)
            p.setPen(QPen(QColor("#111"), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(QPolygonF([QPointF(x, 1), QPointF(x + 5, 6), QPointF(x, 11), QPointF(x - 5, 6)]))
        x = self._x(self.playhead)
        p.setPen(QPen(QColor("#e5484d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        cr = self._chip_rect()
        if cr:                        # 활성 종류 칩 [◆ 빨강 X]
            from .project import GKEY_STYLE
            r, t = cr
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(30, 30, 30, 230))
            p.drawRoundedRect(r, 4, 4)
            c = QColor(GKEY_STYLE.get(self.active[0], ("", "#f2c94c"))[1])
            cy = r.center().y()
            p.setBrush(c)
            p.setPen(QPen(QColor("#111"), 1))
            p.drawPolygon(QPolygonF([QPointF(r.left() + 8, cy - 5), QPointF(r.left() + 13, cy), QPointF(r.left() + 8, cy + 5),
                                     QPointF(r.left() + 3, cy)]))
            p.setPen(QColor("#e8e8e8"))
            p.setFont(self.font())
            p.drawText(QRectF(r.left() + 18, r.top(), r.width() - 20, r.height()), Qt.AlignVCenter | Qt.AlignLeft, t)

    def _paint_gkeys(self, p, h):
        """◆ 종류별 색. 같은 프레임 여러 종류 = 위아래로 나눔(작게). 활성 있으면 그 종류만 진하게."""
        from .project import GKEY_STYLE
        order = [k for k in GKEY_STYLE if k in self.gtypes] + [k for k in self.gtypes if k not in GKEY_STYLE]
        if not order:                 # 예전 형식 = 노랑
            for fr in self.gkeys:
                x = self._gx(fr)
                p.setPen(QPen(QColor("#111"), 1))
                p.setBrush(QColor("#f2c94c"))
                p.drawPolygon(QPolygonF([QPointF(x, 1), QPointF(x + 5, 6), QPointF(x, 11), QPointF(x - 5, 6)]))
            return
        at: dict[int, list] = {}
        for k in order:
            for f in self.gtypes[k]:
                at.setdefault(f, []).append(k)
        for f, ks in at.items():
            if self.active:           # 활성 종류를 위로
                ks = [k for k in ks if k in self.active] + [k for k in ks if k not in self.active]
            ks = ks[:3]
            x = self._gx(f)
            sz = 5.0 if len(ks) <= 2 else 4.0
            for i, k in enumerate(ks):
                cy = (6.0 + i * 11.0) if len(ks) <= 2 else (5.0 + i * 9.0)
                c = QColor(GKEY_STYLE.get(k, ("", "#f2c94c"))[1])
                if self.active and k not in self.active:
                    c.setAlpha(70)
                p.setPen(QPen(QColor(17, 17, 17, c.alpha()), 1))
                p.setBrush(c)
                p.drawPolygon(QPolygonF([QPointF(x, cy - sz), QPointF(x + sz, cy), QPointF(x, cy + sz), QPointF(x - sz, cy)]))

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
        cr = self._chip_rect()
        if cr and cr[0].contains(e.position()):       # 칩 = 전체 ◆ 보기
            self.activeCleared.emit()
            return
        k = self._key_at(x) if e.position().y() <= 14 else None
        gk = self._gkey_at(x) if e.position().y() <= 24 else None
        if e.button() == Qt.RightButton:
            if k is not None:
                self.keyDeleteRequested.emit(k)
            elif gk is not None:
                self.gkeyDeleteRequested.emit(gk)
            return
        if k is None and gk is not None:
            self._drag, self._edge = False, ""
            self.seekRequested.emit(gk)
            self.gkeyClicked.emit(gk)
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
    """타임라인 3줄: 위 = 글자·이미지 / 가운데 = 영상 컷 / 아래 = 음악, 맨 아래 눈금(결과 시간).
    컷: 클릭 = 선택, 드래그 = 순서 변경, 더블클릭 = 소스 열기.
    글자·이미지·음악: 클릭 = 선택, 가운데 끌기 = 이동, 끝 끌기 = 길이(자석), 더블클릭 = 설정, 우클릭 = 삭제.
    빈 곳·눈금 클릭 = 재생 위치(빨간 선)."""
    selected = Signal(str)
    moved = Signal(int, int)          # from, to
    activated = Signal(str)           # 컷 더블클릭
    timeChanged = Signal(float)       # 재생 위치(초)
    ovSelected = Signal(str, str)     # kind("title"|"music"), id
    ovActivated = Signal(str, str)
    ovDragStart = Signal(str, str)
    ovEdited = Signal(str, str)
    ovRemove = Signal(str, str)
    transSelected = Signal(str)       # 나비(화면 전환) 클릭 = 그 컷 id
    transDurStart = Signal(str)       # v0.16.34 전환 구간 끝 끌기 시작(실행취소 지점)
    transDurEdited = Signal(str, float)   # 끌면서 바뀐 전환 길이(초)
    transRemove = Signal(str)         # 나비 우클릭 = 빼기
    transActivated = Signal(str)      # 나비 더블클릭 = 컷편집 창
    cutMenu = Signal(str, object)     # v0.16.66 컷 우클릭 = (컷 id, 화면 좌표) → 원본 소리 메뉴
    ovFollow = Signal(str, str)       # v0.16.67 Shift+클릭 = 따라감 켜고 끄기
    cutEdgeStart = Signal(str, str)   # v0.16.67 나비 아래 날개 끌기 시작 = (컷 id, 'in'|'out')
    cutEdgeDragged = Signal(str, str, float)   # 누른 곳부터 끈 거리(초, 타임라인)
    cutEdgeEnd = Signal()

    WING = 9         # 전환 없는 경계·맨 앞·맨 뒤 날개 폭(px)

    RULER = 20
    TL = 18          # 글자·이미지 줄 높이
    ML = 30          # 음악 줄 높이(v0.16.64 20 → 30: 파형·박자 눈금)
    GRAB = 6
    SNAP = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.pps = 30.0
        self.items = []               # [(id, sec, label, speed, tag, trans(name, d) | None, start)]
        self.sel = ""
        self.trans_sel = ""           # 선택한 화면 전환(뒤 컷 id)
        self.titles, self.music = [], []
        self.loud = {}                # v0.16.66 컷 id → (원본 키움?, aud, 이유)
        self.music_info = {}          # v0.16.64 음악 파일 → 분석(music.analyze): 파형 · 박자 · 마디 첫 박
        self.ov_sel = ("", "")
        self.t = 0.0
        self._press = None            # 컷: (index, x)
        self._drag_x = None
        self._ov = None               # (kind, dict, mode, x0, snapshot)
        self._tdur = None             # 전환 길이 끌기: (컷 id, 누른 x, 처음 길이, 왼쪽 반?, 시작함?)
        self._edge = None             # 컷 인·아웃 끌기: (컷 id, 'in'|'out', 누른 x, 시작함?)
        self.setMouseTracking(True)

    # ---------------------------------------------------------------- 데이터
    def set_items(self, items, sel):
        self.items, self.sel = items, sel
        self._resize()
        self.update()

    def set_overlays(self, titles, music, sel):
        self.titles, self.music, self.ov_sel = titles, music, sel
        self._resize()
        self.update()

    def set_loud(self, loud: dict):
        self.loud = loud
        self.update()

    def set_music_info(self, info: dict):
        self.music_info = info
        self.update()

    def set_time(self, t):
        self.t = max(0.0, t)
        self.update()

    def fit(self):
        self._resize()
        self.update()

    def set_zoom(self, pps):
        self.pps = pps
        self._resize()
        self.update()

    def total(self):
        cut_end = max((it[6] + it[1] for it in self.items), default=0.0)
        ov_end = max([float(t["t1"]) for t in self.titles] + [float(m["t0"]) + float(m["len"]) for m in self.music] + [0.0])
        return max(cut_end, ov_end)


    def _resize(self):
        w = int(self.total() * self.pps + 80)
        h = self.height()
        parent = self.parentWidget()
        if parent is not None:
            w = max(w, parent.width())
            h = max(self.minimumHeight(), parent.height())
        self.setMinimumWidth(w)
        self.resize(w, h)

    # ---------------------------------------------------------------- 좌표
    def _x(self, t):
        return 4 + t * self.pps

    def _t(self, x):
        return max(0.0, (x - 4) / self.pps)

    def _title_rows(self):
        """겹치는 글자·이미지는 줄을 나눠 쌓음 → [(title, row)], 줄 수.
        v0.16.38: 화면에 쌓이는 순서대로 — 위에 그려지는 것(목록 뒤쪽)이 윗줄(0). 사각형(맨 아래)은 겹치는 글자 아래 줄"""
        placed = []                    # (t0, t1, 줄) — 위 레이어부터
        out = []
        for t in reversed(self.titles):
            a, b = float(t["t0"]), float(t["t1"])
            over = [r for x0, x1, r in placed if not (b <= x0 + 1e-6 or a >= x1 - 1e-6)]
            r = max(over) + 1 if over else 0           # 겹치는 위 레이어들보다 아래 줄
            placed.append((a, b, r))
            out.append((t, r))
        out.reverse()
        return out, max(1, 1 + max((r for _a, _b, r in placed), default=0))

    def _lanes(self):
        h = self.height()
        rows = self._title_rows()[1]
        top = QRectF(0, 2, self.width(), self.TL if rows == 1 else min(3, rows) * 16)
        mus = QRectF(0, h - self.RULER - self.ML - 2, self.width(), self.ML)
        vid = QRectF(0, top.bottom() + 3, self.width(), mus.top() - 3 - top.bottom() - 3)
        return top, vid, mus

    def _rects(self):
        _top, vid, _m = self._lanes()
        return [QRectF(self._x(it[6]), vid.top(), max(6.0, it[1] * self.pps) - 2, vid.height()) for it in self.items]

    def _ov_rects(self):
        top, _v, mus = self._lanes()
        out = []
        trs, n = self._title_rows()
        rh = top.height() / n
        for t, r in trs:
            out.append(("title", t, QRectF(self._x(float(t["t0"])), top.top() + r * rh + (1 if n > 1 else 0),
                                           max(4.0, (float(t["t1"]) - float(t["t0"])) * self.pps), rh - (2 if n > 1 else 0))))
        for m in self.music:
            out.append(("music", m, QRectF(self._x(float(m["t0"])), mus.top(), max(4.0, float(m["len"]) * self.pps), mus.height())))
        return out

    def _trans_rects(self):
        """[(컷 id, 나비 사각형)] — 나비 = 컷 앞 경계, 폭 = 전환 길이, 높이 = 영상 줄 전체."""
        out = []
        for it, r in zip(self.items, self._rects()):
            if len(it) > 5 and it[5]:
                tw = max(10.0, it[5][1] * self.pps)
                out.append((it[0], QRectF(r.left(), r.top(), tw, r.height())))
        return out

    def _handles(self):
        """v0.16.67 나비 = 위 노랑(전환 길이) · 아래 왼쪽 하늘색(앞 컷 아웃) · 아래 오른쪽 하늘색(뒤 컷 인).
        → [(종류 'dur'|'out'|'in', 컷 id, 사각형)]. 전환 없는 경계·맨 앞(인)·맨 뒤(아웃)는 아래 날개만."""
        out = []
        rects = self._rects()
        trs = dict(self._trans_rects())
        w = self.WING
        for i, (it, r) in enumerate(zip(self.items, rects)):
            mid = r.top() + r.height() / 2
            tr = trs.get(it[0])
            if tr is not None:
                cx = tr.center().x()
                out.append(("dur", it[0], QRectF(tr.left(), tr.top(), tr.width(), tr.height() / 2)))
                if i > 0:
                    out.append(("out", self.items[i - 1][0], QRectF(tr.left(), mid, cx - tr.left(), tr.bottom() - mid)))
                out.append(("in", it[0], QRectF(cx, mid, tr.right() - cx, tr.bottom() - mid)))
            else:
                x = r.left()
                if i > 0:
                    out.append(("out", self.items[i - 1][0], QRectF(x - w, mid, w, r.bottom() - mid)))
                out.append(("in", it[0], QRectF(x, mid, w, r.bottom() - mid)))
        if self.items:
            r = rects[-1]
            out.append(("out", self.items[-1][0], QRectF(r.right() + 2 - w, r.top() + r.height() / 2, w, r.height() / 2)))
        return out

    def _handle_at(self, pos):
        for kind, cid, r in self._handles():
            if r.adjusted(-1, 0, 1, 0).contains(pos):
                return kind, cid, r
        return None

    def _handle_tip(self, h):
        kind, cid, _r = h
        if kind == "out":
            return "컷아웃 수정"
        if kind == "in":
            return "컷인 수정"
        it = next((x for x in self.items if x[0] == cid), None)
        return f"{it[5][0]} 수정" if it and it[5] else ""

    def _trans_at(self, pos):
        for cid, r in self._trans_rects():
            if r.adjusted(-3, 0, 3, 0).contains(pos):
                return cid
        return ""

    def _index_at(self, x):
        for i, r in enumerate(self._rects()):
            if r.left() <= x <= r.right() + 2:
                return i
        return -1

    def _ov_at(self, pos):
        for kind, d, r in reversed(self._ov_rects()):
            if r.adjusted(-self.GRAB, -1, self.GRAB, 1).contains(pos):
                if abs(pos.x() - r.left()) <= self.GRAB:
                    return kind, d, "l"
                if abs(pos.x() - r.right()) <= self.GRAB:
                    return kind, d, "r"
                if r.contains(pos):
                    return kind, d, "move"
        return None

    def _trans_tip(self, cid):
        it = next((x for x in self.items if x[0] == cid), None)
        return f"{it[5][0]} {it[5][1]:.1f}초" if it and it[5] else ""

    def tooltip_at(self, x):
        i = self._index_at(x)
        tip = []
        if i >= 0 and len(self.items[i]) > 5 and self.items[i][5]:
            n, d = self.items[i][5]
            tip.append(f"{n} {d:.1f}초")
        if i >= 0:
            ld = self.loud.get(self.items[i][0])
            if ld:
                up, aud, why = ld
                how = {"up": "키움(직접)", "keep": "안 키움(직접)"}.get(aud, ("키움" if up else "안 키움") + (f"({why})" if why else ""))
                tip.append(f"원본 소리 {how}")
        return "\n".join(tip)

    @staticmethod
    def _speaker(p, r, col):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        x, y, w, h = r.left(), r.top(), r.width(), r.height()
        p.drawPolygon(QPolygonF([QPointF(x, y + h * 0.35), QPointF(x + w * 0.25, y + h * 0.35), QPointF(x + w * 0.55, y),
                                 QPointF(x + w * 0.55, y + h), QPointF(x + w * 0.25, y + h * 0.65), QPointF(x, y + h * 0.65)]))
        p.setPen(QPen(col, 1.4))
        p.setBrush(Qt.NoBrush)
        for k in (0.25, 0.45):
            p.drawArc(QRectF(x + w * (0.45 - k), y + h * (0.5 - k * 1.3), w * k * 2.4, h * k * 2.6), -50 * 16, 100 * 16)
        p.restore()

    # ---------------------------------------------------------------- 그리기
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#1b1b1b"))
        top, vid, mus = self._lanes()
        p.fillRect(top, QColor("#202020"))
        p.fillRect(mus, QColor("#202020"))
        rects = self._rects()
        f = QFont(self.font())
        for i, (it, r) in enumerate(zip(self.items, rects)):
            sid, sec, label, sp, tag = it[:5]
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
            ld = self.loud.get(sid)
            if ld and ld[0] and rr.width() > 22:          # 원본 소리 키움 = 스피커(손으로 정함 = 노랑)
                self._speaker(p, QRectF(rr.right() - 20, rr.top() + 4, 16, 13), QColor("#f2c94c") if ld[1] == "up" else QColor("#ffffff"))
        for cid, r in self._trans_rects():     # 화면 전환 = 앞뒤 컷이 실제로 섞이는 구간(앞 컷 끝 d = 뒤 컷 앞 d)
            sel = cid == self.trans_sel
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(15, 30, 60, 150))        # 섞이는 구간 칠하기(v0.16.34, 컷 파랑과 구분되게 어둡게)
            p.drawRect(r)
            x0, x1, y0, y1 = r.left(), r.right(), r.top() + 2, r.bottom() - 2
            bow = QPolygonF([QPointF(x0, y0), QPointF(x1, y1), QPointF(x1, y0), QPointF(x0, y1)])
            ym, xc = r.top() + r.height() / 2, r.center().x()
            for clip, col in ((QRectF(x0 - 1, r.top(), x1 - x0 + 2, ym - r.top()), WING_DUR),       # v0.16.67 위 = 전환 길이(노랑)
                              (QRectF(x0 - 1, ym, xc - x0 + 1, r.bottom() - ym), WING_CUT),         # 아래 왼쪽 = 앞 컷 아웃
                              (QRectF(xc, ym, x1 - xc + 1, r.bottom() - ym), WING_CUT)):            # 아래 오른쪽 = 뒤 컷 인
                p.save()
                p.setClipRect(clip)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPolygon(bow)
                p.restore()
            if sel:
                p.setPen(QPen(QColor("white"), 2))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(bow)
            it = next((x for x in self.items if x[0] == cid), None)
            if it and it[5]:
                fl = QFont(self.font())
                fl.setBold(True)
                fl.setPointSizeF(8)
                p.setFont(fl)
                txt = f"{it[5][1]:.1f}초"
                tw = p.fontMetrics().horizontalAdvance(txt) + 6
                box = QRectF(r.center().x() - tw / 2, r.top() + 2, tw, 14)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(20, 30, 45, 210))
                p.drawRoundedRect(box, 3, 3)
                p.setPen(QColor("#ffffff"))
                p.drawText(box, Qt.AlignCenter, txt)
        trs = {c for c, _r in self._trans_rects()}
        p.setPen(Qt.NoPen)
        p.setBrush(WING_CUT)
        for kind, cid, r in self._handles():           # 전환 없는 경계·맨 앞·맨 뒤 = 아래 날개(하늘색 삼각형, 뾰족한 쪽 = 경계)
            if kind == "dur" or (kind == "in" and cid in trs) or (kind == "out" and self._next_has_trans(cid, trs)):
                continue
            y0, y1 = r.top(), r.bottom() - 2
            if kind == "out":
                pts = [QPointF(r.left(), y0), QPointF(r.left(), y1), QPointF(r.right(), y1)]
            else:
                pts = [QPointF(r.right(), y0), QPointF(r.right(), y1), QPointF(r.left(), y1)]
            p.drawPolygon(QPolygonF(pts))
        if self._press is not None and self._drag_x is not None:
            j = self._drop_index(self._drag_x)
            xs = [r.left() for r in rects] + [rects[-1].right() + 2 if rects else 4]
            x = xs[min(j, len(xs) - 1)] - 1
            p.setPen(QPen(QColor("#f2c94c"), 3))
            p.drawLine(QPointF(x, vid.top()), QPointF(x, vid.bottom()))
        # 글자·이미지·음악
        f.setBold(False)
        f.setPointSizeF(8)
        p.setFont(f)
        for kind, d, r in self._ov_rects():
            if kind == "title":
                kd = d.get("kind")
                c = QColor({"text": "#7a5fb0", "rect": "#6a6a6a"}.get(kd, "#5f7f9e"))
                label = (d.get("text") or "").split("\n")[0] if kd == "text" else ("▭" if kd == "rect" else "▣")
            else:
                c = QColor("#2f6b4a")
                label = Path(d.get("path", "")).stem
            c.setAlpha(225)
            p.fillRect(r, c)
            if kind == "music":
                self._paint_music(p, d, r)
            if (kind, d.get("id")) == self.ov_sel:
                p.setPen(QPen(QColor("white"), 2))
                p.drawRect(r.adjusted(1, 1, -1, -1))
            fl = 14 if d.get("follow") else 4
            if d.get("follow"):
                self._ring(p, r)
            p.setPen(QColor("#f4f4f4"))
            p.drawText(r.adjusted(fl, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        # 눈금
        y0 = h - self.RULER
        p.fillRect(QRectF(0, y0, w, self.RULER), QColor("#151515"))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120) if s * self.pps >= 60)
        minor = step / 5
        t = 0.0
        end = (w - 4) / self.pps
        while t <= end:
            x = self._x(t)
            major = abs((t / step) - round(t / step)) < 1e-6
            p.setPen(QColor("#888") if major else QColor("#444"))
            p.drawLine(QPointF(x, y0), QPointF(x, y0 + (8 if major else 4)))
            if major:
                p.drawText(QPointF(x + 2, h - 3), f"{int(t // 60)}:{t % 60:04.1f}" if t >= 60 else f"{t:g}s")
            t = round(t + minor, 6)
        # 재생 위치
        x = self._x(self.t)
        p.setPen(QPen(QColor("#e5484d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    def _next_has_trans(self, cid, trs):
        i = next((k for k, x in enumerate(self.items) if x[0] == cid), -1)
        return 0 <= i < len(self.items) - 1 and self.items[i + 1][0] in trs

    @staticmethod
    def _ring(p, r):
        """따라감 = 고리 표시(막대 왼쪽 안)."""
        d = min(9.0, r.height() - 4)
        if d < 4 or r.width() < d + 4:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        rr = QRectF(r.left() + 3, r.center().y() - d / 2, d, d)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawEllipse(rr)
        p.setPen(QPen(QColor("#f2c94c"), 1.6))
        p.drawEllipse(rr)
        p.restore()

    def _paint_music(self, p, m, r):
        """음악 막대 안: 파형(밝은 초록) · 박자(짧은 눈금) · 마디 첫 박(긴 눈금) · 다른 곡과 겹친 곳 = X(크로스페이드)."""
        inf = self.music_info.get(m.get("path", ""))
        off, ln = float(m.get("off", 0)), float(m["len"])
        p.save()
        p.setClipRect(r)
        if inf and inf.get("peaks"):
            pk = inf["peaks"]
            per = 50.0
            cy, hh = r.center().y(), r.height() / 2 - 2
            x0, x1 = max(r.left(), 0), min(r.right(), self.width())
            step = 2
            col = QColor(150, 220, 175, 150)
            p.setPen(QPen(col, 1))
            x = x0
            while x <= x1:
                ta = off + (x - r.left()) / self.pps
                tb = ta + step / self.pps
                ia, ib = int(ta * per), max(int(ta * per) + 1, int(tb * per))
                seg = pk[max(0, ia):min(len(pk), ib)]
                v = (max(seg) / 255.0) if seg else 0.0
                p.drawLine(QPointF(x, cy - v * hh), QPointF(x, cy + v * hh))
                x += step
            conf = float(inf.get("conf", 0))
            if conf >= 0.15:
                a = 70 + int(140 * min(1.0, conf))
                bt = [b for b in inf.get("beats", []) if off <= b <= off + ln]
                if len(bt) > 1 and (bt[1] - bt[0]) * self.pps >= 5:
                    p.setPen(QPen(QColor(255, 255, 255, a // 2), 1))
                    for b in bt:
                        x = r.left() + (b - off) * self.pps
                        p.drawLine(QPointF(x, r.bottom() - 5), QPointF(x, r.bottom()))
                p.setPen(QPen(QColor(242, 201, 76, a), 1))
                for b in inf.get("bars", []):
                    if off <= b <= off + ln:
                        x = r.left() + (b - off) * self.pps
                        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.restore()
        t0 = float(m["t0"])                              # 앞 곡과 겹침 = X
        for o in self.music:
            if o is m:
                continue
            a, b = float(o["t0"]), float(o["t0"]) + float(o["len"])
            if a < t0 < b:
                xa, xb = self._x(t0), self._x(min(b, t0 + ln))
                p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
                p.drawLine(QPointF(xa, r.top()), QPointF(xb, r.bottom()))
                p.drawLine(QPointF(xa, r.bottom()), QPointF(xb, r.top()))

    def _drop_index(self, x):
        rects = self._rects()
        for i, r in enumerate(rects):
            if x < r.center().x():
                return i
        return len(rects)

    # ---------------------------------------------------------------- 자석
    def _snap_targets(self, exclude):
        ts = [0.0, self.t] + [it[6] for it in self.items] + [it[6] + it[1] for it in self.items]
        for t in self.titles:
            if t is not exclude:
                ts += [float(t["t0"]), float(t["t1"])]
        for m in self.music:
            if m is not exclude:
                ts += [float(m["t0"]), float(m["t0"]) + float(m["len"])]
        if not (isinstance(exclude, dict) and exclude in self.music):      # v0.16.64 글자·이미지 = 음악 박자에도 붙음(리듬 뚜렷한 곡만)
            from .music import beats_on_timeline
            for m in self.music:
                inf = self.music_info.get(m.get("path", ""))
                if inf and float(inf.get("conf", 0)) >= 0.3:
                    ts += beats_on_timeline(m, inf)
        return ts

    def _bar_snap(self, m, n0):
        """음악 옮기기: 마디 첫 박이 컷 경계에 가까우면 그 자리로(v0.16.64). → 새 t0 또는 None."""
        inf = self.music_info.get(m.get("path", ""))
        if not inf or float(inf.get("conf", 0)) < 0.3 or not inf.get("bars"):
            return None
        cuts = [it[6] for it in self.items] + ([self.items[-1][6] + self.items[-1][1]] if self.items else [])
        off, ln = float(m.get("off", 0)), float(m["len"])
        tol = self.SNAP / self.pps
        best = None
        for b in inf["bars"]:
            if not (off <= b <= off + ln):
                continue
            x = n0 + b - off
            for c in cuts:
                d = c - x
                if abs(d) <= tol and (best is None or abs(d) < abs(best)):
                    best = d
        return None if best is None else n0 + best

    def _snap(self, v, targets):
        tol = self.SNAP / self.pps
        best = min(targets, key=lambda t: abs(t - v), default=v)
        return best if abs(best - v) <= tol else v

    # ---------------------------------------------------------------- 마우스
    def mousePressEvent(self, e):
        pos = e.position()
        hd = self._handle_at(pos)
        if hd and hd[0] == "dur" and e.button() == Qt.RightButton:
            self.transRemove.emit(hd[1])
            return
        if hd and e.button() == Qt.LeftButton:
            kind, cid, r = hd
            if kind == "dur":                        # 위 노랑 = 고르기(미리보기) + 끌어서 전환 길이
                it = next((x for x in self.items if x[0] == cid), None)
                d0 = it[5][1] if it and it[5] else 0.5
                self._tdur = (cid, pos.x(), d0, pos.x() < r.center().x(), False)
                self.trans_sel = cid
                self.transSelected.emit(cid)
            else:                                    # 아래 하늘색 = 컷 아웃·인 끌기
                self._edge = (cid, kind, pos.x(), False)
            self.update()
            return
        tid = self._trans_at(pos)
        if tid:
            if e.button() == Qt.RightButton:
                self.transRemove.emit(tid)
                return
            self.trans_sel = tid
            self.transSelected.emit(tid)
            self.update()
            return
        hit = self._ov_at(pos)
        if hit:
            kind, d, mode = hit
            if e.button() == Qt.RightButton:
                self.ovRemove.emit(kind, d["id"])
                return
            if e.modifiers() & Qt.ShiftModifier:    # v0.16.67 Shift+클릭 = 따라감 켜고 끄기
                self.ovFollow.emit(kind, d["id"])
                return
            self.ov_sel = (kind, d["id"])
            self.ovSelected.emit(kind, d["id"])
            self.ovDragStart.emit(kind, d["id"])
            self._ov = (kind, d, mode, pos.x(), dict(d))
            self.update()
            return
        i = self._index_at(pos.x())
        _top, vid, _m = self._lanes()
        if i >= 0 and vid.top() <= pos.y() <= vid.bottom() and e.button() == Qt.RightButton:
            self.cutMenu.emit(self.items[i][0], e.globalPosition().toPoint())
            return
        if i >= 0 and vid.top() <= pos.y() <= vid.bottom():
            self._press = (i, pos.x())
            self._drag_x = None
            self.selected.emit(self.items[i][0])
            return
        self._press = None
        self.t = self._t(pos.x())         # 빈 곳·눈금 = 재생 위치
        self.timeChanged.emit(self.t)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._tdur and (e.buttons() & Qt.LeftButton):
            cid, x0, d0, left, started = self._tdur
            dx = pos.x() - x0
            if not started:
                if abs(dx) < 3:
                    return
                self._tdur = (cid, x0, d0, left, True)
                self.transDurStart.emit(cid)
            d = d0 + (-dx if left else dx) / self.pps
            self.transDurEdited.emit(cid, round(max(0.0, d) * 10) / 10)      # 0.1초 단위(범위는 받는 쪽이 맞춤)
            return
        if self._edge and (e.buttons() & Qt.LeftButton):
            cid, kind, x0, started = self._edge
            dx = pos.x() - x0
            if not started:
                if abs(dx) < 3:
                    return
                self._edge = (cid, kind, x0, True)
                self.cutEdgeStart.emit(cid, kind)
            self.cutEdgeDragged.emit(cid, kind, dx / self.pps)
            return
        if self._ov is not None and (e.buttons() & Qt.LeftButton):
            kind, d, mode, x0, o = self._ov
            dt = (pos.x() - x0) / self.pps
            tg = self._snap_targets(d)
            if kind == "title":
                t0, t1 = float(o["t0"]), float(o["t1"])
                if mode == "move":
                    n0 = max(0.0, t0 + dt)
                    s0, s1 = self._snap(n0, tg), self._snap(n0 + (t1 - t0), tg) - (t1 - t0)
                    n0 = s0 if s0 != n0 else s1
                    d["t0"], d["t1"] = max(0.0, n0), max(0.0, n0) + (t1 - t0)
                elif mode == "l":
                    d["t0"] = max(0.0, min(t1 - 0.2, self._snap(t0 + dt, tg)))
                else:
                    d["t1"] = max(t0 + 0.2, self._snap(t1 + dt, tg))
            else:
                t0, off, ln, dur = float(o["t0"]), float(o.get("off", 0)), float(o["len"]), float(o.get("dur", o["len"]))
                if mode == "move":
                    n0 = max(0.0, t0 + dt)
                    s0, s1 = self._snap(n0, tg), self._snap(n0 + ln, tg) - ln
                    sb = self._bar_snap(d, n0)
                    cands = [x for x in (s0, s1, sb) if x is not None and abs(x - n0) > 1e-6]    # (n0+len)-len 소수 오차 = 안 붙은 것
                    d["t0"] = max(0.0, min(cands, key=lambda x: abs(x - n0)) if cands else n0)
                elif mode == "l":       # 앞을 자름: 파일 안 시작도 같이
                    n0 = self._snap(t0 + dt, tg)
                    n0 = max(t0 - off, min(t0 + ln - 0.2, n0))
                    d["t0"], d["off"], d["len"] = max(0.0, n0), off + (n0 - t0), ln - (n0 - t0)
                else:
                    d["len"] = max(0.2, min(dur - off, self._snap(t0 + ln + dt, tg) - t0))
            self.ovEdited.emit(kind, d["id"])
            self._resize()
            self.update()
            return
        if not e.buttons():
            hit = self._ov_at(pos)
            hd = self._handle_at(pos)
            tid = self._trans_at(pos)
            self.setCursor(Qt.SizeHorCursor if hd else Qt.PointingHandCursor if tid else
                           Qt.SizeHorCursor if hit and hit[2] in ("l", "r") else
                           Qt.OpenHandCursor if hit else Qt.ArrowCursor)
            self.setToolTip(self._handle_tip(hd) if hd else self._trans_tip(tid) if tid else
                            self.tooltip_at(pos.x()) if not hit else "")
        if self._press is not None and (e.buttons() & Qt.LeftButton):
            if self._drag_x is not None or abs(pos.x() - self._press[1]) > 6:
                self._drag_x = pos.x()
                self.update()
        elif e.buttons() & Qt.LeftButton and self._press is None:
            self.t = self._t(pos.x())
            self.timeChanged.emit(self.t)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._tdur:
            self._tdur = None
            return
        if self._edge:
            started = self._edge[3]
            self._edge = None
            if started:
                self.cutEdgeEnd.emit()
            return
        if self._ov is not None:
            self._ov = None
            return
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
        hd = self._handle_at(e.position())
        if hd and hd[0] in ("in", "out"):
            return
        tid = self._trans_at(e.position())
        if tid:
            self.transActivated.emit(tid)
            return
        hit = self._ov_at(e.position())
        if hit:
            self.ovActivated.emit(hit[0], hit[1]["id"])
            return
        i = self._index_at(e.position().x())
        if i >= 0:
            self.activated.emit(self.items[i][0])
