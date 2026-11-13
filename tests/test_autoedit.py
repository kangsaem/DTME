"""v0.16.68 자동 편집 · 음악 웅장함: 엔진(나누기·구간 고르기·웅장함·장면별 곡) + 화면 흐름(창 → 타임라인, 실행취소 1번).
사용: python tests/test_autoedit.py [작업폴더]"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np
from dtme import autoedit, music, paths
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

d = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
os.makedirs(d, exist_ok=True)
ffm = paths.ffmpeg()

# ---------------------------------------------------------------- 1) 엔진
a = autoedit.allot([40, 40, 40], 60)
assert all(autoedit.CUT_MIN <= x <= autoedit.CUT_MAX for c in a for x in c) and abs(sum(sum(c) for c in a) - 60) < 0.5, a
a = autoedit.allot([300, 20], 180)                  # 긴 소스 = 1분 넘으면 컷 여러 개
assert len(a[0]) >= 2 and all(x <= 60 for x in a[0]) and a[1] and a[1][0] <= 20, a
a = autoedit.allot([10, 12], 300)                   # 원본이 모자람 = 원본 길이까지
assert abs(sum(sum(c) for c in a) - (9.8 + 11.8)) < 0.01, a
sc = np.ones(100); sc[60:72] = 5
w = autoedit.best_windows(sc, 6.0, 1)
assert abs(w[0] - 30.0) < 0.6, w                    # 점수 높은 30~36초
w2 = autoedit.best_windows(sc, 6.0, 3)
assert len(w2) == 3 and all(abs(x - y) >= 6.0 for x in w2 for y in w2 if x != y), w2

# 웅장함: 조용 → 크게 터짐 + 낮은 소리 = 웅장 / 잔잔한 고음 = 덜
SR = 22050


def wav(name, y):
    f = os.path.join(d, name)
    raw = (np.clip(np.stack([y, y], 1), -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run([ffm, "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "-", f], input=raw, check=True)
    return f


t = np.arange(int(40 * SR)) / SR
epic = 0.02 * np.sin(2 * np.pi * 220 * t)
loud = t >= 12
beat = (np.sin(2 * np.pi * 1.5 * t) > 0.95).astype(float)
epic = epic + loud * (0.5 * np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * beat) + 0.25 * np.sin(2 * np.pi * 82 * t))
calm = 0.15 * np.sin(2 * np.pi * 880 * t) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.2 * t)) + 0.08 * np.sin(2 * np.pi * 1320 * t)
f_epic, f_calm = wav("epic.wav", epic), wav("calm.wav", calm)
ie, ic = music.analyze(f_epic), music.analyze(f_calm)
print("웅장함 epic", music.grand(ie), ie["dyn"], ie["bass"], "/ calm", music.grand(ic), ic["dyn"], ic["bass"], flush=True)
assert music.grand(ie) > 0.7 and music.grand(ic) < 0.3
# 장면별 곡: 블루워터 구간 = 웅장한 곡, 얕은 구간 = 잔잔한 곡
auds = [{"path": f_epic, "dur": ie["dur"]}, {"path": f_calm, "dur": ic["dur"]}]
infos = {f_epic: ie, f_calm: ic}
runs = [(0.0, 20.0, "calm"), (20.0, 50.0, "grand"), (50.0, 70.0, "calm")]          # v0.16.75 시작·끝 = 잔잔, 가운데 블루워터 = 웅장
items = music.plan_runs(auds, infos, runs, 2.0, targets=autoedit.RUN_TARGET)
at_ = lambda tt: next(x["path"] for x in items if x["t0"] <= tt < x["t0"] + x["len"])     # noqa: E731
assert at_(5) == f_calm and at_(35) == f_epic and at_(65) == f_calm, [(x["path"], x["t0"]) for x in items]
cov = max(x["t0"] + x["len"] for x in items)
assert cov >= 69.5, items
spans = [("a", 0.0, 10.0), ("b", 10.0, 10.0), ("c", 20.0, 30.0), ("d", 50.0, 15.0)]
mr = autoedit.music_runs(spans, {"a": "bluewater", "b": "bluewater", "c": "shallow", "d": "deep"})
assert [g for _a, _b, g in mr] == ["grand", "calm"] and mr[0][1] == 20.0, mr      # 20초 미만 '깊은' 구간 = 앞에 붙음
# 글자 사각형(v0.16.69): 세로 화면에서도 사각형 = 글자 + 여백, 왼쪽 5% · 아래 12%
for wh in ((1920, 1080), (1080, 1920)):
    rc, tx = autoedit.title_pair("2026 0624 1014", 1.0, wh)
    tw, th = autoedit.text_size(tx)
    W, H = wh
    assert abs(rc["w"] * W - (tw + 48 + 0.05 * W)) < 1 and abs(rc["h"] * H - (th + 24)) < 1, (wh, rc, tw, th)
    assert abs((rc["cx"] - rc["w"] / 2) * W) < 1 and abs((rc["cy"] + rc["h"] / 2) * H - 0.88 * H) < 1     # 왼쪽 끝 = 화면 끝
    assert abs((rc["cx"] + rc["w"] / 2) * W - (tx["cx"] * W + (tw + 48) / 2)) < 1 and rc["cy"] == tx["cy"]   # 오른쪽 = 글자 + 여백
print("엔진 OK", flush=True)

# ---------------------------------------------------------------- 2) 화면 흐름
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import ui_style  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402

vids = []
for i, src in enumerate(["testsrc2", "smptebars", "testsrc2", "rgbtestsrc"]):
    v = os.path.join(d, f"k{i}.mp4")
    subprocess.run([ffm, "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s=640x360:r=30:d=40", "-f", "lavfi",
                    "-i", "sine=f=300:d=40", "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v], check=True)
    vids.append(v)
M.dark(app)
w = MainWindow(); w.resize(1700, 950); w.show()


def wait(sec, cond=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond():
            return True


st, e = w.state, w.edit
e.import_files(vids); wait(90, lambda: len(st.project.sources) == 4 and all(st.status.get(x.id) == "준비" for x in st.project.sources))
print("단계: 가져오기", flush=True)
p = st.project
for s, k in zip(p.sources, ["bluewater", "shallow", "", "bluewater"]):
    if k:
        s.auto = {"preset": k, "by": "user"}
p.audios = [{"id": "a1", "path": f_epic, "dur": ie["dur"]}, {"id": "a2", "path": f_calm, "dur": ic["dur"]}]
p.segments = [__import__("dtme.project", fromlist=["Segment"]).Segment(p.sources[0].id, 0, 90)]
st.touch("segments"); wait(0.2)

for s in p.sources:
    s.out = "vertical"                                # 세로 출력에서 글자 사각형 확인(v0.16.69)
from dtme.ui_autoedit import AutoEditDialog  # noqa: E402
dlg = AutoEditDialog(st, {s.id for s in p.sources}, e)
dlg.length.setValue(1)
dlg.music_on.setChecked(True)
assert dlg.settings()["minutes"] == 1 and dlg.settings()["grade"] and dlg.settings()["title"]
dlg.show(); wait(0.2)
dlg.grab().save(os.path.join(d, "autoedit_dialog.png"))
ui_style.confirm = lambda *a_, **k_: "ok"            # 타임라인 바꾸기 확인
print("단계: 실행", flush=True)
nu = len(st._undo)
e.run_autoedit(dlg, dlg.settings())
assert wait(240, lambda: not dlg.isVisible()), dlg.state_lab.text()
print("단계: 끝남", flush=True)
wait(0.5)
p = st.project
segs = p.segments
lens = [p.seg_out_seconds(g, p.source(g.src).fps) for g in segs]
tot = p.out_seconds()
print("컷", len(segs), [round(x, 2) for x in lens], "결과", round(tot, 2), "음악", [(os.path.basename(m["path"]), m["t0"], m["len"]) for m in p.music], flush=True)
assert len(st._undo) == nu + 1                       # 실행취소 1번
assert len(segs) >= 4 and all(autoedit.CUT_MIN - 0.05 <= x <= autoedit.CUT_MAX + 0.05 for x in lens)
assert abs(tot - 60) < 3.0, tot
names = [os.path.basename(p.source(g.src).path) for g in segs]
assert names == sorted(names), names                 # 목록순(이름에 날짜 없음)
assert not segs[0].trans and all(g.trans.get("dur") == 0.5 for g in segs[1:])
assert len({g.trans["type"] for g in segs[1:]}) >= 1
tt = [x for x in p.titles if x.get("auto_edit")]
assert len(tt) == 8 and all(x.get("follow") and x["ain"] == "right" and x["aout"] == "left" for x in tt)
assert all(abs((x["t1"] - x["t0"]) - 5.0) < 1e-3 for x in tt)
from dtme.project import cut_spans, display_name  # noqa: E402
starts = {cid: t for cid, t, _l in cut_spans(p)}
firsts = {}
for g in segs:
    firsts.setdefault(g.src, g.id)
texts = sorted((x["text"], round(x["t0"], 2)) for x in tt if x["kind"] == "text")
tdur = {g.id: float((g.trans or {}).get("dur", 0) or 0) for g in segs}
want = sorted((display_name(p.source(sid).path), round(starts[cid] + tdur[cid] + 1.0, 2)) for sid, cid in firsts.items())
assert texts == want, (texts, want)
assert p.sources[2].auto.get("preset"), p.sources[2].auto       # 보정 안 된 소스 = AUTO 먼저
assert p.music and all(m.get("follow") for m in p.music)
assert max(float(m["t0"]) + float(m["len"]) for m in p.music) >= tot - 0.2
assert os.path.basename(p.music[0]["path"]) == "calm.wav"            # v0.16.75 시작 = 잔잔(끝은 곡이 2개뿐이라 모자라면 다른 곡이 이어짐 — 엔진 시험에서 확인)
assert all("gain" in m for m in p.music) and p.mix["fout"] >= 4.0
e.show_timeline(1.2); wait(1.5)
w.grab().save(os.path.join(d, "autoedit_after.png"))
rx = next(x for x in tt if x["kind"] == "rect")
assert abs(rx["h"] * 1920 - (autoedit.text_size(next(x for x in tt if x["kind"] == "text"))[1] + 24)) < 1   # 세로 기준
e.timeline.grab().save(os.path.join(d, "autoedit_tl.png"))
print("단계: 실행취소", flush=True)
w.undo(); wait(0.3)
assert len(st.project.segments) == 1 and not any(x.get("auto_edit") for x in st.project.titles)
print("OK test_autoedit", flush=True)
os._exit(0)
