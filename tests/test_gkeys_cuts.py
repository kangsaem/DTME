"""v0.16.79 색 키프레임이 여러 컷에 있을 때: 각 컷의 키가 자기 컷에만 들어가는지.
(전에는 필터 이름이 컷마다 같아서 뒷컷 키가 앞컷 필터를 바꿈 → 전환 때 앞컷이 보라색)
사용: python tests/test_gkeys_cuts.py <테스트.mp4> <작업폴더>"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, paths  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402


def mean_rgb(f, n, w, h):
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(f), "-frames:v", "1", "-vf",
                  f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).reshape(-1, 3).astype(float).mean(0)


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})

    def render(name, k0, k1):
        p = Project()
        p.sources.append(src)
        p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, hue=0, sat=1.0, r_gain=1.0, b_gain=1.0)
        p.output.encoder, p.output.gpu_decode = "x264", False
        segs = [Segment(src.id, 0, 50, 1.0, gkeys=k0),
                Segment(src.id, 50, 110, 1.0, gkeys=k1, trans={"type": "wipeleft", "dur": 0.5})]
        f = d / name
        ff.render_video(p, segs, str(f), orientation="horizontal")
        return f

    same = {"r_gain": [{"f": 0, "v": 1.0}, {"f": 50, "v": 1.0}]}          # 앞컷: 키는 있지만 값은 그대로
    red = {"r_gain": [{"f": 50, "v": 0.3}, {"f": 110, "v": 0.3}]}          # 뒷컷: 빨강 크게 줄임
    a = render("both.mp4", same, red)
    b = render("plain.mp4", {}, {})
    W, H = ff.out_size("horizontal")
    # 출력(29.97) 프레임: 앞컷 4, 뒷컷(전환 끝난 뒤) 38
    a10, b10 = mean_rgb(a, 4, W, H), mean_rgb(b, 4, W, H)
    a90, b90 = mean_rgb(a, 38, W, H), mean_rgb(b, 38, W, H)
    print("앞컷(전환 전) 키:", a10.round(1), "기본:", b10.round(1))
    print("뒷컷(전환 후) 키:", a90.round(1), "기본:", b90.round(1))
    assert np.abs(a10 - b10).max() < 3, "앞컷 색이 바뀜"
    assert a90[0] < b90[0] - 20, "뒷컷 키가 안 들어감"
    print("GKEYS CUTS OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
