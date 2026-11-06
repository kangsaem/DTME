"""자동 보정(추천·AUTO) 점검: 합성 장면 판단 · 값 방향 · 키프레임 · 렌더 가능 · 명암/색 균형.
사용: python tests/test_auto.py <작업폴더>      (실제 수중 영상이 아닌 합성 화면이라 기준값 확인용)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dtme import auto, ff, paths  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402

W, H = 320, 180
rng = np.random.default_rng(1)


def blob(img, cx, cy, r, col, soft=0.6):
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
    m = np.clip((1 - d) / soft, 0, 1)[..., None]
    img[:] = img * (1 - m) + np.array(col, np.float32) * m


def texture(img, amp):
    t = rng.random((H // 6 + 1, W // 6 + 1)).repeat(6, 0).repeat(6, 1)[:H, :W]
    img *= (1 - amp + 2 * amp * t)[..., None]


def gradient(top, bot):
    k = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    return (np.array(top, np.float32) * (1 - k) + np.array(bot, np.float32) * k).repeat(W, 1)


def scene(kind):
    if kind == "shallow":
        a = gradient((0.25, 0.55, 0.60), (0.62, 0.70, 0.58))
        texture(a, 0.15)
    elif kind == "coral":
        a = gradient((0.25, 0.55, 0.60), (0.55, 0.62, 0.52))
        texture(a, 0.15)
        for cx, cy in ((70, 130), (160, 140), (250, 125)):
            blob(a, cx, cy, 34, (0.50, 0.26, 0.22), soft=0.3)
    elif kind == "deep":
        a = gradient((0.05, 0.30, 0.40), (0.14, 0.36, 0.36))
        texture(a, 0.35)
    elif kind == "light":
        a = gradient((0.03, 0.15, 0.30), (0.04, 0.18, 0.28))
        blob(a, W / 2, H / 2, 55, (0.85, 0.62, 0.48), soft=0.5)
    elif kind == "night":
        a = np.full((H, W, 3), (0.01, 0.012, 0.02), np.float32)
        blob(a, W / 2, H / 2, 35, (0.75, 0.55, 0.42), soft=0.5)
    elif kind == "bluewater":
        a = gradient((0.06, 0.38, 0.62), (0.03, 0.20, 0.45))
    a += rng.normal(0, 0.004, a.shape).astype(np.float32)
    return np.clip(a, 0, 1)


def check_classify():
    ok = True
    for kind, want in (("shallow", "shallow"), ("coral", "shallow"), ("deep", "deep"), ("light", "light"),
                       ("night", "night"), ("bluewater", "bluewater")):
        samples = [(i * 100, scene(kind)) for i in range(3)]
        r = auto.recommend(samples, dict(lut=""))
        g = r["grade"]
        print(f"{kind:10s} → {r['scene']:9s} {r['subject'] or '-':6s} 빨강 {g['r_gain']:.2f} 파랑 {g['b_gain']:.2f} "
              f"물빛 {g['water']} 녹황 {g['gy']} 커브 {g['curve'][1:-1]}")
        ok &= r["scene"] == want
        if kind == "coral":
            ok &= r["subject"] == "coral"
        if kind == "shallow":
            ok &= r["subject"] == "fish"
    assert ok, "장면 판단 틀림"
    # 강도: 강 > 중 > 약 (빨강)
    s = [(0, scene("shallow"))]
    rv = [auto.recommend(s, dict(lut=""), strength=k)["grade"]["r_gain"] for k in ("weak", "mid", "strong")]
    print("강도 약·중·강 빨강:", rv)
    assert rv[0] < rv[1] < rv[2] <= 2.0
    # 장면 직접 지정
    assert auto.recommend(s, dict(lut=""), scene="light")["scene"] == "light"
    # 프리셋 14개
    keys = auto.preset_keys()
    print("기본 프리셋:", len(keys), [auto.preset_label(k, True) for k in keys])
    assert len(keys) == 14 and auto.preset_label("deep/turtle") == "깊은 수심 · 거북이"


def make_video(path, kinds, sec_each=2.0, fps=30):
    frames = []
    for k in kinds:
        im = (scene(k) * 255).astype(np.uint8)
        frames += [im] * int(sec_each * fps)
    data = b"".join(f.tobytes() for f in frames)
    ff.run([paths.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
            "-i", "-", "-vf", "scale=1280:720", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", str(path)], data=data)
    info = ff.probe(str(path))
    return Source(path=str(path), **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})


def check_video(work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    # 한 클립 안 얕은 → 깊은 → 얕은: 키프레임이 생겨야
    src = make_video(d / "change.mp4", ["shallow", "shallow", "deep", "deep", "shallow"], 2.0)
    fr = auto.sample_frames(src, a=0, b=src.frames)
    print("샘플 프레임:", fr)
    assert 1 <= len(fr) <= auto.SAMPLE_MAX
    r = auto.analyze_source(src, dict(lut=""))
    print("변화 클립:", r["scene"], "키 빨강", r["gkeys"].get("r_gain"))
    assert r["gkeys"] and 2 <= len(r["gkeys"]["r_gain"]) <= 6
    vals = [k["v"] for k in r["gkeys"]["r_gain"]]
    assert max(vals) - min(vals) > 0.15
    # 변화 없는 클립: 키 없음
    src2 = make_video(d / "same.mp4", ["deep"] * 3, 2.0)
    r2 = auto.analyze_source(src2, dict(lut=""))
    print("같은 클립:", r2["scene"], "키", r2["gkeys"])
    assert not r2["gkeys"] and r2["scene"] == "deep"
    # 추천값으로 실제 렌더 (커브·물빛·녹황·키프레임 포함)
    p = Project()
    p.output.encoder, p.output.gpu_decode = "x264", False
    p.grade.update(lut="")
    p.sources.append(src)
    src.grade = {k: v for k, v in r["grade"].items() if p.grade.get(k) != v}
    src.gkeys = r["gkeys"]
    out = d / "auto_render.mp4"
    ff.render_video(p, [Segment(src.id, 0, src.frames, 1.0, gkeys=src.gkeys)], str(out), orientation="horizontal")
    info = ff.probe(str(out))
    print("렌더:", info["width"], "x", info["height"], round(info["duration"], 2), "초")
    assert info["width"] == 1920 and info["duration"] > 9
    # 깊은 구간(가운데) 빨강/초록 비가 원본보다 1 에 가까워졌는지
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-ss", "5", "-i", str(out), "-frames:v", "1", "-vf",
                  "scale=320:180,scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    a = np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(float).reshape(-1, 3).mean(0)
    b = scene("deep").reshape(-1, 3).mean(0) * 255
    print(f"깊은 구간 빨강 평균 원본 {b[0]:.1f} → 보정 {a[0]:.1f}, R/G {b[0] / b[1]:.2f} → {a[0] / a[1]:.2f}")
    # 합성 화면 기준: 깊은 구간 빨강이 원본보다 줄지 않아야(S커브가 암부를 누르는 것과 균형)
    assert a[0] > b[0] * 1.05 and a[0] / a[1] >= b[0] / b[1] - 0.02


def check_fix():
    a = scene("shallow") * 0.8 + 0.1            # 흐릿한 화면(명암 좁음)
    c = auto.contrast_fix(a)
    from dtme.ui_curve import natural_spline
    lo, hi = auto.tone_ends(a)
    sp = dict(natural_spline(c, 512))
    xs = np.array(sorted(sp))

    def f(v):
        return float(np.interp(v, xs, [sp[x] for x in xs]))
    print(f"명암: p2 {lo:.2f}→{f(lo):.3f}  p98 {hi:.2f}→{f(hi):.3f}  커브 {c}")
    assert f(lo) < 0.06 and f(hi) > 0.94 and len(c) <= 7
    assert all(y2 >= y1 for (_x1, y1), (_x2, y2) in zip(c, c[1:])), "커브가 거꾸로"
    r, b = auto.balance_fix(scene("shallow"))
    print(f"색 균형: 빨강 {r:.2f} 파랑 {b:.2f}")
    assert r > 1.1
    m = auto.range_marks(np.clip(a, 0, 1))
    print("목표선 표시(R,G,B):", m)
    assert all(t == "short" and bt == "short" for t, bt in m)


if __name__ == "__main__":
    check_classify()
    check_fix()
    check_video(sys.argv[1] if len(sys.argv) > 1 else "auto_test")
    print("AUTO OK")
