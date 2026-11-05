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
from .project import save_default_grade, timecode
from .state import AppState
from .ui_curve import CurveEditor
from .ui_render import fix_size

BASE = ("base", "")
N_SAMPLES = 6
TILE_W, TILE_H = 150, 84


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
        b_reset = QPushButton("리셋")
        fix_size(b_reset)
        b_reset.setToolTip("이 클립의 조정값을 초기값으로 (LUT 유지)")
        b_reset.clicked.connect(self._reset_clip)
        b_base = QPushButton("기본값")
        fix_size(b_base)
        b_base.setToolTip("이 클립을 기본값으로 되돌림")
        b_base.clicked.connect(self._clear_all)
        b_def = QPushButton("기본값으로 저장")
        b_def.setFixedSize(2 * 76 - 40, 28)     # 글자가 길어 유일하게 넓음(일반 높이)
        b_def.setToolTip("이 클립의 값을 모든 클립의 기본값으로")
        b_def.clicked.connect(self._save_default)
        for b in (b_reset, b_base):
            head.addWidget(b)
        head.addStretch(1)
        head.addWidget(b_def)

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
        orow.addWidget(self.audio)
        orow.addStretch(1)
        self.orient.buttonClicked.connect(self._on_output)
        self.audio.toggled.connect(self._on_output)

        self.before = QCheckBox("보정 전 보기")
        self.before.setToolTip("B")
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
            rb.clicked.connect(lambda _=False, k=key: self._clear_key(k))
            self.resets[key] = rb
            g.addWidget(rb, r, 3)
            r += 1

        self.lut = QComboBox()
        self.lut.activated.connect(lambda _: self._set("lut", self.lut.currentData()))
        add_row("lut", "LUT", self.lut, False)
        lb = QHBoxLayout()
        b1 = QPushButton("LUT 추가…")
        fix_size(b1)
        b1.clicked.connect(self._add_lut)
        b2 = QPushButton("새로고침")
        fix_size(b2)
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
            s.valueChanged.connect(lambda v, k=key, sc=scale: self._set(k, v if sc == 1 else round(v / sc, 3),
                                                                        slider=True))
            return s

        self.r_gain = slider(70, 150, "r_gain", 100, "")
        add_row("r_gain", "R", self.r_gain)
        self.b_gain = slider(70, 150, "b_gain", 100, "")
        add_row("b_gain", "B", self.b_gain)
        self.hue = slider(-30, 30, "hue", 2, "")
        add_row("hue", "Hue", self.hue)
        self.sharp = slider(0, 100, "sharpen", 100, "")
        add_row("sharpen", "샤픈", self.sharp)
        g.addWidget(QLabel("커브"), r, 0, Qt.AlignTop)
        self.curve = CurveEditor()
        self.curve.changed.connect(lambda pts: self._set("curve", pts))
        g.addWidget(self.curve, r, 1, 1, 2)
        rb = QToolButton()
        rb.setText("↺")
        rb.clicked.connect(lambda: self._clear_key("curve"))
        self.resets["curve"] = rb
        g.addWidget(rb, r, 3, Qt.AlignTop)
        r += 1
        crow = QHBoxLayout()
        crow.addStretch(1)
        b3 = QPushButton("커브리셋")
        fix_size(b3)
        b3.clicked.connect(self.curve.reset)
        crow.addWidget(b3)
        g.addLayout(crow, r, 1, 1, 2)
        r += 1
        # 디노이즈: 색 노이즈 / 밝기 노이즈
        self.nr_c = slider(0, 100, "nr_chroma", 1, "")
        add_row("nr_chroma", "색 노이즈", self.nr_c)
        self.nr_l = slider(0, 100, "nr_luma", 1, "")
        add_row("nr_luma", "밝기 노이즈", self.nr_l)
        self.stab = slider(0, 100, "stab", 1, "렌더에만 적용")
        add_row("stab", "흔들림 보정", self.stab)
        g.setColumnStretch(1, 1)


        # --- 샘플 썸네일
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

        inner = QVBoxLayout()
        inner.setContentsMargins(4, 4, 4, 4)
        inner.addLayout(head)
        inner.addLayout(orow)
        inner.addWidget(self.before)
        inner.addLayout(g)
        inner.addStretch(1)
        inner.addWidget(self.samples)
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
        widgets = [self.lut, self.r_gain, self.b_gain, self.hue, self.nr_c, self.nr_l, self.sharp, self.stab]
        for w in widgets:
            w.blockSignals(True)
        if e["lut"] and self.lut.findData(e["lut"]) < 0:
            self.lut.addItem(f"{e['lut']} (파일 없음)", e["lut"])
        self.lut.setCurrentIndex(max(0, self.lut.findData(e["lut"])))
        self.r_gain.setValue(round(e["r_gain"] * 100))
        self.b_gain.setValue(round(e["b_gain"] * 100))
        self.hue.setValue(round(e["hue"] * 2))
        self.sharp.setValue(round(e["sharpen"] * 100))
        self.nr_c.setValue(int(round(e.get("nr_chroma", 0))))
        self.nr_l.setValue(int(round(e.get("nr_luma", 0))))
        self.stab.setValue(int(round(e.get("stab", 0))))
        for w in widgets:
            w.blockSignals(False)
        self.curve.set_points(e["curve"])
        self._update_labels()

    def _update_labels(self):
        e = self._effective()
        over = self._target_dict() if self.target[0] == "src" else {}
        self.vals["r_gain"].setText(f"{e['r_gain']:.2f}")
        self.vals["b_gain"].setText(f"{e['b_gain']:.2f}")
        self.vals["hue"].setText(f"{e['hue']:+.1f}°")
        self.vals["sharpen"].setText(f"{e['sharpen']:.2f}")
        self.vals["nr_chroma"].setText(f"{int(e.get('nr_chroma', 0))}")
        self.vals["nr_luma"].setText(f"{int(e.get('nr_luma', 0))}")
        self.vals["stab"].setText(f"{int(e.get('stab', 0))}" if e.get("stab", 0) else "끔")
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
        pass

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
        before = self.before.isChecked()
        self.samples.clear()
        if not s or not s.frames:
            return
        marks = [m for m in p.samples if m.src == s.id]
        grade = None if before else p.grade_for_source(s.id)
        for m in marks:
            it = QListWidgetItem("")
            it.setToolTip(timecode(m.frame, s.fps))
            it.setSizeHint(QSize(self.tile[0] + 4, self.tile[1] + 4))
            it.setData(Qt.UserRole, m.id)
            if m.id in self.pix:
                it.setIcon(self.pix[m.id])
            self.samples.addItem(it)
            out = sample_dir() / f"{s.id}_{m.frame}{'_raw' if before else ''}.png"

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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_tiles()

    def _fit_tiles(self):
        avail = max(160, self.width() - 22)
        tw = (avail - 8) // 2
        th = tw * 9 // 16
        if (tw, th) == self.tile and self.samples.width() == avail:
            return
        self.tile = (tw, th)
        self.samples.setIconSize(QSize(tw, th))
        self.samples.setGridSize(QSize(tw + 4, th + 4))
        self.samples.setFixedSize(2 * (tw + 4) + 4, 3 * (th + 4) + 4)
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
