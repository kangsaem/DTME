"""색 키프레임(sendcmd) 렌더 점검: 프레임마다 값이 바뀌는지, 같은 프레임의 정지값 렌더와 같은지.
사용: python tests/test_gkeys.py <4K테스트.mp4> <작업폴더>"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, paths  # noqa: E402
from dtme.project import OUT_FPS, Project, Segment, Source, grade_at  # noqa: E402


def mean_rgb(f, n, w, h):
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(f), "-frames:v", "1", "-vf",
                  f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).reshape(-1, 3).astype(float).mean(0)


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, hue=0, sat=1.0, r_gain=1.0, b_gain=1.0)
    p.output.encoder, p.output.gpu_decode = "x264", False
    gk = {"r_gain": [{"f": 10, "v": 0.8}, {"f": 90, "v": 1.6}], "sat": [{"f": 10, "v": 1.0}, {"f": 90, "v": 1.5}]}
    seg = Segment(src.id, 0, 110, 1.0, gkeys=gk)
    f = d / "gk.mp4"
    ff.render_video(p, [seg], str(f), orientation="horizontal")
    worst = 0
    for n in (2, 25, 50):
        srcf = n * float(src.fps) / float(OUT_FPS)
        g = grade_at(dict(p.grade), gk, srcf)
        ref = d / f"ref_{n}.mp4"
        ff.render_video(p, [Segment(src.id, int(round(srcf)), int(round(srcf)) + 2, 1.0)], str(ref), orientation="horizontal")
        # 정지값 렌더(그 프레임 값으로 고정)
        p2 = Project(); p2.sources.append(src); p2.grade.update(p.grade); p2.grade.update({k: g[k] for k in ("r_gain", "sat")})
        p2.output.encoder, p2.output.gpu_decode = "x264", False
        ff.render_video(p2, [Segment(src.id, int(round(srcf)), int(round(srcf)) + 2, 1.0)], str(ref), orientation="horizontal")
        a, b = mean_rgb(f, n, 1920, 1080), mean_rgb(ref, 0, 1920, 1080)
        print(f"출력 {n:2d} 원본 {srcf:5.1f} 빨강 {g['r_gain']:.3f} 채도 {g['sat']:.3f}  키 렌더 {a.round(1)}  고정값 렌더 {b.round(1)}")
        worst = max(worst, np.abs(a - b).max())
    r0, r1 = mean_rgb(f, 2, 1920, 1080)[0], mean_rgb(f, 50, 1920, 1080)[0]
    print("빨강 평균 시작→끝:", round(r0, 1), "→", round(r1, 1), "최대 차이", round(worst, 2))
    assert r1 > r0 + 20 and worst < 3
    print("GKEYS OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
