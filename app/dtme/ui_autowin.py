"""자동 창(v0.17.0) — 예전 AUTO 창 + 자동 편집 창을 하나로.

왼쪽 = 소스 목록(여행별 묶음 머리줄 · 체크 · 이름 · 길이/장면 · 방향 다른 클립 '세로'/'가로' · 섞였을 때 알림 한 줄).
오른쪽 위 = 음악·사진(넣었을 때만) + 요약 한 줄 / 오른쪽 아래 = 단계 4줄 [보정][편집][음악][렌더](체크 = 켬/끔, 줄 = 펼침, 한 번에 하나).
아래 = [취소][AUTO]. AUTO 전 = 파일 정보만(미리 분석 없음). AUTO 뒤 = 이 창 안에서 단계별 진행(막대 하나 · [취소] · [−]).
렌더 켬 = 편집 창·프록시·미리보기 없이 끝까지 → 완료 팝업 [폴더 열기][편집 화면][닫기]. 렌더 끔 = 편집 준비(프록시·전환) 뒤 편집 화면.
작업 자체(값 넣기·자동 편집·렌더)는 EditTab 의 함수를 부름.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSlider, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from . import auto, autoedit, ff, jobs, solo, stage as SG, ui_style
from .project import (ROT, ROT_BACK, VIDEO_EXT, RenderItem, Segment, auto_lut, clamp_src, display_name,
                      get_setting, has_clip_grade, is_portrait, outputs_for, set_setting, short_name, source_out_h, source_vw)
from .ui_auto import OUT_BTNS, Grip, PresetGrid, Seg, cached_samples, choice_args, grab_job, labeled, main_button
from .ui_render import DragMove, Popup, file_name, open_file, out_dir, took_text, unique

ROW_ON = "#2b3a4a"            # 켠 줄 남색(사용자 11/17 시안)
SUB = "#c4cad1"
HEAD_TXT = "#9fb4cc"          # 여행 머리줄 글자
PREP = ("#2f3a4a", "#4a8fe0", "편집 준비")
STEP_NAME = {"grade": "보정", "edit": "편집", "music": "음악", "render": "렌더", "prep": "편집 준비"}
STEP_KIND = {"grade": "analyze", "edit": "edit", "music": "music", "render": "render", "prep": "proxy"}
EMPTY_HINT = ("영상 · 폴더를 여기에 끌어다 놓기", "우클릭 = 파일 추가 · 폴더 추가 · 프로젝트 열기")
PROJ_EXT = (".dtme.json",)


def is_project_file(f: str) -> bool:
    """프로젝트 파일(.dtme.json 또는 다이빙 기록이 아닌 .json)."""
    if not str(f).lower().endswith(".json") or not Path(f).is_file():
        return False
    if str(f).lower().endswith(PROJ_EXT):
        return True
    try:
        from .divelog import is_dive_file
        return not is_dive_file(f)
    except Exception:  # noqa: BLE001
        return False


def mmss(sec: float) -> str:
    sec = max(0.0, float(sec))
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


class AutoRow:
    def __init__(self, src, checked, choice, out):
        self.sid = src.id
        self.checked = checked
        self.choice = choice          # 'auto' | 프리셋 키
        self.out = out
        self.prog = 0.0               # 분석 진행 0~1
        self.result = None            # 이 클립에 들어갈 값(recommend)
        self.rec = None               # 인식(자동) 결과 키
        self.error = ""
        self.running = False
        self.retried = False
        self.out_set = False          # 출력 크기를 직접 고름(아니면 파일 정보가 읽힐 때 다시 계산)


# ------------------------------------------------------------------ 목록 줄
class RowDelegate(QStyledItemDelegate):
    def __init__(self, dlg):
        super().__init__(dlg)
        self.dlg = dlg

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 26 if index.data(Qt.UserRole) is None else 32)

    def paint(self, p: QPainter, option, index):
        sid = index.data(Qt.UserRole)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if sid is None:                                  # 여행 묶음 머리줄: 기간 · 지명
            f = QFont(option.font)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(HEAD_TXT))
            p.drawText(r.adjusted(6, 2, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(index.data(Qt.UserRole + 1) or "", Qt.ElideRight, int(r.width() - 12)))
            p.restore()
            return
        dlg = self.dlg
        row = dlg.row_by.get(sid)
        src = dlg.state.project.source(sid)
        if row is None or src is None:
            p.restore()
            return
        sel = bool(option.state & QStyle.State_Selected)
        stg = SG.stage_of(dlg.state, sid, skip=("render",)) if row.checked or dlg.state.status.get(sid) in SG.ERRORS else None
        if stg and stg[0] == "proxy" and not dlg.running:     # AUTO 전 = 파일 정보만(읽는 중 표시는 그대로)
            stg = stg if stg[2] == "읽는 중" else None
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ROW_ON if row.checked else SG.ROW_OFF))
        p.drawRoundedRect(r, 3, 3)
        active = bool(stg and stg[0] in SG.STAGE and stg[1] is not None and 0 < stg[1] < 1)
        if not active and row.checked and row.result and not row.error and dlg.running and not (stg and stg[0] == "error"):
            p.setBrush(QColor(SG.STAGE["analyze"][0]))
            p.drawRoundedRect(r, 3, 3)
        if active:
            pr = QRectF(r)
            pr.setWidth(r.width() * stg[1])
            p.setBrush(QColor(SG.STAGE[stg[0]][0]))
            p.drawRoundedRect(pr, 3, 3)
        if sel:
            p.setPen(QPen(QColor(SG.SEL_EDGE), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        cb = QRectF(r.left() + 8, r.center().y() - 8, 16, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SG.CHK_BG))
        p.drawRoundedRect(cb, 2, 2)
        if row.checked:
            p.setPen(QPen(QColor("#ffffff"), 1.8))
            p.drawLine(cb.left() + 4, cb.center().y(), cb.left() + 7, cb.bottom() - 4)
            p.drawLine(cb.left() + 7, cb.bottom() - 4, cb.right() - 4, cb.top() + 4)
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff" if row.checked else SG.OFF_TXT))
        x = cb.right() + 10
        nm = display_name(src.path)
        nw = int(max(78, min(p.fontMetrics().horizontalAdvance(nm) + 4, r.width() * 0.5)))
        p.drawText(QRectF(x, r.top(), nw, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(nm, Qt.ElideRight, nw - 2))
        x += nw + 2
        if has_clip_grade(src):
            p.setPen(QColor("#f2c94c"))
            p.drawText(QRectF(x, r.top(), 12, r.height()), Qt.AlignVCenter, "C")
        x += 16
        f.setBold(False)
        p.setFont(f)
        fm = p.fontMetrics()
        tag = dlg.odd_tag(src)                           # 방향 다른 클립 = '세로'(많은 쪽이 세로면 '가로')
        if tag:
            tw = fm.horizontalAdvance(tag) + 12
            tr = QRectF(x, r.top() + 6, tw, r.height() - 12)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#5a4a2a" if row.checked else "#3a3a3a"))
            p.drawRoundedRect(tr, 2, 2)
            p.setPen(QColor("#f2c94c" if row.checked else SG.OFF_TXT))
            p.drawText(tr, Qt.AlignCenter, tag)
            x += tw + 8
        right_end = r.right() - 10
        if stg:
            txt, col = stg[2], (SG.ERR_TXT if stg[0] == "error" else SG.STAGE[stg[0]][1])
        else:
            txt, col = dlg.row_text(row), (SUB if row.checked else SG.OFF_TXT)
        if txt and right_end - x > 20:
            p.setPen(QColor(col))
            p.drawText(QRectF(x, r.top(), right_end - x, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                       fm.elidedText(txt, Qt.ElideRight, int(right_end - x)))
        p.restore()

    def editorEvent(self, event, model, option, index):
        return False            # 체크 = AutoWindow._check_drag(누른 채 쓸기)


class SourceList(QListWidget):
    """빈 목록 = 가운데 안내 두 줄."""

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count():
            return
        p = QPainter(self.viewport())
        r = self.viewport().rect()
        f = QFont(self.font())
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(QColor("#9a9a9a"))
        p.drawText(r.adjusted(0, -14, 0, -14), Qt.AlignCenter, EMPTY_HINT[0])
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor("#6f6f6f"))
        p.drawText(r.adjusted(0, 14, 0, 14), Qt.AlignCenter, EMPTY_HINT[1])
        p.end()


# ------------------------------------------------------------------ 단계 줄
class StageRow(QFrame):
    """[✓] 이름  요약 …  ▸ — 체크 칸 = 켬/끔, 줄 나머지 = 펼침."""
    toggled = Signal(str, bool)
    clicked = Signal(str)

    def __init__(self, key: str, body: QWidget, parent=None):
        super().__init__(parent)
        self.key, self.body = key, body
        self.on, self.open_, self.can = True, False, True
        self.summary = ""
        self.setObjectName("StageRow")
        self.setStyleSheet("#StageRow{background:#2a2a2a; border:1px solid #3a3a3a; border-radius:3px;}")
        self.head = QWidget(self)
        self.head.setFixedHeight(34)
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.installEventFilter(self)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.head)
        body.setVisible(False)
        v.addWidget(body)

    def set_on(self, on: bool):
        self.on = bool(on)
        self.head.update()

    def set_can(self, can: bool):
        self.can = bool(can)
        self.head.update()

    def set_open(self, on: bool):
        self.open_ = bool(on)
        self.body.setVisible(self.open_)
        self.head.update()

    def set_summary(self, text: str):
        if text != self.summary:
            self.summary = text
            self.head.update()

    def active(self) -> bool:
        return self.on and self.can

    def eventFilter(self, obj, e):
        if obj is self.head:
            if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                if e.position().x() < 38:
                    if self.can:
                        self.on = not self.on
                        self.head.update()
                        self.toggled.emit(self.key, self.on)
                else:
                    self.clicked.emit(self.key)
                return True
            if e.type() == QEvent.Paint:
                self._paint_head()
                return True
        return False

    def _paint_head(self):
        p = QPainter(self.head)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.head.rect())
        col = SG.STAGE[STEP_KIND[self.key]][1]
        act = self.active()
        cb = QRectF(12, r.center().y() - 8, 16, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SG.CHK_BG))
        p.drawRoundedRect(cb, 2, 2)
        if act:
            p.setPen(QPen(QColor("#ffffff"), 1.8))
            p.drawLine(cb.left() + 4, cb.center().y(), cb.left() + 7, cb.bottom() - 4)
            p.drawLine(cb.left() + 7, cb.bottom() - 4, cb.right() - 4, cb.top() + 4)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(col if act else "#6f6f6f"))
        p.drawText(QRectF(40, 0, 44, r.height()), Qt.AlignVCenter | Qt.AlignLeft, STEP_NAME[self.key])
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(SUB if act else "#6f6f6f"))
        w = r.width() - 88 - 26
        p.drawText(QRectF(88, 0, w, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.summary, Qt.ElideRight, int(w)))
        p.setPen(QColor("#8a8a8a"))
        p.drawText(QRectF(r.width() - 24, 0, 16, r.height()), Qt.AlignCenter, "▾" if self.open_ else "▸")
        p.end()


class StepBar(QWidget):
    """막대 하나: 켠 단계마다 그 단계 색으로 왼쪽부터 다시 차오름(앞 단계 색 = 꽉 찬 채로 아래에). 위 = 단계 이름(끝남 ✓)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.steps: list[str] = []
        self.k, self.v, self.text = 0, 0.0, ""
        self.setFixedHeight(34)

    def set_steps(self, steps: list[str]):
        self.steps, self.k, self.v, self.text = list(steps), 0, 0.0, ""
        self.update()

    def set(self, key: str, v: float, text: str = ""):
        if key in self.steps:
            self.k = max(self.k, self.steps.index(key))
        self.v, self.text = max(0.0, min(1.0, v)), text
        self.update()

    def color(self, key: str) -> str:
        return PREP[1] if key == "prep" else SG.STAGE[STEP_KIND[key]][1]

    def frac(self) -> float:
        n = max(1, len(self.steps))
        return (self.k + self.v) / n

    def paintEvent(self, _e):
        if not self.steps:
            return
        p = QPainter(self)
        f = QFont(self.font())
        x = 0
        for i, key in enumerate(self.steps):
            name = STEP_NAME[key]
            f.setBold(i == self.k)
            p.setFont(f)
            p.setPen(QColor(self.color(key) if i <= self.k else "#5a5a5a"))
            t = ("✓ " if i < self.k else "") + name
            w = p.fontMetrics().horizontalAdvance(t) + 18
            p.drawText(x, 0, w, 20, Qt.AlignLeft | Qt.AlignVCenter, t)
            x += w
        key = self.steps[self.k]
        lab = f"{self.k + 1}/{len(self.steps)} {STEP_NAME[key]}" + (f" · {self.text}" if self.text else f" {int(self.v * 100)}%")
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(self.color(key)))
        p.drawText(x, 0, self.width() - x, 20, Qt.AlignRight | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(lab, Qt.ElideLeft, max(10, self.width() - x)))
        y, h, w = 28, 6, self.width()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        def bar(width, col):
            if width > 0:
                p.setBrush(QColor(col))
                p.drawRoundedRect(0, y, width, h, 3, 3)
        bar(w, "#2a2a2a")
        if self.k > 0:
            bar(w, self.color(self.steps[self.k - 1]))
        bar(int(w * self.v), self.color(key))
        p.end()


class ItemRow(QWidget):
    """렌더 항목 한 줄(렌더 작업 창과 같은 모양)."""

    def __init__(self, name):
        super().__init__()
        self.name, self.v, self.text, self.done = name, 0.0, "대기", False
        self.setFixedHeight(26)

    def set(self, v, text, done=False):
        self.v, self.text, self.done = v, text, done
        self.update()

    def paintEvent(self, _e):
        bg, fg, _n = SG.STAGE["render"]
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2e2e2e"))
        p.drawRoundedRect(r, 3, 3)
        if self.v > 0:
            p.setBrush(QColor(bg))
            p.drawRoundedRect(QRectF(r.left(), r.top(), r.width() * min(1.0, self.v), r.height()), 3, 3)
        f = p.font()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(r.adjusted(10, 0, -110, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.name, Qt.ElideMiddle, int(r.width() - 120)))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#9a9a9a" if self.done else fg))
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, self.text)
        p.end()


# ------------------------------------------------------------------ 자동 창
class AutoWindow(DragMove, QDialog):
    """outcome: 'edit'(편집 화면으로) | 'close'(닫음 — 렌더 끝 [닫기]) | ''(취소)."""

    def __init__(self, edit, parent=None, from_edit: bool = False):
        flags = (Qt.Dialog if from_edit else Qt.Window | Qt.WindowMinimizeButtonHint) | Qt.FramelessWindowHint
        super().__init__(parent if from_edit else None, flags)
        self.edit, self.state, self.from_edit = edit, edit.state, from_edit
        self.setModal(True)
        self.setObjectName("AutoWindow")
        self.setStyleSheet("#AutoWindow{background:#262626; border:1px solid #555; border-radius:6px;}")
        from . import __version__
        self.setWindowTitle(f"DTME {__version__}")
        self.outcome = ""
        self.running = False
        self.busy = False                     # (EditTab 호환)
        self.waiting = None
        self.armed = False                    # AUTO 누른 뒤에만 분석(미리 분석 없음, 사용자 11/16)
        self.jobs: list = []
        self._job = None                      # 자동 편집 작업(run_autoedit 가 넣음)
        self._folder = ""
        self._step = ""
        self._picked = False
        self._cdrag = None
        self._check_anchor = None
        self._cancelled = False
        self.rows: list[AutoRow] = []
        self.row_by: dict[str, AutoRow] = {}
        self.item_rows: dict[str, ItemRow] = {}
        self._added: set[str] = set()         # 이 창에서 넣은 소스([취소] = 버림)
        cfg = get_setting("autowin", {}) or {}
        self.cfg = cfg
        self.strength_v = cfg.get("strength", (get_setting("auto", {}) or {}).get("strength", "mid"))
        self._build(cfg)
        self.setAcceptDrops(True)
        st = self.state
        st.sourceStatus.connect(self._src_status)
        st.workChanged.connect(self._work_changed)
        st.changed.connect(self._state_changed)
        self.finished.connect(self._closed)
        self._refill = QTimer(self)
        self._refill.setSingleShot(True)
        self._refill.setInterval(80)
        self._refill.timeout.connect(self._fill_list)
        self._fill_list()
        self._media()
        self._sync()

    # ================================================================ 화면
    def _build(self, cfg: dict):
        self.list = SourceList()
        self.list.setItemDelegate(RowDelegate(self))
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet("QListWidget{background:#1e1e1e; border:1px solid #333; border-radius:3px; padding:4px;}")
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(lambda pos: self._menu(self.list.viewport().mapToGlobal(pos)))
        self.list.itemSelectionChanged.connect(self._sel_changed)
        self._vp = self.list.viewport()
        QShortcut(QKeySequence.SelectAll, self, activated=self.check_all)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self.remove_selected)
        self.note = QLabel("")                               # 가로·세로 섞였을 때만
        self.note.setStyleSheet("color:#f2c94c;")
        self.note.setVisible(False)
        lcol = QVBoxLayout()
        lcol.setSpacing(4)
        lcol.addWidget(self.list, 1)
        lcol.addWidget(self.note)
        # ---- 오른쪽 위: 음악 · 사진(넣었을 때만) · 요약
        self.music_box = QLabel("")
        self.music_box.setStyleSheet("QLabel{background:#1e1e1e; border:1px solid #333; border-radius:3px; padding:6px 8px; color:#d8d8d8;}")
        self.music_box.setVisible(False)
        self.photo_box = QWidget()
        self.photo_lay = QHBoxLayout(self.photo_box)
        self.photo_lay.setContentsMargins(0, 0, 0, 0)
        self.photo_lay.setSpacing(4)
        self.photo_box.setVisible(False)
        self.sum = QLabel("")
        self.sum.setStyleSheet(f"color:{SUB};")
        # ---- 단계 4줄
        self.stages: dict[str, StageRow] = {}
        for key, body in (("grade", self._grade_body(cfg)), ("edit", self._edit_body(cfg)),
                          ("music", self._music_body(cfg)), ("render", self._render_body(cfg))):
            sr = StageRow(key, body)
            sr.set_on(bool(cfg.get("on", {}).get(key, key != "render")))        # 렌더 기본 = 끔(켜면 기억)
            sr.toggled.connect(lambda _k, _v: self._sync())
            sr.clicked.connect(self._open_stage)
            self.stages[key] = sr
        right = QVBoxLayout()
        right.setSpacing(8)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.music_box)
        right.addWidget(self.photo_box)
        right.addWidget(self.sum)
        right.addStretch(1)
        for key in ("grade", "edit", "music", "render"):
            right.addWidget(self.stages[key])
        self.rw = QWidget()
        self.rw.setLayout(right)
        self.rw.setFixedWidth(470)
        # ---- 작업 중: 막대 · 항목 줄 · 글자
        self.step_bar = StepBar()
        self.run_lab = QLabel("")
        self.run_lab.setWordWrap(True)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(5)
        runl = QVBoxLayout()
        runl.setContentsMargins(0, 0, 0, 0)
        runl.setSpacing(10)
        runl.addStretch(1)
        runl.addLayout(self.rows_box)
        runl.addWidget(self.run_lab)
        runl.addWidget(self.step_bar)
        self.run_w = QWidget()
        self.run_w.setLayout(runl)
        self.run_w.setFixedWidth(470)
        self.run_w.setVisible(False)
        mid = QHBoxLayout()
        mid.setSpacing(16)
        mid.addLayout(lcol, 1)
        mid.addWidget(self.rw)
        mid.addWidget(self.run_w)
        # ---- 아래
        from . import __version__
        self.ver_lab = QLabel(f"DTME {__version__}")
        self.ver_lab.setStyleSheet("color:#6f6f6f; font-size:11px;")
        self.state_lab = QLabel("")
        self.b_cancel = main_button("취소")
        self.b_cancel.clicked.connect(self.cancel)
        self.b_start = main_button("AUTO", "red")
        self.b_start.clicked.connect(self.start)
        bot = QHBoxLayout()
        bot.setSpacing(8)
        bot.addWidget(self.ver_lab)
        bot.addSpacing(8)
        bot.addWidget(self.state_lab, 1)
        bot.addWidget(self.b_cancel)
        bot.addWidget(self.b_start)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(Grip(), 1)
        self.b_min = solo.min_button(self)
        top.addWidget(self.b_min)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 14)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addLayout(mid, 1)
        lay.addLayout(bot)
        self.resize(1040, 720)
        op = cfg.get("open", "")
        if op in self.stages:
            self.stages[op].set_open(True)

    def _line(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#3a3a3a;")
        return f

    def _body(self, rows) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 4, 12, 12)
        v.setSpacing(9)
        for r in rows:
            if isinstance(r, QWidget):
                v.addWidget(r)
            else:
                v.addLayout(r)
        return w

    def _slider(self, v, lo=0, hi=100, suffix=""):
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(int(v or 0))
        sl.setFocusPolicy(Qt.NoFocus)
        val = QLabel()
        val.setFixedWidth(36)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box = QHBoxLayout()
        box.setSpacing(8)
        box.addWidget(sl, 1)
        box.addWidget(val)
        sl.box = box
        sl.valueChanged.connect(lambda x, lab=val: lab.setText(f"{x}{suffix}"))
        val.setText(f"{sl.value()}{suffix}")
        return sl

    def _grade_body(self, cfg):
        self.keep = Seg([("keep", "기존 보정 유지"), ("drop", "기존 보정 무시")], "drop")       # 늘 [무시][자동]으로 시작(사용자 11/07)
        self.keep.changed.connect(self._keep)
        self.keys = Seg([("keep", "키프레임 유지"), ("auto", "키프레임 자동")], "auto")
        self.keys.changed.connect(lambda _k: self._sync())
        self.grid = PresetGrid()
        self.grid.set_current("auto")
        self.grid.chosen.connect(self._choose)
        self.strength = Seg([("weak", "약"), ("mid", "중"), ("strong", "강")], self.strength_v)
        self.strength.changed.connect(self._strength)
        self.lut_combo = QComboBox()
        self.lut_combo.setFixedHeight(30)
        self.lut_combo.setFocusPolicy(Qt.NoFocus)
        self.lut_combo.addItem("자동 (파일 정보)", "auto")
        self.lut_combo.addItem("LUT 없음", "")
        for n in ff.list_luts():
            self.lut_combo.addItem(n, n)
        self.lut_combo.setToolTip("자동 = D-Log M 영상만 LUT, 일반·알 수 없음은 LUT 없음")
        self.lut_combo.setCurrentIndex(max(0, self.lut_combo.findData(cfg.get("lut", "auto"))))
        self.lut_combo.currentIndexChanged.connect(self._lut_changed)
        self.lens_s = self._slider(cfg.get("lens", 0))
        self.stab_s = self._slider(cfg.get("stab", 0))
        for sl in (self.lens_s, self.stab_s):
            sl.valueChanged.connect(lambda _x: self._lens_stab())
        kk = QHBoxLayout()
        kk.setSpacing(8)
        kk.addWidget(self.keep, 1)
        kk.addWidget(self.keys, 1)
        return self._body([kk, self.grid, labeled("강도", self.strength, 64), labeled("LUT", self.lut_combo, 64),
                           labeled("렌즈 보정", self.lens_s.box, 64), labeled("흔들림 보정", self.stab_s.box, 64)])

    def _card_row(self, key, cur):
        s = Seg([("auto", "켬"), ("none", "없음")], cur if cur in ("auto", "none") else "auto", 28)
        s.changed.connect(lambda _k: self._sync())
        self.card[key] = s
        return s

    def _edit_body(self, cfg):
        self.length = self._slider(cfg.get("minutes", 3), 1, 10, "분")
        self.length.valueChanged.connect(lambda _v: self._sync())
        self.title_on = QCheckBox("날짜 바")
        self.title_on.setChecked(bool(cfg.get("title", True)))
        self.dive_on = QCheckBox("LOG 수심 그래프")
        self.dive_on.setChecked(bool(cfg.get("dive", True)))
        for cb in (self.title_on, self.dive_on):
            cb.toggled.connect(lambda _v: self._sync())
        cbs = QHBoxLayout()
        cbs.setSpacing(18)
        cbs.addWidget(self.title_on)
        cbs.addWidget(self.dive_on)
        cbs.addStretch(1)
        self.card: dict[str, Seg] = {}
        cards = QHBoxLayout()
        cards.setSpacing(8)
        cards.addLayout(labeled("시작 화면", self._card_row("start", cfg.get("start", "auto")), 64), 1)
        cards.addLayout(labeled("끝 화면", self._card_row("end", cfg.get("end", "auto")), 52), 1)
        self.place = QLineEdit()
        self.place.setPlaceholderText("지명")
        self._place_auto = True
        self.place.textEdited.connect(lambda _t: setattr(self, "_place_auto", False))
        self.end_text = QLineEdit()
        self._end_auto = True
        self.end_text.textEdited.connect(lambda _t: setattr(self, "_end_auto", False))
        self.end_text.editingFinished.connect(self._end_done)
        return self._body([labeled("전체 길이", self.length.box, 64), labeled("", cbs, 64), cards,
                           labeled("지명", self.place, 64), labeled("끝 문구", self.end_text, 64)])

    def _end_done(self):
        if not self.end_text.text().strip():              # 다 지움 = 자동 문구로
            self._end_auto = True
            self._sync()

    def _music_body(self, cfg):
        self.beat_on = QCheckBox("박자우선")
        self.beat_on.setChecked(bool(cfg.get("beat", True)))          # 기본 = 늘 켬(기본 음악만이어도, 사용자 11/17)
        self.mix_default = QCheckBox("기본 음악도 같이 쓰기")
        self.mix_default.setChecked(bool(cfg.get("mix_default", False)))
        for cb in (self.beat_on, self.mix_default):
            cb.toggled.connect(lambda _v: self._sync())
        h = QHBoxLayout()
        h.setSpacing(18)
        h.addWidget(self.beat_on)
        h.addWidget(self.mix_default)
        h.addStretch(1)
        return self._body([labeled("", h, 64)])

    def _render_body(self, cfg):
        p = self.state.project
        self.out = Seg(OUT_BTNS, ROT_BACK.get(p.output.orientation, p.output.orientation))
        self.out.btns["vertical"].setToolTip("1080×1920 · 릴스·쇼츠·틱톡")
        self.out.changed.connect(self._out)
        q = get_setting("last_quality", "") or p.output.quality or "normal"
        self.quality = Seg([(k, ff.QUALITY[k]["label"]) for k in ("high", "normal", "small")], q if q in ff.QUALITY else "normal")
        self.quality.changed.connect(lambda _k: self._sync())
        self.folder = QLineEdit(p.output.folder or get_setting("last_folder", "") or "")
        self.folder.setFixedHeight(28)
        self.folder.textChanged.connect(lambda _t: self._sync())
        b = QPushButton("…")
        b.setFixedSize(34, 28)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(self._pick_folder)
        fr = QHBoxLayout()
        fr.setSpacing(5)
        fr.addWidget(self.folder, 1)
        fr.addWidget(b)
        self.name = QLineEdit(p.output.prefix or "DTME")
        self.name.setFixedHeight(28)
        self.name.setFixedWidth(140)
        self.save_on = QCheckBox("프로젝트 저장")
        self.save_on.setChecked(bool(cfg.get("save", True)))
        self.save_on.setToolTip("영상 옆 .dtme.json — 나중에 편집 창에서 고침")
        nr = QHBoxLayout()
        nr.setSpacing(14)
        nr.addWidget(self.name)
        nr.addWidget(self.save_on)
        nr.addStretch(1)
        self.mb_lab = QLabel("")
        self.mb_lab.setStyleSheet("color:#8f9499;")
        return self._body([labeled("출력", self.out, 64), labeled("품질", self.quality, 64), labeled("", self.mb_lab, 64),
                           labeled("저장 폴더", fr, 64), labeled("이름", nr, 64)])

    def resizeEvent(self, e):
        super().resizeEvent(e)

    # ================================================================ 목록
    def _sources(self):
        return list(self.state.project.sources)

    def _list_sig(self):
        p = self.state.project
        return (tuple((s.id, bool(s.frames), s.width, s.height, s.ctime) for s in p.sources), len(p.dives))

    def _fill_list(self):
        p = self.state.project
        srcs = self._sources()
        self._sig = self._list_sig()
        keep_sel = {it.data(Qt.UserRole) for it in self.list.selectedItems()}
        old = self.row_by
        self.rows, self.row_by = [], {}
        self.list.blockSignals(True)
        self.list.clear()
        groups = autoedit.trip_groups(p.dives, srcs)
        for head, grp in groups:
            if head:
                it = QListWidgetItem(head)
                it.setData(Qt.UserRole, None)
                it.setData(Qt.UserRole + 1, head)
                it.setFlags(Qt.ItemIsEnabled)
                self.list.addItem(it)
            for s in grp:
                r = old.get(s.id)
                if r is not None and not r.out_set:
                    r.out = p.out_of(s)                    # 크기·방향이 읽힌 뒤 값으로(세로 촬영 = 돌린 크기)
                if r is None:
                    bad = self.state.status.get(s.id) in ("읽기 오류", "원본 없음")
                    rec = s.auto or {}
                    choice = auto.normalize_key(rec.get("preset", "")) if rec.get("by") == "user" else "auto"
                    r = AutoRow(s, not bad, choice or "auto", p.out_of(s))
                self.rows.append(r)
                self.row_by[s.id] = r
                it = QListWidgetItem(display_name(s.path))
                it.setData(Qt.UserRole, s.id)
                self.list.addItem(it)
                if s.id in keep_sel:
                    it.setSelected(True)
        self.list.blockSignals(False)
        note = autoedit.mix_note([s for s in srcs if self.row_by[s.id].checked])
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self._out_options()
        self._sync()

    def odd_tag(self, src) -> str:
        """방향이 많은 쪽과 다른 클립 표시."""
        srcs = [s for s in self._sources() if s.id in self.row_by and self.row_by[s.id].checked and s.width]
        h, v = autoedit.orient_count(srcs)
        if not h or not v or not src.width:
            return ""
        major_v = v > h
        return ("가로" if major_v else "세로") if is_portrait(src) != major_v else ""

    def row_text(self, row: AutoRow) -> str:
        """오른쪽 글자: 길이(분석 뒤 = 장면 · 길이)."""
        s = self.state.project.source(row.sid)
        if s is None or not s.frames:
            return ""
        a, b = s.io
        parts = []
        if row.result:
            parts.append(auto.preset_label(row.result["preset"]))
        elif row.choice != "auto":
            parts.append(auto.preset_label(row.choice))
        elif (s.auto or {}).get("preset"):
            parts.append(auto.preset_label(s.auto["preset"]))
        if row.error:
            parts.append("분석 실패")
        parts.append(mmss((b - a) / float(s.fps)))
        return "  ·  ".join(parts)

    def _row_of(self, it) -> AutoRow | None:
        return self.row_by.get(it.data(Qt.UserRole)) if it is not None else None

    def _sel_rows(self):
        return [r for r in (self._row_of(it) for it in self.list.selectedItems()) if r is not None]

    def _targets(self):
        return self._sel_rows() or self.rows

    def _out_targets(self):
        return self._targets() if self._picked else self.rows

    def _sel_changed(self):
        rs = self._sel_rows()
        if rs:
            self.grid.set_current(rs[0].choice)
            self.out.set_value(self._btn_key(rs[0]))
        self._out_options()

    def _btn_key(self, r) -> str:
        s = self.state.project.source(r.sid)
        if is_portrait(s):
            return ROT_BACK.get(r.out, "horizontal" if r.out == "vertical" else r.out)
        return r.out if r.out in self.out.btns else "horizontal"

    def _out_options(self):
        p = self.state.project
        ok = set()
        for r in self._out_targets():
            s = p.source(r.sid)
            if s is None:
                continue
            for k in outputs_for(source_out_h(s), source_vw(s)):
                if is_portrait(s):
                    if k in ROT_BACK:
                        ok.add(ROT_BACK[k])
                    elif k == "vertical":
                        ok.add("horizontal")
                else:
                    ok.add(k)
        for k, b in self.out.btns.items():
            b.setVisible(k in ok or not self.rows)

    def _out(self, k):
        p = self.state.project
        for r in self._out_targets():
            s = p.source(r.sid)
            key = ROT.get(k, k) if is_portrait(s) else k
            r.out = clamp_src(key, s)
            r.out_set = True
        self._sync()

    def _choose(self, key):
        rows = self.rows if key == "auto" else self._targets()
        for r in rows:
            r.choice = key
            r.result = None if not self.running else r.result
        self.list.viewport().update()
        self._sync()

    def _strength(self, _k):
        for r in self.rows:
            r.result = None
        self._sync()

    def _keep(self, k):
        for r in self.rows:
            s = self.state.project.source(r.sid)
            if s and has_clip_grade(s) and s.frames:
                r.checked = k != "keep"
        self.list.viewport().update()
        self._sync()

    def _lens_stab(self):
        for r in self.rows:
            if r.result:
                r.result["grade"]["lens"] = self.lens_s.value()
                r.result["grade"]["stab"] = self.stab_s.value()

    def row_lut(self, r) -> str:
        choice = self.lut_combo.currentData()
        p = self.state.project
        s = p.source(r.sid)
        if choice != "auto":
            return choice or ""
        a = auto_lut(p, s) if s else None
        return a if a is not None else (p.grade_for_source(s.id, off=False).get("lut", "") if s else "")

    def _lut_changed(self, *_):
        for r in self.rows:
            r.result, r.prog, r.error = None, 0.0, ""
        self.list.viewport().update()

    # ---------------------------------------------------------------- 체크(누른 채 쓸기 · Shift 범위)
    def showEvent(self, e):
        super().showEvent(e)
        self._vp.installEventFilter(self)

    def hideEvent(self, e):
        try:
            self._vp.removeEventFilter(self)
        except RuntimeError:
            pass
        self._cdrag = None
        super().hideEvent(e)

    def eventFilter(self, obj, e):
        if obj is getattr(self, "_vp", None) and e.type() in (QEvent.MouseButtonPress, QEvent.MouseMove,
                                                                QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            if self.running:
                return True
            if e.type() == QEvent.MouseButtonPress:
                self._picked = True
            try:
                if self._check_drag(e):
                    return True
            except RuntimeError:
                self._cdrag = None
            return False
        return False

    def _src_items(self):
        return [self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole) is not None]

    def _row_idx_at(self, y) -> int:
        """y 자리의 소스 줄 번호(self.rows 기준, 머리줄 = 가까운 아래 줄). 없으면 -1."""
        if not self.rows:
            return -1
        it = self.list.itemAt(8, int(y))
        if it is None:
            first = self.list.item(0)
            return 0 if y < self.list.visualItemRect(first).top() else len(self.rows) - 1
        i = self.list.row(it)
        while i < self.list.count() and self.list.item(i).data(Qt.UserRole) is None:
            i += 1
        if i >= self.list.count():
            return len(self.rows) - 1
        return self.rows.index(self.row_by[self.list.item(i).data(Qt.UserRole)])

    def _check_drag(self, e) -> bool:
        t = e.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            if e.button() != Qt.LeftButton:
                return False
            it = self.list.itemAt(e.position().toPoint())
            if it is None:
                return False
            if it.data(Qt.UserRole) is None:
                return True                                   # 머리줄 = 아무 일 없음
            if e.position().x() >= self.list.visualItemRect(it).left() + 32:
                return False
            i = self.rows.index(self._row_of(it))
            anc = self._check_anchor
            if e.modifiers() & Qt.ShiftModifier and anc is not None and anc[0] < len(self.rows):
                a, b = min(anc[0], i), max(anc[0], i)
                for k in range(a, b + 1):
                    self.rows[k].checked = anc[1]
                self._row_changed()
                return True
            self._cdrag = (i, not self.rows[i].checked, [r.checked for r in self.rows])
            self._check_anchor = (i, not self.rows[i].checked)
            self._paint_checks(i)
            return True
        if self._cdrag is None:
            return False
        if t == QEvent.MouseMove:
            self._paint_checks(self._row_idx_at(e.position().y()))
            return True
        if t == QEvent.MouseButtonRelease:
            self._cdrag = None
            self._row_changed()
            return True
        return False

    def _paint_checks(self, j):
        i, v, orig = self._cdrag
        if j < 0:
            return
        a, b = min(i, j), max(i, j)
        for k, r in enumerate(self.rows):
            r.checked = v if a <= k <= b else orig[k]
        self.list.viewport().update()

    def check_all(self):
        if self.running:
            return
        for r in self.rows:
            r.checked = True
        self.list.selectAll()
        self._row_changed()

    def _row_changed(self):
        note = autoedit.mix_note([s for s in self._sources() if s.id in self.row_by and self.row_by[s.id].checked])
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.list.viewport().update()
        self._sync()

    def remove_selected(self):
        """Del = 고른 소스를 목록에서 제거(체크 끔 = 이번 편집에서만 뺌)."""
        if self.running:
            return
        sids = [r.sid for r in self._sel_rows()]
        for sid in sids:
            self.state.remove_source(sid)
            self._added.discard(sid)
        if sids:
            self._fill_list()

    # ================================================================ 넣기(우클릭 · 끌어다 놓기)
    def _menu(self, gpos):
        if self.running:
            return
        m = QMenu(self)
        a_f = m.addAction("파일 추가…")
        a_d = m.addAction("폴더 추가…")
        m.addSeparator()
        a_p = m.addAction("프로젝트 열기…")
        act = m.exec(gpos)
        start = get_setting("last_src_folder", "") or ""
        if act is a_f:
            from .ui_launch import MEDIA_FILTER
            files, _ = QFileDialog.getOpenFileNames(self, "파일 추가", start, MEDIA_FILTER)
            if files:
                self.add_paths(files)
        elif act is a_d:
            d = QFileDialog.getExistingDirectory(self, "폴더 추가", start)
            if d:
                self.add_paths([d])
        elif act is a_p:
            from .ui_main import PROJ_FILTER
            f, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", start, PROJ_FILTER)
            if f:
                self.open_project(f)

    def contextMenuEvent(self, e):
        self._menu(e.globalPos())

    def dragEnterEvent(self, e):
        if not self.running and e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    def add_paths(self, paths: list[str]):
        """영상·폴더·음악·사진·다이빙 기록 = 넣기 / 프로젝트 파일 = 바로 편집 화면."""
        if self.running:
            return
        from .ui_launch import collect_media
        proj = next((f for f in paths if is_project_file(f)), None)
        if proj:
            self.open_project(proj)
            return
        files = collect_media(paths)
        vids = [f for f in files if Path(f).suffix.lower() in VIDEO_EXT]
        if vids:
            try:
                set_setting("last_src_folder", str(Path(vids[0]).parent))
            except Exception:  # noqa: BLE001
                pass
        before = {s.id for s in self.state.project.sources}
        if not self.from_edit:
            self.state.defer_proxy = True                 # AUTO 전 = 파일 정보만(프록시는 AUTO 뒤)
        self.edit.import_files(files)
        self._added |= {s.id for s in self.state.project.sources} - before
        self._fill_list()
        self._media()

    def open_project(self, f: str):
        mw = self.edit.window()
        if self.from_edit and hasattr(mw, "_confirm_discard") and not mw._confirm_discard():
            return
        self.state.defer_proxy = False
        mw._load(f)
        self.outcome = "edit"
        self.accept()

    # ================================================================ 오른쪽 위(음악 · 사진 · 요약)
    def _media(self):
        p = self.state.project
        user = [a for a in p.audios if not a.get("builtin")]
        if user:
            lines = []
            for a in user[:8]:
                d = float(a.get("dur") or 0.0)
                lines.append(f"♪ {Path(a['path']).stem}" + (f"  ·  {mmss(d)}" if d > 0 and d != 600.0 else ""))
            if len(user) > 8:
                lines.append(f"… 외 {len(user) - 8}곡")
            self.music_box.setText("\n".join(lines))
        self.music_box.setVisible(bool(user))
        while self.photo_lay.count():
            w = self.photo_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for m in p.images[:9]:
            lb = QLabel()
            lb.setFixedSize(44, 44)
            lb.setStyleSheet("background:#1e1e1e; border:1px solid #333;")
            pm = QPixmap(m.path)
            if not pm.isNull():
                lb.setPixmap(pm.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                lb.setAlignment(Qt.AlignCenter)
            lb.setToolTip(Path(m.path).name)
            self.photo_lay.addWidget(lb)
        self.photo_lay.addStretch(1)
        self.photo_box.setVisible(bool(p.images))
        self._sync()

    def has_timeline(self) -> bool:
        return self.from_edit and bool(self.state.project.segments)

    def _trips(self):
        p = self.state.project
        cs = []
        for r in self.rows:
            s = p.source(r.sid)
            if r.checked and s is not None and s.frames:
                a, b = s.io
                w = autoedit.cut_when(s, Segment(s.id, a, b))
                if w is not None:
                    cs.append((w, w + (b - a) / float(s.fps)))
        return autoedit.trips_of(cs)

    def _sync(self):
        """요약 줄 · 단계 요약 · 켬/끔 가능 · [AUTO] 켜짐."""
        if not hasattr(self, "b_start"):
            return
        p = self.state.project
        rows = [r for r in self.rows if r.checked]
        tot = 0.0
        for r in rows:
            s = p.source(r.sid)
            if s is not None and s.frames:
                a, b = s.io
                tot += (b - a) / float(s.fps)
        st = self.stages
        e_on = st["edit"].active()
        parts = []
        if p.dives:
            parts.append(f"다이빙 기록 {len(p.dives)}개")
        if rows:
            parts.append(f"영상 {len(rows)}개 {mmss(tot)}" + (f" → {self.length.value()}분" if e_on else ""))
        self.sum.setText(" · ".join(parts))
        # 보정
        ch = {r.choice for r in rows} or {"auto"}
        pre = "프리셋 자동" if ch == {"auto"} else (auto.preset_label(next(iter(ch))) if len(ch) == 1 else "프리셋 섞음")
        st["grade"].set_summary(" · ".join([pre, {"weak": "약", "mid": "중", "strong": "강"}.get(self.strength.value(), "중"),
                                            "기존 보정 유지" if self.keep.value() == "keep" else "기존 보정 무시"]))
        # 편집
        self.dive_on.setEnabled(bool(p.dives))
        self.dive_on.setToolTip(f"다이빙 {len(p.dives)}개 · 컷 최소 15초" if p.dives else "다이빙 기록 없음 — FIT·DTMD 파일을 이 창에 끌어다 놓기")
        trips = self._trips()
        if self._place_auto and not self.place.hasFocus():
            self.place.setText(autoedit.trips_place(p.dives, trips) if p.dives else "")
        if self._end_auto and not self.end_text.hasFocus():       # 자동 문구를 실제 글로(커서로 바로 고침, ' / ' = 줄바꿈)
            ds = autoedit.trips_dives(p.dives, trips) if self.dive_on.isChecked() and p.dives else []
            ls = autoedit.end_lines(bool(ds), ds, self.place.text().strip(), autoedit.trips_period(trips))
            self.end_text.setText(" / ".join(x[0] for x in ls) if rows else "")
        cards = [n for k, n in (("start", "시작"), ("end", "끝")) if self.card[k].value() == "auto"]
        st["edit"].set_summary(" · ".join(x for x in (f"{self.length.value()}분", "날짜 바" if self.title_on.isChecked() else "",
                                                       "LOG" if self.dive_on.isChecked() and p.dives else "",
                                                       ("/".join(cards) + " 화면") if cards else "") if x))
        # 음악
        user = [a for a in p.audios if not a.get("builtin")]
        n_def = len(self.state.default_music())
        self.mix_default.setVisible(bool(user) and bool(n_def))
        self.mix_default.setText(f"기본 음악도 같이 쓰기 ({n_def}곡)")
        m_can = (e_on or self.has_timeline()) and bool(user or n_def)
        st["music"].set_can(m_can)
        if not (e_on or self.has_timeline()):
            st["music"].set_summary("편집을 켜야 함")
        elif not (user or n_def):
            st["music"].set_summary("음악 없음")
        else:
            st["music"].set_summary(" · ".join(x for x in ("박자우선" if self.beat_on.isChecked() else "",
                                                            f"올린 곡 {len(user)}곡" if user else f"기본 음악 {n_def}곡",
                                                            "기본 음악도" if user and self.mix_default.isChecked() else "") if x))
        # 렌더
        okey = self.out.value() or "horizontal"
        olab = dict(OUT_BTNS).get(okey, "1080")
        fol = self.folder.text().strip()
        q = self.quality.value() or "normal"
        st["render"].set_summary(" · ".join([olab, ff.QUALITY[q]["label"], Path(fol).name or fol if fol else "저장 폴더 —"]))
        secs = self.length.value() * 60.0 if e_on else (p.out_seconds() if self.has_timeline() and not st["grade"].active() else tot)
        self.mb_lab.setText(f"약 {ff.est_mb(q, secs, okey):,.0f}MB" if secs > 0 else "")
        # [AUTO]
        ok = bool(rows) or (self.has_timeline() and (st["music"].active() or st["render"].active())
                            and not st["grade"].active() and not e_on)
        self.b_start.setEnabled(ok and not self.running)

    def _open_stage(self, key):
        """줄 누름 = 펼침(한 번에 하나)."""
        was = self.stages[key].open_
        for k, sr in self.stages.items():
            sr.set_open(k == key and not was)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더", self.folder.text().strip() or get_setting("last_folder", "") or "")
        if d:
            self.folder.setText(d)
            try:
                set_setting("last_folder", d)
            except Exception:  # noqa: BLE001
                pass

    # ================================================================ 설정
    def settings(self) -> dict:
        """EditTab._auto_begin / _auto_apply 가 읽는 값(예전 AUTO 창과 같은 모양)."""
        return {"strength": self.strength.value(), "keep": self.keep.value(), "keys": self.keys.value(),
                "after": "each", "lens": self.lens_s.value(), "stab": self.stab_s.value(), "lut": self.lut_combo.currentData()}

    def config(self) -> dict:
        """마지막 선택 기억(단계 체크 + 각 단계 설정)."""
        return {"on": {k: sr.on for k, sr in self.stages.items()},
                "open": next((k for k, sr in self.stages.items() if sr.open_), ""),
                "strength": self.strength.value(), "lut": self.lut_combo.currentData(),
                "lens": self.lens_s.value(), "stab": self.stab_s.value(),
                "minutes": self.length.value(), "title": self.title_on.isChecked(), "dive": self.dive_on.isChecked(),
                "start": self.card["start"].value(), "end": self.card["end"].value(),
                "beat": self.beat_on.isChecked(), "mix_default": self.mix_default.isChecked(),
                "save": self.save_on.isChecked()}

    def _save_config(self):
        try:
            set_setting("autowin", self.config())
            set_setting("last_quality", self.quality.value() or "normal")
        except Exception:  # noqa: BLE001
            pass

    def edit_settings(self, sids: list[str]) -> dict:
        """run_autoedit 에 넘길 값."""
        p = self.state.project
        return {"sids": sids, "minutes": self.length.value(), "title": self.title_on.isChecked(),
                "music": self.stages["music"].active(), "beat": self.beat_on.isChecked(),
                "mix_default": self.mix_default.isChecked() and bool([a for a in p.audios if not a.get("builtin")]),
                "grade": False, "save": self.save_on.isChecked(), "dive": self.dive_on.isChecked() and bool(p.dives),
                "start": self.card["start"].value(), "end": self.card["end"].value(),
                "place": self.place.text().strip(), "end_text": "" if self._end_auto else self.end_text.text().strip(),
                "full": True, "replace_ok": True, "no_prep": True}

    def chosen(self) -> list[str]:
        return [r.sid for r in self.rows if r.checked]

    def autoedit_settings(self, grade: bool = True) -> dict:
        """자동 편집만 따로 돌릴 때(시험 · run_autoedit 직접): 끝나면 창이 닫히고 편집 화면 타임라인."""
        st = self.edit_settings(self.chosen())
        st.update(full=False, replace_ok=False, no_prep=False, grade=grade)
        return st

    # ================================================================ 분석(보정 단계)
    def _compute(self, r: AutoRow):
        s = self.state.project.source(r.sid)
        lut = self.row_lut(r)
        smp = cached_samples(s, lut) if s else None
        if not smp:
            return
        base = dict(self.state.project.grade)
        base.update({k: v for k, v in s.grade.items() if k in ("sharpen", "lens")})
        base["lut"] = lut
        sc, sb = choice_args(r.choice)
        r.result = auto.recommend(smp, base, sc, sb, self.strength.value() or "mid", fps=float(s.fps),
                                  measure=not auto.is_dji_log(s, lut))
        r.result["grade"]["lens"] = self.lens_s.value()
        r.result["grade"]["stab"] = self.stab_s.value()
        r.rec = auto.recommend(smp, base)["preset"]

    def pending(self):
        return [r for r in self.rows if r.checked and r.result is None and not r.error
                and self.state.status.get(r.sid) not in ("읽기 오류", "원본 없음", "프록시 오류")]

    def chosen_rows(self):
        return [r for r in self.rows if r.checked and r.result]

    def analyze_all(self):
        if not self.armed:
            return
        p = self.state.project
        for r in self.rows:
            s = p.source(r.sid)
            if not r.checked or s is None or not s.frames or r.result is not None or r.prog > 0 or r.error:
                continue
            lut = self.row_lut(r)
            if cached_samples(s, lut):                     # 이번 실행 중 이미 읽은 영상 = 계산만
                self._compute(r)
                if r.result:
                    r.prog = 1.0
                    continue
            r.prog = 0.01
            self.state.set_work(r.sid, "analyze", -1)

            def done(_smp, r=r):
                r.prog, r.running = 1.0, False
                self.state.set_work(r.sid, None)
                self._compute(r)
                self.list.viewport().update()
                self._grade_tick()

            def err(msg, r=r):
                r.running = False
                if msg == "취소됨":
                    r.prog = 0.0
                    self.state.set_work(r.sid, None)
                    self.list.viewport().update()
                    return
                ff.log_error("AUTO 분석", msg)
                if not r.retried:
                    r.retried, r.prog = True, 0.0
                    self.state.set_work(r.sid, "analyze", -1)
                    QTimer.singleShot(800, self.analyze_all)
                    return
                r.error, r.prog = msg, 1.0
                self.state.set_work(r.sid, None)
                self.list.viewport().update()
                self._grade_tick()

            def prog(v, r=r):
                r.running = True
                r.prog = max(0.01, min(0.99, v))
                self.state.set_work(r.sid, "analyze", r.prog)
                self._grade_tick(done=False)
            j = grab_job(s, lut, p.output.gpu_decode, done, err, prog)
            if j:
                self.jobs.append(j)
        self._grade_tick()

    def _src_status(self, sid):
        if sid in self.row_by:
            self.list.viewport().update()
            s = self.state.project.source(sid)
            if s is not None and s.frames:
                if self._list_sig() != getattr(self, "_sig", None) and not self._refill.isActive():
                    self._refill.start()              # 길이·방향·촬영 시각이 읽힘 → 묶음·알림 다시
                if self._step == "grade":
                    self.analyze_all()
        elif self.state.project.source(sid) is not None and not self._refill.isActive():
            self._refill.start()

    def _work_changed(self, _sid):
        try:
            self.list.viewport().update()
        except RuntimeError:
            pass

    def _state_changed(self, what):
        if what in ("sources", "project", "dives"):
            if not self._refill.isActive():
                self._refill.start()
        if what in ("audios", "images", "project", "dives"):
            QTimer.singleShot(0, self._media_safe)
            QTimer.singleShot(400, self._media_safe)       # 곡 길이는 뒤에서 읽힘

    def _media_safe(self):
        try:
            if self.isVisible() or not self.running:
                self._media()
        except RuntimeError:
            pass

    # ================================================================ 실행
    def set_running(self, on: bool):
        """작업 중 = 설정 칸 숨김, 막대·글자·[취소]·[−]만."""
        self.running = self.busy = bool(on)
        self.rw.setVisible(not on)
        self.run_w.setVisible(on)
        self.b_start.setVisible(not on)
        self.list.setEnabled(True)
        self.b_cancel.setEnabled(True)
        if not self.from_edit:
            self.b_min.setVisible(on)
        if not on:
            self._step = ""
            self.waiting = None
            self._clear_items()
            self.state_lab.setText("")
            from . import taskbar
            taskbar.clear(self)
            self.setWindowTitle(self.windowTitle().split(" — ")[0])
        self.list.viewport().update()
        self._sync()

    def set_progress(self, v: float, text: str = ""):
        """run_autoedit 이 부름(편집 단계 진행)."""
        self._show("edit", v, text)

    def _show(self, key: str, v: float, text: str = ""):
        self.step_bar.set(key, v, text)
        frac = self.step_bar.frac()
        from . import taskbar
        taskbar.set_progress(self, frac)
        base = self.windowTitle().split(" — ")[0]
        self.setWindowTitle(f"{base} — {STEP_NAME.get(key, '')} {int(frac * 100)}%")

    def _say(self, text: str, key: str = ""):
        self.run_lab.setText(text)
        col = self.step_bar.color(key) if key else SUB
        self.run_lab.setStyleSheet(f"color:{col};")

    def start(self):
        """[AUTO]."""
        if self.running:
            return
        p = self.state.project
        st = self.stages
        g_on, e_on, m_on, r_on = (st[k].active() for k in ("grade", "edit", "music", "render"))
        rows = [r for r in self.rows if r.checked]
        tl_only = not rows or (self.has_timeline() and not g_on and not e_on)
        if not rows and not self.has_timeline():
            return
        if not (g_on or e_on or m_on or r_on):             # 아무 단계도 안 켬 = 그냥 편집 화면으로
            self._save_config()
            self._to_editor()
            return
        if e_on and p.segments and ui_style.confirm(self, "타임라인을 바꿀까요?",
                                                    [("cancel", "취소", 72, None), ("ok", "바꾸기", 80, "red")]) != "ok":
            return
        if r_on:
            if not self.folder.text().strip():
                self._pick_folder()
            fol = self.folder.text().strip()
            if not fol:
                return
            self._folder = fol
            if p.output.quality != (self.quality.value() or "normal"):
                p.output.quality = self.quality.value() or "normal"
                self.state.dirty = True
        else:
            self._folder = ""
        self._save_config()
        # 단계 목록: 보정 → 편집 → 음악 → 렌더 | 편집 준비
        steps = [k for k, on in (("grade", g_on and not tl_only), ("edit", e_on and not tl_only), ("music", m_on),
                                 ("render", r_on)) if on]
        if not r_on:
            steps.append("prep")
        self._plan = {"grade": "grade" in steps, "edit": "edit" in steps, "music": "music" in steps, "render": r_on,
                      "tl_only": tl_only, "per_clip": r_on and "edit" not in steps and not (self.has_timeline() and "grade" not in steps)}
        self._cancelled = False
        self.step_bar.set_steps(steps)
        self._say("")
        self.set_running(True)
        self._t0 = __import__("time").time()
        if self.from_edit:
            try:
                self.edit.player.pause()
            except Exception:  # noqa: BLE001
                pass
            solo.enter(self, self.edit.window())
        for r in rows:                                     # 출력 크기 = 줄 값(보정 끔이어도)
            s = p.source(r.sid)
            if s is not None and r_on and s.out != r.out:
                s.out = r.out
        ff.log_info(f"자동 창 AUTO: 단계 {steps} · 소스 {len(rows)}개 · 편집 창에서 {self.from_edit}")
        self._step_grade()

    # ---------------------------------------------------------------- 1) 보정
    def _step_grade(self):
        if not self._plan["grade"]:
            self._step_edit()
            return
        self._step = "grade"
        self.armed = True
        for r in self.rows:
            if r.result is None and not r.error:
                r.prog = 0.0
        self._show("grade", 0.0)
        self.analyze_all()

    def _grade_tick(self, done: bool = True):
        if self._step != "grade":
            return
        rows = [r for r in self.rows if r.checked]
        n = len(rows)
        fin = sum(1 for r in rows if r.result is not None or r.error)
        v = sum(min(1.0, r.prog) for r in rows) / max(1, n)
        self._show("grade", v, f"{fin}/{n}")
        if done and not self.pending():
            rows = self.chosen_rows()
            if not rows:
                self._fail("분석 결과 없음")
                return
            self._step = ""
            self.edit._auto_begin(self)
            self.edit._auto_apply(self, rows)
            self._step_edit()

    # ---------------------------------------------------------------- 2) 편집(+ 음악)
    def _step_edit(self):
        p = self.state.project
        if self._plan["edit"]:
            self._step = "edit"
            sids = [r.sid for r in self.rows if r.checked and (p.source(r.sid) is not None and p.source(r.sid).frames)]
            if not sids:
                self._fail("영상 없음")
                return
            st = self.edit_settings(sids)
            st["no_prep"] = True
            self._show("edit", 0.0)
            self.edit.run_autoedit(self, st, then=self._after_edit)
            return
        if self._plan["music"] and p.segments:             # 편집 끔 + 음악 = 지금 타임라인에 음악만
            self._step = "music"
            self._show("music", 0.0)
            self.edit.auto_music(ask=False, then=self._after_music)
            return
        self._step_out()

    def _after_edit(self):
        if self._plan["music"]:
            self._show("music", 1.0)
        self._step_out()

    def _after_music(self, ok: bool = True):
        self._show("music", 1.0)
        self._step_out()

    def _step_out(self):
        if self._cancelled:
            return
        if self._plan["render"]:
            self._step_render()
        else:
            self._step_prep()

    # ---------------------------------------------------------------- 3) 렌더
    def _clear_items(self):
        while self.rows_box.count():
            w = self.rows_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.item_rows = {}

    def _step_render(self):
        p = self.state.project
        ed = self.edit
        self._step = "render"
        p.output.folder = self._folder
        p.output.prefix = self.name.text().strip()
        items = []
        if self._plan["per_clip"]:                         # 편집 끔 = 클립마다 따로
            for r in self.rows:
                s = p.source(r.sid)
                if not r.checked or s is None or not s.frames:
                    continue
                a, b = s.io
                items.append(RenderItem(name=short_name(s.path), segs=[p.snap_seg(Segment(s.id, a, b, 1.0))],
                                        orientation=p.out_of(s), audio=True))
            p.render_items += items
            self.state.touch("render")
        elif p.segments:                                   # 타임라인 1편
            ed.timeline_to_render()
            items = [p.render_items[-1]]
            if self.save_on.isChecked():
                try:
                    f = unique(out_dir(p) / f"{file_name(p, items[0])}.dtme.json")
                    p.save(str(f))
                    self.state.dirty = False
                    win = ed.window()
                    if hasattr(win, "_title"):
                        win._title()
                except Exception as ex:  # noqa: BLE001
                    ff.log_error("자동 창 프로젝트 저장", str(ex))
        if not items:
            self._fail("렌더할 것 없음")
            return
        self._clear_items()
        for it in items[:12]:
            row = ItemRow(f"{file_name(p, it)}.mp4")
            self.item_rows[it.id] = row
            self.rows_box.addWidget(row)
        self._show("render", 0.0)
        rp = ed.render_panel
        rp.itemProgress.connect(self._r_item)
        rp.runProgress.connect(self._r_prog)
        rp.runFinished.connect(self._r_end)
        self._say(str(out_dir(p)), "render")
        rp.enqueue(items)
        if not rp.running:
            self._r_disconnect()
            self._fail("렌더를 시작하지 못함")

    def _r_item(self, _iid, _v, _more):
        rp = self.edit.render_panel
        for iid, row in self.item_rows.items():
            s = rp.status.get(iid, "")
            if s.startswith("완료"):
                row.set(1.0, "완료", True)
            elif s.startswith("실패"):
                row.set(1.0, "실패", True)
            elif s == "취소":
                row.set(0.0, "취소", True)
            elif iid in rp.active:
                stg = rp.stage.get(iid, "")
                pv = rp.progress.get(iid, 0.0)
                row.set(pv, f"인코딩 {int(pv * 100)}%" if stg == "인코딩" else (stg or "준비"))
            else:
                row.set(0.0, "대기")

    def _r_prog(self, frac, text, _bad):
        if self._step == "render":
            self._show("render", frac, text)

    def _r_disconnect(self):
        rp = self.edit.render_panel
        for sig, fn in ((rp.itemProgress, self._r_item), (rp.runProgress, self._r_prog), (rp.runFinished, self._r_end)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass

    def _r_end(self, ok, bad, sec, folder):
        self._r_disconnect()
        if self._step != "render":
            return
        self._r_item("", 1.0, False)
        if self._cancelled or self.edit.render_panel.cancelled:
            self._back("렌더 취소")
            return
        self._show("render", 1.0, f"완료 {ok}" + (f" · 실패 {bad}" if bad else ""))
        self._step = "done"
        from . import taskbar
        taskbar.flash(self)
        self._done_popup(ok, bad, sec, folder)

    def _done_popup(self, ok, bad, sec, folder):
        """완료 팝업 = [폴더 열기] [편집 화면] [닫기]. 편집 화면은 눌렀을 때만 열고 그때 프록시."""
        from .ui_render import done_sound
        d = Popup(self)
        lb = QLabel(f"렌더 완료 {ok}개 · 실패 {bad}개 · {took_text(sec)}")
        lb.setStyleSheet(f"color:{'#ff8a80' if bad else '#e6e6e6'}; font-size:13px;")
        d.body.addWidget(lb)
        br = QHBoxLayout()
        br.addStretch(1)
        got = {"v": "close"}
        for key, text, tone in (("folder", "폴더 열기", None), ("edit", "편집 화면", None), ("close", "닫기", "blue")):
            b = main_button(text, tone)
            b.clicked.connect(lambda _=False, k=key: (got.update(v=k), d.accept()) if k != "folder" else open_file(folder))
            br.addWidget(b)
        d.body.addLayout(br)
        d.center_on(self)
        self._done_dlg = d
        done_sound()
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and not os.environ.get("DTME_DONE_POPUP"):
            got["v"] = os.environ.get("DTME_DONE_CHOICE", "close")      # 화면 없는 시험 = 묻지 않음
        else:
            d.exec()
        self._finish(got["v"])

    def _finish(self, what: str):
        """what = 'edit'(편집 화면) | 'close'."""
        self.set_running(False)
        if what == "edit":
            self._to_editor()
            return
        self.outcome = "close"
        if self.from_edit:
            solo.leave(self)
        self.accept()

    # ---------------------------------------------------------------- 4) 편집 준비(렌더 끔)
    def _prep_sources(self):
        p = self.state.project
        if p.segments:
            ids = list(dict.fromkeys(g.src for g in p.segments))
        else:
            ids = [r.sid for r in self.rows if r.checked]
        return [s for s in (p.source(i) for i in ids) if s is not None and s.frames]

    def _step_prep(self):
        """쓰는 클립 프록시 → 전환 미리보기(파일로만) → 첫 화면. [취소] = 기다리지 않고 편집 화면."""
        self._step = "prep"
        st = self.state
        srcs = self._prep_sources()
        if st.defer_proxy:
            st.defer_proxy = False
        for s in srcs:
            if st.status.get(s.id) == "읽음":
                st._queue_proxy(s)
            else:
                st.ensure_proxy(s)
        self._prep_srcs = srcs
        self._show("prep", 0.0, f"프록시 0/{len(srcs)}")
        self._prep_timer = QTimer(self)
        self._prep_timer.setInterval(250)
        self._prep_timer.timeout.connect(self._prep_tick)
        self._prep_timer.start()
        self._prep_tick()

    def _prep_tick(self):
        if self._step != "prep":
            return
        st = self.state
        srcs = self._prep_srcs
        n = max(1, len(srcs))
        done = [s for s in srcs if st.proxy_ready(s) or st.status.get(s.id) in SG.ERRORS]
        frac = (len(done) + sum(st.proxy_pct.get(s.id, 0.0) for s in srcs if s not in done)) / n
        self._show("prep", 0.7 * frac, f"프록시 {len(done)}/{len(srcs)}")
        if len(done) < len(srcs):
            return
        self._prep_timer.stop()
        self._step = "prep2"

        def prog(i, n2):
            if self._step == "prep2":
                self._show("prep", 0.7 + 0.3 * (i / max(1, n2)), f"전환 {i}/{n2}")
        self.edit.prep_transitions(prog, self._prep_done)

    def _prep_done(self):
        if self._step != "prep2":
            return
        self._show("prep", 1.0)
        self.set_running(False)
        self._to_editor()

    def _to_editor(self):
        """편집 화면으로(프록시는 이제부터 · 타임라인이 있으면 타임라인 첫 화면)."""
        self.state.resume_proxies()
        self.outcome = "edit"
        if self.from_edit:
            solo.leave(self)
        self.accept()                                    # 연 쪽(시작 창·편집 창)이 편집 화면을 보인 뒤 ed.after_auto()

    # ---------------------------------------------------------------- 취소 · 실패
    def _stop_jobs(self):
        for j in self.jobs:
            j.cancel.set()
            jobs.AUTO_POOL.tryTake(j)
        self.jobs = []
        for r in self.rows:
            if r.result is None:
                r.prog, r.running = 0.0, False
        self.state.clear_work("analyze", set(self.row_by))

    def _back(self, text: str = ""):
        """작업을 멈추고 설정 화면으로(값·편집 결과는 그대로 — 실행취소로 되돌림)."""
        self.armed = False
        self.set_running(False)
        if self.from_edit:
            solo.leave(self, keep_dialog=True)
        self.state_lab.setText(text)
        self.state_lab.setStyleSheet("color:#d9a646;")

    def _fail(self, text: str):
        ff.log_error("자동 창", text)
        self._stop_jobs()
        self._back(text)

    def cancel(self):
        if not self.running:
            self._cancel_close()
            return
        self._cancelled = True
        step = self._step
        if step == "grade":
            self._stop_jobs()
            self._back("취소됨")
        elif step in ("edit", "music"):
            j = self._job
            if j is not None:
                j.cancel.set()
            self._back("취소됨")
        elif step == "render":
            self.b_cancel.setEnabled(False)
            self._say("취소 중…", "render")
            rp = self.edit.render_panel
            if rp.running:
                rp.cancel_all()
            else:
                self._r_disconnect()
                self._back("렌더 취소")
        elif step in ("prep", "prep2"):                    # 준비 취소 = 기다리지 않고 편집 화면(값 유지, 프록시는 계속)
            if getattr(self, "_prep_timer", None) is not None:
                self._prep_timer.stop()
            self.edit.prep_transitions_cancel()
            self.set_running(False)
            self._to_editor()
        else:
            j = self._job
            if j is not None:
                j.cancel.set()
            self._back("취소됨")

    def _cancel_close(self):
        """작업 중이 아닐 때 [취소]: 시작 창에서 연 것 = 넣은 영상 버림 / 편집 창에서 연 것 = 닫기만."""
        self._save_config()
        self._stop_jobs()
        self.outcome = ""
        self.reject()

    def reject(self):
        if self.running:                                   # Esc = 작업 중에는 안 닫힘
            return
        super().reject()

    def closeEvent(self, e):
        if self.running:
            e.ignore()
            self.showMinimized()
            return
        super().closeEvent(e)

    def _closed(self, _r):
        for sig, fn in ((self.state.sourceStatus, self._src_status), (self.state.workChanged, self._work_changed),
                        (self.state.changed, self._state_changed)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass
        self.state.clear_work("analyze", set(self.row_by))
        self._refill.stop()
