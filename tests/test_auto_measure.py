"""v0.16.60(P2): DJI 원본(D-Log M + LUT)이 아닌 영상 = 색조 0 · 물빛 0 만 다름(보라만 조금 뺌). DJI 원본·옛 프로젝트 = 예전 값 그대로. python tests/test_auto_measure.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
from dtme import auto
from dtme.project import FACTORY_GRADE, Source


def scene(water_rgb, n=6):
    """위 = 물, 아래 = 밝은 모래(약간 청록). 320×180."""
    out = []
    rng = np.random.default_rng(1)
    for k in range(n):
        a = np.zeros((180, 320, 3), np.float32)
        a[:80] = water_rgb
        a[80:] = (0.50, 0.68, 0.70)
        a += rng.normal(0, 0.01, a.shape).astype(np.float32)
        out.append((k * 120, np.clip(a, 0, 1)))
    return out


base = {**FACTORY_GRADE, "lut": ""}
green = scene((0.10, 0.42, 0.50))      # 청록 물(색상각 ≈ 192°)
blue = scene((0.08, 0.25, 0.60))       # 이미 파란 물(≈ 220°)
for name, smp in (("청록", green), ("파랑", blue)):
    old = auto.recommend(smp, base, "shallow", fps=60.0)
    new = auto.recommend(smp, base, "shallow", fps=60.0, measure=True)
    go, gn = old["grade"], new["grade"]
    print(name, "예전", {k: go[k] for k in ("r_gain", "b_gain", "hue", "water")}, "DJI 원본 아님", {k: gn[k] for k in ("r_gain", "b_gain", "hue", "water")})
    assert go["hue"] == auto.BASE_HUE and go["water"] > 0                       # 예전(DJI 원본) = 그대로
    assert gn["hue"] == 0 and gn["water"] == 0                                  # v0.16.60 P2: 색조 0 · 물빛 0
    diff = {k for k in go if go[k] != gn[k]}
    assert diff == {"hue", "water"}, diff                                       # 그 둘 말고는 전부 같음(빨강·파랑·커브·채도·노이즈…)
    assert old["gkeys"] == new["gkeys"] and new["measured"] and not old["measured"]
# 어느 클립이 예전 값 그대로인가
s = Source(path="x.mp4")
s.lut_mode = "dlog"; assert auto.is_dji_log(s, "DJI.cube") and not auto.is_dji_log(s, "")
s.lut_mode = ""; assert auto.is_dji_log(s, "")                 # 옛 프로젝트
for m in ("normal", "unknown", "ilog"):
    s.lut_mode = m; assert not auto.is_dji_log(s, "x.cube")
print("OK test_auto_measure")
