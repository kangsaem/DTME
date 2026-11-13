"""렌더 리스트(편집 화면 오른쪽) + 렌더 설정 탭."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QListWidget,
                               QListWidgetItem, QStyle, QStyledItemDelegate,
                               QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import ff, jobs
from .project import short_name, spaced

ORIENT_TXT = {"horizontal": "가로", "horizontal1440": "가로 1440", "horizontal2160": "가로 4K", "vertical": "세로",
              "vertical1440": "세로 1440", "vertical2160": "세로 4K"}


from . import ui_style  # noqa: E402  버튼 모양은 ui_style 한 곳에서
BTN_W, BTN_H = 76, 28          # 모든 일반 버튼
MAIN_W, MAIN_H = 88, 32        # 주요 버튼: ▶/❚❚ · ▼ · 렌더리스트로 · 렌더
ADD_W, ADD_H = BTN_W, BTN_H    # 영상 추가 · 삭제(소스)


class DragMove:
    """테두리 없는 창: 빈 바탕을 잡고 끌면 창이 움직임(버튼·목록·입력란 위는 원래 동작)."""
    _drag_off = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_off is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_off)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_off = None
        super().mouseReleaseEvent(e)


class Popup(DragMove, QDialog):
    """모든 팝업 공통(v0.16.19, 사용자 확정): 제목줄·제목 글자 없음 = MOSCO 확인 창 모양
    (진회색 #262626 · 테두리 #555 · 둥근 6 · 빈 바탕 끌어 이동 · 오른쪽 아래 버튼). floating = 떠 있는 창(Tool, 열린 채로 다른 조작 가능)."""
    accepted_ = Signal()
    rejected_ = Signal()

    def __init__(self, parent=None, floating: bool = False):
        flags = (Qt.Tool if floating else Qt.Dialog) | Qt.FramelessWindowHint
        super().__init__(parent, flags)
        self.setModal(not floating)
        self.setObjectName("Popup")
        self.setStyleSheet("#Popup{background:#262626; border:1px solid #555; border-radius:6px;}")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)

    def add_buttons(self, ok: str | None = "확인", cancel: str = "취소"):
        """오른쪽 아래 [취소][확인(파랑)] — ok=None 이면 [취소]만."""
        br = QHBoxLayout()
        br.addStretch(1)
        self.b_cancel = QPushButton(cancel)
        fix_size(self.b_cancel, main=True)
        self.b_cancel.setFocusPolicy(Qt.NoFocus)
        self.b_cancel.clicked.connect(self.reject)
        br.addWidget(self.b_cancel)
        self.b_ok = None
        if ok:
            self.b_ok = QPushButton(ok)
            fix_size(self.b_ok, main=True)
            self.b_ok.setFocusPolicy(Qt.NoFocus)
            ui_style.tone(self.b_ok, "blue")
            self.b_ok.clicked.connect(self.accept)
            br.addWidget(self.b_ok)
        self.body.addLayout(br)

    def center_on(self, w):
        self.adjustSize()
        if w is not None and w.window().isVisible():
            c = w.window().geometry().center()
            self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)

    def accept(self):
        super().accept()
        self.accepted_.emit()

    def reject(self):
        super().reject()
        self.rejected_.emit()


class ProgressButton(QPushButton):
    """렌더 버튼(v0.16.31): 렌더 중 = 전체 진행 막대(왼쪽부터 빨강, 글자 '3/35 · 42%'). frac None = 보통 버튼."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.frac = None
        self.ptext = ""
        self.bad = False

    def set_progress(self, frac, text="", bad=False):
        self.frac, self.ptext, self.bad = frac, text, bad
        self.update()

    def paintEvent(self, e):
        if self.frac is None:
            return super().paintEvent(e)
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#4a1f1b"))
        p.drawRoundedRect(r, 4, 4)
        w = int(r.width() * max(0.0, min(1.0, self.frac)))
        if w > 0:
            p.setBrush(QColor("#8e2a20" if self.bad else "#c0392b"))
            p.drawRoundedRect(r.adjusted(0, 0, w - r.width(), 0), 4, 4)
        f = self.font()
        f.setBold(True)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignCenter, self.ptext)
        p.end()


def fix_size(b, main=False):
    """주요 버튼 = 고정 88×32. 일반 버튼 = 높이 28, 폭 56~76(자리가 모자라면 줄어듦 → 노트북에서 겹치지 않음)."""
    if main:
        b.setFixedSize(MAIN_W, MAIN_H)
    else:
        b.setFixedHeight(BTN_H)
        b.setMinimumWidth(56)
        b.setMaximumWidth(BTN_W)
        from PySide6.QtWidgets import QSizePolicy
        b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return b


def arrow_icon(w=34, h=18, color="#ffffff"):
    """두께 있는 오른쪽 화살표(블록 화살표)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QIcon, QPainter, QPixmap, QPolygonF
    pm = QPixmap(w * 2, h * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    W, H = w * 2, h * 2
    shaft_h, head_w = H * 0.46, W * 0.42
    p.drawPolygon(QPolygonF([QPointF(0, (H - shaft_h) / 2), QPointF(W - head_w, (H - shaft_h) / 2),
                             QPointF(W - head_w, 0), QPointF(W, H / 2), QPointF(W - head_w, H),
                             QPointF(W - head_w, (H + shaft_h) / 2), QPointF(0, (H + shaft_h) / 2)]))
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def render_list_button(fn, tip=""):
    from PySide6.QtCore import QSize
    b = QPushButton()
    b.setIcon(arrow_icon())
    b.setIconSize(QSize(24, 13))      # 화살표 20% 축소
    b.setFixedSize(MAIN_W, MAIN_H)
    b.setFocusPolicy(Qt.NoFocus)
    ui_style.tone(b, "red")
    if tip:
        b.setToolTip(tip)
    b.clicked.connect(fn)
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


def unique(path: Path, taken=()) -> Path:
    """있는 파일·taken(동시 렌더가 잡아 둔 이름)과 겹치지 않는 이름."""
    if not path.exists() and path not in taken:
        return path
    i = 2
    while (q := path.with_name(f"{path.stem}_{i}{path.suffix}")).exists() or q in taken:
        i += 1
    return q


def item_base(project, segs) -> str:
    """첫 컷 소스의 날짜·시간."""
    s = project.source(segs[0].src) if segs else None
    return short_name(s.path) if s else "DTME"


def open_file(path):
    import os
    import subprocess
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])


def remove_later(path) -> None:
    """만들다 만 파일 지우기. Windows 는 막 끈 ffmpeg 가 파일을 잠깐 더 잡고 있음(WinError 32) → 뒤에서 몇 초 다시 시도."""
    import threading

    def go():
        for _ in range(50):
            try:
                Path(path).unlink(missing_ok=True)
                return
            except OSError:
                time.sleep(0.2)
    threading.Thread(target=go, daemon=True).start()


def ask_quality(parent, state, items=None) -> bool:
    """v0.16.80 [렌더] 누르는 순간 용량 고르기 [고화질|보통|작게] → 그다음 저장폴더. 취소 = False.
    items = 렌더할 항목(예상 크기 = 길이 × 평균 목표, 없으면 1분당). 고른 값 = 다음에도 기본(빨강)."""
    import os
    from .project import get_setting, set_setting
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and not os.environ.get("DTME_ASK_QUALITY"):
        return True                                   # 화면 없는 시험 = 묻지 않음(지금 값 그대로)
    o = state.project.output
    last = get_setting("last_quality", "") or o.quality or "normal"
    p = state.project
    secs, ori = 0.0, "horizontal"
    for it in items or []:
        for g in it.segs:
            src = p.source(g.src)
            if src is not None and src.fps:
                secs += g.frames / float(src.fps) / max(0.01, g.speed)
        ori = it.orientation
    lines = []
    for k in ("high", "normal", "small"):
        mb = ff.est_mb(k, secs if secs else 60.0, ori)
        lines.append(f"{ff.QUALITY[k]['label']}  약 {mb:,.0f}MB")
    head = f"렌더 용량 — {int(secs // 60)}분 {int(secs % 60)}초 예상" if secs else "렌더 용량 — 1분당 예상"
    txt = head + "\n\n" + "\n".join(lines) + "\n\n보통·작게 = GPU H.265(PC) / H.264(노트북) · 화면이 자잘하면 더 큼"
    bt = [("cancel", "취소", 72, None)] + [(k, ff.QUALITY[k]["label"], 80, "red" if k == last else None)
                                         for k in ("high", "normal", "small")]
    v = ui_style.confirm(parent, txt, bt)
    if v == "cancel":
        return False
    if o.quality != v:
        o.quality = v
        state.dirty = True
    try:
        set_setting("last_quality", v)
    except Exception:  # noqa: BLE001
        pass
    return True


def ensure_folder(parent, state) -> bool:
    """저장폴더가 비어 있으면 먼저 물어봄(취소하면 False). 고른 폴더는 다음 프로젝트에서도 처음 위치로."""
    o = state.project.output
    if o.folder.strip():
        return True
    from .project import get_setting, set_setting
    last = get_setting("last_folder", "") or ""
    start = last or (str(Path(state.project.sources[0].path).parent) if state.project.sources else "")
    d = QFileDialog.getExistingDirectory(parent, "저장폴더", start)
    if not d:
        return False
    o.folder = d
    state.dirty = True
    try:
        set_setting("last_folder", d)
    except Exception:  # noqa: BLE001
        pass
    state.changed.emit("output")
    return True


def took_text(sec: float) -> str:
    m, s_ = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return (f"{h}시간 " if h else "") + (f"{m}분 " if m or h else "") + f"{s_}초"


def show_done_popup(parent, ok: int, bad: int, sec: float, folder: str, on_close=None):
    """렌더 끝 팝업(v0.16.31·33 공용): '렌더 완료 n개 · 실패 m개 · 시간' [폴더 열기][확인]. 떠 있는 창.
    on_close = 둘 중 무엇을 눌러도 닫힐 때 부름(시작 창 = 프로그램 종료)."""
    from PySide6.QtWidgets import QLabel
    d = Popup(parent, floating=True)
    lb = QLabel(f"렌더 완료 {ok}개 · 실패 {bad}개 · {took_text(sec)}")
    lb.setStyleSheet(f"color:{'#ff8a80' if bad else '#e6e6e6'}; font-size:13px;")
    d.body.addWidget(lb)
    d.add_buttons("확인", "폴더 열기")
    done = [False]

    def close(open_folder=False):
        if done[0]:
            return
        done[0] = True
        if open_folder:
            open_file(folder)
        d.close()
        if on_close:
            on_close()
    d.b_cancel.clicked.disconnect()
    d.b_cancel.clicked.connect(lambda: close(True))
    d.b_ok.clicked.disconnect()
    d.b_ok.clicked.connect(lambda: close(False))
    d.rejected_.connect(lambda: close(False))            # Esc
    d.center_on(parent)
    d.show()
    d.raise_()
    return d


def precache_item(p, it, cancel=None):
    """렌더 항목의 원본 구간들을 미리 읽음(HDD·SD 만, ff.precache)."""
    for g in it.segs:
        src = p.source(g.src)
        if src is None or not src.frames:
            continue
        try:
            ff.precache(src.path, g.fin / src.frames, g.fout / src.frames, cancel)
        except ff.Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            ff.log_error("미리 읽기", f"{src.path}: {e}")


def free_memory():
    """렌더 시작(v0.16.26): DTME 메모리 캐시 비움(프레임 이동 캐시 · 원본 구간 캐시 · 멈춘 화면 · 보정 미리보기).
    렌더 속도와는 무관(측정) — 다른 프로그램 여유. 편집으로 돌아와 프레임을 넘기면 다시 채움."""
    import gc
    try:
        from . import framecache
        if framecache._cache is not None:
            framecache._cache.release()
        ff.range_clear()
        with ff._cache_lock:
            ff._frame_cache.clear()
        with ff._pv_memo_lock:
            ff._pv_memo.clear()
        from . import ui_edit
        with ui_edit.PREVIEW_LOCK:
            ui_edit.PREVIEW_LRU.clear()
    except Exception as e:  # noqa: BLE001
        ff.log_error("메모리 비우기", str(e))
    gc.collect()


def file_name(project, item) -> str:
    pre = project.output.prefix.strip() or "DTME"
    if pre and not pre.endswith(("_", "-", " ")):
        pre += "_"
    return f"{pre}{spaced(item.name)}"            # v0.16.26: DTMD_2026 1028 1144 (소스 목록처럼)


class RenderDelegate(QStyledItemDelegate):
    """렌더 항목 = 바. 대기 진한 회색 · 진행 중 막대 · 완료 연한 회색 · 실패 빨강."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        return QSize(option.rect.width(), 30)

    def paint(self, p, option, index):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPen
        iid = index.data(Qt.UserRole)
        st = self.panel.status.get(iid, "")
        frac = self.panel.progress.get(iid, 0.0)
        done, failed = st.startswith("완료"), st.startswith("실패")
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#6b6b6b") if done else QColor("#7a2a22") if failed else QColor("#3c3c3c"))
        p.drawRoundedRect(r, 3, 3)
        if not done and not failed and frac > 0:
            pr = QRectF(r)
            pr.setWidth(r.width() * frac)
            p.setBrush(QColor("#c0392b"))
            p.drawRoundedRect(pr, 3, 3)
        if option.state & QStyle.State_Selected:
            p.setPen(QPen(QColor("#4a8fe0"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
        p.setPen(QColor("#f2f2f2") if done else QColor("#e6e6e6"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        info = index.data(Qt.UserRole + 1) or ""
        f.setBold(False)
        p.setFont(f)
        iw = p.fontMetrics().horizontalAdvance(info)
        p.drawText(r.adjusted(10, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, info)
        if index.data(Qt.UserRole + 2):           # 보낸 뒤 클립 보정값이 바뀜 → 노란 점
            iw += 12
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#f2c94c"))
            p.drawEllipse(QRectF(r.right() - 8 - iw + 1, r.center().y() - 3, 6, 6))
            p.setPen(QColor("#f2f2f2") if done else QColor("#e6e6e6"))
        f.setBold(True)
        p.setFont(f)
        avail = int(r.width() - iw - 26)          # 이름이 길면 … (길이 글자와 겹치지 않게)
        p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, max(20, avail)))
        p.restore()


class RenderPanel(QWidget):
    """렌더 설정 + 렌더 리스트(바) + 빨간 렌더 버튼."""
    itemProgress = Signal(str, float, bool)       # (항목 id, 진행 0~1, 렌더 계속 중)
    message = Signal(str)                         # 상태줄 짧은 글
    sourcesRequested = Signal()                   # ▼ = 선택한 소스를 렌더 리스트로(EditTab 이 처리)
    runProgress = Signal(float, str, bool)        # v0.16.31 전체 진행(0~1, '3/35 · 42%', 실패 있음) — 창 제목·작업 표시줄
    runFinished = Signal(int, int, float, str)    # 완료 수, 실패 수, 걸린 초, 출력 폴더

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.status: dict[str, str] = {}
        self.progress: dict[str, float] = {}
        self.queue: list = []
        self.active: dict = {}           # 렌더 중인 항목 id → 출력 경로(코어 수만큼 동시, jobs.RENDER_N)
        self.jobs: dict = {}             # 렌더 중인 항목 id → Job(전체 취소용, v0.16.54)
        self.cancelled = False           # 이번 렌더를 [렌더] 버튼으로 멈춤
        self.running = False

        self.table = QListWidget()      # 이름은 table 유지(키 입력 필터에서 사용)
        self.table.setItemDelegate(RenderDelegate(self))
        self.table.setStyleSheet("QListWidget{background:#1a1a1a; border:none;}")
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)
        a_del = QAction("삭제", self.table)
        a_del.setShortcut(Qt.Key_Delete)
        a_del.setShortcutContext(Qt.WidgetShortcut)
        a_del.triggered.connect(self.delete_selected)
        a_re = QAction("다시 렌더", self.table)
        a_re.triggered.connect(self._requeue)
        a_now = QAction("지금 보정값으로", self.table)
        a_now.triggered.connect(self._resnap)
        self.table.addAction(a_del)
        self.table.addAction(a_re)
        self.table.addAction(a_now)

        self.b_render = ProgressButton("렌더")
        self.b_render.setFixedSize(MAIN_W, MAIN_H)
        self.b_render.setFocusPolicy(Qt.NoFocus)
        ui_style.tone(self.b_render, "red")
        self.b_render.clicked.connect(self.press)
        self.dlg = RenderSettingsDialog(state, self)
        self.settings = self.dlg.settings
        self.b_down = QPushButton("▼")             # v0.16.25: 미리보기 렌더 자리 → 소스 목록에서 선택한 것을 렌더 리스트로
        fix_size(self.b_down, main=True)
        self.b_down.setToolTip("선택한 소스 → 렌더 리스트")
        ui_style.tone(self.b_down, "navy")               # 타임라인 ▼ 와 같은 모양
        f = self.b_down.font()
        f.setPixelSize(15)
        self.b_down.setFont(f)
        self.b_down.setFocusPolicy(Qt.NoFocus)
        self.b_down.clicked.connect(self.sourcesRequested.emit)
        self.b_set = QPushButton("⚙")
        self.b_set.setFixedSize(34, MAIN_H)
        self.b_set.setToolTip("렌더 설정")
        self.b_set.setFocusPolicy(Qt.NoFocus)
        self.b_set.clicked.connect(lambda: self.dlg.open_at(self))
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.b_down)
        top.addStretch(1)
        top.addWidget(self.b_set)
        top.addWidget(self.b_render)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        self.setMinimumWidth(200)
        state.changed.connect(lambda w: w in ("render", "sources", "project", "undo", "output", "grade") and self.refresh())

    def refresh(self):
        p = self.state.project
        sel = set(self._selected_ids())
        self.table.blockSignals(True)
        self.table.clear()
        for it in p.render_items:
            ok = all(p.source(g.src) for g in it.segs)
            if it.done and it.id not in self.status:
                self.status[it.id] = f"완료 → {it.done}"
            st = self.status.get(it.id, "" if ok else "실패: 소스 없음")
            li = QListWidgetItem(file_name(p, it))
            li.setData(Qt.UserRole, it.id)
            vlen = p.segs_seconds(it.segs) + float(getattr(it, "lead", 0) or 0)       # v0.16.71 앞뒤 검은 구간 포함
            vlen += p.tail_of(it.titles, vlen) if it.titles else 0.0
            li.setData(Qt.UserRole + 1, f"{ORIENT_TXT.get(it.orientation, '')} {vlen:.1f}초"
                       + ("" if it.audio else " 무음"))
            stale = any(p.seg_stale(g) for g in it.segs)
            li.setData(Qt.UserRole + 2, stale)
            tips = [st] if st.startswith(("실패", "완료")) else []
            if stale:
                tips.append("보낸 뒤 보정값이 바뀜 — 우클릭 ‘지금 보정값으로’")
            if tips:
                li.setToolTip("\n".join(tips))
            self.table.addItem(li)
            li.setSelected(it.id in sel)
        self.table.blockSignals(False)

    def _repaint(self):
        self.table.viewport().update()

    def _selected_ids(self):
        return [i.data(Qt.UserRole) for i in self.table.selectedItems()]

    def delete_selected(self):
        ids = set(self._selected_ids())
        if not ids or self.running:
            return
        self.state.checkpoint()
        self.state.project.render_items = [i for i in self.state.project.render_items if i.id not in ids]
        self.state.touch("render")

    def _requeue(self):
        p = self.state.project
        for i in self._selected_ids():
            self.status.pop(i, None)
            self.progress.pop(i, None)
            it = next((x for x in p.render_items if x.id == i), None)
            if it is not None and it.done:
                it.done = ""
                self.state.dirty = True
        self.refresh()

    def _resnap(self):
        """선택한 항목의 보정값·◆·꺼 둔 항목을 지금 클립 값으로(실행취소 1번)."""
        ids = set(self._selected_ids())
        p = self.state.project
        items = [x for x in p.render_items if x.id in ids]
        if not items or self.running:
            return
        self.state.checkpoint()
        for it in items:
            for g in it.segs:
                p.snap_seg(g)
        self.state.touch("render")

    def press(self):
        """[렌더] 버튼(v0.16.54, MOSCO v0.7.80 과 같음): 렌더 중 = 전체 취소 / 아니면 저장폴더를 매번 묻고 시작."""
        if self.running:
            self.cancel_all()
            return
        p = self.state.project
        todo = [it for it in p.render_items if not it.done and not self.status.get(it.id, "").startswith("완료")]
        if not todo:
            self.message.emit("새 항목 없음")
            return
        if not ask_quality(self, self.state, todo):       # v0.16.80 용량 먼저 → 저장폴더
            return
        if not self._ask_folder():
            return
        self.render()

    def _ask_folder(self) -> bool:
        """[렌더] 누를 때마다 저장폴더를 물어봄(지난 폴더를 처음 위치로). 취소 = False."""
        from .project import get_setting, set_setting
        p = self.state.project
        o = p.output
        start = (o.folder.strip() or get_setting("last_folder", "")
                 or (str(Path(p.sources[0].path).parent) if p.sources else ""))
        d = QFileDialog.getExistingDirectory(self, "저장폴더 선택", start)
        if not d:
            return False
        if o.folder != d:
            o.folder = d
            self.state.dirty = True
            self.state.changed.emit("output")
        try:
            set_setting("last_folder", d)
        except Exception:  # noqa: BLE001
            pass
        return True

    def cancel_all(self):
        """진행 중·대기 중 렌더를 모두 멈춤(완료분은 그대로). 끝나면 _next 가 버튼을 되돌림."""
        if not self.running:
            return
        self.cancelled = True
        for it in self.queue:                         # 아직 시작 안 한 것
            self.status.pop(it.id, None)
            self.progress.pop(it.id, None)
        self.run_items = [x for x in self.run_items if x not in self.queue]
        self.queue = []
        for j in list(self.jobs.values()):
            j.cancel.set()
        self.message.emit("렌더 취소 중…")
        self.refresh()
        self._next()

    def render(self, only=None):
        """렌더 시작(폴더는 비어 있을 때만 물음 — AUTO·코드 경로). 버튼은 press(). only = 이 항목들만(v0.16.81 AUTO·전부 자동)."""
        if self.running:
            return
        if not ensure_folder(self, self.state):
            return
        self.settings._load()
        p = self.state.project
        self.queue = [it for it in p.render_items
                      if not it.done and not self.status.get(it.id, "").startswith("완료") and all(p.source(g.src) for g in it.segs)
                      and (only is None or it.id in only)]
        if not self.queue:
            self.message.emit("새 항목 없음")
            return
        self.running = True
        self.cancelled = False
        self.run_items = list(self.queue)
        self.run_t0 = time.time()
        self.run_ok, self.run_bad = set(), set()
        free_memory()
        self._next()
        self._overall()

    def enqueue(self, items):
        """렌더 중이면 뒤에 붙여 이어서, 아니면 바로 시작(AUTO: 분석 끝난 영상부터)."""
        if not self.running:
            self.render(only={it.id for it in items})
            return
        p = self.state.project
        known = {x.id for x in self.queue} | set(self.active)
        for it in items:
            if it.id not in known and not it.done and all(p.source(g.src) for g in it.segs):
                self.queue.append(it)
                self.run_items.append(it)
        self._next()
        self._overall()

    def _next(self):
        """빈 자리만큼(jobs.RENDER_N) 다음 항목을 시작. 다 끝나면 running = False."""
        while self.queue and len(self.active) < jobs.RENDER_N:
            self._start(self.queue.pop(0))
        if not self.queue and not self.active and self.running:
            self.running = False
            self.b_render.setToolTip("")
            self.b_render.set_progress(None)
            if self.cancelled:
                self.message.emit("렌더 취소")
            self.runFinished.emit(len(self.run_ok), len(self.run_bad), time.time() - self.run_t0,
                                  str(out_dir(self.state.project)))

    def _dur(self, it) -> float:
        p = self.state.project
        t = 0.0
        for g in it.segs:
            src = p.source(g.src)
            if src is not None and src.fps:
                t += g.frames / float(src.fps) / max(0.01, g.speed)
        return max(0.1, t)

    def _overall(self):
        """전체 진행(영상 길이 가중) → 버튼 · 창 제목 · 작업 표시줄."""
        if not self.running or not getattr(self, "run_items", None):
            return
        tot = sum(self._dur(it) for it in self.run_items)
        got = 0.0
        for it in self.run_items:
            if it.id in self.run_ok or it.id in self.run_bad:
                got += self._dur(it)
            elif it.id in self.active:
                got += self._dur(it) * self.progress.get(it.id, 0.0)
        frac = got / tot if tot else 0.0
        n = len(self.run_items)
        k = len(self.run_ok) + len(self.run_bad)
        text = f"{k}/{n} · {int(frac * 100)}%"
        left = self._left_text(frac)
        self.b_render.set_progress(frac, text, bool(self.run_bad))
        self.b_render.setToolTip((f"남은 시간 {left} · " if left else "렌더 중 · ") + "누르면 취소")
        self.runProgress.emit(frac, f"{text} · 남은 {left}" if left else text, bool(self.run_bad))      # 창 제목

    def _left_text(self, frac: float) -> str:
        """남은 시간(v0.16.41): 지금까지 속도로 어림. 처음 10초·3% 전에는 안 보임(초반 값이 크게 흔들림)."""
        el = time.time() - getattr(self, "run_t0", time.time())
        if el < 10 or frac < 0.03 or frac >= 1:
            return ""
        s = int(el * (1 - frac) / frac)
        s = (s + 4) // 5 * 5 if s < 120 else (s + 29) // 30 * 30          # 숫자가 매초 바뀌지 않게
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _start(self, it):
        p = self.state.project
        path = unique(out_dir(p) / f"{file_name(p, it)}.mp4", set(self.active.values()))
        self.active[it.id] = path
        t0 = time.time()
        self.status[it.id] = "진행"
        self.progress[it.id] = 0.0
        self.refresh()
        extras = {"titles": it.titles, "music": it.music, "mix": it.mix, "lead": getattr(it, "lead", 0.0)}

        def work(prog, cancel, it=it, path=path):
            precache_item(p, it, cancel)               # v0.16.26: HDD 원본을 순서대로 한 번 읽어 메모리에(조각들이 거기서 읽음)
            ff.render_video(p, it.segs, str(path), prog, cancel, it.orientation, it.audio, extras=extras)
        job = jobs.Job(work, with_progress=True)
        self.jobs[it.id] = job
        if self.queue:                                 # 다음 항목도 뒤에서 미리 읽기
            nxt = self.queue[0]
            jobs.submit(jobs.PRECACHE_POOL, jobs.Job(lambda nxt=nxt: precache_item(p, nxt)))

        def prog(v, iid=it.id):
            self.progress[iid] = v
            self._repaint()
            self.itemProgress.emit(iid, v, True)
            self._overall()

        def done(_r, iid=it.id, item=it):
            self.active.pop(iid, None)
            self.jobs.pop(iid, None)
            self.status[iid] = f"완료 {time.time() - t0:.0f}초 → {path}"
            ff.log_info(f"렌더 {time.time() - t0:.1f}초 (동시 {jobs.RENDER_N}, 코어 {jobs.CORES}) {path}")
            item.done = str(path)                 # 프로젝트에 저장 → 다시 열어도 완료
            self.state.dirty = True
            self.run_ok.add(iid)
            self._overall()
            self.refresh()
            self.itemProgress.emit(iid, 1.0, bool(self.queue or self.active))
            self._next()

        def err(msg, iid=it.id):
            self.active.pop(iid, None)
            j = self.jobs.pop(iid, None)
            if j is not None and j.cancel.is_set():       # [렌더] 로 멈춤 = 실패 아님, 만들다 만 파일은 지움
                self.status[iid] = "취소"
                self.progress.pop(iid, None)
                remove_later(path)
                self.run_items = [x for x in self.run_items if x.id != iid]
                self.refresh()
                self.itemProgress.emit(iid, 1.0, bool(self.queue or self.active))
                self._next()
                return
            hint = " (인코더를 x264로)" if "nvenc" in msg.lower() else ""
            self.status[iid] = f"실패{hint}: {msg[-300:]}"
            self.run_bad.add(iid)
            self._overall()
            self.refresh()
            self.itemProgress.emit(iid, 1.0, bool(self.queue or self.active))
            self._next()

        job.signals.progress.connect(prog)
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.RENDER_POOL, job)


class RenderSettings(QWidget):
    """렌더 설정 값(⚙ 창 안). 바꿔도 바로 적용하지 않음 → [확인] 때 apply()(실행취소 1번), [취소]·Esc 는 버림."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        f = QFormLayout(self)
        f.setContentsMargins(0, 0, 0, 6)
        f.setVerticalSpacing(6)
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("DTME")
        f.addRow("명칭", self.prefix)
        self.encoder = QComboBox()
        for key, name in ff.ENCODERS:               # v0.16.41: HEVC 10bit 2개 추가(기본은 그대로)
            self.encoder.addItem(name, key)
        f.addRow("인코더", self.encoder)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(8, 100)
        self.bitrate.setSuffix(" Mbps")
        f.addRow("비트레이트", self.bitrate)
        self.gpu = QCheckBox("GPU")
        f.addRow("디코딩", self.gpu)
        self.still = QComboBox()
        self.still.addItem("PNG 8bit", 8)
        self.still.addItem("PNG 16bit", 16)
        self.still.setToolTip("스틸(S) 저장 형식")
        f.addRow("스틸", self.still)
        self.jobs_a, self.jobs_r = QComboBox(), QComboBox()          # 0 = 자동(원본 저장장치 종류로, jobs.tune)
        for cb, n in ((self.jobs_a, 8), (self.jobs_r, 3)):
            cb.addItem("자동", 0)
            for i in range(1, n + 1):
                cb.addItem(str(i), i)
        self.use_pv = QComboBox()                                    # 카메라 프리뷰(LRF 등) 사용 — 프록시·AUTO 분석·멈춘 화면 먼저
        self.use_pv.addItem("사용", 1)
        self.use_pv.addItem("안 씀", 0)
        f.addRow("프리뷰 파일", self.use_pv)
        f.addRow("동시 분석", self.jobs_a)
        f.addRow("동시 렌더", self.jobs_r)
        frow = QHBoxLayout()
        self.folder = QLineEdit()
        b = QPushButton("선택…")
        fix_size(b)
        b.clicked.connect(self._pick_folder)
        frow.addWidget(self.folder, 1)
        frow.addWidget(b)
        f.addRow("저장폴더", frow)
        for w in (self.prefix, self.folder):
            w.returnPressed.connect(w.clearFocus)
        self._load()

    def _load(self):
        from .project import get_setting
        o = self.state.project.output
        self.prefix.setText(o.prefix)
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(o.encoder)))
        self.bitrate.setValue(o.bitrate_mbps)
        self.gpu.setChecked(o.gpu_decode)
        self.still.setCurrentIndex(1 if str(get_setting("still_bits", 8)) == "16" else 0)
        self.use_pv.setCurrentIndex(0 if str(get_setting("use_preview", 1)) not in ("0", "False", "false", "") else 1)
        from . import jobs as J
        for cb, key, cur in ((self.jobs_a, "auto_jobs", J.AUTO_N), (self.jobs_r, "render_jobs", J.RENDER_N)):
            try:
                v = int(get_setting(key, 0) or 0)
            except (TypeError, ValueError):
                v = 0
            cb.setCurrentIndex(max(0, cb.findData(v)))
            cb.setItemText(0, f"자동 ({cur})" if not v else "자동")
        self.folder.setText(o.folder)

    def apply(self):
        """[확인]: 프로젝트에 넣고(실행취소 1번) 새 프로젝트 기본값·스틸 형식은 settings.json 에 기억."""
        from .project import set_setting
        o = self.state.project.output
        new = (self.prefix.text(), self.encoder.currentData(), self.bitrate.value(), self.gpu.isChecked(), self.folder.text().strip())
        if new != (o.prefix, o.encoder, o.bitrate_mbps, o.gpu_decode, o.folder):
            self.state.checkpoint()
            o.prefix, o.encoder, o.bitrate_mbps, o.gpu_decode, o.folder = new
            self.state.dirty = True
            self.state.changed.emit("output")
        try:
            set_setting("render_defaults", {"prefix": o.prefix, "encoder": o.encoder, "bitrate_mbps": o.bitrate_mbps,
                                            "gpu_decode": o.gpu_decode})
            set_setting("still_bits", self.still.currentData())
            set_setting("use_preview", self.use_pv.currentData())
            set_setting("auto_jobs", self.jobs_a.currentData())
            set_setting("render_jobs", self.jobs_r.currentData())
            self.state.retune()
        except Exception:  # noqa: BLE001
            pass

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "저장폴더", self.folder.text())
        if d:
            self.folder.setText(d)


class RenderSettingsDialog(DragMove, QDialog):
    """⚙ 렌더 설정 창: 테두리 없는 어두운 창(AUTO 창과 같은 모양) + [취소][확인]."""

    def __init__(self, state, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setObjectName("RenderSet")
        self.setStyleSheet("#RenderSet{background:#262626; border:1px solid #555; border-radius:6px;}")
        self.settings = RenderSettings(state)
        self.b_cancel = QPushButton("취소")
        self.b_ok = QPushButton("확인")
        for b in (self.b_cancel, self.b_ok):
            fix_size(b, main=True)
            b.setFocusPolicy(Qt.NoFocus)
        ui_style.tone(self.b_ok, "blue")
        self.b_cancel.clicked.connect(self.reject)
        self.b_ok.clicked.connect(self.accept)
        br = QHBoxLayout()
        br.addStretch(1)
        br.addWidget(self.b_cancel)
        br.addWidget(self.b_ok)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(10)
        lay.addWidget(self.settings)
        lay.addLayout(br)
        self.setMinimumWidth(400)

    def open_at(self, anchor):
        self.settings._load()
        self.adjustSize()
        g = anchor.window().geometry()
        self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)
        return self.exec()

    def accept(self):
        self.settings.apply()
        super().accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):      # 입력란 Enter 로 창이 닫히지 않게
            return
        super().keyPressEvent(e)            # Esc = 취소
