"""시작 창(v0.16.8): 큰 [AUTO] + 작은 [MANUAL]. AUTO = 파일·폴더 선택(또는 끌어 놓기) → AUTO 창만 띄워 분석.
[보정+편집] → 메인 편집 화면, [샘플] → AUTO 창 그대로, [보정+렌더] → 이 창에 진행 막대 → 끝나면 프로그램 종료,
[취소] → 프로그램 종료(v0.16.9, 사용자 2026-11-07)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from . import __version__, ui_style
from .project import Project, get_setting, set_setting

VIDEO_EXT = {".mp4", ".mov"}
MEDIA_FILTER = "영상 (*.mp4 *.MP4 *.mov *.MOV)"


def collect_videos(paths) -> list[str]:
    """파일은 그대로(영상만), 폴더는 그 안의 영상(하위 폴더 제외) 이름 순."""
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(str(f) for f in p.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
        elif p.suffix.lower() in VIDEO_EXT:
            out.append(str(p))
    return out


class Launcher(QWidget):
    def __init__(self, mw):
        super().__init__(None, Qt.Window)
        self.mw = mw
        self.setWindowTitle(f"DTME {__version__}")
        self.setObjectName("Launcher")
        self.setAcceptDrops(True)
        self.setFixedSize(420, 300)
        self._style(False)
        self.b_auto = QPushButton("AUTO")
        self.b_auto.setFixedSize(240, 110)
        self.b_auto.setFocusPolicy(Qt.NoFocus)
        ui_style.tone(self.b_auto, "red")
        f = QFont(self.b_auto.font())
        f.setPixelSize(40)
        f.setBold(True)
        self.b_auto.setFont(f)
        self.b_auto.clicked.connect(self._menu)
        self.b_manual = QPushButton("MANUAL")
        self.b_manual.setFixedSize(110, 30)
        self.b_manual.setFocusPolicy(Qt.NoFocus)
        self.b_manual.clicked.connect(self.manual)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(240, 6)
        self.bar.setStyleSheet("QProgressBar{background:#2a2a2a; border:none;} QProgressBar::chunk{background:#c0392b;}")
        self.bar.setVisible(False)
        self.msg = QLabel("")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setStyleSheet("color:#9a9a9a;")
        self.b_folder = QPushButton("폴더 열기")
        self.b_folder.setFixedSize(110, 28)
        self.b_folder.setFocusPolicy(Qt.NoFocus)
        self.b_folder.clicked.connect(self._open_folder)
        self.b_folder.setVisible(False)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 16)
        v.setSpacing(8)
        v.addStretch(1)
        for w in (self.b_auto, self.bar):
            r = QHBoxLayout()
            r.addStretch(1)
            r.addWidget(w)
            r.addStretch(1)
            v.addLayout(r)
        v.addWidget(self.msg)
        v.addStretch(1)
        r = QHBoxLayout()
        r.setSpacing(8)
        r.addStretch(1)
        r.addWidget(self.b_folder)
        r.addWidget(self.b_manual)
        r.addStretch(1)
        v.addLayout(r)
        self.rendering = False
        rp = mw.edit.render_panel
        rp.runProgress.connect(self._render_progress)      # v0.16.33: 편집 화면 [렌더] 버튼과 같은 전체 진행(영상 길이 기준)
        rp.runFinished.connect(self._render_finished)

    def _style(self, hot):
        self.setStyleSheet("#Launcher{background:#232323;}" if not hot else
                           "#Launcher{background:#262a30; border:2px dashed #4a8fe0;}")

    def center(self):
        scr = self.screen().availableGeometry()
        self.move(scr.center().x() - self.width() // 2, scr.center().y() - self.height() // 2)

    # ------------------------------------------------------------ 선택
    def _menu(self):
        m = QMenu(self)
        a_f = m.addAction("파일 선택…")
        a_d = m.addAction("폴더 선택…")
        act = m.exec(self.b_auto.mapToGlobal(self.b_auto.rect().bottomLeft()))
        start = get_setting("last_src_folder", "") or ""
        if act is a_f:
            files, _ = QFileDialog.getOpenFileNames(self, "영상 선택", start, MEDIA_FILTER)
            if files:
                self.run_auto(files)
        elif act is a_d:
            d = QFileDialog.getExistingDirectory(self, "폴더 선택", start)
            if d:
                self.run_auto([d])

    def dragEnterEvent(self, e):
        if not self.rendering and e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._style(True)

    def dragLeaveEvent(self, e):
        self._style(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._style(False)
        self.run_auto([u.toLocalFile() for u in e.mimeData().urls()])

    # ------------------------------------------------------------ AUTO
    def run_auto(self, paths):
        if self.rendering:
            return
        files = collect_videos(paths)
        if not files:
            self._say("영상 없음")
            return
        try:
            set_setting("last_src_folder", str(Path(files[0]).parent))
        except Exception:  # noqa: BLE001
            pass
        self.b_folder.setVisible(False)
        self._say("")
        mw = self.mw
        mw.state.set_project(Project())             # 시작 창 AUTO = 늘 새 작업
        mw.state.defer_proxy = True                 # 프록시(재생용)는 [보정+편집] 때 — 분석·샘플·렌더는 원본에서
        mw.edit.import_files(files)
        if not mw.state.project.sources:
            mw.state.defer_proxy = False
            self._say("영상 없음")
            return
        dlg = mw.edit.make_auto_dialog()
        c = self.geometry().center()
        dlg.move(c.x() - dlg.width() // 2, c.y() - dlg.height() // 2)
        self.hide()
        r = dlg.exec()
        if r == QDialog.Accepted and dlg.mode == "each":       # [보정+편집] → 메인 편집 화면
            mw.state.resume_proxies()
            mw.show()
            mw.raise_()
            self.close()
            return
        if not (r == QDialog.Accepted and dlg.mode == "render" and mw.edit.render_panel.running):
            self._quit()                            # [취소]·Esc(또는 렌더할 것 없음) = 프로그램 종료
            return
        self.show()                                 # [보정+렌더] = 이 창에 진행 막대
        self.rendering = True
        self.b_auto.setEnabled(False)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self._say("렌더 중…")

    def _render_progress(self, frac, text, bad):
        if not self.rendering:
            return
        from . import taskbar
        self.bar.setValue(int(frac * 100))
        self._say(f"렌더 {text}")
        self.setWindowTitle(f"DTME {__version__} — 렌더 {text}")
        taskbar.set_progress(self, frac, bad)          # 시작 창을 내려 둬도 작업 표시줄에 진행

    def _render_finished(self, ok, bad, sec, folder):
        """[보정+렌더] 끝(v0.16.33): 완료 팝업 → [확인]·[폴더 열기] 누르면 프로그램 종료(예전 = 바로 종료)."""
        if not self.rendering:
            return
        from . import taskbar
        from .ui_render import show_done_popup
        self.rendering = False
        self.b_auto.setEnabled(True)
        self.bar.setVisible(False)
        self.setWindowTitle(f"DTME {__version__}")
        taskbar.clear(self)
        self._say(f"완료 {ok}개" + (f" · 실패 {bad}개" if bad else ""), "#7fd18b" if not bad else "#f2c94c")
        self.b_folder.setVisible(ok > 0)
        if self.mw.isVisible():                           # 그새 편집 화면으로 갔으면 거기 팝업
            return
        self.show()
        taskbar.flash(self)
        self._done_dlg = show_done_popup(self, ok, bad, sec, folder,
                                         on_close=None if bad else self._quit)   # 실패가 있으면 시작 창에 남김(예전과 같음)

    def _quit(self):
        from PySide6.QtWidgets import QApplication
        self.hide()
        QApplication.quit()

    def _say(self, t, color="#9a9a9a"):
        self.msg.setStyleSheet(f"color:{color};")
        self.msg.setText(t)

    def _open_folder(self):
        from .ui_render import open_file, out_dir
        open_file(str(out_dir(self.mw.state.project)))

    # ------------------------------------------------------------ MANUAL
    def manual(self):
        if not self.rendering:
            self.mw.state.set_project(Project())
        self.mw.show()
        self.mw.raise_()
        self.close()

    def closeEvent(self, e):
        if self.rendering and not self.mw.isVisible():
            if ui_style.confirm(self, "렌더 중입니다. 끄고 종료할까요?",
                                [("cancel", "취소", 72, None), ("quit", "종료", 80, "red")]) != "quit":
                e.ignore()
                return
        e.accept()
