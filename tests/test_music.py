"""v0.16.64 음악: 박자 분석(합성 곡 정답과 비교) · 분위기 · 음악 자동 계획 · 크로스페이드 렌더.
사용: python tests/test_music.py <작업폴더>"""
import json, os, subprocess, sys  # noqa: E401
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import numpy as np
from dtme import ff, music, paths
from dtme.project import Project, Segment, Source, default_mix, new_music

W = Path(sys.argv[1]); W.mkdir(parents=True, exist_ok=True)
os.environ["DTME_FFMPEG"] = paths.ffmpeg()
subprocess.run([sys.executable, str(Path(__file__).with_name("music_synth.py")), str(W), "short"], check=True)
truth = json.load(open(W / "truth.json"))


def fm(est, ref, tol=0.07):
    est, ref = np.array(est), np.array(ref)
    if not len(est) or not len(ref):
        return 0.0
    p = np.mean([np.min(np.abs(ref - e)) <= tol for e in est])
    r = np.mean([np.min(np.abs(est - x)) <= tol for x in ref])
    return 2 * p * r / (p + r + 1e-9)


info = {}
for name, tr in truth.items():
    d = music.get(str(W / f"{name}.mp3"))
    info[name] = d
    fb, fd = fm(d["beats"], tr["beats"]), fm(d["bars"], tr["downbeats"])
    print(f"{name:10} BPM {d['bpm']:6.1f}(정답 {tr['bpm']}) 박{d['meter']}(정답 {tr['meter']}) 박자 F {fb:.2f} 첫박 F {fd:.2f} 확신 {d['conf']:.2f} 분위기 {music.mood(d):.2f}")
    assert abs(d["bpm"] - tr["bpm"]) / tr["bpm"] < 0.04, name
    assert fb > 0.9 and fd > 0.9 and d["meter"] == tr["meter"], name
    assert len(d["peaks"]) >= int(d["dur"] * 49) and max(d["peaks"]) > 200
assert music.cached(str(W / "kpop_124.mp3")) is not None                      # 저장됨
m = {k: music.mood(v) for k, v in info.items()}
assert m["newage_66"] < m["ballad_72"] < m["soul_92"] < m["kpop_124"], m
# 계획: 잔잔한 영상 = 뉴에이지·발라드 쪽, 빠른 영상 = 케이팝 쪽, 영상이 곡보다 길면 이어 붙임(크로스페이드 2초)
auds = [{"id": k, "path": str(W / f"{k}.mp3"), "dur": v["dur"]} for k, v in info.items()]
infos = {a["path"]: info[a["id"]] for a in auds}
calm = music.plan(auds, infos, 20.0, 0.05)
fast = music.plan(auds, infos, 20.0, 0.95)
print("잔잔한 영상 →", [Path(x["path"]).stem for x in calm], "· 빠른 영상 →", [Path(x["path"]).stem for x in fast])
assert Path(calm[0]["path"]).stem in ("newage_66", "ballad_72") and Path(fast[0]["path"]).stem == "kpop_124"
assert len(calm) == 1 and abs(calm[0]["len"] - 20.0) < 1e-6
long = music.plan(auds, infos, 70.0, 0.05, xfade=2.0)
print("70초 →", [(Path(x["path"]).stem, x["t0"], x["len"]) for x in long])
assert len(long) >= 3 and abs(long[-1]["t0"] + long[-1]["len"] - 70.0) < 1e-3
for a, b in zip(long, long[1:]):
    assert abs((a["t0"] + a["len"]) - b["t0"] - 2.0) < 1e-3, "겹침 2초"
    bars = infos[a["path"]]["bars"]
    assert any(abs(a["off"] + a["len"] - x) < 1e-3 for x in bars), "앞 곡은 마디 첫 박에서 끝남"
# 크로스페이드 렌더: 두 곡을 4초 겹침 → 겹친 곳 소리가 끊기지 않고(합 일정), 앞 곡 끝은 줄어듦
clip = W / "black.mp4"
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=20", "-f", "lavfi", "-i",
                "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
pi = ff.probe(str(clip))
src = Source(path=str(clip), **{k: pi[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
p = Project(); p.sources.append(src)
p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, wnr=0)
p.output.encoder, p.output.gpu_decode = "x264", False
a1 = {**new_music(str(W / "newage_66.mp3"), 0.0, info["newage_66"]["dur"]), "len": 12.0}
a2 = {**new_music(str(W / "ballad_72.mp3"), 8.0, info["ballad_72"]["dur"]), "len": 12.0}
out = W / "xfade.mp4"
ff.render_video(p, [Segment(src.id, 0, src.frames, 1.0)], str(out), orientation="horizontal",
                extras={"titles": [], "music": [a1, a2], "mix": {**default_mix(), "fin": 0.0, "fout": 0.0}})
raw = subprocess.run([paths.ffmpeg(), "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
y = np.frombuffer(raw, np.float32)
rms = [float(np.sqrt(np.mean(y[int(t * 8000):int((t + 0.5) * 8000)] ** 2))) for t in np.arange(0, 19.5, 0.5)]
pre, mid, post = np.mean(rms[2:14]), np.mean(rms[17:23]), np.mean(rms[26:38])
print(f"크로스페이드 세기: 앞 {pre:.3f} · 겹침 {mid:.3f} · 뒤 {post:.3f}")
assert min(rms[16:24]) > 0.35 * min(pre, post), "겹친 곳이 끊기지 않음"
assert mid < 1.6 * max(pre, post), "겹친 곳이 두 배로 커지지 않음"
cmd = " ".join(ff.build_render_cmd(p, [Segment(src.id, 0, src.frames, 1.0)], str(out), orientation="horizontal",
                                   extras={"titles": [], "music": [a1, a2], "mix": default_mix()})[0])
assert cmd.count("curve=qsin") == 2, "겹친 쪽만 크로스페이드 곡선"
print("OK test_music")
