"""글자 설정 창 · 음악 설정 창. 바꾸는 즉시 화면에 반영(창을 열 때 실행취소 지점 1번).
v0.16.19: 제목줄 없는 떠 있는 창(Popup) + [취소][확인]. 확인 = 등록하고 닫기, 취소·Esc = 열기 전으로 되돌림(새 글자는 없앰)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QSlider)

from . import fonts
from .ui_render import Popup

SWATCHES = ["#ffffff", "#ffe28a", "#9fd8ff", "#111111"]
SIZE_MIN, SIZE_MAX = 16, 600          # 글자 크기(1080 화면 기준 px)
RECT_SWATCHES = ["#000000", "#ffffff", "#1f3a5f", "#7a1f1f"]


ANIM_BTNS = (("fade", "페이드"), ("right", "→"), ("left", "←"), ("up", "↑"), ("down", "↓"))


def anim_rows(dlg, grid, row: int, data: dict, all_label: str = ""):
    """들어올 때(인)·나갈 때(아웃): [페이드 | → | ← | ↑ | ↓] 두 줄(v0.16.57). 화살표 = 움직이는 방향. dlg.anim = {'ain': 그룹, 'aout': 그룹}."""
    dlg.anim = {}
    for i, (key, name) in enumerate((("ain", "인"), ("aout", "아웃"))):
        grid.addWidget(QLabel(name), row + i, 0)
        h = QHBoxLayout()
        h.setSpacing(0)
        grp = QButtonGroup(dlg)
        for j, (k, n) in enumerate(ANIM_BTNS):
            b = QPushButton(n)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty("key", k)
            b.setMinimumWidth(34 if k != "fade" else 52)
            b.setChecked(data.get(key, "fade") == k)
            grp.addButton(b, j)
            h.addWidget(b, 1)
        grp.buttonClicked.connect(lambda b, key=key: dlg._set(key, b.property("key")))
        grid.addLayout(h, row + i, 1, 1, 2)
        dlg.anim[key] = grp
    if all_label:                                   # v0.16.67 시안: 인·아웃·길이를 같은 종류 모두에(체크 = 기본 켬)
        from PySide6.QtWidgets import QCheckBox
        dlg.apply_all = QCheckBox(all_label)
        dlg.apply_all.setChecked(True)
        dlg.apply_all.setToolTip("확인을 누르면 이 창의 인 · 아웃 · 길이를 같은 종류(글자 또는 사각형) 모두에 넣음")
        hb = QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(dlg.apply_all)
        grid.addLayout(hb, row + 2, 1, 1, 2)


def _slider(lo, hi, v):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(v)
    s.setFocusPolicy(Qt.NoFocus)
    return s


class _Undoable(Popup):
    """연 때 값 사본 → 취소·Esc 면 그 값으로 되돌림(같은 dict 객체를 고쳐 화면 쪽 참조 그대로)."""
    changed = Signal()

    def __init__(self, data: dict, parent=None):
        super().__init__(parent, floating=True)
        import copy
        self._data, self._snap = data, copy.deepcopy(data)

    def reject(self):
        self._data.clear()
        self._data.update(self._snap)
        self.changed.emit()
        super().reject()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not self.focusWidget().__class__.__name__ == "QPlainTextEdit":
            self.accept()
            return
        super().keyPressEvent(e)              # Esc = 취소


class TextDialog(_Undoable):
    def __init__(self, title: dict, parent=None):
        super().__init__(title, parent)
        self.t = title
        self.setMinimumWidth(340)
        lay = self.body
        self.text = QPlainTextEdit(title.get("text", ""))
        self.text.setFixedHeight(64)
        self.text.textChanged.connect(lambda: self._set("text", self.text.toPlainText()))
        lay.addWidget(self.text)
        fr = QHBoxLayout()
        self.font = QComboBox()
        self.font.setToolTip("글꼴")
        self._fill_fonts()
        self.font.activated.connect(lambda _: self._set("font", self.font.currentText()))
        self.bold = QPushButton("B")
        self.bold.setCheckable(True)
        self.bold.setChecked(bool(title.get("bold")))
        self.bold.setFixedSize(30, 26)
        bf = self.bold.font()
        bf.setBold(True)
        self.bold.setFont(bf)                    # 입체감·켜짐 = 앱 기본(BevelStyle)
        self.bold.toggled.connect(lambda v: self._set("bold", v))
        fr.addWidget(self.font, 1)
        fr.addWidget(self.bold)
        lay.addLayout(fr)
        ar = QHBoxLayout()
        ar.addStretch(1)
        b_add = QPushButton("글꼴 추가…")
        b_add.clicked.connect(self._add_font)
        ar.addWidget(b_add)
        lay.addLayout(ar)
        g = QGridLayout()
        g.addWidget(QLabel("크기"), 0, 0)
        from .ui_grade import ValueEdit
        self.size = _slider(SIZE_MIN, SIZE_MAX, int(title.get("size", 64)))      # v0.16.34: 최대 240 → 600
        self.size_v = ValueEdit()                                            # 숫자 칸 클릭 = 직접 입력(Enter)
        self.size_v.show_value(str(self.size.value()))
        self.size.valueChanged.connect(lambda v: (self.size_v.show_value(str(v)), self._set("size", v)))
        self.size_v.submitted.connect(lambda v: self.size.setValue(int(max(SIZE_MIN, min(SIZE_MAX, round(v))))))
        g.addWidget(self.size, 0, 1)
        g.addWidget(self.size_v, 0, 2)
        g.addWidget(QLabel("색"), 1, 0)
        crow = QHBoxLayout()
        self.sw = []
        for c in SWATCHES:
            b = QPushButton("")
            b.setFixedSize(24, 22)
            b.clicked.connect(lambda _=False, c=c: self._color(c))
            self.sw.append((c, b))
            crow.addWidget(b)
        more = QPushButton("…")
        more.setFixedSize(30, 22)
        more.setToolTip("다른 색")
        more.clicked.connect(self._pick)
        crow.addWidget(more)
        crow.addStretch(1)
        g.addLayout(crow, 1, 1, 1, 2)
        g.addWidget(QLabel("배경"), 2, 0)
        brow = QHBoxLayout()
        brow.setSpacing(0)
        self.bg = QButtonGroup(self)
        for i, (k, n) in enumerate((("none", "없음"), ("shadow", "그림자"), ("band", "띠"))):
            b = QPushButton(n)
            b.setCheckable(True)
            b.setProperty("key", k)
            b.setMinimumWidth(40)
            b.setChecked(title.get("bg", "shadow") == k)
            self.bg.addButton(b, i)
            brow.addWidget(b, 1)
        self.bg.buttonClicked.connect(lambda b: self._set("bg", b.property("key")))
        g.addLayout(brow, 2, 1, 1, 2)
        anim_rows(self, g, 3, title, "모든 글자에 적용")
        g.addWidget(QLabel("길이"), 6, 0)            # 페이드·밀기 길이(예전 이름 '페이드')
        self.fade = _slider(0, 20, int(round(float(title.get("fade", 0.5)) * 10)))
        self.fade_v = QLabel(f"{self.fade.value() / 10:.1f}초")
        self.fade.valueChanged.connect(lambda v: (self.fade_v.setText(f"{v / 10:.1f}초"), self._set("fade", v / 10)))
        g.addWidget(self.fade, 6, 1)
        g.addWidget(self.fade_v, 6, 2)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self._paint_swatches()
        self.add_buttons()

    def _fill_fonts(self):
        self.font.clear()
        for name in fonts.list_fonts():
            self.font.addItem(name)
        i = self.font.findText(self.t.get("font", ""))
        self.font.setCurrentIndex(max(0, i))

    def _add_font(self):
        f, _ = QFileDialog.getOpenFileName(self, "글꼴 추가", "", "글꼴 (*.ttf *.otf *.ttc)")
        if f:
            fam = fonts.add_font(f)
            self._fill_fonts()
            self.font.setCurrentIndex(max(0, self.font.findText(fam)))
            self._set("font", self.font.currentText())

    def _paint_swatches(self):
        cur = (self.t.get("color") or "#ffffff").lower()
        for c, b in self.sw:
            from . import ui_style
            ui_style.tone(b, color=c if len(c) == 7 else "#808080", sel=c == cur)    # 글자 색 칩(입체감 · 고른 색 = 파란 테두리)

    def _color(self, c):
        self._set("color", c)
        self._paint_swatches()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.t.get("color", "#ffffff")), self, "글자색")
        if c.isValid():
            self._color(c.name())

    def _set(self, k, v):
        self.t[k] = v
        self.changed.emit()


class RectDialog(_Undoable):
    """사각형 레이어(v0.16.34): 색 · 불투명도 · 모서리 둥글기 · 페이드. 위치·크기는 모니터에서 끌기(모서리 = 크기)."""

    def __init__(self, rect: dict, parent=None):
        super().__init__(rect, parent)
        self.t = rect
        self.setMinimumWidth(320)
        g = QGridLayout()
        g.addWidget(QLabel("색"), 0, 0)
        crow = QHBoxLayout()
        self.sw = []
        for c in RECT_SWATCHES:
            b = QPushButton("")
            b.setFixedSize(24, 22)
            b.clicked.connect(lambda _=False, c=c: self._color(c))
            self.sw.append((c, b))
            crow.addWidget(b)
        more = QPushButton("…")
        more.setFixedSize(30, 22)
        more.setToolTip("다른 색")
        more.clicked.connect(self._pick)
        crow.addWidget(more)
        crow.addStretch(1)
        g.addLayout(crow, 0, 1, 1, 2)
        rows = (("불투명도", "opacity", 0, 100, 100, "%"), ("둥글기", "radius", 0, 80, 1, ""),
                ("테두리", "border", 0, 30, 1, ""), ("그림자", "shadow", 0, 60, 1, ""), ("길이", "fade", 0, 20, 10, "초"))   # 테두리 = 두께 · 그림자 = 거리(0 = 없음)
        self.vals = {}
        for i, (name, key, lo, hi, sc, unit) in enumerate(rows, 1):
            g.addWidget(QLabel(name), i, 0)
            sl = _slider(lo, hi, int(round(float(rect.get(key, 0)) * sc)))
            lab = QLabel()
            lab.setMinimumWidth(40)

            def show(v, lab=lab, sc=sc, unit=unit, key=key):
                lab.setText(f"{v / sc:.1f}{unit}" if key == "fade" else f"{v}{unit}")
            show(sl.value())
            sl.valueChanged.connect(lambda v, key=key, sc=sc, show=show: (show(v), self._set(key, v / sc if sc != 1 else v)))
            g.addWidget(sl, i, 1)
            g.addWidget(lab, i, 2)
            self.vals[key] = sl
        n = len(rows) + 1
        g.addWidget(QLabel("테두리 색"), n, 0)                 # v0.16.59
        brow = QHBoxLayout()
        self.bsw = []
        for c in ("#ffffff", "#000000", "#ffe28a", "#9fd8ff"):
            b = QPushButton("")
            b.setFixedSize(24, 22)
            b.clicked.connect(lambda _=False, c=c: self._bcolor(c))
            self.bsw.append((c, b))
            brow.addWidget(b)
        bmore = QPushButton("…")
        bmore.setFixedSize(30, 22)
        bmore.setToolTip("다른 색")
        bmore.clicked.connect(self._bpick)
        brow.addWidget(bmore)
        brow.addStretch(1)
        g.addLayout(brow, n, 1, 1, 2)
        anim_rows(self, g, n + 1, rect, "모든 사각형에 적용")
        g.setColumnStretch(1, 1)
        self.body.addLayout(g)
        self._paint_swatches()
        self.add_buttons()

    def _paint_swatches(self):
        from . import ui_style
        cur = (self.t.get("color") or "#000000").lower()
        for c, b in self.sw:
            ui_style.tone(b, color=c, sel=c == cur)
        bcur = (self.t.get("bcolor") or "#ffffff").lower()
        for c, b in self.bsw:
            ui_style.tone(b, color=c, sel=c == bcur)

    def _bcolor(self, c):
        self._set("bcolor", c)
        self._paint_swatches()

    def _bpick(self):
        c = QColorDialog.getColor(QColor(self.t.get("bcolor", "#ffffff")), self, "테두리 색")
        if c.isValid():
            self._bcolor(c.name())

    def _color(self, c):
        self._set("color", c)
        self._paint_swatches()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.t.get("color", "#000000")), self, "사각형 색")
        if c.isValid():
            self._color(c.name())

    def _set(self, k, v):
        self.t[k] = v
        self.changed.emit()


class ImageDialog(_Undoable):
    """타임라인 이미지(v0.16.57): 들어올 때·나갈 때 · 길이. 위치·크기는 모니터에서."""

    def __init__(self, title: dict, parent=None):
        super().__init__(title, parent)
        self.t = title
        self.setMinimumWidth(320)
        g = QGridLayout()
        anim_rows(self, g, 0, title)
        g.addWidget(QLabel("길이"), 2, 0)
        self.fade = _slider(0, 20, int(round(float(title.get("fade", 0.5)) * 10)))
        self.fade_v = QLabel(f"{self.fade.value() / 10:.1f}초")
        self.fade_v.setMinimumWidth(40)
        self.fade.valueChanged.connect(lambda v: (self.fade_v.setText(f"{v / 10:.1f}초"), self._set("fade", v / 10)))
        g.addWidget(self.fade, 2, 1)
        g.addWidget(self.fade_v, 2, 2)
        g.setColumnStretch(1, 1)
        self.body.addLayout(g)
        self.add_buttons()

    def _set(self, k, v):
        self.t[k] = v
        self.changed.emit()


class MusicDialog(_Undoable):
    """음악 볼륨 · 원본 볼륨(자동 = 음악 없으면 100, 있으면 0) · 페이드인/아웃. 전체 길이에 1개씩."""

    def __init__(self, mix: dict, parent=None):
        super().__init__(mix, parent)
        self.mix = mix
        self.setMinimumWidth(340)
        g = QGridLayout()
        self.body.addLayout(g)
        rows = [("음악 볼륨", "music", 0, 200, 100, "%"), ("원본 볼륨", "orig", 0, 200, 100, "%"),
                ("페이드인", "fin", 0, 50, 10, "초"), ("페이드아웃", "fout", 0, 80, 10, "초"), ("곡 사이 겹침", "xfade", 0, 80, 10, "초"),
                ("키운 컷 원본", "up_orig", 0, 200, 100, "%"), ("키운 컷 음악", "up_music", 0, 100, 100, "%")]     # v0.16.66 말소리·수면 위 컷
        self.labels = {}
        for r, (name, k, lo, hi, sc, unit) in enumerate(rows):
            g.addWidget(QLabel(name), r, 0)
            v = mix.get(k)
            cur = 0 if (k == "orig" and v is None) else float(v if v is not None else {"xfade": 2.0, "up_orig": 1.0, "up_music": 0.3}.get(k, 0))
            s = _slider(lo, hi, int(round(cur * sc)))
            lab = QLabel()
            lab.setMinimumWidth(48)
            self.labels[k] = (lab, sc, unit)
            s.valueChanged.connect(lambda val, k=k, sc=sc: self._set(k, val / sc))
            g.addWidget(s, r, 1)
            g.addWidget(lab, r, 2)
            self._label(k)
        self.auto = QPushButton("원본 자동")
        self.auto.setCheckable(True)
        self.auto.setChecked(mix.get("orig") is None)
        self.auto.setToolTip("음악이 없으면 원본 100%, 있으면 0%")
        # 켜짐 = 앱 기본(파랑) — 예전 노란 켜짐 통일(v0.16.5)
        self.auto.toggled.connect(self._auto)
        g.addWidget(self.auto, len(rows), 1, 1, 2, Qt.AlignRight)
        g.setColumnStretch(1, 1)
        self.add_buttons()

    def _label(self, k):
        lab, sc, unit = self.labels[k]
        v = self.mix.get(k, {"xfade": 2.0, "up_orig": 1.0, "up_music": 0.3}.get(k))
        if k == "orig" and v is None:
            lab.setText("자동")
        elif unit == "%":
            lab.setText(f"{float(v) * 100:.0f}%")
        else:
            lab.setText(f"{float(v):.1f}초")

    def _set(self, k, v):
        self.mix[k] = v
        if k == "orig":
            self.auto.blockSignals(True)
            self.auto.setChecked(False)
            self.auto.blockSignals(False)
        self._label(k)
        self.changed.emit()

    def _auto(self, on):
        if on:
            self.mix["orig"] = None
        else:
            self.mix["orig"] = 1.0
        self._label("orig")
        self.changed.emit()
