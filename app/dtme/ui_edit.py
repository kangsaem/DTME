"""편집·보정 화면: 소스 | 모니터·소스 바·조작·타임라인 | 보정."""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QTextEdit,
                               QVBoxLayout, QWidget, QFrame)

from . import ff, jobs
from .project import OUTPUT_LIMIT_SEC, Marker, RenderItem, Segment, speed_label, timecode
from .state import AppState
from .ui_bars import SeqTimeline, SourceBar
from .ui_grade import GradePanel
from .ui_player import Player

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
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(fn)
    if w:
        b.setMinimumWidth(w)
    if h:
        b.setMinimumHeight(h)
    return b


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


class EditTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.cur_sid = ""
        self.sel_cut = ""
        self.pgen = 0

        # ================= 왼쪽: 소스
        self.src_list = QListWidget()
        self.src_list.setFocusPolicy(Qt.NoFocus)
        self.src_list.currentItemChanged.connect(self._on_src_selected)
        self.src_list.setToolTip("클릭하면 모니터에 표시 · 선택한 소스의 프록시를 먼저 만듭니다")
        self.load_bar = QProgressBar()
        self.load_bar.setTextVisible(False)
        self.load_bar.setFixedHeight(8)
        self.load_text = QLabel("")
        self.load_text.setStyleSheet("color:#aaa; font-size:11px;")
        self.load_text.setWordWrap(True)
        self.load_text.setToolTip("프록시: 편집 화면 재생용 가벼운 복사본(960px, 모든 프레임이 기준 프레임).\n"
                                  "최종 렌더는 항상 4K 원본을 씁니다. 준비 전에도 이동·인/아웃 지정 가능.")
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("소스"))
        left.addWidget(self.src_list, 1)
        left.addWidget(self.load_text)
        left.addWidget(self.load_bar)
        row = QHBoxLayout()
        row.addWidget(_btn("영상 추가", "4K 원본 추가 (여러 개, 끌어다 놓기 가능)", self.add_files))
        row.addWidget(_btn("제거", "선택한 소스를 목록에서 제거 (원본 파일은 그대로)", self._remove_source))
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)

        # ================= 가운데: 모니터 + 소스 바 (간격 없음)
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

        # 재생 버튼(가운데 정렬) + 시간
        self.tc = QLabel("--:--.--")
        self.tc.setTextFormat(Qt.RichText)
        self.tc.setStyleSheet("font: 600 17px 'Consolas', monospace;")
        self.tc.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mode_lab = QLabel("")
        self.mode_lab.setStyleSheet("color:#888; font-size:11px;")
        tbar = QHBoxLayout()
        tbar.setSpacing(4)
        for text, tip, k in (("◀◀", "2배속 뒤로 (J) · 다시 누르면 정지", "j"), ("◀|", "1프레임 뒤 (←) · Shift = 1초", "left"),
                             ("▶ / ❚❚", "재생 / 정지 (Space)", "space"), ("|▶", "1프레임 앞 (→) · Shift = 1초", "right"),
                             ("▶▶", "2배속 앞으로 (L) · 다시 누르면 정지", "l")):
            tbar.addWidget(_btn(text, tip, lambda _=False, k=k: self._key(k), 64, 30))
        r1 = QGridLayout()
        r1.addWidget(self.mode_lab, 0, 0, Qt.AlignLeft)
        r1.addLayout(tbar, 0, 1)
        r1.addWidget(self.tc, 0, 2)
        r1.setColumnStretch(0, 1)
        r1.setColumnStretch(2, 1)

        # 인/아웃·배속·스틸·샘플 (가운데 정렬)
        cut = QHBoxLayout()
        cut.setSpacing(4)
        cut.addStretch(1)
        b_in = _btn("[ 컷인", "인 점 (I 또는 [ )", lambda: self._key("i"), 70)
        b_out = _btn("컷아웃 ]", "아웃 점 (O 또는 ] )", lambda: self._key("o"), 70)
        for b in (b_in, b_out):
            b.setStyleSheet("QPushButton{background:#3a3a26;}")
            cut.addWidget(b)
        cut.addWidget(_btn("IO 해제", "인/아웃을 클립 전체로 (Esc)", lambda: self._key("esc")))
        cut.addWidget(_btn("삭제", "타임라인에서 선택한 컷 삭제 (Del)", lambda: self._key("del")))
        cut.addSpacing(12)
        self.speed_group = QButtonGroup(self)
        for i, (sp, key) in enumerate(((2.0, "1"), (1.0, "2"), (0.5, "3"))):
            b = QPushButton(speed_label(sp))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumWidth(52)
            b.setToolTip(f"이 소스의 배속 ({key})")
            b.clicked.connect(lambda _=False, k=key: self._key(k))
            self.speed_group.addButton(b, i)
            cut.addWidget(b)
        self.speed_group.button(1).setChecked(True)
        cut.addSpacing(12)
        cut.addWidget(_btn("스틸", "현재 프레임을 4K PNG로 바로 저장 (S)", lambda: self._key("s")))
        cut.addWidget(_btn("샘플", "현재 클립 전체에서 보정 샘플 6장 생성 (G)", lambda: self._key("g")))
        cut.addSpacing(12)
        self.chk_preview = QCheckBox("정지 시 보정 화면")
        self.chk_preview.setChecked(True)
        self.chk_preview.setFocusPolicy(Qt.NoFocus)
        self.chk_preview.setToolTip("켜면: 멈췄을 때 원본으로 최종 보정 결과를 만들어 표시\n끄면: 프록시 화면(LUT만)")
        self.chk_preview.toggled.connect(lambda _: self.request_preview())
        cut.addWidget(self.chk_preview)
        cut.addStretch(1)

        self.status = QLabel("")
        self.status.setStyleSheet("font-size:13px; padding:3px 6px; background:#1c1c1c; border-radius:3px;")

        # 보내기 버튼 ▼ ▶ (타임라인 바로 위 가운데)
        send = QHBoxLayout()
        send.addStretch(1)
        b_down = _btn("▼", "인/아웃 구간을 타임라인으로 (↓)", lambda: self._key("down"), 56, 28)
        b_right = _btn("▶", "인/아웃 구간을 렌더 리스트로 바로 (Enter)", lambda: self._key("enter"), 56, 28)
        for b in (b_down, b_right):
            b.setStyleSheet("QPushButton{font-size:15px; background:#2f3b4d;}")
        send.addWidget(b_down)
        send.addWidget(b_right)
        send.addStretch(1)

        # 타임라인 머리줄
        self.tl_len = QLabel("")
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(5, 200)
        self.zoom.setValue(30)
        self.zoom.setFixedWidth(160)
        self.zoom.setFocusPolicy(Qt.NoFocus)
        self.zoom.setToolTip("타임라인 가로 확대/축소")
        self.zoom.valueChanged.connect(lambda v: self.timeline.set_zoom(float(v)))
        th = QHBoxLayout()
        tl_title = QLabel("타임라인")
        tl_title.setStyleSheet("font-weight:600;")
        th.addWidget(tl_title)
        th.addWidget(self.tl_len)
        th.addStretch(1)
        th.addWidget(QLabel("확대"))
        th.addWidget(self.zoom)
        th.addSpacing(10)
        th.addWidget(_btn("전체 삭제", "타임라인 비우기", self.clear_timeline))
        th.addWidget(_btn("렌더 리스트로 ▶", "타임라인 전체를 영상 1개로 렌더 리스트에 추가", self.timeline_to_render))

        self.timeline = SeqTimeline()
        self.timeline.selected.connect(self._on_cut_selected)
        self.timeline.moved.connect(self._on_cut_moved)
        self.timeline.activated.connect(self._on_cut_activated)
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidget(self.timeline)
        self.tl_scroll.setWidgetResizable(False)
        self.tl_scroll.setFixedHeight(118)
        self.tl_scroll.setFrameShape(QFrame.NoFrame)
        self.tl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tl_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addLayout(mon, 1)
        center.addLayout(r1)
        center.addLayout(cut)
        center.addWidget(self.status)
        center.addLayout(send)
        center.addLayout(th)
        center.addWidget(self.tl_scroll)
        cw = QWidget()
        cw.setLayout(center)

        # ================= 오른쪽: 보정
        self.grade = GradePanel(state)
        self.grade.gradeChanged.connect(self._on_grade_changed)
        self.grade.beforeToggled.connect(lambda _: self.request_preview())
        self.grade.sampleClicked.connect(self._show_sample)

        hs = QSplitter(Qt.Horizontal)
        hs.addWidget(lw)
        hs.addWidget(cw)
        hs.addWidget(self.grade)
        hs.setCollapsible(2, False)
        hs.setCollapsible(0, False)
        hs.setStretchFactor(1, 1)
        hs.setSizes([230, 960, 380])
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
        self._say("‘영상 추가’로 시작하세요.", C_INFO)
        self._on_import_progress()
        self._refresh_timeline()

    # ================================================================ 키 입력
    def eventFilter(self, obj, e):
        if e.type() != QEvent.KeyPress or not self.isVisible() or not self.window().isActiveWindow():
            return False
        if isinstance(QApplication.focusWidget(), TEXT_INPUTS) or QApplication.activeModalWidget() is not None:
            return False
        name = None
        if os.name == "nt" and e.nativeScanCode():
            name = SCAN.get(e.nativeScanCode() & 0xFF)
        if name is None:
            name = QKEY.get(e.key())
        if name is None:
            return False
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
            self._say("먼저 왼쪽 목록에서 소스를 선택하세요 (분석이 끝나야 합니다).", C_WARN)
            return
        if name == "space":
            if not p.toggle():
                self._say("프록시 준비 전이라 재생은 아직 안 됩니다. ←/→ 이동과 인/아웃 지정은 가능합니다.", C_WARN)
        elif name == "j":
            if not p.backward():
                self._say("프록시 준비 후 재생할 수 있습니다.", C_WARN)
        elif name == "l":
            if not p.forward():
                self._say("프록시 준비 후 재생할 수 있습니다.", C_WARN)
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
            if self.grade.make_samples():
                self._say("샘플 6장 생성 중 — 오른쪽 아래에 표시됩니다.", C_OK)
        elif name == "b":
            self.grade.before.toggle()
        elif name == "down":
            self.send_to_timeline()
        elif name == "enter":
            self.send_to_render()

    # ================================================================ 상태 표시
    def _say(self, text, color=C_INFO):
        self.status.setText(f"<span style='color:{color}'>{text}</span>")

    def _on_import_progress(self):
        a, done, n, frac = self.state.progress_summary()
        if n == 0:
            self.load_text.setText("")
            self.load_bar.setValue(0)
            return
        cur = self._cur()
        extra = f"\n현재: {self.state.status.get(cur.id, '')}" if cur else ""
        self.load_text.setText((f"{n}개 모두 준비됨" if done >= n else f"분석 {a}/{n} · 프록시 {done}/{n}") + extra)
        self.load_bar.setValue(int(frac * 100))

    # ================================================================ 소스
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "영상 추가", "", VIDEO_FILTER)
        if files:
            self.import_files(files)

    def import_files(self, files):
        n = self.state.import_files(files)
        if n:
            self._say(f"{n}개 추가 — 분석·프록시는 뒤에서 진행. 첫 장면은 바로 볼 수 있습니다.", C_OK)

    def _remove_source(self):
        s = self._cur()
        if not s:
            return
        if QMessageBox.question(self, "제거", f"{s.name} 을(를) 목록에서 제거할까요?\n"
                                "(타임라인의 이 소스 컷도 함께 삭제 · 원본 파일은 그대로)") == QMessageBox.Yes:
            self.cur_sid = ""
            self.state.remove_source(s.id)

    def _src_text(self, s):
        st = self.state.status.get(s.id, "")
        dur = f" · {s.frames / float(s.fps):.0f}초" if s.frames else ""
        n = len(self.state.project.segments_of(s.id))
        return f"{s.name}\n   {st}{dur}" + (f" · 타임라인 {n}컷" if n else "")

    def _refresh_sources(self):
        p = self.state.project
        self.src_list.blockSignals(True)
        self.src_list.clear()
        sel = None
        for s in p.sources:
            it = QListWidgetItem(self._src_text(s))
            it.setData(Qt.UserRole, s.id)
            it.setToolTip(s.path)
            self.src_list.addItem(it)
            if s.id == self.cur_sid:
                sel = it
        if sel:
            self.src_list.setCurrentItem(sel)
        self.src_list.blockSignals(False)
        if not sel and p.sources:
            self.src_list.setCurrentRow(0)     # 처음 소스 자동 선택
        elif not p.sources:
            self.cur_sid = ""
            self.player.clear("왼쪽 ‘영상 추가’로 4K 원본을 불러오세요\n(여러 개 선택 가능 · 창에 끌어다 놓아도 됩니다)")
            self.grade.set_current_source("")
            self._refresh_sbar()

    def _refresh_source_texts(self):
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            s = self.state.project.source(it.data(Qt.UserRole))
            if s:
                it.setText(self._src_text(s))

    def _on_source_status(self, sid):
        self._refresh_source_texts()
        if sid != self.cur_sid:
            return
        s = self._cur()
        if s is None:
            return
        if s.frames and self.player.frames == 0:
            self._load_current()
        elif self.state.proxy_ready(s) and not self.player.has_media and not self.player.is_busy():
            self.player.set_source(s.fps, s.frames, s.proxy, self.player.frame)
            self._update_mode()
            self._say("프록시 준비 완료 — 재생(Space) 가능", C_OK)

    def _on_src_selected(self, cur, _prev):
        if cur is None:
            return
        self.cur_sid = cur.data(Qt.UserRole)
        self.state.prioritize(self.cur_sid)
        self.grade.set_current_source(self.cur_sid)
        self._load_current()
        self._on_import_progress()

    def _load_current(self):
        s = self._cur()
        if s is None:
            return
        if not s.frames:
            self.player.clear(f"{s.name}\n분석 중…")
            self._refresh_sbar()
            return
        proxy = s.proxy if self.state.proxy_ready(s) else None
        self.player.set_source(s.fps, s.frames, proxy, s.io[0])
        self._update_mode()
        self._refresh_sbar()
        self._sync_speed_buttons()
        self._pv_timer.start()

    def _update_mode(self):
        s = self._cur()
        self.mode_lab.setText("" if not s else ("재생: 프록시" if self.player.has_media else "프록시 준비 중 · 정지화면"))

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
            self.tc.setText(f"{timecode(f, s.fps)} <span style='color:#777;font-size:11px'>#{f}</span>")
        self.sbar.set_playhead(f)
        if not self.player.is_busy():
            self._pv_timer.start()

    def _on_playing(self, playing):
        if playing:
            self._pv_timer.stop()
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
            p._grab(p.frame)      # 프록시 화면으로
            return
        self.pgen += 1
        gen, frame = self.pgen, p.frame
        grade = None if self.grade.before.isChecked() else self.state.project.grade_for_source(s.id)
        job = jobs.Job(lambda: ff.render_preview(ff.cached_frame(s, frame), grade))
        job.signals.done.connect(lambda data, g=gen, fr=frame: self._on_preview(g, fr, data))
        job.signals.error.connect(lambda msg: self._say(f"미리보기 오류: {msg[-160:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=5)

    def _on_preview(self, gen, frame, data):
        if gen != self.pgen or frame != self.player.frame or self.player.is_busy():
            return
        self.player.overlay_frame = frame
        self.player.show_image(QPixmap.fromImage(QImage.fromData(data, "PNG")))

    def _show_sample(self, sid, frame, pix):
        """샘플 클릭: 이동·재렌더 없이 그 PNG 를 모니터에 그대로."""
        self.player.pause()
        self._pv_timer.stop()
        self.pgen += 1            # 진행 중인 보정 화면이 덮어쓰지 않게
        self.player.overlay_frame = self.player.frame
        self.player.show_image(pix)
        s = self.state.project.source(sid)
        self._say(f"샘플 표시 중 ({timecode(frame, s.fps)}) — 이동하거나 재생하면 원래 화면으로", C_INFO)

    # ================================================================ 인/아웃·배속
    def mark_in(self):
        s = self._cur()
        f = self.player.frame
        self.state.checkpoint()
        s.sel_in = f
        if s.sel_out and s.sel_out <= f + 1:
            s.sel_out = 0
        self._after_io(f"인 {timecode(f, s.fps)}")

    def mark_out(self):
        s = self._cur()
        f = self.player.frame + 1   # 현재 프레임까지 포함
        self.state.checkpoint()
        s.sel_out = min(s.frames, f)
        if s.sel_in >= s.sel_out - 1:
            s.sel_in = 0
        self._after_io(f"아웃 {timecode(f - 1, s.fps)}")

    def clear_io(self):
        s = self._cur()
        self.state.checkpoint()
        s.sel_in, s.sel_out = 0, 0
        self._after_io("인/아웃 해제 (클립 전체)")

    def _after_io(self, what):
        s = self._cur()
        a, b = s.io
        sec = float((b - a) / s.fps / s.speed)
        self.state.dirty = True
        self._refresh_sbar()
        self._say(f"{what} → 구간 {timecode(a, s.fps)} ~ {timecode(b - 1, s.fps)} · {speed_label(s.speed)} · "
                  f"결과 {sec:.2f}초   ▼(↓) 타임라인 · ▶(Enter) 렌더 리스트", C_OK)

    def set_speed(self, sp):
        s = self._cur()
        self.state.checkpoint()
        s.speed = sp
        self._sync_speed_buttons()
        self._after_io(f"배속 {speed_label(sp)}")

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
        s = self._cur()
        self.state.checkpoint()
        self.state.project.segments.append(seg)
        self.state.touch("segments")
        n = len(self.state.project.segments)
        self._say(f"타임라인 {n}번째 컷 추가 ({self.state.project.seg_out_seconds(seg, s.fps):.2f}초) — "
                  f"타임라인 전체 {self.state.project.out_seconds():.1f}초", C_OK)
        QTimer.singleShot(0, lambda: self.tl_scroll.horizontalScrollBar().setValue(
            self.tl_scroll.horizontalScrollBar().maximum()))

    def _new_item(self, name, segs):
        o = self.state.project.output
        tag = "V" if o.orientation == "vertical" else "H"
        return RenderItem(name=f"{name}_{tag}", segs=segs, orientation=o.orientation, audio=o.audio)

    def send_to_render(self):
        s = self._cur()
        seg = self._cur_segment()
        self.state.checkpoint()
        self.state.project.render_items.append(self._new_item(Path(s.path).stem, [seg]))
        self.state.touch("render")
        self._say(f"렌더 리스트에 추가: {Path(s.path).stem} ({self.state.project.seg_out_seconds(seg, s.fps):.2f}초)"
                  f" — 렌더 탭에서 확인", C_OK)

    def timeline_to_render(self):
        p = self.state.project
        if not p.segments:
            self._say("타임라인이 비어 있습니다.", C_WARN)
            return
        self.state.checkpoint()
        segs = [Segment(g.src, g.fin, g.fout, g.speed) for g in p.segments]
        p.render_items.append(self._new_item(f"DTME_{time.strftime('%m%d_%H%M%S')}", segs))
        self.state.touch("render")
        sec = p.segs_seconds(segs)
        warn = " (30초 초과!)" if sec > OUTPUT_LIMIT_SEC else ""
        self._say(f"타임라인 {len(segs)}컷 → 렌더 리스트에 영상 1개로 추가 ({sec:.1f}초){warn}",
                  C_WARN if warn else C_OK)

    # ================================================================ 타임라인
    def clear_timeline(self):
        if not self.state.project.segments:
            return
        self.state.checkpoint()
        self.state.project.segments.clear()
        self.sel_cut = ""
        self.state.touch("segments")
        self._say("타임라인 비움 (실행취소: Ctrl+Z)", C_INFO)

    def delete_cut(self):
        p = self.state.project
        seg = next((g for g in p.segments if g.id == self.sel_cut), None)
        if not seg:
            self._say("삭제할 컷을 타임라인에서 먼저 클릭하세요.", C_WARN)
            return
        self.state.checkpoint()
        p.segments.remove(seg)
        self.sel_cut = ""
        self.state.touch("segments")
        self._say("컷 삭제 (실행취소: Ctrl+Z)", C_INFO)

    def _on_cut_selected(self, cid):
        self.sel_cut = cid
        self._refresh_timeline()
        p = self.state.project
        seg = next((g for g in p.segments if g.id == cid), None)
        if seg:
            s = p.source(seg.src)
            n = p.segments.index(seg) + 1
            self._say(f"컷 {n}: {s.name} {timecode(seg.fin, s.fps)}~{timecode(seg.fout - 1, s.fps)} "
                      f"{speed_label(seg.speed)} — 드래그로 순서 변경 · Del 삭제 · 더블클릭 = 소스 열기", C_INFO)

    def _on_cut_moved(self, a, b):
        segs = self.state.project.segments
        self.state.checkpoint()
        segs.insert(b, segs.pop(a))
        self.state.touch("segments")

    def _on_cut_activated(self, cid):
        seg = next((g for g in self.state.project.segments if g.id == cid), None)
        if seg:
            self._select_source(seg.src)
            self.player.pause()
            self.player.seek(seg.fin)

    # ================================================================ 스틸 (바로 PNG)
    def export_still(self):
        s = self._cur()
        frame = self.player.frame
        g = self.state.project.grade_for_source(s.id)
        path = unique(out_dir(self.state.project) / f"{Path(s.path).stem}_f{frame}.png")
        self.state.project.stills.append(Marker(s.id, frame))
        self._refresh_sbar()
        self._say(f"스틸 저장 중… {path.name} (4K 16bit PNG)", C_INFO)
        gpu = self.state.project.output.gpu_decode
        job = jobs.Job(lambda: ff.export_still(s, frame, g, str(path), gpu))
        job.signals.done.connect(lambda _r: self._say(f"스틸 저장 완료: {path}", C_OK))
        job.signals.error.connect(lambda m: self._say(f"스틸 저장 실패: {m[-200:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=8)

    # ================================================================ 갱신
    def _on_state(self, what):
        if what in ("project", "undo"):
            if what == "project" or not self._cur():
                self.cur_sid = ""
            self._refresh_sources()
            self.grade.set_current_source(self.cur_sid)
            if what == "undo":
                self._sync_speed_buttons()
                self._refresh_sbar()
        elif what == "sources":
            self._refresh_sources()
        if what in ("project", "undo", "sources", "segments", "grade", "output"):
            self._refresh_source_texts()
            self._refresh_timeline()
        if what in ("markers", "undo"):
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
                items.append((g.id, p.seg_out_seconds(g, s.fps), Path(s.path).stem[-8:], g.speed, self._tag(s.id)))
        if self.sel_cut and not any(i[0] == self.sel_cut for i in items):
            self.sel_cut = ""
        self.timeline.set_items(items, self.sel_cut)
        tot = sum(i[1] for i in items)
        color = "#e5484d" if tot > OUTPUT_LIMIT_SEC else "#aaa"
        self.tl_len.setText(f"<span style='color:{color}'>{len(items)}컷 · {tot:.1f} / {OUTPUT_LIMIT_SEC:.0f}초</span>")
