"""메인 창: 상단(새 프로젝트·저장·불러오기·실행취소) + 편집·보정·렌더 한 화면, 드래그 앤 드롭."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QToolBar

from . import __version__, paths, ui_style
from .project import AUDIO_EXT, IMAGE_EXT, Project
from .state import AppState
from .ui_edit import EditTab

PROJ_FILTER = "DTME 프로젝트 (*.dtme.json *.json)"
VIDEO_EXT = {".mp4", ".mov"} | IMAGE_EXT | AUDIO_EXT


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.resize(1800, 1000)
        self.setAcceptDrops(True)

        tb = QToolBar("main")
        tb.setMovable(False)
        tb.setStyleSheet("QToolBar{spacing:6px; padding:3px;} QToolButton{padding:4px 12px;}")
        self.addToolBar(tb)
        a = QAction("새 프로젝트", self)
        a.triggered.connect(self.new_project)
        tb.addAction(a)
        tb.addSeparator()
        for text, key, fn in (("저장하기", QKeySequence.Save, self.save_project),
                              ("불러오기", QKeySequence.Open, self.open_project),
                              ("실행취소", QKeySequence.Undo, self.undo)):
            a = QAction(text, self)
            a.setShortcut(key)
            a.setToolTip(QKeySequence(key).toString())
            a.triggered.connect(fn)
            tb.addAction(a)
        from PySide6.QtWidgets import QToolButton
        for act in tb.actions():                    # 맨 위 줄도 다른 버튼과 같은 입체감(늘 보이게, 그림자 없음)
            btn = tb.widgetForAction(act)
            if isinstance(btn, QToolButton):
                btn.setAutoRaise(False)
                btn.setProperty("bevel", True)

        self.edit = EditTab(self.state)
        self.setCentralWidget(self.edit)

        self.state.message.connect(lambda t: self.statusBar().showMessage(t, 15000))
        self.state.changed.connect(lambda *_: self._title())
        self._autosave = QTimer(self)
        self._autosave.setInterval(60_000)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start()
        self._rtext = ""                                # v0.16.31 렌더 진행 → 창 제목
        rp = self.edit.render_panel
        rp.runProgress.connect(self._render_progress)
        rp.runFinished.connect(self._render_finished)
        self._title()

    def _title(self):
        f = Path(self.state.project.file).name if self.state.project.file else "새 프로젝트"
        r = f"렌더 {self._rtext} — " if getattr(self, "_rtext", "") else ""
        self.setWindowTitle(f"DTME {__version__} — {r}{f}{' *' if self.state.dirty else ''}")

    # ------------------------------------------------------------ 렌더 진행(v0.16.31): 창 제목 · 작업 표시줄 · 완료 팝업
    def _render_progress(self, frac: float, text: str, bad: bool):
        from . import taskbar
        self._rtext = text
        self._title()
        taskbar.set_progress(self, frac, bad)

    def _render_finished(self, ok: int, bad: int, sec: float, folder: str):
        from . import taskbar
        from .ui_render import show_done_popup
        self._rtext = ""
        self._title()
        taskbar.clear(self)
        if not self.isVisible():                      # 시작 창 [보정+렌더](편집 화면 숨김) = 시작 창이 팝업
            return
        taskbar.flash(self)
        old = getattr(self, "_done_dlg", None)
        if old is not None:
            old.close()
        self._done_dlg = show_done_popup(self, ok, bad, sec, folder)

    # ------------------------------------------------------------ 실행취소
    def undo(self):
        if self.state.undo():
            self.statusBar().showMessage("실행취소", 3000)
        else:
            self.statusBar().showMessage("더 이상 취소할 작업이 없습니다", 3000)

    # ------------------------------------------------------------ 프로젝트
    def _confirm_discard(self) -> bool:
        if not self.state.dirty:
            return True
        from .ui_style import confirm_save
        r = confirm_save(self)                      # MOSCO 와 같은 어두운 창 [취소][저장 안 함][저장]
        if r == "save":
            return self.save_project()
        return r == "discard"

    def new_project(self):
        if self._confirm_discard():
            self.state.set_project(Project())
            self._title()

    def open_project(self):
        if not self._confirm_discard():
            return
        f, _ = QFileDialog.getOpenFileName(self, "불러오기", "", PROJ_FILTER)
        if f:
            self._load(f)

    def _load(self, f):
        try:
            p = Project.load(f)
        except Exception as e:  # noqa: BLE001
            ui_style.notice(self, f"불러오기 실패: {e}")
            return
        missing = [s.name for s in p.sources if not Path(s.path).exists()]
        self.state.set_project(p)
        self._title()
        if missing:
            ui_style.notice(self, "원본 파일을 찾을 수 없습니다:\n" + "\n".join(missing))

    def save_project(self, save_as=False) -> bool:
        p = self.state.project
        f = p.file
        if save_as or not f:
            start = str(Path(p.sources[0].path).parent / "프로젝트.dtme.json") if p.sources else "프로젝트.dtme.json"
            f, _ = QFileDialog.getSaveFileName(self, "저장하기", start, PROJ_FILTER)
            if not f:
                return False
        p.save(f)
        self.state.dirty = False
        self._title()
        self.statusBar().showMessage(f"저장됨: {f}", 5000)
        return True

    def _do_autosave(self):
        if self.state.dirty and self.state.project.sources:
            try:
                (paths.cache_dir() / "autosave.dtme.json").write_text(
                    json.dumps(self.state.project.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

    def closeEvent(self, e):
        rp = getattr(getattr(self, "edit", None), "render_panel", None)
        if rp is not None and rp.running and self.isVisible():     # v0.16.23: 메인 창에서도 렌더 중 확인
            if ui_style.confirm(self, "렌더 중입니다. 끄고 종료할까요?",
                                [("cancel", "취소", 72, None), ("quit", "종료", 80, "red")]) != "quit":
                e.ignore()
                return
        if self._confirm_discard():
            e.accept()
            QApplication.quit()             # 숨은 창(시작 창 등)이 남아도 프로그램 종료 → main.finish 정리
        else:
            e.ignore()

    # ------------------------------------------------------------ 드래그 앤 드롭
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        from .ui_launch import collect_videos
        vids = [f for f in files if Path(f).suffix.lower() in VIDEO_EXT]
        vids += collect_videos([f for f in files if Path(f).is_dir()])      # 폴더 = 그 안의 영상
        projs = [f for f in files if f.endswith(".json")]
        if vids:
            self.edit.import_files(vids)
        elif projs and self._confirm_discard():
            self._load(projs[0])
