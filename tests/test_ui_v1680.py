"""v0.16.80: [전체 삭제] = 컷·글자·음악 전부 · 비운 타임라인 = 검은 화면 · ▼ 재생 위치가 마지막 곡 뒤(빈 곳)면 마지막 곡 끝에.
사용: python tests/test_ui_v1680.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from dtme import paths  # noqa: E402
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
FF = paths.ffmpeg()
v = os.path.join(W, "c.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=30", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", v], check=True)
songs = []
for k, d in (("a", 20), ("b", 25)):
    f = os.path.join(W, f"{k} instrumental.wav"); songs.append(f)
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={300 + 100 * len(songs)}:d={d}", f], check=True)
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme.project import Segment, new_music, new_text  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files([v] + songs)
assert wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비"
            and len(st.project.audios) == 2 and all(a.get("dur") for a in st.project.audios))
p = st.project
s = p.sources[0]
A, B = sorted(p.audios, key=lambda a: a["path"])
p.segments = [Segment(s.id, 0, 300), Segment(s.id, 300, 600), Segment(s.id, 600, 900)]
p.music = [new_music(A["path"], 0.0, A["dur"]), new_music(B["path"], 18.0, B["dur"])]
st.touch("segments"); st.touch("titles"); wait(0.3)
e._refresh_audios(); wait(0.2)
# ▼: 마지막 곡(B)을 지우고, 재생 위치는 B 가 있던 끝 → A 끝에 붙음
st.checkpoint(); e.remove_ov("music", p.music[1]["id"]); wait(0.1)
row = next(i for i in range(e.mus_list.count()) if e.mus_list.item(i).data(0x0100) == B["id"])
it = e.mus_list.item(row); e.mus_list.setCurrentItem(it); e.mus_list.itemClicked.emit(it); wait(0.1)
e.tl_time = 42.0; e.timeline.set_time(42.0)
e._key("down"); wait(0.2)
p = st.project
assert len(p.music) == 2, p.music
nb = p.music[-1]
a_end = float(p.music[0]["t0"]) + float(p.music[0]["len"])
print("A 끝", a_end, "B 시작", nb["t0"])
assert a_end - 3.0 <= nb["t0"] <= a_end, nb["t0"]
# ▼ 재생 위치가 곡 안이면 그 자리(예전 그대로)
e.tl_time = 5.0; e.timeline.set_time(5.0); e._key("down"); wait(0.2)
assert abs(st.project.music[-1]["t0"] - 5.0) < 1.0
# 전체 삭제 = 컷·음악·글자 전부, 실행취소 1번이면 다시
st.project.titles.append(new_text(1.0, 4.0, "x"))
nu = len(st._undo)
e.clear_timeline(); wait(0.3)
p = st.project
assert not p.segments and not p.music and not p.titles and len(st._undo) == nu + 1
# 비운 타임라인 이동 = 검은 화면
e.set_mode("timeline") if hasattr(e, "set_mode") else None
e.show_timeline(10.0); wait(0.3)
assert e._tl_seg is None
img = e.player.mon.grab().toImage()
c = img.pixelColor(img.width() // 2, img.height() // 2)
print("가운데 색", c.red(), c.green(), c.blue())
assert max(c.red(), c.green(), c.blue()) < 40, (c.red(), c.green(), c.blue())
# [렌더] = 용량 먼저 → 저장폴더(순서) · 고른 값 = 출력 설정
from dtme import ui_render, ui_style  # noqa: E402
from PySide6.QtWidgets import QFileDialog  # noqa: E402
order = []
ui_style.confirm = lambda parent, text, buttons: (order.append(("q", text, [b[0] for b in buttons])), "small")[1]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: (order.append(("dir",)), "")[1])   # 폴더 취소 = 렌더 안 함
st.project.segments = [Segment(s.id, 0, 300)]; st.touch("segments"); wait(0.2)
e.send_to_render() if hasattr(e, "send_to_render") else None
wait(0.3)
rp = w.render_panel if hasattr(w, "render_panel") else next(x for x in w.findChildren(ui_render.RenderPanel))
assert st.project.render_items, "렌더 항목"
rp.press(); wait(0.2)
print(order)
assert [o[0] for o in order] == ["q", "dir"] and order[0][2] == ["cancel", "high", "normal", "small"] and "MB" in order[0][1]
assert st.project.output.quality == "small" and not rp.running
print("OK test_ui_v1680", flush=True); os._exit(0)
