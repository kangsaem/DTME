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
        self.size = _slider(16, 240, int(title.get("size", 64)))
        self.size_v = QLabel(str(self.size.value()))
        self.size.valueChanged.connect(lambda v: (self.size_v.setText(str(v)), self._set("size", v)))
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
        g.addWidget(QLabel("페이드"), 3, 0)
        self.fade = _slider(0, 20, int(round(float(title.get("fade", 0.5)) * 10)))
        self.fade_v = QLabel(f"{self.fade.value() / 10:.1f}초")
        self.fade.valueChanged.connect(lambda v: (self.fade_v.setText(f"{v / 10:.1f}초"), self._set("fade", v / 10)))
        g.addWidget(self.fade, 3, 1)
        g.addWidget(self.fade_v, 3, 2)
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


class MusicDialog(_Undoable):
    """음악 볼륨 · 원본 볼륨(자동 = 음악 없으면 100, 있으면 0) · 페이드인/아웃. 전체 길이에 1개씩."""

    def __init__(self, mix: dict, parent=None):
        super().__init__(mix, parent)
        self.mix = mix
        self.setMinimumWidth(340)
        g = QGridLayout()
        self.body.addLayout(g)
        rows = [("음악 볼륨", "music", 0, 200, 100, "%"), ("원본 볼륨", "orig", 0, 200, 100, "%"),
                ("페이드인", "fin", 0, 50, 10, "초"), ("페이드아웃", "fout", 0, 80, 10, "초")]
        self.labels = {}
        for r, (name, k, lo, hi, sc, unit) in enumerate(rows):
            g.addWidget(QLabel(name), r, 0)
            v = mix.get(k)
            cur = 0 if (k == "orig" and v is None) else float(v if v is not None else 0)
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
        v = self.mix.get(k)
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
