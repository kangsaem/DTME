"""v0.16.67: 글꼴 9개 · 모든 글자/사각형에 적용 · 따라감(글자·음악) · 타임라인 컷 인·아웃 끌기(나비 날개).
사용: python tests/test_ui_v1667.py [캡처폴더]"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
import main as M
from dtme import fonts, paths
from dtme.project import Segment, follow_anchors, follow_apply, new_music, new_rect, new_text
from dtme.ui_main import MainWindow

out_dir = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
os.makedirs(out_dir, exist_ok=True)
# 1) 글꼴 9개
fs = fonts.list_fonts()
for n in ("도현", "주아", "구기", "독도", "연성", "개구", "감자꽃", "하이멜로디", "기랑해랑"):
    assert n in fs and fs[n]["regular"] and os.path.exists(fs[n]["regular"]), n
    stem = os.path.basename(fs[n]["regular"]).split("-")[0]
    assert os.path.exists(os.path.join(paths.fonts_dir(), f"OFL-{stem}.txt")), stem
assert fs["개구"]["bold"]

d = tempfile.mkdtemp(); vids = []
for i in range(2):
    v = os.path.join(d, f"k{i}.mp4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=20",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", v], check=True); vids.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1700, 950); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond():
            return True


st, e, tl = w.state, w.edit, w.edit.timeline
e.import_files(vids); wait(60, lambda: len(st.project.sources) == 2 and all(st.status.get(x.id) == "준비" for x in st.project.sources))
p = st.project
a, b = p.sources
fps = float(a.fps)
p.segments = [Segment(a.id, 0, int(5 * fps)), Segment(b.id, 0, int(5 * fps)), Segment(a.id, int(10 * fps), int(15 * fps))]
p.segments[1].trans = {"type": "dissolve", "dur": 0.5}
t1 = new_text(5.0, 8.0, "따라감"); t1["follow"] = True          # 둘째 컷 안(시작 4.5)
t2 = new_text(5.0, 8.0, "제자리")
r1 = new_rect(9.6, 12.0); r1["follow"] = True                   # 셋째 컷 안(시작 9.5)
m1 = new_music(vids[0], 0.0, 20.0); m1["len"] = 14.5; m1["follow"] = True    # 끝 = 타임라인 끝(14.5)
m2 = new_music(vids[1], 9.6, 20.0); m2["len"] = 4.0; m2["follow"] = True
p.titles = [r1, t1, t2]; p.music = [m1, m2]
st.touch("segments"); st.touch("titles"); wait(0.5)
assert abs(p.out_seconds() - 14.5) < 0.01, p.out_seconds()

# 2) 엔진: 첫 컷 아웃 −1초 → 뒤 따라감 −1, 제자리 그대로, 음악 = 시작 그대로·끝 −1
anc = follow_anchors(p)
p.segments[0].fout = int(4 * fps)
follow_apply(p, anc)
assert abs(t1["t0"] - 4.0) < 1e-3 and abs(t1["t1"] - 7.0) < 1e-3, t1
assert t2["t0"] == 5.0
assert abs(r1["t0"] - 8.6) < 1e-3
assert m1["t0"] == 0.0 and abs(m1["len"] - 13.5) < 1e-3, m1
assert abs(m2["t0"] - 8.6) < 1e-3 and abs(m2["len"] - 4.0) < 1e-3, m2
st.undo() if False else None
p.segments[0].fout = int(5 * fps); t1.update(t0=5.0, t1=8.0); r1.update(t0=9.6, t1=12.0); m1["len"] = 14.5; m2["t0"] = 9.6
st.touch("segments"); wait(0.3)

# 3) 화면: 나비 손잡이 — 전환 경계 = 위(dur)·아래 왼쪽(out)·아래 오른쪽(in), 전환 없는 경계·맨 앞·맨 뒤 = 날개
hs = tl._handles()
kinds = [(k, c) for k, c, _r in hs]
s0, s1, s2 = [g.id for g in p.segments]
assert ("dur", s1) in kinds and ("out", s0) in kinds and ("in", s1) in kinds, kinds
assert ("in", s0) in kinds and ("out", s2) in kinds and ("in", s2) in kinds and ("out", s1) in kinds
tips = {tl._handle_tip(h) for h in hs}
assert {"컷아웃 수정", "컷인 수정", "디졸브 수정"} <= tips, tips


def mouse(kind, pos, mods=Qt.NoModifier, btn=Qt.LeftButton):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(tl.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))),
                     btn if kind != QMouseEvent.Type.MouseMove else Qt.NoButton,
                     btn if kind != QMouseEvent.Type.MouseButtonRelease else Qt.NoButton, mods)
    app.sendEvent(tl, ev)


def drag(pos, dx):
    mouse(QMouseEvent.Type.MouseButtonPress, pos)
    for k in range(1, 6):
        mouse(QMouseEvent.Type.MouseMove, QPointF(pos.x() + dx * k / 5, pos.y()))
    mouse(QMouseEvent.Type.MouseButtonRelease, QPointF(pos.x() + dx, pos.y()))
    wait(0.2)


# 셋째 컷 앞 날개(전환 없음, 컷인) = 오른쪽으로 1초(pps 만큼) → 셋째 컷이 1초 짧아짐(인 +1초), 따라감 사각형 = 셋째 컷 안이라 그대로
tl.set_zoom(30.0); wait(0.1)
nu = len(st._undo)
r_in = next(r for k, c, r in tl._handles() if (k, c) == ("in", s2))
drag(r_in.center(), 30)
g2 = p.segments[2]
assert g2.fin == int(11 * fps), (g2.fin,)
assert len(st._undo) == nu + 1                     # 실행취소 1번
assert abs(r1["t0"] - 9.6) < 1e-3                  # 같은 컷 안 = 제자리(인을 잘라도 컷 시작은 그대로)
assert abs(m1["len"] - 13.5) < 1e-3                # 끝 = 타임라인 끝 따라감
w.undo(); wait(0.3); p = st.project
assert p.segments[2].fin == int(10 * fps)
# 첫 컷 맨 앞 컷인 날개 = 오른쪽으로 → 뒤 따라감이 당겨짐
s0, s1, s2 = [g.id for g in p.segments]
r_in0 = next(r for k, c, r in tl._handles() if (k, c) == ("in", s0))
drag(r_in0.center(), 30)
t1n = next(x for x in p.titles if x.get("text") == "따라감")
t2n = next(x for x in p.titles if x.get("text") == "제자리")
assert p.segments[0].fin == int(fps) and abs(t1n["t0"] - 4.0) < 1e-3 and t2n["t0"] == 5.0, (p.segments[0].fin, t1n)
w.undo(); wait(0.3); p = st.project
# 전환 위 노랑 = 전환 길이 끌기
r_dur = next(r for k, c, r in tl._handles() if (k, c) == ("dur", p.segments[1].id))
drag(QPointF(r_dur.right() - 2, r_dur.center().y()), 9)
assert abs(p.segments[1].trans["dur"] - 0.8) < 0.11, p.segments[1].trans
w.undo(); wait(0.3); p = st.project

# 4) 컷 삭제 = 따라감 당김
e.sel_cut = p.segments[0].id; e.delete_cut(); wait(0.2); p = st.project
t1n = next(x for x in p.titles if x.get("text") == "따라감")
assert abs(t1n["t0"] - 0.5) < 1e-3, t1n           # 둘째 컷 시작(4.5) → 0 (전환은 첫 컷이 되며 빠짐) + 0.5
w.undo(); wait(0.3); p = st.project

# 5) Shift+클릭 = 따라감 끄고 켜기, 고리 표시
tl.set_overlays(p.titles, p.music, ("", "")); wait(0.1)
kind, dd, rr = next((k, x, r) for k, x, r in tl._ov_rects() if x.get("text") == "제자리")
mouse(QMouseEvent.Type.MouseButtonPress, rr.center() + QPointF(10, 0), Qt.ShiftModifier)
mouse(QMouseEvent.Type.MouseButtonRelease, rr.center() + QPointF(10, 0), Qt.ShiftModifier); wait(0.2)
assert next(x for x in st.project.titles if x.get("text") == "제자리").get("follow") is True
w.grab().save(os.path.join(out_dir, "v1667_timeline.png"))
tl.grab().save(os.path.join(out_dir, "v1667_tl_only.png"))

# 6) 모든 글자에 적용 / 모든 사각형에 적용
p = st.project
tx = next(x for x in p.titles if x.get("text") == "따라감")
e.edit_ov("title", tx["id"]); wait(0.2)
dlg = e._dlg
assert dlg.apply_all.isChecked() and dlg.apply_all.text() == "모든 글자에 적용"
dlg._set("ain", "left"); dlg._set("aout", "up"); dlg._set("fade", 1.2)
dlg.accept(); wait(0.2)
for x in st.project.titles:
    if x.get("kind") == "text":
        assert (x.get("ain"), x.get("aout"), x.get("fade")) == ("left", "up", 1.2), x
rx = next(x for x in st.project.titles if x.get("kind") == "rect")
assert rx.get("ain", "fade") == "fade"
# 끄면 그 글자만
tx2 = next(x for x in st.project.titles if x.get("text") == "제자리")
e.edit_ov("title", tx2["id"]); wait(0.2)
e._dlg.apply_all.setChecked(False); e._dlg._set("ain", "right"); e._dlg.accept(); wait(0.2)
assert next(x for x in st.project.titles if x.get("text") == "따라감")["ain"] == "left"
e.edit_ov("title", rx["id"]); wait(0.2)
assert e._dlg.apply_all.text() == "모든 사각형에 적용"
e._dlg.accept(); wait(0.2)
# 7) 저장·불러오기에 follow 유지
f = os.path.join(d, "p.json"); st.project.save(f)
from dtme.project import Project
q = Project.load(f)
assert any(x.get("follow") for x in q.titles) and all(m.get("follow") for m in q.music)
print("OK test_ui_v1667")
os._exit(0)
