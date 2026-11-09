"""프로젝트 데이터 구조. 모든 위치는 원본 기준 '프레임 번호'로 저장한다."""
from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

from . import paths

MAX_SAMPLES = 5
MAX_CURVE_POINTS = 5          # 양 끝점을 제외한 조정 포인트 수
OUTPUT_LIMIT_SEC = 30.0
OUT_FPS = Fraction(30000, 1001)  # 59.94 원본 → 29.97 출력

SPEEDS = [2.0, 1.0, 0.5]

MAX_LAYERS = 3                  # 영상 1개에 얹을 수 있는 이미지 레이어 수
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".aac"}
VIDEO_EXT = {".mp4", ".mov"}

NR_LEVELS = ["off", "weak", "mid", "strong"]   # strong 은 스틸 전용
# 옛 디노이즈 단계 → (색 노이즈, 밝기 노이즈) 0~100
NR_LEGACY = {"off": (0, 0), "weak": (60, 25), "mid": (80, 45), "strong": (100, 70)}

GRADE_KEYS = ["lut", "r_gain", "b_gain", "hue", "sat", "water", "gy", "curve", "nr_chroma", "nr_luma", "wnr", "sharpen", "dehaze", "lens", "stab"]

# 출력: orientation 값 하나로 방향·크기를 함께 나타냄
OUTPUTS = [("horizontal", "1920×1080"), ("horizontal1440", "2560×1440"), ("horizontal2160", "3840×2160"),
           ("vertical", "1080×1920")]

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
OFFABLE = [k for k in NEUTRAL if k not in ("curve", "dehaze")]        # 이름을 눌러 잠시 끌 수 있는 항목(슬라이더)


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
    p = paths.settings_path()
    g = dict(FACTORY_GRADE)
    if not (paths.lut_dir() / DEFAULT_LUT).exists():
        g["lut"] = ""
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            if int(s.get("defaults_rev", 0)) < DEFAULTS_REV:
                return g
            g.update({k: v for k, v in upgrade_grade(dict(s.get("default_grade", {}))).items() if k in GRADE_KEYS})
        except Exception:
            pass
    return g


def get_setting(key: str, default=None):
    p = paths.settings_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")).get(key, default) if p.exists() else default
    except Exception:  # noqa: BLE001
        return default


def set_setting(key: str, value) -> None:
    p = paths.settings_path()
    try:
        s = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        s = {}
    s[key] = value
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def save_default_grade(grade: dict) -> None:
    p = paths.settings_path()
    s = {}
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            s = {}
    s["default_grade"] = {k: grade[k] for k in GRADE_KEYS}
    s["defaults_rev"] = DEFAULTS_REV
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


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
    out: str = ""                                # AUTO 전체렌더 출력(orientation). "" = 프로젝트 출력
    off: list = field(default_factory=list)      # 이름을 눌러 잠시 끈 보정 항목(미리보기·보낼 때 빼고 적용)
    lut_mode: str = ""                           # DJI 메타로 판단한 색 모드 dlog | normal | unknown ("" = 옛 프로젝트, 판단 안 함)
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

    @property
    def frames(self) -> int:
        return max(0, self.fout - self.fin)

    def copy(self) -> "Segment":
        return Segment(self.src, self.fin, self.fout, self.speed, layers=copy.deepcopy(self.layers),
                       trans=dict(self.trans), reframe=copy.deepcopy(self.reframe), gkeys=copy.deepcopy(self.gkeys),
                       off=list(self.off), grade=copy.deepcopy(self.grade))


# 세로 크롭 위치 이동(리프레이밍). 4K 기준 ±540px(그 이상은 액션캠 가장자리 왜곡)
REFRAME_MAX_4K = 540


def reframe_max(src_width: int) -> float:
    return REFRAME_MAX_4K * src_width / 3840


def ease(u: float) -> float:
    """키프레임 사이 곡선 이동(smoothstep). ffmpeg 식(ff.reframe_expr)과 같은 함수."""
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


KEYABLE = ["r_gain", "b_gain", "hue", "sat", "water", "gy"]     # 시간에 따라 바뀌는 보정(◆)


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


def grade_at(g: dict, gkeys: dict, f: float) -> dict:
    """프레임 f 의 보정값(색 키프레임 반영)."""
    if not gkeys:
        return g
    g = dict(g)
    for k in KEYABLE:
        v = key_at(gkeys.get(k) or [], f)
        if v is not None:
            g[k] = v
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
TRANSITIONS = [("none", "없음"), ("dissolve", "디졸브"),
               ("wipeleft", "커튼 ←"), ("wiperight", "커튼 →"), ("wipeup", "커튼 ↑"), ("wipedown", "커튼 ↓"),
               ("zoomin", "빠른 줌인"), ("zoomout", "빠른 줌아웃"),
               ("rotzoomin", "회전 줌인"), ("rotzoomout", "회전 줌아웃"),
               ("fadeblack", "페이드아웃·인"), ("fadewhite", "화이트아웃·인")]
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


def new_music(path: str, t0: float, dur: float) -> dict:
    """off = 파일 안 시작 위치(초), len = 타임라인에서 쓰는 길이."""
    return {"id": _id(), "path": path, "t0": float(t0), "off": 0.0, "dur": float(dur), "len": float(dur)}


def default_mix() -> dict:
    """orig None = 자동(음악 없으면 1.0, 있으면 0.0)."""
    return {"orig": None, "music": 1.0, "fin": 0.5, "fout": 2.0}


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


@dataclass
class OutputSettings:
    orientation: str = "horizontal"   # horizontal | vertical
    audio: bool = True
    encoder: str = "nvenc"            # nvenc | x264
    gpu_decode: bool = True
    folder: str = ""
    bitrate_mbps: int = 40
    prefix: str = ""                  # 렌더 파일명 앞에 붙일 명칭


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

    # ---- 조회 ----
    def source(self, sid: str) -> Source | None:
        return next((s for s in self.sources if s.id == sid), None)

    def image(self, iid: str) -> ImageSource | None:
        return next((m for m in self.images if m.id == iid), None)

    def segments_of(self, sid: str) -> list[Segment]:
        return [g for g in self.segments if g.src == sid]

    # ---- 보정값 병합: 기본값 → 클립 → (스틸) ----
    def grade_for_source(self, sid: str, frame: float | None = None, off=True, seg=None) -> dict:
        """기본값 → 클립. frame 을 주면 색 키프레임까지 반영.
        off=True 면 잠시 끈 항목을 뺌(seg 를 주면 그 컷에 복사된 꺼짐 목록, 아니면 클립의 지금 목록)."""
        g = dict(self.grade)
        s = self.source(sid)
        if s and seg is not None and getattr(seg, "grade", None):     # 렌더 리스트 = 보낼 때 사본
            g.update(copy.deepcopy(seg.grade))
            return apply_off(g, seg.off) if off else g
        if s:
            g.update(s.grade)
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
            "output": asdict(self.output),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.sources = [Source(**{k: v for k, v in s.items() if k in Source.__dataclass_fields__}) for s in d.get("sources", [])]
        p.images = [ImageSource(**m) for m in d.get("images", [])]
        for s in p.sources:
            upgrade_grade(s.grade)
        p.segments = [Segment(**s) for s in d.get("segments", [])]
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
        g = dict(FACTORY_GRADE)
        g.update(upgrade_grade(dict(d.get("grade", {}))))
        p.grade = g
        o = {k: v for k, v in d.get("output", {}).items() if k in OutputSettings.__dataclass_fields__}
        p.output = OutputSettings(**o)
        return p

    def save(self, file: str) -> None:
        self.file = file
        Path(file).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, file: str) -> "Project":
        p = cls.from_dict(json.loads(Path(file).read_text(encoding="utf-8")))
        p.file = file
        return p


def short_name(path: str) -> str:
    """파일명에서 날짜·시간(YYYYMMDDhhmm) 추출. DJI_20261025100118_0148_D → 202610251001"""
    stem = Path(path).stem
    m = re.search(r"(?<!\d)(\d{14})(?!\d)", stem) or re.search(r"(?<!\d)(\d{12})", stem)
    return m.group(1)[:12] if m else stem


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
