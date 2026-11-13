"""v0.16.84 수심 그래프: FIT · DTMD zip/json 읽기 · 시각 맞추기 · 렌더(글자 1초 뒤 · 그래프 2초부터 긁기 · 9.5초에 사라짐).
사용: python tests/test_dive.py <작업폴더>"""
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
sys.path.insert(0, str(HERE))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtGui import QGuiApplication  # noqa: E402
app = QGuiApplication(sys.argv)
from fitgen import make_fit, profile  # noqa: E402
from dtme import divelog as DL, dive_draw, ff, paths  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402


def naive(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


def main(work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    # 1) FIT: 10:30 KST(UTC 01:30) 입수 전 1분 수면 → 10:31 하강 시작, 2번째 13:30
    st = int(naive(2026, 10, 27, 1, 30, 0))
    fit = d / "dive.fit"
    fit.write_bytes(make_fit([(st, profile(40, 22)), (st + 3 * 3600, profile(35, 18))]))
    ds = DL.read_dives(str(fit))
    print("FIT", [(DL.fmt_hm(x["start"]), x["max"], int(DL.dur(x))) for x in ds])
    assert len(ds) == 2 and ds[0]["start"] == naive(2026, 10, 27, 10, 31, 0) and ds[0]["max"] == 22.0
    assert abs(DL.depth_at(ds[0], 60) - 11.0) < 0.3                  # 하강 2분에 22m → 1분 = 11m
    assert DL.is_dive_file(str(fit))
    # 2) DTMD 백업(json · zip): 첫 입수 10:30(분), 둘째 = 앞 다이빙 + 수면 휴식
    pts = [{"t": 0, "d": 0}, {"t": 120, "d": 20}, {"t": 2400, "d": 5}, {"t": 2460, "d": 0}]
    logs = {"app": "DTMD", "kind": "logbook", "v": 2, "logs": [
        {"id": "a", "date": "2026-10-28", "time": "09:15", "memo": "",
         "sum": {"N0": 2460, "maxD": 20, "dv": [{"N": 2460, "maxD": 20, "si": 0}, {"N": 2000, "maxD": 15, "si": 70}]},
         "state": {"dives": [{"pts": pts, "fit": True}, {"pts": pts, "memo": "Teric (FIT)"}]}},
        {"id": "b", "date": "2026-10-29", "time": "08:00", "memo": "",                      # 손으로 그린 로그 = 뺌
         "sum": {"N0": 2460, "maxD": 20}, "state": {"dives": [{"pts": pts}]}}]}
    js = d / "logbook.json"
    js.write_text(json.dumps(logs), encoding="utf-8")
    zp = d / "dtmd-logbook.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("logbook.json", json.dumps(logs))
        z.writestr("photos/x.jpg", b"jpg")
    for f in (js, zp):
        assert DL.is_dive_file(str(f)), f
        dd = DL.read_dives(str(f))
        print("DTMD", f.name, [(DL.fmt_date(x["start"]), DL.fmt_hm(x["start"])) for x in dd])
        assert [DL.fmt_hm(x["start"]) for x in dd] == ["09:15", "11:06"], dd       # 09:15 + 41분 + 수면 70분
    logs["logs"][0]["time"] = "09:15:30"                                   # 초 단위 저장(DTMD 새 형식)
    js2 = d / "logbook2.json"
    js2.write_text(json.dumps(logs), encoding="utf-8")
    dd = DL.read_dives(str(js2))
    assert dd[0]["start"] == naive(2026, 10, 28, 9, 15, 30), dd[0]["start"]
    logs["logs"][0]["state"]["dives"][1]["sec0"] = 11 * 3600 + 7 * 60 + 9      # DTMD 새 형식(다이빙마다 입수 초, 그날 0시부터)
    logs["logs"][0]["state"]["dives"][1]["pts"] = [{"t": 0, "d": 0}, {"t": 30, "d": 0}, {"t": 32, "d": 0.8}] + pts[1:]
    js3 = d / "logbook3.json"
    js3.write_text(json.dumps(logs), encoding="utf-8")
    dd = DL.read_dives(str(js3))
    assert dd[1]["start"] == naive(2026, 10, 28, 11, 7, 39), DL.fmt_hm(dd[1]["start"])   # 앞 수면 30초 = 뺌(입수 시각도 30초 뒤)
    proj_json = d / "project.json"
    proj_json.write_text(json.dumps({"sources": []}), encoding="utf-8")
    assert not DL.is_dive_file(str(proj_json))
    # 3) 같은 다이빙이면 FIT 우선
    fit_like = [dict(ds[0])]
    dt_like = [{**ds[0], "src": "dtmd", "id": "x", "start": ds[0]["start"] - 50}]
    m = DL.merge(dt_like, fit_like)
    assert len(m) == 1 and m[0]["src"] == "fit"
    # 4) 파일 이름 시각(초까지)
    assert DL.name_time("DJI_20261027104005_0001_D.MP4") == naive(2026, 10, 27, 10, 40, 5)
    assert DL.name_time("VID_20260917_080520_006.mp4") == naive(2026, 9, 17, 8, 5, 20)
    # 5) 렌더: 10:40:00 에 시작한 14초 클립 → 첫 컷 12초 · 둘째 컷
    v = d / "DJI_20261027104000_0001_D.MP4"
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1c5a8a:s=1920x1080:r=30000/1001:d=14",
                    "-f", "lavfi", "-i", "sine=d=14", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(v)], check=True)
    info = ff.probe(str(v))
    src = Source(path=str(v), **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0)
    p.output.encoder, p.output.gpu_decode, p.output.quality = "x264", False, "small"
    w = dive_draw.when_at(src, Segment(src.id, 0, 360), 3.0, 0.0)
    s_ = dive_draw.state(ds, w)
    assert s_ and abs(s_[1] - (9 * 60 + 3)) < 0.01, s_                   # 10:40:03 − 10:31 = 9분 3초
    segs = [Segment(src.id, 0, 360), Segment(src.id, 0, 120, trans={"type": "fade", "dur": 0.5})]
    out, plain = d / "out.mp4", d / "plain.mp4"
    ff.render_video(p, segs, str(out), orientation="horizontal", extras={"dive": {"dives": ds, "off": 0}})
    ff.render_video(p, segs, str(plain), orientation="horizontal", extras={})

    def grab(f, t, box):
        raw = ff.run([paths.ffmpeg(), "-v", "error", "-ss", f"{t}", "-i", str(f), "-frames:v", "1", "-vf",
                      f"crop={box[2]}:{box[3]}:{box[0]}:{box[1]},format=rgb24", "-f", "rawvideo", "-"])
        return np.frombuffer(raw, np.uint8).reshape(box[3], box[2], 3).astype(float)
    TXT = (40, 90, 260, 160)              # 수심·시각 글자 자리
    GR = (0, 760, 1920, 300)              # 그래프 자리
    res = {}
    for t in (0.5, 1.25, 3.0, 5.0, 8.0, 10.5):
        a, b = grab(out, t, TXT), grab(plain, t, TXT)
        ga, gb = grab(out, t, GR), grab(plain, t, GR)
        res[t] = (round(float((a - b).max()), 1), round(float((ga - gb).max()), 1))
    print("차이(글자, 그래프):", res)
    assert res[0.5][0] < 16 and res[0.5][1] < 16                         # 처음 = 없음
    assert res[3.0][0] > 60 and res[5.0][0] > 60 and res[5.0][1] > 60    # 글자 · 그래프 보임
    assert res[8.0][0] < 16 and res[8.0][1] > 60                          # 7초 뒤 글자 사라짐, 그래프는 9초까지
    assert res[10.5][0] < 16 and res[10.5][1] < 16                        # 9.5초 뒤 다 사라짐
    # 6) v0.16.86 UTC 로 맞추기: 카메라 = 필리핀(UTC+8) · 다이빙 컴퓨터 = 한국(UTC+9). 현지끼리면 1시간 어긋남
    v8 = d / "DJI_20261027094000_0002_D.MP4"                              # 09:40 PH = 01:40 UTC = 입수(01:31 UTC) 9분 뒤
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1c5a8a:s=640x360:r=30:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-metadata", "creation_time=2026-10-27T01:40:01.000000Z", str(v8)], check=True)
    i8 = ff.probe(str(v8))
    s8 = Source(path=str(v8), **{k: i8[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    assert abs(i8["cutc"] - naive(2026, 10, 27, 1, 40, 1)) < 0.01
    m8 = dive_draw.match(ds, s8, 2.0, 0.0)
    print("UTC 맞추기:", DL.fmt_hm(m8[2]), round(m8[1]), "초")
    assert m8 and abs(m8[1] - (9 * 60 + 2)) < 0.01 and DL.fmt_hm(m8[2]) == "09:40"     # 표시 = 카메라 현지 시각
    du = [{**x, "utc": None} for x in ds]                                  # UTC 모름 = 현지끼리 → 없음(1시간 차이)
    for x in du:
        x.pop("utc")
    assert dive_draw.match(du, s8, 2.0, 0.0) is None and dive_draw.match(du, s8, 2.0, 3600.0) is not None
    logs["logs"][0]["state"]["dives"][0].update(utc0=naive(2026, 10, 28, 0, 15, 0), off0=9 * 3600, sec0=9 * 3600 + 15 * 60)
    js4 = d / "logbook4.json"
    js4.write_text(json.dumps(logs), encoding="utf-8")
    d4 = DL.read_dives(str(js4))
    assert d4[0].get("utc") == naive(2026, 10, 28, 0, 15, 0) and d4[0]["start"] == naive(2026, 10, 28, 9, 15, 0)
    print("DIVE OK")


if __name__ == "__main__":
    main(sys.argv[1])
