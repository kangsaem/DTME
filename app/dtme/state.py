"""화면들이 공유하는 프로젝트 상태 + 영상 불러오기(비동기)/프록시 관리."""
from __future__ import annotations

import copy
import os
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
        self._redo: list[dict] = []
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
    BIG_UNDO = ("자동 편집", "전체 삭제")       # v0.16.76 되돌리기 전에 묻는 큰 작업

    def checkpoint(self, tag: str = "", label: str = ""):
        """변경 직전에 호출 → 실행취소 지점. tag 가 같고 1초 안에 다시 오면(슬라이더를 연속으로 움직임) 1번으로 합침.
        label(v0.16.76) = 실행취소할 때 상태줄에 보일 작업 이름."""
        import time
        now = time.monotonic()
        if tag and tag == self._ck_tag and now - self._ck_t < 1.0:
            self._ck_t = now
            return
        self._ck_tag, self._ck_t = tag, now
        d = copy.deepcopy(self.project.to_dict())
        d["_label"] = label
        self._undo.append(d)
        del self._undo[:-80]
        self._redo = []                       # 새 작업 = 다시 실행 목록 비움


    def undo_label(self) -> str | None:
        """다음 실행취소가 되돌릴 작업 이름("" = 이름 없음, None = 없음)."""
        return self._undo[-1].get("_label", "") if self._undo else None

    def undo(self) -> bool | str:
        """되돌림 → 그 작업 이름(없으면 True). 되돌릴 것 없음 = False."""
        if not self._undo:
            return False
        d = self._undo.pop()
        cur = copy.deepcopy(self.project.to_dict())
        cur["_label"] = d.get("_label", "")
        self._redo.append(cur)
        self._swap(d)
        return d.get("_label", "") or True

    def redo(self) -> bool | str:
        """다시 실행(v0.16.41): 실행취소한 것을 되돌림. 새 작업을 하면 비워짐."""
        if not self._redo:
            return False
        d = self._redo.pop()
        cur = copy.deepcopy(self.project.to_dict())
        cur["_label"] = d.get("_label", "")
        self._undo.append(cur)
        self._swap(d)
        return d.get("_label", "") or True

    def _swap(self, d: dict):
        file = self.project.file
        p = Project.from_dict(d)
        p.file = file
        if len(p.audios) != len(self.project.audios):     # v0.16.81 진단: 음악 목록이 사라진 일(사용자 18:24, 재현 안 됨)
            ff.log_info(f"실행취소/다시: 음악 {len(self.project.audios)} → {len(p.audios)} ({d.get('_label', '')})")
        self.project = p
        self._ck_tag = ""
        self.dirty = True
        self.changed.emit("undo")

    def missing(self) -> list:
        return [s for s in self.project.sources if self.status.get(s.id) == "원본 없음"]

    def relink(self, folder: str) -> int:
        """원본 없음(v0.16.41): 고른 폴더(아래 폴더 포함)에서 같은 파일 이름을 찾아 다시 연결. 찾은 개수.
        영상·이미지·음악 모두. 보정·컷은 그대로(경로만 바뀜)."""
        want = {}
        for s in self.missing():
            want.setdefault(Path(s.path).name.lower(), []).append(s)
        imgs = [m for m in self.project.images if not Path(m.path).exists()]
        for m in imgs:
            want.setdefault(Path(m.path).name.lower(), []).append(m)
        auds = [a for a in getattr(self.project, "audios", []) if not Path(a.get("path", "") if isinstance(a, dict) else a.path).exists()]
        for a in auds:
            want.setdefault(Path(a.get("path", "") if isinstance(a, dict) else a.path).name.lower(), []).append(a)
        if not want:
            return 0
        found, seen = 0, 0
        for root, _dirs, files in os.walk(folder):
            for f in files:
                seen += 1
                for it in want.pop(f.lower(), []):
                    full = str(Path(root) / f)
                    if isinstance(it, dict):
                        for m in self.project.music:          # 타임라인에 올린 음악도 같은 파일이면 같이
                            if m.get("path") == it["path"]:
                                m["path"] = full
                        it["path"] = full
                    else:
                        it.path = full
                    found += 1
            if not want or seen > 200_000:
                break
        if not found:
            return 0
        for m in self.project.images:
            if self.img_status.get(m.id) == "원본 없음" and Path(m.path).exists():
                self.img_status.pop(m.id, None)
                if not m.width:
                    self._queue_image(m)
        for s in self.project.sources:
            if self.status.get(s.id) == "원본 없음" and Path(s.path).exists():
                self.status.pop(s.id, None)
                s.proxy = ""
                (self._queue_proxy if s.frames > 0 else self._queue_analyze)(s)
                self.sourceStatus.emit(s.id)
        self.dirty = True
        self.retune()
        self.changed.emit("sources")
        self.changed.emit("images")
        self.importProgress.emit()
        return found

    def touch(self, what: str):
        self.dirty = True
        self.changed.emit(what)

    def set_project(self, p: Project):
        if getattr(self, "project", None) is not None and self.project.audios and len(p.audios) != len(self.project.audios):
            ff.log_info(f"프로젝트 바뀜: 음악 {len(self.project.audios)} → {len(p.audios)}")
        self.project = p
        self._undo = []
        self._redo = []
        self.status, self.proxy_pct, self._proxy_jobs = {}, {}, {}
        self.img_status = {}
        self.dirty = False
        for m in p.images:
            if not Path(m.path).exists():
                self.img_status[m.id] = "원본 없음"
            elif not m.width:
                self._queue_image(m)
        for a in getattr(p, "audios", []):               # v0.16.78 길이 읽기 전에 저장된 곡 = 다시 읽음
            if not float(a.get("dur") or 0) and Path(a.get("path", "")).exists():
                self.img_status[a["id"]] = "읽는 중"
                self._queue_audio(a)
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
        from .divelog import is_dive_file
        dvs = [f for f in files if Path(f).suffix.lower() in (".fit", ".zip", ".json") and is_dive_file(f)]
        if dvs:
            self.import_dives(dvs)
        files = [f for f in files if f not in dvs]
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

    def import_dives(self, files: list[str]) -> tuple[int, int]:
        """v0.16.84 다이빙 기록(FIT · DTMD zip/json) → project.dives(같은 다이빙 = FIT 우선). (새로 들어간 수, 못 읽은 파일 수)."""
        from . import divelog
        p = self.project
        new, bad = [], 0
        for f in files:
            try:
                new += divelog.read_dives(f)
            except Exception as ex:  # noqa: BLE001
                bad += 1
                ff.log_error("다이빙 기록 읽기", f"{f}: {ex}")
        before = {d["id"] for d in p.dives}
        self.checkpoint(label="다이빙 기록")
        p.dives = divelog.merge(p.dives, new)
        n = len([d for d in p.dives if d["id"] not in before])
        ff.log_info(f"다이빙 기록: 파일 {len(files)} · 다이빙 {len(new)}(새로 {n}) · 못 읽음 {bad} · 전체 {len(p.dives)}")
        self.dive_msg = (n, len(new), bad)
        self.auto_dive_off()
        self.touch("dives")
        return n, bad

    def auto_dive_off(self) -> bool:
        """v0.16.91 LOG 시각이 0(손대지 않음)이면 시간대 차이를 자동으로 맞춤(dive_draw.guess_off). 바꿨으면 True."""
        p = self.project
        if not p.dives or abs(float(p.dive_off or 0.0)) > 0.01:
            return False
        try:
            from . import dive_draw
            off = dive_draw.guess_off(p.dives, p.sources)
        except Exception as ex:  # noqa: BLE001
            ff.log_error("LOG 시각 자동", str(ex))
            return False
        if not off:
            return False
        p.dive_off = float(off)
        self.dive_auto_msg = off
        ff.log_info(f"LOG 시각 자동: {off:+.0f}초 (카메라·다이빙 컴퓨터 시간대 차이)")
        return True

    def retune(self):
        """원본 저장장치에 맞춰 동시 분석·렌더 수(jobs.tune)."""
        try:
            jobs.tune([s.path for s in self.project.sources if Path(s.path).exists()])
        except Exception as e:  # noqa: BLE001
            ff.log_error("동시 작업 수", str(e))

    def _set_status(self, sid, text):
        self.status[sid] = text
        if text in ("준비", "읽음") and self.project.dives and not self.project.dive_off:     # v0.16.91 영상이 다 읽히면 LOG 시각 자동
            a, _d, n, _f = self.progress_summary()
            if a >= n and self.auto_dive_off():
                self.touch("dives")
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
            s.rotation = int(info.get("rotation", 0) or 0)
            s.cutc = float(info.get("cutc") or 0.0) or -1.0      # v0.16.86 UTC 촬영 시각(수심 그래프)
            first = not s.lut_mode
            if first:                              # v0.16.55 처음 불러올 때만: 이름에 날짜 없으면 만든 시각 · 아이폰 자르기(AAE) → 인/아웃
                from .project import name_has_date, set_name_hint
                if info.get("ctime") and not name_has_date(s.path):
                    s.ctime = info["ctime"]
                    set_name_hint(s.path, s.ctime)
                tr = None if (s.sel_in or s.sel_out) else ff.aae_trim(s.path)
                if tr and s.frames:
                    a = max(0, min(s.frames - 1, int(round(tr[0] * float(s.fps)))))
                    b = max(a + 1, min(s.frames, int(round(tr[1] * float(s.fps)))))
                    if (a, b) != (0, s.frames):
                        s.sel_in, s.sel_out = a, (0 if b >= s.frames else b)
                        ff.log_info(f"AAE 자르기 → 인/아웃 {a}~{b} ({s.path})")
            if first:                              # 처음 불러올 때만: D-Log M = LUT, 일반·알 수 없음 = LUT 없음
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
        for m in new:                           # v0.16.78 목록 먼저(읽는 중 = 흐리게), 크기는 뒤에서(예전 = 하나씩 읽고 나서 → 화면 멈춤)
            self.project.images.append(m)
            self.img_status[m.id] = "읽는 중"
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

    @staticmethod
    def _image_info(path: str) -> dict:
        """크기·방향: Qt 로 헤더만(빠름), 안 되면 ffprobe. 작업 스레드에서."""
        try:
            from PySide6.QtGui import QImageReader
            sz = QImageReader(path).size()
            if sz.isValid() and sz.width() > 0:
                o = ff.exif_orientation(path)
                w, h = sz.width(), sz.height()
                return {"width": h if o >= 5 else w, "height": w if o >= 5 else h, "orient": o}
        except Exception:  # noqa: BLE001
            pass
        return ff.probe_image(path)

    def _queue_image(self, m: ImageSource):
        job = jobs.Job(lambda: self._image_info(m.path))

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
            new.append({"id": _id(), "path": str(pth), "dur": 0.0})      # v0.16.78 목록 먼저, 길이는 뒤에서
        if new:
            self.checkpoint()
            self.project.audios += new
            for a in new:
                self.img_status[a["id"]] = "읽는 중"
                self._queue_audio(a)
            self.touch("audios")
        return len(new)

    @staticmethod
    def default_music() -> list[str]:
        """v0.16.91 프로그램과 같이 오는 기본 음악(music 폴더 mp3, CC0)."""
        from . import paths
        d = paths.music_dir()
        return sorted(str(f) for f in d.glob("*.mp3")) if d.is_dir() else []

    def add_default_music(self) -> int:
        """프로젝트에 곡이 없으면 기본 음악을 음악 목록에 넣음(길이 바로 읽음). 넣은 수."""
        if self.project.audios:
            return 0
        new = []
        for f in self.default_music():
            try:
                new.append({"id": _id(), "path": str(Path(f).resolve()), "dur": float(ff.probe_audio(f))})
            except Exception as ex:  # noqa: BLE001
                ff.log_error(f"기본 음악 {f}", str(ex))
        if new:
            self.project.audios += new
            ff.log_info(f"기본 음악 {len(new)}곡 넣음")
            self.touch("audios")
        return len(new)

    def _queue_audio(self, a: dict):
        job = jobs.Job(lambda path=a["path"]: ff.probe_audio(path))

        def done(dur, aid=a["id"], path=a["path"]):
            self.img_status[aid] = ""
            for x in self.project.audios:
                if x["id"] == aid or x["path"] == path:
                    x["dur"] = float(dur)
            for m in self.project.music:                 # 읽기 전에 넣은 곡 = 임시 길이 → 실제 길이로
                if m.get("path") == path and m.get("_pending"):
                    m["dur"] = float(dur)
                    m["len"] = round(max(0.2, min(float(m["len"]), float(dur) - float(m.get("off", 0)))), 3)
                    m.pop("_pending", None)
            self.changed.emit("audios")
            self.changed.emit("titles")

        def err(msg, aid=a["id"], path=a["path"]):
            ff.log_error(f"음악 {path}", msg)
            self.img_status[aid] = "읽기 오류"
            self.message.emit(f"{Path(path).name}: 읽을 수 없음")
            self.changed.emit("audios")
        job.signals.done.connect(done)
        job.signals.error.connect(err)
        jobs.submit(jobs.ANALYZE_POOL, job, priority=2)

    def remove_audio(self, aid: str):
        ff.log_info(f"곡 삭제: {next((a['path'] for a in self.project.audios if a['id'] == aid), aid)}")
        self.checkpoint(label="곡 삭제")
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
