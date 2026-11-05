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
from .project import OUT_FPS, Marker, Project, Segment, Source

NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # Windows 콘솔창 숨김

NR_PARAMS = {
    "weak": "hqdn3d=1.5:1.5:3:3",
    "mid": "hqdn3d=3:2.5:5:4",
    "strong": "hqdn3d=4.5:3.5:7:6",
}


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
    """노이즈 → (RGB 16bit) LUT → R/B 게인 → 커브 → Hue → 샤픈"""
    f = []
    nr = g.get("nr", "off")
    if nr in NR_PARAMS:
        f.append(NR_PARAMS[nr])
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
    s = float(g.get("sharpen", 0))
    if s > 1e-3:
        f.append(f"cas=strength={min(1.0, s):.3f}")
    return f


def frame_chain(orientation: str) -> list[str]:
    """화면비 맞춰 중앙 크롭 후 축소."""
    if orientation == "vertical":
        w, h, ar = 1080, 1920, "9/16"
        crop = "crop=w='trunc(min(iw,ih*9/16)/2)*2':h='trunc(min(ih,iw*16/9)/2)*2'"
    else:
        w, h, ar = 1920, 1080, "16/9"
        crop = "crop=w='trunc(min(iw,ih*16/9)/2)*2':h='trunc(min(ih,iw*9/16)/2)*2'"
    return [crop, f"scale={w}:{h}:flags=lanczos"]


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
    tmp.replace(out)
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
        os.replace(tmp, out)
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


# ------------------------------------------------------------------ 영상 렌더
def build_render_cmd(project: Project, segs: list[Segment], out_file: str, orientation: str | None = None,
                     audio: bool | None = None) -> tuple[list[str], float, str | None]:
    o = project.output
    orientation = orientation or o.orientation
    audio = o.audio if audio is None else audio
    cmd = [paths.ffmpeg(), "-y"]
    fparts, labels = [], []
    total = 0.0
    cwd = None
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
        if seg.speed != 1.0:
            v.append(f"setpts=PTS/{seg.speed}")
        v.append(f"fps={OUT_FPS.numerator}/{OUT_FPS.denominator}")
        v += frame_chain(orientation)
        v += grade_chain(g, lut)
        v += [TO_YUV709, "setsar=1"]
        fparts.append(f"[{i}:v:0]{','.join(v)}[v{i}]")
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
    n = len(segs)
    if audio:
        fparts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[vo][ao]")
    else:
        fparts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[vo]")
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
    cmd, total, cwd = build_render_cmd(project, segs, out_file, orientation, audio)
    try:
        run_progress(cmd, total, on_progress, cancel, cwd=cwd)
    except FFError:
        if not project.output.gpu_decode:
            raise
        cmd = [c for c in cmd if c not in ("-hwaccel", "cuda")]
        run_progress(cmd, total, on_progress, cancel, cwd=cwd)


# ------------------------------------------------------------------ 스틸 (4K 원본)
def export_still(src: Source, frame: int, g: dict, out_file: str, gpu: bool = False) -> None:
    """원본 4K 프레임에 보정 적용 → 16bit PNG(.png) 또는 TIFF(.tif).
    앞 3프레임을 함께 넣어 시간축 노이즈 제거가 동작하게 하고 마지막 프레임만 저장."""
    cwd, lut = _lut_for(g)
    lead = min(3, frame)
    start = frame - lead
    is_png = str(out_file).lower().endswith(".png")
    vf = grade_chain(g, lut) + ["format=rgb48be" if is_png else "format=rgb48le"]
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
