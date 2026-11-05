"""백그라운드 작업(프록시·미리보기·렌더). 화면이 멈추지 않도록 스레드 풀에서 실행."""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class JobSignals(QObject):
    progress = Signal(float)
    done = Signal(object)
    error = Signal(str)


class Job(QRunnable):
    """fn(progress_cb, cancel_event) 형태의 함수를 실행."""

    def __init__(self, fn, *, with_progress: bool = False):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress
        self.cancel = threading.Event()
        self.signals = JobSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            if self.with_progress:
                r = self.fn(self.signals.progress.emit, self.cancel)
            else:
                r = self.fn()
            self.signals.done.emit(r)
        except Exception as e:  # noqa: BLE001
            msg = str(e) or e.__class__.__name__
            if e.__class__.__name__ == "Cancelled":
                msg = "취소됨"
            else:
                traceback.print_exc()
            self.signals.error.emit(msg)


def make_pool(n: int) -> QThreadPool:
    p = QThreadPool()
    p.setMaxThreadCount(n)
    return p


_alive: set = set()


def submit(pool: QThreadPool, job: Job) -> Job:
    """작업이 끝날 때까지 참조를 유지(파이썬 GC 로 신호가 사라지는 것 방지)."""
    job.setAutoDelete(False)
    _alive.add(job)
    job.signals.done.connect(lambda *_: _alive.discard(job))
    job.signals.error.connect(lambda *_: _alive.discard(job))
    pool.start(job)
    return job


# 프록시: 1개씩(GPU 디코딩 경합 방지), 미리보기: 병렬, 렌더: 1개씩
PROXY_POOL = make_pool(1)
PREVIEW_POOL = make_pool(6)
RENDER_POOL = make_pool(1)
