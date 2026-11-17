"""v0.16.97: 긴 지명 줄바꿈(3줄까지) · 기간 = 지명의 절반 · 끝 문구 84/88% · 세로 끝 화면 줄 간격 ·
LOG 시각 맞춤 클립마다(Project.off_of · 저장/불러오기 · 렌더 값 · 편집 창 칸: 고른 컷의 클립 / 전부 고름 / 기본값 / '—') ·
수심 색 띠 폭(bw) · 렌더 창 작업 표시줄 진행 · 안 쓰는 함수 뺌 · 창 0개 안전장치.
사용: python tests/test_v1697.py"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication(sys.argv)
import main as M  # noqa: E402
from dtme import autoedit as A, dive_draw as D, ff, music  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402

# ---------------------------------------------------------------- 1) 지명 줄바꿈 · 기간 = 지명의 절반
LONG = "미야코지마시 · 다케토미초, 오키나와현, 일본"
rows_v, sz_v = A.wrap_place(LONG, (1080, 1920))
rows_h, sz_h = A.wrap_place(LONG, (1920, 1080))
print("세로:", rows_v, sz_v, "· 가로:", rows_h, sz_h)
assert rows_v == ["미야코지마시", "다케토미초", "오키나와현, 일본"] and sz_v >= A.PLACE_MIN       # 세로 = 3줄, 100 이상
assert rows_h == ["미야코지마시 · 다케토미초", "오키나와현, 일본"] and sz_h >= A.PLACE_MIN      # 가로 = 2줄
assert A.wrap_place("보홀주, 필리핀", (1920, 1080)) == (["보홀주, 필리핀"], 160)                  # 짧으면 그대로 한 줄
assert A.wrap_place("보홀주, 필리핀", (1080, 1920)) == (["보홀주, 필리핀"], 160)
for wh in ((1080, 1920), (1920, 1080)):
    sc = [x for x in A.start_card(LONG, "2025.10.20 ~ 2026.03.21", 5.0, wh) if x["kind"] == "text"]
    pl, pe = sc[:-1], sc[-1]
    assert len({x["size"] for x in pl}) == 1 and pe["size"] == pl[0]["size"] // 2 and pe["cy"] == 0.8, (pl[0]["size"], pe["size"])
    assert abs(sum(x["cy"] for x in pl) / len(pl) - 0.5) < 1e-3                                  # 지명 묶음 = 가운데
    k = min(wh) / 1080
    bottom = max(x["cy"] for x in pl) + pl[0]["size"] * 0.7 * k / wh[1]
    assert bottom < pe["cy"] - pe["size"] * 0.7 * k / wh[1], "지명과 기간이 겹치지 않음"
    for x in sc:
        assert A._metrics(x)[0] * k <= 0.85 * wh[0] + 2, x["text"]
one = [x for x in A.start_card("보홀주, 필리핀", "2026.10.25 ~ 10.27") if x["kind"] == "text"]
assert [(x["size"], x["cy"]) for x in one] == [(160, 0.5), (80, 0.8)]

# ---------------------------------------------------------------- 2) 끝 문구 3배 · 세로 줄 간격
assert (A.END_TAG_SIZE, A.END_TAG_CY) == (84, 0.88)
ls = [("14 DIVES · MAX 35.7m · 9h 20m", 52, True), (LONG, 36, True), ("2025.10.20 ~ 2026.03.21", 36, True)]
eh = [x for x in A.end_card(100.0, ls, (1920, 1080), tag=True) if x["kind"] == "text"]
ev = [x for x in A.end_card(100.0, ls, (1080, 1920), tag=True) if x["kind"] == "text"]
assert eh[-1]["size"] == 84 and ev[-1]["size"] <= 84 and eh[-1]["cy"] == ev[-1]["cy"] == 0.88
gap_h, gap_v = eh[1]["cy"] - eh[0]["cy"], ev[1]["cy"] - ev[0]["cy"]
assert gap_v < gap_h, (gap_h, gap_v)                       # 세로 = 화면이 길어 비율로는 줄 간격이 더 좁음(예전 = 가로와 같은 비율 → 벌어짐)
assert max(x["cy"] for x in eh[:-1]) + 0.05 < 0.88 - 84 * 0.7 / 1080, "가운데 줄과 아래 줄이 겹치지 않음"
assert not hasattr(A, "TYPE_DELAY") and "typing" not in A.card_texts.__code__.co_varnames

# ---------------------------------------------------------------- 3) LOG 시각 맞춤 = 클립마다
p = Project()
s1 = Source("/v/DJI_20251020094016_0010_D.MP4", 30, 1, 30 * 600)
s2 = Source("/v/DJI_20260320141000_0003_D.MP4", 30, 1, 30 * 600)
p.sources += [s1, s2]
p.dive_off = 3600.0
assert p.off_of(s1) == 3600.0 and p.off_of(None) == 3600.0
s2.dive_off = -265.0
assert p.off_of(s2) == -265.0 and p.off_of(s1) == 3600.0
s1.dive_off = 0.0
assert p.off_of(s1) == 0.0                                 # 0 도 '따로 정한 값'(None 만 기본값)
s1.dive_off = None
q = Project.from_dict(p.to_dict())
assert q.sources[1].dive_off == -265.0 and q.sources[0].dive_off is None and q.dive_off == 3600.0
old = p.to_dict()
for sd in old["sources"]:
    sd.pop("dive_off")
assert all(s.dive_off is None for s in Project.from_dict(old).sources)       # 예전 프로젝트 = 전체 값 그대로
assert D._off_for(5.0, s1) == 5.0 and D._off_for({"off": 5.0, "offs": {s2.id: -265.0}}, s2) == -265.0
assert D._off_for({"off": 5.0, "offs": {s2.id: -265.0}}, s1) == 5.0 and D._off_for({"off": 5.0}, s1) == 5.0
# 다이빙 찾기: 클립 값에 따라 같은 클립이 다이빙 안/밖
from dtme import divelog as DL  # noqa: E402
t_clip = DL.name_time(Path(s2.path).name)
dv = [{"id": "d", "src": "fit", "start": t_clip + 300.0, "pts": [[0, 0], [600, 20.0], [1500, 0]], "max": 20.0}]
p.dives = dv
p.dive_off = 0.0
s2.dive_off = None
g = Segment(s2.id, 0, 300)                                 # 클립 처음 10초 = 입수 5분 전 → 다이빙 아님
assert D.cut_dive(dv, s2, g, p.off_of(s2)) is None
s2.dive_off = 400.0                                        # 카메라 시계가 400초 늦었다고 맞춤 → 입수 뒤 100초
assert D.cut_dive(dv, s2, g, p.off_of(s2)) is not None
print("클립마다 LOG 시각: OK")

# ---------------------------------------------------------------- 4) 편집 창 칸: 고른 컷의 클립 / 전부 / 기본값 / '—'
from dtme.ui_main import MainWindow  # noqa: E402
M.dark(app)
w = MainWindow()
w.resize(1600, 900)
w.show()
e, st = w.edit, w.state
pp = st.project
a_ = Source("/v/DJI_20251020094016_0010_D.MP4", 30, 1, 3000, width=1920, height=1080)
b_ = Source("/v/DJI_20260320141000_0003_D.MP4", 30, 1, 3000, width=1920, height=1080)
pp.sources += [a_, b_]
pp.dives = dv
pp.segments = [Segment(a_.id, 0, 300), Segment(b_.id, 0, 300), Segment(b_.id, 600, 900)]
st.touch("sources"); st.touch("segments"); st.touch("dives")
e.set_mode("timeline")
app.processEvents()
sp = e.dive_off
assert sp.minimum() == -7201 and sp.specialValueText() == "LOG 시각 —"
e.sel_cut = ""; e.timeline.all_cuts = False; e._sync_dive_off()
assert sp.value() == 0 and e._dive_targets() is None
sp.setValue(30)                                            # 고른 컷 없음 = 기본값
pp = st.project
assert pp.dive_off == 30.0 and all(s.dive_off is None for s in pp.sources)
e._on_cut_selected(pp.segments[1].id)                      # 둘째 컷(클립 b)
assert sp.value() == 30 and [s.path for s in e._dive_targets()] == [b_.path]
sp.setValue(-265)
pp = st.project
sa, sb = pp.sources
assert sb.dive_off == -265.0 and sa.dive_off is None and pp.dive_off == 30.0      # 그 클립만
assert pp.off_of(sb) == -265.0 and pp.off_of(sa) == 30.0
e._on_cut_selected(pp.segments[2].id)                      # 같은 클립의 다른 컷 = 같은 값
assert sp.value() == -265
e._on_cut_selected(pp.segments[0].id)
assert sp.value() == 30
e.timeline.all_cuts = True; e._sync_dive_off()             # 전부 고름 = 값이 서로 다름 → '—'
assert sp.value() == sp.minimum() and sp.text() == "LOG 시각 —"
sp.stepBy(1)                                               # '—' 에서 한 칸 = 0 에서 시작 → 1, 모든 클립에
pp = st.project
assert sp.value() == 1 and [s.dive_off for s in pp.sources] == [1.0, 1.0]
e.timeline.all_cuts = False
e._on_cut_selected(pp.segments[1].id)
sp.setFocus()
QTest.keyClick(sp, Qt.Key_Up)                              # 방향키 = 1초
assert sp.value() == 2 and st.project.sources[1].dive_off == 2.0 and st.project.sources[0].dive_off == 1.0
QTest.keyClick(sp, Qt.Key_Up, Qt.ShiftModifier)            # Shift+방향키 = 10초
assert sp.value() == 12, sp.value()
# 렌더리스트로 = 클립 값이 같이 감
e.set_mode("timeline")
n0 = len(st.project.render_items)
e.timeline_to_render()
its = st.project.render_items
assert len(its) == n0 + 1
if True:
    assert its[-1].dive["offs"] == {s.id: s.dive_off for s in st.project.sources if s.dive_off is not None}, its[-1].dive
print("편집 창 LOG 시각 칸: OK")

# ---------------------------------------------------------------- 5) 렌더 창 = 작업 표시줄 진행(창 제목 · 아이콘)
from dtme import taskbar  # noqa: E402
calls = []
_sp, _cl = taskbar.set_progress, taskbar.clear
taskbar.set_progress = lambda win, frac, bad=False: calls.append((win, round(frac, 2), bad))
taskbar.clear = lambda win: calls.append((win, None, None))
from PySide6.QtWidgets import QWidget  # noqa: E402
rw = QWidget()
rw.finish = lambda: None
w._rwin = rw
w._render_progress(0.45, "45%", False)
assert (rw, 0.45, False) in calls and rw.windowTitle() == "DTME — 렌더 45%", (calls, rw.windowTitle())
taskbar.set_progress, taskbar.clear = _sp, _cl
w._rwin = None

# ---------------------------------------------------------------- 6) 수심 색 띠 폭 · 안 쓰는 함수 · 안전장치
import inspect  # noqa: E402
src_rl = inspect.getsource(D.render_layers)
assert 'out["bw"]' in src_rl.replace("'", '"') or "out[\"bw\"]" in src_rl
assert "crop={bw}:{bh}:0:{y0}" in inspect.getsource(ff.post_graph)
for name in ("plan_runs", "plan", "hl_start", "first_bar", "SONG_MAX", "GRAND_BOOST", "is_vocal"):
    assert not hasattr(music, name), name
assert not hasattr(A, "place_of")
assert M.WATCH_STEP_MS * M.WATCH_MISS == 6000 and M.is_test_run()
hit = []
tm = M.watch_windows(type("X", (), {"quit": lambda self: hit.append(1)})() if False else app)
tm.stop()                                                  # (실제 종료는 test 에서 돌리지 않음 — 타이머가 만들어지는 것만)
from dtme import single  # noqa: E402
assert single.name("DTME").startswith("DTME-single-") and single.lock_path("DTME").endswith(".lock")
print("OK test_v1697")
sys.stdout.flush()
os._exit(0)
