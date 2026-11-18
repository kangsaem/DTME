"""v0.17.0 자동 창(ui_autowin): 빈 창 · 여행 묶음 머리줄 · '세로' 표시 · 섞임 알림 · 단계 4줄(체크·펼침 한 번에 하나·기억) ·
AUTO 전 = 파일 정보만(분석·프록시 없음) · 전부 자동(렌더 켬) = 편집 창 안 뜸·프록시 없음 → 영상 1편 + 프로젝트 ·
렌더 끔 = 편집 준비(프록시·전환 파일) 뒤 편집 화면 · 시작 창 [AUTO] 하나 · 편집 창 버튼 정리.
사용: python tests/test_ui_v1700.py <작업폴더>"""
import glob, os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
import main as M  # noqa: E402
from dtme import paths, ui_style  # noqa: E402
from dtme.project import Project, get_setting  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "v1700_test"); os.makedirs(WORK, exist_ok=True)
OUT = os.path.join(WORK, "out"); os.makedirs(OUT, exist_ok=True)
for f in glob.glob(os.path.join(OUT, "*")):
    os.remove(f)
vids = []
for n, sz in (("DJI_20251020094016_0010_D.MP4", "640x360"), ("DJI_20251021101500_0011_D.MP4", "640x360"),
              ("DJI_20260320141000_0020_D.MP4", "360x640"), ("DJI_20260321101000_0021_D.MP4", "640x360")):
    v = os.path.join(WORK, n)
    if not os.path.exists(v):
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={sz}:r=30:d=8", "-f", "lavfi", "-i",
                        "sine=d=8", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v], check=True)
    vids.append(v)
song = os.path.join(WORK, "calm instrumental.wav")
if not os.path.exists(song):
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=40", song], check=True)
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

# ---------------------------------------------------------------- 0) 시작 창 = [AUTO] 하나 · 편집 창 버튼 정리
from dtme.ui_launch import Launcher  # noqa: E402
L = Launcher(w)
btns = [b.text() for b in L.findChildren(QPushButton)]
assert "AUTO" in btns and "편집" not in btns and L.b_auto.size().width() == 160 and L.b_auto.size().height() == 48, btns
eb = [b.text() for b in e.findChildren(QPushButton)]
assert "음악 자동" not in eb and "자동 편집" not in eb and eb.count("AUTO") == 1, [x for x in eb if "자동" in x or x == "AUTO"]
assert eb.index("샘플") + 1 == eb.index("스틸"), "샘플 = 스틸 바로 왼쪽"
print("시작 창 [AUTO] 하나 · 편집 창 [음악 자동]·[자동 편집] 없음 · [샘플][스틸]")

# ---------------------------------------------------------------- 1) 빈 자동 창
st.set_project(Project()); st.defer_proxy = True
from dtme.project import set_setting as _ss; _ss("autowin", {})      # 자동 창 기억한 선택 지움(시험끼리 영향 없게)
d = e.make_auto_window(from_edit=False); d.show(); wait(0.3)
assert d.list.count() == 0 and not d.b_start.isEnabled() and d.sum.text() == ""
assert all(d.stages[k].isVisible() for k in ("grade", "edit", "music", "render"))
assert not d.music_box.isVisible() and not d.photo_box.isVisible() and not d.note.isVisible()
assert all(d.stages[k].body.isVisible() for k in d.stages), "v0.17.2 늘 다 펼침(B안)"
print("빈 창: 단계 4줄 다 펼침 · [AUTO] 흐림")

# ---------------------------------------------------------------- 2) 넣기 = 파일 정보만
d.add_paths(vids + [song])
assert wait(60, lambda: len(st.project.sources) == 4 and all(s.frames for s in st.project.sources))
wait(1.0)
heads = [d.list.item(i).text() for i in range(d.list.count()) if d.list.item(i).data(0x0100) is None]
assert heads == ["2025.10.20 ~ 10.21", "2026.03.20 ~ 03.21"], heads
assert d.list.count() == 6 and len(d.rows) == 4
tags = [d.odd_tag(s) for s in (st.project.source(r.sid) for r in d.rows)]
assert tags == ["", "", "세로", ""], tags
assert [r.out for r in d.rows] == ["horizontal", "horizontal", "vertical", "horizontal"], [r.out for r in d.rows]   # 세로 촬영 = 돌린 크기(정보가 읽힌 뒤)
assert d.note.isVisible() and d.note.text().startswith("가로 3 · 세로 1"), d.note.text()
assert d.music_box.isVisible() and "calm instrumental" in d.music_box.text()
assert d.sum.text().startswith("영상 4개 0:32"), d.sum.text()
assert d.b_start.isEnabled()
wait(1.5)
assert not st._proxy_jobs, "AUTO 전 프록시 없음"
assert not d.jobs and all(r.result is None and r.prog == 0 for r in d.rows), "AUTO 전 분석 없음"
assert st.project.tl_source([__import__("dtme.project", fromlist=["Segment"]).Segment(s.id, 0, 10) for s in st.project.sources]).width == 640
print("넣기: 머리줄", heads, "· 표시", tags, "·", d.note.text(), "· 프록시·분석 없음")
# 체크 끔 = 이번 편집에서 뺌 / Del = 목록에서 제거
d.rows[2].checked = False; d._row_changed()
assert not d.note.isVisible() and d.sum.text().startswith("영상 3개")
d.rows[2].checked = True; d._row_changed()

# ---------------------------------------------------------------- 3) 전부 자동(렌더 켬): 편집 창 안 뜸 · 프록시 없음
for k in ("grade", "edit", "music", "render"):
    d.stages[k].set_on(True)
d.length.setValue(1); d.folder.setText(OUT); d.save_on.setChecked(True); d.quality.set_value("normal"); d._sync()
assert d.stages["render"].summary.startswith("타임라인 1편 · 1:00 · 1080 · 보통"), d.stages["render"].summary   # v0.17.1 무엇을 렌더하나 표시
seen = {"mw": False, "steps": [], "rw": False}
_show = d._show
d._show = lambda key, v, text="": (seen["steps"].append(key) if not seen["steps"] or seen["steps"][-1] != key else None,
                                   seen.__setitem__("mw", seen["mw"] or w.isVisible()), _show(key, v, text))[-1]
os.environ["DTME_DONE_CHOICE"] = "close"
d.b_start.click()
assert d.running and d.run_w.isVisible() and not d.rw.isVisible() and not d.b_start.isVisible() and d.b_min.isVisible()
assert not d.lw.isVisible() and d.width() == d.SMALL_W and d.height() < 260, (d.width(), d.height())     # v0.17.1 작업 중 = 작은 팝업
assert d.step_bar.steps == ["grade", "edit", "music", "render"], d.step_bar.steps
ok = wait(600, lambda: d.outcome == "close")
files = sorted(os.listdir(OUT))
p = st.project
print("전부 자동:", files, "· 단계", seen["steps"], "· 컷", len(p.segments), "· 음악", len(p.music))
assert ok, (d._step, d.state_lab.text(), files)
assert seen["steps"] == ["grade", "edit", "music", "render"], seen["steps"]
assert not seen["mw"] and not w.isVisible(), "편집 창이 안 떠야 함"
assert not st._proxy_jobs, "렌더 켬 = 프록시 안 만듦"
assert len([f for f in files if f.endswith(".mp4")]) == 1 and len([f for f in files if f.endswith(".dtme.json")]) == 1, files
assert len(p.segments) >= 3 and p.music and all((s.auto or {}).get("preset") for s in p.sources)
assert not getattr(w, "_rwin", None), "렌더 작업 창은 안 뜸(자동 창 안에서 진행)"
it = p.render_items[-1]
assert it.orientation == "horizontal", it.orientation        # 가로 3 · 세로 1 → 많은 쪽 = 가로
cfg = get_setting("autowin", {})
assert cfg["on"] == {"grade": True, "edit": True, "music": True, "render": True} and cfg["len_sec"] == 60 and "len_mode" not in cfg, cfg
import json  # noqa: E402
mp4 = os.path.join(OUT, [f for f in files if f.endswith(".mp4")][0])
info = json.loads(subprocess.run([paths.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                                  "-of", "json", mp4], capture_output=True, text=True).stdout)
vs = next(x for x in info["streams"] if x["codec_type"] == "video")
assert (vs["width"], vs["height"]) == (1920, 1080) and 20 < float(info["format"]["duration"]) <= 60.6, info   # v0.17.1 직접 지정 1:00 = 파일 길이 상한(영상 32초뿐 = 영상 길이에서 끝)
print("결과 영상:", vs["width"], "x", vs["height"], round(float(info["format"]["duration"]), 1), "초")

# ---------------------------------------------------------------- 4) 렌더 끔 = 편집 준비 → 편집 화면(편집 창에서 다시 열기 = 설정 기억)
st.resume_proxies()
w.show(); wait(0.5)
d2 = e.make_auto_window(from_edit=True); d2.show(); wait(0.3)
assert d2.stages["render"].on and d2.length.value() == 1, "마지막 선택 기억"
assert len(d2.rows) == 4 and d2.has_timeline()
d2.stages["render"].set_on(False); d2.stages["grade"].set_on(False); d2._sync()
steps2 = []
_show2 = d2._show
d2._show = lambda key, v, text="": (steps2.append(key) if not steps2 or steps2[-1] != key else None, _show2(key, v, text))[-1]
d2.b_start.click()
assert d2.step_bar.steps == ["edit", "music", "prep"], d2.step_bar.steps
assert not w.isVisible(), "작업 중 = 편집 창 숨김(자동 창만)"
ok = wait(600, lambda: d2.outcome == "edit")
assert ok, (d2._step, d2.state_lab.text())
e.after_auto(); wait(1.0)
assert w.isVisible() and e.mode == "timeline" and st.project.segments
used = {g.src for g in st.project.segments}
assert all(st.proxy_ready(st.project.source(i)) for i in used), "편집 준비 = 쓰는 클립 프록시"
tr = glob.glob(str(paths.cache_dir() / "preview" / "trans_*.mp4"))
ncut = sum(1 for g in st.project.segments if e._trans_spec(g.id) is not None)
have = sum(1 for g in st.project.segments if (sp := e._trans_spec(g.id)) is not None and sp["out"].exists())
print("편집 준비: 단계", steps2, "· 전환 파일", have, "/", ncut, "(폴더", len(tr), ")")
assert steps2 == ["edit", "music", "prep"] and ncut >= 2 and have == ncut
cfg = get_setting("autowin", {})
assert cfg["on"]["render"] is False and cfg["on"]["grade"] is False

# ---------------------------------------------------------------- 5) v0.17.1 편집 끔 = 음악 단계 못 켬(타임라인이 있어도) · 아무 단계도 안 켬 = 그냥 편집 화면
d3 = e.make_auto_window(from_edit=True); d3.show(); wait(0.2)
assert d3.width() == d3.BIG[0], "다시 열면 설정 화면 크기"
for k in ("grade", "edit", "render"):
    d3.stages[k].set_on(False)
d3.stages["music"].set_on(True); d3._sync()
assert d3.has_timeline() and not d3.stages["music"].can and not d3.stages["music"].active()
assert d3.stages["music"].summary == "편집을 켜야 함"
d3.stages["render"].set_on(True); d3._sync()
assert d3.stages["render"].summary.startswith("클립마다 4개 · 0:32"), d3.stages["render"].summary      # 편집 끔 + 렌더 = 소스마다
d3.reject()
d4 = e.make_auto_window(from_edit=True); d4.show(); wait(0.2)
for k in ("grade", "edit", "music", "render"):
    d4.stages[k].set_on(False)
d4._sync(); d4.b_start.click(); wait(0.2)
assert d4.outcome == "edit" and not d4.running
# 편집 끔이면 음악 = '편집을 켜야 함'(타임라인 없을 때)
st.set_project(Project()); wait(0.2)
d5 = e.make_auto_window(from_edit=True); d5.show(); wait(0.2)
d5.stages["edit"].set_on(False); d5._sync()
assert d5.stages["music"].summary == "편집을 켜야 함" and not d5.stages["music"].active()
d5.reject()
print("편집 끔 = 음악 못 켬 · 단계 없음 = 편집 화면 · '편집을 켜야 함'")

# ---------------------------------------------------------------- 6) 편집 끔 + 보정 + 렌더 = 클립마다 따로(예전 [보정+렌더])
for f in glob.glob(os.path.join(OUT, "*")):
    os.remove(f)
st.defer_proxy = True
d6 = e.make_auto_window(from_edit=False); d6.show(); wait(0.2)
d6.add_paths(vids[:2])
assert wait(60, lambda: len(st.project.sources) == 2 and all(s.frames for s in st.project.sources))
for k, on in (("grade", True), ("edit", False), ("music", False), ("render", True)):
    d6.stages[k].set_on(on)
d6.folder.setText(OUT); d6._sync()
assert not d6.stages["music"].active() and d6.stages["render"].summary.startswith("클립마다 2개"), d6.stages["render"].summary
d6.b_start.click()
assert d6.step_bar.steps == ["grade", "render"] and d6._plan["per_clip"], (d6.step_bar.steps, d6._plan)
assert wait(300, lambda: d6.outcome == "close"), (d6._step, d6.state_lab.text())
mp4 = sorted(f for f in os.listdir(OUT) if f.endswith(".mp4"))
print("클립마다 렌더:", mp4)
assert len(mp4) == 2 and not st.project.segments and not st._proxy_jobs

# ---------------------------------------------------------------- 7) 시작 창: [AUTO] → 자동 창 → 단계 없이 AUTO = 편집 화면 / [취소] = 시작 창
from PySide6.QtCore import QTimer  # noqa: E402
w.hide()
L2 = Launcher(w); L2.show(); wait(0.2)
quits = []
L2._quit = lambda: quits.append(1)


def poke(what):
    dd = getattr(e, "_auto_dlg", None)
    if dd is None or not dd.isVisible() or dd is poke.last:
        QTimer.singleShot(100, lambda: poke(what)); return
    poke.last = dd
    wait(0.3)
    poke.seen = (len(dd.rows), dd.from_edit, not L2.isVisible())
    if what == "cancel":
        dd.cancel(); return
    for k in ("grade", "edit", "music", "render"):
        dd.stages[k].set_on(False)
    dd._sync(); dd.b_start.click()


poke.last = d6
QTimer.singleShot(100, lambda: poke("cancel"))
L2.b_auto.click()                                   # 빈 자동 창
assert poke.seen == (0, False, True), poke.seen
assert L2.isVisible() and not w.isVisible() and not quits, "[취소] = 시작 창으로"
QTimer.singleShot(100, lambda: poke("edit"))
L2.run_auto(vids[:2])                               # 끌어다 놓기 = 그 파일이 들어간 자동 창
assert poke.seen == (2, False, True), poke.seen
assert w.isVisible() and not L2.isVisible() and len(st.project.sources) == 2 and not st.defer_proxy, "편집 화면으로"
print("시작 창: [AUTO] = 빈 자동 창 · [취소] = 시작 창 · 단계 없이 AUTO = 편집 화면")
w.close()
print("OK test_ui_v1700")
os._exit(0)
