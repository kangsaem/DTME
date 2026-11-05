"""보정 패널(편집 화면 오른쪽)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from . import ff, jobs, paths
from .project import NR_LABELS, save_default_grade, timecode
from .state import AppState
from .ui_curve import CurveEditor

BASE = ("base", "")
N_SAMPLES = 6


def sample_dir() -> Path:
    d = paths.cache_dir() / "samples"
    d.mkdir(parents=True, exist_ok=True)
    return d


class GradePanel(QWidget):
    gradeChanged = Signal()
    beforeToggled = Signal(bool)
    sampleClicked = Signal(str, int, QPixmap)   # 모니터에 그대로 띄움(이동·재렌더 없음)

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.target = BASE
        self.cur_sid = ""
        self.gen = 0
        self.pix: dict[str, QPixmap] = {}

        # --- 머리: 보정 + 기본값으로 저장
        head = QHBoxLayout()
        t = QLabel("보정")
        t.setStyleSheet("font-weight:700; font-size:14px;")
        head.addWidget(t)
        head.addStretch(1)
        b_def = QPushButton("기본값으로 저장")
        b_def.setToolTip("지금 ‘기본값’을 새 프로젝트를 만들 때의 기본값으로 저장")
        b_def.clicked.connect(self._save_default)
        head.addWidget(b_def)

        self.tcombo = QComboBox()
        self.tcombo.setToolTip("기본값 = 모든 클립 공통 · 현재 클립 = 이 클립에서 바꾼 항목만 덮어씀")
        self.tcombo.activated.connect(self._on_target)

        # --- 출력 형태(가로/세로·오디오)
        orow = QHBoxLayout()
        self.orient = QButtonGroup(self)
        for i, (k, txt) in enumerate((("horizontal", "가로 1920×1080"), ("vertical", "세로 1080×1920"))):
            rb = QRadioButton(txt)
            rb.setProperty("key", k)
            rb.setFocusPolicy(Qt.NoFocus)
            self.orient.addButton(rb, i)
            orow.addWidget(rb)
        self.audio = QCheckBox("오디오")
        self.audio.setFocusPolicy(Qt.NoFocus)
        self.audio.setToolTip("배속 구간은 음 높이를 유지한 채 속도만 바뀝니다")
        orow.addWidget(self.audio)
        orow.addStretch(1)
        self.orient.buttonClicked.connect(self._on_output)
        self.audio.toggled.connect(self._on_output)

        self.before = QCheckBox("보정 전 보기")
        self.before.setToolTip("단축키 B")
        self.before.setFocusPolicy(Qt.NoFocus)
        self.before.toggled.connect(self.beforeToggled.emit)

        # --- 조절
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        self.resets, self.vals = {}, {}
        r = 0

        def add_row(key, title, widget, val=True):
            nonlocal r
            g.addWidget(QLabel(title), r, 0)
            g.addWidget(widget, r, 1)
            if val:
                lab = QLabel("")
                lab.setMinimumWidth(44)
                lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.vals[key] = lab
                g.addWidget(lab, r, 2)
            rb = QToolButton()
            rb.setText("↺")
            rb.setToolTip("이 항목은 클립에서 바꾼 값 → 누르면 기본값으로")
            rb.clicked.connect(lambda _=False, k=key: self._clear_key(k))
            self.resets[key] = rb
            g.addWidget(rb, r, 3)
            r += 1

        self.lut = QComboBox()
        self.lut.activated.connect(lambda _: self._set("lut", self.lut.currentData()))
        add_row("lut", "LUT", self.lut, False)
        lb = QHBoxLayout()
        b1 = QPushButton("LUT 추가…")
        b1.clicked.connect(self._add_lut)
        b2 = QPushButton("새로고침")
        b2.clicked.connect(self._fill_luts)
        lb.addWidget(b1)
        lb.addWidget(b2)
        g.addLayout(lb, r, 1, 1, 2)
        r += 1

        def slider(lo, hi, key, scale, tip):
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setFocusPolicy(Qt.NoFocus)
            s.setToolTip(tip)
            s.sliderPressed.connect(self.state.checkpoint)
            s.valueChanged.connect(lambda v, k=key, sc=scale: self._set(k, round(v / sc, 3), slider=True))
            return s

        self.r_gain = slider(70, 150, "r_gain", 100, "빨강 — 수중의 파란 기운을 줄일 때 올림")
        add_row("r_gain", "R", self.r_gain)
        self.b_gain = slider(70, 150, "b_gain", 100, "파랑 — 수중에서는 보통 내림")
        add_row("b_gain", "B", self.b_gain)
        self.hue = slider(-30, 30, "hue", 2, "색조 회전 ±15°")
        add_row("hue", "Hue", self.hue)
        self.sharp = slider(0, 100, "sharpen", 100, "샤픈")
        add_row("sharpen", "샤픈", self.sharp)
        self.nr = QComboBox()
        self.nr.activated.connect(lambda _: self._set("nr", self.nr.currentData()))
        add_row("nr", "디노이즈", self.nr, False)
        g.addWidget(QLabel("커브"), r, 0, Qt.AlignTop)
        self.curve = CurveEditor()
        self.curve.changed.connect(lambda pts: self._set("curve", pts))
        g.addWidget(self.curve, r, 1, 1, 2)
        rb = QToolButton()
        rb.setText("↺")
        rb.setToolTip("커브를 기본값으로")
        rb.clicked.connect(lambda: self._clear_key("curve"))
        self.resets["curve"] = rb
        g.addWidget(rb, r, 3, Qt.AlignTop)
        r += 1
        b3 = QPushButton("리셋")
        b3.setToolTip("커브를 직선으로")
        b3.clicked.connect(self.curve.reset)
        g.addWidget(b3, r, 1, 1, 2)
        r += 1
        g.setColumnStretch(1, 1)

        self.b_clear = QPushButton("클립 보정 해제 (기본값으로)")
        self.b_clear.clicked.connect(self._clear_all)

        # --- 샘플 썸네일
        self.samples = QListWidget()
        self.samples.setViewMode(QListWidget.IconMode)
        self.samples.setIconSize(QSize(150, 84))
        self.samples.setResizeMode(QListWidget.Adjust)
        self.samples.setMovement(QListWidget.Static)
        self.samples.setSpacing(3)
        self.samples.setMinimumHeight(300)
        self.samples.setFocusPolicy(Qt.NoFocus)
        self.samples.setToolTip("클릭: 모니터에 크게 · 더블클릭: PNG 파일 열기")
        self.samples.itemClicked.connect(self._on_sample)
        self.samples.itemDoubleClicked.connect(self._open_sample)
        self.sample_lab = QLabel("샘플 — ‘샘플’ 버튼(G)으로 현재 클립 전체에서 6장 생성")
        self.sample_lab.setStyleSheet("color:#aaa; font-size:11px;")
        self.sample_lab.setWordWrap(True)

        inner = QVBoxLayout()
        inner.setContentsMargins(4, 4, 4, 4)
        inner.addLayout(head)
        inner.addWidget(self.tcombo)
        inner.addLayout(orow)
        inner.addWidget(self.before)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        inner.addWidget(line)
        inner.addLayout(g)
        inner.addWidget(self.b_clear)
        inner.addWidget(self.sample_lab)
        inner.addWidget(self.samples, 1)
        box = QWidget()
        box.setLayout(inner)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(box)
        sc.setFrameShape(QFrame.NoFrame)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(sc)
        self.setMinimumWidth(340)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._emit_change)

        state.changed.connect(self._on_state)
        self._fill_luts()
        self._fill_targets()
        self._load_output()

    # ------------------------------------------------------------ 대상
    def set_current_source(self, sid: str):
        self.cur_sid = sid
        if self.target[0] == "src":
            self.target = ("src", sid) if sid else BASE
        self._fill_targets()
        self.refresh_samples()

    def _fill_targets(self):
        p = self.state.project
        self.tcombo.blockSignals(True)
        self.tcombo.clear()
        self.tcombo.addItem("기본값", BASE)
        s = p.source(self.cur_sid)
        if s:
            self.tcombo.addItem(f"현재 클립: {s.name}" + (" (C)" if s.grade else ""), ("src", s.id))
        idx = next((i for i in range(self.tcombo.count()) if tuple(self.tcombo.itemData(i)) == tuple(self.target)), 0)
        if idx == 0:
            self.target = BASE
        self.tcombo.setCurrentIndex(idx)
        self.tcombo.blockSignals(False)
        self._load_controls()

    def _on_target(self, i):
        self.target = tuple(self.tcombo.itemData(i))
        self._load_controls()

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

    # ------------------------------------------------------------ 출력 형태
    def _load_output(self):
        o = self.state.project.output
        for b in self.orient.buttons():
            b.setChecked(b.property("key") == o.orientation)
        self.audio.blockSignals(True)
        self.audio.setChecked(o.audio)
        self.audio.blockSignals(False)

    def _on_output(self, *_):
        o = self.state.project.output
        btn = self.orient.checkedButton()
        new = (btn.property("key") if btn else "horizontal", self.audio.isChecked())
        if new != (o.orientation, o.audio):
            self.state.checkpoint()
            o.orientation, o.audio = new
            self.state.touch("output")

    # ------------------------------------------------------------ 조절값
    def _fill_luts(self):
        cur = self.lut.currentData()
        self.lut.clear()
        self.lut.addItem("없음", "")
        for n in ff.list_luts():
            self.lut.addItem(n, n)
        self.lut.setCurrentIndex(max(0, self.lut.findData(cur)))

    def _add_lut(self):
        f, _ = QFileDialog.getOpenFileName(self, "LUT 추가", "", "LUT (*.cube *.3dl)")
        if f:
            shutil.copy(f, paths.lut_dir() / Path(f).name)
            self._fill_luts()
            self.lut.setCurrentIndex(self.lut.findData(Path(f).name))
            self._set("lut", Path(f).name)

    def _load_controls(self):
        kind = self.target[0]
        e = self._effective()
        widgets = [self.lut, self.r_gain, self.b_gain, self.hue, self.nr, self.sharp]
        for w in widgets:
            w.blockSignals(True)
        if e["lut"] and self.lut.findData(e["lut"]) < 0:
            self.lut.addItem(f"{e['lut']} (파일 없음)", e["lut"])
        self.lut.setCurrentIndex(max(0, self.lut.findData(e["lut"])))
        self.r_gain.setValue(round(e["r_gain"] * 100))
        self.b_gain.setValue(round(e["b_gain"] * 100))
        self.hue.setValue(round(e["hue"] * 2))
        self.sharp.setValue(round(e["sharpen"] * 100))
        self.nr.clear()
        for lv in ("off", "weak", "mid", "strong"):
            self.nr.addItem(NR_LABELS[lv].replace("(스틸)", ""), lv)
        self.nr.setCurrentIndex(max(0, self.nr.findData(e["nr"])))
        for w in widgets:
            w.blockSignals(False)
        self.curve.set_points(e["curve"])
        self._update_labels()
        self.b_clear.setVisible(kind == "src")

    def _update_labels(self):
        e = self._effective()
        over = self._target_dict() if self.target[0] == "src" else {}
        self.vals["r_gain"].setText(f"{e['r_gain']:.2f}")
        self.vals["b_gain"].setText(f"{e['b_gain']:.2f}")
        self.vals["hue"].setText(f"{e['hue']:+.1f}°")
        self.vals["sharpen"].setText(f"{e['sharpen']:.2f}")
        for k, b in self.resets.items():
            b.setVisible(k in over)

    def _set(self, key, value, slider=False):
        if not slider:
            self.state.checkpoint()
        self._target_dict()[key] = value
        self.state.dirty = True
        self._update_labels()
        if slider:
            self._debounce.start()
        else:
            self._emit_change()

    def _emit_change(self):
        self._relabel()
        self.state.changed.emit("grade")
        self.gradeChanged.emit()
        self.refresh_samples()

    def _relabel(self):
        if self.tcombo.count() > 1:
            s = self.state.project.source(self.cur_sid)
            if s:
                self.tcombo.setItemText(1, f"현재 클립: {s.name}" + (" (C)" if s.grade else ""))

    def _clear_key(self, key):
        self.state.checkpoint()
        self._target_dict().pop(key, None)
        self._load_controls()
        self._emit_change()

    def _clear_all(self):
        self.state.checkpoint()
        self._target_dict().clear()
        self._load_controls()
        self._emit_change()

    def _save_default(self):
        save_default_grade(self.state.project.grade)
        QMessageBox.information(self, "저장", "새 프로젝트를 만들 때 지금 기본값이 들어갑니다.")

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
        before = self.before.isChecked()
        self.samples.clear()
        if not s or not s.frames:
            return
        marks = [m for m in p.samples if m.src == s.id]
        self.sample_lab.setText(f"샘플 {len(marks)}장 — 클릭: 모니터에 크게 · 더블클릭: PNG 열기"
                                if marks else "샘플 — ‘샘플’ 버튼(G)으로 현재 클립 전체에서 6장 생성")
        grade = None if before else p.grade_for_source(s.id)
        for m in marks:
            it = QListWidgetItem(timecode(m.frame, s.fps))
            it.setData(Qt.UserRole, m.id)
            if m.id in self.pix:
                it.setIcon(self.pix[m.id])
            self.samples.addItem(it)
            out = sample_dir() / f"{s.id}_{m.frame}{'_raw' if before else ''}.png"

            def work(s=s, fr=m.frame, out=out, grade=grade):
                data = ff.render_preview(ff.cached_frame(s, fr), grade)
                out.write_bytes(data)
                return str(out)

            job = jobs.Job(work)
            job.signals.done.connect(lambda path, mid=m.id, gn=gen: self._on_png(gn, mid, path))
            jobs.submit(jobs.PREVIEW_POOL, job, priority=-1)

    def _on_png(self, gen, mid, path):
        if gen != self.gen:
            return
        pix = QPixmap(path)
        self.pix[mid] = pix
        for i in range(self.samples.count()):
            it = self.samples.item(i)
            if it.data(Qt.UserRole) == mid:
                it.setIcon(pix.scaled(300, 168, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                it.setData(Qt.UserRole + 1, path)

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
