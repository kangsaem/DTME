"""렌더 리스트(편집 화면 오른쪽) + 렌더 설정 탭."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QListWidget,
                               QListWidgetItem, QStyle, QStyledItemDelegate,
                               QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import short_name

ORIENT_TXT = {"horizontal": "가로", "horizontal1440": "가로 1440", "horizontal2160": "가로 4K", "vertical": "세로"}


RED_BTN = ("QPushButton{color:white; background:#c0392b; border:none; border-radius:3px; font-weight:700;}"
           "QPushButton:hover{background:#d64535;} QPushButton:disabled{background:#7a2a22; color:#ddd;}")
BTN_W, BTN_H = 76, 28          # 모든 일반 버튼
MAIN_W, MAIN_H = 88, 32        # 주요 버튼: ▶/❚❚ · ▼ · 렌더리스트로 · 렌더
ADD_W, ADD_H = BTN_W, BTN_H    # 영상 추가 · 삭제(소스)


def fix_size(b, main=False):
    """주요 버튼 = 고정 88×32. 일반 버튼 = 높이 28, 폭 56~76(자리가 모자라면 줄어듦 → 노트북에서 겹치지 않음)."""
    if main:
        b.setFixedSize(MAIN_W, MAIN_H)
    else:
        b.setFixedHeight(BTN_H)
        b.setMinimumWidth(56)
        b.setMaximumWidth(BTN_W)
        from PySide6.QtWidgets import QSizePolicy
        b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return b


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
    b.setFixedSize(MAIN_W, MAIN_H)
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


def paths_cache_preview():
    from . import paths
    d = paths.cache_dir() / "preview"
    d.mkdir(parents=True, exist_ok=True)
    for old in sorted(d.glob("preview_*.mp4"))[:-3]:      # 최근 3개만 남김
        try:
            old.unlink()
        except OSError:
            pass
    return d / f"preview_{int(time.time())}.mp4"


def open_file(path):
    import os
    import subprocess
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])


def ensure_folder(parent, state) -> bool:
    """저장폴더가 비어 있으면 먼저 물어봄(취소하면 False). 고른 폴더는 다음 프로젝트에서도 처음 위치로."""
    o = state.project.output
    if o.folder.strip():
        return True
    import json
    from . import paths
    sp = paths.settings_path()
    try:
        last = json.loads(sp.read_text(encoding="utf-8")).get("last_folder", "") if sp.exists() else ""
    except Exception:  # noqa: BLE001
        last = ""
    start = last or (str(Path(state.project.sources[0].path).parent) if state.project.sources else "")
    d = QFileDialog.getExistingDirectory(parent, "저장폴더", start)
    if not d:
        return False
    o.folder = d
    state.dirty = True
    try:
        st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        st["last_folder"] = d
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    state.changed.emit("output")
    return True


def file_name(project, item) -> str:
    pre = project.output.prefix.strip() or "DTME"
    if pre and not pre.endswith(("_", "-", " ")):
        pre += "_"
    from . import TEST_TAG
    return f"{pre}{item.name}{TEST_TAG}"


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
        p.setBrush(QColor("#6b6b6b") if done else QColor("#7a2a22") if failed else QColor("#3c3c3c"))
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
        p.setPen(QColor("#f2f2f2") if done else QColor("#e6e6e6"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        info = index.data(Qt.UserRole + 1) or ""
        f.setBold(False)
        p.setFont(f)
        iw = p.fontMetrics().horizontalAdvance(info)
        p.drawText(r.adjusted(10, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, info)
        f.setBold(True)
        p.setFont(f)
        avail = int(r.width() - iw - 26)          # 이름이 길면 … (길이 글자와 겹치지 않게)
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, max(20, avail)))
        p.restore()


class RenderPanel(QWidget):
    """렌더 설정 + 렌더 리스트(바) + 빨간 렌더 버튼."""
    itemProgress = Signal(str, float, bool)       # (항목 id, 진행 0~1, 렌더 계속 중)

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
        self.b_render.setFixedSize(MAIN_W, MAIN_H)
        self.b_render.setFocusPolicy(Qt.NoFocus)
        self.b_render.setStyleSheet(RED_BTN)
        add_shadow(self.b_render)
        self.b_render.clicked.connect(self.render)
        self.settings = RenderSettings(state)
        from PySide6.QtWidgets import QDialog
        self.dlg = QDialog(self)
        self.dlg.setWindowTitle("렌더 설정")
        self.dlg.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        dl = QVBoxLayout(self.dlg)
        dl.addWidget(self.settings)
        self.dlg.setMinimumWidth(380)
        self.b_prev = QPushButton("미리보기 렌더")
        fix_size(self.b_prev, main=True)
        self.b_prev.setMaximumWidth(16777215)
        self.b_prev.setToolTip("타임라인을 작은 크기(540p)로 빠르게 렌더해 재생")
        self.b_prev.setFocusPolicy(Qt.NoFocus)
        self.b_prev.clicked.connect(self.preview_render)
        self.b_set = QPushButton("⚙")
        self.b_set.setFixedSize(34, MAIN_H)
        self.b_set.setToolTip("렌더 설정")
        self.b_set.setFocusPolicy(Qt.NoFocus)
        self.b_set.clicked.connect(lambda: (self.settings._load(), self.dlg.exec()))
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.b_prev, 1)
        top.addWidget(self.b_set)
        top.addWidget(self.b_render)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        self.setMinimumWidth(200)
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
        if not ensure_folder(self, self.state):
            return
        self.settings._load()
        p = self.state.project
        self.queue = [it for it in p.render_items
                      if not self.status.get(it.id, "").startswith("완료") and all(p.source(g.src) for g in it.segs)]
        if not self.queue:
            return
        self.running = True
        self.b_render.setEnabled(False)
        self._next()

    def preview_render(self):
        """타임라인 전체(없으면 렌더 리스트 첫 항목)를 960×540 x264 ultrafast 로 → 기본 플레이어로 열기."""
        p = self.state.project
        segs = [g.copy() for g in p.segments] or (p.render_items[0].segs if p.render_items else [])
        extras = {"titles": p.titles, "music": p.music, "mix": p.mix} if p.segments else {}
        if not segs or self.running:
            return
        out = paths_cache_preview()
        self.b_prev.setEnabled(False)
        self.b_prev.setText("미리보기 0%")
        orient = p.output.orientation

        def work(prog, cancel):
            ff.render_video(p, segs, str(out), prog, cancel, "preview_v" if orient == "vertical" else "preview",
                            p.output.audio, fast=True, extras=extras)
            return str(out)

        job = jobs.Job(work, with_progress=True)
        job.signals.progress.connect(lambda v: self.b_prev.setText(f"미리보기 {int(v * 100)}%"))

        def done(path):
            self.b_prev.setEnabled(True)
            self.b_prev.setText("미리보기 렌더")
            open_file(path)

        def err(msg):
            self.b_prev.setEnabled(True)
            self.b_prev.setText("미리보기 렌더")
            ff.log_error("미리보기 렌더", msg)
            self.b_prev.setToolTip(f"실패: {msg[-200:]}")
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.RENDER_POOL, job)

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
        extras = {"titles": it.titles, "music": it.music, "mix": it.mix}
        job = jobs.Job(lambda prog, cancel: ff.render_video(p, it.segs, str(path), prog, cancel,
                                                            it.orientation, it.audio, extras=extras), with_progress=True)

        def prog(v, iid=it.id):
            self.progress[iid] = v
            self._repaint()
            self.itemProgress.emit(iid, v, True)

        def done(_r, iid=it.id):
            self.status[iid] = f"완료 {time.time() - t0:.0f}초 → {path}"
            self.refresh()
            self.itemProgress.emit(iid, 1.0, bool(self.queue))
            self._next()

        def err(msg, iid=it.id):
            hint = " (인코더를 x264로)" if "nvenc" in msg.lower() else ""
            self.status[iid] = f"실패{hint}: {msg[-300:]}"
            self.refresh()
            self.itemProgress.emit(iid, 1.0, bool(self.queue))
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
        self.prefix.setPlaceholderText("DTME")
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
        self.folder.setPlaceholderText("렌더할 때 물어봄")
        b = QPushButton("선택…")
        fix_size(b)
        b.clicked.connect(self._pick_folder)
        frow.addWidget(self.folder, 1)
        frow.addWidget(b)
        f.addRow("저장폴더", frow)
        self.prefix.textChanged.connect(self._save)
        self.encoder.activated.connect(self._save)
        self.bitrate.valueChanged.connect(self._save)
        self.gpu.toggled.connect(self._save)
        self.folder.editingFinished.connect(self._save)
        for w in (self.prefix, self.folder):
            w.returnPressed.connect(w.clearFocus)
        state.changed.connect(lambda w: w in ("project", "undo", "output") and self._load())
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
