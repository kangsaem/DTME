"""메인 창: 상단(저장·불러오기·실행취소), 탭(편집·보정 / 렌더), 드래그 앤 드롭."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTabWidget, QToolBar

from . import __version__, paths
from .project import Project
from .state import AppState
from .ui_edit import EditTab
from .ui_render import RenderTab

PROJ_FILTER = "DTME 프로젝트 (*.dtme.json *.json)"
VIDEO_EXT = {".mp4", ".mov"}


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

        self.tabs = QTabWidget()
        self.edit = EditTab(self.state)
        self.render = RenderTab(self.state)
        self.tabs.addTab(self.edit, "편집 · 보정")
        self.tabs.addTab(self.render, "렌더")
        self.setCentralWidget(self.tabs)

        self.state.message.connect(lambda t: self.statusBar().showMessage(t, 15000))
        self.state.changed.connect(lambda *_: self._title())
        self._autosave = QTimer(self)
        self._autosave.setInterval(60_000)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start()
        self._title()

    def _title(self):
        f = Path(self.state.project.file).name if self.state.project.file else "새 프로젝트"
        self.setWindowTitle(f"DTME {__version__} — {f}{' *' if self.state.dirty else ''}")

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
        r = QMessageBox.question(self, "저장", "변경 내용을 저장할까요?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_project()
        return r == QMessageBox.Discard

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
            QMessageBox.warning(self, "불러오기 실패", str(e))
            return
        missing = [s.name for s in p.sources if not Path(s.path).exists()]
        self.state.set_project(p)
        self._title()
        if missing:
            QMessageBox.warning(self, "원본 없음", "원본 파일을 찾을 수 없습니다:\n" + "\n".join(missing))

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
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()

    # ------------------------------------------------------------ 드래그 앤 드롭
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        vids = [f for f in files if Path(f).suffix.lower() in VIDEO_EXT]
        projs = [f for f in files if f.endswith(".json")]
        if vids:
            self.tabs.setCurrentIndex(0)
            self.edit.import_files(vids)
        elif projs and self._confirm_discard():
            self._load(projs[0])
