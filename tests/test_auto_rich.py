"""v0.16.53 점검: 이미 진한 영상(카메라 비비드 등 — 밝은 곳 중 채도 0.9 넘는 면적이 큼)은 AUTO 가 채도·S커브·암부 누르기·밝기 덧씌움을
덜/안 얹음(색 균형은 그대로). 보통 영상(면적 ≈0)은 예전 그대로. 시작 파랑 ◆ = 밝은 쪽 파랑이 날아가지 않는 데까지만.
사용: python tests/test_auto_rich.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
from dtme import auto
from dtme.project import FACTORY_GRADE

rng = np.random.default_rng(1)


def water(r, g, b, n=0.01):
    """물만 보이는 화면(위가 밝음) — r·g·b = 가운데 밝기에서의 색."""
    y = np.linspace(1.5, 0.5, 90, dtype=np.float32)[:, None, None]
    a = np.ones((90, 160, 3), np.float32) * np.array([r, g, b], np.float32) * y
    return np.clip(a + rng.normal(0, n, a.shape).astype(np.float32), 0, 1)


base = dict(FACTORY_GRADE, lut="")
plain = [(i * 60, water(0.10, 0.30, 0.45)) for i in range(6)]        # 채도 ≈0.78 — 보통(DJI + LUT)
vivid = [(i * 60, water(0.01, 0.25, 0.50)) for i in range(6)]        # 채도 ≈0.98 — 이미 진함
half = [(i * 60, np.concatenate([water(0.10, 0.30, 0.45)[:, :146], water(0.01, 0.25, 0.50)[:, 146:]], 1)) for i in range(6)]
kp, kv, kh = auto.rich_keep(plain), auto.rich_keep(vivid), auto.rich_keep(half)
print("얹는 정도: 보통", kp, "· 진함", kv, "· 사이", round(kh, 2))
assert kp == 1.0 and kv == 0.0 and 0.1 < kh < 0.9
rp, rv, rh = (auto.recommend(s, base, scene="bluewater", fps=30.0) for s in (plain, vivid, half))
old = auto.builtin_grade("bluewater", base)
print("보통:", rp["grade"]["sat"], rp["grade"]["curve"]); print("진함:", rv["grade"]["sat"], rv["grade"]["curve"])
assert rp["rich"] == 0 and rp["grade"]["sat"] == old["sat"] == 1.1, "보통 영상 = 예전 그대로"
cp, cv = rp["grade"]["curve"], rv["grade"]["curve"]
assert [x for x, _y in cp[:3]] == [x for x, _y in cv[:3]], "검정·흰점(커브 x)은 같음"
assert cp[1][1] < 0.20 and cp[2][1] > 0.84, "보통 = S커브 + 암부 누르기 + 밝기 덧씌움(예전 그대로)"
assert rv["rich"] == 1 and rv["grade"]["sat"] == 1.0, "진함 = 채도 안 더함"
assert cv[1][1] == 0.25 and cv[2][1] == 0.75, ("진함 = 가운데 그대로", cv)
assert 1.0 < rh["grade"]["sat"] < 1.1
for k in ("water", "gy", "hue", "nr_chroma", "wnr"):                   # 색 균형·노이즈 쪽은 그대로
    assert rv["grade"][k] == rp["grade"][k], k
# 시작 파랑 ◆ 상한: 시작이 누렇고 밝음(파랑이 모자라 보여 올리고 싶지만 밝은 쪽 파랑이 이미 높음) → 날아가지 않는 데까지만
fr = [0, 15, 30, 60, 90, 150, 240, 360, 480, 600]
smp = [(f, water(0.30, 0.50, 0.45) if f < 150 else water(0.10, 0.30, 0.45)) for f in fr]
r = auto.recommend(smp, base, scene="bluewater", fps=30.0)
bk = r["gkeys"].get("b_gain") or []
print("시작 파랑 ◆:", bk)
assert bk, "시작 색 ◆ 생김"
top = auto.stats(smp[0][1])["top10"][2]
assert all(k["v"] * top <= auto.START_B_TOP + 0.02 or k["v"] <= r["grade"]["b_gain"] + 1e-6 for k in bk if k["f"] < 150), (bk, top)
print("OK test_auto_rich")
