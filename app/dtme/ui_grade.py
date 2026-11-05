"""보정 패널(편집 화면 오른쪽): 대상(기본값/현재 클립/스틸) 선택, 조절, 샘플 썸네일."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QToolButton, QVBoxLayout, QWidget)

from . import ff, jobs, paths
from .project import MAX_SAMPLES, NR_LABELS, save_default_grade, timecode
from .state import AppState
from .ui_curve import CurveEditor

BASE = ("base", "")


def _title(t):
    lab = QLabel(t)
    lab.setStyleSheet("font-weight:600; color:#cfcfcf; padding-top:6px;")
    return lab


class GradePanel(QWidget):
    gradeChanged = Signal()                 # 화면 미리보기 갱신 필요
    seekRequested = Signal(str, int)        # (source id, frame)
    beforeToggled = Signal(bool)

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.target = BASE
        self.cur_sid = ""
        self.gen = 0
        self.thumbs_pix: dict[str, QPixmap] = {}

        # --- 대상
        self.tcombo = QComboBox()
        self.tcombo.activated.connect(self._on_target)
        self.tinfo = QLabel("")
        self.tinfo.setWordWrap(True)
        self.tinfo.setStyleSheet("color:#999; font-size:11px;")
        self.before = QCheckBox("보정 전 보기 (B)")
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
            rb.setToolTip("이 항목 덮어쓰기 해제 (기본값 사용)")
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
            s.setToolTip(tip + " · 더블클릭한 값 표시 옆 ↺ 로 기본값 복귀")
            s.valueChanged.connect(lambda v, k=key, sc=scale: self._set(k, round(v / sc, 3), slider=True))
            return s

        self.r_gain = slider(70, 150, "r_gain", 100, "빨강 증폭 — 수중의 파란 기운을 줄일 때 올림")
        add_row("r_gain", "R 게인", self.r_gain)
        self.b_gain = slider(70, 150, "b_gain", 100, "파랑 증폭 — 수중에서는 보통 내림")
        add_row("b_gain", "B 게인", self.b_gain)
        self.hue = slider(-30, 30, "hue", 2, "전체 색조 회전 ±15°")
        add_row("hue", "Hue", self.hue)
        self.sharp = slider(0, 100, "sharpen", 100, "샤픈 강도 (CAS)")
        add_row("sharpen", "샤픈", self.sharp)
        self.nr = QComboBox()
        self.nr.activated.connect(lambda _: self._set("nr", self.nr.currentData()))
        add_row("nr", "노이즈", self.nr, False)
        g.addWidget(QLabel("커브"), r, 0, Qt.AlignTop)
        self.curve = CurveEditor()
        self.curve.changed.connect(lambda pts: self._set("curve", pts))
        g.addWidget(self.curve, r, 1, 1, 2)
        rb = QToolButton()
        rb.setText("↺")
        rb.setToolTip("커브 덮어쓰기 해제")
        rb.clicked.connect(lambda: self._clear_key("curve"))
        self.resets["curve"] = rb
        g.addWidget(rb, r, 3, Qt.AlignTop)
        r += 1
        b3 = QPushButton("커브 직선으로")
        b3.clicked.connect(self.curve.reset)
        g.addWidget(b3, r, 1, 1, 2)
        r += 1
        g.setColumnStretch(1, 1)

        self.b_clear = QPushButton("이 대상의 덮어쓰기 모두 해제")
        self.b_clear.clicked.connect(self._clear_all)
        self.b_save_def = QPushButton("기본값을 ‘새 프로젝트 기본값’으로 저장")
        self.b_save_def.clicked.connect(self._save_default)
        self.b_sharp = QPushButton("선명한 프레임 찾기 (앞뒤 5프레임)")
        self.b_sharp.clicked.connect(self._find_sharp)
        self.b_del_still = QPushButton("이 스틸 삭제")
        self.b_del_still.clicked.connect(self._delete_still)

        # --- 샘플
        self.samples = QListWidget()
        self.samples.setViewMode(QListWidget.IconMode)
        self.samples.setIconSize(QSize(144, 81))
        self.samples.setResizeMode(QListWidget.Adjust)
        self.samples.setMovement(QListWidget.Static)
        self.samples.setFixedHeight(220)
        self.samples.setSpacing(2)
        self.samples.setFocusPolicy(Qt.NoFocus)
        self.samples.itemClicked.connect(self._on_sample)
        b_del = QPushButton("선택 샘플 삭제")
        b_del.clicked.connect(self._delete_sample)

        inner = QVBoxLayout()
        inner.setContentsMargins(4, 0, 4, 4)
        inner.addWidget(_title("보정 대상"))
        inner.addWidget(self.tcombo)
        inner.addWidget(self.tinfo)
        inner.addWidget(self.before)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        inner.addWidget(line)
        inner.addLayout(g)
        for w in (self.b_clear, self.b_save_def, self.b_sharp, self.b_del_still):
            inner.addWidget(w)
        inner.addWidget(_title(f"보정 샘플 (G 키, 최대 {MAX_SAMPLES}장) — 클릭하면 이동"))
        inner.addWidget(self.samples)
        inner.addWidget(b_del)
        inner.addStretch(1)
        box = QWidget()
        box.setLayout(inner)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(box)
        sc.setFrameShape(QFrame.NoFrame)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(sc)
        self.setMinimumWidth(330)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._emit_change)

        state.changed.connect(self._on_state)
        self._fill_luts()
        self._fill_targets()

    # ------------------------------------------------------------ 대상
    def set_current_source(self, sid: str):
        self.cur_sid = sid
        if self.target[0] == "src":
            self.target = ("src", sid)
        self._fill_targets()

    def _fill_targets(self):
        p = self.state.project
        self.tcombo.clear()
        self.tcombo.addItem("기본값 (모든 클립 공통)", BASE)
        s = p.source(self.cur_sid)
        if s:
            self.tcombo.addItem(f"현재 클립만: {s.name}" + (" ●" if s.grade else ""), ("src", s.id))
        for i, m in enumerate(p.stills):
            ms = p.source(m.src)
            if ms and ms.frames:
                self.tcombo.addItem(f"스틸 {i + 1}: {ms.name[-14:]} {timecode(m.frame, ms.fps)}" +
                                    (" ●" if m.grade else ""), ("still", m.id))
        idx = next((i for i in range(self.tcombo.count()) if tuple(self.tcombo.itemData(i)) == tuple(self.target)), 0)
        if idx == 0:
            self.target = BASE
        self.tcombo.setCurrentIndex(idx)
        self._load_controls()

    def _on_target(self, i):
        self.target = tuple(self.tcombo.itemData(i))
        if self.target[0] == "still":
            m = self._still()
            if m:
                self.seekRequested.emit(m.src, m.frame)
        self._load_controls()
        self.gradeChanged.emit()

    def select_still(self, still_id: str):
        self.target = ("still", still_id)
        self._fill_targets()
        self.gradeChanged.emit()

    def _still(self):
        return next((m for m in self.state.project.stills if m.id == self.target[1]), None)

    def _target_dict(self) -> dict:
        kind, tid = self.target
        p = self.state.project
        if kind == "src" and p.source(tid):
            return p.source(tid).grade
        if kind == "still" and self._still():
            return self._still().grade
        return p.grade

    def _effective(self) -> dict:
        kind, tid = self.target
        p = self.state.project
        if kind == "src" and p.source(tid):
            return p.grade_for_source(tid)
        if kind == "still" and self._still():
            return p.grade_for_still(self._still())
        return dict(p.grade)

    def preview_grade(self, sid: str, frame: int) -> dict:
        """화면 미리보기에 쓸 보정값."""
        p = self.state.project
        m = self._still() if self.target[0] == "still" else None
        if m and m.src == sid and m.frame == frame:
            return p.grade_for_still(m)
        return p.grade_for_source(sid)

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
        info = {"base": "모든 클립에 적용됩니다. 클립·스틸에서 바꾼 항목은 그쪽 값이 우선합니다.",
                "src": "이 클립에서 바꾼 항목만 덮어씁니다 (↺ 표시된 항목).",
                "still": "클립 보정 위에 추가로 적용, 4K TIFF 로 출력됩니다. 노이즈 ‘강’ 사용 가능."}
        self.tinfo.setText(info[kind])
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
        for lv in ["off", "weak", "mid"] + (["strong"] if kind == "still" else []):
            self.nr.addItem(NR_LABELS[lv], lv)
        self.nr.setCurrentIndex(max(0, self.nr.findData(e["nr"])))
        for w in widgets:
            w.blockSignals(False)
        self.curve.set_points(e["curve"])
        self._update_labels()
        self.b_clear.setVisible(kind != "base")
        self.b_save_def.setVisible(kind == "base")
        self.b_sharp.setVisible(kind == "still")
        self.b_del_still.setVisible(kind == "still")

    def _update_labels(self):
        e = self._effective()
        over = self._target_dict() if self.target[0] != "base" else {}
        self.vals["r_gain"].setText(f"{e['r_gain']:.2f}")
        self.vals["b_gain"].setText(f"{e['b_gain']:.2f}")
        self.vals["hue"].setText(f"{e['hue']:+.1f}°")
        self.vals["sharpen"].setText(f"{e['sharpen']:.2f}")
        for k, b in self.resets.items():
            b.setVisible(k in over)

    def _set(self, key, value, slider=False):
        self._target_dict()[key] = value
        self.state.dirty = True
        self._update_labels()
        if slider:
            self._debounce.start()
        else:
            self._emit_change()

    def _emit_change(self):
        self._relabel_target()
        self.gradeChanged.emit()
        self.refresh_samples()

    def _relabel_target(self):
        i = self.tcombo.currentIndex()
        if i > 0:
            t = self.tcombo.itemText(i).rstrip(" ●")
            self.tcombo.setItemText(i, t + (" ●" if self._target_dict() else ""))

    def _clear_key(self, key):
        self._target_dict().pop(key, None)
        self._load_controls()
        self._emit_change()

    def _clear_all(self):
        self._target_dict().clear()
        self._load_controls()
        self._emit_change()

    def _save_default(self):
        save_default_grade(self.state.project.grade)
        QMessageBox.information(self, "저장", "새 프로젝트를 만들 때 이 값이 기본으로 들어갑니다.")

    # ------------------------------------------------------------ 샘플 썸네일
    def refresh_samples(self):
        p = self.state.project
        self.gen += 1
        gen = self.gen
        before = self.before.isChecked()
        self.samples.clear()
        for m in p.samples:
            s = p.source(m.src)
            if not s or not s.frames:
                continue
            it = QListWidgetItem(f"{timecode(m.frame, s.fps)}")
            it.setToolTip(f"{s.name} #{m.frame}")
            it.setData(Qt.UserRole, m.id)
            if m.id in self.thumbs_pix:
                it.setIcon(self.thumbs_pix[m.id])
            self.samples.addItem(it)
            grade = None if before else p.grade_for_source(s.id)

            def work(s=s, fr=m.frame, grade=grade):
                return ff.render_preview(ff.cached_frame(s, fr), grade)

            job = jobs.Job(work)
            job.signals.done.connect(lambda data, mid=m.id, gn=gen: self._on_thumb(gn, mid, data))
            jobs.submit(jobs.PREVIEW_POOL, job, priority=-1)

    def _on_thumb(self, gen, mid, data):
        if gen != self.gen:
            return
        pix = QPixmap.fromImage(QImage.fromData(data, "PNG")).scaled(288, 162, Qt.KeepAspectRatio,
                                                                       Qt.SmoothTransformation)
        self.thumbs_pix[mid] = pix
        for i in range(self.samples.count()):
            it = self.samples.item(i)
            if it.data(Qt.UserRole) == mid:
                it.setIcon(pix)

    def _on_sample(self, it):
        m = next((x for x in self.state.project.samples if x.id == it.data(Qt.UserRole)), None)
        if m:
            self.seekRequested.emit(m.src, m.frame)

    def _delete_sample(self):
        it = self.samples.currentItem()
        if it:
            mid = it.data(Qt.UserRole)
            self.state.project.samples = [m for m in self.state.project.samples if m.id != mid]
            self.state.touch("markers")

    def _delete_still(self):
        m = self._still()
        if m:
            self.state.project.stills.remove(m)
            self.target = BASE
            self.state.touch("markers")

    def _find_sharp(self):
        m = self._still()
        if not m:
            return
        s = self.state.project.source(m.src)
        self.b_sharp.setEnabled(False)
        self.b_sharp.setText("분석 중…")
        job = jobs.Job(lambda: ff.sharpness_around(s, m.frame))

        def restore():
            self.b_sharp.setEnabled(True)
            self.b_sharp.setText("선명한 프레임 찾기 (앞뒤 5프레임)")

        def done(res):
            restore()
            best_f, best_v = max(res, key=lambda x: x[1])
            cur_v = dict(res).get(m.frame, 0)
            if best_f == m.frame:
                QMessageBox.information(self, "선명도", "현재 프레임이 가장 선명합니다.")
                return
            txt = (f"가장 선명한 프레임: {best_f - m.frame:+d}프레임 (#{best_f})\n"
                   f"선명도 점수: 현재 {cur_v:.0f} → {best_v:.0f}\n\n스틸을 이 프레임으로 옮길까요?")
            if QMessageBox.question(self, "선명도", txt) == QMessageBox.Yes:
                m.frame = best_f
                self.state.touch("markers")
                self.seekRequested.emit(m.src, m.frame)

        def err(msg):
            restore()
            QMessageBox.warning(self, "오류", msg[-300:])

        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.PREVIEW_POOL, job)

    # ------------------------------------------------------------ 상태
    def _on_state(self, what):
        if what in ("project", "sources", "markers"):
            self._fill_targets()
            self.refresh_samples()
