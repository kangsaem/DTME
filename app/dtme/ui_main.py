"""메인 창: 탭(편집/보정/출력), 프로젝트 저장·열기, 드래그 앤 드롭."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTabWidget

from . import __version__, paths
from .project import Project
from .state import AppState
from .ui_edit import EditTab
from .ui_output import OutputTab

PROJ_FILTER = "DTME 프로젝트 (*.dtme.json *.json)"
VIDEO_EXT = {".mp4", ".mov"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.resize(1600, 960)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.edit = EditTab(self.state)
        self.output = OutputTab(self.state)
        self.tabs.addTab(self.edit, "1. 편집 · 보정")
        self.tabs.addTab(self.output, "2. 출력")
        self.tabs.currentChanged.connect(self._on_tab)
        self.setCentralWidget(self.tabs)

        m = self.menuBar().addMenu("파일")
        for text, key, fn in (("새 프로젝트", QKeySequence.New, self.new_project),
                              ("열기…", QKeySequence.Open, self.open_project),
                              ("저장", QKeySequence.Save, self.save_project),
                              ("다른 이름으로 저장…", QKeySequence.SaveAs, lambda: self.save_project(True)),
                              ("영상 추가…", "Ctrl+I", self.edit.add_files)):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(fn)
            m.addAction(a)

        self.state.message.connect(lambda t: self.statusBar().showMessage(t, 15000))
        self.state.changed.connect(lambda *_: self._title())
        self._autosave = QTimer(self)
        self._autosave.setInterval(60_000)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start()
        self._title()
        self.statusBar().showMessage("영상 추가(Ctrl+I) 또는 창에 영상 파일을 끌어다 놓으세요.")

    def _on_tab(self, i):
        if i == 1:
            self.output._refresh_plan()

    def _title(self):
        f = Path(self.state.project.file).name if self.state.project.file else "새 프로젝트"
        self.setWindowTitle(f"DTME {__version__} — {f}{' *' if self.state.dirty else ''}")

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
        f, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", "", PROJ_FILTER)
        if f:
            try:
                p = Project.load(f)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "열기 실패", str(e))
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
            f, _ = QFileDialog.getSaveFileName(self, "프로젝트 저장", start, PROJ_FILTER)
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
                d = self.state.project.to_dict()
                import json
                (paths.cache_dir() / "autosave.dtme.json").write_text(
                    json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
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
            self.state.set_project(Project.load(projs[0]))
