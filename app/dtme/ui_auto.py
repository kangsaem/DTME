"""AUTO 창 · 보정 탭 프리셋 창 · [샘플] 저장 창.

공통 부품(PresetGrid): [모두 자동] / 줄마다 [자동](장면 고정·피사체 자동) + 피사체 4 / 기타(블루워터·야간) / 강도 / 세부 정보.
AUTO 창: 왼쪽 클립 목록(체크·C·프리셋·인식·◆·출력, 분석 진행 = 줄 배경) · 오른쪽 프리셋·강도·출력·이름·세부 정보 ·
오른쪽 맨 위 [기존 보정 유지|무시] [키프레임 유지|자동] · 아래 진행 막대 · [취소][샘플][보정만][보정+렌더].
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QProgressBar, QPushButton,
                               QSlider, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import auto, ff, jobs
from .project import (OUTPUTS, Segment, display_name, has_clip_grade, get_setting, grade_at, list_presets, load_preset, set_setting,
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
LIGHT_BTN = ("QPushButton{color:#111; background:#c9c9c9; border:1px solid #dcdcdc; border-radius:3px; font-weight:700;}"
             "QPushButton:hover{background:#d6d6d6;} QPushButton:disabled{background:#6a6a6a; color:#bbb;}")
ORANGE_BTN = ("QPushButton{color:white; background:#d9822b; border:none; border-radius:3px; font-weight:700;}"
              "QPushButton:hover{background:#e8964a;} QPushButton:disabled{background:#7a4a1a; color:#ddd;}")
ON_BTN = (f"QPushButton{{background:#2e2e2e;}} QPushButton:checked{{background:{SEL_BLUE}; border:1px solid {EDGE_BLUE}; color:#fff;}}")
AUTO_BTN = ("QPushButton{border:1px dashed #666; color:#bbb; background:#2e2e2e;}"
            f"QPushButton:checked{{border:1px solid {YELLOW}; color:{YELLOW}; background:#3a3420;}}")
SEG_BTN = ON_BTN              # [a|b] 도 격자 버튼과 같은 모양(떨어진 둥근 버튼, 켜짐 = 파랑)
MAIN_W, MAIN_H = 88, 32
OUT_SHORT = {"horizontal": "1080", "horizontal1440": "1440", "horizontal2160": "4K", "vertical": "세로"}
VALUE_ROWS = [("r_gain", "빨강", "{:.2f}"), ("b_gain", "파랑", "{:.2f}"), ("hue", "색조", "{:.1f}°"), ("sat", "채도", "{:.2f}"),
              ("water", "물빛", "{:+.0f}°"), ("gy", "녹황 빼기", "{:.0f}"), ("curve", "명암 S", ""),
              ("nr_chroma", "색 노이즈", "{:.0f}"), ("nr_luma", "밝기 노이즈", "{:.0f}"), ("wnr", "물 노이즈", "{:.0f}")]


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
    """커브의 S 세기(표시용, 0~10 정도): 어두운 쪽 1/4 포인트가 0.25 에서 얼마나 내려갔는지(×100)."""
    pts = sorted(curve or [])
    q = [y for x, y in pts[1:-1] if 0.1 <= y <= 0.4]
    return max(0, int(round((0.25 - q[0]) * 100))) if q else 0


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
    """'auto' | 프리셋 키(옛 키도 됨) → (scene, None)."""
    if not choice or choice == "auto":
        return None, None
    return auto.normalize_key(choice) or None, None


# ------------------------------------------------------------------ 공통 부품
class Seg(QWidget):
    """[a|b|c] 하나만 켜짐."""
    changed = Signal(str)

    def __init__(self, opts, cur=None, height=30, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
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
    """[프리셋 자동] / [라이트][산호][얕은 수심] / [깊은 수심][블루워터][야간]. chosen('auto'|키), hovered(키 또는 '')."""
    chosen = Signal(str)
    hovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(5)
        g.setVerticalSpacing(5)
        self.btns: dict[str, QPushButton] = {}
        g.addWidget(self._btn("auto", "프리셋 자동", ON_BTN, 30, tip="클립마다 프리셋을 자동 인식으로"), 0, 0, 1, 3)   # 고르기(실행 아님)
        for i, (k, name) in enumerate(auto.SCENES):
            g.addWidget(self._btn(k, name, ON_BTN, 30), 1 + i // 3, i % 3)
        for c in range(3):
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
        if key in auto.SCENE_NAME:
            self.detail.show_values(auto.preset_label(key), auto.builtin_grade(key, self.base, self.strength.value()))
        elif key:
            self.detail.show_values("프리셋 자동" if key == "auto" else "", None)
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
        self.choice = choice          # 'auto' | 프리셋 키
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
        if src and has_clip_grade(src):
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
            has_c = has_clip_grade(s)
            rec = s.auto or {}
            choice = auto.normalize_key(rec.get("preset", "")) if rec.get("by") == "user" else "auto"
            bad = state.status.get(s.id) in ("읽기 오류", "원본 없음")
            self.rows.append(AutoRow(s, not bad and not (keep == "keep" and has_c), choice or "auto",
                                     s.out or p.output.orientation))
        self.jobs = []
        self.waiting = None              # 'start' | 'sample' (분석 끝나길 기다리는 중)
        self.busy = False

        # 왼쪽 목록
        self.list = QListWidget()
        self.list.setItemDelegate(AutoDelegate(self))
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        self._top_opts = QHBoxLayout()           # [기존 보정 유지|무시] [키프레임 유지|자동] — [프리셋 자동] 위 (사용자 2026-11-06)
        self._top_opts.setSpacing(5)
        right.addLayout(self._top_opts)
        right.addWidget(self.grid)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        right.addWidget(line)
        right.addLayout(labeled("강도", self.strength))
        right.addLayout(labeled("출력", self.out))
        right.addLayout(labeled("이름", nrow))
        self.lens_s = self._slider(st.get("lens", 0))     # 렌즈 보정·흔들림 보정 0~100 — 체크된 클립 모두에(사용자 2026-11-06)
        self.stab_s = self._slider(st.get("stab", 0))
        right.addLayout(labeled("렌즈 보정", self.lens_s.box))
        right.addLayout(labeled("흔들림 보정", self.stab_s.box))
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
        self.keep = Seg([("keep", "기존 보정 유지"), ("drop", "기존 보정 무시")], keep)
        self.keep.changed.connect(self._keep)
        self.keys = Seg([("keep", "키프레임 유지"), ("auto", "키프레임 자동")], keys)
        self.keys.changed.connect(lambda _k: self.list.viewport().update())
        self.mode = after if after in ("render", "each") else "render"   # [보정만] = each, [보정+렌더] = render
        self.b_cancel = main_button("취소")
        self.b_cancel.clicked.connect(self.cancel)
        self.b_sample = main_button("샘플", ORANGE_BTN)
        self.b_sample.clicked.connect(self.sampleRequested.emit)
        self.b_each = main_button("보정만", LIGHT_BTN)
        self.b_each.setToolTip("클립에 값을 넣고 개별 보정(반반 보기)")
        self.b_each.clicked.connect(lambda: self._go("each"))
        self.b_start = main_button("보정+렌더", RED_BTN)
        self.b_start.setToolTip("클립에 값을 넣고 바로 렌더")
        self.b_start.clicked.connect(lambda: self._go("render"))
        # 기존 보정·키프레임 = 오른쪽 맨 위, 아래 줄 = 오른쪽 버튼 4개
        self._top_opts.addWidget(self.keep)
        self._top_opts.addStretch(1)
        self._top_opts.addWidget(self.keys)
        for sgm in (self.keep, self.keys):
            for b in sgm.btns.values():
                b.setMinimumWidth(100)
        rb = QHBoxLayout()
        rb.setSpacing(8)
        rb.addStretch(1)
        for b in (self.b_cancel, self.b_sample, self.b_each, self.b_start):
            rb.addWidget(b)
        rbw = QWidget()
        rbw.setLayout(rb)
        rbw.setFixedWidth(470)
        rb.setContentsMargins(0, 0, 0, 0)
        r1 = QHBoxLayout()
        r1.setSpacing(16)
        r1.addStretch(1)
        r1.addWidget(rbw)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addLayout(mid, 1)
        lay.addSpacing(4)
        lay.addWidget(self.bar)
        lay.addSpacing(4)
        lay.addLayout(r1)
        self.resize(1040, 720)
        self._name_preview()
        if self.list.count():
            self.list.setCurrentRow(0)
        state.sourceStatus.connect(self._src_status)      # 영상을 막 넣었으면 로딩이 끝나는 대로 분석
        QTimer.singleShot(0, self.analyze_all)

    def _slider(self, v):
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        sl.setValue(int(v or 0))
        sl.setFocusPolicy(Qt.NoFocus)
        val = QLabel()
        val.setFixedWidth(30)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box = QHBoxLayout()
        box.setSpacing(8)
        box.addWidget(sl, 1)
        box.addWidget(val)
        sl.box = box

        def show(x, lab=val):
            lab.setText(str(x))
        show(sl.value())
        sl.valueChanged.connect(show)
        sl.sliderReleased.connect(self._lens_stab)
        sl.valueChanged.connect(lambda _x, s_=sl: None if s_.isSliderDown() else self._lens_stab())
        return sl

    def _lens_stab(self):
        for r in self.rows:
            if r.result:
                r.result["grade"]["lens"] = self.lens_s.value()
                r.result["grade"]["stab"] = self.stab_s.value()
        self._show_detail()

    def _src_status(self, sid):
        if any(r.sid == sid for r in self.rows):
            self.list.viewport().update()
            s = self.state.project.source(sid)
            if s is not None and s.frames:              # 정보만 읽으면 바로(프록시는 재생용이라 기다리지 않음)
                self.analyze_all()

    def loading(self, r) -> str:
        """로딩 중이면 표시 글자(프록시 n%), 아니면 ''."""
        st = self.state.status.get(r.sid, "")
        if st in ("읽기 오류", "원본 없음"):
            return st
        s = self.state.project.source(r.sid)
        if st == "준비" or (s is not None and s.frames):    # 분석은 원본에서 → 프록시(재생용)를 기다리지 않음
            return ""
        pct = self.state.proxy_pct.get(r.sid, 0.0)
        return f"로딩 중 {int(pct * 100)}%" if pct > 0 else "로딩 중"

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
        elif fixed:
            label = auto.preset_label(row.choice)
        else:
            label = "자동"
        sub = []
        ld = self.loading(row)
        if ld and row.result is None:
            sub.append(ld)
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
        if key in auto.SCENE_NAME:
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
            if s and has_clip_grade(s) and s.frames:
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
        r.result["grade"]["lens"] = self.lens_s.value()
        r.result["grade"]["stab"] = self.stab_s.value()
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
                ff.log_error("AUTO 분석", msg)
                if msg != "취소됨" and not getattr(r, "retried", False):
                    r.retried, r.prog = True, 0.0
                    QTimer.singleShot(800, self.analyze_all)
                    return
                r.error, r.prog = msg, 1.0
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
        """아직 결과가 없는 체크된 줄(로딩 중 포함). 읽기 오류는 제외."""
        return [r for r in self.rows if r.checked and r.result is None and not r.error
                and self.state.status.get(r.sid) not in ("읽기 오류", "원본 없음", "프록시 오류")]

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

    def _go(self, mode):
        self.mode = mode
        self.startRequested.emit()

    def settings(self):
        return {"strength": self.strength.value(), "keep": self.keep.value(), "keys": self.keys.value(),
                "after": self.mode, "lens": self.lens_s.value(), "stab": self.stab_s.value()}

    def chosen_rows(self):
        return [r for r in self.rows if r.checked and r.result]

    def set_busy(self, on, color=None):
        self.busy = on
        for w in (self.grid, self.strength, self.out, self.name, self.keep, self.keys, self.b_sample, self.lens_s, self.stab_s,
                  self.b_each, self.b_start, self.list):
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
