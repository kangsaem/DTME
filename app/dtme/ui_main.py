"""메인 창: 상단(새 프로젝트·저장·불러오기·실행취소) + 편집·보정·렌더 한 화면, 드래그 앤 드롭."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMainWindow, QToolBar

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
        tb.setStyleSheet("QToolBar{spacing:6px; padding:3px; background:#232323; border-bottom:1px solid #333;}"
                         " QToolButton{padding:4px 12px;}")           # MOSCO 와 같은 값(v0.16.55: 바탕·아래 선)
        self.addToolBar(tb)
        a = QAction("새 프로젝트", self)
        a.triggered.connect(self.new_project)
        tb.addAction(a)
        tb.addSeparator()
        for text, key, fn in (("저장하기", QKeySequence.Save, self.save_project),
                              ("불러오기", QKeySequence.Open, self.open_project),
                              ("실행취소", QKeySequence.Undo, self.undo),
                              ("다시 실행", QKeySequence("Ctrl+Shift+Z"), self.redo)):          # v0.16.76 [다시 실행]
            a = QAction(text, self)
            if fn != self.redo:                          # Ctrl+Shift+Z 는 편집 화면이 이미 받음(겹치면 두 번 실행)
                a.setShortcut(key)
            a.setToolTip(QKeySequence(key).toString() + (" · Ctrl+Y" if fn == self.redo else ""))
            a.triggered.connect(fn)
            tb.addAction(a)
        a = QAction("되살리기", self)                   # v0.16.76 자동 저장(최근 10개) 고르기
        a.setToolTip("자동 저장 — 5분마다 최근 10개")
        a.triggered.connect(self.pick_autosave)
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
        rp.runStarted.connect(self._render_started)
        self._title()

    def _render_started(self):
        """v0.16.91 렌더 작업 창(A안): 재생·전환 미리보기 멈춤 → 편집 창 숨김 → 작업 창만."""
        from . import solo
        from .ui_renderwin import RenderWindow
        e = self.edit
        try:
            e.player.pause()
            e._music_stop()
            e.trans_prev.stop()
        except Exception:  # noqa: BLE001
            pass
        old = getattr(self, "_rwin", None)
        if old is not None:
            old.finish()
        self._rwin = RenderWindow(e.render_panel, self)
        self._rwin.move(self.geometry().center() - self._rwin.rect().center())
        self._rwin.show()
        solo.enter(self._rwin, self)

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
        rw = getattr(self, "_rwin", None)
        if rw is not None:                            # v0.16.91 렌더 작업 창 닫고 편집 창으로
            self._rwin = None
            rw.finish()
        if not self.isVisible():                      # 시작 창 [보정+렌더](편집 화면 숨김) = 시작 창이 팝업
            return
        if self.edit.render_panel.cancelled:          # [렌더] 로 멈춤(v0.16.54) = 완료 팝업 없음
            return
        taskbar.flash(self)
        old = getattr(self, "_done_dlg", None)
        if old is not None:
            old.close()
        self._done_dlg = show_done_popup(self, ok, bad, sec, folder)

    # ------------------------------------------------------------ 실행취소
    def undo(self):
        lab = self.state.undo_label()
        if lab in self.state.BIG_UNDO:                  # v0.16.76 큰 작업 = 되돌리기 전에 물음(다시 실행으로 돌아올 수 있지만 새 작업을 하면 사라짐)
            if ui_style.confirm(self, f"{lab} 전으로 돌아갈까요?", [("cancel", "취소", 72, None), ("ok", "되돌리기", 92, "red")]) != "ok":
                return
        r = self.state.undo()
        msg = ("실행취소" + (f": {r}" if isinstance(r, str) else "")) if r else "더 이상 취소할 작업이 없습니다"
        self.statusBar().showMessage(msg, 5000)
        self.edit._say(msg)

    def redo(self):
        r = self.state.redo()
        msg = ("다시 실행" + (f": {r}" if isinstance(r, str) else "")) if r else "다시 실행할 작업이 없습니다"
        self.statusBar().showMessage(msg, 5000)
        self.edit._say(msg)

    # ------------------------------------------------------------ 원본 없음 → 폴더 다시 지정(v0.16.41)
    def relink(self) -> int:
        """원본을 못 찾은 소스가 있으면 폴더를 골라 같은 이름으로 다시 연결. 찾은 개수."""
        if not self.state.missing() and not any(v == "원본 없음" for v in self.state.img_status.values()):
            return 0
        d = QFileDialog.getExistingDirectory(self, "원본 폴더", "")
        if not d:
            return 0
        n = self.state.relink(d)
        left = len(self.state.missing())
        self.statusBar().showMessage(f"원본 {n}개 다시 연결" + (f" · {left}개 못 찾음" if left else ""), 8000)
        return n

    # ------------------------------------------------------------ 자동 저장 되살리기(v0.16.41)
    def autosave_file(self) -> Path:
        return paths.cache_dir() / "autosave.dtme.json"

    def drop_autosave(self):
        try:
            self.autosave_file().unlink(missing_ok=True)
        except OSError:
            pass

    def restore_autosave(self, file: Path | None = None) -> bool:
        """지난번에 저장 못 하고 꺼진 작업(자동 저장 파일)을 불러옴. 원래 프로젝트 파일 이름은 유지, 저장 안 된 상태로."""
        import json
        from .project import Project
        try:
            d = json.loads((file or self.autosave_file()).read_text(encoding="utf-8"))
            p = Project.from_dict(d)
            p.file = d.get("_file", "") or ""
        except Exception as e:  # noqa: BLE001
            ui_style.notice(self, f"되살리기 실패: {e}")
            return False
        self.state.set_project(p)
        self.state.dirty = True
        self._title()
        return True

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
            more = f"\n… 외 {len(missing) - 8}개" if len(missing) > 8 else ""
            if ui_style.confirm(self, "원본 파일을 찾을 수 없습니다:\n" + "\n".join(missing[:8]) + more,
                                [("cancel", "닫기", 72, None), ("pick", "폴더 지정", 92, "blue")]) == "pick":
                self.relink()

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
        self.drop_autosave()
        self._title()
        self.statusBar().showMessage(f"저장됨: {f}", 5000)
        return True

    AUTOSAVE_KEEP = 10                               # v0.16.76 최근 10개
    AUTOSAVE_EVERY = 300                             # 5분마다 하나 남김(자동 저장 자체는 1분마다)

    def autosave_dir(self) -> Path:
        d = paths.cache_dir() / "autosave"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _do_autosave(self):
        if self.state.dirty and self.state.project.sources:
            try:
                from .project import write_json_atomic
                data = {**self.state.project.to_dict(), "_file": self.state.project.file or ""}
                write_json_atomic(self.autosave_file(), data, indent=1)
                import time as _t
                if _t.time() - getattr(self, "_hist_t", 0.0) >= self.AUTOSAVE_EVERY:     # v0.16.76 여러 개 남김
                    self._hist_t = _t.time()
                    write_json_atomic(self.autosave_dir() / f"{_t.strftime('%Y%m%d_%H%M%S')}.dtme.json", data, indent=1)
                    old = sorted(self.autosave_dir().glob("*.dtme.json"))[:-self.AUTOSAVE_KEEP]
                    for f in old:
                        f.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    def autosave_list(self) -> list[tuple[Path, str]]:
        """[(파일, '11-13 16:20 · 컷 21 · 음악 4')] 최신순."""
        import json
        out = []
        for f in sorted(self.autosave_dir().glob("*.dtme.json"), reverse=True):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                st = f.name.split(".")[0]
                when = f"{st[4:6]}-{st[6:8]} {st[9:11]}:{st[11:13]}"
                out.append((f, f"{when} · 컷 {len(d.get('segments', []))} · 글자 {len(d.get('titles', []))} · 음악 {len(d.get('music', []))}"
                               + (f" · {Path(d.get('_file')).stem}" if d.get("_file") else "")))
            except Exception:  # noqa: BLE001
                pass
        return out

    def pick_autosave(self):
        """[되살리기] 자동 저장 목록(최근 10개)에서 골라 불러옴 — 저장 안 된 상태로(원래 파일 이름 유지)."""
        from PySide6.QtWidgets import QListWidget
        from .ui_render import Popup
        items = self.autosave_list()
        if not items:
            ui_style.notice(self, "자동 저장된 작업이 없습니다")
            return
        dlg = Popup(self)
        lw = QListWidget()
        lw.setMinimumWidth(420)
        for f, text in items:
            lw.addItem(text)
        lw.setCurrentRow(0)
        dlg.body.addWidget(lw)
        dlg.add_buttons("되살리기")
        lw.itemDoubleClicked.connect(lambda _it: dlg.accept())
        if dlg.exec() != QDialog.Accepted or lw.currentRow() < 0:
            return
        if not self._confirm_discard():
            return
        self.restore_autosave(items[lw.currentRow()][0])

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_tinted", False):          # v0.16.58 윈도우 제목 줄(흰색) → 진회색, MOSCO 와 같음
            self._tinted = True
            ui_style.tint_title(self)

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
        from .divelog import is_dive_file
        from .ui_launch import collect_videos
        vids = [f for f in files if Path(f).suffix.lower() in VIDEO_EXT]
        vids += collect_videos([f for f in files if Path(f).is_dir()])      # 폴더 = 그 안의 영상
        dives = [f for f in files if Path(f).is_file() and Path(f).suffix.lower() in (".fit", ".zip", ".json")
                 and is_dive_file(f)]                                       # v0.16.84 다이빙 기록
        projs = [f for f in files if f.endswith(".json") and f not in dives]
        if vids or dives:
            self.edit.import_files(vids + dives)
        elif projs and self._confirm_discard():
            self._load(projs[0])
