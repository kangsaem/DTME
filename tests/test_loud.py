"""v0.16.66 컷 원본 소리: 말소리 → 키움 / 물속 호흡기 소리 → 안 키움(화면에 빨강이 많아도) / 둘 다 아니면 화면이 수면 위 → 키움 / 물속 → 안 키움.
키운 컷 = 원본 ↑ · 음악 ↓(0.5초 경사). 사용: python tests/test_loud.py <작업폴더>"""
import os, subprocess, sys  # noqa: E401
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import numpy as np
from dtme import ff, music, paths
from dtme.project import Project, Segment, Source, default_mix, new_music

W = Path(sys.argv[1]); W.mkdir(parents=True, exist_ok=True)
D = Path(__file__).with_name("data")
FF = paths.ffmpeg()


def breathing_wav(path, sec=8.0, sr=48000):
    """물속 호흡기 소리 흉내: 바탕 잡음 + 4초마다 들숨 '쉬익'(2.5~8kHz 잡음 0.9초) + 날숨 거품(낮은 소리 덩어리 1.5초)."""
    rng = np.random.default_rng(5)
    n = int(sec * sr)
    y = rng.normal(0, 0.004, n)
    for t0 in np.arange(0.6, sec - 1, 4.0):
        k = int(0.9 * sr)
        hiss = np.fft.irfft(np.fft.rfft(rng.normal(0, 1, k)) * ((np.fft.rfftfreq(k, 1 / sr) > 2500) & (np.fft.rfftfreq(k, 1 / sr) < 8000)), k)
        env = np.sin(np.linspace(0, np.pi, k)) ** 0.5
        y[int(t0 * sr):int(t0 * sr) + k] += 0.12 * hiss / (hiss.std() + 1e-9) * env * 0.5
        b0 = int((t0 + 1.4) * sr)
        for _ in range(60):                       # 거품 = 짧은 낮은 소리
            c = b0 + int(rng.uniform(0, 1.5) * sr)
            m = int(0.03 * sr)
            tt = np.arange(m) / sr
            if c + m < n:
                y[c:c + m] += 0.05 * np.sin(2 * np.pi * rng.uniform(150, 700) * tt) * np.exp(-tt * 90)
    raw = (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run([FF, "-v", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "-", str(path)], input=raw, check=True)
    return path


BREATH = breathing_wav(W / "breathing.wav")
LAND, SEA = "0xb59a72", "0x1b5f8c"          # 모래·하늘빛 / 물속 파랑
cases = {"land_talk": (LAND, D / "speech_librispeech_198-209.ogg", True, "말소리"),
         "underwater": (SEA, BREATH, False, "호흡기"),
         "surface_quiet": (LAND, None, True, "수면 위"),
         "red_breath": (LAND, BREATH, False, "호흡기")}
srcs = {}
for name, (col, aud, _up, _why) in cases.items():
    out = W / f"{name}.mp4"
    a_in = ["-i", str(aud)] if aud else ["-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.003:r=48000"]
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=640x360:r=30:d=6", *a_in, "-t", "6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out)], check=True)
    pi = ff.probe(str(out))
    srcs[name] = Source(path=str(out), **{k: pi[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
# v0.16.77 물속 화면 + 말소리처럼 잡힌 소리 = 안 키움(물속에선 말 못 함)
uw = W / "underwater_talk.mp4"
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={SEA}:s=640x360:r=30:d=6", "-i", str(D / "speech_librispeech_198-209.ogg"),
                "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(uw)], check=True)
pi = ff.probe(str(uw))
su = Source(path=str(uw), **{k: pi[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
ru = music.cut_scene(su, Segment(su.id, 0, su.frames, 1.0))
print("물속 말소리 →", ru["up"], ru["why"], ru.get("speech"))
assert ru.get("speech") and not ru["up"] and ru["why"] == "물속", ru
p = Project()
segs = []
for name, (_c, _a, up, why) in cases.items():
    s = srcs[name]
    p.sources.append(s)
    g = Segment(s.id, 0, s.frames, 1.0)
    r = music.cut_scene(s, g)
    print(f"{name:14} → {'키움' if r['up'] else '안 키움'} ({r['why']})  {({k: v for k, v in r.items() if k not in ('up', 'why')})}")
    assert (r["up"], r["why"]) == (up, why), (name, r)
    g.loud, g.why = r["up"], r["why"]
    segs.append(g)
assert [music.seg_up(g) for g in segs] == [True, False, True, False]
segs[1].aud = "up"; assert music.seg_up(segs[1]); segs[1].aud = "auto"          # 손으로 정함이 먼저
segs[0].aud = "keep"; assert not music.seg_up(segs[0]); segs[0].aud = "auto"
# 렌더: 음악 = 12kHz 사인(원본 소리와 안 겹치는 소리) 24초 → 키운 컷(0~6, 12~18초)은 음악이 30%
mus = W / "tone.m4a"
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=12000:d=30:r=48000", "-c:a", "aac", "-b:a", "256k", str(mus)], check=True)
p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, wnr=0)
p.output.encoder, p.output.gpu_decode = "x264", False
out = W / "loud.mp4"
mix = {**default_mix(), "fin": 0.0, "fout": 0.0}
ex = {"titles": [], "music": [{**new_music(str(mus), 0.0, 30.0), "len": 24.0}], "mix": mix}
cmd = " ".join(ff.build_render_cmd(p, segs, str(out), orientation="horizontal", extras=ex)[0])
assert "volume=eval=frame" in cmd and "clip(min((t-" in cmd
ff.render_video(p, segs, str(out), orientation="horizontal", extras=ex)
raw = subprocess.run([FF, "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
y = np.frombuffer(raw, np.float32)


def tone(a, b):
    x = y[int(a * 48000):int(b * 48000)]
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / 48000)
    return float(X[(f > 11900) & (f < 12100)].max() / len(x))


lv = [tone(a, a + 4) for a in (1, 7, 13, 19)]
print("음악(12kHz) 세기 — 말소리·물속·수면 위·빨강+호흡기:", [round(v, 4) for v in lv])
assert abs(lv[0] / lv[1] - 0.7) < 0.08, "v0.16.73 첫 컷(키움) = 음악 70%"
assert abs(lv[2] / lv[1] - 0.3) < 0.06, "키운 컷 = 음악 30%"
assert abs(lv[3] / lv[1] - 0.5) < 0.07, "v0.16.75 마지막 컷 = 음악 50%"
mid = [tone(5.75 + k * 0.1, 5.85 + k * 0.1) for k in range(5)]                    # 6초 경계: 경사(0.5초)
assert mid[0] < mid[2] < mid[4], ("경사", mid)
print("OK test_loud")
