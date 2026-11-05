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

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import ff, jobs


class Monitor(QWidget):
    """layerPressed(id) = 레이어를 잡기 직전(실행취소 지점), layerChanged = 위치·크기 바뀜, layerSelected(id 또는 '')."""
    layerPressed = Signal(str)
    layerChanged = Signal()
    layerSelected = Signal(str)
    cropPressed = Signal()
    cropDragged = Signal(float)        # 세로 크롭 이동량(원본 px)
    whitePicked = Signal(float, float)   # 흰색 찍기: 영상 안 위치(0~1)
    viewChanged = Signal()               # 확대·이동 바뀜(→ 확대 영역 고화질 다시 만들기)
    titlePressed = Signal(str)           # 타임라인 모드: 글자·이미지를 잡음(실행취소 지점)
    titleChanged = Signal()
    modeRequested = Signal(str)          # "source" | "timeline"

    HANDLE = 9

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img: QImage | None = None
        self.text = ""
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
        self._tdrag = None
        self._build_zoom_ui()
        self._build_mode_ui()
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
            b.setStyleSheet("QPushButton{background:rgba(25,25,25,210); color:#bbb; border:1px solid #555;"
                            "border-radius:0; font-size:11px; padding:0 10px;} QPushButton:checked{background:#2f4f78; color:#fff;}")
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
        if t.get("kind") == "image":
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
            if t["id"] == self.sel_title:
                r = self._title_rect(t, wh)
                p.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)

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
        css = ("QPushButton{background:rgba(25,25,25,210); color:#ddd; border:1px solid #555; border-radius:3px;"
               "font-size:11px; padding:0 6px;}")
        self.b_zm = QPushButton("−")
        self.b_zl = QPushButton("맞춤")
        self.b_zp = QPushButton("+")
        for b, w in ((self.b_zm, 24), (self.b_zl, 52), (self.b_zp, 24)):
            b.setFixedSize(w, 22)
            b.setStyleSheet(css)
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
        if self.zoom > 1.0001:
            self.set_zoom(1.0)

    def set_before(self, img):
        self.before = img
        self.update()

    def set_scope(self, on):
        self.scope = on
        self._scope_data = None
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

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self.space_pan):
            self._pan = (pos, list(self.center))
            self.space_moved = self.space_pan or self.space_moved
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        r = self._img_rect
        if self.pick_mode and not r.isEmpty() and r.contains(pos):
            self.whitePicked.emit((pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height())
            return
        if self.before is not None and not r.isEmpty() and abs(pos.x() - self._split_px()) <= 8:
            self._split_drag = True
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
            self.split_x = max(0.02, min(0.98, (pos.x() - r.left()) / max(1.0, r.width())))
            self.update()
            return
        if self.pick_mode:
            self.setCursor(Qt.CrossCursor)
            return
        if self.before is not None and abs(pos.x() - self._split_px()) <= 8:
            self.setCursor(Qt.SplitHCursor)
            return
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

    def mouseReleaseEvent(self, _):
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.OpenHandCursor if self.space_pan else Qt.ArrowCursor)
            self.viewChanged.emit()
        self._drag = None
        self._split_drag = False
        self._tdrag = None

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
            else:
                tt["size"] = int(max(8, min(400, round(float(tt.get("size", 64)) * f))))
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
            if self.text:
                p.setPen(QColor("#9a9a9a"))
                p.drawText(self.rect(), Qt.AlignCenter, self.text)
            return
        r = self._view_rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.smooth or self.zoom > 1)
        p.drawImage(r, self.img)
        if self.patch is not None and self.patch_rect and not self.patch.isNull():     # 확대 영역 고화질
            x, y, w, h = self.patch_rect
            p.drawImage(QRectF(r.left() + x * r.width(), r.top() + y * r.height(), w * r.width(), h * r.height()), self.patch)
        if self.before is not None and not self.before.isNull():      # 반반: 왼쪽 = 원본
            sx = r.width() * self.split_x
            src = QRectF(0, 0, self.before.width() * self.split_x, self.before.height())
            p.drawImage(QRectF(r.left(), r.top(), sx, r.height()), self.before, src)
            x = r.left() + sx
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QPen(QColor("#1b1b1b"), 2))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(x, r.center().y()), 9, 9)
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

    def _paint_scope(self, p: QPainter):
        """RGB 파형(채널별 밝기 분포). 오른쪽 위 작은 창."""
        if not self.scope or self.img is None or self.img.isNull():
            return
        if self._scope_data is None:
            import numpy as np
            im = self.img.scaled(320, 180, Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_RGB888)
            a = np.frombuffer(im.constBits(), np.uint8, im.bytesPerLine() * im.height()).reshape(im.height(), im.bytesPerLine())
            a = a[:, :im.width() * 3].reshape(im.height(), im.width(), 3)
            hs = [np.histogram(a[:, :, c], bins=64, range=(0, 256))[0].astype(float) for c in range(3)]
            m = max(1.0, max(h[1:-1].max() for h in hs))
            self._scope_data = [np.minimum(1.0, h / m) for h in hs]
        w, h = max(160, self.width() * 0.22), max(84, self.height() * 0.2)
        box = QRectF(self.width() - w - 8, 8, w, h)
        p.fillRect(box, QColor(10, 10, 10, 215))
        p.setPen(QPen(QColor(70, 70, 70), 1))
        p.drawRect(box)
        from PySide6.QtGui import QPolygonF
        for hist, col in zip(self._scope_data, ("#e5484d", "#5fd17a", "#4a8fe0")):
            pts = [QPointF(box.left() + i / 63 * box.width(), box.bottom() - 2 - v * (box.height() - 6)) for i, v in enumerate(hist)]
            p.setPen(QPen(QColor(col), 1.5))
            p.drawPolyline(QPolygonF(pts))

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
            if lay["id"] != self.sel_layer:
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
    def _grab(self, frame: int, force=False):
        if not self.proxy:
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
        if self._grab_busy:
            self._grab_want = self._frame
        else:
            self._grab_back(self._frame)

    def _grab_back(self, frame):
        self._grab_busy = True
        proxy, fps, tok = self.proxy, self.fps, self._token
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))

        def done(data):
            if tok == self._token and not self.is_playing():
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
