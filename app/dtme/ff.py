"""FFmpeg 처리: 분석, 프록시, 필터 체인, 렌더, 스틸, 미리보기, 선명도."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from fractions import Fraction
from pathlib import Path
from typing import Callable

from . import paths
from .project import OUT_FPS, ImageSource, Marker, Project, Segment, Source, layer_box, plan_transitions

NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # Windows 콘솔창 숨김

def denoise_chain(g: dict) -> list[str]:
    """F안: 밝기·색을 따로. 색은 시간축 평균을 강하게 + 색 채널만 미디언(튀는 점 제거).
    hqdn3d 는 0 을 '기본값(4)'으로 처리하므로 0 대신 아주 작은 값."""
    c = max(0.0, min(100.0, float(g.get("nr_chroma", 0))))
    lu = max(0.0, min(100.0, float(g.get("nr_luma", 0))))
    f = []
    if c > 0 or lu > 0:
        ls, lt = max(0.01, lu * 0.04), max(0.01, lu * 0.08)
        cs, ct = max(0.01, c * 0.05), max(0.01, c * 0.133)
        f.append(f"hqdn3d={ls:.2f}:{cs:.2f}:{lt:.2f}:{ct:.2f}")
    if c >= 40:
        f.append(f"median=radius={2 if c >= 85 else 1}:planes=6")
    return f


def sharpen_chain(g: dict) -> list[str]:
    """밝기(Y)에만 언샤프 → 색 노이즈를 날카롭게 만들지 않음."""
    s = float(g.get("sharpen", 0))
    return [f"unsharp=5:5:{min(2.0, s * 2):.3f}:5:5:0"] if s > 1e-3 else []


# RGB → YUV 변환 시 BT.709 를 명시하지 않으면 BT.601 로 변환돼 색이 틀어진다(실측 평균 4.8 → 2.5 차이).
TO_YUV709 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"


class Cancelled(Exception):
    pass


class FFError(Exception):
    pass


# ------------------------------------------------------------------ 실행
def _popen(cmd, **kw):
    return subprocess.Popen(cmd, creationflags=NO_WINDOW, **kw)


def run(cmd: list[str], cwd: str | None = None) -> bytes:
    p = _popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        raise FFError(err.decode("utf-8", "replace")[-2000:])
    return out


def run_progress(cmd: list[str], total_sec: float, on_progress: Callable[[float], None] | None = None,
                 cancel: threading.Event | None = None, cwd: str | None = None) -> None:
    """-progress pipe:1 로 진행률(0~1)을 보고하며 실행."""
    cmd = [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1"] + cmd[1:]
    errf = tempfile.TemporaryFile()
    p = _popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=errf, text=True)
    try:
        for line in p.stdout:
            if cancel is not None and cancel.is_set():
                p.kill()
                raise Cancelled()
            if line.startswith("out_time_us=") and on_progress and total_sec > 0:
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(1.0, us / 1e6 / total_sec))
                except ValueError:
                    pass
        p.wait()
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode != 0:
        errf.seek(0)
        raise FFError(errf.read().decode("utf-8", "replace")[-2000:])
    if on_progress:
        on_progress(1.0)


def replace_retry(src, dst, tries: int = 60) -> None:
    """Windows 에서 백신·색인 등이 방금 만든 파일을 잠깐 잡고 있으면 이름 바꾸기가 WinError 32 로 실패한다 → 재시도."""
    import time
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1 if i < 20 else 0.3)


def log_error(where: str, msg: str) -> None:
    try:
        import time
        with open(paths.cache_dir() / "dtme.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {where}: {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _abs(p) -> str:
    """LUT 때문에 cwd 를 바꾸므로 모든 파일 경로는 절대 경로로."""
    return os.path.abspath(str(p))


def _hw(gpu: bool) -> list[str]:
    return ["-hwaccel", "cuda"] if gpu else []


def _seek(frame: float, fps: Fraction) -> str:
    """프레임 n 을 정확히 잡기 위해 (n-0.5)/fps 로 탐색."""
    return f"{max(0.0, float((Fraction(frame) - Fraction(1, 2)) / fps)):.6f}"


# ------------------------------------------------------------------ 분석
def probe(path: str) -> dict:
    out = run([paths.ffprobe(), "-v", "error", "-print_format", "json",
               "-show_streams", "-show_format", path])
    d = json.loads(out)
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    if v is None:
        raise FFError("영상 스트림이 없습니다.")
    num, den = (int(x) for x in v.get("r_frame_rate", "60000/1001").split("/"))
    anum, aden = (int(x) for x in (v.get("avg_frame_rate") or f"{num}/{den}").split("/"))
    fps = Fraction(num, den)
    dur = float(v.get("duration") or d["format"].get("duration") or 0)
    frames = int(v.get("nb_frames") or 0) or int(round(dur * float(fps)))
    vfr = aden != 0 and abs(float(Fraction(anum, aden)) - float(fps)) > 0.01
    return {
        "fps_num": num, "fps_den": den, "frames": frames,
        "width": int(v["width"]), "height": int(v["height"]),
        "has_audio": any(s.get("codec_type") == "audio" for s in d["streams"]),
        "pix_fmt": v.get("pix_fmt", ""), "codec": v.get("codec_name", ""),
        "vfr": vfr, "duration": dur,
    }


def exif_orientation(path: str) -> int:
    """JPEG EXIF Orientation(1~8). 없거나 읽지 못하면 1. (ffmpeg 은 이 값을 적용하지 않으므로 직접 처리)"""
    import struct
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 1
            while True:
                m = f.read(2)
                if len(m) < 2 or m[0] != 0xFF or m[1] in (0xD9, 0xDA):
                    return 1
                ln = struct.unpack(">H", f.read(2))[0]
                if m[1] != 0xE1:
                    f.seek(ln - 2, 1)
                    continue
                d = f.read(ln - 2)
                if not d.startswith(b"Exif\x00\x00"):
                    continue
                t = d[6:]
                e = "<" if t[:2] == b"II" else ">"
                off = struct.unpack(e + "I", t[4:8])[0]
                n = struct.unpack(e + "H", t[off:off + 2])[0]
                for i in range(n):
                    ent = t[off + 2 + i * 12: off + 14 + i * 12]
                    if struct.unpack(e + "H", ent[:2])[0] == 0x0112:
                        v = struct.unpack(e + "H", ent[8:10])[0]
                        return v if 1 <= v <= 8 else 1
                return 1
    except Exception:  # noqa: BLE001
        return 1


# EXIF 방향 → ffmpeg 필터 (Qt QImageReader.setAutoTransform 과 같은 결과)
ORIENT_FILTER = {1: [], 2: ["hflip"], 3: ["hflip", "vflip"], 4: ["vflip"],
                 5: ["transpose=0"], 6: ["transpose=1"], 7: ["transpose=3"], 8: ["transpose=2"]}


def probe_image(path: str) -> dict:
    """JPG/PNG 크기(방향 반영)·방향."""
    out = run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", path])
    v = next((s for s in json.loads(out)["streams"] if s.get("codec_type") == "video"), None)
    if v is None:
        raise FFError("이미지를 읽을 수 없습니다.")
    w, h = int(v["width"]), int(v["height"])
    o = exif_orientation(path)
    if o >= 5:
        w, h = h, w
    return {"width": w, "height": h, "orient": o}


# ------------------------------------------------------------------ LUT
def lut_ref(name: str) -> tuple[str, str] | None:
    """LUT 를 캐시 폴더에 안전한 이름으로 복사 → (cwd, 파일명). 경로 이스케이프 문제 회피."""
    if not name:
        return None
    src = paths.lut_dir() / name
    if not src.exists():
        raise FFError(f"LUT 파일이 없습니다: {src}")
    d = paths.cache_dir() / "lut"
    d.mkdir(exist_ok=True)
    h = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
    dst = d / f"lut_{h}.cube"
    if not dst.exists():
        shutil.copyfile(src, dst)
    return str(d), dst.name


def list_luts() -> list[str]:
    return sorted(p.name for p in paths.lut_dir().iterdir() if p.suffix.lower() in (".cube", ".3dl"))


# ------------------------------------------------------------------ 필터 체인
def curve_is_identity(curve) -> bool:
    return all(abs(x - y) < 1e-4 for x, y in curve)


def grade_chain(g: dict, lut_file: str | None) -> list[str]:
    """(YUV) 노이즈 → 밝기 샤픈 → (RGB 16bit) LUT → R/B 게인 → 커브 → Hue"""
    f = denoise_chain(g) + sharpen_chain(g)
    f.append("format=gbrp16le")
    if lut_file:
        f.append(f"lut3d=file={lut_file}:interp=tetrahedral")
    r, b = float(g.get("r_gain", 1)), float(g.get("b_gain", 1))
    if abs(r - 1) > 1e-3 or abs(b - 1) > 1e-3:
        f.append(f"colorchannelmixer=rr={r:.4f}:bb={b:.4f}")
    curve = sorted(g.get("curve") or [[0, 0], [1, 1]])
    if not curve_is_identity(curve):
        pts = " ".join(f"{x:.4f}/{y:.4f}" for x, y in curve)
        f.append(f"curves=m='{pts}'")
    hue = float(g.get("hue", 0))
    if abs(hue) > 1e-3:
        f.append(f"huesaturation=hue={hue:.2f}")
    return f


def out_size(orientation: str) -> tuple[int, int]:
    return (1080, 1920) if orientation == "vertical" else (1920, 1080)


def crop_filter(orientation: str) -> str:
    if orientation == "vertical":
        return "crop=w='trunc(min(iw,ih*9/16)/2)*2':h='trunc(min(ih,iw*16/9)/2)*2'"
    return "crop=w='trunc(min(iw,ih*16/9)/2)*2':h='trunc(min(ih,iw*9/16)/2)*2'"


def frame_chain(orientation: str) -> list[str]:
    """화면비 맞춰 중앙 크롭(4K에서) 후 축소."""
    w, h = out_size(orientation)
    return [crop_filter(orientation), f"scale={w}:{h}:flags=lanczos"]


# ------------------------------------------------------------------ 흔들림 보정 (vidstab 2패스)
# 화질 순서: 4K 에서 화면비 크롭 → 출력의 1.25배 크기로 축소 → 흔들림 보정(자동 확대 포함) → 출력 크기로 축소.
# 확대가 일어나도 최종 단계는 항상 '축소'라 업스케일 흐림이 없고, 4K 전체 처리보다 약 4배 빠름.
STAB_OVERSIZE = 1.25


def stab_params(g: dict) -> tuple[int, int] | None:
    v = float(g.get("stab", 0))
    if v <= 0:
        return None
    return int(round(4 + v * 0.06)), int(round(6 + v * 0.30))   # (shakiness 4~10, smoothing 6~36)


def _stab_size(orientation):
    w, h = out_size(orientation)
    return int(w * STAB_OVERSIZE) // 2 * 2, int(h * STAB_OVERSIZE) // 2 * 2


def stab_file(src: Source, seg: Segment, orientation: str, shakiness: int) -> Path:
    key = f"{os.path.abspath(src.path)}|{seg.fin}|{seg.fout}|{orientation}|{shakiness}"
    d = paths.cache_dir() / "lut"       # LUT 와 같은 작업 폴더(cwd) 사용 → 경로 이스케이프 불필요
    d.mkdir(parents=True, exist_ok=True)
    return d / f"stab_{hashlib.sha1(key.encode()).hexdigest()[:12]}.trf"


def stab_detect(src: Source, seg: Segment, orientation: str, shakiness: int, gpu: bool,
                on_progress=None, cancel=None) -> Path:
    trf = stab_file(src, seg, orientation, shakiness)
    if trf.exists() and trf.stat().st_size > 0:
        return trf
    sw, sh = _stab_size(orientation)
    tmp = trf.with_suffix(".part.trf")
    sec = float(Fraction(seg.frames) / src.fps)
    vf = [f"trim=end_frame={seg.frames}", "setpts=PTS-STARTPTS", crop_filter(orientation),
          f"scale={sw}:{sh}:flags=bicubic", f"vidstabdetect=shakiness={shakiness}:accuracy=15:result={tmp.name}"]
    cmd = [paths.ffmpeg(), "-y", *_hw(gpu), "-ss", _seek(seg.fin, src.fps), "-t", f"{sec + 0.5:.6f}",
           "-i", _abs(src.path), "-an", "-vf", ",".join(vf), "-f", "null", "-"]
    try:
        run_progress(cmd, sec, on_progress, cancel, cwd=str(trf.parent))
    except FFError:
        if not gpu:
            raise
        run_progress([c for c in cmd if c not in ("-hwaccel", "cuda")], sec, on_progress, cancel, cwd=str(trf.parent))
    replace_retry(tmp, trf)
    return trf


def _lut_for(g: dict) -> tuple[str | None, str | None]:
    ref = lut_ref(g.get("lut", ""))
    return (ref[0], ref[1]) if ref else (None, None)


# ------------------------------------------------------------------ 프록시
def proxy_path(src_path: str) -> Path:
    st = os.stat(src_path)
    h = hashlib.sha1(f"{os.path.abspath(src_path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]
    d = paths.cache_dir() / "proxy"
    d.mkdir(exist_ok=True)
    return d / f"{Path(src_path).stem}_{h}.mp4"


def make_proxy(src: Source, lut: str, gpu: bool, on_progress=None, cancel=None) -> str:
    """960 폭, 모든 프레임 키프레임(H.264) → 프레임 단위 탐색이 빠름. LUT 를 미리 입혀 보기 좋게."""
    out = proxy_path(src.path)
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    tmp = out.with_suffix(".part.mp4")
    ref = lut_ref(lut) if lut else None
    vf = ["scale=960:-2:flags=bilinear"]
    if ref:
        vf += ["format=gbrp16le", f"lut3d=file={ref[1]}"]
    vf += [TO_YUV709]
    cmd = [paths.ffmpeg(), "-y", *_hw(gpu), "-i", _abs(src.path), "-map", "0:v:0"]
    if src.has_audio:
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-vf", ",".join(vf), "-fps_mode", "passthrough",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
            "-g", "1", "-crf", "23", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", _abs(tmp)]
    try:
        run_progress(cmd, src.frames / float(src.fps), on_progress, cancel, cwd=ref[0] if ref else None)
    except FFError:
        if not gpu:
            raise
        # GPU 디코딩 실패 시 CPU 로 재시도
        cmd = [c for c in cmd if c not in ("-hwaccel", "cuda")]
        run_progress(cmd, src.frames / float(src.fps), on_progress, cancel, cwd=ref[0] if ref else None)
    replace_retry(tmp, out)
    return str(out)


# ------------------------------------------------------------------ 미리보기용 프레임 캐시
def cached_frame(src: Source, frame: int, gpu: bool = False) -> str:
    """원본에서 해당 프레임을 1280 폭 10bit 무손실(ffv1)로 저장 → 보정 미리보기 입력."""
    d = paths.cache_dir() / "frames"
    d.mkdir(exist_ok=True)
    out = d / f"{src.id}_{frame}.mkv"
    with _frame_locks.setdefault(out.name, threading.Lock()):   # 같은 프레임 동시 생성 방지
        if out.exists():
            return str(out)
        tmp = d / f"{src.id}_{frame}.{threading.get_ident()}.part.mkv"
        run([paths.ffmpeg(), "-v", "error", "-y", *_hw(gpu), "-ss", _seek(frame, src.fps), "-i", _abs(src.path),
             "-frames:v", "1", "-an", "-vf", "scale=1280:-2:flags=lanczos,format=yuv420p10le",
             "-c:v", "ffv1", str(tmp)])
        replace_retry(tmp, out)
    return str(out)


_frame_locks: dict[str, threading.Lock] = {}


def render_preview(cached: str, g: dict | None) -> bytes:
    """보정 적용 결과를 PNG 바이트로. g=None 이면 보정 전(원본 Log)."""
    cwd, lut = (None, None)
    if g is None:
        vf = ["format=rgb24"]
    else:
        cwd, lut = _lut_for(g)
        vf = grade_chain(g, lut) + ["format=rgb24"]
    return run([paths.ffmpeg(), "-v", "error", "-i", _abs(cached), "-frames:v", "1",
                "-vf", ",".join(vf), "-f", "image2pipe", "-c:v", "png", "-"], cwd=cwd)


# ------------------------------------------------------------------ 선명도
def sharpness_around(src: Source, frame: int, radius: int = 5) -> list[tuple[int, float]]:
    import numpy as np
    start = max(0, frame - radius)
    n = min(src.frames, frame + radius + 1) - start
    w, h = 960, 540
    raw = run([paths.ffmpeg(), "-v", "error", "-ss", _seek(start, src.fps), "-i", src.path,
               "-frames:v", str(n), "-an", "-vf", f"scale={w}:{h},format=gray",
               "-f", "rawvideo", "-"])
    arr = np.frombuffer(raw, np.uint8)
    cnt = len(arr) // (w * h)
    res = []
    for i in range(cnt):
        im = arr[i * w * h:(i + 1) * w * h].reshape(h, w).astype(np.float32)
        lap = (-4 * im[1:-1, 1:-1] + im[:-2, 1:-1] + im[2:, 1:-1] + im[1:-1, :-2] + im[1:-1, 2:])
        res.append((start + i, float(lap.var())))
    return res


# ------------------------------------------------------------------ 화면 전환
XFADE = {"dissolve": "fade", "wipeleft": "wipeleft", "wiperight": "wiperight", "wipeup": "wipeup",
         "wipedown": "wipedown", "zoomin": "fade", "zoomout": "fade", "rotzoomin": "fade", "rotzoomout": "fade",
         "fadeblack": "fadeblack", "fadewhite": "fadewhite"}
ROT_MAX = 0.5236     # 회전 최대 30°


def zoom_filter(kind: str, start: float, dur: float, head: bool) -> str:
    """빠른 줌·회전 줌: perspective(프레임마다 계산, 3차 보간, 크기 고정).
    u = 0→1 가속(제곱). 배율 s = 1+2u, 각도 = u·30° → 확대가 항상 회전보다 커서 화면 밖(검은 모서리)이 보이지 않음.
    tail(앞 컷 끝): start~start+dur 동안 확대(회전). head(뒷 컷 시작): 0~dur 동안 확대 상태에서 원래로."""
    fps = float(OUT_FPS)
    if head:
        u = f"pow(1-clip(in/{fps:.5f}/{dur:.5f},0,1),2)"
        en = f"lte(t,{dur + 0.5 / fps:.5f})"
        sign = -1
    else:
        u = f"pow(clip((in/{fps:.5f}-{start:.5f})/{dur:.5f},0,1),2)"
        en = f"gte(t,{start - 0.5 / fps:.5f})"
        sign = 1
    sc = f"(1+2*{u})"
    th = f"({sign}*{u}*{ROT_MAX})" if kind.startswith("rot") else "0"

    def pt(dx, dy):     # 출력 모서리 ← 원본 좌표: 중심 + R(θ)(모서리-중심)/s
        return (f"W/2+(({dx})*cos({th})-({dy})*sin({th}))/{sc}",
                f"H/2+(({dx})*sin({th})+({dy})*cos({th}))/{sc}")
    xy = [pt(dx, dy) for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:interpolation=cubic:eval=frame:enable='{en}'"


def transition_graph(fparts: list, plan: list, lens: list, audio: bool) -> float:
    """[v0][a0]… 를 화면 전환(xfade/acrossfade)과 이어붙이기(concat)로 연결 → [vo][ao]. 결과 길이(초) 반환."""
    n = len(lens)
    vl = [f"[v{i}]" for i in range(n)]
    al = [f"[a{i}]" for i in range(n)]
    for i in range(n):                       # 컷 자체에 들어가는 효과(줌·첫 컷 페이드)
        f = []
        nxt = plan[i + 1] if i + 1 < n else None
        if nxt and nxt[0] in ("zoomin", "rotzoomin"):
            f.append(zoom_filter(nxt[0], lens[i] - nxt[1], nxt[1], head=False))
        cur = plan[i]
        if cur and i > 0 and cur[0] in ("zoomout", "rotzoomout"):
            f.append(zoom_filter(cur[0], 0, cur[1], head=True))
        if cur and i == 0:
            f.append(f"fade=t=in:st=0:d={cur[1]:.5f}:color={'white' if cur[0] == 'fadewhite' else 'black'}")
            if audio:
                fparts.append(f"[a0]afade=t=in:st=0:d={cur[1]:.5f}[a0f]")
                al[0] = "[a0f]"
        f.append("settb=AVTB")
        fparts.append(f"{vl[i]}{','.join(f)}[w{i}]")
        vl[i] = f"[w{i}]"
    acc_v, acc_a, acc = vl[0], al[0], lens[0]
    for i in range(1, n):
        last = i == n - 1
        ov, oa = ("[vo]", "[ao]") if last else (f"[xv{i}]", f"[xa{i}]")
        t = plan[i]
        if t:
            d = t[1]
            fparts.append(f"{acc_v}{vl[i]}xfade=transition={XFADE[t[0]]}:duration={d:.5f}:offset={acc - d:.5f}{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}acrossfade=d={d:.5f}{oa}")
            acc += lens[i] - d
        else:
            fparts.append(f"{acc_v}{vl[i]}concat=n=2:v=1:a=0{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}concat=n=2:v=0:a=1{oa}")
            acc += lens[i]
        acc_v, acc_a = ov, oa
    if n == 1:
        fparts.append(f"{acc_v}null[vo]")
        if audio:
            fparts.append(f"{acc_a}anull[ao]")
    return acc


# ------------------------------------------------------------------ 영상 렌더
YUV444_709 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p10le"
OV_CONVERT = "out_color_matrix=bt709:out_range=tv"


def seg_layers(project: Project, seg: Segment) -> list[tuple[dict, ImageSource, int, int]]:
    """컷 범위 안으로 자른 레이어 [(layer, image, fin, fout)]. 이미지 파일이 없으면 건너뜀."""
    out = []
    for lay in seg.layers:
        img = project.image(lay.get("img", ""))
        if img is None or not img.width or not os.path.exists(img.path):
            continue
        lf, lo = max(seg.fin, int(lay["fin"])), min(seg.fout, int(lay["fout"]))
        if lo > lf:
            out.append((lay, img, lf, lo))
    return out


def build_render_cmd(project: Project, segs: list[Segment], out_file: str, orientation: str | None = None,
                     audio: bool | None = None) -> tuple[list[str], float, str | None]:
    o = project.output
    orientation = orientation or o.orientation
    audio = o.audio if audio is None else audio
    cmd = [paths.ffmpeg(), "-y"]
    fparts, labels = [], []
    total = 0.0
    cwd = None
    img_inputs: list[str] = []          # 이미지 입력은 영상 입력 뒤에 붙임(번호 = len(segs) + k)
    lens: list[float] = []
    for i, seg in enumerate(segs):
        src = project.source(seg.src)
        g = project.grade_for_source(src.id)
        lcwd, lut = _lut_for(g)
        cwd = cwd or lcwd
        seg_src_sec = float(Fraction(seg.frames) / src.fps)
        out_sec = seg_src_sec / seg.speed
        total += out_sec
        cmd += [*_hw(o.gpu_decode), "-ss", _seek(seg.fin, src.fps), "-t", f"{seg_src_sec + 0.5:.6f}", "-i", _abs(src.path)]
        v = [f"trim=end_frame={seg.frames}", "setpts=PTS-STARTPTS"]
        sp = stab_params(g)
        if sp:
            sw, sh = _stab_size(orientation)
            ow, oh = out_size(orientation)
            trf = stab_file(src, seg, orientation, sp[0])
            v += [crop_filter(orientation), f"scale={sw}:{sh}:flags=lanczos",
                  f"vidstabtransform=input={trf.name}:smoothing={sp[1]}:optzoom=1:interpol=bicubic",
                  f"scale={ow}:{oh}:flags=lanczos"]
            cwd = str(trf.parent)
        if seg.speed != 1.0:
            v.append(f"setpts=PTS/{seg.speed}")
        v.append(f"fps={OUT_FPS.numerator}/{OUT_FPS.denominator}")
        if not sp:
            v += frame_chain(orientation)
        v += grade_chain(g, lut)
        lays = seg_layers(project, seg)
        if not lays:
            v += [TO_YUV709, "setsar=1"]
            fparts.append(f"[{i}:v:0]{','.join(v)}[v{i}]")
        else:
            # 보정 끝난 화면에 이미지 합성(보정 없음). 10bit 4:4:4 에서 합성 후 4:2:0 으로만 바꿈(행렬 재변환 없음)
            v.append(YUV444_709)
            fparts.append(f"[{i}:v:0]{','.join(v)}[b{i}_0]")
            ow, oh = out_size(orientation)
            e = 0.25 / float(OUT_FPS)
            for k, (lay, img, lf, lo) in enumerate(lays):
                ii = len(segs) + len(img_inputs)
                img_inputs.append(_abs(img.path))
                x, y, w, h = layer_box(lay, img, ow, oh)
                pre = ORIENT_FILTER.get(img.orient, [])
                fparts.append(f"[{ii}:v:0]{','.join(pre + [f'scale=w={w}:h={h}:flags=lanczos:{OV_CONVERT}', 'format=yuva444p10le'])}[l{i}_{k}]")
                t0 = float(Fraction(lf - seg.fin) / src.fps / Fraction(seg.speed)) - e
                t1 = float(Fraction(lo - seg.fin) / src.fps / Fraction(seg.speed)) - e
                fparts.append(f"[b{i}_{k}][l{i}_{k}]overlay=x={x}:y={y}:format=yuv444p10:eof_action=repeat"
                              f":enable='between(t,{t0:.6f},{t1:.6f})'[b{i}_{k + 1}]")
            fparts.append(f"[b{i}_{len(lays)}]format=yuv420p,setsar=1[v{i}]")
        lab = f"[v{i}]"
        if audio:
            if src.has_audio:
                a = [f"atrim=duration={seg_src_sec:.6f}", "asetpts=PTS-STARTPTS"]
                if seg.speed != 1.0:
                    a.append(f"atempo={seg.speed}")
                a.append("aresample=48000")
                fparts.append(f"[{i}:a:0]{','.join(a)}[a{i}]")
            else:
                fparts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={out_sec:.6f}[a{i}]")
            lab += f"[a{i}]"
        labels.append(lab)
        lens.append(out_sec)
    for f in img_inputs:
        cmd += ["-noautorotate", "-i", f]      # EXIF 회전은 ORIENT_FILTER 로 직접(ffmpeg 버전마다 자동 적용 여부가 다름)
    n = len(segs)
    plan = plan_transitions(segs, lens)
    if not any(plan):
        if audio:
            fparts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[vo][ao]")
        else:
            fparts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[vo]")
    else:
        total = transition_graph(fparts, plan, lens, audio)
    cmd += ["-filter_complex", ";".join(fparts), "-map", "[vo]"]
    if audio:
        cmd += ["-map", "[ao]", "-c:a", "aac", "-b:a", "192k"]
    br = int(o.bitrate_mbps)
    if o.encoder == "nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19",
                "-b:v", f"{br}M", "-maxrate", f"{int(br * 1.5)}M", "-bufsize", f"{br * 2}M", "-profile:v", "high"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-maxrate", f"{int(br * 1.5)}M", "-bufsize", f"{br * 2}M"]
    cmd += ["-pix_fmt", "yuv420p", "-r", f"{OUT_FPS.numerator}/{OUT_FPS.denominator}",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
            "-map_metadata", "-1", "-write_tmcd", "0", "-movflags", "+faststart", _abs(out_file)]
    # 모든 LUT 는 같은 캐시 폴더에 있으므로 cwd 하나로 충분
    return cmd, total, cwd


def render_video(project: Project, segs: list[Segment], out_file: str, on_progress=None, cancel=None,
                 orientation: str | None = None, audio: bool | None = None) -> None:
    orient = orientation or project.output.orientation
    gpu = project.output.gpu_decode
    # 1패스: 흔들림 분석(필요한 컷만, 결과 캐시). 진행률 앞 40%
    todo = []
    for seg in segs:
        src = project.source(seg.src)
        sp = stab_params(project.grade_for_source(src.id))
        if sp and not stab_file(src, seg, orient, sp[0]).exists():
            todo.append((src, seg, sp[0]))
    share = 0.4 if todo else 0.0
    for k, (src, seg, shk) in enumerate(todo):
        def sub(v, k=k):
            if on_progress:
                on_progress(share * (k + v) / len(todo))
        stab_detect(src, seg, orient, shk, gpu, sub, cancel)
    outer = on_progress
    on_progress = (lambda v: outer(share + (1 - share) * v)) if outer else None
    cmd, total, cwd = build_render_cmd(project, segs, out_file, orientation, audio)
    try:
        run_progress(cmd, total, on_progress, cancel, cwd=cwd)
    except FFError:
        if not project.output.gpu_decode:
            raise
        cmd = [c for c in cmd if c not in ("-hwaccel", "cuda")]
        run_progress(cmd, total, on_progress, cancel, cwd=cwd)


# ------------------------------------------------------------------ 스틸 (4K 원본)
# 스틸 파일 색 태그 = sRGB. 그대로 두면 BT.709 전달 특성(cICP·gAMA 1/1.96)이 기록되어
# Windows 사진 앱 등 색 관리 뷰어가 더 어둡고 진하게 표시한다(픽셀 값은 프리뷰와 같음, 실측 평균 차 1.4/255).
SRGB_TAG = "setparams=color_trc=iec61966-2-1:color_primaries=bt709:colorspace=gbr"


def export_still(src: Source, frame: int, g: dict, out_file: str, gpu: bool = False) -> None:
    """원본 4K 프레임에 보정 적용 → 16bit PNG(.png) 또는 TIFF(.tif).
    앞 3프레임을 함께 넣어 시간축 노이즈 제거가 동작하게 하고 마지막 프레임만 저장."""
    cwd, lut = _lut_for(g)
    lead = min(3, frame)
    start = frame - lead
    is_png = str(out_file).lower().endswith(".png")
    vf = grade_chain(g, lut) + [SRGB_TAG, "format=rgb48be" if is_png else "format=rgb48le"]
    codec = ["-c:v", "png", "-compression_level", "3"] if is_png else ["-c:v", "tiff", "-compression_algo", "deflate"]
    cmd = [paths.ffmpeg(), "-v", "error", "-y", *_hw(gpu), "-ss", _seek(start, src.fps), "-i", _abs(src.path),
           "-frames:v", str(lead + 1), "-an", "-vf", ",".join(vf), "-update", "1", *codec, _abs(out_file)]
    try:
        run(cmd, cwd=cwd)
    except FFError:
        if not gpu:
            raise
        run([c for c in cmd if c not in ("-hwaccel", "cuda")], cwd=cwd)


def render_still(project: Project, still: Marker, out_file: str, gpu: bool = False) -> None:
    export_still(project.source(still.src), still.frame, project.grade_for_still(still), out_file, gpu)


# ------------------------------------------------------------------ 프록시 프레임 (드래그·이동 시 즉시 표시)
def grab_proxy_frame(proxy: str, fps: Fraction, frame: int) -> bytes:
    """전 프레임 키프레임 프록시라 한 장 디코딩이 빠름(수십 ms)."""
    return run([paths.ffmpeg(), "-v", "error", "-ss", _seek(frame, fps), "-i", _abs(proxy), "-frames:v", "1",
                "-an", "-f", "image2pipe", "-c:v", "bmp", "-pix_fmt", "bgr24", "-"])
