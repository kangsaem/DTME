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
        self.prio = 0              # 디스크·GPU 자리 우선순위(작을수록 먼저, submit 이 풀에 따라 정함 — ff.Gate)

    def _emit(self, sig, *a):
        try:
            sig.emit(*a)
        except RuntimeError:      # 프로그램 종료 중(신호 객체 삭제됨)
            pass

    def run(self):
        self.started = True
        from . import ff
        ff.set_prio(self.prio)
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
    job.prio = pool_prio(pool, priority)
    _alive.add(job)
    job.signals.done.connect(lambda *_: _alive.discard(job))
    job.signals.error.connect(lambda *_: _alive.discard(job))
    pool.start(job, priority)
    return job


def pool_prio(pool: QThreadPool, priority: int = 0) -> int:
    """자리 우선순위(v0.16.24): 0 화면(멈춘 화면·스틸 등 사용자가 기다리는 것) · 1 분석 · 2 렌더 · 3 프록시 · 4 뒤에서 미리."""
    if pool is GRAB_POOL or (pool is PREVIEW_POOL and priority >= 0):
        return 0
    if pool in (AUTO_POOL, ANALYZE_POOL):
        return 1
    if pool is RENDER_POOL:
        return 2
    if pool is PROXY_POOL:
        return 3
    return 4


def bump(pool: QThreadPool, job: Job, priority: int = 10) -> bool:
    """아직 시작 안 한 작업을 맨 앞으로."""
    if job.started:
        return False
    if pool.tryTake(job):
        pool.start(job, priority)
        return True
    return False


_pools: list = []


def make_pool(n: int) -> QThreadPool:
    p = QThreadPool()
    p.setMaxThreadCount(n)
    _pools.append(p)
    return p


def shutdown(wait_ms: int = 1500) -> int:
    """종료 정리(v0.16.23): 대기열 비움 → 돌던 작업 취소 신호 → ffmpeg 모두 끔 → 잠깐 기다림. 끈 ffmpeg 개수.
    이전엔 창을 닫아도 대기열의 분석·프록시를 끝까지 처리한 뒤에야 프로그램이 끝났음(GPU 계속 사용)."""
    from . import ff
    for p in _pools:
        p.clear()
    for j in list(_alive):
        j.cancel.set()
    n = ff.kill_all()
    for p in _pools:
        p.waitForDone(max(0, wait_ms // max(1, len(_pools))))
    n += ff.kill_all()
    return n


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
PRECACHE_POOL = make_pool(1)   # v0.16.26: 렌더 다음 항목 원본 미리 읽기(우선순위 4)
DRIVE = "unknown"              # 원본 저장장치(가장 느린 것) — tune()


def tune(paths) -> tuple[int, int]:
    """원본 저장장치 종류로 동시 분석·렌더 수를 다시 정함(v0.16.19). 설정 auto_jobs/render_jobs(0 = 자동)가 있으면 그 값.
    풀 크기는 실행 중에도 바꿀 수 있음(돌던 작업은 그대로, 다음 작업부터)."""
    global AUTO_N, RENDER_N, DRIVE
    from . import drives
    from .project import get_setting
    DRIVE = drives.slowest(list(paths))
    a, r = drives.counts(DRIVE, CORES)
    try:
        a = int(get_setting("auto_jobs", 0) or 0) or a
        r = int(get_setting("render_jobs", 0) or 0) or r
    except (TypeError, ValueError):
        pass
    a, r = max(1, min(16, a)), max(1, min(3, r))
    if (a, r) != (AUTO_N, RENDER_N):
        try:
            from . import ff
            ff.log_info(f"동시 분석 {a} · 렌더 {r} (원본 {DRIVE}, 코어 {CORES})")
        except Exception:  # noqa: BLE001
            pass
    AUTO_N, RENDER_N = a, r
    AUTO_POOL.setMaxThreadCount(a)
    RENDER_POOL.setMaxThreadCount(r)
    return a, r
