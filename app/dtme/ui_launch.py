"""시작 창(v0.16.52): MOSCO v0.7.75 시작 창과 같은 틀 — 제목 표시줄·테두리 없는 400×560, 위 = 정사각형 그림(assets/start.png)
+ 왼쪽 위 'DTME'·버전 + 오른쪽 위 ✕(종료) + 오른쪽 아래 세로 글자, 아래(#262626) = [AUTO] 160×48 + [편집] 160×32. 빈 곳을 끌어 옮김.
(v0.16.8) 큰 [AUTO] + 작은 [MANUAL → 편집]. AUTO = 파일·폴더 선택(또는 끌어 놓기) → AUTO 창만 띄워 분석.
[보정+편집] → 메인 편집 화면, [샘플] → AUTO 창 그대로, [보정+렌더] → 이 창에 진행 막대 → 끝나면 프로그램 종료,
[취소] → 프로그램 종료(v0.16.9, 사용자 2026-11-07)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QLabel, QMenu, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from . import __version__, paths, ui_style
from .project import Project, get_setting, set_setting

VIDEO_EXT = {".mp4", ".mov"}
MEDIA_FILTER = ("영상·사진·음악 (*.mp4 *.MP4 *.mov *.MOV *.jpg *.JPG *.jpeg *.JPEG *.png *.PNG "
                "*.mp3 *.MP3 *.m4a *.M4A *.wav *.WAV *.flac *.FLAC *.aac *.AAC)")


def collect_media(paths) -> list[str]:
    """v0.16.72 영상·사진·음악: 파일은 그대로, 폴더는 그 안의 것(하위 폴더 제외) 이름 순."""
    from .project import AUDIO_EXT, IMAGE_EXT
    ok = VIDEO_EXT | IMAGE_EXT | AUDIO_EXT
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(str(f) for f in p.iterdir() if f.is_file() and f.suffix.lower() in ok)
        elif p.suffix.lower() in ok:
            out.append(str(p))
    return out


def collect_videos(paths) -> list[str]:
    """파일은 그대로(영상만), 폴더는 그 안의 영상(하위 폴더 제외) 이름 순."""
    return [f for f in collect_media(paths) if Path(f).suffix.lower() in VIDEO_EXT]


IMG = 400                                      # 그림 한 변(논리 px). 그림 파일은 800×800(고배율 화면용)
W, H = IMG, IMG + 160
SIDE_TEXT = "Diving Tour Movie Editor"


class SideText(QWidget):
    """그림 오른쪽 아래의 세로 글자: 90° 돌려 아래 → 위로 읽음. 아주 가는 글씨(Segoe UI ExtraLight 14px), 흰색 알파 225, 자간 1.5px."""

    def __init__(self, text, parent):
        super().__init__(parent)
        self.text = text
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        f = QFont("Segoe UI")
        f.setPixelSize(14)
        f.setWeight(QFont.ExtraLight)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.setFont(f)
        fm = self.fontMetrics()
        self.setFixedSize(fm.height() + 2, fm.horizontalAdvance(text) + 4)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setPen(QColor(255, 255, 255, 225))
        p.translate(0, self.height())
        p.rotate(-90)
        p.drawText(0, 0, self.height(), self.width(), Qt.AlignLeft | Qt.AlignVCenter, self.text)
        p.end()


class Launcher(QWidget):
    def __init__(self, mw):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.mw = mw
        self.setWindowTitle(f"DTME {__version__}")          # 작업 표시줄 이름
        self.setObjectName("Launcher")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFixedSize(W, H)
        self._drag = None
        self._style(False)
        # 위: 정사각형 그림 + 제목·버전(왼쪽 위) + ✕(오른쪽 위) + 세로 글자(오른쪽 아래)
        self.img = QLabel(self)
        self.img.setFixedSize(IMG, IMG)
        self.img.setAlignment(Qt.AlignCenter)
        pm = QPixmap(str(paths.asset("start.png")))
        if pm.isNull():
            self.img.setStyleSheet("background:#3a3a3a;")
        else:
            dpr = self.devicePixelRatioF() or 1.0
            pm = pm.scaled(round(IMG * dpr), round(IMG * dpr), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.img.setPixmap(pm)
        head = QWidget(self.img)
        head.setAttribute(Qt.WA_TransparentForMouseEvents, True)     # 글자 위를 잡아도 창이 끌림
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        self.title = QLabel("DTME", head)
        tf = QFont(self.title.font())
        tf.setPixelSize(42)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        self.title.setFont(tf)
        self.title.setStyleSheet("color:#ffffff; background:transparent;")
        self.ver = QLabel(f"v{__version__}", head)
        vf = QFont(self.ver.font())
        vf.setPixelSize(13)
        self.ver.setFont(vf)
        self.ver.setStyleSheet("color:#e6e6e6; padding-left:2px; background:transparent;")
        hl.addWidget(self.title)
        hl.addWidget(self.ver)
        head.adjustSize()
        head.move(18, 12)
        self.side = SideText(SIDE_TEXT, self.img)
        self.side.move(IMG - 14 - self.side.width(), IMG - 14 - self.side.height())
        self.b_close = QPushButton("✕", self.img)
        self.b_close.setToolTip("종료")
        self.b_close.setCursor(Qt.PointingHandCursor)
        self.b_close.setFocusPolicy(Qt.NoFocus)
        self.b_close.setFixedSize(26, 26)
        self.b_close.setStyleSheet("QPushButton{color:#ffffff; background:rgba(0,0,0,90); border:none; border-radius:13px;"
                                   " font-size:14px; padding:0;} QPushButton:hover{background:#c0392b;}")
        self.b_close.move(IMG - 26 - 10, 10)
        self.b_close.clicked.connect(self.close)
        # 아래: 버튼(동작은 예전 그대로 — [AUTO] · [편집](예전 MANUAL) · 렌더 중 진행 막대·글자·[폴더 열기])
        self.b_auto = QPushButton("AUTO")
        self.b_auto.setFixedSize(160, 48)
        self.b_auto.setFocusPolicy(Qt.NoFocus)
        ui_style.tone(self.b_auto, "red")
        f = QFont(self.b_auto.font())
        f.setPointSizeF(f.pointSizeF() * 1.3)
        f.setBold(True)
        self.b_auto.setFont(f)
        self.b_auto.clicked.connect(self._menu)
        self.b_manual = QPushButton("편집")
        self.b_manual.setFixedSize(160, 32)
        self.b_manual.setFocusPolicy(Qt.NoFocus)
        self.b_manual.clicked.connect(self.manual)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(160, 6)
        from . import stage as SG
        self.bar.setStyleSheet("QProgressBar{background:#2a2a2a; border:none;} QProgressBar::chunk{background:%s;}" % SG.STAGE["render"][1])   # v0.16.82 렌더 색 통일
        self.bar.setVisible(False)
        self.msg = QLabel("")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setStyleSheet("color:#9a9a9a;")
        self.msg.setVisible(False)
        self.b_folder = QPushButton("폴더 열기")
        self.b_folder.setFixedSize(160, 26)
        self.b_folder.setFocusPolicy(Qt.NoFocus)
        self.b_folder.clicked.connect(self._open_folder)
        self.b_folder.setVisible(False)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.img)
        v.addStretch(1)
        v.addWidget(self.b_auto, 0, Qt.AlignHCenter)
        v.addSpacing(4)
        v.addWidget(self.bar, 0, Qt.AlignHCenter)
        v.addWidget(self.msg)
        v.addSpacing(8)
        v.addWidget(self.b_manual, 0, Qt.AlignHCenter)
        v.addWidget(self.b_folder, 0, Qt.AlignHCenter)
        v.addStretch(1)
        self.rendering = False
        rp = mw.edit.render_panel
        rp.runProgress.connect(self._render_progress)      # v0.16.33: 편집 화면 [렌더] 버튼과 같은 전체 진행(영상 길이 기준)
        rp.runFinished.connect(self._render_finished)

    def _style(self, hot):
        self.setStyleSheet("#Launcher{background:#262626; border:none;}" if not hot else
                           "#Launcher{background:#262a30; border:2px dashed #4a8fe0;}")     # 끌어 놓는 동안만 점선

    # ------------------------------------------------------------ 빈 곳을 끌어 옮김(제목 표시줄이 없음)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)

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
            files, _ = QFileDialog.getOpenFileNames(self, "파일 선택", start, MEDIA_FILTER)
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
        allf = collect_media(paths)                 # v0.16.72 음악·사진도 같이 받음(편집 화면에서 씀)
        files = [f for f in allf if Path(f).suffix.lower() in VIDEO_EXT]
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
        mw.edit.import_files(allf)
        if not mw.state.project.sources:
            mw.state.defer_proxy = False
            self._say("영상 없음")
            return
        dlg = mw.edit.make_auto_dialog()
        c = self.geometry().center()
        dlg.move(c.x() - dlg.width() // 2, c.y() - dlg.height() // 2)
        self.hide()
        r = dlg.exec()
        if r == QDialog.Accepted and dlg.mode in ("each", "full"):   # [보정+편집]·[전부 자동](v0.16.81) → 메인 편집 화면
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
        self.msg.setVisible(bool(t))

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
