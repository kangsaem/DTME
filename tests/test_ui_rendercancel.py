"""v0.16.54: [렌더] 버튼 = 누를 때마다 저장폴더 물음(취소 = 렌더 안 함) · 렌더 중 다시 누르면 전체 취소(완료분 그대로, 버튼 복귀, 완료 팝업 없음).
AUTO·코드 경로(render/enqueue)는 폴더가 있으면 안 물음. 사용: python tests/test_ui_rendercancel.py <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication, QFileDialog
import main as M
from dtme import ff, jobs, paths
from dtme.ui_main import MainWindow
WORK = sys.argv[1]; os.makedirs(WORK, exist_ok=True)
clips = []
for i in range(3):
    c = os.path.join(WORK, f"DJI_2026111211{i}000_000{i}_D.MP4")
    if not os.path.exists(c):
        ff.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60000/1001:d=12", c])
    clips.append(c)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


w.edit.import_files(clips)
assert wait(180, lambda: len(w.state.project.sources) == 3 and all(s.frames for s in w.state.project.sources))
p = w.state.project
p.output.encoder = "x264"; p.output.gpu_decode = False
e = w.edit; rp = e.render_panel
jobs.RENDER_N = 1                                   # 1개씩 → 대기 중인 항목이 생김
for i in range(e.src_list.count()):
    e.src_list.item(i).setSelected(True)
e.sources_to_render(); wait(0.3)
assert len(p.render_items) == 3
out1, out2 = os.path.join(WORK, "out1"), os.path.join(WORK, "out2")
os.makedirs(out1, exist_ok=True); os.makedirs(out2, exist_ok=True)
asked = []
ans = [""]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), ans[0])[1])
# 1) 폴더 창에서 취소 = 렌더 안 함
rp.b_render.click(); wait(0.2)
assert len(asked) == 1 and not rp.running, "취소 = 렌더 안 함"
# 2) 폴더 고름 → 렌더 시작
ans[0] = out1
rp.b_render.click()
assert len(asked) == 2 and rp.running and p.output.folder == out1
assert wait(120, lambda: rp.b_render.frac is not None and rp.b_render.frac > 0.02), "진행"
assert "누르면 취소" in rp.b_render.toolTip(), rp.b_render.toolTip()
assert len(rp.active) == 1 and len(rp.queue) == 2
# 3) 렌더 중 다시 누름 = 전체 취소(폴더 안 물음)
t0 = time.time()
rp.b_render.click()
assert len(asked) == 2, "렌더 중 = 폴더 안 물음"
assert wait(30, lambda: not rp.running), "취소 뒤 끝남"
wait(0.5)
print(f"취소 {time.time() - t0:.1f}초 · 상태 {[rp.status.get(x.id, '') for x in p.render_items]}")
assert rp.b_render.frac is None and not rp.active and not rp.queue and not rp.jobs, "버튼 복귀"
assert not any(x.done for x in p.render_items) and not os.listdir(out1), ("만들다 만 파일 없음", os.listdir(out1))
assert getattr(w, "_done_dlg", None) is None, "취소 = 완료 팝업 없음"
assert "렌더 " not in w.windowTitle()
# 4) 다시 누름 = 또 물어봄(처음 위치 = 지난 폴더) → 끝까지
ans[0] = out2
rp.b_render.click()
assert len(asked) == 3 and asked[-1] == out1 and p.output.folder == out2, asked
jobs.RENDER_N = 3
assert wait(600, lambda: not rp.running), "렌더 끝"
wait(0.5)
assert len([f for f in os.listdir(out2) if f.endswith(".mp4")]) == 3 and all(x.done for x in p.render_items)
assert getattr(w, "_done_dlg", None) is not None, "끝 = 완료 팝업"
# 5) 코드 경로(render) = 폴더가 있으면 안 물음
rp.render(); wait(0.2)
assert len(asked) == 3
print("OK test_ui_rendercancel"); os._exit(0)
