"""글꼴: fonts/ 폴더(기본 무료 글꼴 + 사용자가 추가한 것) + Windows 맑은 고딕.
렌더(ffmpeg drawtext)는 글꼴 '파일'이 필요하므로 이름이 아니라 파일로 관리한다."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import paths

FONT_EXT = {".ttf", ".otf", ".ttc"}
# 파일 이름 앞부분 → 보여줄 이름
NICE = {"Pretendard": "Pretendard", "NotoSansKR": "Noto Sans KR", "BlackHanSans": "Black Han Sans",
        "Montserrat": "Montserrat", "Inter": "Inter", "TeXGyreHeros": "TeX Gyre Heros",
        # v0.16.67 Google Fonts(OFL) 9개
        "DoHyeon": "도현", "Jua": "주아", "Gugi": "구기", "Dokdo": "독도", "YeonSung": "연성", "Gaegu": "개구",
        "GamjaFlower": "감자꽃", "HiMelody": "하이멜로디", "KirangHaerang": "기랑해랑"}
ORDER = ["Pretendard", "Noto Sans KR", "Black Han Sans", "Montserrat", "Inter", "TeX Gyre Heros", "맑은 고딕",
         "도현", "주아", "구기", "독도", "연성", "개구", "감자꽃", "하이멜로디", "기랑해랑"]


def _family_of(stem: str) -> tuple[str, bool]:
    """'Pretendard-Bold' → ('Pretendard', True)"""
    m = re.match(r"^(.*?)[-_ ]?(Regular|Bold|Medium|Light|SemiBold|Black)?$", stem, re.I)
    base, w = (m.group(1), m.group(2)) if m else (stem, None)
    return NICE.get(base, base or stem), bool(w and w.lower() == "bold")


def list_fonts() -> dict[str, dict]:
    """{보여줄 이름: {"regular": 경로, "bold": 경로 또는 None}}"""
    out: dict[str, dict] = {}
    for f in sorted(paths.fonts_dir().iterdir()):
        if f.suffix.lower() not in FONT_EXT:
            continue
        fam, bold = _family_of(f.stem)
        d = out.setdefault(fam, {"regular": None, "bold": None})
        if bold:
            d["bold"] = str(f)
        elif d["regular"] is None or "regular" in f.stem.lower():
            d["regular"] = str(f)
    win = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if (win / "malgun.ttf").exists():
        out["맑은 고딕"] = {"regular": str(win / "malgun.ttf"),
                         "bold": str(win / "malgunbd.ttf") if (win / "malgunbd.ttf").exists() else None}
    for d in out.values():
        if d["regular"] is None:
            d["regular"] = d["bold"]
    return dict(sorted(out.items(), key=lambda kv: (ORDER.index(kv[0]) if kv[0] in ORDER else 99, kv[0].lower())))


def font_file(family: str, bold: bool) -> tuple[str, bool]:
    """(파일, 진짜 굵은 글꼴인지). 굵은 파일이 없으면 보통 파일 + 가짜 굵게(테두리)."""
    fs = list_fonts()
    d = fs.get(family) or fs.get("Pretendard") or (next(iter(fs.values())) if fs else None)
    if d is None:
        return "", False
    if bold and d.get("bold"):
        return d["bold"], True
    return d["regular"], False


def add_font(path: str) -> str:
    dst = paths.fonts_dir() / Path(path).name
    if Path(path).resolve() != dst.resolve():
        shutil.copyfile(path, dst)
    return _family_of(dst.stem)[0]


_QT_FAM: dict = {}


def family_of_file(name: str) -> str:
    """fonts/ 안 글꼴 파일 → Qt 글꼴 이름(처음 한 번 등록). 없으면 ''(기본 글꼴).
    등록은 화면 스레드에서 먼저(dive_draw.ensure_fonts) — 렌더 스레드는 등록된 이름만 씀."""
    if name in _QT_FAM:
        return _QT_FAM[name]
    from PySide6.QtGui import QFontDatabase
    f = paths.fonts_dir() / name
    fam = ""
    if f.exists():
        fid = QFontDatabase.addApplicationFont(str(f))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        fam = fams[0] if fams else ""
    _QT_FAM[name] = fam
    return fam
