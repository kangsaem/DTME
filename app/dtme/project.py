"""프로젝트 데이터 구조. 모든 위치는 원본 기준 '프레임 번호'로 저장한다."""
from __future__ import annotations

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

    @property
    def frames(self) -> int:
        return max(0, self.fout - self.fin)


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
        total = 0.0
        for seg in segs:
            s = self.source(seg.src)
            if s and s.frames:
                total += self.seg_out_seconds(seg, s.fps)
        return total

    def out_seconds(self, sid: str | None = None) -> float:
        return self.segs_seconds([g for g in self.segments if not sid or g.src == sid])

    # ---- 저장 ----
    def to_dict(self) -> dict:
        return {
            "version": 2,
            "sources": [asdict(s) for s in self.sources],
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
