"""프리뷰 모니터.
- 재생 중: 프록시 영상(QMediaPlayer)
- 정지·이동·드래그·역재생: 프록시에서 한 장씩 뽑아 즉시 표시(검은 화면 없음)
- 멈춘 뒤: 편집 화면이 원본 기준 보정 화면을 덮어씀(show_image)
"""
from __future__ import annotations

import math
import os
from fractions import Fraction

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedLayout, QWidget

from . import ff, jobs


class ImageView(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setStyleSheet("background:#0e0e0e; color:#999; font-size:14px;")
        self._pix: QPixmap | None = None

    def set_pix(self, pix: QPixmap | None, text: str = ""):
        self._pix = pix
        if pix is None:
            self.setPixmap(QPixmap())
            self.setText(text)
        else:
            self.setText("")
            self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def sizeHint(self):
        return QSize(960, 540)


class Player(QWidget):
    frameChanged = Signal(int)
    playingChanged = Signal(bool)

    SPEED = 2.0     # J/L 배속 고정

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.video = QVideoWidget(self)
        self.image = ImageView()
        lay = QStackedLayout(self)
        lay.addWidget(self.image)
        lay.addWidget(self.video)
        self._stack = lay

        self.player = QMediaPlayer(self)
        self.audio = None
        if not os.environ.get("DTME_NO_AUDIO"):   # 테스트 환경(사운드 장치 없음)용
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.6)
            self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_pos)
        self.player.mediaStatusChanged.connect(self._on_status)

        self.fps = Fraction(60000, 1001)
        self.frames = 0
        self._frame = 0
        self.proxy = ""
        self.has_media = False
        self._pending_seek: int | None = None
        self.rate = 1.0
        self._back = QTimer(self)
        self._back.setInterval(50)
        self._back.timeout.connect(self._back_tick)
        # 프록시 프레임 뽑기: 동시에 1개만, 밀리면 최신 요청만 처리
        self._grab_busy = False
        self._grab_want: int | None = None
        self.overlay_frame: int | None = None   # 보정 화면/샘플이 덮고 있는 프레임
        self.set_message("왼쪽 ‘영상 추가’로 4K 원본을 불러오세요\n(여러 개 선택 가능 · 창에 끌어다 놓아도 됩니다)")

    # ---------------------------------------------------------------- 표시
    def set_message(self, text: str):
        self.image.set_pix(None, text)
        self._stack.setCurrentWidget(self.image)

    def show_image(self, pix: QPixmap):
        if not self.is_busy():
            self.image.set_pix(pix)
            self._stack.setCurrentWidget(self.image)

    # ---------------------------------------------------------------- 로드
    def set_source(self, fps: Fraction, frames: int, proxy: str | None, frame: int = 0):
        """분석만 끝났으면 proxy=None (정지화면 모드)."""
        self.stop_all()
        self.fps, self.frames = fps, frames
        self._frame = max(0, min(frames - 1, frame)) if frames else 0
        self.proxy = proxy or ""
        self.has_media = bool(proxy)
        if proxy:
            self._pending_seek = self._frame
            self.player.setSource(QUrl.fromLocalFile(proxy))
            self._grab(self._frame)
        else:
            self.player.setSource(QUrl())
        self.frameChanged.emit(self._frame)

    def clear(self, text: str):
        self.stop_all()
        self.player.setSource(QUrl())
        self.has_media = False
        self.proxy = ""
        self.frames = 0
        self.set_message(text)

    def _on_status(self, st):
        if st in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._pending_seek is not None:
            f = self._pending_seek
            self._pending_seek = None
            self.player.setPosition(self._ms(f))

    # ---------------------------------------------------------------- 프록시 프레임
    def _grab(self, frame: int):
        if not self.proxy:
            return
        if self._grab_busy:
            self._grab_want = frame
            return
        self._grab_busy = True
        proxy, fps = self.proxy, self.fps
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))
        job.signals.done.connect(lambda data, f=frame, px=proxy: self._on_grab(f, px, data))
        job.signals.error.connect(lambda _m: self._grab_done())
        jobs.submit(jobs.GRAB_POOL, job)

    def _on_grab(self, frame, proxy, data):
        if proxy == self.proxy and frame == self._frame and not self.is_playing() \
                and self.overlay_frame != frame:
            img = QImage.fromData(data, "BMP")
            if not img.isNull():
                self.image.set_pix(QPixmap.fromImage(img))
                self._stack.setCurrentWidget(self.image)
        self._grab_done()

    def _grab_done(self):
        self._grab_busy = False
        if self._grab_want is not None:
            f = self._grab_want
            self._grab_want = None
            if f == self._frame:
                self._grab(f)

    # ---------------------------------------------------------------- 위치
    def _ms(self, frame: int) -> int:
        # 프레임 구간의 가운데를 지정해 반올림 오차로 이웃 프레임이 잡히지 않게
        return int((Fraction(frame) + Fraction(1, 2)) / self.fps * 1000)

    def _on_pos(self, ms: int):
        if self.is_playing():
            f = min(self.frames - 1, int(math.floor(Fraction(ms, 1000) * self.fps)))
            if f != self._frame:
                self._frame = max(0, f)
                self.frameChanged.emit(self._frame)

    @property
    def frame(self) -> int:
        return self._frame

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlayingState

    def is_busy(self) -> bool:
        return self.is_playing() or self._back.isActive()

    def seek(self, frame: int):
        if not self.frames:
            return
        frame = max(0, min(self.frames - 1, int(frame)))
        self._frame = frame
        self.overlay_frame = None
        if self.has_media:
            self.player.setPosition(self._ms(frame))
            if not self.is_playing():
                self._grab(frame)
        self.frameChanged.emit(frame)

    def step(self, d: int):
        self.pause()
        self.seek(self._frame + d)

    # ---------------------------------------------------------------- 재생
    def toggle(self) -> bool:
        if self.is_busy():
            self.pause()
            return True
        return self.play(1.0)

    def play(self, rate: float = 1.0) -> bool:
        if not self.has_media:
            return False   # 프록시 준비 전에는 재생 불가(프레임 이동은 가능)
        self._back.stop()
        self.rate = rate
        self.overlay_frame = None
        self.player.setPlaybackRate(rate)
        if self.audio:
            self.audio.setMuted(rate != 1.0)
        self._stack.setCurrentWidget(self.video)
        self.player.play()
        self.playingChanged.emit(True)
        return True

    def forward(self) -> bool:  # L: 2배속 고정 (다시 누르면 정지)
        if self.is_playing() and self.rate == self.SPEED:
            self.pause()
            return True
        return self.play(self.SPEED)

    def backward(self) -> bool:  # J: 2배속 역재생 고정 (다시 누르면 정지)
        if not self.has_media:
            return False
        if self._back.isActive():
            self.pause()
            return True
        if self.is_playing():
            self.player.pause()
        self.overlay_frame = None
        self._back.start()
        self.playingChanged.emit(True)
        return True

    def _back_tick(self):
        step = max(1, round(float(self.fps) * 0.05 * self.SPEED))
        if self._frame <= 0:
            self.pause()
            return
        self._frame = max(0, self._frame - step)
        self.player.setPosition(self._ms(self._frame))
        self._grab_force(self._frame)
        self.frameChanged.emit(self._frame)

    def _grab_force(self, frame):
        """역재생 중 표시용(재생 상태 검사 없이)."""
        if self._grab_busy:
            self._grab_want = frame
            return
        self._grab_busy = True
        proxy, fps = self.proxy, self.fps
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))

        def done(data):
            img = QImage.fromData(data, "BMP")
            if not img.isNull() and not self.is_playing():
                self.image.set_pix(QPixmap.fromImage(img))
                self._stack.setCurrentWidget(self.image)
            self._grab_busy = False
            if self._grab_want is not None:
                f = self._grab_want
                self._grab_want = None
                (self._grab_force if self._back.isActive() else self._grab)(f)

        job.signals.done.connect(done)
        job.signals.error.connect(lambda _m: setattr(self, "_grab_busy", False))
        jobs.submit(jobs.GRAB_POOL, job)

    def pause(self):
        was = self.is_busy()
        self._back.stop()
        if self.is_playing():
            self.player.pause()
        if was:
            self.seek(self._frame)   # 프레임 경계에 맞추고 정지화면으로
            self.playingChanged.emit(False)

    def stop_all(self):
        self._back.stop()
        self.player.stop()
