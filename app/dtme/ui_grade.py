"""보정 패널(왼쪽 열). 제목 없음(툴팁만), 접는 묶음, 숫자 클릭 = 직접 입력, 프리셋."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from . import ff, jobs, paths
from .project import (KEYABLE, OUTPUTS, delete_preset, get_setting, grade_at, list_presets, load_preset,
                      rename_preset, save_default_grade, save_preset, set_setting, timecode)
from .state import AppState
from .ui_curve import CurveEditor
from .ui_render import fix_size

BASE = ("base", "")
N_SAMPLES = 6
TILE_W, TILE_H = 150, 84
SIDE_W = 60            # 오른쪽 버튼(저장… · 오디오 · RGB) 폭
ON_STYLE = ("QPushButton:checked{background:#5a4a1a; border-color:#f2c94c; color:#f2c94c;}")

# key: (슬라이더 최소, 최대, 값 = 슬라이더 / scale, 표시 형식)
SLIDERS = {
    "r_gain": (50, 200, 100, "{:.2f}"), "b_gain": (50, 150, 100, "{:.2f}"), "hue": (-30, 30, 2, "{:+.1f}°"),
    "sat": (0, 200, 100, "{:.2f}"), "sharpen": (0, 100, 100, "{:.2f}"), "dehaze": (0, 100, 1, "{:.0f}"),
    "nr_chroma": (0, 100, 1, "{:.0f}"), "nr_luma": (0, 100, 1, "{:.0f}"), "lens": (0, 100, 1, "{:.0f}"),
    "stab": (0, 100, 1, "{:.0f}"),
}


def sample_dir() -> Path:
    d = paths.cache_dir() / "samples"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ValueEdit(QLineEdit):
    """평소엔 숫자 글자, 클릭하면 직접 입력(Enter 적용 · Esc 취소)."""
    submitted = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(44)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self._shown = ""
        self._idle()
        self.returnPressed.connect(self._commit)

    def _idle(self):
        self.setReadOnly(True)
        self.setStyleSheet("QLineEdit{background:transparent; border:1px solid transparent; color:#d0d0d0; padding:0 2px;}")

    def show_value(self, text):
        self._shown = text
        if self.isReadOnly():
            self.setText(text)

    def mousePressEvent(self, e):
        if self.isReadOnly():
            self.setReadOnly(False)
            self.setStyleSheet("QLineEdit{background:#111; border:1px solid #4a8fe0; color:#fff; padding:0 2px;}")
            self.setText(self._shown.replace("°", "").replace("+", "").replace("끔", "0"))
            self.setFocus()
            QTimer.singleShot(0, self.selectAll)
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if not self.isReadOnly():
            self._cancel()

    def _cancel(self):
        self._idle()
        self.setText(self._shown)
        self.clearFocus()

    def _commit(self):
        try:
            v = float(self.text().replace(",", "."))
        except ValueError:
            self._cancel()
            return
        self._idle()
        self.clearFocus()
        self.submitted.emit(v)


class Section(QWidget):
    """제목 줄을 누르면 펴고 접는 묶음. 상태는 settings.json 'sections' 에 기억."""

    def __init__(self, key, title, parent=None):
        super().__init__(parent)
        self.key = key
        self.head = QPushButton()
        self.head.setCheckable(True)
        self.head.setFocusPolicy(Qt.NoFocus)
        self.head.setFixedHeight(22)
        self.head.setStyleSheet("QPushButton{background:#2b2b2b; border:none; border-radius:3px; color:#e0e0e0;"
                                "font-weight:700; text-align:left; padding:0 8px;}"
                                "QPushButton:checked{background:#2b2b2b;}")
        self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title = title
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 2, 0, 2)
        self.lay.setSpacing(4)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        v.addWidget(self.head)
        v.addWidget(self.body)
        opened = (get_setting("sections", {}) or {}).get(key, True)
        self.head.setChecked(opened)
        self.head.toggled.connect(self._toggle)
        self._toggle(opened, save=False)

    def _toggle(self, on, save=True):
        self.head.setText(("▾  " if on else "▸  ") + self.title)
        self.body.setVisible(on)
        if save:
            st = dict(get_setting("sections", {}) or {})
            st[self.key] = on
            try:
                set_setting("sections", st)
            except Exception:  # noqa: BLE001
                pass


class GradePanel(QWidget):
    gradeChanged = Signal()
    viewChanged = Signal(str)                    # "grade" | "raw" | "split"
    scopeToggled = Signal(bool)
    whitePickToggled = Signal(bool)
    sampleClicked = Signal(str, int, QPixmap)   # 모니터에 그대로 띄움(이동·재렌더 없음)
    keysChanged = Signal()                      # 색 키프레임 추가·삭제·이동

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.frame = 0
        self.kbtn: dict[str, QPushButton] = {}
        self.target = BASE
        self.cur_sid = ""
        self.gen = 0
        self.pix: dict[str, QPixmap] = {}
        self.targets_fn = None                   # 여러 클립 선택 → 프리셋 적용 대상(EditTab 이 지정)
        self.sliders: dict[str, QSlider] = {}
        self.vals: dict[str, ValueEdit] = {}

        # --- 머리: 리셋 · 기본값 ··· 기본값으로 저장
        head = QHBoxLayout()
        b_reset = fix_size(QPushButton("리셋"))
        b_reset.setToolTip("이 클립의 조정값을 초기값으로 (LUT 유지)")
        b_reset.clicked.connect(self._reset_clip)
        b_base = fix_size(QPushButton("기본값"))
        b_base.setToolTip("이 클립을 기본값으로 되돌림")
        b_base.clicked.connect(self._clear_all)
        b_def = QPushButton("기본값으로 저장")
        b_def.setFixedHeight(26)
        b_def.setToolTip("이 클립의 값을 모든 클립의 기본값으로")
        b_def.clicked.connect(self._save_default)
        for b in (b_reset, b_base, b_def):
            b.setFocusPolicy(Qt.NoFocus)
        head.addWidget(b_reset)
        head.addWidget(b_base)
        head.addStretch(1)
        head.addWidget(b_def)

        # --- 프리셋 ▾ [저장…]
        self.preset = QComboBox()
        self.preset.setToolTip("프리셋 (우클릭: 이름 바꾸기 · 덮어쓰기 · 기본값으로 쓰기 · 삭제)")
        self.preset.setPlaceholderText("프리셋")
        self.preset.setFocusPolicy(Qt.NoFocus)
        self.preset.activated.connect(self._apply_preset)
        self.preset.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preset.customContextMenuRequested.connect(self._preset_menu)
        b_ps = self._side(QPushButton("저장…"))
        b_ps.setToolTip("지금 값을 프리셋으로 저장")
        b_ps.clicked.connect(self._save_preset)
        prow = QHBoxLayout()
        prow.addWidget(self.preset, 1)
        prow.addWidget(b_ps)

        # --- 출력 ▾ [오디오]
        self.out = QComboBox()
        self.out.setToolTip("출력 크기")
        self.out.setFocusPolicy(Qt.NoFocus)
        for k, label in OUTPUTS:
            self.out.addItem(label, k)
        self.out.activated.connect(self._on_output)
        self.audio = self._side(QPushButton("오디오"), checkable=True)
        self.audio.setToolTip("소리 넣기")
        self.audio.toggled.connect(self._on_output)
        orow = QHBoxLayout()
        orow.addWidget(self.out, 1)
        orow.addWidget(self.audio)

        # --- 보기 [보정|원본|반반] [RGB]
        self.view = QButtonGroup(self)
        vbox = QHBoxLayout()
        vbox.setSpacing(0)
        for i, (k, t, tip) in enumerate((("grade", "보정", ""), ("raw", "원본", "B"), ("split", "반반", "왼쪽 원본 · 오른쪽 보정"))):
            b = QPushButton(t)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(26)
            b.setToolTip(tip)
            b.setProperty("key", k)
            b.setStyleSheet("QPushButton{border-radius:0; background:#2a2a2a;} QPushButton:checked{background:#2f4f78; color:#fff;}")
            self.view.addButton(b, i)
            vbox.addWidget(b, 1)
        self.view.button(0).setChecked(True)
        self.view.buttonClicked.connect(lambda b: self.viewChanged.emit(b.property("key")))
        self.rgb = self._side(QPushButton("RGB"), checkable=True)
        self.rgb.setToolTip("RGB 파형")
        self.rgb.toggled.connect(self.scopeToggled.emit)
        vrow = QHBoxLayout()
        vrow.addLayout(vbox, 1)
        vrow.addWidget(self.rgb)

        # --- 묶음: 색
        s_col = Section("color", "색")
        self.lut = LutCombo(self._fill_luts)
        self.lut.setToolTip("LUT")
        self.lut.setFocusPolicy(Qt.NoFocus)
        self.lut.activated.connect(lambda _: self._set("lut", self.lut.currentData()))
        s_col.lay.addWidget(self.lut)
        lb = QHBoxLayout()
        lb.addStretch(1)
        self.b_white = fix_size(QPushButton("흰색 찍기"))
        self.b_white.setCheckable(True)
        self.b_white.setToolTip("모니터에서 모래·흰 부분을 클릭 → 빨강·파랑 자동 (W)")
        self.b_white.setStyleSheet(ON_STYLE)
        self.b_white.setFocusPolicy(Qt.NoFocus)
        self.b_white.toggled.connect(self.whitePickToggled.emit)
        b1 = fix_size(QPushButton("LUT 추가…"))
        b1.setFocusPolicy(Qt.NoFocus)
        b1.clicked.connect(self._add_lut)
        lb.addWidget(self.b_white)
        lb.addWidget(b1)
        s_col.lay.addLayout(lb)
        for key, name in (("r_gain", "빨강"), ("b_gain", "파랑"), ("hue", "색조"), ("sat", "채도")):
            s_col.lay.addLayout(self._row(key, name, 30, Qt.AlignLeft))
        s_col.lay.setSpacing(3)
        self.curve = CurveEditor()
        self.curve.changed.connect(lambda pts: self._set("curve", pts))
        s_col.lay.addWidget(self.curve)
        crow = QHBoxLayout()
        crow.addStretch(1)
        b3 = fix_size(QPushButton("커브리셋"))
        b3.setFocusPolicy(Qt.NoFocus)
        b3.clicked.connect(self.curve.reset)
        crow.addWidget(b3)
        s_col.lay.addLayout(crow)

        # --- 묶음: 디테일 / 렌즈·흔들림
        s_det = Section("detail", "디테일")
        for key, name in (("sharpen", "샤픈"), ("dehaze", "디헤이즈"), ("nr_chroma", "색 노이즈"), ("nr_luma", "밝기 노이즈")):
            s_det.lay.addLayout(self._row(key, name, 72, Qt.AlignRight))
        s_lens = Section("lens", "렌즈 · 흔들림")
        s_lens.lay.addLayout(self._row("lens", "렌즈 보정", 72, Qt.AlignRight, "액션캠 휘어짐 보정"))
        s_lens.lay.addLayout(self._row("stab", "흔들림 보정", 72, Qt.AlignRight, "렌더에만 적용"))

        # --- 묶음: 샘플
        s_smp = Section("samples", "샘플")
        self.samples = QListWidget()
        self.samples.setViewMode(QListWidget.IconMode)
        self.tile = (TILE_W, TILE_H)
        self.samples.setIconSize(QSize(TILE_W, TILE_H))
        self.samples.setGridSize(QSize(TILE_W + 4, TILE_H + 4))
        self.samples.setResizeMode(QListWidget.Fixed)
        self.samples.setMovement(QListWidget.Static)
        self.samples.setFlow(QListWidget.LeftToRight)
        self.samples.setWrapping(True)
        self.samples.setSpacing(0)
        self.samples.setUniformItemSizes(True)
        self.samples.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.samples.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.samples.setFocusPolicy(Qt.NoFocus)
        self.samples.setStyleSheet("QListWidget{background:#151515; border:none;}")
        self.samples.itemClicked.connect(self._on_sample)
        self.samples.itemDoubleClicked.connect(self._open_sample)
        s_smp.lay.addWidget(self.samples)
        self.sections = (s_col, s_det, s_lens, s_smp)

        inner = QVBoxLayout()
        inner.setContentsMargins(4, 4, 4, 4)
        inner.setSpacing(4)
        for lay in (head, prow, orow, vrow):
            inner.addLayout(lay)
        for sct in self.sections:
            inner.addWidget(sct)
        inner.addStretch(1)
        box = QWidget()
        box.setLayout(inner)
        sc = self._scroll = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(box)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.viewport().installEventFilter(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(sc)
        self.setMinimumWidth(280)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._emit_change)

        state.changed.connect(self._on_state)
        self._fill_luts()
        self._fill_presets()
        self._fill_targets()
        self._load_output()

    # ------------------------------------------------------------ 위젯 도우미
    def _side(self, b, checkable=False):
        b.setFixedSize(SIDE_W, 26)
        b.setFocusPolicy(Qt.NoFocus)
        if checkable:
            b.setCheckable(True)
            b.setStyleSheet(ON_STYLE)
        return b

    def _row(self, key, name, lw, align, tip=""):
        lo, hi, sc, _fmt = SLIDERS[key]
        row = QHBoxLayout()
        row.setSpacing(6)
        lab = QLabel(name)
        lab.setFixedWidth(lw)
        lab.setAlignment(align | Qt.AlignVCenter)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setFocusPolicy(Qt.NoFocus)
        if tip:
            s.setToolTip(tip)
            lab.setToolTip(tip)
        s.sliderPressed.connect(lambda k=key: self.state.checkpoint(f"slider:{k}"))
        s.valueChanged.connect(lambda v, k=key, c=sc: self._set(k, v if c == 1 else round(v / c, 3), slider=True))
        val = ValueEdit()
        val.submitted.connect(lambda v, k=key: self._typed(k, v))
        self.sliders[key], self.vals[key] = s, val
        row.addWidget(lab)
        row.addWidget(s, 1)
        row.addWidget(val)
        if key in KEYABLE:
            kb = QPushButton("◆")
            kb.setFixedSize(22, 20)
            kb.setFocusPolicy(Qt.NoFocus)
            kb.setToolTip("이 프레임에 키프레임 (다시 누르면 삭제)")
            kb.clicked.connect(lambda _=False, k=key: self._toggle_key(k))
            self.kbtn[key] = kb
            row.addWidget(kb)
        return row

    # ------------------------------------------------------------ 색 키프레임 ◆
    def _src(self):
        return self.state.project.source(self.cur_sid) if self.target[0] == "src" else None

    def set_frame(self, f):
        self.frame = f
        s = self._src()
        if s and s.gkeys:
            self._load_controls()

    def _toggle_key(self, key):
        s = self._src()
        if not s:
            return
        self.state.checkpoint()
        ks = s.gkeys.setdefault(key, [])
        hit = next((k for k in ks if k["f"] == self.frame), None)
        if hit:
            ks.remove(hit)
        else:
            ks.append({"f": self.frame, "v": float(self._shown()[key])})
            ks.sort(key=lambda k: k["f"])
        if not ks:
            s.gkeys.pop(key, None)
        self.state.dirty = True
        self._load_controls()
        self.keysChanged.emit()
        self._emit_change()

    def _shown(self) -> dict:
        """지금 프레임에 보이는 값(키프레임 보간 포함)."""
        s = self._src()
        e = self._effective()
        return grade_at(e, s.gkeys, self.frame) if s and s.gkeys else e

    def _write(self, key, value):
        """키프레임이 있는 항목이면 현재 프레임 키를 만들거나 고침, 아니면 클립 값."""
        s = self._src()
        if s and key in KEYABLE and s.gkeys.get(key):
            ks = s.gkeys[key]
            hit = next((k for k in ks if k["f"] == self.frame), None)
            if hit:
                hit["v"] = float(value)
            else:
                ks.append({"f": self.frame, "v": float(value)})
                ks.sort(key=lambda k: k["f"])
                self.keysChanged.emit()
        else:
            self._target_dict()[key] = value

    def _typed(self, key, v):
        lo, hi, sc, _f = SLIDERS[key]
        self.state.checkpoint()
        v = max(lo / sc, min(hi / sc, v))
        self._write(key, v if sc != 1 else int(round(v)))
        self.state.dirty = True
        self._load_controls()
        self._emit_change()

    # ------------------------------------------------------------ 대상
    def set_current_source(self, sid: str):
        self.cur_sid = sid
        self.target = ("src", sid) if sid and self.state.project.source(sid) else BASE
        self._load_controls()
        self.refresh_samples()

    def _fill_targets(self):
        self.set_current_source(self.cur_sid)

    def _target_dict(self) -> dict:
        kind, tid = self.target
        s = self.state.project.source(tid) if kind == "src" else None
        return s.grade if s else self.state.project.grade

    def _effective(self) -> dict:
        kind, tid = self.target
        p = self.state.project
        if kind == "src" and p.source(tid):
            return p.grade_for_source(tid)
        return dict(p.grade)

    def view_mode(self) -> str:
        b = self.view.checkedButton()
        return b.property("key") if b else "grade"

    def set_view(self, key):
        for b in self.view.buttons():
            if b.property("key") == key:
                b.setChecked(True)
        self.viewChanged.emit(key)

    # ------------------------------------------------------------ 출력
    def _load_output(self):
        o = self.state.project.output
        self.out.setCurrentIndex(max(0, self.out.findData(o.orientation)))
        self.audio.blockSignals(True)
        self.audio.setChecked(o.audio)
        self.audio.blockSignals(False)

    def set_output(self, key):
        self.out.setCurrentIndex(max(0, self.out.findData(key)))
        self._on_output()

    def _on_output(self, *_):
        o = self.state.project.output
        new = (self.out.currentData() or "horizontal", self.audio.isChecked())
        if new != (o.orientation, o.audio):
            self.state.checkpoint()
            o.orientation, o.audio = new
            self.state.touch("output")

    # ------------------------------------------------------------ LUT
    def _fill_luts(self):
        cur = self.lut.currentData()
        self.lut.blockSignals(True)
        self.lut.clear()
        self.lut.addItem("LUT 없음", "")
        for n in ff.list_luts():
            self.lut.addItem(n, n)
        self.lut.setCurrentIndex(max(0, self.lut.findData(cur)))
        self.lut.blockSignals(False)

    def _add_lut(self):
        f, _ = QFileDialog.getOpenFileName(self, "LUT 추가", "", "LUT (*.cube *.3dl)")
        if f:
            shutil.copy(f, paths.lut_dir() / Path(f).name)
            self._fill_luts()
            self.lut.setCurrentIndex(self.lut.findData(Path(f).name))
            self._set("lut", Path(f).name)

    # ------------------------------------------------------------ 프리셋
    def _fill_presets(self, select=""):
        self.preset.blockSignals(True)
        self.preset.clear()
        for n in list_presets():
            self.preset.addItem(n, n)
        self.preset.setCurrentIndex(self.preset.findData(select) if select else -1)
        self.preset.blockSignals(False)

    def _apply_preset(self, i):
        name = self.preset.itemData(i)
        if not name:
            return
        try:
            g = load_preset(name)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "프리셋", str(e))
            return
        p = self.state.project
        sids = (self.targets_fn() if self.targets_fn else []) or ([self.cur_sid] if self.cur_sid else [])
        self.state.checkpoint()
        if sids:
            for sid in sids:
                s = p.source(sid)
                if s:
                    s.grade = {k: v for k, v in g.items() if p.grade.get(k) != v}
                    s.gkeys = {}
            self.keysChanged.emit()
        else:
            p.grade.update(g)
        self.state.dirty = True
        self._load_controls()
        self._emit_change()

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "프리셋 저장", "이름", text=self.preset.currentData() or "")
        name = name.strip()
        if not ok or not name:
            return
        if name in list_presets() and QMessageBox.question(self, "프리셋", f"{name} 덮어쓰기?") != QMessageBox.Yes:
            return
        save_preset(name, self._effective())
        self._fill_presets(name)

    def _preset_menu(self, pos):
        name = self.preset.currentData()
        if not name:
            return
        m = QMenu(self)
        a_ren = QAction("이름 바꾸기", m)
        a_ovr = QAction("지금 값으로 덮어쓰기", m)
        a_def = QAction("기본값으로 쓰기", m)
        a_del = QAction("삭제", m)
        for a in (a_ren, a_ovr, a_def):
            m.addAction(a)
        m.addSeparator()
        m.addAction(a_del)
        act = m.exec(self.preset.mapToGlobal(pos))
        if act is a_ren:
            new, ok = QInputDialog.getText(self, "이름 바꾸기", "이름", text=name)
            if ok and new.strip() and new.strip() != name:
                rename_preset(name, new.strip())
                self._fill_presets(new.strip())
        elif act is a_ovr:
            save_preset(name, self._effective())
        elif act is a_def:
            self.state.checkpoint()
            self.state.project.grade.update(load_preset(name))
            save_default_grade(self.state.project.grade)
            self._load_controls()
            self._emit_change()
        elif act is a_del:
            if QMessageBox.question(self, "삭제", f"{name} 삭제?") == QMessageBox.Yes:
                delete_preset(name)
                self._fill_presets()

    # ------------------------------------------------------------ 조절값
    def _load_controls(self):
        e = self._shown()
        s = self._src()
        for k, b in self.kbtn.items():
            ks = (s.gkeys.get(k) or []) if s else []
            on = any(x["f"] == self.frame for x in ks)
            b.setStyleSheet("QPushButton{background:#5a4a1a; border:1px solid #f2c94c; color:#f2c94c; padding:0;}" if on else
                            "QPushButton{color:#f2c94c; padding:0;}" if ks else "QPushButton{color:#777; padding:0;}")
        widgets = [self.lut, *self.sliders.values()]
        for w in widgets:
            w.blockSignals(True)
        if e["lut"] and self.lut.findData(e["lut"]) < 0:
            self.lut.addItem(f"{e['lut']} (파일 없음)", e["lut"])
        self.lut.setCurrentIndex(max(0, self.lut.findData(e["lut"])))
        for k, s in self.sliders.items():
            lo, hi, sc, _f = SLIDERS[k]
            s.setValue(int(round(float(e.get(k, 0)) * sc)))
        for w in widgets:
            w.blockSignals(False)
        self.curve.set_points(e["curve"])
        self._update_labels()

    def _update_labels(self):
        e = self._shown()
        for k, v in self.vals.items():
            x = float(e.get(k, 0))
            v.show_value("끔" if k == "stab" and x <= 0 else SLIDERS[k][3].format(x))

    def _set(self, key, value, slider=False):
        # 슬라이더: 손잡이·홈 클릭·휠 어느 쪽이든 실행취소 지점(연속 조작은 1번으로 합침)
        self.state.checkpoint(f"slider:{key}" if slider else "")
        self._write(key, value)
        self.state.dirty = True
        self._update_labels()
        if slider:
            self._debounce.start()
        else:
            self._emit_change()

    def set_values(self, values: dict):
        """흰색 찍기 등 여러 값을 한 번에(실행취소 1번)."""
        self.state.checkpoint()
        d = self._target_dict()
        for k, v in values.items():
            lo, hi, sc, _f = SLIDERS.get(k, (None, None, 1, ""))
            d[k] = round(max(lo / sc, min(hi / sc, v)), 3) if lo is not None else v
        self.state.dirty = True
        self._load_controls()
        self._emit_change()

    def _emit_change(self):
        self.state.changed.emit("grade")
        self.gradeChanged.emit()
        self.refresh_samples()

    def _clear_all(self):
        self.state.checkpoint()
        self._target_dict().clear()
        if self._src():
            self._src().gkeys = {}
            self.keysChanged.emit()
        self._load_controls()
        self._emit_change()

    def _reset_clip(self):
        """조정값 초기화(LUT 는 유지)."""
        from .project import FACTORY_GRADE
        self.state.checkpoint()
        d = self._target_dict()
        lut = self._effective().get("lut", "")
        if self.target[0] == "src":
            d.clear()
            d.update({k: v for k, v in FACTORY_GRADE.items() if k != "lut"})
            d["nr_chroma"], d["nr_luma"], d["sharpen"], d["stab"] = 0, 0, 0.0, 0
        else:
            d.update({k: v for k, v in FACTORY_GRADE.items() if k != "lut"})
            d["nr_chroma"], d["nr_luma"], d["sharpen"] = 0, 0, 0.0
        if self.target[0] == "src" and lut != self.state.project.grade.get("lut", ""):
            d["lut"] = lut
        if self._src():
            self._src().gkeys = {}
            self.keysChanged.emit()
        self._load_controls()
        self._emit_change()

    def _save_default(self):
        """이 클립의 값을 기본값(모든 클립 공통)으로 + 새 프로젝트 기본값으로 저장."""
        self.state.checkpoint()
        e = self._effective()
        p = self.state.project
        p.grade.update({k: e[k] for k in p.grade if k in e})
        if self.target[0] == "src":
            self._target_dict().clear()
        save_default_grade(p.grade)
        self._load_controls()
        self._emit_change()
        QMessageBox.information(self, "저장", "기본값으로 저장됨")

    # ------------------------------------------------------------ 샘플 (PNG)
    def make_samples(self):
        """현재 클립 전체(인/아웃과 무관)에서 고르게 6장."""
        s = self.state.project.source(self.cur_sid)
        if not s or not s.frames:
            return False
        from .project import Marker
        self.state.checkpoint()
        p = self.state.project
        p.samples = [m for m in p.samples if m.src != s.id]
        for k in range(N_SAMPLES):
            p.samples.append(Marker(s.id, int((k + 0.5) / N_SAMPLES * s.frames)))
        self.state.touch("markers")
        return True

    def refresh_samples(self):
        p = self.state.project
        s = p.source(self.cur_sid)
        self.gen += 1
        gen = self.gen
        raw = self.view_mode() == "raw"
        self.samples.clear()
        if not s or not s.frames:
            return
        marks = [m for m in p.samples if m.src == s.id]
        for m in marks:
            grade = None if raw else p.grade_for_source(s.id, m.frame)
            it = QListWidgetItem("")
            it.setToolTip(timecode(m.frame, s.fps))
            it.setSizeHint(QSize(self.tile[0] + 4, self.tile[1] + 4))
            it.setData(Qt.UserRole, m.id)
            if m.id in self.pix:
                it.setIcon(self.pix[m.id])
            self.samples.addItem(it)
            out = sample_dir() / f"{s.id}_{m.frame}{'_raw' if raw else ''}.png"

            def work(s=s, fr=m.frame, out=out, grade=grade):
                data = ff.render_preview(ff.cached_frame(s, fr), grade)
                tmp = out.with_suffix(f".{gen}.part")
                tmp.write_bytes(data)
                try:
                    ff.replace_retry(tmp, out, tries=10)
                except PermissionError:      # 열려 있으면(뷰어 등) 이번 PNG 저장만 건너뜀
                    tmp.unlink(missing_ok=True)
                return data, str(out)

            job = jobs.Job(work)
            job.signals.done.connect(lambda r, mid=m.id, gn=gen: self._on_png(gn, mid, r))
            jobs.submit(jobs.PREVIEW_POOL, job, priority=-1)

    def _on_png(self, gen, mid, result):
        if gen != self.gen:
            return
        data, path = result
        pix = QPixmap()
        pix.loadFromData(data, "PNG")      # 파일을 다시 열지 않음(쓰기와 충돌 방지)
        self.pix[mid] = pix
        for i in range(self.samples.count()):
            it = self.samples.item(i)
            if it.data(Qt.UserRole) == mid:
                it.setIcon(self._icon(pix))
                it.setData(Qt.UserRole + 1, path)

    # ------------------------------------------------------------ 샘플 타일 크기 = 패널 폭에 맞춤
    def _icon(self, pix):
        return pix.scaled(self.tile[0] * 2, self.tile[1] * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Resize and obj is self._scroll.viewport():
            QTimer.singleShot(0, self._fit_tiles)
        return False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_tiles()
        QTimer.singleShot(0, self._fit_tiles)       # 스크롤 영역 폭이 확정된 뒤 한 번 더

    def _fit_curve(self):
        """커브 높이 = 남는 높이(70~240) → 화면이 낮아도(노트북) 모든 묶음을 펴고 스크롤 없이."""
        box = self._scroll.widget()
        if box is None or not self.curve.isVisible():
            return
        spare = self._scroll.viewport().height() - box.sizeHint().height()
        ch = int(max(70, min(240, self.curve.height() + spare)))
        if abs(self.curve.height() - ch) > 2:
            self.curve.setFixedHeight(ch)

    def _fit_tiles(self):
        """샘플 폭 = 조절 영역 폭. 좁으면 3열×2줄, 넓으면(360px 이상) 2열×3줄."""
        self._fit_curve()
        avail = max(160, self._scroll.viewport().width() - 8)
        cols = 2 if avail >= 360 else 3
        tw = (avail - 4 * cols - 4) // cols
        th = tw * 9 // 16
        rows = (N_SAMPLES + cols - 1) // cols
        if (tw, th) == self.tile and self.samples.width() == avail:
            return
        self.tile = (tw, th)
        self.samples.setIconSize(QSize(tw, th))
        self.samples.setGridSize(QSize(tw + 4, th + 4))
        self.samples.setFixedSize(cols * (tw + 4) + 4, rows * (th + 4) + 4)
        for i in range(self.samples.count()):
            it = self.samples.item(i)
            it.setSizeHint(QSize(tw + 4, th + 4))
            pix = self.pix.get(it.data(Qt.UserRole))
            if pix:
                it.setIcon(self._icon(pix))

    def _on_sample(self, it):
        mid = it.data(Qt.UserRole)
        m = next((x for x in self.state.project.samples if x.id == mid), None)
        if m and mid in self.pix:
            self.sampleClicked.emit(m.src, m.frame, self.pix[mid])

    def _open_sample(self, it):
        path = it.data(Qt.UserRole + 1)
        if path and Path(path).exists():
            if os.name == "nt":
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])

    # ------------------------------------------------------------ 상태
    def _on_state(self, what):
        if what in ("project", "sources", "undo"):
            self._fill_targets()
            self._load_output()
            self.refresh_samples()
        elif what == "markers":
            self.refresh_samples()
        elif what == "output":
            self._load_output()


class LutCombo(QComboBox):
    """열 때마다 luts 폴더를 다시 읽음(새로고침 버튼 대신)."""

    def __init__(self, refill, parent=None):
        super().__init__(parent)
        self._refill = refill

    def showPopup(self):
        self._refill()
        super().showPopup()


_ = QGridLayout
