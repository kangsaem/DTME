"""v0.16.81 AUTO 창 [전부 자동]: 팝업(자동 편집 설정 + 프로젝트 저장 기본 체크) → 용량 → 폴더 → 분석 → AUTO 값 → 자동 편집(음악) →
타임라인 1편만 렌더 → 영상 옆 프로젝트(.dtme.json). 음악 없으면 음악 없이.
사용: python tests/test_ui_v1681.py <작업폴더>"""
import glob, os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import paths, ui_style  # noqa: E402
from dtme.project import RenderItem, Segment  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
OUT = os.path.join(WORK, "out"); os.makedirs(OUT, exist_ok=True)
for f in glob.glob(os.path.join(OUT, "*")):
    os.remove(f)
vids = []
for i in range(2):
    v = os.path.join(WORK, f"DJI_2026062{i}_10{i}000_0001_D.MP4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8", "-f", "lavfi", "-i",
                    "sine=d=8", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v], check=True)
    vids.append(v)
song = os.path.join(WORK, "calm instrumental.wav")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=40", song], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files(vids + [song])
assert wait(90, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources)
            and st.project.audios and all(a.get("dur") for a in st.project.audios))
ui_style.confirm = lambda *a, **k: "ok"
e._ask_folder = lambda title="": OUT
# 렌더 리스트에 다른 항목이 있어도 = 전부 자동 1편만 렌더
s0 = st.project.sources[0]
st.project.render_items.append(RenderItem(name="other", segs=[Segment(s0.id, 0, 30, 1.0)]))
from dtme import ui_autoedit  # noqa: E402
stages = []
_set = ui_autoedit.StageBar.set
ui_autoedit.StageBar.set = lambda self, kind, v, text="": (stages.append(kind) if not stages or stages[-1] != kind else None, _set(self, kind, v, text))[1]
for s_ in st.project.sources:
    s_.auto = {}
ad = e.make_auto_dialog(); ad.show(); wait(0.3)
for r in ad.rows:                                   # 분석 기다림부터(작업 창 막대 = 보정 단계)
    r.result, r.prog = None, 0.0
assert ad.b_full.text() == "전부 자동" and ad.b_full.isVisible()
seen = {}


def click_popup():
    from dtme.ui_autoedit import AutoEditDialog
    ed = next((x for x in app.topLevelWidgets() if isinstance(x, AutoEditDialog) and x.isVisible()), None)
    if ed is None:
        QTimer.singleShot(100, click_popup); return
    seen["save"] = ed.save_on.isChecked() and ed.save_on.isVisible()
    seen["grade_hidden"] = not ed.grade_on.isVisible()
    seen["btn"] = ed.b_start.text()
    ed.length.setValue(1)
    ed.b_start.click()


QTimer.singleShot(200, click_popup)
ad.b_full.click()
print("팝업:", seen)
assert seen == {"save": True, "grade_hidden": True, "btn": "전부 자동"}, seen
wait(0.5)
work = e._full_dlg
assert work is not None and work.isVisible() and work.stage_bar.isVisible() and not ad.isVisible(), "작업 창 하나"
print("작업 중: 편집 창 숨김", not w.isVisible())
assert not w.isVisible()
ok = wait(400, lambda: any(f.endswith(".mp4") for f in os.listdir(OUT)) and not e.render_panel.running and not work.isVisible())
assert w.isVisible(), "끝 = 편집 창"
p = st.project
files = sorted(os.listdir(OUT))
print("결과:", files, "· 컷", len(p.segments), "· 음악", len(p.music), "· 보정", [s.auto.get("preset") for s in p.sources])
assert ok, files
assert len(p.segments) >= 2 and p.music and all(s.auto.get("preset") for s in p.sources)
mp4 = [f for f in files if f.endswith(".mp4")]
prj = [f for f in files if f.endswith(".dtme.json")]
assert len(mp4) == 1 and len(prj) == 1, files
assert p.file and p.file.endswith(".dtme.json")
other = next(it for it in p.render_items if it.name == "other")
assert not other.done, "다른 렌더 항목은 안 함"
d = __import__("dtme.ff", fromlist=["ff"]).probe(os.path.join(OUT, mp4[0]))
print("단계", stages)
assert stages == ["analyze", "edit", "music", "render"], stages
print("영상 길이", round(d["frames"] / (d["fps_num"] / d["fps_den"]), 1), "초")
print("OK test_ui_v1681", flush=True); os._exit(0)
