"""자동 편집 창(v0.16.68): 고른 소스에서 하이라이트를 골라 정한 길이로 타임라인을 채움(작업 = ui_edit.run_autoedit · autoedit.py)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QSlider, QStyledItemDelegate, QVBoxLayout, QWidget)

from .project import display_name
from .ui_auto import RED_BTN, SUB, Grip, labeled, main_button, preset_name
from .ui_render import DragMove

class _RowDelegate(QStyledItemDelegate):
    """[✓] 이름 ······ 길이 · 장면 · 하이라이트 n"""

    def paint(self, p: QPainter, opt, idx):
        p.save()
        r = opt.rect.adjusted(2, 2, -2, -2)
        cs = idx.data(Qt.CheckStateRole)
        on = cs in (Qt.Checked, 2) or getattr(cs, "value", cs) == 2
        p.fillRect(r, QColor("#2b3a4a" if on else "#232323"))
        bx = r.left() + 8
        by = r.center().y() - 7
        p.setPen(QColor("#9ab"))
        p.drawRect(bx, by, 14, 14)
        if on:
            p.fillRect(bx + 3, by + 3, 9, 9, QColor("#5aa0e6"))
        p.setPen(QColor("#e6e6e6" if on else "#8a8a8a"))
        p.drawText(r.adjusted(32, 0, -170, 0), Qt.AlignVCenter | Qt.AlignLeft, idx.data(Qt.DisplayRole))
        p.setPen(QColor(SUB if on else "#777"))
        p.drawText(r.adjusted(0, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, idx.data(Qt.UserRole + 1) or "")
        p.restore()

    def sizeHint(self, opt, idx):
        s = super().sizeHint(opt, idx)
        s.setHeight(30)
        return s


class StageBar(QWidget):
    """[전부 자동](v0.16.82) 막대 하나: 단계마다 그 단계 색으로 왼쪽부터 다시 차오름(앞 단계 색 = 꽉 찬 채로 아래에).
    위 = 단계 이름(끝남 ✓ · 지금 = 굵게), 오른쪽 = 'n/4 단계 글자'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from . import stage as SG
        self.steps = SG.FULL_STEPS
        self.k, self.v, self.text = 0, 0.0, ""
        self.setFixedHeight(34)

    def set(self, kind: str, v: float, text: str = ""):
        k = next((i for i, (x, _n) in enumerate(self.steps) if x == kind), self.k)
        self.k, self.v, self.text = max(self.k, k), max(0.0, min(1.0, v)), text
        self.update()

    def paintEvent(self, _e):
        from PySide6.QtGui import QFont
        from . import stage as SG
        p = QPainter(self)
        f = QFont(self.font())
        x = 0
        for i, (kind, name) in enumerate(self.steps):
            col = SG.STAGE[kind][1] if i <= self.k else "#5a5a5a"
            f.setBold(i == self.k)
            p.setFont(f)
            p.setPen(QColor(col))
            t = ("✓ " if i < self.k else "") + name
            p.drawText(x, 0, 90, 20, Qt.AlignLeft | Qt.AlignVCenter, t)
            x += 78
        kind, name = self.steps[self.k]
        lab = f"{self.k + 1}/{len(self.steps)} {name}" + (f" · {self.text}" if self.text else f" {int(self.v * 100)}%")
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(SG.STAGE[kind][1]))
        p.drawText(0, 0, self.width(), 20, Qt.AlignRight | Qt.AlignVCenter, lab)
        y, h, w = 28, 6, self.width()               # v0.16.83 다른 진행 막대와 같은 6px · 둥근 끝 3
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        def bar(width, col):
            if width > 0:
                p.setBrush(QColor(col))
                p.drawRoundedRect(0, y, width, h, 3, 3)
        bar(w, "#2a2a2a")
        if self.k > 0:
            bar(w, SG.STAGE[self.steps[self.k - 1][0]][1])
        bar(int(w * self.v), SG.STAGE[kind][1])
        p.end()


class AutoEditDialog(DragMove, QDialog):
    startRequested = Signal(dict)

    def __init__(self, state, sids, parent=None, full: bool = False):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.state = state
        self.setModal(True)
        self.setObjectName("AutoEditDialog")
        self.setStyleSheet("#AutoEditDialog{background:#262626; border:1px solid #555; border-radius:6px;}")
        p = state.project
        # 왼쪽: 소스(고른 것 = 체크)
        self.list = QListWidget()
        self.list.setItemDelegate(_RowDelegate(self))
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setStyleSheet("QListWidget{background:#1e1e1e; border:1px solid #333; border-radius:3px; padding:4px;}")
        tot = 0.0
        for s in p.sources:
            sec = s.frames / float(s.fps) if s.frames else 0.0
            it = QListWidgetItem(display_name(s.path))
            it.setData(Qt.UserRole, s.id)
            sc = preset_name(s.auto) if (s.auto or {}).get("preset") else ""
            it.setData(Qt.UserRole + 1, "  ·  ".join(x for x in (f"{int(sec // 60)}:{int(sec % 60):02d}", sc) if x))
            it.setCheckState(Qt.Checked if s.id in sids else Qt.Unchecked)
            self.list.addItem(it)
            if s.id in sids:
                tot += sec
        self.list.itemClicked.connect(self._toggle)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence.SelectAll, self, activated=self.check_all)      # v0.16.91 Ctrl+A = 전부 체크
        self.sum = QLabel("")
        self.sum.setStyleSheet(f"color:{SUB};")
        lv = QVBoxLayout()
        lv.setSpacing(6)
        lv.addWidget(self.list, 1)
        lv.addWidget(self.sum)
        # 오른쪽: 설정(사용자 2026-11-13: 컷 길이 · 순서 · 전환 · 글자 모양은 버튼 없이 자동)
        self.length = QSlider(Qt.Horizontal)
        self.length.setRange(1, 10)
        self.length.setValue(3)
        self.length.setFocusPolicy(Qt.NoFocus)
        self.len_v = QLabel("3분")
        self.len_v.setFixedWidth(40)
        self.length.valueChanged.connect(lambda v: (self.len_v.setText(f"{v}분"), self._sum()))
        len_row = QHBoxLayout()
        len_row.setSpacing(10)
        len_row.addWidget(self.length, 1)
        len_row.addWidget(self.len_v)
        self.title_on = QCheckBox("날짜 바")
        self.title_on.setChecked(True)
        n_def = 0 if p.audios else len(state.default_music())   # v0.16.91 곡이 없으면 기본 음악(CC0)
        self.music_on = QCheckBox("음악 자동" + (f" (기본 음악 {n_def}곡)" if n_def else ""))   # 켜면 컷을 마디에 맞추는 것까지
        self.music_on.setChecked(bool(p.audios) or bool(n_def))
        self.music_on.setEnabled(bool(p.audios) or bool(n_def))
        self.grade_on = QCheckBox("보정 안 된 소스는 AUTO 먼저")   # AUTO 했거나 손으로 보정한 소스는 건너뜀
        self.grade_on.setChecked(True)
        self.full = full                                   # v0.16.81 [전부 자동] 팝업: 보정은 AUTO 창 값 → 보정 칸 대신 프로젝트 저장
        self.save_on = QCheckBox("프로젝트 저장 (영상 옆 .dtme.json — 나중에 편집 창에서 고침)")
        self.save_on.setChecked(True)
        self.dive_on = QCheckBox("")                       # v0.16.84 수심 그래프(다이빙 기록이 있을 때) — 켜면 컷 최소 10초
        self._dive_label()
        self.dive_on.setChecked(bool(p.dives) and p.dive_on)
        self.setAcceptDrops(True)                          # 이 창에 FIT·DTMD 파일을 끌어다 놓아도 됨

        def line():
            f = QFrame()
            f.setFrameShape(QFrame.HLine)
            f.setStyleSheet("color:#3a3a3a;")
            return f
        right = QVBoxLayout()
        right.setSpacing(14)
        right.setContentsMargins(9, 4, 9, 9)
        right.addLayout(labeled("전체 길이", len_row))
        right.addWidget(line())
        for cb in (self.title_on, self.music_on, self.dive_on, self.save_on if full else self.grade_on):
            right.addLayout(labeled("", cb))
        right.addWidget(line())
        # v0.16.91 시작·끝 화면 [자동 | 스틸 고르기 | 없음] · 지명 · 끝 문구 (설명 글 없음)
        self.card = {}
        for key, name in (("start", "시작 화면"), ("end", "끝 화면")):
            right.addLayout(labeled(name, self._card_row(key)))
        self.place = QLineEdit()
        self.place.setPlaceholderText("지명")
        self.place.textEdited.connect(lambda _t: setattr(self, "_place_auto", False))
        self._place_auto = True
        right.addLayout(labeled("지명", self.place))
        self.end_text = QLineEdit()
        self.end_text.setPlaceholderText("")
        right.addLayout(labeled("끝 문구", self.end_text))
        self.dive_on.toggled.connect(lambda _v: self._end_hint())
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(520)
        mid = QHBoxLayout()
        mid.setSpacing(16)
        mid.addLayout(lv, 1)
        mid.addWidget(rw)
        # 아래
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.state_lab = QLabel("")
        from . import stage as SG
        self.state_lab.setStyleSheet(f"color:{SG.STAGE['edit'][1]};")       # v0.16.82 편집 = 보라(단계 색 통일)
        self.bar.setStyleSheet("QProgressBar{background:#2a2a2a; border:none; border-radius:3px;}"
                               f"QProgressBar::chunk{{background:{SG.STAGE['edit'][1]}; border-radius:3px;}}")
        self.stage_bar = StageBar() if full else None
        self.b_cancel = main_button("취소")
        self.b_cancel.clicked.connect(self._cancel)
        self._job = None
        self.b_start = main_button("전부 자동" if full else "자동 편집", RED_BTN, 100)
        self.b_start.clicked.connect(lambda: self.startRequested.emit(self.settings()))
        bot = QHBoxLayout()
        bot.addWidget(self.state_lab, 1)
        bot.addWidget(self.b_cancel)
        bot.addWidget(self.b_start)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        title = QLabel("전부 자동 — 보정 → 편집 → 음악 → 렌더" if full else "자동 편집")
        title.setStyleSheet("font-weight:bold; font-size:14px;")
        top.addWidget(title)
        top.addWidget(Grip(), 1)
        from .solo import min_button
        self.b_min = min_button(self)                     # v0.16.74 작업 중 [−] = 내림(작업 표시줄 DTME 아이콘)
        top.addWidget(self.b_min)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(10)
        v.addLayout(top)
        v.addLayout(mid, 1)
        if self.stage_bar is not None:                     # 전부 자동 = 단계 막대 하나(보통 막대·글자 대신)
            self.bar.setVisible(False)
            v.addWidget(self.stage_bar)
        else:
            v.addWidget(self.bar)
        v.addLayout(bot)
        self.resize(940, 560)
        self._sum()

    def _card_row(self, key):
        h = QHBoxLayout()
        h.setSpacing(0)
        grp = QButtonGroup(self)
        for j, (k, n) in enumerate((("auto", "자동"), ("pick", "스틸 고르기"), ("none", "없음"))):
            b = QPushButton(n)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty("key", k)
            b.setChecked(k == "auto")
            grp.addButton(b, j)
            h.addWidget(b, 1)
        grp.buttonClicked.connect(lambda b, key=key: self._card_click(key, b))
        self.card[key] = {"grp": grp, "mode": "auto", "img": ""}
        return h

    def _card_click(self, key, b):
        c = self.card[key]
        k = b.property("key")
        if k == "pick":
            f, _ = QFileDialog.getOpenFileName(self, "스틸 고르기", os.path.dirname(c["img"]) if c["img"] else "",
                                               "그림 (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
            if not f:
                for x in c["grp"].buttons():
                    x.setChecked(x.property("key") == c["mode"])
                return
            c["img"] = f
            b.setToolTip(f)
        c["mode"] = k
        self._end_hint()

    def card_mode(self, key, mode, img=""):
        """(시험·밖에서) 시작·끝 화면 고르기."""
        c = self.card[key]
        c["mode"], c["img"] = mode, img or c["img"]
        for x in c["grp"].buttons():
            x.setChecked(x.property("key") == mode)
        self._end_hint()

    def _span(self):
        """고른 소스 촬영 기간(현지 초) (처음, 끝) — 이름·파일 시각."""
        from .dive_draw import shot_time
        p = self.state.project
        ids = set(self.chosen())
        ts = []
        for s in p.sources:
            if s.id in ids:
                t = shot_time(s)
                if t is not None:
                    ts += [t, t + (s.frames / float(s.fps) if s.frames and s.fps else 0.0)]
        return (min(ts), max(ts)) if ts else (None, None)

    def _end_hint(self):
        """지명(직접 안 고쳤으면 다이빙 메모 '위치:' 에서) · 끝 문구 자리 글(자동 문구)."""
        from . import autoedit
        p = self.state.project
        a, b = self._span()
        if getattr(self, "_place_auto", True) and hasattr(self, "place"):
            self.place.setText(autoedit.place_of(p.dives, a, b))
        if hasattr(self, "end_text"):
            ds = autoedit.period_dives(p.dives, a, b) if self.dive_on.isChecked() else []
            ls = autoedit.end_lines(bool(ds), ds, self.place.text().strip(), autoedit.period_text(a, b))
            self.end_text.setPlaceholderText(" / ".join(x[0] for x in ls))

    def check_all(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked)
        self._sum()

    def _toggle(self, it):
        """클릭 = 하나 켜고 끄기 · Shift+클릭 = 지난번 누른 줄부터 여기까지 같은 상태로(v0.16.91)."""
        from PySide6.QtWidgets import QApplication
        i = self.list.row(it)
        anc = getattr(self, "_anchor", None)
        if QApplication.keyboardModifiers() & Qt.ShiftModifier and anc is not None:
            st = Qt.Checked if anc[1] else Qt.Unchecked
            for k in range(min(anc[0], i), max(anc[0], i) + 1):
                self.list.item(k).setCheckState(st)
        else:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
            self._anchor = (i, it.checkState() == Qt.Checked)
        self._sum()

    def chosen(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]

    def _sum(self):
        p = self.state.project
        ids = set(self.chosen())
        sec = sum(s.frames / float(s.fps) for s in p.sources if s.id in ids and s.frames)
        want = int(self.length.value()) * 60
        tip = "  (원본이 더 짧음 → 원본 길이까지)" if sec and sec < want else ""
        self.sum.setText(f"{len(ids)}개 · 원본 {int(sec // 60)}분 {int(sec % 60):02d}초 → {want // 60}분{tip}")
        self._end_hint()

    def settings(self) -> dict:
        return {"sids": self.chosen(), "minutes": int(self.length.value()), "title": self.title_on.isChecked(),
                "music": self.music_on.isChecked(), "grade": self.grade_on.isChecked() and not self.full,
                "save": self.full and self.save_on.isChecked(),
                "dive": self.dive_on.isChecked() and bool(self.state.project.dives),
                "start": self.card["start"]["mode"], "start_img": self.card["start"]["img"],
                "end": self.card["end"]["mode"], "end_img": self.card["end"]["img"],
                "place": self.place.text().strip(), "end_text": self.end_text.text().strip()}

    def _dive_label(self):
        n = len(self.state.project.dives)
        self.dive_on.setText(f"LOG 수심 그래프 (다이빙 {n}개 · 컷 최소 15초)" if n else
                             "LOG 수심 그래프 (다이빙 기록 없음 — FIT·DTMD 파일을 이 창에 끌어다 놓기)")
        self.dive_on.setEnabled(bool(n))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        """v0.16.84 다이빙 기록(FIT · DTMD zip/json) 끌어다 놓기 → 수심 그래프 켬."""
        from .divelog import is_dive_file
        fs = [u.toLocalFile() for u in e.mimeData().urls()]
        dv = [f for f in fs if os.path.isfile(f) and os.path.splitext(f)[1].lower() in (".fit", ".zip", ".json") and is_dive_file(f)]
        if dv:
            self.state.import_dives(dv)
            self._dive_label()
            self.dive_on.setChecked(bool(self.state.project.dives))
            self._end_hint()

    def set_running(self, on: bool):
        self.b_start.setEnabled(not on)
        self.list.setEnabled(not on)
        for w in (self.length, self.title_on, self.music_on, self.grade_on, self.save_on, self.dive_on, self.place, self.end_text):
            w.setEnabled(not on and (w is not self.music_on or bool(self.state.project.audios) or bool(self.state.default_music())))
        for c in self.card.values():
            for b in c["grp"].buttons():
                b.setEnabled(not on)
        if on:
            self.set_progress(0.0, "")
        else:
            self._job = None

    def set_progress(self, v: float, text: str = ""):
        self.bar.setValue(int(v * 100))
        if self.stage_bar is None:
            self.state_lab.setText(text)
        if self.stage_bar is not None and self.stage_bar.k in (1, 2):     # 전부 자동 편집 중: '음악' 단계 글자 = 음악 단계
            if text.startswith("음악"):
                self.stage_bar.set("music", 0.5)
            elif text.startswith("실패"):
                self.stage_bar.set(self.stage_bar.steps[self.stage_bar.k][0], self.stage_bar.v, text)
            else:
                self.stage_bar.set("edit", v)

    def set_stage(self, kind: str, v: float, text: str = ""):
        if self.stage_bar is not None:
            self.stage_bar.set(kind, v, text)

    on_cancel = None                                      # 전부 자동: 밖(EditTab)에서 단계별 멈춤

    def _cancel(self):
        if self._job is not None:
            self._job.cancel.set()
        if self.on_cancel is not None:
            self.on_cancel()
        self.reject()
