"""이미지 레이어 엔진 점검: 위치·구간·색·EXIF 방향·투명.
사용: python tests/test_layers.py <4K테스트.mp4> <작업폴더>
작업폴더에 테스트용 PNG/JPG 를 직접 만든다(numpy + Qt 없이 ffmpeg 로)."""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dtme import ff, paths  # noqa: E402
from dtme.project import ImageSource, Project, Segment, Source, new_layer  # noqa: E402


def make_images(d: Path):
    # 투명 PNG 400x200: 왼쪽 불투명 빨강(230,40,30) / 오른쪽 흰색 alpha 128
    a = np.zeros((200, 400, 4), np.uint8)
    a[:, :200] = (230, 40, 30, 255)
    a[:, 200:] = (255, 255, 255, 128)
    png = d / "ov.png"
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "400x200",
                    "-i", "-", "-frames:v", "1", str(png)], input=a.tobytes(), check=True)
    return png


def frame_rgb(f: Path, t: float, w: int, h: int) -> np.ndarray:
    """출력 프레임 번호 round(t*29.97) 를 정확히 뽑음."""
    n = int(t * 30000 / 1001)
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(f), "-frames:v", "1",
                  "-vf", f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
                  "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    png = make_images(d)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0)
    im = ImageSource(path=str(png), **ff.probe_image(str(png)))
    assert (im.width, im.height, im.orient) == (400, 200, 1), im
    p.images.append(im)
    lay = new_layer(im.id, 30, 90)          # 원본 30~89 프레임(0.5~1.5초), 가운데
    lay.update(cx=0.25, cy=0.5)
    seg = Segment(src.id, 0, 110, 1.0, layers=[lay])
    p.output.encoder, p.output.gpu_decode = "x264", False
    for orient, (W, H) in (("horizontal", (1920, 1080)), ("vertical", (1080, 1920))):
        f = d / f"layer_{orient}.mp4"
        ff.render_video(p, [seg], str(f), orientation=orient)
        r = ff.probe(str(f))
        assert (r["width"], r["height"]) == (W, H) and r["frames"] == 55, r
        x0, y0 = int(0.25 * W - 200), int(0.5 * H - 100)
        on = frame_rgb(f, 1.0, W, H)
        off = frame_rgb(f, 0.2, W, H)
        red = on[y0 + 50:y0 + 150, x0 + 50:x0 + 150].reshape(-1, 3).mean(0)
        print(orient, "빨강", red.round(1), "(230,40,30)")
        assert np.abs(red - (230, 40, 30)).max() < 6, red
        # 반투명 흰색 = 배경과 흰색의 중간
        bg = off[y0 + 60:y0 + 140, x0 + 260:x0 + 340].reshape(-1, 3).mean(0)
        half = on[y0 + 60:y0 + 140, x0 + 260:x0 + 340].reshape(-1, 3).mean(0)
        exp = bg + (255 - bg) * 128 / 255
        print(orient, "반투명", half.round(1), "기대", exp.round(1))
        assert np.abs(half - exp).max() < 8
        # 구간 밖(0.2초)에는 이미지 없음 / 구간 끝(1.5초 이후)도 없음
        late = frame_rgb(f, 1.7, W, H)[y0 + 50:y0 + 150, x0 + 50:x0 + 150].reshape(-1, 3).mean(0)
        assert np.abs(off[y0 + 50:y0 + 150, x0 + 50:x0 + 150].reshape(-1, 3).mean(0) - (230, 40, 30)).max() > 20
        assert np.abs(late - (230, 40, 30)).max() > 20
    # 레이어 없는 컷과 같은 색인지(합성 경로의 색 차이)
    seg0 = Segment(src.id, 0, 110, 1.0)
    f0 = d / "nolayer.mp4"
    ff.render_video(p, [seg0], str(f0), orientation="horizontal")
    a = frame_rgb(f0, 0.2, 1920, 1080)
    b = frame_rgb(d / "layer_horizontal.mp4", 0.2, 1920, 1080)
    diff = np.abs(a - b).mean()
    print("레이어 경로 vs 일반 경로 평균 차이:", round(diff, 3))
    assert diff < 1.5
    # 2개 컷 + 배속 + 레이어 시간 위치 (2배속 컷 안의 레이어)
    lay2 = new_layer(im.id, 60, 100)
    segs = [Segment(src.id, 0, 40, 1.0), Segment(src.id, 40, 120, 2.0, layers=[lay2])]
    f2 = d / "two.mp4"
    ff.render_video(p, segs, str(f2), orientation="horizontal")
    r = ff.probe(str(f2))
    assert r["frames"] == 20 + 20, r
    x0, y0 = 960 - 200, 540 - 100
    # 두 번째 컷 시작 = 출력 20 프레임. 59.94→29.97 + 2배속 = 출력 1프레임당 원본 4프레임
    # 레이어 원본 60~99 → 컷 안 출력 (60-40)/4 = 5 ~ 14 프레임
    def has(t):
        return np.abs(frame_rgb(f2, t, 1920, 1080)[y0 + 50:y0 + 150, x0 + 50:x0 + 150].reshape(-1, 3).mean(0)
                      - (230, 40, 30)).max() < 10
    fps = 30000 / 1001
    got = [has((20 + n + 0.5) / fps) for n in (4, 5, 14, 15)]
    print("2배속 컷 레이어 (4,5,14,15):", got)
    assert got == [False, True, True, False]
    # JPG: 색(풀레인지 BT.601 → BT.709) + EXIF 방향 6 (PIL 이 있을 때만)
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        j = np.zeros((100, 300, 3), np.uint8)
        j[:] = (40, 60, 200)
        j[:, :100] = (20, 200, 40)       # 저장 기준 왼쪽 초록 → 방향 6(시계 90°) 이면 화면 위쪽이 초록
        ex = Image.Exif()
        ex[0x0112] = 6
        Image.fromarray(j).save(d / "rot6.jpg", exif=ex, quality=98)
        jm = ImageSource(path=str(d / "rot6.jpg"), **ff.probe_image(str(d / "rot6.jpg")))
        assert (jm.width, jm.height, jm.orient) == (100, 300, 6), jm
        p.images.append(jm)
        jl = new_layer(jm.id, 0, 110)
        f3 = d / "jpg.mp4"
        ff.render_video(p, [Segment(src.id, 0, 110, 1.0, layers=[jl])], str(f3), orientation="horizontal")
        fr = frame_rgb(f3, 0.5, 1920, 1080)
        top = fr[540 - 150 + 20:540 - 150 + 80, 960 - 50 + 20:960 + 30].reshape(-1, 3).mean(0)
        bot = fr[540 + 150 - 80:540 + 150 - 20, 960 - 50 + 20:960 + 30].reshape(-1, 3).mean(0)
        print("JPG 방향6 위", top.round(1), "(20,200,40) / 아래", bot.round(1), "(40,60,200)")
        assert np.abs(top - (20, 200, 40)).max() < 8 and np.abs(bot - (40, 60, 200)).max() < 8
    print("LAYERS OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
