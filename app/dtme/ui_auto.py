"""보정 탭 프리셋 창 + 자동 창(ui_autowin)이 같이 쓰는 부품(v0.17.0: 예전 AUTO 창·[샘플] 저장 창은 없앰 → ui_autowin).

PresetGrid: [프리셋 자동] / [라이트][산호][얕은 수심] / [깊은 수심][블루워터][야간] · Seg: [a|b|c] · 분석 샘플 기억(grab_job).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import auto, jobs, ui_style
from .ui_render import DragMove
from .project import list_presets

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
