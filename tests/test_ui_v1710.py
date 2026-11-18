"""v0.17.1 화면: 자동 창 전체 길이 [곡에 맞춤 | 직접 지정] · LOG 칸(기록 없음 = 체크 없이 흐림) · 지명 안내 글 DTME ·
편집 끔 = 음악 못 켬 · 작업 팝업(작은 창 · 막대 그림자 · 파일 줄 = 글자 + 가는 선) · 곡에 맞춤으로 돌리기(영상 끝 = 곡 끝) ·
타임라인: 휠 이동 · Ctrl+휠·슬라이드바 확대 = 재생 위치 중심 · 가운데 버튼/Space 끌기 = 화면 이동 · 끌다 끝에 닿으면 넘어감 ·
컷 아웃 마디 자석 · 마디에 맞은 경계 표시.
사용: python tests/test_ui_v1710.py <작업폴더>"""
import glob, os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import autoedit, music, paths, ui_style  # noqa: E402
from dtme.project import Project, cut_spans, get_setting, set_setting  # noqa: E402
from dtme.ui_autowin import LengthBox, parse_mmss  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
from dtme.ui_renderwin import ItemRow  # noqa: E402
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "v1710_test"); os.makedirs(WORK, exist_ok=True)
vids = []
for i, n in enumerate(("DJI_20251020094016_0010_D.MP4", "DJI_20251020101500_0011_D.MP4", "DJI_20251020111000_0012_D.MP4",
                       "DJI_20251020121000_0013_D.MP4")):
    v = os.path.join(WORK, n)
    if not os.path.exists(v):
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=20", "-f", "lavfi", "-i",
                        "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v], check=True)
    vids.append(v)
song = os.path.join(WORK, "calm instrumental.wav")
if not os.path.exists(song):                       # 120 BPM 딸깍 + 낮은 소리 34초(박자가 잡히게)
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.4*sin(2*PI*110*t)*lt(mod(t,0.5),0.08)+0.1*sin(2*PI*330*t)':d=34:s=22050", song], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850)


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
ui_style.confirm = lambda *a, **k: "ok"

# ---------------------------------------------------------------- 1) 전체 길이 칸
assert parse_mmss("1:30") == 90 and parse_mmss("90") == 90 and parse_mmss("1.5") == 90 and parse_mmss("x") is None
lb = LengthBox("", 180)                                                 # v0.17.2 = 직접 지정 + '곡 길이에 맞춤' 체크
assert lb.mode() == "manual" and lb.seconds() == 180 and not lb.song.isEnabled() and lb.edit.text() == "3:00"
lb.set_song_ok(True, song_sec=340.0)
assert lb.mode() == "manual" and lb.song.isEnabled() and lb.edit.text() == "3:00"   # 올린 곡이 있어도 저절로 안 켜짐
lb.song.setChecked(True)
assert lb.mode() == "song" and not lb.edit.isEnabled() and lb.edit.text() == "5:40"  # 켜면 칸 숫자 = 곡 길이
lb.set_song_ok(False)
assert lb.mode() == "manual" and lb.edit.text() == "3:00" and lb.edit.isEnabled()   # 못 쓰면 직접 지정 숫자로
lb.set_song_ok(True); lb.song.setChecked(False)
lb.edit.setText("1:30"); lb._typed()
assert lb.seconds() == 90
lb.setValue(2); assert lb.mode() == "manual" and lb.value() == 2

# ---------------------------------------------------------------- 2) 자동 창: LOG 칸 · 지명 안내 글 · 음악·렌더 규칙
st.set_project(Project()); st.defer_proxy = True
set_setting("autowin", {})
d = e.make_auto_window(from_edit=False); d.show(); wait(0.3)
assert not d.dive_on.isChecked() and not d.dive_on.isEnabled(), "기록 없음 = 체크 없이 흐림"
assert d.place.placeholderText() == "DTME" and d.place.text() == ""
d.add_paths(vids)
assert wait(60, lambda: len(st.project.sources) == 4 and all(s.frames for s in st.project.sources))
wait(0.6)
assert d.length.mode() == "manual" and d.sum.text().endswith("→ 3:00"), d.sum.text()        # 기본 음악만 = 직접 지정 3:00
assert "DTME" in d.end_text.text(), d.end_text.text()
assert d.stages["edit"].summary.startswith("3:00") and "LOG" not in d.stages["edit"].summary
st.project.dives = [{"id": "x", "start": 0.0, "pts": [[0, 0], [600, 10.0], [1200, 0]], "max": 10.0}]
d._sync()
assert d.dive_on.isEnabled() and d.dive_on.isChecked(), "기록이 들어오면 기억한 선택(기본 켬)대로"
d.dive_on.setChecked(False); assert d.config()["dive"] is False
st.project.dives = []; d._sync()
assert not d.dive_on.isChecked() and not d.dive_on.isEnabled() and d.config()["dive"] is False
d._dive_want = True
d.add_paths([song])
assert wait(30, lambda: any(float(a.get("dur") or 0) not in (0.0, 600.0) for a in st.project.audios if not a.get("builtin")))
wait(0.6); d._sync()
assert d.length.mode() == "manual" and d.length.song.isEnabled() and d.sum.text().endswith("→ 3:00"), d.sum.text()   # v0.17.2 저절로 안 켜짐
d.length.song.setChecked(True); d._sync()
assert d.length.mode() == "song" and "(곡)" in d.sum.text() and d.length.edit.text() == d.sum.text().split("→ ")[1][:-3], d.sum.text()
d.stages["music"].set_on(False); d._sync()
assert d.length.mode() == "manual" and not d.length.song.isEnabled()                      # 음악 끔 = 곡에 맞춤 흐림
d.stages["music"].set_on(True); d.stages["edit"].set_on(False); d._sync()
assert not d.stages["music"].active() and d.stages["music"].summary == "편집을 켜야 함"
d.stages["render"].set_on(True); d._sync()
assert d.stages["render"].summary.startswith("클립마다 4개 · 1:20"), d.stages["render"].summary
d.stages["edit"].set_on(True); d._sync()
assert d.stages["render"].summary.startswith("타임라인 1편 · "), d.stages["render"].summary
d.grab().save(os.path.join(WORK, "autowin_settings.png"))
print("자동 창:", d.sum.text(), "|", d.stages["edit"].summary, "|", d.stages["render"].summary)

# ---------------------------------------------------------------- 3) 곡에 맞춤으로 돌리기(보정·편집·음악, 렌더 끔) + 작업 팝업
for k, on in (("grade", True), ("edit", True), ("music", True), ("render", False)):
    d.stages[k].set_on(on)
d._sync()
assert d.length.mode() == "song"
big = d.size()
assert big.width() == d.BIG[0] and all(d.stages[k].body.isVisible() for k in d.stages)
d.b_start.click()
assert d.running and d.width() == d.SMALL_W and d.height() < 200 and not d.lw.isVisible() and not d.rw.isVisible() and not d.ver_lab.isVisible()
said = []
_say = d._say
d._say = lambda text, key="": (said.append(text), _say(text, key))[-1]
wait(1.0)
d.step_bar.set("edit", 0.4, "하이라이트 2/4"); app.processEvents()
d.grab().save(os.path.join(WORK, "autowin_popup.png"))
ok = wait(600, lambda: d.outcome == "edit")
assert ok, (d._step, d.state_lab.text())
assert any("2025 1020" in x for x in said), said                       # 왼쪽 아래 = 방금 판정한 클립
p = st.project
inf = music.get(song)
vend = max(t + ln for _c, t, ln in cut_spans(p))
mend = music.music_end(p.music)
print("곡에 맞춤: 영상 끝", round(vend, 2), "· 음악 끝", round(mend, 2), "· 곡", inf["dur"], "· 컷", len(p.segments), "· 박자 확신", inf["conf"])
assert len(p.music) == 1 and abs(vend - mend) < 0.2 and abs(vend - (inf["dur"] - p.music[0]["off"])) < 0.2, (vend, mend)
tend = max(float(x["t1"]) for x in p.titles if x.get("card") == "end")
print("끝:", p.out_seconds(), tend)
assert abs(tend - (vend + autoedit.END_SEC)) < 0.1
texts = [x.get("text") for x in p.titles if x.get("card")]
assert texts.count("DTME") == 2, texts                                  # 지명 없음 = 시작·끝 화면에 DTME
assert not any(x.get("text") == "See You Underwater" for x in p.titles)
cfg = get_setting("autowin", {})
assert "len_mode" not in cfg and cfg["len_sec"] == 180                 # v0.17.2 '곡 길이에 맞춤'은 기억 안 함
# 다시 열면 큰 창 · 직접 지정 0:40 = 시작 5 + 본문 27 + 끝 8
w.show(); wait(0.3); e.after_auto(); wait(0.5)
d2 = e.make_auto_window(from_edit=True); d2.show(); wait(0.3)
assert d2.size() == big
assert d2.length.mode() == "manual" and not d2.length.song.isChecked()
d2.length.edit.setText("0:40"); d2.length._typed()
for k, on in (("grade", False), ("edit", True), ("music", True), ("render", False)):
    d2.stages[k].set_on(on)
d2._sync()
assert d2.sum.text().endswith("→ 0:40") and d2.edit_settings([])["seconds"] == 40 and d2.edit_settings([])["len_mode"] == "manual"
d2.b_start.click()
assert wait(600, lambda: d2.outcome == "edit"), (d2._step, d2.state_lab.text())
e.after_auto(); wait(0.5)
p = st.project
tend = max(float(x["t1"]) for x in p.titles if x.get("card") == "end")
print("직접 지정 0:40: 파일", round(tend, 2), "· 본문", round(p.out_seconds(), 2), "· 음악", [(round(m["t0"], 1), round(m["len"], 1)) for m in p.music])
assert abs(tend - 40.0) < 0.05 and abs(p.out_seconds() - 27.0) < 0.05, (tend, p.out_seconds())     # 시작 5 + 본문 27 + 끝 8
assert abs(music.music_end(p.music) - (40.0 - autoedit.END_SEC)) < 0.2         # 곡이 더 김 = 영상 끝에서 자름(줄임)
assert get_setting("autowin", {})["len_sec"] == 40

# ---------------------------------------------------------------- 4) 파일 줄 = 글자 + 가는 선
r = ItemRow("DTME_2025 1020.mp4"); r.resize(600, 26); r.set(0.5, "인코딩 50%")
im = r.grab().toImage()
line = [im.pixelColor(x, 24) for x in (10, 500)]
assert line[0].lightness() > line[1].lightness() + 30 and line[1].name() == "#333333", [c.name() for c in line]     # 왼쪽 절반만 채운 2px 선
assert im.pixelColor(300, 2).red() < 60                                         # 두꺼운 줄 없음(위는 바탕)

# ---------------------------------------------------------------- 5) 타임라인
tl, sb = e.timeline, e.tl_scroll.horizontalScrollBar()
assert e.mode == "timeline" and len(p.segments) >= 2
e.zoom.setValue(60); wait(0.3)
assert tl.width() > e.tl_scroll.viewport().width() and sb.maximum() > 200
bars = [t for t, _b in tl._bars_all()]
bnds = tl._bounds()
on_bar = [b for b in bnds[1:-1] if min(abs(b - t) for t in bars) <= 0.05]
print("타임라인: 마디", len(bars), "· 경계", [round(b, 2) for b in bnds], "· 마디에 맞음", len(on_bar))
assert bars and len(on_bar) >= 1
tl.grab().save(os.path.join(WORK, "timeline_bars.png"))
# 휠 = 앞뒤 이동 · Ctrl+휠 = 확대(재생 위치가 화면 같은 자리에)


def wheel(dy, mod=Qt.NoModifier):
    QApplication.sendEvent(tl, QWheelEvent(QPointF(100, 50), QPointF(100, 50), QPoint(0, 0), QPoint(0, dy), Qt.NoButton, mod,
                                           Qt.NoScrollPhase, False))
    wait(0.15)


sb.setValue(0); wheel(-120)
assert sb.value() == 120, sb.value()
e.show_timeline(12.0); wait(0.3)
sb.setValue(int(tl._x(tl.t) - 300)); wait(0.1)
sx0, z0 = tl._x(tl.t) - sb.value(), e.zoom.value()
wheel(120, Qt.ControlModifier)
assert e.zoom.value() > z0 and abs((tl._x(tl.t) - sb.value()) - sx0) <= 2, (z0, e.zoom.value(), sx0, tl._x(tl.t) - sb.value())
e.zoom.setValue(40); wait(0.2)
assert abs((tl._x(tl.t) - sb.value()) - sx0) <= 2, "슬라이드바 = 재생 위치 중심"
assert not e._tl_fit
# 가운데 버튼 끌기 · Space 누른 채 끌기 = 화면 이동(끌었으면 재생/정지 안 함)
e.zoom.setValue(80); wait(0.2)
sb.setValue(300); v0 = sb.value()
QTest.mousePress(tl, Qt.MiddleButton, Qt.NoModifier, QPoint(500, 60)); QTest.mouseMove(tl, QPoint(420, 60)); wait(0.05)
QTest.mouseRelease(tl, Qt.MiddleButton, Qt.NoModifier, QPoint(420, 60))
assert sb.value() > v0, (v0, sb.value())
tl.space_pan, tl.space_moved = True, False
v1, t1 = sb.value(), tl.t
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(500, 60)); QTest.mouseMove(tl, QPoint(560, 60)); wait(0.05)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(560, 60))
assert sb.value() < v1 and tl.space_moved and tl.t == t1                  # 화면만 옮김(재생 위치·선택 그대로)
tl.space_pan = False
# 컷 아웃 끌기 = 뒤 경계가 마디 첫 박에 붙음
e.zoom.setValue(40); wait(0.2); sb.setValue(0); wait(0.1)
cid = p.segments[0].id
b0 = tl._bounds()[1]
far = [t for t in bars if t - b0 > 1.0][0]                                # 1초 넘게 뒤의 첫 마디
hd = next(h for h in tl._handles() if h[0] == "out" and h[1] == cid)
c = hd[2].center().toPoint()
dx = int(round((far - b0) * tl.pps)) - 5                                  # 5px 못 미친 곳까지 끎(자석 8px)
g0 = p.segments[0]; len0 = g0.fout - g0.fin
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, c); QTest.mouseMove(tl, c + QPoint(4, 0)); QTest.mouseMove(tl, c + QPoint(dx, 0)); wait(0.2)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, c + QPoint(dx, 0)); wait(0.3)
grown = (p.segments[0].fout - p.segments[0].fin - len0) / 30.0
print("컷 아웃 자석: 늘어남", round(grown, 3), "· 마디까지", round(far - b0, 3))
assert abs(grown - (far - b0)) <= 1.0 / 30 + 1e-6, (grown, far - b0)
# 음악을 끌다 오른쪽 끝(40px)에 닿음 = 자동으로 넘어감 · 놓으면 멈춤
e.zoom.setValue(80); wait(0.2); sb.setValue(0); wait(0.1)
k, m, rr = next(x for x in tl._ov_rects() if x[0] == "music")
y = int(rr.center().y()); vw = e.tl_scroll.viewport().width()
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(200, y)); QTest.mouseMove(tl, QPoint(400, y)); QTest.mouseMove(tl, QPoint(vw - 5, y))
a0 = sb.value(); wait(0.5); a1 = sb.value()
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(sb.value() + vw - 5, y)); wait(0.3)
assert a1 > a0 + 30 and sb.value() == a1 or sb.value() >= a1, (a0, a1, sb.value())
a2 = sb.value(); wait(0.3); assert sb.value() == a2
print("OK test_ui_v1710", flush=True)
os._exit(0)
