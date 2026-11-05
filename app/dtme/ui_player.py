"""프리뷰 모니터. 모든 화면을 직접 그린다(재생 프레임도 QVideoSink 로 받아 그림).
- 재생: 프록시 프레임
- 정지·이동·드래그·역재생: 프록시에서 한 장씩 뽑아 즉시 표시
- 멈춘 뒤: 편집 화면이 원본 기준 보정 화면을 덮어씀(show_image)
- 세로 출력이면 잘리는 영역을 어둡게 표시
"""
from __future__ import annotations

import math
import os
from fractions import Fraction

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import ff, jobs


class Monitor(QWidget):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img: QImage | None = None
        self.text = ""
        self.out_aspect = 16 / 9       # 출력 화면비(세로 = 9/16)
        self.smooth = True

    def sizeHint(self):
        return QSize(960, 540)

    def set_image(self, img: QImage | None, smooth=True):
        self.img = img
        self.text = ""
        self.smooth = smooth
        self.update()

    def set_text(self, text: str):
        self.img = None
        self.text = text
        self.update()

    def set_aspect(self, aspect: float):
        self.out_aspect = aspect
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0e0e0e"))
        if self.img is None or self.img.isNull():
            if self.text:
                p.setPen(QColor("#9a9a9a"))
                p.drawText(self.rect(), Qt.AlignCenter, self.text)
            return
        iw, ih = self.img.width(), self.img.height()
        k = min(self.width() / iw, self.height() / ih)
        r = QRectF((self.width() - iw * k) / 2, (self.height() - ih * k) / 2, iw * k, ih * k)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.smooth)
        p.drawImage(r, self.img)
        # 출력에서 잘리는 영역
        src_aspect = r.width() / r.height()
        if abs(src_aspect - self.out_aspect) > 0.01:
            if self.out_aspect < src_aspect:
                cw = r.height() * self.out_aspect
                c = QRectF(r.center().x() - cw / 2, r.top(), cw, r.height())
                masks = [QRectF(r.left(), r.top(), c.left() - r.left(), r.height()),
                         QRectF(c.right(), r.top(), r.right() - c.right(), r.height())]
            else:
                ch = r.width() / self.out_aspect
                c = QRectF(r.left(), r.center().y() - ch / 2, r.width(), ch)
                masks = [QRectF(r.left(), r.top(), r.width(), c.top() - r.top()),
                         QRectF(r.left(), c.bottom(), r.width(), r.bottom() - c.bottom())]
            for m in masks:
                p.fillRect(m, QColor(0, 0, 0, 160))
            p.setPen(QPen(QColor(255, 255, 255, 140), 1))
            p.drawRect(c)


class Player(QWidget):
    frameChanged = Signal(int)
    playingChanged = Signal(bool)

    SPEED = 2.0     # J/L 배속 고정

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.mon = Monitor()
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.mon)

        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_video_frame)
        self.audio = None
        if not os.environ.get("DTME_NO_AUDIO"):   # 테스트 환경(사운드 장치 없음)용
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.6)
            self.player.setAudioOutput(self.audio)
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
        self._grab_busy = False
        self._grab_want: int | None = None
        self._token = 0                 # 소스가 바뀌면 증가 → 이전 소스의 늦은 결과 무시
        self.overlay_frame: int | None = None
        self.mon.set_text("영상 추가")

    # ---------------------------------------------------------------- 표시
    def show_image(self, pix: QPixmap | QImage):
        if not self.is_busy():
            self.mon.set_image(pix.toImage() if isinstance(pix, QPixmap) else pix)

    def set_aspect(self, aspect: float):
        self.mon.set_aspect(aspect)

    def _on_video_frame(self, vf):
        if self.is_playing() and vf.isValid():
            img = vf.toImage()
            if not img.isNull():
                self.mon.set_image(img, smooth=False)

    # ---------------------------------------------------------------- 로드
    def set_source(self, fps: Fraction, frames: int, proxy: str | None, frame: int = 0):
        """분석만 끝났으면 proxy=None (정지화면 모드)."""
        self.stop_all()
        self._token += 1
        self.fps, self.frames = fps, frames
        self._frame = max(0, min(frames - 1, frame)) if frames else 0
        self.proxy = proxy or ""
        self.has_media = bool(proxy)
        self.overlay_frame = None
        self.mon.set_text("로딩 중…")
        if proxy:
            self._pending_seek = self._frame
            self.player.setSource(QUrl.fromLocalFile(proxy))
            self._grab(self._frame)
        else:
            self.player.setSource(QUrl())
        self.frameChanged.emit(self._frame)

    def clear(self, text: str):
        self.stop_all()
        self._token += 1
        self.player.setSource(QUrl())
        self.has_media = False
        self.proxy = ""
        self.frames = 0
        self.mon.set_text(text)

    def _on_status(self, st):
        if st in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._pending_seek is not None:
            f = self._pending_seek
            self._pending_seek = None
            self.player.setPosition(self._ms(f))

    # ---------------------------------------------------------------- 프록시 프레임
    def _grab(self, frame: int, force=False):
        if not self.proxy:
            return
        if self._grab_busy:
            self._grab_want = frame
            return
        self._grab_busy = True
        proxy, fps, tok = self.proxy, self.fps, self._token
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))
        job.signals.done.connect(lambda data, f=frame, t=tok: self._on_grab(f, t, data))
        job.signals.error.connect(lambda _m: self._grab_done())
        jobs.submit(jobs.GRAB_POOL, job)

    def _on_grab(self, frame, tok, data):
        if tok == self._token and frame == self._frame and not self.is_playing() \
                and self.overlay_frame != frame:
            img = QImage.fromData(data, "BMP")
            if not img.isNull():
                self.mon.set_image(img, smooth=not self._back.isActive())
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
            return False
        self._back.stop()
        self.rate = rate
        self.overlay_frame = None
        self.player.setPlaybackRate(rate)
        if self.audio:
            self.audio.setMuted(rate != 1.0)
        self.player.play()
        self.playingChanged.emit(True)
        return True

    def forward(self) -> bool:  # L: 2배속 (다시 누르면 정지)
        if self.is_playing() and self.rate == self.SPEED:
            self.pause()
            return True
        return self.play(self.SPEED)

    def backward(self) -> bool:  # J: 2배속 역재생 (다시 누르면 정지)
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
        self.frameChanged.emit(self._frame)
        if self._grab_busy:
            self._grab_want = self._frame
        else:
            self._grab_back(self._frame)

    def _grab_back(self, frame):
        self._grab_busy = True
        proxy, fps, tok = self.proxy, self.fps, self._token
        job = jobs.Job(lambda: ff.grab_proxy_frame(proxy, fps, frame))

        def done(data):
            if tok == self._token and not self.is_playing():
                img = QImage.fromData(data, "BMP")
                if not img.isNull():
                    self.mon.set_image(img, smooth=False)
            self._grab_busy = False
            if self._grab_want is not None:
                f = self._grab_want
                self._grab_want = None
                (self._grab_back if self._back.isActive() else self._grab)(f)

        job.signals.done.connect(done)
        job.signals.error.connect(lambda _m: setattr(self, "_grab_busy", False))
        jobs.submit(jobs.GRAB_POOL, job)

    def pause(self):
        was = self.is_busy()
        self._back.stop()
        if self.is_playing():
            self.player.pause()
        if was:
            self.seek(self._frame)
            self.playingChanged.emit(False)

    def stop_all(self):
        self._back.stop()
        self.player.stop()
