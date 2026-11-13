"""v0.16.78 세로 촬영(회전 정보) 원본 = GPU 프레임 경로(-hwaccel_output_format cuda) 안 씀 — ffmpeg 이 자동 회전을 못 해 누운 채로
읽혀 눌린 그림 + 회전 정보가 남던 것(사용자 렌더). GPU 없이 명령만 확인.
사용: python tests/test_rotate_gpu.py <작업폴더>"""
import os, subprocess, sys  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from dtme import ff, paths
from dtme.project import Project, Segment, Source
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
FF = paths.ffmpeg()
land = os.path.join(W, "land.mp4"); vert = os.path.join(W, "vert.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", land], check=True)
subprocess.run([FF, "-v", "error", "-y", "-display_rotation", "90", "-i", land, "-c", "copy", vert], check=True)
p = Project(); p.output.gpu_decode = True; p.output.encoder = "x264"
srcs = {}
for f in (land, vert):
    i = ff.probe(f)
    s = Source(path=f, **{k: i[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    s.rotation = int(i.get("rotation", 0)); s.grade = {"lut": ""}
    p.sources.append(s); srcs[f] = s
assert srcs[vert].rotation and ff.may_rotate(srcs[vert]) and not ff.may_rotate(srcs[land])
ff.has_cuda = lambda: True                                   # GPU 있다고 치고 명령만
for f, orient, want in ((land, "horizontal", True), (vert, "vertical", False)):
    s = srcs[f]
    cmd = ff.build_render_cmd(p, [Segment(s.id, 0, s.frames)], os.path.join(W, "o.mp4"), orient, False)[0]
    got = "-hwaccel_output_format" in cmd
    print(os.path.basename(f), orient, "GPU 프레임 경로", got)
    assert got == want, (f, got)
print("OK test_rotate_gpu", flush=True)
