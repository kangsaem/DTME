"""v0.16.25 점검: 렌더 칸 ▼(미리보기 렌더 자리) · 소스 우클릭 '렌더 리스트로'.
- 소스 목록에서 선택한 것만, 소스마다 항목 1개(인/아웃·배속·지금 보정값·출력 방향 = AUTO 출력 또는 렌더 설정)
- 다시 누르면: 완료 안 된 항목 = 지금 값으로 갱신(개수 그대로), 완료 = 건너뜀
- 미리보기 렌더 버튼 없음
사용: python tests/test_ui_srcrender.py <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.ui_main import MainWindow
WORK = sys.argv[1]; os.makedirs(WORK, exist_ok=True)
clips = []
for i in range(3):
    c = os.path.join(WORK, f"DJI_2026110910000{i}_000{i}_D.MP4")
    ff.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=60000/1001:d=2", c])
    clips.append(c)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


st, e, rp = w.state, w.edit, w.edit.render_panel
assert not hasattr(rp, "b_prev") and rp.b_down.text() == "▼", "미리보기 렌더 → ▼"
e.import_files(clips)
assert wait(120, lambda: len(st.project.sources) == 3 and all(s.frames for s in st.project.sources))
p = st.project
s0, s1, s2 = p.sources
s0.sel_in, s0.sel_out = 10, 90; s0.speed = 2.0
s0.grade["r_gain"] = 1.3
s1.out = "vertical"
p.output.orientation = "horizontal"


def select(*srcs):
    e.src_list.clearSelection()
    ids = {s.id for s in srcs}
    for i in range(e.src_list.count()):
        it = e.src_list.item(i)
        it.setSelected(it.data(0x0100) in ids)


select(s0, s1)
rp.b_down.click(); wait(0.3)
items = p.render_items
print("1번:", [(it.name, it.orientation, it.segs[0].fin, it.segs[0].fout, it.segs[0].speed, it.segs[0].grade.get("r_gain")) for it in items])
assert len(items) == 2 and {it.segs[0].src for it in items} == {s0.id, s1.id}, "선택한 것만"
i0 = next(it for it in items if it.segs[0].src == s0.id); i1 = next(it for it in items if it.segs[0].src == s1.id)
assert (i0.segs[0].fin, i0.segs[0].fout, i0.segs[0].speed) == (10, 90, 2.0) and i0.segs[0].grade["r_gain"] == 1.3
assert i0.orientation == "horizontal" and i1.orientation == "vertical", "출력 방향 = AUTO 출력 또는 렌더 설정"

# 갱신: 값 바꾸고 다시 → 개수 그대로, 새 값
s0.grade["r_gain"] = 1.1; s0.sel_in, s0.sel_out = 0, 60
e.sources_to_render(); wait(0.2)
assert len(p.render_items) == 2 and i0.segs[0].grade["r_gain"] == 1.1 and i0.segs[0].fout == 60, "완료 안 된 항목 = 갱신"
# 완료 = 건너뜀
i1.done = "x.mp4"; s1.grade["b_gain"] = 0.9
e.sources_to_render(); wait(0.2)
assert len(p.render_items) == 2 and i1.segs[0].grade.get("b_gain") != 0.9, "완료 = 건너뜀"
# 다른 소스 하나 더 = 추가, 실행취소 1번 = 되돌림
select(s2); e.sources_to_render(); wait(0.2)
assert len(p.render_items) == 3
st.undo(); wait(0.3)
print("실행취소 후 항목:", len(st.project.render_items))
assert len(st.project.render_items) == 2, "실행취소 1번"
print("OK test_ui_srcrender")
