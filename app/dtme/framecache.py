"""프록시 프레임 RAM 캐시 — 스크럽·프레임 이동을 ffmpeg 재실행 없이 즉시.

- 프록시(640px, 예전 960px 도 그대로, 모든 프레임 키프레임)를 구간(CHUNK 프레임) 단위로 한 번에 디코딩(ffmpeg 1번 = 120장)해 메모리에 둠
- 재생 위치가 있는 구간부터 → 앞뒤로 넓혀 가며 백그라운드로 채움(가능하면 클립 전체)
- 상한(기본 = 실제 메모리의 12%, 최대 32GB — v0.16.26, 예전 25%·64GB, settings `ram_cache_gb` 로 바꿈)을 넘으면 오래 안 쓴 구간부터 비움
- 한 장 = 640×360×3 ≈ 0.7MB → 59.94fps 1분 ≈ 2.5GB (예전 960 프록시 = 1.5MB·5.6GB)
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict

import numpy as np

from . import ff, paths

CHUNK = 120                    # 구간 = 120 프레임(59.94fps 약 2초)
WINDOW = 15                    # 재생 위치 앞뒤로 먼저 채울 구간 수(약 ±30초)


def total_ram() -> int:
    """실제 메모리(바이트). 못 읽으면 8GB 로 가정."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys)
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:  # noqa: BLE001
        return 8 << 30


def cap_bytes() -> int:
    from .project import get_setting
    gb = get_setting("ram_cache_gb", None)
    if gb is not None:
        try:
            return max(0, int(float(gb) * (1 << 30)))
        except (TypeError, ValueError):
            pass
    return min(32 << 30, total_ram() * 12 // 100)       # v0.16.26: 25%·64GB → 12%·32GB(다른 프로그램 여유)


class FrameCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.chunks: "OrderedDict[tuple, np.ndarray]" = OrderedDict()   # (proxy, 구간 번호) → (n, h, w, 3) RGB
        self.size: dict[str, tuple[int, int]] = {}                      # proxy → (w, h)
        self.used = 0
        self.cap = None
        self.focus = None            # (proxy, fps, 전체 프레임 수, 현재 구간)
        self.busy: set = set()
        self.wake = threading.Event()
        self.stop = False
        self.decode_count = 0        # 점검용: ffmpeg 구간 디코딩 횟수
        n = max(1, min(4, (os.cpu_count() or 2) // 4))
        self.threads = [threading.Thread(target=self._worker, daemon=True, name=f"framecache{i}") for i in range(n)]
        for t in self.threads:
            t.start()

    # ------------------------------------------------------------ 조회
    def get(self, proxy: str, frame: int):
        """있으면 (RGB 배열 한 장, (w, h)), 없으면 None. 즉시 반환(블록 안 함)."""
        k = (proxy, frame // CHUNK)
        with self.lock:
            a = self.chunks.get(k)
            if a is None:
                return None
            self.chunks.move_to_end(k)
            i = frame - k[1] * CHUNK
            if i >= len(a):
                return None
            return a[i], self.size[proxy]

    def has(self, proxy: str, frame: int) -> bool:
        with self.lock:
            return (proxy, frame // CHUNK) in self.chunks

    def stats(self) -> tuple[int, int, int]:
        """(구간 수, 사용 바이트, 상한 바이트)"""
        with self.lock:
            return len(self.chunks), self.used, self.cap or cap_bytes()

    # ------------------------------------------------------------ 채우기 요청
    def request(self, proxy: str, fps, frames: int, frame: int):
        """재생 위치를 알려줌 → 그 구간부터 백그라운드로 채움."""
        if not proxy or frames <= 0:
            return
        if self.cap is None:
            self.cap = cap_bytes()
        if self.cap <= 0:
            return
        self.focus = (proxy, fps, frames, max(0, frame) // CHUNK)
        self.wake.set()

    def _next(self):
        """다음에 채울 구간(재생 위치에서 가까운 순). 창(±WINDOW) 밖은 메모리에 여유가 있을 때만."""
        f = self.focus
        if f is None:
            return None
        proxy, fps, frames, c0 = f
        n = (frames + CHUNK - 1) // CHUNK
        with self.lock:
            per = self._chunk_bytes(proxy)
            for d in range(n):
                for c in ((c0 + d, c0 - d) if d else (c0,)):
                    if 0 <= c < n and (proxy, c) not in self.chunks and (proxy, c) not in self.busy:
                        if d > WINDOW and self.used + per > self.cap:
                            return None        # 창 밖은 상한 안에서만
                        self.busy.add((proxy, c))
                        return proxy, fps, frames, c
        return None

    def _chunk_bytes(self, proxy):
        w, h = self.size.get(proxy, (960, 540))
        return w * h * 3 * CHUNK

    # ------------------------------------------------------------ 작업 스레드
    def _worker(self):
        while not self.stop:
            job = self._next()
            if job is None:
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            proxy, fps, frames, c = job
            try:
                arr = self._decode(proxy, fps, c, min(CHUNK, frames - c * CHUNK))
                with self.lock:
                    self.chunks[(proxy, c)] = arr
                    self.used += arr.nbytes
                    self._evict()
            except Exception as e:  # noqa: BLE001
                ff.log_error("RAM 캐시", f"{proxy} 구간 {c}: {e}")
                time.sleep(0.5)
            finally:
                with self.lock:
                    self.busy.discard((proxy, c))

    def _evict(self):
        """상한을 넘으면 오래 안 쓴 구간부터(지금 재생 위치 ±WINDOW 구간은 남김)."""
        f = self.focus
        keep = set()
        if f:
            keep = {(f[0], c) for c in range(f[3] - WINDOW, f[3] + WINDOW + 1)}
        for k in list(self.chunks):
            if self.used <= self.cap:
                break
            if k in keep:
                continue
            self.used -= self.chunks.pop(k).nbytes

    def _size_of(self, proxy):
        if proxy not in self.size:
            info = ff.probe(proxy)
            self.size[proxy] = (info["width"], info["height"])
        return self.size[proxy]

    def _decode(self, proxy, fps, c, n):
        w, h = self._size_of(proxy)
        raw = ff.run([paths.ffmpeg(), "-v", "error", "-ss", ff._seek(c * CHUNK, fps), "-i", ff._abs(proxy),
                      "-frames:v", str(n), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        self.decode_count += 1
        got = len(raw) // (w * h * 3)
        return np.frombuffer(raw[:got * w * h * 3], np.uint8).reshape(got, h, w, 3)

    def clear(self, proxy: str | None = None):
        with self.lock:
            for k in [k for k in self.chunks if proxy is None or k[0] == proxy]:
                self.used -= self.chunks.pop(k).nbytes

    def release(self):
        """렌더 시작(v0.16.26): 모두 비우고 채우기 멈춤. 편집에서 프레임을 넘기면(focus) 다시 채움."""
        with self.lock:
            self.focus = None
            self.chunks.clear()
            self.used = 0


_cache: FrameCache | None = None


def cache() -> FrameCache:
    global _cache
    if _cache is None:
        _cache = FrameCache()
    return _cache


def qimage(entry):
    """get() 결과 → QImage(복사본, 1.5MB 복사는 1ms 미만)."""
    from PySide6.QtGui import QImage
    a, (w, h) = entry
    return QImage(a.tobytes(), w, h, w * 3, QImage.Format_RGB888).copy()
