"""렌더 작업 창(v0.16.91 A안, 사용자 11/14): [렌더] 누르면 편집 창 숨김 · 재생·미리보기 멈춤 → 이 창만(작업 표시줄 DTME).
항목마다 줄(이름 · 지금 단계 + 가는 선 2px — v0.17.1 자동 창 작업 팝업과 같은 모양) + 전체 막대 한 줄 · 남은 시간 · 저장폴더 · [취소] · [−].
끝·취소 = 편집 창으로."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import solo
from .stage import STAGE
from .ui_auto import Grip, main_button
from .ui_render import DragMove, file_name, out_dir

BG, FG, _N = STAGE["render"]


class ItemRow(QWidget):
    """렌더 파일 한 줄(v0.17.1, 사용자 11/17): 이름 · 상태 글자 + 아래 가는 선(2px) — 두꺼운 줄(26px 채움) 없앰. 자동 창 작업 팝업도 같은 줄."""
    LINE = 2

    def __init__(self, name):
        super().__init__()
        self.name, self.v, self.text, self.done = name, 0.0, "대기", False
        self.setFixedHeight(26)

    def set(self, v, text, done=False):
        self.v, self.text, self.done = v, text, done
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        tr = r.adjusted(2, 0, -2, -self.LINE - 3)
        f = p.font()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#9a9a9a" if self.done else "#ffffff"))
        p.drawText(tr.adjusted(0, 0, -110, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.name, Qt.ElideMiddle, int(tr.width() - 110)))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#9a9a9a" if self.done else FG))
        p.drawText(tr, Qt.AlignVCenter | Qt.AlignRight, self.text)
        p.setPen(Qt.NoPen)
        y = r.bottom() - self.LINE - 1
        p.fillRect(QRectF(0, y, r.width(), self.LINE), QColor("#333333"))
        if self.v > 0:
            p.fillRect(QRectF(0, y, r.width() * min(1.0, self.v), self.LINE), QColor("#6a6a6a" if self.done else FG))
        p.end()


_Row = ItemRow


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
