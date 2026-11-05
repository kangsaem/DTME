"""실행 위치·외부 도구(ffmpeg) 경로 관리. 설치 없이 폴더째 실행하는 구조."""
import os
import shutil
import sys
from pathlib import Path


def app_dir() -> Path:
    """exe(배포) 또는 저장소 루트(개발) 위치."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bin_dir() -> Path:
    return app_dir() / "bin"


def lut_dir() -> Path:
    d = app_dir() / "luts"
    d.mkdir(exist_ok=True)
    return d


def cache_dir() -> Path:
    d = app_dir() / "cache"
    d.mkdir(exist_ok=True)
    return d


def settings_path() -> Path:
    return app_dir() / "settings.json"


def _tool(name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    local = bin_dir() / exe
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{exe} 를 찾을 수 없습니다. bin 폴더에 넣어주세요.")


def ffmpeg() -> str:
    return _tool("ffmpeg")


def ffprobe() -> str:
    return _tool("ffprobe")
