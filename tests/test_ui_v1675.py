"""v0.16.75: 시작·끝 잔잔 · 노래 = 첫 구간만 · 발랄 안 씀 · 블루워터 첫 등장 = 웅장(+3dB) · 곡 음량 맞추기 · 배 위 판정 ·
▼(음악 목록 골랐을 때) = 재생 위치에 곡 · 음악 목록 → 타임라인 끌어다 놓기 · 실행취소 뒤 타임라인 보이게.
사용: python tests/test_ui_v1675.py <작업폴더>"""
import os, shutil, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np
from dtme import autoedit, music, paths
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
FF = paths.ffmpeg()
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_synth.py"), W, "short"], check=True,
               env={**os.environ, "DTME_FFMPEG": FF})
song = os.path.join(W, "가수 1집 - 잔잔한 노래.mp3"); shutil.copy(os.path.join(W, "ballad_72.mp3"), song)      # 노래(잔잔)
bright = os.path.join(W, "가수 2집 - 신나는 노래.mp3"); shutil.copy(os.path.join(W, "kpop_124.mp3"), bright)   # 노래(발랄)
calm = os.path.join(W, "calm instrumental.mp3"); shutil.copy(os.path.join(W, "newage_66.mp3"), calm)
SR = 22050
t = np.arange(int(40 * SR)) / SR
beat = (np.sin(2 * np.pi * 1.5 * t) > 0.95).astype(float)
y = 0.02 * np.sin(2 * np.pi * 220 * t) + (t >= 12) * (0.5 * np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * beat) + 0.25 * np.sin(2 * np.pi * 82 * t))
epic = os.path.join(W, "epic cinematic.wav")
subprocess.run([FF, "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", epic],
               input=(np.clip(y, -1, 1) * 32767).astype("<i2").tobytes(), check=True)
infos = {f: music.analyze(f) for f in (song, bright, calm, epic)}
auds = [{"path": f, "dur": infos[f]["dur"]} for f in infos]
runs = [(0.0, 15.0, "surface"), (15.0, 45.0, "calm"), (45.0, 75.0, "grand"), (75.0, 95.0, "calm"), (95.0, 120.0, "grand"), (120.0, 135.0, "surface")]
items = music.plan_runs(auds, infos, runs, 2.0, targets=autoedit.RUN_TARGET)
nm = lambda f: os.path.basename(f)          # noqa: E731
at = lambda tt: next(x for x in items if x["t0"] <= tt < x["t0"] + x["len"])      # noqa: E731
print([(nm(x["path"]), x["t0"], round(x["len"], 1), x.get("boost")) for x in items])
assert nm(at(130)["path"]) in (nm(calm),), "끝 = 잔잔(연주곡)"
assert all(nm(x["path"]) != nm(bright) for x in items), "발랄한 곡 안 씀"
assert all(music.guess_kind(x["path"]) != "vocal" for x in items if x["t0"] > 14.5), "노래 = 첫 구간만"
assert nm(at(60)["path"]) == nm(epic) and at(60).get("boost") == music.GRAND_BOOST, "블루워터 첫 등장 = 웅장 + 음량 업"
assert not at(110).get("boost"), "두 번째 블루워터 = 보통 음량"
# 곡 음량 맞추기
g_loud, g_quiet = music.norm_gain({"loud": -8.0}), music.norm_gain({"loud": -25.0})
assert abs(g_loud - 10 ** (-10 / 20)) < 0.01 and abs(g_quiet - 10 ** (7 / 20)) < 0.01 and music.norm_gain(None) == 1.0
# 배 위(바다 수면이 절반) = 물 밖
img = np.zeros((90, 160, 3), np.float32)
img[:50] = [0.86, 0.84, 0.82]                    # 하늘·배(밝은 회색)
img[50:] = [0.20, 0.42, 0.55]                    # 바다 수면(화면 45% — 예전 기준 35% 를 넘어 물속으로 봤음)
ok, rg, water = music.above_water(img)
print("배 위 판정", ok, rg, water)
assert ok and water > 0.35, (rg, water)
img2 = np.zeros((90, 160, 3), np.float32); img2[:] = [0.10, 0.35, 0.55]
assert not music.above_water(img2)[0]

# 화면: ▼(음악 목록) · 끌어다 놓기 · 실행취소 뒤 보이게
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme.project import Segment  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
v = os.path.join(W, "c.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=30", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", v], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files([v, calm]); assert wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비" and st.project.audios)
p = st.project
s = p.sources[0]
p.segments = [Segment(s.id, 0, 300), Segment(s.id, 300, 600), Segment(s.id, 600, 900)]
st.touch("segments"); wait(0.3)
e._refresh_audios(); wait(0.2)
# 클릭 = 고르기만(넣지 않음)
it = e.mus_list.item(0); e.mus_list.setCurrentItem(it); e.mus_list.itemClicked.emit(it); wait(0.1)
assert not p.music and e._del_target == "mus"
# ▼ = 재생 위치(12초)에
e.tl_time = 12.0; e.timeline.set_time(12.0)
nu = len(st._undo)
e._key("down"); wait(0.2)
p = st.project
assert len(p.music) == 1 and abs(p.music[0]["t0"] - 12.0) < 1.0 and len(p.segments) == 3, (p.music, len(p.segments))
assert "gain" in p.music[0] and len(st._undo) == nu + 1
# 끌어다 놓기 = 놓은 시각에
e.timeline.audioDropped.emit(20.0); wait(0.2)
assert len(st.project.music) == 2 and abs(st.project.music[1]["t0"] - 20.0) < 1.0
# 실행취소 뒤 타임라인이 비어 보이지 않게(맨 끝에 머물러 있던 스크롤)
e.zoom.setValue(200); wait(0.2)
sb = e.tl_scroll.horizontalScrollBar(); sb.setValue(sb.maximum()); wait(0.1)
p = st.project
p.segments.append(Segment(s.id, 0, 900)); st.touch("segments"); wait(0.2)
sb.setValue(sb.maximum()); wait(0.1)
st.checkpoint(); st.project.segments.pop(); st.touch("segments"); wait(0.3)
end = e.timeline._x(e.timeline.total())
assert sb.value() <= end - 40, (sb.value(), end)
print("OK test_ui_v1675", flush=True); os._exit(0)
