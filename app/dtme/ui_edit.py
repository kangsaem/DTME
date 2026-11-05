"""편집·보정 화면: 소스 목록 | 화면·조작·타임라인·구간 목록 | 보정 패널."""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import MAX_SAMPLES, OUTPUT_LIMIT_SEC, Marker, Segment, timecode
from .state import AppState
from .ui_grade import GradePanel
from .ui_player import Player
from .ui_timeline import SPEED_TEXT, Timeline

VIDEO_FILTER = "영상 (*.mp4 *.MP4 *.mov *.MOV)"

# Windows 물리 키(스캔코드) — 한/영 상태와 무관하게 동작
SCAN = {0x39: "space", 0x24: "j", 0x25: "k", 0x26: "l", 0x17: "i", 0x18: "o", 0x1F: "s", 0x22: "g",
        0x30: "b", 0x02: "1", 0x03: "2", 0x04: "3", 0x53: "del", 0x0E: "del", 0x01: "esc",
        0x4B: "left", 0x4D: "right"}
QKEY = {Qt.Key_Space: "space", Qt.Key_J: "j", Qt.Key_K: "k", Qt.Key_L: "l", Qt.Key_I: "i", Qt.Key_O: "o",
        Qt.Key_S: "s", Qt.Key_G: "g", Qt.Key_B: "b", Qt.Key_1: "1", Qt.Key_2: "2", Qt.Key_3: "3",
        Qt.Key_Delete: "del", Qt.Key_Backspace: "del", Qt.Key_Escape: "esc", Qt.Key_Left: "left",
        Qt.Key_Right: "right"}
TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)

C_INFO, C_OK, C_WARN = "#cfd8e3", "#7fd18b", "#f2c94c"


def _btn(text, tip, fn, w=None):
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(fn)
    if w:
        b.setMinimumWidth(w)
    return b


class EditTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.cur_sid = ""
        self.pending_in: int | None = None
        self.selected = ""
        self.next_speed = 1.0
        self.pgen = 0

        # ================= 왼쪽: 소스 목록
        self.src_list = QListWidget()
        self.src_list.setFocusPolicy(Qt.NoFocus)
        self.src_list.currentItemChanged.connect(self._on_src_selected)
        self.src_list.setToolTip("클릭하면 화면에 표시. 선택한 파일의 프록시를 먼저 만듭니다.")
        self.load_bar = QProgressBar()
        self.load_bar.setTextVisible(False)
        self.load_bar.setFixedHeight(8)
        self.load_text = QLabel("")
        self.load_text.setStyleSheet("color:#aaa; font-size:11px;")
        self.load_text.setWordWrap(True)
        self.load_text.setToolTip("프록시: 편집 화면 재생용 가벼운 복사본(960px, 모든 프레임이 기준 프레임).\n"
                                  "프레임 이동이 빨라지며, 최종 렌더는 항상 4K 원본을 씁니다.\n"
                                  "프록시가 준비되기 전에도 프레임 이동·컷 지정은 가능합니다(재생만 불가).")
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("소스 영상"))
        left.addWidget(self.src_list, 1)
        left.addWidget(self.load_text)
        left.addWidget(self.load_bar)
        row = QHBoxLayout()
        row.addWidget(_btn("영상 추가", "4K 원본 추가 (여러 개 선택 가능, 창에 끌어다 놓아도 됨)", self.add_files))
        row.addWidget(_btn("제거", "선택한 영상을 목록에서 제거 (원본 파일은 지우지 않음)", self._remove_source))
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)

        # ================= 가운데: 화면
        self.player = Player()
        self.player.frameChanged.connect(self._on_frame)
        self.player.playingChanged.connect(self._on_playing)

        self.tc = QLabel("--:--.--")
        self.tc.setTextFormat(Qt.RichText)
        self.tc.setStyleSheet("font: 600 18px 'Consolas', monospace;")
        self.mode_lab = QLabel("")
        self.mode_lab.setStyleSheet("color:#888; font-size:11px;")

        r1 = QHBoxLayout()
        p = self.player
        r1.addWidget(_btn("◀◀  J", "뒤로 재생 (누를수록 2·4·8배)", lambda: self._key("j"), 70))
        r1.addWidget(_btn("◀ 1프레임  ←", "1프레임 뒤로 (Shift+← = 1초)", lambda: self._key("left"), 100))
        r1.addWidget(_btn("▶ / ❚❚   Space", "재생 / 정지", lambda: self._key("space"), 110))
        r1.addWidget(_btn("→  1프레임 ▶", "1프레임 앞으로 (Shift+→ = 1초)", lambda: self._key("right"), 100))
        r1.addWidget(_btn("L  ▶▶", "앞으로 재생 (누를수록 2·4·8배)", lambda: self._key("l"), 70))
        r1.addWidget(_btn("K ❚❚", "정지", lambda: self._key("k"), 50))
        r1.addStretch(1)
        r1.addWidget(self.mode_lab)
        r1.addSpacing(10)
        r1.addWidget(self.tc)

        r2 = QHBoxLayout()
        self.b_in = _btn("[ 컷인  I", "현재 프레임을 구간 시작으로 (구간 선택 중이면 그 구간의 시작 수정)",
                         lambda: self._key("i"), 80)
        self.b_out = _btn("컷아웃  O ]", "현재 프레임까지를 구간 끝으로 → 아래 목록에 추가", lambda: self._key("o"), 90)
        self.b_in.setStyleSheet("QPushButton{background:#3a3a26;}")
        self.b_out.setStyleSheet("QPushButton{background:#3a3a26;}")
        r2.addWidget(self.b_in)
        r2.addWidget(self.b_out)
        r2.addWidget(_btn("구간 삭제  Del", "선택한 구간 삭제 (컷인 대기 중이면 취소)", lambda: self._key("del")))
        r2.addWidget(_btn("선택 해제  Esc", "구간 선택 해제", lambda: self._key("esc")))
        r2.addSpacing(14)
        r2.addWidget(QLabel("배속"))
        self.speed_group = QButtonGroup(self)
        self.speed_group.setExclusive(True)
        for i, (sp, key) in enumerate(((2.0, "1"), (1.0, "2"), (0.5, "3"))):
            b = QPushButton(f"{SPEED_TEXT[sp]}  ({key})")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip("구간 선택 중이면 그 구간의 배속, 아니면 다음에 만들 구간의 배속")
            b.clicked.connect(lambda _=False, k=key: self._key(k))
            self.speed_group.addButton(b, i)
            r2.addWidget(b)
        self.speed_group.button(1).setChecked(True)
        r2.addSpacing(14)
        r2.addWidget(_btn("◆ 스틸  S", "현재 프레임을 4K 스틸로 표시", lambda: self._key("s")))
        r2.addWidget(_btn("● 샘플  G", f"현재 프레임을 보정 샘플로 (최대 {MAX_SAMPLES}장)", lambda: self._key("g")))
        r2.addStretch(1)
        self.chk_preview = QCheckBox("정지 시 보정 화면")
        self.chk_preview.setChecked(True)
        self.chk_preview.setFocusPolicy(Qt.NoFocus)
        self.chk_preview.setToolTip("켜면: 멈췄을 때 원본에서 최종 결과와 같은 보정 화면을 만들어 보여줌\n"
                                    "끄면: 프록시 화면 그대로(LUT만 적용)")
        self.chk_preview.toggled.connect(lambda _: self.request_preview(force=True))
        r2.addWidget(self.chk_preview)

        self.status = QLabel("")
        self.status.setStyleSheet("font-size:13px; padding:3px 6px; background:#1c1c1c; border-radius:3px;")
        self.out_len = QLabel("")

        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self._seek_from_timeline)
        self.timeline.segmentClicked.connect(self._select_segment)
        self.timeline.stillClicked.connect(self._on_still_clicked)

        # 구간 목록
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "소스", "컷인", "컷아웃", "배속", "결과 길이"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.cellClicked.connect(self._on_table_click)
        tb = QVBoxLayout()
        tb.addWidget(_btn("▲ 위로", "출력 순서 위로", lambda: self._move(-1)))
        tb.addWidget(_btn("▼ 아래로", "출력 순서 아래로", lambda: self._move(1)))
        tb.addStretch(1)
        trow = QHBoxLayout()
        trow.addWidget(self.table, 1)
        trow.addLayout(tb)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addWidget(self.player, 1)
        center.addLayout(r1)
        center.addLayout(r2)
        srow = QHBoxLayout()
        srow.addWidget(self.status, 1)
        srow.addWidget(self.out_len)
        center.addLayout(srow)
        center.addWidget(self.timeline)
        hint = QLabel("타임라인: 클릭·드래그 = 이동 · 휠 = 확대/축소 · 블록 클릭 = 구간 선택 · ◆ 클릭 = 스틸 보정")
        hint.setStyleSheet("color:#777; font-size:11px;")
        center.addWidget(hint)
        cw = QWidget()
        cw.setLayout(center)
        tw = QWidget()
        trow.setContentsMargins(0, 0, 0, 0)
        tw.setLayout(trow)
        vs = QSplitter(Qt.Vertical)
        vs.addWidget(cw)
        vs.addWidget(tw)
        vs.setSizes([680, 170])

        # ================= 오른쪽: 보정
        self.grade = GradePanel(state)
        self.grade.gradeChanged.connect(lambda: self.request_preview(force=True))
        self.grade.beforeToggled.connect(lambda _: self.request_preview(force=True))
        self.grade.seekRequested.connect(self._goto)

        hs = QSplitter(Qt.Horizontal)
        hs.addWidget(lw)
        hs.addWidget(vs)
        hs.addWidget(self.grade)
        hs.setStretchFactor(1, 1)
        hs.setSizes([230, 900, 360])
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
        if e.isAutoRepeat() and name not in ("left", "right"):
            return True
        self._key(name, shift=bool(e.modifiers() & Qt.ShiftModifier))
        return True

    def _key(self, name, shift=False):
        p = self.player
        src = self._cur()
        if src is None or not src.frames:
            if name not in ("esc",):
                self._say("먼저 왼쪽 목록에서 영상을 선택하세요 (분석이 끝나야 합니다).", C_WARN)
            return
        if name == "space":
            if not p.toggle():
                self._say("프록시 준비 전이라 재생은 아직 안 됩니다. ←/→ 로 프레임 이동, 컷 지정은 가능합니다.", C_WARN)
        elif name == "j":
            if not p.backward():
                self._say("프록시 준비 후 재생할 수 있습니다.", C_WARN)
        elif name == "k":
            p.pause()
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
            self._speed_key({"1": 2.0, "2": 1.0, "3": 0.5}[name])
        elif name == "del":
            self._delete_selected()
        elif name == "esc":
            self._select_segment("")
            self._say("선택 해제", C_INFO)
        elif name == "s":
            self.add_still()
        elif name == "g":
            self.add_sample()
        elif name == "b":
            self.grade.before.toggle()

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
        extra = f"\n현재 파일: {self.state.status.get(cur.id, '')}" if cur else ""
        if done >= n:
            self.load_text.setText(f"{n}개 모두 준비됨{extra}")
        else:
            self.load_text.setText(f"분석 {a}/{n} · 프록시 {done}/{n}{extra}")
        self.load_bar.setValue(int(frac * 100))

    # ================================================================ 소스
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "영상 추가", "", VIDEO_FILTER)
        if files:
            self.import_files(files)

    def import_files(self, files):
        n = self.state.import_files(files)
        if n:
            self._say(f"{n}개 추가 — 분석·프록시 생성은 뒤에서 진행됩니다. 첫 장면부터 바로 볼 수 있습니다.", C_OK)

    def _remove_source(self):
        s = self._cur()
        if not s:
            return
        n = len(self.state.project.segments_of(s.id))
        if QMessageBox.question(self, "제거", f"{s.name} 을(를) 목록에서 제거할까요?\n"
                                f"(이 영상의 구간 {n}개, 스틸·샘플도 함께 삭제 · 원본 파일은 그대로)") == QMessageBox.Yes:
            self.cur_sid = ""
            self.state.remove_source(s.id)

    def _src_text(self, s):
        st = self.state.status.get(s.id, "")
        n = len(self.state.project.segments_of(s.id))
        tail = f" · 구간 {n} · {self.state.project.out_seconds(s.id):.1f}초" if n else ""
        dur = f" · {s.frames / float(s.fps):.0f}초" if s.frames else ""
        return f"{s.name}\n   {st}{dur}{tail}"

    def _refresh_sources(self):
        p = self.state.project
        self.src_list.blockSignals(True)
        self.src_list.clear()
        sel = None
        for s in p.sources:
            it = QListWidgetItem(self._src_text(s))
            it.setData(Qt.UserRole, s.id)
            self.src_list.addItem(it)
            if s.id == self.cur_sid:
                sel = it
        if sel:
            self.src_list.setCurrentItem(sel)
        self.src_list.blockSignals(False)
        if not sel and p.sources:
            self.src_list.setCurrentRow(0)     # 처음 파일 자동 선택
        elif not p.sources:
            self.cur_sid = ""
            self.player.clear("왼쪽 ‘영상 추가’로 4K 원본을 불러오세요\n(여러 개 선택 가능 · 창에 끌어다 놓아도 됩니다)")
            self.grade.set_current_source("")
            self._refresh_timeline()

    def _on_source_status(self, sid):
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            if it.data(Qt.UserRole) == sid:
                s = self.state.project.source(sid)
                if s:
                    it.setText(self._src_text(s))
        if sid != self.cur_sid:
            return
        s = self._cur()
        if s is None:
            return
        # 분석 완료 → 정지화면 모드로 첫 장면 표시 / 프록시 완료 → 재생 가능
        if s.frames and self.player.frames == 0:
            self._load_current()
        elif self.state.proxy_ready(s) and not self.player.has_media and not self.player.is_playing():
            self.player.set_source(s.fps, s.frames, s.proxy, self.player.frame)
            self._update_mode()
            self._say("프록시 준비 완료 — 이제 재생(Space, J/K/L)할 수 있습니다.", C_OK)

    def _on_src_selected(self, cur, _prev):
        if cur is None:
            return
        self.cur_sid = cur.data(Qt.UserRole)
        self.pending_in = None
        self.selected = ""
        self.state.prioritize(self.cur_sid)
        self.grade.set_current_source(self.cur_sid)
        self._load_current()
        self._refresh_table()
        self._on_import_progress()

    def _load_current(self):
        s = self._cur()
        if s is None:
            return
        if not s.frames:
            self.player.clear(f"{s.name}\n분석 중…")
            self._refresh_timeline()
            return
        proxy = s.proxy if self.state.proxy_ready(s) else None
        self.player.set_source(s.fps, s.frames, proxy, 0)
        self._update_mode()
        self._refresh_timeline()
        self.request_preview(force=True)

    def _update_mode(self):
        s = self._cur()
        if not s:
            self.mode_lab.setText("")
        elif self.player.has_media:
            self.mode_lab.setText("재생: 프록시")
        else:
            self.mode_lab.setText("프록시 준비 중 · 정지화면 모드")

    def _cur(self):
        return self.state.project.source(self.cur_sid)

    def _goto(self, sid, frame):
        if sid != self.cur_sid:
            for i in range(self.src_list.count()):
                if self.src_list.item(i).data(Qt.UserRole) == sid:
                    self.src_list.setCurrentRow(i)
        self.player.pause()
        self.player.seek(frame)

    # ================================================================ 보정 화면 미리보기
    def _on_frame(self, f):
        s = self._cur()
        if s:
            self.tc.setText(f"{timecode(f, s.fps)} <span style='color:#777;font-size:11px'>#{f}</span>")
        self.timeline.set_playhead(f)
        if not self.player.is_playing() and not self.player._back_timer.isActive():
            if self.player.has_media:
                self.player.show_video()       # 이동 직후엔 프록시 화면 → 멈추면 보정 화면
            self._pv_timer.start()

    def _on_playing(self, playing):
        if playing:
            self._pv_timer.stop()
        else:
            self._pv_timer.start()

    def request_preview(self, force=False):
        s = self._cur()
        p = self.player
        if not s or not s.frames or p.is_playing():
            return
        if not self.chk_preview.isChecked() and p.has_media:
            p.show_video()
            return
        self.pgen += 1
        gen, frame = self.pgen, p.frame
        before = self.grade.before.isChecked()
        grade = None if before else self.grade.preview_grade(s.id, frame)

        def work():
            return ff.render_preview(ff.cached_frame(s, frame), grade)

        job = jobs.Job(work)
        job.signals.done.connect(lambda data, g=gen, fr=frame: self._on_preview(g, fr, data))
        job.signals.error.connect(lambda msg: self._say(f"미리보기 오류: {msg[-160:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=5)

    def _on_preview(self, gen, frame, data):
        if gen != self.pgen or frame != self.player.frame or self.player.is_playing():
            return
        self.player.show_image(QPixmap.fromImage(QImage.fromData(data, "PNG")))

    # ================================================================ 컷 지정
    def _seg(self, sid):
        return next((g for g in self.state.project.segments if g.id == sid), None)

    def mark_in(self):
        s = self._cur()
        f = self.player.frame
        seg = self._seg(self.selected)
        if seg:
            if f < seg.fout - 1:
                seg.fin = f
                self.state.touch("segments")
                self._say(f"구간 시작 수정 → {timecode(f, s.fps)}", C_OK)
            else:
                self._say("시작은 끝보다 앞이어야 합니다.", C_WARN)
            return
        self.pending_in = f
        self._refresh_table()
        self._refresh_timeline()
        self._say(f"컷인 {timecode(f, s.fps)} 지정 → 끝낼 지점으로 이동해서 O (컷아웃)", C_WARN)

    def mark_out(self):
        s = self._cur()
        f = self.player.frame + 1   # 현재 프레임까지 포함
        seg = self._seg(self.selected)
        if seg:
            if f > seg.fin + 1:
                seg.fout = min(s.frames, f)
                self.state.touch("segments")
                self._say(f"구간 끝 수정 → {timecode(f - 1, s.fps)}", C_OK)
            else:
                self._say("끝은 시작보다 뒤여야 합니다.", C_WARN)
            return
        if self.pending_in is None:
            self._say("먼저 시작 지점에서 I (컷인)을 누르세요.", C_WARN)
            return
        fin = self.pending_in
        if f <= fin + 1:
            self._say("컷아웃은 컷인보다 뒤여야 합니다. 앞으로 이동한 뒤 O.", C_WARN)
            return
        seg = Segment(s.id, fin, min(s.frames, f), self.next_speed)
        self.state.project.segments.append(seg)
        self.pending_in = None
        self.state.touch("segments")
        sec = self.state.project.seg_out_seconds(seg, s.fps)
        self._say(f"구간 추가: {timecode(seg.fin, s.fps)} ~ {timecode(seg.fout - 1, s.fps)} · "
                  f"{SPEED_TEXT[seg.speed]} · 결과 {sec:.2f}초", C_OK)

    def _speed_key(self, sp):
        idx = {2.0: 0, 1.0: 1, 0.5: 2}[sp]
        seg = self._seg(self.selected)
        if seg:
            seg.speed = sp
            self.state.touch("segments")
            self._say(f"선택 구간 배속 → {SPEED_TEXT[sp]}", C_OK)
        else:
            self.next_speed = sp
            self._say(f"다음 구간 배속 → {SPEED_TEXT[sp]}", C_INFO)
        self.speed_group.button(idx).setChecked(True)

    def _select_segment(self, sid):
        self.selected = sid
        seg = self._seg(sid)
        if seg:
            if seg.src != self.cur_sid:
                self._goto(seg.src, seg.fin)
            self.speed_group.button({2.0: 0, 1.0: 1, 0.5: 2}[seg.speed]).setChecked(True)
            n = self.state.project.segments.index(seg) + 1
            self._say(f"구간 #{n} 선택 — I/O 로 시작·끝 수정, 1/2/3 배속, Del 삭제, Esc 해제", C_INFO)
        else:
            self.speed_group.button({2.0: 0, 1.0: 1, 0.5: 2}[self.next_speed]).setChecked(True)
        self._refresh_table()
        self._refresh_timeline()

    def _delete_selected(self):
        seg = self._seg(self.selected)
        if seg:
            self.state.project.segments.remove(seg)
            self.selected = ""
            self.state.touch("segments")
            self._say("구간 삭제", C_INFO)
        elif self.pending_in is not None:
            self.pending_in = None
            self._refresh_table()
            self._refresh_timeline()
            self._say("컷인 대기 취소", C_INFO)

    def _move(self, d):
        segs = self.state.project.segments
        seg = self._seg(self.selected)
        if not seg:
            self._say("순서를 바꿀 구간을 먼저 선택하세요.", C_WARN)
            return
        i = segs.index(seg)
        j = i + d
        if 0 <= j < len(segs):
            segs[i], segs[j] = segs[j], segs[i]
            self.state.touch("segments")

    def _on_table_click(self, row, _col):
        segs = self.state.project.segments
        if 0 <= row < len(segs):
            seg = segs[row]
            self._select_segment(seg.id)
            self._goto(seg.src, seg.fin)

    def _seek_from_timeline(self, f):
        self.player.pause()
        self.player.seek(f)

    # ================================================================ 스틸 / 샘플
    def add_still(self):
        s = self._cur()
        m = Marker(s.id, self.player.frame)
        self.state.project.stills.append(m)
        self.state.touch("markers")
        self._say(f"◆ 스틸 {len(self.state.project.stills)} 추가 ({timecode(m.frame, s.fps)}) — "
                  "오른쪽 ‘보정 대상’에서 골라 추가 조정", C_OK)

    def add_sample(self):
        s = self._cur()
        if len(self.state.project.samples) >= MAX_SAMPLES:
            self._say(f"보정 샘플은 최대 {MAX_SAMPLES}장입니다. 오른쪽에서 지운 뒤 추가하세요.", C_WARN)
            return
        self.state.project.samples.append(Marker(s.id, self.player.frame))
        self.state.touch("markers")
        self._say(f"● 샘플 {len(self.state.project.samples)}/{MAX_SAMPLES} 추가", C_OK)

    def _on_still_clicked(self, frame):
        m = next((x for x in self.state.project.stills if x.src == self.cur_sid and x.frame == frame), None)
        if m:
            self.grade.select_still(m.id)
            self._goto(m.src, m.frame)
            self._say("스틸 보정 중 — 오른쪽 값은 이 스틸에만 추가 적용됩니다.", C_INFO)

    # ================================================================ 갱신
    def _on_state(self, what):
        if what in ("project", "sources"):
            if what == "project":
                self.cur_sid = ""
            self._refresh_sources()
        if what in ("project", "sources", "segments"):
            for i in range(self.src_list.count()):
                it = self.src_list.item(i)
                s = self.state.project.source(it.data(Qt.UserRole))
                if s:
                    it.setText(self._src_text(s))
            self._refresh_table()
        if what == "output":
            self._refresh_len()
        self._refresh_timeline()

    def _refresh_table(self):
        p = self.state.project
        rows = list(p.segments)
        pend = self.pending_in is not None and self._cur() is not None
        self.table.setRowCount(len(rows) + (1 if pend else 0))
        for r, seg in enumerate(rows):
            s = p.source(seg.src)
            if not s or not s.frames:
                continue
            vals = [str(r + 1), s.name, timecode(seg.fin, s.fps), timecode(seg.fout - 1, s.fps),
                    SPEED_TEXT.get(seg.speed, str(seg.speed)), f"{p.seg_out_seconds(seg, s.fps):.2f}초"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c != 1:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            if seg.id == self.selected:
                self.table.selectRow(r)
        if pend:
            s = self._cur()
            r = len(rows)
            vals = ["…", s.name, timecode(self.pending_in, s.fps), "O 를 누르세요", SPEED_TEXT[self.next_speed], ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setForeground(Qt.yellow)
                if c != 1:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            self.table.scrollToBottom()
        if not self.selected:
            self.table.clearSelection()
        self._refresh_len()

    def _refresh_len(self):
        p = self.state.project
        cur = p.out_seconds(self.cur_sid) if self.cur_sid else 0
        total = p.out_seconds()
        val = total if p.output.mode == "concat" else cur
        color = "#e5484d" if val > OUTPUT_LIMIT_SEC else "#ddd"
        mode = "이어붙이기 전체" if p.output.mode == "concat" else "이 영상"
        self.out_len.setText(f"<span style='color:{color}; font-weight:600'>결과({mode}) {val:.1f} / "
                             f"{OUTPUT_LIMIT_SEC:.0f}초</span> <span style='color:#888'>· 전체 {total:.1f}초</span>")

    def _refresh_timeline(self):
        p = self.state.project
        s = self._cur()
        if not s or not s.frames:
            self.timeline.set_data(1, [], [], [], "", None)
            return
        self.timeline.set_data(s.frames, p.segments_of(s.id), [m.frame for m in p.stills if m.src == s.id],
                               [m.frame for m in p.samples if m.src == s.id], self.selected, self.pending_in)
        self._refresh_len()
