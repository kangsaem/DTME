"""v0.16.41 인코더: HEVC 10bit(x265) = 컷 1개 · 전환 · 글자·이미지 · 레이어 모두 10bit 로 나오고 8bit 와 화면이 같음(오차 안).
AQ 확인(nvenc_aq) = GPU 없으면 끔·렌더는 그대로. 사용: python tests/test_encoders.py <4K테스트.mp4> <작업폴더>"""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, paths  # noqa: E402
from dtme.project import ImageSource, Project, Segment, Source, new_text  # noqa: E402


def frame(f, n, w, h):
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(f), "-frames:v", "1", "-vf",
                  f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)


def fmt(f):
    out = subprocess.run([paths.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,pix_fmt,codec_tag_string", "-of", "csv=p=0", str(f)], capture_output=True, text=True)
    return out.stdout.strip()


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    png = d / "red.png"
    a = np.zeros((100, 200, 4), np.uint8)
    a[:] = (230, 40, 30, 255)
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "200x100", "-i", "-",
                    "-frames:v", "1", str(png)], input=a.tobytes(), check=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, wnr=0)
    p.output.gpu_decode = False
    im = ImageSource(path=str(png), **ff.probe_image(str(png)))
    p.images.append(im)
    one = [Segment(src.id, 0, 60, 1.0)]
    two = [Segment(src.id, 0, 60, 1.0), Segment(src.id, 60, 110, 1.0, trans={"type": "dissolve", "dur": 0.3})]
    rot = [Segment(src.id, 0, 60, 1.0), Segment(src.id, 60, 110, 1.0, trans={"type": "zoomin", "dur": 0.3})]
    t1 = new_text(0.2, 1.4, "10bit")
    cases = {"컷1": (one, None), "디졸브": (two, None), "줌": (rot, None), "글자": (two, {"titles": [t1], "music": []})}
    for name, (segs, extras) in cases.items():
        files = {}
        for enc in ("x264", "x265_10"):
            p.output.encoder = enc
            f = d / f"enc_{name}_{enc}.mp4"
            ff.render_video(p, segs, str(f), extras=extras)
            files[enc] = f
        info10 = fmt(files["x265_10"])
        assert info10.split(",")[0] == "hevc" and "yuv420p10le" in info10 and "hvc1" in info10, info10
        assert "yuv420p" in fmt(files["x264"]) and "10" not in fmt(files["x264"]).split(",")[1]
        r8, r10 = ff.probe(str(files["x264"])), ff.probe(str(files["x265_10"]))
        assert r8["frames"] == r10["frames"], (name, r8["frames"], r10["frames"])
        n = r8["frames"] // 2
        df = np.abs(frame(files["x264"], n, 1920, 1080) - frame(files["x265_10"], n, 1920, 1080)).mean()
        print(f"{name}: {info10} · 프레임 {r10['frames']} · 8bit 와 평균 차 {df:.2f}")
        assert df < 3.0, (name, df)
    # 10bit 가 실제로 더 고움: 완만한 밝기 변화(16단계 폭)에서 서로 다른 값의 수
    cmd, _t, _c = ff.build_render_cmd(p, one, str(d / "x.mp4"))
    assert "format=yuv420p10le" in " ".join(cmd) and cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"
    # AQ: GPU 없는 곳 = 끔(렌더 명령에 안 들어감), 확인은 1번만
    p.output.encoder = "nvenc"
    a1 = ff.nvenc_aq("h264_nvenc")
    cmd, _t, _c = ff.build_render_cmd(p, one, str(d / "y.mp4"))
    assert ("-spatial-aq" in cmd) == bool(a1), (a1, cmd)
    print("AQ(h264_nvenc):", "켬" if a1 else "끔", "· 알아낸 것", ff._aq_known)
    print("OK test_encoders")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
