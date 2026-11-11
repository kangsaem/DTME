"""v0.16.34 커브 ◆: 시작 구간 샘플(0·1·2·3·5초) · 안정 전 커브 키(최대 3) · 렌더 sendcmd · 보정 패널 커브 ◆.
사용: QT_QPA_PLATFORM=offscreen python tests/test_curvekeys.py"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import auto, ff  # noqa: E402
from dtme.project import CURVE_KEY, Segment, Source, curve_at, grade_at  # noqa: E402

FPS = 30.0
src = Source(path="x.mp4", fps_num=30, fps_den=1, frames=int(60 * FPS), width=1920, height=1080, id="s1")

# 1) 샘플 위치: 인점 + 1·2·3·5초 포함
fr = auto.sample_frames(src, a=0, b=src.frames)
for t in (0, 1, 2, 3, 5):
    assert any(abs(f - t * FPS) <= FPS * 0.1 for f in fr), (t, fr)
assert fr == sorted(fr) and len(set(fr)) == len(fr)
print("samples", [round(f / FPS, 1) for f in fr])

# 2) 시작이 어두운 클립 → 커브 ◆(인점 ~ 안정 지점, 최대 3)
rng = np.random.default_rng(0)


def img(level):
    a = rng.random((90, 160, 3)).astype(np.float32) * 0.6 + 0.2
    a *= np.array([0.6, 1.0, 1.0], np.float32)
    return np.clip(a * level, 0, 1)


lev = {0: 0.6, 1: 0.72, 2: 0.85, 3: 0.97}
smp = [(f, img(lev.get(int(round(f / FPS)), 1.0))) for f in fr]
base = {"lut": ""}
r = auto.recommend(smp, base, "shallow", None, "mid", fps=FPS)
ck = r["gkeys"].get(CURVE_KEY)
assert ck and 2 <= len(ck) <= 3, ck
assert ck[0]["f"] == 0 and ck[-1]["v"] == r["grade"]["curve"]
assert ck[-1]["f"] <= 5 * FPS + 1, ck[-1]["f"]
print("curve keys", [k["f"] for k in ck])
c0 = np.array(ck[0]["v"]); assert c0.shape[1] == 2
# 시작 커브가 더 밝게 펴는 쪽(같은 입력에서 출력이 큼)
from dtme.project import spline_eval  # noqa: E402
assert spline_eval(ck[0]["v"], [0.4])[0] > spline_eval(r["grade"]["curve"], [0.4])[0]

# 안정된 클립 = 커브 ◆ 없음
smp2 = [(f, img(1.0)) for f in fr]
r2 = auto.recommend(smp2, base, "shallow", None, "mid", fps=FPS)
assert CURVE_KEY not in r2["gkeys"], r2["gkeys"].keys()
# fps 모름(이전 호출) = 커브 ◆ 없음
assert CURVE_KEY not in auto.recommend(smp, base, "shallow", None, "mid")["gkeys"]

# 2b) v0.16.38 시작 구간 색 ◆: 빨강이 0초 1/3 → 5초에 자리 잡음 = 빨강·파랑 ◆(최대 3 + 자리 잡은 지점), 빨강 시작 ≤ 1.8배
def img_c(rk):
    a = rng.random((90, 160, 3)).astype(np.float32) * 0.6 + 0.2
    return np.clip(a * np.array([0.6 * rk, 1.0, 1.0 + 0.2 * (1 - rk)], np.float32), 0, 1)


ramp = {0: 0.33, 0.5: 0.45, 1: 0.55, 2: 0.7, 2.5: 0.78, 3: 0.86, 5: 1.0}
smp3 = [(f, img_c(ramp.get(round(f / FPS * 2) / 2, 1.0))) for f in fr]
r3 = auto.recommend(smp3, base, "shallow", None, "mid", fps=FPS)
rk3 = r3["gkeys"].get("r_gain")
print("색 ◆ 빨강:", rk3, "파랑:", r3["gkeys"].get("b_gain"))
assert rk3 and rk3[0]["f"] == 0 and len([k for k in rk3 if k["f"] <= 5 * FPS]) <= 4
settle = [k for k in rk3 if k["f"] <= 5 * FPS][-1]
assert rk3[0]["v"] > settle["v"] * 1.2 and rk3[0]["v"] <= max(settle["v"], min(1.6, settle["v"] * 1.4)) + 1e-3, (rk3[0], settle)
sk3 = r3["gkeys"].get("sat")                                  # v0.16.42 채도 ◆: 시작 낮게 → 자리 잡은 지점 = 클립 채도
assert sk3 and sk3[0]["v"] < sk3[-1]["v"] and sk3[0]["v"] >= sk3[-1]["v"] - 0.2 - 1e-6 and sk3[-1]["v"] == r3["grade"]["sat"], sk3
ck3 = r3["gkeys"].get(CURVE_KEY)                              # 밝기 맞춤: 시작 커브가 클립 커브보다 밝게, γ 0.8 까지만
assert ck3 and ck3[-1]["f"] >= settle["f"], ck3
from dtme.project import spline_eval as _se  # noqa: E402
y0, y1 = _se(ck3[0]["v"], [0.4])[0], _se(curve_at(ck3, settle["f"]), [0.4])[0]
print("채도 ◆:", sk3, "· 커브 0.4 →", round(y0, 3), "(자리 잡은 뒤", round(y1, 3), ")")
assert y0 >= y1 - 1e-6
assert r3["gkeys"]["b_gain"][0]["v"] < [k for k in r3["gkeys"]["b_gain"] if k["f"] == settle["f"]][0]["v"]
# 색이 안정된 클립 = 색 ◆ 없음
assert "r_gain" not in auto.recommend([(f, img_c(1.0)) for f in fr], base, "shallow", None, "mid", fps=FPS)["gkeys"]

# 3) grade_at / 렌더 sendcmd
g = grade_at(dict(r["grade"]), r["gkeys"], ck[-1]["f"] + 100)
assert g["curve"] == r["grade"]["curve"]
mid = curve_at(ck, ck[-1]["f"] // 2)
assert len(mid) >= 2
seg = Segment("s1", 0, src.frames, 1.0, gkeys=r["gkeys"])
cmds = ff.gkey_cmds(dict(r["grade"]), seg, src, src.frames, FPS)
assert "curves@g" in cmds, cmds[:300]

# 4) 보정 패널 커브 ◆ (짧은 합성 영상)
import os, subprocess, tempfile, time  # noqa: E401,E402
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from dtme import paths  # noqa: E402
mp4 = os.path.join(tempfile.mkdtemp(), "ck_ui.mp4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4], check=True)
from PySide6.QtWidgets import QApplication  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import main as M  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
app = QApplication.instance() or QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond():
            return True


st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([mp4]); wait(30, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
s = st.project.sources[0]
assert CURVE_KEY in gp.kbtn
e.player.seek(10); wait(0.3)
gp.kbtn[CURVE_KEY].click(); wait(0.2)
assert [k["f"] for k in s.gkeys[CURVE_KEY]] == [10] and isinstance(s.gkeys[CURVE_KEY][0]["v"], list)
e.player.seek(60); wait(0.3)
gp.curve.set_points([[0, 0], [0.5, 0.7], [1, 1]]); gp.curve.changed.emit(gp.curve.points()); wait(0.3)
assert [k["f"] for k in s.gkeys[CURVE_KEY]] == [10, 60], s.gkeys[CURVE_KEY]
e.player.seek(35); wait(0.3)
y = spline_eval(gp.curve.points(), [0.5])[0]
assert 0.52 < y < 0.68, y                       # 두 키 사이 = 보간된 커브 표시
print("소스 바 ◆:", e.sbar.gkeys); assert e.sbar.gkeys == [10, 60]
e.player.seek(60); wait(0.3); gp.kbtn[CURVE_KEY].click(); wait(0.2)
assert [k["f"] for k in s.gkeys[CURVE_KEY]] == [10]
w.undo(); wait(0.3); s = st.project.sources[0]
assert len(s.gkeys[CURVE_KEY]) == 2
print("OK curvekeys")
os._exit(0)
