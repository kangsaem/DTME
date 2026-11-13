"""다이빙 기록(v0.16.84): FIT(다이빙 컴퓨터) · DTMD 백업(dtmd-logbook.zip / logbook.json) → 다이빙 목록.
DTMD(kangsaem/DTMD index.html parseFIT·fitToDives·rowsOf)와 같은 방식.

다이빙 = {"id", "src": "fit"|"dtmd", "name", "start": 현지 시각(초, 시간대 없는 숫자 — 파일 이름 시각과 같은 기준),
          "pts": [[초, 수심m], ...] (입수부터), "max": 최대 수심}
시각 = 'naive' 초: datetime(…, tzinfo=UTC) 로 계산(현지 시각을 UTC 인 척) — 시간대 계산 없이 파일 이름 시각과 바로 비교.
FIT = 초 단위 · DTMD = 첫 입수 분 단위(둘째부터 수면 휴식 분 단위 누적 → ±1~2분)."""
from __future__ import annotations

import io
import json
import os
import re
import struct
import zipfile
from datetime import datetime, timezone

FIT_EPOCH = 631065600            # 1989-12-31 00:00 UTC
DIVE_EXT = (".fit",)             # .zip / .json 은 내용으로 판단(DTMD 백업만)


# ------------------------------------------------------------------ FIT
def parse_fit(buf: bytes) -> dict:
    """FIT 바이너리 → {'record': [...], 'session': [...], 'activity': [...], 'file_id': [...], 'device_info': [...]}.
    메시지 = {필드 번호: 값}. 압축 시간 머리글(253 = timestamp) 처리. 잘못된 값(invalid) = 뺌."""
    if len(buf) < 12 or buf[8:12] != b".FIT":
        raise ValueError("FIT 파일이 아님")
    hs = buf[0]
    data_end = min(len(buf), hs + struct.unpack_from("<I", buf, 4)[0])
    names = {0: "file_id", 18: "session", 20: "record", 34: "activity", 23: "device_info"}
    out = {v: [] for v in names.values()}
    inv = {0: 0xFF, 1: 0x7F, 2: 0xFF, 0x83: 0x7FFF, 0x84: 0xFFFF, 0x85: 0x7FFFFFFF, 0x86: 0xFFFFFFFF,
           0x8C: 0xFFFFFFFF, 0x8B: 0xFFFF, 0x0A: 0, 0x0D: 0xFF}
    defs: dict = {}
    p, last_ts = hs, 0

    def rd(bt, off, size, le):
        e = "<" if le else ">"
        if bt == 7:
            s = buf[off:off + size].split(b"\0", 1)[0]
            try:
                return s.decode("utf-8")
            except UnicodeDecodeError:
                return s.decode("latin-1")
        if size == 1:
            return struct.unpack_from("b" if bt == 1 else "B", buf, off)[0]
        if size == 2:
            return struct.unpack_from(e + ("h" if bt == 0x83 else "H"), buf, off)[0]
        if size == 4:
            if bt == 0x85:
                return struct.unpack_from(e + "i", buf, off)[0]
            if bt == 0x88:
                return struct.unpack_from(e + "f", buf, off)[0]
            return struct.unpack_from(e + "I", buf, off)[0]
        if size == 8 and bt == 0x89:
            return struct.unpack_from(e + "d", buf, off)[0]
        return None

    def read_data(d):
        nonlocal p
        m = {}
        for n, s, bt in d["f"]:
            if p + s > len(buf):
                raise ValueError("FIT 끝이 잘림")
            v = rd(bt, p, s, d["le"])
            p += s
            if v is None:
                continue
            iv = inv.get(bt)
            if bt != 7 and iv is not None and v == iv:
                continue
            m[n] = v
        for _n, s, _d in d["dev"]:
            p += s
        return m

    def push(d, m):
        nm = names.get(d["gm"])
        if nm:
            out[nm].append(m)

    while p < data_end:
        h = buf[p]
        p += 1
        if h & 0x80:                                      # 압축 시간 머리글
            lt, off = (h >> 5) & 3, h & 0x1F
            d = defs.get(lt)
            if d is None:
                raise ValueError("FIT 정의 없음")
            ts = (last_ts & ~0x1F) + off
            if off < (last_ts & 0x1F):
                ts += 0x20
            last_ts = ts
            m = read_data(d)
            m[253] = ts
            push(d, m)
            continue
        lt = h & 0x0F
        if h & 0x40:                                      # 정의 메시지
            le = buf[p + 1] == 0
            gm = struct.unpack_from("<H" if le else ">H", buf, p + 2)[0]
            nf = buf[p + 4]
            p += 5
            f = []
            for _ in range(nf):
                f.append((buf[p], buf[p + 1], buf[p + 2]))
                p += 3
            dev = []
            if h & 0x20:
                nd = buf[p]
                p += 1
                for _ in range(nd):
                    dev.append((buf[p], buf[p + 1], buf[p + 2]))
                    p += 3
            defs[lt] = {"gm": gm, "le": le, "f": f, "dev": dev}
            continue
        d = defs.get(lt)
        if d is None:
            raise ValueError("FIT 정의 없음")
        m = read_data(d)
        if m.get(253) is not None:
            last_ts = m[253]
        push(d, m)
    return out


def _rdp(pts, eps):
    """수심 점 줄이기(DTMD rdpV 와 같음): 직선에서 eps(m) 넘게 벗어나는 점만 남김."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    st = [(0, len(pts) - 1)]
    while st:
        i, j = st.pop()
        (ta, da), (tb, db) = pts[i], pts[j]
        mx, mi = -1.0, -1
        for k in range(i + 1, j):
            u = (pts[k][0] - ta) / ((tb - ta) or 1)
            dd = abs(pts[k][1] - (da + (db - da) * u))
            if dd > mx:
                mx, mi = dd, k
        if mx > eps:
            keep[mi] = True
            st += [(i, mi), (mi, j)]
    return [q for q, k in zip(pts, keep) if k]


def fit_dives(o: dict, name: str = "") -> list:
    """FIT 메시지 → 다이빙(세션마다). 현지 시각 = UTC + (activity local_timestamp − timestamp), 없으면 0(UTC)."""
    rec = o["record"]
    ses = o["session"] or ([{2: rec[0].get(253), 253: rec[-1].get(253)}] if rec else [])
    act = o["activity"][0] if o["activity"] else None
    off = (act[5] - act[253]) if act and act.get(5) is not None and act.get(253) is not None else None
    dives = []
    for k, s in enumerate(ses):
        st, en = s.get(2), s.get(253)
        if st is None or en is None:
            continue
        rs = [r for r in rec if r.get(253) is not None and st <= r[253] <= en and r.get(92) is not None]
        raw = [(0.0, 0.0)] + [(float(r[253] - st), r[92] / 1000.0) for r in rs if r[253] > st]
        if len(raw) < 3 or max(d for _t, d in raw) <= 0.5:
            continue
        uw = [r for r in rs if r[92] / 1000 > 0.5]                  # 프리다이빙(가장 길게 물속 < 3분)은 뺌(DTMD 와 같음)
        sub = s.get(6)
        if sub in (56, 57):
            continue
        best, a = 0, None
        for r in rs:
            u = r[92] / 1000 > 0.5
            if u and a is None:
                a = r[253]
            if not u and a is not None:
                best, a = max(best, r[253] - a), None
        if a is not None and rs:
            best = max(best, rs[-1][253] - a)
        if uw and best < 180:
            continue
        pts, t0 = _trim(_rdp(raw, 0.1))
        dives.append({"id": f"fit{st}", "src": "fit", "name": name, "start": float(st + t0 + FIT_EPOCH + (off or 0)),
                      "utc": float(st + t0 + FIT_EPOCH),
                      "pts": [[round(t, 1), round(max(0.0, d), 2)] for t, d in pts],
                      "max": round(max(d for _t, d in raw), 1), "tz": off is not None})
    return dives


def _trim(pts):
    """앞뒤 수면(0.3m 이하) 구간 줄이기: 입수 직전·출수 직후 한 점만 → (점들(0초부터), 앞에서 뺀 초)."""
    if len(pts) < 3:
        return list(pts), 0.0
    i = 0
    while i + 1 < len(pts) and pts[i + 1][1] <= 0.3:
        i += 1
    j = len(pts) - 1
    while j - 1 > i and pts[j - 1][1] <= 0.3:
        j -= 1
    out = pts[i:j + 1]
    t0 = out[0][0]
    return [(t - t0, d) for t, d in out], t0


# ------------------------------------------------------------------ DTMD 백업
_FIT_MEMO = re.compile(r"\((FIT|UDDF|JSON)\)\s*$", re.M)


def _naive(y, mo, d, h=0, mi=0, s=0.0) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() + s


def dtmd_dives(obj, name: str = "") -> list:
    """DTMD logbook.json(백업) → 다이빙. FIT·UDDF·JSON 에서 온 다이빙만(손으로 그린 로그 = 뺌).
    입수 시각 = 그날 첫 입수(시:분) + 앞 다이빙 길이 + 수면 휴식(분) (DTMD rowsOf 와 같음)."""
    logs = obj.get("logs") if isinstance(obj, dict) else obj
    out = []
    for x in logs or []:
        if not isinstance(x, dict) or x.get("id") == "dtmd-sample":
            continue
        st = x.get("state") or {}
        ds = st.get("dives") or []
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(x.get("date", "")))
        tm = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?", str(x.get("time", "")))    # 초도(DTMD 초 단위 저장 대비)
        if not ds or not m or not tm:
            continue
        sm = x.get("sum") or {}
        dv = sm.get("dv") or [{"N": sm.get("N0", 0), "maxD": sm.get("maxD", 0), "si": 0}]
        cur = int(tm.group(1)) * 60 + int(tm.group(2)) + float(tm.group(3) or 0) / 60   # 분
        for i, d in enumerate(ds):
            if i > 0:
                prev = dv[i - 1] if i - 1 < len(dv) else {}
                si = (dv[i] if i < len(dv) else {}).get("si", d.get("si", 0)) or 0
                cur += float(prev.get("N", 0) or 0) / 60 + float(si)
            memo = d.get("memo") if d.get("memo") is not None else (x.get("memo") if len(ds) == 1 else "")
            if not (d.get("fit") or _FIT_MEMO.search(memo or "") or x.get("src") == "fit"):
                continue
            pts = [(float(q.get("t", 0)), float(q.get("d", 0))) for q in (d.get("pts") or []) if isinstance(q, dict)]
            if len(pts) < 2 or max(dd for _t, dd in pts) <= 0.5:
                continue
            start = _naive(int(m.group(1)), int(m.group(2)), int(m.group(3))) + cur * 60
            utc = None
            u0, o0 = d.get("utc0", d.get("startUTC")), d.get("off0", d.get("localOff"))
            if isinstance(u0, (int, float)) and isinstance(o0, (int, float)) and u0 > 1e9:   # DTMD: 입수 UTC + 현지 시차
                utc = float(u0)
            if isinstance(d.get("sec0"), (int, float)):          # DTMD 새 형식: 다이빙마다 입수 시각 = 그날 0시부터 초(현지)
                start = _naive(int(m.group(1)), int(m.group(2)), int(m.group(3))) + float(d["sec0"])
            elif utc is not None:
                start = utc + float(o0)
            elif d.get("start") is not None and isinstance(d.get("start"), (int, float)) and d["start"] > 1e9:
                start = float(d["start"])
            pts, t0 = _trim(pts)                                 # 입수 전 수면 구간 = 뺌(FIT 과 같게), 입수 시각도 그만큼
            start += t0
            out.append({"id": f"dtmd{int(start)}", "src": "dtmd", "name": name, "start": float(start),
                        **({"utc": utc + t0} if utc is not None else {}),
                        "sec": isinstance(d.get("sec0"), (int, float)),
                        "pts": [[round(t, 1), round(max(0.0, dd), 2)] for t, dd in pts],
                        "max": round(max(dd for _t, dd in pts), 1), "tz": True})
    return out


# ------------------------------------------------------------------ 파일 → 다이빙
def is_dive_file(path: str) -> bool:
    """끌어다 놓은 파일이 다이빙 기록인가: .fit · DTMD 백업 .zip(logbook.json 들어 있음) · DTMD .json."""
    ext = os.path.splitext(path)[1].lower()
    if ext in DIVE_EXT:
        return True
    try:
        if ext == ".zip":
            with zipfile.ZipFile(path) as z:
                return "logbook.json" in z.namelist()
        if ext == ".json" and os.path.getsize(path) < 200 * 1024 * 1024:
            with open(path, "rb") as f:
                head = f.read(4096).decode("utf-8", "ignore")
            return '"app":"DTMD"' in head.replace(" ", "") or '"logs"' in head
    except (OSError, zipfile.BadZipFile):
        return False
    return False


def read_dives(path: str) -> list:
    """다이빙 기록 파일 → 다이빙 목록(입수 시각 순). 못 읽으면 ValueError."""
    name = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fit":
        with open(path, "rb") as f:
            ds = fit_dives(parse_fit(f.read()), name)
    elif ext == ".zip":
        with zipfile.ZipFile(path) as z:
            ds = dtmd_dives(json.load(io.TextIOWrapper(z.open("logbook.json"), "utf-8")), name)
    else:
        with open(path, encoding="utf-8") as f:
            ds = dtmd_dives(json.load(f), name)
    return sorted(ds, key=lambda d: d["start"])


def merge(old: list, new: list) -> list:
    """같은 다이빙(시간이 절반 넘게 겹침)이 있으면 FIT 우선(초 단위). 나머지는 더함."""
    def same(a, b):
        a0, a1, b0, b1 = a["start"], a["start"] + dur(a), b["start"], b["start"] + dur(b)
        return min(a1, b1) - max(a0, b0) > 0.5 * max(1.0, min(a1 - a0, b1 - b0))
    out = list(old)
    for d in new:
        hit = next((i for i, o in enumerate(out) if same(o, d)), None)
        if hit is None:
            out.append(d)
        elif d["src"] == "fit" and out[hit]["src"] != "fit":
            out[hit] = d
    return sorted(out, key=lambda d: d["start"])


# ------------------------------------------------------------------ 시각 → 수심
def dur(d: dict) -> float:
    return float(d["pts"][-1][0]) if d.get("pts") else 0.0


def depth_at(d: dict, t: float) -> float:
    """입수부터 t 초의 수심(점 사이 직선)."""
    pts = d["pts"]
    if not pts:
        return 0.0
    if t <= pts[0][0]:
        return float(pts[0][1])
    lo, hi = 0, len(pts) - 1
    if t >= pts[hi][0]:
        return float(pts[hi][1])
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pts[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    (ta, da), (tb, db) = pts[lo], pts[hi]
    return float(da + (db - da) * (t - ta) / ((tb - ta) or 1))


def find_utc(dives: list, utc: float):
    """UTC 초 → 그 시각이 들어가는 다이빙(UTC 를 아는 다이빙만)."""
    for d in dives or []:
        u = d.get("utc")
        if u is not None and u <= utc <= u + dur(d):
            return d
    return None


def find(dives: list, when: float, margin: float = 0.0):
    """현지 시각(초) → 그 시각이 들어가는 다이빙(없으면 None)."""
    for d in dives or []:
        if d["start"] - margin <= when <= d["start"] + dur(d) + margin:
            return d
    return None


def name_time(path: str):
    """파일 이름의 촬영 시각(초 단위, naive 현지): DJI_20261025100118_… · VID_20260917_080520 · 20261025_100118.
    초가 없으면(12자리) 0초. 없으면 None."""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?!\d)", stem) \
        or re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if m:
        y, mo, d, h, mi, s = (int(v) for v in m.groups())
    else:
        m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?!\d)", stem)
        if not m:
            return None
        y, mo, d, h, mi = (int(v) for v in m.groups())
        s = 0
    try:
        return _naive(y, mo, d, h, mi, s)
    except ValueError:
        return None


def fmt_date(when: float) -> str:
    t = datetime.fromtimestamp(when, timezone.utc)
    return f"{t.year}/{t.month:02d}/{t.day:02d}"


def fmt_hm(when: float) -> str:
    t = datetime.fromtimestamp(when, timezone.utc)
    return f"{t.hour:02d}:{t.minute:02d}"
