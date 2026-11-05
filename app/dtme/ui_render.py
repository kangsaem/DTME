"""렌더 탭: 인코더·비트레이트·디코딩·저장폴더 + 렌더 리스트 + 렌더 버튼."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import OUTPUT_LIMIT_SEC
from .ui_edit import out_dir, unique

ORIENT_TXT = {"horizontal": "가로", "vertical": "세로"}


class RenderTab(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.status: dict[str, str] = {}     # item id → 대기/진행/완료/실패
        self.queue: list = []
        self.running = False

        box = QGroupBox("설정")
        box.setMaximumWidth(760)
        f = QFormLayout(box)
        self.encoder = QComboBox()
        self.encoder.addItem("NVENC (GPU, 빠름)", "nvenc")
        self.encoder.addItem("x264 (CPU, 느림·고품질)", "x264")
        f.addRow("인코더", self.encoder)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(8, 100)
        self.bitrate.setSuffix(" Mbps")
        f.addRow("비트레이트", self.bitrate)
        self.gpu = QCheckBox("GPU 디코딩 (실패 시 자동으로 CPU)")
        f.addRow("디코딩", self.gpu)
        frow = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("비우면 첫 소스와 같은 폴더의 ‘DTME_출력’ (스틸 PNG도 여기에 저장)")
        b = QPushButton("선택…")
        b.clicked.connect(self._pick_folder)
        frow.addWidget(self.folder, 1)
        frow.addWidget(b)
        f.addRow("저장폴더", frow)
        f.addRow("", QLabel("29.97fps · H.264 · BT.709"))
        self.encoder.activated.connect(self._save)
        self.bitrate.valueChanged.connect(self._save)
        self.gpu.toggled.connect(self._save)
        self.folder.editingFinished.connect(self._save)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["파일 이름", "컷", "길이", "화면", "오디오", "상태"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)
        a_del = QAction("삭제 (Del)", self.table)
        a_del.setShortcut(Qt.Key_Delete)
        a_del.setShortcutContext(Qt.WidgetShortcut)
        a_del.triggered.connect(self._delete)
        a_re = QAction("다시 렌더 대기로", self.table)
        a_re.triggered.connect(self._requeue)
        self.table.addAction(a_del)
        self.table.addAction(a_re)

        self.b_render = QPushButton("렌더")
        self.b_render.setMinimumHeight(40)
        self.b_render.setStyleSheet("QPushButton{font-size:15px; font-weight:600; background:#2f4a6b;}")
        self.b_render.clicked.connect(self.render)

        lay = QVBoxLayout(self)
        lay.addWidget(box)
        t = QLabel("렌더 리스트 — 편집 화면의 ▶(Enter) 또는 타임라인 ‘렌더 리스트로’로 추가 · 우클릭/Del 로 삭제")
        t.setStyleSheet("color:#aaa;")
        lay.addWidget(t)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.b_render)
        state.changed.connect(self._on_state)
        self._load()

    # ------------------------------------------------------------ 설정
    def _load(self):
        o = self.state.project.output
        for w in (self.encoder, self.bitrate, self.gpu):
            w.blockSignals(True)
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(o.encoder)))
        self.bitrate.setValue(o.bitrate_mbps)
        self.gpu.setChecked(o.gpu_decode)
        for w in (self.encoder, self.bitrate, self.gpu):
            w.blockSignals(False)
        self.folder.setText(o.folder)
        self.refresh()

    def _save(self, *_):
        o = self.state.project.output
        o.encoder = self.encoder.currentData()
        o.bitrate_mbps = self.bitrate.value()
        o.gpu_decode = self.gpu.isChecked()
        o.folder = self.folder.text().strip()
        self.state.dirty = True

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "저장폴더")
        if d:
            self.folder.setText(d)
            self._save()

    def _on_state(self, what):
        if what in ("project", "undo"):
            self._load()
        elif what in ("render", "sources", "grade"):
            self.refresh()

    # ------------------------------------------------------------ 리스트
    def refresh(self):
        p = self.state.project
        self.table.setRowCount(len(p.render_items))
        for r, it in enumerate(p.render_items):
            ok = all(p.source(g.src) for g in it.segs)
            sec = p.segs_seconds(it.segs)
            st = self.status.get(it.id, "대기" if ok else "소스 없음")
            vals = [it.name + ".mp4", f"{len(it.segs)}", f"{sec:.2f}초", ORIENT_TXT.get(it.orientation, ""),
                    "켬" if it.audio else "끔", st]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c:
                    cell.setTextAlignment(Qt.AlignCenter)
                if c == 2 and sec > OUTPUT_LIMIT_SEC:
                    cell.setForeground(QColor("#e5484d"))
                    cell.setText(f"{sec:.2f}초 (30초 초과)")
                if c == 5:
                    cell.setForeground(QColor("#7fd18b" if st.startswith("완료") else
                                              "#e5484d" if st.startswith("실패") else "#ddd"))
                    if st.startswith("실패"):
                        cell.setToolTip(st)
                self.table.setItem(r, c, cell)

    def _selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        items = self.state.project.render_items
        return [items[r].id for r in rows if r < len(items)]

    def _delete(self):
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

    # ------------------------------------------------------------ 렌더
    def render(self):
        if self.running:
            return
        p = self.state.project
        self._save()
        self.queue = [it for it in p.render_items
                      if not self.status.get(it.id, "").startswith("완료") and all(p.source(g.src) for g in it.segs)]
        if not self.queue:
            self.b_render.setText("렌더 (대기 중인 항목 없음)")
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
        path = unique(out_dir(p) / f"{it.name}.mp4")
        left = len(self.queue)
        self.b_render.setText(f"렌더 중… {it.name}" + (f" (남은 {left}개)" if left else ""))
        t0 = time.time()
        self.status[it.id] = "진행 0%"
        self.refresh()
        job = jobs.Job(lambda prog, cancel: ff.render_video(p, it.segs, str(path), prog, cancel,
                                                            it.orientation, it.audio), with_progress=True)

        def prog(v, iid=it.id):
            self.status[iid] = f"진행 {int(v * 100)}%"
            self.refresh()

        def done(_r, iid=it.id):
            self.status[iid] = f"완료 ({time.time() - t0:.0f}초) → {path.name}"
            self.refresh()
            self._next()

        def err(msg, iid=it.id):
            hint = " → 인코더를 x264로 바꿔 보세요" if "nvenc" in msg.lower() else ""
            self.status[iid] = f"실패: {msg[-300:]}{hint}"
            self.refresh()
            self._next()

        job.signals.progress.connect(prog)
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.RENDER_POOL, job)

    def refresh_status_text(self):
        """완료 상태 표시용 — 상태 앞부분으로 색 판단."""
        self.refresh()


_ = Path
