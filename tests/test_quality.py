"""v0.16.80 렌더 용량 [고화질|보통|작게]: 인코더 인자 · 예상 크기 · 실제 크기 순서(작게 < 보통 < 고화질).
사용: python tests/test_quality.py <테스트.mp4> <작업폴더>"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402


def main(sample, work):
    d = Path(work); d.mkdir(parents=True, exist_ok=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project(); p.sources.append(src)
    segs = [Segment(src.id, 0, min(src.frames, 110), 1.0)]
    # 인자: GPU 보통 = H.265(되면) · CPU = H.264 crf
    for enc in ("nvenc", "x264", "qsv", "x265_10", "nvenc_hevc10"):
        for q in ("high", "normal", "small"):
            p.output.encoder, p.output.quality = enc, q
            ff._ctx.last_cmd = None
            cmd = ff.build_render_cmd(p, segs, str(d / "x.mp4"), orientation="horizontal")[0]
            c = cmd[cmd.index("-c:v") + 1]
            print(enc, q, ff.eff_encoder(enc), c, " ".join(cmd[cmd.index("-c:v"):cmd.index("-pix_fmt")])[:110])
            if q == "high":
                continue
            if ff.eff_encoder(enc) in ("nvenc", "nvenc_hevc10"):
                assert c == ("hevc_nvenc" if ff.hevc_nvenc_ok() else "h264_nvenc"), c
            elif ff.eff_encoder(enc) == "x264":
                assert c == "libx264" and "-maxrate" in cmd, cmd
    # GPU 경로(이 환경 GPU 없으면 인자만): H.265 되면 hevc_nvenc main · 안 되면 h264_nvenc
    real = (ff.eff_encoder, ff.hevc_nvenc_ok, ff.nvenc_aq)
    ff.eff_encoder, ff.nvenc_aq = (lambda e: e), (lambda c: [])
    for ok, want in ((True, "hevc_nvenc"), (False, "h264_nvenc")):
        ff.hevc_nvenc_ok = lambda ok=ok: ok
        p.output.encoder, p.output.quality = "nvenc", "small"
        cmd = ff.build_render_cmd(p, segs, str(d / "x.mp4"), orientation="horizontal2160")[0]
        print("GPU", ok, " ".join(cmd[cmd.index("-c:v"):cmd.index("-pix_fmt")]))
        assert cmd[cmd.index("-c:v") + 1] == want and cmd[cmd.index("-b:v") + 1] == "10M", cmd
    p.output.quality = "high"
    cmd = ff.build_render_cmd(p, segs, str(d / "x.mp4"), orientation="horizontal")[0]
    assert cmd[cmd.index("-c:v") + 1] == "h264_nvenc" and cmd[cmd.index("-cq") + 1] == "19"     # 고화질 = 예전 그대로
    ff.eff_encoder, ff.hevc_nvenc_ok, ff.nvenc_aq = real
    # 예상 크기
    assert ff.est_mb("small", 60) < ff.est_mb("normal", 60) < ff.est_mb("high", 60)
    assert abs(ff.est_mb("normal", 60, "horizontal2160") / ff.est_mb("normal", 60) - 2.4) < 0.2
    # 실제 크기(CPU x264)
    sz = {}
    for q in ("high", "normal", "small"):
        p.output.encoder, p.output.quality = "x264", q
        f = d / f"q_{q}.mp4"
        ff.render_video(p, segs, str(f), orientation="horizontal")
        sz[q] = os.path.getsize(f)
    print("크기", sz)
    assert sz["small"] < sz["normal"] < sz["high"], sz
    print("QUALITY OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
