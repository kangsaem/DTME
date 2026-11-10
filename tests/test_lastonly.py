"""v0.16.40: 한 장만 만드는 체인(멈춘 화면·확대·스틸)에서 마지막 장을 일찍 고름 → 결과 화면은 예전(끝에서 고름)과 같아야 함.
python tests/test_lastonly.py <합성4K.mp4>"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import numpy as np  # noqa: E402

from dtme import ff, paths, project  # noqa: E402
from dtme.project import Source  # noqa: E402


def old_preview(c, g):
    cwd, lut = ff._lut_for(g)
    vf = ff.lens_chain(g, *c.size) + ff.grade_chain(g, lut, 1280) + [f"select=gte(n\\,{c.lead})", "format=rgb24"]
    return ff.run([paths.ffmpeg(), "-v", "error", *c.input_args(), "-filter_complex", ff.graph(vf, "[0:v]", "[po]"),
                   "-map", "[po]", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"], cwd=cwd, data=c.data)


def px(png):
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-f", "image2pipe", "-c:v", "png", "-i", "-", "-f", "rawvideo",
                  "-pix_fmt", "rgb24", "-"], data=png)
    return np.frombuffer(raw, np.uint8).astype(int)


def main(video):
    info = ff.probe(video)
    s = Source(path=video, fps_num=info["fps_num"], fps_den=info["fps_den"], frames=info["frames"],
               width=info["width"], height=info["height"])
    lut = next((x for x in ff.list_luts() if "DJI" in x), "")
    base = dict(project.NEUTRAL)
    base.update(lut=lut, r_gain=1.2, b_gain=1.05, hue=5, sat=1.1, sharpen=0.3, nr_chroma=60, nr_luma=25, water=12, gy=20,
                wnr=40, curve=[[0, 0], [0.25, 0.2], [0.5, 0.5], [0.75, 0.8], [1, 1]])
    cases = {"전체": base, "노이즈 없음": dict(base, nr_chroma=0, nr_luma=0), "렌즈": dict(base, lens=60),
             "LUT만": ff.lut_only(base)}
    fr = min(60, s.frames - 1)
    c = ff.cached_frame(s, fr)
    for name, g in cases.items():
        t0 = time.perf_counter()
        a = px(old_preview(c, g))
        t1 = time.perf_counter()
        b = px(ff.render_preview(c, g))
        t2 = time.perf_counter()
        d = int(np.abs(a - b).max())
        print(f"{name}: 차이 최대 {d} · 예전 {t1 - t0:.2f}초 → {t2 - t1:.2f}초")
        assert d == 0, name
    assert "select" in ff.last_only(["a", "hqdn3d=1", "b"], 3)[2] and ff.last_only(["a"], 0) == ["a"]
    assert ff.last_only(["a", "b"], 2)[0].startswith("select")
    # 같은 화면·같은 값 = 기억한 것(ffmpeg 안 띄움)
    t0 = time.perf_counter()
    again = ff.render_preview(c, base)
    assert time.perf_counter() - t0 < 0.05 and again is ff.render_preview(c, base)
    settings_check()
    print("OK")


def settings_check():
    """settings.json: 읽어 둔 것 쓰기 · 밖에서 고치면 다시 읽음 · 여러 스레드가 같이 써도 안 깨짐 · 깨진 파일 = 기본값."""
    import json
    import tempfile
    import threading
    f = Path(tempfile.mkdtemp()) / "settings.json"
    old = paths.settings_path
    paths.settings_path = lambda: f
    try:
        assert project.get_setting("a", 7) == 7
        project.set_setting("a", 1)
        project.set_setting("d", {"x": 1})
        v = project.get_setting("d")
        v["x"] = 2                                           # 받은 것을 고쳐도 저장된 값은 그대로
        assert project.get_setting("d") == {"x": 1} and project.get_setting("a") == 1
        ts = [threading.Thread(target=lambda i=i: [project.set_setting(f"k{i}", j) for j in range(30)]) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        d = json.loads(f.read_text(encoding="utf-8"))
        assert all(d[f"k{i}"] == 29 for i in range(6)) and d["a"] == 1, d
        time.sleep(0.02)
        f.write_text(json.dumps({"a": 5, "pad": "x" * 50}), encoding="utf-8")     # 밖에서 고침
        assert project.get_setting("a") == 5 and project.get_setting("k0", None) is None
        f.write_text("{깨짐", encoding="utf-8")
        assert project.get_setting("a", 9) == 9
        project.set_setting("a", 3)
        assert json.loads(f.read_text(encoding="utf-8")) == {"a": 3}
        pj = f.with_name("p.json")
        project.write_json_atomic(pj, {"v": 1})
        assert json.loads(pj.read_text(encoding="utf-8")) == {"v": 1} and not pj.with_name("p.json.tmp").exists()
    finally:
        paths.settings_path = old
    print("설정 파일 OK")


if __name__ == "__main__":
    main(sys.argv[1])
