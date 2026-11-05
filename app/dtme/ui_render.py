"""렌더 리스트(편집 화면 오른쪽) + 렌더 설정 탭."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QListWidget,
                               QListWidgetItem, QStyle, QStyledItemDelegate,
                               QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import short_name

ORIENT_TXT = {"horizontal": "가로", "vertical": "세로"}


RED_BTN = ("QPushButton{color:white; background:#c0392b; border:none; border-radius:3px; font-weight:700;}"
           "QPushButton:hover{background:#d64535;} QPushButton:disabled{background:#7a2a22; color:#ddd;}")
BTN_W, BTN_H = 72, 28          # ▼ · 렌더리스트로 · 전체 삭제 공통 크기
ADD_W, ADD_H = 90, 30          # 영상 추가 · 렌더 공통 크기


def arrow_icon(w=34, h=18, color="#ffffff"):
    """두께 있는 오른쪽 화살표(블록 화살표)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygonF
    pm = QPixmap(w * 2, h * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    W, H = w * 2, h * 2
    shaft_h, head_w = H * 0.46, W * 0.42
    p.drawPolygon(QPolygonF([QPointF(0, (H - shaft_h) / 2), QPointF(W - head_w, (H - shaft_h) / 2),
                             QPointF(W - head_w, 0), QPointF(W, H / 2), QPointF(W - head_w, H),
                             QPointF(W - head_w, (H + shaft_h) / 2), QPointF(0, (H + shaft_h) / 2)]))
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def render_list_button(fn, tip=""):
    from PySide6.QtCore import QSize
    b = QPushButton()
    b.setIcon(arrow_icon())
    b.setIconSize(QSize(24, 13))      # 화살표 20% 축소
    b.setFixedSize(BTN_W, BTN_H)
    b.setFocusPolicy(Qt.NoFocus)
    b.setStyleSheet(RED_BTN)
    if tip:
        b.setToolTip(tip)
    add_shadow(b)
    b.clicked.connect(fn)
    return b


def add_shadow(w):
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    e = QGraphicsDropShadowEffect(w)
    e.setBlurRadius(10)
    e.setOffset(0, 2)
    e.setColor(QColor(0, 0, 0, 170))
    w.setGraphicsEffect(e)


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


class RenderDelegate(QStyledItemDelegate):
    """렌더 항목 = 바. 대기 진한 회색 · 진행 중 막대 · 완료 연한 회색 · 실패 빨강."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        return QSize(option.rect.width(), 30)

    def paint(self, p, option, index):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPen
        iid = index.data(Qt.UserRole)
        st = self.panel.status.get(iid, "")
        frac = self.panel.progress.get(iid, 0.0)
        done, failed = st.startswith("완료"), st.startswith("실패")
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#c9c9c9") if done else QColor("#7a2a22") if failed else QColor("#3c3c3c"))
        p.drawRoundedRect(r, 3, 3)
        if not done and not failed and frac > 0:
            pr = QRectF(r)
            pr.setWidth(r.width() * frac)
            p.setBrush(QColor("#c0392b"))
            p.drawRoundedRect(pr, 3, 3)
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor("#4a8fe0"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        p.setPen(QColor("#111") if done else QColor("#e6e6e6"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole))
        f.setBold(False)
        p.setFont(f)
        p.drawText(r.adjusted(10, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, index.data(Qt.UserRole + 1) or "")
        p.restore()


class RenderPanel(QWidget):
    """렌더 설정 + 렌더 리스트(바) + 빨간 렌더 버튼."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.status: dict[str, str] = {}
        self.progress: dict[str, float] = {}
        self.queue: list = []
        self.running = False

        self.table = QListWidget()      # 이름은 table 유지(키 입력 필터에서 사용)
        self.table.setItemDelegate(RenderDelegate(self))
        self.table.setStyleSheet("QListWidget{background:#1a1a1a; border:none;}")
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
        self.b_render.setFixedSize(ADD_W, ADD_H)
        self.b_render.setFocusPolicy(Qt.NoFocus)
        self.b_render.setStyleSheet(RED_BTN)
        add_shadow(self.b_render)
        self.b_render.clicked.connect(self.render)
        self.settings = RenderSettings(state)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.settings)
        lay.addWidget(self.table, 1)
        brow = QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(self.b_render)
        brow.addStretch(1)
        lay.addLayout(brow)
        self.setMinimumWidth(300)
        state.changed.connect(lambda w: w in ("render", "sources", "project", "undo", "output") and self.refresh())

    def refresh(self):
        p = self.state.project
        sel = set(self._selected_ids())
        self.table.blockSignals(True)
        self.table.clear()
        for it in p.render_items:
            ok = all(p.source(g.src) for g in it.segs)
            st = self.status.get(it.id, "" if ok else "실패: 소스 없음")
            li = QListWidgetItem(file_name(p, it))
            li.setData(Qt.UserRole, it.id)
            li.setData(Qt.UserRole + 1, f"{ORIENT_TXT.get(it.orientation, '')} {p.segs_seconds(it.segs):.1f}초"
                       + ("" if it.audio else " 무음"))
            if st.startswith("실패"):
                li.setToolTip(st)
            self.table.addItem(li)
            li.setSelected(it.id in sel)
        self.table.blockSignals(False)

    def _repaint(self):
        self.table.viewport().update()

    def _selected_ids(self):
        return [i.data(Qt.UserRole) for i in self.table.selectedItems()]

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
            self.progress.pop(i, None)
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
            return
        it = self.queue.pop(0)
        path = unique(out_dir(p) / f"{file_name(p, it)}.mp4")
        t0 = time.time()
        self.status[it.id] = "진행"
        self.progress[it.id] = 0.0
        self.refresh()
        job = jobs.Job(lambda prog, cancel: ff.render_video(p, it.segs, str(path), prog, cancel,
                                                            it.orientation, it.audio), with_progress=True)

        def prog(v, iid=it.id):
            self.progress[iid] = v
            self._repaint()

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


class RenderSettings(QWidget):
    """렌더 설정(렌더 리스트 맨 위)."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        f = QFormLayout(self)
        f.setContentsMargins(0, 0, 0, 6)
        f.setVerticalSpacing(4)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("예: 보홀")
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
        self.folder.setPlaceholderText("소스 폴더/DTME_출력")
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
