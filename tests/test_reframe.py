"""세로 크롭 위치 이동(리프레이밍) 엔진 점검.
사용: python tests/test_reframe.py <4K테스트.mp4> <작업폴더>
렌더 결과 프레임을 '원본에서 그 위치로 직접 자른 화면'과 비교."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dtme import ff, paths  # noqa: E402
from dtme.project import OUT_FPS, Project, Segment, Source, reframe_at  # noqa: E402


def gray(cmd_in, vf, w, h):
    raw = ff.run([paths.ffmpeg(), "-v", "error", *cmd_in, "-frames:v", "1", "-vf", vf + ",format=gray",
                  "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(h, w).astype(float)


def main(sample, work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    info = ff.probe(sample)
    src = Source(path=sample, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0)
    p.output.encoder, p.output.gpu_decode = "x264", False
    keys = [{"f": 10, "dx": -540}, {"f": 90, "dx": 540}]
    cw = 1214
    fps_out = float(OUT_FPS)
    for speed in (1.0, 2.0):
        seg = Segment(src.id, 0, 110, speed, reframe=keys)
        f = d / f"reframe_x{speed:g}.mp4"
        ff.render_video(p, [seg], str(f), orientation="vertical")
        n_out = ff.probe(str(f))["frames"]
        worst = 0.0
        for n in (0, n_out // 3, n_out // 2, n_out - 2):
            sf = seg.fin + n / fps_out * float(src.fps) * speed          # 그 출력 프레임의 원본 프레임
            sf = int(round(sf))
            x = int(round((3840 - cw) / 2 + reframe_at(keys, sf)))
            got = gray(["-i", str(f)], f"select=eq(n\\,{n})", 1080, 1920)
            # 기대 위치 ±24px 중 가장 잘 맞는 크롭 위치를 찾음(압축·축소 차이와 무관하게 위치만 확인)
            res = []
            for xx in range(x - 24, x + 25, 4):
                exp = gray(["-ss", ff._seek(sf, src.fps), "-i", sample], f"crop={cw}:2160:{xx}:0,scale=1080:1920",
                           1080, 1920)
                res.append((np.abs(got - exp).mean(), xx))
            diff, bx = min(res)
            worst = max(worst, abs(bx - x))
            print(f"x{speed:g} 출력 {n:3d} ← 원본 {sf:3d} 기대 x={x} 가장 맞는 x={bx} (평균차 {diff:.1f})")
        assert worst <= 4, worst
    # 흔들림 보정 + 리프레이밍(보정 → 크롭): 실행·길이·이동 방향 확인
    p.grade["stab"] = 40
    seg = Segment(src.id, 0, 110, 1.0, reframe=keys)
    f = d / "reframe_stab.mp4"
    ff.render_video(p, [seg], str(f), orientation="vertical")
    r = ff.probe(str(f))
    assert (r["width"], r["height"], r["frames"]) == (1080, 1920, 55), r
    a = gray(["-i", str(f)], "select=eq(n\\,2)", 1080, 1920)
    b = gray(["-i", str(f)], "select=eq(n\\,52)", 1080, 1920)
    e0 = gray(["-ss", ff._seek(4, src.fps), "-i", sample], f"crop={cw}:2160:{1313 - 540}:0,scale=1080:1920", 1080, 1920)
    e1 = gray(["-ss", ff._seek(104, src.fps), "-i", sample], f"crop={cw}:2160:{1313 + 540}:0,scale=1080:1920", 1080, 1920)
    print("흔들림 보정+리프레이밍 시작/끝 평균차:", round(np.abs(a - e0).mean(), 2), round(np.abs(b - e1).mean(), 2),
          "(반대 위치와 비교:", round(np.abs(a - e1).mean(), 2), ")")
    assert np.abs(a - e0).mean() < np.abs(a - e1).mean() and np.abs(b - e1).mean() < np.abs(b - e0).mean()
    # 가로 출력에는 영향 없음
    p.grade["stab"] = 0
    ff.render_video(p, [seg], str(d / "reframe_h.mp4"), orientation="horizontal")
    print("REFRAME OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
