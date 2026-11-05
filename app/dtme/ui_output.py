"""출력 탭: 영상 렌더(소스별/이어붙이기), 스틸 4K TIFF."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
                               QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
                               QHeaderView, QAbstractItemView)

from . import ff, jobs
from .project import OUTPUT_LIMIT_SEC, timecode
from .state import AppState


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        p = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not p.exists():
            return p
        i += 1


class OutputTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.job = None
        self.queue = []

        box = QGroupBox("영상 출력 설정")
        f = QFormLayout(box)
        self.orient = QButtonGroup(self)
        orow = QHBoxLayout()
        for i, (k, t) in enumerate((("horizontal", "가로 1920×1080"), ("vertical", "세로 1080×1920 (중앙 크롭)"))):
            rb = QRadioButton(t)
            rb.setProperty("key", k)
            self.orient.addButton(rb, i)
            orow.addWidget(rb)
        orow.addStretch(1)
        f.addRow("화면", orow)
        self.mode = QButtonGroup(self)
        mrow = QHBoxLayout()
        for i, (k, t) in enumerate((("per_source", "소스 영상마다 1개"), ("concat", "전체 구간 이어붙여 1개"))):
            rb = QRadioButton(t)
            rb.setProperty("key", k)
            self.mode.addButton(rb, i)
            mrow.addWidget(rb)
        mrow.addStretch(1)
        f.addRow("구성", mrow)
        self.audio = QCheckBox("오디오 포함 (배속 구간은 음 높이 유지하며 속도 변경)")
        f.addRow("오디오", self.audio)
        self.encoder = QComboBox()
        self.encoder.addItem("NVENC (GPU, 빠름)", "nvenc")
        self.encoder.addItem("x264 (CPU, 느림·고품질)", "x264")
        f.addRow("인코더", self.encoder)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(8, 100)
        self.bitrate.setSuffix(" Mbps")
        f.addRow("비트레이트", self.bitrate)
        self.gpu = QCheckBox("GPU 디코딩 사용 (실패 시 자동으로 CPU)")
        f.addRow("디코딩", self.gpu)
        frow = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("비우면 원본 영상과 같은 폴더의 'DTME_출력'")
        b = QPushButton("선택…")
        b.clicked.connect(self._pick_folder)
        frow.addWidget(self.folder, 1)
        frow.addWidget(b)
        f.addRow("저장 폴더", frow)
        f.addRow("", QLabel("29.97fps · H.264 · BT.709 고정"))

        for w in (self.orient, self.mode):
            w.buttonToggled.connect(lambda *_: self._save())
        self.audio.toggled.connect(lambda *_: self._save())
        self.gpu.toggled.connect(lambda *_: self._save())
        self.encoder.activated.connect(lambda *_: self._save())
        self.bitrate.valueChanged.connect(lambda *_: self._save())
        self.folder.editingFinished.connect(self._save)

        self.plan = QTableWidget(0, 3)
        self.plan.setHorizontalHeaderLabels(["출력 파일", "구간", "길이"])
        self.plan.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.plan.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.b_render = QPushButton("영상 렌더")
        self.b_render.setMinimumHeight(34)
        self.b_render.clicked.connect(self.render_videos)
        self.b_still = QPushButton("스틸 출력 (4K 16bit TIFF)")
        self.b_still.setMinimumHeight(34)
        self.b_still.clicked.connect(self.render_stills)
        self.b_cancel = QPushButton("취소")
        self.b_cancel.clicked.connect(self._cancel)
        self.b_cancel.setEnabled(False)
        self.b_open = QPushButton("출력 폴더 열기")
        self.b_open.clicked.connect(self._open_folder)
        brow = QHBoxLayout()
        for w in (self.b_render, self.b_still, self.b_cancel, self.b_open):
            brow.addWidget(w)
        self.progress = QProgressBar()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)

        box.setMaximumWidth(900)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addWidget(QLabel("출력 예정"))
        lay.addWidget(self.plan, 1)
        lay.addLayout(brow)
        lay.addWidget(self.progress)
        lay.addWidget(self.log, 1)
        state.changed.connect(lambda w: w != "output" and self._load())
        self._load()

    # ------------------------------------------------------------ 설정
    def _load(self):
        o = self.state.project.output
        for grp, val in ((self.orient, o.orientation), (self.mode, o.mode)):
            grp.blockSignals(True)
            for b in grp.buttons():
                b.setChecked(b.property("key") == val)
            grp.blockSignals(False)
        for w in (self.audio, self.gpu, self.encoder, self.bitrate):
            w.blockSignals(True)
        self.audio.setChecked(o.audio)
        self.gpu.setChecked(o.gpu_decode)
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(o.encoder)))
        self.bitrate.setValue(o.bitrate_mbps)
        for w in (self.audio, self.gpu, self.encoder, self.bitrate):
            w.blockSignals(False)
        self.folder.setText(o.folder)
        self._refresh_plan()

    def _save(self):
        o = self.state.project.output
        o.orientation = self.orient.checkedButton().property("key") if self.orient.checkedButton() else "horizontal"
        o.mode = self.mode.checkedButton().property("key") if self.mode.checkedButton() else "per_source"
        o.audio = self.audio.isChecked()
        o.gpu_decode = self.gpu.isChecked()
        o.encoder = self.encoder.currentData()
        o.bitrate_mbps = self.bitrate.value()
        o.folder = self.folder.text().strip()
        self.state.touch("output")
        self._refresh_plan()

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더")
        if d:
            self.folder.setText(d)
            self._save()

    def _out_dir(self) -> Path:
        o = self.state.project.output
        if o.folder:
            d = Path(o.folder)
        elif self.state.project.sources:
            d = Path(self.state.project.sources[0].path).parent / "DTME_출력"
        else:
            d = Path.home() / "DTME_출력"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _open_folder(self):
        d = self._out_dir()
        if os.name == "nt":
            os.startfile(str(d))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(d)])

    # ------------------------------------------------------------ 계획
    def plan_outputs(self):
        """[(파일이름, 세그먼트 목록)]"""
        p = self.state.project
        tag = "V" if p.output.orientation == "vertical" else "H"
        if p.output.mode == "concat":
            return [(f"DTME_{time.strftime('%Y%m%d_%H%M')}_{tag}.mp4", list(p.segments))] if p.segments else []
        out = []
        for s in p.sources:
            segs = p.segments_of(s.id)
            if segs:
                out.append((f"{Path(s.path).stem}_{tag}.mp4", segs))
        return out

    def _refresh_plan(self):
        p = self.state.project
        plan = self.plan_outputs()
        rows = [(n, f"{len(segs)}개", sum(p.seg_out_seconds(g, p.source(g.src).fps) for g in segs)) for n, segs in plan]
        rows += [(f"{Path(p.source(m.src).path).stem}_f{m.frame}.tif", timecode(m.frame, p.source(m.src).fps), None)
                 for m in p.stills if p.source(m.src)]
        self.plan.setRowCount(len(rows))
        for r, (n, c, sec) in enumerate(rows):
            self.plan.setItem(r, 0, QTableWidgetItem(n))
            self.plan.setItem(r, 1, QTableWidgetItem(c))
            it = QTableWidgetItem("스틸 4K" if sec is None else f"{sec:.2f}초")
            if sec is not None and sec > OUTPUT_LIMIT_SEC:
                it.setForeground(Qt.red)
                it.setText(f"{sec:.2f}초 (30초 초과)")
            self.plan.setItem(r, 2, it)

    # ------------------------------------------------------------ 실행
    def _busy(self, on):
        self.b_render.setEnabled(not on)
        self.b_still.setEnabled(not on)
        self.b_cancel.setEnabled(on)

    def _say(self, t):
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {t}")

    def render_videos(self):
        plan = self.plan_outputs()
        if not plan:
            self._say("렌더할 구간이 없습니다. 편집 탭에서 I/O 로 구간을 지정하세요.")
            return
        out_dir = self._out_dir()
        self.queue = [("video", _unique(out_dir / n), segs) for n, segs in plan]
        self._busy(True)
        self._next()

    def render_stills(self):
        p = self.state.project
        if not p.stills:
            self._say("스틸이 없습니다. 편집 탭에서 S 키로 지정하세요.")
            return
        out_dir = self._out_dir()
        self.queue = [("still", _unique(out_dir / f"{Path(p.source(m.src).path).stem}_f{m.frame}.tif"), m)
                      for m in p.stills if p.source(m.src)]
        self._busy(True)
        self._next()

    def _next(self):
        if not self.queue:
            self._busy(False)
            self.progress.setValue(100)
            self._say("완료")
            return
        kind, path, item = self.queue.pop(0)
        p = self.state.project
        t0 = time.time()
        self._say(f"시작: {path.name}")
        self.progress.setValue(0)
        if kind == "video":
            job = jobs.Job(lambda prog, cancel: ff.render_video(p, item, str(path), prog, cancel), with_progress=True)
        else:
            job = jobs.Job(lambda prog, cancel: ff.render_still(p, item, str(path), p.output.gpu_decode),
                           with_progress=True)
        job.signals.progress.connect(lambda v: self.progress.setValue(int(v * 100)))
        job.signals.done.connect(lambda _r: (self._say(f"완료: {path.name} ({time.time() - t0:.1f}초)"), self._next()))
        job.signals.error.connect(self._on_error)
        self.job = jobs.submit(jobs.RENDER_POOL, job)

    def _on_error(self, msg):
        self._say(f"실패: {msg[-600:]}")
        if "nvenc" in msg.lower() or "No NVENC" in msg:
            self._say("→ NVENC 를 쓸 수 없습니다. 인코더를 x264(CPU)로 바꿔 다시 시도하세요.")
        self.queue = []
        self._busy(False)

    def _cancel(self):
        self.queue = []
        if self.job:
            self.job.cancel.set()
