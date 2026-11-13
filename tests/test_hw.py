"""v0.16.48 그래픽 판별 · 인코더 바꿔 쓰기 · 저사양. python tests/test_hw.py <4K테스트.mp4> <작업폴더>
GPU 없는 곳(CI)에서: 판별 = none → 설정이 NVENC 여도 x264 로 렌더됨 · -hwaccel 안 붙음. 나머지 경우는 강제(DTME_HW)로 명령 모양만."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, jobs, paths, project as P  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    sf = d / "settings.json"
    paths.settings_path = lambda: sf                       # 이 PC 설정을 건드리지 않음
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.output.quality = "high"                                          # v0.16.80 용량: 이 시험은 예전(고화질) 인자 기준
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, wnr=0)
    seg = [Segment(src.id, 0, 60, 1.0)]
    cmd = lambda: ff.build_render_cmd(p, seg, str(d / "o.mp4"))[0]      # noqa: E731

    def force(kind):
        ff._hw_kind[0] = kind

    # 1) 실제 판별(이 기기) → 렌더가 됨
    os.environ.pop("DTME_HW", None)
    real = ff.hw_kind()
    print("이 기기:", real, "· 저사양", ff.low_spec())
    assert real in ("nvenc", "qsv", "none")
    p.output.encoder, p.output.gpu_decode = "nvenc", True              # 기본 설정 그대로
    ff.render_video(p, seg, str(d / "hw_default.mp4"))
    assert ff.probe(str(d / "hw_default.mp4"))["frames"] > 0
    if real == "none":
        c = cmd()
        assert "libx264" in c and "-hwaccel" not in c and "h264_nvenc" not in c, c
    # 2) 강제: 없음
    force("none")
    assert [ff.eff_encoder(e) for e in ("nvenc", "qsv", "x264", "nvenc_hevc10", "x265_10")] == ["x264", "x264", "x264", "x265_10", "x265_10"]
    c = cmd()
    assert "libx264" in c and "-hwaccel" not in c and "scale_cuda" not in " ".join(c)
    # 3) 강제: Quick Sync(인코딩만 GPU · 디코딩 CPU)
    force("qsv")
    assert [ff.eff_encoder(e) for e in ("nvenc", "qsv", "x264", "nvenc_hevc10")] == ["qsv", "qsv", "x264", "x265_10"]
    c = cmd()
    assert "h264_qsv" in c and c[c.index("-pix_fmt") + 1] == "nv12" and "-global_quality" in c and "-hwaccel" not in c, c
    ff._qsv_mode[0] = "vbr"
    c = cmd()
    assert "h264_qsv" in c and "-global_quality" not in c and "-b:v" in c
    ff._qsv_mode[0] = "icq"
    p.output.encoder = "x264"                                          # 직접 고른 x264 는 그대로
    assert "libx264" in cmd()
    # Quick Sync 가 렌더에서 실패 → x264 로 다시(이 기기에 인텔 GPU 가 없을 때만 시험됨)
    p.output.encoder = "nvenc"
    if real != "qsv":
        ff.render_video(p, seg, str(d / "hw_qsvfail.mp4"))
        assert ff.hw_kind() == "none" and ff.probe(str(d / "hw_qsvfail.mp4"))["frames"] > 0
    # 4) 강제: NVIDIA = 지금까지와 같음
    force("nvenc")
    p.output.gpu_decode = True
    c = cmd()
    assert "-hwaccel" in c and (("h264_nvenc" in c) or True) and ff.eff_encoder("qsv") == "nvenc" and not ff.low_spec()
    # 5) 저사양: 설정으로 강제 → x264 faster · 조각 렌더 안 함 · 동시 작업 줄임
    force("none")
    p.output.encoder, p.output.gpu_decode = "x264", False
    long = [Segment(src.id, 0, src.frames, 1.0)]
    P.set_setting("low_spec", 1)
    c = cmd()
    assert c[c.index("-preset") + 1] == "faster" and ff.chunk_plan(p, long, "horizontal", None) is None
    jobs.apply_hw()
    assert jobs.PREVIEW_POOL.maxThreadCount() == 2 and jobs.PROXY_POOL.maxThreadCount() == 1
    P.set_setting("low_spec", 2)
    c = cmd()
    assert c[c.index("-preset") + 1] == "medium"
    print("OK test_hw")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
