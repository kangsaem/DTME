"""편집 탭: 소스 목록, 플레이어, 단축키, 타임라인, 구간 목록."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .project import MAX_SAMPLES, OUTPUT_LIMIT_SEC, Marker, Segment, timecode
from .state import AppState
from .ui_player import Player
from .ui_timeline import SPEED_TEXT, Timeline

VIDEO_FILTER = "영상 (*.mp4 *.MP4 *.mov *.MOV)"

HELP = ("Space 재생/정지 · J/K/L 뒤로/정지/앞으로(반복 시 빨라짐) · ←/→ 1프레임 · Shift+←/→ 1초 · "
        "I 컷인 · O 컷아웃 · 1/2/3 = 2x/1x/½x · Del 구간 삭제 · Esc 선택 해제 · S 스틸 · G 보정 샘플 · 휠 = 타임라인 확대")


class EditTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.cur_sid = ""
        self.pending_in: int | None = None
        self.selected = ""
        self.next_speed = 1.0

        # --- 소스 목록
        self.src_list = QListWidget()
        self.src_list.setFocusPolicy(Qt.NoFocus)
        self.src_list.currentItemChanged.connect(self._on_src_selected)
        b_add = QPushButton("영상 추가")
        b_add.clicked.connect(self.add_files)
        b_del = QPushButton("목록에서 제거")
        b_del.clicked.connect(self._remove_source)
        for b in (b_add, b_del):
            b.setFocusPolicy(Qt.NoFocus)
        left = QVBoxLayout()
        left.addWidget(QLabel("소스 영상"))
        left.addWidget(self.src_list, 1)
        row = QHBoxLayout()
        row.addWidget(b_add)
        row.addWidget(b_del)
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)

        # --- 플레이어 + 조작
        self.player = Player()
        self.player.frameChanged.connect(self._on_frame)
        self.tc = QLabel("00:00.00")
        self.tc.setStyleSheet("font: 600 16px 'Consolas', monospace;")
        self.out_len = QLabel("")
        self.out_len.setStyleSheet("font-size:13px;")

        btns = QHBoxLayout()
        for text, fn in (("◀◀ J", self.player.backward), ("◀ ←", lambda: self.player.step(-1)),
                         ("▶ / ❚❚", self.player.toggle), ("→ ▶", lambda: self.player.step(1)),
                         ("L ▶▶", self.player.forward)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addSpacing(16)
        btns.addWidget(QLabel("새 구간 배속:"))
        self.speed_group = QButtonGroup(self)
        for i, sp in enumerate((2.0, 1.0, 0.5)):
            rb = QRadioButton(f"{SPEED_TEXT[sp]} ({i + 1})")
            rb.setFocusPolicy(Qt.NoFocus)
            rb.setChecked(sp == 1.0)
            rb.toggled.connect(lambda on, s=sp: on and self._set_next_speed(s))
            self.speed_group.addButton(rb, i)
            btns.addWidget(rb)
        btns.addStretch(1)
        btns.addWidget(self.tc)

        self.timeline = Timeline()
        self.timeline.seekRequested.connect(lambda f: (self.player.pause(), self.player.seek(f)))
        self.timeline.segmentClicked.connect(self._select_segment)

        # --- 구간 목록
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["소스", "컷인", "컷아웃", "배속", "결과 길이"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.cellClicked.connect(self._on_table_click)
        tb = QVBoxLayout()
        for text, fn in (("▲ 위로", lambda: self._move(-1)), ("▼ 아래로", lambda: self._move(1)),
                         ("삭제", self._delete_selected)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            tb.addWidget(b)
        tb.addStretch(1)
        trow = QHBoxLayout()
        trow.addWidget(self.table, 1)
        trow.addLayout(tb)

        center = QVBoxLayout()
        center.addWidget(self.player, 1)
        center.addLayout(btns)
        center.addWidget(self.timeline)
        info = QHBoxLayout()
        hl = QLabel(HELP)
        hl.setWordWrap(True)
        hl.setStyleSheet("color:#888; font-size:11px;")
        info.addWidget(hl, 1)
        info.addWidget(self.out_len)
        center.addLayout(info)
        cw = QWidget()
        cw.setLayout(center)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(lw)
        top.addWidget(cw)
        top.setStretchFactor(1, 1)
        top.setSizes([260, 1000])
        tw = QWidget()
        tw.setLayout(trow)
        vs = QSplitter(Qt.Vertical)
        vs.addWidget(top)
        vs.addWidget(tw)
        vs.setSizes([620, 200])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(vs)

        self._shortcuts()
        state.changed.connect(self._on_state)
        state.proxyStatus.connect(self._on_proxy)

    # ------------------------------------------------------------ 단축키
    def _shortcuts(self):
        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(fn)

        p = self.player
        sc(Qt.Key_Space, p.toggle)
        sc(Qt.Key_J, p.backward)
        sc(Qt.Key_K, p.pause)
        sc(Qt.Key_L, p.forward)
        sc(Qt.Key_Left, lambda: p.step(-1))
        sc(Qt.Key_Right, lambda: p.step(1))
        sc("Shift+Left", lambda: p.step(-round(float(p.fps))))
        sc("Shift+Right", lambda: p.step(round(float(p.fps))))
        sc(Qt.Key_I, self.mark_in)
        sc(Qt.Key_O, self.mark_out)
        sc(Qt.Key_1, lambda: self._speed_key(2.0))
        sc(Qt.Key_2, lambda: self._speed_key(1.0))
        sc(Qt.Key_3, lambda: self._speed_key(0.5))
        sc(Qt.Key_Delete, self._delete_selected)
        sc(Qt.Key_Escape, lambda: self._select_segment(""))
        sc(Qt.Key_S, self.add_still)
        sc(Qt.Key_G, self.add_sample)

    # ------------------------------------------------------------ 소스
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "영상 추가", "", VIDEO_FILTER)
        if files:
            self.import_files(files)

    def import_files(self, files):
        warns = self.state.import_files(files)
        if warns:
            QMessageBox.warning(self, "확인 필요", "\n".join(warns))

    def _remove_source(self):
        if not self.cur_sid:
            return
        s = self.state.project.source(self.cur_sid)
        n = len(self.state.project.segments_of(self.cur_sid))
        if QMessageBox.question(self, "제거", f"{s.name} 을(를) 목록에서 제거할까요?\n(이 영상의 구간 {n}개, 스틸·샘플도 함께 삭제)") \
                == QMessageBox.Yes:
            self.cur_sid = ""
            self.state.remove_source(s.id)

    def _src_text(self, s):
        st = self.state.proxy_state.get(s.id, "")
        n = len(self.state.project.segments_of(s.id))
        return f"{s.name}\n   {st} · 구간 {n}개 · {self.state.project.out_seconds(s.id):.1f}초"

    def _refresh_sources(self):
        p = self.state.project
        self.src_list.blockSignals(True)
        self.src_list.clear()
        for s in p.sources:
            it = QListWidgetItem(self._src_text(s))
            it.setData(Qt.UserRole, s.id)
            self.src_list.addItem(it)
            if s.id == self.cur_sid:
                self.src_list.setCurrentItem(it)
        self.src_list.blockSignals(False)
        if not self.cur_sid and p.sources:
            self.src_list.setCurrentRow(0)
        elif not p.sources:
            self.player.show_message("‘영상 추가’로 4K 원본을 불러오세요 (여러 개 선택 가능, 창에 끌어다 놓아도 됨)")

    def _on_proxy(self, sid):
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            if it.data(Qt.UserRole) == sid:
                it.setText(self._src_text(self.state.project.source(sid)))
        if sid == self.cur_sid and self.state.proxy_state.get(sid) == "준비" \
                and self.player._stack.currentWidget() is not self.player.video:
            self._load_current()

    def _on_src_selected(self, cur, _prev):
        if cur is None:
            return
        self.cur_sid = cur.data(Qt.UserRole)
        self.pending_in = None
        self.selected = ""
        self._load_current()

    def _load_current(self):
        s = self.state.project.source(self.cur_sid)
        if s is None:
            return
        if self.state.proxy_state.get(s.id) == "준비" and s.proxy:
            self.player.load(s.proxy, s.fps, s.frames)
        else:
            self.player.show_message(f"{s.name}\n프록시 준비 중… ({self.state.proxy_state.get(s.id, '')})")
        self._refresh_timeline()

    # ------------------------------------------------------------ 컷 지정
    def _cur(self):
        return self.state.project.source(self.cur_sid)

    def _seg(self, sid):
        return next((g for g in self.state.project.segments if g.id == sid), None)

    def mark_in(self):
        if not self._cur():
            return
        f = self.player.frame
        seg = self._seg(self.selected)
        if seg and f < seg.fout:
            seg.fin = f
            self.state.touch("segments")
        else:
            self.pending_in = f
            self._refresh_timeline()

    def mark_out(self):
        src = self._cur()
        if not src:
            return
        f = self.player.frame + 1   # 현재 프레임까지 포함
        seg = self._seg(self.selected)
        if seg and f > seg.fin:
            seg.fout = min(src.frames, f)
            self.state.touch("segments")
            return
        fin = self.pending_in if self.pending_in is not None else 0
        if f - fin < 2:
            return
        self.state.project.segments.append(Segment(src.id, fin, min(src.frames, f), self.next_speed))
        self.pending_in = None
        self.state.touch("segments")

    def _set_next_speed(self, sp):
        self.next_speed = sp

    def _speed_key(self, sp):
        seg = self._seg(self.selected)
        if seg:
            seg.speed = sp
            self.state.touch("segments")
        else:
            self.speed_group.button({2.0: 0, 1.0: 1, 0.5: 2}[sp]).setChecked(True)

    def _select_segment(self, sid):
        self.selected = sid
        seg = self._seg(sid)
        if seg and seg.src != self.cur_sid:
            self._select_source(seg.src)
        self._refresh_table()
        self._refresh_timeline()

    def _select_source(self, sid):
        for i in range(self.src_list.count()):
            if self.src_list.item(i).data(Qt.UserRole) == sid:
                self.src_list.setCurrentRow(i)

    def _delete_selected(self):
        seg = self._seg(self.selected)
        if seg:
            self.state.project.segments.remove(seg)
            self.selected = ""
            self.state.touch("segments")

    def _move(self, d):
        segs = self.state.project.segments
        seg = self._seg(self.selected)
        if not seg:
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
            self.player.pause()
            self.player.seek(seg.fin)

    # ------------------------------------------------------------ 스틸 / 샘플
    def add_still(self):
        src = self._cur()
        if src:
            self.state.project.stills.append(Marker(src.id, self.player.frame))
            self.state.touch("markers")

    def add_sample(self):
        src = self._cur()
        if not src:
            return
        if len(self.state.project.samples) >= MAX_SAMPLES:
            QMessageBox.information(self, "샘플", f"보정 샘플은 최대 {MAX_SAMPLES}장입니다. 보정 탭에서 지운 뒤 추가하세요.")
            return
        self.state.project.samples.append(Marker(src.id, self.player.frame))
        self.state.touch("markers")

    # ------------------------------------------------------------ 갱신
    def _on_state(self, what):
        if what in ("project", "sources"):
            if what == "project":
                self.cur_sid = ""
            self._refresh_sources()
        if what in ("project", "sources", "segments"):
            self._refresh_sources_text()
            self._refresh_table()
        self._refresh_timeline()

    def _refresh_sources_text(self):
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            s = self.state.project.source(it.data(Qt.UserRole))
            if s:
                it.setText(self._src_text(s))

    def _refresh_table(self):
        p = self.state.project
        self.table.setRowCount(len(p.segments))
        for r, seg in enumerate(p.segments):
            s = p.source(seg.src)
            vals = [s.name if s else "?", timecode(seg.fin, s.fps), timecode(seg.fout, s.fps),
                    SPEED_TEXT.get(seg.speed, str(seg.speed)), f"{p.seg_out_seconds(seg, s.fps):.2f}초"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            if seg.id == self.selected:
                self.table.selectRow(r)
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
        self.out_len.setText(f"<span style='color:{color}; font-weight:600'>결과 길이({mode}) {val:.1f} / "
                             f"{OUTPUT_LIMIT_SEC:.0f}초</span>  <span style='color:#888'>전체 {total:.1f}초</span>")

    def _refresh_timeline(self):
        p = self.state.project
        s = self._cur()
        if not s:
            self.timeline.set_data(1, [], [], [], "", None)
            return
        self.timeline.set_data(s.frames, p.segments_of(s.id), [m.frame for m in p.stills if m.src == s.id],
                               [m.frame for m in p.samples if m.src == s.id], self.selected, self.pending_in)
        self._refresh_len()

    def _on_frame(self, f):
        s = self._cur()
        if s:
            self.tc.setText(f"{timecode(f, s.fps)}  <span style='color:#888;font-size:11px'>#{f}</span>")
            self.tc.setTextFormat(Qt.RichText)
        self.timeline.set_playhead(f)
