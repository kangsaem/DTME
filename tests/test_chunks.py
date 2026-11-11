"""v0.16.26 점검: 조각 렌더 = 통째 렌더와 같은 결과(무손실로 비교).
- 출력 프레임 수 같음 · 프레임마다 화면 차(특히 조각 경계) · 소리 길이 · ◆(색 키프레임) 위치
- 배속 x1 · x2 · x1/2, 인/아웃 구간, 세로(리프레임)
사용: python tests/test_chunks.py <작업폴더>"""
import os as _os0
_os0.environ.setdefault("DTME_HW", "nvenc")     # GPU 명령 모양 시험(v0.16.48: 그래픽 판별을 건너뜀)
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
from dtme import ff, auto, paths, project as P
from dtme.project import Project, Source, Segment, set_setting

WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
clip = os.path.join(WORK, "DJI_20261109120000_0001_D.MP4")
if not os.path.exists(clip):      # 1080p 59.94 10bit HEVC 12초, 움직임 + 색이 시간에 따라 변함 + 소리
    ff.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=60000/1001:d=12,hue=h=20*t,noise=alls=12:allf=t",
            "-f", "lavfi", "-i", "sine=f=440:d=12", "-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
            "-x265-params", "keyint=30:log-level=error", "-c:a", "aac", "-shortest", clip])
info = ff.probe(clip)
s = Source(path=clip, frames=info["frames"])
for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio"):
    setattr(s, k, info[k])
p = Project(); p.sources.append(s); p.output.gpu_decode = False
base = dict(p.grade); base["lut"] = P.DEFAULT_LUT
r = auto.recommend(auto.grab_samples(s, P.DEFAULT_LUT, use_preview=False), base)
s.grade = {k: v for k, v in r["grade"].items() if p.grade.get(k) != v}
s.gkeys = {"r_gain": [{"f": 60, "v": 1.0}, {"f": 400, "v": 1.4}, {"f": 650, "v": 0.9}]}     # 조각 경계를 지나는 ◆
ff.TEST_LOSSLESS = True
set_setting("chunk_max", 0)                        # 이전 실행이 중간에 멈췄어도 기본으로
ff.CHUNK_MIN_SEC = 2.5


def frames_of(path):
    w, h = 320, 180
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", path, "-vf", f"scale={w}:{h}:flags=neighbor,format=rgb24", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16)


def adur(path):
    import json
    d = json.loads(ff.run([paths.ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "json", path]))
    return float(d["streams"][0]["duration"])


ok = True
for name, fin, fout, speed, orient in [("x1", 0, s.frames, 1.0, "horizontal"), ("x2 구간", 30, 690, 2.0, "horizontal"),
                                        ("x0.5 구간", 100, 400, 0.5, "horizontal"), ("세로", 0, s.frames, 1.0, "vertical")]:
    seg = p.snap_seg(Segment(s.id, fin, fout, speed))
    if orient == "vertical":
        seg.reframe = [{"f": 0, "dx": -200}, {"f": 600, "dx": 200}]
    plan = ff.chunk_plan(p, [seg], orient, None)
    assert plan and len(plan) >= 2, f"{name}: 조각 안 됨"
    a, b = os.path.join(WORK, f"whole_{name}.mp4"), os.path.join(WORK, f"chunk_{name}.mp4")
    set_setting("chunk_max", 1)                     # 통째
    assert ff.chunk_plan(p, [seg], orient, None) is None
    t = time.time(); ff.render_video(p, [seg], a, orientation=orient, audio=True); tw = time.time() - t
    set_setting("chunk_max", 0)                     # 기본(조각)
    t = time.time(); ff.render_video(p, [seg], b, orientation=orient, audio=True); tc = time.time() - t
    A, B = frames_of(a), frames_of(b)
    bounds, acc = [], 0
    for _sub, _drop, nout in plan[:-1]:
        acc += nout; bounds.append(acc)
    if len(A) != len(B):
        print(f"{name}: 프레임 수 다름 {len(A)} / {len(B)}"); ok = False; continue
    d = np.abs(A - B).mean(axis=(1, 2, 3))
    near = [d[max(0, x - 2):x + 3].max() for x in bounds]
    print(f"{name}: 조각 {len(plan)}개 · 프레임 {len(A)} · 화면 차 평균 {d.mean():.3f} 최대 {d.max():.3f} "
          f"(경계 ±2 최대 {max(near):.3f}) · 소리 {adur(a):.3f}/{adur(b):.3f}초 · 시간 통째 {tw:.1f} / 조각 {tc:.1f}초")
    if d.max() > 1.0 or abs(adur(a) - adur(b)) > 0.03:
        ok = False
set_setting("chunk_max", 0)
# v0.16.28: GPU 축소 명령 모양 · GPU 없는 환경에서는 실패 → CPU 로 넘어가도 결과 같음
p.output.gpu_decode = True
seg = p.snap_seg(Segment(s.id, 0, s.frames, 1.0))
cmd, _t, _c = ff.build_render_cmd(p, [seg], os.path.join(WORK, "x.mp4"), "horizontal", False)
js = " ".join(cmd)
print("GPU 축소 명령:", "scale_cuda" in js, "-hwaccel_output_format" in js)
assert "scale_cuda=1920:1080" in js and "hwdownload" in js and "-hwaccel_output_format" in js
cmdv, _t, _c = ff.build_render_cmd(p, [seg], os.path.join(WORK, "x.mp4"), "vertical", False)
assert "scale_cuda" not in " ".join(cmdv), "세로(크롭 필요) = CPU 축소"
c = os.path.join(WORK, "chunk_gpu.mp4")
ff.render_video(p, [seg], c, orientation="horizontal", audio=True)
G = frames_of(c); A0 = frames_of(os.path.join(WORK, "whole_x1.mp4"))
dd = np.abs(G - A0).mean(axis=(1, 2, 3)) if len(G) == len(A0) else np.array([99.0])
print(f"GPU 켬(시험 환경은 GPU 없음 → CPU 로 넘어감): 프레임 {len(G)}/{len(A0)} 차 최대 {dd.max():.3f}")
ok = ok and len(G) == len(A0) and dd.max() <= 1.0
p.output.gpu_decode = False
assert ok, "조각 렌더 결과가 통째와 다름"
print("OK test_chunks")
