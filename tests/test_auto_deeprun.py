"""v0.16.62: 깊은 구간이 섞인 클립 = 그 구간에만 약한 커브(커브 ◆). 샘플 1장만 깊어 보이면 무시(예전 = 1장 때문에 클립 전체 대비가 0.45배).
python tests/test_auto_deeprun.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
from dtme import auto
from dtme.project import FACTORY_GRADE, curve_at

rng = np.random.default_rng(3)


def img(kind):
    a = np.zeros((180, 320, 3), np.float32)
    if kind == "s":                                  # 얕은: 모래·산호(빨강이 꽤 있음)
        a[:60] = (0.20, 0.45, 0.60); a[60:] = (0.50, 0.62, 0.60)
    else:                                            # 깊은: 빨강 거의 없음
        a[:60] = (0.05, 0.30, 0.45); a[60:] = (0.14, 0.42, 0.50)
    a[60:] *= 1 + 0.25 * np.sin(np.arange(320) / 5.0)[None, :, None]        # 무늬(바닥)
    a += rng.normal(0, 0.012, a.shape).astype(np.float32)
    return np.clip(a, 0.02, 1)


def clip(pattern):
    return [(k * 120, img(c)) for k, c in enumerate(pattern)]


base = {**FACTORY_GRADE, "lut": ""}
assert auto.classify([auto.stats(img("s"))]) == "shallow" and auto.classify([auto.stats(img("d"))]) == "deep"
assert auto.deep_runs([0, 1, 0, 1, 1, 1, 0, 1], 0) == [(3, 5)] and auto.deep_runs([1, 1, 0, 0], 1) == [] and auto.deep_runs([1, 1, 1], 0) == [(0, 2)]
def S(c):
    """S 세기 = 가운데 구간 기울기 − 양끝 포함 평균 기울기(클수록 대비가 셈)."""
    xs, ys = zip(*c)
    return round(float((np.interp(0.7, xs, ys) - np.interp(0.3, xs, ys)) / 0.4 - 1), 3)


r0 = auto.recommend(clip("ssssssssss"), base, fps=60.0)
r1 = auto.recommend(clip("ssssssssds"), base, fps=60.0)          # 1장만 깊음
r1e = auto.recommend(clip("sssssssssd"), base, fps=60.0)         # 끝 1장만 깊음(받은 Ace Pro 클립 꼴)
r3 = auto.recommend(clip("ssssdddsss"), base, fps=60.0)          # 가운데 3장(6초) 깊은 구간
rend = auto.recommend(clip("sssssssddd"), base, fps=60.0)        # 뒤쪽이 깊은 구간으로 끝남
for r in (r0, r1, r1e, r3, rend):
    assert r["preset"] == "shallow", r["preset"]
s0 = S(r0["grade"]["curve"])
print("S: 깊은 곳 없음", s0, "· 1장", S(r1["grade"]["curve"]), "· 끝 1장", S(r1e["grade"]["curve"]), "· 구간", S(r3["grade"]["curve"]))
assert s0 > 0.05
eq = lambda a, b: abs(a - b) < 0.012                                         # noqa: E731  (샘플 노이즈만큼)
assert eq(S(r1["grade"]["curve"]), s0) and eq(S(r1e["grade"]["curve"]), s0), "1장 = 무시(클립 대비 그대로)"
assert "curve" not in r1["gkeys"] and "curve" not in r1e["gkeys"]
assert eq(S(r3["grade"]["curve"]), s0), "클립 커브 = 그대로(예전 = 전체가 약해짐)"
ck = r3["gkeys"]["curve"]
ck = [k for k in ck if k["f"] >= 360]                # (맨 앞에 시작 구간 ◆ 가 더 있을 수 있음 = 클립 커브)
print("가운데 구간 커브 ◆:", [k["f"] for k in ck], [S(k["v"]) for k in ck])
assert [k["f"] for k in ck] == [360, 480, 720, 840]                        # 앞 샘플 · 구간 처음 · 구간 끝 · 뒤 샘플
assert eq(S(ck[0]["v"]), s0) and eq(S(ck[3]["v"]), s0) and S(ck[1]["v"]) == S(ck[2]["v"]) < s0 * 0.7
assert eq(S(curve_at(ck, 0)), s0) and S(curve_at(ck, 600)) < s0 * 0.7 and eq(S(curve_at(ck, 1080)), s0)
ce = [k for k in rend["gkeys"]["curve"] if k["f"] >= 720]
print("끝 구간 커브 ◆:", [k["f"] for k in ce], [S(k["v"]) for k in ce])
assert [k["f"] for k in ce] == [720, 840, 1080] and eq(S(ce[0]["v"]), s0) and S(ce[1]["v"]) < s0 * 0.7 and S(curve_at(ce, 2000)) < s0 * 0.7
# 깊은 구간이 여러 번 = 긴 것부터, 커브 ◆ 전체 8개까지
rm = auto.recommend(clip("ssddssdddssddsssddss"), base, fps=60.0)
assert len(rm["gkeys"]["curve"]) <= auto.CURVE_KEYS_ALL, len(rm["gkeys"]["curve"])
print("여러 구간 커브 ◆:", len(rm["gkeys"]["curve"]))
# 전체가 깊음 = 깊은 수심 프리셋(◆ 없음)
rd = auto.recommend(clip("dddddddd"), base, fps=60.0)
assert rd["preset"] == "deep" and "curve" not in rd["gkeys"]
print("OK test_auto_deeprun")
