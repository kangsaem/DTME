"""자동 보정(추천 · AUTO): 샘플 추출 → 색 통계 → 장면·피사체 판단 → 값 계산 → (필요하면) 색 키프레임.

AI 가 아닌 색 통계 휴리스틱이다. 출발점 용도.
- 수심·라이트·야간은 색 통계로 꽤 맞힘. 피사체는 산호초(따뜻한 색 면적)만 추정, 나머지는 '물고기'.
- 값 = 장면 프리셋 기준값 + 영상별 흰색(빨강·파랑)·명암(커브) 미세 조정.
"""
from __future__ import annotations

import numpy as np

from . import ff, paths
from .project import FACTORY_GRADE, Source

# ------------------------------------------------------------------ 장면·피사체·프리셋
SCENES = [("light", "라이트"), ("shallow", "얕은 수심"), ("deep", "깊은 수심"), ("bluewater", "블루워터"), ("night", "야간")]
SUBJECTS = [("fish", "물고기"), ("coral", "산호초"), ("turtle", "거북이"), ("diver", "다이버")]
SUBJECT_SCENES = ("light", "shallow", "deep")       # 피사체로 나누는 장면(나머지 2개는 하나씩)
SCENE_NAME, SUBJECT_NAME = dict(SCENES), dict(SUBJECTS)
STRENGTH = {"weak": 0.6, "mid": 1.0, "strong": 1.3}
STRENGTH_NAME = {"weak": "약", "mid": "중", "strong": "강"}

# 장면 기준값. r/b = 고정 프리셋 게인, k = 영상별 흰색 맞춤 정도, ref = 흰색 기준(밝은 쪽 비율), s = 커브 S 세기
SCENE_BASE = {
    # 실제 수중 샘플(2026-11-06, 보홀) 보고 조정. 원칙(사용자): 물속은 원래 파랗고 어느 정도 뿌연 것.
    # 원색(특히 빨강)을 되살리거나 그랑블루로 만들 필요 없음 — **색이 틀어지거나 노이즈가 나오지 않는 것이 먼저**.
    # 파란 물의 빨간 점·노이즈 = 빨강 게인·커브 늘이기·채도가 원인 → 셋 다 작게, 색 노이즈 제거는 강하게(60 이상 = 색 채널 미디언)
    # r/b = 고정 프리셋 게인, rmax = 빨강 최대, k = 영상별 흰색 맞춤 정도, ref = 흰색 기준(밝은 쪽 비율),
    # s = 커브 S 세기, lo = 검정점 배율, sh = 샤픈, wnr = 물 노이즈(파란 영역 붉은 노이즈 정리)
    "light":     dict(r=1.05, b=1.00, rmax=1.15, k=0.25, ref=0.10, water=8, gy=25, sat=1.00, nrc=60, nrl=30, dehaze=0, s=0.04, lo=0.8, sh=0.15, wnr=30),
    "shallow":   dict(r=1.10, b=1.00, rmax=1.20, k=0.40, ref=0.30, water=8, gy=30, sat=1.00, nrc=60, nrl=30, dehaze=0, s=0.04, lo=0.8, sh=0.15, wnr=40),
    "deep":      dict(r=1.15, b=1.00, rmax=1.28, k=0.40, ref=0.50, water=8, gy=30, sat=1.00, nrc=65, nrl=35, dehaze=0, s=0.03, lo=0.5, sh=0.10, wnr=65),
    "bluewater": dict(r=1.00, b=1.00, rmax=1.08, k=0.15, ref=0.30, water=12, gy=40, sat=1.00, nrc=65, nrl=30, dehaze=5, s=0.05, lo=0.8, sh=0.10, wnr=70),
    "night":     dict(r=1.00, b=1.00, rmax=1.10, k=0.25, ref=0.10, water=0, gy=20, sat=1.00, nrc=65, nrl=40, dehaze=0, s=0.04, lo=0.8, sh=0.10, wnr=50),
}
# 피사체별 차이(더하기). 산호초 = 보통 라이트를 비춰 찍음 → 빨강 덜, 거북이 = 등껍질(노란 갈색) 지키려고 녹황 약하게, 다이버 = 피부
SUBJECT_DELTA = {
    "fish": {},
    "coral": dict(r=-0.05, rmax=-0.08, k=-0.15, gy=-5),
    "turtle": dict(gy=-20, rmax=-0.05),
    "diver": dict(sat=-0.05, gy=-10),
}


BASE_HUE, BASE_SAT = 5.0, 1.1      # 사용자 기본: 색조 +5, 채도 1.1 (장면별 채도는 이 값에서 더하고 뺌)
BLUE_FOLLOW = 0.9                  # 빨강을 올리면 파랑은 빨강의 0.9배 이상(물이 자주·회색으로 가지 않게)


def follow_blue(r: float, b: float) -> float:
    """파랑 ≥ 빨강 × 0.9 (자동 계산 값에만: AUTO·프리셋·흰색 찍기·색 균형. 슬라이더를 직접 움직이는 건 그대로)."""
    return max(float(b), round(BLUE_FOLLOW * float(r), 3))


def preset_keys() -> list[str]:
    """기본 프리셋 14개: light/fish … deep/diver, bluewater, night"""
    return [f"{sc}/{sb}" for sc in SUBJECT_SCENES for sb, _ in SUBJECTS] + ["bluewater", "night"]


def split_key(key: str) -> tuple[str, str]:
    sc, _, sb = (key or "").partition("/")
    return sc, (sb or "fish")


def preset_label(key: str, short: bool = False) -> str:
    sc, sb = split_key(key)
    if sc not in SCENE_NAME:
        return ""
    name = SCENE_NAME[sc]
    if sc not in SUBJECT_SCENES:
        return name
    if short:
        name = name.replace(" 수심", "")
    return f"{name}{'·' if short else ' · '}{SUBJECT_NAME.get(sb, '')}"


def scene_params(scene: str, subject: str, strength: str = "mid") -> dict:
    b = dict(SCENE_BASE.get(scene, SCENE_BASE["shallow"]))
    if scene in SUBJECT_SCENES:
        for k, v in SUBJECT_DELTA.get(subject, {}).items():
            b[k] = b[k] + v
    b["st"] = STRENGTH.get(strength, 1.0)
    return b


def s_curve(lo: float, hi: float, s: float, min_range: float = 0.75) -> list:
    """명암: 암부 lo → 거의 0, 명부 hi → 거의 1, 사이는 S자(s). 포인트는 양 끝 포함 최대 7개(중간 5개)."""
    lo, hi = max(0.0, min(0.45, lo)), max(0.4, min(1.0, hi))
    if hi - lo < min_range:               # 너무 좁으면 늘이는 양 제한(노이즈가 커짐)
        c = min(1 - min_range / 2, max(min_range / 2, (lo + hi) / 2))
        lo, hi = c - min_range / 2, c + min_range / 2
    d = hi - lo
    pts = [[0.0, 0.0]]
    if lo > 0.02:
        pts.append([round(lo, 4), 0.012])
    pts.append([round(lo + 0.25 * d, 4), round(max(0.03, 0.25 - s), 4)])
    pts.append([round(lo + 0.75 * d, 4), round(min(0.97, 0.75 + s), 4)])
    if hi < 0.98:
        pts.append([round(hi, 4), 0.985])
    pts.append([1.0, 1.0])
    return pts


def builtin_grade(key: str, base: dict | None = None, strength: str = "mid") -> dict:
    """기본 프리셋(고정값). base 의 LUT·샤픈·렌즈 등은 그대로."""
    sc, sb = split_key(key)
    p = scene_params(sc, sb, strength)
    st = p["st"]
    g = dict(base or FACTORY_GRADE)
    r = round(min(2.0, 1 + (p["r"] - 1) * st), 3)
    g.update(r_gain=r, b_gain=follow_blue(r, round(1 + (p["b"] - 1) * st, 3)), hue=BASE_HUE,
             sat=round(BASE_SAT + (p["sat"] - 1) * st, 3), water=int(round(p["water"] * st)), gy=int(round(min(100, p["gy"] * st))),
             nr_chroma=int(p["nrc"]), nr_luma=int(p["nrl"]), dehaze=int(round(p["dehaze"] * st)),
             curve=s_curve(0.04, 0.95, p["s"] * st), stab=0, sharpen=p.get("sh", 0.15),
             wnr=int(p.get("wnr", 0)))
    return g


# ------------------------------------------------------------------ 샘플 추출
SAMPLE_W = 320
SAMPLE_EVERY_SEC = 2.0
SAMPLE_MAX = 20


def sample_frames(src: Source, every: float = SAMPLE_EVERY_SEC, n_max: int = SAMPLE_MAX,
                  a: int | None = None, b: int | None = None) -> list[int]:
    """구간 [a, b) 에서 every 초마다 1장(최대 n_max, 넘으면 고르게). 가운데 정렬."""
    a = 0 if a is None else a
    b = src.frames if b is None else b
    n = max(1, min(n_max, int((b - a) / float(src.fps) / every)))
    return [int(a + (k + 0.5) * (b - a) / n) for k in range(n)]


def grab_small(src: Source, frame: int, lut: str, gpu: bool = False, w: int = SAMPLE_W) -> np.ndarray:
    """원본 1장 → (LUT 만 입혀) 작은 RGB float 배열(0~1)."""
    ref = ff.lut_ref(lut) if lut else None
    vf = [f"scale={w}:-2:flags=bilinear", "format=gbrp16le"]
    if ref:
        vf.append(f"lut3d=file={ref[1]}:interp=tetrahedral")
    vf.append("format=rgb24")
    cmd = [paths.ffmpeg(), "-v", "error", *ff._hw(gpu), "-ss", ff._seek(frame, src.fps), "-i", ff._abs(src.path),
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


def grab_samples(src: Source, lut: str, gpu: bool = False, frames: list[int] | None = None,
                 cancel=None, on_progress=None) -> list[tuple[int, np.ndarray]]:
    out = []
    frames = frames if frames is not None else sample_frames(src, a=src.io[0], b=src.io[1])
    for i, f in enumerate(frames):
        if cancel is not None and cancel.is_set():
            raise ff.Cancelled()
        out.append((f, grab_small(src, f, lut, gpu)))
        if on_progress:
            on_progress((i + 1) / len(frames))
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
def gains_for(st: dict, p: dict) -> tuple[float, float]:
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
    return r, follow_blue(r, float(np.clip(bg, pb - 0.05, pb + 0.05)))


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


def recommend(samples: list[tuple[int, np.ndarray]], base: dict, scene: str | None = None, subject: str | None = None,
              strength: str = "mid") -> dict:
    """샘플 → {"grade": 클립 값(전체), "gkeys": 색 키프레임 또는 {}, "scene", "subject", "preset"}"""
    sts = [stats(a) for _f, a in samples]
    sc = scene if scene in SCENE_NAME else classify(sts)
    p0 = scene_params(sc, "fish", strength)
    g0 = [gains_for(s, p0) for s in sts]
    if subject in SUBJECT_NAME:
        sb = subject
    else:
        warm = float(np.median([warm_fraction(a, r, b) for (_f, a), (r, b) in zip(samples, g0)]))
        sb = "coral" if warm > 0.08 else "fish"
    if sc not in SUBJECT_SCENES:
        sb = ""
    p = scene_params(sc, sb or "fish", strength)
    gains = [gains_for(s, p) for s in sts]
    lo, hi = tone_for(samples, gains)
    # 커브는 클립 전체 1개 → 깊은 구간이 섞여 있으면 깊은 곳 기준(S·검정점 약하게). 깊은 곳은 빨강이 암부에 있음
    mixed = any(classify([x]) == "deep" for x in sts) and sc != "deep"
    pd = SCENE_BASE["deep"] if mixed else p
    lo *= pd.get("lo", 0.9)
    s_amt = min(p["s"], pd["s"]) * (0.6 if mixed else 1.0)
    st = p["st"]
    g = builtin_grade(f"{sc}/{sb}" if sb else sc, base, strength)
    rs, bs = _med3([x[0] for x in gains]), _med3([x[1] for x in gains])
    g.update(r_gain=round(float(np.median(rs)), 3), b_gain=round(float(np.median(bs)), 3),
             curve=s_curve(lo - 0.01, hi + 0.01, s_amt * st))
    gkeys = {}
    frames = [f for f, _a in samples]
    if len(frames) >= 2 and (max(rs) - min(rs) > KEY_TOL_R or max(bs) - min(bs) > KEY_TOL_B):
        idx = sorted(set(pick_keys(frames, rs, KEY_TOL_R / 3)) | set(pick_keys(frames, bs, KEY_TOL_B / 3)))
        if len(idx) > 6:      # 두 값의 키 위치를 합쳐 6개 넘으면 고르게 줄임
            idx = [idx[int(round(i * (len(idx) - 1) / 5))] for i in range(6)]
        gkeys = {"r_gain": [{"f": frames[i], "v": round(rs[i], 3)} for i in idx],
                 "b_gain": [{"f": frames[i], "v": round(bs[i], 3)} for i in idx]}
    return {"grade": g, "gkeys": gkeys, "scene": sc, "subject": sb, "preset": f"{sc}/{sb}" if sb else sc}


def analyze_source(src: Source, base: dict, scene=None, subject=None, strength="mid", gpu=False,
                   cancel=None, on_progress=None) -> dict:
    samples = grab_samples(src, base.get("lut", ""), gpu, cancel=cancel, on_progress=on_progress)
    return recommend(samples, base, scene, subject, strength)


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
