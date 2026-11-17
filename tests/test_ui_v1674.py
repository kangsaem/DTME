"""v0.16.74: 자동 편집·AUTO 작업 중 = 편집 창 숨김, 작업 창만 작업 표시줄(주인 없는 창 · [−]), 끝·취소 = 편집 창 원래대로.
사용: python tests/test_ui_v1674.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths, ui_style
from dtme.ui_main import MainWindow
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
vids = []
for i in range(2):
    v = os.path.join(WORK, f"k{i}.mp4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
    vids.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files(vids); assert wait(90, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
for s in st.project.sources:
    s.auto = {"preset": "shallow", "by": "user"}
ui_style.confirm = lambda *a, **k: "ok"
# 1) 자동 편집(v0.17.0 자동 창): 시작 = 편집 창 숨김, 자동 창 = 주인 없는 창 + [−] / 끝 = 편집 창 다시
from dtme.project import set_setting as _ss; _ss("autowin", {})      # 자동 창 기억한 선택 지움(시험끼리 영향 없게)
dlg = e.make_auto_window(); dlg.show(); wait(0.2)
dlg.length.setValue(1)
assert not dlg.b_min.isVisible()
e.run_autoedit(dlg, dlg.autoedit_settings()); wait(0.2)
hidden = not w.isVisible()
print("작업 중: 편집 창 숨김", hidden, "· 주인 없음", dlg.parent() is None, "· [−]", dlg.b_min.isVisible())
assert hidden and dlg.parent() is None and dlg.b_min.isVisible() and dlg.isVisible()
dlg.b_min.click(); wait(0.1)                       # 내리기
assert wait(120, lambda: w.isVisible()), "끝나면 편집 창"
assert not dlg.isVisible() and st.project.segments
# 2) 자동 창 작업 중 [취소] = 편집 창 다시 + 자동 창 남음(설정 화면)
wait(1.0)                                          # 앞 작업 정리(Windows CI 에서 가끔 늦음)
dlg2 = e.make_auto_window(); dlg2.show(); wait(0.2)
for k in ("grade", "music", "render"):
    dlg2.stages[k].set_on(False)
dlg2.stages["edit"].set_on(True); dlg2._sync()
dlg2.b_start.click()
assert wait(3, lambda: not w.isVisible()), "두 번째 자동 편집 = 편집 창 숨김"
assert dlg2.running and not dlg2.rw.isVisible() and dlg2.run_w.isVisible()
dlg2.cancel(); wait(0.3)
assert w.isVisible() and dlg2.isVisible() and not dlg2.running and dlg2.rw.isVisible()
dlg2.cancel(); wait(0.2)                           # 작업 없음 [취소] = 닫힘
assert not dlg2.isVisible()
# 3) 보정 단계: 분석 기다림 = 편집 창 숨김 / 작업 중 [취소] = 편집 창 + 자동 창 남음
for s in st.project.sources:
    s.auto = {}
ad = e.make_auto_window(); ad.show(); wait(0.2)
for k in ("edit", "music", "render"):
    ad.stages[k].set_on(False)
ad.stages["grade"].set_on(True); ad._sync()
ad.analyze_all = lambda: None                      # 분석이 안 끝난 상태로 둠
ad.b_start.click(); wait(0.1)
print("보정 기다림: 편집 창 숨김", not w.isVisible(), "· 자동 창", ad.isVisible(), ad.parent() is None)
assert ad.running and not w.isVisible() and ad.isVisible() and ad.parent() is None
ad.cancel(); wait(0.3)
assert w.isVisible() and ad.isVisible() and not ad.running
ad.cancel()
print("OK test_ui_v1674", flush=True); os._exit(0)
