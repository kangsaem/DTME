"""v0.16.57: 글자·사각형·이미지 밀려 들어오기/나가기(→ ← ↑ ↓, 가속) — 렌더 위치가 project.title_anim/anim_offset 계산과 같은지 +
페이드를 고른 쪽은 예전처럼 페이드. 사용: python tests/test_title_anim.py <작업폴더>"""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import ff, paths  # noqa: E402
from dtme.project import (ImageSource, Project, Segment, Source, anim_offset, default_mix, new_rect, new_text,  # noqa: E402
                          new_title_image, title_anim)

W, H, FPS = 1920, 1080, 30000 / 1001


def frame(f, n):
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(f), "-frames:v", "1", "-vf",
                  f"select=eq(n\\,{n}),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return None if len(xs) < 20 else (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def main(work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    clip = d / "black.mp4"
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=60000/1001:d=4",
                    "-f", "lavfi", "-i", "sine=d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)], check=True)
    png = d / "green.png"
    a = np.zeros((100, 200, 4), np.uint8)
    a[:] = (20, 230, 40, 255)
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "200x100", "-i", "-",
                    "-frames:v", "1", str(png)], input=a.tobytes(), check=True)
    info = ff.probe(str(clip))
    src = Source(path=str(clip), **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, hue=0, sat=1.0, r_gain=1.0, b_gain=1.0, wnr=0, gy=0, water=0)
    p.output.encoder, p.output.gpu_decode = "x264", False
    im = ImageSource(path=str(png), **ff.probe_image(str(png)))
    p.images.append(im)
    rc = new_rect(0.0, 3.0)                       # 빨강 사각형: 왼쪽에서 들어와(→) 아래로 나감(↓)
    rc.update(cx=0.3, cy=0.3, w=0.2, h=0.1, color="#ff0000", opacity=1.0, radius=0, fade=1.0, ain="right", aout="down")
    img = new_title_image(im.id, 0.0, 3.0)        # 초록 이미지: 아래에서 올라와(↑) 왼쪽으로 나감(←)
    img.update(cx=0.7, cy=0.6, fade=1.0, ain="up", aout="left")
    tx = new_text(0.0, 3.0, "DTME")               # 흰 글자: 오른쪽에서 들어와(←) 페이드로 나감
    tx.update(cx=0.5, cy=0.85, bg="none", fade=1.0, size=80, ain="left", aout="fade", color="#ffffff")
    out = d / "anim.mp4"
    ff.render_video(p, [Segment(src.id, 0, 200, 1.0)], str(out), orientation="horizontal",
                    extras={"titles": [rc, img, tx], "music": [], "mix": default_mix()})
    rx, ry, rw, rh = ff.rect_box(rc, W, H)
    ix, iy, iw, ih = ff.layer_box(img, im, W, H)
    red = lambda f: (f[..., 0] > 150) & (f[..., 1] < 90) & (f[..., 2] < 90)        # noqa: E731
    grn = lambda f: (f[..., 1] > 150) & (f[..., 0] < 110) & (f[..., 2] < 110)      # noqa: E731
    wht = lambda f: f.min(-1) > 150                                                  # noqa: E731
    f_mid = frame(out, int(1.5 * FPS))
    tb = bbox(wht(f_mid))                                                           # 글자 제자리
    assert tb and abs((tb[0] + tb[2]) / 2 - 0.5 * W) < 12, tb
    assert bbox(wht(frame(out, 0))) is None or bbox(wht(frame(out, 0)))[0] > W - 40, "글자: 처음엔 화면 밖(오른쪽)"
    prev = {}
    for sec in (0.2, 0.5, 0.8, 1.5, 2.3, 2.6, 2.9):
        n = int(round(sec * FPS))
        t = n / FPS
        f = frame(out, n)
        for name, dd, mask, box in (("사각형", rc, red(f), (rx, ry, rw, rh)), ("이미지", img, grn(f), (ix, iy, iw, ih))):
            a_, ph, key, fr = title_anim(dd, t)
            dx, dy = anim_offset(ph, key, fr, box, W, H, 2)
            ex, ey = box[0] + dx, box[1] + dy
            b = bbox(mask)
            vis = ex < W and ex + box[2] > 0 and ey < H and ey + box[3] > 0
            if not vis:
                assert b is None, (name, sec, b)
                continue
            assert b is not None, (name, sec, "안 보임", ex, ey)
            gx = b[0] if ex >= 0 else b[2] - box[2]                 # 화면에 걸친 쪽은 보이는 가장자리로 역산
            gy = b[1] if ey >= 0 else b[3] - box[3]
            assert abs(gx - ex) <= 4 and abs(gy - ey) <= 4, (name, sec, (gx, gy), (round(ex), round(ey)))
            prev[(name, sec)] = (gx, gy)
        tbn = bbox(wht(f))
        a_, ph, key, fr = title_anim(tx, t)
        if ph == "in":                                              # 글자: 왼쪽으로 가까워짐(제자리 오른쪽에 있음)
            assert tbn is None or tbn[0] >= tb[0] - 2, (sec, tbn, tb)
        elif sec == 1.5:
            assert tbn == tb
        elif sec >= 2.3:                                            # 나갈 때 = 페이드(제자리에서 어두워짐)
            fl = f[tb[1]:tb[3], tb[0]:tb[2]].max()
            assert fl < 255 * (a_ + 0.15) + 8, (sec, fl, a_)
    # 가속: 들어올 때 처음이 더 빠름 / 나갈 때 끝이 더 빠름
    r = lambda s: prev[("사각형", s)]                                # noqa: E731
    assert (r(0.5)[0] - r(0.2)[0]) > (r(0.8)[0] - r(0.5)[0]) > 0, "들어올 때 = 빠르게 출발해 부드럽게"
    assert r(1.5) == (rx, ry) or (abs(r(1.5)[0] - rx) <= 2 and abs(r(1.5)[1] - ry) <= 2)
    assert (r(2.6)[1] - r(2.3)[1]) > (r(2.3)[1] - r(1.5)[1]) >= 0, "나갈 때 = 천천히 출발해 빠르게"
    # 고르지 않으면(옛 프로젝트) = 예전과 같은 필터
    old = new_rect(0.0, 3.0)
    assert ff._slide_xy(old, "10", "20", "30", "40", W, H, 2) == ("10", "20") and len(ff._fade_chain(old)) == 2
    print("OK test_title_anim")


if __name__ == "__main__":
    main(sys.argv[1])
