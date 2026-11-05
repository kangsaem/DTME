"""화면 전환 엔진 점검: 모든 종류 렌더 → 길이(겹침만큼 줄어듦)·오디오 길이 확인.
사용: python tests/test_transitions.py <4K테스트.mp4> <작업폴더> [all]
all 이면 모든 종류, 아니면 대표 4종(CI). 작업폴더/trans_<종류>.png = 전환 구간 4장 이어붙인 확인용 그림"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dtme import ff, paths  # noqa: E402
from dtme.project import OUT_FPS, TRANSITIONS, Project, Segment, Source  # noqa: E402


def main(sample, work, every=False):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0)
    p.output.encoder, p.output.gpu_decode = "x264", False
    fps = float(OUT_FPS)
    kinds = [k for k, _ in TRANSITIONS if k != "none"]
    if not every:
        kinds = ["dissolve", "wipeleft", "rotzoomin", "zoomout"]
    for kind in kinds:
        # 컷1 원본 0~60(1초) / 컷2 원본 60~110 → 화면이 달라 보이도록 2배속 x
        segs = [Segment(src.id, 0, 60, 1.0), Segment(src.id, 60, 120, 1.0, trans={"type": kind, "dur": 0.5})]
        f = d / f"trans_{kind}.mp4"
        ff.render_video(p, segs, str(f), orientation="horizontal")
        r = ff.probe(str(f))
        exp = 30 + 30 - round(0.5 * fps)
        print(f"{kind:11s} frames={r['frames']} 기대≈{exp} 결과 길이 {p.segs_seconds(segs):.3f}s")
        assert abs(r["frames"] - exp) <= 1, (kind, r["frames"], exp)
        a = ff.run([paths.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries", "stream=duration",
                    "-of", "csv=p=0", str(f)]).decode().strip()
        assert abs(float(a) - exp / fps) < 0.1, (kind, a)
        ts = [0.5 / fps * 0 + (30 - 15 + k * 5) / fps for k in range(4)]
        ins = []
        for k, t in enumerate(ts):
            png = d / f"_t{k}.png"
            ff.run([paths.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.4f}", "-i", str(f), "-frames:v", "1",
                    "-vf", "scale=320:-2", str(png)])
            ins += ["-i", str(png)]
        ff.run([paths.ffmpeg(), "-v", "error", "-y", *ins, "-filter_complex", "hstack=4", str(d / f"trans_{kind}.png")])
    # 3컷: 첫 컷 페이드인(흰색) + 전환 + 전환 없는 경계 + 배속
    segs = [Segment(src.id, 0, 40, 1.0, trans={"type": "fadewhite", "dur": 0.3}),
            Segment(src.id, 40, 80, 2.0, trans={"type": "rotzoomout", "dur": 2.0}),   # 길이 제한으로 줄어듦
            Segment(src.id, 80, 110, 1.0)]
    f = d / "trans_mix.mp4"
    ff.render_video(p, segs, str(f), orientation="vertical")
    r = ff.probe(str(f))
    lens = [20 / fps, 10 / fps, 15 / fps]
    exp = (sum(lens) - min(lens[0], lens[1]) * 0.5) * fps
    print("mix frames", r["frames"], "기대≈", round(exp, 1), r["width"], r["height"])
    assert abs(r["frames"] - exp) <= 1.5 and (r["width"], r["height"]) == (1080, 1920)
    print("TRANSITIONS OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "all")
