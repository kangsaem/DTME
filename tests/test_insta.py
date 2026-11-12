"""v0.16.50 Insta360(Ace Pro 2) 파일: 세로 촬영(회전 −90°) 인식 · 프리뷰 짝(LRV_같은이름.lrv) · 이름 날짜 · 색 프로파일(vivid = LUT 없음, I-Log = Insta LUT).
합성 파일로 확인(실물 = 사용자 VID_20260917_080520_006.mp4). 사용: python tests/test_insta.py <작업폴더>"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, paths, project  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402

MAGIC = b"8db42d694ccc418790edff439fe026bf"


def make(d, name, size, fps, color):
    raw = d / ("raw_" + name)
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r={fps}:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuvj420p", "-f", "mp4", str(raw)], check=True)
    out = d / name
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-display_rotation", "90", "-i", str(raw), "-c", "copy",
                    "-f", "mp4", str(out)], check=True)          # 회전 정보 −90°(세로로 찍음)
    raw.unlink()
    with open(out, "ab") as f:                                    # 파일 끝 기록 흉내(모델명 · 색 이름 · 표식)
        f.write(b"\x00" * 40 + b"\x12\x12Insta360 Ace Pro 2\x1a\x10v_2.0.51_build1\x2a\x05" + color + b"\x00\x00" + MAGIC)
    return out


def main(work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    v = make(d, "VID_20260917_080520_006.mp4", "640x360", "60000/1001", b"vivid")
    lrv = make(d, "LRV_20260917_080520_006.lrv", "320x180", "30000/1001", b"vivid")
    i = ff.probe(str(v))
    print({k: i[k] for k in ("width", "height", "rotation", "color_mode")})
    assert (i["width"], i["height"]) == (360, 640) and abs(i["rotation"]) == 90 and i["color_mode"] == "normal"
    assert project.display_name(str(v)) == "2026 0917 0805" and project.display_name("DJI_20261025100118_0148_D.MP4") == "2026 1025 1001"
    assert Path(ff.find_preview(str(v))).name == lrv.name, ff.find_preview(str(v))
    s = Source(path=str(v), **{k: i[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    r = ff.check_preview(s, "")
    print("프리뷰 판정:", r["ok"], r["why"], r["w"], r["h"])
    assert r["ok"] and (r["w"], r["h"]) == (180, 320), r
    # 세로 영상 그대로 렌더(세로 출력 = 화면 전체, 가로 출력 = 가운데)
    p = Project()
    p.sources.append(s)
    p.grade.update(lut="")
    p.output.encoder, p.output.gpu_decode = "x264", False
    for o, wh in (("vertical", (1080, 1920)), ("horizontal", (1920, 1080))):
        f = d / f"insta_{o}.mp4"
        ff.render_video(p, [Segment(s.id, 0, 30, 1.0)], str(f), orientation=o)
        q = ff.probe(str(f))
        assert (q["width"], q["height"]) == wh and q["frames"] > 0, (o, q)
    c = ff.cached_frame(s, 20)
    assert c.size[0] < c.size[1], c.size                          # 멈춘 화면도 세로
    # 색: vivid = LUT 없음 / I-Log = LUT 폴더의 Insta LUT(없으면 LUT 없음) / DJI·다른 파일 = 예전대로
    s.lut_mode = "normal"
    assert project.auto_lut(p, s) == ""
    v2 = make(d, "VID_20260917_090000_007.mp4", "640x360", "30", b"I-Log")
    assert ff.insta_color_mode(str(v2)) == "ilog" and ff.probe(str(v2))["color_mode"] == "ilog"
    plain = d / "plain.mp4"
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1", "-pix_fmt", "yuv420p", str(plain)], check=True)
    pi = ff.probe(str(plain))
    assert pi["color_mode"] == "unknown" and pi["rotation"] == 0 and (pi["width"], pi["height"]) == (320, 180)
    ld = d / "luts"
    ld.mkdir(exist_ok=True)
    old = paths.lut_dir
    paths.lut_dir = lambda: ld
    try:
        s.lut_mode = "ilog"
        assert project.auto_lut(p, s) == ""                       # Insta LUT 없음 = LUT 없음
        for n in ("Insta360_I-Log_to_Rec2020.cube", "Insta360_I-Log_to_Rec709.cube", "DJI_x.cube"):
            (ld / n).write_text("LUT_3D_SIZE 2\n")
        assert project.auto_lut(p, s) == "Insta360_I-Log_to_Rec709.cube", project.auto_lut(p, s)
    finally:
        paths.lut_dir = old
    print("OK test_insta")


if __name__ == "__main__":
    main(sys.argv[1])
