"""v0.16.56: DJI 원본(D-Log M + LUT)이 아닌 영상 = 화면을 재서(색조 0 · 파랑은 빨강을 따라 올리지 않음 · 물빛 = 물 색상각이 목표에 못 미치는 만큼 0~20).
DJI 원본·옛 프로젝트 = 예전 값 그대로. 커브·◆(밝기 쪽)는 두 방식이 같음. python tests/test_auto_measure.py"""
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
    print(name, "예전", {k: go[k] for k in ("r_gain", "b_gain", "hue", "water")}, "측정", {k: gn[k] for k in ("r_gain", "b_gain", "hue", "water")})
    assert go["hue"] == auto.BASE_HUE and go["b_gain"] >= round(auto.BLUE_FOLLOW * go["r_gain"], 3) - 1e-6      # 예전 = 그대로
    assert gn["hue"] == 0 and gn["r_gain"] == go["r_gain"] and gn["b_gain"] <= go["b_gain"]
    assert 0 <= gn["water"] <= auto.WATER_CAP
    assert gn["curve"] == go["curve"] and gn["sat"] == go["sat"] and gn["gy"] == go["gy"]                       # 밝기·나머지 = 같음
    assert new["measured"] and not old["measured"]
gw = auto.recommend(green, base, "shallow", fps=60.0, measure=True)["grade"]["water"]
bw = auto.recommend(blue, base, "shallow", fps=60.0, measure=True)["grade"]["water"]
assert gw > bw == 0, (gw, bw)                                   # 청록 물 = 더 많이, 이미 파란 물 = 0
# 물이 안 보이는 화면 = 프리셋 물빛 그대로
sand = [(k * 120, np.full((180, 320, 3), (0.5, 0.5, 0.45), np.float32)) for k in range(4)]
assert auto.recommend(sand, base, "shallow", fps=60.0, measure=True)["grade"]["water"] == auto.builtin_grade("shallow", base)["water"]
# 어느 클립이 예전 값 그대로인가
s = Source(path="x.mp4")
s.lut_mode = "dlog"; assert auto.is_dji_log(s, "DJI.cube") and not auto.is_dji_log(s, "")
s.lut_mode = ""; assert auto.is_dji_log(s, "")                 # 옛 프로젝트
for m in ("normal", "unknown", "ilog"):
    s.lut_mode = m; assert not auto.is_dji_log(s, "x.cube")
print("OK test_auto_measure")
