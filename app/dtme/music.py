"""음악 분석(v0.16.63): 파형 · 박자 · 마디 첫 박 · 세기 · 분위기 점수. numpy 만(외부 음악 라이브러리 없음).

방법(널리 쓰는 방식 그대로):
- 소리 → 22050Hz 모노 → STFT(2048, 512 = 23ms) → 대역별 로그 세기의 증가분 합 = '소리가 치는 정도'(onset) 곡선
- 템포 = onset 곡선의 자기상관에서 40~220 BPM 사이 가장 센 주기(120 BPM 근처를 조금 더 믿음)
- 박자 = 동적 계획법(Ellis 2007): 소리가 치는 곳에 맞추되 간격이 템포에서 크게 벗어나지 않게
- 마디 첫 박 = 3박/4박 × 시작 위치 중 낮은 소리(킥·베이스)가 가장 센 조합
- 확신도 = 박자 위치의 onset 이 평균보다 얼마나 센가(잔잔한 피아노·현악은 낮음 → 화면에 흐리게)
결과는 cache/music/ 에 저장(같은 파일은 다시 안 함).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np

from . import paths

SR = 22050
N_FFT = 2048
HOP = 512
FPS = SR / HOP                  # onset 곡선 프레임/초 ≈ 43
PEAKS_PER_SEC = 50              # 파형 표시용
VERSION = 3                     # v0.16.68 웅장함(음량 변화 폭·저음) 추가 → 다시 분석


def _decode(path: str, sr: int = SR) -> np.ndarray:
    r = subprocess.run([paths.ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
    return np.frombuffer(r.stdout, np.float32).copy()


def _stft_mag(y: np.ndarray) -> np.ndarray:
    if len(y) < N_FFT:
        y = np.pad(y, (0, N_FFT - len(y)))
    y = np.pad(y, (N_FFT // 2, N_FFT // 2))
    n = 1 + (len(y) - N_FFT) // HOP
    win = np.hanning(N_FFT).astype(np.float32)
    out = np.empty((n, N_FFT // 2 + 1), np.float32)
    step = 2048
    for i in range(0, n, step):                         # 메모리 아끼려고 나눠서
        k = min(step, n - i)
        idx = (np.arange(k)[:, None] + i) * HOP + np.arange(N_FFT)[None, :]
        out[i:i + k] = np.abs(np.fft.rfft(y[idx] * win, axis=1))
    return out


def _bands(n_bands: int = 40, fmin: float = 30.0, fmax: float = 8000.0):
    """로그 간격 대역 → STFT 칸 묶음 행렬."""
    freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
    edges = np.geomspace(fmin, fmax, n_bands + 1)
    m = np.zeros((len(freqs), n_bands), np.float32)
    for b in range(n_bands):
        sel = (freqs >= edges[b]) & (freqs < edges[b + 1])
        if not sel.any():
            sel[np.argmin(np.abs(freqs - (edges[b] + edges[b + 1]) / 2))] = True
        m[sel, b] = 1.0 / sel.sum()
    return m, edges


def _onset(S: np.ndarray):
    """(전체 onset, 낮은 소리(<120Hz, 킥·베이스) onset, 대역 로그 세기 B, 대역 경계) — onset 은 평균 빼고 양수만, 크기 맞춤."""
    m, edges = _bands()
    B = np.log1p(100.0 * (S @ m))
    d = np.maximum(0.0, np.diff(B, axis=0, prepend=B[:1]))
    on = d.mean(axis=1)
    lo = d[:, edges[1:] <= 120].mean(axis=1)
    k = int(FPS * 1.0) | 1
    ker = np.ones(k) / k

    def hp(x):
        x = x - np.convolve(x, ker, "same")             # 느린 변화(크레센도) 빼기
        x = np.maximum(0.0, x)
        s = x.std()
        return x / s if s > 1e-9 else x
    return hp(on), hp(lo), B, edges


def _tempo(on: np.ndarray, start_bpm: float = 115.0, std_oct: float = 1.0):
    """자기상관 → (bpm, 자기상관 세기 0~1)."""
    n = len(on)
    x = on - on.mean()
    f = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    if ac[0] <= 0:
        return 120.0, 0.0
    ac = ac / ac[0]
    lags = np.arange(n)
    with np.errstate(divide="ignore"):
        bpm = 60.0 * FPS / np.maximum(lags, 1)
    ok = (bpm >= 40) & (bpm <= 220) & (lags > 0)
    prior = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1e-3) / start_bpm) / std_oct) ** 2)
    score = np.where(ok, np.maximum(ac, 0) * prior, -1)
    # 2배·절반 주기 합치기(박자 하나만 튀는 것 방지)
    best = int(np.argmax(score))
    lag = best
    if lag > 0:                                         # 포물선으로 칸 사이 값
        a, b, c = score[lag - 1], score[lag], score[min(n - 1, lag + 1)]
        den = a - 2 * b + c
        lag = lag + (0.5 * (a - c) / den if abs(den) > 1e-9 else 0.0)
    return float(60.0 * FPS / max(lag, 1e-6)), float(max(0.0, ac[best]))


def _beats(on: np.ndarray, bpm: float, tight: float = 100.0) -> np.ndarray:
    """동적 계획법 박자 추적 → 프레임 번호들."""
    n = len(on)
    period = 60.0 * FPS / bpm
    w = np.arange(-int(period), int(period) + 1)
    local = np.convolve(on, np.exp(-0.5 * (w * 32.0 / period) ** 2), "same")
    cum = np.zeros(n)
    back = -np.ones(n, int)
    lo, hi = int(round(2 * period)), int(round(period / 2))
    offs = np.arange(-lo, -hi + 1)
    txw = -tight * np.log(-offs / period) ** 2
    for i in range(n):
        z = i + offs
        v = z >= 0
        if not v.any():
            cum[i] = local[i]
            continue
        cand = cum[z[v]] + txw[v]
        j = int(np.argmax(cand))
        if cand[j] > 0:
            cum[i] = local[i] + cand[j]
            back[i] = z[v][j]
        else:
            cum[i] = local[i]
    # 끝 박자 = 마지막 한 주기 안에서 누적값이 가장 큰 곳
    tail = max(0, n - int(period * 1.5))
    i = tail + int(np.argmax(cum[tail:]))
    out = []
    while i >= 0:
        out.append(i)
        i = back[i]
    b = np.array(out[::-1])
    # 앞뒤 조용한 곳의 박자 빼기(onset 이 거의 없는 곳)
    if len(b) > 4:
        thr = 0.15 * np.sqrt(np.mean(local[b] ** 2))
        keep = np.nonzero(local[b] > thr)[0]
        if len(keep):
            b = b[keep[0]:keep[-1] + 1]
    return b


def _downbeats(beat_fr: np.ndarray, lo: np.ndarray, on: np.ndarray, B: np.ndarray, edges: np.ndarray):
    """(박자 수 3|4, 첫 마디 첫 박 위치 0..m-1). 마디 첫 박 = 화음이 바뀌는 곳(그 박 앞뒤 반 박의 중·고음 대역 모양 차이)
    + 낮은 소리(킥·베이스). 킥이 매 박마다인 곡(케이팝·댄스)은 화음 바뀜이 가름. 3박은 뚜렷할 때만."""
    if len(beat_fr) < 8:
        return 4, 0
    mid = (edges[:-1] >= 150) & (edges[1:] <= 4000)
    H = B[:, mid]
    half = max(2, int(np.median(np.diff(beat_fr)) / 2))
    chg = np.zeros(len(beat_fr))
    for i, f in enumerate(beat_fr):
        a = H[max(0, f - half):f].mean(axis=0) if f > 0 else H[0]
        c = H[f:f + half].mean(axis=0)
        a, c = a - a.mean(), c - c.mean()
        chg[i] = 1 - float((a * c).sum() / (np.sqrt((a * a).sum() * (c * c).sum()) + 1e-9))

    def z(x):
        return (x - x.mean()) / (x.std() + 1e-9)
    v = 0.5 * z(chg) + 0.35 * z(lo[beat_fr]) + 0.15 * z(on[beat_fr])
    best = {}
    for m in (4, 3):
        sc = [v[ph::m].mean() for ph in range(m)]
        ph = int(np.argmax(sc))
        best[m] = (ph, sc[ph])
    if best[3][1] > 0.3 and best[3][1] > best[4][1] * 1.3:
        return 3, best[3][0]
    return 4, best[4][0]


def analyze(path: str) -> dict:
    """곡 1개 분석 → dict(JSON 저장 가능)."""
    y = _decode(path)
    dur = len(y) / SR
    out = {"v": VERSION, "dur": round(dur, 3)}
    # 파형(초당 50개, 0~255)
    k = max(1, SR // PEAKS_PER_SEC)
    n = len(y) // k
    pk = np.abs(y[:n * k]).reshape(n, k).max(axis=1) if n else np.zeros(0)
    top = float(np.percentile(pk, 99.5)) if len(pk) else 1.0
    out["peaks"] = np.clip(np.round(pk / max(top, 1e-6) * 255), 0, 255).astype(int).tolist()
    # 세기(0.5초마다, dBFS)
    k2 = SR // 2
    n2 = len(y) // k2
    rms = np.sqrt((y[:n2 * k2].reshape(n2, k2) ** 2).mean(axis=1) + 1e-12) if n2 else np.zeros(1)
    db = 20 * np.log10(rms + 1e-9)
    out["energy"] = np.round(db, 1).tolist()
    loud = db[db > db.max() - 40] if len(db) else db
    out["loud"] = round(float(np.mean(loud)) if len(loud) else -60.0, 2)
    # 앞 조용한 곳(소리 시작)
    lead = 0.0
    if len(db):
        thr = db.max() - 35
        i = int(np.argmax(db > thr))
        lead = max(0.0, i * 0.5 - 0.25)
    out["lead"] = round(lead, 2)
    if dur < 3:
        out.update(bpm=0.0, conf=0.0, beats=[], bars=[], meter=4, rate=0.0, bright=0.0)
        return out
    S = _stft_mag(y)
    on, lo, B, edges = _onset(S)
    bpm, acs = _tempo(on)
    b = _beats(on, bpm)
    bt = b / FPS
    if len(bt) > 3:                                   # 박자 간격 중앙값으로 템포 다시
        bpm = float(60.0 / np.median(np.diff(bt)))
    # 느린 곡이 2배 빠르기로 잡히는 것: 리듬이 흐릿(확신 낮음)하고 타악기가 적은 곡이 100 BPM 넘으면 절반으로(피아노·발라드·뉴에이지)
    dd0 = np.maximum(0.0, np.diff(B, axis=0))
    perc = float(dd0[:, edges[:-1] >= 4000].mean() / (dd0.mean() + 1e-9))
    if bpm > 100 and perc < 0.6 and acs < 0.3:          # acs = 자기상관 세기(박이 일정하게 반복되는 정도)
        bpm /= 2
        b = _beats(on, bpm)
        bt = b / FPS
        if len(bt) > 3:
            bpm = float(60.0 / np.median(np.diff(bt)))
    meter, ph = _downbeats(b, lo, on, B, edges)
    # 확신도: 박자 위치 onset ÷ 전체 평균 (리듬 뚜렷 ≈ 3 이상, 잔잔 ≈ 1.3)
    loc = np.convolve(on, np.ones(5) / 5, "same")
    ratio = float(loc[b].mean() / (loc.mean() + 1e-9)) if len(b) else 0.0
    conf = float(np.clip((ratio - 1.3) / 1.5, 0, 1)) * float(np.clip(acs * 3, 0.3, 1))
    # 소리가 치는 횟수(초당) — 분위기
    pk_on = (on[1:-1] > on[:-2]) & (on[1:-1] >= on[2:]) & (on[1:-1] > 1.0)
    rate = float(pk_on.sum() / dur)
    cent = (S @ np.fft.rfftfreq(N_FFT, 1 / SR)) / (S.sum(axis=1) + 1e-9)
    w8 = S.sum(axis=1)
    bright = float((cent * w8).sum() / (w8.sum() + 1e-9))
    # 웅장함 재료(v0.16.68): 저음(150Hz 아래) 에너지 비율 · 음량 변화 폭(0.5초 세기의 큰 쪽 − 작은 쪽, 소리 나는 곳만)
    fq = np.fft.rfftfreq(N_FFT, 1 / SR)                 # 크기(제곱 아님) 합 비율 — 제곱이면 킥·베이스가 거의 다 차지해 곡끼리 차이가 안 남
    out["bass"] = round(float(S[:, fq < 150].sum() / (S[:, fq < 8000].sum() + 1e-12)), 4)
    lv = db[db > db.max() - 40] if len(db) else db
    out["dyn"] = round(float(np.percentile(lv, 95) - np.percentile(lv, 20)) if len(lv) > 4 else 0.0, 2)
    out["perc"] = round(perc, 3)              # 타악기 정도: 높은 대역(>4kHz) 세기 증가분 ÷ 전체(드럼·하이햇 = 큼, 피아노·현악 = 작음)
    out.update(bpm=round(bpm, 2), conf=round(conf, 3), beats=np.round(bt, 3).tolist(),
               bars=np.round(bt[ph::meter], 3).tolist(), meter=int(meter), rate=round(rate, 2), bright=round(bright, 1))
    return out


def mood(info: dict) -> float:
    """곡 분위기 0(잔잔) ~ 1(신남) = 빠르기(리듬이 뚜렷할수록 믿음) · 타악기 정도 · 소리 치는 횟수 · 리듬 뚜렷함.
    음량은 안 씀(마스터링에 따라 같은 분위기도 크게 다름)."""
    if not info:
        return 0.5
    c = float(info.get("conf", 0))
    bpm = float(info.get("bpm", 0)) or 80.0
    e_tempo = float(np.clip((bpm - 65) / 75, 0, 1))
    e_perc = float(np.clip(float(info.get("perc", 0.5)) / 1.2, 0, 1))
    e_rate = float(np.clip(float(info.get("rate", 0)) / 5.0, 0, 1))
    return round(0.35 * e_tempo * (0.5 + 0.5 * c) + 0.25 * e_perc + 0.20 * e_rate + 0.20 * c, 3)


def grand(info: dict) -> float:
    """곡 웅장함 0 ~ 1(v0.16.68) = 음량 변화 폭(조용 → 크게 터짐, 6dB 0 ~ 20dB 1) · 저음 비율(150Hz 아래 크기 합 ÷ 8kHz 아래, 0.05 0 ~ 0.30 1).
    한계: 실제 곡으로 기준 확인 전(합성음으로만 시험)."""
    if not info or "dyn" not in info:
        return 0.5
    e_dyn = float(np.clip((float(info.get("dyn", 0)) - 6) / 14, 0, 1))
    e_bass = float(np.clip((float(info.get("bass", 0)) - 0.05) / 0.25, 0, 1))
    return round(0.55 * e_dyn + 0.45 * e_bass, 3)


def fit_score(info: dict, mood_t: float, grand_t: float | None) -> float:
    """작을수록 맞음: 분위기 차 + (웅장함 목표가 있으면) 웅장함 차 × 0.7."""
    d = abs(mood(info) - mood_t)
    if grand_t is not None:
        d += 0.7 * abs(grand(info) - grand_t)
    return d


# ------------------------------------------------------------------ 캐시
def _key(path: str) -> str:
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|{VERSION}".encode()).hexdigest()[:16]


def cache_file(path: str) -> Path:
    d = paths.cache_dir() / "music"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_key(path)}.json"


_mem: dict = {}


def cached(path: str) -> dict | None:
    """저장된 분석(없으면 None, 분석 안 함)."""
    try:
        k = _key(path)
    except OSError:
        return None
    if k in _mem:
        return _mem[k]
    f = cache_file(path)
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("v") == VERSION:
                _mem[k] = d
                return d
        except Exception:  # noqa: BLE001
            pass
    return None


def get(path: str) -> dict:
    """분석(저장된 것 있으면 그것). 작업 스레드에서 부름."""
    d = cached(path)
    if d is not None:
        return d
    d = analyze(path)
    f = cache_file(path)
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, f)
    _mem[_key(path)] = d
    return d


# ------------------------------------------------------------------ 타임라인 좌표
def beats_on_timeline(m: dict, info: dict | None, bars: bool = False) -> list[float]:
    """음악 클립(타임라인 t0 · 파일 안 시작 off · 길이 len)의 박자(또는 마디 첫 박) → 타임라인 초."""
    if not info:
        return []
    t0, off, ln = float(m["t0"]), float(m.get("off", 0)), float(m["len"])
    src = info.get("bars" if bars else "beats") or []
    return [t0 + b - off for b in src if off - 1e-6 <= b <= off + ln + 1e-6]


# ------------------------------------------------------------------ 영상 분위기 · 음악 자동(v0.16.64)
def _gray_pair(path: str, t: float, gap: float = 0.25):
    """t 와 t+gap 의 화면(80×45 회색, 작게 줄여 물속 부유물·노이즈 덜 봄) 2장 → (a, b) 또는 None."""
    r = subprocess.run([paths.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-an",
                        "-vf", f"fps={1 / gap:.4f},scale=80:45:flags=area,format=gray", "-frames:v", "2", "-f", "rawvideo", "-"],
                       capture_output=True, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    d = np.frombuffer(r.stdout, np.uint8)
    n = 80 * 45
    if len(d) < 2 * n:
        return None
    return d[:n].reshape(45, 80).astype(np.float32), d[n:2 * n].reshape(45, 80).astype(np.float32)


def video_mood(project, segs, cancel=None) -> dict:
    """타임라인 영상의 분위기 0(잔잔) ~ 1(빠름) = 움직임(0.25초 사이 화면 차이) · 컷 빠르기 · 배속.
    프록시(작고 빠름)가 있으면 그것으로, 컷마다 최대 3곳(전체 30곳까지)."""
    lens, motions, speeds = [], [], []
    pts = []
    for g in segs:
        src = project.source(g.src)
        if src is None or not src.frames:
            continue
        fps = float(src.fps)
        ln = (g.fout - g.fin) / fps / max(0.01, g.speed)
        lens.append(ln)
        speeds.append((g.speed, ln))
        path = src.proxy if getattr(src, "proxy", "") and Path(src.proxy).exists() else src.path
        k = 1 if ln < 3 else 2 if ln < 8 else 3
        for j in range(k):
            pts.append((path, (g.fin + (j + 0.5) / k * (g.fout - g.fin)) / fps))
    if len(pts) > 30:
        pts = [pts[int(i * len(pts) / 30)] for i in range(30)]
    for path, t in pts:
        if cancel is not None and cancel.is_set():
            break
        pr = _gray_pair(path, t)
        if pr is not None:
            motions.append(float(np.abs(pr[0] - pr[1]).mean() / 255.0))
    total = sum(lens) or 1.0
    m = float(np.median(motions)) if motions else 0.02
    cpm = len(lens) / total * 60
    sp = sum(s * ln for s, ln in speeds) / total if speeds else 1.0
    # 움직임 기준: 사용자 Ace Pro 거북이 클립(천천히 따라 헤엄, 들고 찍음) ≈ 0.07 = '잔잔한 편'(0.2 남짓)
    e = 0.55 * float(np.clip((m - 0.04) / 0.14, 0, 1)) + 0.30 * float(np.clip((cpm - 4) / 20, 0, 1)) + 0.15 * float(np.clip(sp - 1, 0, 1))
    return {"mood": round(e, 3), "motion": round(m, 4), "cuts_per_min": round(cpm, 1), "speed": round(sp, 2), "length": round(total, 2)}


def mood_word(x: float) -> str:
    return "잔잔" if x < 0.35 else "보통" if x < 0.6 else "신남"


def target_mood(video: float) -> float:
    """영상 분위기(0~1) → 곡 분위기 목표(곡 점수는 대략 0.15~0.9 에 모임)."""
    return 0.15 + 0.75 * float(np.clip(video, 0, 1))


def first_bar(inf: dict, lead: float) -> float:
    """곡 시작 = 앞 조용한 곳 뒤 첫 마디 첫 박(리듬 뚜렷할 때), 아니면 조용한 곳 뒤."""
    if float(inf.get("conf", 0)) >= 0.3:
        b = [x for x in (inf.get("bars") or []) if x >= lead - 0.05]
        if b and b[0] - lead < 4.0:
            return float(b[0])
    return lead


def plan(audios: list[dict], infos: dict, total: float, video: float, xfade: float = 2.0, max_songs: int = 3,
         target: float | None = None, grand_t: float | None = None, avoid: str = "", bar_start: bool = False) -> list[dict]:
    """음악 자동: 영상 길이(total)를 채우는 곡 순서 → 음악 줄 항목 [{"path","t0","off","dur","len"}].
    - 곡 고르기 = 곡 분위기가 영상 분위기에 가까운 순. 1곡으로 채울 수 있는 곡이 분위기 차이 0.1 안에 있으면 그 곡 1개.
    - 곡 시작 = 앞 조용한 곳 다음. 이어 붙일 곡은 마지막 마디 첫 박에서 끝내고 다음 곡과 xfade 초 겹침(크로스페이드).
    - 마지막 곡 = 영상 끝에서 자름(페이드아웃은 음악 설정 값)."""
    target = target_mood(video) if target is None else target
    cand = []
    for a in audios:
        inf = infos.get(a["path"])
        if not inf or float(inf.get("dur", 0)) < 5:
            continue
        cand.append((fit_score(inf, target, grand_t) + (0.25 if a["path"] == avoid else 0.0), a, inf))
    if not cand or total <= 0.5:
        return []
    cand.sort(key=lambda c: c[0])
    usable = lambda inf: float(inf["dur"]) - float(inf.get("lead", 0))          # noqa: E731
    one = [c for c in cand if usable(c[2]) >= total and c[0] <= cand[0][0] + 0.10]
    order = [one[0]] + [c for c in cand if c is not one[0]] if one else cand
    out, t = [], 0.0
    for _d, a, inf in order[:max_songs]:
        off = first_bar(inf, float(inf.get("lead", 0))) if bar_start else float(inf.get("lead", 0))
        dur = float(inf["dur"])
        avail = dur - off
        if t + avail >= total - 0.05:
            out.append({"path": a["path"], "t0": round(t, 3), "off": round(off, 3), "dur": dur, "len": round(total - t, 3)})
            return out
        end = dur - 0.3
        bars = [b for b in (inf.get("bars") or []) if off + avail * 0.6 <= b <= end]
        if bars and float(inf.get("conf", 0)) >= 0.3:
            end = bars[-1]
        ln = max(1.0, end - off)
        out.append({"path": a["path"], "t0": round(t, 3), "off": round(off, 3), "dur": dur, "len": round(ln, 3)})
        t = t + ln - min(xfade, ln / 2)
    return out


# ------------------------------------------------------------------ 컷 소리·장면(v0.16.66): 수면 위·말소리 = 원본 소리 키움
# 사용자 규칙: 말소리 → 키움 / 물속 호흡기 소리 → 안 키움(빨강이 많아도) / 둘 다 아니면 화면이 수면 위 → 키움 / 물속 → 안 키움.
ASR = 16000
HISS_MIN = 0.4                    # 호흡기 들숨 '쉬익' = 고음(2.5~7.5kHz) 잡음이 이만큼(초) 넘게 이어짐(말소리의 ㅅ·ㅆ 는 0.1~0.2초)
HISS_RISE = 6.0                   # 바탕 고음보다 이만큼(dB) 큼
HISS_FLAT = 0.35                  # 잡음 같음(스펙트럼 평탄도)
VOICED = (0.15, 0.80)             # 말소리: 목소리 떨림(80~400Hz 주기)이 있는 시간 비율
SWITCH = (2.5, 9.0)               # 말소리: 목소리가 켜졌다 꺼졌다 하는 횟수(초당, 음절)


def _cut_audio(path: str, t0: float, dur: float) -> np.ndarray:
    r = subprocess.run([paths.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", str(path), "-vn",
                        "-ac", "1", "-ar", str(ASR), "-f", "f32le", "-"],
                       capture_output=True, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    return np.frombuffer(r.stdout, np.float32).copy()


def sound_traits(y: np.ndarray) -> dict:
    """소리 → {"level" dB, "voiced" 목소리 비율, "switch" 초당 켜짐/꺼짐, "hiss" 긴 쉬익 수, "speech", "breath"}.
    실측(2026-11-12): 말소리(LibriSpeech 3개) 목소리 0.03~0.58 · 켜짐/꺼짐 1.9~7.3 · 쉬익 0 /
    물속 호흡기(Ace Pro 6초 구간 4개) 쉬익 1개씩(0.4~1.0초) · 목소리 0.09~0.53 · 켜짐/꺼짐 8~21 / 음악 쉬익 0."""
    hop, win = 256, 512                             # 16ms · 32ms
    n = (len(y) - win) // hop
    if n < 60:
        return {"level": -99.0, "voiced": 0.0, "switch": 0.0, "hiss": 0, "speech": False, "breath": False}
    level = float(20 * np.log10(np.sqrt((y ** 2).mean()) + 1e-9))
    idx = np.arange(n)[:, None] * hop + np.arange(win)[None, :]
    fr = y[idx] * np.hanning(win).astype(np.float32)
    S = np.abs(np.fft.rfft(fr, axis=1))
    f = np.fft.rfftfreq(win, 1 / ASR)
    e = 10 * np.log10((fr ** 2).mean(axis=1) + 1e-12)
    F = np.fft.rfft(fr, 2 * win, axis=1)
    ac = np.fft.irfft(np.abs(F) ** 2, axis=1)[:, :win]
    ac = ac / (ac[:, :1] + 1e-12)
    voiced = (ac[:, ASR // 400:ASR // 80].max(axis=1) > 0.5) & (e > np.percentile(e, 30))
    vf = float(voiced.mean())
    sw = float(np.abs(np.diff(voiced.astype(int))).sum() / (n * hop / ASR))
    hb = (f >= 2500) & (f < 7500)
    hi = 10 * np.log10((S[:, hb] ** 2).mean(axis=1) + 1e-12)
    flat = np.exp(np.log(S[:, hb] + 1e-9).mean(axis=1)) / (S[:, hb].mean(axis=1) + 1e-9)
    on = (hi > np.median(hi) + HISS_RISE) & (flat > HISS_FLAT)
    runs, k = [], 0
    for v in list(on) + [False]:
        if v:
            k += 1
        elif k:
            runs.append(k * hop / ASR)
            k = 0
    hiss = sum(1 for r in runs if r >= HISS_MIN)
    dur = n * hop / ASR
    breath = hiss >= 1 and (hiss >= 2 or dur < 8)          # 8초 넘는 컷 = 숨 2번 이상
    speech = level > -55 and VOICED[0] <= vf <= VOICED[1] and SWITCH[0] <= sw <= SWITCH[1] and hiss == 0
    return {"level": round(level, 1), "voiced": round(vf, 2), "switch": round(sw, 2), "hiss": hiss,
            "speech": bool(speech), "breath": bool(breath)}


def _look(path: str, t: float):
    """t 의 화면(320×180 RGB 0~1) 또는 None."""
    r = subprocess.run([paths.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-an", "-frames:v", "1",
                        "-vf", "scale=320:180,format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    if len(r.stdout) < 320 * 180 * 3:
        return None
    return np.frombuffer(r.stdout[:320 * 180 * 3], np.uint8).reshape(180, 320, 3).astype(np.float32) / 255.0


def above_water(a: np.ndarray) -> tuple[bool, float, float]:
    """수면 위(배·육상·물 밖) 화면인가 → (판단, 빨강/초록, 물색 면적). 물속 = 빨강이 적고 물색(파랑·청록)이 넓음."""
    y = a.mean(axis=2)
    lit = y >= np.percentile(y, 40)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    rg = float(r[lit].mean() / (g[lit].mean() + 1e-6))
    water = float(((b > r * 1.25) & (g > r * 1.1) & (a.max(axis=2) > 0.12)).mean())
    return bool(rg > 0.85 and water < 0.35), round(rg, 3), round(water, 3)


def cut_scene(src, seg) -> dict:
    """컷 1개 → {"up": 원본 키움?, "why": 말소리|호흡기|수면 위|물속, ...}. 소리가 화면보다 먼저(사용자)."""
    fps = float(src.fps)
    t0, t1 = seg.fin / fps, seg.fout / fps
    dur = max(0.1, t1 - t0)
    out = {}
    if getattr(src, "has_audio", True):
        tr = sound_traits(_cut_audio(src.path, t0, min(dur, 30.0)))
        out.update(tr)
        if tr["breath"]:                                   # 호흡기 소리 = 빨강이 많아도 안 키움(사용자)
            return {**out, "up": False, "why": "호흡기"}
        if tr["speech"]:
            return {**out, "up": True, "why": "말소리"}
    vid = src.proxy if getattr(src, "proxy", "") and Path(src.proxy).exists() else src.path
    looks = [above_water(a) for a in (_look(vid, t0 + dur * k) for k in (0.3, 0.7)) if a is not None]
    if not looks:
        return {**out, "up": False, "why": "물속"}
    up = sum(x[0] for x in looks) * 2 > len(looks)
    out.update(rg=looks[0][1], water=looks[0][2])
    return {**out, "up": bool(up), "why": "수면 위" if up else "물속"}


def loud_spans(segs, lens, plan_, ramp_ok=True) -> list[tuple[float, float]]:
    """원본을 키울 컷의 결과 영상 구간 [(시작, 끝)] — 전환 겹침 반영."""
    out, t = [], 0.0
    for i, (g, ln) in enumerate(zip(segs, lens)):
        if i > 0 and plan_[i]:
            t -= plan_[i][1]
        if seg_up(g):
            out.append((round(t, 4), round(t + ln, 4)))
        t += ln
    return out


def seg_up(seg) -> bool:
    """컷 원본 키움: 손으로 정함(aud = up | keep) 먼저, 아니면 자동 판단(loud)."""
    a = getattr(seg, "aud", "auto") or "auto"
    if a == "up":
        return True
    if a == "keep":
        return False
    return bool(getattr(seg, "loud", None))


def ramp_expr(spans, r: float = 0.5) -> str:
    """구간 안 = 1, 밖 = 0, 경계 앞뒤 r/2 에 걸쳐 직선으로(ffmpeg 식, t = 초)."""
    if not spans:
        return "0"
    parts = [f"clip(min((t-{a - r / 2:.4f})/{r},({b + r / 2:.4f}-t)/{r}),0,1)" for a, b in spans]
    e = parts[0]
    for p_ in parts[1:]:
        e = f"max({e},{p_})"
    return e


def plan_runs(audios: list[dict], infos: dict, runs: list, xfade: float = 2.0, video: float = 0.5,
              targets: dict | None = None) -> list[dict]:
    """장면별 곡(v0.16.68): runs = [(시작, 끝, 묶음)] → 묶음마다 맞는 곡(블루워터 = 웅장·신남, 얕은·산호 = 잔잔).
    구간 사이 = xfade 초 겹침(앞 곡 끝을 늘림), 다음 곡의 마디 첫 박이 구간 경계에 오게 둠. 바로 앞 곡은 되도록 안 겹침."""
    targets = targets or {}
    out, last = [], ""
    for k, (a, b, grp) in enumerate(runs):
        mt, gt = targets.get(grp, (None, None))
        if mt is None:
            mt = target_mood(video)
        lead_in = xfade / 2 if k > 0 else 0.0
        items = plan(audios, infos, (b - a) + lead_in, video, xfade, target=mt, grand_t=gt, avoid=last, bar_start=True)
        if not items:
            continue
        if out and lead_in:                                   # 앞 곡 끝을 늘려 겹침(곡이 모자라면 그만큼만)
            pv = out[-1]
            room = float(pv["dur"]) - float(pv["off"]) - float(pv["len"])
            pv["len"] = round(float(pv["len"]) + max(0.0, min(lead_in, room)), 3)
        for x in items:
            x["t0"] = round(float(x["t0"]) + a - lead_in, 3)
            if x is items[0] and lead_in:                     # 곡 첫 마디 첫 박이 경계(a)에: 곡 안 시작을 앞당겨 겹침 구간을 채움
                ob = float(x["off"])
                nb = max(0.0, ob - lead_in)
                x["off"], x["t0"] = round(nb, 3), round(a - (ob - nb), 3)
                x["len"] = round(float(x["len"]) - (lead_in - (ob - nb)), 3)
            out.append(x)
        last = items[-1]["path"]
    return out
