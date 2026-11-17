"""v0.17.0 엔진 점검(화면 없음): 수심 그래프 색 2.0초 · 여행 묶음 · 가로·세로 섞임(많은 쪽) · 줌 한도·자석·위치 한도 ·
줌·위치 렌더(원본에서 그 사각형을 직접 자른 화면과 비교) · 세로 클립 → 가로 출력 위아래 이동.
사용: python tests/test_v1700.py [작업폴더]"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import autoedit as A, dive_draw as D, ff, paths  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402

W = Path(sys.argv[1] if len(sys.argv) > 1 else "v1700e_test")
W.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 1) 선 아래 색 = 그래프 시작(2.0초)부터 0.4초
fi = [D.fill_in(D.anim(tc, 20.0)[1]) for tc in (0.0, 1.99, 2.0, 2.2, 2.4, 3.0)]
assert max(fi[:3]) < 1e-3 and abs(fi[3] - 0.5) < 0.02 and fi[4] > 0.999 and fi[5] > 0.999, fi
print("색 디졸브:", [round(x, 2) for x in fi])


# ---------------------------------------------------------------- 2) 여행 묶음 · 섞임
def S(name, w=3840, h=2160, frames=600):
    return Source(path=f"/x/{name}", fps_num=30, fps_den=1, frames=frames, width=w, height=h)


a, b, c, d = S("DJI_20251020094016_0010_D.MP4"), S("DJI_20251021101500_0011_D.MP4"), \
    S("DJI_20260320141000_0020_D.MP4", 2160, 3840), S("clip.mp4")
g = A.trip_groups([], [c, d, b, a])
assert [(h, [s.id for s in ss]) for h, ss in g] == [("2025.10.20 ~ 10.21", [a.id, b.id]), ("2026.03.20", [c.id]), ("", [d.id])], g
print("여행 묶음:", [h for h, _s in g])
assert A.orient_count([a, b, c]) == (2, 1)
assert A.mix_note([a, b]) == "" and A.mix_note([a, b, c]) == "가로 2 · 세로 1 — 세로 1개는 가운데 잘라 넣음"
assert A.mix_note([a, c, S("v2.mp4", 2160, 3840)]) == "가로 1 · 세로 2 — 가로 1개는 가운데 잘라 넣음"
p = Project()
p.sources += [a, b, c]
sg = lambda s: Segment(s.id, 0, 100)  # noqa: E731
assert p.tl_source([sg(c), sg(a), sg(b)]) is a, "세로가 첫 컷이어도 많은 쪽(가로)"
assert p.tl_source([sg(c), sg(a)]) is a, "같으면 가로"
assert p.tl_source([sg(c)]) is c and p.tl_source([]) is None
print("섞임: 출력 = 많은 쪽(같으면 가로)")

# ---------------------------------------------------------------- 3) 줌 한도 · 자석 · 위치 한도
assert ff.zoom_max(a, "horizontal") == 2.0 and ff.zoom_max(a, "horizontal1440") == 1.5 and ff.zoom_max(a, "horizontal2160") == 1.0
assert ff.zoom_max(S("hd.mp4", 1920, 1080), "horizontal") == 1.0
assert abs(ff.zoom_max(a, "vertical") - 1.124) < 0.002        # 4K 가로 → 인스타(1214×2160 → 1080×1920)
zs = [ff.zoom_snap(x, 2.0) for x in (0.9, 1.03, 1.05, 1.47, 1.54, 1.55, 1.97, 2.3)]
assert zs == [1.0, 1.0, 1.05, 1.5, 1.5, 1.55, 2.0, 2.0], zs
assert ff.zoom_snap(1.49, 1.4) == 1.4, "한도 밖 자석은 안 붙음"
assert ff.pan_limits(a, 1.0, "horizontal") == (0.0, 0.0)
assert ff.pan_limits(a, 2.0, "horizontal") == (960.0, 540.0)
lx, ly = ff.pan_limits(c, 1.0, "horizontal")                   # 세로 클립 → 가로 출력: 위아래만, 리프레임 범위(4K = 540)
assert lx == 0.0 and ly == 540.0, (lx, ly)
assert ff.pan_limits(a, 1.0, "vertical")[1] == 0.0 and ff.pan_limits(a, 1.0, "vertical")[0] == 540.0
assert ff.seg_view(a, Segment(a.id, 0, 10), "horizontal") is None
assert ff.seg_view(a, Segment(a.id, 0, 10, zoom=2.0), "horizontal") == (1920, 1080, 960, 540)
assert ff.seg_view(a, Segment(a.id, 0, 10, zoom=2.0, dx=5000, dy=-5000), "horizontal") == (1920, 1080, 1920, 0)
assert ff.seg_view(c, Segment(c.id, 0, 10, dy=300), "horizontal") == (2160, 1214, 0, 1613)
cp = Segment(a.id, 0, 10, zoom=1.5, dx=10, dy=-20).copy()
assert (cp.zoom, cp.dx, cp.dy) == (1.5, 10, -20)
print("줌: 한도 4K→1080 ×2 · 4K→1440 ×1.5 · 자석", zs)


# ---------------------------------------------------------------- 4) 렌더 = 원본에서 그 사각형을 직접 자른 화면
def gray(cmd_in, vf, w, h):
    raw = ff.run([paths.ffmpeg(), "-v", "error", *cmd_in, "-frames:v", "1", "-vf", vf + ",format=gray", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w).astype(float)


def make(name, size):
    f = W / name
    if not f.exists():
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d=1", "-c:v", "libx264",
                        "-preset", "ultrafast", "-qp", "12", "-pix_fmt", "yuv420p", str(f)], check=True)
    info = ff.probe(str(f))
    return Source(path=str(f), **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})


land, port = make("land4k.mp4", "3840x2160"), make("port4k.mp4", "2160x3840")
pr = Project()
pr.sources += [land, port]
pr.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0)
pr.output.encoder, pr.output.gpu_decode = "x264", False
for src, seg, tag in ((land, Segment(land.id, 0, 20, zoom=2.0), "zoom2"),
                      (land, Segment(land.id, 0, 20, zoom=1.5, dx=300, dy=-200), "zoom15pan"),
                      (port, Segment(port.id, 0, 20, dy=400), "port_dy"),
                      (port, Segment(port.id, 0, 20), "port_center")):
    out = W / f"{tag}.mp4"
    ff.render_video(pr, [seg], str(out), orientation="horizontal")
    r = ff.probe(str(out))
    assert (r["width"], r["height"]) == (1920, 1080), r
    v = ff.seg_view(src, seg, "horizontal") or (*ff.crop_size(src.width, src.height, "horizontal"),
                                                (src.width - ff.crop_size(src.width, src.height, "horizontal")[0]) // 2,
                                                (src.height - ff.crop_size(src.width, src.height, "horizontal")[1]) // 2)
    got = gray(["-i", str(out)], "select=eq(n\\,3)", 1920, 1080)
    res = []                                         # 기대 자리와 ±16px 어긋난 자리 중 가장 잘 맞는 곳 = 기대 자리여야 함
    for ox, oy in ((0, 0), (16, 0), (-16, 0), (0, 16), (0, -16)):
        x, y = v[2] + ox, v[3] + oy
        if x < 0 or y < 0 or x + v[0] > src.width or y + v[1] > src.height:
            continue
        exp = gray(["-ss", ff._seek(3, src.fps), "-i", src.path], f"crop={v[0]}:{v[1]}:{x}:{y},scale=1920:1080:flags=lanczos", 1920, 1080)
        res.append((float(np.abs(got - exp).mean()), (ox, oy)))
    best = min(res)
    print(f"{tag}: 자른 사각형 {v} · 가장 맞는 자리 {best[1]} (평균차 {best[0]:.1f} · 나머지 {[round(r_[0], 1) for r_ in sorted(res)[1:]]})")
    assert best[1] == (0, 0) and len(res) >= 3, (tag, res)
# 가로 4K → 세로 출력: 예전 ◆ 리프레임 + 줌이 같이(실행·크기만)
seg = Segment(land.id, 0, 20, zoom=1.1, reframe=[{"f": 0, "dx": -200}, {"f": 19, "dx": 200}])
out = W / "vert_zoom_reframe.mp4"
ff.render_video(pr, [seg], str(out), orientation="vertical")
r = ff.probe(str(out))
assert (r["width"], r["height"]) == (1080, 1920), r
print("OK test_v1700")
