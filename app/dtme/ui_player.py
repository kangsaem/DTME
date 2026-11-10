"""프리뷰 모니터. 모든 화면을 직접 그린다(재생 프레임도 QVideoSink 로 받아 그림).
- 재생: 프록시 프레임
- 정지·이동·드래그·역재생: 프록시에서 한 장씩 뽑아 즉시 표시
- 멈춘 뒤: 편집 화면이 원본 기준 보정 화면을 덮어씀(show_image)
- 세로 출력이면 잘리는 영역을 어둡게 표시
"""
from __future__ import annotations

import math
import os
from fractions import Fraction

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import ff, framecache, jobs


class Monitor(QWidget):
    """layerPressed(id) = 레이어를 잡기 직전(실행취소 지점), layerChanged = 위치·크기 바뀜, layerSelected(id 또는 '')."""
    layerPressed = Signal(str)
    layerChanged = Signal()
    layerSelected = Signal(str)
    cropPressed = Signal()
    cropDragged = Signal(float)        # 세로 크롭 이동량(원본 px)
    whitePicked = Signal(float, float)   # 흰색 찍기: 영상 안 위치(0~1)
    viewChanged = Signal()               # 확대·이동 바뀜(→ 확대 영역 고화질 다시 만들기)
    splitFlipped = Signal(bool)          # 반반 선 우클릭 → 방향(True = 좌우)
    titlePressed = Signal(str)           # 타임라인 모드: 글자·이미지를 잡음(실행취소 지점)
    titleActivated = Signal(str)         # 글자 더블클릭 = 글자 창(v0.16.33)
    titleChanged = Signal()
    modeRequested = Signal(str)          # "source" | "timeline"
    contrastRequested = Signal()         # RGB 그래프 [명암]
    balanceRequested = Signal()          # RGB 그래프 [색 균형]

    HANDLE = 9

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img: QImage | None = None
        self.text = ""
        self.loading = None          # 프록시 준비 진행(0~1) — 모니터 가운데 표시
        self.out_aspect = 16 / 9       # 출력 화면비(세로 = 9/16)
        self.out_wh = (1920, 1080)     # 출력 픽셀(레이어 위치·크기 기준)
        self.smooth = True
        self.layers = []               # [(layer dict, QImage, (원본 w, h))] 아래 → 위 순서. 현재 프레임에 보이는 것만
        self.sel_layer = ""
        self._out_rect = QRectF()
        self._drag = None              # (mode, layer, press pos, cx, cy, scale)
        self._wheel_t = 0.0
        self.crop_dx = 0.0             # 세로 크롭 이동량(원본 px)
        self.src_w = 3840
        self.crop_max = 540.0
        self._img_rect = QRectF()
        self.before: QImage | None = None      # 반반 보기: 왼쪽에 그릴 원본
        self.split_x = 0.5
        self.split_y = 0.5
        self.split_v = True          # True = 좌우(세로 선) · False = 위아래(가로 선). 선 우클릭으로 바꿈
        self._split_drag = False
        self.pick_mode = False                  # 흰색 찍기
        self.scope = False                      # RGB 파형
        self._scope_data = None
        # 확대 보기: zoom 1 = 맞춤, center = 화면 가운데에 오는 영상 위치(0~1)
        self.zoom = 1.0
        self.center = [0.5, 0.5]
        self.space_pan = False                  # Space 누르고 있음 → 왼쪽 끌기 = 이동
        self.space_moved = False
        self._pan = None                        # (press pos, center)
        self.patch: QImage | None = None        # 확대 영역 고화질(원본에서 다시 만든 것)
        self.patch_rect = None                  # (x, y, w, h) 영상 기준 0~1
        self.titles = []                        # 타임라인 모드: [(title, alpha, QImage|None, (w, h) | None)]
        self.sel_title = ""
        self.playing = False          # v0.16.36 재생 중 = 고른 레이어·글자 틀(점선·손잡이) 숨김
        self._tdrag = None
        self._tresize = None                    # 사각형 모서리 끌기(v0.16.34)
        self._build_zoom_ui()
        self._build_mode_ui()
        self._build_scope_ui()
        self.setMouseTracking(True)

    # ---------------------------------------------------------------- [소스 | 타임라인]
    def _build_mode_ui(self):
        from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton
        self.mbox = QWidget(self)
        lay = QHBoxLayout(self.mbox)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.mode_grp = QButtonGroup(self)
        for i, (k, t) in enumerate((("source", "소스"), ("timeline", "타임라인"))):
            b = QPushButton(t)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(22)
            b.setProperty("key", k)
            from . import ui_style
            ui_style.tone(b, "overlay")
            f = b.font()
            f.setPixelSize(11)
            b.setFont(f)
            b.setFixedWidth(b.fontMetrics().horizontalAdvance(t) + 20)
            self.mode_grp.addButton(b, i)
            lay.addWidget(b)
        self.mode_grp.button(0).setChecked(True)
        self.mode_grp.buttonClicked.connect(lambda b: self.modeRequested.emit(b.property("key")))
        self.mbox.adjustSize()
        self.mbox.move(8, 8)

    def set_mode_button(self, key):
        for b in self.mode_grp.buttons():
            b.setChecked(b.property("key") == key)

    def set_titles(self, titles, sel):
        self.titles, self.sel_title = titles, sel
        self.update()

    def _title_rect(self, t, img_wh, fm=None) -> QRectF:
        c = self._out_rect
        k = c.width() / self.out_wh[0]
        if t.get("kind") == "rect":                    # v0.16.34 사각형 = 출력 화면 비율
            w, h = float(t.get("w", 0.6)) * c.width(), float(t.get("h", 0.16)) * c.height()
        elif t.get("kind") == "image":
            w, h = img_wh[0] * float(t.get("scale", 1)) * k, img_wh[1] * float(t.get("scale", 1)) * k
        else:
            from PySide6.QtGui import QFontMetricsF
            fm = fm or QFontMetricsF(self._title_font(t, k))
            lines = (t.get("text") or " ").split("\n")
            w = max(fm.horizontalAdvance(x) for x in lines) + 4
            h = fm.lineSpacing() * len(lines) + 8 * k * (len(lines) - 1)
        return QRectF(c.left() + float(t.get("cx", 0.5)) * c.width() - w / 2,
                      c.top() + float(t.get("cy", 0.5)) * c.height() - h / 2, w, h)

    _font_ids: dict = {}

    def _title_font(self, t, k):
        from PySide6.QtGui import QFont, QFontDatabase
        from .fonts import font_file
        f, real_bold = font_file(t.get("font", ""), bool(t.get("bold")))
        fam = None
        if f:
            if f not in Monitor._font_ids:
                fid = QFontDatabase.addApplicationFont(f)
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                Monitor._font_ids[f] = fams[0] if fams else None
            fam = Monitor._font_ids[f]
        font = QFont(fam) if fam else QFont()
        font.setPixelSize(max(4, int(float(t.get("size", 64)) * k)))
        font.setBold(bool(t.get("bold")) and not real_bold)
        return font

    def _paint_titles(self, p: QPainter):
        if not self.titles or self._out_rect.isEmpty():
            return
        from PySide6.QtGui import QFontMetricsF
        c = self._out_rect
        k = c.width() / self.out_wh[0]
        p.save()
        p.setClipRect(c)
        for t, alpha, img, wh in self.titles:
            p.setOpacity(max(0.0, min(1.0, alpha)))
            if t.get("kind") == "rect":
                col = QColor(t.get("color", "#000000"))
                col.setAlphaF(max(0.0, min(1.0, float(t.get("opacity", 0.5)))))
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                rad = float(t.get("radius", 0)) * min(self.out_wh) / 1080 * k     # 렌더와 같은 기준(1080 px)
                p.drawRoundedRect(self._title_rect(t, None), rad, rad)
                continue
            if t.get("kind") == "image":
                if img is not None:
                    p.drawImage(self._title_rect(t, wh), img)
                continue
            font = self._title_font(t, k)
            fm = QFontMetricsF(font)
            r = self._title_rect(t, None, fm)
            p.setFont(font)
            if t.get("bg") == "band":
                pad = 16 * k
                p.fillRect(r.adjusted(-pad, -pad, pad, pad), QColor(0, 0, 0, 115))
            lines = (t.get("text") or "").split("\n")
            y = r.top()
            for line in lines:
                lw = fm.horizontalAdvance(line)
                x = r.center().x() - lw / 2
                if t.get("bg") == "shadow":
                    p.setPen(QColor(0, 0, 0, 150))
                    p.drawText(QPointF(x + 3 * k, y + fm.ascent() + 3 * k), line)
                p.setPen(QColor(t.get("color", "#ffffff")))
                p.drawText(QPointF(x, y + fm.ascent()), line)
                y += fm.lineSpacing() + 8 * k
        p.restore()
        for t, _a, img, wh in self.titles:
            if t["id"] == self.sel_title and not self.playing:
                r = self._title_rect(t, wh)
                p.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
                if t.get("kind") == "rect":            # 모서리 손잡이(끌면 크기)
                    p.setPen(QPen(QColor("#ffffff"), 1))
                    p.setBrush(QColor("#4a8fe0"))
                    for q in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                        p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))

    def _rect_corner(self, pos):
        """고른 사각형의 모서리 근처면 (사각형, 반대쪽 모서리 점) — 크기 끌기용."""
        for t, _a, _img, wh in self.titles:
            if t["id"] == self.sel_title and t.get("kind") == "rect":
                r = self._title_rect(t, wh)
                for q, opp in ((r.topLeft(), r.bottomRight()), (r.topRight(), r.bottomLeft()),
                               (r.bottomLeft(), r.topRight()), (r.bottomRight(), r.topLeft())):
                    if abs(pos.x() - q.x()) <= 9 and abs(pos.y() - q.y()) <= 9:
                        return t, opp
        return None

    def _title_hit(self, pos):
        for t, _a, img, wh in reversed(self.titles):
            if self._title_rect(t, wh).contains(pos):
                return t
        return None

    # ---------------------------------------------------------------- 확대 보기
    def _build_zoom_ui(self):
        from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton
        self.zbox = QWidget(self)
        lay = QHBoxLayout(self.zbox)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        from . import ui_style
        self.b_zm = QPushButton("−")
        self.b_zl = QPushButton("맞춤")
        self.b_zp = QPushButton("+")
        for b, w in ((self.b_zm, 24), (self.b_zl, 52), (self.b_zp, 24)):
            b.setFixedSize(w, 22)
            ui_style.tone(b, "overlay")
            f = b.font()
            f.setPixelSize(11)
            b.setFont(f)
            b.setFocusPolicy(Qt.NoFocus)
            lay.addWidget(b)
        self.b_zm.setToolTip("축소")
        self.b_zp.setToolTip("확대 (휠)")
        self.b_zl.setToolTip("맞춤 · 100% · 200% · 400%")
        self.b_zm.clicked.connect(lambda: self.zoom_by(1 / 1.25))
        self.b_zp.clicked.connect(lambda: self.zoom_by(1.25))
        menu = QMenu(self)
        for label, pct in (("맞춤", 0), ("100%", 100), ("200%", 200), ("400%", 400)):
            menu.addAction(label).triggered.connect(lambda _=False, v=pct: self.set_percent(v))
        self.b_zl.clicked.connect(lambda: menu.exec(self.b_zl.mapToGlobal(self.b_zl.rect().topLeft())
                                                    - QPointF(0, menu.sizeHint().height()).toPoint()))
        self.zbox.adjustSize()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.zbox.move(self.width() - self.zbox.width() - 8, self.height() - self.zbox.height() - 8)
        self._place_scope_ui()

    # ---------------------------------------------------------------- RGB 그래프 [명암] [색 균형]
    def _build_scope_ui(self):
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        self.sbox = QWidget(self)
        lay = QHBoxLayout(self.sbox)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        from . import ui_style
        for t, tip, sig in (("명암", "양끝을 목표선(5%·95%)에 맞춤", self.contrastRequested),
                            ("색 균형", "중간 밝기에서 빨강·파랑을 초록에 맞춘 뒤 물빛만 파랑", self.balanceRequested)):
            b = QPushButton(t)
            b.setFixedSize(56, 22)
            ui_style.tone(b, "overlay")
            f = b.font()
            f.setPixelSize(11)
            b.setFont(f)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
        self.sbox.adjustSize()
        self.sbox.hide()

    def _scope_box(self) -> QRectF:
        w, h = max(180, self.width() * 0.24), max(92, self.height() * 0.22)
        return QRectF(self.width() - w - 8, 8, w, h)

    def _place_scope_ui(self):
        b = self._scope_box()
        self.sbox.move(int(b.right() - self.sbox.width()), int(b.bottom() + 3))
        self.sbox.setVisible(bool(self.scope))

    def _fit_rect(self):
        if self.img is None or self.img.isNull():
            return QRectF()
        iw, ih = self.img.width(), self.img.height()
        k = min(self.width() / iw, self.height() / ih)
        return QRectF((self.width() - iw * k) / 2, (self.height() - ih * k) / 2, iw * k, ih * k)

    def _view_rect(self):
        """확대·이동을 반영한 영상 사각형(화면 좌표)."""
        r0 = self._fit_rect()
        if r0.isEmpty() or self.zoom <= 1.0001:
            return r0
        w, h = r0.width() * self.zoom, r0.height() * self.zoom
        cx = max(0.5 * self.width() / w, min(1 - 0.5 * self.width() / w, self.center[0])) if w > self.width() else 0.5
        cy = max(0.5 * self.height() / h, min(1 - 0.5 * self.height() / h, self.center[1])) if h > self.height() else 0.5
        self.center = [cx, cy]
        return QRectF(self.width() / 2 - cx * w, self.height() / 2 - cy * h, w, h)

    def percent(self) -> float:
        r = self._view_rect()
        return r.width() / max(1, self.src_w) * 100 * self.devicePixelRatioF() if not r.isEmpty() else 0

    def _zoom_label(self):
        self.b_zl.setText("맞춤" if self.zoom <= 1.0001 else f"{self.percent():.0f}%")

    def set_zoom(self, z, anchor=None):
        """anchor = 화면 좌표: 그 점의 영상 위치가 그대로 남게."""
        r = self._view_rect()
        z = max(1.0, min(40.0, z))
        if anchor is not None and not r.isEmpty():
            nx = (anchor.x() - r.left()) / r.width()
            ny = (anchor.y() - r.top()) / r.height()
            r0 = self._fit_rect()
            w, h = r0.width() * z, r0.height() * z
            self.center = [nx - (anchor.x() - self.width() / 2) / w, ny - (anchor.y() - self.height() / 2) / h]
        self.zoom = z
        if z <= 1.0001:
            self.center = [0.5, 0.5]
        self.patch = None
        self._zoom_label()
        self.update()
        self.viewChanged.emit()

    def zoom_by(self, f, anchor=None):
        self.set_zoom(self.zoom * f, anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2))

    def set_percent(self, pct):
        if pct <= 0:
            self.set_zoom(1.0)
            return
        r0 = self._fit_rect()
        if r0.isEmpty():
            return
        self.set_zoom(pct / 100 * self.src_w / self.devicePixelRatioF() / r0.width(), QPointF(self.width() / 2, self.height() / 2))

    def visible_norm(self):
        """보이는 영상 영역 (x, y, w, h) 0~1."""
        r = self._view_rect()
        if r.isEmpty():
            return None
        x0 = max(0.0, -r.left() / r.width())
        y0 = max(0.0, -r.top() / r.height())
        x1 = min(1.0, (self.width() - r.left()) / r.width())
        y1 = min(1.0, (self.height() - r.top()) / r.height())
        return x0, y0, x1 - x0, y1 - y0

    def set_patch(self, img, rect):
        self.patch, self.patch_rect = img, rect
        self.update()

    def mouseDoubleClickEvent(self, e):
        tt = self._title_hit(e.position()) if self.titles else None
        if tt is not None and e.button() == Qt.LeftButton:     # v0.16.33: 모니터의 글자·이미지 더블클릭 = 설정 창
            self._tdrag = None
            self.titleActivated.emit(tt["id"])
            return
        if self.zoom > 1.0001:
            self.set_zoom(1.0)

    def set_before(self, img):
        self.before = img
        self.update()

    def set_scope(self, mode):
        """0 끔 · 1 겹침(채널 히스토그램) · 2 파레이드(R·G·B 3칸, 세로 = 밝기). True = 1."""
        self.scope = int(mode)
        self._scope_data = None
        self._place_scope_ui()
        self.update()

    def set_pick(self, on):
        self.pick_mode = on
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def set_crop(self, dx: float, src_w: int, max_px: float):
        self.crop_dx, self.src_w, self.crop_max = dx, max(1, src_w), max_px
        self.update()

    def _crop_mode(self) -> bool:
        return not self._img_rect.isEmpty() and self.out_aspect < self._img_rect.width() / self._img_rect.height() - 0.01

    def sizeHint(self):
        return QSize(960, 540)

    def set_image(self, img: QImage | None, smooth=True):
        self.img = img
        self._scope_data = None
        self.patch = None
        self.text = ""
        self.smooth = smooth
        self.update()

    def set_text(self, text: str):
        self.img = None
        self.text = text
        self.update()

    def set_aspect(self, aspect: float):
        self.out_aspect = aspect
        self.out_wh = (1080, 1920) if aspect < 1 else (1920, 1080)
        self.update()

    def set_layers(self, layers, sel: str):
        self.layers, self.sel_layer = layers, sel
        self.update()

    # ---------------------------------------------------------------- 레이어 위치(화면 좌표)
    def _layer_rect(self, lay, wh) -> QRectF:
        c = self._out_rect
        k = c.width() / self.out_wh[0]
        w, h = wh[0] * lay["scale"] * k, wh[1] * lay["scale"] * k
        return QRectF(c.left() + lay["cx"] * c.width() - w / 2, c.top() + lay["cy"] * c.height() - h / 2, w, h)

    def _corners(self, r: QRectF):
        return [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]

    def _hit(self, pos):
        """위에 있는 레이어부터 (mode, layer). mode = 'scale' | 'move'"""
        if self._out_rect.isEmpty():
            return None, None
        for lay, _img, wh in reversed(self.layers):
            r = self._layer_rect(lay, wh)
            if lay["id"] == self.sel_layer:
                for c in self._corners(r):
                    if abs(pos.x() - c.x()) <= self.HANDLE and abs(pos.y() - c.y()) <= self.HANDLE:
                        return "scale", lay
            if r.contains(pos):
                return "move", lay
        return None, None

    def _split_px(self):
        r = self._img_rect
        return r.left() + r.width() * self.split_x

    def _split_hit(self, pos) -> bool:
        r = self._img_rect
        if self.before is None or r.isEmpty():
            return False
        if self.split_v:
            return abs(pos.x() - self._split_px()) <= 8
        return abs(pos.y() - (r.top() + r.height() * self.split_y)) <= 8

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self.space_pan):
            self._pan = (pos, list(self.center))
            self.space_moved = self.space_pan or self.space_moved
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton and self._split_hit(pos):     # 반반 선 우클릭 = 좌우 ↔ 위아래
            self.split_v = not self.split_v
            self._split_tip(pos, True)
            self.update()
            self.splitFlipped.emit(self.split_v)
            return
        if e.button() != Qt.LeftButton:
            return
        r = self._img_rect
        if self.pick_mode and not r.isEmpty() and r.contains(pos):
            self.whitePicked.emit((pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height())
            return
        if self._split_hit(pos):
            self._split_drag = True
            return
        rc = self._rect_corner(pos) if self.titles else None
        if rc is not None:
            self.titlePressed.emit(rc[0]["id"])
            self._tresize = rc
            return
        tt = self._title_hit(pos) if self.titles else None
        if tt is not None:
            self.titlePressed.emit(tt["id"])
            self._tdrag = (tt, pos, float(tt.get("cx", 0.5)), float(tt.get("cy", 0.5)))
            return
        mode, lay = self._hit(e.position())
        if lay is None:
            if self.sel_layer:
                self.layerSelected.emit("")
            if self._crop_mode() and self._out_rect.contains(e.position()):
                self.cropPressed.emit()
                self._drag = ("crop", None, e.position(), self.crop_dx, 0, 0)
            return
        self.layerPressed.emit(lay["id"])
        self._drag = (mode, lay, e.position(), lay["cx"], lay["cy"], lay["scale"])

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._pan is not None:
            p0, c0 = self._pan
            r = self._view_rect()
            if not r.isEmpty():
                self.center = [c0[0] - (pos.x() - p0.x()) / r.width(), c0[1] - (pos.y() - p0.y()) / r.height()]
                self.patch = None
                self.update()
            return
        if self.space_pan:
            self.setCursor(Qt.OpenHandCursor)
            return
        if getattr(self, "_tresize", None) is not None and (e.buttons() & Qt.LeftButton):
            t, opp = self._tresize
            c = self._out_rect
            x0, x1 = sorted((opp.x(), pos.x()))
            y0, y1 = sorted((opp.y(), pos.y()))
            w, h = max(6.0, x1 - x0), max(6.0, y1 - y0)
            t["w"], t["h"] = min(2.0, w / c.width()), min(2.0, h / c.height())
            t["cx"] = ((x0 + x1) / 2 - c.left()) / c.width()
            t["cy"] = ((y0 + y1) / 2 - c.top()) / c.height()
            self.update()
            self.titleChanged.emit()
            return
        if self.titles and self._rect_corner(pos) is not None and not (e.buttons() & Qt.LeftButton):
            self.setCursor(Qt.SizeFDiagCursor)
        if self._tdrag is not None and (e.buttons() & Qt.LeftButton):
            t, p0, cx, cy = self._tdrag
            c = self._out_rect
            t["cx"] = max(0.0, min(1.0, cx + (pos.x() - p0.x()) / c.width()))
            t["cy"] = max(0.0, min(1.0, cy + (pos.y() - p0.y()) / c.height()))
            self.update()
            self.titleChanged.emit()
            return
        if self._split_drag and (e.buttons() & Qt.LeftButton):
            r = self._img_rect
            if self.split_v:
                self.split_x = max(0.02, min(0.98, (pos.x() - r.left()) / max(1.0, r.width())))
            else:
                self.split_y = max(0.02, min(0.98, (pos.y() - r.top()) / max(1.0, r.height())))
            self.update()
            return
        if self.pick_mode:
            self.setCursor(Qt.CrossCursor)
            return
        if self._split_hit(pos):
            self.setCursor(Qt.SplitHCursor if self.split_v else Qt.SplitVCursor)
            self._split_tip(pos, True)
            return
        self._split_tip(pos, False)
        if self._drag and (e.buttons() & Qt.LeftButton):
            mode, lay, p0, cx, cy, sc = self._drag
            c = self._out_rect
            if mode == "crop":
                px = (pos.x() - p0.x()) / max(1.0, self._img_rect.width()) * self.src_w
                self.crop_dx = max(-self.crop_max, min(self.crop_max, cx + px))
                self.update()
                self.cropDragged.emit(self.crop_dx)
                return
            if mode == "move":
                lay["cx"] = max(0.0, min(1.0, cx + (pos.x() - p0.x()) / c.width()))
                lay["cy"] = max(0.0, min(1.0, cy + (pos.y() - p0.y()) / c.height()))
            else:
                ctr = QPointF(c.left() + cx * c.width(), c.top() + cy * c.height())
                d0 = math.hypot(p0.x() - ctr.x(), p0.y() - ctr.y())
                d1 = math.hypot(pos.x() - ctr.x(), pos.y() - ctr.y())
                if d0 > 2:
                    lay["scale"] = max(0.02, min(20.0, sc * d1 / d0))
            self.update()
            self.layerChanged.emit()
            return
        mode, lay = self._hit(pos)
        if mode == "scale":
            r = self._layer_rect(lay, next(w for l, _i, w in self.layers if l is lay))
            diag = (pos.x() < r.center().x()) == (pos.y() < r.center().y())
            self.setCursor(Qt.SizeFDiagCursor if diag else Qt.SizeBDiagCursor)
        elif mode == "move":
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.SizeHorCursor if self._crop_mode() and self._out_rect.contains(pos) else Qt.ArrowCursor)

    def _split_tip(self, pos, on):
        """반반 선 위 = '우클릭 = 상하 반반' 알림(선에서 벗어나면 바로 숨김)."""
        from PySide6.QtWidgets import QToolTip
        if on:
            t = "우클릭 = 상하 반반" if self.split_v else "우클릭 = 좌우 반반"
            QToolTip.showText(self.mapToGlobal(pos.toPoint()) + QPoint(14, 18), t, self)
            self._tip_on = True
        elif getattr(self, "_tip_on", False):
            QToolTip.hideText()
            self._tip_on = False

    def leaveEvent(self, e):
        self._split_tip(None, False)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, _):
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.OpenHandCursor if self.space_pan else Qt.ArrowCursor)
            self.viewChanged.emit()
        self._drag = None
        self._split_drag = False
        self._tdrag = None
        self._tresize = None

    def wheelEvent(self, e):
        """레이어 위에서 휠 = 레이어 크기 ±5%, 그 밖 = 마우스 위치 기준 확대·축소"""
        tt = self._title_hit(e.position()) if self.titles else None
        if tt is not None:                 # 타임라인 글자·이미지 위 휠 = 크기 ±5%
            import time
            now = time.monotonic()
            if now - self._wheel_t > 1.0:
                self.titlePressed.emit(tt["id"])
            self._wheel_t = now
            f = 1.05 if e.angleDelta().y() > 0 else 1 / 1.05
            if tt.get("kind") == "image":
                tt["scale"] = max(0.02, min(20.0, float(tt.get("scale", 1)) * f))
            elif tt.get("kind") == "rect":
                tt["w"] = max(0.01, min(2.0, float(tt.get("w", 0.6)) * f))
                tt["h"] = max(0.01, min(2.0, float(tt.get("h", 0.16)) * f))
            else:
                tt["size"] = int(max(8, min(600, round(float(tt.get("size", 64)) * f))))
            self.update()
            self.titleChanged.emit()
            return
        mode, lay = self._hit(e.position())
        if lay is None:
            if self.img is not None:
                self.zoom_by(1.2 if e.angleDelta().y() > 0 else 1 / 1.2, e.position())
            return
        import time
        now = time.monotonic()
        if now - self._wheel_t > 1.0:
            self.layerPressed.emit(lay["id"])      # 연속 휠은 실행취소 1번
        self._wheel_t = now
        f = 1.05 if e.angleDelta().y() > 0 else 1 / 1.05
        lay["scale"] = max(0.02, min(20.0, lay["scale"] * f))
        self.update()
        self.layerChanged.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0e0e0e"))
        if self.img is None or self.img.isNull():
            self._out_rect = QRectF()
            if self.text and self.loading is None:
                p.setPen(QColor("#9a9a9a"))
                p.drawText(self.rect(), Qt.AlignCenter, self.text)
            self._paint_loading(p)
            return
        r = self._view_rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.smooth or self.zoom > 1)
        p.drawImage(r, self.img)
        if self.patch is not None and self.patch_rect and not self.patch.isNull():     # 확대 영역 고화질
            x, y, w, h = self.patch_rect
            p.drawImage(QRectF(r.left() + x * r.width(), r.top() + y * r.height(), w * r.width(), h * r.height()), self.patch)
        if self.before is not None and not self.before.isNull():      # 반반: 왼쪽(또는 위) = 보정 전
            if self.split_v:
                sx = r.width() * self.split_x
                src = QRectF(0, 0, self.before.width() * self.split_x, self.before.height())
                p.drawImage(QRectF(r.left(), r.top(), sx, r.height()), self.before, src)
                a, b = QPointF(r.left() + sx, r.top()), QPointF(r.left() + sx, r.bottom())
            else:
                sy = r.height() * self.split_y
                src = QRectF(0, 0, self.before.width(), self.before.height() * self.split_y)
                p.drawImage(QRectF(r.left(), r.top(), r.width(), sy), self.before, src)
                a, b = QPointF(r.left(), r.top() + sy), QPointF(r.right(), r.top() + sy)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(a, b)
            p.setPen(QPen(QColor("#1b1b1b"), 2))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse((a + b) / 2, 9, 9)
        # 출력에서 잘리는 영역
        src_aspect = r.width() / r.height()
        self._out_rect = QRectF(r)
        self._img_rect = QRectF(r)
        if abs(src_aspect - self.out_aspect) <= 0.01:
            self._paint_layers(p)
        else:
            if self.out_aspect < src_aspect:
                cw = r.height() * self.out_aspect
                off = self.crop_dx / self.src_w * r.width()          # 세로 크롭 위치 이동
                c = QRectF(r.center().x() - cw / 2 + off, r.top(), cw, r.height())
                masks = [QRectF(r.left(), r.top(), c.left() - r.left(), r.height()),
                         QRectF(c.right(), r.top(), r.right() - c.right(), r.height())]
            else:
                ch = r.width() / self.out_aspect
                c = QRectF(r.left(), r.center().y() - ch / 2, r.width(), ch)
                masks = [QRectF(r.left(), r.top(), r.width(), c.top() - r.top()),
                         QRectF(r.left(), c.bottom(), r.width(), r.bottom() - c.bottom())]
            for m in masks:
                p.fillRect(m, QColor(0, 0, 0, 160))
            p.setPen(QPen(QColor(255, 255, 255, 140), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(c)
            self._out_rect = QRectF(c)
            self._paint_layers(p)
        self._paint_titles(p)
        self._paint_scope(p)
        self._paint_loading(p)

    def set_loading(self, pct):
        """프록시(재생용) 준비 중이면 0~1, 끝나면 None. 정지 화면·보정은 그동안에도 됨."""
        if pct != self.loading:
            self.loading = pct
            self.update()

    def _paint_loading(self, p: QPainter):
        if self.loading is None:
            return
        w, h = 200, 46
        box = QRectF(self.width() / 2 - w / 2, self.height() / 2 - h / 2, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("#e0e0e0"))
        p.drawText(QRectF(box.left(), box.top() + 4, w, 22), Qt.AlignCenter, f"로딩 중 {int(self.loading * 100)}%")
        bar = QRectF(box.left() + 16, box.bottom() - 13, w - 32, 4)
        p.setBrush(QColor("#3a3a3a"))
        p.drawRoundedRect(bar, 2, 2)
        p.setBrush(QColor("#4a8fe0"))
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, self.loading)), bar.height()), 2, 2)

    def _scope_calc(self):
        import numpy as np
        from . import auto
        im = self.img.scaled(320, 180, Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_RGB888)
        a = np.frombuffer(im.constBits(), np.uint8, im.bytesPerLine() * im.height()).reshape(im.height(), im.bytesPerLine())
        a = a[:, :im.width() * 3].reshape(im.height(), im.width(), 3)
        marks = auto.range_marks(a.astype(np.float32) / 255)
        if self.scope == 2:      # 파레이드: 칸마다 (열 80 × 밝기 64) 점 밀도
            cols, bins = 80, 64
            out = np.zeros((bins, cols * 3 + 4, 4), np.uint8)
            xi = (np.arange(a.shape[1]) * cols // a.shape[1])
            for c, rgb in enumerate(((229, 72, 77), (95, 209, 122), (74, 143, 224))):
                v = (a[:, :, c].astype(np.int32) * bins // 256)
                h = np.zeros((bins, cols), np.float32)
                np.add.at(h, (bins - 1 - v.reshape(-1), np.tile(xi, a.shape[0])), 1)
                al = np.clip(np.sqrt(h / max(1.0, np.percentile(h[h > 0], 95) if (h > 0).any() else 1)) * 255, 0, 255)
                x0 = c * (cols + 2)
                out[:, x0:x0 + cols, 0], out[:, x0:x0 + cols, 1], out[:, x0:x0 + cols, 2] = rgb[2], rgb[1], rgb[0]
                out[:, x0:x0 + cols, 3] = al.astype(np.uint8)
            qi = QImage(out.tobytes(), out.shape[1], bins, out.shape[1] * 4, QImage.Format_ARGB32).copy()
            return ("parade", qi, marks)
        hs = [np.histogram(a[:, :, c], bins=64, range=(0, 256))[0].astype(float) for c in range(3)]
        m = max(1.0, max(h[1:-1].max() for h in hs))
        return ("hist", [np.minimum(1.0, h / m) for h in hs], marks)

    def _paint_scope(self, p: QPainter):
        """RGB 그래프(오른쪽 위). 목표선 5%·95%(점선), 끝에 붙어 뭉개지면 빨강 점 · 목표선까지 못 가면 파랑 점."""
        if not self.scope or self.img is None or self.img.isNull():
            return
        if self._scope_data is None or self._scope_data[0] != ("parade" if self.scope == 2 else "hist"):
            self._scope_data = self._scope_calc()
        kind, data, marks = self._scope_data
        box = self._scope_box()
        p.fillRect(box, QColor(10, 10, 10, 215))
        p.setPen(QPen(QColor(70, 70, 70), 1))
        p.setBrush(Qt.NoBrush)          # 반반 손잡이가 남긴 흰 붓으로 칠해지지 않게
        p.drawRect(box)
        from PySide6.QtGui import QPolygonF
        inner = box.adjusted(3, 3, -3, -3)
        guide = QPen(QColor(255, 255, 255, 90), 1, Qt.DashLine)
        dot = {"over": QColor("#e5484d"), "short": QColor("#4a8fe0")}
        p.setRenderHint(QPainter.Antialiasing, True)
        if kind == "parade":
            p.drawImage(inner, data)
            pw = inner.width() / 3
            for c in range(3):
                x0 = inner.left() + c * pw
                p.setPen(guide)
                for frac in (0.05, 0.95):
                    y = inner.bottom() - frac * inner.height()
                    p.drawLine(QPointF(x0 + 1, y), QPointF(x0 + pw - 2, y))
                top, bot = marks[c]
                p.setPen(Qt.NoPen)
                for st, y in ((top, inner.top() + 3), (bot, inner.bottom() - 3)):
                    if st:
                        p.setBrush(dot[st])
                        p.drawEllipse(QPointF(x0 + pw / 2, y), 3, 3)
        else:
            p.setPen(guide)
            for frac in (0.05, 0.95):
                x = inner.left() + frac * inner.width()
                p.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
            for hist, col in zip(data, ("#e5484d", "#5fd17a", "#4a8fe0")):
                pts = [QPointF(inner.left() + i / 63 * inner.width(), inner.bottom() - v * (inner.height() - 4)) for i, v in enumerate(hist)]
                p.setPen(QPen(QColor(col), 1.5))
                p.drawPolyline(QPolygonF(pts))
            # 겹침: 세 채널 중 가장 나쁜 것 하나(뭉개짐 우선)
            p.setPen(Qt.NoPen)
            for i, x in ((0, inner.right() - 4), (1, inner.left() + 4)):
                sts = [m[i] for m in marks]
                st = "over" if "over" in sts else "short" if "short" in sts else ""
                if st:
                    p.setBrush(dot[st])
                    p.drawEllipse(QPointF(x, inner.bottom() - 4), 3, 3)
        p.setRenderHint(QPainter.Antialiasing, False)

    def _paint_layers(self, p: QPainter):
        """이미지 레이어(보정 없음, 투명 그대로). 출력 화면 밖은 잘림. 선택한 레이어는 테두리·모서리."""
        if not self.layers:
            return
        c = self._out_rect
        p.save()
        p.setClipRect(c)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for lay, img, wh in self.layers:
            p.drawImage(self._layer_rect(lay, wh), img)
        p.restore()
        for lay, _img, wh in self.layers:
            if lay["id"] != self.sel_layer or self.playing:
                continue
            r = self._layer_rect(lay, wh)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff"))
            for pt in self._corners(r):
                p.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))


class Player(QWidget):
    frameChanged = Signal(int)
    playingChanged = Signal(bool)

    SPEED = 2.0     # J/L 배속 고정

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.mon = Monitor()
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.mon)

        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_video_frame)
        self.audio = None
        if not os.environ.get("DTME_NO_AUDIO"):   # 테스트 환경(사운드 장치 없음)용
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.6)
            self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._on_pos)
        self.player.mediaStatusChanged.connect(self._on_status)

        self.fps = Fraction(60000, 1001)
        self.frames = 0
        self._frame = 0
        self.proxy = ""
        self.has_media = False
        self._pending_seek: int | None = None
        self.rate = 1.0
        self._back = QTimer(self)
        self.playingChanged.connect(self._mon_playing)
        self.player.playbackStateChanged.connect(self._mon_playing)
        self._back.setInterval(50)
        self._back.timeout.connect(self._back_tick)
        self._grab_busy = False
        self._grab_want: int | None = None
        self._token = 0                 # 소스가 바뀌면 증가 → 이전 소스의 늦은 결과 무시
        self.overlay_frame: int | None = None
        self.mon.set_text("영상 추가")

    # ---------------------------------------------------------------- 표시
    def show_image(self, pix: QPixmap | QImage):
        if not self.is_busy():
            self.mon.set_image(pix.toImage() if isinstance(pix, QPixmap) else pix)

    def set_aspect(self, aspect: float):
        self.mon.set_aspect(aspect)

    def _on_video_frame(self, vf):
        if self.is_playing() and vf.isValid():
            img = vf.toImage()
            if not img.isNull():
                self.mon.set_image(img, smooth=False)

    # ---------------------------------------------------------------- 로드
    def set_source(self, fps: Fraction, frames: int, proxy: str | None, frame: int = 0):
        """분석만 끝났으면 proxy=None (정지화면 모드)."""
        self.stop_all()
        self._token += 1
        self.fps, self.frames = fps, frames
        self._frame = max(0, min(frames - 1, frame)) if frames else 0
        self.proxy = proxy or ""
        self.has_media = bool(proxy)
        self.overlay_frame = None
        self.mon.set_text("로딩 중…")
        if proxy:
            self._pending_seek = self._frame
            self.player.setSource(QUrl.fromLocalFile(proxy))
            self._grab(self._frame)
        else:
            self.player.setSource(QUrl())
        self.frameChanged.emit(self._frame)

    def clear(self, text: str):
        self.stop_all()
        self._token += 1
        self.player.setSource(QUrl())
        self.has_media = False
        self.proxy = ""
        self.frames = 0
        self.mon.set_text(text)

    def _on_status(self, st):
        if st in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._pending_seek is not None:
            f = self._pending_seek
            self._pending_seek = None
            self.player.setPosition(self._ms(f))

    # ---------------------------------------------------------------- 프록시 프레임
    def _from_cache(self, frame: int, smooth: bool) -> bool:
        """RAM 캐시에 있으면 바로 표시(ffmpeg 안 띄움). 없으면 그 구간부터 채우도록 요청."""
        fc = framecache.cache()
        fc.request(self.proxy, self.fps, self.frames, frame)
        e = fc.get(self.proxy, frame)
        if e is None:
            return False
        if self.overlay_frame != frame:
            self.mon.set_image(framecache.qimage(e), smooth=smooth)
        return True

    def _grab(self, frame: int, force=False):
        if not self.proxy:
            return
        if self._from_cache(frame, smooth=not self._back.isActive()):
            return
        if self._grab_busy:
            self._grab_want = frame
            return
        self._grab_busy = True
        proxy, fps, tok = self.proxy, self.fps, self._token
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))
        job.signals.done.connect(lambda data, f=frame, t=tok: self._on_grab(f, t, data))
        job.signals.error.connect(lambda _m: self._grab_done())
        jobs.submit(jobs.GRAB_POOL, job)

    def _on_grab(self, frame, tok, data):
        if tok == self._token and frame == self._frame and not self.is_playing() \
                and self.overlay_frame != frame:
            img = QImage.fromData(data, "BMP")
            if not img.isNull():
                self.mon.set_image(img, smooth=not self._back.isActive())
        self._grab_done()

    def _grab_done(self):
        self._grab_busy = False
        if self._grab_want is not None:
            f = self._grab_want
            self._grab_want = None
            if f == self._frame:
                self._grab(f)

    # ---------------------------------------------------------------- 위치
    def _ms(self, frame: int) -> int:
        return int((Fraction(frame) + Fraction(1, 2)) / self.fps * 1000)

    def _on_pos(self, ms: int):
        if self.is_playing():
            f = min(self.frames - 1, int(math.floor(Fraction(ms, 1000) * self.fps)))
            if f != self._frame:
                self._frame = max(0, f)
                self.frameChanged.emit(self._frame)

    @property
    def frame(self) -> int:
        return self._frame

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlayingState

    def _mon_playing(self, *_a):
        on = self.is_busy()
        if self.mon.playing != on:
            self.mon.playing = on
            self.mon.update()

    def is_busy(self) -> bool:
        return self.is_playing() or self._back.isActive()

    def seek(self, frame: int):
        if not self.frames:
            return
        frame = max(0, min(self.frames - 1, int(frame)))
        self._frame = frame
        self.overlay_frame = None
        if self.has_media:
            self.player.setPosition(self._ms(frame))
            if not self.is_playing():
                self._grab(frame)
        self.frameChanged.emit(frame)

    def step(self, d: int):
        self.pause()
        self.seek(self._frame + d)

    # ---------------------------------------------------------------- 재생
    def toggle(self) -> bool:
        if self.is_busy():
            self.pause()
            return True
        return self.play(1.0)

    def play(self, rate: float = 1.0) -> bool:
        if not self.has_media:
            return False
        self._back.stop()
        self.rate = rate
        self.overlay_frame = None
        self.player.setPlaybackRate(rate)
        if self.audio:
            self.audio.setMuted(rate != 1.0)
        self.player.play()
        self.playingChanged.emit(True)
        return True

    def forward(self) -> bool:  # L: 2배속 (다시 누르면 정지)
        if self.is_playing() and self.rate == self.SPEED:
            self.pause()
            return True
        return self.play(self.SPEED)

    def backward(self) -> bool:  # J: 2배속 역재생 (다시 누르면 정지)
        if not self.has_media:
            return False
        if self._back.isActive():
            self.pause()
            return True
        if self.is_playing():
            self.player.pause()
        self.overlay_frame = None
        self._back.start()
        self.playingChanged.emit(True)
        return True

    def _back_tick(self):
        step = max(1, round(float(self.fps) * 0.05 * self.SPEED))
        if self._frame <= 0:
            self.pause()
            return
        self._frame = max(0, self._frame - step)
        self.frameChanged.emit(self._frame)
        if self._from_cache(self._frame, smooth=False):
            return
        if self._grab_busy:
            self._grab_want = self._frame
        else:
            self._grab_back(self._frame)

    def _grab_back(self, frame):
        if self._from_cache(frame, smooth=False):
            return
        self._grab_busy = True
        proxy, fps, tok = self.proxy, self.fps, self._token
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))

        def done(data):
            if tok == self._token and not self.is_playing() and frame == self._frame:
                img = QImage.fromData(data, "BMP")
                if not img.isNull():
                    self.mon.set_image(img, smooth=False)
            self._grab_busy = False
            if self._grab_want is not None:
                f = self._grab_want
                self._grab_want = None
                (self._grab_back if self._back.isActive() else self._grab)(f)

        job.signals.done.connect(done)
        job.signals.error.connect(lambda _m: setattr(self, "_grab_busy", False))
        jobs.submit(jobs.GRAB_POOL, job)

    def pause(self):
        was = self.is_busy()
        self._back.stop()
        if self.is_playing():
            self.player.pause()
        if was:
            self.seek(self._frame)
            self.playingChanged.emit(False)

    def stop_all(self):
        self._back.stop()
        self.player.stop()
