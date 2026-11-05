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
VIDEO_EXT = {".mp4", ".mov"}

NR_LEVELS = ["off", "weak", "mid", "strong"]   # strong 은 스틸 전용
# 옛 디노이즈 단계 → (색 노이즈, 밝기 노이즈) 0~100
NR_LEGACY = {"off": (0, 0), "weak": (60, 25), "mid": (80, 45), "strong": (100, 70)}

GRADE_KEYS = ["lut", "r_gain", "b_gain", "hue", "curve", "nr_chroma", "nr_luma", "sharpen", "stab"]

FACTORY_GRADE = {
    "lut": "",
    "r_gain": 1.0,
    "b_gain": 1.0,
    "hue": 0.0,
    "curve": [[0.0, 0.0], [1.0, 1.0]],
    "nr_chroma": 60,     # 색 노이즈(푸른 물속의 보라·빨강 점) 0~100
    "nr_luma": 25,       # 밝기 노이즈 0~100
    "sharpen": 0.3,      # 밝기에만 적용
    "stab": 0,           # 흔들림 보정 0(끔)~100, 렌더에만 적용
}


def upgrade_grade(g: dict) -> dict:
    """옛 'nr'(끔/약/중/강) → nr_chroma/nr_luma."""
    if "nr" in g:
        c, l = NR_LEGACY.get(g.pop("nr"), (60, 25))
        g.setdefault("nr_chroma", c)
        g.setdefault("nr_luma", l)
    return g


def load_default_grade() -> dict:
    """사용자가 '새 프로젝트 기본값'으로 저장한 값. 없으면 공장값."""
    p = paths.settings_path()
    g = dict(FACTORY_GRADE)
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            g.update({k: v for k, v in upgrade_grade(dict(s.get("default_grade", {}))).items() if k in GRADE_KEYS})
        except Exception:
            pass
    return g


def save_default_grade(grade: dict) -> None:
    p = paths.settings_path()
    s = {}
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            s = {}
    s["default_grade"] = {k: grade[k] for k in GRADE_KEYS}
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


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

    @property
    def frames(self) -> int:
        return max(0, self.fout - self.fin)

    def copy(self) -> "Segment":
        return Segment(self.src, self.fin, self.fout, self.speed, layers=copy.deepcopy(self.layers),
                       trans=dict(self.trans), reframe=copy.deepcopy(self.reframe))


# 세로 크롭 위치 이동(리프레이밍). 4K 기준 ±540px(그 이상은 액션캠 가장자리 왜곡)
REFRAME_MAX_4K = 540


def reframe_max(src_width: int) -> float:
    return REFRAME_MAX_4K * src_width / 3840


def ease(u: float) -> float:
    """키프레임 사이 곡선 이동(smoothstep). ffmpeg 식(ff.reframe_expr)과 같은 함수."""
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


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


def layer_box(layer: dict, img: "ImageSource", out_w: int, out_h: int) -> tuple[int, int, int, int]:
    """출력 화면에서 레이어 사각형 (x, y, w, h) 픽셀."""
    w = max(2, int(round(img.width * layer["scale"])))
    h = max(2, int(round(img.height * layer["scale"])))
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
    grade: dict = field(default_factory=load_default_grade)
    output: OutputSettings = field(default_factory=OutputSettings)
    file: str = ""

    # ---- 조회 ----
    def source(self, sid: str) -> Source | None:
        return next((s for s in self.sources if s.id == sid), None)

    def image(self, iid: str) -> ImageSource | None:
        return next((m for m in self.images if m.id == iid), None)

    def segments_of(self, sid: str) -> list[Segment]:
        return [g for g in self.segments if g.src == sid]

    # ---- 보정값 병합: 기본값 → 클립 → (스틸) ----
    def grade_for_source(self, sid: str) -> dict:
        g = dict(self.grade)
        s = self.source(sid)
        if s:
            g.update(s.grade)
        return g

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
            "grade": self.grade,
            "output": asdict(self.output),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.sources = [Source(**s) for s in d.get("sources", [])]
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


def display_name(path: str) -> str:
    """목록 표시용: 202610251207 → 2026 1025 1207"""
    n = short_name(path)
    return " ".join(n[i:i + 4] for i in range(0, len(n), 4)) if n.isdigit() else n


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
