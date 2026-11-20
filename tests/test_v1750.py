"""v0.17.5 ① 물속 판정 = 다이빙 기록 수심 먼저(≥ 1m = 무조건 물속) + 판정 화면 = LUT 입힌 화면
② 수심 그래프 그리기 = 스레드 풀(그림 파일이 스레드 1개와 같은지 · 시간).
사용: python tests/test_v1750.py <작업폴더>"""
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
sys.path.insert(0, str(HERE))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtGui import QGuiApplication  # noqa: E402
app = QGuiApplication(sys.argv)
from fitgen import make_fit, profile  # noqa: E402
from dtme import autoedit, divelog as DL, dive_draw, ff, music, paths  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402

W = Path(sys.argv[1] if len(sys.argv) > 1 else "v1750_test")
W.mkdir(parents=True, exist_ok=True)
FF = paths.ffmpeg()


def naive(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


def clip(name, color, sec, size="640x360", audio=False):
    v = W / name
    cmd = [FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30:d={sec}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"anoisesrc=d={sec}:a=0.002"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(v)]
    subprocess.run(cmd, check=True)
    i = ff.probe(str(v))
    return Source(path=str(v), **{k: i[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})


# 다이빙: 10:31 하강 시작(KST) · 40분 · 최대 22m
st = int(naive(2026, 10, 27, 1, 30, 0))
fit = W / "dive.fit"
fit.write_bytes(make_fit([(st, profile(40, 22))]))
ds = DL.read_dives(str(fit))
assert len(ds) == 1

# ---------------------------------------------------------------- ① 물속 판정
SAND = "0xd8c7a6"                       # 얕은 흰 모래 바닥 흉내(붉은 기 많음 · 물색 적음) = 색만 보면 '수면 위'
s_in = clip("DJI_20261027104000_0001_D.MP4", SAND, 6, audio=True)    # 10:40 = 다이빙 9분(깊음)
s_out = clip("DJI_20261027120000_0002_D.MP4", SAND, 6, audio=True)   # 12:00 = 다이빙 끝난 뒤(기록 없음)
g_in, g_out = Segment(s_in.id, 0, s_in.frames, 1.0), Segment(s_out.id, 0, s_out.frames, 1.0)
assert music.above_water(music._look(s_in.path, 1.0))[0], "흰 모래 = 색으로는 수면 위(시험 전제)"
dep = music.log_depth(s_in, g_in, ds, 0.0)
assert dep is not None and dep >= 1.0, dep
assert music.log_depth(s_out, g_out, ds, 0.0) is None
r = music.cut_scene(s_in, g_in, ds, 0.0)
print("기록 있음:", r)
assert r["up"] is False and r["why"] == "물속" and r["depth"] == dep and "rg" not in r      # 색·소리 안 봄
r2 = music.cut_scene(s_out, g_out, ds, 0.0)
print("기록 없음:", r2)
assert r2["up"] is True and r2["why"] == "수면 위"                                         # 기록 없을 때만 색
assert music.cut_scene(s_in, g_in)["why"] == "수면 위"                                    # 기록 안 줌 = 예전과 같음
# 수면(1m 미만) = 색으로: 입수 직후(10:31:01 쯤 = 수심 0.2m 안팎) 클립
s_sh = clip("DJI_20261027103100_0003_D.MP4", SAND, 2, audio=True)
g_sh = Segment(s_sh.id, 0, s_sh.frames, 1.0)
d_sh = music.log_depth(s_sh, g_sh, ds, 0.0)
print("얕음:", d_sh)
assert d_sh is not None and d_sh < 1.0 and music.cut_scene(s_sh, g_sh, ds, 0.0)["why"] == "수면 위"

# 판정 화면 = LUT 입힌 화면: 원본(프록시·LRF 없음) + LUT = 색이 바뀜
lut = "DJI_OSMO_Action_4_D-Log_M_to_Rec.709_V1.cube"
src_lut = Path(__file__).resolve().parents[1] / "luts" / lut
dst = paths.lut_dir() / lut
if not dst.exists():
    dst.write_bytes(src_lut.read_bytes())
vid, ref, at, kind = music._look_src(s_out, lut)
assert kind == "원본" and ref is not None and abs(at(30) - 1.0) < 1e-6, (kind, ref)
a0, a1 = music._look(vid, 1.0), music._look(vid, 1.0, ref)
assert a0 is not None and a1 is not None and float(abs(a0 - a1).mean()) > 0.02, float(abs(a0 - a1).mean())
assert music.cut_scene(s_out, g_out, ds, 0.0, lut)["look"] == "원본"
s_px = clip("proxy_src.MP4", SAND, 2)
s_px.proxy = s_px.path
assert music._look_src(s_px, lut)[3] == "프록시" and music._look_src(s_px, lut)[1] is None     # 프록시 = 이미 LUT 입혀 있음
print("판정 화면 LUT: OK")

# 자동 편집 '물 밖(surface)' 자리도 기록 수심 먼저
p = Project()
p.sources += [s_in, s_out]
p.dives = ds
picks = [{"src": s, "scene": "", "score": None, "surface": [True] * 20} for s in (s_in, s_out)]
plan = autoedit.build(p, picks, 0, total=8.0, titles=False)
sc = {p.source(g.src).path: plan["scenes"][g.id] for g in plan["segs"]}
print("장면:", {Path(k).name: v for k, v in sc.items()})
assert sc[s_in.path] != "surface" and sc[s_out.path] == "surface"
p.dives = []
plan = autoedit.build(p, picks, 0, total=8.0, titles=False)
assert all(v == "surface" for v in plan["scenes"].values())
print("① OK")

# ---------------------------------------------------------------- ② 수심 그래프 = 스레드 풀 · 결과 같음
big = clip("DJI_20261027104100_0004_D.MP4", "0x1c5a8a", 40, size="1920x1080")
pr = Project()
pr.sources.append(big)
segs = [Segment(big.id, 0, 600), Segment(big.id, 600, 1200)]
spans = [(0.0, 20.0, segs[0], 0.5), (20.0, 40.0, segs[1], 0.0)]


def run(n, folder):
    keep = dive_draw.draw_workers
    dive_draw.draw_workers = lambda: n
    try:
        t0 = time.monotonic()
        out = dive_draw.render_layers(pr, ds, 0.0, spans, 40.0, 1920, 1080, W / folder)
        return out, time.monotonic() - t0
    finally:
        dive_draw.draw_workers = keep


o1, t1 = run(1, "lay1")
oN, tN = run(16, "layN")
print(f"그리기: 스레드 1개 {t1:.1f}초 · 16개 {tN:.1f}초 · {oN['stat']}")
assert "스레드 16개" in oN["stat"]
for kind in ("txt", "gr", "mul", "add", "pulse"):
    l1 = Path(o1[kind]).read_text(encoding="utf-8").replace("/lay1/", "/X/")
    lN = Path(oN[kind]).read_text(encoding="utf-8").replace("/layN/", "/X/")
    assert l1 == lN, kind
f1 = sorted((W / "lay1").glob("*.png"))
fN = sorted((W / "layN").glob("*.png"))
assert [f.name for f in f1] == [f.name for f in fN] and len(f1) > 50, (len(f1), len(fN))
from PySide6.QtGui import QImage  # noqa: E402
bad = []
for a, b in zip(f1, fN):
    if hashlib.sha1(a.read_bytes()).digest() != hashlib.sha1(b.read_bytes()).digest():
        ia, ib = QImage(str(a)), QImage(str(b))
        if ia.size() != ib.size() or bytes(ia.constBits()) != bytes(ib.constBits()):
            bad.append(a.name)
assert not bad, bad[:5]
print(f"그림 {len(f1)}장 픽셀 같음")
print("OK test_v1750")
