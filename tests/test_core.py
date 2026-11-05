"""핵심 엔진 점검. 사용: python tests/test_core.py <샘플.MP4> <LUT.cube>
GPU 가 없는 환경에서도 돌도록 gpu=False, x264 로 실행한다."""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dtme import ff, paths  # noqa: E402
from dtme.project import Marker, Project, Segment, Source  # noqa: E402


def main(sample: str, lut: str, out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(lut, paths.lut_dir() / Path(lut).name)

    info = ff.probe(sample)
    print("probe:", info)
    assert info["frames"] > 0 and not info["vfr"]

    p = Project()
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p.sources.append(src)
    p.grade.update(lut=Path(lut).name, r_gain=1.25, b_gain=0.88, hue=3,
                   curve=[[0, 0], [0.25, 0.22], [0.75, 0.8], [1, 1]], nr_chroma=60, nr_luma=25, sharpen=0.4)

    t = time.time()
    src.proxy = ff.make_proxy(src, p.grade["lut"], gpu=False)
    pi = ff.probe(src.proxy)
    print(f"proxy {time.time()-t:.1f}s", pi["width"], pi["height"], pi["frames"])
    assert pi["frames"] == info["frames"], "프록시 프레임 수 불일치"

    # 세그먼트: 2x, 1x, 0.5x
    p.segments = [Segment(src.id, 0, 60, 2.0), Segment(src.id, 60, 120, 1.0), Segment(src.id, 120, 180, 0.5)]
    print("예상 길이:", round(p.out_seconds(src.id), 3))

    # 클립별 덮어쓰기
    src.grade = {"hue": -5}
    assert p.grade_for_source(src.id)["hue"] == -5

    for orient in ("horizontal", "vertical"):
        p.output.orientation = orient
        p.output.encoder = "x264"
        p.output.gpu_decode = False
        f = out / f"render_{orient}.mp4"
        t = time.time()
        ff.render_video(p, p.segments, str(f), on_progress=None)
        r = ff.probe(str(f))
        print(f"{orient}: {time.time()-t:.1f}s {r['width']}x{r['height']} frames={r['frames']} dur={r['duration']:.3f}")

    # 미리보기
    c = ff.cached_frame(src, 100)
    png = ff.render_preview(c, p.grade_for_source(src.id))
    (out / "preview.png").write_bytes(png)
    (out / "preview_before.png").write_bytes(ff.render_preview(c, None))

    # 스틸
    st = Marker(src.id, 150, grade={"nr_chroma": 100, "nr_luma": 70, "sharpen": 0.6})
    p.stills.append(st)
    ff.render_still(p, st, str(out / "still.tif"))
    s = ff.probe(str(out / "still.tif"))
    print("still:", s["width"], s["height"], s["pix_fmt"])

    sc = ff.sharpness_around(src, 150)
    best = max(sc, key=lambda x: x[1])
    print("sharpness best:", best, "of", [f for f, _ in sc])
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "test_out")
