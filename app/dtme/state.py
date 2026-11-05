"""화면들이 공유하는 프로젝트 상태 + 영상 불러오기(비동기)/프록시 관리."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import ff, jobs
from .project import Project, Source


class AppState(QObject):
    changed = Signal(str)          # "sources" | "segments" | "markers" | "grade" | "output" | "project"
    sourceStatus = Signal(str)     # source id — 분석/프록시 상태 변경
    importProgress = Signal()      # 전체 진행률 변경
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.status: dict[str, str] = {}      # sid → 상태 문구
        self.proxy_pct: dict[str, float] = {}
        self._proxy_jobs: dict[str, jobs.Job] = {}
        self.dirty = False

    def touch(self, what: str):
        self.dirty = True
        self.changed.emit(what)

    def set_project(self, p: Project):
        self.project = p
        self.status, self.proxy_pct, self._proxy_jobs = {}, {}, {}
        self.dirty = False
        for s in p.sources:
            if not Path(s.path).exists():
                self.status[s.id] = "원본 없음"
            elif s.frames > 0:
                self._queue_proxy(s)
            else:
                self._queue_analyze(s)
        self.changed.emit("project")
        self.importProgress.emit()

    # ------------------------------------------------------------ 상태 조회
    def analyzed(self, s: Source) -> bool:
        return s.frames > 0

    def proxy_ready(self, s: Source) -> bool:
        return self.status.get(s.id) == "준비" and bool(s.proxy)

    def progress_summary(self) -> tuple[int, int, int, float]:
        """(분석 완료 수, 프록시 완료 수, 전체 수, 전체 진행률 0~1)"""
        srcs = self.project.sources
        n = len(srcs)
        if not n:
            return 0, 0, 0, 1.0
        a = sum(1 for s in srcs if s.frames > 0 or self.status.get(s.id) in ("읽기 오류", "원본 없음"))
        done = sum(1 for s in srcs if self.status.get(s.id) in ("준비", "읽기 오류", "원본 없음", "프록시 오류"))
        part = sum(self.proxy_pct.get(s.id, 0) for s in srcs if self.status.get(s.id, "").startswith("프록시 "))
        return a, done, n, min(1.0, (done + part) / n)

    # ------------------------------------------------------------ 불러오기 (즉시 목록 등록)
    def import_files(self, files: list[str]) -> int:
        known = {Path(s.path).resolve() for s in self.project.sources}
        added = 0
        for f in files:
            pth = Path(f).resolve()
            if pth in known:
                continue
            known.add(pth)
            src = Source(path=str(pth), frames=0)
            self.project.sources.append(src)
            self._queue_analyze(src)
            added += 1
        if added:
            self.touch("sources")
            self.importProgress.emit()
        return added

    def _set_status(self, sid, text):
        self.status[sid] = text
        self.sourceStatus.emit(sid)
        self.importProgress.emit()

    def _queue_analyze(self, src: Source):
        self._set_status(src.id, "분석 대기")
        job = jobs.Job(lambda: ff.probe(src.path))

        def done(info, s=src):
            if self.project.source(s.id) is None:
                return
            for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio"):
                setattr(s, k, info[k])
            if info["vfr"]:
                self.message.emit(f"{s.name}: 가변 프레임레이트(VFR) 의심 — 컷 위치가 어긋날 수 있습니다.")
            self.sourceStatus.emit(s.id)
            self._queue_proxy(s)

        def err(msg, s=src):
            self._set_status(s.id, "읽기 오류")
            self.message.emit(f"{s.name}: 읽을 수 없음 ({msg[-120:]})")

        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.ANALYZE_POOL, job)

    def remove_source(self, sid: str):
        j = self._proxy_jobs.pop(sid, None)
        if j:
            j.cancel.set()
            jobs.PROXY_POOL.tryTake(j)
        p = self.project
        p.sources = [s for s in p.sources if s.id != sid]
        p.segments = [s for s in p.segments if s.src != sid]
        p.samples = [m for m in p.samples if m.src != sid]
        p.stills = [m for m in p.stills if m.src != sid]
        self.touch("sources")
        self.importProgress.emit()

    # ------------------------------------------------------------ 프록시
    def prioritize(self, sid: str):
        """선택한 파일의 프록시를 먼저 만든다."""
        j = self._proxy_jobs.get(sid)
        if j:
            jobs.bump(jobs.PROXY_POOL, j)

    def _queue_proxy(self, src: Source):
        pp = ff.proxy_path(src.path)
        if pp.exists() and pp.stat().st_size > 0:
            src.proxy = str(pp)
            self._set_status(src.id, "준비")
            return
        self._set_status(src.id, "프록시 대기")
        lut = self.project.grade.get("lut", "")
        gpu = self.project.output.gpu_decode
        job = jobs.Job(lambda prog, cancel: ff.make_proxy(src, lut, gpu, prog, cancel), with_progress=True)
        self._proxy_jobs[src.id] = job

        def on_prog(v, sid=src.id):
            self.proxy_pct[sid] = v
            self.status[sid] = f"프록시 {int(v * 100)}%"
            self.sourceStatus.emit(sid)
            self.importProgress.emit()

        def on_done(path, s=src):
            self._proxy_jobs.pop(s.id, None)
            s.proxy = path
            self._set_status(s.id, "준비")

        def on_err(msg, s=src):
            self._proxy_jobs.pop(s.id, None)
            if msg == "취소됨":
                return
            self._set_status(s.id, "프록시 오류")
            self.message.emit(f"{s.name} 프록시 생성 실패: {msg[-300:]}")

        job.signals.progress.connect(on_prog)
        job.signals.done.connect(on_done)
        job.signals.error.connect(on_err)
        jobs.submit(jobs.PROXY_POOL, job)
