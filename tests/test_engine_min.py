"""CI(Windows)용 최소 점검: 합성 4K 영상으로 프록시·렌더·스틸·미리보기 확인.
사용: python tests/test_engine_min.py <4K테스트.mp4>"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dtme import ff, paths  # noqa: E402
from dtme.project import Marker, Project, Segment, Source  # noqa: E402


def identity_lut(path: Path, n=17):
    lines = [f"LUT_3D_SIZE {n}"]
    for b in range(n):
        for g in range(n):
            for r in range(n):
                lines.append(f"{r/(n-1):.6f} {g/(n-1):.6f} {b/(n-1):.6f}")
    path.write_text("\n".join(lines))


def main(sample):
    identity_lut(paths.lut_dir() / "_ci_identity.cube")
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="_ci_identity.cube", r_gain=1.1, b_gain=0.9, hue=5,
                   curve=[[0, 0], [0.5, 0.55], [1, 1]], nr="weak", sharpen=0.3)
    src.proxy = ff.make_proxy(src, p.grade["lut"], gpu=False)
    assert ff.probe(src.proxy)["frames"] == info["frames"]
    p.segments = [Segment(src.id, 0, 40, 2.0), Segment(src.id, 40, 80, 1.0), Segment(src.id, 80, 110, 0.5)]
    expect = 40 // 4 + 40 // 2 + 30
    out = Path(tempfile.mkdtemp())
    p.output.encoder, p.output.gpu_decode = "x264", False
    for o in ("horizontal", "vertical"):
        p.output.orientation = o
        f = out / f"{o}.mp4"
        ff.render_video(p, p.segments, str(f))
        r = ff.probe(str(f))
        print(o, r["width"], r["height"], r["frames"])
        assert r["frames"] == expect, (r["frames"], expect)
    st = Marker(src.id, 60, grade={"nr": "strong"})
    ff.render_still(p, st, str(out / "s.tif"))
    assert ff.probe(str(out / "s.tif"))["width"] == 3840
    assert ff.render_preview(ff.cached_frame(src, 30), p.grade)[:4] == b"\x89PNG"
    print("ENGINE OK")


if __name__ == "__main__":
    main(sys.argv[1])
