"""프로젝트 데이터 구조. 모든 위치는 원본 기준 '프레임 번호'로 저장한다."""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

from . import paths

MAX_CURVE_POINTS = 5          # 양 끝점을 제외한 조정 포인트 수
OUT_FPS = Fraction(30000, 1001)  # 59.94 원본 → 29.97 출력


MAX_LAYERS = 3                  # 영상 1개에 얹을 수 있는 이미지 레이어 수
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".aac"}
VIDEO_EXT = {".mp4", ".mov"}

# 옛 디노이즈 단계 → (색 노이즈, 밝기 노이즈) 0~100
NR_LEGACY = {"off": (0, 0), "weak": (60, 25), "mid": (80, 45), "strong": (100, 70)}

GRADE_KEYS = ["lut", "r_gain", "b_gain", "hue", "sat", "water", "gy", "curve", "nr_chroma", "nr_luma", "wnr", "sharpen", "dehaze", "lens", "stab"]

# 출력: orientation 값 하나로 방향·크기를 함께 나타냄
OUTPUTS = [("horizontal", "1920×1080"), ("horizontal1440", "2560×1440"), ("horizontal2160", "3840×2160"),
           ("vertical", "1080×1920"), ("vertical1440", "1440×2560"), ("vertical2160", "2160×3840")]

OUT_H = {"horizontal": 1080, "horizontal1440": 1440, "horizontal2160": 2160}   # 가로 출력 높이(세로 = 늘 허용)
OUT_VW = {"vertical1440": 1440, "vertical2160": 2160}       # v0.16.70 세로 1440·4K = 세로로 찍은 원본(폭이 그 이상)에만
ROT = {"horizontal": "vertical", "horizontal1440": "vertical1440", "horizontal2160": "vertical2160"}   # 세로 촬영 = 90도 돌린 크기
ROT_BACK = {v: k for k, v in ROT.items()}


def is_portrait(src) -> bool:
    """세로로 찍은 원본(높이 > 폭, 회전 정보 반영)."""
    return src is not None and bool(getattr(src, "width", 0)) and getattr(src, "height", 0) > getattr(src, "width", 0)


def source_vw(src) -> int:
    """세로로 찍은 원본에서 9:16 로 낼 수 있는 폭(가로 촬영 = 0)."""
    if not is_portrait(src):
        return 0
    return int(min(src.width, src.height * 9 / 16))


def rotate_for(key: str, src) -> str:
    """v0.16.70 고른 크기 → 이 소스의 출력: 세로로 찍은 소스면 가로 크기를 90도 돌린 세로."""
    return ROT.get(key, key) if is_portrait(src) else key


def out_label(key: str, src=None, short: bool = False) -> str:
    """출력 이름: 가로 = 1080·1440·4K / 세로 촬영 = 세로 1080·1440·4K / 가로 촬영을 세로로 자름 = 인스타."""
    if key == "vertical" and not is_portrait(src):
        return "인스타" if short else "인스타 1080×1920"
    if short:
        return {"horizontal": "1080", "horizontal1440": "1440", "horizontal2160": "4K", "vertical": "세로 1080",
                "vertical1440": "세로 1440", "vertical2160": "세로 4K"}.get(key, "1080")
    return dict(OUTPUTS).get(key, key)


def src_out_h(width: int, height: int) -> int:
    """16:9 로 자른 원본 높이(업스케일 없이 낼 수 있는 가로 출력 높이). 모름 = 0."""
    if not width or not height:
        return 0
    return int(min(height, width * 9 / 16))


def outputs_for(h: int, vw: int = 0) -> list[str]:
    """v0.16.32: 원본(16:9 높이 h)에 맞는 출력 — 가로 1080·세로 1080 는 늘, 1440·4K 는 원본이 그 이상일 때만. h=0(모름) = 가로 전부.
    v0.16.70 세로 1440·4K = 세로로 찍은 원본의 9:16 폭(vw)이 그 이상일 때만."""
    return [k for k, _ in OUTPUTS if k == "vertical" or (k in OUT_H and (not h or OUT_H[k] <= max(h, 1080)))
            or (k in OUT_VW and vw >= OUT_VW[k])]


def clamp_out(key: str, h: int, vw: int = 0) -> str:
    """원본보다 큰 출력이면 원본이 낼 수 있는 가장 큰 같은 방향으로."""
    ok = outputs_for(h, vw)
    if key in ok:
        return key
    if key in OUT_VW:
        return max((k for k in ok if k in OUT_VW), key=lambda k: OUT_VW[k], default="vertical")
    return max((k for k in ok if k in OUT_H), key=lambda k: OUT_H[k], default="horizontal")


def clamp_src(key: str, src) -> str:
    return clamp_out(key, source_out_h(src), source_vw(src))


def source_out_h(src) -> int:
    return src_out_h(getattr(src, "width", 0), getattr(src, "height", 0)) if src is not None else 0


DEFAULT_LUT = "DJI_OSMO_Action_4_D-Log_M_to_Rec.709_V1.cube"   # DJI 공개 LUT, 프로그램에 포함
DEFAULTS_REV = 2      # 공장 기본값을 바꾸면 올림 → 이전에 저장한 '새 프로젝트 기본값'은 한 번 무시

FACTORY_GRADE = {
    "lut": DEFAULT_LUT,
    "r_gain": 1.0,
    "b_gain": 1.05,
    "hue": 5.0,
    "sat": 1.1,          # 채도(vibrance 방식: 진한 색은 덜 올림) 0~2 — 기본 1.1(사용자 2026-11-06)
    "water": 0,          # 물빛: 청록·녹색 범위만 파랑 쪽으로(°) −10~40
    "gy": 0,             # 녹황: 녹·황 채도만 줄임 0~100
    "curve": [[0.0, 0.0], [1.0, 1.0]],
    "nr_chroma": 25,     # 색 노이즈(푸른 물속의 보라·빨강 점) 0~100
    "nr_luma": 25,       # 밝기 노이즈 0~100
    "wnr": 0,            # 물 노이즈: 파란 영역의 붉은 색 노이즈만 정리 0~100
    "sharpen": 0.3,      # 밝기에만 적용
    "dehaze": 0,         # 디헤이즈 — v0.16.2 에서 뺌(계단 문제). 옛 값은 무시
    "lens": 0,           # 렌즈 왜곡 보정(액션캠 휘어짐) 0~100
    "stab": 0,           # 흔들림 보정 0(끔)~100, 렌더에만 적용
}


# 보정 없음(LUT만) — 새로 불러온 클립 · [리셋]. LUT 는 프로젝트 기본값을 따름(사용자 2026-11-06: 액션을 해야 보정 시작)
NEUTRAL = {"r_gain": 1.0, "b_gain": 1.0, "hue": 0.0, "sat": 1.0, "water": 0, "gy": 0, "curve": [[0.0, 0.0], [1.0, 1.0]],
           "nr_chroma": 0, "nr_luma": 0, "wnr": 0, "sharpen": 0.0, "dehaze": 0, "lens": 0, "stab": 0}


def auto_lut(project, s) -> str | None:
    """색 모드에 맞는 LUT: D-Log M = 프로젝트 기본 LUT(없으면 DJI LUT), 일반·알 수 없음 = LUT 없음. 판단 전(옛 소스) = None(그대로)."""
    mode = getattr(s, "lut_mode", "")
    if not mode:
        return None
    if mode == "dlog":
        lut = project.grade.get("lut", "")
        if not lut and (paths.lut_dir() / DEFAULT_LUT).exists():
            lut = DEFAULT_LUT
        return lut
    if mode == "ilog":                       # Insta360 I-Log(v0.16.50): LUT 폴더에서 이름에 insta/i-log 가 든 것(Rec709 먼저). 없으면 LUT 없음
        try:
            c = sorted(p.name for p in paths.lut_dir().iterdir() if p.suffix.lower() in (".cube", ".3dl")
                       and re.search(r"insta|i[-_ ]?log", p.name, re.I))
        except OSError:
            c = []
        c.sort(key=lambda n: (not re.search(r"709", n), n))
        return c[0] if c else ""
    return ""


def keep_lut(project, s, d: dict) -> dict:
    """클립 값 d 에 클립의 지금 LUT 를 넣어 둠(프리셋·기본값·AUTO 가 D-Log/일반 LUT 를 바꾸지 않게). 기본값과 같으면 뺌."""
    lut = project.grade_for_source(s.id, off=False).get("lut", "")
    d = dict(d)
    if lut != project.grade.get("lut", ""):
        d["lut"] = lut
    else:
        d.pop("lut", None)
    return d


def plain_grade() -> dict:
    return copy.deepcopy(NEUTRAL)


def apply_off(g: dict, off) -> dict:
    """잠시 끈 항목 = 보정 없음 값으로."""
    if not off:
        return g
    g = dict(g)
    for k in off:
        if k in NEUTRAL:
            g[k] = copy.deepcopy(NEUTRAL[k])
    return g


def is_plain(s) -> bool:
    """아직 아무 보정도 안 한 클립(LUT만)."""
    return not s.gkeys and not getattr(s, "off", None) and {k: v for k, v in s.grade.items() if k != "lut"} == NEUTRAL


def has_clip_grade(s) -> bool:
    """클립 값(C)이 있음 — 보정 없음(LUT만)은 제외."""
    return bool({k for k in s.grade if k != "lut"} or s.gkeys or getattr(s, "off", None)) and not is_plain(s)   # LUT 만 다름(일반 영상) = C 아님


def upgrade_grade(g: dict) -> dict:
    """옛 'nr'(끔/약/중/강) → nr_chroma/nr_luma."""
    if "nr" in g:
        c, l = NR_LEGACY.get(g.pop("nr"), (60, 25))
        g.setdefault("nr_chroma", c)
        g.setdefault("nr_luma", l)
    return g


def load_default_output() -> "OutputSettings":
    """새 프로젝트 렌더 설정 = 마지막으로 [확인]한 값(settings.json render_defaults). 저장폴더는 따로(last_folder)."""
    o = OutputSettings()
    try:
        d = get_setting("render_defaults", {}) or {}
        for k in ("prefix", "encoder", "bitrate_mbps", "gpu_decode"):
            if k in d:
                setattr(o, k, type(getattr(o, k))(d[k]))
    except Exception:  # noqa: BLE001
        pass
    return o


def load_default_grade() -> dict:
    """사용자가 '새 프로젝트 기본값'으로 저장한 값. 없으면 공장값."""
    g = dict(FACTORY_GRADE)
    if not (paths.lut_dir() / DEFAULT_LUT).exists():
        g["lut"] = ""
    try:
        s = _settings()
        if int(s.get("defaults_rev", 0)) < DEFAULTS_REV:
            return g
        g.update({k: v for k, v in upgrade_grade(dict(s.get("default_grade", {}))).items() if k in GRADE_KEYS})
    except Exception:
        pass
    return g


# settings.json: ffmpeg 를 띄울 때마다 여러 번 읽으므로(자리 수 등) 파일이 그대로면 읽어 둔 것을 씀. 쓰기는 잠금 + 임시 파일 → 이름 바꾸기
# (작업 스레드와 화면이 동시에 쓰거나 쓰는 중 꺼지면 파일이 깨져 설정이 모두 기본값으로 돌아가던 위험, v0.16.40).
_set_lock = threading.RLock()
_set_cache: list = [None, {}]          # [(mtime_ns, size), dict]


def _settings() -> dict:
    """settings.json 내용(읽기 전용으로 쓸 것). 없거나 깨졌으면 {}."""
    p = paths.settings_path()
    with _set_lock:
        try:
            st = p.stat()
        except OSError:
            _set_cache[:] = [None, {}]
            return {}
        sig = (st.st_mtime_ns, st.st_size)
        if _set_cache[0] != sig:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                d = d if isinstance(d, dict) else {}
            except Exception:  # noqa: BLE001
                d = {}
            _set_cache[:] = [sig, d]
        return _set_cache[1]


def _settings_update(values: dict) -> None:
    p = paths.settings_path()
    with _set_lock:
        s = dict(_settings())
        s.update(values)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        for i in range(20):                      # Windows: 백신 등이 잠깐 잡고 있으면 다시
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)
        _set_cache[0] = None


def get_setting(key: str, default=None):
    try:
        v = _settings().get(key, default)
        return copy.deepcopy(v) if isinstance(v, (dict, list)) else v     # 받은 쪽이 고쳐도 읽어 둔 것은 그대로
    except Exception:  # noqa: BLE001
        return default


def set_setting(key: str, value) -> None:
    _settings_update({key: value})


def save_default_grade(grade: dict) -> None:
    _settings_update({"default_grade": {k: grade[k] for k in GRADE_KEYS}, "defaults_rev": DEFAULTS_REV})


def write_json_atomic(file, data, indent=2) -> None:
    """프로젝트·자동 저장: 임시 파일에 다 쓴 뒤 바꿔치기(쓰는 중 꺼져도 예전 파일이 남음, v0.16.40)."""
    f = Path(file)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    for i in range(20):
        try:
            os.replace(tmp, f)
            return
        except PermissionError:
            if i == 19:
                raise
            time.sleep(0.05)


# ------------------------------------------------------------------ 프리셋 (presets/*.json)
def _preset_dir() -> Path:
    d = paths.app_dir() / "presets"
    d.mkdir(exist_ok=True)
    return d


def _preset_file(name: str) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "preset"
    return _preset_dir() / f"{safe}.json"


def list_presets() -> list[str]:
    out = []
    for f in sorted(_preset_dir().glob("*.json"), key=lambda x: x.stem.lower()):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")).get("name", f.stem))
        except Exception:  # noqa: BLE001
            pass
    return out


def load_preset(name: str) -> dict:
    d = json.loads(_preset_file(name).read_text(encoding="utf-8"))
    g = upgrade_grade(dict(d.get("grade", {})))
    return {k: v for k, v in g.items() if k in GRADE_KEYS}


def save_preset(name: str, grade: dict) -> None:
    _preset_file(name).write_text(json.dumps({"name": name, "grade": {k: grade[k] for k in GRADE_KEYS if k in grade}},
                                             ensure_ascii=False, indent=2), encoding="utf-8")


def delete_preset(name: str) -> None:
    _preset_file(name).unlink(missing_ok=True)


def rename_preset(old: str, new: str) -> None:
    g = load_preset(old)
    delete_preset(old)
    save_preset(new, g)


def _id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Source:
    path: str
    fps_num: int = 60000
    fps_den: int = 1001
    frames: int = 0
    width: int = 0
    height: int = 0
    has_audio: bool = True
    proxy: str = ""
    grade: dict = field(default_factory=dict)   # 클립별 덮어쓰기(일부 키만)
    sel_in: int = 0          # 소스 모니터의 인 점(포함)
    sel_out: int = 0         # 아웃 점(제외). 0 = 끝까지
    speed: float = 1.0       # 소스 모니터에서 지정한 배속
    layers: list = field(default_factory=list)  # 이미지 레이어(new_layer 형식 dict, 아래가 먼저 그려짐)
    reframe: list = field(default_factory=list)  # 세로 크롭 키프레임 [{"f": 프레임, "dx": 원본 px}] (프레임 순)
    gkeys: dict = field(default_factory=dict)    # 색 키프레임 {"r_gain": [{"f", "v"}], …} (KEYABLE 만)
    stars: list = field(default_factory=list)    # ★ 장면 표시(프레임)
    auto: dict = field(default_factory=dict)     # AUTO·프리셋 기록 {"preset": 키, "by": "auto"|"user", "rec": 인식 키, "nkeys": n}
    out: str = ""                                # 이 소스의 출력(orientation, v0.16.55 보정 패널 출력 칸 = 소스별). "" = 프로젝트 출력
    ctime: str = ""                              # 파일 안의 만든 시각 YYYYMMDDhhmm(현지 시간) — 이름에 날짜가 없을 때 표시·렌더 이름(v0.16.55)
    off: list = field(default_factory=list)      # 이름을 눌러 잠시 끈 보정 항목(미리보기·보낼 때 빼고 적용)
    lut_mode: str = ""                           # DJI 메타로 판단한 색 모드 dlog | normal | unknown ("" = 옛 프로젝트, 판단 안 함)
    rotation: int = 0                            # v0.16.78 파일의 회전 정보(세로 촬영 ±90) — GPU 프레임 경로는 자동 회전이 안 돼서 피함
    id: str = field(default_factory=_id)

    @property
    def fps(self) -> Fraction:
        return Fraction(self.fps_num, self.fps_den)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def io(self) -> tuple[int, int]:
        out = self.sel_out if 0 < self.sel_out <= self.frames else self.frames
        return max(0, min(self.sel_in, out - 1)), out

    @property
    def io_trimmed(self) -> bool:
        a, b = self.io
        return a > 0 or b < self.frames


@dataclass
class Segment:
    """타임라인/렌더 리스트의 컷 하나."""
    src: str
    fin: int          # 인 프레임(포함)
    fout: int         # 아웃 프레임(제외)
    speed: float = 1.0
    id: str = field(default_factory=_id)
    layers: list = field(default_factory=list)  # 보낼 때 소스 레이어의 사본
    trans: dict = field(default_factory=dict)   # 이 컷 '앞 경계'의 화면 전환 {"type", "dur"}
    reframe: list = field(default_factory=list)  # 보낼 때 소스 세로 크롭 키프레임의 사본
    gkeys: dict = field(default_factory=dict)    # 보낼 때 소스 색 키프레임의 사본
    off: list = field(default_factory=list)      # 보낼 때 잠시 꺼 둔 보정 항목의 사본(렌더에서 빼고 적용)
    grade: dict = field(default_factory=dict)    # 렌더 리스트로 보낼 때 보정값 사본(v0.16.2). 비면(옛 항목) 지금 클립 값
    aud: str = "auto"                            # v0.16.66 원본 소리: auto(판단대로) | up(키움) | keep(키우지 않음)
    loud: object = None                          # 자동 판단: True = 키움(말소리·수면 위) / False / None = 아직
    why: str = ""                                # 판단 이유: 말소리 | 호흡기 | 수면 위 | 물속

    @property
    def frames(self) -> int:
        return max(0, self.fout - self.fin)

    def copy(self) -> "Segment":
        return Segment(self.src, self.fin, self.fout, self.speed, layers=copy.deepcopy(self.layers),
                       trans=dict(self.trans), reframe=copy.deepcopy(self.reframe), gkeys=copy.deepcopy(self.gkeys),
                       off=list(self.off), grade=copy.deepcopy(self.grade), aud=self.aud, loud=self.loud, why=self.why)


# 세로 크롭 위치 이동(리프레이밍). 4K 기준 ±540px(그 이상은 액션캠 가장자리 왜곡)
REFRAME_MAX_4K = 540


def reframe_max(src_width: int) -> float:
    return REFRAME_MAX_4K * src_width / 3840


def ease(u: float) -> float:
    """키프레임 사이 곡선 이동(smoothstep). ffmpeg 식(ff.reframe_expr)과 같은 함수."""
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


STAB_LIMIT = {"bluewater": 0, "coral": 100}      # v0.16.45 흔들림 보정 한계(사용자): 블루워터 = 끔 · 산호 = 100 · 나머지 = 50
STAB_LIMIT_ELSE = 50                             # 화면만 보고 흔들림을 찾아서, 고정된 무늬가 없는 장면(물·물고기 떼)은 오히려 더 흔들림(1218 실측)


def stab_limit(src) -> int:
    """이 클립에서 쓸 수 있는 흔들림 보정 최대값(프리셋 기준). 프리셋 없음·사용자 프리셋 = 나머지(50)."""
    k = ((getattr(src, "auto", None) or {}).get("preset", "") or "") if src is not None else ""
    if k.startswith("scene:"):
        k = k[6:]
    sc, _, sb = k.partition("/")
    return STAB_LIMIT.get("coral" if sb == "coral" else sc, STAB_LIMIT_ELSE)


def _stab_cap(g: dict, src) -> dict:
    lim = stab_limit(src)
    if float(g.get("stab", 0) or 0) > lim:
        g["stab"] = lim
    return g


KEYABLE = ["r_gain", "b_gain", "hue", "sat", "water", "gy"]     # 시간에 따라 바뀌는 보정(◆, 숫자)
CURVE_KEY = "curve"
# v0.16.35 ◆ 종류별 (이름, 색) — 소스 바 ◆ · 보정 패널 ◆ 버튼 같은 색
GKEY_STYLE = {"r_gain": ("빨강", "#e05555"), "b_gain": ("파랑", "#4a90e2"), "hue": ("색조", "#b07cff"),
              "sat": ("채도", "#ff9f43"), "water": ("물빛", "#2ec4b6"), "gy": ("녹황 빼기", "#a3d65c"),
              "curve": ("커브", "#f0f0f0")}                                              # 커브 ◆(v0.16.34): {"f", "v": [[x, y], …]}


def key_at(keys: list, f: float, field_: str = "v") -> float | None:
    """키프레임 사이 smoothstep. 첫 키 전·마지막 키 뒤는 그 값."""
    if not keys:
        return None
    if f <= keys[0]["f"]:
        return float(keys[0][field_])
    for a, b in zip(keys, keys[1:]):
        if f < b["f"]:
            return a[field_] + (b[field_] - a[field_]) * ease((f - a["f"]) / max(1, b["f"] - a["f"]))
    return float(keys[-1][field_])


def spline_eval(pts, xs) -> list:
    """커브 점(ffmpeg curves 와 같은 natural spline)을 xs 에서 계산. 0~1 로 자름."""
    pts = sorted((float(x), float(y)) for x, y in pts)
    k = len(pts)
    if k < 2:
        return [max(0.0, min(1.0, x)) for x in xs]
    px = [q[0] for q in pts]
    py = [q[1] for q in pts]
    h = [max(1e-6, px[i + 1] - px[i]) for i in range(k - 1)]
    M = [0.0] * k
    if k > 2:
        a, b, c, d = [0.0] * k, [1.0] * k, [0.0] * k, [0.0] * k
        for i in range(1, k - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            d[i] = 6 * ((py[i + 1] - py[i]) / h[i] - (py[i] - py[i - 1]) / h[i - 1])
        for i in range(1, k):
            m = a[i] / b[i - 1]
            b[i] -= m * c[i - 1]
            d[i] -= m * d[i - 1]
        M[-1] = d[-1] / b[-1]
        for i in range(k - 2, -1, -1):
            M[i] = (d[i] - c[i] * M[i + 1]) / b[i]
    out = []
    for x in xs:
        if x <= px[0]:
            out.append(max(0.0, min(1.0, py[0])))
            continue
        if x >= px[-1]:
            out.append(max(0.0, min(1.0, py[-1])))
            continue
        i = next(j for j in range(k - 1) if x <= px[j + 1])
        dx, hi = x - px[i], h[i]
        y = (py[i] + ((py[i + 1] - py[i]) / hi - hi * (2 * M[i] + M[i + 1]) / 6) * dx + M[i] / 2 * dx * dx
             + (M[i + 1] - M[i]) / (6 * hi) * dx ** 3)
        out.append(max(0.0, min(1.0, y)))
    return out


def blend_curves(ca, cb, t: float) -> list:
    """두 커브 사이(t 0~1): 두 커브의 점 x 를 합친 위치에서 각자 계산해 섞음(점 개수가 달라도 됨)."""
    if t <= 0:
        return [list(q) for q in ca]
    if t >= 1:
        return [list(q) for q in cb]
    xs = sorted({round(float(q[0]), 4) for q in list(ca) + list(cb)} | {0.0, 1.0})
    ya, yb = spline_eval(ca, xs), spline_eval(cb, xs)
    return [[x, round(a + (b - a) * t, 4)] for x, a, b in zip(xs, ya, yb)]


def curve_at(keys: list, f: float):
    """커브 ◆(v0.16.34): 키 사이 smoothstep 으로 섞은 커브. 첫 키 전·마지막 키 뒤는 그 커브."""
    if not keys:
        return None
    if f <= keys[0]["f"]:
        return [list(q) for q in keys[0]["v"]]
    for a, b in zip(keys, keys[1:]):
        if f < b["f"]:
            return blend_curves(a["v"], b["v"], ease((f - a["f"]) / max(1, b["f"] - a["f"])))
    return [list(q) for q in keys[-1]["v"]]


def grade_at(g: dict, gkeys: dict, f: float) -> dict:
    """프레임 f 의 보정값(색 키프레임 · 커브 ◆ 반영)."""
    if not gkeys:
        return g
    g = dict(g)
    for k in KEYABLE:
        v = key_at(gkeys.get(k) or [], f)
        if v is not None:
            g[k] = v
    c = curve_at(gkeys.get(CURVE_KEY) or [], f)
    if c is not None:
        g["curve"] = c
    return g


def reframe_at(keys: list, f: float) -> float:
    """프레임 f 의 크롭 이동량(원본 px). 첫 키프레임 전·마지막 뒤는 그 값 유지."""
    if not keys:
        return 0.0
    if f <= keys[0]["f"]:
        return float(keys[0]["dx"])
    for a, b in zip(keys, keys[1:]):
        if f < b["f"]:
            return a["dx"] + (b["dx"] - a["dx"]) * ease((f - a["f"]) / max(1, b["f"] - a["f"]))
    return float(keys[-1]["dx"])


# 화면 전환: (종류, 이름). 첫 컷에는 페이드(검정·흰색)만 = 검정/흰 화면에서 들어옴
# v0.16.34 이름 = 새 화면이 들어오는 방향(ffmpeg 시험: wipeleft = 오른쪽에서 들어옴)
TRANSITIONS = [("none", "없음"), ("dissolve", "디졸브"),
               ("wipeleft", "우 → 좌"), ("wiperight", "좌 → 우"), ("wipeup", "아래 → 위"), ("wipedown", "위 → 아래"),
               ("zoomin", "줌인"), ("zoomout", "줌아웃"),
               ("rotzoomin", "회전 줌인"), ("rotzoomout", "회전 줌아웃"),
               ("fadeblack", "검정 페이드"), ("fadewhite", "흰색 페이드")]
TRANS_NAME = dict(TRANSITIONS)
FIRST_OK = {"fadeblack", "fadewhite"}
TRANS_DEFAULT_SEC = 0.5
TRANS_RANGE = (0.2, 2.0)


def plan_transitions(segs, lengths) -> list:
    """컷마다 (종류, 실제 길이 초) 또는 None. 길이는 앞뒤 컷 길이의 절반을 넘지 않게 줄임(겹침이 서로 침범하지 않음)."""
    out = []
    for i, seg in enumerate(segs):
        t = getattr(seg, "trans", None) or {}
        typ = t.get("type", "")
        if typ not in TRANS_NAME or typ == "none" or (i == 0 and typ not in FIRST_OK):
            out.append(None)
            continue
        d = max(TRANS_RANGE[0], min(TRANS_RANGE[1], float(t.get("dur", TRANS_DEFAULT_SEC))))
        lim = lengths[i] * 0.5 if i == 0 else min(lengths[i - 1], lengths[i]) * 0.5
        d = min(d, lim)
        out.append((typ, d) if d >= 0.07 else None)
    return out


@dataclass
class ImageSource:
    """스틸 소스(JPG/PNG). 보정·흔들림 보정 없음. width/height 는 EXIF 방향 반영 후 크기."""
    path: str
    width: int = 0
    height: int = 0
    orient: int = 1          # EXIF Orientation 1~8
    id: str = field(default_factory=_id)

    @property
    def name(self) -> str:
        return Path(self.path).name


def new_layer(img: str, fin: int, fout: int, scale: float = 1.0) -> dict:
    """이미지 레이어. 위치는 출력 화면 기준(cx, cy = 이미지 중심, 0~1), scale 1 = 출력 화면에서 원본 픽셀 크기.
    fin/fout = 원본 영상 프레임(fout 제외)."""
    return {"id": _id(), "img": img, "fin": int(fin), "fout": int(fout), "cx": 0.5, "cy": 0.5, "scale": float(scale)}


# ------------------------------------------------------------------ 타임라인 글자·이미지 / 음악 (시간 = 결과 영상 초)
TITLE_DEFAULT_SEC = 3.0
TITLE_FADE = 0.5
FONT_DEFAULT = "Pretendard"


def new_text(t0: float, t1: float, text: str = "") -> dict:
    return {"id": _id(), "kind": "text", "t0": float(t0), "t1": float(t1), "text": text, "font": FONT_DEFAULT,
            "size": 64, "bold": True, "color": "#ffffff", "bg": "shadow", "fade": TITLE_FADE, "cx": 0.5, "cy": 0.82}


def new_title_image(img: str, t0: float, t1: float, scale: float = 1.0) -> dict:
    return {"id": _id(), "kind": "image", "img": img, "t0": float(t0), "t1": float(t1), "fade": TITLE_FADE,
            "cx": 0.5, "cy": 0.5, "scale": float(scale)}


# v0.16.57 글자·사각형·이미지: 들어올 때(ain)·나갈 때(aout) = 페이드 대신 밀려 들어오기/나가기(움직이는 방향).
# 길이 = fade 값. 들어올 때 = 빠르게 출발해 부드럽게 멈춤(남은 거리 (1-u)^3), 나갈 때 = 천천히 출발해 빠르게(u^3). 화면 밖 ↔ 제자리.
ANIMS = ("fade", "right", "left", "up", "down")


def title_anim(d: dict, t: float):
    """t(초)에서 → (알파, 'in'|'out'|None, 방향, 거리 비율 0~1)."""
    t0, t1 = float(d["t0"]), float(d["t1"])
    fd = min(float(d.get("fade", 0.5)), (t1 - t0) / 2)
    if fd <= 0.01:
        return 1.0, None, "", 0.0
    ain, aout = d.get("ain", "fade"), d.get("aout", "fade")
    if t < t0 + fd:
        u = max(0.0, min(1.0, (t - t0) / fd))
        return (u, None, "", 0.0) if ain not in ANIMS[1:] else (1.0, "in", ain, (1 - u) ** 3)
    if t > t1 - fd:
        u = max(0.0, min(1.0, (t - (t1 - fd)) / fd))
        return (1 - u, None, "", 0.0) if aout not in ANIMS[1:] else (1.0, "out", aout, u ** 3)
    return 1.0, None, "", 0.0


def anim_offset(phase, key: str, f: float, box, ow: float, oh: float, pad: float = 0.0):
    """밀기 (dx, dy). box = (x, y, w, h) 제자리. 들어올 때 = 움직이는 방향의 반대쪽 화면 밖에서, 나갈 때 = 그 방향 화면 밖으로."""
    if not phase or f <= 0:
        return 0.0, 0.0
    x, y, w, h = box
    away = {"right": (ow - x + pad, 0.0), "left": (-(x + w + pad), 0.0), "up": (0.0, -(y + h + pad)), "down": (0.0, oh - y + pad)}
    if phase == "out":
        dx, dy = away.get(key, (0.0, 0.0))
    else:                                           # 들어옴 = 반대 방향으로 나가 있는 자리에서
        opp = {"right": "left", "left": "right", "up": "down", "down": "up"}.get(key, "")
        dx, dy = away.get(opp, (0.0, 0.0))
    return dx * f, dy * f


def new_rect(t0: float, t1: float) -> dict:
    """사각형 레이어(v0.16.34, 글자 배경용). cx·cy·w·h = 출력 화면 비율, radius = 1080 기준 px, opacity 0~1."""
    return {"id": _id(), "kind": "rect", "t0": float(t0), "t1": float(t1), "fade": TITLE_FADE,
            "cx": 0.5, "cy": 0.82, "w": 0.6, "h": 0.16, "color": "#000000", "opacity": 0.5, "radius": 0}


def new_music(path: str, t0: float, dur: float) -> dict:
    """off = 파일 안 시작 위치(초), len = 타임라인에서 쓰는 길이."""
    return {"id": _id(), "path": path, "t0": float(t0), "off": 0.0, "dur": float(dur), "len": float(dur)}


def default_mix() -> dict:
    """orig None = 자동(음악 없으면 1.0, 있으면 0.0)."""
    return {"orig": None, "music": 1.0, "fin": 0.5, "fout": 2.0, "xfade": 2.0,     # xfade = 곡을 이어 붙일 때 겹침(초, v0.16.64)
            "up_orig": 1.0, "up_music": 0.3}     # v0.16.66 말소리·수면 위 컷 = 원본 · 음악 볼륨


def orig_volume(mix: dict, music: list) -> float:
    v = (mix or {}).get("orig")
    return (0.0 if music else 1.0) if v is None else float(v)


def layer_box(layer: dict, img: "ImageSource", out_w: int, out_h: int) -> tuple[int, int, int, int]:
    """출력 화면에서 레이어 사각형 (x, y, w, h) 픽셀. scale 1 = 1080p 출력에서 원본 픽셀 크기
    (1440·4K 출력은 같은 비율로 커짐)."""
    k = min(out_w, out_h) / 1080
    w = max(2, int(round(img.width * layer["scale"] * k)))
    h = max(2, int(round(img.height * layer["scale"] * k)))
    return int(round(layer["cx"] * out_w - w / 2)), int(round(layer["cy"] * out_h - h / 2)), w, h


@dataclass
class Marker:
    """샘플 또는 스틸 위치."""
    src: str
    frame: int
    grade: dict = field(default_factory=dict)
    id: str = field(default_factory=_id)


@dataclass
class RenderItem:
    """렌더 예정 리스트의 출력 파일 1개."""
    name: str
    segs: list = field(default_factory=list)     # Segment 목록(보낼 때의 사본)
    orientation: str = "horizontal"
    audio: bool = True
    id: str = field(default_factory=_id)
    titles: list = field(default_factory=list)   # 타임라인 전체를 보낼 때만(사본)
    music: list = field(default_factory=list)
    mix: dict = field(default_factory=dict)
    done: str = ""                               # 렌더 끝난 파일 경로(프로젝트에 저장 → 다시 열어도 완료). "" = 대기
    lead: float = 0.0                            # v0.16.71 영상 앞 검은 구간(초, 타임라인 전체를 보낼 때 사본)
    dive: dict = field(default_factory=dict)     # v0.16.84 타임라인일 때 {"on", "off"} 사본(다이빙 기록은 프로젝트 것)


@dataclass
class OutputSettings:
    orientation: str = "horizontal"   # horizontal | vertical
    audio: bool = True
    encoder: str = "nvenc"            # nvenc | x264
    gpu_decode: bool = True
    folder: str = ""
    bitrate_mbps: int = 40
    prefix: str = ""                  # 렌더 파일명 앞에 붙일 명칭
    quality: str = "normal"           # v0.16.80 용량: high(예전 그대로) | normal | small — [렌더] 누를 때 고름


@dataclass
class Project:
    sources: list[Source] = field(default_factory=list)
    images: list[ImageSource] = field(default_factory=list)   # 스틸 소스
    segments: list[Segment] = field(default_factory=list)     # 타임라인
    render_items: list[RenderItem] = field(default_factory=list)
    samples: list[Marker] = field(default_factory=list)
    stills: list[Marker] = field(default_factory=list)
    audios: list = field(default_factory=list)       # 음악 소스 [{"id", "path", "dur"}]
    titles: list = field(default_factory=list)       # 타임라인 글자·이미지 줄
    music: list = field(default_factory=list)        # 타임라인 음악 줄
    mix: dict = field(default_factory=default_mix)   # 원본·음악 볼륨, 음악 페이드
    grade: dict = field(default_factory=load_default_grade)
    output: OutputSettings = field(default_factory=lambda: load_default_output())
    file: str = ""
    lead: float = 0.0                                # v0.16.71 첫 컷 앞 검은 구간(초) — 글자·음악을 0초 앞으로 끌면 생김
    tl_out: str = ""                                 # v0.16.72 타임라인 출력("" = 첫 컷 소스를 따라감)
    dives: list = field(default_factory=list)        # v0.16.84 다이빙 기록(FIT·DTMD) → 수심 그래프(divelog 형식)
    dive_on: bool = True                             # 수심 그래프 넣기
    dive_off: float = 0.0                            # 시각 맞춤(초): 카메라 시계 − 다이빙 컴퓨터 시계 차이 보정

    def tail_of(self, titles=None, video_end: float | None = None) -> float:
        """영상 끝 뒤 검은 구간(초) = 글자·사각형·이미지가 영상 끝을 넘은 만큼(음악은 안 늘림)."""
        titles = self.titles if titles is None else titles
        end = (self.lead + self.out_seconds()) if video_end is None else video_end
        return max(0.0, max([float(t["t1"]) for t in titles] + [0.0]) - end)

    def normalize_lead(self) -> bool:
        """v0.16.71: 0초 앞으로 나간 글자·음악 = 그만큼 앞 검은 구간을 늘리고 모두 뒤로 밂.
        앞 검은 구간이 필요 없어지면(모든 글자·음악이 그보다 뒤) 줄이고 모두 앞으로. 바뀌었으면 True."""
        items = list(self.titles) + list(self.music)
        mn = min([float(d["t0"]) for d in items] + [float("inf")])
        if mn < -1e-6:
            sh = -mn
        elif self.lead > 1e-6:
            sh = -min(self.lead, mn)
        else:
            return False
        if abs(sh) < 1e-6:
            return False
        self.lead = round(max(0.0, self.lead + sh), 4)
        for d in self.titles:
            d["t0"], d["t1"] = round(float(d["t0"]) + sh, 4), round(float(d["t1"]) + sh, 4)
        for m in self.music:
            m["t0"] = round(float(m["t0"]) + sh, 4)
        return True

    # ---- 조회 ----
    def out_of(self, src) -> str:
        """소스의 출력(v0.16.55 소스별): 소스 값 → 없으면 프로젝트 출력. 원본보다 큰 가로는 낮춤."""
        key = (getattr(src, "out", "") if src is not None else "") or rotate_for(self.output.orientation, src)   # v0.16.70 세로 촬영 = 돌린 크기
        return clamp_src(key, src)

    def source(self, sid: str) -> Source | None:
        return next((s for s in self.sources if s.id == sid), None)

    def image(self, iid: str) -> ImageSource | None:
        return next((m for m in self.images if m.id == iid), None)


    # ---- 보정값 병합: 기본값 → 클립 → (스틸) ----
    def grade_for_source(self, sid: str, frame: float | None = None, off=True, seg=None) -> dict:
        """기본값 → 클립. frame 을 주면 색 키프레임까지 반영.
        off=True 면 잠시 끈 항목을 뺌(seg 를 주면 그 컷에 복사된 꺼짐 목록, 아니면 클립의 지금 목록)."""
        g = dict(self.grade)
        s = self.source(sid)
        if s and seg is not None and getattr(seg, "grade", None):     # 렌더 리스트 = 보낼 때 사본
            g.update(copy.deepcopy(seg.grade))
            _stab_cap(g, s)
            return apply_off(g, seg.off) if off else g
        if s:
            g.update(s.grade)
            _stab_cap(g, s)                   # 흔들림 보정 한계(프리셋별) — 저장된 값이 커도 여기서 자름
            if frame is not None and s.gkeys:
                g = grade_at(g, s.gkeys, frame)
            if off:
                g = apply_off(g, seg.off if seg is not None else s.off)
        return g

    def snap_seg(self, seg: "Segment") -> "Segment":
        """컷에 지금 클립의 보정값·색 키프레임·꺼 둔 항목을 사본으로(렌더 리스트로 보낼 때, '지금 보정값으로')."""
        s = self.source(seg.src)
        if s:
            seg.grade = copy.deepcopy(self.grade_for_source(s.id, off=False))
            seg.gkeys = copy.deepcopy(s.gkeys)
            seg.off = list(s.off)
        return seg

    def seg_stale(self, seg: "Segment") -> bool:
        """보낸 뒤 클립 보정값이 바뀌었나(렌더 리스트 노란 점)."""
        s = self.source(seg.src)
        if not s or not getattr(seg, "grade", None):
            return False
        return (seg.grade != self.grade_for_source(s.id, off=False) or seg.gkeys != s.gkeys
                or sorted(seg.off) != sorted(s.off))

    def grade_for_still(self, still: Marker) -> dict:
        g = self.grade_for_source(still.src)
        g.update(still.grade)
        return g

    # ---- 길이 ----
    @staticmethod
    def seg_out_seconds(seg: Segment, fps: Fraction) -> float:
        return float(seg.frames / fps / Fraction(seg.speed))

    def segs_seconds(self, segs) -> float:
        """결과 길이(화면 전환 겹침만큼 줄어듦)."""
        segs = [g for g in segs if self.source(g.src) and self.source(g.src).frames]
        lens = [self.seg_out_seconds(g, self.source(g.src).fps) for g in segs]
        overlap = sum(t[1] for i, t in enumerate(plan_transitions(segs, lens)) if t and i > 0)
        return sum(lens) - overlap

    def out_seconds(self, sid: str | None = None) -> float:
        return self.segs_seconds([g for g in self.segments if not sid or g.src == sid])

    # ---- 저장 ----
    def to_dict(self) -> dict:
        return {
            "version": 2,
            "sources": [asdict(s) for s in self.sources],
            "images": [asdict(m) for m in self.images],
            "segments": [asdict(s) for s in self.segments],
            "render_items": [asdict(r) for r in self.render_items],
            "samples": [asdict(s) for s in self.samples],
            "stills": [asdict(s) for s in self.stills],
            "titles": self.titles, "music": self.music, "mix": self.mix, "audios": self.audios,
            "grade": self.grade,
            "output": asdict(self.output), "lead": self.lead, "tl_out": self.tl_out, "loud_rev": 2,
            "dives": self.dives, "dive_on": self.dive_on, "dive_off": self.dive_off,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.sources = [Source(**{k: v for k, v in s.items() if k in Source.__dataclass_fields__}) for s in d.get("sources", [])]
        p.images = [ImageSource(**m) for m in d.get("images", [])]
        for s in p.sources:
            upgrade_grade(s.grade)
            set_name_hint(s.path, s.ctime)
        p.segments = [Segment(**s) for s in d.get("segments", [])]
        if int(d.get("loud_rev", 1)) < 2:                 # v0.16.77 예전 '말소리' 판단 = 다시(물속 화면이면 안 키움)
            for g in p.segments:
                if g.why == "말소리":
                    g.loud, g.why = None, ""
        p.render_items = []
        for r in d.get("render_items", []):
            r = dict(r)
            r["segs"] = [Segment(**g) if isinstance(g, dict) else g for g in r.get("segs", [])]
            p.render_items.append(RenderItem(**r))
        p.samples = [Marker(**s) for s in d.get("samples", [])]
        p.stills = [Marker(**s) for s in d.get("stills", [])]
        p.titles = list(d.get("titles", []))
        p.audios = list(d.get("audios", []))
        p.music = list(d.get("music", []))
        p.mix = {**default_mix(), **d.get("mix", {})}
        p.lead = float(d.get("lead", 0.0) or 0.0)
        p.tl_out = str(d.get("tl_out", "") or "")
        p.dives = [x for x in d.get("dives", []) if isinstance(x, dict) and x.get("pts")]
        p.dive_on = bool(d.get("dive_on", True))
        p.dive_off = float(d.get("dive_off", 0.0) or 0.0)
        g = dict(FACTORY_GRADE)
        g.update(upgrade_grade(dict(d.get("grade", {}))))
        p.grade = g
        o = {k: v for k, v in d.get("output", {}).items() if k in OutputSettings.__dataclass_fields__}
        p.output = OutputSettings(**o)
        return p

    def save(self, file: str) -> None:
        self.file = file
        write_json_atomic(file, self.to_dict())

    @classmethod
    def load(cls, file: str) -> "Project":
        p = cls.from_dict(json.loads(Path(file).read_text(encoding="utf-8")))
        p.file = file
        return p


_NAME_HINT: dict = {}      # 경로 → YYYYMMDDhhmm (이름에 날짜가 없는 파일: 파일 안의 만든 시각, v0.16.55)


def set_name_hint(path: str, ts: str) -> None:
    if ts and len(ts) == 12 and ts.isdigit():
        _NAME_HINT[os.path.abspath(path)] = ts


def name_has_date(path: str) -> bool:
    stem = Path(path).stem
    return bool(re.search(r"(?<!\d)(\d{14})(?!\d)", stem) or re.search(r"(?<!\d)(\d{12})", stem)
                or re.search(r"(?<!\d)(20\d{6})_(\d{6})(?!\d)", stem))


def short_name(path: str) -> str:
    """파일명에서 날짜·시간(YYYYMMDDhhmm) 추출. DJI_20261025100118_0148_D → 202610251001.
    이름에 날짜가 없으면(폰을 거친 파일 등) 파일 안의 만든 시각(set_name_hint), 그것도 없으면 이름 그대로."""
    stem = Path(path).stem
    if not name_has_date(path):
        return _NAME_HINT.get(os.path.abspath(path), stem)
    m = re.search(r"(?<!\d)(\d{14})(?!\d)", stem) or re.search(r"(?<!\d)(\d{12})", stem)
    if m:
        return m.group(1)[:12]
    m = re.search(r"(?<!\d)(20\d{6})_(\d{6})(?!\d)", stem)       # Insta360: VID_20260917_080520_006 → 202609170805 (v0.16.50)
    return m.group(1) + m.group(2)[:4] if m else stem


def spaced(n: str) -> str:
    """읽기 쉽게: 202610251207 → 2026 1025 1207 (숫자 12자리만, 나머지 그대로)."""
    return " ".join(n[i:i + 4] for i in range(0, len(n), 4)) if n.isdigit() and len(n) == 12 else n


def display_name(path: str) -> str:
    """목록 표시용: 202610251207 → 2026 1025 1207"""
    return spaced(short_name(path))


def speed_label(sp: float) -> str:
    return {2.0: "x2", 1.0: "x1", 0.5: "x1/2"}.get(sp, f"x{sp:g}")


def timecode(frame: int, fps: Fraction) -> str:
    """mm:ss.ff (ff = 원본 프레임, 0~59)"""
    fr = max(0, int(frame))
    fps_round = round(float(fps))
    sec_total = float(fr / fps)
    m = int(sec_total // 60)
    s = int(sec_total % 60)
    f = fr - int(round((m * 60 + s) * float(fps)))
    f = max(0, min(fps_round - 1, f))
    return f"{m:02d}:{s:02d}.{f:02d}"


# ------------------------------------------------------------------ 따라감(v0.16.67): 컷 길이가 바뀌면 'follow' 켠 글자·사각형·이미지·음악이 따라 움직임
def cut_spans(project, segs=None) -> list:
    """타임라인 컷 → [(컷 id, 시작 초, 길이 초)] (전환 겹침 반영). 소스 없는 컷은 뺌."""
    p = project
    segs = [g for g in (p.segments if segs is None else segs) if p.source(g.src) and p.source(g.src).frames]
    lens = [p.seg_out_seconds(g, p.source(g.src).fps) for g in segs]
    plan = plan_transitions(segs, lens)
    out, t = [], float(getattr(p, "lead", 0.0) or 0.0)
    for i, (g, ln, tr) in enumerate(zip(segs, lens, plan)):
        if i > 0 and tr:
            t -= tr[1]
        out.append((g.id, t, ln))
        t += ln
    return out


def _anchor(spans, t: float, end: bool = False):
    """시각 t → (컷 id, 컷 시작부터 거리). 끝(end)이 타임라인 끝에 붙어 있으면 ('END', 끝부터 거리)."""
    total = max((s + ln for _c, s, ln in spans), default=0.0)
    if end and spans and t >= total - 1e-3:
        return ("END", t - total)
    cur = None
    for cid, s, _ln in spans:
        if s <= t + 1e-6:
            cur = (cid, t - s)
    return cur or ("", t)


def follow_anchors(project) -> dict:
    """변경 전에 부름: 따라감 켠 항목의 자리를 컷 기준으로 적어 둠."""
    spans = cut_spans(project)
    order = [c for c, _s, _l in spans]
    items = {}
    for d in project.titles:
        if d.get("follow"):
            items[d["id"]] = ("title", _anchor(spans, float(d["t0"])), float(d["t1"]) - float(d["t0"]))
    for m in project.music:
        if m.get("follow"):
            t0, ln = float(m["t0"]), float(m["len"])
            items[m["id"]] = ("music", _anchor(spans, t0), _anchor(spans, t0 + ln, end=True), t0, ln)
    return {"order": order, "items": items}


def _place(spans, order, a) -> float:
    cid, off = a
    if not cid:
        return off
    total = max((s + ln for _c, s, ln in spans), default=0.0)
    if cid == "END":
        return total + off
    start = {c: s for c, s, _l in spans}
    if cid in start:
        return start[cid] + off
    i = order.index(cid) if cid in order else -1             # 지운 컷 = 그 자리(다음 남은 컷 시작)
    nxt = next((start[c] for c in order[i + 1:] if c in start), None) if i >= 0 else None
    return (total if nxt is None else nxt) + off


def follow_apply(project, anchors: dict) -> None:
    """변경 뒤에 부름. 글자·사각형·이미지 = 시작이 따라가고 길이 그대로.
    음악 = 시작이 따라감, 끝은 곡 뒤를 늘리거나 줄여 맞춤(곡이 모자라면 곡 끝까지)."""
    if not anchors or not anchors.get("items"):
        return
    spans = cut_spans(project)
    order = anchors["order"]
    it = anchors["items"]
    for d in project.titles:
        a = it.get(d["id"])
        if a and a[0] == "title":
            t0 = max(0.0, _place(spans, order, a[1]))
            d["t0"], d["t1"] = round(t0, 4), round(t0 + a[2], 4)
    for m in project.music:
        a = it.get(m["id"])
        if a and a[0] == "music":
            t0 = max(0.0, _place(spans, order, a[1]))
            end = _place(spans, order, a[2])
            room = float(m.get("dur", a[4])) - float(m.get("off", 0))
            m["t0"] = round(t0, 4)
            m["len"] = round(max(0.2, min(room, end - t0)), 4)
