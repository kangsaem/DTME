"""AUTO 창 · 보정 탭 프리셋 창 · [샘플] 저장 창.

공통 부품(PresetGrid): [모두 자동] / 줄마다 [자동](장면 고정·피사체 자동) + 피사체 4 / 기타(블루워터·야간) / 강도 / 세부 정보.
AUTO 창: 왼쪽 클립 목록(체크·C·프리셋·인식·◆·출력, 분석 진행 = 줄 배경) · 오른쪽 프리셋·강도·출력·이름·세부 정보 ·
아래 진행 막대 · 기존 값 [기존 보정 유지|무시] [키프레임 유지|자동] · 이후 [바로 렌더|개별 보정] · [취소][샘플][시작].
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QProgressBar, QPushButton,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import auto, ff, jobs
from .project import (OUTPUTS, Segment, display_name, get_setting, grade_at, list_presets, load_preset, set_setting,
                      short_name)

# ------------------------------------------------------------------ 색·모양 (DTME 공통)
LIST_BG = "#6b6b6b"          # 목록 바(준비됨)
LIST_DIM = "#3c3c3c"         # 준비 전 · 제외
SEL_BLUE = "#2f4f78"         # 선택·켜짐
EDGE_BLUE = "#4a8fe0"
AUTO_FILL = "#5d7896"        # 분석 진행(줄 배경)
REND_FILL = "#8a5a54"        # 렌더 진행(줄 배경)
YELLOW = "#f2c94c"
SUB = "#c4cad1"              # 자동 인식 글자(흐린 흰색)
RED_BTN = ("QPushButton{color:white; background:#c0392b; border:none; border-radius:3px; font-weight:700;}"
           "QPushButton:hover{background:#d64535;} QPushButton:disabled{background:#7a2a22; color:#ddd;}")
ORANGE_BTN = ("QPushButton{color:white; background:#d9822b; border:none; border-radius:3px; font-weight:700;}"
              "QPushButton:hover{background:#e8964a;} QPushButton:disabled{background:#7a4a1a; color:#ddd;}")
ON_BTN = (f"QPushButton{{background:#2e2e2e;}} QPushButton:checked{{background:{SEL_BLUE}; border:1px solid {EDGE_BLUE}; color:#fff;}}")
AUTO_BTN = ("QPushButton{border:1px dashed #666; color:#bbb; background:#2e2e2e;}"
            f"QPushButton:checked{{border:1px solid {YELLOW}; color:{YELLOW}; background:#3a3420;}}")
SEG_BTN = (f"QPushButton{{border-radius:0; background:#2a2a2a; border:1px solid #555;}}"
           f"QPushButton:checked{{background:{SEL_BLUE}; color:#fff;}}")
MAIN_W, MAIN_H = 88, 32
OUT_SHORT = {"horizontal": "1080", "horizontal1440": "1440", "horizontal2160": "4K", "vertical": "세로"}
VALUE_ROWS = [("r_gain", "빨강", "{:.2f}"), ("b_gain", "파랑", "{:.2f}"), ("hue", "색조", "{:.1f}°"), ("sat", "채도", "{:.2f}"),
              ("water", "물빛", "{:+.0f}°"), ("gy", "녹황", "{:.0f}"), ("curve", "명암 S", ""), ("dehaze", "디헤이즈", "{:.0f}"),
              ("nr_chroma", "색 노이즈", "{:.0f}"), ("nr_luma", "밝기 노이즈", "{:.0f}")]


def main_button(text, style=None, w=MAIN_W):
    from .ui_render import add_shadow
    b = QPushButton(text)
    b.setFixedSize(w, MAIN_H)
    b.setFocusPolicy(Qt.NoFocus)
    if style:
        b.setStyleSheet(style)
        add_shadow(b)
    return b


def curve_s(curve) -> int:
    """커브의 S 세기(표시용, 0~10): 1/4 지점이 얼마나 내려갔는지."""
    pts = sorted(curve or [])
    if len(pts) < 4:
        return 0
    from .ui_curve import natural_spline
    sp = natural_spline(pts, 256)
    lo, hi = pts[1][0], pts[-2][0]
    x = lo + (hi - lo) * 0.25
    y = min(sp, key=lambda p: abs(p[0] - x))[1]
    return max(0, int(round((0.25 - y) * 100)))


def preset_name(rec: dict) -> str:
    """소스 auto 기록 → 표시 이름. user:이름 = 사용자 프리셋."""
    k = (rec or {}).get("preset", "")
    return k[5:] if k.startswith("user:") else auto.preset_label(k)


def short_preset(rec: dict) -> str:
    k = (rec or {}).get("preset", "")
    return k[5:] if k.startswith("user:") else auto.preset_label(k, short=True)


# ------------------------------------------------------------------ 분석 결과 기억(샘플은 클립·LUT 별로 한 번만)
_samples: dict = {}


def _skey(src, lut):
    a, b = src.io
    return f"{src.path}|{a}|{b}|{lut}"


def cached_samples(src, lut):
    return _samples.get(_skey(src, lut))


def grab_job(src, lut, gpu, on_done, on_error=None, on_progress=None, pool=None) -> jobs.Job:
    """샘플 추출(백그라운드). 이미 있으면 바로 on_done."""
    k = _skey(src, lut)
    if k in _samples:
        QTimer.singleShot(0, lambda: on_done(_samples[k]))
        return None
    job = jobs.Job(lambda prog, cancel: auto.grab_samples(src, lut, gpu, cancel=cancel, on_progress=prog), with_progress=True)

    def done(r):
        _samples[k] = r
        on_done(r)
    job.signals.done.connect(done)
    if on_error:
        job.signals.error.connect(on_error)
    if on_progress:
        job.signals.progress.connect(on_progress)
    jobs.submit(pool or jobs.AUTO_POOL, job)
    return job


def choice_args(choice: str):
    """'auto' | 'scene:shallow' | 'shallow/coral' | 'bluewater' → (scene, subject)."""
    if not choice or choice == "auto":
        return None, None
    if choice.startswith("scene:"):
        return choice[6:], None
    sc, sb = auto.split_key(choice)
    return sc, (sb if sc in auto.SUBJECT_SCENES else None)


# ------------------------------------------------------------------ 공통 부품
class Seg(QWidget):
    """[a|b|c] 하나만 켜짐."""
    changed = Signal(str)

    def __init__(self, opts, cur=None, height=28, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.btns = {}
        for k, t in opts:
            b = QPushButton(t)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(height)
            b.setStyleSheet(SEG_BTN)
            self.group.addButton(b)
            self.btns[k] = b
            lay.addWidget(b, 1)
            b.clicked.connect(lambda _=False, k=k: self.changed.emit(k))
        if cur in self.btns:
            self.btns[cur].setChecked(True)

    def value(self):
        return next((k for k, b in self.btns.items() if b.isChecked()), None)

    def set_value(self, k):
        if k in self.btns:
            self.btns[k].setChecked(True)


class DetailBox(QFrame):
    """세부 정보: 제목 + 값 10개(2열)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:#1c1c1c; border:1px solid #333; border-radius:3px;} QLabel{border:none; background:transparent;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)
        self.title = QLabel("")
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        v.addWidget(self.title)
        g = QGridLayout()
        g.setHorizontalSpacing(22)
        g.setVerticalSpacing(3)
        self.vals = {}
        for i, (k, name, _f) in enumerate(VALUE_ROWS):
            r, c = i // 2, (i % 2) * 2
            n = QLabel(name)
            n.setStyleSheet("color:#aaa;")
            val = QLabel("")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            g.addWidget(n, r, c)
            g.addWidget(val, r, c + 1)
            self.vals[k] = val
        v.addLayout(g)
        self.show_values("", None)

    def show_values(self, title, g):
        self.title.setText(title or "")
        for k, name, fmt in VALUE_ROWS:
            if not g:
                self.vals[k].setText("")
            elif k == "curve":
                self.vals[k].setText(str(curve_s(g.get("curve"))))
            else:
                self.vals[k].setText(fmt.format(float(g.get(k, 0))))


class PresetGrid(QWidget):
    """[모두 자동] / 라이트·얕은·깊은 [자동] + 피사체 4 / 기타. chosen('auto'|'scene:x'|키), hovered(키 또는 '')."""
    chosen = Signal(str)
    hovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(5)
        g.setVerticalSpacing(5)
        self.btns: dict[str, QPushButton] = {}
        b = self._btn("auto", "모두 자동", ON_BTN, 32)
        f = b.font()
        f.setBold(True)
        b.setFont(f)
        g.addWidget(b, 0, 1, 1, 5)
        for r, sc in enumerate(auto.SUBJECT_SCENES, start=1):
            lab = QLabel(auto.SCENE_NAME[sc])
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            g.addWidget(lab, r, 0)
            g.addWidget(self._btn(f"scene:{sc}", "자동", AUTO_BTN, 30, tip=f"{auto.SCENE_NAME[sc]} · 피사체 자동"), r, 1)
            for c, (sb, name) in enumerate(auto.SUBJECTS, start=2):
                g.addWidget(self._btn(f"{sc}/{sb}", name, ON_BTN, 30), r, c)
        lab = QLabel("기타")
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        r = len(auto.SUBJECT_SCENES) + 1
        g.addWidget(lab, r, 0)
        g.addWidget(self._btn("bluewater", "블루워터", ON_BTN, 30), r, 2, 1, 2)
        g.addWidget(self._btn("night", "야간", ON_BTN, 30), r, 4, 1, 2)
        g.setColumnMinimumWidth(0, 70)
        g.setColumnMinimumWidth(1, 52)
        for c in range(2, 6):
            g.setColumnStretch(c, 1)

    def _btn(self, key, text, style, h, tip=""):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setFocusPolicy(Qt.NoFocus)
        b.setFixedHeight(h)
        b.setMinimumWidth(40)
        b.setStyleSheet(style)
        if tip:
            b.setToolTip(tip)
        b.setProperty("key", key)
        b.clicked.connect(lambda _=False, k=key: (self.set_current(k), self.chosen.emit(k)))
        b.installEventFilter(self)
        self.btns[key] = b
        return b

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Enter:
            self.hovered.emit(obj.property("key"))
        elif e.type() == QEvent.Leave:
            self.hovered.emit("")
        return False

    def set_current(self, key):
        for k, b in self.btns.items():
            b.setChecked(k == key)


def labeled(text, w, lw=76):
    row = QHBoxLayout()
    row.setSpacing(5)
    lab = QLabel(text)
    lab.setFixedWidth(lw)
    lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    row.addWidget(lab)
    if isinstance(w, QWidget):
        row.addWidget(w, 1)
    else:
        row.addLayout(w, 1)
    return row


# ------------------------------------------------------------------ 보정 탭 프리셋 창
class PresetDialog(QDialog):
    """누르면 바로 적용하고 닫힘. picked('auto'|'scene:x'|키|'user:이름'|'base', 강도)."""
    picked = Signal(str, str)

    def __init__(self, base: dict, current: str = "", strength: str = "mid", parent=None):
        super().__init__(parent, Qt.Popup)
        self.base = base
        self.setStyleSheet("PresetDialog{background:#262626; border:1px solid #555;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        self.grid = PresetGrid()
        self.grid.set_current(current)
        v.addWidget(self.grid)
        v.addWidget(self._line())
        self.strength = Seg([("weak", "약"), ("mid", "중"), ("strong", "강")], strength)
        self.strength.changed.connect(lambda _k: self._hover(self._last_hover))
        v.addLayout(labeled("강도", self.strength))
        self.detail = DetailBox()
        dl = QHBoxLayout()
        dl.addSpacing(81)
        dl.addWidget(self.detail, 1)
        v.addLayout(dl)
        v.addWidget(self._line())
        ul = QHBoxLayout()
        ul.setSpacing(5)
        ul.addSpacing(81)
        self.user_box = ul
        for name in ["기본값"] + list_presets():
            b = QPushButton(name)
            b.setFixedHeight(28)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCheckable(True)
            b.setStyleSheet(ON_BTN)
            b.setChecked(current == ("base" if name == "기본값" else f"user:{name}"))
            key = "base" if name == "기본값" else f"user:{name}"
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            if key != "base":
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pos, n=name, bb=b: self.userMenu.emit(n, bb.mapToGlobal(pos)))
            ul.addWidget(b)
        ul.addStretch(1)
        v.addLayout(ul)
        self.setFixedWidth(540)
        self._last_hover = ""
        self.grid.chosen.connect(self._pick)
        self.grid.hovered.connect(self._hover)
        self._hover("")

    userMenu = Signal(str, object)

    def _line(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#3a3a3a;")
        return f

    def _hover(self, key):
        self._last_hover = key
        if key and "/" in key or key in ("bluewater", "night"):
            self.detail.show_values(auto.preset_label(key), auto.builtin_grade(key, self.base, self.strength.value()))
        elif key:
            self.detail.show_values("모두 자동" if key == "auto" else f"{auto.SCENE_NAME.get(key[6:], '')} · 자동", None)
        else:
            self.detail.show_values("", None)

    def _pick(self, key):
        self.picked.emit(key, self.strength.value() or "mid")
        self.accept()


# ------------------------------------------------------------------ AUTO 창 클립 목록
class AutoRow:
    def __init__(self, src, checked, choice, out):
        self.sid = src.id
        self.checked = checked
        self.choice = choice          # 'auto' | 'scene:x' | 키
        self.out = out
        self.prog = 0.0               # 분석 진행 0~1
        self.result = None            # 이 클립에 들어갈 값(recommend)
        self.rec = None               # 인식(자동) 결과 키
        self.error = ""


class AutoDelegate(QStyledItemDelegate):
    def __init__(self, dlg):
        super().__init__(dlg)
        self.dlg = dlg

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 32)

    def paint(self, p: QPainter, option, index):
        row: AutoRow = self.dlg.rows[index.row()]
        src = self.dlg.state.project.source(row.sid)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        sel = bool(option.state & QStyle.State_Selected)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SEL_BLUE if sel else LIST_BG if row.checked else LIST_DIM))
        p.drawRoundedRect(r, 3, 3)
        if 0 < row.prog < 1:
            pr = QRectF(r)
            pr.setWidth(r.width() * row.prog)
            p.setBrush(QColor(AUTO_FILL))
            p.drawRoundedRect(pr, 3, 3)
        # 체크
        cb = QRectF(r.left() + 8, r.center().y() - 7, 14, 14)
        p.setPen(QPen(QColor("#888"), 1))
        p.setBrush(QColor(EDGE_BLUE) if row.checked else Qt.NoBrush)
        p.drawRoundedRect(cb, 2, 2)
        if row.checked:
            p.setPen(QPen(QColor("#fff"), 2))
            p.drawLine(cb.left() + 3, cb.center().y(), cb.left() + 6, cb.bottom() - 3)
            p.drawLine(cb.left() + 6, cb.bottom() - 3, cb.right() - 3, cb.top() + 3)
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#fff" if row.checked else "#8a8a8a"))
        x = cb.right() + 8
        p.drawText(QRectF(x, r.top(), 78, r.height()), Qt.AlignVCenter | Qt.AlignLeft, display_name(src.path) if src else "")
        x += 80
        if src and (src.grade or src.gkeys):
            p.setPen(QColor(YELLOW))
            p.drawText(QRectF(x, r.top(), 12, r.height()), Qt.AlignVCenter, "C")
        x += 16
        f.setBold(False)
        p.setFont(f)
        label, fixed, sub = self.dlg.row_text(row)
        fm = p.fontMetrics()
        chip_w = 38
        avail = r.right() - chip_w - 12 - x
        p.setPen(QColor("#fff" if fixed else SUB))
        lw = min(fm.horizontalAdvance(label), int(avail))
        p.drawText(QRectF(x, r.top(), lw + 2, r.height()), Qt.AlignVCenter, fm.elidedText(label, Qt.ElideRight, int(avail)))
        x += lw + 10
        if sub and x < r.right() - chip_w - 20:
            f2 = QFont(f)
            f2.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            p.setFont(f2)
            p.setPen(QColor(SUB))
            p.drawText(QRectF(x, r.top(), r.right() - chip_w - 12 - x, r.height()), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(sub, Qt.ElideRight, int(r.right() - chip_w - 12 - x)))
            p.setFont(f)
        chip = QRectF(r.right() - chip_w - 6, r.center().y() - 9, chip_w, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2a2a"))
        p.drawRoundedRect(chip, 2, 2)
        p.setPen(QColor("#fff"))
        f2 = QFont(f)
        f2.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f2)
        p.drawText(chip, Qt.AlignCenter, OUT_SHORT.get(row.out, "1080"))
        p.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.position().x() < option.rect.left() + 32:
            row = self.dlg.rows[index.row()]
            row.checked = not row.checked
            self.dlg.list.viewport().update()
            self.dlg._row_changed()
            return True
        return False


class AutoDialog(QDialog):
    """AUTO 창. start(이후 'render'|'each') 와 샘플은 EditTab 이 받아 처리(저장폴더·적용·렌더)."""
    startRequested = Signal()
    sampleRequested = Signal()
    rowProgress = Signal(str, float)        # 메인 소스 목록 줄 배경(분석 진행)

    def __init__(self, state, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.state = state
        self.setModal(True)
        self.setObjectName("AutoDialog")
        self.setStyleSheet("#AutoDialog{background:#262626; border:1px solid #555; border-radius:6px;}")
        p = state.project
        st = get_setting("auto", {}) or {}
        self.strength_v = st.get("strength", "mid")
        keep = st.get("keep", "keep")
        keys = st.get("keys", "keep")
        after = st.get("after", "render")
        self.rows: list[AutoRow] = []
        for s in p.sources:
            has_c = bool(s.grade or s.gkeys)
            rec = s.auto or {}
            choice = rec.get("preset", "") if rec.get("by") == "user" and not rec.get("preset", "").startswith("user:") else "auto"
            self.rows.append(AutoRow(s, s.frames > 0 and not (keep == "keep" and has_c), choice or "auto",
                                     s.out or p.output.orientation))
        self.jobs = []
        self.waiting = None              # 'start' | 'sample' (분석 끝나길 기다리는 중)
        self.busy = False

        # 왼쪽 목록
        self.list = QListWidget()
        self.list.setItemDelegate(AutoDelegate(self))
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setStyleSheet("QListWidget{background:#1e1e1e; border:1px solid #333; border-radius:3px; padding:4px;}")
        for s in p.sources:
            it = QListWidgetItem(display_name(s.path))
            self.list.addItem(it)
        self.list.itemSelectionChanged.connect(self._sel_changed)
        # 오른쪽
        self.grid = PresetGrid()
        self.grid.chosen.connect(self._choose)
        self.grid.hovered.connect(self._hover)
        self.strength = Seg([("weak", "약"), ("mid", "중"), ("strong", "강")], self.strength_v)
        self.strength.changed.connect(self._strength)
        self.out = Seg([(k, OUT_SHORT[k]) for k, _ in OUTPUTS], p.output.orientation)
        self.out.changed.connect(self._out)
        self.name = QLineEdit(p.output.prefix or "DTME")
        self.name.setFixedWidth(160)
        self.name.setFixedHeight(28)
        self.name.textChanged.connect(self._name_preview)
        self.name_eg = QLabel("")
        self.name_eg.setStyleSheet(f"color:{SUB}; font-family:Consolas,monospace;")
        nrow = QHBoxLayout()
        nrow.setSpacing(8)
        nrow.addWidget(self.name)
        nrow.addWidget(self.name_eg, 1)
        self.detail = DetailBox()
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self.grid)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        right.addWidget(line)
        right.addLayout(labeled("강도", self.strength))
        right.addLayout(labeled("출력", self.out))
        right.addLayout(labeled("이름", nrow))
        right.addStretch(1)
        dl = QHBoxLayout()
        dl.addSpacing(81)
        dl.addWidget(self.detail, 1)
        right.addLayout(dl)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(470)
        mid = QHBoxLayout()
        mid.setSpacing(16)
        mid.addWidget(self.list, 1)
        mid.addWidget(rw)
        # 아래
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.set_bar_color(EDGE_BLUE)
        self.keep = Seg([("keep", "기존 보정 유지"), ("drop", "기존 보정 무시")], keep, 32)
        self.keep.changed.connect(self._keep)
        self.keys = Seg([("keep", "키프레임 유지"), ("auto", "키프레임 자동")], keys, 32)
        self.keys.changed.connect(lambda _k: self.list.viewport().update())
        self.after = Seg([("render", "자동 보정 후 바로 렌더"), ("each", "자동 보정 후 개별 보정")], after, 32)
        for sgm in (self.keep, self.keys, self.after):
            for b in sgm.btns.values():
                b.setMinimumWidth(130)
        r1 = QHBoxLayout()
        r1.setSpacing(10)
        r1.addWidget(self._lab("기존 값"))
        r1.addWidget(self.keep)
        r1.addSpacing(6)
        r1.addWidget(self.keys)
        r1.addStretch(1)
        self.b_cancel = main_button("취소")
        self.b_cancel.clicked.connect(self.cancel)
        self.b_sample = main_button("샘플", ORANGE_BTN)
        self.b_sample.clicked.connect(self.sampleRequested.emit)
        self.b_start = main_button("시작", RED_BTN)
        self.b_start.clicked.connect(self.startRequested.emit)
        r2 = QHBoxLayout()
        r2.setSpacing(10)
        r2.addWidget(self._lab("이후"))
        r2.addWidget(self.after)
        r2.addStretch(1)
        for b in (self.b_cancel, self.b_sample, self.b_start):
            r2.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addLayout(mid, 1)
        lay.addSpacing(4)
        lay.addWidget(self.bar)
        lay.addSpacing(4)
        lay.addLayout(r1)
        lay.addLayout(r2)
        self.resize(1040, 720)
        self._name_preview()
        if self.list.count():
            self.list.setCurrentRow(0)
        QTimer.singleShot(0, self.analyze_all)

    def _lab(self, t):
        lab = QLabel(t)
        lab.setFixedWidth(52)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lab

    def set_bar_color(self, col):
        self.bar.setStyleSheet(f"QProgressBar{{background:#2a2a2a; border:none; border-radius:3px;}}"
                               f"QProgressBar::chunk{{background:{col}; border-radius:3px;}}")

    # ---------------------------------------------------------------- 표시
    def row_text(self, row: AutoRow):
        """(프리셋 글자, 직접 지정 여부, 작은 회색 글씨)."""
        fixed = row.choice != "auto"
        if row.result:
            label = auto.preset_label(row.result["preset"])
        elif row.choice.startswith("scene:"):
            label = f"{auto.SCENE_NAME[row.choice[6:]]} · 자동"
        elif fixed:
            label = auto.preset_label(row.choice)
        else:
            label = "자동"
        sub = []
        if row.error:
            sub.append("분석 실패")
        if fixed and row.rec and row.result and row.rec != row.result["preset"]:
            sub.append(f"인식: {auto.preset_label(row.rec)}")
        if row.result and row.result["gkeys"] and self.keys.value() == "auto":
            sub.append(f"◆{len(next(iter(row.result['gkeys'].values())))}")
        return label, fixed, "  ".join(sub)

    def _name_preview(self, *_):
        first = next((self.state.project.source(r.sid) for r in self.rows if r.checked), None)
        pre = self.name.text().strip() or "DTME"
        self.name_eg.setText(f"{pre}_{short_name(first.path) if first else ''}.mp4")

    def _sel_rows(self):
        idx = sorted({i.row() for i in self.list.selectedIndexes()})
        return [self.rows[i] for i in idx]

    def _current(self):
        i = self.list.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def _sel_changed(self):
        r = self._current()
        if r:
            self.grid.set_current(r.choice)
            self.out.set_value(r.out)
        self._show_detail()

    def _show_detail(self):
        r = self._current()
        if r and r.result:
            self.detail.show_values(auto.preset_label(r.result["preset"]), r.result["grade"])
        else:
            self.detail.show_values("", None)

    def _hover(self, key):
        if key and ("/" in key or key in ("bluewater", "night")):
            self.detail.show_values(auto.preset_label(key), auto.builtin_grade(key, self.state.project.grade, self.strength.value()))
        else:
            self._show_detail()

    # ---------------------------------------------------------------- 선택
    def _targets(self):
        return self._sel_rows() or self.rows

    def _choose(self, key):
        rows = self.rows if key == "auto" else self._targets()
        for r in rows:
            r.choice = key
            self._compute(r)
        self.list.viewport().update()
        self._show_detail()

    def _strength(self, _k):
        for r in self.rows:
            self._compute(r)
        self.list.viewport().update()
        self._show_detail()

    def _out(self, k):
        for r in self._targets():
            r.out = k
        self.list.viewport().update()

    def _keep(self, k):
        for r in self.rows:
            s = self.state.project.source(r.sid)
            if s and (s.grade or s.gkeys) and s.frames:
                r.checked = k != "keep"
        self.list.viewport().update()
        self._row_changed()

    def _row_changed(self):
        self._name_preview()
        self.analyze_all()

    # ---------------------------------------------------------------- 분석
    def _compute(self, r: AutoRow):
        s = self.state.project.source(r.sid)
        smp = cached_samples(s, self.state.project.grade_for_source(s.id).get("lut", "")) if s else None
        if not smp:
            return
        base = dict(self.state.project.grade)
        base.update({k: v for k, v in s.grade.items() if k in ("lut", "sharpen", "lens")})
        sc, sb = choice_args(r.choice)
        r.result = auto.recommend(smp, base, sc, sb, self.strength.value() or "mid")
        r.rec = auto.recommend(smp, base)["preset"]

    def analyze_all(self):
        p = self.state.project
        for i, r in enumerate(self.rows):
            s = p.source(r.sid)
            if not r.checked or s is None or not s.frames or r.result is not None or r.prog > 0 or r.error:
                continue
            lut = p.grade_for_source(s.id).get("lut", "")
            r.prog = 0.01

            def done(_smp, r=r):
                r.prog = 1.0
                self.rowProgress.emit(r.sid, 1.0)
                self._compute(r)
                self.list.viewport().update()
                self._show_detail()
                self._progress()

            def err(msg, r=r):
                r.error, r.prog = msg, 1.0
                ff.log_error("AUTO 분석", msg)
                self.list.viewport().update()
                self._progress()

            def prog(v, r=r):
                r.prog = max(0.01, min(0.99, v))
                self.rowProgress.emit(r.sid, r.prog)
                self.list.viewport().update()
                self._progress()
            j = grab_job(s, lut, p.output.gpu_decode, done, err, prog)
            if j:
                self.jobs.append(j)
        self._progress()

    def pending(self):
        return [r for r in self.rows if r.checked and r.result is None and not r.error]

    def _progress(self):
        rows = [r for r in self.rows if r.checked]
        if not self.busy:
            self.set_bar_color(EDGE_BLUE)
            self.bar.setValue(int(100 * sum(min(1.0, r.prog) for r in rows) / max(1, len(rows))))
        if self.waiting and not self.pending():
            w, self.waiting = self.waiting, None
            (self.startRequested if w == "start" else self.sampleRequested).emit()

    def wait_then(self, what):
        """분석이 덜 끝났으면 끝난 뒤 다시 실행."""
        if self.pending():
            self.waiting = what
            self.analyze_all()
            return True
        return False

    def settings(self):
        return {"strength": self.strength.value(), "keep": self.keep.value(), "keys": self.keys.value(),
                "after": self.after.value()}

    def chosen_rows(self):
        return [r for r in self.rows if r.checked and r.result]

    def set_busy(self, on, color=None):
        self.busy = on
        for w in (self.grid, self.strength, self.out, self.name, self.keep, self.keys, self.after, self.b_sample,
                  self.b_start, self.list):
            w.setEnabled(not on)
        if color:
            self.set_bar_color(color)

    def cancel(self):
        for j in self.jobs:
            j.cancel.set()
            jobs.AUTO_POOL.tryTake(j)
        self.waiting = None
        try:
            set_setting("auto", self.settings())
        except Exception:  # noqa: BLE001
            pass
        self.reject()


# ------------------------------------------------------------------ [샘플] 저장 창
SAMPLE_SIZES = [(1280, "1280"), (1920, "1920"), (2560, "2560"), (3840, "4K")]
SAMPLE_FMTS = [("png8", "PNG 8bit"), ("png16", "PNG 16bit"), ("jpg", "JPG")]
N_SAMPLE = 6


def sample_name(cfg: dict, src, k: int, preset: str = "") -> str:
    parts = [cfg.get("name", "").strip() or "DTME"]
    att = cfg.get("attach", ["date", "num"])
    if "date" in att:
        parts.append(short_name(src.path))
    if "preset" in att and preset:
        parts.append(preset.replace(" · ", "_").replace(" ", ""))
    if "num" in att:
        parts.append(str(k))
    ext = "jpg" if cfg.get("fmt") == "jpg" else "png"
    return "_".join(parts) + f".{ext}"


class SampleDialog(QDialog):
    def __init__(self, name: str, folder: str, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("SampleDialog")
        self.setStyleSheet("#SampleDialog{background:#262626; border:1px solid #555; border-radius:6px;}")
        self.setModal(True)
        cfg = dict(get_setting("sample_export", {}) or {})
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        self.folder = QLineEdit(folder)
        self.folder.setFixedHeight(28)
        b = QPushButton("선택…")
        b.setFixedHeight(28)
        b.clicked.connect(self._pick)
        fr = QHBoxLayout()
        fr.setSpacing(6)
        fr.addWidget(self.folder, 1)
        fr.addWidget(b)
        v.addLayout(labeled("저장폴더", fr))
        self.size = Seg([(str(k), t) for k, t in SAMPLE_SIZES], str(cfg.get("size", 1920)))
        v.addLayout(labeled("크기", self.size))
        self.fmt = Seg(SAMPLE_FMTS, cfg.get("fmt", "png8"))
        self.fmt.changed.connect(self._eg)
        v.addLayout(labeled("형식", self.fmt))
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        v.addWidget(line)
        self.name = QLineEdit(cfg.get("name") or name or "DTME")
        self.name.setFixedSize(180, 28)
        self.name.textChanged.connect(self._eg)
        nr = QHBoxLayout()
        nr.addWidget(self.name)
        nr.addStretch(1)
        v.addLayout(labeled("이름", nr))
        ar = QHBoxLayout()
        ar.setSpacing(6)
        self.att = {}
        for k, t in (("date", "날짜시간"), ("preset", "프리셋"), ("num", "번호")):
            bt = QPushButton(t)
            bt.setCheckable(True)
            bt.setFixedHeight(28)
            bt.setStyleSheet(ON_BTN)
            bt.setFocusPolicy(Qt.NoFocus)
            bt.setChecked(k in cfg.get("attach", ["date", "num"]))
            bt.toggled.connect(self._eg)
            self.att[k] = bt
            ar.addWidget(bt)
        ar.addStretch(1)
        v.addLayout(labeled("붙이기", ar))
        self.eg = QLabel("")
        self.eg.setStyleSheet(f"color:{SUB}; font-family:Consolas,monospace;")
        v.addLayout(labeled("", self.eg))
        br = QHBoxLayout()
        br.addStretch(1)
        bc = main_button("취소")
        bc.clicked.connect(self.reject)
        bs = main_button("샘플", ORANGE_BTN)
        bs.clicked.connect(self._ok)
        br.addWidget(bc)
        br.addWidget(bs)
        v.addSpacing(6)
        v.addLayout(br)
        self.setFixedWidth(560)
        self._eg()

    def config(self) -> dict:
        return {"size": int(self.size.value() or 1920), "fmt": self.fmt.value() or "png8", "name": self.name.text().strip(),
                "attach": [k for k, b in self.att.items() if b.isChecked()]}

    def _eg(self, *_):
        c = self.config()

        class _S:
            path = "DJI_20261025120700_0001_D.MP4"
        a = sample_name(c, _S, 1, "얕은 수심 · 산호초")
        b = sample_name(c, _S, N_SAMPLE, "얕은 수심 · 산호초")
        self.eg.setText(f"{a} … {b[len(a) - 5:] if 'num' in c['attach'] else ''}" if a != b else a)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "저장폴더", self.folder.text())
        if d:
            self.folder.setText(d)

    def _ok(self):
        if not self.folder.text().strip():
            self._pick()
            if not self.folder.text().strip():
                return
        try:
            set_setting("sample_export", self.config())
        except Exception:  # noqa: BLE001
            pass
        self.accept()


def sample_frames6(src) -> list[int]:
    a, b = src.io
    return [int(a + (k + 0.5) * (b - a) / N_SAMPLE) for k in range(N_SAMPLE)]


_ = (copy, Path, QMenu, Segment, grade_at, load_preset)
