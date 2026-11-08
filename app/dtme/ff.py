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
from .project import (KEYABLE, OUT_FPS, ImageSource, Marker, Project, Segment, Source, apply_off, grade_at, layer_box,
                      orig_volume, plan_transitions, reframe_max)

NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # Windows 콘솔창 숨김
LOW_PRIO = 0x00004000 if os.name == "nt" else 0    # BELOW_NORMAL_PRIORITY_CLASS: 크롬·에펙을 같이 써도 그쪽이 먼저(v0.16.14)

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


def sharpen_chain(g: dict, width: int = 1920) -> list[str]:
    """밝기(Y)에만 언샤프 → 색 노이즈를 날카롭게 만들지 않음.
    디헤이즈는 v0.16.2 에서 뺌: unsharp 가 10bit 에서 효과를 몇 단계 정수로만 더해 완만한 물빛에 계단(실측 7.8/255)을 만들었음.
    옛 프로젝트의 dehaze 값은 무시."""
    f = []
    s = float(g.get("sharpen", 0))
    if s > 1e-3:
        f.append(f"unsharp=5:5:{min(2.0, s * 2):.3f}:5:5:0")
    return f


LENS_K1 = 0.15      # 렌즈 보정 100 일 때 왜곡 계수(+ = 외곽을 안쪽으로 당김)


def lens_zoom(g: dict) -> float:
    v = float(g.get("lens", 0))
    return 1.0 + LENS_K1 * v / 100 if v >= 0.5 else 1.0


def lens_chain(g: dict, w: int = 0, h: int = 0) -> list[str]:
    """액션캠 외곽 늘어짐 줄이기(원본 크기에서, 크롭·축소 전). 외곽을 안쪽으로 당기고(k1 > 0),
    생기는 검은 모서리는 가운데를 1+k1 배로 살짝 확대해 잘라냄. w·h = 들어오는 화면 크기(정확히 원래 크기로 되돌림).
    v0.15.3 까지는 반대 방향(k1 < 0, 외곽을 더 늘림)이었음 — 사용자 지적으로 수정(격자 실측)."""
    v = float(g.get("lens", 0))
    if v < 0.5:
        return []
    k1 = LENS_K1 * v / 100
    z = 1.0 + k1                          # 크롭 모서리 r0/z → 원본 r0(1+k1/z²)/z < r0 : 검은 부분 없음
    f = [f"lenscorrection=k1={k1:.4f}:k2=0:i=bilinear"]
    if w and h:
        cw, ch = int(w / z) // 2 * 2, int(h / z) // 2 * 2
        f += [f"crop={cw}:{ch}:{(w - cw) // 2}:{(h - ch) // 2}", f"scale={w}:{h}:flags=bicubic"]
    else:
        f += [f"crop=trunc(iw/{z:.5f}/2)*2:trunc(ih/{z:.5f}/2)*2", f"scale=iw*{z:.5f}:ih*{z:.5f}:flags=bicubic"]
    return f


# RGB → YUV 변환 시 BT.709 를 명시하지 않으면 BT.601 로 변환돼 색이 틀어진다(실측 평균 4.8 → 2.5 차이).
TO_YUV709 = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"


class Cancelled(Exception):
    pass


class FFError(Exception):
    pass


# ------------------------------------------------------------------ 실행
def _popen(cmd, **kw):
    """ffmpeg 이 키 입력(stdin)을 기다리며 멈추는 일 방지(Windows GUI 에서 렌더가 멈추던 원인): -nostdin + 입력 차단."""
    cmd = list(cmd)
    if Path(cmd[0]).stem.lower() == "ffmpeg" and "-nostdin" not in cmd:
        cmd.insert(1, "-nostdin")
    kw.setdefault("stdin", subprocess.DEVNULL)
    import time
    for i in range(12):      # WinError 32(백신이 ffmpeg.exe 를 잠깐 잡음 등) → 0.2초 간격 다시 시도. 화면에 '미리보기 오류'가 자주 뜨던 원인
        try:
            return subprocess.Popen(cmd, creationflags=NO_WINDOW | LOW_PRIO, **kw)
        except OSError as e:
            if getattr(e, "winerror", None) not in (32, 33) or i == 11:
                raise
            time.sleep(0.2)


def run(cmd: list[str], cwd: str | None = None, data: bytes | None = None) -> bytes:
    """data 가 있으면 stdin 으로 넘김(미리보기: 디스크 파일 없이)."""
    if data is not None:
        cmd = [c for c in cmd]
        p = _popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(data)
    else:
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


def log_info(msg: str) -> None:
    """속도 기록 등(cache/dtme.log)."""
    log_error("정보", msg)


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
        "color_mode": dji_color_mode(path, d),
    }


# ------------------------------------------------------------------ DJI 메타(djmd)로 색 모드 판단
def _pb_fields(b: bytes, path: str = "", depth: int = 0, out: dict | None = None) -> dict | None:
    """protobuf(이름 없는 필드) → {'.2.5.1': 값, …} 첫 값만. 형식이 안 맞으면 None."""
    out = {} if out is None else out
    i = 0
    try:
        while i < len(b):
            key, i = _pb_varint(b, i)
            fn, wt = key >> 3, key & 7
            if fn == 0 or fn > 2000:
                return None
            k = f"{path}.{fn}"
            if wt == 0:
                v, i = _pb_varint(b, i)
                out.setdefault(k, v)
            elif wt == 1:
                i += 8
            elif wt == 5:
                i += 4
            elif wt == 2:
                ln, i = _pb_varint(b, i)
                sub = b[i:i + ln]
                i += ln
                if depth < 5 and ln and _pb_fields(sub, k, depth + 1, dict()) is not None:
                    _pb_fields(sub, k, depth + 1, out)
                else:
                    out.setdefault(k, sub)
            else:
                return None
            if i > len(b):
                return None
        return out
    except IndexError:
        return None


def _pb_varint(b: bytes, i: int):
    r = sh = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << sh
        sh += 7
        if x < 0x80:
            return r, i


def dji_color_mode(path: str, info: dict | None = None) -> str:
    """'dlog' | 'normal' | 'unknown'. DJI 영상의 djmd 첫 패킷(0.1초 안팎)에서 필드 .2.5.1(2 = D-Log M, 1 = 일반).
    사용자 액션4 파일 2개로 찾은 필드: .1.9.1(5/1) · .2.3.5(10/8 bit)도 같은 방향 → 엇갈리면 unknown.
    DJI 가 아니거나 못 읽으면 unknown(→ LUT 없음, 사용자 2026-11-06)."""
    try:
        if info is None:
            info = json.loads(run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]))
        enc = str((info.get("format", {}).get("tags") or {}).get("encoder", ""))
        st = next((x for x in info.get("streams", []) if x.get("codec_tag_string") == "djmd"), None)
        if st is None or "DJI" not in enc.upper():
            return "unknown"
        txt = run([paths.ffprobe(), "-v", "error", "-select_streams", str(st["index"]), "-show_packets", "-show_data",
                   "-read_intervals", "%+#1", _abs(path)]).decode("utf-8", "replace")
        import re
        m = re.search(r"data=\s*\n(.*?)\[/PACKET\]", txt, re.S)
        if not m:
            return "unknown"
        hexs = "".join(re.findall(r"^[0-9a-f]{8}: ((?:[0-9a-f]{2,4} ?){1,8})", m.group(1), re.M)).replace(" ", "")   # 홀수 바이트 = 끝 묶음 2자리
        f = _pb_fields(bytes.fromhex(hexs)) or {}
        mode = f.get(".2.5.1")
        if mode == 2 and f.get(".1.9.1", 5) != 1:
            return "dlog"
        if mode == 1 and f.get(".1.9.1", 1) != 5:
            return "normal"
        return "unknown"
    except Exception as e:  # noqa: BLE001
        log_error(f"색 모드 {path}", str(e)[-200:])
        return "unknown"


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
    _safe_copy(src, dst)
    return str(d), dst.name


_copy_lock = threading.Lock()


def _safe_copy(src, dst) -> None:
    """작업 폴더로 복사(여러 작업이 동시에 같은 파일을 쓰면 반쯤 써진 파일을 읽어 실패 → 잠금 + 임시 파일 → 이름 바꾸기).
    AUTO 분석·프록시·미리보기가 동시에 시작될 때 '분석 실패'가 나던 원인."""
    dst = Path(dst)
    with _copy_lock:
        if dst.exists() and dst.stat().st_size == Path(src).stat().st_size:
            return
        tmp = dst.with_name(dst.name + f".{threading.get_ident()}.part")
        shutil.copyfile(src, tmp)
        replace_retry(tmp, dst)


def list_luts() -> list[str]:
    return sorted(p.name for p in paths.lut_dir().iterdir() if p.suffix.lower() in (".cube", ".3dl"))


# ------------------------------------------------------------------ 필터 체인
def curve_is_identity(curve) -> bool:
    return all(abs(x - y) < 1e-4 for x, y in curve)


# 물빛 = 청록·녹색 범위만 색상 회전(+ = 파랑 쪽), 녹황 = 녹·황 범위만 채도 감소. 피부·산호(주황)는 거의 그대로(실측)
WATER_OPT = "colors=c+g:strength=2"
GY_OPT = "colors=g+y:strength=1.5"


def grade_chain(g: dict, lut_file: str | None, width: int = 1920, named: bool = False) -> list[str]:
    """(YUV) 노이즈 → 밝기 샤픈·디헤이즈 → (RGB 16bit) LUT → R/B 게인 → 커브 → Hue → 채도
    named = 색 키프레임용: 게인·Hue·채도 필터를 항상 넣고 이름(@g)을 붙임 → sendcmd 로 프레임마다 값 변경."""
    if named:
        return _grade_named(g, lut_file, width)
    f = denoise_chain(g) + sharpen_chain(g, width)
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
    wt, gy = float(g.get("water", 0)), float(g.get("gy", 0))
    if abs(wt) > 1e-3:
        f.append(f"huesaturation={WATER_OPT}:hue={wt:.2f}")
    if gy > 1e-3:
        f.append(f"huesaturation={GY_OPT}:saturation={-gy / 100:.4f}")
    sat = float(g.get("sat", 1.0))
    if abs(sat - 1) > 1e-3:
        f.append(f"vibrance=intensity={max(-2.0, min(2.0, sat - 1)):.3f}")
    f += wnr_mark(g, width)
    return f


# ------------------------------------------------------------------ 물 노이즈: 파란 영역의 붉은 색 노이즈만 정리
WNR = "§wnr:"


def wnr_mark(g: dict, width: int) -> list[str]:
    """체인 안 표시(나중에 graph() 가 갈래 그래프로 바꿈). 0 이면 없음."""
    w = float(g.get("wnr", 0))
    return [f"{WNR}{w:.1f}:{int(width)}"] if w > 0.5 else []


def wnr_graph(mark: str, inlab: str, outlab: str, uid: str) -> list[str]:
    """[in] → 원본 / 색만 흐리게 + 빨강·자주 채도 낮춤 / 파란 영역 지도(넓게 흐린 B−R) → 지도만큼 섞음 → [out].
    밝기(Y)는 그대로라 디테일은 안 뭉개짐. 빨간 피사체(산호·거북이) 위치는 지도 값이 0 이라 그대로(실측)."""
    w, width = (float(x) for x in mark[len(WNR):].split(":"))
    k = width / 1920
    sc = max(1.0, (2 + 8 * w / 100) * k)          # 색 흐림 정도
    sm = max(4.0, 24 * k)                          # 파란 영역 지도의 넓이
    gain = min(2.0, 1.4 * w / 80)                  # 지도 세기
    desat = -min(1.0, 0.85 * w / 80)
    o, c, m, cb, mk = (f"[wn{uid}{x}]" for x in ("o", "c", "m", "cb", "mk"))
    return [f"{inlab}format=gbrp16le,split=3{o}{c}{m}",
            f"{c}scale=out_color_matrix=bt709:out_range=pc,format=yuv444p16le,gblur=sigma={sc:.2f}:planes=6,"
            f"scale=in_color_matrix=bt709:in_range=pc,format=gbrp16le,huesaturation=colors=r+m:saturation={desat:.3f}:strength=2{cb}",
            f"{m}gblur=sigma={sm:.1f},colorchannelmixer=rr=-2:rb=2:gr=-2:gb=2:br=-2:bb=2,"
            f"colorchannelmixer=rr={gain:.3f}:gg={gain:.3f}:bb={gain:.3f}{mk}",
            f"{o}{cb}{mk}maskedmerge{outlab}"]


def graph(chain: list[str], inlab: str, outlab: str, uid: str = "0") -> str:
    """필터 목록 → filter_complex 문자열. 물 노이즈 표시가 있으면 그 자리에서 갈래 그래프로."""
    parts, cur, seg, k = [], inlab, [], 0
    for f in chain:
        if f.startswith(WNR):
            lab = f"[wa{uid}_{k}]"
            parts.append(f"{cur}{','.join(seg) or 'null'}{lab}")
            nxt = f"[wb{uid}_{k}]"
            parts += wnr_graph(f, lab, nxt, f"{uid}_{k}")
            cur, seg, k = nxt, [], k + 1
        else:
            seg.append(f)
    parts.append(f"{cur}{','.join(seg) or 'null'}{outlab}")
    return ";".join(parts)


def _grade_named(g, lut_file, width):
    f = denoise_chain(g) + sharpen_chain(g, width) + ["format=gbrp16le"]
    if lut_file:
        f.append(f"lut3d=file={lut_file}:interp=tetrahedral")
    f.append(f"colorchannelmixer@g=rr={float(g.get('r_gain', 1)):.4f}:bb={float(g.get('b_gain', 1)):.4f}")
    curve = sorted(g.get("curve") or [[0, 0], [1, 1]])
    if not curve_is_identity(curve):
        f.append(f"curves=m='{' '.join(f'{x:.4f}/{y:.4f}' for x, y in curve)}'")
    f.append(f"huesaturation@g=hue={float(g.get('hue', 0)):.2f}")
    f.append(f"huesaturation@w={WATER_OPT}:hue={float(g.get('water', 0)):.2f}")
    f.append(f"huesaturation@y={GY_OPT}:saturation={-float(g.get('gy', 0)) / 100:.4f}")
    f.append(f"vibrance@g=intensity={max(-2.0, min(2.0, float(g.get('sat', 1)) - 1)):.3f}")
    return f + wnr_mark(g, width)


def has_gkeys(seg) -> bool:
    return any(seg.gkeys.get(k) for k in KEYABLE) if getattr(seg, "gkeys", None) else False


def gkey_cmds(g: dict, seg: Segment, src: Source, n_out: int, frames_per_sec: float) -> str:
    """sendcmd 명령: 출력 프레임마다 색 키프레임 보간값(바뀔 때만)."""
    lines, last = [], None
    for n in range(n_out):
        t = n / float(OUT_FPS)
        v = apply_off(grade_at(g, seg.gkeys, seg.fin + t * frames_per_sec), getattr(seg, "off", None))
        cur = (round(v["r_gain"], 4), round(v["b_gain"], 4), round(v["hue"], 2), round(max(-2, min(2, v["sat"] - 1)), 3),
               round(float(v.get("water", 0)), 2), round(-float(v.get("gy", 0)) / 100, 4))
        if cur == last:
            continue
        last = cur
        lines.append(f"{max(0.0, t - 0.25 / float(OUT_FPS)):.6f} [enter] colorchannelmixer@g rr {cur[0]}, "
                     f"colorchannelmixer@g bb {cur[1]}, huesaturation@g hue {cur[2]}, vibrance@g intensity {cur[3]}, "
                     f"huesaturation@w hue {cur[4]}, huesaturation@y saturation {cur[5]};")
    return "\n".join(lines) + "\n"


def out_size(orientation: str) -> tuple[int, int]:
    return {"vertical": (1080, 1920), "horizontal1440": (2560, 1440), "horizontal2160": (3840, 2160),
            "preview": (960, 540), "preview_v": (540, 960)}.get(orientation, (1920, 1080))


def is_vertical(orientation: str) -> bool:
    return orientation in ("vertical", "preview_v")


def crop_filter(orientation: str) -> str:
    if is_vertical(orientation):
        return "crop=w='trunc(min(iw,ih*9/16)/2)*2':h='trunc(min(ih,iw*16/9)/2)*2'"
    return "crop=w='trunc(min(iw,ih*16/9)/2)*2':h='trunc(min(ih,iw*9/16)/2)*2'"


def crop_size(w: int, h: int, orientation: str) -> tuple[int, int]:
    """crop_filter 와 같은 계산(숫자)."""
    if is_vertical(orientation):
        return int(min(w, h * 9 / 16) / 2) * 2, int(min(h, w * 16 / 9) / 2) * 2
    return int(min(w, h * 16 / 9) / 2) * 2, int(min(h, w * 9 / 16) / 2) * 2


def seg_reframe(src: Source, seg: Segment, orientation: str) -> list | None:
    """세로 출력에서 쓸 크롭 키프레임(범위 제한). 없거나 모두 0 이면 None → 기존 가운데 크롭."""
    if not is_vertical(orientation) or not seg.reframe:
        return None
    m = reframe_max(src.width or 3840)
    keys = sorted(({"f": int(k["f"]), "dx": max(-m, min(m, float(k["dx"])))} for k in seg.reframe),
                  key=lambda k: k["f"])
    return keys if any(abs(k["dx"]) >= 0.5 for k in keys) else None


def reframe_expr(keys: list, f0: int, frames_per_sec: float, mul: float = 1.0) -> str:
    """t(초) → 이동량 식. 프레임 = f0 + t*frames_per_sec. 키프레임 사이 smoothstep (project.ease 와 같음)."""
    tk = [((k["f"] - f0) / frames_per_sec, k["dx"] * mul) for k in keys]
    e = f"{tk[-1][1]:.3f}"
    for (t0, d0), (t1, d1) in reversed(list(zip(tk, tk[1:]))):
        u = f"clip((t-{t0:.6f})/{max(1e-6, t1 - t0):.6f},0,1)"
        e = f"if(lt(t,{t1:.6f}),{d0:.3f}+({d1 - d0:.3f})*{u}*{u}*(3-2*{u}),{e})"
    return f"if(lt(t,{tk[0][0]:.6f}),{tk[0][1]:.3f},{e})"


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


def _stab_size(orientation, src: Source | None = None):
    """흔들림 보정 작업 크기 = 출력의 1.25배. 단 원본 크롭 크기보다 크게 키우지 않음(1440·4K 출력)."""
    w, h = out_size(orientation)
    if src is not None and src.width:
        cw, ch = crop_size(src.width, src.height, orientation)
        k = min(STAB_OVERSIZE, cw / w, ch / h)
        if k < STAB_OVERSIZE:
            return int(w * max(1.0, k)) // 2 * 2, int(h * max(1.0, k)) // 2 * 2
    return int(w * STAB_OVERSIZE) // 2 * 2, int(h * STAB_OVERSIZE) // 2 * 2


def stab_band(src: Source, seg: Segment, orientation: str, lens: list | tuple = ()):
    """흔들림 보정 앞 크롭. 세로 리프레이밍이 있으면 이동 범위 전체를 덮는 띠를 먼저 보정하고(보정 → 크롭)
    그 안에서 움직이는 크롭. 반환 (보정 전 필터들, 보정 후 크롭 필터 또는 None, 캐시 키)."""
    sw, sh = _stab_size(orientation, src)
    keys = seg_reframe(src, seg, orientation)
    tag = f"{sw}x{sh}|{','.join(lens)}"
    if not keys:
        return [*lens, crop_filter(orientation), f"scale={sw}:{sh}:flags=lanczos"], None, tag
    cw, ch = crop_size(src.width, src.height, orientation)
    dmin, dmax = min(k["dx"] for k in keys), max(k["dx"] for k in keys)
    x0 = max(0, int((src.width - cw) / 2 + dmin))
    bw = min(src.width - x0, int(cw + (dmax - dmin) + 2) // 2 * 2)
    k = sh / ch
    bws = int(round(bw * k / 2)) * 2
    pre = [*lens, f"crop={bw}:{ch}:{x0}:{(src.height - ch) // 2}", f"scale={bws}:{sh}:flags=lanczos"]
    cx0 = (src.width - cw) / 2 - x0          # 띠 안 가운데 크롭 위치(원본 px)
    xe = reframe_expr(keys, seg.fin, float(src.fps), k)
    post = f"crop={sw}:{sh}:x='clip({cx0 * k:.3f}+{xe},0,iw-{sw})':y=0"
    return pre, post, f"{x0}x{bw}|{tag}"


def stab_file(src: Source, seg: Segment, orientation: str, shakiness: int, lens=()) -> Path:
    key = (f"{os.path.abspath(src.path)}|{seg.fin}|{seg.fout}|{orientation}|{shakiness}|"
           f"{stab_band(src, seg, orientation, lens)[2]}")
    d = paths.cache_dir() / "lut"       # LUT 와 같은 작업 폴더(cwd) 사용 → 경로 이스케이프 불필요
    d.mkdir(parents=True, exist_ok=True)
    return d / f"stab_{hashlib.sha1(key.encode()).hexdigest()[:12]}.trf"


def stab_detect(src: Source, seg: Segment, orientation: str, shakiness: int, gpu: bool,
                on_progress=None, cancel=None, lens=()) -> Path:
    trf = stab_file(src, seg, orientation, shakiness, lens)
    if trf.exists() and trf.stat().st_size > 0:
        return trf
    tmp = trf.with_suffix(".part.trf")
    sec = float(Fraction(seg.frames) / src.fps)
    pre = [f.replace("flags=lanczos", "flags=bicubic") for f in stab_band(src, seg, orientation, lens)[0]]
    vf = [f"trim=end_frame={seg.frames}", "setpts=PTS-STARTPTS", *pre,
          f"vidstabdetect=shakiness={shakiness}:accuracy=15:result={tmp.name}"]
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
def proxy_path(src_path: str, lut: str | None = None) -> Path:
    """프록시 파일(LUT 를 입혀 만듦). 기본 LUT 는 예전 이름 그대로(이미 만든 프록시 재사용), 다른 LUT·LUT 없음은 이름에 반영."""
    from .project import DEFAULT_LUT
    st = os.stat(src_path)
    key = f"{os.path.abspath(src_path)}|{st.st_size}|{int(st.st_mtime)}"
    if lut is not None and lut != DEFAULT_LUT:
        key += f"|lut={lut}"
    h = hashlib.sha1(key.encode()).hexdigest()[:12]
    d = paths.cache_dir() / "proxy"
    d.mkdir(exist_ok=True)
    return d / f"{Path(src_path).stem}_{h}.mp4"


def _proxy_pix(path: str) -> str:
    try:
        out = run([paths.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
                   "-of", "csv=p=0", _abs(path)])
        return out.decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


PROXY_W = 640      # 프록시 폭(v0.16.16: 960 → 640, 만드는 시간·메모리 캐시 줄임. 예전 960 프록시는 그대로 재사용)


# ------------------------------------------------------------------ 카메라 프리뷰 파일(LRF·LRV) — v0.16.19 (design/PREVIEW_FILES.md 1·2단계)
# 있으면 영상마다 자동 판정(길이·비율·디코딩·색) → 맞으면 프리뷰로 프록시(빠름), 없거나 안 맞으면 지금처럼 원본. 결과는 cache/dtme.log.
PREVIEW_USE = True


def find_preview(path: str) -> str | None:
    """원본과 짝인 프리뷰 파일(같은 폴더, 대소문자 무시). DJI = 같은 이름 .LRF / GoPro GX·GH01xxxx → GL01xxxx.LRV /
    Insta360 VID_…_00_n.mp4 → LRV_…_01_n.lrv (PRO_VID → PRO_LRV)."""
    import re
    p = Path(path)
    stem = p.stem
    cands = [stem + ".lrf", stem + ".lrv"]
    m = re.match(r"^G[XH](\d{2})(\d{4})$", stem, re.I)
    if m:
        cands.append(f"gl{m.group(1)}{m.group(2)}.lrv")
    m = re.match(r"^(PRO_)?VID_(.+)_0(\d)_(\d+)$", stem, re.I)
    if m:
        cands += [f"{m.group(1) or ''}LRV_{m.group(2)}_{k}_{m.group(4)}.lrv" for k in ("01", "11", "00")]
    want = [c.lower() for c in cands]
    try:
        names = {f.name.lower(): f for f in p.parent.iterdir() if f.is_file() and f.suffix.lower() in (".lrf", ".lrv")}
    except OSError:
        return None
    for w in want:
        if w in names:
            return str(names[w])
    return None


def _tiny(path: str, t: float, lut_ref_: tuple | None, w: int = 64, h: int = 36, gpu: bool = False):
    """t 초 프레임을 w×h rgb24 로(LUT 는 축소 뒤 — 비교는 양쪽 같은 순서). 실패 = None."""
    import numpy as np
    vf = [f"scale={w}:{h}:flags=area"]
    if lut_ref_:
        vf += ["format=gbrp16le", f"lut3d=file={lut_ref_[1]}"]
    vf.append("format=rgb24")
    cmd = [paths.ffmpeg(), "-v", "error", *_hw(gpu), "-ss", f"{max(0.0, t):.3f}", "-i", _abs(path), "-frames:v", "1",
           "-an", "-vf", ",".join(vf), "-f", "rawvideo", "-"]
    try:
        out = run(cmd, cwd=lut_ref_[0] if lut_ref_ else None)
    except FFError:
        return None
    if len(out) < w * h * 3:
        return None
    return np.frombuffer(out[:w * h * 3], dtype=np.uint8).reshape(h, w, 3).astype(np.float32)


def check_preview(src: Source, lut: str, pv: str | None = None) -> dict:
    """프리뷰 판정. 반환 {"path", "ok", "why", "color": "raw"|"lut"|"", "fps", "dur", "diff"}.
    ok 조건: 디코딩 됨 · 길이 차 ≤ 프리뷰 1프레임(+원본 1프레임) · 가로세로 비 차 ≤ 2% · 색 = 가운데 프레임(원본 + 요청 LUT)과
    프리뷰 그대로 / 프리뷰 + LUT 중 가까운 쪽의 차(화소 차 중앙값, 0~255) ≤ PREVIEW_DIFF 이고 다른 쪽의 60% 이하."""
    r = {"path": pv or find_preview(src.path), "ok": False, "why": "", "color": "", "fps": 0.0, "dur": 0.0, "diff": -1.0,
         "shift": 0}
    if not r["path"]:
        r["why"] = "없음"
        return r
    try:
        out = run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", _abs(r["path"])])
        d = json.loads(out)
        v = next(x for x in d["streams"] if x.get("codec_type") == "video" and not x.get("disposition", {}).get("attached_pic"))
        n, dd = (int(x) for x in (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/"))
        r["fps"] = n / dd if dd else 30.0
        r["dur"] = float(v.get("duration") or d["format"].get("duration") or 0)
        pw, ph = int(v["width"]), int(v["height"])
    except Exception as e:  # noqa: BLE001
        r["why"] = f"읽기 실패 {str(e)[-80:]}"
        return r
    sdur = src.frames / float(src.fps)
    tol = 1.0 / max(1.0, r["fps"]) + 1.0 / float(src.fps) + 0.002
    if abs(r["dur"] - sdur) > tol:
        r["why"] = f"길이 다름 {r['dur']:.3f}/{sdur:.3f}초"
        return r
    if src.width and src.height and abs(pw / ph - src.width / src.height) > 0.02 * (src.width / src.height):
        r["why"] = f"비율 다름 {pw}x{ph}"
        return r
    ref = lut_ref(lut) if lut else None
    t = sdur * 0.5
    a = _tiny(src.path, t, ref)
    b = _tiny(r["path"], t, None)
    if a is None or b is None:
        r["why"] = "디코딩 실패" if b is None else "원본 프레임 실패"
        return r
    def dif(x, y):          # 화소별 평균 차의 중앙값 → 움직이는 작은 부분·압축 차이는 덜 탐(색 차이는 화면 전체라 그대로 잡힘)
        import numpy as np
        return float(np.median(abs(x - y).mean(axis=2)))
    diffs = {"raw": dif(a, b)}
    if ref:
        c = _tiny(r["path"], t, ref)
        if c is not None:
            diffs["lut"] = dif(a, c)
    r["shift"] = _align(src, r["path"], r["fps"])
    best = min(diffs, key=diffs.get)
    r["diff"] = round(diffs[best], 1)
    other = max(diffs.values()) if len(diffs) > 1 else None
    if diffs[best] > PREVIEW_DIFF:
        r["why"] = f"색 다름 {diffs}"
        return r
    if other is not None and diffs[best] > 0.6 * other:
        r["why"] = f"색 판정 애매 {diffs}"
        return r
    r["ok"], r["color"] = True, best
    return r


PREVIEW_DIFF = 10.0


def _align(src: Source, pv_path: str, pv_fps: float) -> int:
    """프리뷰 k번째(시각 k/pv_fps)가 원본 몇 번째와 같은 화면인지 = ratio·k + shift 의 shift(0..ratio-1).
    영상 중간 → 1/4 → 3/4 지점에서 프리뷰 15장씩(키프레임 시크 + 실제 pts 로 짝 맞춤) 비교해 확실한 표가 6개 이상 나오면 결정.
    실물 DJI(2026-11-08): 영상마다 0 또는 1. 끝까지 판단 안 되면(움직임 없음) 0 — 그런 화면은 어긋나도 티가 안 남."""
    import re
    import numpy as np
    ratio = max(1, int(round(float(src.fps) / max(1.0, pv_fps))))
    if ratio == 1:
        return 0
    fs = float(src.fps)
    dur = src.frames / fs

    def grab(p, t0, n):
        cmd = [paths.ffmpeg(), "-hide_banner", "-copyts", "-ss", f"{t0:.3f}", "-i", _abs(p), "-map", "0:v:0", "-frames:v", str(n),
               "-vf", "showinfo,scale=96:54:flags=area,format=rgb24", "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
        pr = _popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = pr.communicate()
        ts = [float(x) for x in re.findall(rb"pts_time:\s*([-0-9.]+)", err)]
        fr = np.frombuffer(out, np.uint8).reshape(-1, 54, 96, 3).astype(np.float32)
        return {int(round(t * (fs if p == src.path else pv_fps))): fr[i] for i, t in enumerate(ts[:len(fr)])}

    votes = [0] * ratio
    for frac in (0.5, 0.25, 0.75):
        t0 = max(0.0, dur * frac - 0.25)
        try:
            L, O = grab(pv_path, t0, 15), grab(src.path, t0, 15 * ratio + 4)
        except Exception:  # noqa: BLE001
            continue
        for k, lf in L.items():
            d = [float(abs(lf - O[j]).mean()) if j in O else None for j in range(ratio * k, ratio * k + ratio)]
            if None in d:
                continue
            srt = sorted(d)
            if srt[0] < 0.77 * srt[1]:                       # 확실히 가까운 것만 셈
                votes[d.index(srt[0])] += 1
        if max(votes) >= 6 and max(votes) >= 3 * (sum(votes) - max(votes)):
            return votes.index(max(votes))
    return votes.index(max(votes)) if max(votes) >= 6 else 0


def _proxy_from_preview(src: Source, lut: str, pv: dict, tmp: Path, pw: int, ph: int, on_progress, cancel) -> None:
    """프리뷰 → 프록시. fps = 원본 fps(30p → 60p 는 프레임 복제), 끝은 복제로 채운 뒤 원본 프레임 수에서 자름
    → 프록시 프레임 수 = 원본 프레임 수(다른 코드 그대로). 색 = 판정이 'lut' 면 LUT, 'raw' 면 그대로."""
    ref = lut_ref(lut) if (lut and pv["color"] == "lut") else None
    color = ["format=gbrp16le", f"lut3d=file={ref[1]}"] if ref else []
    # 시점 맞춤(v0.16.21): 프리뷰 k번째 = 원본 2k+shift번째(_align 이 영상마다 잼, DJI 실물 = 0 또는 1)
    # → shift 프레임만큼 늦춰 놓고 fps 를 0초부터 채움: 짝이 있는 프레임 = 같은 화면, 나머지 = 바로 앞 화면
    k = int(pv.get("shift") or 0)
    shift = f"+{k * src.fps_den}/({src.fps_num}*TB)" if k else ""
    vf = [f"setpts=PTS-STARTPTS{shift}", f"fps={src.fps_num}/{src.fps_den}:start_time=0", "tpad=stop_mode=clone:stop=8",
          f"trim=end_frame={src.frames}", f"scale={pw}:{ph}:flags=bilinear", *color, TO_YUV709]
    tail = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"] if src.has_audio else ["-an"]
    cmd = [paths.ffmpeg(), "-y", "-i", _abs(pv["path"]), "-map", "0:v:0", "-vf", ",".join(vf), *tail,
           "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
           "-g", "1", "-crf", "23", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-movflags", "+faststart", _abs(tmp)]
    run_progress(cmd, src.frames / float(src.fps), on_progress, cancel, cwd=ref[0] if ref else None)


def frame_count(path: str) -> int:
    """실제 프레임 수(패킷 세기, 프록시 확인용)."""
    out = run([paths.ffprobe(), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=nb_read_packets", "-of", "csv=p=0", _abs(path)])
    return int(out.decode().strip() or 0)


def make_proxy(src: Source, lut: str, gpu: bool, on_progress=None, cancel=None) -> str:
    """PROXY_W 폭, 모든 프레임 키프레임(H.264) → 프레임 단위 탐색이 빠름. LUT 를 미리 입혀 보기 좋게.
    GPU 켜짐: ① 디코딩·축소 모두 GPU(scale_cuda, 4K 프레임을 CPU 로 안 내림) → 실패하면 ② GPU 디코딩 + CPU 축소 → ③ CPU.
    걸린 시간은 cache/dtme.log 에 남김(사용자 PC 속도 확인용)."""
    import time
    out = proxy_path(src.path, lut or "")
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    tmp = out.with_suffix(".part.mp4")
    ref = lut_ref(lut) if lut else None
    color = ["format=gbrp16le", f"lut3d=file={ref[1]}"] if ref else []
    pw = PROXY_W
    ph = max(2, int(round(pw * (src.height or 2160) / (src.width or 3840) / 2)) * 2)
    tail = []
    if src.has_audio:
        tail += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"]
    tail += ["-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
             "-g", "1", "-crf", "23", "-colorspace", "bt709", "-color_primaries", "bt709",
             "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", _abs(tmp)]
    tries = []
    if gpu:
        dl = "p010le" if "10" in _proxy_pix(src.path) else "nv12"
        tries.append(("GPU 축소", ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
                      [f"scale_cuda={pw}:{ph}:interp_algo=bilinear", "hwdownload", f"format={dl}"]))
        tries.append(("GPU 디코딩", ["-hwaccel", "cuda"], [f"scale={pw}:{ph}:flags=bilinear"]))
    tries.append(("CPU", [], [f"scale={pw}:{ph}:flags=bilinear"]))
    dur = src.frames / float(src.fps)
    if PREVIEW_USE:                                   # 카메라 프리뷰(LRF 등)가 맞으면 그걸로(실패하면 아래 원본 방식)
        pv = None
        t0 = time.monotonic()
        try:
            pv = check_preview(src, lut or "")
            if pv["ok"]:
                t1 = time.monotonic()
                _proxy_from_preview(src, lut or "", pv, tmp, pw, ph, on_progress, cancel)
                n = frame_count(str(tmp))
                if abs(n - src.frames) > 1:
                    raise FFError(f"프레임 수 다름 {n}/{src.frames}")
                log_error("프록시", f"{Path(src.path).name} 프리뷰({Path(pv['path']).suffix[1:].upper()}, {pv['fps']:.2f}fps, "
                                   f"색 {pv['color']}, 차 {pv['diff']}, 시점 +{pv.get('shift', 0)}) 판정 {t1 - t0:.1f}초 + 만들기 {time.monotonic() - t1:.1f}초 "
                                   f"(영상 {dur:.0f}초)")
                replace_retry(tmp, out)
                return str(out)
            if pv["why"] != "없음":
                log_error("프리뷰 안 씀 → 원본", f"{Path(src.path).name}: {pv['why']}")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            if cancel is not None and cancel.is_set():
                raise
            log_error("프리뷰 실패 → 원본", f"{Path(src.path).name}: {str(e)[-300:]}")
    last = None
    for i, (name, hw, pre) in enumerate(tries):
        cmd = [paths.ffmpeg(), "-y", *hw, "-i", _abs(src.path), "-map", "0:v:0", "-vf", ",".join(pre + color + [TO_YUV709]), *tail]
        t0 = time.monotonic()
        try:
            run_progress(cmd, dur, on_progress, cancel, cwd=ref[0] if ref else None)
        except FFError as e:
            if cancel is not None and cancel.is_set():
                raise
            last = e
            log_error(f"프록시 {name} 실패 → 다음 방식", str(e)[-300:])
            continue
        log_error("프록시", f"{Path(src.path).name} {name} {time.monotonic() - t0:.1f}초 (영상 {dur:.0f}초)")
        replace_retry(tmp, out)
        return str(out)
    raise last


# ------------------------------------------------------------------ 미리보기용 프레임 캐시 (메모리)
# 디스크에 임시 파일을 쓰지 않음 → Windows 에서 백신·색인이 파일을 잡아 생기던 '다른 프로세스가 사용 중' 오류 제거.
# 앞 프레임(PREVIEW_LEAD)을 함께 넣어 시간축 노이즈 제거(hqdn3d)가 미리보기에도 보이게 함.
PREVIEW_LEAD = 4
_FRAME_CACHE_MAX = 48


class CachedFrame:
    """미리보기 입력(앞 프레임 + 그 프레임). fmt = 'nut'(ffv1 무손실) | 'raw'(yuv420p10le, 원본 구간 캐시에서 잘라 옴)."""

    def __init__(self, data: bytes, lead: int, size=(0, 0), fmt: str = "nut"):
        self.data, self.lead, self.size, self.fmt = data, lead, size, fmt

    def input_args(self) -> list[str]:
        if self.fmt == "raw":
            return ["-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-s", f"{self.size[0]}x{self.size[1]}", "-framerate", "60",
                    "-i", "-"]
        return ["-f", "nut", "-i", "-"]


# ------------------------------------------------------------------ 원본 구간 캐시(v0.16.7)
# 멈출 때 보정 화면 = 원본 4K 디코딩(키프레임부터) + 보정. 근처 프레임으로 옮겨 다닐 때마다 디코딩하던 것을,
# 멈춘 곳 앞뒤 1초(RANGE_HALF)를 뒤에서 한 번에 1280 폭 10bit 로 풀어 메모리에 둠 → 근처 프레임은 디코딩 없이 보정만.
# 1장 ≈ 1280×720×1.5×2 B ≈ 2.8MB, 59.94fps 120장 ≈ 330MB, 구간 RANGE_MAX 개까지(오래 안 쓴 것부터 지움).
RANGE_HALF = 60
RANGE_MAX = 4
_ranges: "dict[tuple, tuple]" = {}            # (경로, 시작) → (시작, 끝(제외), 데이터, 폭, 높이, 1장 바이트)
_range_busy: set = set()
_range_lock = threading.Lock()


def _preview_size(src) -> tuple[int, int]:
    return 1280, int(round(1280 * (src.height or 2160) / (src.width or 3840) / 2)) * 2


def range_lookup(path: str, lo: int, hi: int):
    """[lo, hi] 프레임이 모두 들어 있는 구간 → (데이터 조각, 폭, 높이) 또는 None."""
    path = os.path.abspath(path)
    with _range_lock:
        for k, (a, b, data, w, h, fs) in list(_ranges.items()):
            if k[0] == path and a <= lo and hi < b:
                _ranges[k] = _ranges.pop(k)           # 최근 사용 → 뒤로
                return data[(lo - a) * fs:(hi - a + 1) * fs], w, h
    return None


def prefetch_range(src: Source, center: int, gpu: bool = False) -> bool:
    """center 앞뒤 RANGE_HALF 프레임을 한 번에 디코딩해 둠(이미 덮여 있거나 만드는 중이면 건너뜀). 작업 스레드에서 부름."""
    path = os.path.abspath(src.path)
    a = max(0, center - RANGE_HALF)
    b = min(src.frames or center + RANGE_HALF, center + RANGE_HALF)
    if b - a < 2 or range_lookup(path, max(0, center - PREVIEW_LEAD - 8), min(b - 1, center + 8)) is not None:
        return False
    key = (path, a)
    with _range_lock:
        if key in _range_busy or any(k[0] == path and abs(k[1] - a) < RANGE_HALF // 3 for k in _range_busy):
            return False
        _range_busy.add(key)
    try:
        w, h = _preview_size(src)
        fs = w * h * 3                                 # yuv420p10le = 1.5 × 2바이트
        data = run([paths.ffmpeg(), "-v", "error", *_hw(gpu), "-ss", _seek(a, src.fps), "-i", _abs(src.path),
                    "-frames:v", str(b - a), "-an", "-vf", f"scale={w}:{h}:flags=lanczos,format=yuv420p10le",
                    "-f", "rawvideo", "-"])
        n = len(data) // fs
        if n < 2:
            return False
        with _range_lock:
            _ranges[key] = (a, a + n, data[:n * fs], w, h, fs)
            while len(_ranges) > RANGE_MAX:
                _ranges.pop(next(iter(_ranges)))
        return True
    finally:
        with _range_lock:
            _range_busy.discard(key)


def range_clear(path: str | None = None):
    with _range_lock:
        for k in [k for k in _ranges if path is None or k[0] == os.path.abspath(path)]:
            _ranges.pop(k, None)


_frame_cache: "dict[str, CachedFrame]" = {}
_frame_locks: dict[str, threading.Lock] = {}
_cache_lock = threading.Lock()


def cached_frame(src: Source, frame: int, gpu: bool = False) -> CachedFrame:
    """원본의 (앞 프레임 + 해당 프레임)을 1280 폭 10bit 무손실(ffv1, nut)로 메모리에 보관."""
    key = f"{os.path.abspath(src.path)}|{frame}"
    with _cache_lock:
        lk = _frame_locks.setdefault(key, threading.Lock())
    with lk:                                   # 같은 프레임 동시 생성 방지
        c = _frame_cache.get(key)
        if c is not None:
            return c
        lead = min(PREVIEW_LEAD, frame)
        hit = range_lookup(src.path, frame - lead, frame)      # 원본 구간 캐시에 있으면 디코딩 없이
        if hit is not None:
            data, w, h = hit
            return CachedFrame(data, lead, (w, h), "raw")
        data = run([paths.ffmpeg(), "-v", "error", *_hw(gpu), "-ss", _seek(frame - lead, src.fps), "-i", _abs(src.path),
                    "-frames:v", str(lead + 1), "-an", "-vf", "scale=1280:-2:flags=lanczos,format=yuv420p10le",
                    "-c:v", "ffv1", "-f", "nut", "-"])
        ch = int(round(1280 * (src.height or 2160) / (src.width or 3840) / 2)) * 2
        c = CachedFrame(data, lead, (1280, ch))
        with _cache_lock:
            _frame_cache[key] = c
            while len(_frame_cache) > _FRAME_CACHE_MAX:
                _frame_cache.pop(next(iter(_frame_cache)))
        return c


def lut_only(g: dict | None) -> dict:
    """보정 전 화면 = LUT만(반반 왼쪽 · [원본] 보기 · 샘플 왼쪽). v0.16.2 부터 Log 원본 대신."""
    from .project import NEUTRAL
    return {**NEUTRAL, "lut": (g or {}).get("lut", "")}


def render_preview(cached: CachedFrame, g: dict | None) -> bytes:
    """보정 적용 결과(마지막 프레임)를 PNG 바이트로. g=None 이면 보정 전(원본 Log)."""
    cwd, lut = (None, None)
    if g is None:
        vf = []
    else:
        cwd, lut = _lut_for(g)
        vf = lens_chain(g, *cached.size) + grade_chain(g, lut, 1280)
    vf += [f"select=gte(n\\,{cached.lead})", "format=rgb24"]
    return run([paths.ffmpeg(), "-v", "error", *cached.input_args(), "-filter_complex", graph(vf, "[0:v]", "[po]"),
                "-map", "[po]", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"], cwd=cwd, data=cached.data)


def render_region(src: Source, frame: int, g: dict | None, rect, max_w: int = 2560) -> bytes:
    """확대 보기: 원본(4K)에서 보이는 영역만 잘라 보정 → PNG. rect = (x, y, w, h) 0~1."""
    x, y, w, h = rect
    W, H = src.width or 3840, src.height or 2160
    cw, ch = max(16, int(w * W)) // 2 * 2, max(16, int(h * H)) // 2 * 2
    cx, cy = min(W - cw, int(x * W)) // 2 * 2, min(H - ch, int(y * H)) // 2 * 2
    lead = min(PREVIEW_LEAD, frame)
    cwd, lut = (None, None)
    vf = (lens_chain(g, W, H) if g else []) + [f"crop={cw}:{ch}:{cx}:{cy}"]
    if cw > max_w:
        vf.append(f"scale={max_w}:-2:flags=lanczos")
    if g is not None:
        cwd, lut = _lut_for(g)
        vf += grade_chain(g, lut, 3840)
    vf += [f"select=gte(n\\,{lead})", "format=rgb24"]
    return run([paths.ffmpeg(), "-v", "error", "-ss", _seek(frame - lead, src.fps), "-i", _abs(src.path),
                "-frames:v", str(lead + 1), "-an", "-filter_complex", graph(vf, "[0:v]", "[po]"), "-map", "[po]",
                "-f", "image2pipe", "-c:v", "png", "-"], cwd=cwd)


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


def zoom_filter(kind: str, start: float, dur: float, head: bool) -> str:
    """빠른 줌(회전 없음): perspective(프레임마다 계산, 3차 보간, 크기 고정).
    u = 0→1 가속(제곱). 배율 s = 1+2u.
    tail(앞 컷 끝): start~start+dur 동안 확대(회전). head(뒷 컷 시작): 0~dur 동안 확대 상태에서 원래로."""
    fps = float(OUT_FPS)
    if head:
        u = f"pow(1-clip(in/{fps:.5f}/{dur:.5f},0,1),2)"
        en = f"lte(t,{dur + 0.5 / fps:.5f})"
    else:
        u = f"pow(clip((in/{fps:.5f}-{start:.5f})/{dur:.5f},0,1),2)"
        en = f"gte(t,{start - 0.5 / fps:.5f})"
    sc = f"(1+2*{u})"
    th = "0"

    def pt(dx, dy):     # 출력 모서리 ← 원본 좌표: 중심 + R(θ)(모서리-중심)/s
        return (f"W/2+(({dx})*cos({th})-({dy})*sin({th}))/{sc}",
                f"H/2+(({dx})*sin({th})+({dy})*cos({th}))/{sc}")
    xy = [pt(dx, dy) for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:interpolation=cubic:eval=frame:enable='{en}'"


# 회전 줌(v0.16.11): 앞 컷 0→180° · 뒤 컷 −180→0° 를 이어 돌림(가운데 가장 빠름) + 모션블러.
ROT_DEG = 180.0
ROT_MIX = 0.2          # 겹침 구간 가운데에서 섞는 비율(나머지는 한 컷만 보임 → 회전이 흐려지지 않음)
ROT_BLUR = 16          # 모션블러 서브프레임 수
ROT_SHUTTER = 0.5      # 셔터 180°(1프레임 시간의 절반)
ROT_EXTRA = 0.5        # 검은 모서리 안 생기는 확대 위에 더하는 확대(가운데 최대)
ROT_KINDS = ("rotzoomin", "rotzoomout")


def rot_frames(d: float) -> tuple[int, int, int]:
    """전환 길이(초) → (겹침 프레임 nd, 한쪽만 보이는 프레임 k, 섞는 프레임 x). nd = 2k + x."""
    nd = max(3, int(round(d * float(OUT_FPS))))
    k = int(round(nd * (1 - ROT_MIX) / 2))
    x = max(1, nd - 2 * k)
    return k * 2 + x, k, x


def rot_state(kind: str, v: float) -> tuple[float, float]:
    """미리보기·점검용: 진행 v(0~1) → (앞 컷 각도°, 배율). 뒤 컷 각도 = 앞 컷 − 180°(방향 부호 포함)."""
    import math
    v = max(0.0, min(1.0, v))
    e = 4 * v ** 3 if v < 0.5 else 1 - (-2 * v + 2) ** 3 / 2
    th = math.radians(ROT_DEG * e)
    r = 16 / 9
    cov = abs(math.cos(th)) + abs(math.sin(th)) * r
    w = v ** (1.16 if kind == "rotzoomin" else 0.87)
    s = cov * (1 + ROT_EXTRA * math.sin(math.pi * w))
    return (1 if kind == "rotzoomin" else -1) * ROT_DEG * e, s


def _rot_persp(kind: str, role: str, off: float, nd: int) -> str:
    """perspective 한 장: in = 창 안 프레임 번호, off = 서브프레임 시간 + 시작 위치(프레임). role a = 앞 컷 / b = 뒤 컷."""
    v = f"clip((in+{off:.5f})/{nd},0,1)"
    e = f"if(lt({v},0.5),4*pow({v},3),1-pow(2-2*{v},3)/2)"
    sign = 1 if kind == "rotzoomin" else -1
    th = f"({sign}*PI*({e}{'' if role == 'a' else '-1'}))"
    pw = 1.16 if kind == "rotzoomin" else 0.87
    sc = (f"((abs(cos({th}))+abs(sin({th}))*max(W/H,H/W))*(1+{ROT_EXTRA}*sin(PI*pow({v},{pw}))))")

    def pt(dx, dy):
        return (f"W/2+(({dx})*cos({th})-({dy})*sin({th}))/{sc}",
                f"H/2+(({dx})*sin({th})+({dy})*cos({th}))/{sc}")
    xy = [pt(dx, dy) for dx, dy in (("-W/2", "-H/2"), ("W/2", "-H/2"), ("-W/2", "H/2"), ("W/2", "H/2"))]
    opts = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(xy))
    return f"perspective={opts}:interpolation=cubic:eval=frame"


def rot_window(fparts: list, inlab: str, outlab: str, kind: str, role: str, f0: int, f1: int, start: int, nd: int,
               uid: str, blur: int = ROT_BLUR) -> None:
    """컷의 프레임 f0~f1(제외) 를 회전 줌 + 모션블러로. start = 창 첫 프레임의 진행 위치(프레임)."""
    pre = f"{inlab}trim=start_frame={f0}:end_frame={f1},setpts=PTS-STARTPTS"
    n = max(1, int(blur))
    if n == 1:
        fparts.append(f"{pre},{_rot_persp(kind, role, start, nd)},setpts=PTS-STARTPTS{outlab}")
        return
    subs = [f"[rs{uid}_{j}]" for j in range(n)]
    fparts.append(f"{pre},split={n}{''.join(subs)}")
    outs = []
    for j, lab in enumerate(subs):
        off = start + (j / (n - 1) - 0.5) * ROT_SHUTTER
        o = f"[rp{uid}_{j}]"
        fparts.append(f"{lab}{_rot_persp(kind, role, off, nd)}{o}")
        outs.append(o)
    fparts.append(f"{''.join(outs)}mix=inputs={n}{outlab}")


_FF_MAJOR = None


def ffmpeg_major() -> int:
    """ffmpeg 주 버전(못 읽으면 0)."""
    global _FF_MAJOR
    if _FF_MAJOR is None:
        try:
            v = run([paths.ffmpeg(), "-hide_banner", "-version"]).decode(errors="ignore").split()
            num = v[2] if len(v) > 2 else ""
            _FF_MAJOR = int(num.split(".")[0]) if num[:1].isdigit() else 99    # master 빌드(N-xxxxx) = 최신
        except Exception:
            _FF_MAJOR = 0
    return _FF_MAJOR


FG_INLINE_MAX = 6000      # 이보다 긴 그래프는 파일로(Windows 명령줄 32K 제한 · 회전 줌 모션블러)


def filter_complex_args(graph_text: str) -> list[str]:
    """필터 그래프 인자. 길면 cache/lut 에 파일로 쓰고 ffmpeg 7+ 은 -/filter_complex, 그 전은 -filter_complex_script."""
    if len(graph_text) <= FG_INLINE_MAX:
        return ["-filter_complex", graph_text]
    d = paths.cache_dir() / "lut"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"fg_{hashlib.sha1(graph_text.encode()).hexdigest()[:16]}.txt"
    if not f.exists():
        tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(graph_text, encoding="utf-8")
        replace_retry(str(tmp), str(f))
    return ["-/filter_complex" if ffmpeg_major() >= 7 else "-filter_complex_script", str(f.resolve())]


def transition_graph(fparts: list, plan: list, lens: list, audio: bool, blur: int = ROT_BLUR) -> float:
    """[v0][a0]… 를 화면 전환(xfade/acrossfade)과 이어붙이기(concat)로 연결 → [vo][ao]. 결과 길이(초) 반환."""
    n = len(lens)
    fps = float(OUT_FPS)
    vl = [f"[v{i}]" for i in range(n)]
    al = [f"[a{i}]" for i in range(n)]
    eff = list(lens)                          # 회전 줌으로 앞뒤를 잘라 낸 뒤 길이
    xdur = [0.0] * n                          # 경계 i 의 xfade 길이(초)
    adur = [0.0] * n                          # 경계 i 의 acrossfade 길이(초)
    for i in range(n):
        t = plan[i]
        if t and i > 0:
            if t[0] in ROT_KINDS:
                nd, k, x = rot_frames(t[1])
                eff[i - 1] -= k / fps
                eff[i] -= k / fps
                xdur[i], adur[i] = x / fps, nd / fps
            else:
                xdur[i] = adur[i] = t[1]
    for i in range(n):                       # 컷 자체에 들어가는 효과(줌·회전 줌·첫 컷 페이드)
        f = []
        nxt = plan[i + 1] if i + 1 < n else None
        cur = plan[i]
        if nxt and nxt[0] == "zoomin":
            f.append(zoom_filter(nxt[0], lens[i] - nxt[1], nxt[1], head=False))
        if cur and i > 0 and cur[0] == "zoomout":
            f.append(zoom_filter(cur[0], 0, cur[1], head=True))
        if cur and i == 0:
            f.append(f"fade=t=in:st=0:d={cur[1]:.5f}:color={'white' if cur[0] == 'fadewhite' else 'black'}")
            if audio:
                fparts.append(f"[a0]afade=t=in:st=0:d={cur[1]:.5f}[a0f]")
                al[0] = "[a0f]"
        f.append("settb=AVTB")
        head = cur if (cur and i > 0 and cur[0] in ROT_KINDS) else None
        tail = nxt if (nxt and nxt[0] in ROT_KINDS) else None
        if not (head or tail):
            fparts.append(f"{vl[i]}{','.join(f)}[w{i}]")
            vl[i] = f"[w{i}]"
            continue
        lf = int(round(lens[i] * fps))
        pieces = []                           # (종류, f0, f1, …)
        b0, b1 = 0, lf
        if head:
            nd, k, _x = rot_frames(head[1])
            pieces.append(("b", k, nd, head[0], k, nd))
            b0 = nd
        if tail:
            nd, k, _x = rot_frames(tail[1])
            b1 = lf - nd
            tail_piece = ("a", lf - nd, lf - k, tail[0], 0, nd)
        if b1 > b0:
            pieces.append(("body", b0, b1))
        if tail:
            pieces.append(tail_piece)
        m = len(pieces)
        fparts.append(f"{vl[i]}{','.join(f)},split={m}" + "".join(f"[c{i}_{j}]" for j in range(m)))
        outs = []
        for j, pc in enumerate(pieces):
            o = f"[d{i}_{j}]"
            if pc[0] == "body":
                fparts.append(f"[c{i}_{j}]trim=start_frame={pc[1]}:end_frame={pc[2]},setpts=PTS-STARTPTS{o}")
            else:
                role, f0, f1, kind, start, nd = pc
                rot_window(fparts, f"[c{i}_{j}]", o, kind, role, f0, f1, start, nd, f"{i}_{j}", blur)
            outs.append(o)
        if m == 1:
            fparts.append(f"{outs[0]}null,settb=AVTB[w{i}]")
        else:
            fparts.append(f"{''.join(outs)}concat=n={m}:v=1:a=0,settb=AVTB[w{i}]")
        vl[i] = f"[w{i}]"
    acc_v, acc_a, acc = vl[0], al[0], eff[0]
    for i in range(1, n):
        last = i == n - 1
        ov, oa = ("[vo]", "[ao]") if last else (f"[xv{i}]", f"[xa{i}]")
        t = plan[i]
        if t:
            d = xdur[i]
            fparts.append(f"{acc_v}{vl[i]}xfade=transition={XFADE[t[0]]}:duration={d:.5f}:offset={acc - d:.5f}{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}acrossfade=d={adur[i]:.5f}{oa}")
            acc += eff[i] - d
        else:
            fparts.append(f"{acc_v}{vl[i]}concat=n=2:v=1:a=0{ov}")
            if audio:
                fparts.append(f"{acc_a}{al[i]}concat=n=2:v=0:a=1{oa}")
            acc += eff[i]
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


def probe_audio(path: str) -> float:
    """음악 파일 길이(초)."""
    out = run([paths.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.decode().strip() or 0)


def _hex(c: str) -> str:
    c = (c or "#ffffff").lstrip("#")
    return "0x" + (c if len(c) == 6 else "ffffff")


def _fade_alpha(t0, t1, f):
    f = min(f, (t1 - t0) / 2)
    if f <= 0.01:
        return "1"
    return f"if(lt(t,{t0 + f:.4f}),(t-{t0:.4f})/{f:.4f},if(gt(t,{t1 - f:.4f}),({t1:.4f}-t)/{f:.4f},1))"


def _work_copy(path: str, prefix: str) -> str:
    """글꼴·글자 파일을 작업 폴더(cache/lut, cwd)로 → 경로 이스케이프 문제 없음."""
    d = paths.cache_dir() / "lut"
    d.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    h = hashlib.sha1(f"{src.resolve()}|{src.stat().st_size}".encode()).hexdigest()[:10]
    dst = d / f"{prefix}_{h}{src.suffix.lower()}"
    _safe_copy(src, dst)
    return dst.name


def text_filter(t: dict, ow: int, oh: int) -> str | None:
    """타임라인 글자 1개 → drawtext."""
    from .fonts import font_file
    if not (t.get("text") or "").strip():
        return None
    k = min(ow, oh) / 1080
    ffile, real_bold = font_file(t.get("font", ""), bool(t.get("bold")))
    if not ffile:
        return None
    fname = _work_copy(ffile, "font")
    txt = (t.get("text") or "").replace("\r\n", "\n")
    tf = paths.cache_dir() / "lut" / f"tx_{hashlib.sha1(txt.encode()).hexdigest()[:10]}.txt"
    tf.write_text(txt, encoding="utf-8")
    t0, t1 = float(t["t0"]), float(t["t1"])
    col = _hex(t.get("color"))
    o = [f"fontfile={fname}", f"textfile={tf.name}", f"fontsize={max(8, round(float(t.get('size', 64)) * k))}",
         f"fontcolor={col}", "text_align=C", f"line_spacing={round(8 * k)}",
         f"x={float(t.get('cx', 0.5)) * ow:.1f}-text_w/2", f"y={float(t.get('cy', 0.8)) * oh:.1f}-text_h/2"]
    if t.get("bold") and not real_bold:
        o.append(f"borderw={max(1, round(1.5 * k))}:bordercolor={col}")
    bg = t.get("bg", "shadow")
    if bg == "shadow":
        sh = max(1, round(3 * k))
        o.append(f"shadowx={sh}:shadowy={sh}:shadowcolor=0x000000@0.6")
    elif bg == "band":
        o.append(f"box=1:boxcolor=0x000000@0.45:boxborderw={round(16 * k)}")
    o.append(f"enable='between(t,{t0:.4f},{t1:.4f})'")
    o.append(f"alpha='{_fade_alpha(t0, t1, float(t.get('fade', 0.5)))}'")
    return "drawtext=" + ":".join(o)


def post_graph(fparts: list, cmd: list, project: Project, extras: dict, total: float, orientation: str,
               audio: bool, n_inputs: int) -> None:
    """[vm][am] → 타임라인 글자·이미지(아래→위) + 음악/원본 볼륨 → [vo][ao]."""
    ow, oh = out_size(orientation)
    titles = [t for t in extras.get("titles", []) if float(t["t1"]) > float(t["t0"]) and float(t["t0"]) < total]
    music = [m for m in extras.get("music", []) if os.path.exists(m.get("path", "")) and float(m["t0"]) < total]
    mix = extras.get("mix") or {}
    cur, k, ii = "[vm]", 0, n_inputs
    for t in titles:
        nxt = f"[tv{k}]"
        if t.get("kind") == "text":
            f = text_filter(t, ow, oh)
            if not f:
                continue
            fparts.append(f"{cur}{f}{nxt}")
        else:
            img = project.image(t.get("img", ""))
            if img is None or not img.width or not os.path.exists(img.path):
                continue
            t0, t1 = float(t["t0"]), float(t["t1"])
            cmd += ["-loop", "1", "-framerate", f"{OUT_FPS.numerator}/{OUT_FPS.denominator}", "-t", f"{total + 1:.3f}",
                    "-noautorotate", "-i", _abs(img.path)]
            x, y, w, h = layer_box(t, img, ow, oh)
            fd = min(float(t.get("fade", 0.5)), (t1 - t0) / 2)
            chain = ORIENT_FILTER.get(img.orient, []) + [f"scale=w={w}:h={h}:flags=lanczos:{OV_CONVERT}", "format=yuva420p"]
            if fd > 0.01:
                chain += [f"fade=t=in:st={t0:.4f}:d={fd:.4f}:alpha=1", f"fade=t=out:st={t1 - fd:.4f}:d={fd:.4f}:alpha=1"]
            fparts.append(f"[{ii}:v:0]{','.join(chain)}[ti{k}]")
            fparts.append(f"{cur}[ti{k}]overlay=x={x}:y={y}:format=yuv420:eof_action=pass"
                          f":enable='between(t,{t0:.4f},{t1:.4f})'{nxt}")
            ii += 1
        cur, k = nxt, k + 1
    fparts.append(f"{cur}null[vo]")
    if not audio:
        return
    vo = orig_volume(mix, music)
    fparts.append(f"[am]volume={vo:.3f}[ab]")
    labs = ["[ab]"]
    for j, m in enumerate(music):
        t0 = float(m["t0"])
        ln = max(0.05, min(float(m.get("len", m.get("dur", 0))), total - t0))
        fi, fo = min(float(mix.get("fin", 0.5)), ln / 2), min(float(mix.get("fout", 2.0)), ln / 2)
        cmd += ["-i", _abs(m["path"])]
        a = [f"atrim=start={float(m.get('off', 0)):.4f}:duration={ln:.4f}", "asetpts=PTS-STARTPTS",
             "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if fi > 0.01:
            a.append(f"afade=t=in:st=0:d={fi:.4f}")
        if fo > 0.01:
            a.append(f"afade=t=out:st={ln - fo:.4f}:d={fo:.4f}")
        a += [f"volume={float(mix.get('music', 1.0)):.3f}", f"adelay=delays={int(t0 * 1000)}:all=1"]
        fparts.append(f"[{ii}:a:0]{','.join(a)}[mu{j}]")
        labs.append(f"[mu{j}]")
        ii += 1
    if len(labs) == 1:
        fparts.append("[ab]anull[ao]")
    else:
        fparts.append(f"{''.join(labs)}amix=inputs={len(labs)}:duration=first:normalize=0:dropout_transition=0[ao]")


def build_render_cmd(project: Project, segs: list[Segment], out_file: str, orientation: str | None = None,
                     audio: bool | None = None, fast: bool = False,
                     extras: dict | None = None) -> tuple[list[str], float, str | None]:
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
        g = project.grade_for_source(src.id, seg=seg)       # 보낼 때 꺼 둔 항목은 빼고
        lcwd, lut = _lut_for(g)
        cwd = cwd or lcwd
        seg_src_sec = float(Fraction(seg.frames) / src.fps)
        out_sec = seg_src_sec / seg.speed
        total += out_sec
        cmd += [*_hw(o.gpu_decode), "-ss", _seek(seg.fin, src.fps), "-t", f"{seg_src_sec + 0.5:.6f}", "-i", _abs(src.path)]
        v = [f"trim=end_frame={seg.frames}", "setpts=PTS-STARTPTS"]
        lensf = lens_chain(g, src.width, src.height)
        sp = None if fast else stab_params(g)       # 미리보기 렌더는 흔들림 보정 생략(분석이 느림)
        if sp:
            ow, oh = out_size(orientation)
            trf = stab_file(src, seg, orientation, sp[0], lensf)
            pre, post, _k = stab_band(src, seg, orientation, lensf)
            v += [*pre, f"vidstabtransform=input={trf.name}:smoothing={sp[1]}:optzoom=1:interpol=bicubic",
                  *([post] if post else []), f"scale={ow}:{oh}:flags=lanczos"]
            cwd = str(trf.parent)
        if seg.speed != 1.0:
            v.append(f"setpts=PTS/{seg.speed}")
        v.append(f"fps={OUT_FPS.numerator}/{OUT_FPS.denominator}")
        if not sp:
            v += lensf
            keys = seg_reframe(src, seg, orientation)
            if keys:      # 움직이는 세로 크롭(배속·fps 뒤라 t = 출력 시간)
                cw, ch = crop_size(src.width, src.height, orientation)
                ow, oh = out_size(orientation)
                xe = reframe_expr(keys, seg.fin, float(src.fps) * seg.speed)
                v += [f"crop={cw}:{ch}:x='clip((iw-{cw})/2+{xe},0,iw-{cw})':y=(ih-{ch})/2",
                      f"scale={ow}:{oh}:flags=lanczos"]
            else:
                v += frame_chain(orientation)
        if has_gkeys(seg):          # 색 키프레임: 프레임마다 값 변경(sendcmd, 파일은 LUT 와 같은 작업 폴더)
            n_out = int(round(seg_src_sec / seg.speed * float(OUT_FPS))) + 2
            cmdtxt = gkey_cmds(g, seg, src, n_out, float(src.fps) * seg.speed)
            cfile = paths.cache_dir() / "lut" / f"gk_{hashlib.sha1(cmdtxt.encode()).hexdigest()[:12]}.txt"
            cfile.parent.mkdir(parents=True, exist_ok=True)
            cfile.write_text(cmdtxt, encoding="utf-8")
            cwd = cwd or str(cfile.parent)
            v.append(f"sendcmd=f={cfile.name}")
            v += grade_chain(g, lut, min(out_size(orientation)) * 16 // 9, named=True)
        else:
            v += grade_chain(g, lut, min(out_size(orientation)) * 16 // 9)
        lays = seg_layers(project, seg)
        if not lays:
            v += [TO_YUV709, "setsar=1"]
            fparts.append(graph(v, f"[{i}:v:0]", f"[v{i}]", str(i)))
        else:
            # 보정 끝난 화면에 이미지 합성(보정 없음). 10bit 4:4:4 에서 합성 후 4:2:0 으로만 바꿈(행렬 재변환 없음)
            v.append(YUV444_709)
            fparts.append(graph(v, f"[{i}:v:0]", f"[b{i}_0]", str(i)))
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
    if extras and (extras.get("titles") or extras.get("music")):
        fparts[:] = [f.replace("[vo]", "[vm]").replace("[ao]", "[am]") for f in fparts]
        post_graph(fparts, cmd, project, extras, total, orientation, audio, len(segs) + len(img_inputs))
        cwd = cwd or str(paths.cache_dir() / "lut")
    cmd += [*filter_complex_args(";".join(fparts)), "-map", "[vo]"]
    if audio:
        cmd += ["-map", "[ao]", "-c:a", "aac", "-b:a", "192k"]
    br = int(o.bitrate_mbps * {"horizontal1440": 1.5, "horizontal2160": 2.5}.get(orientation, 1.0))   # 설정값 = 1080p 기준
    if fast:                         # 미리보기 렌더: 작고 빠르게
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26"]
    elif o.encoder == "nvenc":
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
                 orientation: str | None = None, audio: bool | None = None, fast: bool = False,
                 extras: dict | None = None) -> None:
    orient = orientation or project.output.orientation
    gpu = project.output.gpu_decode
    # 1패스: 흔들림 분석(필요한 컷만, 결과 캐시). 진행률 앞 40%
    todo = []
    for seg in segs:
        src = project.source(seg.src)
        gg = project.grade_for_source(src.id, seg=seg)
        sp = stab_params(gg)
        if sp and not fast and not stab_file(src, seg, orient, sp[0], lens_chain(gg, src.width, src.height)).exists():
            todo.append((src, seg, sp[0], lens_chain(gg, src.width, src.height)))
    share = 0.4 if todo else 0.0
    for k, (src, seg, shk, lens) in enumerate(todo):
        def sub(v, k=k):
            if on_progress:
                on_progress(share * (k + v) / len(todo))
        stab_detect(src, seg, orient, shk, gpu, sub, cancel, lens)
    outer = on_progress
    on_progress = (lambda v: outer(share + (1 - share) * v)) if outer else None
    cmd, total, cwd = build_render_cmd(project, segs, out_file, orientation, audio, fast, extras)
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
    """원본 4K 프레임에 보정 적용 → PNG(기본 8bit, 설정 still_bits=16 이면 16bit) 또는 16bit TIFF(.tif).
    앞 3프레임을 함께 넣어 시간축 노이즈 제거가 동작하게 하고 마지막 프레임만 저장."""
    cwd, lut = _lut_for(g)
    lead = min(3, frame)
    start = frame - lead
    is_png = str(out_file).lower().endswith(".png")
    from .project import get_setting
    bits = 16 if str(get_setting("still_bits", 8)) == "16" else 8     # v0.16.2: 기본 8bit(16bit PNG 는 뷰어에 따라 띠가 보임)
    pf = ("rgb48be" if bits == 16 else "rgb24") if is_png else "rgb48le"
    vf = lens_chain(g, src.width, src.height) + grade_chain(g, lut, 3840) + [SRGB_TAG, f"format={pf}"]
    codec = ["-c:v", "png", "-compression_level", "3"] if is_png else ["-c:v", "tiff", "-compression_algo", "deflate"]
    cmd = [paths.ffmpeg(), "-v", "error", "-y", *_hw(gpu), "-ss", _seek(start, src.fps), "-i", _abs(src.path),
           "-frames:v", str(lead + 1), "-an", "-filter_complex", graph(vf, "[0:v]", "[so]"), "-map", "[so]",
           "-update", "1", *codec, _abs(out_file)]
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


# ------------------------------------------------------------------ 반반 샘플 파일 (왼쪽 보정 전 = LUT만 · 오른쪽 보정)
def split_vf(g: dict, lut: str | None, orientation: str, size: int, fmt: str, src_wh=(0, 0), layout: str = "lr") -> str:
    """filter_complex: 보정 전(LUT만)과 보정 후를 같은 크기로 → 한 장.
    layout: lr = 왼쪽 반 전 · 오른쪽 반 후 / tb = 위 반 전 · 아래 반 후 /
            side = 나란히(전체 화면 2장: 가로 영상은 위(전)·아래(후), 세로 영상은 왼쪽(전)·오른쪽(후)). 경계에 흰 선 2px."""
    vert = is_vertical(orientation)
    sc = f"scale=-2:{size}:flags=lanczos" if vert else f"scale={size}:-2:flags=lanczos"
    lens = lens_chain(g, *src_wh)
    pre = ",".join(lens + [crop_filter(orientation), sc])
    gr = graph(grade_chain(g, lut, size * 9 // 16 if vert else size) + ["format=gbrp16le"], "[sb]", "[sr0]", "s")
    out = {"png16": SRGB_TAG + ",format=rgb48be", "jpg": "format=yuvj444p"}.get(fmt, SRGB_TAG + ",format=rgb24")
    left = f"format=gbrp16le,lut3d=file={lut}:interp=tetrahedral" if lut else "format=gbrp16le"     # 보정 전 = LUT만
    head = f"[0:v]{pre},split=2[sa][sb];[sa]{left}[sl0];{gr};"
    line = "color=white@0.9:t=fill"
    if layout == "tb":
        return (head + "[sl0]crop=iw:trunc(ih/4)*2:0:0[sl];[sr0]crop=iw:ih-trunc(ih/4)*2:0:trunc(ih/4)*2[sr];"
                f"[sl][sr]vstack=2,drawbox=x=0:y=trunc(ih/4)*2-1:w=iw:h=2:{line},{out}[so]")
    if layout == "side":
        if vert:
            return head + f"[sl0][sr0]hstack=2,drawbox=x=iw/2-1:y=0:w=2:h=ih:{line},{out}[so]"
        return head + f"[sl0][sr0]vstack=2,drawbox=x=0:y=ih/2-1:w=iw:h=2:{line},{out}[so]"
    return (head + "[sl0]crop=trunc(iw/4)*2:ih:0:0[sl];[sr0]crop=iw-trunc(iw/4)*2:ih:trunc(iw/4)*2:0[sr];"
            f"[sl][sr]hstack=2,drawbox=x=trunc(iw/4)*2-1:y=0:w=2:h=ih:{line},{out}[so]")


def export_split(src: Source, frame: int, g: dict, out_file: str, size: int = 1920, fmt: str = "png8",
                 orientation: str = "horizontal", gpu: bool = False, layout: str = "lr") -> None:
    """반반 샘플 1장 저장(png8 · png16 · jpg). 앞 3프레임을 넣어 시간축 노이즈 제거가 동작."""
    cwd, lut = _lut_for(g)
    lead = min(3, frame)
    codec = (["-c:v", "mjpeg", "-q:v", "2"] if fmt == "jpg" else ["-c:v", "png", "-compression_level", "3"])
    cmd = [paths.ffmpeg(), "-v", "error", "-y", *_hw(gpu), "-ss", _seek(frame - lead, src.fps), "-i", _abs(src.path),
           "-frames:v", str(lead + 1), "-an", "-filter_complex", split_vf(g, lut, orientation, size, fmt, (src.width, src.height), layout), "-map", "[so]",
           "-update", "1", *codec, _abs(out_file)]
    try:
        run(cmd, cwd=cwd)
    except FFError:
        if not gpu:
            raise
        run([c for c in cmd if c not in ("-hwaccel", "cuda")], cwd=cwd)
