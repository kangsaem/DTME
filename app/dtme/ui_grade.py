"""보정 탭: 대상(기본값/클립/스틸) 선택, 샘플 미리보기, 보정 조절."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSlider,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from . import ff, jobs, paths
from .project import FACTORY_GRADE, NR_LABELS, save_default_grade, timecode
from .state import AppState
from .ui_curve import CurveEditor

BASE = ("base", "")


class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#111; color:#888;")
        self._pix: QPixmap | None = None

    def set_image(self, pix: QPixmap | None, text=""):
        self._pix = pix
        if pix is None:
            self.setPixmap(QPixmap())
            self.setText(text)
        else:
            self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class GradeTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.target = BASE
        self.gen = 0
        self.focus_key = None       # 크게 볼 프레임 key
        self.images: dict[str, QPixmap] = {}

        # --- 대상 목록
        self.targets = QListWidget()
        self.targets.setWordWrap(True)
        self.targets.setTextElideMode(Qt.ElideMiddle)
        self.targets.currentItemChanged.connect(self._on_target)
        tl = QVBoxLayout()
        tl.addWidget(QLabel("보정 대상"))
        tl.addWidget(self.targets, 1)
        self.b_del_still = QPushButton("스틸 삭제")
        self.b_del_still.clicked.connect(self._delete_still)
        tl.addWidget(self.b_del_still)
        tw = QWidget()
        tw.setLayout(tl)

        # --- 미리보기
        self.preview = PreviewLabel()
        self.before = QCheckBox("보정 전 보기 (B)")
        self.before.toggled.connect(lambda _: self.refresh_preview())
        self.caption = QLabel("")
        self.caption.setStyleSheet("color:#aaa;")
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setIconSize(QSize(192, 108))
        self.thumbs.setFixedHeight(150)
        self.thumbs.setFlow(QListWidget.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.currentItemChanged.connect(self._on_thumb)
        b_del_sample = QPushButton("선택 샘플 삭제")
        b_del_sample.clicked.connect(self._delete_sample)
        pv = QVBoxLayout()
        pv.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(self.caption, 1)
        row.addWidget(self.before)
        pv.addLayout(row)
        pv.addWidget(self.thumbs)
        row2 = QHBoxLayout()
        hint = QLabel("샘플은 편집 탭에서 G 키로 지정(최대 5장). 미리보기는 최종 렌더와 같은 FFmpeg 처리로 만듭니다.")
        hint.setStyleSheet("color:#888; font-size:11px;")
        row2.addWidget(hint, 1)
        row2.addWidget(b_del_sample)
        pv.addLayout(row2)
        pw = QWidget()
        pw.setLayout(pv)

        # --- 조절
        self.ctrl = QGroupBox("기본값")
        g = QGridLayout(self.ctrl)
        self.resets = {}
        self.vals = {}
        r = 0

        def add_row(key, title, widget, val_label=True):
            nonlocal r
            g.addWidget(QLabel(title), r, 0)
            g.addWidget(widget, r, 1)
            if val_label:
                lab = QLabel("")
                lab.setMinimumWidth(48)
                self.vals[key] = lab
                g.addWidget(lab, r, 2)
            rb = QToolButton()
            rb.setText("↺")
            rb.setToolTip("이 항목 덮어쓰기 해제(기본값 사용)")
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
        b2 = QPushButton("LUT 폴더 새로고침")
        b2.clicked.connect(self._fill_luts)
        lb.addWidget(b1)
        lb.addWidget(b2)
        g.addLayout(lb, r, 1)
        r += 1

        def slider(lo, hi, key, scale):
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.valueChanged.connect(lambda v, k=key, sc=scale: self._set(k, round(v / sc, 3), slider=True))
            s.sliderReleased.connect(self.refresh_preview)
            return s

        self.r_gain = slider(70, 150, "r_gain", 100)
        add_row("r_gain", "R 게인", self.r_gain)
        self.b_gain = slider(70, 150, "b_gain", 100)
        add_row("b_gain", "B 게인", self.b_gain)
        self.hue = slider(-30, 30, "hue", 2)
        add_row("hue", "Hue 회전", self.hue)
        self.curve = CurveEditor()
        self.curve.changed.connect(lambda pts: self._set("curve", pts))
        add_row("curve", "커브", self.curve, False)
        b3 = QPushButton("커브 초기화")
        b3.clicked.connect(self.curve.reset)
        g.addWidget(b3, r, 1)
        r += 1
        self.nr = QComboBox()
        self.nr.activated.connect(lambda _: self._set("nr", self.nr.currentData()))
        add_row("nr", "노이즈 제거", self.nr, False)
        self.sharp = slider(0, 100, "sharpen", 100)
        add_row("sharpen", "샤픈", self.sharp)

        self.b_clear = QPushButton("이 대상의 덮어쓰기 모두 해제")
        self.b_clear.clicked.connect(self._clear_all)
        g.addWidget(self.b_clear, r, 0, 1, 4)
        r += 1
        self.b_save_def = QPushButton("현재 기본값을 '새 프로젝트 기본값'으로 저장")
        self.b_save_def.clicked.connect(self._save_default)
        g.addWidget(self.b_save_def, r, 0, 1, 4)
        r += 1
        self.b_sharp = QPushButton("선명한 프레임 찾기 (앞뒤 5프레임)")
        self.b_sharp.clicked.connect(self._find_sharp)
        g.addWidget(self.b_sharp, r, 0, 1, 4)
        r += 1
        g.setRowStretch(r, 1)
        g.setColumnStretch(1, 1)

        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(tw)
        sp.addWidget(pw)
        sp.addWidget(self.ctrl)
        sp.setSizes([260, 800, 380])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(sp)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.refresh_preview)

        state.changed.connect(self._on_state)
        self._fill_luts()
        self._fill_targets()

    # ------------------------------------------------------------ 대상
    def _fill_targets(self):
        p = self.state.project
        self.targets.blockSignals(True)
        self.targets.clear()
        items = [("기본값 (전체 클립 공통)", BASE)]
        for s in p.sources:
            mark = " ●" if s.grade else ""
            items.append((f"클립: {s.name}{mark}", ("src", s.id)))
        for i, m in enumerate(p.stills):
            s = p.source(m.src)
            if s:
                mark = " ●" if m.grade else ""
                items.append((f"스틸 {i + 1}: {s.name} {timecode(m.frame, s.fps)}{mark}", ("still", m.id)))
        sel = None
        for text, key in items:
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, key)
            self.targets.addItem(it)
            if key == self.target:
                sel = it
        if sel is None:
            self.target = BASE
            sel = self.targets.item(0)
        self.targets.setCurrentItem(sel)
        self.targets.blockSignals(False)
        self._load_controls()

    def _on_target(self, cur, _):
        if cur is None:
            return
        self.target = tuple(cur.data(Qt.UserRole))
        self.focus_key = None
        self._load_controls()
        self.refresh_preview()

    def _target_dict(self) -> dict:
        kind, tid = self.target
        p = self.state.project
        if kind == "src":
            return p.source(tid).grade
        if kind == "still":
            return self._still().grade
        return p.grade

    def _still(self):
        return next((m for m in self.state.project.stills if m.id == self.target[1]), None)

    def _effective(self) -> dict:
        kind, tid = self.target
        p = self.state.project
        if kind == "src":
            return p.grade_for_source(tid)
        if kind == "still":
            return p.grade_for_still(self._still())
        return dict(p.grade)

    # ------------------------------------------------------------ 조절값
    def _fill_luts(self):
        cur = self.lut.currentData()
        self.lut.clear()
        self.lut.addItem("없음", "")
        for n in ff.list_luts():
            self.lut.addItem(n, n)
        i = self.lut.findData(cur)
        self.lut.setCurrentIndex(max(0, i))

    def _add_lut(self):
        f, _ = QFileDialog.getOpenFileName(self, "LUT 추가", "", "LUT (*.cube *.3dl)")
        if f:
            shutil.copy(f, paths.lut_dir() / Path(f).name)
            self._fill_luts()
            i = self.lut.findData(Path(f).name)
            self.lut.setCurrentIndex(i)
            self._set("lut", Path(f).name)

    def _load_controls(self):
        kind = self.target[0]
        e = self._effective()
        over = self._target_dict() if kind != "base" else {}
        titles = {"base": "기본값 — 모든 클립에 적용", "src": "클립 보정 (바꾼 항목만 덮어씀)",
                  "still": "스틸 보정 (클립 보정 위에 추가, 4K 출력)"}
        self.ctrl.setTitle(titles[kind])
        widgets = [self.lut, self.r_gain, self.b_gain, self.hue, self.nr, self.sharp]
        for w in widgets:
            w.blockSignals(True)
        if self.lut.findData(e["lut"]) < 0 and e["lut"]:
            self.lut.addItem(f"{e['lut']} (없음!)", e["lut"])
        self.lut.setCurrentIndex(max(0, self.lut.findData(e["lut"])))
        self.r_gain.setValue(round(e["r_gain"] * 100))
        self.b_gain.setValue(round(e["b_gain"] * 100))
        self.hue.setValue(round(e["hue"] * 2))
        self.sharp.setValue(round(e["sharpen"] * 100))
        self.nr.clear()
        levels = ["off", "weak", "mid"] + (["strong"] if kind == "still" else [])
        for lv in levels:
            self.nr.addItem(NR_LABELS[lv], lv)
        self.nr.setCurrentIndex(max(0, self.nr.findData(e["nr"])))
        for w in widgets:
            w.blockSignals(False)
        self.curve.set_points(e["curve"])
        self._update_labels(e, over)
        self.b_clear.setVisible(kind != "base")
        self.b_save_def.setVisible(kind == "base")
        self.b_sharp.setVisible(kind == "still")
        self.b_del_still.setEnabled(kind == "still")

    def _update_labels(self, e=None, over=None):
        e = e or self._effective()
        if over is None:
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
        self._mark_target_text()
        if slider:
            self._debounce.start()
        else:
            self.refresh_preview()

    def _clear_key(self, key):
        self._target_dict().pop(key, None)
        self._after_override_change()

    def _clear_all(self):
        self._target_dict().clear()
        self._after_override_change()

    def _after_override_change(self):
        self.state.dirty = True
        self._load_controls()
        self._mark_target_text()
        self.refresh_preview()

    def _mark_target_text(self):
        it = self.targets.currentItem()
        if it and self.target[0] != "base":
            t = it.text().rstrip(" ●")
            it.setText(t + (" ●" if self._target_dict() else ""))

    def _save_default(self):
        save_default_grade(self.state.project.grade)
        QMessageBox.information(self, "저장", "새 프로젝트를 만들 때 이 값이 기본으로 들어갑니다.")

    # ------------------------------------------------------------ 미리보기
    def _frames(self):
        """(key, source, frame, grade) 목록"""
        p = self.state.project
        kind, tid = self.target
        if kind == "still":
            m = self._still()
            s = p.source(m.src)
            return [(f"still_{m.id}", s, m.frame, p.grade_for_still(m))]
        out = []
        for m in p.samples:
            s = p.source(m.src)
            if s:
                out.append((f"sample_{m.id}", s, m.frame, p.grade_for_source(s.id)))
        if kind == "src" and not any(f[1].id == tid for f in out):
            s = p.source(tid)   # 이 클립에 샘플이 없으면 가운데 프레임을 임시로 사용
            out.insert(0, (f"mid_{s.id}", s, s.frames // 2, p.grade_for_source(s.id)))
        return out

    def refresh_preview(self):
        frames = self._frames()
        self.gen += 1
        gen = self.gen
        before = self.before.isChecked()
        keys = [f[0] for f in frames]
        if self.focus_key not in keys:
            self.focus_key = keys[0] if keys else None
        # 썸네일 목록 재구성
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for key, s, fr, _g in frames:
            it = QListWidgetItem(f"{s.name[-12:]}  {timecode(fr, s.fps)}")
            it.setToolTip(f"{s.name} #{fr}")
            it.setData(Qt.UserRole, key)
            if key in self.images:
                it.setIcon(self.images[key])
            self.thumbs.addItem(it)
            if key == self.focus_key:
                self.thumbs.setCurrentItem(it)
        self.thumbs.blockSignals(False)
        if not frames:
            self.preview.set_image(None, "편집 탭에서 G 키로 보정 샘플을 지정하세요 (최대 5장)")
            self.caption.setText("")
            return
        self._show_focus()
        gpu = self.state.project.output.gpu_decode
        for key, s, fr, g in frames:
            grade = None if before else dict(g)

            def work(s=s, fr=fr, grade=grade):
                c = ff.cached_frame(s, fr, gpu=False)
                return ff.render_preview(c, grade)

            job = jobs.Job(work)
            job.signals.done.connect(lambda data, k=key, gn=gen: self._on_img(gn, k, data))
            job.signals.error.connect(lambda msg, gn=gen: gn == self.gen and self.caption.setText(f"미리보기 오류: {msg[-200:]}"))
            jobs.submit(jobs.PREVIEW_POOL, job)

    def _on_img(self, gen, key, data):
        if gen != self.gen:
            return
        img = QImage.fromData(data, "PNG")
        pix = QPixmap.fromImage(img)
        self.images[key] = pix
        for i in range(self.thumbs.count()):
            it = self.thumbs.item(i)
            if it.data(Qt.UserRole) == key:
                it.setIcon(pix)
        if key == self.focus_key:
            self._show_focus()

    def _show_focus(self):
        frames = {f[0]: f for f in self._frames()}
        f = frames.get(self.focus_key)
        if not f:
            return
        _k, s, fr, _g = f
        self.caption.setText(f"{s.name}  {timecode(fr, s.fps)}  (#{fr})" + ("  — 보정 전" if self.before.isChecked() else ""))
        pix = self.images.get(self.focus_key)
        self.preview.set_image(pix, "미리보기 생성 중…")

    def _on_thumb(self, cur, _):
        if cur is not None:
            self.focus_key = cur.data(Qt.UserRole)
            self._show_focus()

    def _delete_sample(self):
        it = self.thumbs.currentItem()
        if not it:
            return
        key = it.data(Qt.UserRole)
        if key.startswith("sample_"):
            sid = key[len("sample_"):]
            self.state.project.samples = [m for m in self.state.project.samples if m.id != sid]
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

        def done(res):
            self.b_sharp.setEnabled(True)
            self.b_sharp.setText("선명한 프레임 찾기 (앞뒤 5프레임)")
            best_f, best_v = max(res, key=lambda x: x[1])
            cur_v = dict(res).get(m.frame, 0)
            if best_f == m.frame:
                QMessageBox.information(self, "선명도", "현재 프레임이 가장 선명합니다.")
                return
            txt = (f"가장 선명한 프레임: #{best_f} ({best_f - m.frame:+d}프레임)\n"
                   f"선명도 점수: 현재 {cur_v:.0f} → {best_v:.0f}\n\n이 프레임으로 옮길까요?")
            if QMessageBox.question(self, "선명도", txt) == QMessageBox.Yes:
                m.frame = best_f
                self.state.touch("markers")

        def err(msg):
            self.b_sharp.setEnabled(True)
            self.b_sharp.setText("선명한 프레임 찾기 (앞뒤 5프레임)")
            QMessageBox.warning(self, "오류", msg[-300:])

        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.PREVIEW_POOL, job)

    # ------------------------------------------------------------ 상태
    def _on_state(self, what):
        if what in ("project", "sources", "markers"):
            self._fill_targets()
            if self.isVisible():
                self.refresh_preview()

    def showEvent(self, e):
        super().showEvent(e)
        self._fill_luts()
        self._load_controls()
        self.refresh_preview()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_B:
            self.before.toggle()
        else:
            super().keyPressEvent(e)


_ = FACTORY_GRADE
