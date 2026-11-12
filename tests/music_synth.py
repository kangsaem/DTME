"""시험용: 박자를 아는 합성 곡(장르 흉내 — 케이팝·발라드·뉴에이지 피아노·소울·왈츠) → mp3 + 정답 박자 truth.json.
사용: python tests/music_synth.py <폴더> [짧게]"""
import json, os, subprocess, sys
import numpy as np
SR = 44100
rng = np.random.default_rng(7)

def tone(f, dur, amp=0.2, decay=3.0, harm=(1, .5, .25, .12), att=0.004):
    t = np.arange(int(dur * SR)) / SR
    w = sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(harm))
    env = np.minimum(1, t / att) * np.exp(-decay * t)
    return amp * w * env

def kick(amp=0.9):
    t = np.arange(int(0.35 * SR)) / SR
    f = 50 + 90 * np.exp(-t * 30)
    return amp * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)

def snare(amp=0.5):
    t = np.arange(int(0.2 * SR)) / SR
    return amp * (rng.normal(0, 1, len(t)) * np.exp(-t * 25) * 0.7 + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 20) * 0.5)

def hat(amp=0.15):
    t = np.arange(int(0.05 * SR)) / SR
    n = rng.normal(0, 1, len(t)); n = np.diff(n, prepend=0)
    return amp * n * np.exp(-t * 80)

def put(buf, x, at):
    i = int(at * SR)
    if i >= len(buf): return
    n = min(len(x), len(buf) - i); buf[i:i + n] += x[:n]

def nf(m): return 440 * 2 ** ((m - 69) / 12)
PROG = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]       # Am F C G

def song(kind, bpm, dur, rubato=0.0, swing=0.0, meter=4):
    buf = np.zeros(int((dur + 2) * SR))
    beat = 60 / bpm
    beats, t, k = [], 0.6, 0
    while t < dur:
        beats.append(t)
        t += beat * (1 + rubato * np.sin(k / 7.0) + rubato * rng.normal(0, 0.3))
        k += 1
    for i, b in enumerate(beats):
        bar, pos = divmod(i, meter)
        ch = PROG[(bar) % 4]
        nxt = beats[i + 1] if i + 1 < len(beats) else b + beat
        if kind == "kpop":
            put(buf, kick(), b)
            if pos in (1, 3): put(buf, snare(), b)
            for h in (0, 0.5): put(buf, hat(), b + h * (nxt - b))
            if pos == 0:
                for m in ch: put(buf, tone(nf(m + 12), beat * 4, 0.06, 0.6, (1, .6, .4, .3, .2)), b)
            put(buf, tone(nf(ch[0] - 12), beat * 0.9, 0.35, 4, (1, .3)), b)
            mel = ch[(i * 3) % 3] + 12 + (2 if i % 5 == 0 else 0)
            put(buf, tone(nf(mel), beat * 0.9, 0.08, 2, (1, .2)) * (1 + 0.003 * np.sin(np.arange(int(beat * .9 * SR)) / SR * 2 * np.pi * 5)), b)
        elif kind == "ballad":
            if pos == 0: put(buf, kick(0.5), b)
            if pos == 2: put(buf, snare(0.18), b)
            for m in ch: put(buf, tone(nf(m + 12), beat * 1.5, 0.05, 1.2), b + (0.02 if pos else 0))
            if pos == 0: put(buf, tone(nf(ch[0] - 12), beat * 4, 0.2, 0.7, (1, .4)), b)
            put(buf, tone(nf(ch[pos % 3] + 24), beat * 1.2, 0.05, 1.5, (1, .2)), b)
        elif kind == "newage":
            if pos == 0:
                put(buf, tone(nf(ch[0] - 12), beat * 4, 0.15, 0.5), b)
            for j, m in enumerate([ch[0], ch[1], ch[2], ch[1]][:2]):
                put(buf, tone(nf(m + 12 + (12 if (pos + j) % 3 == 0 else 0)), beat * 2, 0.07, 0.9, (1, .3, .1), att=0.012), b + j * (nxt - b) / 2)
        elif kind == "soul":
            put(buf, kick(0.7 if pos in (0, 2) else 0.0), b)
            if pos in (1, 3): put(buf, snare(0.4), b)
            put(buf, hat(0.12), b); put(buf, hat(0.08), b + (0.5 + swing) * (nxt - b))
            put(buf, tone(nf(ch[pos % 3] - 12), beat * 0.8, 0.3, 3, (1, .5)), b)
            if pos == 0:
                for m in ch: put(buf, tone(nf(m + 12), beat * 3, 0.05, 0.8, (1, .5, .3)), b + 0.03)
        elif kind == "waltz":
            if pos == 0: put(buf, tone(nf(ch[0] - 12), beat, 0.3, 3), b)
            else:
                for m in ch: put(buf, tone(nf(m + 12), beat * 0.6, 0.07, 4), b)
            put(buf, tone(nf(ch[pos % 3] + 24), beat, 0.06, 2), b)
    buf += rng.normal(0, 0.002, len(buf))
    buf = buf[:int(dur * SR)]
    buf /= np.abs(buf).max() * 1.12
    return buf, [b for b in beats if b < dur], meter

specs = {"kpop_124": ("kpop", 124, 70), "ballad_72": ("ballad", 72, 80), "newage_66": ("newage", 66, 90, 0.025),
         "soul_92": ("soul", 92, 60, 0.0, 0.12), "waltz_150": ("waltz", 150, 45, 0.0, 0.0, 3)}
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
short = len(sys.argv) > 2
if short:
    specs = {k: (v[0], v[1], min(v[2], 30)) + tuple(v[3:]) for k, v in specs.items()}
truth = {}
for name, sp in specs.items():
    kind, bpm, dur = sp[:3]
    rub = sp[3] if len(sp) > 3 else 0.0; sw = sp[4] if len(sp) > 4 else 0.0; meter = sp[5] if len(sp) > 5 else 4
    y, beats, meter = song(kind, bpm, dur, rub, sw, meter)
    st = np.stack([y, y], 1)
    raw = (np.clip(st, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run([os.environ.get("DTME_FFMPEG", "ffmpeg"), "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "libmp3lame", "-b:a", "192k", f"{out}/{name}.mp3"], input=raw, check=True)
    truth[name] = {"bpm": bpm, "beats": beats, "downbeats": beats[::meter], "meter": meter}
json.dump(truth, open(f"{out}/truth.json", "w"))
print("ok", list(truth))
