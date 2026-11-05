"""화면들이 공유하는 프로젝트 상태 + 영상 불러오기/프록시 관리."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import ff, jobs
from .project import Project, Source


class AppState(QObject):
    changed = Signal(str)          # "sources" | "segments" | "markers" | "grade" | "output" | "project"
    proxyStatus = Signal(str)      # source id
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.proxy_state: dict[str, str] = {}   # sid → 상태 문구
        self.dirty = False

    def touch(self, what: str):
        self.dirty = True
        self.changed.emit(what)

    def set_project(self, p: Project):
        self.project = p
        self.proxy_state = {}
        self.dirty = False
        for s in p.sources:
            self._ensure_proxy(s)
        self.changed.emit("project")

    # ------------------------------------------------------------ 불러오기
    def import_files(self, files: list[str]) -> list[str]:
        warns = []
        known = {Path(s.path).resolve() for s in self.project.sources}
        for f in files:
            if Path(f).resolve() in known:
                continue
            try:
                info = ff.probe(f)
            except Exception as e:  # noqa: BLE001
                warns.append(f"{Path(f).name}: 읽을 수 없음 ({str(e)[:80]})")
                continue
            if info["vfr"]:
                warns.append(f"{Path(f).name}: 가변 프레임레이트(VFR) 의심 — 컷 위치가 어긋날 수 있습니다.")
            src = Source(path=str(Path(f).resolve()),
                         **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
            self.project.sources.append(src)
            self._ensure_proxy(src)
        self.touch("sources")
        return warns

    def remove_source(self, sid: str):
        p = self.project
        p.sources = [s for s in p.sources if s.id != sid]
        p.segments = [s for s in p.segments if s.src != sid]
        p.samples = [m for m in p.samples if m.src != sid]
        p.stills = [m for m in p.stills if m.src != sid]
        self.touch("sources")

    # ------------------------------------------------------------ 프록시
    def _ensure_proxy(self, src: Source):
        pp = ff.proxy_path(src.path) if Path(src.path).exists() else None
        if pp is None:
            self.proxy_state[src.id] = "원본 없음"
            self.proxyStatus.emit(src.id)
            return
        if pp.exists():
            src.proxy = str(pp)
            self.proxy_state[src.id] = "준비"
            self.proxyStatus.emit(src.id)
            return
        self.proxy_state[src.id] = "대기"
        lut = self.project.grade.get("lut", "")
        gpu = self.project.output.gpu_decode
        job = jobs.Job(lambda prog, cancel: ff.make_proxy(src, lut, gpu, prog, cancel), with_progress=True)

        def on_prog(v, sid=src.id):
            self.proxy_state[sid] = f"프록시 {int(v * 100)}%"
            self.proxyStatus.emit(sid)

        def on_done(path, s=src):
            s.proxy = path
            self.proxy_state[s.id] = "준비"
            self.proxyStatus.emit(s.id)

        def on_err(msg, s=src):
            self.proxy_state[s.id] = "오류"
            self.proxyStatus.emit(s.id)
            self.message.emit(f"{s.name} 프록시 생성 실패: {msg[-300:]}")

        job.signals.progress.connect(on_prog)
        job.signals.done.connect(on_done)
        job.signals.error.connect(on_err)
        jobs.submit(jobs.PROXY_POOL, job)
