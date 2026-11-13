"""FFmpeg 처리: 분석, 프록시, 필터 체인, 렌더, 스틸, 미리보기, 선명도."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from fractions import Fraction
from pathlib import Path
from typing import Callable

from . import paths
from .project import (CURVE_KEY, KEYABLE, OUT_FPS, ImageSource, Marker, Project, Segment, Source, apply_off, grade_at, layer_box,
                      orig_volume, plan_transitions, reframe_max)

NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # Windows 콘솔창 숨김
LOW_PRIO = 0    # v0.16.24: 보통 우선순위(사용자). v0.16.14~23 은 BELOW_NORMAL(0x4000)

def denoise_chain(g: dict) -> list[str]:
    """F안: 밝기·색을 따로. 색은 시간축 평균을 강하게 + 색 채널만 미디언(튀는 점 제거).
    hqdn3d 는 0 을 '기본값(4)'으로 처리하므로 0 대신 아주 작은 값."""
    c = max(0.0, min(100.0, float(g.get("nr_chroma", 0))))
    lu = max(0.0, min(100.0, float(g.get("nr_luma", 0))))
    f = []
    if c > 0 or lu > 0:
        ls, lt = max(0.01, lu * 0.04), max(0.01, lu * 0.08)
        cs, ct = max(0.01, c * 0.05), max(0.01, c * 0.133)
        f.append(f"hqdn3d={ls:.2f}:{cs:.2f}:{lt:.2f}:{ct:.2f}")
    if c >= 40:
        f.append(f"median=radius={2 if c >= 85 else 1}:planes=6")
    return f


def sharpen_chain(g: dict, width: int = 1920) -> list[str]:
    """밝기(Y)에만 언샤프 → 색 노이즈를 날카롭게 만들지 않음.
    디헤이즈는 v0.16.2 에서 뺌: unsharp 가 10bit 에서 효과를 몇 단계 정수로만 더해 완만한 물빛에 계단(실측 7.8/255)을 만들었음.
    옛 프로젝트의 dehaze 값은 무시."""
    f = []
    s = float(g.get("sharpen", 0))
    if s > 1e-3:
        f.append(f"unsharp=5:5:{min(2.0, s * 2):.3f}:5:5:0")
    return f


LENS_K1 = 0.15      # 렌즈 보정 100 일 때 왜곡 계수(+ = 외곽을 안쪽으로 당김)


def lens_chain(g: dict, w: int = 0, h: int = 0) -> list[str]:
    """액션캠 외곽 늘어짐 줄이기(원본 크기에서, 크롭·축소 전). 외곽을 안쪽으로 당기고(k1 > 0),
    생기는 검은 모서리는 가운데를 1+k1 배로 살짝 확대해 잘라냄. w·h = 들어오는 화면 크기(정확히 원래 크기로 되돌림).
    v0.15.3 까지는 반대 방향(k1 < 0, 외곽을 더 늘림)이었음 — 사용자 지적으로 수정(격자 실측)."""
    v = float(g.get("lens", 0))
    if v < 0.5:
        return []
    k1 = LENS_K1 * v / 100
    z = 1.0 + k1                          # 크롭 모서리 r0/z → 원본 r0(1+k1/z²)/z < r0 : 검은 부분 없음
    f = [f"lenscorrection=k1={k1:.4f}:k2=0:i=bilinear"]
    if w and h:
        cw, ch = int(w / z) // 2 * 2, int(h / z) // 2 * 2
        f += [f"crop={cw}:{ch}:{(w - cw) // 2}:{(h - ch) // 2}", f"scale={w}:{h}:flags=bicubic"]
    else:
        f += [f"crop=trunc(iw/{z:.5f}/2)*2:trunc(ih/{z:.5f}/2)*2", f"scale=iw*{z:.5f}:ih*{z:.5f}:flags=bicubic"]
    return f


# RGB → YUV 변환 시 BT.709 를 명시하지 않으면 BT.601 로 변환돼 색이 틀어진다(실측 평균 4.8 → 2.5 차이).
TO_YUV709 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ 종료 정리(v0.16.23)
# 창을 닫아도 대기열의 분석·프록시가 끝까지 돌며 GPU 를 쓰던 문제 → 실행 중인 ffmpeg 를 모아 두고 종료 때 끔.
# Windows 는 작업 묶음(Job Object, 닫히면 안의 프로세스 모두 종료)에도 넣음 → DTME 가 갑자기 죽어도 ffmpeg 가 남지 않음.
_live: set = set()
_live_lock = threading.Lock()
_closing = threading.Event()
_job_handle = None


def _win_job():
    """KILL_ON_JOB_CLOSE 작업 묶음 하나(프로세스가 끝나면 Windows 가 핸들을 닫고 → 안의 ffmpeg 종료)."""
    global _job_handle
    if _job_handle is not None or os.name != "nt":
        return _job_handle
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        h = k.CreateJobObjectW(None, None)
        if not h:
            return None
        info = EXT()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):   # 9 = Extended
            return None
        _job_handle = h
    except Exception:  # noqa: BLE001
        _job_handle = None
    return _job_handle


def _attach(p) -> None:
    h = _win_job()
    if not h:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject(h, wintypes.HANDLE(int(p._handle)))
    except Exception:  # noqa: BLE001
        pass


def kill_all() -> int:
    """종료 중 표시 + 실행 중인 ffmpeg·ffprobe 모두 끔. 끈 개수."""
    _closing.set()
    with _live_lock:
        ps = list(_live)
    n = 0
    for p in ps:
        try:
            if p.poll() is None:
                p.kill()
                n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def live_count() -> int:
    with _live_lock:
        return sum(1 for p in list(_live) if p.poll() is None)


class FFError(Exception):
    pass


# ------------------------------------------------------------------ 작업 자리(v0.16.24): 같은 저장장치·GPU 를 동시에 쓰는 ffmpeg 수 제한
# 이전: 풀(분석·프록시·미리보기·…)마다 따로 세서 HDD 하나를 최대 14개가 동시에 읽음 → 헤드가 오가며 모두 느려짐(사용자 로그: 판정 9.5 → 116초).
# 이제: ffmpeg 입력 파일의 저장장치마다 자리 수(HDD·SD 2 / 모름 4 / SSD 8, 설정 disk_jobs) + GPU 쓰는 ffmpeg 자리(설정 gpu_jobs, 기본 2).
# 자리가 나면 우선순위 높은 작업부터: 0 화면(멈춘 화면·스틸) · 1 분석 · 2 렌더 · 3 프록시 · 4 뒤에서 미리.
# 화면 스레드(메인)에서 부른 ffmpeg 는 기다리지 않음(화면 멈춤 방지).
import heapq
import itertools
import time as _time

_ctx = threading.local()            # prio · waited(이 스레드가 자리를 기다린 시간 합)
DISK_SLOTS = {"hdd": 2, "removable": 2, "unknown": 4, "ssd": 8}
GPU_SLOTS = 6               # v0.16.26: 조각 렌더(2 → 6). 설정 gpu_jobs. GPU 인코더 개수 제한에 걸리면 nvenc_max 로 줄여 기억


def set_prio(p: int) -> None:
    _ctx.prio = p


def waited() -> float:
    return getattr(_ctx, "waited", 0.0)


class Gate:
    """우선순위 자리표. slot() 안에서만 ffmpeg 실행."""

    def __init__(self, name: str, n: int):
        self.name, self.n, self.used = name, n, 0
        self.cv = threading.Condition()
        self.q: list = []
        self._seq = itertools.count()

    def acquire(self, prio: int) -> None:
        t = (prio, next(self._seq))
        t0 = _time.monotonic()
        with self.cv:
            heapq.heappush(self.q, t)
            try:
                while not (self.used < self.n and self.q[0] == t):
                    if _closing.is_set():
                        raise Cancelled()
                    self.cv.wait(0.25)
            except BaseException:
                self.q.remove(t)
                heapq.heapify(self.q)
                self.cv.notify_all()
                raise
            heapq.heappop(self.q)
            self.used += 1
            self.cv.notify_all()
        _ctx.waited = waited() + (_time.monotonic() - t0)

    def release(self) -> None:
        with self.cv:
            self.used -= 1
            self.cv.notify_all()


_gates: dict = {}
_gates_lock = threading.Lock()


def _setting_int(key: str, default: int) -> int:
    try:
        from .project import get_setting
        return int(get_setting(key, 0) or 0) or default
    except Exception:  # noqa: BLE001
        return default


def _disk_id(path: str) -> tuple[str, str] | None:
    """(장치 이름, 종류). 파일이 아니면 None."""
    try:
        if not os.path.isfile(path):
            return None
        from . import drives
        did = drives._drive_root(path) if os.name == "nt" else str(os.stat(path).st_dev)
        return did, drives.kind(path)
    except Exception:  # noqa: BLE001
        return None


def _gate(key: str, n: int) -> Gate:
    """자리 수는 부를 때마다 설정값으로(실행 중 바꿔도 다음 ffmpeg 부터)."""
    with _gates_lock:
        g = _gates.get(key)
        if g is None:
            g = _gates[key] = Gate(key, n)
    if g.n != n:
        with g.cv:
            g.n = n
            g.cv.notify_all()
    return g


def _gates_for(cmd) -> list:
    """이 ffmpeg 가 차지할 자리들(정해진 순서 = 서로 기다리며 멈추는 일 없음): GPU → 저장장치들."""
    if threading.current_thread() is threading.main_thread():
        return []
    cmd = list(cmd)
    out = []
    if "-hwaccel" in cmd or any(str(c).endswith("_nvenc") for c in cmd):
        out.append(_gate("gpu", gpu_cap()))
    disks = {}
    for i, c in enumerate(cmd[:-1]):
        if c == "-i" and not (i >= 2 and cmd[i - 2] == "-f" and cmd[i - 1] == "lavfi"):
            if is_precached(str(cmd[i + 1])):          # 미리 읽어 메모리에 있음 = 저장장치 자리 안 잡음(v0.16.26)
                continue
            d = _disk_id(str(cmd[i + 1]))
            if d:
                disks[d[0]] = d[1]
    for did in sorted(disks):
        out.append(_gate("disk:" + did, _setting_int("disk_jobs", DISK_SLOTS.get(disks[did], 4))))
    return out


def gpu_cap() -> int:
    """GPU 쓰는 ffmpeg 동시 최대 = min(설정 gpu_jobs(기본 6), 기억한 인코더 한계 nvenc_max)."""
    n = _setting_int("gpu_jobs", GPU_SLOTS)
    m = _setting_int("nvenc_max", 0)
    return max(1, min(n, m) if m else n)


NVENC_LIMIT_ERR = ("OpenEncodeSessionEx", "incompatible client key", "out of memory", "No NVENC capable",
                   "Cannot init CUDA", "CUDA_ERROR_OUT_OF_MEMORY")


def nvenc_limited(msg: str) -> bool:
    return any(k.lower() in msg.lower() for k in NVENC_LIMIT_ERR)


def lower_gpu_cap(running: int) -> int:
    """GPU 인코더 동시 개수 한계에 걸림 → 지금 돌던 수 - 1 로 줄여 기억(settings nvenc_max). 새 한계."""
    from .project import set_setting
    with _gates_lock:
        cur = gpu_cap()
        new = max(1, min(cur, running) - 1) if running > 1 else 1
        if new < cur:
            try:
                set_setting("nvenc_max", new)
            except Exception:  # noqa: BLE001
                pass
            log_info(f"GPU 인코더 동시 한계 → {new}개로 줄여 기억(settings nvenc_max, 지우면 다시 {GPU_SLOTS})")
        return new


# ------------------------------------------------------------------ 미리 읽기(v0.16.26): HDD·SD 원본을 순서대로 한 번 읽어 Windows 캐시에
# 렌더(조각 여러 개가 동시에 읽음)가 HDD 를 헤드 왕복 없이 메모리에서 읽게. 지금 렌더 + 다음 항목, 합계 precache_gb(기본 32GB) 까지.
# Windows 파일 캐시('캐시됨'·대기 메모리) = 다른 프로그램이 필요하면 바로 내줌. 한계를 넘는 파일은 미리 읽지 않음(그냥 HDD 에서).
PRECACHE_GB = 32
_pre: "dict[str, int]" = {}          # 경로 → 읽은 바이트(넣은 순서 = 오래된 것부터)
_pre_lock = threading.Lock()
_pre_disk_locks: dict = {}            # 장치마다 미리 읽기는 하나씩(순서대로 읽어야 빠름)


def is_precached(path: str) -> bool:
    with _pre_lock:
        return os.path.abspath(path) in _pre


def precache(path: str, frac_a: float = 0.0, frac_b: float = 1.0, cancel=None) -> bool:
    """path 의 [frac_a, frac_b] 부분(+ 앞뒤 머리 정보)을 순서대로 읽음. HDD·SD 만. 반환 = 메모리에 있다고 봄."""
    path = os.path.abspath(path)
    if is_precached(path):
        return True
    d = _disk_id(path)
    if not d or d[1] not in ("hdd", "removable"):
        return False
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    budget = _setting_int("precache_gb", PRECACHE_GB) << 30
    margin = 32 << 20
    a = max(0, int(size * max(0.0, frac_a)) - margin)
    b = min(size, int(size * min(1.0, frac_b)) + margin)
    spans = [(0, min(size, 4 << 20)), (a, b), (max(0, size - (16 << 20)), size)]     # 앞 머리 · 구간 · 끝(moov)
    need = sum(y - x for x, y in spans)
    if need > budget:
        log_info(f"미리 읽기 건너뜀 {Path(path).name}: {need >> 20}MB > 한계 {budget >> 30}GB")
        return False
    with _pre_lock:
        lk = _pre_disk_locks.setdefault(d[0], threading.Lock())
    t0, w0 = _time.monotonic(), waited()
    with lk:
        if is_precached(path):
            return True
        g = _gate("disk:" + d[0], _setting_int("disk_jobs", DISK_SLOTS.get(d[1], 4)))
        g.acquire(getattr(_ctx, "prio", 0))
        try:
            got = 0
            buf = bytearray(8 << 20)
            with open(path, "rb", buffering=0) as f:
                for x, y in spans:
                    f.seek(x)
                    pos = x
                    while pos < y:
                        if _closing.is_set() or (cancel is not None and cancel.is_set()):
                            raise Cancelled()
                        n = f.readinto(memoryview(buf)[:min(len(buf), y - pos)])
                        if not n:
                            break
                        pos += n
                        got += n
        finally:
            g.release()
    sec = _time.monotonic() - t0
    with _pre_lock:
        _pre[path] = got
        while sum(_pre.values()) > budget and len(_pre) > 1:
            _pre.pop(next(iter(_pre)))
    log_info(f"미리 읽기 {Path(path).name}: {got >> 20}MB {sec:.1f}초 ({(got >> 20) / max(0.01, sec):.0f}MB/s, 자리 대기 {waited() - w0:.1f}초)")
    return True


def precache_forget(path: str | None = None) -> None:
    with _pre_lock:
        if path is None:
            _pre.clear()
        else:
            _pre.pop(os.path.abspath(path), None)


class _slots:
    def __init__(self, cmd):
        self.gs = _gates_for(cmd)
        self.got = []

    def __enter__(self):
        prio = getattr(_ctx, "prio", 0)
        try:
            for g in self.gs:
                g.acquire(prio)
                self.got.append(g)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *a):
        for g in reversed(self.got):
            g.release()
        self.got = []


# ------------------------------------------------------------------ 실행
def _popen(cmd, **kw):
    """ffmpeg 이 키 입력(stdin)을 기다리며 멈추는 일 방지(Windows GUI 에서 렌더가 멈추던 원인): -nostdin + 입력 차단."""
    cmd = list(cmd)
    if Path(cmd[0]).stem.lower() == "ffmpeg" and "-nostdin" not in cmd:
        cmd.insert(1, "-nostdin")
    kw.setdefault("stdin", subprocess.DEVNULL)
    import time
    for i in range(12):      # WinError 32(백신이 ffmpeg.exe 를 잠깐 잡음 등) → 0.2초 간격 다시 시도. 화면에 '미리보기 오류'가 자주 뜨던 원인
        if _closing.is_set():                # 종료 중 = 새 ffmpeg 안 띄움(v0.16.23)
            raise Cancelled()
        try:
            p = subprocess.Popen(cmd, creationflags=NO_WINDOW | LOW_PRIO, **kw)
            with _live_lock:
                for q in [q for q in _live if q.returncode is not None or q.poll() is not None]:
                    _live.discard(q)          # 끝난 것 정리
                _live.add(p)
            _attach(p)
            if _closing.is_set():            # 띄우는 사이 종료 시작
                p.kill()
            return p
        except OSError as e:
            if getattr(e, "winerror", None) not in (32, 33) or i == 11:
                raise
            time.sleep(0.2)


def run(cmd: list[str], cwd: str | None = None, data: bytes | None = None) -> bytes:
    """data 가 있으면 stdin 으로 넘김(미리보기: 디스크 파일 없이)."""
    with _slots(cmd):
        if data is not None:
            p = _popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(data)
        else:
            p = _popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
    if p.returncode != 0:
        if _closing.is_set():
            raise Cancelled()
        raise FFError(err.decode("utf-8", "replace")[-2000:])
    return out


def run_progress(cmd: list[str], total_sec: float, on_progress: Callable[[float], None] | None = None,
                 cancel: threading.Event | None = None, cwd: str | None = None) -> None:
    """-progress pipe:1 로 진행률(0~1)을 보고하며 실행."""
    cmd = [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1"] + cmd[1:]
    with _slots(cmd):
        _run_progress(cmd, total_sec, on_progress, cancel, cwd)


def _run_progress(cmd, total_sec, on_progress, cancel, cwd) -> None:
    errf = tempfile.TemporaryFile()
    p = _popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=errf, text=True)
    try:
        for line in p.stdout:
            if cancel is not None and cancel.is_set():
                p.kill()
                raise Cancelled()
            if line.startswith("out_time_us=") and on_progress and total_sec > 0:
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(1.0, us / 1e6 / total_sec))
                except ValueError:
                    pass
        p.wait()
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode != 0:
        if _closing.is_set():
            raise Cancelled()
        errf.seek(0)
        raise FFError(errf.read().decode("utf-8", "replace")[-2000:])
    if on_progress:
        on_progress(1.0)


def replace_retry(src, dst, tries: int = 60) -> None:
    """Windows 에서 백신·색인 등이 방금 만든 파일을 잠깐 잡고 있으면 이름 바꾸기가 WinError 32 로 실패한다 → 재시도."""
    import time
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1 if i < 20 else 0.3)


LOG_MAX = 2 << 20
_dbg_last = ["", 0]


def dbg(msg: str) -> None:
    """진단 기록(v0.16.43, 미리보기가 안 바뀌는 문제 추적용 — 원인을 찾으면 뺌). 같은 줄이 이어지면 횟수만."""
    if msg == _dbg_last[0]:
        _dbg_last[1] += 1
        if _dbg_last[1] % 50:
            return
        msg = f"{msg} (×{_dbg_last[1]})"
    else:
        _dbg_last[:] = [msg, 0]
    log_error("진단", f"[{threading.current_thread().name}] {msg}")


def log_trim() -> None:
    """시작할 때 한 번: 기록(cache/dtme.log)이 2MB 를 넘으면 뒤 절반만 남김(계속 쌓이기만 하던 것, v0.16.40)."""
    try:
        f = paths.cache_dir() / "dtme.log"
        if f.exists() and f.stat().st_size > LOG_MAX:
            b = f.read_bytes()[-LOG_MAX // 2:]
            f.write_bytes(b[b.find(b"\n") + 1:])
    except Exception:  # noqa: BLE001
        pass


def log_error(where: str, msg: str) -> None:
    try:
        import time
        with open(paths.cache_dir() / "dtme.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {where}: {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def log_info(msg: str) -> None:
    """속도 기록 등(cache/dtme.log)."""
    log_error("정보", msg)


def _abs(p) -> str:
    """LUT 때문에 cwd 를 바꾸므로 모든 파일 경로는 절대 경로로."""
    return os.path.abspath(str(p))


def _hw(gpu: bool) -> list[str]:
    """GPU 디코딩. v0.16.24: 4K 원본을 길게 읽는 작업(렌더·원본 프록시·흔들림 분석·원본 구간 캐시)에만.
    사진 1장·작은 영상은 CPU(ffmpeg 마다 CUDA 준비 비용이 더 크고 화면이 끊기던 원인으로 추정)."""
    return ["-hwaccel", "cuda"] if gpu and has_cuda() else []      # v0.16.48: NVIDIA 가 없으면 CPU 디코딩(헛도는 시도 없이)


def _seek(frame: float, fps: Fraction) -> str:
    """프레임 n 을 정확히 잡기 위해 (n-0.5)/fps 로 탐색."""
    return f"{max(0.0, float((Fraction(frame) - Fraction(1, 2)) / fps)):.6f}"


# ------------------------------------------------------------------ 분석
def _rot_wh(v: dict) -> tuple[int, int, int]:
    """ffprobe 영상 스트림 → (폭, 높이, 회전°). 세로로 찍은 영상(회전 정보 ±90°, v0.16.50 Insta360 Ace Pro 2)은
    ffmpeg 이 읽을 때 돌려 주므로 실제 화면 = 폭·높이가 바뀐 것."""
    w, h, rot = int(v["width"]), int(v["height"]), 0
    for sd in v.get("side_data_list") or []:
        try:
            rot = int(round(float(sd.get("rotation", 0)))) if "rotation" in sd else rot
        except (TypeError, ValueError):
            pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    return w, h, rot


def probe(path: str) -> dict:
    out = run([paths.ffprobe(), "-v", "error", "-print_format", "json",
               "-show_streams", "-show_format", path])
    d = json.loads(out)
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    if v is None:
        raise FFError("영상 스트림이 없습니다.")
    num, den = (int(x) for x in v.get("r_frame_rate", "60000/1001").split("/"))
    anum, aden = (int(x) for x in (v.get("avg_frame_rate") or f"{num}/{den}").split("/"))
    fps = Fraction(num, den)
    dur = float(v.get("duration") or d["format"].get("duration") or 0)
    frames = int(v.get("nb_frames") or 0) or int(round(dur * float(fps)))
    vfr = aden != 0 and abs(float(Fraction(anum, aden)) - float(fps)) > 0.01
    w, h, rot = _rot_wh(v)
    return {
        "fps_num": num, "fps_den": den, "frames": frames,
        "width": w, "height": h, "rotation": rot,
        "has_audio": any(s.get("codec_type") == "audio" for s in d["streams"]),
        "pix_fmt": v.get("pix_fmt", ""), "codec": v.get("codec_name", ""),
        "vfr": vfr, "duration": dur,
        "color_mode": (lambda m: m if m != "unknown" else insta_color_mode(path))(dji_color_mode(path, d)),
        "ctime": _ctime12((d.get("format", {}).get("tags") or {}).get("creation_time", "")),
        "cutc": utc_secs((d.get("format", {}).get("tags") or {}).get("creation_time", "")),
    }


def utc_secs(t: str) -> float:
    """파일 안의 만든 시각(UTC) → 초(epoch). 없음·이상한 값 = 0. (v0.16.86 수심 그래프 UTC 맞추기)"""
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(t.strip()[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return 0.0 if dt.year < 2005 else dt.timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _ctime12(t: str) -> str:
    """파일 안의 만든 시각(UTC '2026-06-25T02:35:25.000000Z') → 현지 시간 YYYYMMDDhhmm. 없음·이상한 값(1904·1970 등) = ''."""
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(t.strip()[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if dt.year < 2005:
            return ""
        return dt.astimezone().strftime("%Y%m%d%H%M")
    except Exception:  # noqa: BLE001
        return ""


def aae_trim(path: str):
    """아이폰 사진 앱 편집 기록(.AAE, 영상 옆에 같이 옴)의 자르기 구간 → (시작 초, 끝 초). 없음·못 읽음 = None.
    짝: 같은 이름.AAE · IMG_1234 → IMG_O1234.AAE. 자르기 말고 다른 편집(색·필터)은 안 읽음."""
    import plistlib
    import re
    import zlib
    p = Path(path)
    names = [p.stem + e for e in (".AAE", ".aae")]
    m = re.match(r"^(IMG_)E?(\d+)$", p.stem, re.I)
    if m:
        names += [f"{m.group(1)}O{m.group(2)}{e}" for e in (".AAE", ".aae")]
    f = next((p.parent / n for n in names if (p.parent / n).is_file()), None)
    if f is None:
        return None
    try:
        with open(f, "rb") as fh:
            raw = plistlib.load(fh).get("adjustmentData")
        d = None
        for wbits in (-15, 15, 31):
            try:
                d = json.loads(zlib.decompress(raw, wbits))
                break
            except Exception:  # noqa: BLE001
                continue
        if d is None:
            d = json.loads(raw)
        for a in d.get("adjustments", []):
            if a.get("identifier") == "Trim" and a.get("enabled", True):
                st = a.get("settings", {})
                sec = lambda k: float(st[k]["value"]) / float(st[k].get("timescale") or 1)   # noqa: E731
                t0, t1 = sec("startTime"), sec("endTime")
                if t1 > t0 >= 0:
                    return t0, t1
    except Exception:  # noqa: BLE001
        return None
    return None


def insta_color_mode(path: str) -> str:
    """Insta360(Ace Pro 2 등) 파일 끝의 기록에서 색 프로파일: 'ilog' | 'normal' | 'unknown'(v0.16.50).
    사용자 파일(Ace Pro 2, vivid)로 확인한 것: 끝 3KB 안에 'Insta360 …' 모델명 · 색 이름('vivid') · 표식 8db42d69….
    I-Log 파일은 아직 못 봄 → 이름에 log 가 들어가면 ilog 로 봄(실제 파일로 확인 필요)."""
    import re
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - 8192))
            t = f.read()
        if b"8db42d694ccc418790edff439fe026bf" not in t or b"Insta360" not in t:
            return "unknown"
        if re.search(rb"(?<![A-Za-z])i[-_ ]?log(?![A-Za-z])", t, re.I):
            return "ilog"
        if re.search(rb"(?<![A-Za-z])(vivid|standard|flat)(?![A-Za-z])", t, re.I):
            return "normal"
        return "unknown"
    except Exception as e:  # noqa: BLE001
        log_error(f"색 모드 {path}", str(e)[-200:])
        return "unknown"


# ------------------------------------------------------------------ DJI 메타(djmd)로 색 모드 판단
def _pb_fields(b: bytes, path: str = "", depth: int = 0, out: dict | None = None) -> dict | None:
    """protobuf(이름 없는 필드) → {'.2.5.1': 값, …} 첫 값만. 형식이 안 맞으면 None."""
    out = {} if out is None else out
    i = 0
    try:
        while i < len(b):
            key, i = _pb_varint(b, i)
            fn, wt = key >> 3, key & 7
            if fn == 0 or fn > 2000:
                return None
            k = f"{path}.{fn}"
            if wt == 0:
                v, i = _pb_varint(b, i)
                out.setdefault(k, v)
            elif wt == 1:
                i += 8
            elif wt == 5:
                i += 4
            elif wt == 2:
                ln, i = _pb_varint(b, i)
                sub = b[i:i + ln]
                i += ln
                if depth < 5 and ln and _pb_fields(sub, k, depth + 1, dict()) is not None:
                    _pb_fields(sub, k, depth + 1, out)
                else:
                    out.setdefault(k, sub)
            else:
                return None
            if i > len(b):
                return None
        return out
    except IndexError:
        return None


def _pb_varint(b: bytes, i: int):
    r = sh = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << sh
        sh += 7
        if x < 0x80:
            return r, i


def dji_color_mode(path: str, info: dict | None = None) -> str:
    """'dlog' | 'normal' | 'unknown'. DJI 영상의 djmd 첫 패킷(0.1초 안팎)에서 필드 .2.5.1(2 = D-Log M, 1 = 일반).
    사용자 액션4 파일 2개로 찾은 필드: .1.9.1(5/1) · .2.3.5(10/8 bit)도 같은 방향 → 엇갈리면 unknown.
    DJI 가 아니거나 못 읽으면 unknown(→ LUT 없음, 사용자 2026-11-06)."""
    try:
        if info is None:
            info = json.loads(run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]))
        enc = str((info.get("format", {}).get("tags") or {}).get("encoder", ""))
        st = next((x for x in info.get("streams", []) if x.get("codec_tag_string") == "djmd"), None)
        if st is None or "DJI" not in enc.upper():
            return "unknown"
        txt = run([paths.ffprobe(), "-v", "error", "-select_streams", str(st["index"]), "-show_packets", "-show_data",
                   "-read_intervals", "%+#1", _abs(path)]).decode("utf-8", "replace")
        import re
        m = re.search(r"data=\s*\n(.*?)\[/PACKET\]", txt, re.S)
        if not m:
            return "unknown"
        hexs = "".join(re.findall(r"^[0-9a-f]{8}: ((?:[0-9a-f]{2,4} ?){1,8})", m.group(1), re.M)).replace(" ", "")   # 홀수 바이트 = 끝 묶음 2자리
        f = _pb_fields(bytes.fromhex(hexs)) or {}
        mode = f.get(".2.5.1")
        if mode == 2 and f.get(".1.9.1", 5) != 1:
            return "dlog"
        if mode == 1 and f.get(".1.9.1", 1) != 5:
            return "normal"
        return "unknown"
    except Exception as e:  # noqa: BLE001
        log_error(f"색 모드 {path}", str(e)[-200:])
        return "unknown"


def exif_orientation(path: str) -> int:
    """JPEG EXIF Orientation(1~8). 없거나 읽지 못하면 1. (ffmpeg 은 이 값을 적용하지 않으므로 직접 처리)"""
    import struct
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 1
            while True:
                m = f.read(2)
                if len(m) < 2 or m[0] != 0xFF or m[1] in (0xD9, 0xDA):
                    return 1
                ln = struct.unpack(">H", f.read(2))[0]
                if m[1] != 0xE1:
                    f.seek(ln - 2, 1)
                    continue
                d = f.read(ln - 2)
                if not d.startswith(b"Exif\x00\x00"):
                    continue
                t = d[6:]
                e = "<" if t[:2] == b"II" else ">"
                off = struct.unpack(e + "I", t[4:8])[0]
                n = struct.unpack(e + "H", t[off:off + 2])[0]
                for i in range(n):
                    ent = t[off + 2 + i * 12: off + 14 + i * 12]
                    if struct.unpack(e + "H", ent[:2])[0] == 0x0112:
                        v = struct.unpack(e + "H", ent[8:10])[0]
                        return v if 1 <= v <= 8 else 1
                return 1
    except Exception:  # noqa: BLE001
        return 1


# EXIF 방향 → ffmpeg 필터 (Qt QImageReader.setAutoTransform 과 같은 결과)
ORIENT_FILTER = {1: [], 2: ["hflip"], 3: ["hflip", "vflip"], 4: ["vflip"],
                 5: ["transpose=0"], 6: ["transpose=1"], 7: ["transpose=3"], 8: ["transpose=2"]}


def probe_image(path: str) -> dict:
    """JPG/PNG 크기(방향 반영)·방향."""
    out = run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", path])
    v = next((s for s in json.loads(out)["streams"] if s.get("codec_type") == "video"), None)
    if v is None:
        raise FFError("이미지를 읽을 수 없습니다.")
    w, h = int(v["width"]), int(v["height"])
    o = exif_orientation(path)
    if o >= 5:
        w, h = h, w
    return {"width": w, "height": h, "orient": o}


# ------------------------------------------------------------------ LUT
def lut_ref(name: str) -> tuple[str, str] | None:
    """LUT 를 캐시 폴더에 안전한 이름으로 복사 → (cwd, 파일명). 경로 이스케이프 문제 회피."""
    if not name:
        return None
    src = paths.lut_dir() / name
    if not src.exists():
        raise FFError(f"LUT 파일이 없습니다: {src}")
    d = paths.cache_dir() / "lut"
    st = src.stat()
    mk = (str(src), st.st_mtime_ns, st.st_size)
    hit = _lut_memo.get(mk)                    # ffmpeg 마다 LUT 를 통째로 읽어 해시하던 것 → 파일이 그대로면 기억(v0.16.40)
    if hit is not None and (d / hit).exists():
        return str(d), hit
    d.mkdir(exist_ok=True)
    h = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
    dst = d / f"lut_{h}.cube"
    _safe_copy(src, dst)
    _lut_memo[mk] = dst.name
    return str(d), dst.name


_lut_memo: dict = {}


_copy_lock = threading.Lock()


def _safe_copy(src, dst) -> None:
    """작업 폴더로 복사(여러 작업이 동시에 같은 파일을 쓰면 반쯤 써진 파일을 읽어 실패 → 잠금 + 임시 파일 → 이름 바꾸기).
    AUTO 분석·프록시·미리보기가 동시에 시작될 때 '분석 실패'가 나던 원인."""
    dst = Path(dst)
    with _copy_lock:
        if dst.exists() and dst.stat().st_size == Path(src).stat().st_size:
            return
        tmp = dst.with_name(dst.name + f".{threading.get_ident()}.part")
        shutil.copyfile(src, tmp)
        replace_retry(tmp, dst)


def list_luts() -> list[str]:
    return sorted(p.name for p in paths.lut_dir().iterdir() if p.suffix.lower() in (".cube", ".3dl"))


# ------------------------------------------------------------------ 필터 체인
def curve_is_identity(curve) -> bool:
    return all(abs(x - y) < 1e-4 for x, y in curve)


# 물빛 = 청록·녹색 범위만 색상 회전(+ = 파랑 쪽), 녹황 = 녹·황 범위만 채도 감소. 피부·산호(주황)는 거의 그대로(실측)
WATER_OPT = "colors=c+g:strength=2"
GY_OPT = "colors=g+y:strength=1.5"


def grade_chain(g: dict, lut_file: str | None, width: int = 1920, named: bool = False, tag: str = "") -> list[str]:
    """(YUV) 노이즈 → 밝기 샤픈·디헤이즈 → (RGB 16bit) LUT → R/B 게인 → 커브 → Hue → 채도
    named = 색 키프레임용: 게인·Hue·채도 필터를 항상 넣고 이름(@g)을 붙임 → sendcmd 로 프레임마다 값 변경."""
    if named:
        return _grade_named(g, lut_file, width, tag)
    f = denoise_chain(g) + sharpen_chain(g, width)
    f.append("format=gbrp16le")
    if lut_file:
        f.append(f"lut3d=file={lut_file}:interp=tetrahedral")
    r, b = float(g.get("r_gain", 1)), float(g.get("b_gain", 1))
    if abs(r - 1) > 1e-3 or abs(b - 1) > 1e-3:
        f.append(f"colorchannelmixer=rr={r:.4f}:bb={b:.4f}")
    curve = sorted(g.get("curve") or [[0, 0], [1, 1]])
    if not curve_is_identity(curve):
        pts = " ".join(f"{x:.4f}/{y:.4f}" for x, y in curve)
        f.append(f"curves=m='{pts}'")
    hue = float(g.get("hue", 0))
    if abs(hue) > 1e-3:
        f.append(f"huesaturation=hue={hue:.2f}")
    wt, gy = float(g.get("water", 0)), float(g.get("gy", 0))
    if abs(wt) > 1e-3:
        f.append(f"huesaturation={WATER_OPT}:hue={wt:.2f}")
    if gy > 1e-3:
        f.append(f"huesaturation={GY_OPT}:saturation={-gy / 100:.4f}")
    sat = float(g.get("sat", 1.0))
    if abs(sat - 1) > 1e-3:
        f.append(f"vibrance=intensity={max(-2.0, min(2.0, sat - 1)):.3f}")
    f += wnr_mark(g, width)
    return f


# ------------------------------------------------------------------ 물 노이즈: 파란 영역의 붉은 색 노이즈만 정리
WNR = "§wnr:"


def wnr_mark(g: dict, width: int) -> list[str]:
    """체인 안 표시(나중에 graph() 가 갈래 그래프로 바꿈). 0 이면 없음."""
    w = float(g.get("wnr", 0))
    return [f"{WNR}{w:.1f}:{int(width)}"] if w > 0.5 else []


def wnr_graph(mark: str, inlab: str, outlab: str, uid: str) -> list[str]:
    """[in] → 원본 / 색만 흐리게 + 빨강·자주 채도 낮춤 / 파란 영역 지도(넓게 흐린 B−R) → 지도만큼 섞음 → [out].
    밝기(Y)는 그대로라 디테일은 안 뭉개짐. 빨간 피사체(산호·거북이) 위치는 지도 값이 0 이라 그대로(실측)."""
    w, width = (float(x) for x in mark[len(WNR):].split(":"))
    k = width / 1920
    sc = max(1.0, (2 + 8 * w / 100) * k)          # 색 흐림 정도
    sm = max(4.0, 24 * k)                          # 파란 영역 지도의 넓이
    gain = min(2.0, 1.4 * w / 80)                  # 지도 세기
    desat = -min(1.0, 0.85 * w / 80)
    o, c, m, cb, mk = (f"[wn{uid}{x}]" for x in ("o", "c", "m", "cb", "mk"))
    return [f"{inlab}format=gbrp16le,split=3{o}{c}{m}",
            f"{c}scale=out_color_matrix=bt709:out_range=pc,format=yuv444p16le,gblur=sigma={sc:.2f}:planes=6,"
            f"scale=in_color_matrix=bt709:in_range=pc,format=gbrp16le,huesaturation=colors=r+m:saturation={desat:.3f}:strength=2{cb}",
            f"{m}gblur=sigma={sm:.1f},colorchannelmixer=rr=-2:rb=2:gr=-2:gb=2:br=-2:bb=2,"
            f"colorchannelmixer=rr={gain:.3f}:gg={gain:.3f}:bb={gain:.3f}{mk}",
            f"{o}{cb}{mk}maskedmerge{outlab}"]


def graph(chain: list[str], inlab: str, outlab: str, uid: str = "0") -> str:
    """필터 목록 → filter_complex 문자열. 물 노이즈 표시가 있으면 그 자리에서 갈래 그래프로."""
    parts, cur, seg, k = [], inlab, [], 0
    for f in chain:
        if f.startswith(WNR):
            lab = f"[wa{uid}_{k}]"
            parts.append(f"{cur}{','.join(seg) or 'null'}{lab}")
            nxt = f"[wb{uid}_{k}]"
            parts += wnr_graph(f, lab, nxt, f"{uid}_{k}")
            cur, seg, k = nxt, [], k + 1
        else:
            seg.append(f)
    parts.append(f"{cur}{','.join(seg) or 'null'}{outlab}")
    return ";".join(parts)


def _grade_named(g, lut_file, width, tag=""):
    """tag = 컷 번호. 이름이 컷마다 같으면 sendcmd 가 그래프의 첫 컷 필터를 바꿈 → 전환 때 뒷컷 색이 앞컷에(v0.16.79)."""
    f = denoise_chain(g) + sharpen_chain(g, width) + ["format=gbrp16le"]
    if lut_file:
        f.append(f"lut3d=file={lut_file}:interp=tetrahedral")
    f.append(f"colorchannelmixer@g{tag}=rr={float(g.get('r_gain', 1)):.4f}:bb={float(g.get('b_gain', 1)):.4f}")
    curve = sorted(g.get("curve") or [[0, 0], [1, 1]])
    if g.get("_ck"):                               # 커브 ◆ = 이름 붙여 늘 넣음(프레임마다 바꿈)
        f.append(f"curves@g{tag}=m='{_curve_arg(curve)}'")
    elif not curve_is_identity(curve):
        f.append(f"curves=m='{' '.join(f'{x:.4f}/{y:.4f}' for x, y in curve)}'")
    f.append(f"huesaturation@g{tag}=hue={float(g.get('hue', 0)):.2f}")
    f.append(f"huesaturation@w{tag}={WATER_OPT}:hue={float(g.get('water', 0)):.2f}")
    f.append(f"huesaturation@y{tag}={GY_OPT}:saturation={-float(g.get('gy', 0)) / 100:.4f}")
    f.append(f"vibrance@g{tag}=intensity={max(-2.0, min(2.0, float(g.get('sat', 1)) - 1)):.3f}")
    return f + wnr_mark(g, width)


def has_gkeys(seg) -> bool:
    return any(seg.gkeys.get(k) for k in KEYABLE + [CURVE_KEY]) if getattr(seg, "gkeys", None) else False


def _curve_arg(curve) -> str:
    return " ".join(f"{float(x):.4f}/{float(y):.4f}" for x, y in sorted(curve or [[0, 0], [1, 1]]))


def gkey_cmds(g: dict, seg: Segment, src: Source, n_out: int, frames_per_sec: float, tag: str = "") -> str:
    """sendcmd 명령: 출력 프레임마다 색 키프레임 보간값(바뀔 때만). 커브 ◆ 가 있으면 curves@g 도(v0.16.34)."""
    lines, last = [], None
    ck = bool(seg.gkeys.get(CURVE_KEY))
    for n in range(n_out):
        t = n / float(OUT_FPS)
        v = apply_off(grade_at(g, seg.gkeys, seg.fin + t * frames_per_sec), getattr(seg, "off", None))
        cur = (round(v["r_gain"], 4), round(v["b_gain"], 4), round(v["hue"], 2), round(max(-2, min(2, v["sat"] - 1)), 3),
               round(float(v.get("water", 0)), 2), round(-float(v.get("gy", 0)) / 100, 4),
               _curve_arg(v.get("curve")) if ck else "")
        if cur == last:
            continue
        last = cur
        k = tag
        lines.append(f"{max(0.0, t - 0.25 / float(OUT_FPS)):.6f} [enter] colorchannelmixer@g{k} rr {cur[0]}, "
                     f"colorchannelmixer@g{k} bb {cur[1]}, huesaturation@g{k} hue {cur[2]}, vibrance@g{k} intensity {cur[3]}, "
                     f"huesaturation@w{k} hue {cur[4]}, huesaturation@y{k} saturation {cur[5]}"
                     + (f", curves@g{k} m '{cur[6]}'" if ck else "") + ";")
    return "\n".join(lines) + "\n"


def out_size(orientation: str) -> tuple[int, int]:
    return {"vertical": (1080, 1920), "vertical1440": (1440, 2560), "vertical2160": (2160, 3840),
            "horizontal1440": (2560, 1440), "horizontal2160": (3840, 2160),
            "preview": (960, 540), "preview_v": (540, 960)}.get(orientation, (1920, 1080))


def is_vertical(orientation: str) -> bool:
    return orientation in ("vertical", "vertical1440", "vertical2160", "preview_v")


def crop_filter(orientation: str) -> str:
    if is_vertical(orientation):
        return "crop=w='trunc(min(iw,ih*9/16)/2)*2':h='trunc(min(ih,iw*16/9)/2)*2'"
    return "crop=w='trunc(min(iw,ih*16/9)/2)*2':h='trunc(min(ih,iw*9/16)/2)*2'"


def crop_size(w: int, h: int, orientation: str) -> tuple[int, int]:
    """crop_filter 와 같은 계산(숫자)."""
    if is_vertical(orientation):
        return int(min(w, h * 9 / 16) / 2) * 2, int(min(h, w * 16 / 9) / 2) * 2
    return int(min(w, h * 16 / 9) / 2) * 2, int(min(h, w * 9 / 16) / 2) * 2


def seg_reframe(src: Source, seg: Segment, orientation: str) -> list | None:
    """세로 출력에서 쓸 크롭 키프레임(범위 제한). 없거나 모두 0 이면 None → 기존 가운데 크롭."""
    if not is_vertical(orientation) or not seg.reframe:
        return None
    m = reframe_max(src.width or 3840)
    keys = sorted(({"f": int(k["f"]), "dx": max(-m, min(m, float(k["dx"])))} for k in seg.reframe),
                  key=lambda k: k["f"])
    return keys if any(abs(k["dx"]) >= 0.5 for k in keys) else None


def reframe_expr(keys: list, f0: int, frames_per_sec: float, mul: float = 1.0) -> str:
    """t(초) → 이동량 식. 프레임 = f0 + t*frames_per_sec. 키프레임 사이 smoothstep (project.ease 와 같음)."""
    tk = [((k["f"] - f0) / frames_per_sec, k["dx"] * mul) for k in keys]
    e = f"{tk[-1][1]:.3f}"
    for (t0, d0), (t1, d1) in reversed(list(zip(tk, tk[1:]))):
        u = f"clip((t-{t0:.6f})/{max(1e-6, t1 - t0):.6f},0,1)"
        e = f"if(lt(t,{t1:.6f}),{d0:.3f}+({d1 - d0:.3f})*{u}*{u}*(3-2*{u}),{e})"
    return f"if(lt(t,{tk[0][0]:.6f}),{tk[0][1]:.3f},{e})"


ROT_FIX_T = 1794558600.0          # 2026-11-13 17:30 KST — 이 전에 만든 세로 촬영 프록시는 GPU 경로로 누웠을 수 있음


def may_rotate(src) -> bool:
    """v0.16.78 회전 정보가 있는(또는 있을 수 있는 = 세로) 원본. GPU 프레임(-hwaccel_output_format cuda)으로 읽으면 ffmpeg 이
    자동 회전을 못 해서 누운 채로 읽힘 → 세로 출력에 눌린 그림 + 결과 파일에 회전 정보가 남아 플레이어가 또 돌림(사용자 렌더)."""
    return bool(getattr(src, "rotation", 0)) or (bool(src.width) and src.height > src.width)


def _crop_noop(src: Source, orientation: str) -> bool:
    """화면비가 이미 출력과 같음(크롭 없음) — GPU 축소 조건."""
    w, h = out_size(orientation)
    return bool(src.width and src.height) and abs(src.width * h - src.height * w) <= max(w, h) * 2


def _dl_fmt(src: Source) -> str:
    return "p010le" if "10" in (_proxy_pix(src.path) or "") else "nv12"


def frame_chain(orientation: str) -> list[str]:
    """화면비 맞춰 중앙 크롭(4K에서) 후 축소."""
    w, h = out_size(orientation)
    return [crop_filter(orientation), f"scale={w}:{h}:flags=lanczos"]


# ------------------------------------------------------------------ 흔들림 보정 (vidstab 2패스)
# 화질 순서: 4K 에서 화면비 크롭 → 출력의 1.25배 크기로 축소 → 흔들림 보정(자동 확대 포함) → 출력 크기로 축소.
# 확대가 일어나도 최종 단계는 항상 '축소'라 업스케일 흐림이 없고, 4K 전체 처리보다 약 4배 빠름.
STAB_OVERSIZE = 1.25


def stab_params(g: dict) -> tuple[int, int] | None:
    v = float(g.get("stab", 0))
    if v <= 0:
        return None
    return int(round(4 + v * 0.06)), int(round(6 + v * 0.30))   # (shakiness 4~10, smoothing 6~36)


def _stab_size(orientation, src: Source | None = None):
    """흔들림 보정 작업 크기 = 출력의 1.25배. 단 원본 크롭 크기보다 크게 키우지 않음(1440·4K 출력)."""
    w, h = out_size(orientation)
    if src is not None and src.width:
        cw, ch = crop_size(src.width, src.height, orientation)
        k = min(STAB_OVERSIZE, cw / w, ch / h)
        if k < STAB_OVERSIZE:
            return int(w * max(1.0, k)) // 2 * 2, int(h * max(1.0, k)) // 2 * 2
    return int(w * STAB_OVERSIZE) // 2 * 2, int(h * STAB_OVERSIZE) // 2 * 2


def stab_band(src: Source, seg: Segment, orientation: str, lens: list | tuple = ()):
    """흔들림 보정 앞 크롭. 세로 리프레이밍이 있으면 이동 범위 전체를 덮는 띠를 먼저 보정하고(보정 → 크롭)
    그 안에서 움직이는 크롭. 반환 (보정 전 필터들, 보정 후 크롭 필터 또는 None, 캐시 키)."""
    sw, sh = _stab_size(orientation, src)
    keys = seg_reframe(src, seg, orientation)
    tag = f"{sw}x{sh}|{','.join(lens)}"
    if not keys:
        return [*lens, crop_filter(orientation), f"scale={sw}:{sh}:flags=lanczos"], None, tag
    cw, ch = crop_size(src.width, src.height, orientation)
    dmin, dmax = min(k["dx"] for k in keys), max(k["dx"] for k in keys)
    x0 = max(0, int((src.width - cw) / 2 + dmin))
    bw = min(src.width - x0, int(cw + (dmax - dmin) + 2) // 2 * 2)
    k = sh / ch
    bws = int(round(bw * k / 2)) * 2
    pre = [*lens, f"crop={bw}:{ch}:{x0}:{(src.height - ch) // 2}", f"scale={bws}:{sh}:flags=lanczos"]
    cx0 = (src.width - cw) / 2 - x0          # 띠 안 가운데 크롭 위치(원본 px)
    xe = reframe_expr(keys, seg.fin, float(src.fps), k)
    post = f"crop={sw}:{sh}:x='clip({cx0 * k:.3f}+{xe},0,iw-{sw})':y=0"
    return pre, post, f"{x0}x{bw}|{tag}"


def stab_file(src: Source, seg: Segment, orientation: str, shakiness: int, lens=()) -> Path:
    key = (f"{os.path.abspath(src.path)}|{seg.fin}|{seg.fout}|{orientation}|{shakiness}|"
           f"{stab_band(src, seg, orientation, lens)[2]}")
    d = paths.cache_dir() / "lut"       # LUT 와 같은 작업 폴더(cwd) 사용 → 경로 이스케이프 불필요
    d.mkdir(parents=True, exist_ok=True)
    return d / f"stab_{hashlib.sha1(key.encode()).hexdigest()[:12]}.trf"


def stab_detect(src: Source, seg: Segment, orientation: str, shakiness: int, gpu: bool,
                on_progress=None, cancel=None, lens=()) -> Path:
    trf = stab_file(src, seg, orientation, shakiness, lens)
    if trf.exists() and trf.stat().st_size > 0:
        return trf
    tmp = trf.with_suffix(".part.trf")
    sec = float(Fraction(seg.frames) / src.fps)
    pre = [f.replace("flags=lanczos", "flags=bicubic") for f in stab_band(src, seg, orientation, lens)[0]]
    vf = [f"trim=end_frame={seg.frames}", "setpts=PTS-STARTPTS", *pre,
          f"vidstabdetect=shakiness={shakiness}:accuracy=15:result={tmp.name}"]
    cmd = [paths.ffmpeg(), "-y", *_hw(gpu), "-ss", _seek(seg.fin, src.fps), "-t", f"{sec + 0.5:.6f}",
           "-i", _abs(src.path), "-an", "-vf", ",".join(vf), "-f", "null", "-"]
    try:
        run_progress(cmd, sec, on_progress, cancel, cwd=str(trf.parent))
    except FFError:
        if not gpu:
            raise
        run_progress([c for c in cmd if c not in ("-hwaccel", "cuda")], sec, on_progress, cancel, cwd=str(trf.parent))
    replace_retry(tmp, trf)
    return trf


def _lut_for(g: dict) -> tuple[str | None, str | None]:
    ref = lut_ref(g.get("lut", ""))
    return (ref[0], ref[1]) if ref else (None, None)


# ------------------------------------------------------------------ 프록시
def proxy_path(src_path: str, lut: str | None = None) -> Path:
    """프록시 파일(LUT 를 입혀 만듦). 기본 LUT 는 예전 이름 그대로(이미 만든 프록시 재사용), 다른 LUT·LUT 없음은 이름에 반영."""
    from .project import DEFAULT_LUT
    st = os.stat(src_path)
    key = f"{os.path.abspath(src_path)}|{st.st_size}|{int(st.st_mtime)}"
    if lut is not None and lut != DEFAULT_LUT:
        key += f"|lut={lut}"
    h = hashlib.sha1(key.encode()).hexdigest()[:12]
    d = paths.cache_dir() / "proxy"
    d.mkdir(exist_ok=True)
    return d / f"{Path(src_path).stem}_{h}.mp4"


def _proxy_pix(path: str) -> str:
    try:
        out = run([paths.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
                   "-of", "csv=p=0", _abs(path)])
        return out.decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


PROXY_W = 640      # 프록시 폭(v0.16.16: 960 → 640, 만드는 시간·메모리 캐시 줄임. 예전 960 프록시는 그대로 재사용)


# ------------------------------------------------------------------ 카메라 프리뷰 파일(LRF·LRV) — v0.16.19 (design/PREVIEW_FILES.md 1·2단계)
# 있으면 영상마다 자동 판정(길이·비율·디코딩·색) → 맞으면 프리뷰로 프록시(빠름), 없거나 안 맞으면 지금처럼 원본. 결과는 cache/dtme.log.
PREVIEW_USE = True


def find_preview(path: str) -> str | None:
    """원본과 짝인 프리뷰 파일(같은 폴더, 대소문자 무시). DJI = 같은 이름 .LRF / GoPro GX·GH01xxxx → GL01xxxx.LRV /
    Insta360 VID_…_00_n.mp4 → LRV_…_01_n.lrv (PRO_VID → PRO_LRV)."""
    import re
    p = Path(path)
    stem = p.stem
    cands = [stem + ".lrf", stem + ".lrv"]
    m = re.match(r"^G[XH](\d{2})(\d{4})$", stem, re.I)
    if m:
        cands.append(f"gl{m.group(1)}{m.group(2)}.lrv")
    m = re.match(r"^(PRO_)?VID_(.+)_0(\d)_(\d+)$", stem, re.I)
    if m:
        cands += [f"{m.group(1) or ''}LRV_{m.group(2)}_{k}_{m.group(4)}.lrv" for k in ("01", "11", "00")]
    m = re.match(r"^(PRO_)?VID_(.+)$", stem, re.I)          # Ace Pro 2: VID_날짜_시간_번호.mp4 ↔ LRV_날짜_시간_번호.lrv (v0.16.50)
    if m:
        cands.append(f"{m.group(1) or ''}LRV_{m.group(2)}.lrv")
    want = [c.lower() for c in cands]
    try:
        names = {f.name.lower(): f for f in p.parent.iterdir() if f.is_file() and f.suffix.lower() in (".lrf", ".lrv")}
    except OSError:
        return None
    for w in want:
        if w in names:
            return str(names[w])
    return None


PREVIEW_DIFF = 10.0          # 색 판정: 가까운 쪽 차(화소 차 중앙값, 0~255) 상한
PREVIEW_N = 8                # 판정 창 하나에 프리뷰 몇 장(v0.16.22: 15 → 8)
PREVIEW_MIN_W_AUTO = 640     # AUTO 분석에 쓸 최소 폭(분석은 320 폭)
PREVIEW_LONG = 1280          # 멈춘 보정 화면의 긴 쪽
PREVIEW_MIN_W_STILL = 1280   # 멈춘 화면(먼저 보이기)에 쓸 최소 폭(보정 화면이 1280 폭)


def _pv_win(path: str, t0: float, n: int, fps: float, ref: tuple | None) -> dict:
    """t0 부터 n장(키프레임 시크 + 실제 pts 로 번호) → {프레임 번호: (그대로, LUT 입힘 또는 None)} 96×54 float.
    LUT 는 같은 디코딩에서 갈라 옆에 붙여(hstack) 받음 = 원본을 한 번만 읽음."""
    import re
    import numpy as np
    w, h = 96, 54
    if ref:
        fc = (f"[0:v:0]showinfo,scale={w}:{h}:flags=area,split[a][b];[a]format=rgb24[a2];"
              f"[b]format=gbrp16le,lut3d=file={ref[1]},format=rgb24[b2];[a2][b2]hstack[o]")
    else:
        fc = f"[0:v:0]showinfo,scale={w}:{h}:flags=area,format=rgb24[o]"
    cmd = [paths.ffmpeg(), "-hide_banner", "-copyts", "-ss", f"{max(0.0, t0):.3f}", "-i", _abs(path),
           "-filter_complex", fc, "-map", "[o]", "-frames:v", str(n), "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    with _slots(cmd):
        pr = _popen(cmd, cwd=ref[0] if ref else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = pr.communicate()
    if pr.returncode != 0:
        if _closing.is_set():
            raise Cancelled()
        raise FFError(err.decode("utf-8", "replace")[-300:])
    ts = [float(x) for x in re.findall(rb"pts_time:\s*([-0-9.]+)", err)]
    ww = w * 2 if ref else w
    fr = np.frombuffer(out[:len(out) // (ww * h * 3) * ww * h * 3], np.uint8).reshape(-1, h, ww, 3).astype(np.float32)
    res = {}
    for i, t in enumerate(ts[:len(fr)]):
        res[int(round(t * fps))] = (fr[i][:, :w], fr[i][:, w:] if ref else None)
    return res


def _dif(x, y) -> float:
    """화소별 평균 차의 중앙값 → 움직이는 작은 부분·압축 차이는 덜 탐(색 차이는 화면 전체라 그대로 잡힘)."""
    import numpy as np
    return float(np.median(abs(x - y).mean(axis=2)))


def check_preview(src: Source, lut: str, pv: str | None = None, shift_hint: int | None = None,
                  color_only: bool = False) -> dict:
    """프리뷰 판정(v0.16.22: 원본을 한 번만 읽음). 반환 {"path","ok","why","color":"raw"|"lut","shift","ratio",
    "fps_num","fps_den","frames","w","h","diff","sec"}.
    1) 파일 정보: 디코딩 · 길이 차 ≤ 프리뷰 1프레임 + 원본 1프레임 · 가로세로 비 차 ≤ 2%
    2) 영상 가운데에서 프리뷰 8장 ↔ 원본 8·ratio+4장(같은 디코딩에서 LUT 입힌 것도). 기준 = 원본(+요청 LUT)
       색: 프리뷰 그대로 / +LUT 각각 (장마다 짝 후보 중 가장 가까운 차)의 중앙값 → 작은 쪽 ≤ PREVIEW_DIFF, 다른 쪽의 60% 이하
       시점: 그 색으로 프리뷰 k ↔ 원본 ratio·k+j(j=0..ratio-1) 중 확실히 가까운 j 에 표(DJI 실물 = 영상마다 0 또는 1)
    3) 표가 모자라면 1/4·3/4 지점에서 더(시점만). 끝까지 모자라면 0.
    color_only(v0.16.24, AUTO 분석용) = 2)의 색까지만(시점 안 잼, shift 0)."""
    import time as _t
    t_start = _t.monotonic()
    r = {"path": pv or find_preview(src.path), "ok": False, "why": "", "color": "", "shift": 0, "ratio": 1,
         "fps_num": 30, "fps_den": 1, "frames": 0, "w": 0, "h": 0, "diff": -1.0, "sec": 0.0}
    if not r["path"]:
        r["why"] = "없음"
        return r
    try:
        out = run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", _abs(r["path"])])
        d = json.loads(out)
        v = next(x for x in d["streams"] if x.get("codec_type") == "video" and not x.get("disposition", {}).get("attached_pic"))
        n, dd = (int(x) for x in (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/"))
        if not dd or not n:
            n, dd = 30, 1
        r["fps_num"], r["fps_den"] = n, dd
        pfps = n / dd
        pdur = float(v.get("duration") or d["format"].get("duration") or 0)
        r["frames"] = int(v.get("nb_frames") or round(pdur * pfps))
        r["w"], r["h"], _rot = _rot_wh(v)
    except Exception as e:  # noqa: BLE001
        r["why"] = f"읽기 실패 {str(e)[-80:]}"
        return r
    sfps = float(src.fps)
    sdur = src.frames / sfps
    if abs(pdur - sdur) > 1.0 / max(1.0, pfps) + 1.0 / sfps + 0.002:
        r["why"] = f"길이 다름 {pdur:.3f}/{sdur:.3f}초"
        return r
    if src.width and src.height and abs(r["w"] / r["h"] - src.width / src.height) > 0.02 * (src.width / src.height):
        r["why"] = f"비율 다름 {r['w']}x{r['h']}"
        return r
    ratio = max(1, int(round(sfps / pfps)))
    r["ratio"] = ratio
    ref = lut_ref(lut) if lut else None
    npv = max(3, min(PREVIEW_N, r["frames"]))

    def window(frac):
        t0 = max(0.0, min(sdur * frac - npv / pfps / 2, pdur - (npv + 0.5) / pfps))
        return _pv_win(r["path"], t0, npv, pfps, ref), _pv_win(src.path, t0, npv * ratio + 4, sfps, ref)

    try:
        L, O = window(0.5)
    except Exception as e:  # noqa: BLE001
        r["why"] = f"디코딩 실패 {str(e)[-120:]}"
        return r
    R = {j: (o[1] if ref else o[0]) for j, o in O.items()}          # 기준 = 원본(+LUT)
    cands = {"raw": 0, "lut": 1} if ref else {"raw": 0}
    diffs = {}
    for c, ci in cands.items():
        m = []
        for k, lf in L.items():
            js = [ratio * k + j for j in range(ratio)]
            if all(j in R for j in js) and lf[ci] is not None:
                m.append(min(_dif(lf[ci], R[j]) for j in js))
        if len(m) >= 3:
            import statistics
            diffs[c] = statistics.median(m)
    if not diffs:
        r["why"] = "비교할 프레임 없음"
        return r
    best = min(diffs, key=diffs.get)
    r["diff"] = round(diffs[best], 1)
    if diffs[best] > PREVIEW_DIFF:
        r["why"] = f"색 다름 {({k: round(x, 1) for k, x in diffs.items()})}"
        return r
    if len(diffs) > 1 and diffs[best] > 0.6 * max(diffs.values()):
        r["why"] = f"색 판정 애매 {({k: round(x, 1) for k, x in diffs.items()})}"
        return r
    r["color"] = best
    if color_only:
        r["ok"] = True
        r["sec"] = round(_t.monotonic() - t_start, 2)
        return r
    if ratio > 1 and shift_hint is not None:          # 같은 영상을 다른 LUT 로 이미 판정 = 시점은 같음
        r["shift"] = int(shift_hint)
    elif ratio > 1:
        ci = cands[best]
        votes = [0] * ratio

        def vote(L, R):
            for k, lf in L.items():
                js = [ratio * k + j for j in range(ratio)]
                if not all(j in R for j in js):
                    continue
                d = [float(abs(lf[ci] - R[j]).mean()) for j in js]      # 시점은 평균 차(움직임이 화면 일부여도 잡힘)
                srt = sorted(d)
                if srt[0] < 0.77 * srt[1]:                       # 확실히 가까운 것만 셈
                    votes[d.index(srt[0])] += 1

        def decided():
            mx = max(votes)
            return mx >= 5 and mx >= 3 * (sum(votes) - mx)
        vote(L, R)
        for frac in (0.25, 0.75):
            if decided():
                break
            try:
                L2, O2 = window(frac)
            except Exception:  # noqa: BLE001
                continue
            vote(L2, {j: (o[1] if ref else o[0]) for j, o in O2.items()})
        r["shift"] = votes.index(max(votes)) if max(votes) >= 5 else 0
    r["ok"] = True
    r["sec"] = round(_t.monotonic() - t_start, 2)
    return r


# 판정 결과 저장(v0.16.22): 영상 파일(경로·크기·수정 시각) + LUT 마다 한 번. cache/preview_judge.json 에도(다음 실행)
_pv_cache: dict = {}
_pv_lock = threading.Lock()
_pv_locks: dict = {}
_pv_loaded = False


def preview_enabled() -> bool:
    """⚙ 렌더 설정 '프리뷰 파일'(기본 사용)."""
    if not PREVIEW_USE:
        return False
    try:
        from .project import get_setting
        return str(get_setting("use_preview", 1)) not in ("0", "False", "false", "")
    except Exception:  # noqa: BLE001
        return True


def _pv_key(src: Source, lut: str) -> str:
    st = os.stat(src.path)
    return f"{os.path.abspath(src.path)}|{st.st_size}|{int(st.st_mtime)}|{lut or ''}"


def _pv_file() -> Path:
    return paths.cache_dir() / "preview_judge.json"


def _pv_load():
    global _pv_loaded
    if _pv_loaded:
        return
    _pv_loaded = True
    try:
        _pv_cache.update(json.loads(_pv_file().read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass


def _pv_save():
    try:
        tmp = _pv_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(_pv_cache, ensure_ascii=False), encoding="utf-8")
        replace_retry(tmp, _pv_file())
    except Exception:  # noqa: BLE001
        pass


def preview_info(src: Source, lut: str, judge: bool = True) -> dict | None:
    """쓸 수 있는 프리뷰 판정 결과(없거나 안 맞거나 꺼짐 = None). judge=False = 저장된 결과만(판정 안 함, 멈춘 화면용).
    같은 영상·LUT 를 동시에 판정하지 않음(프록시·AUTO 가 같이 불러도 한 번)."""
    if not preview_enabled():
        return None
    try:
        key = _pv_key(src, lut)
    except OSError:
        return None
    with _pv_lock:
        _pv_load()
        hit = _pv_cache.get(key)
        if hit is not None or not judge:
            return hit if (hit and hit.get("ok") and Path(hit["path"]).exists()) else None
        lk = _pv_locks.setdefault(key, threading.Lock())
    with lk:
        with _pv_lock:
            hit = _pv_cache.get(key)
        if hit is None:
            base = key.rsplit("|", 1)[0] + "|"
            with _pv_lock:
                hint = next((v.get("shift") for k2, v in _pv_cache.items() if k2.startswith(base) and v.get("ok")), None)
            w0 = waited()
            hit = check_preview(src, lut or "", shift_hint=hint)
            if hit["why"] != "없음":
                name = Path(src.path).name
                if hit["ok"]:
                    _batch_seen.add(key)
                    _batch_note(src, lut or "", hit)
                    log_error("프리뷰 판정", f"{name}: 사용 {Path(hit['path']).suffix[1:].upper()} {hit['w']}x{hit['h']} "
                                         f"{hit['fps_num'] / hit['fps_den']:.2f}fps · 색 {hit['color']} · 시점 +{hit['shift']} "
                                         f"· 차 {hit['diff']} · {hit['sec']}초 (자리 대기 {waited() - w0:.1f}초)")
                else:
                    log_error("프리뷰 판정", f"{name}: 안 씀(원본) — {hit['why']}")
            with _pv_lock:
                _pv_cache[key] = hit
                _pv_save()
    return hit if hit.get("ok") else None


# ------------------------------------------------------------------ AUTO 분석용 프리뷰(v0.16.24): 시점 판정을 기다리지 않음
# 사용자 로그: 판정 29개 모두 같은 결과(색 lut, 차 1.3~2.0), 다른 것은 시점(0/1)뿐 → 시점은 분석에 필요 없음(색 통계).
# 같은 묶음(폴더 · LUT · 프리뷰 크기·fps · 원본 크기·fps)에서 색을 두 번 확인해 같으면 나머지는 파일 정보(길이·비율)만 확인.
# 묶음 안에서 색이 엇갈리면 그 묶음은 영상마다 색 확인. 전체 판정(시점 포함)은 프록시 만들 때(우선순위 낮음).
BATCH_CONFIRM = 2
_batch: dict = {}           # 묶음 → {"color", "n", "mixed"}
_batch_locks: dict = {}
_batch_seen: set = set()


def _batch_key(src: Source, lut: str, meta: dict) -> str:
    return (f"{os.path.dirname(os.path.abspath(src.path))}|{lut}|{meta['w']}x{meta['h']}|{meta['fps_num']}/{meta['fps_den']}"
            f"|{src.width}x{src.height}|{src.fps_num}/{src.fps_den}")


def _batch_note(src: Source, lut: str, r: dict) -> None:
    """판정 결과(전체·색만)를 묶음에 더함."""
    if not r.get("ok"):
        return
    k = _batch_key(src, lut, r)
    with _pv_lock:
        b = _batch.setdefault(k, {"color": r["color"], "n": 0, "mixed": False})
        if b["color"] != r["color"]:
            b["mixed"] = True
        b["n"] += 1


def _pv_meta(src: Source, path: str) -> dict:
    """프리뷰 파일 정보만으로 1)단계 확인(디코딩 없음). 반환 check_preview 와 같은 모양(color 비어 있음)."""
    r = {"path": path, "ok": False, "why": "", "color": "", "shift": 0, "ratio": 1,
         "fps_num": 30, "fps_den": 1, "frames": 0, "w": 0, "h": 0, "diff": -1.0, "sec": 0.0}
    try:
        d = json.loads(run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                            _abs(path)]))
        v = next(x for x in d["streams"] if x.get("codec_type") == "video" and not x.get("disposition", {}).get("attached_pic"))
        n, dd = (int(x) for x in (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/"))
        if not dd or not n:
            n, dd = 30, 1
        r["fps_num"], r["fps_den"] = n, dd
        pfps = n / dd
        pdur = float(v.get("duration") or d["format"].get("duration") or 0)
        r["frames"] = int(v.get("nb_frames") or round(pdur * pfps))
        r["w"], r["h"], _rot = _rot_wh(v)
    except Exception as e:  # noqa: BLE001
        r["why"] = f"읽기 실패 {str(e)[-80:]}"
        return r
    sfps = float(src.fps)
    if abs(pdur - src.frames / sfps) > 1.0 / max(1.0, pfps) + 1.0 / sfps + 0.002:
        r["why"] = "길이 다름"
    elif src.width and src.height and abs(r["w"] / r["h"] - src.width / src.height) > 0.02 * (src.width / src.height):
        r["why"] = "비율 다름"
    r["ratio"] = max(1, int(round(sfps / pfps)))
    return r


def preview_for_analysis(src: Source, lut: str) -> dict | None:
    """AUTO 분석에 쓸 프리뷰(색까지 확인된 것) 또는 None(원본으로)."""
    if not preview_enabled():
        return None
    try:
        key = _pv_key(src, lut)
    except OSError:
        return None
    with _pv_lock:
        _pv_load()
        hit = _pv_cache.get(key)
    if hit is not None:                                    # 전체 판정이 이미 있음(지난 실행 것도) → 묶음 확인에도 셈
        ok = hit.get("ok") and Path(hit["path"]).exists()
        if ok and key not in _batch_seen:
            _batch_seen.add(key)
            _batch_note(src, lut or "", hit)
        return hit if ok else None
    path = find_preview(src.path)
    if not path:
        return None
    meta = _pv_meta(src, path)
    if meta["why"]:
        log_error("분석 프리뷰", f"{Path(src.path).name}: 안 씀(원본) — {meta['why']}")
        return None
    bk = _batch_key(src, lut, meta)
    with _pv_lock:
        lk = _batch_locks.setdefault(bk, threading.Lock())
    with lk:                                               # 같은 묶음의 색 확인은 하나씩(앞 결과를 뒤가 씀)
        with _pv_lock:
            b = dict(_batch.get(bk) or {})
        if b and not b.get("mixed") and b.get("n", 0) >= BATCH_CONFIRM:
            meta.update(ok=True, color=b["color"], why="묶음")
            return meta
        r = check_preview(src, lut or "", pv=path, color_only=True)
        _batch_note(src, lut or "", r)
        log_error("분석 프리뷰", f"{Path(src.path).name}: " + (f"색 확인 {r['color']} · 차 {r['diff']} · {r['sec']}초" if r["ok"]
                                                              else f"안 씀(원본) — {r['why']}"))
        return r if r["ok"] else None


def preview_pos(pv: dict, frame: int) -> int:
    """원본 프레임 → 같은(또는 바로 앞) 화면인 프리뷰 프레임 번호."""
    k = (frame - int(pv.get("shift", 0))) // max(1, int(pv.get("ratio", 1)))
    return max(0, min(max(0, int(pv.get("frames", 1)) - 1), k))


def preview_fps(pv: dict) -> Fraction:
    return Fraction(int(pv["fps_num"]), int(pv["fps_den"]))


def _proxy_from_preview(src: Source, lut: str, pv: dict, tmp: Path, pw: int, ph: int, on_progress, cancel) -> None:
    """프리뷰 → 프록시. fps = 원본 fps(30p → 60p 는 프레임 복제), 끝은 복제로 채운 뒤 원본 프레임 수에서 자름
    → 프록시 프레임 수 = 원본 프레임 수(다른 코드 그대로). 색 = 판정이 'lut' 면 LUT, 'raw' 면 그대로."""
    ref = lut_ref(lut) if (lut and pv["color"] == "lut") else None
    color = ["format=gbrp16le", f"lut3d=file={ref[1]}"] if ref else []
    # 시점 맞춤(v0.16.21): 프리뷰 k번째 = 원본 2k+shift번째(_align 이 영상마다 잼, DJI 실물 = 0 또는 1)
    # → shift 프레임만큼 늦춰 놓고 fps 를 0초부터 채움: 짝이 있는 프레임 = 같은 화면, 나머지 = 바로 앞 화면
    k = int(pv.get("shift") or 0)
    shift = f"+{k * src.fps_den}/({src.fps_num}*TB)" if k else ""
    vf = [f"setpts=PTS-STARTPTS{shift}", f"fps={src.fps_num}/{src.fps_den}:start_time=0", "tpad=stop_mode=clone:stop=8",
          f"trim=end_frame={src.frames}", f"scale={pw}:{ph}:flags=bilinear", *color, TO_YUV709]
    tail = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"] if src.has_audio else ["-an"]
    cmd = [paths.ffmpeg(), "-y", "-i", _abs(pv["path"]), "-map", "0:v:0", "-vf", ",".join(vf), *tail,
           "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
           "-g", "1", "-crf", "23", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-movflags", "+faststart", _abs(tmp)]
    run_progress(cmd, src.frames / float(src.fps), on_progress, cancel, cwd=ref[0] if ref else None)


def frame_count(path: str) -> int:
    """실제 프레임 수(패킷 세기, 프록시 확인용)."""
    out = run([paths.ffprobe(), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=nb_read_packets", "-of", "csv=p=0", _abs(path)])
    return int(out.decode().strip() or 0)


def make_proxy(src: Source, lut: str, gpu: bool, on_progress=None, cancel=None) -> str:
    """PROXY_W 폭, 모든 프레임 키프레임(H.264) → 프레임 단위 탐색이 빠름. LUT 를 미리 입혀 보기 좋게.
    GPU 켜짐: ① 디코딩·축소 모두 GPU(scale_cuda, 4K 프레임을 CPU 로 안 내림) → 실패하면 ② GPU 디코딩 + CPU 축소 → ③ CPU.
    걸린 시간은 cache/dtme.log 에 남김(사용자 PC 속도 확인용)."""
    import time
    out = proxy_path(src.path, lut or "")
    if out.exists() and may_rotate(src) and out.stat().st_mtime < ROT_FIX_T:     # v0.16.78 예전에 GPU 로 누운 채 만든 프록시 = 다시
        try:
            out.unlink()
        except OSError:
            pass
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    tmp = out.with_suffix(".part.mp4")
    ref = lut_ref(lut) if lut else None
    color = ["format=gbrp16le", f"lut3d=file={ref[1]}"] if ref else []
    pw = PROXY_W
    ph = max(2, int(round(pw * (src.height or 2160) / (src.width or 3840) / 2)) * 2)
    tail = []
    if src.has_audio:
        tail += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"]
    tail += ["-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
             "-g", "1", "-crf", "23", "-colorspace", "bt709", "-color_primaries", "bt709",
             "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", _abs(tmp)]
    tries = []
    if gpu and has_cuda():
        if not may_rotate(src):                  # v0.16.78 세로 촬영(회전 정보) = GPU 프레임 경로 안 씀(자동 회전 안 됨)
            dl = "p010le" if "10" in _proxy_pix(src.path) else "nv12"
            tries.append(("GPU 축소", ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
                          [f"scale_cuda={pw}:{ph}:interp_algo=bilinear", "hwdownload", f"format={dl}"]))
        tries.append(("GPU 디코딩", ["-hwaccel", "cuda"], [f"scale={pw}:{ph}:flags=bilinear"]))
    tries.append(("CPU", [], [f"scale={pw}:{ph}:flags=bilinear"]))
    dur = src.frames / float(src.fps)
    pv = None
    try:
        pv = preview_info(src, lut or "")            # 카메라 프리뷰(LRF 등): 판정 통과면 그걸로(결과 저장, 영상·LUT 마다 한 번)
    except Exception as e:  # noqa: BLE001
        log_error("프리뷰 판정 실패 → 원본", f"{Path(src.path).name}: {str(e)[-300:]}")
    if pv:
        try:
            t1, w1 = time.monotonic(), waited()
            _proxy_from_preview(src, lut or "", pv, tmp, pw, ph, on_progress, cancel)
            n = frame_count(str(tmp))
            if abs(n - src.frames) > 1:
                raise FFError(f"프레임 수 다름 {n}/{src.frames}")
            log_error("프록시", f"{Path(src.path).name} 프리뷰({Path(pv['path']).suffix[1:].upper()}) "
                               f"{time.monotonic() - t1:.1f}초 (영상 {dur:.0f}초, 자리 대기 {waited() - w1:.1f}초)")
            replace_retry(tmp, out)
            return str(out)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            if cancel is not None and cancel.is_set():
                raise
            log_error("프리뷰 프록시 실패 → 원본", f"{Path(src.path).name}: {str(e)[-300:]}")
    last = None
    for i, (name, hw, pre) in enumerate(tries):
        cmd = [paths.ffmpeg(), "-y", *hw, "-i", _abs(src.path), "-map", "0:v:0", "-vf", ",".join(pre + color + [TO_YUV709]), *tail]
        t0, w0 = time.monotonic(), waited()
        try:
            run_progress(cmd, dur, on_progress, cancel, cwd=ref[0] if ref else None)
        except FFError as e:
            if cancel is not None and cancel.is_set():
                raise
            last = e
            log_error(f"프록시 {name} 실패 → 다음 방식", str(e)[-300:])
            continue
        log_error("프록시", f"{Path(src.path).name} {name} {time.monotonic() - t0:.1f}초 (영상 {dur:.0f}초, 자리 대기 {waited() - w0:.1f}초)")
        replace_retry(tmp, out)
        return str(out)
    raise last


# ------------------------------------------------------------------ 미리보기용 프레임 캐시 (메모리)
# 디스크에 임시 파일을 쓰지 않음 → Windows 에서 백신·색인이 파일을 잡아 생기던 '다른 프로세스가 사용 중' 오류 제거.
# 앞 프레임(PREVIEW_LEAD)을 함께 넣어 시간축 노이즈 제거(hqdn3d)가 미리보기에도 보이게 함.
PREVIEW_LEAD = 4
_FRAME_CACHE_MAX = 48


def last_only(vf: list[str], lead: int) -> list[str]:
    """한 장만 필요한 체인(멈춘 화면·확대·스틸): 앞 프레임(lead)은 시간축 노이즈 제거(hqdn3d) 예열에만 쓰이므로
    hqdn3d 바로 뒤에서 마지막 장만 남김 → 그 뒤(LUT·색·물 노이즈…)는 1장만 계산(v0.16.40, 결과 화면은 같음).
    hqdn3d 가 없으면 맨 앞에서 고름."""
    k = max((i + 1 for i, f in enumerate(vf) if f.startswith("hqdn3d")), default=0)
    return vf[:k] + ([f"select=gte(n\\,{lead})"] if lead > 0 else []) + vf[k:]


class CachedFrame:
    """미리보기 입력(앞 프레임 + 그 프레임). fmt = 'nut'(ffv1 무손실) | 'raw'(yuv420p10le, 원본 구간 캐시에서 잘라 옴)."""

    def __init__(self, data: bytes, lead: int, size=(0, 0), fmt: str = "nut", key: str = ""):
        self.data, self.lead, self.size, self.fmt = data, lead, size, fmt
        self.key = key                # 같은 화면 표시(경로|프레임) — render_preview 결과 기억용. "" = 기억 안 함

    def input_args(self) -> list[str]:
        if self.fmt == "raw":
            return ["-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-s", f"{self.size[0]}x{self.size[1]}", "-framerate", "60",
                    "-i", "-"]
        return ["-f", "nut", "-i", "-"]


# ------------------------------------------------------------------ 원본 구간 캐시(v0.16.7)
# 멈출 때 보정 화면 = 원본 4K 디코딩(키프레임부터) + 보정. 근처 프레임으로 옮겨 다닐 때마다 디코딩하던 것을,
# 멈춘 곳 앞뒤 1초(RANGE_HALF)를 뒤에서 한 번에 1280 폭 10bit 로 풀어 메모리에 둠 → 근처 프레임은 디코딩 없이 보정만.
# 1장 ≈ 1280×720×1.5×2 B ≈ 2.8MB, 59.94fps 120장 ≈ 330MB, 구간 RANGE_MAX 개까지(오래 안 쓴 것부터 지움).
RANGE_HALF = 60
RANGE_MAX = 4
_ranges: "dict[tuple, tuple]" = {}            # (경로, 시작) → (시작, 끝(제외), 데이터, 폭, 높이, 1장 바이트)
_range_busy: set = set()
_range_lock = threading.Lock()


def _fit_preview(w: int, h: int) -> tuple[int, int]:
    """멈춘 보정 화면 크기 = 긴 쪽 1280(v0.16.54: 세로 영상은 720×1280 — 예전 1280×2276 은 화소가 3배라 느림)."""
    w, h = w or 3840, h or 2160
    if h > w:
        return int(round(PREVIEW_LONG * w / h / 2)) * 2, PREVIEW_LONG
    return PREVIEW_LONG, int(round(PREVIEW_LONG * h / w / 2)) * 2


def _preview_size(src) -> tuple[int, int]:
    return _fit_preview(src.width, src.height)


def range_lookup(path: str, lo: int, hi: int):
    """[lo, hi] 프레임이 모두 들어 있는 구간 → (데이터 조각, 폭, 높이) 또는 None."""
    path = os.path.abspath(path)
    with _range_lock:
        for k, (a, b, data, w, h, fs) in list(_ranges.items()):
            if k[0] == path and a <= lo and hi < b:
                _ranges[k] = _ranges.pop(k)           # 최근 사용 → 뒤로
                return data[(lo - a) * fs:(hi - a + 1) * fs], w, h
    return None


def prefetch_range(src: Source, center: int, gpu: bool = False) -> bool:
    """center 앞뒤 RANGE_HALF 프레임을 한 번에 디코딩해 둠(이미 덮여 있거나 만드는 중이면 건너뜀). 작업 스레드에서 부름."""
    path = os.path.abspath(src.path)
    a = max(0, center - RANGE_HALF)
    b = min(src.frames or center + RANGE_HALF, center + RANGE_HALF)
    if b - a < 2 or range_lookup(path, max(0, center - PREVIEW_LEAD - 8), min(b - 1, center + 8)) is not None:
        return False
    key = (path, a)
    with _range_lock:
        if key in _range_busy or any(k[0] == path and abs(k[1] - a) < RANGE_HALF // 3 for k in _range_busy):
            return False
        _range_busy.add(key)
    try:
        w, h = _preview_size(src)
        fs = w * h * 3                                 # yuv420p10le = 1.5 × 2바이트
        data = run([paths.ffmpeg(), "-v", "error", *_hw(gpu), "-ss", _seek(a, src.fps), "-i", _abs(src.path),
                    "-frames:v", str(b - a), "-an", "-vf", f"scale={w}:{h}:flags=lanczos,format=yuv420p10le",
                    "-f", "rawvideo", "-"])
        n = len(data) // fs
        if n < 2:
            return False
        with _range_lock:
            _ranges[key] = (a, a + n, data[:n * fs], w, h, fs)
            while len(_ranges) > RANGE_MAX:
                _ranges.pop(next(iter(_ranges)))
        return True
    finally:
        with _range_lock:
            _range_busy.discard(key)


def range_clear(path: str | None = None):
    with _range_lock:
        for k in [k for k in _ranges if path is None or k[0] == os.path.abspath(path)]:
            _ranges.pop(k, None)


_frame_cache: "dict[str, CachedFrame]" = {}
_frame_locks: dict[str, threading.Lock] = {}
_cache_lock = threading.Lock()


def cached_frame(src: Source, frame: int, gpu: bool = False) -> CachedFrame:
    """원본의 (앞 프레임 + 해당 프레임)을 1280 폭 10bit 무손실(ffv1, nut)로 메모리에 보관."""
    key = f"{os.path.abspath(src.path)}|{frame}"
    with _cache_lock:
        lk = _frame_locks.setdefault(key, threading.Lock())
    try:
        with lk:                                   # 같은 프레임 동시 생성 방지
            with _cache_lock:
                c = _frame_cache.get(key)
            if c is not None:
                return c
            lead = min(PREVIEW_LEAD, frame)
            hit = range_lookup(src.path, frame - lead, frame)      # 원본 구간 캐시에 있으면 디코딩 없이
            if hit is not None:
                data, w, h = hit
                return CachedFrame(data, lead, (w, h), "raw", key + "|r")
            pw, ph = _preview_size(src)
            data = run([paths.ffmpeg(), "-v", "error", "-ss", _seek(frame - lead, src.fps), "-i", _abs(src.path),
                        "-frames:v", str(lead + 1), "-an", "-vf", f"scale={pw}:{ph}:flags=lanczos,format=yuv420p10le",
                        "-c:v", "ffv1", "-f", "nut", "-"])
            c = CachedFrame(data, lead, (pw, ph), "nut", key)
            with _cache_lock:
                _frame_cache[key] = c
                while len(_frame_cache) > _FRAME_CACHE_MAX:
                    _frame_cache.pop(next(iter(_frame_cache)))
            return c
    finally:
        with _cache_lock:                          # 프레임마다 잠금이 계속 쌓이지 않게(v0.16.40)
            if not lk.locked():
                _frame_locks.pop(key, None)


def frame_ready(src: Source, frame: int) -> bool:
    """원본 보정 화면 입력이 이미 메모리에 있음(디코딩 없이 바로) = 프리뷰 먼저 보이기 필요 없음."""
    key = f"{os.path.abspath(src.path)}|{frame}"
    with _cache_lock:
        if key in _frame_cache:
            return True
    return range_lookup(src.path, frame - min(PREVIEW_LEAD, frame), frame) is not None


def cached_frame_preview(src: Source, frame: int, pv: dict) -> CachedFrame:
    """멈춘 화면 먼저 보이기(v0.16.22): 카메라 프리뷰(LRF 등)에서 같은(또는 바로 앞) 화면 + 앞 2장 → 1280 폭 10bit.
    H.264 720p 라 원본 4K 보다 훨씬 빠름. 화질(디테일·계조)은 원본보다 낮아 곧 원본으로 바뀜."""
    k = preview_pos(pv, frame)
    key = f"pv|{os.path.abspath(pv['path'])}|{k}"
    with _cache_lock:
        c = _frame_cache.get(key)
    if c is not None:
        return c
    lead = min(2, k)
    cw, ch = _fit_preview(pv["w"], pv["h"])
    data = run([paths.ffmpeg(), "-v", "error", "-ss", _seek(k - lead, preview_fps(pv)), "-i", _abs(pv["path"]),
                "-frames:v", str(lead + 1), "-an", "-vf", f"scale={cw}:{ch}:flags=bicubic,format=yuv420p10le",
                "-c:v", "ffv1", "-f", "nut", "-"])
    c = CachedFrame(data, lead, (cw, ch), "nut", key)
    with _cache_lock:
        _frame_cache[key] = c
        while len(_frame_cache) > _FRAME_CACHE_MAX:
            _frame_cache.pop(next(iter(_frame_cache)))
    return c


def preview_grade(g: dict | None, pv: dict) -> dict | None:
    """프리뷰가 이미 709(색 raw)면 LUT 빼고 같은 보정."""
    if g is None or pv.get("color") == "lut":
        return g
    return {**g, "lut": ""}


def lut_only(g: dict | None) -> dict:
    """보정 전 화면 = LUT만(반반 왼쪽 · [원본] 보기 · 샘플 왼쪽). v0.16.2 부터 Log 원본 대신."""
    from .project import NEUTRAL
    return {**NEUTRAL, "lut": (g or {}).get("lut", "")}


_pv_memo: "dict[tuple, bytes]" = {}        # (화면 표시, 보정값) → PNG. 반반의 '보정 전'·샘플 타일처럼 같은 화면을 되풀이해 만들던 것(v0.16.40)
_PV_MEMO_MAX = 96
_pv_memo_lock = threading.Lock()


def render_preview(cached: CachedFrame, g: dict | None) -> bytes:
    """보정 적용 결과(마지막 프레임)를 PNG 바이트로. g=None 이면 보정 전(원본 Log).
    같은 화면·같은 보정값은 기억해 둔 것을 돌려줌(최근 96장)."""
    mk = (cached.key, json.dumps(g, sort_keys=True, default=str), _lut_for(g)[1] if g else None) if cached.key else None
    if mk is not None:
        with _pv_memo_lock:
            hit = _pv_memo.get(mk)
            if hit is not None:
                _pv_memo[mk] = _pv_memo.pop(mk)
                return hit
    out = _render_preview(cached, g)
    if mk is not None:
        with _pv_memo_lock:
            _pv_memo[mk] = out
            while len(_pv_memo) > _PV_MEMO_MAX:
                _pv_memo.pop(next(iter(_pv_memo)))
    return out


def _render_preview(cached: CachedFrame, g: dict | None) -> bytes:
    cwd, lut = (None, None)
    if g is None:
        vf = []
    else:
        cwd, lut = _lut_for(g)
        vf = lens_chain(g, *cached.size) + grade_chain(g, lut, cached.size[0])
    vf = last_only(vf, cached.lead) + ["format=rgb24"]
    return run([paths.ffmpeg(), "-v", "error", *cached.input_args(), "-filter_complex", graph(vf, "[0:v]", "[po]"),
                "-map", "[po]", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"], cwd=cwd, data=cached.data)


def render_region(src: Source, frame: int, g: dict | None, rect, max_w: int = 2560) -> bytes:
    """확대 보기: 원본(4K)에서 보이는 영역만 잘라 보정 → PNG. rect = (x, y, w, h) 0~1."""
    x, y, w, h = rect
    W, H = src.width or 3840, src.height or 2160
    cw, ch = max(16, int(w * W)) // 2 * 2, max(16, int(h * H)) // 2 * 2
    cx, cy = min(W - cw, int(x * W)) // 2 * 2, min(H - ch, int(y * H)) // 2 * 2
    lead = min(PREVIEW_LEAD, frame)
    cwd, lut = (None, None)
    vf = (lens_chain(g, W, H) if g else []) + [f"crop={cw}:{ch}:{cx}:{cy}"]
    if cw > max_w:
        vf.append(f"scale={max_w}:-2:flags=lanczos")
    if g is not None:
        cwd, lut = _lut_for(g)
        vf += grade_chain(g, lut, 3840)
    vf = last_only(vf, lead) + ["format=rgb24"]
    return run([paths.ffmpeg(), "-v", "error", "-ss", _seek(frame - lead, src.fps), "-i", _abs(src.path),
                "-frames:v", str(lead + 1), "-an", "-filter_complex", graph(vf, "[0:v]", "[po]"), "-map", "[po]",
                "-f", "image2pipe", "-c:v", "png", "-"], cwd=cwd)


# ------------------------------------------------------------------ 선명도
def sharpness_around(src: Source, frame: int, radius: int = 5) -> list[tuple[int, float]]:
    import numpy as np
    start = max(0, frame - radius)
    n = min(src.frames, frame + radius + 1) - start
    w, h = 960, 540
    raw = run([paths.ffmpeg(), "-v", "error", "-ss", _seek(start, src.fps), "-i", src.path,
               "-frames:v", str(n), "-an", "-vf", f"scale={w}:{h},format=gray",
               "-f", "rawvideo", "-"])
    arr = np.frombuffer(raw, np.uint8)
    cnt = len(arr) // (w * h)
    res = []
    for i in range(cnt):
        im = arr[i * w * h:(i + 1) * w * h].reshape(h, w).astype(np.float32)
        lap = (-4 * im[1:-1, 1:-1] + im[:-2, 1:-1] + im[2:, 1:-1] + im[1:-1, :-2] + im[1:-1, 2:])
        res.append((start + i, float(lap.var())))
    return res


# ------------------------------------------------------------------ 화면 전환
XFADE = {"dissolve": "fade", "wipeleft": "wipeleft", "wiperight": "wiperight", "wipeup": "wipeup",
         "wipedown": "wipedown", "zoomin": "fade", "zoomout": "fade", "rotzoomin": "fade", "rotzoomout": "fade",
         "fadeblack": "fadeblack", "fadewhite": "fadewhite"}


def zoom_filter(kind: str, start: float, dur: float, head: bool) -> str:
    """빠른 줌(회전 없음): perspective(프레임마다 계산, 3차 보간, 크기 고정).
    u = 0→1 가속(제곱). 배율 s = 1+2u.
    tail(앞 컷 끝): start~start+dur 동안 확대(회전). head(뒷 컷 시작): 0~dur 동안 확대 상태에서 원래로."""
    fps = float(OUT_FPS)
    if head:
        u = f"pow(1-clip(in/{fps:.5f}/{dur:.5f},0,1),2)"
        en = f"lte(t,{dur + 0.5 / fps:.5f})"
    else:
        u = f"pow(clip((in/{fps:.5f}-{start:.5f})/{dur:.5f},0,1),2)"
        en = f"gte(t,{start - 0.5 / fps:.5f})"
    sc = f"(1+2*{u})"
    th = "0"

    def pt(dx, dy):     # 출력 모서리 ← 원본 좌표: 중심 + R(θ)(모서리-중심)/s
        return (f"W/2+(({dx})*cos({th})-({dy})*sin({th}))/{sc}",
                f"H/2+(({dx})*sin({th})+({dy})*cos({th}))/{sc}")
    xy = [pt(dx, dy) for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:interpolation=cubic:eval=frame:enable='{en}'"


# 회전 줌(v0.16.11): 앞 컷 0→180° · 뒤 컷 −180→0° 를 이어 돌림(가운데 가장 빠름) + 모션블러.
ROT_DEG = 180.0
ROT_MIX = 0.2          # 겹침 구간 가운데에서 섞는 비율(나머지는 한 컷만 보임 → 회전이 흐려지지 않음)
ROT_BLUR = 16          # 모션블러 서브프레임 수
ROT_SHUTTER = 0.5      # 셔터 180°(1프레임 시간의 절반)
ROT_EXTRA = 0.5        # 검은 모서리 안 생기는 확대 위에 더하는 확대(가운데 최대)
ROT_KINDS = ("rotzoomin",)            # v0.16.38: 회전 줌아웃 = 따로(ROTOUT) — 예전엔 방향만 다른 같은 효과
ROTOUT = "rotzoomout"
ROTOUT_SA = 0.75       # 앞 컷이 작아지는 양(1 → 0.25)
ROTOUT_SB = 0.6        # 뒤 컷 시작 확대(1.6 → 1)
ROTOUT_FADE = (0.7, 0.95)   # 앞 컷이 사라지는 진행 구간


def rotout_state(v: float) -> tuple[float, float, float, float]:
    """회전 줌아웃 진행 v(0~1) → (앞 컷 각도°(화면 시계 +), 앞 컷 배율, 앞 컷 불투명도, 뒤 컷 배율). 미리보기·렌더 같은 식."""
    v = max(0.0, min(1.0, v))
    e = 4 * v ** 3 if v < 0.5 else 1 - (-2 * v + 2) ** 3 / 2
    a0, a1 = ROTOUT_FADE
    op = max(0.0, min(1.0, (a1 - v) / (a1 - a0)))
    return ROT_DEG * e, 1 - ROTOUT_SA * e, op, 1 + ROTOUT_SB * (1 - e)


def _ease(v: str) -> str:
    return f"if(lt({v},0.5),4*pow({v},3),1-pow(2-2*{v},3)/2)"


def _rotout_a(off: float, nd: int) -> str:
    """앞 컷 한 장(투명 테두리 덧댄 뒤): 시계 방향으로 돌며 작아짐 — sense=destination(원본 모서리를 보낼 자리)."""
    v = f"clip((in+{off:.5f})/{nd},0,1)"
    e = _ease(v)
    th = f"(PI*{e})"
    sc = f"(1-{ROTOUT_SA}*{e})"

    def pt(dx, dy):
        return (f"W/2+(({dx})*cos({th})-({dy})*sin({th}))*{sc}",
                f"H/2+(({dx})*sin({th})+({dy})*cos({th}))*{sc}")
    xy = [pt(dx, dy) for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:sense=destination:interpolation=cubic:eval=frame"


def _rotout_b(nd: int) -> str:
    """뒤 컷: 확대(1.6) → 원래(1). 회전 없음."""
    v = f"clip(in/{nd},0,1)"
    sc = f"(1+{ROTOUT_SB}*(1-{_ease(v)}))"
    xy = [(f"W/2+({dx})/{sc}", f"H/2+({dy})/{sc}") for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:interpolation=cubic:eval=frame"


def rotout_mix(fparts: list, a_lab: str, b_lab: str, out: str, nd: int, w: int, h: int, uid: str, blur: int = ROT_BLUR):
    """앞 컷 마지막 nd 장(a_lab) + 뒤 컷 처음 nd 장(b_lab) → 회전 줌아웃 nd 장. 앞 컷 = 투명 테두리 2px 덧대 돌리고 줄여
    (perspective 는 바깥을 가장자리로 채움 → 투명 테두리가 바깥 = 투명) 모션블러 후 서서히 사라짐, 뒤 컷 위에 얹음."""
    fps = float(OUT_FPS)
    a0, a1 = ROTOUT_FADE
    pre = f"{a_lab}format=yuva444p,pad=iw+4:ih+4:2:2:color=black@0"
    n = max(1, int(blur))
    if n == 1:
        fparts.append(f"{pre},{_rotout_a(0, nd)}[ra{uid}]")
    else:
        subs = [f"[ras{uid}_{j}]" for j in range(n)]
        fparts.append(f"{pre},split={n}{''.join(subs)}")
        outs = []
        for j, lab in enumerate(subs):
            o = f"[rap{uid}_{j}]"
            fparts.append(f"{lab}{_rotout_a((j / (n - 1) - 0.5) * ROT_SHUTTER, nd)}{o}")
            outs.append(o)
        fparts.append(f"{''.join(outs)}mix=inputs={n}[ra{uid}]")
    fparts.append(f"[ra{uid}]crop=iw-4:ih-4:2:2,fade=t=out:st={a0 * nd / fps:.5f}:d={(a1 - a0) * nd / fps:.5f}:alpha=1[rb{uid}]")
    fparts.append(f"{b_lab}{_rotout_b(nd)},format=yuva444p[rc{uid}]")
    fparts.append(f"[rc{uid}][rb{uid}]overlay=0:0:format=yuv444:eof_action=pass,format=yuv420p,setsar=1,setpts=PTS-STARTPTS{out}")


def rot_frames(d: float) -> tuple[int, int, int]:
    """전환 길이(초) → (겹침 프레임 nd, 한쪽만 보이는 프레임 k, 섞는 프레임 x). nd = 2k + x."""
    nd = max(3, int(round(d * float(OUT_FPS))))
    k = int(round(nd * (1 - ROT_MIX) / 2))
    x = max(1, nd - 2 * k)
    return k * 2 + x, k, x


def rot_state(kind: str, v: float) -> tuple[float, float]:
    """미리보기·점검용: 진행 v(0~1) → (앞 컷 각도°, 배율). 뒤 컷 각도 = 앞 컷 − 180°(방향 부호 포함)."""
    import math
    v = max(0.0, min(1.0, v))
    e = 4 * v ** 3 if v < 0.5 else 1 - (-2 * v + 2) ** 3 / 2
    th = math.radians(ROT_DEG * e)
    r = 16 / 9
    cov = abs(math.cos(th)) + abs(math.sin(th)) * r
    w = v ** (1.16 if kind == "rotzoomin" else 0.87)
    s = cov * (1 + ROT_EXTRA * math.sin(math.pi * w))
    return (1 if kind == "rotzoomin" else -1) * ROT_DEG * e, s


def _rot_persp(kind: str, role: str, off: float, nd: int) -> str:
    """perspective 한 장: in = 창 안 프레임 번호, off = 서브프레임 시간 + 시작 위치(프레임). role a = 앞 컷 / b = 뒤 컷."""
    v = f"clip((in+{off:.5f})/{nd},0,1)"
    e = f"if(lt({v},0.5),4*pow({v},3),1-pow(2-2*{v},3)/2)"
    sign = 1 if kind == "rotzoomin" else -1
    th = f"({sign}*PI*({e}{'' if role == 'a' else '-1'}))"
    pw = 1.16 if kind == "rotzoomin" else 0.87
    sc = (f"((abs(cos({th}))+abs(sin({th}))*max(W/H,H/W))*(1+{ROT_EXTRA}*sin(PI*pow({v},{pw}))))")

    def pt(dx, dy):
        return (f"W/2+(({dx})*cos({th})-({dy})*sin({th}))/{sc}",
                f"H/2+(({dx})*sin({th})+({dy})*cos({th}))/{sc}")
    xy = [pt(dx, dy) for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:interpolation=cubic:eval=frame"


def rot_window(fparts: list, inlab: str, outlab: str, kind: str, role: str, f0: int, f1: int, start: int, nd: int,
               uid: str, blur: int = ROT_BLUR) -> None:
    """컷의 프레임 f0~f1(제외) 를 회전 줌 + 모션블러로. start = 창 첫 프레임의 진행 위치(프레임)."""
    pre = f"{inlab}trim=start_frame={f0}:end_frame={f1},setpts=PTS-STARTPTS"
    n = max(1, int(blur))
    if n == 1:
        fparts.append(f"{pre},{_rot_persp(kind, role, start, nd)},setpts=PTS-STARTPTS{outlab}")
        return
    subs = [f"[rs{uid}_{j}]" for j in range(n)]
    fparts.append(f"{pre},split={n}{''.join(subs)}")
    outs = []
    for j, lab in enumerate(subs):
        off = start + (j / (n - 1) - 0.5) * ROT_SHUTTER
        o = f"[rp{uid}_{j}]"
        fparts.append(f"{lab}{_rot_persp(kind, role, off, nd)}{o}")
        outs.append(o)
    fparts.append(f"{''.join(outs)}mix=inputs={n}{outlab}")


_FF_MAJOR = None


def ffmpeg_major() -> int:
    """ffmpeg 주 버전(못 읽으면 0)."""
    global _FF_MAJOR
    if _FF_MAJOR is None:
        try:
            v = run([paths.ffmpeg(), "-hide_banner", "-version"]).decode(errors="ignore").split()
            num = v[2] if len(v) > 2 else ""
            _FF_MAJOR = int(num.split(".")[0]) if num[:1].isdigit() else 99    # master 빌드(N-xxxxx) = 최신
        except Exception:
            _FF_MAJOR = 0
    return _FF_MAJOR


FG_INLINE_MAX = 6000      # 이보다 긴 그래프는 파일로(Windows 명령줄 32K 제한 · 회전 줌 모션블러)


def filter_complex_args(graph_text: str) -> list[str]:
    """필터 그래프 인자. 길면 cache/lut 에 파일로 쓰고 ffmpeg 7+ 은 -/filter_complex, 그 전은 -filter_complex_script."""
    if len(graph_text) <= FG_INLINE_MAX:
        return ["-filter_complex", graph_text]
    d = paths.cache_dir() / "lut"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"fg_{hashlib.sha1(graph_text.encode()).hexdigest()[:16]}.txt"
    if not f.exists():
        tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(graph_text, encoding="utf-8")
        replace_retry(str(tmp), str(f))
    return ["-/filter_complex" if ffmpeg_major() >= 7 else "-filter_complex_script", str(f.resolve())]


def transition_graph(fparts: list, plan: list, lens: list, audio: bool, blur: int = ROT_BLUR) -> float:
    """[v0][a0]… 를 화면 전환(xfade/acrossfade)과 이어붙이기(concat)로 연결 → [vo][ao]. 결과 길이(초) 반환."""
    n = len(lens)
    fps = float(OUT_FPS)
    vl = [f"[v{i}]" for i in range(n)]
    al = [f"[a{i}]" for i in range(n)]
    eff = list(lens)                          # 회전 줌으로 앞뒤를 잘라 낸 뒤 길이
    xdur = [0.0] * n                          # 경계 i 의 xfade 길이(초)
    adur = [0.0] * n                          # 경계 i 의 acrossfade 길이(초)
    for i in range(n):
        t = plan[i]
        if t and i > 0:
            if t[0] in ROT_KINDS:
                nd, k, x = rot_frames(t[1])
                eff[i - 1] -= k / fps
                eff[i] -= k / fps
                xdur[i], adur[i] = x / fps, nd / fps
            elif t[0] == ROTOUT:
                nd = max(3, int(round(t[1] * fps)))
                xdur[i] = adur[i] = nd / fps
            else:
                xdur[i] = adur[i] = t[1]
    for i in range(n):                       # 컷 자체에 들어가는 효과(줌·회전 줌·첫 컷 페이드)
        f = []
        nxt = plan[i + 1] if i + 1 < n else None
        cur = plan[i]
        if nxt and nxt[0] == "zoomin":
            f.append(zoom_filter(nxt[0], lens[i] - nxt[1], nxt[1], head=False))
        if cur and i > 0 and cur[0] == "zoomout":
            f.append(zoom_filter(cur[0], 0, cur[1], head=True))
        if cur and i == 0:
            f.append(f"fade=t=in:st=0:d={cur[1]:.5f}:color={'white' if cur[0] == 'fadewhite' else 'black'}")
            if audio:
                fparts.append(f"[a0]afade=t=in:st=0:d={cur[1]:.5f}[a0f]")
                al[0] = "[a0f]"
        f.append("settb=AVTB")
        head = cur if (cur and i > 0 and cur[0] in ROT_KINDS) else None
        tail = nxt if (nxt and nxt[0] in ROT_KINDS) else None
        if not (head or tail):
            fparts.append(f"{vl[i]}{','.join(f)}[w{i}]")
            vl[i] = f"[w{i}]"
            continue
        lf = int(round(lens[i] * fps))
        pieces = []                           # (종류, f0, f1, …)
        b0, b1 = 0, lf
        if head:
            nd, k, _x = rot_frames(head[1])
            pieces.append(("b", k, nd, head[0], k, nd))
            b0 = nd
        if tail:
            nd, k, _x = rot_frames(tail[1])
            b1 = lf - nd
            tail_piece = ("a", lf - nd, lf - k, tail[0], 0, nd)
        if b1 > b0:
            pieces.append(("body", b0, b1))
        if tail:
            pieces.append(tail_piece)
        m = len(pieces)
        fparts.append(f"{vl[i]}{','.join(f)},split={m}" + "".join(f"[c{i}_{j}]" for j in range(m)))
        outs = []
        for j, pc in enumerate(pieces):
            o = f"[d{i}_{j}]"
            if pc[0] == "body":
                fparts.append(f"[c{i}_{j}]trim=start_frame={pc[1]}:end_frame={pc[2]},setpts=PTS-STARTPTS{o}")
            else:
                role, f0, f1, kind, start, nd = pc
                rot_window(fparts, f"[c{i}_{j}]", o, kind, role, f0, f1, start, nd, f"{i}_{j}", blur)
            outs.append(o)
        if m == 1:
            fparts.append(f"{outs[0]}null,settb=AVTB[w{i}]")
        else:
            fparts.append(f"{''.join(outs)}concat=n={m}:v=1:a=0,settb=AVTB[w{i}]")
        vl[i] = f"[w{i}]"
    acc_v, acc_a, acc = vl[0], al[0], eff[0]
    for i in range(1, n):
        last = i == n - 1
        ov, oa = ("[vo]", "[ao]") if last else (f"[xv{i}]", f"[xa{i}]")
        t = plan[i]
        if t and t[0] == ROTOUT:              # v0.16.38 회전 줌아웃 = 앞 컷 끝 nd 장 · 뒤 컷 처음 nd 장을 얹어 합침
            d = xdur[i]
            nd = int(round(d * fps))
            pf = int(round(acc * fps))
            fparts.append(f"{acc_v}split=2[zp{i}][za{i}]")
            fparts.append(f"[zp{i}]trim=end_frame={pf - nd},setpts=PTS-STARTPTS[zpre{i}]")
            fparts.append(f"[za{i}]trim=start_frame={pf - nd}:end_frame={pf},setpts=PTS-STARTPTS[zaw{i}]")
            fparts.append(f"{vl[i]}split=2[zb{i}][zq{i}]")
            fparts.append(f"[zb{i}]trim=end_frame={nd},setpts=PTS-STARTPTS[zbw{i}]")
            fparts.append(f"[zq{i}]trim=start_frame={nd},setpts=PTS-STARTPTS[zpost{i}]")
            rotout_mix(fparts, f"[zaw{i}]", f"[zbw{i}]", f"[zmid{i}]", nd, 0, 0, f"z{i}", blur)
            fparts.append(f"[zpre{i}]format=yuv420p,settb=AVTB[zp2{i}]")
            fparts.append(f"[zmid{i}]settb=AVTB[zm2{i}]")
            fparts.append(f"[zpost{i}]format=yuv420p,settb=AVTB[zq2{i}]")
            fparts.append(f"[zp2{i}][zm2{i}][zq2{i}]concat=n=3:v=1:a=0{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}acrossfade=d={adur[i]:.5f}{oa}")
            acc += eff[i] - d
        elif t:
            d = xdur[i]
            fparts.append(f"{acc_v}{vl[i]}xfade=transition={XFADE[t[0]]}:duration={d:.5f}:offset={acc - d:.5f}{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}acrossfade=d={adur[i]:.5f}{oa}")
            acc += eff[i] - d
        else:
            fparts.append(f"{acc_v}{vl[i]}concat=n=2:v=1:a=0{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}concat=n=2:v=0:a=1{oa}")
            acc += eff[i]
        acc_v, acc_a = ov, oa
    if n == 1:
        fparts.append(f"{acc_v}null[vo]")
        if audio:
            fparts.append(f"{acc_a}anull[ao]")
    return acc


# ------------------------------------------------------------------ 영상 렌더
YUV444_709 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p10le"
OV_CONVERT = "out_color_matrix=bt709:out_range=tv"


def seg_layers(project: Project, seg: Segment) -> list[tuple[dict, ImageSource, int, int]]:
    """컷 범위 안으로 자른 레이어 [(layer, image, fin, fout)]. 이미지 파일이 없으면 건너뜀."""
    out = []
    for lay in seg.layers:
        img = project.image(lay.get("img", ""))
        if img is None or not img.width or not os.path.exists(img.path):
            continue
        lf, lo = max(seg.fin, int(lay["fin"])), min(seg.fout, int(lay["fout"]))
        if lo > lf:
            out.append((lay, img, lf, lo))
    return out


def probe_audio(path: str) -> float:
    """음악 파일 길이(초)."""
    out = run([paths.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.decode().strip() or 0)


def _hex(c: str) -> str:
    c = (c or "#ffffff").lstrip("#")
    return "0x" + (c if len(c) == 6 else "ffffff")


def _fade_alpha(t0, t1, f, fin: bool = True, fout: bool = True):
    f = min(f, (t1 - t0) / 2)
    if f <= 0.01 or not (fin or fout):
        return "1"
    a = f"(t-{t0:.4f})/{f:.4f}" if fin else "1"
    b = f"({t1:.4f}-t)/{f:.4f}" if fout else "1"
    return f"if(lt(t,{t0 + f:.4f}),{a},if(gt(t,{t1 - f:.4f}),{b},1))"


def _anim_sides(t: dict) -> tuple[str, str, float]:
    """(들어올 때, 나갈 때, 길이) — 밀기가 아니면 'fade'."""
    from .project import ANIMS
    t0, t1 = float(t["t0"]), float(t["t1"])
    fd = min(float(t.get("fade", 0.5)), (t1 - t0) / 2)
    ain, aout = t.get("ain", "fade"), t.get("aout", "fade")
    return (ain if ain in ANIMS[1:] else "fade"), (aout if aout in ANIMS[1:] else "fade"), fd


def _slide_xy(t: dict, x0: str, y0: str, w: str, h: str, ow: int, oh: int, pad: float) -> tuple[str, str]:
    """밀려 들어오기/나가기(v0.16.57) → overlay·drawtext 의 x, y 식(t = 초). project.title_anim/anim_offset 과 같은 계산.
    x0·y0·w·h = 제자리 위치·크기(숫자 또는 text_w 같은 식)."""
    ain, aout, fd = _anim_sides(t)
    if fd <= 0.01 or (ain == "fade" and aout == "fade"):
        return x0, y0
    t0, t1 = float(t["t0"]), float(t["t1"])
    away = {"right": (f"({ow}-({x0})+{pad:.1f})", ""), "left": (f"(-(({x0})+({w})+{pad:.1f}))", ""),
            "up": ("", f"(-(({y0})+({h})+{pad:.1f}))"), "down": ("", f"({oh}-({y0})+{pad:.1f})")}
    opp = {"right": "left", "left": "right", "up": "down", "down": "up"}
    fin = f"pow(1-(t-{t0:.4f})/{fd:.4f},3)"
    fout = f"pow((t-{t1 - fd:.4f})/{fd:.4f},3)"
    out = []
    for axis, base in ((0, x0), (1, y0)):
        e = f"({base})"
        if ain != "fade" and away[opp[ain]][axis]:
            e += f"+if(lt(t,{t0 + fd:.4f}),{away[opp[ain]][axis]}*{fin},0)"
        if aout != "fade" and away[aout][axis]:
            e += f"+if(gt(t,{t1 - fd:.4f}),{away[aout][axis]}*{fout},0)"
        out.append(e)
    return out[0], out[1]


def _fade_chain(t: dict) -> list[str]:
    """사각형·이미지: 페이드를 고른 쪽만 알파 페이드."""
    ain, aout, fd = _anim_sides(t)
    t0, t1 = float(t["t0"]), float(t["t1"])
    c = []
    if fd > 0.01 and ain == "fade":
        c.append(f"fade=t=in:st={t0:.4f}:d={fd:.4f}:alpha=1")
    if fd > 0.01 and aout == "fade":
        c.append(f"fade=t=out:st={t1 - fd:.4f}:d={fd:.4f}:alpha=1")
    return c


def _work_copy(path: str, prefix: str) -> str:
    """글꼴·글자 파일을 작업 폴더(cache/lut, cwd)로 → 경로 이스케이프 문제 없음."""
    d = paths.cache_dir() / "lut"
    d.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    h = hashlib.sha1(f"{src.resolve()}|{src.stat().st_size}".encode()).hexdigest()[:10]
    dst = d / f"{prefix}_{h}{src.suffix.lower()}"
    _safe_copy(src, dst)
    return dst.name


def text_filter(t: dict, ow: int, oh: int) -> str | None:
    """타임라인 글자 1개 → drawtext."""
    from .fonts import font_file
    if not (t.get("text") or "").strip():
        return None
    k = min(ow, oh) / 1080
    ffile, real_bold = font_file(t.get("font", ""), bool(t.get("bold")))
    if not ffile:
        return None
    fname = _work_copy(ffile, "font")
    txt = (t.get("text") or "").replace("\r\n", "\n")
    tf = paths.cache_dir() / "lut" / f"tx_{hashlib.sha1(txt.encode()).hexdigest()[:10]}.txt"
    tf.write_text(txt, encoding="utf-8")
    t0, t1 = float(t["t0"]), float(t["t1"])
    col = _hex(t.get("color"))
    o = [f"fontfile={fname}", f"textfile={tf.name}", f"fontsize={max(8, round(float(t.get('size', 64)) * k))}",
         f"fontcolor={col}", "text_align=C", f"line_spacing={round(8 * k)}",
         ]
    sx, sy = _slide_xy(t, f"{float(t.get('cx', 0.5)) * ow:.1f}-text_w/2", f"{float(t.get('cy', 0.8)) * oh:.1f}-text_h/2",
                       "text_w", "text_h", ow, oh, 24 * k)
    o += [f"x='{sx}'", f"y='{sy}'"]
    if t.get("bold") and not real_bold:
        o.append(f"borderw={max(1, round(1.5 * k))}:bordercolor={col}")
    bg = t.get("bg", "shadow")
    if bg == "shadow":
        sh = max(1, round(3 * k))
        o.append(f"shadowx={sh}:shadowy={sh}:shadowcolor=0x000000@0.6")
    elif bg == "band":
        o.append(f"box=1:boxcolor=0x000000@0.45:boxborderw={round(16 * k)}")
    o.append(f"enable='between(t,{t0:.4f},{t1:.4f})'")
    ain, aout, _fd = _anim_sides(t)
    o.append(f"alpha='{_fade_alpha(t0, t1, float(t.get('fade', 0.5)), ain == 'fade', aout == 'fade')}'")
    return "drawtext=" + ":".join(o)


def rect_box(t: dict, ow: int, oh: int) -> tuple[int, int, int, int]:
    """사각형 레이어 → (x, y, w, h) 출력 px."""
    w = max(2, int(round(float(t.get("w", 0.6)) * ow)))
    h = max(2, int(round(float(t.get("h", 0.16)) * oh)))
    x = int(round(float(t.get("cx", 0.5)) * ow - w / 2))
    y = int(round(float(t.get("cy", 0.5)) * oh - h / 2))
    return x, y, w, h


RECT_SHADOW_ALPHA = 0.5          # 사각형 그림자 = 검정 50%(× 사각형 불투명도는 안 곱함), 가장자리 부드럽게


def rect_margin(t: dict, k: float) -> int:
    """그림자 때문에 사각형 그림이 사방으로 넓어지는 px(그림자 없음 = 0). 그림자 = 오른쪽 아래로 거리 d, 번짐 = d 의 절반."""
    d = max(0.0, float(t.get("shadow", 0))) * k
    import math
    return int(math.ceil(d * 1.5)) + 1 if d > 0.25 else 0


def rect_png(t: dict, w: int, h: int, k: float) -> str:
    """사각형 레이어 그림(PNG, 색·불투명도·둥근 모서리, 가장자리 부드럽게) → 캐시 파일 경로. Qt 없이(작업 스레드 안전).
    v0.16.59: 테두리(border = 두께 px·1080 기준, bcolor, 사각형 안쪽으로) · 그림자(shadow = 거리 px·1080 기준, 오른쪽 아래).
    그림자가 있으면 그림이 사방 rect_margin 만큼 큼(얹을 때 그만큼 왼쪽 위로)."""
    import hashlib
    import struct
    import zlib
    import numpy as np
    col = (t.get("color") or "#000000").lstrip("#")
    bcol = (t.get("bcolor") or "#ffffff").lstrip("#")
    op = max(0.0, min(1.0, float(t.get("opacity", 0.5))))
    rad = max(0.0, min(min(w, h) / 2, float(t.get("radius", 0)) * k))
    bw = max(0.0, min(min(w, h) / 2, float(t.get("border", 0)) * k))
    sd = max(0.0, float(t.get("shadow", 0))) * k
    m = rect_margin(t, k)
    key = hashlib.md5(f"{col}|{op:.3f}|{rad:.2f}|{w}|{h}|{bcol}|{bw:.2f}|{sd:.2f}".encode()).hexdigest()[:16]
    d = paths.cache_dir() / "rects"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"rect_{key}.png"
    if f.exists():
        return str(f)
    W, H = w + 2 * m, h + 2 * m
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5

    def mask(x0, y0, ww, hh, r, soft=0.5):
        """둥근 사각형 덮임(0~1). 가장자리 = 거리 ±soft 에 걸쳐 번짐(soft 0.5 = 1px 부드럽게)."""
        r = max(0.0, min(r, ww / 2, hh / 2))
        qx = np.abs(xx - (x0 + ww / 2)) - (ww / 2 - r)
        qy = np.abs(yy - (y0 + hh / 2)) - (hh / 2 - r)
        dist = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - r   # 바깥 +, 안 −
        return np.clip(0.5 - dist / (2 * soft), 0.0, 1.0).astype(np.float32)

    fill = mask(m, m, w, h, rad)
    rgb = np.zeros((H, W, 3), np.float32)
    alpha = np.zeros((H, W), np.float32)

    def over(c_hex, a):
        nonlocal rgb, alpha
        c = np.array([int(c_hex[0:2], 16), int(c_hex[2:4], 16), int(c_hex[4:6], 16)], np.float32)
        na = a + alpha * (1 - a)
        rgb = np.where(na[..., None] > 1e-6, (c * a[..., None] + rgb * (alpha * (1 - a))[..., None]) / np.maximum(na, 1e-6)[..., None], rgb)
        alpha = na
    if sd > 0.25:                                   # 그림자(맨 아래): 오른쪽 아래로 sd, 번짐 sd/2
        sh = mask(m + sd, m + sd, w, h, rad, soft=max(0.5, sd / 2))
        sh = sh * sh * (3 - 2 * sh)                 # 부드러운 감쇠
        over("000000", sh * RECT_SHADOW_ALPHA)
    over(col, fill * op)
    if bw > 0.25:                                   # 테두리(맨 위, 불투명): 사각형 안쪽으로 bw
        inner = mask(m + bw, m + bw, w - 2 * bw, h - 2 * bw, max(0.0, rad - bw)) if (w > 2 * bw and h > 2 * bw) else np.zeros_like(fill)
        over(bcol, np.clip(fill - inner, 0.0, 1.0))
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    rgba[..., 3] = np.round(np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(H))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(png)
    os.replace(tmp, f)
    return str(f)


def _clean_old(root, days: float = 1.0):
    """수심 그래프 그림 폴더: 하루 지난 것 지움."""
    import shutil
    import time
    try:
        for d in root.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > days * 86400:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def post_graph(fparts: list, cmd: list, project: Project, extras: dict, total: float, orientation: str,
               audio: bool, n_inputs: int) -> None:
    """[vm][am] → 타임라인 글자·이미지(아래→위) + 음악/원본 볼륨 → [vo][ao]."""
    ow, oh = out_size(orientation)
    titles = [t for t in extras.get("titles", []) if float(t["t1"]) > float(t["t0"]) and float(t["t0"]) < total]
    music = [m for m in extras.get("music", []) if os.path.exists(m.get("path", "")) and float(m["t0"]) < total]
    mix = extras.get("mix") or {}
    cur, k, ii = "[vm]", 0, n_inputs
    lay = extras.get("dive_layers")
    if lay:                                       # v0.16.84 수심 그래프(글자·이미지보다 아래)
        fr = f"{OUT_FPS.numerator}/{OUT_FPS.denominator}"
        y0, bh = int(lay["y0"]), int(lay["bh"])
        for kind in ("mul", "add", "gr", "txt"):
            cmd += ["-f", "concat", "-safe", "0", "-i", _abs(lay[kind])]
        fparts.append(f"{cur}split=2[dvm][dvb]")
        fparts.append(f"[dvb]crop={ow}:{bh}:0:{y0},format=gbrp10le[dvb0]")
        fparts.append(f"[{ii}:v:0]fps={fr},scale={ow}:{bh},format=gbrp10le[dvM]")
        fparts.append(f"[dvb0][dvM]blend=all_mode=multiply:shortest=0:repeatlast=1[dvb1]")
        fparts.append(f"[{ii + 1}:v:0]fps={fr},scale={ow}:{bh},format=gbrp10le[dvA]")
        fparts.append(f"[dvb1][dvA]blend=all_mode=addition:shortest=0:repeatlast=1[dvb2]")
        fparts.append(f"[{ii + 2}:v:0]fps={fr},format=yuva420p[dvG]")
        fparts.append(f"[dvb2]format=yuv420p[dvb3]")
        fparts.append(f"[dvb3][dvG]overlay=0:0:format=yuv420:eof_action=pass[dvb4]")
        fparts.append(f"[dvm][dvb4]overlay=0:{y0}:format=yuv420:eof_action=pass[dvo]")
        fparts.append(f"[{ii + 3}:v:0]fps={fr},format=yuva420p[dvT]")
        fparts.append(f"[dvo][dvT]overlay=0:0:format=yuv420:eof_action=pass[dvx]")
        cur, ii = "[dvx]", ii + 4
    for t in titles:
        nxt = f"[tv{k}]"
        if t.get("kind") == "text":
            f = text_filter(t, ow, oh)
            if not f:
                continue
            fparts.append(f"{cur}{f}{nxt}")
        elif t.get("kind") == "rect":                     # v0.16.34 사각형 = 그림으로 그려 얹기(페이드 포함)
            t0, t1 = float(t["t0"]), float(t["t1"])
            x, y, w, h = rect_box(t, ow, oh)
            png = rect_png(t, w, h, min(ow, oh) / 1080)
            mg = rect_margin(t, min(ow, oh) / 1080)             # 그림자만큼 큰 그림 → 그만큼 왼쪽 위에 얹음
            x, y, w, h = x - mg, y - mg, w + 2 * mg, h + 2 * mg
            cmd += ["-loop", "1", "-framerate", f"{OUT_FPS.numerator}/{OUT_FPS.denominator}", "-t", f"{total + 1:.3f}",
                    "-i", _abs(png)]
            chain = ["format=yuva420p"] + _fade_chain(t)
            sx, sy = _slide_xy(t, str(x), str(y), str(w), str(h), ow, oh, 2)
            fparts.append(f"[{ii}:v:0]{','.join(chain)}[ti{k}]")
            fparts.append(f"{cur}[ti{k}]overlay=x='{sx}':y='{sy}':format=yuv420:eof_action=pass"
                          f":enable='between(t,{t0:.4f},{t1:.4f})'{nxt}")
            ii += 1
        else:
            img = project.image(t.get("img", ""))
            if img is None or not img.width or not os.path.exists(img.path):
                continue
            t0, t1 = float(t["t0"]), float(t["t1"])
            cmd += ["-loop", "1", "-framerate", f"{OUT_FPS.numerator}/{OUT_FPS.denominator}", "-t", f"{total + 1:.3f}",
                    "-noautorotate", "-i", _abs(img.path)]
            x, y, w, h = layer_box(t, img, ow, oh)
            chain = ORIENT_FILTER.get(img.orient, []) + [f"scale=w={w}:h={h}:flags=lanczos:{OV_CONVERT}", "format=yuva420p"] + _fade_chain(t)
            sx, sy = _slide_xy(t, str(x), str(y), str(w), str(h), ow, oh, 2)
            fparts.append(f"[{ii}:v:0]{','.join(chain)}[ti{k}]")
            fparts.append(f"{cur}[ti{k}]overlay=x='{sx}':y='{sy}':format=yuv420:eof_action=pass"
                          f":enable='between(t,{t0:.4f},{t1:.4f})'{nxt}")
            ii += 1
        cur, k = nxt, k + 1
    fparts.append(f"{cur}null[vo]")
    if not audio:
        return
    vo = orig_volume(mix, music)
    spans = extras.get("loud") or []
    from .music import ramp_expr
    if spans:                                     # v0.16.66 말소리·수면 위 컷 = 원본을 키움(앞뒤 0.5초 경사)
        w = ramp_expr(spans)
        up = max(vo, float(mix.get("up_orig", 1.0)))
        fparts.append(f"[am]volume=eval=frame:volume='{vo:.3f}+{up - vo:.3f}*({w})'[ab]")
    else:
        fparts.append(f"[am]volume={vo:.3f}[ab]")
    dsp = extras.get("duck") or []                # 음악 낮춤: 키운 컷(30%) · 첫 컷(70%) · 마지막 컷(50%, v0.16.75)
    if dsp:
        wd = ramp_expr(dsp, weights=extras.get("duck_w"))
        duck = f"1-{1 - float(mix.get('up_music', 0.3)):.3f}*({wd})"
    else:
        duck = ""
    labs = ["[ab]"]
    spans = [(float(x["t0"]), float(x["t0"]) + float(x.get("len", x.get("dur", 0)))) for x in music]
    for j, m in enumerate(music):
        t0 = float(m["t0"])
        ln = max(0.05, min(float(m.get("len", m.get("dur", 0))), total - t0))
        fi, fo = min(float(mix.get("fin", 0.5)), ln / 2), min(float(mix.get("fout", 2.0)), ln / 2)
        # v0.16.64 크로스페이드: 다른 곡과 겹친 만큼 = 겹친 구간에서 줄고/커짐(두 곡 합이 일정한 곡선 qsin). 안 겹친 쪽 = 설정 페이드
        ci = max([b - t0 for k, (a_, b) in enumerate(spans) if k != j and a_ < t0 < b] + [0.0])
        co = max([t0 + ln - a_ for k, (a_, b) in enumerate(spans) if k != j and t0 < a_ < t0 + ln and b > t0 + ln] + [0.0])
        cmd += ["-i", _abs(m["path"])]
        a = [f"atrim=start={float(m.get('off', 0)):.4f}:duration={ln:.4f}", "asetpts=PTS-STARTPTS",
             "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if ci > 0.01:
            a.append(f"afade=t=in:st=0:d={min(ci, ln):.4f}:curve=qsin")
        elif fi > 0.01:
            a.append(f"afade=t=in:st=0:d={fi:.4f}")
        if co > 0.01:
            co = min(co, ln)
            a.append(f"afade=t=out:st={ln - co:.4f}:d={co:.4f}:curve=qsin")
        elif fo > 0.01:
            a.append(f"afade=t=out:st={ln - fo:.4f}:d={fo:.4f}")
        g_ = float(m.get("gain", 1.0) or 1.0) * float(m.get("boost", 1.0) or 1.0)     # v0.16.75 곡 음량 맞추기 · 블루워터 첫 등장 +3dB
        a += [f"volume={float(mix.get('music', 1.0)) * g_:.3f}", f"adelay=delays={int(t0 * 1000)}:all=1"]
        if duck:                                  # 그 컷 동안 음악 낮춤(adelay 뒤 = 결과 영상 시간)
            a.append(f"volume=eval=frame:volume='{duck}'")
        fparts.append(f"[{ii}:a:0]{','.join(a)}[mu{j}]")
        labs.append(f"[mu{j}]")
        ii += 1
    if len(labs) == 1:
        fparts.append("[ab]anull[ao]")
    else:
        fparts.append(f"{''.join(labs)}amix=inputs={len(labs)}:duration=first:normalize=0:dropout_transition=0[ao]")


def build_render_cmd(project: Project, segs: list[Segment], out_file: str, orientation: str | None = None,
                     audio: bool | None = None, fast: bool = False,
                     extras: dict | None = None, head_trim: int = 0,
                     gpu_scale: bool | None = None) -> tuple[list[str], float, str | None]:
    """head_trim(조각 렌더, v0.16.26) = 앞 출력 프레임 몇 장을 버림(노이즈 제거 시간축 예열). 컷 1개·소리 없음일 때만.
    gpu_scale(v0.16.28) = 4K → 출력 크기 축소를 GPU(scale_cuda)에서 한 뒤 CPU 로(넘기는 양 1/4, CPU 축소 없음).
    None = GPU 디코딩 켜짐이면 사용. 조건이 안 맞는 컷(크롭 필요·렌즈·흔들림·리프레임)은 그 컷만 CPU 축소."""
    o = project.output
    if gpu_scale is None:
        gpu_scale = bool(o.gpu_decode) and has_cuda() and not fast and _setting_int("gpu_scale", 1) != 0
    orientation = orientation or o.orientation
    audio = o.audio if audio is None else audio
    cmd = [paths.ffmpeg(), "-y"]
    fparts, labels = [], []
    total = 0.0
    cwd = None
    img_inputs: list[str] = []          # 이미지 입력은 영상 입력 뒤에 붙임(번호 = len(segs) + k)
    lens: list[float] = []
    for i, seg in enumerate(segs):
        src = project.source(seg.src)
        g = project.grade_for_source(src.id, seg=seg)       # 보낼 때 꺼 둔 항목은 빼고
        lcwd, lut = _lut_for(g)
        cwd = cwd or lcwd
        seg_src_sec = float(Fraction(seg.frames) / src.fps)
        out_sec = seg_src_sec / seg.speed
        total += out_sec
        lensf = lens_chain(g, src.width, src.height)
        sp = None if fast else stab_params(g)       # 미리보기 렌더는 흔들림 보정 생략(분석이 느림)
        gs = (gpu_scale and not sp and not lensf and not seg_reframe(src, seg, orientation)
              and _crop_noop(src, orientation) and not may_rotate(src))
        cmd += [*_hw(o.gpu_decode), *(["-hwaccel_output_format", "cuda"] if gs else []),
                "-ss", _seek(seg.fin, src.fps), "-t", f"{seg_src_sec + 0.5:.6f}", "-i", _abs(src.path)]
        v = [f"trim=end_frame={seg.frames}", "setpts=PTS-STARTPTS"]
        if sp:
            ow, oh = out_size(orientation)
            trf = stab_file(src, seg, orientation, sp[0], lensf)
            pre, post, _k = stab_band(src, seg, orientation, lensf)
            v += [*pre, f"vidstabtransform=input={trf.name}:smoothing={sp[1]}:optzoom=1:interpol=bicubic",
                  *([post] if post else []), f"scale={ow}:{oh}:flags=lanczos"]
            cwd = str(trf.parent)
        if seg.speed != 1.0:
            v.append(f"setpts=PTS/{seg.speed}")
        v.append(f"fps={OUT_FPS.numerator}/{OUT_FPS.denominator}")
        if not sp:
            v += lensf
            keys = seg_reframe(src, seg, orientation)
            if keys:      # 움직이는 세로 크롭(배속·fps 뒤라 t = 출력 시간)
                cw, ch = crop_size(src.width, src.height, orientation)
                ow, oh = out_size(orientation)
                xe = reframe_expr(keys, seg.fin, float(src.fps) * seg.speed)
                v += [f"crop={cw}:{ch}:x='clip((iw-{cw})/2+{xe},0,iw-{cw})':y=(ih-{ch})/2",
                      f"scale={ow}:{oh}:flags=lanczos"]
            elif gs:
                ow, oh = out_size(orientation)
                v += [f"scale_cuda={ow}:{oh}:interp_algo=lanczos", "hwdownload", f"format={_dl_fmt(src)}",
                      "format=yuv420p10le" if _dl_fmt(src) == "p010le" else "format=yuv420p"]
            else:
                v += frame_chain(orientation)
        if has_gkeys(seg):          # 색 키프레임: 프레임마다 값 변경(sendcmd, 파일은 LUT 와 같은 작업 폴더)
            n_out = int(round(seg_src_sec / seg.speed * float(OUT_FPS))) + 2
            cmdtxt = gkey_cmds(g, seg, src, n_out, float(src.fps) * seg.speed, tag=str(i))
            cfile = paths.cache_dir() / "lut" / f"gk_{hashlib.sha1(cmdtxt.encode()).hexdigest()[:12]}.txt"
            cfile.parent.mkdir(parents=True, exist_ok=True)
            cfile.write_text(cmdtxt, encoding="utf-8")
            cwd = cwd or str(cfile.parent)
            v.append(f"sendcmd=f={cfile.name}")
            gn = dict(g, _ck=True) if seg.gkeys.get(CURVE_KEY) else g
            v += grade_chain(gn, lut, min(out_size(orientation)) * 16 // 9, named=True, tag=str(i))
        else:
            v += grade_chain(g, lut, min(out_size(orientation)) * 16 // 9)
        lays = seg_layers(project, seg)
        if not lays:
            v += [TO_YUV709, "setsar=1"]
            fparts.append(graph(v, f"[{i}:v:0]", f"[v{i}]", str(i)))
        else:
            # 보정 끝난 화면에 이미지 합성(보정 없음). 10bit 4:4:4 에서 합성 후 4:2:0 으로만 바꿈(행렬 재변환 없음)
            v.append(YUV444_709)
            fparts.append(graph(v, f"[{i}:v:0]", f"[b{i}_0]", str(i)))
            ow, oh = out_size(orientation)
            e = 0.25 / float(OUT_FPS)
            for k, (lay, img, lf, lo) in enumerate(lays):
                ii = len(segs) + len(img_inputs)
                img_inputs.append(_abs(img.path))
                x, y, w, h = layer_box(lay, img, ow, oh)
                pre = ORIENT_FILTER.get(img.orient, [])
                fparts.append(f"[{ii}:v:0]{','.join(pre + [f'scale=w={w}:h={h}:flags=lanczos:{OV_CONVERT}', 'format=yuva444p10le'])}[l{i}_{k}]")
                t0 = float(Fraction(lf - seg.fin) / src.fps / Fraction(seg.speed)) - e
                t1 = float(Fraction(lo - seg.fin) / src.fps / Fraction(seg.speed)) - e
                fparts.append(f"[b{i}_{k}][l{i}_{k}]overlay=x={x}:y={y}:format=yuv444p10:eof_action=repeat"
                              f":enable='between(t,{t0:.6f},{t1:.6f})'[b{i}_{k + 1}]")
            fparts.append(f"[b{i}_{len(lays)}]format=yuv420p,setsar=1[v{i}]")
        lab = f"[v{i}]"
        if audio:
            if src.has_audio:
                a = [f"atrim=duration={seg_src_sec:.6f}", "asetpts=PTS-STARTPTS"]
                if seg.speed != 1.0:
                    a.append(f"atempo={seg.speed}")
                a.append("aresample=48000")
                fparts.append(f"[{i}:a:0]{','.join(a)}[a{i}]")
            else:
                fparts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={out_sec:.6f}[a{i}]")
            lab += f"[a{i}]"
        labels.append(lab)
        lens.append(out_sec)
    for f in img_inputs:
        cmd += ["-noautorotate", "-i", f]      # EXIF 회전은 ORIENT_FILTER 로 직접(ffmpeg 버전마다 자동 적용 여부가 다름)
    n = len(segs)
    plan = plan_transitions(segs, lens)
    if not any(plan):
        if audio:
            fparts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[vo][ao]")
        elif head_trim and n == 1:
            fparts.append(f"{labels[0]}trim=start_frame={head_trim},setpts=PTS-STARTPTS[vo]")
            total = max(0.0, total - head_trim / float(OUT_FPS))
        else:
            fparts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[vo]")
    else:
        total = transition_graph(fparts, plan, lens, audio)
    lead = max(0.0, float((extras or {}).get("lead", 0) or 0))          # v0.16.71 앞뒤 검은 구간
    tail = max(0.0, max([float(t["t1"]) for t in (extras or {}).get("titles", [])] + [0.0]) - (lead + total))
    if lead > 0.005 or tail > 0.005:
        fparts[:] = [f.replace("[vo]", "[vpad]").replace("[ao]", "[apad]") for f in fparts]
        fparts.append(f"[vpad]tpad=start_duration={lead:.4f}:stop_duration={tail:.4f}:start_mode=add:stop_mode=add:color=black[vo]")
        if audio:
            fparts.append(f"[apad]adelay=delays={int(round(lead * 1000))}:all=1,apad=pad_dur={tail:.4f}[ao]")
        total += lead + tail
    if audio:                                     # v0.16.66 원본을 키울 컷(말소리·수면 위)의 결과 영상 구간
        from .music import EDGE_MUSIC, loud_spans
        from .music import LAST_MUSIC
        sp3 = loud_spans(segs, lens, plan if any(plan) else [None] * n, with_index=True)
        spans = [(a + lead, b + lead) for a, b, _i in sp3]
        um = float(((extras or {}).get("mix") or {}).get("up_music", 0.3))
        edge = (1 - EDGE_MUSIC) / (1 - um) if um < EDGE_MUSIC else 1.0          # v0.16.73 첫 컷(키움) = 음악 70%
        last = (1 - LAST_MUSIC) / (1 - um) if um < 1 else 1.0                     # v0.16.75 마지막 컷 = 음악 50%(키움 아니어도)
        dsp, dw = [], []
        for a, b, i in sp3:
            dsp.append((a + lead, b + lead))
            dw.append(min(1.0, last) if i == n - 1 else edge if i == 0 else 1.0)
        if n and (extras or {}).get("music") and not any(i == n - 1 for _a, _b, i in sp3):
            t_, starts = 0.0, []
            for i in range(n):
                if i > 0 and plan[i]:
                    t_ -= plan[i][1]
                starts.append(t_)
                t_ += lens[i]
            dsp.append((starts[-1] + lead, starts[-1] + lens[-1] + lead + 5.0))   # 뒤 검은 구간까지
            dw.append(min(1.0, last))
        if spans or dsp:
            extras = {**(extras or {}), "loud": spans, "duck": dsp, "duck_w": dw}
    dv = (extras or {}).get("dive") or {}
    if dv.get("dives") and not fast:              # v0.16.84 수심 그래프: 0.5초마다 그림(선·점·글자 / 띠 멀티플라이·애드)
        from . import dive_draw
        import uuid
        starts, t_ = [], 0.0
        for i in range(n):
            if i > 0 and plan[i]:
                t_ -= plan[i][1]
            starts.append(t_)
            t_ += lens[i]
        spans = [(starts[i] + lead, starts[i] + lens[i] + lead, segs[i],
                  float(plan[i + 1][1]) if i + 1 < n and plan[i + 1] else 0.0) for i in range(n)]
        ow, oh = out_size(orientation)
        root = paths.cache_dir() / "dive"
        _clean_old(root)
        lay = dive_draw.render_layers(project, dv["dives"], float(dv.get("off", 0.0)), spans, total, ow, oh,
                                      root / uuid.uuid4().hex[:10], dv.get("cancel"))
        if lay:
            extras = {**extras, "dive_layers": lay}
            log_info(f"수심 그래프: {lay['txt']}")
    if extras and (extras.get("titles") or extras.get("music") or extras.get("loud") or extras.get("duck")
                   or extras.get("dive_layers")):
        fparts[:] = [f.replace("[vo]", "[vm]").replace("[ao]", "[am]") for f in fparts]
        post_graph(fparts, cmd, project, extras, total, orientation, audio, len(segs) + len(img_inputs))
        cwd = cwd or str(paths.cache_dir() / "lut")
    enc = eff_encoder(o.encoder)     # 설정한 인코더를 이 PC 에서 되는 것으로(v0.16.48)
    ten = is_10bit(enc) and not fast and not TEST_LOSSLESS
    if ten:                          # 10bit 출력(v0.16.41): 컷 끝·합성·전환 뒤 형식을 10bit 로(보정은 원래 16bit 계산)
        fparts[:] = [f.replace("format=yuv420p,", "format=yuv420p10le,").replace("format=yuv420p[", "format=yuv420p10le[")
                     .replace(":format=yuv420:", ":format=yuv420p10:") for f in fparts]
    cmd += [*filter_complex_args(";".join(fparts)), "-map", "[vo]"]
    if audio:
        cmd += ["-map", "[ao]", "-c:a", "aac", "-b:a", "192k"]
    rf = res_factor(orientation)
    br = int(o.bitrate_mbps * rf)    # 설정값 = 1080p 기준
    rate = ["-maxrate", f"{int(br * 1.5)}M", "-bufsize", f"{br * 2}M"]
    pix = "yuv420p"
    q = getattr(o, "quality", "high") or "high"
    if q not in QUALITY:
        q = "high"
    if TEST_LOSSLESS:                # 시험 전용: 무손실(조각 ↔ 통째 화면 비교)
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-qp", "0"]
    elif fast:                       # 미리보기 렌더: 작고 빠르게
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26"]
    elif q != "high":                # v0.16.80 보통·작게: GPU = H.265(안 되면 H.264), CPU = H.264(노트북에서도 빠르게)
        qv = QUALITY[q]
        tb, mb = max(1, round(qv["mbps"] * rf)), max(2, round(qv["max"] * rf))
        crate = ["-b:v", f"{tb}M", "-maxrate", f"{mb}M", "-bufsize", f"{mb * 2}M"]
        if enc in ("nvenc", "nvenc_hevc10") and hevc_nvenc_ok():
            if enc == "nvenc_hevc10":
                pix = "p010le"
            cmd += ["-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", str(qv["cq"] + 2), *crate,
                    "-profile:v", "main10" if pix == "p010le" else "main", "-tag:v", "hvc1", *nvenc_aq("hevc_nvenc")]
        elif enc in ("nvenc", "nvenc_hevc10"):
            cmd += ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", str(qv["cq"]), *crate,
                    "-profile:v", "high", *nvenc_aq("h264_nvenc")]
        elif enc == "qsv":
            pix = "nv12"
            cmd += ["-c:v", "h264_qsv", "-preset", "medium", *crate, "-profile:v", "high"]
        elif enc == "x265_10":
            pix = "yuv420p10le"
            cmd += ["-c:v", "libx265", "-preset", "medium", "-crf", str(qv["crf"] + 3), "-maxrate", f"{mb}M", "-bufsize", f"{mb * 2}M",
                    "-tag:v", "hvc1", "-x265-params", "log-level=error"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "faster" if low_spec() else "medium", "-crf", str(qv["crf"]),
                    "-maxrate", f"{mb}M", "-bufsize", f"{mb * 2}M"]
    elif enc == "qsv":               # 인텔 내장 그래픽(Quick Sync, v0.16.48) — 이 환경에서 못 돌려 봄(노트북 로그로 확인)
        pix = "nv12"
        cmd += ["-c:v", "h264_qsv", *qsv_args(br), "-profile:v", "high"]
    elif enc == "nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19",
                "-b:v", f"{br}M", *rate, "-profile:v", "high", *nvenc_aq("h264_nvenc")]
    elif enc == "nvenc_hevc10":
        pix = "p010le"
        cmd += ["-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "21",
                "-b:v", f"{br}M", *rate, "-profile:v", "main10", "-tag:v", "hvc1", *nvenc_aq("hevc_nvenc")]
    elif enc == "x265_10":
        pix = "yuv420p10le"
        cmd += ["-c:v", "libx265", "-preset", "medium", "-crf", "20", *rate, "-tag:v", "hvc1",
                "-x265-params", "log-level=error"]
    else:                            # 저사양(v0.16.48) = faster(사용자 PC 는 medium 그대로)
        cmd += ["-c:v", "libx264", "-preset", "faster" if low_spec() else "medium", "-crf", "18", *rate]
    cmd += ["-pix_fmt", pix, "-r", f"{OUT_FPS.numerator}/{OUT_FPS.denominator}",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
            "-map_metadata", "-1", "-write_tmcd", "0", "-movflags", "+faststart", _abs(out_file)]
    # 모든 LUT 는 같은 캐시 폴더에 있으므로 cwd 하나로 충분
    _ctx.last_cmd = cmd
    return cmd, total, cwd


# ------------------------------------------------------------------ 용량(v0.16.80): [렌더] 누를 때 고름
# mbps = 1080 기준 평균 목표(예상 크기 계산에도 씀), max = 상한. 고화질 = 예전 설정 그대로(평균은 실측 아님, 대략).
QUALITY = {"high": {"label": "고화질", "mbps": 20, "max": 60, "cq": 19, "crf": 18},
           "normal": {"label": "보통", "mbps": 8, "max": 12, "cq": 24, "crf": 22},
           "small": {"label": "작게", "mbps": 4, "max": 6, "cq": 28, "crf": 26}}


def res_factor(orientation: str) -> float:
    return {"horizontal1440": 1.5, "horizontal2160": 2.5, "vertical1440": 1.5, "vertical2160": 2.5}.get(orientation, 1.0)


def est_mb(quality: str, secs: float, orientation: str = "horizontal", audio: bool = True) -> float:
    """예상 크기(MB) = 평균 목표 × 길이(+ 소리 192k). 화면이 자잘하면 더 큼."""
    q = QUALITY.get(quality, QUALITY["normal"])
    mbps = q["mbps"] * res_factor(orientation) + (0.192 if audio else 0)
    return mbps * secs / 8


_hevc_ok: list = []


def hevc_nvenc_ok() -> bool:
    """이 GPU 가 H.265 를 만들 수 있나(오래된 GPU 는 H.264 만). 실행마다 1번."""
    if not _hevc_ok:
        ok, msg = _enc_probe("hevc_nvenc", ["-preset", "p6"], "yuv420p")
        _hevc_ok.append(ok)
        log_info(f"H.265 GPU: {'됨' if ok else '안 됨 → H.264'}{'' if ok else ' · ' + msg}")
    return _hevc_ok[0]


# ------------------------------------------------------------------ 인코더(v0.16.41)
ENCODERS = [("nvenc", "NVENC (GPU)"), ("x264", "x264 (CPU)"), ("nvenc_hevc10", "NVENC HEVC 10bit (GPU)"), ("x265_10", "x265 10bit (CPU)"),
            ("qsv", "Quick Sync (인텔 GPU)")]

# ---- 이 PC 의 그래픽 판별(v0.16.48, 사용자: 사무용 노트북 i5-1335U · Iris Xe · 16GB 에서도 돌게)
# 실행마다 1번, 아주 짧게 인코딩해 봄: NVENC → Quick Sync → 없음. 결과는 cache/dtme.log.
#   nvenc = 지금까지와 같음 / qsv = 인코딩만 인텔 GPU(디코딩은 CPU — 다음 단계) / none = 전부 CPU
# 설정의 인코더는 '바라는 것': GPU 인코더를 골랐는데 그 GPU 가 없으면 되는 쪽으로 바꿔 씀(x264 를 직접 고른 것은 그대로).
_hw_lock = threading.Lock()
_hw_kind: list = [None]
_qsv_mode: list = ["icq"]
QSV_MODES = {"icq": ["-preset", "medium", "-global_quality", "21"],                       # 품질 기준(cq 와 비슷)
             "vbr": ["-preset", "medium"]}                                              # 안 되면 비트레이트 기준


def qsv_args(br: int) -> list[str]:
    if _qsv_mode[0] == "vbr":
        return [*QSV_MODES["vbr"], "-b:v", f"{br}M", "-maxrate", f"{int(br * 1.5)}M", "-bufsize", f"{br * 2}M"]
    return list(QSV_MODES["icq"])


def _enc_probe(codec: str, extra: list[str], pix: str) -> tuple[bool, str]:
    try:
        p = _popen([paths.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=0.5", "-frames:v", "8",
                    "-c:v", codec, *extra, "-pix_fmt", pix, "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _out, err = p.communicate(timeout=30)
        return p.returncode == 0, err.decode("utf-8", "replace")[-160:].strip().replace("\n", " / ")
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001
        return False, str(e)[-160:]


def hw_kind() -> str:
    """'nvenc' | 'qsv' | 'none'. 환경 변수 DTME_HW 로 강제(시험)."""
    if _hw_kind[0] is not None:
        return _hw_kind[0]
    with _hw_lock:
        if _hw_kind[0] is not None:
            return _hw_kind[0]
        forced = os.environ.get("DTME_HW", "")
        if forced in ("nvenc", "qsv", "none"):
            _hw_kind[0] = forced
            return forced
        ok, m1 = _enc_probe("h264_nvenc", ["-preset", "p6"], "yuv420p")
        kind, m2 = ("nvenc" if ok else "none"), ""
        if not ok:
            for mode in ("icq", "vbr"):
                extra = QSV_MODES[mode] + (["-b:v", "8M", "-maxrate", "12M", "-bufsize", "16M"] if mode == "vbr" else [])
                ok2, m2 = _enc_probe("h264_qsv", extra, "nv12")
                if ok2:
                    kind, _qsv_mode[0] = "qsv", mode
                    break
        _hw_kind[0] = kind
        try:
            ram = __import__("dtme.framecache", fromlist=["total_ram"]).total_ram() / (1 << 30)
        except Exception:  # noqa: BLE001
            ram = 0.0
        note = {"nvenc": "NVIDIA(NVENC) — 인코딩·디코딩 GPU",
                "qsv": f"인텔 Quick Sync({_qsv_mode[0]}) — 인코딩 GPU · 디코딩 CPU",
                "none": "GPU 인코더 없음 — 전부 CPU(x264)"}[kind]
        log_info(f"그래픽 확인: {note} · 코어 {os.cpu_count()} · 메모리 {ram:.0f}GB · 저사양 {'예' if low_spec() else '아니오'}"
                 + (f" · NVENC 안 됨({m1})" if kind != "nvenc" else "") + (f" · QSV 안 됨({m2})" if kind == "none" else ""))
        return kind


def has_cuda() -> bool:
    return hw_kind() == "nvenc"


def hw_downgrade(to: str, why: str) -> None:
    """렌더 중 GPU 인코더가 실패 → 이 실행 동안 한 단계 내림(qsv → none)."""
    with _hw_lock:
        if _hw_kind[0] != to:
            log_info(f"그래픽 전환: {_hw_kind[0]} → {to} ({why[-200:]})")
            _hw_kind[0] = to


def eff_encoder(enc: str) -> str:
    """설정 인코더 → 이 PC 에서 실제로 쓸 인코더."""
    k = hw_kind()
    if enc in ("nvenc", "qsv"):
        return {"nvenc": "nvenc", "qsv": "qsv"}.get(k, "x264")
    if enc == "nvenc_hevc10":
        return "nvenc_hevc10" if k == "nvenc" else "x265_10"
    return enc


def low_spec() -> bool:
    """저사양: NVIDIA 없음 + (논리 코어 12 이하 또는 메모리 17GB 이하). 설정 low_spec = 1 강제 켬 · 2 강제 끔(0·없음 = 자동).
    바뀌는 것 = 미리보기 동시 2 · 프록시 1 · 조각 렌더 안 함 · x264 faster."""
    v = _setting_int("low_spec", 0)
    if v in (1, 2):
        return v == 1
    if _hw_kind[0] in (None, "nvenc"):
        return False
    try:
        from .framecache import total_ram
        ram = total_ram() / (1 << 30)
    except Exception:  # noqa: BLE001
        ram = 64.0
    return (os.cpu_count() or 8) <= 12 or ram <= 17
AQ_ARGS = ["-spatial-aq", "1", "-temporal-aq", "1", "-aq-strength", "8", "-rc-lookahead", "20"]
_aq_lock = threading.Lock()
_aq_known: dict = {}                  # 인코더 이름 → True/False(이번 실행 동안). 판단 못 함(GPU 가 바쁨·없음)은 60초 뒤 다시
_aq_retry: dict = {}


def is_10bit(encoder: str) -> bool:
    return encoder in ("nvenc_hevc10", "x265_10")


def is_hevc(encoder: str) -> bool:
    return is_10bit(encoder)


def nvenc_aq(codec: str) -> list[str]:
    """AQ(완만한 물빛에 비트를 더 줌 = 계단 줄임) — 이 PC 의 GPU·드라이버·ffmpeg 가 받는지 아주 짧게 인코딩해 보고
    되면 자동으로 켬, 안 되면 끔(사용자 '확인 후 자동'). 실행마다 인코더별 1번, 결과는 cache/dtme.log.
    AQ 없이도 안 되면(GPU 없음·자리 없음) 판단을 미룸(끔으로 돌려주고 60초 뒤 다시 확인)."""
    if os.environ.get("DTME_NO_AQ"):
        return []
    with _aq_lock:
        if codec in _aq_known:
            return list(AQ_ARGS) if _aq_known[codec] else []
        if _time.monotonic() < _aq_retry.get(codec, 0.0):
            return []
        base = [paths.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=0.5", "-frames:v", "8",
                "-c:v", codec, "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "8M"]
        end = ["-pix_fmt", "p010le" if codec == "hevc_nvenc" else "yuv420p", "-f", "null", "-"]

        def ok(extra):
            try:
                p = _popen(base + extra + end, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                _out, err = p.communicate(timeout=30)
                return p.returncode == 0, err.decode("utf-8", "replace")[-200:].strip()
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                return False, str(e)
        good, msg = ok(AQ_ARGS)
        if good:
            _aq_known[codec] = True
            log_info(f"AQ 확인 {codec}: 됨 → 켬")
            return list(AQ_ARGS)
        plain, msg2 = ok([])
        if plain:
            _aq_known[codec] = False
            log_info(f"AQ 확인 {codec}: 안 됨 → 끔 ({msg})")
        else:
            _aq_retry[codec] = _time.monotonic() + 60
            log_info(f"AQ 확인 {codec}: 인코더 자체가 안 열림 → 이번엔 끔, 나중에 다시 ({msg2})")
        return []


# ------------------------------------------------------------------ 조각 렌더(v0.16.26)
# 렌더 1개의 필터(노이즈·LUT·색·물 노이즈)는 대부분 코어를 늘려도 안 빨라짐(측정: 2스레드 1.0~1.1배) → 64코어에서 출력 ≈21장/초.
# 컷 1개짜리 항목은 구간을 조각내 동시에(조각마다 ffmpeg) 렌더하고 다시 인코딩 없이 이어 붙임. 소리는 따로 한 번.
# 조각 경계: 앞 PREROLL_OUT 장을 더 렌더해 버림(시간축 노이즈 제거 예열). ◆·리프레임·레이어는 컷 시작 기준이라 조각 시작만 바꾸면 맞음.
# 안 하는 경우: 흔들림 보정 · 여러 컷/전환 · 글자·음악 · 조각 2개가 안 되는 길이 · 배속×fps 가 정수배가 아닌 원본.
TEST_LOSSLESS = False
CHUNK_MIN_SEC = 10.0
CHUNK_MAX = 8
PREROLL_OUT = 15            # 출력 프레임(29.97fps 0.5초)


def chunk_plan(project: Project, segs: list, orientation: str, extras: dict | None, fast: bool = False) -> list | None:
    """[(조각 Segment, 버릴 앞 출력 프레임 수, 출력 프레임 수)] 또는 None(통째로)."""
    import dataclasses
    import math
    if fast or len(segs) != 1 or (extras and (extras.get("titles") or extras.get("music") or extras.get("lead")
                                              or extras.get("dive"))):
        return None
    from .music import seg_up
    if seg_up(segs[0]):               # v0.16.66 원본 키움 경사가 조각 경계마다 생기지 않게 = 통째로
        return None
    if low_spec():                    # 코어가 적으면 나눠도 이득 없음(v0.16.48)
        return None
    seg = segs[0]
    src = project.source(seg.src)
    if src is None or not src.frames:
        return None
    g = project.grade_for_source(src.id, seg=seg)
    if stab_params(g):
        return None
    r = Fraction(src.fps) * Fraction(seg.speed).limit_denominator(1000) / OUT_FPS      # 원본 프레임 / 출력 프레임
    if r.denominator == 1:
        unit, out_per_unit = r.numerator, 1
    elif r.numerator == 1:
        unit, out_per_unit = 1, r.denominator
    else:
        return None
    total_out = seg.frames * out_per_unit // unit
    sec = total_out / float(OUT_FPS)
    n = min(_setting_int("chunk_max", CHUNK_MAX), int(sec // CHUNK_MIN_SEC))
    if n < 2:
        return None
    L = math.ceil(seg.frames / n / unit) * unit                  # 조각 길이(원본 프레임, unit 배수 = 출력 경계 일치)
    pre_src = math.ceil(PREROLL_OUT / out_per_unit) * unit
    plan = []
    k = 0
    while seg.fin + k * L < seg.fout:
        a, b = seg.fin + k * L, min(seg.fout, seg.fin + (k + 1) * L)
        a0 = max(seg.fin, a - pre_src) if k else a
        sub = dataclasses.replace(seg, fin=a0, fout=b)
        plan.append((sub, (a - a0) * out_per_unit // unit, (b - a) * out_per_unit // unit))
        k += 1
    return plan


def _audio_cmd(project: Project, seg: Segment, out_file: str) -> list[str]:
    """통째 렌더와 같은 소리(같은 입력 시크 · atrim · atempo · 48k)."""
    src = project.source(seg.src)
    seg_src_sec = float(Fraction(seg.frames) / src.fps)
    out_sec = seg_src_sec / seg.speed
    if src.has_audio:
        a = [f"atrim=duration={seg_src_sec:.6f}", "asetpts=PTS-STARTPTS"]
        if seg.speed != 1.0:
            a.append(f"atempo={seg.speed}")
        a.append("aresample=48000")
        inp = ["-ss", _seek(seg.fin, src.fps), "-t", f"{seg_src_sec + 0.5:.6f}", "-i", _abs(src.path)]
        fg = f"[0:a:0]{','.join(a)}[ao]"
    else:
        inp = []
        fg = f"anullsrc=r=48000:cl=stereo,atrim=duration={out_sec:.6f}[ao]"
    return [paths.ffmpeg(), "-y", *inp, "-filter_complex", fg, "-map", "[ao]", "-c:a", "aac", "-b:a", "192k", _abs(out_file)]


def _render_chunked(project: Project, segs: list, plan: list, out_file: str, on_progress, cancel,
                    orientation: str, audio: bool | None) -> None:
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    t0, w0 = _time.monotonic(), waited()
    prio = getattr(_ctx, "prio", 2)
    audio = project.output.audio if audio is None else audio
    out = Path(out_file)
    parts = out.parent / f".{out.stem}.parts"
    shutil.rmtree(parts, ignore_errors=True)
    parts.mkdir(parents=True, exist_ok=True)
    n = len(plan)
    prog = [0.0] * (n + 1)
    weights = [max(1, k[2]) for k in plan]
    wsum = float(sum(weights))
    plock = threading.Lock()
    running = [0]
    fails = []

    class _Stop:
        """밖의 취소 또는 조각 하나 실패 = 모든 조각 멈춤."""
        def __init__(self):
            self.ev = threading.Event()

        def is_set(self):
            return self.ev.is_set() or (cancel is not None and cancel.is_set())

        def set(self):
            self.ev.set()
    stop = _Stop()

    def report():
        if on_progress:
            v = sum(prog[i] * weights[i] for i in range(n)) / wsum
            on_progress(min(0.99, 0.97 * v + 0.03 * prog[n]))

    import os as _os
    thr = _setting_int("chunk_threads", 0) or max(2, (_os.cpu_count() or 8) // max(1, min(n * 2, gpu_cap())))
    gscale = [None]                                   # GPU 축소 실패하면 False 로(이 렌더 동안)
    nohw = [False]                                    # GPU 디코딩도 실패하면 True(CPU 디코딩)

    def one(i):
        set_prio(prio)
        sub, drop, _nout = plan[i]
        f = parts / f"p{i:02d}.mp4"
        tries = 0
        while True:
            cmd, total, cwd = build_render_cmd(project, [sub], str(f), orientation, False, False, None, head_trim=drop,
                                               gpu_scale=False if nohw[0] else gscale[0])     # GPU 디코딩 끔 = GPU 축소도 끔
            if nohw[0]:
                cmd = [c for c in cmd if c not in ("-hwaccel", "cuda")]
            cmd[1:1] = ["-filter_complex_threads", str(thr), "-threads", str(thr)]   # v0.16.28 A: 조각마다 코어 나눔
            try:
                with plock:
                    running[0] += 1
                try:
                    run_progress(cmd, total, lambda v: (prog.__setitem__(i, v), report()), stop, cwd=cwd)
                finally:
                    with plock:
                        running[0] -= 1
                return str(f)
            except FFError as e:
                tries += 1
                if stop.is_set():
                    raise
                if nvenc_limited(str(e)) and tries <= 4:
                    with plock:
                        r = running[0] + 1
                    lower_gpu_cap(r)
                    _time.sleep(0.5)
                    continue
                # 실패한 명령에 든 것 기준(조각 여러 개가 동시에 실패해도 각자 다음 단계로): GPU 축소 → GPU 디코딩 → 포기
                if tries <= 8 and "scale_cuda" in " ".join(map(str, cmd)):
                    if gscale[0] is not False:
                        gscale[0] = False
                        log_error("GPU 축소 실패 → CPU 축소", str(e)[-300:])
                    continue
                if tries <= 8 and "-hwaccel" in cmd:              # GPU 디코딩 실패 → CPU 디코딩(이 렌더 동안)
                    nohw[0] = True
                    continue
                raise

    try:
        with ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(one, i) for i in range(n)]
            files = []
            for fu in futs:
                try:
                    files.append(fu.result())
                except Exception as e:  # noqa: BLE001
                    fails.append(e)
                    stop.set()                               # 나머지 조각도 멈춤
            if fails:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                raise next((e for e in fails if not isinstance(e, Cancelled)), fails[0])
        lst = parts / "list.txt"
        lst.write_text("".join(f"file '{Path(x).name}'\n" for x in files), encoding="utf-8")
        cmd = [paths.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name]
        maps = ["-map", "0:v:0"]
        if audio:
            run(_audio_cmd(project, segs[0], str(parts / "a.m4a")))
            cmd += ["-i", "a.m4a"]
            maps += ["-map", "1:a:0"]
        if is_hevc(eff_encoder(project.output.encoder)):
            maps += ["-tag:v", "hvc1"]
        cmd += [*maps, "-c", "copy", "-map_metadata", "-1", "-write_tmcd", "0", "-movflags", "+faststart", _abs(out_file)]
        run(cmd, cwd=str(parts))
        prog[n] = 1.0
        report()
    finally:
        shutil.rmtree(parts, ignore_errors=True)
    src = project.source(segs[0].src)
    dur = float(Fraction(segs[0].frames) / src.fps / Fraction(segs[0].speed).limit_denominator(1000))
    log_info(f"조각 렌더 {Path(out_file).name}: {n}조각 {_time.monotonic() - t0:.1f}초 (영상 {dur:.0f}초, "
             f"GPU 동시 한계 {gpu_cap()}, 조각 스레드 {thr}, GPU 축소 {'끔' if gscale[0] is False else '켬'}, "
             f"자리 대기 {waited() - w0:.1f}초)")


def render_video(project: Project, segs: list[Segment], out_file: str, on_progress=None, cancel=None,
                 orientation: str | None = None, audio: bool | None = None, fast: bool = False,
                 extras: dict | None = None) -> None:
    """렌더 + 결과 크기 확인(v0.16.70 진단: 사용자 PC 에서 세로 타임라인이 가로로 나온 일 — 다르면 명령을 기록)."""
    _render_video(project, segs, out_file, on_progress, cancel, orientation, audio, fast, extras)
    want = out_size(orientation or project.output.orientation)
    try:
        pr = probe(str(out_file))
        got = (int(pr.get("width", 0)), int(pr.get("height", 0)))
    except Exception as e:  # noqa: BLE001
        log_error("렌더 크기 확인", str(e)[-200:])
        return
    if got != want:
        log_error("렌더 크기 다름", f"{Path(out_file).name}: 요청 {orientation} {want} → 결과 {got} · 명령 "
                  + " ".join(map(str, getattr(_ctx, "last_cmd", []) or []))[-4000:])
    else:
        log_info(f"렌더 크기 {Path(out_file).name}: {got[0]}×{got[1]} ({orientation})")


def _render_video(project: Project, segs: list[Segment], out_file: str, on_progress=None, cancel=None,
                  orientation: str | None = None, audio: bool | None = None, fast: bool = False,
                  extras: dict | None = None) -> None:
    orient = orientation or project.output.orientation
    plan = chunk_plan(project, segs, orient, extras, fast)
    if plan:
        _render_chunked(project, segs, plan, out_file, on_progress, cancel, orientation, audio)
        return
    gpu = project.output.gpu_decode
    # 1패스: 흔들림 분석(필요한 컷만, 결과 캐시). 진행률 앞 40%
    todo = []
    for seg in segs:
        src = project.source(seg.src)
        gg = project.grade_for_source(src.id, seg=seg)
        sp = stab_params(gg)
        if sp and not fast and not stab_file(src, seg, orient, sp[0], lens_chain(gg, src.width, src.height)).exists():
            todo.append((src, seg, sp[0], lens_chain(gg, src.width, src.height)))
    share = 0.4 if todo else 0.0
    for k, (src, seg, shk, lens) in enumerate(todo):
        def sub(v, k=k):
            if on_progress:
                on_progress(share * (k + v) / len(todo))
        stab_detect(src, seg, orient, shk, gpu, sub, cancel, lens)
    outer = on_progress
    on_progress = (lambda v: outer(share + (1 - share) * v)) if outer else None
    cmd, total, cwd = build_render_cmd(project, segs, out_file, orientation, audio, fast, extras)
    try:
        run_progress(cmd, total, on_progress, cancel, cwd=cwd)
    except FFError as e:
        if cancel is not None and cancel.is_set():
            raise
        if "h264_qsv" in cmd:                                  # Quick Sync 실패 → 이 실행 동안 x264 로(v0.16.48)
            log_error("Quick Sync 렌더 실패 → x264", str(e)[-400:])
            hw_downgrade("none", str(e))
            cmd, total, cwd = build_render_cmd(project, segs, out_file, orientation, audio, fast, extras)
            run_progress(cmd, total, on_progress, cancel, cwd=cwd)
            return
        if not project.output.gpu_decode or not has_cuda():
            raise
        if "scale_cuda" in " ".join(map(str, cmd)):            # GPU 축소 실패 → CPU 축소(GPU 디코딩은 유지)
            log_error("GPU 축소 실패 → CPU 축소", str(e)[-300:])
            cmd, total, cwd = build_render_cmd(project, segs, out_file, orientation, audio, fast, extras, gpu_scale=False)
            try:
                run_progress(cmd, total, on_progress, cancel, cwd=cwd)
                return
            except FFError:
                if cancel is not None and cancel.is_set():
                    raise
        cmd = [c for c in cmd if c not in ("-hwaccel", "cuda")]
        run_progress(cmd, total, on_progress, cancel, cwd=cwd)


# ------------------------------------------------------------------ 스틸 (4K 원본)
# 스틸 파일 색 태그 = sRGB. 그대로 두면 BT.709 전달 특성(cICP·gAMA 1/1.96)이 기록되어
# Windows 사진 앱 등 색 관리 뷰어가 더 어둡고 진하게 표시한다(픽셀 값은 프리뷰와 같음, 실측 평균 차 1.4/255).
SRGB_TAG = "setparams=color_trc=iec61966-2-1:color_primaries=bt709:colorspace=gbr"


def export_still(src: Source, frame: int, g: dict, out_file: str, gpu: bool = False) -> None:
    """원본 4K 프레임에 보정 적용 → PNG(기본 8bit, 설정 still_bits=16 이면 16bit) 또는 16bit TIFF(.tif).
    앞 3프레임을 함께 넣어 시간축 노이즈 제거가 동작하게 하고 마지막 프레임만 저장."""
    cwd, lut = _lut_for(g)
    lead = min(3, frame)
    start = frame - lead
    is_png = str(out_file).lower().endswith(".png")
    from .project import get_setting
    bits = 16 if str(get_setting("still_bits", 8)) == "16" else 8     # v0.16.2: 기본 8bit(16bit PNG 는 뷰어에 따라 띠가 보임)
    pf = ("rgb48be" if bits == 16 else "rgb24") if is_png else "rgb48le"
    vf = last_only(lens_chain(g, src.width, src.height) + grade_chain(g, lut, 3840), lead) + [SRGB_TAG, f"format={pf}"]
    codec = ["-c:v", "png", "-compression_level", "3"] if is_png else ["-c:v", "tiff", "-compression_algo", "deflate"]
    cmd = [paths.ffmpeg(), "-v", "error", "-y", "-ss", _seek(start, src.fps), "-i", _abs(src.path),
           "-frames:v", str(lead + 1), "-an", "-filter_complex", graph(vf, "[0:v]", "[so]"), "-map", "[so]",
           "-update", "1", *codec, _abs(out_file)]
    try:
        run(cmd, cwd=cwd)
    except FFError:
        if not gpu:
            raise
        run([c for c in cmd if c not in ("-hwaccel", "cuda")], cwd=cwd)


def render_still(project: Project, still: Marker, out_file: str, gpu: bool = False) -> None:
    export_still(project.source(still.src), still.frame, project.grade_for_still(still), out_file, gpu)


# ------------------------------------------------------------------ 프록시 프레임 (드래그·이동 시 즉시 표시)
def grab_proxy_frame(proxy: str, fps: Fraction, frame: int) -> bytes:
    """전 프레임 키프레임 프록시라 한 장 디코딩이 빠름(수십 ms)."""
    return run([paths.ffmpeg(), "-v", "error", "-ss", _seek(frame, fps), "-i", _abs(proxy), "-frames:v", "1",
                "-an", "-f", "image2pipe", "-c:v", "bmp", "-pix_fmt", "bgr24", "-"])


# ------------------------------------------------------------------ 반반 샘플 파일 (왼쪽 보정 전 = LUT만 · 오른쪽 보정)
def split_vf(g: dict, lut: str | None, orientation: str, size: int, fmt: str, src_wh=(0, 0), layout: str = "lr") -> str:
    """filter_complex: 보정 전(LUT만)과 보정 후를 같은 크기로 → 한 장.
    layout: lr = 왼쪽 반 전 · 오른쪽 반 후 / tb = 위 반 전 · 아래 반 후 /
            side = 나란히(전체 화면 2장: 가로 영상은 위(전)·아래(후), 세로 영상은 왼쪽(전)·오른쪽(후)). 경계에 흰 선 2px."""
    vert = is_vertical(orientation)
    sc = f"scale=-2:{size}:flags=lanczos" if vert else f"scale={size}:-2:flags=lanczos"
    lens = lens_chain(g, *src_wh)
    pre = ",".join(lens + [crop_filter(orientation), sc])
    gr = graph(grade_chain(g, lut, size * 9 // 16 if vert else size) + ["format=gbrp16le"], "[sb]", "[sr0]", "s")
    out = {"png16": SRGB_TAG + ",format=rgb48be", "jpg": "format=yuvj444p"}.get(fmt, SRGB_TAG + ",format=rgb24")
    left = f"format=gbrp16le,lut3d=file={lut}:interp=tetrahedral" if lut else "format=gbrp16le"     # 보정 전 = LUT만
    head = f"[0:v]{pre},split=2[sa][sb];[sa]{left}[sl0];{gr};"
    line = "color=white@0.9:t=fill"
    if layout == "tb":
        return (head + "[sl0]crop=iw:trunc(ih/4)*2:0:0[sl];[sr0]crop=iw:ih-trunc(ih/4)*2:0:trunc(ih/4)*2[sr];"
                f"[sl][sr]vstack=2,drawbox=x=0:y=trunc(ih/4)*2-1:w=iw:h=2:{line},{out}[so]")
    if layout == "side":
        if vert:
            return head + f"[sl0][sr0]hstack=2,drawbox=x=iw/2-1:y=0:w=2:h=ih:{line},{out}[so]"
        return head + f"[sl0][sr0]vstack=2,drawbox=x=0:y=ih/2-1:w=iw:h=2:{line},{out}[so]"
    return (head + "[sl0]crop=trunc(iw/4)*2:ih:0:0[sl];[sr0]crop=iw-trunc(iw/4)*2:ih:trunc(iw/4)*2:0[sr];"
            f"[sl][sr]hstack=2,drawbox=x=trunc(iw/4)*2-1:y=0:w=2:h=ih:{line},{out}[so]")


def export_split(src: Source, frame: int, g: dict, out_file: str, size: int = 1920, fmt: str = "png8",
                 orientation: str = "horizontal", gpu: bool = False, layout: str = "lr") -> None:
    """반반 샘플 1장 저장(png8 · png16 · jpg). 앞 3프레임을 넣어 시간축 노이즈 제거가 동작."""
    cwd, lut = _lut_for(g)
    lead = min(3, frame)
    codec = (["-c:v", "mjpeg", "-q:v", "2"] if fmt == "jpg" else ["-c:v", "png", "-compression_level", "3"])
    cmd = [paths.ffmpeg(), "-v", "error", "-y", "-ss", _seek(frame - lead, src.fps), "-i", _abs(src.path),
           "-frames:v", str(lead + 1), "-an", "-filter_complex", split_vf(g, lut, orientation, size, fmt, (src.width, src.height), layout), "-map", "[so]",
           "-update", "1", *codec, _abs(out_file)]
    try:
        run(cmd, cwd=cwd)
    except FFError:
        if not gpu:
            raise
        run([c for c in cmd if c not in ("-hwaccel", "cuda")], cwd=cwd)
