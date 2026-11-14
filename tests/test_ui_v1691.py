"""v0.16.91: 타이핑 · 날짜 바 · 시작·끝 화면 · 컷 LOG 칩 · 글자 복사/붙이기·Shift 고르기·우클릭 메뉴 · 끝 페이드 렌더.
사용: python tests/test_ui_v1691.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from fitgen import make_fit, profile  # noqa: E402
from dtme import autoedit, divelog, ff, paths, ui_style  # noqa: E402
from dtme.project import type_count, type_lines, new_text, cut_spans  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
app = QApplication(sys.argv); M.dark(app)
FFM = paths.ffmpeg()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


def grab(vf, at, size="1920x1080", src=None):
    cwd = str(paths.cache_dir() / "lut")
    inp = ["-i", src] if src else ["-f", "lavfi", "-i", f"color=black:s={size}:r=30:d=6"]
    r = subprocess.run([FFM, "-v", "error", *inp, "-vf", vf, "-ss", f"{at}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       cwd=cwd, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-600:]
    wh = [int(x) for x in size.split("x")]
    return np.frombuffer(r.stdout, np.uint8).reshape(wh[1], wh[0], 3)


# ---------------------------------------------------------------- 1) 타이핑(엔진·렌더)
d = {"kind": "text", "ain": "type", "t0": 1.0, "t1": 5.0, "text": "ab\ncd", "tdelay": 0.5}
assert [type_count(d, x) for x in (1.0, 1.5, 1.56, 1.62, 1.68)] == [0, 1, 2, 3, None] and type_lines("ab\ncd", 3) == ["ab", "c"]
t = new_text(0.0, 4.0, "Hello 보홀\nDTME 2026"); t.update(size=80, bg="none")
ta = dict(t, ain="type", tdelay=0.2)
full, typed = grab(ff.text_filter(t, 1920, 1080), 2.0), grab(ff.text_filter(ta, 1920, 1080), 2.0)
diff = np.abs(full.astype(int) - typed).mean()
mid, before = grab(ff.text_filter(ta, 1920, 1080), 0.45), grab(ff.text_filter(ta, 1920, 1080), 0.1)
def _bb(x):
    ys, xs = np.nonzero(x.max(2) > 128)
    return np.array([xs.min(), ys.min(), xs.max(), ys.max()])
shift = np.abs(_bb(full) - _bb(typed)).max()
print("타이핑: 다 친 화면 차이", round(diff, 2), "상자 어긋남 px", int(shift), "중간 픽셀", int((mid > 128).sum()), "/", int((typed > 128).sum()))
assert shift <= 3 and (before > 128).sum() == 0 and 0 < (mid > 128).sum() < 0.6 * (typed > 128).sum()

from dtme.ui_titles import RectDialog, TextDialog  # noqa: E402
td = TextDialog(dict(t))
keys = [b.property("key") for b in td.anim["ain"].buttons()]
assert keys[-1] == "type" and "type" not in [b.property("key") for b in td.anim["aout"].buttons()]
next(b for b in td.anim["ain"].buttons() if b.property("key") == "type").click()
assert td.t["ain"] == "type"
assert "type" not in [b.property("key") for b in RectDialog({"kind": "rect", "t0": 0, "t1": 1}).anim["ain"].buttons()]

# ---------------------------------------------------------------- 2) 날짜 바 자리
for wh in ((1920, 1080), (1080, 1920)):
    rc, ty, tdt, ttm = autoedit.date_bar(divelog._naive(2026, 10, 30, 10, 30), 2.0, wh)
    assert [x["text"] for x in (ty, tdt, ttm)] == ["2026", "10/30", "10:30"] and all(x["ain"] == "type" for x in (ty, tdt, ttm))
    assert abs((rc["cx"] - rc["w"] / 2)) < 1e-4 and abs(rc["cy"] - (autoedit.DB_CY + autoedit.DB_DOWN * rc["h"])) < 1e-3   # 왼쪽 끝 · 64% + 바 2개 아래
    bl = {x["text"]: ff.type_layout(x, *wh)[0][0] for x in (ty, tdt, ttm)}                        # (줄, 왼쪽 x, 기준선 y)
    k = min(wh) / 1080
    assert abs(bl["10/30"][2] - bl["10:30"][2]) < 1.0 and abs(bl["10/30"][1] - 84 * k) < 1.5 and bl["2026"][1] > bl["10/30"][1]
    assert bl["2026"][2] < bl["10/30"][2] - 30 * k
    assert tdt["tdelay"] > ty["tdelay"] and ttm["tdelay"] > tdt["tdelay"]
print("날짜 바 자리 OK")

# ---------------------------------------------------------------- 3) 지명·기간·끝 문구
assert divelog.memo_loc("수온 28\n위치: 팡라오, 보홀주, 필리핀") == "보홀주, 필리핀"
a_ = {"id": "x", "src": "dtmd", "start": 1000.0, "pts": [[0, 0], [600, 10]], "max": 10, "loc": "보홀주, 필리핀"}
f_ = {"id": "y", "src": "fit", "start": 1010.0, "pts": [[0, 0], [600, 10]], "max": 10, "utc": 5.0}
mg = divelog.merge([a_], [f_])
assert len(mg) == 1 and mg[0]["src"] == "fit" and mg[0]["loc"] == "보홀주, 필리핀"
t0 = divelog._naive(2026, 10, 27, 9, 0)
assert autoedit.period_text(t0, t0 + 3600) == "2026.10.27" and autoedit.period_text(t0, t0 + 6 * 86400) == "2026.10.27 – 11.02"
assert autoedit.end_lines(False, [], "", "")[0][0] == "See You Underwater"
# 클립이 너무 많음(1분에 20개): 가능한 많이(13개 = 4.5초씩) · 흐림·흔들림 먼저 뺌
from dtme.project import Project, Source  # noqa: E402
pj = Project()
pk = [{"src": Source(f"/x/DJI_2026102710{i:02d}00_0001_D.MP4", 30, 1, 1200), "score": np.full(80, 1.0 + i * 0.01),
       "contrast": 0.02 if i in (3, 7) else 0.2, "motion": 0.2 if i == 5 else 0.01} for i in range(20)]
kept, dropped = autoedit.trim_picks(pj, pk, 1)
print("클립 뺌:", dropped)
assert len(kept) == 13 and {"blur", "shake"} <= {w_ for _n, w_ in dropped}
assert all(pk[i] not in kept for i in (3, 5, 7)) and pk[19] in kept and kept == [x for x in pk if x in kept]
assert autoedit.trim_picks(pj, pk[:5], 1) == (pk[:5], [])

# ---------------------------------------------------------------- 4) 화면: 자동 편집(날짜 바 · 시작·끝 화면)
vids = []
for name, col in (("DJI_20261027104000_0001_D.MP4", "0x1c5a8a"), ("DJI_20261027120000_0002_D.MP4", "0x2a7a6a"),
                  ("DJI_20261027140000_0003_D.MP4", "0x6a4a2a")):
    v = os.path.join(W, name)
    subprocess.run([FFM, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d=40,hue=s=0.4,drawbox=c={col}@0.6:t=fill",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
    vids.append(v)
st0 = int(datetime(2026, 10, 27, 1, 30, tzinfo=timezone.utc).timestamp())       # 현지 10:30 ~ 11:10
fit = os.path.join(W, "teric.fit")
open(fit, "wb").write(make_fit([(st0, profile(40, 22))]))
w = MainWindow(); w.resize(1500, 900); w.show()
st, e = w.state, w.edit
e.import_files(vids + [fit])
assert wait(90, lambda: len(st.project.sources) == 3 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
p = st.project
for dv in p.dives:
    dv["loc"] = "보홀주, 필리핀"
from dtme import dive_draw  # noqa: E402
assert dive_draw.guess_off(p.dives, p.sources) == 0.0 and p.dive_off == 0.0
import dataclasses  # noqa: E402
sh = [dataclasses.replace(s, path=s.path.replace("_20261027104000", "_20261027094000"), cutc=-1.0) for s in p.sources if "104000" in s.path]
print("시간대 1시간 다른 카메라:", dive_draw.guess_off(p.dives, sh))
assert dive_draw.guess_off(p.dives, sh) == 3600.0              # 카메라 필리핀(+8) · 시계 한국(+9) = +3600초(사용자 11:07 확인)
p.output.folder = os.path.join(W, "out"); p.output.encoder = "x264"; p.output.gpu_decode = False
from dtme.ui_autoedit import AutoEditDialog  # noqa: E402
dlg = AutoEditDialog(st, {s.id for s in p.sources}, w)
print("지명:", dlg.place.text(), "| 끝 문구:", dlg.end_text.text())
assert dlg.place.text() == "보홀주, 필리핀" and dlg.end_text.text().startswith("1 DIVE · MAX 22.0m · 40m")   # 실제 글(커서로 고침)
assert dlg.settings()["end_text"] == ""                       # 안 고침 = 자동(글자 크기 등 자동 그대로)
from PySide6.QtTest import QTest as _QT  # noqa: E402
dlg.end_text.setFocus(); dlg.end_text.end(False); _QT.keyClicks(dlg.end_text, "!")
assert dlg.settings()["end_text"].endswith("2026.10.27!")
assert [x[0] for x in autoedit.end_lines(True, [], "", "", dlg.settings()["end_text"])][1].endswith("!")
dlg._end_auto = True; dlg._end_hint()
from PySide6.QtWidgets import QApplication as _QA  # noqa: E402
_orig_mods = _QA.keyboardModifiers
dlg._toggle(dlg.list.item(0)); dlg._toggle(dlg.list.item(0))      # 끔 → 켬(기준 = 0번 켬)
dlg._toggle(dlg.list.item(2))                                    # 2번 끔
dlg._toggle(dlg.list.item(0))                                    # 0번 끔(기준 = 끔)
_QA.keyboardModifiers = staticmethod(lambda: Qt.ShiftModifier)
dlg._toggle(dlg.list.item(2))                                    # Shift = 0~2 모두 끔
_QA.keyboardModifiers = _orig_mods
assert dlg.chosen() == []
for i in range(3):
    dlg._toggle(dlg.list.item(i))
assert len(dlg.chosen()) == 3
print("음악 칸:", dlg.music_on.text())
assert "기본 음악" in dlg.music_on.text() and dlg.music_on.isChecked() and len(st.default_music()) == 2   # v0.16.91 곡 없음 = 기본 음악(CC0)
dlg.length.setValue(1); dlg.music_on.setChecked(False)
sset = dlg.settings()
assert sset["start"] == "auto" and sset["end"] == "auto" and sset["place"] == "보홀주, 필리핀"
dlg.show(); wait(0.3); dlg.grab().save(os.path.join(W, "dialog.png"))
ui_style.confirm = lambda *a_, **k_: "ok"
e.run_autoedit(dlg, sset)
assert wait(400, lambda: not dlg.isVisible()), dlg.state_lab.text()
wait(0.5)
p = st.project
segs = p.segments
names = [os.path.basename(p.source(g.src).path)[:18] for g in segs]
print("컷:", list(zip(names, [round((g.fout - g.fin) / 30, 1) for g in segs])), "앞", p.lead, "끝 페이드", p.end_fade)
assert p.lead == autoedit.START_SEC and not segs[0].trans and p.end_fade == 0.0       # 끝 화면 = 페이드 없이 끝
cards = {k: [x for x in p.titles if x.get("card") == k] for k in ("start", "end")}
print("시작 화면:", [(x["kind"], x.get("text")) for x in cards["start"]])
print("끝 화면:", [(x["kind"], x.get("text")) for x in cards["end"]])
assert [x["kind"] for x in cards["start"]] == ["image", "text", "text"] and cards["start"][1]["text"] == "보홀주, 필리핀"
assert cards["start"][2]["text"] == "2026.10.27"
assert cards["end"][1]["text"].startswith("1 DIVE · MAX 22.0m") and cards["end"][2]["text"] == "보홀주, 필리핀 · 2026.10.27"
for x in (cards["start"][0], cards["end"][0]):
    m = p.image(x["img"])
    assert m and os.path.exists(m.path) and (m.width, m.height) == (1920, 1080)
vend = max(tt + ln for _c, tt, ln in cut_spans(p))
assert abs(cards["end"][0]["t0"] - vend) < 1e-3 and abs(p.tail_of() - autoedit.END_SEC) < 1e-3
wr = cards["end"][-1]
assert wr["kind"] == "rect" and wr["color"] == "#ffffff" and abs(wr["t0"] - (vend - 1.0)) < 1e-3 and abs(wr["t1"] - (vend + 1.0)) < 1e-3
st_t = [x for x in cards["start"] if x["kind"] == "text"]
assert cards["start"][0]["ain"] == "cut" and all(x["ain"] == "type" for x in st_t)
from dtme.project import type_end  # noqa: E402
assert abs(max(type_end(x) for x in st_t) - (0.5 + 2.0 - st_t[-1]["tsec"])) < 0.02          # 2초에 다 침
assert all(x["ain"] == "cut" for x in cards["end"] if x["kind"] == "text")
bars = [x for x in p.titles if x.get("datebar") and x["kind"] == "text" and x["size"] == autoedit.DB_TIME]
print("날짜 바 시각:", [x["text"] for x in bars])
assert [x["text"] for x in bars] == ["12:00", "14:00"]          # 보정+편집 = 클립마다(다이빙 컷 = 없음)
# 전부 자동 방식(1시간 넘게 뒤만): 다이빙 컷(10:40) 다음 12:00 = 1시간 넘음, 14:00 = 넘음 / 30분 뒤 클립이면 안 넣음
import copy  # noqa: E402
picks = [{"src": s, "scene": "", "score": np.ones(80), "surface": None} for s in sorted(p.sources, key=lambda s: s.path)]
pl = autoedit.build(p, picks, 1, seed=1, date_mode="gap")
assert len([x for x in pl["titles"] if x.get("datebar")]) == 8
p2 = copy.copy(p); p2.dives = []
pl = autoedit.build(p2, picks, 1, seed=1, date_mode="gap")
print("gap(기록 없음):", [x["text"] for x in pl["titles"] if x.get("size") == autoedit.DB_TIME])
assert [x["text"] for x in pl["titles"] if x.get("size") == autoedit.DB_TIME] == ["10:40", "12:00", "14:00"]
s3 = sorted(p.sources, key=lambda s: s.path)[2]
old = s3.path
s3.path = old.replace("140000", "122000")                     # 12:20 = 마지막(12:00)보다 20분 뒤 → 안 넣음
pl = autoedit.build(p2, picks, 1, seed=1, date_mode="gap")
assert [x["text"] for x in pl["titles"] if x.get("size") == autoedit.DB_TIME] == ["10:40", "12:00"]
pl = autoedit.build(p2, picks, 1, seed=1, date_mode="clip")
assert len([x for x in pl["titles"] if x.get("size") == autoedit.DB_TIME]) == 3
s3.path = old
# 미리보기: 시작 화면(멈춤 = 다 보임) · 날짜 바
e.set_mode("timeline"); wait(0.3)
e.show_timeline(2.0); wait(0.6)
w.grab().save(os.path.join(W, "shot_start.png"))
img = e.player.mon.grab().toImage()
assert not img.isNull()
bt = next(x for x in bars)
e.show_timeline(bt["t0"] + 2.5); wait(0.6)
e.player.mon.grab().save(os.path.join(W, "shot_datebar.png"))
e.show_timeline(vend + 2.0); wait(0.6)
e.player.mon.grab().save(os.path.join(W, "shot_end.png"))

# ---------------------------------------------------------------- 5) 컷 LOG 칩 · [LOG 전체]
e.show_timeline(1.0); wait(0.3)
ls = dict(e.timeline.log_state)
print("LOG 칩:", ls)
assert ls and all(ls.values())
cid = next(iter(ls))
rects = dict((it[0], r) for it, r in zip(e.timeline.items, e.timeline._rects()))
from PySide6.QtCore import QRectF  # noqa: E402
lr = e.timeline._log_rect(QRectF(rects[cid]))
assert lr is not None
QTest.mouseClick(e.timeline, Qt.LeftButton, Qt.NoModifier, lr.center().toPoint()); wait(0.3)
g = next(x for x in p.segments if x.id == cid)
assert not g.log and e.timeline.log_state[cid] is False
if len(ls) > 1:
    assert "d9b24a" in e.b_dive.styleSheet()                  # 일부만 = 노란 테두리
e.b_dive.click(); wait(0.3)
assert p.dive_on and all(x.log for x in p.segments) and all(e.timeline.log_state.values())
e.b_dive.click(); wait(0.3)
assert not p.dive_on and not any(e.timeline.log_state.values())
QTest.mouseClick(e.timeline, Qt.LeftButton, Qt.NoModifier, lr.center().toPoint()); wait(0.3)   # 전체 꺼짐 + 칩 = 이 컷만
assert p.dive_on and g.log and sum(e.timeline.log_state.values()) == 1
w.grab().save(os.path.join(W, "shot_log.png"))
e.b_dive.click(); wait(0.3)
assert (not any(e.timeline.log_state.values())) if len(ls) == 1 else all(e.timeline.log_state.values())
if not p.dive_on:
    e.b_dive.click(); wait(0.3)
assert p.dive_on and all(e.timeline.log_state.values())

# ---------------------------------------------------------------- 6) 글자 Shift 고르기 · 복사/붙이기 · 우클릭 메뉴
tl = e.timeline
ov = [(k, dd, rr) for k, dd, rr in tl._ov_rects() if k == "title" and dd.get("datebar")]
r1 = next(rr for k, dd, rr in ov if dd["kind"] == "rect")
r2 = next(rr for k, dd, rr in ov if dd["kind"] == "text" and dd["size"] == autoedit.DB_TIME and abs(rr.center().x() - r1.center().x()) < 400)
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r1.center().toPoint()); wait(0.2)
QTest.mouseClick(tl, Qt.LeftButton, Qt.ShiftModifier, r2.center().toPoint()); wait(0.2)
print("Shift 범위:", len(tl.ov_multi))
assert len(tl.ov_multi) == 4                                    # 같은 시각의 날짜 바 4개(사각형·연도·날짜·시각)
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r1.center().toPoint()); wait(0.2)
assert len(tl.ov_multi) == 4                                    # 고른 묶음 안을 누름 = 묶음 그대로(같이 끌기)
tl.ov_multi = set()
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r1.center().toPoint()); wait(0.2)
assert len(tl.ov_multi) == 1
QTest.mouseClick(tl, Qt.LeftButton, Qt.ControlModifier, r2.center().toPoint()); wait(0.2)
print("Ctrl 같이 고름:", len(tl.ov_multi))
assert len(tl.ov_multi) == 2
n0 = len(p.titles)
e.tl_time = 20.0
QTest.keyClick(tl, Qt.Key_C, Qt.ControlModifier); wait(0.1)
QTest.keyClick(tl, Qt.Key_V, Qt.ControlModifier); wait(0.3)
new = [x for x in p.titles if x["id"] in tl.ov_multi]
print("붙인 것:", [(x["kind"], round(x["t0"], 2)) for x in new], "글자 수", n0, "→", len(p.titles))
assert len(p.titles) == n0 + 2 and len(new) == 2 and abs(min(x["t0"] for x in new) - 20.0) < 1e-6 and not any(x.get("follow") for x in new)
e.menu_hook = lambda m: next(a for a in m.actions() if a.text() == "맨 아래로")
e._ov_menu("title", new[0]["id"], QPoint(0, 0)); wait(0.2)
assert {x["id"] for x in p.titles[:2]} == {x["id"] for x in new}
e.menu_hook = lambda m: next(a for a in m.actions() if a.text().startswith("삭제"))
e._ov_menu("title", new[0]["id"], QPoint(0, 0)); wait(0.2)
e.menu_hook = None
assert len(p.titles) == n0
w.undo(); wait(0.3)
assert len(st.project.titles) == n0 + 2
w.undo(); wait(0.2); w.undo(); wait(0.3)
p = st.project
assert len(p.titles) == n0, len(p.titles)

# ---------------------------------------------------------------- 6b) 재생 중 전환 구간 = 만든 전환 영상 덮기
from PySide6.QtGui import QImage as _QI  # noqa: E402
fr = [_QI(64, 36, _QI.Format_RGB888) for _ in range(60)]
e._tp_cache = {"x": (fr, 9.0, 10.0, 0.5)}
_ip = e.player.is_playing
e.player.is_playing = lambda: True
e._trans_overlay(10.2)
assert e.trans_prev.isVisible() and e.trans_prev.sync and e.trans_prev.i == round(1.2 * 29.97)
e._trans_overlay(10.6)
assert not e.trans_prev.isVisible()
e.player.is_playing = _ip
st.touch("segments"); wait(0.1)
assert not e._tp_cache

# ---------------------------------------------------------------- 7) 렌더: 시작 = 바로 · 끝 = 흰색 → 끝 화면(페이드 없이 끝) · 시작 화면 = 흰빛 + 남색 글자
e.timeline_to_render(); it = p.render_items[-1]
assert it.lead == autoedit.START_SEC and it.end_fade == 0.0
e.render_panel.render(); assert wait(1500, lambda: not e.render_panel.running)
outs = [f for f in os.listdir(os.path.join(W, "out")) if f.endswith(".mp4")]
print("출력:", outs, e.render_panel.status.get(it.id, "")[:60])
assert outs
out = os.path.join(W, "out", outs[0])
dur = float(ff.probe(out)["frames"]) / 29.97
exp = p.lead + p.out_seconds() + p.tail_of()
print("길이", round(dur, 2), "기대", round(exp, 2))
assert abs(dur - exp) < 0.2
vend_r = p.lead + p.out_seconds()
f0, f1, f2, fw, fz = (grab("null", x, src=out) for x in (0.05, 3.0, p.lead - 0.6, vend_r, dur - 0.05))
navy = ((f1[..., 2].astype(int) - f1[..., 0] > 30) & (f1.mean(2) < 120)).sum()
print("밝기: 처음", round(f0.mean(), 1), "시작 화면", round(f1.mean(), 1), "남색 픽셀", int(navy), "흰색", round(fw.mean(), 1), "끝", round(fz.mean(), 1))
assert f0.mean() > 140 and f1.mean() > 140 and navy > 500 and fw.mean() > 235 and fz.mean() > 140     # 처음 = 바로 · 끝 = 흰색 → 화면, 페이드 없음
for x, nm in ((f1, "r_start"), (f2, "r_start2")):
    from PySide6.QtGui import QImage  # noqa: E402
    QImage(x.data, 1920, 1080, 1920 * 3, QImage.Format_RGB888).save(os.path.join(W, nm + ".png"))
print("OK test_ui_v1691", flush=True); os._exit(0)
