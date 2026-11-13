"""AUTO 창 · 보정 탭 프리셋 창 · [샘플] 저장 창.

공통 부품(PresetGrid): [모두 자동] / 줄마다 [자동](장면 고정·피사체 자동) + 피사체 4 / 기타(블루워터·야간) / 강도 / 세부 정보.
AUTO 창: 왼쪽 클립 목록(체크·C·프리셋·인식·◆·출력, 분석 진행 = 줄 배경) · 오른쪽 프리셋·강도·출력·이름·세부 정보 ·
오른쪽 맨 위 [기존 보정 유지|무시] [키프레임 유지|자동] · 아래 진행 막대 · [취소][샘플][보정+편집][보정+렌더].
줄 = MOSCO 모양(진회색, 단계 색으로 차오름, 오른쪽 = 지금 하는 일). 창을 열면 분석만 뒤에서 조용히 미리(표시 없음) → 버튼을 누르면 진행 표시·값 넣기.
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QProgressBar, QPushButton,
                               QSlider, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import auto, ff, jobs, stage as SG, ui_style
from .ui_render import DragMove
from .project import (ROT, ROT_BACK, Segment, clamp_src, is_portrait, out_label, outputs_for, source_out_h, source_vw, auto_lut, display_name, has_clip_grade, get_setting, grade_at, list_presets, load_preset, set_setting,
                      short_name)

# ------------------------------------------------------------------ 색·모양 (DTME 공통)
SEL_BLUE = "#2f4f78"         # 선택·켜짐
EDGE_BLUE = "#4a8fe0"
YELLOW = "#f2c94c"
SUB = "#c4cad1"              # 자동 인식 글자(흐린 흰색)
RED_BTN, LIGHT_BTN, ORANGE_BTN = "red", "light", "orange"    # 버튼 색 이름(ui_style.tone) — 모양은 ui_style 한 곳에서
ON_BTN = ""                   # 일반 버튼 = 앱 기본(입체감 · 켜짐 파랑)
SEG_BTN = ON_BTN              # [a|b] 도 격자 버튼과 같은 모양(떨어진 둥근 버튼, 켜짐 = 파랑)
MAIN_W, MAIN_H = 88, 32
OUT_SHORT = {"horizontal": "1080", "horizontal1440": "1440", "horizontal2160": "4K", "vertical": "인스타",
             "vertical1440": "세로 1440", "vertical2160": "세로 4K"}     # 소스를 모를 때만. 소스가 있으면 project.out_label
OUT_BTNS = [("horizontal", "1080"), ("horizontal1440", "1440"), ("horizontal2160", "4K"), ("vertical", "인스타")]   # v0.16.70 크기 칸
VALUE_ROWS = [("r_gain", "빨강", "{:.2f}"), ("b_gain", "파랑", "{:.2f}"), ("hue", "색조", "{:.1f}°"), ("sat", "채도", "{:.2f}"),
              ("water", "물빛", "{:+.0f}°"), ("gy", "녹황 빼기", "{:.0f}"), ("curve", "명암 S", ""),
              ("nr_chroma", "색 노이즈", "{:.0f}"), ("nr_luma", "밝기 노이즈", "{:.0f}"), ("wnr", "물 노이즈", "{:.0f}")]


def main_button(text, style=None, w=MAIN_W):
    b = QPushButton(text)
    b.setFixedSize(w, MAIN_H)
    b.setFocusPolicy(Qt.NoFocus)
    if style:
        ui_style.tone(b, style)
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
class Grip(QWidget):
    """테두리 없는 창 맨 위 손잡이(점 6개). 누름은 창으로 넘어가 DragMove 가 옮김."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setCursor(Qt.SizeAllCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#6a6a6a"))
        cx, cy = self.width() / 2, self.height() / 2
        for i in range(-2, 3):
            for j in (-2, 2):
                p.drawEllipse(QRectF(cx + i * 7 - 1.5, cy + j - 1.5, 3, 3))
        p.end()


class PresetDialog(DragMove, QDialog):
    """떠 있는 프리셋 창(v0.16.54 = MOSCO v0.7.76·78 방식): 항상 위 · 열면 아무것도 안 골라짐 · 누르면 고르기만 →
    [적용] 을 눌러야 적용(창은 그대로) · 닫기 = ✕ 또는 [프리셋] 다시 누르기뿐(Esc·바깥 클릭 무시) · 고른 클립이 바뀌면 따라감.
    picked('auto'|'scene:x'|키|'user:이름'|'base', 강도) = [적용] 때 1번."""
    picked = Signal(str, str)
    closed = Signal()

    def __init__(self, base: dict, current: str = "", strength: str = "mid", parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.pending = None                       # 고른 것(아직 적용 안 함)
        self.base = base
        self.setModal(False)
        self.setObjectName("PresetDialog")
        self.setStyleSheet("#PresetDialog{background:#262626; border:1px solid #555; border-radius:6px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 4, 16, 16)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.setContentsMargins(20, 0, 0, 0)       # 왼쪽 20 = ✕ 폭(손잡이 점이 가운데 오게)
        top.setSpacing(0)
        top.addWidget(Grip(), 1)                  # 맨 위 손잡이 줄 = 잡고 끌어 옮김(빈 바탕도 됨)
        self.b_x = QPushButton("✕")
        self.b_x.setObjectName("x")
        self.b_x.setFixedSize(20, 20)
        self.b_x.setFocusPolicy(Qt.NoFocus)
        self.b_x.setFlat(True)
        self.b_x.setStyleSheet("#x{background:transparent; border:none; color:#cfcfcf;} #x:hover{background:#c0392b; color:#fff;}")
        self.b_x.clicked.connect(self.close)
        top.addWidget(self.b_x)
        v.addLayout(top)
        self.grid = PresetGrid()
        self.grid.set_current("")
        v.addWidget(self.grid)                    # 왼쪽 여백 = 오른쪽(16), 강도 글자 없음(사용자 2026-11-07)
        v.addWidget(self._line())
        self.strength = Seg([("weak", "약"), ("mid", "중"), ("strong", "강")], strength)
        self.strength.changed.connect(lambda _k: self._hover(self._last_hover))
        v.addWidget(self.strength)
        self.detail = DetailBox()
        v.addWidget(self.detail)
        v.addWidget(self._line())
        ul = QHBoxLayout()
        ul.setSpacing(5)
        self.user_box = ul
        self.user_btns = {}
        for name in ["기본값"] + list_presets():
            b = QPushButton(name)
            b.setFixedHeight(28)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCheckable(True)
            b.setStyleSheet(ON_BTN)
            key = "base" if name == "기본값" else f"user:{name}"
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            if key != "base":
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pos, n=name, bb=b: self.userMenu.emit(n, bb.mapToGlobal(pos)))
            self.user_btns[key] = b
            ul.addWidget(b)
        ul.addStretch(1)
        v.addLayout(ul)
        v.addWidget(self._line())
        bl = QHBoxLayout()
        bl.setSpacing(8)
        self.cur = QLabel("")                    # 지금 클립 · 들어가 있는 프리셋(글자만, 칸은 안 켬)
        self.cur.setStyleSheet("color:#aaa;")
        bl.addWidget(self.cur, 1)
        self.b_apply = QPushButton("적용")
        self.b_apply.setFixedSize(MAIN_W, MAIN_H)
        self.b_apply.setFocusPolicy(Qt.NoFocus)
        ui_style.tone(self.b_apply, "red")
        self.b_apply.setEnabled(False)
        self.b_apply.clicked.connect(self._apply)
        bl.addWidget(self.b_apply)
        v.addLayout(bl)
        self.setFixedWidth(459)                  # 내용 폭 그대로(예전 540 - 왼쪽 81)
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
        """고르기만(적용은 [적용])."""
        self.pending = key
        self.set_current(key)
        self.b_apply.setEnabled(True)

    def _apply(self):
        if self.pending and not self.busy:
            self.picked.emit(self.pending, self.strength.value() or "mid")

    busy = False

    def set_busy(self, on: bool):
        """[프리셋 자동] 분석 중 = [적용] 자리에 '분석 중…'(멈춘 게 아님을 알림, v0.16.58)."""
        self.busy = bool(on)
        self.b_apply.setText("분석 중…" if on else "적용")
        self.b_apply.setEnabled(not on and self.pending is not None)

    def set_current(self, key):
        self.grid.set_current(key)
        for k, b in self.user_btns.items():
            b.setChecked(k == key)

    def set_clip(self, text: str):
        """지금 클립 표시만 바꿈(고른 칸은 그대로)."""
        self.cur.setText(self.cur.fontMetrics().elidedText(text, Qt.ElideRight, 300))

    def reject(self):                             # Esc 로는 안 닫힘(닫기 = ✕ · [프리셋] 다시 누르기)
        pass

    def closeEvent(self, e):
        e.accept()
        self.closed.emit()


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
        """MOSCO 줄: 진회색(체크 해제 = 더 어둡게·회색 이름), 선택 = 파란 테두리, 진행 = 단계 색으로 차오름 + 오른쪽 글자."""
        row: AutoRow = self.dlg.rows[index.row()]
        src = self.dlg.state.project.source(row.sid)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        sel = bool(option.state & QStyle.State_Selected)
        stg = SG.stage_of(self.dlg.state, row.sid) if row.checked or self.dlg.state.status.get(row.sid) in SG.ERRORS else None
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SG.ROW_BG if row.checked else SG.ROW_OFF))
        p.drawRoundedRect(r, 3, 3)
        active = bool(stg and stg[0] in SG.STAGE and stg[1] is not None and 0 < stg[1] < 1)
        if not active and row.checked and row.result and not row.error and not (stg and stg[0] == "error"):
            p.setBrush(QColor(SG.STAGE["analyze"][0]))          # v0.16.27: 분석 끝 = 청록이 끝까지 찬 채로
            p.drawRoundedRect(r, 3, 3)
        if active:
            pr = QRectF(r)
            pr.setWidth(r.width() * stg[1])
            p.setBrush(QColor(SG.STAGE[stg[0]][0]))
            p.drawRoundedRect(pr, 3, 3)
        if sel:
            p.setPen(QPen(QColor(SG.SEL_EDGE), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        # 체크 상자(진한 칸 + 흰 ✓)
        cb = QRectF(r.left() + 8, r.center().y() - 8, 16, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SG.CHK_BG))
        p.drawRoundedRect(cb, 2, 2)
        if row.checked:
            p.setPen(QPen(QColor("#ffffff"), 1.8))
            p.drawLine(cb.left() + 4, cb.center().y(), cb.left() + 7, cb.bottom() - 4)
            p.drawLine(cb.left() + 7, cb.bottom() - 4, cb.right() - 4, cb.top() + 4)
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff" if row.checked else SG.OFF_TXT))
        x = cb.right() + 10
        nm = display_name(src.path) if src else ""
        nw = int(max(78, min(p.fontMetrics().horizontalAdvance(nm) + 4, r.width() * 0.34)))   # v0.16.41: 줄이 넓으면 이름 다 보임(좁으면 …)
        p.drawText(QRectF(x, r.top(), nw, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(nm, Qt.ElideRight, nw - 2))          # 길면 … (C 표시와 겹치지 않게)
        x += nw + 2
        if src and has_clip_grade(src):
            p.setPen(QColor(YELLOW))
            p.drawText(QRectF(x, r.top(), 12, r.height()), Qt.AlignVCenter, "C")
        x += 16
        f.setBold(False)
        p.setFont(f)
        label, fixed, sub = self.dlg.row_text(row)
        fm = p.fontMetrics()
        chip_w = 40
        chip = QRectF(r.right() - chip_w - 4, r.top() + 3, chip_w, r.height() - 6)
        right_end = chip.left() - 10
        p.setPen(QColor(("#ffffff" if fixed else SG.SUB_TXT) if row.checked else SG.OFF_TXT))
        lw = min(fm.horizontalAdvance(label), int(max(0, right_end - x)))
        p.drawText(QRectF(x, r.top(), lw + 2, r.height()), Qt.AlignVCenter, fm.elidedText(label, Qt.ElideRight, lw + 1))
        x += lw + 10
        # 오른쪽: 진행 글자(단계 색) 또는 보조 정보(회색)
        if stg:
            txt, col = stg[2], (SG.ERR_TXT if stg[0] == "error" else SG.STAGE[stg[0]][1])
        else:
            txt, col = (sub if row.checked else ""), SG.SUB_TXT
        if txt and right_end - x > 20:
            p.setPen(QColor(col))
            p.drawText(QRectF(x, r.top(), right_end - x, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                       fm.elidedText(txt, Qt.ElideRight, int(right_end - x)))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SG.CHIP_AUTO))
        p.drawRoundedRect(chip, 2, 2)
        p.setPen(QColor("#ffffff" if row.checked else SG.OFF_TXT))
        f2 = QFont(f)
        f2.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f2)
        p.drawText(chip, Qt.AlignCenter, out_label(row.out, self.dlg.state.project.source(row.sid), short=True))
        p.restore()

    def editorEvent(self, event, model, option, index):
        return False            # v0.16.37 체크 = AutoDialog._check_drag(누른 채 쓸기)


class AutoDialog(DragMove, QDialog):
    """AUTO 창. start(이후 'render'|'each') 와 샘플은 EditTab 이 받아 처리(저장폴더·적용·렌더)."""
    startRequested = Signal()
    sampleRequested = Signal()

    def __init__(self, state, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.state = state
        self.setModal(True)
        self.setObjectName("AutoDialog")
        self.setStyleSheet("#AutoDialog{background:#262626; border:1px solid #555; border-radius:6px;}")
        p = state.project
        st = get_setting("auto", {}) or {}
        self.strength_v = st.get("strength", "mid")
        keep, keys = "drop", "auto"           # 늘 [기존 보정 무시][키프레임 자동]으로 시작(사용자 2026-11-07)
        after = st.get("after", "render")
        self.rows: list[AutoRow] = []
        for s in p.sources:
            has_c = has_clip_grade(s)
            rec = s.auto or {}
            choice = auto.normalize_key(rec.get("preset", "")) if rec.get("by") == "user" else "auto"
            bad = state.status.get(s.id) in ("읽기 오류", "원본 없음")
            self.rows.append(AutoRow(s, not bad and not (keep == "keep" and has_c), choice or "auto",
                                     p.out_of(s)))   # v0.16.32 원본보다 크지 않게 · v0.16.70 세로 촬영 = 돌린 크기
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
        self._cdrag = None                 # v0.16.37 체크 쓸기: (시작 줄, 새 상태, 원래 상태들)
        self._vp = self.list.viewport()          # 필터는 보이는 동안만(showEvent/hideEvent) — 종료 때 지워진 창 호출 방지
        # 오른쪽
        self.grid = PresetGrid()
        self.grid.chosen.connect(self._choose)
        self.grid.hovered.connect(self._hover)
        self.strength = Seg([("weak", "약"), ("mid", "중"), ("strong", "강")], self.strength_v)
        self.strength.changed.connect(self._strength)
        self.out = Seg(OUT_BTNS, ROT_BACK.get(p.output.orientation, p.output.orientation))
        self.out.btns["vertical"].setToolTip("1080×1920 · 릴스·쇼츠·틱톡")
        self.out.changed.connect(self._out)
        self.lut_combo = QComboBox()                # 창 전체에 LUT 하나(사용자 2026-11-06): 자동 = 파일 정보(D-Log M 만 LUT)
        self.lut_combo.setFixedHeight(30)
        self.lut_combo.setFocusPolicy(Qt.NoFocus)
        self.lut_combo.addItem("자동 (파일 정보)", "auto")
        self.lut_combo.addItem("LUT 없음", "")
        for n in ff.list_luts():
            self.lut_combo.addItem(n, n)
        self.lut_combo.setToolTip("자동 = D-Log M 영상만 LUT, 일반·알 수 없음은 LUT 없음")
        i = self.lut_combo.findData(st.get("lut", "auto"))
        self.lut_combo.setCurrentIndex(max(0, i))
        self.lut_combo.currentIndexChanged.connect(self._lut_changed)
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
        right.setContentsMargins(9, 9, 9, 9)       # 아래 버튼 줄 x 맞춤에 씀
        self._top_opts = QHBoxLayout()           # [기존 보정 유지|무시] [키프레임 유지|자동] — [프리셋 자동] 위 (사용자 2026-11-06)
        self._top_opts.setSpacing(5)
        right.addLayout(self._top_opts)
        gl = QHBoxLayout()                        # 프리셋 격자 왼쪽 끝 = 강도 [약] x (사용자 2026-11-07)
        gl.addSpacing(81)
        gl.addWidget(self.grid, 1)
        right.addLayout(gl)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        right.addWidget(line)
        right.addLayout(labeled("강도", self.strength))
        right.addLayout(labeled("출력", self.out))
        right.addLayout(labeled("LUT", self.lut_combo))
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
        self.mode = after if after in ("render", "each") else "render"   # [보정+편집] = each, [보정+렌더] = render
        self.b_cancel = main_button("취소")
        self.b_cancel.clicked.connect(self.cancel)
        self.b_sample = main_button("샘플", ORANGE_BTN)
        self.b_sample.clicked.connect(self._sample_clicked)
        self.b_each = main_button("보정+편집", LIGHT_BTN)
        self.b_each.setToolTip("클립에 값을 넣고 편집 화면에서 개별 보정(반반 보기)")
        self.b_each.clicked.connect(lambda: self._go("each"))
        self.b_start = main_button("보정+렌더", RED_BTN)
        self.b_start.setToolTip("클립에 값을 넣고 바로 렌더")
        self.b_start.clicked.connect(lambda: self._go("render"))
        # 기존 보정·키프레임 = 오른쪽 맨 위, 아래 줄 = 오른쪽 버튼 4개
        self._top_opts.addSpacing(81)             # 왼쪽 끝 = 강도 [약] 버튼 x (라벨 76 + 간격 5)
        self._top_opts.addWidget(self.keep)
        self._top_opts.addSpacing(8)
        self._top_opts.addWidget(self.keys)
        self._top_opts.addStretch(1)
        for sgm in (self.keep, self.keys):
            for b in sgm.btns.values():
                b.setFixedWidth(90)             # 4개 + 간격 = [약] 부터 오른쪽 끝까지
        rb = QHBoxLayout()
        rb.setSpacing(8)
        rb.addSpacing(81 + 9)   # 왼쪽 끝 = 강도 [약] 버튼 x (오른쪽 열 바깥 여백 포함)
        for b in (self.b_cancel, self.b_sample, self.b_each, self.b_start):
            rb.addWidget(b)
        rb.addStretch(1)
        rbw = QWidget()
        rbw.setLayout(rb)
        rbw.setFixedWidth(470)
        rb.setContentsMargins(0, 0, 0, 0)
        self.state_lab = QLabel("")             # MOSCO 처럼 왼쪽 아래 = 지금 진행(단계 색)
        r1 = QHBoxLayout()
        r1.setSpacing(16)
        from . import __version__
        self.ver_lab = QLabel(f"DTME {__version__}")     # v0.16.37 왼쪽 아래 버전
        self.ver_lab.setStyleSheet("color:#6f6f6f; font-size:11px;")
        r1.addWidget(self.ver_lab)
        r1.addWidget(self.state_lab)
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
        self._out_options()
        self.proxy_wait = False             # 시작 창 [보정+편집]: 프록시까지 끝나면 닫힘
        self.armed = False                  # 버튼 전 = 분석만 뒤에서 조용히 미리(v0.16.18), 값 넣기·렌더·표시는 버튼 뒤
        for r in self.rows:                 # 이번 실행 중에 이미 분석한 영상(같은 LUT)은 바로 결과(계산만, 0초)
            s = p.source(r.sid)
            if r.checked and s is not None and s.frames and cached_samples(s, self.row_lut(r)):
                self._compute(r)
                if r.result:
                    r.prog = 1.0
        state.sourceStatus.connect(self._src_status)
        state.workChanged.connect(lambda _sid: self.list.viewport().update())
        self.finished.connect(lambda _r: state.clear_work("analyze", {r.sid for r in self.rows}))
        self._progress()
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

    def row_lut(self, r) -> str:
        """이 줄에 쓸 LUT: 직접 고른 것, 자동이면 색 모드(D-Log M = LUT, 일반·알 수 없음 = 없음, 판단 전 = 지금 클립 LUT)."""
        choice = self.lut_combo.currentData()
        p = self.state.project
        s = p.source(r.sid)
        if choice != "auto":
            return choice or ""
        a = auto_lut(p, s) if s else None
        return a if a is not None else (p.grade_for_source(s.id, off=False).get("lut", "") if s else "")

    def _lut_changed(self, *_):
        """LUT 를 바꾸면 체크된 줄을 그 LUT 로 다시 분석(샘플은 LUT 별로 메모리에 남음)."""
        for r in self.rows:
            r.result, r.prog, r.error = None, 0.0, ""
        self.list.viewport().update()
        self._show_detail()
        self.analyze_all()

    def _src_status(self, sid):
        if any(r.sid == sid for r in self.rows):
            self.list.viewport().update()
            s = self.state.project.source(sid)
            if s is not None and s.frames:              # 정보만 읽히는 대로 분석(버튼 전 = 조용히 미리, 프록시는 기다리지 않음)
                self.analyze_all()
            self._progress()

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
        s = self.state.project.source(row.sid)
        mode = {"dlog": "D-Log M", "ilog": "I-Log", "normal": "일반", "unknown": "알 수 없음"}.get(getattr(s, "lut_mode", ""), "") if s else ""
        if s is not None and s.frames:
            nolut = self.row_lut(row) == ""
            sub.append(" · ".join(x for x in (mode, "LUT 없음" if nolut else "") if x))
        if row.error:
            sub.append("분석 실패")
        if fixed and row.rec and row.result and row.rec != row.result["preset"]:
            sub.append(f"인식: {auto.preset_label(row.rec)}")
        if row.result and row.result["gkeys"] and self.keys.value() == "auto":
            sub.append(f"◆{len({k['f'] for ks in row.result['gkeys'].values() for k in ks})}")
        return label, fixed, "  ".join(sub)

    def _name_preview(self, *_):
        first = next((self.state.project.source(r.sid) for r in self.rows if r.checked), None)
        pre = self.name.text().strip() or "DTME"
        self.name_eg.setText(f"{pre}_{display_name(first.path) if first else ''}.mp4")

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
            self.out.set_value(self._btn_key(r))
        self._out_options()
        self._show_detail()

    def _out_options(self):
        """v0.16.32: 고른 줄(없으면 전체)의 원본 중 하나라도 낼 수 있는 출력만 보임."""
        p = self.state.project
        ok = set()
        for r in self._targets():
            s = p.source(r.sid)
            for k in outputs_for(source_out_h(s), source_vw(s)):
                if is_portrait(s):                      # v0.16.70 세로 촬영: 세로 크기 = 같은 크기 버튼, 인스타 = 숨김(세로 1080 과 같음)
                    if k in ROT_BACK:
                        ok.add(ROT_BACK[k])
                    elif k == "vertical":
                        ok.add("horizontal")
                else:
                    ok.add(k)
        for k, b in self.out.btns.items():
            b.setVisible(k in ok)

    def _btn_key(self, r) -> str:
        """줄의 출력 → 크기 칸 버튼(세로 촬영의 세로 = 그 크기 버튼)."""
        s = self.state.project.source(r.sid)
        if is_portrait(s):
            return ROT_BACK.get(r.out, "horizontal" if r.out == "vertical" else r.out)
        return r.out if r.out in self.out.btns else "horizontal"

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
        p = self.state.project
        for r in self._targets():
            s = p.source(r.sid)
            key = ROT.get(k, k) if is_portrait(s) else k            # v0.16.70 세로 촬영 = 고른 크기를 90도 돌린 세로
            r.out = clamp_src(key, s)     # 원본보다 크면 그 원본의 가장 큰 값
        self.list.viewport().update()

    def _keep(self, k):
        for r in self.rows:
            s = self.state.project.source(r.sid)
            if s and has_clip_grade(s) and s.frames:
                r.checked = k != "keep"
        self.list.viewport().update()
        self._row_changed()

    # ---------------------------------------------------------------- v0.16.37 체크 쓸기
    def showEvent(self, e):
        super().showEvent(e)
        self._vp.installEventFilter(self)

    def hideEvent(self, e):
        try:
            self._vp.removeEventFilter(self)
        except RuntimeError:
            pass
        self._cdrag = None
        super().hideEvent(e)

    def eventFilter(self, obj, e):
        # 창이 닫히며 목록이 먼저 지워져도 안전하게(목록 위젯을 다시 부르지 않음: 저장해 둔 viewport 와 비교만)
        if obj is getattr(self, "_vp", None) and e.type() in (QEvent.MouseButtonPress, QEvent.MouseMove,
                                                                QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            try:
                if self._check_drag(e):
                    return True
            except RuntimeError:      # 지워진 위젯
                self._cdrag = None
            return False
        return False

    def _row_at(self, y):
        it = self.list.itemAt(8, int(y))
        if it is not None:
            return self.list.row(it)
        n = self.list.count()
        if not n:
            return -1
        return 0 if y < self.list.visualItemRect(self.list.item(0)).top() else n - 1

    def _check_drag(self, e) -> bool:
        """✓ 칸(왼쪽 32px)을 누른 채 위아래로 쓸기 = 처음 줄의 바뀐 상태를 지나간 줄에 칠함. 되돌리면 원래대로."""
        t = e.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            if e.button() != Qt.LeftButton:
                return False
            it = self.list.itemAt(e.position().toPoint())
            if it is None or e.position().x() >= self.list.visualItemRect(it).left() + 32:
                return False
            i = self.list.row(it)
            if i >= len(self.rows):
                return False
            self._cdrag = (i, not self.rows[i].checked, [r.checked for r in self.rows])
            self._paint_checks(i)
            return True
        if self._cdrag is None:
            return False
        if t == QEvent.MouseMove:
            self._paint_checks(self._row_at(e.position().y()))
            return True
        if t == QEvent.MouseButtonRelease:
            _i, _v, orig = self._cdrag
            self._cdrag = None
            if [r.checked for r in self.rows] != orig:
                self._row_changed()
            return True
        return False

    def _paint_checks(self, j):
        i, v, orig = self._cdrag
        if j < 0:
            return
        a, b = min(i, j), max(i, j)
        for k, r in enumerate(self.rows):
            r.checked = v if a <= k <= b else orig[k]
        self.list.viewport().update()

    def _row_changed(self):
        self._name_preview()
        self.analyze_all()

    # ---------------------------------------------------------------- 분석
    def _compute(self, r: AutoRow):
        s = self.state.project.source(r.sid)
        lut = self.row_lut(r)
        smp = cached_samples(s, lut) if s else None
        if not smp:
            if s is not None and r.prog >= 1.0:       # 분석 중에 LUT 를 바꿈 → 새 LUT 로 다시
                r.prog = 0.0
                QTimer.singleShot(0, self.analyze_all)
            return
        base = dict(self.state.project.grade)
        base.update({k: v for k, v in s.grade.items() if k in ("sharpen", "lens")})
        base["lut"] = lut
        sc, sb = choice_args(r.choice)
        r.result = auto.recommend(smp, base, sc, sb, self.strength.value() or "mid", fps=float(s.fps),
                                  measure=not auto.is_dji_log(s, lut))        # v0.16.56 DJI 원본이 아니면 화면을 재서
        r.result["grade"]["lens"] = self.lens_s.value()
        r.result["grade"]["stab"] = self.stab_s.value()
        r.rec = auto.recommend(smp, base)["preset"]

    def start_analysis(self):
        """분석 시작(버튼을 누른 것과 같음 — 보정·렌더는 안 함)."""
        self.armed = True
        self.analyze_all()

    def _sample_clicked(self):
        self.armed = True
        self.sampleRequested.emit()

    def _mark_waiting(self):
        """버튼을 누른 뒤 아직 결과 없는 체크된 줄 = 분석 대기(진행 중이면 그대로), 체크 뺀 줄 = 지움."""
        for r in self.rows:
            w = self.state.work.get(r.sid)
            if r.checked and r.result is None and not r.error:
                if getattr(r, "running", False) and r.prog < 1:   # 버튼 전부터 조용히 돌던 것 = 지금 진행률로 바로 표시
                    self.state.set_work(r.sid, "analyze", r.prog)
                elif not (w and w[0] == "analyze" and w[1] >= 0):
                    self.state.set_work(r.sid, "analyze", -1)
            elif w and w[0] == "analyze":
                self.state.set_work(r.sid, None)

    def analyze_all(self):
        """체크된 줄 분석. 버튼 전(armed 아님) = 뒤에서 조용히 미리(진행 표시 없음, ffmpeg 낮은 우선순위) → 버튼 누르면 이미 끝나 있거나 이어서 표시."""
        p = self.state.project
        if self.armed:
            self._mark_waiting()
        for i, r in enumerate(self.rows):
            s = p.source(r.sid)
            if not r.checked or s is None or not s.frames or r.result is not None or r.prog > 0 or r.error:
                continue
            lut = self.row_lut(r)
            r.prog = 0.01                               # 넣음 표시(내부용)
            if self.armed:
                self.state.set_work(r.sid, "analyze", -1)    # v0.16.24: 차례 기다림 = '분석 대기'(시작하면 grab_samples 가 1%)

            def done(_smp, r=r):
                r.prog = 1.0
                self.state.set_work(r.sid, None)
                self._compute(r)
                if self.waiting == "start" and self.mode == "render" and self.pending():
                    self.startRequested.emit()          # [보정+렌더]: 이 영상은 바로 렌더 시작(뒤 영상은 계속 분석)
                self.list.viewport().update()
                self._show_detail()
                self._progress()

            def err(msg, r=r):
                ff.log_error("AUTO 분석", msg)
                if msg != "취소됨" and not getattr(r, "retried", False):
                    r.retried, r.prog, r.running = True, 0.0, False
                    if self.armed:
                        self.state.set_work(r.sid, "analyze", -1)
                    QTimer.singleShot(800, self.analyze_all)
                    return
                r.error, r.prog = msg, 1.0
                self.state.set_work(r.sid, None)
                self.list.viewport().update()
                self._progress()

            def prog(v, r=r):
                r.running = True                        # 실제로 시작함(그 전엔 '분석 대기')
                r.prog = max(0.01, min(0.99, v))
                if self.armed:                          # 버튼 전 = 조용히(줄·왼쪽 아래 표시 없음)
                    self.state.set_work(r.sid, "analyze", r.prog)
                    self._progress()
            j = grab_job(s, lut, p.output.gpu_decode, done, err, prog)
            if j:
                self.jobs.append(j)
        self._progress()

    def pending(self):
        """아직 결과가 없는 체크된 줄(로딩 중 포함). 읽기 오류는 제외."""
        return [r for r in self.rows if r.checked and r.result is None and not r.error
                and self.state.status.get(r.sid) not in ("읽기 오류", "원본 없음", "프록시 오류")]

    def status_text(self):
        """왼쪽 아래 글자 + 막대 (글자, 단계, 진행 0~1). 예: '프록시 1/4 (2번 62%) · 분석 1/4 (2번 45%)'."""
        rows = [(i, r) for i, r in enumerate(self.rows, start=1) if r.checked]
        n = len(rows)
        if not n:
            return "", "proxy", 0.0
        parts, kind, val = [], "proxy", 0.0
        st = self.state.status
        bad = [r for _i, r in rows if st.get(r.sid) in SG.ERRORS]
        adone = sum(1 for _i, r in rows if r.result is not None or r.error)
        if self.armed:
            cur = next(((i, r.prog) for i, r in rows if getattr(r, "running", False) and r.prog < 1), None)
            if adone < n or cur:
                parts.append(f"분석 {adone}/{n}" + (f" ({cur[0]}번 {int(cur[1] * 100)}%)" if cur else ""))
                kind, val = "analyze", sum(min(1.0, r.prog) for _i, r in rows) / n
        pend = [(i, r) for i, r in rows if st.get(r.sid, "") in ("분석 대기", "프록시 대기")
                or (st.get(r.sid, "").startswith("프록시 ") and st.get(r.sid) not in SG.ERRORS)]
        if pend:                                    # 프록시를 만드는 중일 때만(미룸 = "읽음" 은 표시 안 함)
            cur = next(((i, self.state.proxy_pct.get(r.sid, 0.0)) for i, r in pend
                        if st.get(r.sid, "") not in ("분석 대기", "프록시 대기")), None)
            parts.append(f"프록시 {n - len(pend)}/{n}" + (f" ({cur[0]}번 {int(cur[1] * 100)}%)" if cur else ""))
            if kind != "analyze":
                kind = "proxy"
                val = (n - len(pend) + sum(self.state.proxy_pct.get(r.sid, 0.0) for _i, r in pend)) / n
            if self.waiting == "proxy":
                parts.append("끝나면 편집")
        elif self.armed and adone >= n and not parts:
            parts.append(f"분석 {n}/{n}")
            kind, val = "analyze", 1.0
        if bad:
            parts.append(f"읽기 실패 {len(bad)}")
        return " · ".join(parts), kind, val

    def proxy_pending(self):
        """프록시가 아직 안 끝난 줄(읽기 오류 제외) — 시작 창 [보정+편집] 은 이게 비면 편집 화면으로."""
        st = self.state.status
        return [r for r in self.rows if st.get(r.sid) not in ("준비", "읽음") and st.get(r.sid) not in SG.ERRORS]

    def _progress(self):
        if self.waiting == "proxy":
            if not self.proxy_pending():
                self.waiting = None
                self.accept()                        # 프록시까지 끝 → 편집 화면
                return
        if not self.busy or self.waiting:            # 기다리는 중(분석·프록시)에도 왼쪽 아래·막대 갱신
            txt, kind, val = self.status_text()
            col = SG.STAGE[kind][1]
            self.set_bar_color(col)
            self.bar.setValue(int(100 * val))
            self.state_lab.setText(txt)
            self.state_lab.setStyleSheet(f"color:{col};")
        if self.waiting in ("start", "sample") and not self.pending():
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
        self.armed = True
        self.startRequested.emit()

    def show_state(self, text, kind):
        """밖(EditTab)에서 샘플·렌더 진행 글자를 왼쪽 아래에(단계 색)."""
        self.state_lab.setText(text)
        self.state_lab.setStyleSheet(f"color:{SG.STAGE[kind][1]};")

    def settings(self):
        return {"strength": self.strength.value(), "keep": self.keep.value(), "keys": self.keys.value(),
                "after": self.mode, "lens": self.lens_s.value(), "stab": self.stab_s.value(),
                "lut": self.lut_combo.currentData()}

    def chosen_rows(self):
        return [r for r in self.rows if r.checked and r.result]

    def set_busy(self, on, color=None):
        self.busy = on
        for w in (self.grid, self.strength, self.out, self.name, self.keep, self.keys, self.b_sample, self.lens_s, self.stab_s,
                  self.lut_combo,
                  self.b_each, self.b_start, self.list):
            w.setEnabled(not on)
        if color:
            self.set_bar_color(color)

    def cancel(self):
        if self.waiting == "proxy":                  # 프록시 기다리는 중 [취소] = 기다리지 않고 편집 화면으로(값 유지, 프록시는 계속)
            self.waiting = None
            self.accept()
            return
        for j in self.jobs:
            j.cancel.set()
            jobs.AUTO_POOL.tryTake(j)
        self.waiting = None
        self.state.clear_work("analyze", {r.sid for r in self.rows})
        self.state.clear_work("sample", {r.sid for r in self.rows})
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
    att = cfg.get("attach", ["num"])
    parts.append(short_name(src.path))          # 클립 날짜(소스 이름) 항상 — 여러 클립이어도 안 겹침(v0.16.7, 토글 없음)
    if "preset" in att and preset:
        parts.append(preset.replace(" · ", "_").replace(" ", ""))
    if "num" in att:
        parts.append(str(k))
    ext = "jpg" if cfg.get("fmt") == "jpg" else "png"
    return "_".join(parts) + f".{ext}"


class SampleDialog(DragMove, QDialog):
    def __init__(self, name: str, folder: str, parent=None, layout: str = ""):
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
        self.layout_seg = Seg([("side", "나란히"), ("tb", "상하"), ("lr", "좌우")], layout or cfg.get("layout", "side"))
        self.layout_seg.setToolTip("나란히 = 보정 전·후 전체 화면 2장 / 상하·좌우 = 반반")
        v.addLayout(labeled("배치", self.layout_seg))
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
        for k, t in (("preset", "프리셋"), ("num", "번호")):
            bt = QPushButton(t)
            bt.setCheckable(True)
            bt.setFixedHeight(28)
            bt.setStyleSheet(ON_BTN)
            bt.setFocusPolicy(Qt.NoFocus)
            bt.setChecked(k in cfg.get("attach", ["num"]))
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
                "attach": [k for k, b in self.att.items() if b.isChecked()], "layout": self.layout_seg.value() or "side"}

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
