"""타임라인 글자·이미지·음악 렌더 점검.
사용: python tests/test_titles.py <4K테스트.mp4> <작업폴더>"""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, paths  # noqa: E402
from dtme.project import (ImageSource, Project, Segment, Source, default_mix, new_music, new_text,  # noqa: E402
                          new_title_image)


def frame(f, n, w, h):
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(f), "-frames:v", "1", "-vf",
                  f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)


def loud(f, ss, t):
    """구간 평균 음량(dB)."""
    r = subprocess.run([paths.ffmpeg(), "-v", "info", "-ss", str(ss), "-t", str(t), "-i", str(f), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    line = [x for x in r.stderr.splitlines() if "mean_volume" in x]
    return float(line[0].split(":")[1].split()[0]) if line else -99.0


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    # 음악: 1kHz 사인 4초 / 이미지: 빨강 200x100
    mus = d / "music.m4a"
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=1000:d=4", "-c:a", "aac", str(mus)], check=True)
    png = d / "red.png"
    a = np.zeros((100, 200, 4), np.uint8)
    a[:] = (230, 40, 30, 255)
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "200x100", "-i", "-",
                    "-frames:v", "1", str(png)], input=a.tobytes(), check=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0)
    p.output.encoder, p.output.gpu_decode = "x264", False
    im = ImageSource(path=str(png), **ff.probe_image(str(png)))
    p.images.append(im)
    segs = [Segment(src.id, 0, 60, 1.0), Segment(src.id, 60, 110, 1.0, trans={"type": "dissolve", "dur": 0.3})]
    t1 = new_text(0.2, 1.4, "BOHOL · 2026.10.25\n발리카삭 18m")
    t1.update(cy=0.3, bg="band", fade=0.2)
    img = new_title_image(im.id, 0.5, 1.2)
    img.update(cx=0.85, cy=0.8, fade=0.05)
    extras = {"titles": [t1, img], "music": [new_music(str(mus), 0.3, ff.probe_audio(str(mus)))], "mix": default_mix()}
    for orient, (W, H) in (("horizontal", (1920, 1080)), ("horizontal2160", (3840, 2160))):
        f = d / f"titles_{orient}.mp4"
        ff.render_video(p, segs, str(f), orientation=orient, extras=extras)
        r = ff.probe(str(f))
        n_mid = int(0.9 * 29.97)
        fr = frame(f, n_mid, W, H)
        band = fr[int(0.3 * H) - 5:int(0.3 * H) + 5, W // 2 - 300:W // 2 + 300].reshape(-1, 3).mean(0)
        k = W / 1920
        red = fr[int(0.8 * H) - int(20 * k):int(0.8 * H) + int(20 * k), int(0.85 * W) - int(40 * k):int(0.85 * W) + int(40 * k)].reshape(-1, 3).mean(0)
        late = frame(f, int(1.4 * 29.97), W, H)[int(0.8 * H) - 10:int(0.8 * H) + 10, int(0.85 * W) - 20:int(0.85 * W) + 20].reshape(-1, 3).mean(0)
        print(orient, r["width"], r["height"], r["frames"], "띠 평균", band.round(0), "이미지", red.round(0), "1.4초 이미지 자리", late.round(0))
        assert np.abs(red - (230, 40, 30)).max() < 12 and np.abs(late - (230, 40, 30)).max() > 40
    v_pre, v_mus, v_end = loud(f, 0.0, 0.25), loud(f, 0.6, 0.6), loud(f, 1.45, 0.08)
    print("음량 dB: 음악 전", v_pre, "/ 음악", v_mus, "/ 끝 페이드", v_end)
    assert v_mus > v_pre + 20
    # 원본 볼륨 100% 로 직접 지정 → 음악 전 구간에도 소리
    extras["mix"] = {**default_mix(), "orig": 1.0}
    f2 = d / "titles_orig.mp4"
    ff.render_video(p, segs, str(f2), orientation="horizontal", extras=extras)
    print("원본 100%: 음악 전", loud(f2, 0.0, 0.25))
    assert loud(f2, 0.0, 0.25) > v_pre + 20
    print("TITLES OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
