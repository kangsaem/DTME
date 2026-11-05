"""편집·보정 화면: 소스 | 모니터·소스 바·조작·타임라인 | 보정 | 렌더 리스트."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                               QSplitter, QStyle, QStyledItemDelegate, QTextEdit, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import Marker, RenderItem, Segment, short_name, speed_label, timecode
from .state import AppState
from .ui_bars import SeqTimeline, SourceBar
from .ui_grade import GradePanel
from .ui_player import Player
from .ui_render import RenderPanel, item_base, out_dir, unique

VIDEO_FILTER = "영상 (*.mp4 *.MP4 *.mov *.MOV)"

# Windows 물리 키(스캔코드) — 한/영 상태와 무관하게 동작
SCAN = {0x39: "space", 0x24: "j", 0x26: "l", 0x17: "i", 0x18: "o", 0x1A: "i", 0x1B: "o", 0x1F: "s", 0x22: "g",
        0x30: "b", 0x02: "1", 0x03: "2", 0x04: "3", 0x53: "del", 0x0E: "del", 0x01: "esc",
        0x4B: "left", 0x4D: "right", 0x50: "down", 0x1C: "enter", 0x2C: "z"}
QKEY = {Qt.Key_Space: "space", Qt.Key_J: "j", Qt.Key_L: "l", Qt.Key_I: "i", Qt.Key_O: "o",
        Qt.Key_BracketLeft: "i", Qt.Key_BracketRight: "o", Qt.Key_S: "s", Qt.Key_G: "g", Qt.Key_B: "b",
        Qt.Key_1: "1", Qt.Key_2: "2", Qt.Key_3: "3", Qt.Key_Delete: "del", Qt.Key_Backspace: "del",
        Qt.Key_Escape: "esc", Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Down: "down",
        Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Z: "z"}
TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)

C_INFO, C_OK, C_WARN = "#cfd8e3", "#7fd18b", "#f2c94c"


def _btn(text, tip, fn, w=None, h=None):
    b = QPushButton(text)
    if tip:
        b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(fn)
    if w:
        b.setMinimumWidth(w)
    if h:
        b.setMinimumHeight(h)
    return b


class SourceDelegate(QStyledItemDelegate):
    """소스 1개 = 회색 바. 준비 전 진한 회색(프록시 진행만큼 밝게), 준비되면 연한 회색."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 30)

    def paint(self, p: QPainter, option, index):
        sid = index.data(Qt.UserRole)
        st = self.tab.state.status.get(sid, "")
        pct = self.tab.state.proxy_pct.get(sid, 0.0)
        ready = st == "준비"
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#c9c9c9") if ready else QColor("#3c3c3c"))
        p.drawRoundedRect(r, 3, 3)
        if not ready and pct > 0:
            pr = QRectF(r)
            pr.setWidth(r.width() * pct)
            p.setBrush(QColor("#6a6a6a"))
            p.drawRoundedRect(pr, 3, 3)
        if st in ("읽기 오류", "원본 없음", "프록시 오류"):
            p.setBrush(QColor("#7a2a22"))
            p.drawRoundedRect(r, 3, 3)
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor("#4a8fe0"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        p.setPen(QColor("#111") if ready else QColor("#dddddd"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole))
        p.restore()


class EditTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.cur_sid = ""
        self.sel_cut = ""
        self.pgen = 0

        # ================= 소스
        self.src_list = QListWidget()
        self.src_list.setFocusPolicy(Qt.NoFocus)
        self.src_list.setItemDelegate(SourceDelegate(self))
        self.src_list.setStyleSheet("QListWidget{background:#1a1a1a; border:none;}")
        self.src_list.currentItemChanged.connect(self._on_src_selected)
        self.src_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.src_list.customContextMenuRequested.connect(lambda _pos: self.add_files())
        self.load_bar = QProgressBar()
        self.load_bar.setTextVisible(False)
        self.load_bar.setFixedHeight(6)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        t = QLabel("소스")
        t.setStyleSheet("font-weight:700; font-size:14px;")
        left.addWidget(t)
        left.addWidget(self.src_list, 1)
        left.addWidget(self.load_bar)
        row = QHBoxLayout()
        row.addWidget(_btn("영상 추가", "", self.add_files))
        row.addWidget(_btn("제거", "", self._remove_source))
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMinimumWidth(170)

        # ================= 모니터 + 소스 바 (간격 없음)
        self.player = Player()
        self.player.frameChanged.connect(self._on_frame)
        self.player.playingChanged.connect(self._on_playing)
        self.sbar = SourceBar()
        self.sbar.seekRequested.connect(lambda f: (self.player.pause(), self.player.seek(f)))
        mon = QVBoxLayout()
        mon.setSpacing(0)
        mon.setContentsMargins(0, 0, 0, 0)
        mon.addWidget(self.player, 1)
        mon.addWidget(self.sbar)

        # 재생 버튼 줄: [정지 시 보정 화면] ··· [◀◀ ◀| ▶ |▶ ▶▶] ··· [시간]
        self.chk_preview = QCheckBox("정지 시 보정 화면")
        self.chk_preview.setChecked(True)
        self.chk_preview.setFocusPolicy(Qt.NoFocus)
        self.chk_preview.toggled.connect(lambda _: self.request_preview())
        self.tc = QLabel("00:00.00")
        self.tc.setAlignment(Qt.AlignCenter)
        self.tc.setMinimumWidth(110)
        self.tc.setStyleSheet("background:#000; color:#e8e8e8; font: 300 16px 'Consolas', monospace;"
                              "padding:2px 10px; border-radius:2px;")
        tbar = QHBoxLayout()
        tbar.setSpacing(4)
        for text, tip, k in (("◀◀", "J", "j"), ("◀|", "←  (Shift: 1초)", "left"), ("▶ / ❚❚", "Space", "space"),
                             ("|▶", "→  (Shift: 1초)", "right"), ("▶▶", "L", "l")):
            tbar.addWidget(_btn(text, tip, lambda _=False, k=k: self._key(k), 64, 30))
        r1 = QGridLayout()
        r1.addWidget(self.chk_preview, 0, 0, Qt.AlignLeft)
        r1.addLayout(tbar, 0, 1)
        r1.addWidget(self.tc, 0, 2, Qt.AlignRight)
        r1.setColumnStretch(0, 1)
        r1.setColumnStretch(2, 1)

        # 컷 줄 (가운데)
        cut = QHBoxLayout()
        cut.setSpacing(4)
        cut.addStretch(1)
        b_in = _btn("[ 컷인", "I  또는  [", lambda: self._key("i"), 70)
        b_out = _btn("컷아웃 ]", "O  또는  ]", lambda: self._key("o"), 70)
        for b in (b_in, b_out):
            b.setStyleSheet("QPushButton{background:#3a3a26;}")
            cut.addWidget(b)
        cut.addWidget(_btn("IO 해제", "Esc", lambda: self._key("esc")))
        cut.addWidget(_btn("삭제", "Del", lambda: self._key("del")))
        cut.addSpacing(12)
        self.speed_group = QButtonGroup(self)
        for i, (sp, key) in enumerate(((2.0, "1"), (1.0, "2"), (0.5, "3"))):
            b = QPushButton(speed_label(sp))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumWidth(52)
            b.setToolTip(key)
            b.clicked.connect(lambda _=False, k=key: self._key(k))
            self.speed_group.addButton(b, i)
            cut.addWidget(b)
        self.speed_group.button(1).setChecked(True)
        cut.addSpacing(12)
        cut.addWidget(_btn("스틸", "S", lambda: self._key("s")))
        cut.addWidget(_btn("샘플", "G", lambda: self._key("g")))
        cut.addSpacing(12)
        b_r = _btn("렌더리스트로", "Enter", lambda: self._key("enter"))
        b_r.setStyleSheet("QPushButton{background:#2f3b4d;}")
        cut.addWidget(b_r)
        cut.addStretch(1)

        self.status = QLabel("")
        self.status.setStyleSheet("font-size:13px; padding:3px 6px; background:#1c1c1c; border-radius:3px;")

        # 타임라인 머리줄: [타임라인 n초] ··· [▼] ··· [확대 ━━] [전체 삭제] [렌더리스트로]
        self.tl_len = QLabel("")
        self.tl_len.setStyleSheet("color:#aaa;")
        tl_title = QLabel("타임라인")
        tl_title.setStyleSheet("font-weight:600;")
        lbox = QHBoxLayout()
        lbox.addWidget(tl_title)
        lbox.addWidget(self.tl_len)
        b_down = _btn("▼", "↓", lambda: self._key("down"), 64, 28)
        b_down.setStyleSheet("QPushButton{font-size:15px; background:#2f3b4d;}")
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(5, 200)
        self.zoom.setValue(30)
        self.zoom.setFixedWidth(140)
        self.zoom.setFocusPolicy(Qt.NoFocus)
        self.zoom.valueChanged.connect(lambda v: self.timeline.set_zoom(float(v)))
        rbox = QHBoxLayout()
        rbox.addWidget(QLabel("확대"))
        rbox.addWidget(self.zoom)
        rbox.addWidget(_btn("전체 삭제", "", self.clear_timeline))
        rbox.addWidget(_btn("렌더리스트로", "", self.timeline_to_render))
        th = QGridLayout()
        th.addLayout(lbox, 0, 0, Qt.AlignLeft)
        th.addWidget(b_down, 0, 1)
        th.addLayout(rbox, 0, 2, Qt.AlignRight)
        th.setColumnStretch(0, 1)
        th.setColumnStretch(2, 1)

        self.timeline = SeqTimeline()
        self.timeline.selected.connect(self._on_cut_selected)
        self.timeline.moved.connect(self._on_cut_moved)
        self.timeline.activated.connect(self._on_cut_activated)
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidget(self.timeline)
        self.tl_scroll.setWidgetResizable(False)
        self.tl_scroll.setFixedHeight(118)
        self.tl_scroll.setFrameShape(QFrame.NoFrame)
        self.tl_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addLayout(mon, 1)
        center.addLayout(r1)
        center.addLayout(cut)
        center.addWidget(self.status)
        center.addLayout(th)
        center.addWidget(self.tl_scroll)
        cw = QWidget()
        cw.setLayout(center)

        # ================= 보정 / 렌더 리스트
        self.grade = GradePanel(state)
        self.grade.gradeChanged.connect(self._on_grade_changed)
        self.grade.beforeToggled.connect(lambda _: self.request_preview())
        self.grade.sampleClicked.connect(self._show_sample)
        self.render_panel = RenderPanel(state)

        hs = QSplitter(Qt.Horizontal)
        for w in (lw, cw, self.grade, self.render_panel):
            hs.addWidget(w)
        for i in (0, 2, 3):
            hs.setCollapsible(i, False)
        hs.setStretchFactor(1, 1)
        hs.setSizes([190, 900, 350, 320])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(hs)

        self._pv_timer = QTimer(self)
        self._pv_timer.setSingleShot(True)
        self._pv_timer.setInterval(350)
        self._pv_timer.timeout.connect(self.request_preview)

        state.changed.connect(self._on_state)
        state.sourceStatus.connect(self._on_source_status)
        state.importProgress.connect(self._on_import_progress)
        QApplication.instance().installEventFilter(self)
        self._on_import_progress()
        self._refresh_timeline()
        self._apply_aspect()

    # ================================================================ 키 입력
    def eventFilter(self, obj, e):
        if e.type() != QEvent.KeyPress or not self.isVisible() or not self.window().isActiveWindow():
            return False
        fw = QApplication.focusWidget()
        if isinstance(fw, TEXT_INPUTS) or QApplication.activeModalWidget() is not None:
            return False
        name = None
        if os.name == "nt" and e.nativeScanCode():
            name = SCAN.get(e.nativeScanCode() & 0xFF)
        if name is None:
            name = QKEY.get(e.key())
        if name is None:
            return False
        if name == "del" and fw is self.render_panel.table:
            self.render_panel.delete_selected()
            return True
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if ctrl:
            if name == "z":
                self.window().undo()
                return True
            if name == "s":
                self.window().save_project()
                return True
            return False
        if name == "z":
            return False
        if e.isAutoRepeat() and name not in ("left", "right"):
            return True
        self._key(name, shift=bool(e.modifiers() & Qt.ShiftModifier))
        return True

    def _key(self, name, shift=False):
        p = self.player
        if name == "del":
            self.delete_cut()
            return
        src = self._cur()
        if src is None or not src.frames:
            return
        if name == "space":
            if not p.toggle():
                self._say("프록시 준비 중", C_WARN)
        elif name == "j":
            if not p.backward():
                self._say("프록시 준비 중", C_WARN)
        elif name == "l":
            if not p.forward():
                self._say("프록시 준비 중", C_WARN)
        elif name in ("left", "right"):
            d = round(float(p.fps)) if shift else 1
            p.step(-d if name == "left" else d)
        elif name == "i":
            self.mark_in()
        elif name == "o":
            self.mark_out()
        elif name in ("1", "2", "3"):
            self.set_speed({"1": 2.0, "2": 1.0, "3": 0.5}[name])
        elif name == "esc":
            self.clear_io()
        elif name == "s":
            self.export_still()
        elif name == "g":
            self.grade.make_samples()
        elif name == "b":
            self.grade.before.toggle()
        elif name == "down":
            self.send_to_timeline()
        elif name == "enter":
            self.send_to_render()

    # ================================================================ 표시
    def _say(self, text, color=C_INFO):
        self.status.setText(f"<span style='color:{color}'>{text}</span>")

    def _on_import_progress(self):
        _a, _done, n, frac = self.state.progress_summary()
        self.load_bar.setVisible(n > 0 and frac < 1.0)
        self.load_bar.setValue(int(frac * 100))
        self.src_list.viewport().update()

    def _apply_aspect(self):
        self.player.set_aspect(9 / 16 if self.state.project.output.orientation == "vertical" else 16 / 9)

    # ================================================================ 소스
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "영상 추가", "", VIDEO_FILTER)
        if files:
            self.import_files(files)

    def import_files(self, files):
        self.state.import_files(files)

    def _remove_source(self):
        s = self._cur()
        if not s:
            return
        if QMessageBox.question(self, "제거", f"{short_name(s.path)} 제거?") == QMessageBox.Yes:
            self.cur_sid = ""
            self.state.remove_source(s.id)

    def _refresh_sources(self):
        p = self.state.project
        self.src_list.blockSignals(True)
        self.src_list.clear()
        sel = None
        for s in p.sources:
            it = QListWidgetItem(short_name(s.path))
            it.setData(Qt.UserRole, s.id)
            it.setToolTip(s.path)
            self.src_list.addItem(it)
            if s.id == self.cur_sid:
                sel = it
        if sel:
            self.src_list.setCurrentItem(sel)
        self.src_list.blockSignals(False)
        if not sel and p.sources:
            self.src_list.setCurrentRow(0)
        elif not p.sources:
            self.cur_sid = ""
            self.player.clear("영상 추가")
            self.grade.set_current_source("")
            self._refresh_sbar()

    def _on_source_status(self, sid):
        self.src_list.viewport().update()
        if sid != self.cur_sid:
            return
        s = self._cur()
        if s is None:
            return
        if s.frames and self.player.frames == 0:
            self._load_current()
        elif self.state.proxy_ready(s) and not self.player.has_media and not self.player.is_busy():
            self.player.set_source(s.fps, s.frames, s.proxy, self.player.frame)
            self._pv_timer.start()

    def _on_src_selected(self, cur, _prev):
        if cur is None:
            return
        self.cur_sid = cur.data(Qt.UserRole)
        self.pgen += 1
        self.player.clear("로딩 중…")      # 이전 소스 화면 즉시 지움
        self.state.prioritize(self.cur_sid)
        self.grade.set_current_source(self.cur_sid)
        QTimer.singleShot(0, self._load_current)

    def _load_current(self):
        s = self._cur()
        if s is None:
            return
        if not s.frames:
            self.player.clear("로딩 중…")
            self._refresh_sbar()
            return
        proxy = s.proxy if self.state.proxy_ready(s) else None
        self.player.set_source(s.fps, s.frames, proxy, s.io[0])
        self._refresh_sbar()
        self._sync_speed_buttons()
        self._pv_timer.start()

    def _cur(self):
        return self.state.project.source(self.cur_sid)

    def _select_source(self, sid):
        for i in range(self.src_list.count()):
            if self.src_list.item(i).data(Qt.UserRole) == sid:
                self.src_list.setCurrentRow(i)

    # ================================================================ 모니터 보정 화면
    def _on_frame(self, f):
        s = self._cur()
        if s:
            self.tc.setText(timecode(f, s.fps))
        self.sbar.set_playhead(f)
        if not self.player.is_busy():
            self._pv_timer.start()

    def _on_playing(self, playing):
        if playing:
            self._pv_timer.stop()
            self.pgen += 1          # 진행 중인 보정 화면 무시 → 바로 부드럽게 재생
        else:
            self._pv_timer.start()

    def _on_grade_changed(self):
        self._refresh_sbar()
        self._refresh_timeline()
        self.request_preview()

    def request_preview(self):
        s = self._cur()
        p = self.player
        if not s or not s.frames or p.is_busy():
            return
        if not self.chk_preview.isChecked() and p.has_media:
            p.overlay_frame = None
            p._grab(p.frame)
            return
        self.pgen += 1
        gen, frame, tok = self.pgen, p.frame, p._token
        grade = None if self.grade.before.isChecked() else self.state.project.grade_for_source(s.id)
        job = jobs.Job(lambda: ff.render_preview(ff.cached_frame(s, frame), grade))
        job.signals.done.connect(lambda data, g=gen, fr=frame, t=tok: self._on_preview(g, fr, t, data))
        job.signals.error.connect(lambda msg: self._say(f"미리보기 오류: {msg[-160:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=5)

    def _on_preview(self, gen, frame, tok, data):
        p = self.player
        if gen != self.pgen or frame != p.frame or tok != p._token or p.is_busy():
            return
        p.overlay_frame = frame
        p.show_image(QImage.fromData(data, "PNG"))

    def _show_sample(self, sid, frame, pix):
        self.player.pause()
        self._pv_timer.stop()
        self.pgen += 1
        self.player.overlay_frame = self.player.frame
        self.player.show_image(pix)

    # ================================================================ 인/아웃·배속
    def mark_in(self):
        s = self._cur()
        f = self.player.frame
        self.state.checkpoint()
        s.sel_in = f
        if s.sel_out and s.sel_out <= f + 1:
            s.sel_out = 0
        self._after_io()

    def mark_out(self):
        s = self._cur()
        f = self.player.frame + 1
        self.state.checkpoint()
        s.sel_out = min(s.frames, f)
        if s.sel_in >= s.sel_out - 1:
            s.sel_in = 0
        self._after_io()

    def clear_io(self):
        s = self._cur()
        self.state.checkpoint()
        s.sel_in, s.sel_out = 0, 0
        self._after_io()

    def _after_io(self):
        s = self._cur()
        a, b = s.io
        sec = float((b - a) / s.fps / s.speed)
        self.state.dirty = True
        self._refresh_sbar()
        self._say(f"{timecode(a, s.fps)} ~ {timecode(b - 1, s.fps)}  {speed_label(s.speed)}  {sec:.2f}초", C_OK)

    def set_speed(self, sp):
        s = self._cur()
        self.state.checkpoint()
        s.speed = sp
        self._sync_speed_buttons()
        self._after_io()

    def _sync_speed_buttons(self):
        s = self._cur()
        if s:
            self.speed_group.button({2.0: 0, 1.0: 1, 0.5: 2}.get(s.speed, 1)).setChecked(True)

    # ================================================================ 보내기
    def _cur_segment(self):
        s = self._cur()
        a, b = s.io
        return Segment(s.id, a, b, s.speed)

    def send_to_timeline(self):
        seg = self._cur_segment()
        self.state.checkpoint()
        self.state.project.segments.append(seg)
        self.state.touch("segments")
        QTimer.singleShot(0, lambda: self.tl_scroll.horizontalScrollBar().setValue(
            self.tl_scroll.horizontalScrollBar().maximum()))

    def _new_item(self, segs):
        o = self.state.project.output
        return RenderItem(name=item_base(self.state.project, segs), segs=segs,
                          orientation=o.orientation, audio=o.audio)

    def send_to_render(self):
        self.state.checkpoint()
        self.state.project.render_items.append(self._new_item([self._cur_segment()]))
        self.state.touch("render")

    def timeline_to_render(self):
        p = self.state.project
        if not p.segments:
            return
        self.state.checkpoint()
        p.render_items.append(self._new_item([Segment(g.src, g.fin, g.fout, g.speed) for g in p.segments]))
        self.state.touch("render")

    # ================================================================ 타임라인
    def clear_timeline(self):
        if not self.state.project.segments:
            return
        self.state.checkpoint()
        self.state.project.segments.clear()
        self.sel_cut = ""
        self.state.touch("segments")

    def delete_cut(self):
        p = self.state.project
        seg = next((g for g in p.segments if g.id == self.sel_cut), None)
        if not seg:
            return
        self.state.checkpoint()
        p.segments.remove(seg)
        self.sel_cut = ""
        self.state.touch("segments")

    def _on_cut_selected(self, cid):
        self.sel_cut = cid
        self._refresh_timeline()

    def _on_cut_moved(self, a, b):
        segs = self.state.project.segments
        self.state.checkpoint()
        segs.insert(b, segs.pop(a))
        self.state.touch("segments")

    def _on_cut_activated(self, cid):
        seg = next((g for g in self.state.project.segments if g.id == cid), None)
        if seg:
            self._select_source(seg.src)
            QTimer.singleShot(50, lambda: (self.player.pause(), self.player.seek(seg.fin)))

    # ================================================================ 스틸 (바로 PNG)
    def export_still(self):
        s = self._cur()
        frame = self.player.frame
        g = self.state.project.grade_for_source(s.id)
        path = unique(out_dir(self.state.project) / f"{short_name(s.path)}_f{frame}.png")
        self.state.project.stills.append(Marker(s.id, frame))
        self._refresh_sbar()
        self._say(f"스틸 저장 중… {path.name}", C_INFO)
        gpu = self.state.project.output.gpu_decode
        job = jobs.Job(lambda: ff.export_still(s, frame, g, str(path), gpu))
        job.signals.done.connect(lambda _r: self._say(f"스틸 저장: {path}", C_OK))
        job.signals.error.connect(lambda m: self._say(f"스틸 실패: {m[-200:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=8)

    # ================================================================ 갱신
    def _on_state(self, what):
        if what in ("project", "undo"):
            if what == "project" or not self._cur():
                self.cur_sid = ""
            self._refresh_sources()
            self.grade.set_current_source(self.cur_sid)
            self._sync_speed_buttons()
            self._refresh_sbar()
        elif what == "sources":
            self._refresh_sources()
        if what in ("project", "undo", "output"):
            self._apply_aspect()
        if what in ("project", "undo", "sources", "segments", "grade", "output"):
            self._refresh_timeline()
        if what == "markers":
            self._refresh_sbar()

    def _tag(self, sid):
        s = self.state.project.source(sid)
        return "C" if s and s.grade else "E"

    def _refresh_sbar(self):
        s = self._cur()
        p = self.state.project
        if not s or not s.frames:
            self.sbar.set_data(0, (0, 0), False, 1.0, "", [], [])
            return
        self.sbar.set_data(s.frames, s.io, s.io_trimmed, s.speed, self._tag(s.id),
                           [m.frame for m in p.stills if m.src == s.id], [m.frame for m in p.samples if m.src == s.id])

    def _refresh_timeline(self):
        p = self.state.project
        items = []
        for g in p.segments:
            s = p.source(g.src)
            if s and s.frames:
                items.append((g.id, p.seg_out_seconds(g, s.fps), short_name(s.path)[-4:], g.speed, self._tag(s.id)))
        if self.sel_cut and not any(i[0] == self.sel_cut for i in items):
            self.sel_cut = ""
        self.timeline.set_items(items, self.sel_cut)
        tot = sum(i[1] for i in items)
        self.tl_len.setText(f"{tot:.1f}초" if items else "")


_ = (Path, QPixmap)
