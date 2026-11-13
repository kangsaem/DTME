"""v0.16.73 장면별 곡: 물 밖 = 발랄(노래 괜찮음) · 블루워터 = 웅장(연주곡) · 얕은 = 잔잔(연주곡), 물속엔 발랄한 곡·노래를 안 씀(다른 곡이 있으면) ·
노래/연주곡 추정(이름·태그) · 컷 길이 = 곡 마디 · 첫·마지막 컷 음악 덜 줄임(렌더 식).
사용: python tests/test_music_scene.py <작업폴더>"""
import os, shutil, subprocess, sys  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
from dtme import autoedit, music, paths
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
FF = paths.ffmpeg()
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_synth.py"), W, "short"], check=True,
               env={**os.environ, "DTME_FFMPEG": FF})
bright = os.path.join(W, "가수 1집 - 신나는 노래.mp3"); shutil.copy(os.path.join(W, "kpop_124.mp3"), bright)
calm = os.path.join(W, "ocean calm (instrumental).mp3"); shutil.copy(os.path.join(W, "newage_66.mp3"), calm)
SR = 22050
t = np.arange(int(40 * SR)) / SR
beat = (np.sin(2 * np.pi * 1.5 * t) > 0.95).astype(float)
y = 0.02 * np.sin(2 * np.pi * 220 * t) + (t >= 12) * (0.5 * np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * beat) + 0.25 * np.sin(2 * np.pi * 82 * t))
epic = os.path.join(W, "epic cinematic.wav")
subprocess.run([FF, "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", epic],
               input=(np.clip(y, -1, 1) * 32767).astype("<i2").tobytes(), check=True)
assert music.guess_kind(bright) == "vocal" and music.guess_kind(calm) == "inst" and music.guess_kind(epic) == "inst"
assert music.guess_kind("/x/휘성 2- 04.I Am Missing You.mp3") == "vocal" and music.guess_kind("/x/I LOVE YOU.mp3") == ""
infos = {f: music.analyze(f) for f in (bright, calm, epic)}
for f, i in infos.items():
    print(os.path.basename(f), "분위기", music.mood(i), "웅장", music.grand(i), "발랄", music.is_bright(i), "종류", i.get("kind"))
assert music.is_bright(infos[bright]) and not music.is_bright(infos[epic]) and not music.is_bright(infos[calm])
auds = [{"path": f, "dur": infos[f]["dur"]} for f in (bright, calm, epic)]
runs = [(0.0, 12.0, "surface"), (12.0, 40.0, "calm"), (40.0, 70.0, "grand"), (70.0, 90.0, "calm")]
items = music.plan_runs(auds, infos, runs, 2.0, targets=autoedit.RUN_TARGET)
at = lambda tt: next(os.path.basename(x["path"]) for x in items if x["t0"] <= tt < x["t0"] + x["len"])   # noqa: E731
print([(os.path.basename(x["path"]), x["t0"], x["len"]) for x in items])
assert at(5) == os.path.basename(bright), "물 밖 = 발랄"
assert at(55) == os.path.basename(epic), "블루워터 = 웅장"
assert all(os.path.basename(x["path"]) != os.path.basename(bright) for x in items if x["t0"] > 10.5), "물속엔 발랄한 노래 안 씀"
# 직접 정함(노래)이 추정보다 먼저
auds2 = [dict(a, kind="vocal") if a["path"] == epic else a for a in auds]
items2 = music.plan_runs(auds2, infos, [(0.0, 30.0, "grand")], 2.0, targets=autoedit.RUN_TARGET)
print("웅장 곡을 노래로 표시:", [os.path.basename(x["path"]) for x in items2])
# 컷 길이 = 마디 단위
for f in (bright, calm):
    b = autoedit.bar_len(infos[f]); L = autoedit.cut_len_for(infos[f])
    print(os.path.basename(f), "마디", round(b, 2), "컷", round(L, 2))
    if b:
        assert 6 - 1e-6 <= L <= 16 + 1e-6 and abs(L / b - round(L / b)) < 1e-6
assert autoedit.cut_len_for({}) == autoedit.CUT_MAX
c = autoedit.allot([60, 60], 60, cut_max=[8, 8])
assert all(len(x) >= 3 for x in c) and all(v <= 10.5 for x in c for v in x), c
# 물 밖 구간은 4초만 넘어도 따로
mr = autoedit.music_runs([("a", 0, 6), ("b", 6, 40), ("c", 46, 30)], {"a": "surface", "b": "shallow", "c": "bluewater"})
assert [g for _a, _b, g in mr] == ["surface", "calm", "grand"], mr
# 첫·마지막 컷 음악 덜 줄임(가중치 식)
assert "*0.4286" in music.ramp_expr([(0, 5), (5, 9)], weights=[(1 - 0.7) / (1 - 0.3), 1.0])
print("OK test_music_scene")
