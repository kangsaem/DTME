"""렌더 리스트(편집 화면 오른쪽) + 렌더 설정 탭."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import short_name

ORIENT_TXT = {"horizontal": "가로", "vertical": "세로"}


def out_dir(project) -> Path:
    o = project.output
    if o.folder:
        d = Path(o.folder)
    elif project.sources:
        d = Path(project.sources[0].path).parent / "DTME_출력"
    else:
        d = Path.home() / "DTME_출력"
    d.mkdir(parents=True, exist_ok=True)
    return d


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while (path.with_name(f"{path.stem}_{i}{path.suffix}")).exists():
        i += 1
    return path.with_name(f"{path.stem}_{i}{path.suffix}")


def item_base(project, segs) -> str:
    """첫 컷 소스의 날짜·시간."""
    s = project.source(segs[0].src) if segs else None
    return short_name(s.path) if s else "DTME"


def file_name(project, item) -> str:
    pre = project.output.prefix.strip()
    if pre and not pre.endswith(("_", "-", " ")):
        pre += "_"
    return f"{pre}{item.name}"


class RenderPanel(QWidget):
    """렌더 리스트 + 빨간 렌더 버튼."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.status: dict[str, str] = {}
        self.queue: list = []
        self.running = False

        t = QLabel("렌더 리스트")
        t.setStyleSheet("font-weight:700; font-size:14px;")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["파일명", "길이", "화면", "오디오", "상태"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)
        a_del = QAction("삭제", self.table)
        a_del.setShortcut(Qt.Key_Delete)
        a_del.setShortcutContext(Qt.WidgetShortcut)
        a_del.triggered.connect(self.delete_selected)
        a_re = QAction("다시 렌더", self.table)
        a_re.triggered.connect(self._requeue)
        self.table.addAction(a_del)
        self.table.addAction(a_re)

        self.b_render = QPushButton("렌더")
        self.b_render.setMinimumHeight(40)
        self.b_render.setFocusPolicy(Qt.NoFocus)
        self.b_render.setStyleSheet("QPushButton{font-size:15px; font-weight:700; color:white; background:#c0392b;"
                                    "border:none; border-radius:4px;} QPushButton:hover{background:#d64535;}"
                                    "QPushButton:disabled{background:#7a2a22; color:#ddd;}")
        self.b_render.clicked.connect(self.render)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(t)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.b_render)
        self.setMinimumWidth(300)
        state.changed.connect(lambda w: w in ("render", "sources", "project", "undo", "output") and self.refresh())

    def refresh(self):
        p = self.state.project
        self.table.setRowCount(len(p.render_items))
        for r, it in enumerate(p.render_items):
            ok = all(p.source(g.src) for g in it.segs)
            st = self.status.get(it.id, "대기" if ok else "소스 없음")
            vals = [file_name(p, it), f"{p.segs_seconds(it.segs):.1f}초", ORIENT_TXT.get(it.orientation, ""),
                    "켬" if it.audio else "끔", st.split(" → ")[0]]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c:
                    cell.setTextAlignment(Qt.AlignCenter)
                if c == 4:
                    cell.setForeground(QColor("#7fd18b" if st.startswith("완료") else
                                              "#e5484d" if st.startswith("실패") else "#ddd"))
                    cell.setToolTip(st)
                self.table.setItem(r, c, cell)

    def _selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        items = self.state.project.render_items
        return [items[r].id for r in rows if r < len(items)]

    def delete_selected(self):
        ids = set(self._selected_ids())
        if not ids or self.running:
            return
        self.state.checkpoint()
        self.state.project.render_items = [i for i in self.state.project.render_items if i.id not in ids]
        self.state.touch("render")

    def _requeue(self):
        for i in self._selected_ids():
            self.status.pop(i, None)
        self.refresh()

    def render(self):
        if self.running:
            return
        p = self.state.project
        self.queue = [it for it in p.render_items
                      if not self.status.get(it.id, "").startswith("완료") and all(p.source(g.src) for g in it.segs)]
        if not self.queue:
            return
        self.running = True
        self.b_render.setEnabled(False)
        self._next()

    def _next(self):
        p = self.state.project
        if not self.queue:
            self.running = False
            self.b_render.setEnabled(True)
            self.b_render.setText("렌더")
            return
        it = self.queue.pop(0)
        path = unique(out_dir(p) / f"{file_name(p, it)}.mp4")
        self.b_render.setText(f"렌더 중… ({len(self.queue) + 1})")
        t0 = time.time()
        self.status[it.id] = "0%"
        self.refresh()
        job = jobs.Job(lambda prog, cancel: ff.render_video(p, it.segs, str(path), prog, cancel,
                                                            it.orientation, it.audio), with_progress=True)

        def prog(v, iid=it.id):
            self.status[iid] = f"{int(v * 100)}%"
            self.refresh()

        def done(_r, iid=it.id):
            self.status[iid] = f"완료 {time.time() - t0:.0f}초 → {path}"
            self.refresh()
            self._next()

        def err(msg, iid=it.id):
            hint = " (인코더를 x264로)" if "nvenc" in msg.lower() else ""
            self.status[iid] = f"실패{hint}: {msg[-300:]}"
            self.refresh()
            self._next()

        job.signals.progress.connect(prog)
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.RENDER_POOL, job)


class RenderTab(QWidget):
    """렌더 설정."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        box = QGroupBox("렌더 설정")
        box.setMaximumWidth(760)
        f = QFormLayout(box)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("예: 보홀  →  보홀_202610251001.mp4")
        f.addRow("명칭", self.prefix)
        self.encoder = QComboBox()
        self.encoder.addItem("NVENC (GPU)", "nvenc")
        self.encoder.addItem("x264 (CPU)", "x264")
        f.addRow("인코더", self.encoder)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(8, 100)
        self.bitrate.setSuffix(" Mbps")
        f.addRow("비트레이트", self.bitrate)
        self.gpu = QCheckBox("GPU")
        f.addRow("디코딩", self.gpu)
        frow = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("비우면 소스 폴더/DTME_출력")
        b = QPushButton("선택…")
        b.clicked.connect(self._pick_folder)
        frow.addWidget(self.folder, 1)
        frow.addWidget(b)
        f.addRow("저장폴더", frow)
        self.prefix.textChanged.connect(self._save)
        self.encoder.activated.connect(self._save)
        self.bitrate.valueChanged.connect(self._save)
        self.gpu.toggled.connect(self._save)
        self.folder.editingFinished.connect(self._save)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addStretch(1)
        state.changed.connect(lambda w: w in ("project", "undo") and self._load())
        self._load()

    def _load(self):
        o = self.state.project.output
        ws = (self.prefix, self.encoder, self.bitrate, self.gpu)
        for w in ws:
            w.blockSignals(True)
        self.prefix.setText(o.prefix)
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(o.encoder)))
        self.bitrate.setValue(o.bitrate_mbps)
        self.gpu.setChecked(o.gpu_decode)
        for w in ws:
            w.blockSignals(False)
        self.folder.setText(o.folder)

    def _save(self, *_):
        o = self.state.project.output
        o.prefix = self.prefix.text()
        o.encoder = self.encoder.currentData()
        o.bitrate_mbps = self.bitrate.value()
        o.gpu_decode = self.gpu.isChecked()
        o.folder = self.folder.text().strip()
        self.state.dirty = True
        self.state.changed.emit("output")

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "저장폴더")
        if d:
            self.folder.setText(d)
            self._save()
