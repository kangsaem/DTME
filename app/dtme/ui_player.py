"""프록시 재생기. 내부 위치는 항상 '원본 프레임 번호'로 다룬다."""
from __future__ import annotations

import math
import os
from fractions import Fraction

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget
from PySide6.QtCore import Qt


class Player(QWidget):
    frameChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video = QVideoWidget(self)
        self.msg = QLabel("왼쪽 목록에서 영상을 선택하세요", self)
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setStyleSheet("color:#aaa; background:#111; font-size:14px;")
        lay = QStackedLayout(self)
        lay.addWidget(self.msg)
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
        self._pending_seek: int | None = None
        self.rate = 1.0
        self._back_speed = 0
        self._back_timer = QTimer(self)
        self._back_timer.setInterval(50)
        self._back_timer.timeout.connect(self._back_tick)

    # ---------------------------------------------------------------- 로드
    def load(self, proxy: str, fps: Fraction, frames: int, start_frame: int = 0):
        self.stop_all()
        self.fps, self.frames = fps, frames
        self._frame = start_frame
        self._pending_seek = start_frame
        self.player.setSource(QUrl.fromLocalFile(proxy))
        self._stack.setCurrentWidget(self.video)

    def show_message(self, text: str):
        self.stop_all()
        self.player.setSource(QUrl())
        self.msg.setText(text)
        self._stack.setCurrentWidget(self.msg)

    def _on_status(self, st):
        if st in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._pending_seek is not None:
            f = self._pending_seek
            self._pending_seek = None
            self.seek(f)

    # ---------------------------------------------------------------- 위치
    def _ms(self, frame: int) -> int:
        # 프레임 구간의 가운데를 지정해 반올림 오차로 이웃 프레임이 잡히지 않게
        return int((Fraction(frame) + Fraction(1, 2)) / self.fps * 1000)

    def _on_pos(self, ms: int):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            f = min(self.frames - 1, int(math.floor(Fraction(ms, 1000) * self.fps)))
            if f != self._frame:
                self._frame = max(0, f)
                self.frameChanged.emit(self._frame)

    @property
    def frame(self) -> int:
        return self._frame

    def seek(self, frame: int):
        frame = max(0, min(self.frames - 1, int(frame))) if self.frames else 0
        self._frame = frame
        self.player.setPosition(self._ms(frame))
        self.frameChanged.emit(frame)

    def step(self, d: int):
        self.pause()
        self.seek(self._frame + d)

    # ---------------------------------------------------------------- 재생 (J/K/L)
    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState or self._back_timer.isActive():
            self.pause()
        else:
            self.play(1.0)

    def play(self, rate: float = 1.0):
        self._back_timer.stop()
        self._back_speed = 0
        self.rate = rate
        self.player.setPlaybackRate(rate)
        if self.audio:
            self.audio.setMuted(rate != 1.0)
        self.player.play()

    def forward(self):  # L
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.play(min(8.0, self.rate * 2))
        else:
            self.play(1.0)

    def backward(self):  # J — 역재생은 탐색 반복으로 구현
        self.player.pause()
        self._back_speed = min(8, max(1, self._back_speed * 2))
        self._back_timer.start()

    def _back_tick(self):
        step = max(1, round(float(self.fps) * 0.05 * self._back_speed))
        if self._frame <= 0:
            self.pause()
            return
        self.seek(self._frame - step)

    def pause(self):  # K
        self._back_timer.stop()
        self._back_speed = 0
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            # 정지 위치를 프레임 경계에 맞춤
            self.seek(self._frame)

    def stop_all(self):
        self._back_timer.stop()
        self.player.stop()
