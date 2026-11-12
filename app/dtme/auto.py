"""자동 보정(추천 · AUTO): 샘플 추출 → 색 통계 → 장면·피사체 판단 → 값 계산 → (필요하면) 색 키프레임.

AI 가 아닌 색 통계 휴리스틱이다. 출발점 용도.
- 프리셋 6개: 라이트·산호·얕은 수심·깊은 수심·블루워터·야간. 산호는 따뜻한 색 면적으로 추정.
- 값 = 장면 프리셋 기준값 + 영상별 흰색(빨강·파랑)·명암(커브) 미세 조정.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import ff, paths
from .project import FACTORY_GRADE, Source

# ------------------------------------------------------------------ 프리셋 6개 (사용자 2026-11-06: 피사체 구분 없앰)
# 거북이·다이버·물고기는 색 통계로 구별 불가 + 값 차이가 작아 없앰. 산호 = 산호초(보통 라이트를 비춰 찍음)
SCENES = [("light", "라이트"), ("coral", "산호"), ("shallow", "얕은 수심"), ("deep", "깊은 수심"),
          ("bluewater", "블루워터"), ("night", "야간")]
SCENE_NAME = dict(SCENES)
STRENGTH = {"weak": 0.6, "mid": 1.0, "strong": 1.3}

SCENE_BASE = {
    # 실제 수중 샘플(2026-11-06, 보홀) 보고 조정. 원칙(사용자): 물속은 원래 파랗고 어느 정도 뿌연 것.
    # 원색(특히 빨강)을 되살리거나 그랑블루로 만들 필요 없음 — **색이 틀어지거나 노이즈가 나오지 않는 것이 먼저**.
    # 파란 물의 빨간 점·노이즈 = 빨강 게인·커브 늘이기·채도가 원인 → 셋 다 작게, 색 노이즈 제거는 강하게(60 이상 = 색 채널 미디언)
    # r/b = 고정 프리셋 게인, rmax = 빨강 최대, k = 영상별 흰색 맞춤 정도, ref = 흰색 기준(밝은 쪽 비율),
    # s = 커브 S 세기, lo = 검정점 배율, sh = 샤픈, wnr = 물 노이즈(파란 영역 붉은 노이즈 정리),
    # sd = 암부만 더 어둡게(깊은 수심·블루워터: “안 하면 물이 뿌옇게 보임” → v0.15.3 과 강조안의 중간)
    "light":     dict(r=1.05, b=1.00, rmax=1.15, k=0.25, ref=0.10, water=8, gy=25, sat=1.00, nrc=60, nrl=30, dehaze=0, s=0.04, lo=0.8, sh=0.15, wnr=30),
    "coral":     dict(r=1.05, b=1.00, rmax=1.12, k=0.20, ref=0.10, water=8, gy=25, sat=1.00, nrc=65, nrl=30, dehaze=0, s=0.04, lo=0.8, sh=0.15, wnr=45),
    "shallow":   dict(r=1.10, b=1.00, rmax=1.20, k=0.40, ref=0.30, water=8, gy=30, sat=1.00, nrc=60, nrl=30, dehaze=0, s=0.04, lo=0.8, sh=0.15, wnr=40),
    "deep":      dict(r=1.15, b=1.00, rmax=1.28, k=0.40, ref=0.50, water=8, gy=30, sat=1.00, nrc=65, nrl=35, dehaze=0, s=0.03, lo=0.75, sh=0.10, wnr=65, sd=0.035),
    "bluewater": dict(r=1.00, b=1.00, rmax=1.08, k=0.15, ref=0.30, water=12, gy=40, sat=1.00, nrc=65, nrl=30, dehaze=0, s=0.05, lo=0.975, sh=0.10, wnr=70, sd=0.04, lift=1),
    "night":     dict(r=1.00, b=1.00, rmax=1.10, k=0.25, ref=0.10, water=0, gy=20, sat=1.00, nrc=65, nrl=40, dehaze=0, s=0.04, lo=0.8, sh=0.10, wnr=50),
}


def normalize_key(key: str) -> str:
    """옛 프리셋 키(v0.15.0~0.15.3: 장면/피사체) → 6개 중 하나. '얕은 수심 · 산호초' → 산호, '깊은 수심 · 거북이' → 깊은 수심."""
    k = (key or "").strip()
    if k.startswith("scene:"):
        k = k[6:]
    sc, _, sb = k.partition("/")
    if sb == "coral":
        return "coral"
    return sc if sc in SCENE_NAME else ""


BASE_HUE, BASE_SAT = 5.0, 1.1      # 사용자 기본: 색조 +5, 채도 1.1 (장면별 채도는 이 값에서 더하고 뺌)
BLUE_FOLLOW = 0.9                  # 빨강을 올리면 파랑은 빨강의 0.9배 이상(물이 자주·회색으로 가지 않게)


def follow_blue(r: float, b: float) -> float:
    """파랑 ≥ 빨강 × 0.9 (자동 계산 값에만: AUTO·프리셋·흰색 찍기·색 균형. 슬라이더를 직접 움직이는 건 그대로)."""
    return max(float(b), round(BLUE_FOLLOW * float(r), 3))


def preset_keys() -> list[str]:
    """기본 프리셋 6개."""
    return [k for k, _ in SCENES]


def preset_label(key: str, short: bool = False) -> str:
    name = SCENE_NAME.get(normalize_key(key), "")
    return name.replace(" 수심", "") if short else name


def scene_params(scene: str, subject=None, strength: str = "mid") -> dict:
    b = dict(SCENE_BASE.get(normalize_key(scene) or "shallow"))
    b["st"] = STRENGTH.get(strength, 1.0)
    return b


def s_curve(lo: float, hi: float, s: float, min_range: float = 0.75, sd: float = 0.0) -> list:
    """명암: 암부 lo → 거의 0, 명부 hi → 거의 1, 사이는 S자(s). sd = 암부만 더 어둡게(깊은 수심·블루워터: 물이 뿌옇지 않게).
    포인트는 양 끝 포함 최대 7개(중간 5개)."""
    lo, hi = max(0.0, min(0.45, lo)), max(0.4, min(1.0, hi))
    if hi - lo < min_range:               # 너무 좁으면 늘이는 양 제한(노이즈가 커짐)
        c = min(1 - min_range / 2, max(min_range / 2, (lo + hi) / 2))
        lo, hi = c - min_range / 2, c + min_range / 2
    d = hi - lo
    pts = [[0.0, 0.0]]
    if lo > 0.02:
        pts.append([round(lo, 4), 0.012])
    pts.append([round(lo + 0.25 * d, 4), round(max(0.03, 0.25 - s - sd), 4)])
    pts.append([round(lo + 0.75 * d, 4), round(min(0.97, 0.75 + s), 4)])
    if hi < 0.98:
        pts.append([round(hi, 4), 0.985])
    pts.append([1.0, 1.0])
    return pts


# 블루워터 밝기 맞춤(v0.16.2): 디헤이즈(unsharp 10bit 치우침)가 올려 주던 밝기 ≈ +10/255 를 커브로.
# 사용자 실제 렌더 2개(디헤이즈 5 / 0, 같은 프레임)의 밝기 분포를 맞춘 곡선. 출력 밝기 x → y
LIFT = [(0.0, 0.0), (0.05, 0.07), (0.10, 0.121), (0.20, 0.235), (0.30, 0.335), (0.50, 0.551), (0.70, 0.759),
        (0.85, 0.90), (0.95, 0.969), (1.0, 1.0)]


def lift_curve(pts: list, k: float = 1.0) -> list:
    """커브의 출력(y)에 LIFT 를 덧씌움(new_y = LIFT(old_y)). 양 끝 0·1 은 그대로. k = 덧씌우는 정도(0 = 안 함)."""
    import numpy as np
    xs, ys = zip(*LIFT)
    return [[x, round(float(y + (np.interp(y, xs, ys) - y) * k), 4)] for x, y in pts]


def builtin_grade(key: str, base: dict | None = None, strength: str = "mid") -> dict:
    """기본 프리셋(고정값). base 의 LUT·샤픈·렌즈 등은 그대로."""
    p = scene_params(key, None, strength)
    st = p["st"]
    g = dict(base or FACTORY_GRADE)
    r = round(min(2.0, 1 + (p["r"] - 1) * st), 3)
    g.update(r_gain=r, b_gain=follow_blue(r, round(1 + (p["b"] - 1) * st, 3)), hue=BASE_HUE,
             sat=round(BASE_SAT + (p["sat"] - 1) * st, 3), water=int(round(p["water"] * st)), gy=int(round(min(100, p["gy"] * st))),
             nr_chroma=int(p["nrc"]), nr_luma=int(p["nrl"]), dehaze=0,
             curve=s_curve(0.04 * p.get("lo", 0.9) / 0.9, 0.95, p["s"] * st, sd=p.get("sd", 0) * st), stab=0, sharpen=p.get("sh", 0.15),
             wnr=int(p.get("wnr", 0)))
    if p.get("lift"):
        g["curve"] = lift_curve(g["curve"])
    return g


# ------------------------------------------------------------------ 샘플 추출
SAMPLE_W = 320
SAMPLE_EVERY_SEC = 2.0
SAMPLE_MAX = 12          # v0.16.17: 20 → 12 (분석 시간 ≈60%, 사용자 확정). v0.16.29 부터 + 맨 앞 1장


EARLY_SEC = (0.5, 1, 2, 3, 5)     # v0.16.34 시작 구간 샘플(초), v0.16.38 0.5초 추가(0~1초 사이 튐)
EARLY_WIN = 6.0                   # 이 초 안을 시작 구간으로 봄
CURVE_TOL = 0.04                  # 시작 구간 밝기 양끝이 뒤쪽과 이만큼 넘게 다르면 커브 ◆
CURVE_KEYS_MAX = 3                # 시작 구간 커브 ◆
CURVE_KEYS_ALL = 8                # v0.16.62 커브 ◆ 전체 상한(시작 구간 3 + 깊은 구간)
DEEP_RUN_MIN = 2                  # 깊은 수심으로 읽힌 샘플이 이만큼 이어져야 '깊은 구간'(1장 = 무시: 카메라가 잠깐 물 쪽을 봄·그림자)
COLOR_TOL = 0.095                 # v0.16.38 시작 구간 색(빨강/초록·파랑/초록 비, log) 이만큼(≈10%) 넘게 다르면 색 ◆
COLOR_R_MAX = 1.4                 # 시작 빨강 게인 = 자리 잡은 값의 최대 1.4배(v0.16.42: 1.8 → 1.4, 빨강 2.0 에서 붉은 노이즈가 보임)
COLOR_R_TOP = 1.6                 # 시작 빨강 게인 상한(예전 2.0)
START_SAT_DROP = 0.2              # 빨강을 최대 배율로 올린 ◆ 는 채도를 이만큼 낮춤(붉은 얼룩이 덜 보이게), 배율에 비례
START_GAMMA_MIN = 0.8             # 덜 올린 빨강만큼 어두운 시작 = 커브로 밝기 맞춤(출력 y^γ), 이보다 더 밝히지 않음(노이즈)
COLOR_B_RANGE = (0.7, 1.3)
START_B_TOP = 0.90                # v0.16.53 시작 파랑 ◆: 밝은 쪽 10% 의 파랑이 이 값을 넘지 않는 데까지만 올림(해·빛기둥 날림)
# v0.16.53 이미 진한 영상(카메라 비비드 등)은 덜 얹음: 밝은 곳 중 채도 0.9 넘는 면적(샘플 중앙값)이
# RICH_LO 이하 = 예전 그대로, RICH_HI 이상 = 채도 더하기·S커브·암부 누르기·밝기 덧씌움 없음(색 균형·검정/흰점만).
# 실측: Insta360 Ace Pro 2 vivid 0.226 / DJI D-Log M + LUT 는 AUTO 를 건 결과물에서도 0.00(3개 클립)
RICH_SAT, RICH_LO, RICH_HI = 0.9, 0.03, 0.15


def rich_area(a: np.ndarray) -> float:
    y = luma(a)
    lit = y > 0.06
    if lit.mean() < 0.02:
        return 0.0
    _h, s = hue_sat(a)
    return float((s[lit] > RICH_SAT).mean())


def rich_keep(samples: list) -> float:
    """1 = 예전대로 다 얹음 … 0 = 이미 진함(채도·대비를 더 얹지 않음)."""
    if not samples:
        return 1.0
    f = float(np.median([rich_area(a) for _f, a in samples]))
    return float(np.clip((RICH_HI - f) / (RICH_HI - RICH_LO), 0.0, 1.0))


def sample_frames(src: Source, every: float = SAMPLE_EVERY_SEC, n_max: int = SAMPLE_MAX,
                  a: int | None = None, b: int | None = None) -> list[int]:
    """구간 [a, b) 에서 every 초마다 1장(최대 n_max, 넘으면 고르게). 가운데 정렬.
    v0.16.29: 맨 앞(인점)에도 1장 → ◆ 첫 키 = 인점(녹화 시작 직후 카메라 색이 바뀌는 구간도 따라감, 사용자).
    v0.16.30: 첫 샘플이 인점에서 1초 안이면 그 샘플 대신 인점(사용자)."""
    a = 0 if a is None else a
    b = src.frames if b is None else b
    n = max(1, min(n_max, int((b - a) / float(src.fps) / every)))
    fr = [int(a + (k + 0.5) * (b - a) / n) for k in range(n)]
    if fr[0] - a < float(src.fps) * 1.0:          # v0.16.30: 첫 샘플이 인점에서 1초 안 = 인점으로 바꿈(가까운 두 장 대신 한 장)
        fr[0] = int(a)
    else:                                         # 1초 이상 뒤 = 인점을 맨 앞에 더함
        fr.insert(0, int(a))
    fps = float(src.fps)                          # v0.16.34: 시작 구간(카메라가 밝기를 잡는 동안) 1·2·3·5초 더
    for t in EARLY_SEC:
        f = int(a + t * fps)
        if f < b - 1 and all(abs(f - x) > fps * 0.4 for x in fr):
            fr.append(f)
    return sorted(fr)


def grab_small(src: Source, frame: int, lut: str, gpu: bool = False, w: int = SAMPLE_W,
               use_preview: bool = False) -> np.ndarray:
    """원본 1장 → (LUT 만 입혀) 작은 RGB float 배열(0~1).
    use_preview(AUTO 분석, v0.16.22) = 판정 통과한 카메라 프리뷰(LRF 등, 폭 640 이상)가 있으면 그 같은 화면에서
    (프리뷰가 이미 709 면 LUT 없이). 실물 DJI: 결과 거의 같음(빨강 1.02 vs 1.022), 시간 약 1/7."""
    path, seek, use_lut = src.path, ff._seek(frame, src.fps), lut
    if use_preview:
        try:
            pv = ff.preview_for_analysis(src, lut)      # v0.16.24: 시점 판정 안 기다림(색만)
        except Exception:  # noqa: BLE001
            pv = None
        if pv and pv.get("w", 0) >= ff.PREVIEW_MIN_W_AUTO:
            path, seek = pv["path"], ff._seek(ff.preview_pos(pv, frame), ff.preview_fps(pv))
            use_lut = lut if pv.get("color") == "lut" else ""
    ref = ff.lut_ref(use_lut) if use_lut else None
    vf = [f"scale={w}:-2:flags=bilinear", "format=gbrp16le"]
    if ref:
        vf.append(f"lut3d=file={ref[1]}:interp=tetrahedral")
    vf.append("format=rgb24")
    cmd = [paths.ffmpeg(), "-v", "error", "-ss", seek, "-i", ff._abs(path),        # v0.16.24: 1장 = CPU(gpu 무시)
           "-frames:v", "1", "-an", "-vf", ",".join(vf), "-f", "rawvideo", "-"]
    try:
        raw = ff.run(cmd, cwd=ref[0] if ref else None)
    except ff.FFError:
        # GPU 실패 또는 일시적 실패(다른 작업과 겹침) → CPU 로 잠시 뒤 한 번 더
        import time
        time.sleep(0.3)
        raw = ff.run([c for c in cmd if c not in ("-hwaccel", "cuda")], cwd=ref[0] if ref else None)
    h = len(raw) // (w * 3)
    return np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3).astype(np.float32) / 255.0


def grab_samples_preview(src: Source, lut: str, pv: dict, frames: list[int]) -> list[tuple[int, np.ndarray]] | None:
    """v0.16.24: 프리뷰(LRF)를 ffmpeg 한 번으로 — 구간만 읽고 기준 프레임(키프레임)만 디코딩 → 샘플마다 가장 가까운 것.
    이전(장마다 ffmpeg 1번·정확한 위치) 대비 이 환경 3.4 → 0.2초, HDD 에서 파일 열기·건너뛰기가 12번 → 1번.
    한계: 샘플 위치가 가장 가까운 기준 프레임(DJI LRF ≈1초 간격 → 최대 ≈0.5초 차). 기준 프레임이 없으면 None."""
    import re
    if not frames:
        return []
    sfps = float(src.fps)
    t_a = max(0.0, min(frames) / sfps - 2.0)
    t_b = max(frames) / sfps + 2.0
    ref = ff.lut_ref(lut) if (lut and pv.get("color") == "lut") else None
    vf = ["showinfo", f"scale={SAMPLE_W}:-2:flags=bilinear", "format=gbrp16le"]
    if ref:
        vf.append(f"lut3d=file={ref[1]}:interp=tetrahedral")
    vf.append("format=rgb24")
    cmd = [paths.ffmpeg(), "-hide_banner", "-v", "info", "-skip_frame", "nokey", "-ss", f"{t_a:.3f}", "-to", f"{t_b:.3f}",
           "-copyts", "-i", ff._abs(pv["path"]), "-an", "-vf", ",".join(vf), "-fps_mode", "passthrough",
           "-f", "rawvideo", "-"]
    with ff._slots(cmd):
        pr = ff._popen(cmd, cwd=ref[0] if ref else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw, err = pr.communicate()
    if pr.returncode != 0:
        if ff._closing.is_set():
            raise ff.Cancelled()
        raise ff.FFError(err.decode("utf-8", "replace")[-300:])
    ts = [float(x) for x in re.findall(rb"pts_time:\s*([-0-9.]+)", err)]
    w = SAMPLE_W
    h = int(round(w * pv["h"] / pv["w"] / 2)) * 2
    n = min(len(ts), len(raw) // (w * h * 3))
    if n == 0:
        return None
    imgs = np.frombuffer(raw[:n * w * h * 3], np.uint8).reshape(n, h, w, 3)
    out = []
    for f in frames:
        t = f / sfps
        k = min(range(n), key=lambda i: abs(ts[i] - t))
        out.append((f, imgs[k].astype(np.float32) / 255.0))
    return out


def grab_samples(src: Source, lut: str, gpu: bool = False, frames: list[int] | None = None,
                 cancel=None, on_progress=None, use_preview: bool = True) -> list[tuple[int, np.ndarray]]:
    """AUTO 분석 샘플. use_preview = 카메라 프리뷰가 맞으면 그걸로(한 번에), 아니면 원본에서 장마다.
    걸린 시간·자리 대기를 cache/dtme.log 에(v0.16.24)."""
    import time
    t0, w0 = time.monotonic(), ff.waited()
    if on_progress:
        on_progress(0.01)                        # 실제로 시작함(대기열에서는 '분석 대기')
    frames = frames if frames is not None else sample_frames(src, a=src.io[0], b=src.io[1])
    how, out = "원본", None
    if use_preview:
        try:
            pv = ff.preview_for_analysis(src, lut)
            if pv and pv.get("w", 0) >= ff.PREVIEW_MIN_W_AUTO:
                out = grab_samples_preview(src, lut, pv, frames)
                how = f"프리뷰({Path(pv['path']).suffix[1:].upper()}, 색 {pv.get('why') or '확인'})"
        except ff.Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            ff.log_error("분석 프리뷰 실패 → 원본", f"{Path(src.path).name}: {str(e)[-200:]}")
            out = None
    if out is None:
        how, out = "원본", []
        for i, f in enumerate(frames):
            if cancel is not None and cancel.is_set():
                raise ff.Cancelled()
            out.append((f, grab_small(src, f, lut, gpu, use_preview=False)))
            if on_progress:
                on_progress((i + 1) / len(frames))
    if on_progress:
        on_progress(1.0)
    ff.log_info(f"분석 샘플 {Path(src.path).name}: {how} {len(out)}장 {time.monotonic() - t0:.1f}초 "
                f"(자리 대기 {ff.waited() - w0:.1f}초)")
    return out


# ------------------------------------------------------------------ 색 통계
def luma(a: np.ndarray) -> np.ndarray:
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def hue_sat(a: np.ndarray):
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn + 1e-6
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    return h, d / (mx + 1e-6)


def stats(a: np.ndarray) -> dict:
    """LUT 만 입힌 작은 화면 1장의 통계."""
    y = luma(a)
    flat, yf = a.reshape(-1, 3), y.reshape(-1)
    lit = yf > 0.06
    sel = flat[lit] if lit.mean() > 0.02 else flat
    mean = sel.mean(0) + 1e-4
    order = np.argsort(yf)
    top10 = flat[order[-max(1, len(order) // 10):]].mean(0) + 1e-4
    top30 = flat[order[-max(1, len(order) * 3 // 10):]].mean(0) + 1e-4
    top50 = flat[order[-max(1, len(order) // 2):]].mean(0) + 1e-4
    darkhalf = flat[order[:len(order) // 2]].mean(0) + 1e-4
    h, s = hue_sat(a)
    water = ((h >= 170) & (h <= 250) & (s > 0.2)).mean()
    hh, ww = y.shape
    c = y[hh // 4: hh * 3 // 4, ww // 4: ww * 3 // 4].mean()
    edge = (y.sum() - y[hh // 4: hh * 3 // 4, ww // 4: ww * 3 // 4].sum()) / max(1, y.size - (hh // 2) * (ww // 2))
    return {
        "rg": float(mean[0] / mean[1]), "bg": float(mean[2] / mean[1]),
        "rg_top": float(top10[0] / top10[1]), "rg_dark": float(darkhalf[0] / darkhalf[1]),
        "top10": top10.tolist(), "top30": top30.tolist(), "top50": top50.tolist(), "mean": mean.tolist(),
        "p2": float(np.percentile(yf, 2)), "p50": float(np.percentile(yf, 50)), "p98": float(np.percentile(yf, 98)),
        "dark": float((yf < 0.06).mean()), "water": float(water), "ystd": float(yf.std()),
        "tex": float(np.abs(np.diff(y, axis=0)).mean() + np.abs(np.diff(y, axis=1)).mean()),
        "center": float(c), "edge": float(edge),
    }


def warm_fraction(a: np.ndarray, r_gain: float, b_gain: float) -> float:
    """게인 적용 후 따뜻한 색(빨강·주황·분홍) 면적 → 산호초 추정."""
    g = np.clip(a * np.array([r_gain, 1.0, b_gain], np.float32), 0, 1)
    h, s = hue_sat(g)
    y = luma(g)
    return float((((h < 40) | (h > 320)) & (s > 0.3) & (y > 0.12)).mean())


def classify(st_list: list[dict]) -> str:
    """장면: night / light / bluewater / shallow / deep (샘플 통계 중앙값)."""
    med = {k: float(np.median([s[k] for s in st_list])) for k in ("rg", "rg_top", "rg_dark", "p50", "dark", "water",
                                                                   "ystd", "tex", "center", "edge")}
    lighted = med["rg_top"] > 0.75 and med["rg_top"] > med["rg_dark"] * 1.6
    if med["p50"] < 0.10 and med["dark"] > 0.5:
        return "night"
    if lighted and med["center"] > med["edge"] * 1.3:
        return "light"
    if med["water"] > 0.75 and med["tex"] < 0.02:       # 화면 대부분 물, 무늬(바닥·산호) 거의 없음
        return "bluewater"
    return "shallow" if med["rg"] > 0.55 else "deep"


# ------------------------------------------------------------------ 값 계산
# v0.16.60 = P2 로 바꿈: DJI 원본이 아닌 영상 = 색조 0 · 물빛 0 만(파랑·나머지는 예전 그대로). 아래 측정 함수(water_angle · measured_water ·
# gains_for(follow=False))는 남겨 두되 AUTO 는 안 씀 — v0.16.56~59 의 ⑥(파랑 잰 값 · 물빛 측정)은 암부 파랑이 빠져 사용자가 되돌림.
# (기록) v0.16.56 DJI 원본(D-Log M + LUT)이 아닌 영상 = 보라로 덜 돌게 화면을 재서(사용자 비교 사진 ⑥):
# 색조 0 · 파랑은 빨강을 따라 올리지 않음(잰 값) · 물빛 = 물 색상각이 WATER_GOAL 에 못 미치는 만큼(0~WATER_CAP).
# 근거: Ace Pro 일반 색 1클립(BJVS3373) — 프리셋 고정값(색조 +5 · 물빛 +8 · 파랑 ≥ 빨강×0.9)이면 물 +14~19°, 흰 모래가 연보라.
WATER_GOAL = 209.0                # BJVS3373(자리 잡은 뒤 · 게인 뒤 물 색상각 중앙값 198.7°)에서 물빛 +16 이 나오는 값(사용자 ⑥). 이보다 파란 물 = 물빛 0
WATER_PER_DEG = 0.65              # 물빛 1 = 물 색상각 약 0.65°(v0.16.45 실측)
WATER_CAP = 20


def is_dji_log(src, lut: str = "") -> bool:
    """예전 값 그대로 쓸 클립: DJI D-Log M + LUT 로 확인됨(옛 프로젝트 = 색 모드 기록 없음 → 예전 그대로)."""
    mode = getattr(src, "lut_mode", "") if src is not None else ""
    return mode == "" or (mode == "dlog" and bool(lut))


def water_angle(a: np.ndarray, r: float = 1.0, b: float = 1.0):
    """물(파랑이 빨강보다 뚜렷이 센 곳)의 색상각 중앙값(°, 클수록 보라 쪽). 물이 화면의 3% 안 되면 None."""
    a = np.clip(a * np.array([r, 1.0, b], np.float32), 0, 1)
    rr, gg, bb = a[..., 0], a[..., 1], a[..., 2]
    w = (bb > rr * 1.25) & (a.max(-1) > 0.15)
    if w.mean() < 0.03:
        return None
    hue = np.degrees(np.arctan2(np.sqrt(3) * (gg - bb), 2 * rr - gg - bb)) % 360
    return float(np.median(hue[w]))


def measured_water(samples, gains) -> int | None:
    """물빛 = 목표에 못 미치는 만큼(0~WATER_CAP). 물이 안 보이면 None(프리셋 값 그대로)."""
    hs = [water_angle(a, r, b) for (_f, a), (r, b) in zip(samples, gains)]
    hs = [h for h in hs if h is not None]
    if not hs:
        return None
    return int(round(float(np.clip((WATER_GOAL - float(np.median(hs))) / WATER_PER_DEG, 0, WATER_CAP))))


def gains_for(st: dict, p: dict, follow: bool = True) -> tuple[float, float]:
    """흰색 기준(밝은 쪽 ref 비율 평균)을 초록에 맞추는 정도 k·강도 → 빨강·파랑. 파랑은 절반만(물빛 짙은 파랑 유지)."""
    key = "top10" if p["ref"] <= 0.1 else "top30" if p["ref"] <= 0.3 else "top50"
    r, g, b = st[key]
    k = p["k"] * p["st"]
    rg = 1 + k * (g / r - 1)
    bg = (1 + 0.5 * k * (g / b - 1)) * (1 + (p["b"] - 1) * p["st"])
    # 프리셋 값 주변으로만(물속은 빨강을 줄이지 않음, 물만 보이는 화면에서 회색으로 가지 않게)
    pr, pb = min(2.0, 1 + (p["r"] - 1) * p["st"]), 1 + (p["b"] - 1) * p["st"]
    rmax = min(2.0, 1 + (p["rmax"] - 1) * p["st"])
    r = float(np.clip(rg, max(1.0, pr - 0.15), min(rmax, pr + 0.15)))
    bq = float(np.clip(bg, pb - 0.05, pb + 0.05))
    return r, (follow_blue(r, bq) if follow else bq)


def tone_ends(a: np.ndarray) -> tuple[float, float]:
    """커브(모든 채널에 같이 걸림)의 검정·흰색 기준: 픽셀마다 가장 약한 채널의 2% / 가장 센 채널의 98%.
    밝기(Y) 기준이면 물속에서 약한 빨강이 검정으로 뭉개짐(실측)."""
    return float(np.percentile(a.min(-1), 2)), float(np.percentile(a.max(-1), 98))


def tone_for(samples: list[tuple[int, np.ndarray]], gains: list[tuple[float, float]]) -> tuple[float, float]:
    """게인 적용 후 밝기 p2/p98. 커브는 클립 전체 1개라 가장 어두운/밝은 샘플 기준(한 구간이 뭉개지지 않게)."""
    lo, hi = [], []
    for (_f, a), (r, b) in zip(samples, gains):
        lo_, hi_ = tone_ends(np.clip(a * np.array([r, 1.0, b], np.float32), 0, 1))
        lo.append(lo_)
        hi.append(hi_)
    return float(np.min(lo)), float(np.max(hi))


def pick_keys(frames: list[int], vals: list[float], tol: float, n_max: int = 6) -> list[int]:
    """키프레임 위치 고르기(양 끝 + 보간 오차가 가장 큰 곳을 차례로, 최대 n_max)."""
    from .project import key_at
    idx = [0, len(frames) - 1] if len(frames) > 1 else [0]
    while len(idx) < n_max:
        ks = [{"f": frames[i], "v": vals[i]} for i in sorted(idx)]
        err = [abs(key_at(ks, f) - v) for f, v in zip(frames, vals)]
        j = int(np.argmax(err))
        if err[j] <= tol:
            break
        idx.append(j)
    return sorted(set(idx))


def _med3(v: list[float]) -> list[float]:
    if len(v) < 3:
        return list(v)
    return [v[0]] + [float(np.median(v[i - 1:i + 2])) for i in range(1, len(v) - 1)] + [v[-1]]


KEY_TOL_R, KEY_TOL_B = 0.08, 0.05       # 이보다 크게 변하면 키프레임(빨강을 조금만 쓰는 값에 맞춤)


def settle_index(frames: list[int], ends: list[tuple[float, float]], fps: float | None, tol: float = CURVE_TOL) -> int:
    """시작 구간(인점~EARLY_WIN초)에서 밝기 양끝(p2/p98)이 뒤쪽 중앙값과 CURVE_TOL 안으로 들어온 첫 샘플 번호.
    0 = 처음부터 안정(커브 ◆ 없음). 뒤쪽 샘플이 없거나 fps 모름 = 0."""
    if not fps or len(frames) < 3:
        return 0
    early = [i for i, f in enumerate(frames) if f - frames[0] <= EARLY_WIN * fps]
    late = [i for i in range(len(frames)) if i not in early][:3]     # 기준 = 시작 구간 바로 뒤 3장
    if not late or len(early) < 2:
        return 0
    for k in (0, 1):            # 기준 샘플끼리 다르면(장면이 바뀌는 중) 판단 안 함 — 장면 변화를 카메라 적응으로 오인 방지
        v = [ends[i][k] for i in late]
        if max(v) - min(v) > 2 * tol:
            return 0
    rl = float(np.median([ends[i][0] for i in late]))
    rh = float(np.median([ends[i][1] for i in late]))
    off = [abs(ends[i][0] - rl) > tol or abs(ends[i][1] - rh) > tol for i in early]
    if not any(off):
        return 0
    last = max(k for k, o in enumerate(off) if o)
    return early[last + 1] if last + 1 < len(early) else late[0]


def _start_color_keys(gkeys: dict, frames: list[int], sts: list[dict], g: dict, fps: float | None) -> int:
    """v0.16.38 시작 구간 색 ◆: 카메라 화이트밸런스가 자리 잡는 동안(빨강이 점점 늘어남) 빨강·파랑 ◆ 최대 3개
    (인점 · 가운데 1 · 자리 잡은 지점). 값 = 자리 잡은 지점 게인 × (자리 잡은 색 비 / 그 샘플 색 비), 빨강 최대 1.8배·2.0,
    파랑 0.7~1.3배. 자리 잡은 지점 앞의 기존 빨강·파랑 ◆는 이것으로 바꿈, 뒤는 그대로."""
    from .project import key_at
    lv = [(float(np.log(max(1e-4, x["rg"]))), float(np.log(max(1e-4, x["bg"])))) for x in sts]
    si = settle_index(frames, lv, fps, COLOR_TOL)
    if si <= 0:
        return 0
    fs = frames[si]
    rk, bk = gkeys.get("r_gain"), gkeys.get("b_gain")
    r_s = key_at(rk, fs) if rk else float(g["r_gain"])
    b_s = key_at(bk, fs) if bk else float(g["b_gain"])
    idx = [0]
    if si >= 2:                      # 직선(log)에서 가장 벗어난 가운데 1장
        def dev(i):
            t = (frames[i] - frames[0]) / max(1, fs - frames[0])
            return max(abs(lv[i][k] - (lv[0][k] + (lv[si][k] - lv[0][k]) * t)) for k in (0, 1))
        j = max(range(1, si), key=dev)
        if dev(j) > COLOR_TOL:
            idx.append(j)

    def rv(i):
        k = float(np.exp(lv[si][0] - lv[i][0]))
        return round(min(max(COLOR_R_TOP, r_s), r_s * min(COLOR_R_MAX, max(1 / COLOR_R_MAX, k))), 3)

    def bv(i):
        k = float(np.exp(lv[si][1] - lv[i][1]))
        v = max(0.5, min(1.5, b_s * min(COLOR_B_RANGE[1], max(COLOR_B_RANGE[0], k))))
        top = max(b_s, START_B_TOP / max(1e-3, sts[i]["top10"][2]))      # 밝은 쪽 파랑이 날아가지 않는 데까지만
        return round(min(v, top), 3)
    for key, fn, cur, val_s in (("r_gain", rv, rk, r_s), ("b_gain", bv, bk, b_s)):
        keep = [x for x in (cur or []) if x["f"] > fs]
        new = [{"f": frames[i], "v": fn(i)} for i in idx] + [{"f": fs, "v": round(val_s, 3)}]
        gkeys[key] = new + keep
    # v0.16.42 채도 ◆: 빨강을 올린 만큼 채도를 낮춤(자리 잡은 지점 = 클립 채도). 기존 채도 ◆ 가 있으면 건드리지 않음
    if not gkeys.get("sat") and r_s > 0:
        sat_s = float(g.get("sat", 1.0))
        sk = [{"f": frames[i], "v": round(sat_s - START_SAT_DROP * max(0.0, min(1.0, (rv(i) / r_s - 1) / (COLOR_R_MAX - 1))), 3)}
              for i in idx]
        if any(sat_s - k["v"] > 0.02 for k in sk):
            gkeys["sat"] = sk + [{"f": fs, "v": round(sat_s, 3)}]
    # 물빛 ◆(v0.16.45)·색조 ◆(v0.16.46)는 뺌(v0.16.47, 사용자: 돌릴수록 맨 앞 노이즈·보라 얼룩 — 시작의 약한 녹색은 그대로 둠)
    return si


def _lit_luma(a: np.ndarray, r: float, b: float, curve: list) -> float:
    """게인 + 커브 뒤 밝기 중앙값."""
    from .project import spline_eval
    xs = np.linspace(0, 1, 256)
    lut = np.array(spline_eval(curve, xs.tolist()), np.float32)
    x = np.clip(a * np.array([r, 1.0, b], np.float32), 0, 1)
    return float(np.median(luma(np.interp(x, xs, lut))))


def _start_luma_keys(gkeys: dict, samples: list, si: int, g: dict) -> None:
    """v0.16.42 시작 구간 밝기(사용자 '커브로 명도 조절'): 빨강을 덜 올린 만큼 시작이 어두움 → 시작 ◆ 위치마다
    (게인 + 커브 뒤) 밝기 중앙값을 자리 잡은 지점에 맞추는 γ(출력 y^γ, START_GAMMA_MIN~1 = 밝히는 쪽만)를 커브 ◆ 에 넣음.
    커브 ◆ 가 없으면 색 ◆ 위치에 만듦. 자리 잡은 지점 뒤 커브 ◆ 는 그대로."""
    from .project import CURVE_KEY, curve_at, key_at
    by = {f: a for f, a in samples}
    fs = samples[si][0]
    val = lambda k, f: key_at(gkeys.get(k) or [], f) or float(g[k])     # noqa: E731
    cur = gkeys.get(CURVE_KEY) or []
    target = _lit_luma(by[fs], val("r_gain", fs), val("b_gain", fs), curve_at(cur, fs) or g["curve"])
    at = sorted({k["f"] for k in gkeys.get("r_gain", []) if k["f"] < fs} | {k["f"] for k in cur if k["f"] < fs})
    new = []
    for f in at:
        if f not in by:
            continue
        c = curve_at(cur, f) or [list(q) for q in g["curve"]]
        now = _lit_luma(by[f], val("r_gain", f), val("b_gain", f), c)
        gm = 1.0
        if 0.01 < now < target < 0.99:
            gm = max(START_GAMMA_MIN, float(np.log(target) / np.log(now)))
        new.append({"f": f, "v": [[x, round(float(y) ** gm, 4)] for x, y in c] if gm < 0.985 else c})
    if not new or all(k["v"] == (curve_at(cur, k["f"]) or g["curve"]) for k in new) and not cur:
        return
    tail = [k for k in cur if k["f"] >= fs] or [{"f": fs, "v": [list(q) for q in g["curve"]]}]
    gkeys[CURVE_KEY] = new + tail


def deep_runs(flags: list[bool], start: int = 0, n_min: int = DEEP_RUN_MIN) -> list[tuple[int, int]]:
    """True 가 n_min 장 이상 이어진 구간들 [(처음, 끝)] — start 앞(시작 구간)은 안 봄."""
    out, i, n = [], max(0, start), len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j + 1 < n and flags[j + 1]:
                j += 1
            if j - i + 1 >= n_min:
                out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def recommend(samples: list[tuple[int, np.ndarray]], base: dict, scene: str | None = None, subject: str | None = None,
              strength: str = "mid", fps: float | None = None, measure: bool = False) -> dict:
    """샘플 → {"grade": 클립 값(전체), "gkeys": 색 키프레임 또는 {}, "scene", "subject", "preset"}"""
    sts = [stats(a) for _f, a in samples]
    scene = normalize_key(scene or "")
    sc = scene or classify(sts)
    if not scene and sc in ("light", "shallow", "deep"):      # 산호 = 게인 후 따뜻한 색(빨강·주황·분홍) 면적 8% 넘음
        p0 = scene_params(sc, None, strength)
        g0 = [gains_for(s_, p0) for s_ in sts]
        warm = float(np.median([warm_fraction(a_, r, b_) for (_f, a_), (r, b_) in zip(samples, g0)]))
        if warm > 0.08:
            sc = "coral"
    sb = ""
    p = scene_params(sc, None, strength)
    gains = [gains_for(s, p) for s in sts]        # 커브·시작 구간 판단 = 늘 예전 방식 게인으로(측정 쪽도 밝기 처리는 같게)
    gout = gains                                  # v0.16.60(P2): 파랑은 예전대로(빨강 따라 올림) — 안 올리면 암부 파랑이 빠져 암부가 평평해 보임(사용자)
    frames = [f for f, _a in samples]
    ends = [tone_ends(np.clip(a * np.array([r, 1.0, b], np.float32), 0, 1)) for (_f, a), (r, b) in zip(samples, gains)]
    si = settle_index(frames, ends, fps)          # v0.16.34: 시작 구간이 안정되기 전 샘플은 클립 커브 계산에서 뺌
    dflag = [classify([x]) == "deep" for x in sts] if sc != "deep" else [False] * len(sts)
    use = [i for i in range(si, len(samples)) if not dflag[i]] or list(range(si, len(samples)))   # 클립 커브 양끝 = 깊어 보이는 샘플 빼고
    lo, hi = tone_for([samples[i] for i in use], [gains[i] for i in use])
    # v0.16.62: 깊은 구간이 섞인 클립 = 그 구간에만 약한 커브(커브 ◆). 예전 = 샘플 1장만 깊어 보여도 클립 전체를 깊은 곳 기준으로
    # (S ×0.45 · 검정점 배율) → 인/아웃을 조금 바꾸면 대비가 뛰었음(사용자: '그 구간에서만 장면이 바뀌는 것 아닌가').
    # 깊은 구간 = 자리 잡은 뒤 샘플에서 '깊은 수심'이 DEEP_RUN_MIN 장 이상 이어진 곳. 1장뿐 = 무시.
    runs = deep_runs(dflag, si)
    pd = p                                        # 클립 커브 = 그 장면 기준 그대로
    dp = SCENE_BASE["deep"]
    lo *= pd.get("lo", 0.9)
    keep = rich_keep(samples)                     # v0.16.53: 이미 진한 영상이면 채도·대비를 덜 얹음(0 = 안 얹음)
    s_amt = p["s"] * keep
    st = p["st"]
    sd = p.get("sd", 0) * st * keep
    g = builtin_grade(sc, base, strength)
    g["sat"] = round(1 + (float(g["sat"]) - 1) * keep, 3) if g["sat"] > 1 else g["sat"]
    rs, bs = _med3([x[0] for x in gout]), _med3([x[1] for x in gout])
    g.update(r_gain=round(float(np.median(rs)), 3), b_gain=round(float(np.median(bs)), 3),
             curve=s_curve(lo - 0.01, hi + 0.01, s_amt * st, sd=sd))
    if p.get("lift"):
        g["curve"] = lift_curve(g["curve"], keep)
    if measure:                                   # v0.16.60(사용자 P2) DJI 원본이 아님 = 색조 0 · 물빛 0(보라만 조금 뺌). 나머지는 예전과 같음
        g["hue"] = 0.0
        g["water"] = 0

    def mk(lo_, hi_):
        c = s_curve(lo_ * pd.get("lo", 0.9) - 0.01, hi_ + 0.01, s_amt * st, sd=sd)
        return lift_curve(c, keep) if p.get("lift") else c

    gkeys = {}
    if len(frames) >= 2 and (max(rs) - min(rs) > KEY_TOL_R or max(bs) - min(bs) > KEY_TOL_B):
        idx = sorted(set(pick_keys(frames, rs, KEY_TOL_R / 3)) | set(pick_keys(frames, bs, KEY_TOL_B / 3)))
        if len(idx) > 6:      # 두 값의 키 위치를 합쳐 6개 넘으면 고르게 줄임
            idx = [idx[int(round(i * (len(idx) - 1) / 5))] for i in range(6)]
        gkeys = {"r_gain": [{"f": frames[i], "v": round(rs[i], 3)} for i in idx],
                 "b_gain": [{"f": frames[i], "v": round(bs[i], 3)} for i in idx]}
    csi = _start_color_keys(gkeys, frames, sts, g, fps)
    if si > 0:          # v0.16.34 커브 ◆: 인점 · (가운데 1개) · 안정 지점(= 클립 커브), 최대 3개. 뒤는 클립 커브 그대로
        ck = [0]
        if si >= 2 and CURVE_KEYS_MAX >= 3:
            def dev(i):
                t = (frames[i] - frames[0]) / max(1, frames[si] - frames[0])
                return max(abs(ends[i][k] - (ends[0][k] + (ends[si][k] - ends[0][k]) * t)) for k in (0, 1))
            j = max(range(1, si), key=dev)
            if dev(j) > CURVE_TOL:
                ck.append(j)
        gkeys["curve"] = [{"f": frames[i], "v": mk(*ends[i])} for i in ck] + [{"f": frames[si], "v": g["curve"]}]
    if runs:            # 깊은 구간 커브 ◆: 구간 앞 샘플 = 클립 커브 → 구간 처음·끝 = 깊은 곳 커브(예전 '섞임' 커브) → 구간 뒤 샘플 = 클립 커브
        keys = {k["f"]: k["v"] for k in gkeys.get("curve", [])}
        clip_c = [list(q) for q in g["curve"]]
        deep_ids = set()
        for a, b in sorted(runs, key=lambda r: r[0] - r[1]):          # 긴 구간부터
            dlo, dhi = tone_for(samples[a:b + 1], gains[a:b + 1])     # 그 구간의 양끝으로
            deep_c = s_curve(dlo * dp.get("lo", 0.9) - 0.01, dhi + 0.01, min(p["s"], dp["s"]) * 0.6 * keep * st, sd=sd)
            if p.get("lift"):
                deep_c = lift_curve(deep_c, keep)
            add = {frames[a]: deep_c, frames[b]: deep_c}
            if a - 1 >= si:
                add[frames[a - 1]] = keys.get(frames[a - 1], clip_c) if a - 1 == si else clip_c
            if b + 1 < len(frames):
                add[frames[b + 1]] = clip_c
            if len(set(keys) | set(add)) > CURVE_KEYS_ALL:
                continue
            for f_, v_ in add.items():
                if f_ in (frames[a], frames[b]) or f_ not in keys:
                    keys[f_] = v_
            deep_ids.add(id(deep_c))
        if deep_ids:
            gkeys["curve"] = [{"f": f_, "v": [list(q) for q in keys[f_]]} for f_ in sorted(keys)]
    if csi > 0:
        _start_luma_keys(gkeys, samples, csi, g)
    return {"grade": g, "gkeys": gkeys, "scene": sc, "subject": sb, "preset": sc, "rich": round(1 - keep, 2), "measured": bool(measure)}


def analyze_source(src: Source, base: dict, scene=None, subject=None, strength="mid", gpu=False,
                   cancel=None, on_progress=None) -> dict:
    samples = grab_samples(src, base.get("lut", ""), gpu, cancel=cancel, on_progress=on_progress)
    return recommend(samples, base, scene, subject, strength, fps=float(src.fps), measure=not is_dji_log(src, base.get("lut", "")))


# ------------------------------------------------------------------ RGB 그래프 도움: 한 번에 맞추기 (현재 화면 1장)
def contrast_fix(a: np.ndarray, s: float = 0.06) -> list:
    """[명암] 보정 끝난 화면(커브 없이)의 양끝을 목표선(5%·95%)에 맞추는 커브."""
    lo, hi = tone_ends(a)
    return s_curve(lo - 0.01, hi + 0.01, s, min_range=0.2)


def balance_fix(a: np.ndarray) -> tuple[float, float]:
    """[색 균형] LUT 만 입힌 화면의 중간 밝기(0.2~0.8)에서 빨강·파랑을 초록에 맞춤(파랑 ≥ 빨강×0.9)."""
    y = luma(a)
    m = (y > 0.2) & (y < 0.8)
    sel = a[m] if m.mean() > 0.02 else a.reshape(-1, 3)
    r, g, b = sel.mean(0) + 1e-4
    rr = float(np.clip(g / r, 0.5, 2.0))
    return rr, min(1.5, follow_blue(rr, float(np.clip(g / b, 0.5, 1.5))))


def range_marks(a: np.ndarray, lo: float = 0.05, hi: float = 0.95) -> list[tuple[str, str]]:
    """채널별 (명부, 암부) 표시: "over" = 끝에 붙어 뭉개짐(빨강 점) / "short" = 목표선까지 못 감(파랑 점) / "" = 적당.
    값 0~1 배열(H×W×3)."""
    out = []
    for c in range(3):
        v = a[..., c].reshape(-1)
        top = "over" if (v >= 0.995).mean() > 0.01 else "short" if np.percentile(v, 98) < hi else ""
        bot = "over" if (v <= 0.005).mean() > 0.01 else "short" if np.percentile(v, 2) > lo else ""
        out.append((top, bot))
    return out
