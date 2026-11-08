"""v0.16.19 카메라 프리뷰(LRF) 1·2단계: 짝 찾기 · 자동 판정 · 프리뷰로 프록시(프레임 수 = 원본) · 안 맞으면 원본.
사용: python tests/test_preview.py <작업폴더>  (합성 영상을 만들어 씀, 실제 DJI LRF 아님)"""
import os, shutil, subprocess, sys, time
from fractions import Fraction
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from dtme import ff, paths
from dtme.project import Source

work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/dtme_pv").resolve()
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)

# 테스트 LUT: 대비를 크게(Log → 709 흉내)
lut_name = "test_contrast.cube"
n = 9
with open(paths.lut_dir() / lut_name, "w") as f:
    f.write(f"LUT_3D_SIZE {n}\n")
    for b in range(n):
        for g in range(n):
            for r in range(n):
                c = [min(1.0, max(0.0, (x / (n - 1) - 0.5) * 1.6 + 0.5)) for x in (r, g, b)]
                f.write(f"{c[0]:.5f} {c[1]:.5f} {c[2]:.5f}\n")

FF = paths.ffmpeg()


def mk(out, vf_extra="", size="1280x720", rate="60000/1001", dur=3.0, codec=("libx265", "yuv420p10le"), audio=True, cwd=None):
    src = f"testsrc2=size={size}:rate={rate},eq=contrast=0.4:saturation=0.45{vf_extra}"
    cmd = [FF, "-v", "error", "-y", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000"]
    cmd += ["-t", str(dur), "-c:v", codec[0], "-pix_fmt", codec[1]]
    if codec[0] == "libx265":
        cmd += ["-x265-params", "log-level=error"]
    cmd += (["-c:a", "aac", "-shortest"] if audio else []) + ["-f", "mp4", str(out)]
    subprocess.run(cmd, check=True, cwd=cwd)


def source(p):
    i = ff.probe(str(p))
    return Source(path=str(p), fps_num=i["fps_num"], fps_den=i["fps_den"], frames=i["frames"],
                  width=i["width"], height=i["height"], has_audio=i["has_audio"])


H264 = ("libx264", "yuv420p")
# 1) DJI: 같은 이름 .LRF, 30p, 같은 Log 화면 → 색 'lut'(LUT 를 입혀야 같음)
a = work / "DJI_20261025100118_0148_D.MP4"
mk(a)
mk(work / "DJI_20261025100118_0148_D.lrf", size="640x360", rate="30000/1001", codec=H264)
assert ff.find_preview(str(a)).lower().endswith("_d.lrf"), "DJI 짝 (대소문자 무시)"
sa = source(a)
r = ff.check_preview(sa, lut_name)
print("DJI log:", r)
assert r["ok"] and r["color"] == "lut", r
r0 = ff.check_preview(sa, "")
print("DJI log, LUT 없이:", r0)
assert r0["ok"] and r0["color"] == "raw", r0

t = time.time()
out = ff.make_proxy(sa, lut_name, False)
print(f"프록시(프리뷰) {time.time() - t:.1f}초")
assert ff.frame_count(out) == sa.frames, (ff.frame_count(out), sa.frames)
log = (paths.cache_dir() / "dtme.log").read_text(encoding="utf-8")
assert "프리뷰(LRF" in log.splitlines()[-1], log.splitlines()[-1]

# 2) 프리뷰가 이미 709(대비 큼) → 색 'raw'
b = work / "DJI_20261025100500_0150_D.MP4"
_ref = ff.lut_ref(lut_name)
mk(b)
mk(work / "DJI_20261025100500_0150_D.LRF", vf_extra=f",scale=640:360,format=gbrp16le,lut3d=file={_ref[1]}", size="640x360", rate="30000/1001", codec=H264,
   cwd=_ref[0])   # Windows 경로(D:\\) 는 필터 안에서 깨짐 → 앱처럼 LUT 폴더에서 상대 이름
r = ff.check_preview(source(b), lut_name)
print("DJI 709:", r)
assert r["ok"] and r["color"] == "raw", r

# 3) 길이 다름 → 원본으로
c = work / "DJI_20261025101000_0151_D.MP4"
mk(c)
mk(work / "DJI_20261025101000_0151_D.LRF", size="640x360", rate="30000/1001", codec=H264, dur=2.0)
sc = source(c)
r = ff.check_preview(sc, lut_name)
print("길이 다름:", r)
assert not r["ok"] and "길이" in r["why"]
out = ff.make_proxy(sc, lut_name, False)
assert ff.frame_count(out) == sc.frames
log = (paths.cache_dir() / "dtme.log").read_text(encoding="utf-8").splitlines()
assert any("프리뷰 안 씀" in x and c.name in x for x in log[-3:]) and " CPU " in log[-1], log[-3:]

# 4) 다른 장면(시점·내용 안 맞음) → 색 다름
d = work / "DJI_20261025102000_0152_D.MP4"
mk(d)
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30000/1001", "-t", "3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "mp4", str(work / "DJI_20261025102000_0152_D.LRF")], check=True)
r = ff.check_preview(source(d), lut_name)
print("다른 장면:", r)
assert not r["ok"] and "색" in r["why"], r

# 4-1) 시점: 프리뷰 k = 원본 2k+1 (DJI 실물에서 영상마다 0/1) → shift 1, 프록시 홀수 프레임 = 원본
g = work / "DJI_20261025104000_0154_D.MP4"
mk(g, vf_extra=",scroll=h=0.003", dur=4.0)          # 화면이 옆으로 흐름(움직임)
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60000/1001,eq=contrast=0.4:saturation=0.45,scroll=h=0.003",
                "-t", "4.0", "-vf", "select='mod(n\\,2)',setpts=N*1001/30000/TB", "-r", "30000/1001", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-f", "mp4", str(work / "DJI_20261025104000_0154_D.LRF")], check=True)
sg = source(g)
r = ff.check_preview(sg, "")
print("시점 +1:", {k: r[k] for k in ("ok", "why", "shift", "diff")})
assert r["ok"] and r["shift"] == 1, r
assert ff.check_preview(sa, "")["shift"] == 0
out = ff.make_proxy(sg, "", False)
import numpy as np
def frs(p):
    b = subprocess.run([FF, "-v", "error", "-i", p, "-map", "0:v:0", "-vf", "scale=96:54,format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, check=True).stdout
    return np.frombuffer(b, np.uint8).reshape(-1, 54, 96, 3).astype(np.float32)
O, X = frs(str(g)), frs(out)
same = np.mean([abs(X[j] - O[j]).mean() for j in range(41, 81, 2)])        # 홀수 = 같은 화면
prev = np.mean([abs(X[j] - O[j - 1]).mean() for j in range(40, 80, 2)])    # 짝수 = 바로 앞 화면
nxt = np.mean([abs(X[j] - O[j + 1]).mean() for j in range(40, 80, 2)])     # (미래 화면이면 이쪽이 작음 = 틀림)
print(f"프록시↔원본 홀수 같은 화면 {same:.1f} · 짝수↔앞 {prev:.1f} · 짝수↔뒤 {nxt:.1f}")
assert same < 0.8 * nxt and prev < 0.8 * nxt, (same, prev, nxt)

# 5) 없음 · GoPro · Insta360 이름 규칙
e = work / "DJI_20261025103000_0153_D.MP4"
mk(e, audio=False, dur=1.0)
assert ff.find_preview(str(e)) is None and ff.check_preview(source(e), "")["why"] == "없음"
(work / "GX010123.MP4").write_bytes(b"")
(work / "GL010123.LRV").write_bytes(b"")
assert ff.find_preview(str(work / "GX010123.MP4")).endswith("GL010123.LRV")
(work / "VID_20240801_154541_00_012.mp4").write_bytes(b"")
(work / "LRV_20240801_154541_01_012.lrv").write_bytes(b"")
assert ff.find_preview(str(work / "VID_20240801_154541_00_012.mp4")).endswith("LRV_20240801_154541_01_012.lrv")

(paths.lut_dir() / lut_name).unlink()
print("OK test_preview")
