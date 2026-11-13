"""자동 편집(v0.16.68): 고른 소스에서 하이라이트를 골라 정한 전체 길이로 타임라인을 채움.

하이라이트(프록시 또는 원본의 기준 프레임을 0.5초마다 96×54 로 읽어 화면만 봄 — AI 인식 아님):
- 블루워터 = 대비가 강하고 또렷한 화면
- 그 밖 = 피사체(가운데가 둘레와 다른 정도) + 사람(뭉친 검은 덩어리 + 그 위로 3~6초마다 올라가는 기포 + 장비 색
  주황·노랑·빨강) + 또렷함 − 흔들림. 한 피사체를 계속 찍은 클립은 그 점수가 높은 쪽으로 앞뒤가 잘림
컷 = 최소 5초 · 최대 1분, 전체 길이에 맞춤, 순서 = 촬영순(모르면 목록순), 전환 = 모든 경계 랜덤 0.5초.
한계: 색·밝기 통계라 물고기 떼·그림자를 사람으로, 멀리 있는 다이버를 못 보는 경우가 있음(사용자 클립으로 기준 조정 예정).
"""
from __future__ import annotations

import math
import random
import subprocess

import numpy as np

from . import ff, paths
from .project import (TRANSITIONS, Segment, display_name, new_rect, new_text, short_name)

STEP = 0.5                       # 초 — 화면 읽는 간격
SW, SH = 96, 54
CUT_MIN, CUT_MAX = 5.0, 60.0
TRANS_SEC = 0.5
TITLE_SEC = 5.0
TITLE_DELAY = 1.0                # 전환(디졸브)이 끝나고 이만큼 뒤에 글자·사각형
CALM = ("shallow", "coral", "light")          # 장면 → 음악 묶음
GRAND = ("bluewater",)


# ------------------------------------------------------------------ 화면 읽기
def scan(src, cancel=None) -> np.ndarray:
    """→ (n, 54, 96, 3) float32 0~1, 0.5초마다. 프록시가 있으면 프록시(LUT 입힘), 없으면 원본(LUT 없음 — 비교용이라 충분)."""
    path = src.proxy if getattr(src, "proxy", "") and __import__("os").path.exists(src.proxy) else src.path
    cmd = [paths.ffmpeg(), "-hide_banner", "-v", "error", "-skip_frame", "nokey", "-i", ff._abs(path), "-an",
           "-vf", f"fps={1 / STEP:g},scale={SW}:{SH}:flags=area,format=rgb24", "-f", "rawvideo", "-"]
    with ff._slots(cmd):
        pr = ff._popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw, err = pr.communicate()
    if cancel is not None and cancel.is_set():
        raise ff.Cancelled()
    n = len(raw) // (SW * SH * 3)
    if n == 0:
        raise ff.FFError(err.decode("utf-8", "replace")[-300:] or "화면을 못 읽음")
    return np.frombuffer(raw[:n * SW * SH * 3], np.uint8).reshape(n, SH, SW, 3).astype(np.float32) / 255.0


def features(a: np.ndarray) -> dict:
    """프레임들 → 특징(각 길이 n)."""
    y = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    n = len(a)
    contrast = y.reshape(n, -1).std(axis=1)
    lap = np.abs(4 * y[:, 1:-1, 1:-1] - y[:, :-2, 1:-1] - y[:, 2:, 1:-1] - y[:, 1:-1, :-2] - y[:, 1:-1, 2:])
    sharp = lap.reshape(n, -1).mean(axis=1)
    # 가운데(가로·세로 50%) vs 둘레: 색·밝기 차 + 가운데 대비
    c = a[:, SH // 4:SH * 3 // 4, SW // 4:SW * 3 // 4]
    ring_mask = np.ones((SH, SW), bool)
    ring_mask[SH // 4:SH * 3 // 4, SW // 4:SW * 3 // 4] = False
    ring = a[:, ring_mask]
    sal = np.abs(c.reshape(n, -1, 3).mean(1) - ring.mean(1)).sum(1) + c.reshape(n, -1, 3).mean(2).std(1)
    # 흔들림 = 0.5초 사이 화면 차
    mot = np.zeros(n, np.float32)
    if n > 1:
        mot[1:] = np.abs(y[1:] - y[:-1]).reshape(n - 1, -1).mean(1)
        mot[0] = mot[1]
    # 사람: 뭉친 검은 덩어리(어두운 픽셀이 2~30% · 그 범위 상자 안을 35% 넘게 채움)
    blob = np.zeros(n, np.float32)
    bub = np.zeros(n, np.float32)
    for i in range(n):
        yi = y[i]
        med = float(np.median(yi))
        dk = (yi < min(0.25, med * 0.6))
        fr = float(dk.mean())
        if 0.02 <= fr <= 0.30:
            rows, cols = np.nonzero(dk)
            box = (rows.max() - rows.min() + 1) * (cols.max() - cols.min() + 1)
            fill = dk.sum() / box
            if fill > 0.35:
                blob[i] = min(1.0, fill) * min(1.0, fr / 0.06)
                top = rows.min()
                if top > 2:                          # 그 위쪽의 밝고 작은 점 = 기포
                    up = yi[:top]
                    bub[i] = float((up > max(0.75, np.percentile(yi, 97))).mean())
    # 장비 색(주황·노랑·빨강)
    mx, mn = a.max(axis=3), a.min(axis=3)
    sat = (mx - mn) / (mx + 1e-6)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    warm = (r >= g) & (g >= b * 0.9) & (sat > 0.5) & (mx > 0.35)
    gear = warm.reshape(n, -1).mean(1)
    return {"contrast": contrast, "sharp": sharp, "sal": sal, "motion": mot, "blob": blob, "bubble": bub, "gear": gear}


def _z(x):
    x = np.asarray(x, np.float64)
    s = x.std()
    return (x - x.mean()) / s if s > 1e-9 else np.zeros_like(x)


def bubble_rhythm(bub: np.ndarray, i: int, win: int = 24) -> float:
    """i 앞뒤 win 칸(±6초)의 기포 세기에서 3~6초 주기(자기상관) 0~1."""
    a, b = max(0, i - win), min(len(bub), i + win + 1)
    x = bub[a:b] - bub[a:b].mean()
    if len(x) < 14 or x.std() < 1e-4:
        return 0.0
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    ac = ac / (ac[0] + 1e-12)
    lags = range(int(3 / STEP), min(len(ac), int(6 / STEP) + 1))
    return float(max(0.0, max((ac[k] for k in lags), default=0.0)))


def scores(f: dict, scene: str) -> np.ndarray:
    """칸마다 하이라이트 점수(높을수록 좋음)."""
    n = len(f["contrast"])
    if scene in GRAND:
        s = 0.6 * _z(f["contrast"]) + 0.4 * _z(f["sharp"]) - 0.25 * _z(f["motion"])
    else:
        rhythm = np.array([bubble_rhythm(f["bubble"], i) for i in range(n)])
        person = f["blob"] * (0.6 + 0.4 * rhythm) + 2.0 * np.clip(f["gear"] / 0.02, 0, 1) * 0.3
        s = 0.40 * _z(f["sal"]) + 0.30 * person / (person.std() + 0.3) + 0.20 * _z(f["sharp"]) - 0.20 * _z(f["motion"])
    w = np.ones(n)
    k1, k2 = int(1.5 / STEP), int(1.0 / STEP)       # 녹화 시작·끝(손 흔들림) 덜
    w[:k1] = 0.5
    if k2:
        w[-k2:] = 0.5
    return (s - s.min() + 0.1) * w


def best_windows(sc: np.ndarray, length: float, k: int) -> list[float]:
    """점수 합이 큰 구간 k개(안 겹침) → 시작 초(시간 순)."""
    L = max(1, int(round(length / STEP)))
    n = len(sc)
    if n <= L:
        return [0.0]
    cs = np.concatenate([[0.0], np.cumsum(sc)])
    tot = cs[L:] - cs[:-L]                          # 시작 칸 i 의 합(i = 0..n-L)
    used = np.zeros(len(tot), bool)
    out = []
    for _ in range(k):
        cand = np.where(used, -np.inf, tot)
        i = int(np.argmax(cand))
        if not np.isfinite(cand[i]):
            break
        out.append(i * STEP)
        used[max(0, i - L + 1):i + L] = True
    return sorted(out)


# ------------------------------------------------------------------ 계획
def shoot_order(sources) -> list:
    """촬영순(이름·파일 안 시각 12자리) — 모르는 것이 하나라도 있으면 목록순."""
    keys = [short_name(s.path) for s in sources]
    if all(len(k) == 12 and k.isdigit() for k in keys):
        return [s for _k, s in sorted(zip(keys, sources), key=lambda x: x[0])]
    return list(sources)


def allot(durs: list[float], total: float) -> list[list[float]]:
    """소스마다 컷 길이 목록. 전체(전환 겹침 포함)가 total 이 되게, 긴 소스에 더(√길이). 원본이 모자라면 원본 길이까지."""
    usable = [max(0.0, d - 0.2) for d in durs]
    if sum(usable) <= total:
        out = []
        for u in usable:
            k = max(1, math.ceil(u / CUT_MAX))
            out.append([u / k] * k if u >= 1.0 else [])
        return out
    w = np.sqrt(np.maximum(usable, 0.01))
    share = [0.0] * len(durs)
    left, free = total, list(range(len(durs)))
    for _ in range(4):                               # 소스보다 긴 몫은 소스 길이로 묶고 남은 것을 다시 나눔
        ws = sum(w[i] for i in free)
        for i in free:
            share[i] = left * w[i] / ws
        over = [i for i in free if share[i] > usable[i]]
        if not over:
            break
        for i in over:
            share[i] = usable[i]
            left -= usable[i]
            free.remove(i)
        if not free:
            break
    out = []
    for i, a in enumerate(share):
        if a < CUT_MIN * 0.6 and usable[i] >= CUT_MIN:  # 아주 작은 몫 = 5초 1개(대신 다른 소스가 조금 줄어듦)
            a = CUT_MIN
        if a < 1.0:
            out.append([])
            continue
        k = max(1, math.ceil(a / CUT_MAX))
        out.append([max(min(a / k, usable[i]), min(CUT_MIN, usable[i]))] * k)
    return out


def fit_total(cuts: list[list[float]], total: float, n_trans: int) -> list[list[float]]:
    """전환 겹침(경계마다 0.5초)만큼 컷을 늘려 결과 길이 = total (5~60초 안에서)."""
    cur = sum(sum(c) for c in cuts) - n_trans * TRANS_SEC
    if cur <= 0:
        return cuts
    k = total / cur
    return [[float(np.clip(x * k, CUT_MIN, CUT_MAX)) if x >= CUT_MIN else x for x in c] for c in cuts]


def build(project, picks: list[dict], minutes: int, seed: int = 0, titles: bool = True) -> dict:
    """picks = [{"src": Source, "scene": str, "score": ndarray}] (촬영순).
    → {"segs": [Segment], "titles": [dict], "scenes": {컷 id: scene}}"""
    total = float(minutes) * 60.0
    durs = [p["src"].frames / float(p["src"].fps) for p in picks]
    cuts = allot(durs, total)
    n = sum(len(c) for c in cuts)
    cuts = fit_total(cuts, total, max(0, n - 1))
    rnd = random.Random(seed)
    kinds = [k for k, _ in TRANSITIONS if k != "none"]
    segs, scene_of, firsts = [], {}, []
    for p, lens in zip(picks, cuts):
        s = p["src"]
        if not lens:
            continue
        fps = float(s.fps)
        dur = s.frames / fps
        L = min(max(lens), dur)
        starts = best_windows(p["score"], L, len(lens)) if p.get("score") is not None else [0.0]
        for j, (st, ln) in enumerate(zip(starts, lens)):
            ln = min(ln, dur)
            st = max(0.0, min(st, dur - ln))
            fin = int(round(st * fps))
            fout = min(s.frames, fin + max(1, int(round(ln * fps))))
            g = Segment(s.id, fin, fout, 1.0)
            if segs:
                g.trans = {"type": rnd.choice(kinds), "dur": TRANS_SEC}
            if j == 0:
                firsts.append((g.id, s))
            scene_of[g.id] = p.get("scene", "")
            segs.append(g)
    tts = []
    if titles:
        from .project import cut_spans
        tmp = type(project)()
        tmp.sources = project.sources
        tmp.segments = segs
        tmp.lead = project.lead
        start = {c: t for c, t, _l in cut_spans(tmp)}
        tdur = {g.id: float((g.trans or {}).get("dur", 0) or 0) for g in segs}
        from .ff import out_size
        o = project.out_of(picks[0]["src"]) if picks else "horizontal"
        wh = (1080, 1920) if out_size(o)[0] < out_size(o)[1] else (1920, 1080)     # 위치 비율 = 화면 방향만(크기 무관)
        for cid, s in firsts:
            t0 = start.get(cid, 0.0) + tdur.get(cid, 0.0) + TITLE_DELAY     # v0.16.72 디졸브 끝나고 1초 뒤(사용자)
            tts += title_pair(display_name(s.path), t0, wh)
    return {"segs": segs, "titles": tts, "scenes": scene_of}


TITLE_SIZE = 52
TITLE_PAD = (24, 12)               # 사각형 = 글자 + 좌우 24 · 위아래 12 (1080 기준 px)
TITLE_LEFT, TITLE_BOTTOM = 0.05, 0.12   # 사각형 왼쪽 = 화면 폭 5%, 아래 = 화면 높이 12% 위


def text_size(t: dict) -> tuple[float, float]:
    """글자 상자 (폭, 높이) — 출력 px(1080 기준 = 글자 크기 그대로). 화면 모니터와 같은 글꼴·계산(Qt)."""
    try:
        from PySide6.QtGui import QFontMetricsF, QGuiApplication
        if QGuiApplication.instance() is None:          # 화면 없이 Qt 글꼴을 쓰면 죽음 → 어림
            raise RuntimeError("no app")
        from .ui_player import Monitor
        fm = QFontMetricsF(Monitor._title_font(None, t, 1.0))
        lines = (t.get("text") or " ").split("\n")
        return (max(fm.horizontalAdvance(x) for x in lines) + 4,
                fm.lineSpacing() * len(lines) + 8 * (len(lines) - 1))
    except Exception:  # noqa: BLE001 — 화면 없이(시험) = 어림
        n = max(len(x) for x in (t.get("text") or " ").split("\n"))
        return n * float(t.get("size", 64)) * 0.58 + 4, float(t.get("size", 64)) * 1.3


def title_pair(text: str, t0: float, out_wh: tuple[int, int] = (1920, 1080)) -> list[dict]:
    """글자 + 배경 사각형(v0.16.69: 실제 글자 크기 + 여백, 출력 가로·세로에 맞춘 비율): 왼쪽에서 들어와 왼쪽으로 나감, 5초, 따라감.
    → [사각형, 글자] (사각형이 아래). 글자 크기·여백은 1080 기준 px → 출력 짧은 쪽/1080 배."""
    W, H = out_wh
    k = min(W, H) / 1080
    tx = new_text(t0, t0 + TITLE_SEC, text)
    tx.update(size=TITLE_SIZE, bg="none", ain="right", aout="left", follow=True, auto_edit=True)
    tw, th = text_size(tx)
    rw, rh = (tw + 2 * TITLE_PAD[0]) * k, (th + 2 * TITLE_PAD[1]) * k
    cx = (TITLE_LEFT * W + rw / 2) / W
    cy = ((1 - TITLE_BOTTOM) * H - rh / 2) / H
    tx.update(cx=round(cx, 4), cy=round(cy, 4))
    rc = new_rect(t0, t0 + TITLE_SEC)
    full = TITLE_LEFT * W + rw                       # v0.16.72 사각형 = 화면 왼쪽 끝부터 글자 오른쪽 여백까지(사용자)
    rc.update(cx=round(full / 2 / W, 4), cy=round(cy, 4), w=round(full / W, 4), h=round(rh / H, 4), opacity=0.5, ain="right", aout="left",
              follow=True, auto_edit=True)
    return [rc, tx]


def music_runs(spans, scenes: dict, min_len: float = 20.0) -> list[tuple[float, float, str]]:
    """컷 장면 → 음악 구간 [(시작, 끝, 'grand'|'calm'|'mid')]. 짧은 구간(20초 미만)은 앞 구간에 붙임."""
    def grp(sc):
        return "grand" if sc in GRAND else "calm" if sc in CALM else "mid"
    runs = []
    for cid, t, ln in spans:
        gname = grp(scenes.get(cid, ""))
        if runs and runs[-1][2] == gname:
            runs[-1][1] = t + ln
        else:
            if runs:
                runs[-1][1] = t
            runs.append([t, t + ln, gname])
    merged = []                                   # [시작, 끝, {묶음: 길이}] — 짧은 구간은 앞(없으면 뒤)에 붙이고 더 긴 묶음 성격으로
    for a, b, gname in runs:
        if merged and (b - a < min_len or merged[-1][1] - merged[-1][0] < min_len):
            m = merged[-1]
            m[1] = b
            m[2][gname] = m[2].get(gname, 0.0) + (b - a)
        else:
            merged.append([a, b, {gname: b - a}])
    merged = [[a, b, max(w.items(), key=lambda kv: kv[1])[0]] for a, b, w in merged]   # 같은 길이 = 먼저 나온 것
    return [tuple(r) for r in merged]


RUN_TARGET = {"grand": (0.75, 0.8), "calm": (0.25, 0.25), "mid": (0.5, None)}


def snap_to_bars(project, music_info: dict, tol_bar: float = 0.5) -> int:
    """컷 경계(전환 가운데)를 그 자리 음악의 마디 첫 박에 맞춤: 앞 컷 아웃을 늘리거나 줄임(5~60초·원본 안).
    글자·음악은 따라감 규칙으로 같이 움직임. 맞춘 경계 수."""
    from .music import beats_on_timeline
    from .project import cut_spans, follow_anchors, follow_apply
    p = project
    moved = 0
    for i in range(1, len(p.segments)):
        spans = cut_spans(p)
        if i >= len(spans):
            break
        cid, t, _ln = spans[i]
        d = float((p.segments[i].trans or {}).get("dur", 0)) if p.segments[i].trans else 0.0
        T = t + min(d, TRANS_SEC) / 2
        best = None
        for m in p.music:
            inf = music_info.get(m["path"])
            if not inf or float(inf.get("conf", 0)) < 0.3:
                continue
            if not (float(m["t0"]) - 0.01 <= T <= float(m["t0"]) + float(m["len"])):
                continue
            bars = beats_on_timeline(m, inf, bars=True)
            if len(bars) < 2:
                continue
            per = float(np.median(np.diff(bars)))
            for b in bars:
                if abs(b - T) <= per * tol_bar and (best is None or abs(b - T) < abs(best)):
                    best = b - T
        if best is None or abs(best) < 0.02:
            continue
        g = p.segments[i - 1]
        s = p.source(g.src)
        fps = float(s.fps)
        cur = (g.fout - g.fin) / fps
        want = float(np.clip(cur + best, CUT_MIN, CUT_MAX))
        fout = min(s.frames, g.fin + int(round(want * fps)))
        if fout == g.fout:
            continue
        anc = follow_anchors(p)
        g.fout = fout
        follow_apply(p, anc)
        moved += 1
    return moved
