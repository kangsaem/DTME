"""v0.17.2 엔진: 끝 화면 직접 쓴 문구 크기(자동과 같은 규칙) · 미리보기 렌더(fast) = 카메라 프리뷰(LRF)에서 읽음 · 수심 그래프 시간 로그.
사용: python tests/test_v1720.py [작업 폴더]"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np  # noqa: E402
from dtme import autoedit as A, ff, paths  # noqa: E402
from dtme.project import DEFAULT_LUT, Project, Segment, Source  # noqa: E402

d = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="dtme_v1720_")
os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------- 1) 끝 문구: 직접 쓴(고친) 글도 80·64·64(예전 64·40·40)
assert [x[1] for x in A.end_lines(True, [], "", "", "7 DIVES · MAX 34.8m · 5h 37m / DTMR / 2026.10.25 ~ 10.27")] == [80, 64, 64]
assert [x[1] for x in A.end_lines(False, [], "", "", "Bohol / 2025.10.20")] == [64, 64]         # 다이빙 줄 없음 = 자동(LOG 없음)과 같음
assert A.end_lines(False, [], "", "", "Bye") == [("Bye", 80, True)]                              # 한 줄 = 80
assert [x[1] for x in A.end_lines(False, [], "Bohol", "2025.10.20")] == [64, 64]

# ---------------------------------------------------------------- 2) 미리보기 렌더 = LRF 에서(판정 저장된 것만 · 색 'lut')
ffm = paths.ffmpeg()
big = os.path.join(d, "DJI_20251020094000_0001_D.MP4")
lrf = os.path.join(d, "DJI_20251020094000_0001_D.LRF")
if not os.path.exists(big):
    subprocess.run([ffm, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=60000/1001:d=8", "-c:v", "libx264", "-preset",
                    "ultrafast", "-g", "30", "-pix_fmt", "yuv420p", big], check=True)
    subprocess.run([ffm, "-v", "error", "-y", "-i", big, "-vf", "fps=30000/1001,scale=1280:720", "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "30", "-pix_fmt", "yuv420p", "-f", "mp4", lrf], check=True)
pr = ff.probe(big)
src = Source(big, 60000, 1001, int(pr["frames"]))
src.width, src.height = 1920, 1080
p = Project()
p.sources.append(src)
src.grade["lut"] = DEFAULT_LUT
p.output.encoder = "x264"
p.output.gpu_decode = False
pv = ff.preview_info(src, DEFAULT_LUT)                      # 판정(저장) — 편집 화면 프록시 때 하는 것
print("판정:", pv and {k: pv[k] for k in ("color", "shift", "ratio", "fps_num", "fps_den")})
assert pv and pv["color"] == "lut" and pv["ratio"] == 2
g1 = Segment(src.id, 60, 240)
g2 = Segment(src.id, 300, 420); g2.trans = {"type": "dissolve", "dur": 0.5}
seen = []
_popen = ff._popen


def spy(cmd, **kw):
    seen.append([os.path.basename(cmd[i + 1]) for i, x in enumerate(cmd) if x == "-i"])
    return _popen(cmd, **kw)


for fast in (True, False):
    out = os.path.join(d, f"fast_{fast}.mp4")
    seen.clear()
    ff._popen = spy
    ff._ctx.fast_pv = []
    try:
        ff.render_video(p, [g1, g2], out, None, None, "horizontal", False, fast=fast)
    finally:
        ff._popen = _popen
    ins = [x for c in seen for x in c if x.endswith((".LRF", ".MP4"))]
    print("fast" if fast else "보통", "입력:", ins, "· 프리뷰", ff._ctx.fast_pv)
    if fast:
        assert ins and all(x.endswith(".LRF") for x in ins) and ff._ctx.fast_pv == ["LRF", "LRF"]
    else:
        assert ins and all(x.endswith(".MP4") for x in ins)
    ff._ctx.fast_pv = None
# 같은 화면(LRF = 같은 시각 · 같은 색): 컷 가운데 프레임 밝기
fa, fb = (os.path.join(d, f"fast_{x}.mp4") for x in (True, False))
assert abs(float(ff.probe(fa)["duration"]) - float(ff.probe(fb)["duration"])) < 0.1


def frame(f, t):
    r = subprocess.run([ffm, "-v", "error", "-ss", f"{t}", "-i", f, "-frames:v", "1", "-vf", "scale=96:54", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).astype(float)


for t in (1.0, 3.5):
    a, b = frame(fa, t), frame(fb, t)
    diff = float(np.abs(a - b).mean())
    print(f"{t}초 차", round(diff, 1))
    assert diff < 12, diff
# 프리뷰 판정이 없으면(저장 안 됨) = 원본(여기서 새로 판정하지 않음)
ff._pv_cache.clear()
ff._pv_load = lambda: None
seen.clear(); ff._popen = spy
try:
    ff.render_video(p, [g1], os.path.join(d, "fast_nopv.mp4"), None, None, "horizontal", False, fast=True)
finally:
    ff._popen = _popen
assert all(x.endswith(".MP4") for c in seen for x in c if x.endswith((".LRF", ".MP4")))

# ---------------------------------------------------------------- 3) 수심 그래프 시간 로그(stat)
from dtme import dive_draw  # noqa: E402
assert "저장 기다림" in open(dive_draw.__file__, encoding="utf-8").read()
print("OK test_v1720", flush=True)
