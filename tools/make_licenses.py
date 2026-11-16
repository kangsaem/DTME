"""빌드에 LICENSES 폴더 만들기(v0.16.95).
사용: python tools/make_licenses.py <dist/DTME> <ffmpeg 압축 푼 폴더(LICENSE.txt 있는 곳)> [받아 둔 LGPL·GPL 글 폴더]
- ffmpeg: zip 안 LICENSE.txt(GPL v3) + `ffmpeg -version` 기록 + 소스 받는 곳(FFmpeg 커밋 · BtbN 빌드 스크립트)
- Qt(PySide6·shiboken6): LGPL v3(+GPL v3, LGPL 이 참조) 글 + 소스 받는 곳
- numpy: dist-info 의 licenses 폴더 통째(안에 넣은 수학 라이브러리 표시 포함)
- Python: 설치 폴더의 LICENSE.txt
- 글꼴·음악·LUT: 이미 각 폴더에 들어감 → README 에 안내만
"""
import importlib.metadata as md
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _ver(name: str) -> str:
    try:
        return md.version(name)
    except Exception:  # noqa: BLE001
        return "?"


def ffmpeg_info(exe: Path) -> tuple[str, str, str]:
    """(첫 줄, configuration 줄, 소스 커밋 링크)."""
    try:
        out = subprocess.run([str(exe), "-hide_banner", "-version"], capture_output=True, text=True, timeout=30).stdout
    except Exception as e:  # noqa: BLE001
        return f"(ffmpeg -version 실패: {e})", "", ""
    lines = out.splitlines()
    first = lines[0] if lines else ""
    conf = next((x for x in lines if x.startswith("configuration:")), "")
    m = re.search(r"-g([0-9a-f]{7,40})", first)
    link = f"https://github.com/FFmpeg/FFmpeg/commit/{m.group(1)}" if m else "https://github.com/FFmpeg/FFmpeg"
    return first, conf, link


def main(dist: str, ffdir: str, texts: str = "") -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # Windows 콘솔(cp1252) = 한글 출력 실패 방지
    except Exception:  # noqa: BLE001
        pass
    dist_p, ff_p = Path(dist), Path(ffdir)
    out = dist_p / "LICENSES"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    tx = Path(texts) if texts else None

    # ffmpeg
    (out / "ffmpeg").mkdir()
    lic = min(ff_p.rglob("LICENSE*"), key=lambda q: (len(q.parts), str(q)), default=None)     # zip 맨 위 LICENSE.txt
    if lic:
        shutil.copy(lic, out / "ffmpeg" / "LICENSE.txt")
    first, conf, link = ffmpeg_info(dist_p / "bin" / "ffmpeg.exe")
    (out / "ffmpeg" / "version.txt").write_text(f"{first}\n{conf}\n", encoding="utf-8")

    # Qt (PySide6 · shiboken6)
    (out / "Qt-PySide6").mkdir()
    for name in ("lgpl-3.0.txt", "gpl-3.0.txt"):
        if tx and (tx / name).exists():
            shutil.copy(tx / name, out / "Qt-PySide6" / name)

    # numpy
    try:
        d = md.distribution("numpy")
        base = Path(d.locate_file(""))
        for f in d.files or []:
            s = str(f)
            if "licenses" in s.replace("\\", "/").split("/") or s.upper().endswith(("LICENSE.TXT", "LICENSE")):
                src = base / f
                if src.is_file():
                    rel = Path(*Path(s).parts[1:]) if len(Path(s).parts) > 1 else Path(s)
                    dst = out / "numpy" / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(src, dst)
    except Exception as e:  # noqa: BLE001
        print("numpy 라이선스 복사 실패:", e)

    # Python
    (out / "Python").mkdir()
    for cand in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if cand.exists():
            shutil.copy(cand, out / "Python" / "LICENSE.txt")
            break

    pyside = _ver("PySide6")
    readme = f"""DTME — 들어 있는 다른 프로그램과 라이선스 / Third-party components and licenses

1. FFmpeg (bin/ffmpeg.exe, bin/ffprobe.exe) — GPL v3 (x264·x265 등 포함 빌드)
   버전 / version: {first}
   소스 / source: {link}
   빌드 스크립트 / build scripts: https://github.com/BtbN/FFmpeg-Builds
   라이선스 전문: LICENSES/ffmpeg/LICENSE.txt · 빌드 설정: LICENSES/ffmpeg/version.txt
   DTME 는 ffmpeg 를 별도 프로그램으로 실행합니다. ffmpeg.exe 는 GPL 에 따라 자유롭게 다시 배포할 수 있습니다.
   DTME runs ffmpeg as a separate program. You may redistribute ffmpeg.exe under the GPL.

2. Qt for Python (PySide6 {pyside}, shiboken6 {_ver('shiboken6')}) — LGPL v3
   소스 / source: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v{pyside} · https://download.qt.io/official_releases/QtForPython/
   라이선스 전문: LICENSES/Qt-PySide6/ (lgpl-3.0.txt, gpl-3.0.txt — 없으면 https://www.gnu.org/licenses/lgpl-3.0.txt)
   Qt 라이브러리(DLL)는 따로 들어 있어 다른 버전으로 바꿔 끼울 수 있습니다.

3. NumPy {_ver('numpy')} — BSD 3-Clause (안에 든 라이브러리 표시 포함) — LICENSES/numpy/

4. Python {sys.version.split()[0]} — PSF License — LICENSES/Python/LICENSE.txt

5. 글꼴 / fonts — SIL OFL 1.1 · GUST Font License 등 — fonts/ 폴더의 각 라이선스 파일

6. 기본 음악 / default music — CC0 — music/CREDITS.txt

7. LUT (DJI · Insta360) — 각 제조사가 배포한 파일 — luts/README.txt
"""
    (out / "README.txt").write_text(readme, encoding="utf-8")
    print(readme)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
