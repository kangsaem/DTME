"""자동 편집 창(v0.16.68): 고른 소스에서 하이라이트를 골라 정한 길이로 타임라인을 채움(작업 = ui_edit.run_autoedit · autoedit.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
                               QSlider, QStyledItemDelegate, QVBoxLayout, QWidget)

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
        self.title_on = QCheckBox("클립마다 글자 + 사각형")
        self.title_on.setChecked(True)
        self.music_on = QCheckBox("음악 자동")              # 켜면 컷을 마디에 맞추는 것까지(따로 옵션 없음)
        self.music_on.setChecked(bool(p.audios))
        self.music_on.setEnabled(bool(p.audios))
        self.grade_on = QCheckBox("보정 안 된 소스는 AUTO 먼저")   # AUTO 했거나 손으로 보정한 소스는 건너뜀
        self.grade_on.setChecked(True)
        self.full = full                                   # v0.16.81 [전부 자동] 팝업: 보정은 AUTO 창 값 → 보정 칸 대신 프로젝트 저장
        self.save_on = QCheckBox("프로젝트 저장 (영상 옆 .dtme.json — 나중에 편집 창에서 고침)")
        self.save_on.setChecked(True)

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
        for cb in (self.title_on, self.music_on, self.save_on if full else self.grade_on):
            right.addLayout(labeled("", cb))
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
        self.state_lab.setStyleSheet(f"color:{SUB};")
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
        v.addWidget(self.bar)
        v.addLayout(bot)
        self.resize(940, 420)
        self._sum()

    def _toggle(self, it):
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
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

    def settings(self) -> dict:
        return {"sids": self.chosen(), "minutes": int(self.length.value()), "title": self.title_on.isChecked(),
                "music": self.music_on.isChecked(), "grade": self.grade_on.isChecked() and not self.full,
                "save": self.full and self.save_on.isChecked()}

    def set_running(self, on: bool):
        self.b_start.setEnabled(not on)
        self.list.setEnabled(not on)
        for w in (self.length, self.title_on, self.music_on, self.grade_on, self.save_on):
            w.setEnabled(not on and (w is not self.music_on or bool(self.state.project.audios)))
        if on:
            self.set_progress(0.0, "")
        else:
            self._job = None

    def set_progress(self, v: float, text: str = ""):
        self.bar.setValue(int(v * 100))
        self.state_lab.setText(text)

    def _cancel(self):
        if self._job is not None:
            self._job.cancel.set()
        self.reject()
