"""렌더 작업 창(v0.16.91 A안, 사용자 11/14): [렌더] 누르면 편집 창 숨김 · 재생·미리보기 멈춤 → 이 창만(작업 표시줄 DTME).
항목마다 줄(이름 · 지금 단계 · 진행) + 전체 막대 · 남은 시간 · 저장폴더 · [취소] · [−]. 끝·취소 = 편집 창으로."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import solo
from .stage import STAGE
from .ui_auto import Grip, main_button
from .ui_render import DragMove, file_name, out_dir

BG, FG, _N = STAGE["render"]


class _Row(QWidget):
    def __init__(self, name):
        super().__init__()
        self.name, self.v, self.text, self.done = name, 0.0, "대기", False
        self.setFixedHeight(26)

    def set(self, v, text, done=False):
        self.v, self.text, self.done = v, text, done
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2e2e2e"))
        p.drawRoundedRect(r, 3, 3)
        if self.v > 0:
            p.setBrush(QColor(BG))
            p.drawRoundedRect(QRectF(r.left(), r.top(), r.width() * min(1.0, self.v), r.height()), 3, 3)
        f = p.font()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(r.adjusted(10, 0, -150, 0), Qt.AlignVCenter | Qt.AlignLeft, self.name)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#9a9a9a" if self.done else FG))
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, self.text)
        p.end()


class _Bar(QWidget):
    def __init__(self):
        super().__init__()
        self.v = 0.0
        self.setFixedHeight(6)

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2a2a"))
        p.drawRoundedRect(r, 3, 3)
        p.setBrush(QColor(FG))
        p.drawRoundedRect(QRectF(0, 0, r.width() * max(0.0, min(1.0, self.v)), r.height()), 3, 3)
        p.end()


class RenderWindow(DragMove, QDialog):
    def __init__(self, rp, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.rp = rp
        self.setObjectName("RenderWin")
        self.setStyleSheet("#RenderWin{background:#262626; border:1px solid #555; border-radius:6px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(10)
        top = QHBoxLayout()
        t = QLabel("렌더")
        t.setStyleSheet("font-weight:bold; font-size:14px;")
        top.addWidget(t)
        top.addWidget(Grip(), 1)
        self.b_min = solo.min_button(self)
        top.addWidget(self.b_min)
        v.addLayout(top)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(5)
        v.addLayout(self.rows_box)
        self.bar = _Bar()
        v.addWidget(self.bar)
        bot = QHBoxLayout()
        self.lab = QLabel("")
        self.lab.setStyleSheet(f"color:{FG};")
        bot.addWidget(self.lab, 1)
        self.b_cancel = main_button("취소")
        self.b_cancel.clicked.connect(self._cancel)
        bot.addWidget(self.b_cancel)
        v.addLayout(bot)
        self.rows = {}
        for it in rp.run_items:
            r = _Row(f"{file_name(rp.state.project, it)}.mp4")
            self.rows[it.id] = r
            self.rows_box.addWidget(r)
        self.folder = str(out_dir(rp.state.project))
        rp.itemProgress.connect(self._item)
        rp.runProgress.connect(self._overall)
        self.resize(640, 120 + 31 * len(self.rows))
        self._item("", 0.0, True)

    def _item(self, _iid, _v, _more):
        rp = self.rp
        for iid, row in self.rows.items():
            st = rp.status.get(iid, "")
            if st.startswith("완료"):
                row.set(1.0, "완료", True)
            elif st.startswith("실패"):
                row.set(1.0, "실패", True)
            elif st == "취소":
                row.set(0.0, "취소", True)
            elif iid in rp.active:
                stage = rp.stage.get(iid, "")
                pv = rp.progress.get(iid, 0.0)
                row.set(pv, f"인코딩 {int(pv * 100)}%" if stage == "인코딩" else (stage or "준비"))
            else:
                row.set(0.0, "대기")

    def _overall(self, frac, text, _bad):
        self.bar.v = frac
        self.bar.update()
        self.lab.setText(f"{text}   ·   {self.folder}")

    def _cancel(self):
        self.b_cancel.setEnabled(False)
        self.lab.setText("취소 중…")
        self.rp.cancel_all()

    def finish(self):
        for sig, fn in ((self.rp.itemProgress, self._item), (self.rp.runProgress, self._overall)):
            try:
                sig.disconnect(fn)
            except (RuntimeError, TypeError):
                pass
        solo.leave(self)
        self.close()
        self.deleteLater()
