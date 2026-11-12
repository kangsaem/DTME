"""편집·보정 화면: 소스 | 모니터·소스 바·조작·타임라인 | 보정 | 렌더 리스트."""
from __future__ import annotations

import copy
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                               QSplitter, QStyle, QStyledItemDelegate, QTextEdit, QVBoxLayout, QWidget)

from . import ff, jobs, ui_style
from .project import (MAX_LAYERS, TITLE_DEFAULT_SEC, Marker, RenderItem, Segment, display_name, grade_at, has_clip_grade, is_plain, new_layer,
                      new_music, new_text, new_title_image, reframe_at, reframe_max, short_name,
                      speed_label, timecode)
from .state import AppState
from .ui_bars import LayerBar, SeqTimeline, SourceBar
from .ui_grade import GradePanel
from .ui_player import Player
from .ui_render import (ADD_W, MAIN_H, MAIN_W, RenderPanel, fix_size, item_base, out_dir,
                        render_list_button, unique)

MEDIA_FILTER = ("영상·이미지·음악 (*.mp4 *.MP4 *.mov *.MOV *.jpg *.JPG *.jpeg *.JPEG *.png *.PNG "
                "*.mp3 *.MP3 *.m4a *.M4A *.wav *.WAV *.flac *.FLAC *.aac *.AAC)")
IMG_DISPLAY_MAX = 2048      # 모니터 표시용 이미지 최대 변(렌더는 원본 사용)

# Windows 물리 키(스캔코드) — 한/영 상태와 무관하게 동작
SCAN = {0x11: "w", 0x32: "m", 0x39: "space", 0x24: "j", 0x26: "l", 0x17: "i", 0x18: "o", 0x1A: "i", 0x1B: "o", 0x1F: "s", 0x22: "g",
        0x30: "b", 0x02: "1", 0x03: "2", 0x04: "3", 0x53: "del", 0x0E: "del", 0x01: "esc",
        0x4B: "left", 0x4D: "right", 0x50: "down", 0x1C: "enter", 0x2C: "z", 0x15: "y"}
QKEY = {Qt.Key_W: "w", Qt.Key_M: "m", Qt.Key_Space: "space", Qt.Key_J: "j", Qt.Key_L: "l", Qt.Key_I: "i", Qt.Key_O: "o",
        Qt.Key_BracketLeft: "i", Qt.Key_BracketRight: "o", Qt.Key_S: "s", Qt.Key_G: "g", Qt.Key_B: "b",
        Qt.Key_1: "1", Qt.Key_2: "2", Qt.Key_3: "3", Qt.Key_Delete: "del", Qt.Key_Backspace: "del",
        Qt.Key_Escape: "esc", Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Down: "down",
        Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Z: "z", Qt.Key_Y: "y"}
TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)

C_INFO, C_OK, C_WARN = "#cfd8e3", "#7fd18b", "#f2c94c"


def _btn(text, tip, fn, main=False):
    """버튼 크기 통일: 일반 BTN_W×BTN_H, 주요 MAIN_W×MAIN_H."""
    b = QPushButton(text)
    if tip:
        b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(fn)
    return fix_size(b, main)


PREVIEW_LRU: "OrderedDict[tuple, tuple]" = OrderedDict()   # 보정 미리보기 PNG (최근 120장 ≈ 200MB)
PREVIEW_LRU_MAX = 120
PREVIEW_LOCK = threading.Lock()


class SourceDelegate(QStyledItemDelegate):
    """소스 1개 = 회색 바. 준비 전 진한 회색(프록시 진행만큼 밝게), 준비되면 연한 회색."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 30)

    def paint(self, p: QPainter, option, index):
        """MOSCO 줄: 진회색, 선택 = 파란 테두리, 진행 = 단계 색으로 차오름 + 오른쪽 글자(단계 색), 오른쪽 칩 = 프리셋.
        읽기 실패 = 밝은 회색 줄 + 빨간 '읽기 실패'(누르면 다시 읽기, 툴팁 = 오류 문구)."""
        from . import stage as SG
        from .ui_auto import YELLOW, short_preset
        sid = index.data(Qt.UserRole)
        st = SG.stage_of(self.tab.state, sid, skip=("render",))     # v0.16.39 렌더 진행 = 렌더 목록 바에만(MOSCO 와 같음)
        err = st is not None and st[0] == "error"
        src = self.tab.state.project.source(sid)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SG.ERR_BG if err else SG.ROW_BG))
        p.drawRoundedRect(r, 3, 3)
        if st and not err and st[1] is not None and 0 < st[1] < 1:
            pr = QRectF(r)
            pr.setWidth(r.width() * st[1])
            p.setBrush(QColor(SG.STAGE[st[0]][0]))
            p.drawRoundedRect(pr, 3, 3)
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor(SG.SEL_EDGE), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        name = index.data(Qt.DisplayRole)
        nw = fm.horizontalAdvance(name)
        p.setPen(QColor(SG.ERR_NAME if err else "#f2f2f2"))
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, name)
        if src is not None:
            f.setBold(False)
            p.setFont(f)
            fm = p.fontMetrics()
            x = r.right() - 5
            left = r.left() + 10 + nw + 10
            rec = src.auto or {}
            label = short_preset(rec)
            if label:                                   # 칩 = 프리셋(직접 = 흰 글자, 자동 = 흐린 흰색)
                f2 = QFont(f)
                f2.setPointSizeF(max(7.0, f.pointSizeF() - 1))
                p.setFont(f2)
                fm2 = p.fontMetrics()
                t = fm2.elidedText(label, Qt.ElideRight, 90)
                cw = fm2.horizontalAdvance(t) + 14
                if x - cw > left:
                    chip = QRectF(x - cw, r.top() + 4, cw, r.height() - 8)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(SG.CHIP_SRC))
                    p.drawRoundedRect(chip, 2, 2)
                    p.setPen(QColor("#ffffff" if rec.get("by") == "user" else "#e4e4e4"))
                    p.drawText(chip, Qt.AlignCenter, t)
                    x -= cw + 8
                p.setFont(f)
            if st:                                      # 지금 하는 일(단계 색)
                txt = fm.elidedText(st[2], Qt.ElideRight, int(max(0, x - left)))
                w = fm.horizontalAdvance(txt)
                if txt and x - w > left:
                    p.setPen(QColor(SG.ERR_TXT if err else SG.STAGE[st[0]][1]))
                    p.drawText(QRectF(x - w, r.top(), w + 1, r.height()), Qt.AlignVCenter, txt)
                    x -= w + 8
            parts = []
            if has_clip_grade(src):
                parts.append("C")
            nk = len({k["f"] for ks in src.gkeys.values() for k in ks}) if src.gkeys else 0
            if nk:
                parts.append(f"◆{nk}")
            for t in reversed(parts):
                w = fm.horizontalAdvance(t)
                if x - w < left:
                    break
                p.setPen(QColor(YELLOW))
                p.drawText(QRectF(x - w, r.top(), w + 1, r.height()), Qt.AlignVCenter, t)
                x -= w + 5
        p.restore()

    def helpEvent(self, event, view, option, index):
        """읽기 실패 줄 툴팁 = 오류 문구(누르면 다시 읽기)."""
        from PySide6.QtWidgets import QToolTip
        sid = index.data(Qt.UserRole)
        msg = self.tab.state.errors.get(sid, "")
        if self.tab.state.status.get(sid) in ("읽기 오류", "원본 없음", "프록시 오류") and event.type() == QEvent.ToolTip:
            QToolTip.showText(event.globalPos(), f"누르면 다시 읽기\n{msg[-300:]}" if msg else "누르면 다시 읽기", view)
            return True
        return super().helpEvent(event, view, option, index)


class ImageDelegate(QStyledItemDelegate):
    """스틸·음악 소스 1개 = 연한 바(오류는 빨강), 파일 이름."""

    def __init__(self, tab, color="#a9b0b8"):
        super().__init__(tab)
        self.tab = tab
        self.color = color

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 26)

    def paint(self, p: QPainter, option, index):
        iid = index.data(Qt.UserRole)
        bad = bool(self.tab.state.img_status.get(iid))
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#7a2a22") if bad else QColor(self.color))
        p.drawRoundedRect(r, 3, 3)
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor("#4a8fe0"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        p.setPen(QColor("#dddddd") if bad else QColor("#111"))
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   option.fontMetrics.elidedText(index.data(Qt.DisplayRole), Qt.ElideMiddle, int(r.width()) - 16))
        p.restore()


class EditTab(QWidget):
    autoRenderProgress = Signal(float, bool)      # AUTO 렌더 전체 진행(0~1, 계속 중) → 시작 창

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.cur_sid = ""
        self.sel_cut = ""
        self.sel_layer = ""
        self._del_target = "cut"        # Del 키 대상: "cut" | "layer"
        self._last_list = "src"         # [삭제](소스) 대상: "src" | "img"
        self._img_cache: dict[str, QImage] = {}
        self._text_key = None
        self._space_down = False
        self.tl_time = 0.0
        self.sel_ov = ("", "")
        self.mode = "source"            # 모니터: "source" | "timeline"
        self._tl_cuts = []              # [(segment, start, length)]
        self._tl_seg = None             # 타임라인 모드에서 지금 보이는 컷
        self._pending_frame = None
        self._tl_switching = False
        self._tl_play_after = False
        self._tl_img_cache = {}
        self._music_player = None
        self.pgen = 0
        self._auto_items: set = set()               # AUTO 가 넣은 렌더 항목
        self._auto_feeding = False                  # [보정+렌더] 분석이 덜 끝나 렌더 항목이 더 들어올 예정
        self._allow_hidden = False                  # 숨어 있어도 모니터 미리 준비([보정+편집] 누른 뒤)

        # ================= 소스
        self.src_list = QListWidget()
        self.src_list.setFocusPolicy(Qt.NoFocus)
        self.src_list.setItemDelegate(SourceDelegate(self))
        self.src_list.setSelectionMode(QListWidget.ExtendedSelection)      # Ctrl·Shift = 여러 클립(프리셋 적용)
        self.src_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.src_list.setStyleSheet("QListWidget{background:#1a1a1a; border:none;}")
        self.src_list.currentItemChanged.connect(self._on_src_selected)
        self.src_list.itemClicked.connect(lambda it: self.state.prioritize(it.data(Qt.UserRole)))   # 읽기 실패 줄 = 다시 읽기
        self.src_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.src_list.customContextMenuRequested.connect(self._src_menu)
        self.src_list.itemPressed.connect(lambda _it: self._set_target("src"))
        # 스틸 소스(이미지) — 영상 목록 아래, 클릭 = 현재 영상에 레이어로 얹음
        self.img_list = QListWidget()
        self.img_list.setFocusPolicy(Qt.NoFocus)
        self.img_list.setItemDelegate(ImageDelegate(self))
        self.img_list.setStyleSheet("QListWidget{background:#1a1a1a; border:none; border-top:1px solid #333;}")
        self.img_list.itemClicked.connect(self._on_img_clicked)
        self.img_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.img_list.customContextMenuRequested.connect(self._img_menu)
        self.img_list.setVisible(False)
        # 음악 소스 — 클릭 = 타임라인 음악 줄 끝에 붙임
        self.mus_list = QListWidget()
        self.mus_list.setFocusPolicy(Qt.NoFocus)
        self.mus_list.setItemDelegate(ImageDelegate(self, "#8fc4a4"))
        self.mus_list.setStyleSheet("QListWidget{background:#1a1a1a; border:none; border-top:1px solid #333;}")
        self.mus_list.itemClicked.connect(self._on_mus_clicked)
        self.mus_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mus_list.customContextMenuRequested.connect(lambda _pos: self.add_files())
        self.mus_list.setVisible(False)
        self.load_bar = QProgressBar()
        self.load_bar.setTextVisible(False)
        self.load_bar.setFixedHeight(6)
        from .ui_auto import main_button
        self.b_auto = main_button("AUTO", "red")
        self.b_auto.setToolTip("전체 자동 보정 · 렌더")
        self.b_auto.clicked.connect(self.open_auto)
        self.auto_bar = QProgressBar()
        self.auto_bar.setTextVisible(False)
        self.auto_bar.setFixedHeight(3)
        self.auto_bar.setVisible(False)
        ab = QHBoxLayout()                      # [영상 추가][AUTO][삭제] 한 줄(v0.16.41 사용자: AUTO 를 가운데)
        ab.setSpacing(4)
        self.b_auto.setMinimumWidth(64)         # 열이 좁으면(노트북) 셋이 같이 줄어듦
        self.b_auto.setMaximumWidth(MAIN_W)
        for text, fn in (("영상 추가", self.add_files), ("삭제", self._remove_selected)):
            b = _btn(text, "", fn)
            b.setFixedHeight(MAIN_H)
            b.setMinimumWidth(48)
            b.setMaximumWidth(ADD_W)
            ab.addWidget(b, 3)
            if text == "영상 추가":
                ab.addWidget(self.b_auto, 4)
        ab.addStretch(1)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(3)
        left.addLayout(ab)
        left.addWidget(self.auto_bar)
        left.addWidget(self.src_list, 3)
        left.addWidget(self.img_list, 1)
        left.addWidget(self.mus_list, 1)
        left.addWidget(self.load_bar)
        self.src_box = QWidget()          # 오른쪽 열 위: 소스. 높이 = 모니터+바(렌더가 재생 버튼 줄부터 시작)
        self.src_box.setLayout(left)

        # ================= 모니터 + 소스 바 (간격 없음)
        self.player = Player()
        self.player.frameChanged.connect(self._on_frame)
        self.player.playingChanged.connect(self._on_playing)
        self.sbar = SourceBar()
        self.sbar.seekRequested.connect(lambda f: (self.player.pause(), self.player.seek(f)))
        self.sbar.ioDragStarted.connect(self._io_drag_start)
        self.sbar.ioDragged.connect(self._io_drag)
        self.sbar.ioDragFinished.connect(self._after_io)
        self.lbar = LayerBar()
        self.lbar.selected.connect(self._select_layer)
        self.lbar.dragStarted.connect(lambda _lid: self.state.checkpoint())
        self.lbar.dragged.connect(self._layer_drag)
        self.lbar.dragFinished.connect(lambda: setattr(self.state, "dirty", True))
        self.lbar.removeRequested.connect(self.remove_layer)
        mon_w = self.player.mon
        mon_w.layerPressed.connect(self._on_layer_pressed)
        mon_w.layerChanged.connect(lambda: setattr(self.state, "dirty", True))
        mon_w.layerSelected.connect(self._select_layer)
        mon_w.cropPressed.connect(self._crop_pressed)
        mon_w.cropDragged.connect(self._crop_dragged)
        self.sbar.keyDeleteRequested.connect(self._delete_key)
        mon = QVBoxLayout()
        mon.setSpacing(0)
        mon.setContentsMargins(0, 0, 0, 0)
        mon.addWidget(self.player, 1)
        mon.addWidget(self.lbar)
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
        self.b_kprev = _btn("key◀", "이전 ◆ (보정 항목을 만지면 그 종류만)", lambda: self.goto_gkey(-1))
        self.b_knext = _btn("key▶", "다음 ◆ (보정 항목을 만지면 그 종류만)", lambda: self.goto_gkey(1))
        for b in (self.b_kprev, self.b_knext):
            ui_style.tone(b, fg="#f2c94c")
        tbar.addWidget(self.b_kprev)
        for text, tip, k in (("I◀", "인 점으로 (Shift+I)", "goto_in"), ("◀◀", "J", "j"), ("◀|", "←  (Shift: 1초)", "left"),
                             ("▶ / ❚❚", "Space", "space"), ("|▶", "→  (Shift: 1초)", "right"), ("▶▶", "L", "l"),
                             ("▶I", "아웃 점으로 (Shift+O)", "goto_out")):
            tbar.addWidget(_btn(text, tip, lambda _=False, k=k: self._key(k), main=(k == "space")))
        tbar.addWidget(self.b_knext)
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
        b_in = _btn("[ 컷인", "I  또는  [", lambda: self._key("i"))
        b_out = _btn("컷아웃 ]", "O  또는  ]", lambda: self._key("o"))
        for b in (b_in, b_out):
            ui_style.tone(b, "cut")
            cut.addWidget(b)
        cut.addWidget(_btn("IO 해제", "Esc", lambda: self._key("esc")))
        cut.addWidget(_btn("삭제", "Del", lambda: self._key("del")))
        cut.addSpacing(12)
        self.speed_group = QButtonGroup(self)
        for i, (sp, key) in enumerate(((2.0, "1"), (1.0, "2"), (0.5, "3"))):
            b = QPushButton(speed_label(sp))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            fix_size(b)
            b.setToolTip(key)
            b.clicked.connect(lambda _=False, k=key: self._key(k))
            self.speed_group.addButton(b, i)
            cut.addWidget(b)
        self.speed_group.button(1).setChecked(True)
        cut.addSpacing(12)
        cut.addWidget(_btn("샘플", "G", lambda: self._key("g")))
        cut.addWidget(_btn("★", "장면 표시 (M) · 다시 누르면 지움", lambda: self._key("m")))
        cut.addWidget(_btn("글자", "타임라인 맨 앞에 글자 추가", self.add_text))
        cut.addWidget(_btn("사각형", "글자 배경용 사각형(타임라인 맨 앞, 글자 아래)", self.add_rect))
        cut.addSpacing(12)
        b_still = _btn("스틸", "S", lambda: self._key("s"))         # 빨강, ➜ 바로 왼쪽(v0.16.8)
        ui_style.tone(b_still, "red")
        cut.addWidget(b_still)
        cut.addWidget(render_list_button(lambda: self._key("enter"), "렌더리스트로 (Enter)"))
        cut.addStretch(1)

        self._say_hold = False
        self.status = QLabel("")
        self.status.mousePressEvent = lambda _e: self._say_clear()
        self.status.setStyleSheet("font-size:13px; padding:3px 6px; background:#1c1c1c; border-radius:3px;")

        # 타임라인 머리줄: [타임라인 n초] ··· [▼] ··· [확대 ━━] [전체 삭제] [렌더리스트로]
        self.tl_len = QLabel("")
        self.tl_len.setStyleSheet("color:#aaa;")
        b_trans = _btn("컷편집", "선택한 컷 앞 경계의 화면 전환", self.edit_transition)
        lbox = QHBoxLayout()
        lbox.addWidget(b_trans)
        lbox.addWidget(self.tl_len)
        b_down = _btn("▼", "↓", lambda: self._key("down"), main=True)
        ui_style.tone(b_down, "navy")
        f = b_down.font()
        f.setPixelSize(15)
        b_down.setFont(f)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(5, 200)
        self.zoom.setValue(30)
        self.zoom.setFixedWidth(140)
        self.zoom.setFocusPolicy(Qt.NoFocus)
        self.zoom.valueChanged.connect(lambda v: self.timeline.set_zoom(float(v)))
        rbox = QHBoxLayout()
        rbox.addWidget(self.zoom)
        b_clr = _btn("전체 삭제", "", self.clear_timeline)
        rbox.addWidget(b_clr)
        rbox.addWidget(render_list_button(self.timeline_to_render, "타임라인 전체를 렌더리스트로"))
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
        self.timeline.timeChanged.connect(self._on_tl_time)
        self.timeline.ovSelected.connect(self._on_ov_selected)
        self.timeline.ovDragStart.connect(lambda _k, _i: self.state.checkpoint())
        self.timeline.ovEdited.connect(self._on_ov_edited)
        self.timeline.ovRemove.connect(self.remove_ov)
        self.timeline.ovActivated.connect(self.edit_ov)
        self.timeline.transSelected.connect(self._on_trans_selected)
        self.timeline.transRemove.connect(self.remove_transition)
        self.timeline.transActivated.connect(self.edit_transition)
        self.timeline.transDurStart.connect(lambda _cid: self.state.checkpoint())
        self.timeline.transDurEdited.connect(self._trans_dur)
        from .ui_trans import TransPreview
        self.trans_prev = TransPreview(self.player.mon)
        self.sel_trans = ""
        self._tp_job = None
        self._tp_key = None
        self._tp_frames = []
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidget(self.timeline)
        self.tl_scroll.setWidgetResizable(False)
        self.tl_scroll.setFixedHeight(150)
        self.tl_scroll.setFrameShape(QFrame.NoFrame)
        self.tl_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tl_scroll.viewport().installEventFilter(self)     # 크기 바뀌면 타임라인 폭 맞춤

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
        self.grade.liveChanged.connect(self._on_grade_live)
        self._live_busy = self._live_pending = False
        self._pv_flight: dict = {}                  # 만드는 중인 보정 화면: 키 → {gen, tok, live}
        self.grade.viewChanged.connect(lambda _k: self.request_preview())
        self.grade.splitDirChanged.connect(self._set_split_dir)
        self.player.mon.splitFlipped.connect(lambda v: self.grade.set_split_dir(v, emit=False))
        self.grade.scopeToggled.connect(self.player.mon.set_scope)
        self.grade.whitePickToggled.connect(self._white_mode)
        self.grade.sampleClicked.connect(self._show_sample)
        self.grade.targets_fn = self._selected_sids
        self.src_list.itemSelectionChanged.connect(self.grade._sync_presets)      # 떠 있는 프리셋 창 = 고른 클립 따라감
        self.grade.keysChanged.connect(self._refresh_marks)
        self.grade.message.connect(lambda t, c: self._say(t, c))
        self.player.mon.contrastRequested.connect(self.fix_contrast)
        self.player.mon.balanceRequested.connect(self.fix_balance)
        self.sbar.gkeyDeleteRequested.connect(self._delete_gkeys)
        self.sbar.gkeyClicked.connect(self._gkey_clicked)                    # v0.16.35 ◆ → 그 보정 줄
        self.sbar.activeCleared.connect(self.grade.clear_active)
        self.grade.activeChanged.connect(self.sbar.set_active)
        self.player.mon.whitePicked.connect(self._white_picked)
        self.player.mon.modeRequested.connect(self.set_mode)
        self.player.mon.titlePressed.connect(self._on_title_pressed)
        self.player.mon.titleActivated.connect(lambda tid: self.edit_ov("title", tid))
        self.player.mon.titleChanged.connect(lambda: (setattr(self.state, "dirty", True), self.timeline.update()))
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(400)
        self._zoom_timer.timeout.connect(self.request_zoom_patch)
        self.player.mon.viewChanged.connect(self._zoom_timer.start)
        self.zgen = 0
        self.render_panel = RenderPanel(state)
        self.render_panel.itemProgress.connect(self._render_progress)
        self.render_panel.message.connect(lambda t: self._say(t, C_WARN))
        self.render_panel.sourcesRequested.connect(self.sources_to_render)

        # 3열: 보정 | 모니터·타임라인 | 소스·렌더
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.src_box)
        rl.addWidget(self.render_panel, 1)
        rw.setMinimumWidth(200)
        hs = QSplitter(Qt.Horizontal)
        for w in (self.grade, cw, rw):
            hs.addWidget(w)
        for i in (0, 2):
            hs.setCollapsible(i, False)
        hs.setStretchFactor(1, 1)
        hs.setSizes([310, 1000, 230])
        self._hs, self._sized = hs, False
        self.player.installEventFilter(self)
        self.lbar.installEventFilter(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(hs)

        self._pv_timer = QTimer(self)
        self._pv_timer.setSingleShot(True)
        self._pv_timer.setInterval(350)
        self._pv_timer.timeout.connect(self.request_preview)

        state.changed.connect(self._on_state)
        state.sourceStatus.connect(self._on_source_status)
        state.workChanged.connect(lambda _sid: self.src_list.viewport().update())
        state.importProgress.connect(self._on_import_progress)
        QApplication.instance().installEventFilter(self)
        self._on_import_progress()
        self._refresh_timeline()
        self._apply_aspect()

    # ================================================================ 키 입력
    def eventFilter(self, obj, e):
        if e.type() == QEvent.Resize and obj is self.tl_scroll.viewport():
            self.timeline.fit()
            return False
        if e.type() == QEvent.Resize and obj in (self.player, self.lbar):
            QTimer.singleShot(0, self._sync_right)
            return False
        if e.type() == QEvent.KeyRelease and not e.isAutoRepeat() and self._space_down and self._is_space(e):
            # Space 를 뗄 때: 누르는 동안 화면을 끌었으면 이동만, 아니면 재생/정지
            self._space_down = False
            mon = self.player.mon
            mon.space_pan = False
            mon.setCursor(Qt.ArrowCursor)
            if not mon.space_moved:
                self._key("space")
            return True
        if e.type() != QEvent.KeyPress or not self.isVisible() or not self.window().isActiveWindow():
            return False
        fw = QApplication.focusWidget()
        if QApplication.activeModalWidget() is not None:
            return False
        stamp = (e.timestamp(), e.key(), int(e.modifiers().value) if hasattr(e.modifiers(), "value") else 0)
        if stamp == self._text_key:      # 입력란이 처리한 키(Enter 등)가 부모로 다시 올라온 것 → 무시
            return False
        if isinstance(fw, TEXT_INPUTS):
            # 입력란에 커서가 있어도 Ctrl+Z / Ctrl+S 는 앱 기능(실행취소·저장)
            if e.modifiers() & Qt.ControlModifier and e.key() in (Qt.Key_Z, Qt.Key_S):
                fw.clearFocus()
                redo = bool(e.modifiers() & Qt.ShiftModifier)
                (self.window().save_project if e.key() == Qt.Key_S else self.window().redo if redo else self.window().undo)()
                return True
            self._text_key = stamp
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
            if name == "z":                      # Ctrl+Z 실행취소 · Ctrl+Shift+Z 다시 실행(v0.16.41)
                (self.window().redo if e.modifiers() & Qt.ShiftModifier else self.window().undo)()
                return True
            if name == "y":
                self.window().redo()
                return True
            if name == "s":
                self.window().save_project()
                return True
            return False
        if name in ("z", "y"):
            return False
        if e.isAutoRepeat() and name not in ("left", "right"):
            return True
        if name == "space":                  # 재생은 뗄 때(누른 채 끌면 화면 이동)
            self._space_down = True
            self.player.mon.space_pan = True
            self.player.mon.space_moved = False
            return True
        self._key(name, shift=bool(e.modifiers() & Qt.ShiftModifier))
        return True

    def _is_space(self, e):
        if os.name == "nt" and e.nativeScanCode():
            return (e.nativeScanCode() & 0xFF) == 0x39
        return e.key() == Qt.Key_Space

    def _key(self, name, shift=False):
        p = self.player
        if self.trans_prev.isVisible():       # 전환 미리보기 중 = 아무 키나 닫기(Esc 는 닫기만)
            self.trans_prev.stop()
            if name == "esc":
                return
        if name == "del":                  # 마지막으로 누른 대상: 레이어 / 스틸 소스 / 영상 소스 / 타임라인 컷 / 화면 전환
            t = self._del_target
            if t == "trans" and self.sel_trans:
                self.remove_transition(self.sel_trans)
            elif t == "layer" and self.sel_layer:
                self.remove_layer(self.sel_layer)
            elif t == "ov" and self.sel_ov[1]:
                self.remove_ov(*self.sel_ov)
            elif t == "mus" and self.mus_list.currentItem() is not None:
                self.state.remove_audio(self.mus_list.currentItem().data(Qt.UserRole))
            elif t in ("src", "img"):
                self._last_list = t
                self._remove_selected()
            else:
                self.delete_cut()
            return
        src = self._cur()
        if src is None or not src.frames:
            return
        if name == "space":
            if self.mode == "timeline" and self._tl_seg is not None and not p.is_busy():
                if not p.play(self._tl_seg.speed):
                    self._say("프록시 준비 중", C_WARN)
                else:
                    self._music_play()
            elif not p.toggle():
                self._say("프록시 준비 중", C_WARN)
            elif not p.is_busy():
                self._music_stop()
        elif name == "j":
            if not p.backward():
                self._say("프록시 준비 중", C_WARN)
        elif name == "l":
            if not p.forward():
                self._say("프록시 준비 중", C_WARN)
        elif name in ("left", "right"):
            d = round(float(p.fps)) if shift else 1
            p.step(-d if name == "left" else d)
        elif name == "goto_in" or (name == "i" and shift):
            p.pause()
            p.seek(src.io[0])
        elif name == "goto_out" or (name == "o" and shift):
            p.pause()
            p.seek(src.io[1] - 1)
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
            self.grade.set_view("grade" if self.grade.view_mode() == "raw" else "raw")
        elif name == "w":
            self.grade.b_white.toggle()
        elif name == "m":
            self.toggle_star()
        elif name == "down":
            self.send_to_timeline()
        elif name == "enter":
            self.send_to_render()

    # ================================================================ 표시
    def _say(self, text, color=C_INFO):
        """상태줄. 오류·실패 글은 다른 안내 글에 덮이지 않고 남음 → 상태줄을 누르면 지워짐(새 오류·실패는 바꿔 씀, v0.16.41).
        '프록시 준비 중' 같은 노란 안내는 예전처럼 다음 글에 바뀜."""
        bad = color == C_WARN and any(k in text for k in ("오류", "실패"))
        if self._say_hold and not bad:
            return
        self._say_hold = bad
        self.status.setToolTip("누르면 지움" if bad else "")
        self.status.setText(f"<span style='color:{color}'>{text}</span>")

    def _say_clear(self):
        self._say_hold = False
        self.status.setToolTip("")
        self.status.setText("")

    def _on_import_progress(self):
        _a, _done, n, frac = self.state.progress_summary()
        self.load_bar.setVisible(n > 0 and frac < 1.0)
        self.load_bar.setValue(int(frac * 100))
        self.src_list.viewport().update()

    def _vert(self, s=None) -> bool:
        """지금(또는 준) 소스의 출력이 세로(v0.16.55 출력 = 소스별)."""
        return self.state.project.out_of(s if s is not None else self._cur()) == "vertical"

    def _apply_aspect(self):
        self.player.set_aspect(9 / 16 if self._vert() else 16 / 9)
        self._update_monitor_layers()
        self._refresh_keys()

    # ================================================================ 소스
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "영상 추가", "", MEDIA_FILTER)
        if files:
            self.import_files(files)

    def import_files(self, files):
        self.state.import_files(files)

    def _remove_selected(self):
        if self._last_list == "mus" and self.mus_list.currentItem() is not None:
            self.state.remove_audio(self.mus_list.currentItem().data(Qt.UserRole))
            return
        if self._last_list == "img" and self.img_list.currentItem() is not None:
            iid = self.img_list.currentItem().data(Qt.UserRole)
            m = self.state.project.image(iid)
            if m and ui_style.ask(self, f"{Path(m.path).name} 삭제?"):
                self.state.remove_image(iid)
                self._img_cache.pop(iid, None)
            return
        self._remove_source()

    def _remove_source(self):
        s = self._cur()
        if not s:
            return
        if ui_style.ask(self, f"{display_name(s.path)} 삭제?"):
            self.cur_sid = ""
            self.state.remove_source(s.id)

    def _refresh_sources(self):
        p = self.state.project
        self.src_list.blockSignals(True)
        self.src_list.clear()
        sel = None
        for s in p.sources:
            it = QListWidgetItem(display_name(s.path))
            it.setData(Qt.UserRole, s.id)
            it.setToolTip(self._src_tip(s))
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
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            if it.data(Qt.UserRole) == sid:
                s = self.state.project.source(sid)
                err = self.state.errors.get(sid, "")
                tip = self._src_tip(s) if s else ""
                if err:
                    tip += f"\n{self.state.status.get(sid, '')} — 클릭하면 다시 시도\n{err[-400:]}"
                it.setToolTip(tip)
        if sid != self.cur_sid:
            return
        self._sync_loading()
        s = self._cur()
        if s is None:
            return
        if s.frames and self.player.frames == 0:
            self._load_current()
        elif self.state.proxy_ready(s) and (not self.player.has_media or self.player.proxy != s.proxy) and not self.player.is_busy():
            self.player.set_source(s.fps, s.frames, s.proxy, self.player.frame)
            self._pv_timer.start()

    def _on_src_selected(self, cur, _prev):
        if cur is None:
            return
        self.cur_sid = cur.data(Qt.UserRole)
        self.sel_layer = ""
        if not self._tl_switching:
            self.set_mode("source", load=False)
        self.pgen += 1
        self.player.clear("로딩 중…")      # 이전 소스 화면 즉시 지움
        self.state.prioritize(self.cur_sid)
        self.grade.set_current_source(self.cur_sid)
        self._apply_aspect()                       # v0.16.55 출력 = 소스별 → 고른 소스의 화면비
        QTimer.singleShot(0, self._load_current)

    def _sync_loading(self):
        """모니터 가운데 '로딩 중 n%' (재생용 프록시 준비 중). 정지 화면·보정·AUTO 는 그동안에도 됨."""
        s = self._cur()
        st = self.state.status.get(s.id, "") if s else ""
        if s is None or st in ("준비", "읽음", "읽기 오류", "원본 없음", "프록시 오류"):
            self.player.mon.set_loading(None)
        else:
            self.player.mon.set_loading(self.state.proxy_pct.get(s.id, 0.0) if st.startswith("프록시 ") else 0.0)

    def _load_current(self):
        s = self._cur()
        if not self.window().isVisible() and not getattr(self, "_allow_hidden", False):   # 시작 창 AUTO 중(메인 창 숨김) = 모니터 작업 안 함 → 보일 때 불러옴
            self._load_pending = True
            return
        self._sync_loading()
        if s is None:
            return
        if not s.frames:
            self.player.clear("로딩 중…")
            self._refresh_sbar()
            return
        proxy = s.proxy if self.state.proxy_ready(s) else None
        start = self._pending_frame if self._pending_frame is not None else s.io[0]
        self._pending_frame = None
        self.player.set_source(s.fps, s.frames, proxy, start)
        if self._tl_play_after:
            self._tl_play_after = False
            QTimer.singleShot(120, lambda: self.player.play(self._tl_seg.speed if self._tl_seg else 1.0))
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
        if self.mode == "timeline" and self._tl_seg is not None and s and s.id == self._tl_seg.src:
            self._tl_follow(f)
        if s:
            self.tc.setText(timecode(f, s.fps))
        self.sbar.set_playhead(f)
        self.lbar.set_playhead(f)
        self.grade.set_frame(f)
        if self.player.overlay_frame != f:
            self.player.mon.set_before(None)
        self._update_monitor_layers()
        if not self.player.is_busy():
            self._pv_timer.start()

    def _on_playing(self, playing):
        if playing:
            self.player.mon.set_before(None)
            self._pv_timer.stop()
            self.pgen += 1          # 진행 중인 보정 화면 무시 → 바로 부드럽게 재생
        else:
            self._pv_timer.start()

    def _on_grade_changed(self):
        s = self._cur()
        if s is not None:
            self.state.ensure_proxy(s)                # LUT 를 바꿨으면 그 LUT 로 프록시
        self._refresh_sbar()
        self._refresh_timeline()
        self.request_preview()

    def _on_grade_live(self):
        """슬라이더를 끄는 동안(v0.16.40): 모니터 보정 화면만 따라감. 한 번에 1개만 만들고, 만드는 사이 또 바뀌면 끝난 뒤 마지막 값으로 1번 더
        (예전 = 손을 멈추고 0.25초 뒤에야 바뀜). 샘플 타일·타임라인은 예전처럼 멈춘 뒤."""
        if self._live_busy:
            self._live_pending = True
            return
        self._live_busy = True
        if not self.request_preview(live=True):
            self._live_busy = False

    def _live_done(self):
        self._live_busy = False
        if self._live_pending:
            self._live_pending = False
            self._on_grade_live()

    def request_preview(self, live: bool = False) -> bool:
        """True = 뒤에서 만드는 중(끝나면 live 는 _live_done)."""
        s = self._cur()
        p = self.player
        if not s or not s.frames or p.is_busy() or (not self.window().isVisible() and not getattr(self, "_allow_hidden", False)):   # 숨김 = 안 만듦([보정+편집] 누른 뒤는 미리)
            ff.dbg(f"요청 안 함: 소스={bool(s)} 재생={p.is_playing()} 뒤로={p._back.isActive()} 창={self.window().isVisible()}")
            return False
        if not self.chk_preview.isChecked() and p.has_media:
            ff.dbg("요청 안 함: 정지 시 보정 화면 꺼짐")
            p.overlay_frame = None
            p.mon.set_before(None)
            p._grab(p.frame)
            return False
        self.pgen += 1
        gen, frame, tok = self.pgen, p.frame, p._token
        self._prefetch_range(s, frame)
        mode = self.grade.view_mode()
        full = self.state.project.grade_for_source(s.id, frame)
        grade = ff.lut_only(full) if mode == "raw" else full        # [원본] = LUT만
        key = (s.path, frame, mode, json.dumps(grade, sort_keys=True, default=str))
        with PREVIEW_LOCK:
            hit = PREVIEW_LRU.get(key)
            if hit is not None:                  # 같은 프레임·같은 보정은 다시 안 만듦
                PREVIEW_LRU.move_to_end(key)
        fl = self._pv_flight.get(key)
        ff.dbg(f"요청 #{gen} f={frame} 보기={mode} 끄는중={int(live)} 기억={int(hit is not None)} 같은작업={int(fl is not None)}")
        if hit is not None:
            self._on_preview(gen, frame, tok, hit)
            return False
        if fl is not None:                       # 같은 화면을 이미 만드는 중(v0.16.54) = 새로 안 만들고 그 결과를 씀
            fl["gen"], fl["tok"] = gen, tok      # (예전: 손을 떼면 같은 값으로 한 번 더 만들고 먼저 것은 버림 → 늦게 뜸)
            fl["live"] = fl["live"] or live
            return True
        fl = {"gen": gen, "tok": tok, "live": live}
        self._pv_flight[key] = fl

        def work():
            if fl["gen"] != self.pgen:           # 기다리는 사이 다른 화면을 요청함 = 안 만듦(ffmpeg 를 헛돌리지 않음, v0.16.40)
                return None
            c = ff.cached_frame(s, frame)
            out = ff.render_preview(c, grade)
            res = (out, ff.render_preview(c, ff.lut_only(full))) if mode == "split" else (out, None)
            with PREVIEW_LOCK:                   # 작업 스레드 여러 개가 같이 씀
                PREVIEW_LRU[key] = res
                while len(PREVIEW_LRU) > PREVIEW_LRU_MAX:
                    PREVIEW_LRU.popitem(last=False)
            return res

        def done(data, fr=frame):
            self._pv_flight.pop(key, None)
            if data is None and fl["gen"] == self.pgen:      # 건너뛴 직후 같은 화면을 다시 요청함 → 새로
                if not self.request_preview(live=fl["live"]) and fl["live"]:
                    self._live_done()
                return
            if data is not None:
                self._on_preview(fl["gen"], fr, fl["tok"], data)
            if fl["live"]:
                self._live_done()

        def fail(msg):
            self._pv_flight.pop(key, None)
            ff.log_error("미리보기", msg)
            self._say(f"미리보기 오류: {msg[-160:]}", C_WARN)
            if fl["live"]:
                self._live_done()
        job = jobs.Job(work)
        job.signals.done.connect(done)
        job.signals.error.connect(fail)
        self._full_shown = None
        if not live:
            self._quick_preview(s, frame, gen, tok, mode, grade, full)
        jobs.submit(jobs.PREVIEW_POOL, job, priority=5)
        return True

    def _quick_preview(self, s, frame, gen, tok, mode, grade, full):
        """원본 보정 화면이 오기 전에 카메라 프리뷰(LRF, 폭 1280 이상, 판정 통과)로 같은 보정을 먼저(v0.16.22).
        원본 입력이 이미 메모리에 있으면(바로 나옴) 안 함. 원본이 먼저 오면 버림."""
        if ff.frame_ready(s, frame):
            return
        try:
            pv = ff.preview_info(s, (full or {}).get("lut", ""), judge=False)     # 저장된 판정만(여기서 판정 안 함)
        except Exception:  # noqa: BLE001
            pv = None
        if not pv or max(pv.get("w", 0), pv.get("h", 0)) < ff.PREVIEW_MIN_W_STILL:      # 세로 프리뷰 = 긴 쪽으로
            return

        def work():
            c = ff.cached_frame_preview(s, frame, pv)
            out = ff.render_preview(c, ff.preview_grade(grade, pv))
            before = ff.render_preview(c, ff.preview_grade(ff.lut_only(full), pv)) if mode == "split" else None
            return out, before

        def done(data, g=gen, fr=frame, t=tok):
            if self._full_shown == g:             # 원본이 이미 나옴
                return
            self._on_preview(g, fr, t, data, quick=True)
        job = jobs.Job(work)
        job.signals.done.connect(done)
        job.signals.error.connect(lambda msg: ff.log_error("미리보기(프리뷰)", msg))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=6)

    def _prefetch_range(self, s, frame):
        """멈춘 곳 앞뒤 1초 원본을 뒤에서 한 번에 디코딩(근처 프레임 보정 화면이 빨라짐). 미리보기보다 낮은 우선순위."""
        job = jobs.Job(lambda: ff.prefetch_range(s, frame))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=-5)

    def _on_preview(self, gen, frame, tok, data, quick: bool = False):
        p = self.player
        if gen != self.pgen or frame != p.frame or tok != p._token or p.is_busy():
            ff.dbg(f"표시 버림 #{gen}: 지금 #{self.pgen} f {frame}/{p.frame} 표 {int(tok == p._token)} 재생 {int(p.is_busy())} 빠른={int(quick)}")
            return
        ff.dbg(f"표시 #{gen} f={frame} 빠른={int(quick)}")
        if not quick:
            self._full_shown = gen
        img, before = data
        p.overlay_frame = frame
        p.mon.set_before(QImage.fromData(before, "PNG") if before else None)
        p.show_image(QImage.fromData(img, "PNG"))
        if p.mon.zoom > 1:
            self._zoom_timer.start()

    # ================================================================ 확대 보기: 보이는 부분만 원본에서 고화질
    def request_zoom_patch(self):
        s = self._cur()
        p, mon = self.player, self.player.mon
        if not s or not s.frames or p.is_busy() or mon.zoom <= 1.0001 or self.grade.view_mode() == "split":
            return
        r = mon._view_rect()
        if r.width() * mon.devicePixelRatioF() < ff._preview_size(s)[0] * 1.3:      # 미리보기(긴 쪽 1280)로 충분
            return
        rect = mon.visible_norm()
        if not rect:
            return
        self.zgen += 1
        gen, frame, tok = self.zgen, p.frame, p._token
        g = self.state.project.grade_for_source(s.id, frame)
        if self.grade.view_mode() == "raw":
            g = ff.lut_only(g)
        job = jobs.Job(lambda: ff.render_region(s, frame, g, rect))

        def done(data):
            if gen == self.zgen and frame == p.frame and tok == p._token and not p.is_busy():
                mon.set_patch(QImage.fromData(data, "PNG"), rect)
        job.signals.done.connect(done)
        job.signals.error.connect(lambda m: ff.log_error("확대 영역", m))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=6)

    # ================================================================ 흰색 찍기
    def _white_mode(self, on):
        self.player.mon.set_pick(on)
        if on:
            self.player.pause()
            self._say("모래·흰 부분 클릭", C_INFO)

    def _white_picked(self, nx, ny):
        """LUT 만 입힌 화면(게인 1, 커브·색조·채도 없음)에서 찍은 곳 평균 → 빨강·파랑 = 초록/빨강, 초록/파랑."""
        s = self._cur()
        if not s or not s.frames:
            return
        self.grade.b_white.setChecked(False)
        g = dict(self.state.project.grade_for_source(s.id, self.player.frame))
        g.update(r_gain=1.0, b_gain=1.0, curve=[[0, 0], [1, 1]], hue=0, sat=1.0, dehaze=0, sharpen=0)
        frame = self.player.frame

        def work():
            import numpy as np
            png = ff.render_preview(ff.cached_frame(s, frame), g)
            im = QImage.fromData(png, "PNG").convertToFormat(QImage.Format_RGB888)
            a = np.frombuffer(im.constBits(), np.uint8, im.bytesPerLine() * im.height()).reshape(im.height(), im.bytesPerLine())
            a = a[:, :im.width() * 3].reshape(im.height(), im.width(), 3).astype(float)
            x, y = int(nx * im.width()), int(ny * im.height())
            r = max(3, im.width() // 160)
            patch = a[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3).mean(0)
            return patch
        job = jobs.Job(work)

        def done(patch):
            from .auto import follow_blue
            rr, gg, bb = (max(1.0, float(v)) for v in patch)
            r, b = gg / rr, follow_blue(gg / rr, gg / bb)          # 파랑 ≥ 빨강×0.9
            self.grade.set_values({"r_gain": r, "b_gain": b})
            self._say(f"흰색 찍기 → 빨강 {r:.2f}  파랑 {b:.2f}", C_OK)
        job.signals.done.connect(done)
        job.signals.error.connect(lambda m: self._say(f"흰색 찍기 실패: {m[-120:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=9)

    # ================================================================ ★ · 색 키프레임 표시
    def toggle_star(self):
        s = self._cur()
        if not s:
            return
        f = self.player.frame
        near = [x for x in s.stars if abs(x - f) <= 2]
        self.state.checkpoint()
        if near:
            s.stars = [x for x in s.stars if x not in near]
        else:
            s.stars = sorted(s.stars + [f])
        self.state.dirty = True
        self._refresh_marks()

    # ---------------------------------------------------------------- v0.16.35 ◆ 이동 · 종류
    def _gtypes_at(self, s, f):
        return [k for k, ks in s.gkeys.items() if any(x["f"] == f for x in ks)]

    def goto_gkey(self, d):
        """key◀ / key▶: 이전·다음 ◆ (활성 종류가 있으면 그 종류만). 도착 = 그 보정 줄 테두리."""
        s = self._cur()
        if not s or not s.gkeys:
            return
        act = self.grade.active
        fs = sorted({x["f"] for k, ks in s.gkeys.items() if not act or k in act for x in ks})
        f0 = self.player.frame
        cand = [f for f in fs if f > f0] if d > 0 else [f for f in fs if f < f0]
        if not cand:
            return
        f = cand[0] if d > 0 else cand[-1]
        self.player.pause()
        self.player.seek(f)
        if act:
            self.grade.set_active(act)
        else:
            self.grade.set_active(self._gtypes_at(s, f), filt=False)

    def _gkey_clicked(self, f):
        s = self._cur()
        if s:
            self.grade.set_active(self._gtypes_at(s, f))

    def _delete_gkeys(self, f):
        s = self._cur()
        if not s:
            return
        self.state.checkpoint()
        for k in list(s.gkeys):
            s.gkeys[k] = [x for x in s.gkeys[k] if x["f"] != f]
            if not s.gkeys[k]:
                s.gkeys.pop(k)
        self.state.dirty = True
        self.grade.set_frame(self.player.frame)
        self.grade._load_controls()
        self._refresh_marks()
        self.request_preview()

    def _refresh_marks(self):
        s = self._cur()
        if not s:
            self.sbar.set_marks([], [])
            return
        self.sbar.set_marks({k: [x["f"] for x in ks] for k, ks in s.gkeys.items() if ks}, list(s.stars))
        self.sbar.set_active(self.grade.active)

    def _selected_sids(self):
        return [it.data(Qt.UserRole) for it in self.src_list.selectedItems()]

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_load_pending", False):     # 숨어 있는 동안 미룬 모니터 불러오기
            self._load_pending = False
            QTimer.singleShot(0, self._load_current)
        if not self._sized:                  # 처음 한 번: 화면 폭에 비례(노트북 ≈ 310 | … | 230, 4K 는 더 넓게)
            self._sized = True
            QTimer.singleShot(0, self._init_sizes)

    def _init_sizes(self):
        w = max(1200, self._hs.width())
        left = int(max(330, min(480, w * 0.19)))
        right = int(max(220, min(360, w * 0.13)))
        self._hs.setSizes([left, w - left - right, right])

    def _sync_right(self):
        """오른쪽 열 소스 영역 높이 = 모니터 + 레이어 바 + 소스 바 → 렌더 영역이 재생 버튼 줄 높이부터."""
        h = self.player.height() + self.lbar.height() + self.sbar.height()
        if h > 50 and self.src_box.height() != h:
            self.src_box.setFixedHeight(h)

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

    def _io_drag_start(self):
        if self._cur():
            self.state.checkpoint()
            self.player.pause()

    def _io_drag(self, which, f):
        s = self._cur()
        if not s or not s.frames:
            return
        a, b = s.io
        if which == "in":
            s.sel_in = max(0, min(f, b - 2))
        else:
            s.sel_out = max(a + 2, min(s.frames, f))
        self._clamp_layers(s)
        self._refresh_sbar()          # 프리뷰 위치는 그대로(재생 위치·재생 버튼으로만 이동)

    def clear_io(self):
        s = self._cur()
        self.state.checkpoint()
        s.sel_in, s.sel_out = 0, 0
        self._after_io()

    def _after_io(self):
        s = self._cur()
        self._clamp_layers(s)
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
        """인/아웃 구간 + 그 구간에 걸친 이미지 레이어(사본)."""
        return self._segment_of(self._cur())

    def _segment_of(self, s):
        """소스 s 의 인/아웃 구간(배속·레이어·리프레임·◆·꺼 둔 항목 사본)."""
        a, b = s.io
        lays = [copy.deepcopy(l) for l in s.layers if l["fout"] > a and l["fin"] < b]
        for l in lays:
            l["id"] = new_layer("", 0, 0)["id"]
        return Segment(s.id, a, b, s.speed, layers=lays, reframe=copy.deepcopy(s.reframe), gkeys=copy.deepcopy(s.gkeys),
                       off=list(s.off))

    def send_to_timeline(self):
        seg = self._cur_segment()
        self.state.checkpoint()
        self.state.project.segments.append(seg)
        self.state.touch("segments")
        QTimer.singleShot(0, lambda: self.tl_scroll.horizontalScrollBar().setValue(
            self.tl_scroll.horizontalScrollBar().maximum()))

    def _new_item(self, segs):
        """➜ · 타임라인 → 렌더 리스트. v0.16.32: 출력이 원본(들 중 가장 큰 것)보다 크면 낮춤."""
        from .project import clamp_out, source_out_h
        p = self.state.project
        o = p.output
        hs = [source_out_h(p.source(g.src)) for g in segs]
        h = 0 if (not hs or 0 in hs) else max(hs)
        first = p.source(segs[0].src) if segs else None             # v0.16.55 출력 = 첫 컷 소스의 출력(여러 소스를 이은 타임라인도 영상 1개 = 출력 1개)
        want = (first.out if first is not None else "") or o.orientation
        return RenderItem(name=item_base(p, segs), segs=segs, orientation=clamp_out(want, h), audio=o.audio)

    def send_to_render(self):
        self.state.checkpoint()
        self.state.project.render_items.append(self._new_item([self.state.project.snap_seg(self._cur_segment())]))
        self.state.touch("render")

    def sources_to_render(self):  # noqa: C901
        """v0.16.25 ▼ · 소스 우클릭: 소스 목록에서 선택한 소스마다 렌더 항목 1개(지금 값: 인/아웃·배속·보정값·◆·출력 방향).
        같은 소스 · 같은 구간(인/아웃) 단독 항목이 있으면: 완료 = 건너뜀, 완료 안 됨 = 지금 값으로 갱신(렌더 중인 것은 건너뜀).
        구간이 다르면 새 항목(v0.16.26: 한 소스를 나눠 렌더). 렌더는 [렌더] 로."""
        from .project import clamp_out, source_out_h
        p = self.state.project
        rp = self.render_panel
        want = set(self._selected_sids())
        srcs = [s for s in p.sources if s.id in want and s.frames]
        if not srcs:
            self._say("소스를 선택하세요", C_WARN)
            return
        self.state.checkpoint()
        add = upd = skip = 0
        for s in srcs:
            seg = p.snap_seg(self._segment_of(s))
            orient = clamp_out(s.out or p.output.orientation, source_out_h(s))     # v0.16.32 원본보다 크지 않게
            same = [it for it in p.render_items if len(it.segs) == 1 and it.segs[0].src == s.id and not it.titles
                    and (it.segs[0].fin, it.segs[0].fout) == (seg.fin, seg.fout)]
            if any(it.done or rp.status.get(it.id, "").startswith("완료") for it in same):
                skip += 1
                continue
            idle = [it for it in same if it.id not in rp.active]
            if idle:
                idle[0].segs, idle[0].orientation = [seg], orient
                rp.status.pop(idle[0].id, None)
                upd += 1
            elif same:
                skip += 1
            else:
                p.render_items.append(RenderItem(name=short_name(s.path), segs=[seg], orientation=orient, audio=p.output.audio))
                add += 1
        self.state.touch("render")
        self._say(f"렌더 리스트: 추가 {add} · 갱신 {upd} · 건너뜀 {skip}", C_OK)

    def _src_menu(self, pos):
        """소스 목록 우클릭: 렌더 리스트로(선택한 것) · 영상 추가."""
        m = QMenu(self)
        a_r = m.addAction("렌더 리스트로")
        a_r.setEnabled(bool(self._selected_sids()))
        a_add = m.addAction("영상 추가…")
        a_link = m.addAction("원본 폴더 지정…") if self.state.missing() else None      # 원본 없음이 있을 때만(v0.16.41)
        act = m.exec(self.src_list.viewport().mapToGlobal(pos))
        if act is None:
            return
        if act is a_link:
            self.window().relink()
        elif act is a_r:
            self.sources_to_render()
        elif act is a_add:
            self.add_files()

    def timeline_to_render(self):
        p = self.state.project
        if not p.segments:
            return
        self.state.checkpoint()
        it = self._new_item([p.snap_seg(g.copy()) for g in p.segments])      # 보정값·◆·꺼 둔 항목 = 보내는 순간 값
        it.titles, it.music, it.mix = copy.deepcopy(p.titles), copy.deepcopy(p.music), dict(p.mix)
        p.render_items.append(it)
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

    def edit_transition(self, cid: str = ""):
        from .ui_trans import TransitionDialog
        segs = self.state.project.segments
        cid = cid if isinstance(cid, str) and cid else self.sel_cut
        i = next((k for k, g in enumerate(segs) if g.id == cid), -1)
        if i < 0:
            self._say("컷을 선택", C_WARN)
            return
        self.trans_prev.stop()
        dlg = TransitionDialog(segs[i].trans, first=(i == 0), parent=self, frames=self._trans_frames(i))

        def apply(kind, dur, seg=segs[i]):
            self.state.checkpoint()
            seg.trans = {} if kind == "none" else {"type": kind, "dur": dur}
            self.sel_trans = "" if kind == "none" else seg.id
            self.state.touch("segments")
        dlg.chosen.connect(apply)
        dlg.center_on(self)
        dlg.exec()

    def _trans_frames(self, i):
        """컷편집 창 샘플 = 실제 앞 컷 마지막 프레임 · 뒤 컷 첫 프레임(프록시 = 클립 LUT, 보정 전). 없으면 None."""
        from .ui_trans import H, W
        p = self.state.project
        segs = p.segments

        def grab(seg, frame):
            s = p.source(seg.src) if seg else None
            if s is None or not self.state.proxy_ready(s):
                return None
            try:
                im = QImage.fromData(ff.grab_proxy_frame(s.proxy, s.fps, max(0, min(s.frames - 1, frame))), "BMP")
            except Exception:   # noqa: BLE001
                return None
            if im.isNull():
                return None
            return QPixmap.fromImage(im.scaled(W * 2, H * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        b = grab(segs[i], segs[i].fin)
        if i == 0:
            a = QPixmap(W * 2, H * 2)
            a.fill(QColor("black"))
        else:
            a = grab(segs[i - 1], segs[i - 1].fout - 1)
        return (a, b) if a is not None and b is not None else None

    def _on_trans_selected(self, cid):
        self.sel_trans = cid
        self.sel_cut = cid
        self._del_target = "trans"
        self._refresh_timeline()
        self.preview_transition(cid)

    def _trans_dur(self, cid, d):
        """타임라인에서 전환 구간 끝 끌기(v0.16.34) — 0.2~2.0초(앞뒤 컷 길이 절반까지는 렌더·표시에서 맞춤)."""
        from .project import TRANS_RANGE
        seg = next((g for g in self.state.project.segments if g.id == cid), None)
        if seg is None or not seg.trans:
            return
        d = max(TRANS_RANGE[0], min(TRANS_RANGE[1], d))
        if abs(float(seg.trans.get("dur", 0)) - d) < 1e-6:
            return
        seg.trans = dict(seg.trans, dur=d)
        self.trans_prev.stop()
        self._tp_key = None
        self.state.touch("segments")

    def remove_transition(self, cid):
        seg = next((g for g in self.state.project.segments if g.id == cid), None)
        if seg is None or not seg.trans:
            return
        self.trans_prev.stop()
        self.state.checkpoint()
        seg.trans = {}
        if self.sel_trans == cid:
            self.sel_trans = ""
        self.state.touch("segments")
        self._say("전환 뺌")

    def preview_transition(self, cid):
        """그 경계 앞뒤만 540p 로 빨리 렌더 → 모니터 위에서 반복 재생(같은 내용이면 다시 렌더 안 함)."""
        from .project import plan_transitions
        from . import paths
        from .ui_trans import decode_frames
        p = self.state.project
        segs = [g for g in p.segments if p.source(g.src) and p.source(g.src).frames]
        i = next((k for k, g in enumerate(segs) if g.id == cid), -1)
        if i < 0:
            return
        lens = [p.seg_out_seconds(g, p.source(g.src).fps) for g in segs]
        t = plan_transitions(segs, lens)[i]
        if not t:
            return
        d = t[1]
        margin = max(1.0, d)

        def part(g, tail):
            s = p.source(g.src)
            n = int(round((d + margin) * float(s.fps) * g.speed))
            c = g.copy()
            if tail:
                c.fin = max(g.fin, g.fout - n)
            else:
                c.fout = min(g.fout, g.fin + n)
            return c
        pick = ([part(segs[i - 1], True)] if i > 0 else []) + [part(segs[i], False)]
        orient = "preview_v" if self._vert(p.source(segs[0].src) if segs else None) else "preview"
        # v0.16.33: 그 구간의 타임라인 글자·이미지도 같이(예전 = 전환 미리보기에 글자·PNG 가 안 보임)
        starts, st = [], 0.0
        for k, g in enumerate(segs):
            pt = plan_transitions(segs, lens)[k]
            if k > 0 and pt:
                st -= pt[1]
            starts.append(st)
            st += lens[k]
        if i > 0:
            w0 = starts[i] + d - p.seg_out_seconds(pick[0], p.source(pick[0].src).fps)
        else:
            w0 = starts[i]
        w1 = w0 + sum(p.seg_out_seconds(c, p.source(c.src).fps) for c in pick) - (d if i > 0 else 0.0)
        tts = []
        for tt in p.titles:
            a, b = float(tt["t0"]), float(tt["t1"])
            if b > w0 and a < w1:
                c = dict(tt)
                c["t0"], c["t1"] = a - w0, b - w0
                tts.append(c)
        extras = {"titles": tts, "music": [], "mix": p.mix} if tts else None
        key = (repr([({k: v for k, v in vars(c).items() if k != "id"}, p.grade_for_source(c.src, seg=c)) for c in pick])
               + orient + repr(tts))
        if key == self._tp_key and self._tp_frames:
            self.trans_prev.play(self._tp_frames)
            return
        if self._tp_job is not None:
            self._tp_job.cancel.set()
        pdir = paths.cache_dir() / "preview"
        pdir.mkdir(parents=True, exist_ok=True)
        for old in sorted(pdir.glob("trans_*.mp4"), key=lambda f: f.stat().st_mtime)[:-3]:   # 최근 3개만
            try:
                old.unlink()
            except OSError:
                pass
        out = pdir / f"trans_{abs(hash(key)) % 10**10}.mp4"

        def work(prog, cancel):
            ff.render_video(p, pick, str(out), prog, cancel, orient, False, fast=True, extras=extras)
            return decode_frames(str(out))
        job = jobs.Job(work, with_progress=True)
        self._tp_job = job
        job.signals.progress.connect(lambda v: self._say(f"전환 미리보기 {int(v * 100)}%"))

        def done(frames, job=job, key=key, cid=cid):
            if job is not self._tp_job:
                return
            self._tp_job = None
            self._tp_key, self._tp_frames = key, frames
            self._say("")
            if self.sel_trans == cid and frames:
                self.trans_prev.play(frames)

        def err(msg, job=job):
            if job is self._tp_job:
                self._tp_job = None
                if msg != "취소됨":
                    ff.log_error("전환 미리보기", msg)
                    self._say("전환 미리보기 실패", C_WARN)
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.PREVIEW_POOL, job)

    def _on_cut_selected(self, cid):
        self.sel_cut = cid
        self.sel_trans = ""
        self.trans_prev.stop()
        self._del_target = "cut"
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
        from .ui_render import ensure_folder
        if not ensure_folder(self, self.state):
            return
        s = self._cur()
        frame = self.player.frame
        g = self.state.project.grade_for_source(s.id)
        path = unique(out_dir(self.state.project) / f"{short_name(s.path)}.png")
        self.state.project.stills.append(Marker(s.id, frame))
        self._refresh_sbar()
        self._say(f"스틸 저장 중… {path.name}", C_INFO)
        gpu = self.state.project.output.gpu_decode
        job = jobs.Job(lambda: ff.export_still(s, frame, g, str(path), gpu))
        def still_done(_r):
            self._say(f"스틸 저장 완료 ✓  {path.name}", C_OK)
            self.window().statusBar().showMessage(f"스틸 저장 완료: {path}", 8000)

        job.signals.done.connect(still_done)
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
            if what == "undo" and self.cur_sid:      # 실행취소 = 값만 돌아가고 화면은 그대로이던 문제 → 보정 화면 다시
                self._refresh_marks()
                self.request_preview()
        elif what == "sources":
            self._refresh_sources()
        if what in ("project", "undo", "images"):
            self._refresh_images()
        if what in ("project", "undo", "audios"):
            self._refresh_audios()
        if what in ("titles",):
            self._refresh_timeline()
            if self.mode == "timeline":
                self._update_tl_titles(self.tl_time)
        if what in ("project", "undo", "images", "sources"):
            self._refresh_layers()
        if what in ("project", "undo", "output"):
            self._apply_aspect()
        if what in ("project", "undo", "sources", "segments", "grade", "output"):
            self._refresh_timeline()
        if what in ("grade", "undo", "project"):
            self._refresh_tips()
        if what == "markers":
            self._refresh_sbar()

    def _tag(self, sid):
        s = self.state.project.source(sid)
        if s and is_plain(s):
            return ""                         # 보정 없음(LUT만) = 표시 없음
        return "C" if s and has_clip_grade(s) else "E"

    def _refresh_sbar(self):
        s = self._cur()
        p = self.state.project
        if not s or not s.frames:
            self.sbar.set_data(0, (0, 0), False, 1.0, "", [], [])
            self._refresh_layers()
            return
        self.sbar.set_data(s.frames, s.io, s.io_trimmed, s.speed, self._tag(s.id),
                           [m.frame for m in p.stills if m.src == s.id], [m.frame for m in p.samples if m.src == s.id])
        self._refresh_marks()
        self._refresh_layers()

    # ================================================================ 스틸 소스·이미지 레이어
    def _refresh_images(self):
        p = self.state.project
        cur = self.img_list.currentItem().data(Qt.UserRole) if self.img_list.currentItem() else ""
        self.img_list.clear()
        for m in p.images:
            it = QListWidgetItem(Path(m.path).stem)
            it.setData(Qt.UserRole, m.id)
            err = self.state.img_status.get(m.id, "")
            it.setToolTip(m.path + (f"\n{err}" if err else f"\n{m.width}×{m.height}" if m.width else ""))
            self.img_list.addItem(it)
            if m.id == cur:
                self.img_list.setCurrentItem(it)
        self.img_list.setVisible(bool(p.images))
        ids = {m.id for m in p.images}
        for k in [k for k in self._img_cache if k not in ids]:
            self._img_cache.pop(k)

    def _qimage(self, iid):
        """모니터 표시용 이미지(EXIF 방향 반영, 큰 이미지는 줄여서 보관)."""
        if iid in self._img_cache:
            return self._img_cache[iid]
        m = self.state.project.image(iid)
        if m is None:
            return None
        r = QImageReader(m.path)
        r.setAutoTransform(True)
        img = r.read()
        if img.isNull():
            return None
        if max(img.width(), img.height()) > IMG_DISPLAY_MAX:
            img = img.scaled(IMG_DISPLAY_MAX, IMG_DISPLAY_MAX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._img_cache[iid] = img
        return img

    def _set_target(self, t):
        self._last_list = t if t in ("src", "img", "mus") else self._last_list
        self._del_target = t

    def _on_img_clicked(self, it):
        self._set_target("img")
        self.add_layer(it.data(Qt.UserRole))

    def add_layer(self, iid):
        s = self._cur()
        m = self.state.project.image(iid)
        if s is None or not s.frames or m is None:
            return
        if not m.width or self.state.img_status.get(iid):
            self._say("이미지를 읽을 수 없음", C_WARN)
            return
        if len(s.layers) >= MAX_LAYERS:
            self._say(f"레이어는 {MAX_LAYERS}개까지", C_WARN)
            return
        ow, oh = ff.out_size("vertical" if self._vert(s) else "horizontal")
        scale = min(1.0, ow / m.width, oh / m.height)       # 1080p 기준(1440·4K 는 같은 비율로 커짐)      # 원본 크기. 출력 화면보다 크면 화면에 맞춤
        a, b = s.io
        self.state.checkpoint()
        lay = new_layer(iid, a, b, scale)
        s.layers.append(lay)
        self.state.dirty = True
        self.sel_layer = lay["id"]
        self._refresh_layers()      # Del 대상은 스틸 소스(방금 클릭) 그대로, 레이어를 누르면 레이어

    def remove_layer(self, lid):
        s = self._cur()
        if not s or not any(l["id"] == lid for l in s.layers):
            return
        self.state.checkpoint()
        s.layers = [l for l in s.layers if l["id"] != lid]
        self.state.dirty = True
        if self.sel_layer == lid:
            self.sel_layer = ""
        self._refresh_layers()

    def _select_layer(self, lid):
        self.sel_layer = lid
        if lid:
            self._del_target = "layer"
        self._refresh_layers()

    def _on_layer_pressed(self, lid):
        self.state.checkpoint()
        if self.sel_layer != lid:
            self._select_layer(lid)
        self._del_target = "layer"

    SNAP_PX = 8

    def _layer_drag(self, lid, which, f):
        """자석: 소스 인/아웃·다른 레이어 끝·재생 위치에 SNAP_PX 안이면 붙음. 소스 인/아웃 밖으로는 못 나감."""
        s = self._cur()
        lay = next((l for l in s.layers if l["id"] == lid), None) if s else None
        if lay is None:
            return
        a, b = s.io
        tol = self.SNAP_PX * s.frames / max(1, self.lbar.width())
        targets = [a, b, self.player.frame] + [x for l in s.layers if l is not lay for x in (l["fin"], l["fout"])]

        def snap(v):
            t = min(targets, key=lambda t: abs(t - v))
            return t if abs(t - v) <= tol else v
        if which == "in":
            lay["fin"] = max(a, min(snap(f), lay["fout"] - 1))
        elif which == "out":
            lay["fout"] = min(b, max(snap(f), lay["fin"] + 1))
        else:                          # 통째 이동: 시작 또는 끝 중 더 가까운 쪽이 붙음
            ln = lay["fout"] - lay["fin"]
            s1, s2 = snap(f), snap(f + ln) - ln
            d1 = abs(s1 - f) if s1 != f else float("inf")
            d2 = abs(s2 - f) if s2 != f else float("inf")
            nf = s1 if d1 <= d2 and d1 < float("inf") else s2 if d2 < float("inf") else f
            nf = max(a, min(int(round(nf)), b - ln))
            lay["fin"], lay["fout"] = nf, nf + ln
        self._refresh_layers()         # 프리뷰 위치는 그대로

    def _clamp_layers(self, s):
        """소스 인/아웃이 바뀌면 레이어를 그 안으로. 완전히 밖이면 인/아웃 전체로."""
        a, b = s.io
        for l in s.layers:
            fi, fo = max(a, l["fin"]), min(b, l["fout"])
            l["fin"], l["fout"] = (fi, fo) if fo > fi else (a, b)

    def _refresh_layers(self):
        s = self._cur()
        if not s or not s.frames:
            self.lbar.set_data(0, [], "")
            self.player.mon.set_layers([], "")
            self.sbar.set_keys([])
            return
        if self.sel_layer and not any(l["id"] == self.sel_layer for l in s.layers):
            self.sel_layer = ""
        p = self.state.project
        rows = []
        for l in s.layers:
            m = p.image(l["img"])
            rows.append((l["id"], l["fin"], l["fout"], Path(m.path).name if m else ""))
        self.lbar.set_data(s.frames, rows, self.sel_layer)
        self._refresh_keys()
        self.lbar.set_playhead(self.player.frame)
        self._update_monitor_layers()

    # ================================================================ 세로 크롭 위치 이동(키프레임)
    def _crop_pressed(self):
        if self._cur():
            self.player.pause()
            self.state.checkpoint()

    def _crop_dragged(self, dx):
        """현재 프레임에 키프레임(있으면 갱신). 프리뷰 위치는 그대로."""
        s = self._cur()
        if not s:
            return
        f = self.player.frame
        k = next((k for k in s.reframe if k["f"] == f), None)
        if k is None:
            s.reframe.append({"f": f, "dx": round(dx, 1)})
            s.reframe.sort(key=lambda k: k["f"])
        else:
            k["dx"] = round(dx, 1)
        self.state.dirty = True
        self._refresh_keys()

    def _delete_key(self, f):
        s = self._cur()
        if not s or not any(k["f"] == f for k in s.reframe):
            return
        self.state.checkpoint()
        s.reframe = [k for k in s.reframe if k["f"] != f]
        self.state.dirty = True
        self._refresh_keys()
        self._update_crop()

    def _refresh_keys(self):
        s = self._cur()
        vert = self._vert(s)
        self.sbar.set_keys([k["f"] for k in s.reframe] if s and vert else [])

    def _update_crop(self):
        s = self._cur()
        if not s or not s.frames:
            return
        self.player.mon.set_crop(reframe_at(s.reframe, self.player.frame), s.width or 3840, reframe_max(s.width or 3840))

    def _update_monitor_layers(self):
        s = self._cur()
        if not s or not s.frames:
            self.player.mon.set_layers([], "")
            return
        if self.player.mon._drag is None or self.player.mon._drag[0] != "crop":
            self._update_crop()
        f = self.player.frame
        vis = []
        for l in s.layers:
            m = self.state.project.image(l["img"])
            if m is None or not m.width or not (l["fin"] <= f < l["fout"]):
                continue
            img = self._qimage(m.id)
            if img is not None:
                vis.append((l, img, (m.width, m.height)))
        self.player.mon.set_layers(vis, self.sel_layer)

    # ================================================================ 타임라인 글자·이미지·음악
    def _on_tl_time(self, t):
        self.tl_time = t
        self.set_mode("timeline", load=False)
        self.show_timeline(t)

    # ================================================================ 타임라인 프리뷰
    def set_mode(self, mode, load=True):
        if mode == self.mode:
            self.player.mon.set_mode_button(mode)
            return
        self.mode = mode
        self.player.mon.set_mode_button(mode)
        if mode == "source":
            self._tl_seg = None
            self._music_stop()
            self.player.mon.set_titles([], "")
            self.timeline.update()
        elif load:
            self.show_timeline(self.tl_time)

    def _tl_locate(self, t):
        """결과 시간 t → (컷, 원본 프레임). 전환 겹침 구간은 뒤 컷(들어오는 컷)."""
        cut = None
        for seg, st, ln in self._tl_cuts:
            if st <= t + 1e-6:
                cut = (seg, st, ln)
        if cut is None:
            return None
        seg, st, ln = cut
        src = self.state.project.source(seg.src)
        if src is None:
            return None
        f = seg.fin + (min(t, st + ln) - st) * float(src.fps) * seg.speed
        return seg, st, int(max(seg.fin, min(seg.fout - 1, round(f))))

    def show_timeline(self, t, play=False):
        """그 시점의 컷 소스를 열어 해당 프레임으로(보정 화면은 평소처럼), 글자·이미지는 모니터에 그림."""
        loc = self._tl_locate(t)
        self.timeline.set_time(t)
        self._update_tl_titles(t)
        if loc is None:
            return
        seg, _st, f = loc
        self._tl_seg = seg
        if seg.src != self.cur_sid or self.player.frames == 0:
            self._pending_frame = f
            self._tl_play_after = play
            if seg.src != self.cur_sid:
                self._tl_switching = True
                self._select_source(seg.src)      # → _on_src_selected → _load_current(이 프레임으로)
                self._tl_switching = False
            else:
                QTimer.singleShot(0, self._load_current)
        else:
            if not play:
                self.player.pause()
            self.player.seek(f)
            if play and not self.player.is_busy():
                self.player.play(seg.speed)

    def _tl_follow(self, f):
        """타임라인 모드 재생 중: 프레임 → 결과 시간, 컷 끝이면 다음 컷으로."""
        seg = self._tl_seg
        st = next((c[1] for c in self._tl_cuts if c[0] is seg), None)
        src = self.state.project.source(seg.src)
        if st is None or src is None:
            return
        t = st + (f - seg.fin) / float(src.fps) / seg.speed
        self.tl_time = t
        self.timeline.set_time(t)
        self._update_tl_titles(t)
        if self.player.is_playing() and f >= seg.fout - 1:
            idx = next((i for i, c in enumerate(self._tl_cuts) if c[0] is seg), -1)
            if 0 <= idx < len(self._tl_cuts) - 1:
                _nseg, nst, _ln = self._tl_cuts[idx + 1]
                self.tl_time = max(nst, t)
                QTimer.singleShot(0, lambda: self.show_timeline(self.tl_time + 1e-3, play=True))
            else:
                self.player.pause()
                self._music_stop()

    def _update_tl_titles(self, t):
        p = self.state.project
        out = []
        for d in p.titles:
            t0, t1 = float(d["t0"]), float(d["t1"])
            if not (t0 <= t < t1):
                continue
            fd = min(float(d.get("fade", 0.5)), (t1 - t0) / 2)
            a = 1.0 if fd <= 0.01 else max(0.0, min(1.0, (t - t0) / fd, (t1 - t) / fd))
            if not self.player.is_playing():
                a = 1.0                                  # 멈춤 = 페이드 무시(0초 시작 글자·사각형도 보이게), 페이드는 재생할 때만
            img, wh = None, None
            if d.get("kind") == "image":
                m = p.image(d.get("img", ""))
                if m is None or not m.width:
                    continue
                img, wh = self._qimage(m.id), (m.width, m.height)
            out.append((d, a, img, wh))
        self.player.mon.set_titles(out, self.sel_ov[1] if self.sel_ov[0] == "title" else "")

    def _on_title_pressed(self, tid):
        self.state.checkpoint()
        self.sel_ov = ("title", tid)
        self._del_target = "ov"
        self.timeline.set_overlays(self.state.project.titles, self.state.project.music, self.sel_ov)
        self._update_tl_titles(self.tl_time)

    # ---------------------------------------------------------------- 음악(타임라인 재생 중)
    def _music_play(self):
        p = self.state.project
        if os.environ.get("DTME_NO_AUDIO") or not p.music:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from .project import orig_volume
        m = next((x for x in p.music if float(x["t0"]) <= self.tl_time < float(x["t0"]) + float(x["len"])), None)
        if m is None:
            return
        if self._music_player is None:
            self._music_player = QMediaPlayer(self)
            self._music_out = QAudioOutput(self)
            self._music_player.setAudioOutput(self._music_out)
        self._music_out.setVolume(min(1.0, float(p.mix.get("music", 1.0))))
        if self.player.audio:
            self.player.audio.setVolume(0.6 * min(1.0, orig_volume(p.mix, p.music)))
        self._music_player.setSource(QUrl.fromLocalFile(m["path"]))
        self._music_player.setPosition(int((float(m.get("off", 0)) + self.tl_time - float(m["t0"])) * 1000))
        self._music_player.play()

    def _music_stop(self):
        if self._music_player is not None:
            self._music_player.stop()
        if self.player.audio:
            self.player.audio.setVolume(0.6)

    def _on_ov_selected(self, kind, oid):
        self.sel_ov = (kind, oid)
        self._del_target = "ov"
        self.sel_cut = ""
        self._refresh_timeline()
        if self.mode == "timeline":
            self._update_tl_titles(self.tl_time)

    def _on_ov_edited(self, kind, oid):
        self.state.dirty = True
        if self.mode == "timeline":
            self._update_tl_titles(self.tl_time)

    def _ov(self, kind, oid):
        p = self.state.project
        return next((d for d in (p.titles if kind == "title" else p.music) if d["id"] == oid), None)

    def remove_ov(self, kind, oid):
        p = self.state.project
        self.state.checkpoint()
        if kind == "title":
            p.titles = [d for d in p.titles if d["id"] != oid]
        else:
            p.music = [d for d in p.music if d["id"] != oid]
        self.sel_ov = ("", "")
        self.state.touch("titles")

    def edit_ov(self, kind, oid, new: bool = False):
        """글자·음악 설정 = 떠 있는 창(v0.16.19). 열린 채로 타임라인·모니터 조작 가능.
        [확인] = 등록하고 닫기(빈 글자면 없앰) / [취소]·Esc = 열기 전으로(새 글자면 없앰). 다른 창을 열면 앞 창은 [확인]."""
        from .ui_titles import MusicDialog, RectDialog, TextDialog
        d = self._ov(kind, oid)
        if d is None:
            return
        old = getattr(self, "_dlg", None)
        if old is not None and old.isVisible():
            old.accept()
        if kind == "title" and d.get("kind") == "text":
            if self.state.project.segments:          # 글자는 '타임라인' 보기에서만 보임
                self.set_mode("timeline")
            if not new:                             # 새 글자는 add_text 에서 이미 실행취소 지점
                self.state.checkpoint()
            dlg = TextDialog(d, self)
        elif kind == "title" and d.get("kind") == "rect":
            if self.state.project.segments:
                self.set_mode("timeline")
            if not new:
                self.state.checkpoint()
            dlg = RectDialog(d, self)
        elif kind == "music":
            self.state.checkpoint()
            dlg = MusicDialog(self.state.project.mix, self)
        else:
            return
        dlg.changed.connect(lambda: (setattr(self.state, "dirty", True), self.state.changed.emit("titles")))
        p = self.state.project

        def drop():
            if kind == "title" and any(x is d for x in p.titles):
                p.titles = [x for x in p.titles if x is not d]
                if self.sel_ov == ("title", oid):
                    self.sel_ov = ("", "")
                self.state.touch("titles")

        def ok():
            if kind == "title" and d.get("kind") == "text" and not (d.get("text") or "").strip():   # 빈 글자만(사각형 X)
                drop()
            else:
                self.state.touch("titles")

        def cancel():
            if new:
                drop()
            else:
                self.state.touch("titles")
        dlg.accepted_.connect(ok)
        dlg.rejected_.connect(cancel)
        self._dlg = dlg
        dlg.center_on(self)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if kind == "title" and hasattr(dlg, "text"):
            dlg.text.setFocus()

    def add_text(self):
        """[글자] = 늘 타임라인 맨 앞(0초)에 만들고 재생 위치도 0초로(v0.16.33, 사용자 — 예전 = 마지막 타임라인 위치라 클립 뒤에 생김)."""
        p = self.state.project
        t0 = 0.0
        self.state.checkpoint()
        d = new_text(t0, t0 + TITLE_DEFAULT_SEC, "")
        p.titles.append(d)
        self.sel_ov = ("title", d["id"])
        self._del_target = "ov"
        self.state.touch("titles")
        if p.segments:
            self.tl_time = t0
            self.timeline.set_time(t0)
            self.set_mode("timeline", load=False)
            self.show_timeline(t0)
        self.edit_ov("title", d["id"], new=True)

    def add_rect(self):
        """[사각형] = 타임라인 맨 앞(0초), 글자 아래(맨 아래 = 목록 맨 앞)에 만들고 설정 창(v0.16.34)."""
        from .project import new_rect
        p = self.state.project
        self.state.checkpoint()
        d = new_rect(0.0, TITLE_DEFAULT_SEC)
        p.titles.insert(0, d)
        self.sel_ov = ("title", d["id"])
        self._del_target = "ov"
        self.state.touch("titles")
        if p.segments:
            self.tl_time = 0.0
            self.timeline.set_time(0.0)
            self.set_mode("timeline", load=False)
            self.show_timeline(0.0)
        self.edit_ov("title", d["id"], new=True)

    def _img_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        it = self.img_list.itemAt(pos)
        m = QMenu(self)
        a_src = m.addAction("현재 영상에 얹기") if it else None
        a_tl = m.addAction("타임라인에 넣기") if it else None
        m.addSeparator()
        a_add = m.addAction("불러오기…")
        act = m.exec(self.img_list.mapToGlobal(pos))
        if act is None:
            return
        if act is a_add:
            self.add_files()
        elif act is a_src:
            self.add_layer(it.data(Qt.UserRole))
        elif act is a_tl:
            self.add_title_image(it.data(Qt.UserRole))

    def add_title_image(self, iid):
        """스틸 → 타임라인 = 글자·사각형과 같이 맨 앞(0초) + 재생 위치 0초(v0.16.36, 예전 = 지금 타임라인 위치)."""
        m = self.state.project.image(iid)
        if m is None or not m.width:
            return
        p = self.state.project
        ow, oh = ff.out_size("vertical" if self._vert(p.source(p.segments[0].src) if p.segments else None) else "horizontal")
        self.state.checkpoint()
        d = new_title_image(iid, 0.0, TITLE_DEFAULT_SEC, min(1.0, ow / m.width, oh / m.height))
        p.titles.append(d)
        self.sel_ov = ("title", d["id"])
        self._del_target = "ov"
        self.state.touch("titles")
        if p.segments:
            self.tl_time = 0.0
            self.timeline.set_time(0.0)
            self.set_mode("timeline", load=False)
            self.show_timeline(0.0)

    def _refresh_audios(self):
        self.mus_list.clear()
        for a in self.state.project.audios:
            it = QListWidgetItem(Path(a["path"]).stem)
            it.setData(Qt.UserRole, a["id"])
            it.setToolTip(f"{a['path']}\n{a['dur']:.1f}초")
            self.mus_list.addItem(it)
        self.mus_list.setVisible(bool(self.state.project.audios))

    def _on_mus_clicked(self, it):
        self._set_target("mus")
        a = next((x for x in self.state.project.audios if x["id"] == it.data(Qt.UserRole)), None)
        if not a:
            return
        p = self.state.project
        t0 = max([float(m["t0"]) + float(m["len"]) for m in p.music] + [0.0])
        self.state.checkpoint()
        p.music.append(new_music(a["path"], t0, a["dur"]))
        self.state.touch("titles")

    # ================================================================ 소스 줄 툴팁(프리셋 · 인식 · 출력)
    def _src_tip(self, s):
        from . import auto
        from .ui_auto import OUT_SHORT, preset_name
        rec = s.auto or {}
        lines = [s.path]
        if preset_name(rec):
            lines.append(f"{preset_name(rec)} ({'직접' if rec.get('by') == 'user' else '자동'})")
        if rec.get("rec") and rec.get("rec") != rec.get("preset"):
            lines.append(f"인식: {auto.preset_label(rec['rec'])}")
        if s.out:
            lines.append(f"출력 {OUT_SHORT.get(s.out, '')}")
        return "\n".join(lines)

    def _refresh_tips(self):
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            s = self.state.project.source(it.data(Qt.UserRole))
            if s and not self.state.errors.get(s.id):
                it.setToolTip(self._src_tip(s))
        self.src_list.viewport().update()

    # ================================================================ RGB 그래프 도움: [명암] [색 균형]
    def _frame_array(self, g, done):
        s = self._cur()
        if not s or not s.frames:
            return
        frame = self.player.frame

        def work():
            import numpy as np
            png = ff.render_preview(ff.cached_frame(s, frame), g)
            im = QImage.fromData(png, "PNG").convertToFormat(QImage.Format_RGB888)
            a = np.frombuffer(im.constBits(), np.uint8, im.bytesPerLine() * im.height()).reshape(im.height(), im.bytesPerLine())
            return a[:, :im.width() * 3].reshape(im.height(), im.width(), 3).astype(np.float32) / 255
        job = jobs.Job(work)
        job.signals.done.connect(done)
        job.signals.error.connect(lambda m: self._say(f"실패: {m[-120:]}", C_WARN))
        jobs.submit(jobs.PREVIEW_POOL, job, priority=9)

    def fix_contrast(self):
        """[명암] 지금 화면(커브만 빼고 보정)의 양끝을 목표선에 맞추는 커브."""
        from . import auto
        s = self._cur()
        if not s:
            return
        g = dict(self.state.project.grade_for_source(s.id, self.player.frame))
        g["curve"] = [[0, 0], [1, 1]]

        def done(a):
            self.grade.set_values({"curve": auto.contrast_fix(a)})
            self._say("명암 → 목표선", C_OK)
        self._frame_array(g, done)

    def fix_balance(self):
        """[색 균형] LUT 만 입힌 화면의 중간 밝기에서 빨강·파랑을 초록에 맞춘 뒤 물빛만 파랑."""
        from . import auto
        s = self._cur()
        if not s:
            return
        g = dict(self.state.project.grade_for_source(s.id, self.player.frame))
        cur_water = float(g.get("water", 0))
        g.update(r_gain=1.0, b_gain=1.0, curve=[[0, 0], [1, 1]], hue=0, sat=1.0, water=0, gy=0, dehaze=0, sharpen=0)

        def done(a):
            r, b = auto.balance_fix(a)
            self.grade.set_values({"r_gain": r, "b_gain": b, "water": max(cur_water, 12)})
            self._say(f"색 균형 → 빨강 {r:.2f}  파랑 {b:.2f}", C_OK)
        self._frame_array(g, done)

    # ================================================================ AUTO
    def _set_auto_bar(self, v, color):
        self.auto_bar.setVisible(0 <= v < 1)
        self.auto_bar.setStyleSheet(f"QProgressBar{{background:#2a2a2a; border:none;}} QProgressBar::chunk{{background:{color};}}")
        self.auto_bar.setValue(int(v * 100))

    def open_auto(self):
        if not self.state.project.sources:
            return
        self.player.pause()
        self.make_auto_dialog().exec()

    def make_auto_dialog(self):
        from .ui_auto import AutoDialog
        dlg = AutoDialog(self.state, self)
        dlg.startRequested.connect(lambda: self._auto_start(dlg))
        dlg.sampleRequested.connect(lambda: self._auto_sample(dlg))
        geo = self.window().geometry()
        dlg.move(geo.center().x() - dlg.width() // 2, geo.center().y() - dlg.height() // 2)
        self._auto_dlg = dlg
        return dlg

    def _set_split_dir(self, v):
        self.player.mon.split_v = v
        self.player.mon.update()

    def _ask_folder(self, title="저장폴더"):
        from .project import get_setting, set_setting
        o = self.state.project.output
        start = o.folder or get_setting("last_folder", "") or (str(Path(self.state.project.sources[0].path).parent)
                                                               if self.state.project.sources else "")
        d = QFileDialog.getExistingDirectory(self, title, start)
        if d:
            try:
                set_setting("last_folder", d)
            except Exception:  # noqa: BLE001
                pass
        return d

    def _auto_start(self, dlg):
        """[시작] 저장폴더 → (분석 덜 끝났으면 기다림) → 클립에 적용 → 바로 렌더 또는 개별 보정."""
        if dlg.mode == "render" and not dlg.busy and not getattr(dlg, "_folder", ""):   # [보정+편집]은 파일을 안 만들어 폴더 안 물음
            d = self._ask_folder()
            if not d:
                return
            dlg._folder = d
        if dlg.mode == "render":
            self._auto_render_step(dlg)
            return
        if self.state.defer_proxy:                 # 시작 창 [보정+편집]: 분석과 함께 프록시 시작(기다리지 않음 → 편집 화면에서 계속)
            self.state.resume_proxies()
        if not self.window().isVisible() and not self._allow_hidden:   # 편집 화면 첫 장면 미리(원본 구간 캐시·보정 화면)
            self._allow_hidden = True
            self._load_current()
        if dlg.wait_then("start"):
            dlg.set_busy(True)
            return
        rows = dlg.chosen_rows()
        if not rows:
            dlg.set_busy(False)
            return
        self._auto_begin(dlg)
        self._auto_apply(dlg, rows)
        self.grade.set_view("split")
        if rows:
            self._select_source(rows[0].sid)
        self._say(f"AUTO 완료: {len(rows)}개 클립", C_OK)
        dlg.accept()

    def _auto_begin(self, dlg):
        """AUTO 적용 시작: 설정 저장 · 실행취소 지점 1번 · 저장폴더·이름."""
        from .project import set_setting
        p = self.state.project
        try:
            set_setting("auto", dlg.settings())
        except Exception:  # noqa: BLE001
            pass
        self.state.checkpoint()
        if getattr(dlg, "_folder", ""):
            p.output.folder = dlg._folder
        p.output.prefix = dlg.name.text().strip()

    def _auto_apply(self, dlg, rows):
        """줄 결과를 클립에 넣음(보정값·◆·출력)."""
        p = self.state.project
        st = dlg.settings()
        for r in rows:
            s = p.source(r.sid)
            res = r.result
            s.grade = {k: v for k, v in res["grade"].items() if p.grade.get(k) != v}
            s.off = []
            if st["keys"] == "auto":
                s.gkeys = copy.deepcopy(res["gkeys"])
            s.auto = {"preset": res["preset"], "by": "auto" if r.choice == "auto" else "user", "rec": r.rec,
                      "nkeys": len({k["f"] for ks in res["gkeys"].values() for k in ks}) if st["keys"] == "auto" else 0}
            s.out = r.out
            self.state.ensure_proxy(s)               # LUT 가 바뀌었으면 그 LUT 로 프록시(시작 창 AUTO = 미룸)
        self.state.dirty = True
        self.state.changed.emit("output")
        self.state.changed.emit("grade")
        self.grade._load_controls()
        self.grade.keysChanged.emit()
        self._refresh_tips()

    def _auto_render_step(self, dlg):
        """[보정+렌더]: 분석이 끝난 영상부터 바로 값 넣고 렌더 시작(뒤 영상은 그동안 분석). 모두 끝나면 창 닫음."""
        p = self.state.project
        if not getattr(dlg, "_started", False):
            dlg._started, dlg._applied = True, set()
            self._auto_begin(dlg)
            self._auto_items = set()
            self._auto_feeding = True
        ready = [r for r in dlg.chosen_rows() if r.sid not in dlg._applied]
        if ready:
            self._auto_apply(dlg, ready)
            items = []
            for r in ready:
                dlg._applied.add(r.sid)
                s = p.source(r.sid)
                a, b = s.io
                items.append(RenderItem(name=short_name(s.path), segs=[p.snap_seg(Segment(s.id, a, b, 1.0))],
                                        orientation=r.out, audio=True))
            p.render_items += items
            self._auto_items |= {it.id for it in items}
            self.state.touch("render")
            if not self.render_panel.running:
                self._set_auto_bar(0.0, "#d9604f")
            self.render_panel.enqueue(items)
        if dlg.pending():
            dlg.waiting = "start"
            dlg.set_busy(True)
            dlg.analyze_all()
            return
        dlg.waiting = None
        self._auto_feeding = False
        dlg.accept()
        if not dlg._applied:
            dlg.set_busy(False)
        elif not self.render_panel.running:          # 이미 다 끝남
            self._render_progress("", 1.0, False)

    def _auto_sample(self, dlg):
        """[샘플] 저장 창(폴더·크기·형식·이름) → 클립마다 반반 PNG 6장. 클립 값은 바꾸지 않음."""
        from . import auto
        from .ui_auto import SampleDialog, sample_frames6, sample_name
        if not dlg.busy and not getattr(dlg, "_scfg", None):
            from .project import get_setting
            sd = SampleDialog(dlg.name.text().strip(), self.state.project.output.folder or get_setting("last_folder", ""), dlg,
                              "lr" if self.player.mon.split_v else "tb")      # 배치 기본 = 모니터 반반 방향
            sd.move(dlg.geometry().center().x() - sd.width() // 2, dlg.geometry().center().y() - 150)
            if sd.exec() != QDialog.Accepted:
                return
            dlg._scfg = sd.config()
            dlg._sfolder = sd.folder.text().strip()
        if dlg.wait_then("sample"):
            dlg.set_busy(True)
            return
        cfg, folder = dlg._scfg, Path(dlg._sfolder)
        dlg._scfg = None
        folder.mkdir(parents=True, exist_ok=True)
        rows = dlg.chosen_rows()
        p = self.state.project
        todo = []
        for r in rows:
            s = p.source(r.sid)
            gk = r.result["gkeys"] if dlg.keys.value() == "auto" else s.gkeys
            for k, f in enumerate(sample_frames6(s), start=1):
                g = grade_at(r.result["grade"], gk, f) if gk else r.result["grade"]
                out = unique(folder / sample_name(cfg, s, k, auto.preset_label(r.result["preset"])))
                todo.append((s, f, g, str(out), r.out))
        if not todo:
            dlg.set_busy(False)
            return
        dlg.set_busy(True, "#d9a646")
        dlg.bar.setValue(0)
        gpu = p.output.gpu_decode
        size, fmt, layout = int(cfg.get("size", 1920)), cfg.get("fmt", "png8"), cfg.get("layout", "side")

        def work(prog, cancel):
            for i, (s, f, g, out, orient) in enumerate(todo):
                if cancel.is_set():
                    raise ff.Cancelled()
                ff.export_split(s, f, g, out, size, fmt, "vertical" if orient == "vertical" else "horizontal", gpu, layout)
                prog((i + 1) / len(todo))
            return len(todo)
        job = jobs.Job(work, with_progress=True)
        dlg.jobs.append(job)
        per = {}                                    # sid → [인덱스…] (소스 줄 = 샘플 k/6)
        for i, t in enumerate(todo):
            per.setdefault(t[0].id, []).append(i)
        for sid in per:
            self.state.set_work(sid, "sample", -1)
        order = list(per)

        def on_prog(v):
            k = int(round(v * len(todo)))
            dlg.bar.setValue(int(v * 100))
            for sid, idx in per.items():
                got = sum(1 for i in idx if i < k)
                if got >= len(idx):
                    self.state.set_work(sid, None)
                elif got > 0 or (idx[0] <= k):
                    self.state.set_work(sid, "sample", got / len(idx), f"샘플 {got}/{len(idx)}")
            cur = next((n for n, sid in enumerate(order, start=1) if self.state.work.get(sid, ("",))[0] == "sample"
                        and self.state.work[sid][1] >= 0), 0)
            done_n = sum(1 for sid in order if sid not in self.state.work)
            dlg.show_state(f"샘플 {done_n}/{len(order)}" + (f" ({cur}번)" if cur else ""), "sample")
        job.signals.progress.connect(on_prog)
        on_prog(0.0)

        def done(n):
            self.state.clear_work("sample", set(per))
            dlg.set_busy(False)
            dlg.set_bar_color("#d9a646")
            dlg.bar.setValue(100)
            dlg.show_state(f"샘플 {len(order)}/{len(order)} · {n}장 저장", "sample")
            self._say(f"샘플 {n}장 저장 ✓  {folder}", C_OK)

        def err(m):
            self.state.clear_work("sample", set(per))
            dlg.set_busy(False)
            dlg._progress()
            self._say(f"샘플 실패: {m[-160:]}", C_WARN)
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.RENDER_POOL, job)

    def _render_progress(self, iid, v, running):
        """AUTO 렌더 진행 → 맨 위 빨간 막대 + 소스 줄 배경."""
        p = self.state.project
        it = next((x for x in p.render_items if x.id == iid), None)
        if it is not None and it.segs:              # 렌더 진행 → 소스 줄(빨강)
            sids = {g.src for g in it.segs}
            for sid in sids:
                if running and v < 1:
                    self.state.set_work(sid, "render", v)
                else:
                    w = self.state.work.get(sid)
                    if w and w[0] == "render":
                        self.state.set_work(sid, None)
        if self._auto_items:
            ids = [x for x in p.render_items if x.id in self._auto_items]
            done = sum(self.render_panel.progress.get(x.id, 0.0) if not self.render_panel.status.get(x.id, "").startswith(("완료", "실패")) else 1.0
                       for x in ids)
            tot = done / max(1, len(ids))
            running = running or self._auto_feeding           # 뒤 영상이 아직 분석 중이면 계속
            self._set_auto_bar(tot if running else 1.0, "#d9604f")
            self.autoRenderProgress.emit(tot if running else 1.0, running)
            if not running:
                self._auto_items = set()
        self.src_list.viewport().update()

    def _refresh_timeline(self):
        p = self.state.project
        items = []
        from .project import TRANS_NAME, plan_transitions
        segs = [g for g in p.segments if p.source(g.src) and p.source(g.src).frames]
        lens = [p.seg_out_seconds(g, p.source(g.src).fps) for g in segs]
        plan = plan_transitions(segs, lens)
        start = 0.0
        cuts = []
        for i, (g, ln, t) in enumerate(zip(segs, lens, plan)):
            s = p.source(g.src)
            if i > 0 and t:
                start -= t[1]
            items.append((g.id, ln, short_name(s.path)[-4:], g.speed, self._tag(s.id),
                          (TRANS_NAME[t[0]], t[1]) if t else None, start))
            cuts.append((g, start, ln))
            start += ln
        if self.sel_cut and not any(i[0] == self.sel_cut for i in items):
            self.sel_cut = ""
        self._tl_cuts = cuts
        if self.sel_trans and not any(i[0] == self.sel_trans and i[5] for i in items):
            self.sel_trans = ""
        self.timeline.trans_sel = self.sel_trans
        self.timeline.set_items(items, self.sel_cut)
        if self.sel_ov[1] and not any(d["id"] == self.sel_ov[1] for d in p.titles + p.music):
            self.sel_ov = ("", "")
        self.timeline.set_overlays(p.titles, p.music, self.sel_ov)
        tot = p.segs_seconds(segs)
        self.tl_len.setText(f"{tot:.1f}초" if items else "")


_ = (Path, QPixmap)
