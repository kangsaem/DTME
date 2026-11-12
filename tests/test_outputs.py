"""v0.16.32 점검: 원본보다 큰 출력은 안 보이고 안 골라짐(업스케일 없음, 세로는 늘).
- 규칙(project.outputs_for · clamp_out) · 보정 패널 출력 칸(불러온 원본 중 가장 큰 것 기준)
- AUTO 창: 고른 줄 원본에 맞는 버튼만 보임, 큰 값을 눌러도 줄마다 원본 한도까지
- 렌더 리스트로(▼ · ➜): 원본보다 크면 낮춤
사용: python tests/test_outputs.py <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.project import outputs_for, clamp_out, src_out_h
from dtme.ui_main import MainWindow

assert outputs_for(src_out_h(3840, 2160)) == ["horizontal", "horizontal1440", "horizontal2160", "vertical"]
assert outputs_for(src_out_h(2688, 1512)) == ["horizontal", "horizontal1440", "vertical"]
assert outputs_for(src_out_h(1920, 1080)) == ["horizontal", "vertical"]
assert clamp_out("horizontal2160", 1512) == "horizontal1440" and clamp_out("vertical", 1080) == "vertical"
print("규칙 OK")

WORK = sys.argv[1]; os.makedirs(WORK, exist_ok=True)
mk = {}
for name, size in (("1080", "1920x1080"), ("27k", "2688x1512"), ("4k", "3840x2160")):
    c = os.path.join(WORK, f"DJI_2026111009{len(mk)}000_000{len(mk)}_D.MP4")
    if not os.path.exists(c):
        ff.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=60000/1001:d=1",
                "-c:v", "libx264", "-preset", "ultrafast", c])
    mk[name] = c
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
p = st.project
p.output.orientation = "horizontal2160"
e.import_files([mk["1080"]])
assert wait(60, lambda: len(p.sources) == 1 and p.sources[0].frames)
wait(0.5)
items = [e.grade.out.itemData(i) for i in range(e.grade.out.count())]
print("1080 만:", items, p.output.orientation)
assert items == ["horizontal", "vertical"] and p.output.orientation == "horizontal"
e.import_files([mk["27k"], mk["4k"]])
assert wait(60, lambda: len(p.sources) == 3 and all(x.frames for x in p.sources))
wait(0.5)
items = [e.grade.out.itemData(i) for i in range(e.grade.out.count())]
print("섞임(지금 클립 = 1080):", items)
assert items == ["horizontal", "vertical"]                    # v0.16.55 출력 칸 = 지금 클립에 맞는 것만(출력 = 소스별)
e._select_source(next(x.id for x in p.sources if x.width == 3840)); wait(0.5)
items = [e.grade.out.itemData(i) for i in range(e.grade.out.count())]
assert items == ["horizontal", "horizontal1440", "horizontal2160", "vertical"], items

# 렌더 리스트로: 기본 4K → 원본마다 한도
p.output.orientation = "horizontal2160"
for i in range(e.src_list.count()):
    e.src_list.item(i).setSelected(True)
e.sources_to_render(); wait(0.3)
got = {p.source(it.segs[0].src).width: it.orientation for it in p.render_items}
print("▼:", got)
assert got == {1920: "horizontal", 2688: "horizontal1440", 3840: "horizontal2160"}

# AUTO 창
d = e.make_auto_dialog(); d.show(); wait(0.3)
byw = {p.source(r.sid).width: i for i, r in enumerate(d.rows)}
d.list.clearSelection(); d.list.item(byw[1920]).setSelected(True); d.list.setCurrentRow(byw[1920]); wait(0.2)
vis = [k for k, b in d.out.btns.items() if b.isVisible()]
print("AUTO 1080 줄 버튼:", vis)
assert vis == ["horizontal", "vertical"]
for i in range(d.list.count()):
    d.list.item(i).setSelected(True)
wait(0.2)
vis = [k for k, b in d.out.btns.items() if b.isVisible()]
assert vis == ["horizontal", "horizontal1440", "horizontal2160", "vertical"]
d._out("horizontal2160")
outs = {p.source(r.sid).width: r.out for r in d.rows}
print("AUTO 전체 4K 누름:", outs)
assert outs == {1920: "horizontal", 2688: "horizontal1440", 3840: "horizontal2160"}
d.close()
print("OK test_outputs")
