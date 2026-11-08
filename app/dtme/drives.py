"""원본이 있는 저장장치 종류 → 동시 분석·렌더 수(v0.16.19).

종류: "ssd"(탐색 빠름) | "hdd"(회전 디스크) | "removable"(SD카드·USB 메모리) | "unknown".
Windows = GetDriveTypeW(이동식) + IOCTL_STORAGE_QUERY_PROPERTY(StorageDeviceSeekPenaltyProperty: 탐색 지연 있음 = HDD).
Linux = /sys/block/*/queue/rotational, removable(작업 환경 시험용). 판단 못 하면 unknown.
한계: USB 연결 장치는 다리 칩에 따라 탐색 지연 값을 못 읽음 → unknown(= 예전 기본값).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _drive_root(path: str) -> str:
    p = Path(path).resolve()
    if os.name == "nt":
        return (p.drive or str(p)[:2]).upper()          # "D:" (네트워크 경로 \\server\share 도 drive 로 옴)
    return str(p)


@lru_cache(maxsize=64)
def _kind_nt(drive: str) -> str:
    import ctypes
    from ctypes import wintypes
    if drive.startswith("\\\\"):
        return "unknown"                               # 네트워크
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    t = k32.GetDriveTypeW(ctypes.c_wchar_p(drive + "\\"))
    if t == 2:                                         # DRIVE_REMOVABLE (SD 리더기 대부분)
        return "removable"
    if t != 3:                                         # 3 = DRIVE_FIXED. 그 밖(네트워크·CD·RAM) = 모름
        return "unknown"
    CreateFileW = k32.CreateFileW
    CreateFileW.restype = wintypes.HANDLE
    CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = CreateFileW("\\\\.\\" + drive, 0, 3, None, 3, 0, None)      # 권한 없이 열기(관리자 불필요)
    if h in (None, wintypes.HANDLE(-1).value):
        return "unknown"
    try:
        class Query(ctypes.Structure):
            _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int), ("Extra", ctypes.c_ubyte * 1)]

        class Seek(ctypes.Structure):
            _fields_ = [("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("IncursSeekPenalty", ctypes.c_ubyte)]

        class Desc(ctypes.Structure):
            _fields_ = [("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("DeviceType", ctypes.c_ubyte),
                        ("DeviceTypeModifier", ctypes.c_ubyte), ("RemovableMedia", ctypes.c_ubyte),
                        ("CommandQueueing", ctypes.c_ubyte), ("VendorIdOffset", wintypes.DWORD),
                        ("ProductIdOffset", wintypes.DWORD), ("ProductRevisionOffset", wintypes.DWORD),
                        ("SerialNumberOffset", wintypes.DWORD), ("BusType", ctypes.c_int),
                        ("RawPropertiesLength", wintypes.DWORD), ("Raw", ctypes.c_ubyte * 1)]
        IOCTL = 0x2D1400
        ret = wintypes.DWORD()
        d = Desc()
        if k32.DeviceIoControl(h, IOCTL, ctypes.byref(Query(0, 0)), ctypes.sizeof(Query), ctypes.byref(d),
                               ctypes.sizeof(d), ctypes.byref(ret), None):
            if d.BusType in (12, 13):                  # BusTypeSd · BusTypeMmc
                return "removable"
        s = Seek()
        if k32.DeviceIoControl(h, IOCTL, ctypes.byref(Query(7, 0)), ctypes.sizeof(Query), ctypes.byref(s),
                               ctypes.sizeof(s), ctypes.byref(ret), None):
            return "hdd" if s.IncursSeekPenalty else "ssd"
        return "unknown"
    finally:
        k32.CloseHandle(h)


def _kind_linux(path: str) -> str:
    try:
        st = os.stat(path)
        dev = Path(f"/sys/dev/block/{os.major(st.st_dev)}:{os.minor(st.st_dev)}").resolve()
        for d in (dev, dev.parent):
            rot = d / "queue" / "rotational"
            if rot.exists():
                if (d / "removable").exists() and (d / "removable").read_text().strip() == "1":
                    return "removable"
                return "hdd" if rot.read_text().strip() == "1" else "ssd"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def kind(path: str) -> str:
    """파일이 있는 저장장치 종류. 실패 = unknown."""
    try:
        if os.name == "nt":
            return _kind_nt(_drive_root(path))
        return _kind_linux(path)
    except Exception:  # noqa: BLE001
        return "unknown"


SLOW = ("hdd", "removable")
ORDER = {"removable": 0, "hdd": 1, "unknown": 2, "ssd": 3}


def slowest(paths) -> str:
    """여러 원본 중 가장 느린 장치(동시 작업 수는 그 기준)."""
    ks = {kind(p) for p in paths if p}
    return min(ks, key=ORDER.get) if ks else "unknown"


def counts(k: str, cores: int) -> tuple[int, int]:
    """(동시 분석, 동시 렌더). 렌더는 원본을 순서대로 읽어 느린 장치에서도 2개까지는 괜찮음(추정)."""
    base_r = max(1, min(3, cores // 16))                # NVENC 인코더 수 한계로 최대 3
    if k in SLOW:
        return 2, min(base_r, 2)
    if k == "ssd":
        return max(4, min(8, cores // 8)), base_r
    return max(2, min(4, cores // 8)), base_r            # 모름 = v0.16.18 값
