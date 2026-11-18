"""시작 창(v0.16.52 틀 · v0.17.0 [AUTO] 하나): 제목 표시줄·테두리 없는 400×560, 위 = 정사각형 그림(assets/start.png)
+ 왼쪽 위 'DTME'·버전 + 오른쪽 위 ✕(종료) + 오른쪽 아래 세로 글자, 아래(#262626) = [AUTO] 160×48. 빈 곳을 끌어 옮김.
[AUTO] = 빈 자동 창(ui_autowin) · 끌어다 놓기 = 그 파일이 들어간 자동 창 · 프로젝트 파일 = 바로 편집 화면.
자동 창 [취소] = 넣은 영상 버리고 이 창으로 · 렌더 끝 [닫기] = 프로그램 종료 · 그 밖 = 편집 화면.
v0.17.3: 그림 자리 = 시작 영상(assets/start.mp4, 4초 · 소리 없음). 처음 = 첫 장면(start.png)에 멈춤 → [AUTO] = 재생(버튼 흐림),
끝나면 자동 창 · 재생 중 그림을 누르면 바로 자동 창 · 끌어다 놓기 = 재생 없이 바로 · [취소]로 돌아오면 다시 첫 장면."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from . import __version__, paths, ui_style
from .project import Project

VIDEO_EXT = {".mp4", ".mov"}
MEDIA_FILTER = ("영상·사진·음악·다이빙 기록 (*.mp4 *.MP4 *.mov *.MOV *.jpg *.JPG *.jpeg *.JPEG *.png *.PNG "
                "*.mp3 *.MP3 *.m4a *.M4A *.wav *.WAV *.flac *.FLAC *.aac *.AAC *.fit *.FIT *.zip *.json)")


def collect_media(paths) -> list[str]:
    """v0.16.72 영상·사진·음악: 파일은 그대로, 폴더는 그 안의 것(하위 폴더 제외) 이름 순."""
    from .project import AUDIO_EXT, IMAGE_EXT
    from .divelog import is_dive_file
    ok = VIDEO_EXT | IMAGE_EXT | AUDIO_EXT
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(str(f) for f in p.iterdir() if f.is_file() and (f.suffix.lower() in ok or
                                                                          (f.suffix.lower() == ".fit")))
        elif p.suffix.lower() in ok or (p.suffix.lower() in (".fit", ".zip", ".json") and is_dive_file(str(p))):
            out.append(str(p))       # v0.16.84 다이빙 기록(FIT · DTMD 백업 zip/json) 도
    return out


def collect_videos(paths) -> list[str]:
    """파일은 그대로(영상만), 폴더는 그 안의 영상(하위 폴더 제외) 이름 순."""
    return [f for f in collect_media(paths) if Path(f).suffix.lower() in VIDEO_EXT]


IMG = 400                                      # 그림 한 변(논리 px). 그림 파일은 800×800(고배율 화면용)
INTRO_MAX = 10.0                               # 시작 영상이 이 초 안에 안 끝나면(재생 안 됨 등) 그냥 자동 창으로
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
        self.player = None                          # 시작 영상 재생기(재생할 때만 만듦)
        self.playing = False
        self._show_still()
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
        # 아래: [AUTO] 하나(v0.17.0 — [편집] 없앰: 프로젝트 열기·그냥 편집 = 자동 창에서)
        self.b_auto = QPushButton("AUTO")
        self.b_auto.setFixedSize(160, 48)
        self.b_auto.setFocusPolicy(Qt.NoFocus)
        ui_style.tone(self.b_auto, "red")
        f = QFont(self.b_auto.font())
        f.setPointSizeF(f.pointSizeF() * 1.3)
        f.setBold(True)
        self.b_auto.setFont(f)
        self.b_auto.clicked.connect(self.play_intro)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.img)
        v.addStretch(1)
        v.addWidget(self.b_auto, 0, Qt.AlignHCenter)
        v.addStretch(1)

    # ------------------------------------------------------------ 시작 영상(v0.17.3)
    def _set_pix(self, pm: QPixmap):
        dpr = self.devicePixelRatioF() or 1.0
        pm = pm.scaled(round(IMG * dpr), round(IMG * dpr), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.img.setPixmap(pm)

    def _show_still(self):
        """첫 장면(start.png — 시작 영상 첫 프레임)."""
        pm = QPixmap(str(paths.asset("start.png")))
        if pm.isNull():
            self.img.setStyleSheet("background:#3a3a3a;")
        else:
            self._set_pix(pm)

    def play_intro(self):
        """[AUTO] = 시작 영상 재생 → 끝나면 자동 창. 영상이 없거나 재생이 안 되면 바로 자동 창."""
        import os
        if self.playing:
            return
        clip = paths.asset("start.mp4")
        if not clip.exists() or os.environ.get("DTME_NO_INTRO"):
            self.run_auto([])
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        except Exception:  # noqa: BLE001 — 재생 모듈 없음 = 바로
            self.run_auto([])
            return
        self.playing = True
        self.b_auto.setEnabled(False)
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)            # 소리 출력 없음(영상에 소리도 없음)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.mediaStatusChanged.connect(
            lambda st: self._intro_done() if st in (QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia) else None)
        self.player.errorOccurred.connect(lambda *_a: self._intro_done())
        self._guard = QTimer(self)
        self._guard.setSingleShot(True)
        self._guard.timeout.connect(self._intro_done)
        self._guard.start(int(INTRO_MAX * 1000))
        self.player.setSource(QUrl.fromLocalFile(str(clip)))
        self.player.play()

    def _frame(self, fr):
        if not self.playing:
            return
        im = fr.toImage()
        if not im.isNull():
            self._set_pix(QPixmap.fromImage(im))

    def _intro_done(self):
        """재생 끝 · 그림 누름 · 오류 · 시간 넘음 → (한 번만) 자동 창."""
        if not self.playing:
            return
        self.playing = False
        self._guard.stop()
        pl, self.player = self.player, None
        if pl is not None:
            try:
                pl.stop()
            except RuntimeError:
                pass
            pl.deleteLater()
        QTimer.singleShot(0, self._after_intro)

    def _after_intro(self):
        self.run_auto([])
        if self.isVisible():                            # [취소]로 돌아옴 = 다시 첫 장면에 멈춤
            self._show_still()
            self.b_auto.setEnabled(True)

    def _style(self, hot):
        self.setStyleSheet("#Launcher{background:#262626; border:none;}" if not hot else
                           "#Launcher{background:#262a30; border:2px dashed #4a8fe0;}")     # 끌어 놓는 동안만 점선

    # ------------------------------------------------------------ 빈 곳을 끌어 옮김(제목 표시줄이 없음)
    def mousePressEvent(self, e):
        if self.playing and e.button() == Qt.LeftButton and self.img.geometry().contains(e.position().toPoint()):
            self._intro_done()                          # 재생 중 그림 누름 = 바로 자동 창
            return
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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
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
        """[AUTO] = 빈 자동 창 / 끌어다 놓기 = 그 파일이 들어간 자동 창. 프로젝트 파일 = 바로 편집 화면.
        자동 창 결과: 편집 화면으로 · 닫기(렌더 끝) = 종료 · 취소 = 넣은 영상 버리고 이 창으로."""
        from .ui_autowin import is_project_file
        mw = self.mw
        proj = next((f for f in paths if is_project_file(f)), None)
        if proj:
            mw.state.set_project(Project())
            mw._load(proj)
            self._to_editor()
            return
        mw.state.set_project(Project())             # 시작 창 AUTO = 늘 새 작업
        mw.state.defer_proxy = True                 # AUTO 전 = 파일 정보만(프록시는 AUTO 뒤)
        dlg = mw.edit.make_auto_window(from_edit=False)
        c = self.geometry().center()
        dlg.move(c.x() - dlg.width() // 2, c.y() - dlg.height() // 2)
        if paths:
            dlg.add_paths(list(paths))
            if dlg.outcome == "edit":               # 끌어다 놓은 것이 프로젝트였음
                self._to_editor()
                return
        self.hide()
        self._auto_dlg = dlg
        dlg.exec()
        if dlg.outcome == "edit":
            self._to_editor()
        elif dlg.outcome == "close":                # 렌더 끝 [닫기]
            self._quit()
        else:                                       # [취소] = 넣은 영상 버림
            mw.state.defer_proxy = False
            mw.state.set_project(Project())
            self.show()
            from . import taskbar
            taskbar.front(self)

    def _to_editor(self):
        mw = self.mw
        mw.state.resume_proxies()
        mw.show()
        mw.raise_()
        self.close()
        mw.edit.after_auto()

    def _quit(self):
        from PySide6.QtWidgets import QApplication
        self.hide()
        QApplication.quit()
