"""백그라운드 작업(분석·프록시·미리보기·렌더). 화면이 멈추지 않도록 스레드 풀에서 실행."""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class JobSignals(QObject):
    progress = Signal(float)
    done = Signal(object)
    error = Signal(str)


class Job(QRunnable):
    """fn() 또는 fn(progress_cb, cancel_event) 실행."""

    def __init__(self, fn, *, with_progress: bool = False):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress
        self.cancel = threading.Event()
        self.signals = JobSignals()
        self.started = False

    def _emit(self, sig, *a):
        try:
            sig.emit(*a)
        except RuntimeError:      # 프로그램 종료 중(신호 객체 삭제됨)
            pass

    def run(self):
        self.started = True
        try:
            r = self.fn(lambda v: self._emit(self.signals.progress, v), self.cancel) if self.with_progress else self.fn()
            self._emit(self.signals.done, r)
        except Exception as e:  # noqa: BLE001
            msg = str(e) or e.__class__.__name__
            if e.__class__.__name__ == "Cancelled":
                msg = "취소됨"
            else:
                traceback.print_exc()
            self._emit(self.signals.error, msg)


_alive: set = set()


def submit(pool: QThreadPool, job: Job, priority: int = 0) -> Job:
    """작업이 끝날 때까지 참조를 유지(파이썬 GC 로 신호가 사라지는 것 방지)."""
    job.setAutoDelete(False)
    _alive.add(job)
    job.signals.done.connect(lambda *_: _alive.discard(job))
    job.signals.error.connect(lambda *_: _alive.discard(job))
    pool.start(job, priority)
    return job


def bump(pool: QThreadPool, job: Job, priority: int = 10) -> bool:
    """아직 시작 안 한 작업을 맨 앞으로."""
    if job.started:
        return False
    if pool.tryTake(job):
        pool.start(job, priority)
        return True
    return False


def make_pool(n: int) -> QThreadPool:
    p = QThreadPool()
    p.setMaxThreadCount(n)
    return p


def _cores() -> int:
    import os
    return os.cpu_count() or 4


CORES = _cores()
RENDER_N = max(1, min(3, CORES // 16))     # 동시 렌더: 코어 16개당 1개(1~3, NVENC 인코더 수 한계로 최대 3)
AUTO_N = max(2, min(4, CORES // 8))        # 동시 분석(샘플 추출): 코어 8개당 1개(2~4) — v0.16.18: 8 → 4 (SD카드·HDD 동시 읽기 막힘 방지)

ANALYZE_POOL = make_pool(4)   # ffprobe
PROXY_POOL = make_pool(2)     # 동시에 2개(사용자 PC 32코어·RTX 4090 기준, 2026-11-06)
PREVIEW_POOL = make_pool(4)
GRAB_POOL = make_pool(2)      # 프록시 프레임 즉시 표시
RENDER_POOL = make_pool(RENDER_N)
AUTO_POOL = make_pool(AUTO_N)  # AUTO·추천: 샘플 추출
