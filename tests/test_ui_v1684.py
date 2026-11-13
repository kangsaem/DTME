"""v0.16.84 UI: 다이빙 기록 끌어다 놓기(편집 화면) → [수심]·시각 칸 · 미리보기 그래프 · 자동 편집 창 체크(컷 최소 10초) · 회전 줌 제한.
사용: python tests/test_ui_v1684.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from fitgen import make_fit, profile  # noqa: E402
from dtme import autoedit, paths  # noqa: E402
from dtme.project import Segment  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
v = os.path.join(W, "DJI_20261027104000_0001_D.MP4")              # 10:40:00 = 다이빙 안
v2 = os.path.join(W, "DJI_20261027120000_0002_D.MP4")             # 12:00 = 다이빙 밖(수면 휴식)
for f in (v, v2):
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1c5a8a:s=640x360:r=30:d=40",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", f], check=True)
st0 = int(datetime(2026, 10, 27, 1, 30, tzinfo=timezone.utc).timestamp())
fit = os.path.join(W, "teric.fit")
open(fit, "wb").write(make_fit([(st0, profile(40, 22))]))
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
assert not e.b_dive.isVisible()
e.import_files([v, v2, fit])
assert wait(60, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
p = st.project
print("다이빙", len(p.dives), "상태줄", e.status.text())
assert len(p.dives) == 1 and e.b_dive.isVisible() and e.dive_off.isVisible() and "다이빙 기록 1개" in e.status.text()
s1, s2 = sorted(p.sources, key=lambda s: s.path)
assert autoedit.dive_src(p, s1) and not autoedit.dive_src(p, s2)
# 미리보기: 타임라인에 다이빙 컷 → 모니터에 그래프(멈춤 = 다 보임)
p.segments = [Segment(s1.id, 0, 600), Segment(s2.id, 0, 300)]
st.touch("segments"); wait(0.3)
e.set_mode("timeline"); wait(0.3)
e.show_timeline(5.0); wait(0.5)
dv = e.player.mon.dive
print("모니터:", dv[1] if dv else None, dv[3] if dv else None)
assert dv is not None and abs(dv[1] - (9 * 60 + 5)) < 0.2 and dv[4:] == (1.0, 1.0, 1.0)
img = e.player.mon.grab().toImage()
assert not img.isNull()
e.show_timeline(25.0); wait(0.3)                   # 둘째 컷 = 다이빙 밖 → 없음
assert e.player.mon.dive is None
# 시각 맞춤 +60초 → 점 1분 뒤
e.dive_off.setValue(60); wait(0.2)
e.show_timeline(5.0); wait(0.3)
assert abs(e.player.mon.dive[1] - (10 * 60 + 5)) < 0.2
# [수심] 끄기 → 없음 · 시각 칸 숨김
e.b_dive.click(); wait(0.2)
assert not p.dive_on and e.player.mon.dive is None and not e.dive_off.isVisible()
e.b_dive.click(); wait(0.2)
assert p.dive_on
# 자동 편집 창: 체크칸(다이빙 1개 · 기본 켬)
from dtme.ui_autoedit import AutoEditDialog  # noqa: E402
d = AutoEditDialog(st, {s1.id, s2.id}, w)
print("체크:", d.dive_on.text(), d.dive_on.isChecked())
assert d.dive_on.isEnabled() and d.dive_on.isChecked() and "다이빙 1개" in d.dive_on.text() and d.settings()["dive"]
# 컷 최소 10초(다이빙 소스) · 다이빙 밖은 그대로
assert autoedit.dive_lens([6.0, 7.0, 8.0], 40.0) == [10.5, 10.5]
assert autoedit.dive_lens([12.0], 40.0) == [12.0] and autoedit.dive_lens([6.0], 8.0) == [8.0]
import numpy as np  # noqa: E402
picks = [{"src": s1, "scene": "", "score": np.ones(80), "surface": None},
         {"src": s2, "scene": "", "score": np.ones(80), "surface": None}]
plan = autoedit.build(p, picks, 1, seed=3, titles=True, cut_max=[6.0, 6.0])
lens = [((g.fout - g.fin) / 30.0, g.src) for g in plan["segs"]]
print("컷:", [(round(a, 1), "다이빙" if s == s1.id else "밖") for a, s in lens])
assert all(a >= 9.99 for a, s in lens if s == s1.id) and any(a < 9.99 for a, s in lens if s == s2.id)
assert all(t.get("text") != "2026 1027 1040" for t in plan["titles"])     # 다이빙 컷 = 날짜 사각형 안 넣음
# 회전 줌: 최대 2번 · 연달아 안 씀
for seed in range(30):
    pl = autoedit.build(p, picks * 6, 10, seed=seed, titles=False)
    ks = [(g.trans or {}).get("type", "") for g in pl["segs"]]
    rz = [k.startswith("rotzoom") for k in ks]
    assert sum(rz) <= 2 and not any(a and b for a, b in zip(rz, rz[1:])), ks
print("OK test_ui_v1684", flush=True); os._exit(0)
