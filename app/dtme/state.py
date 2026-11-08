"""화면들이 공유하는 프로젝트 상태 + 영상 불러오기(비동기)/프록시 관리."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import ff, jobs
from .project import AUDIO_EXT, IMAGE_EXT, ImageSource, Project, Source, _id, auto_lut, plain_grade


class AppState(QObject):
    changed = Signal(str)          # "sources" | "segments" | "markers" | "grade" | "output" | "project"
    sourceStatus = Signal(str)     # source id — 분석/프록시 상태 변경
    importProgress = Signal()      # 전체 진행률 변경
    message = Signal(str)
    workChanged = Signal(str)      # sid — 분석·샘플·렌더 진행(state.work) 변경

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.status: dict[str, str] = {}      # sid → 상태 문구
        self.img_status: dict[str, str] = {}  # 이미지 id → "" (정상) | "읽기 오류" | "원본 없음"
        self.proxy_pct: dict[str, float] = {}
        self.errors: dict[str, str] = {}      # sid → 마지막 오류 내용
        self.defer_proxy = False              # 시작 창 AUTO: 프록시(재생용)를 [보정+편집] 때까지 미룸 → 상태 "읽음"
        self.work: dict[str, tuple] = {}      # sid → (단계 "analyze"|"sample"|"render", 진행 0~1 | -1 = 대기, 글자 | "")
        self._proxy_jobs: dict[str, jobs.Job] = {}
        self._undo: list[dict] = []
        self._ck_tag, self._ck_t = "", 0.0
        self.dirty = False

    def set_work(self, sid: str, kind: str | None, v: float = -1.0, text: str = ""):
        """소스 줄 진행 표시. kind=None 이면 지움(그 단계만 지우려면 only=)."""
        if kind is None:
            if self.work.pop(sid, None) is None:
                return
        else:
            self.work[sid] = (kind, v, text)
        self.workChanged.emit(sid)

    def clear_work(self, kind: str, sids=None):
        for sid in [k for k, w in self.work.items() if w[0] == kind and (sids is None or k in sids)]:
            self.work.pop(sid, None)
            self.workChanged.emit(sid)

    # ------------------------------------------------------------ 실행취소
    def checkpoint(self, tag: str = ""):
        """변경 직전에 호출 → 실행취소 지점. tag 가 같고 1초 안에 다시 오면(슬라이더를 연속으로 움직임) 1번으로 합침."""
        import time
        now = time.monotonic()
        if tag and tag == self._ck_tag and now - self._ck_t < 1.0:
            self._ck_t = now
            return
        self._ck_tag, self._ck_t = tag, now
        self._undo.append(copy.deepcopy(self.project.to_dict()))
        del self._undo[:-80]

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        file = self.project.file
        p = Project.from_dict(self._undo.pop())
        p.file = file
        self.project = p
        self.dirty = True
        self.changed.emit("undo")
        return True

    def touch(self, what: str):
        self.dirty = True
        self.changed.emit(what)

    def set_project(self, p: Project):
        self.project = p
        self._undo = []
        self.status, self.proxy_pct, self._proxy_jobs = {}, {}, {}
        self.img_status = {}
        self.dirty = False
        for m in p.images:
            if not Path(m.path).exists():
                self.img_status[m.id] = "원본 없음"
            elif not m.width:
                self._queue_image(m)
        for s in p.sources:
            if not Path(s.path).exists():
                self.status[s.id] = "원본 없음"
            elif s.frames > 0:
                self._queue_proxy(s)
            else:
                self._queue_analyze(s)
        self.retune()
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
        done = sum(1 for s in srcs if self.status.get(s.id) in ("준비", "읽음", "읽기 오류", "원본 없음", "프록시 오류"))
        part = sum(self.proxy_pct.get(s.id, 0) for s in srcs if self.status.get(s.id, "").startswith("프록시 "))
        return a, done, n, min(1.0, (done + part) / n)

    # ------------------------------------------------------------ 불러오기 (즉시 목록 등록)
    def import_files(self, files: list[str]) -> int:
        imgs = [f for f in files if Path(f).suffix.lower() in IMAGE_EXT]
        auds = [f for f in files if Path(f).suffix.lower() in AUDIO_EXT]
        files = [f for f in files if Path(f).suffix.lower() not in IMAGE_EXT | AUDIO_EXT]
        if imgs:
            self.import_images(imgs)
        if auds:
            self.import_audios(auds)
        if not files:
            return 0
        known = {Path(s.path).resolve() for s in self.project.sources}
        added = 0
        self.checkpoint()
        for f in files:
            pth = Path(f).resolve()
            if pth in known:
                continue
            known.add(pth)
            src = Source(path=str(pth), frames=0, grade=plain_grade())     # 보정 없음(LUT만) — AUTO·프리셋·조작부터 보정
            self.project.sources.append(src)
            self._queue_analyze(src)
            added += 1
        if added:
            self.retune()
            self.touch("sources")
            self.importProgress.emit()
        return added

    def retune(self):
        """원본 저장장치에 맞춰 동시 분석·렌더 수(jobs.tune)."""
        try:
            jobs.tune([s.path for s in self.project.sources if Path(s.path).exists()])
        except Exception as e:  # noqa: BLE001
            ff.log_error("동시 작업 수", str(e))

    def _set_status(self, sid, text):
        self.status[sid] = text
        self.sourceStatus.emit(sid)
        self.importProgress.emit()

    def _queue_analyze(self, src: Source):
        self._set_status(src.id, "분석 대기")
        job = jobs.Job(lambda: ff.probe(src.path))

        def done(info, sid=src.id):
            s = self.project.source(sid)
            if s is None:
                return
            for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio"):
                setattr(s, k, info[k])
            if not s.lut_mode:                     # 처음 불러올 때만: D-Log M = LUT, 일반·알 수 없음 = LUT 없음
                s.lut_mode = info.get("color_mode", "unknown")
                lut = auto_lut(self.project, s)
                if lut is not None and lut != self.project.grade.get("lut", ""):
                    s.grade["lut"] = lut
            if info["vfr"]:
                self.message.emit(f"{s.name}: 가변 프레임레이트(VFR) 의심 — 컷 위치가 어긋날 수 있습니다.")
            self.sourceStatus.emit(s.id)
            self._queue_proxy(s)

        def err(msg, s=src):
            self.errors[s.id] = msg
            ff.log_error(f"분석 {s.path}", msg)
            self._set_status(s.id, "읽기 오류")
            self.message.emit(f"{s.name}: 읽을 수 없음 ({msg[-120:]})")

        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.ANALYZE_POOL, job)

    # ------------------------------------------------------------ 스틸 소스(이미지)
    def import_images(self, files: list[str]) -> int:
        known = {Path(m.path).resolve() for m in self.project.images}
        new = []
        for f in files:
            pth = Path(f).resolve()
            if pth not in known:
                known.add(pth)
                new.append(ImageSource(path=str(pth)))
        if not new:
            return 0
        self.checkpoint()
        for m in new:
            self.project.images.append(m)
            if not self._read_image_now(m):     # 보통 즉시 끝남(헤더만 읽음). 실패할 때만 ffprobe 로
                self._queue_image(m)
        self.touch("images")
        return len(new)

    def _read_image_now(self, m: ImageSource) -> bool:
        """Qt 로 크기만 즉시 읽기(영상 분석·프록시 대기열과 무관). EXIF 방향은 직접 읽음."""
        try:
            from PySide6.QtGui import QImageReader
            r = QImageReader(m.path)
            sz = r.size()
            if not sz.isValid() or sz.width() <= 0:
                return False
            o = ff.exif_orientation(m.path)
            w, h = sz.width(), sz.height()
            m.width, m.height, m.orient = (h, w, o) if o >= 5 else (w, h, o)
            self.img_status[m.id] = ""
            return True
        except Exception as e:  # noqa: BLE001
            ff.log_error(f"이미지 {m.path}", str(e))
            return False

    def _queue_image(self, m: ImageSource):
        job = jobs.Job(lambda: ff.probe_image(m.path))

        def done(info, iid=m.id):
            im = self.project.image(iid)
            if im is not None:
                im.width, im.height, im.orient = info["width"], info["height"], info["orient"]
                self.img_status[iid] = ""
                self.changed.emit("images")

        def err(msg, im=m):
            ff.log_error(f"이미지 {im.path}", msg)
            self.img_status[im.id] = "읽기 오류"
            self.changed.emit("images")
            self.message.emit(f"{im.name}: 읽을 수 없음")

        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.ANALYZE_POOL, job)

    # ------------------------------------------------------------ 음악 소스
    def import_audios(self, files: list[str]) -> int:
        known = {Path(a["path"]).resolve() for a in self.project.audios}
        new = []
        for f in files:
            pth = Path(f).resolve()
            if pth in known:
                continue
            known.add(pth)
            try:
                dur = ff.probe_audio(str(pth))
            except Exception as e:  # noqa: BLE001
                ff.log_error(f"음악 {pth}", str(e))
                self.message.emit(f"{pth.name}: 읽을 수 없음")
                continue
            new.append({"id": _id(), "path": str(pth), "dur": dur})
        if new:
            self.checkpoint()
            self.project.audios += new
            self.touch("audios")
        return len(new)

    def remove_audio(self, aid: str):
        self.checkpoint()
        self.project.audios = [a for a in self.project.audios if a["id"] != aid]
        self.touch("audios")

    def remove_image(self, iid: str):
        """이미지와 그 이미지를 쓰는 레이어(소스·타임라인·렌더 리스트)를 모두 지움."""
        self.checkpoint()
        p = self.project
        p.images = [m for m in p.images if m.id != iid]
        for s in p.sources:
            s.layers = [l for l in s.layers if l.get("img") != iid]
        for g in p.segments + [g for r in p.render_items for g in r.segs]:
            g.layers = [l for l in g.layers if l.get("img") != iid]
        p.titles = [t for t in p.titles if t.get("img") != iid]
        self.touch("images")

    def remove_source(self, sid: str):
        self.checkpoint()
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
        """선택한 파일의 프록시를 먼저 만든다. 오류였으면 다시 시도."""
        s = self.project.source(sid)
        if s and self.status.get(sid) in ("프록시 오류", "읽기 오류") and Path(s.path).exists():
            self.errors.pop(sid, None)
            (self._queue_proxy if s.frames else self._queue_analyze)(s)
        j = self._proxy_jobs.get(sid)
        if j:
            jobs.bump(jobs.PROXY_POOL, j)

    def ensure_proxy(self, src: Source):
        """클립 LUT 가 바뀌었으면 그 LUT 의 프록시로(있으면 바로, 없으면 새로 만듦 — 그동안 정지 화면·보정은 됨)."""
        if not src or not src.frames or src.id in self._proxy_jobs:
            return
        lut = self.project.grade_for_source(src.id, off=False).get("lut", "")
        if src.proxy and Path(src.proxy) == ff.proxy_path(src.path, lut):
            return
        self._queue_proxy(src)

    def resume_proxies(self):
        """미뤄 둔 프록시를 지금 만듦([보정+편집] → 편집 화면)."""
        self.defer_proxy = False
        for s in self.project.sources:
            if self.status.get(s.id) == "읽음" and s.frames:
                self._queue_proxy(s)

    def _queue_proxy(self, src: Source):
        lut = self.project.grade_for_source(src.id, off=False).get("lut", "")      # 클립 LUT 로(일반 영상 = LUT 없음)
        pp = ff.proxy_path(src.path, lut)
        if pp.exists() and pp.stat().st_size > 0:          # 만들어 둔 것이 있으면 미룸과 상관없이 바로
            src.proxy = str(pp)
            self._set_status(src.id, "준비")
            return
        if self.defer_proxy:                                # 분석·샘플·렌더는 원본에서 → 프록시는 편집 화면에서만 필요
            self._set_status(src.id, "읽음")
            return
        self._set_status(src.id, "프록시 대기")
        gpu = self.project.output.gpu_decode
        job = jobs.Job(lambda prog, cancel: ff.make_proxy(src, lut, gpu, prog, cancel), with_progress=True)
        self._proxy_jobs[src.id] = job

        def on_prog(v, sid=src.id):
            self.proxy_pct[sid] = v
            self.status[sid] = f"프록시 {int(v * 100)}%"
            self.sourceStatus.emit(sid)
            self.importProgress.emit()

        def on_done(path, sid=src.id):
            self._proxy_jobs.pop(sid, None)
            s = self.project.source(sid)
            if s:
                s.proxy = path
            self._set_status(sid, "준비")

        def on_err(msg, s=src):
            self._proxy_jobs.pop(s.id, None)
            if msg == "취소됨":
                return
            self.errors[s.id] = msg
            ff.log_error(f"프록시 {s.path}", msg)
            self._set_status(s.id, "프록시 오류")
            self.message.emit(f"{s.name} 프록시 생성 실패: {msg[-300:]}")

        job.signals.progress.connect(on_prog)
        job.signals.done.connect(on_done)
        job.signals.error.connect(on_err)
        jobs.submit(jobs.PROXY_POOL, job)
