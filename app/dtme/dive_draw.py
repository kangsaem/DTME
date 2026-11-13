"""수심 그래프 오버레이(v0.16.84) — 미리보기와 렌더가 같은 그림. DTMD 포토 로그 모양.
아래 = 다이빙 전체 수심 흰 선(수면 = H-330k, 최대 수심까지 260k) + 지금 위치 빨간 점(실제 시간대로 천천히 이동)
     + 지나온 구간 아래 푸른색(왼쪽 아래 진함 → 멀어지며 옅음, 점 쪽으로 서서히 사라짐 = 경계선 없음, 멀티플라이/애드 자동).
좌상단 = 날짜(작게) · 지금 수심 · 시각(시:분). GF·기체·지명·DTMD 로고 없음(사용자 11/13).
k = 짧은 변 / 1080."""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

from . import divelog as DL

# 컷마다 애니메이션(사용자 11/13) — 기준 = 컷 시작(전환 겹침 시작). 디졸브 0.5초.
FADE = 0.5
TXT_IN = 1.0                           # 글자: 1초 뒤 디졸브 인
G_IN, G_WIPE = 2.0, 2.0                # 그래프: 2초 뒤 왼쪽부터 2초간 긁어 나타남(페더)
SHOW_MIN, SHOW_LESS = 10.0, 5.0        # v0.16.88 로그 표시 길이 = 컷 길이 − 5초(최소 10초): 15초 컷 = 10초, 20초 컷 = 15초
MIN_CUT = 15.0                         # LOG 켠 자동 편집 컷 최소 길이(전환 겹침 포함) = 그래프가 다음 전환 전에 다 사라짐
FEATHER = 0.18                         # 긁는 경계 부드러움(화면 폭 비율)
ANIM_FPS = 15                          # 애니메이션 중 렌더 그림 바꾸는 횟수(초당)


def _sm(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _wins(L: float, tail: float):
    """(애니메이션 구간들, 글자 아웃 시작, 그래프 아웃 시작). 글자 = 1초~(1+표시) · 그래프 = 2초~(2+표시)에 다 사라짐."""
    show = max(SHOW_MIN, L - SHOW_LESS)
    to = TXT_IN + show - FADE
    go = G_IN + show - FADE
    w = [(TXT_IN, TXT_IN + FADE), (to, to + FADE), (G_IN, G_IN + G_WIPE), (go, go + FADE)]
    if tail > 0:
        w.append((L - tail, L))
    return w, to, go


def anim(tc: float, L: float, tail: float = 0.0) -> tuple[float, float, float]:
    """컷 시작부터 tc 초 · 컷 길이 L(전환 겹침 포함) · 끝 전환 tail 초 → (글자 알파, 그래프 드러남 0~1, 그래프 알파).
    짧은 컷 = 시간표 그대로, 컷이 끝나는 전환 동안 같이 사라짐."""
    _w, to, go = _wins(L, tail)
    end = 1 - _sm((tc - (L - tail)) / tail) if tail > 0 else (1.0 if tc < L else 0.0)
    ta = _sm((tc - TXT_IN) / FADE) * (1 - _sm((tc - to) / FADE)) * end
    rv = _sm((tc - G_IN) / G_WIPE)
    ga = (1 - _sm((tc - go) / FADE)) * end
    return ta, rv, ga


def anim_busy(tc: float, L: float, tail: float = 0.0) -> bool:
    """이 순간 애니메이션 중인가(렌더 그림을 자주 바꿔야 하나)."""
    w, _to, _go = _wins(L, tail)
    return any(a - 0.1 <= tc <= b + 0.1 for a, b in w)


def wipe_mask(W: int, rv: float) -> np.ndarray:
    """왼쪽부터 드러나는 정도(열마다 0~1). rv=0 전부 숨김, 1 전부."""
    F = FEATHER * W
    e = rv * (W + F)
    x = np.arange(W, dtype=np.float32) + 0.5
    m = np.clip((e - x) / F, 0, 1)
    return m * m * (3 - 2 * m)


BLUE = (14, 140, 230)          # DTMD 그래프 아래 색
DOT = "#E31B3F"
RATE = 2                       # 렌더 그림 바꾸는 횟수(초당) — 점은 1초에 1px 도 안 움직임
FADE_MIN = 220                 # 점 앞 색이 사라지는 최소 길이(1080 기준 px) — 다이빙 초반에도 색이 보이게


def ensure_fonts():
    """화면 스레드에서 미리 글꼴 등록(렌더 스레드에서 처음 등록하지 않게)."""
    from .fonts import family_of_file
    family_of_file("TeXGyreHeros-Regular.otf")
    family_of_file("TeXGyreHeros-Bold.otf")


def k_of(W: int, H: int) -> float:
    return min(W, H) / 1080


def geo(W: int, H: int):
    k = k_of(W, H)
    return k, H - 330 * k, 260 * k          # k, 수면 y, 최대 수심까지 높이


def band_top(W: int, H: int) -> int:
    """색을 섞는 띠(아래쪽)의 위 끝 = 수면 선 조금 위."""
    _k, top, _gh = geo(W, H)
    return max(0, int(top - 6 * k_of(W, H)))


def _xy(dive, W, H):
    k, top, gh = geo(W, H)
    n = max(1.0, DL.dur(dive))
    md = max(1.0, float(dive.get("max") or max(d for _t, d in dive["pts"])))
    return (lambda t: t / n * W), (lambda d: top + d / md * gh)


def state(dives, when: float | None):
    """현지 시각 → (다이빙, 입수부터 초) 또는 None."""
    if when is None:
        return None
    d = DL.find(dives, when)
    return (d, when - d["start"]) if d else None


# ------------------------------------------------------------------ 위: 선 · 점 · 글자
def _font(family: str, px: float, bold: bool) -> QFont:
    f = QFont(family)
    f.setPixelSize(max(1, int(round(px))))
    f.setBold(bold)
    return f


_SHADOW: dict = {}


def _blur(a: np.ndarray, r: int) -> np.ndarray:
    """상자 흐림 3번 ≈ 가우스(반지름 r px)."""
    if r < 1:
        return a
    for ax in (0, 1):
        for _ in range(3):
            c = np.cumsum(np.pad(a, [(r + 1, r) if i == ax else (0, 0) for i in range(2)], mode="constant"), axis=ax)
            a = (np.take(c, range(2 * r + 1, c.shape[ax]), axis=ax) - np.take(c, range(0, c.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)
    return a


def _shadow_img(s: str, font: QFont, k: float):
    """글자 그림자 그림(검정 45%, 흐림 = DTMD shadowBlur 10k, 거리 없음) → (QImage, 글자 기준점에서 왼쪽 위까지)."""
    key = (s, font.family(), font.pixelSize(), font.bold(), round(k, 3))
    hit = _SHADOW.get(key)
    if hit is not None:
        return hit
    from PySide6.QtGui import QFontMetricsF
    fm = QFontMetricsF(font)
    br = fm.tightBoundingRect(s)
    pad = int(14 * k) + 2
    w, h = int(br.width()) + 2 * pad + 4, int(br.height()) + 2 * pad + 4
    im = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    im.fill(Qt.transparent)
    ox, oy = pad - br.left() + 2, pad - br.top() + 2
    q = QPainter(im)
    q.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addText(QPointF(ox, oy), font, s)
    q.fillPath(path, QColor("#000000"))
    q.end()
    ptr = im.constBits()
    a = np.frombuffer(ptr, np.uint8, im.bytesPerLine() * h).reshape(h, im.bytesPerLine() // 4, 4)[:, :w, 3].astype(np.float32)
    a = _blur(a, max(1, int(round(5 * k))))                      # canvas shadowBlur 10 ≈ 가우스 시그마 5
    a = np.clip(a * 0.45, 0, 255).astype(np.uint8)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 3] = a                                             # 검정(미리 곱한 알파 = 0,0,0,a)
    out = QImage(rgba.data, w, h, 4 * w, QImage.Format_ARGB32_Premultiplied).copy()
    res = (out, ox, oy)
    if len(_SHADOW) > 400:
        _SHADOW.clear()
    _SHADOW[key] = res
    return res


def _text(p: QPainter, x: float, y: float, s: str, font: QFont, k: float):
    """흰 글자 + 부드러운 그림자(거리 없이, 사용자 11/13)."""
    img, ox, oy = _shadow_img(s, font, k)
    p.drawImage(QPointF(x - ox, y - oy), img)
    path = QPainterPath()
    path.addText(QPointF(x, y), font, s)
    p.fillPath(path, QColor("#ffffff"))


def paint_graph(p: QPainter, W: int, H: int, dive: dict, t: float):
    """선 + 점(출력 좌표)."""
    k = k_of(W, H)
    px, py = _xy(dive, W, H)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    for i, (tt, d) in enumerate(dive["pts"]):
        (path.lineTo if i else path.moveTo)(QPointF(px(tt), py(d)))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 40), 7 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))   # 선 그림자(아주 옅게)
    p.drawPath(path)
    p.setPen(QPen(QColor("#ffffff"), 3 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(path)
    tt = max(0.0, min(DL.dur(dive), t))
    c = QPointF(px(tt), py(DL.depth_at(dive, tt)))
    p.setPen(QPen(QColor("#ffffff"), 3 * k))
    p.setBrush(QColor(DOT))
    p.drawEllipse(c, 11 * k, 11 * k)
    p.restore()


def paint_text(p: QPainter, W: int, H: int, dive: dict, t: float, when: float):
    """좌상단 날짜 · 수심 · 시각(헬베티카 같은 글꼴, 부드러운 그림자)."""
    from .fonts import family_of_file
    k = k_of(W, H)
    dep = DL.depth_at(dive, max(0.0, min(DL.dur(dive), t)))
    reg, bold = family_of_file("TeXGyreHeros-Regular.otf"), family_of_file("TeXGyreHeros-Bold.otf")
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    _text(p, 44 * k, 79 * k, DL.fmt_date(when), _font(reg, 31.2 * k, False), k)
    _text(p, 42 * k, 156 * k, f"{dep:.1f}m", _font(bold, 72 * k, True), k)
    _text(p, 42 * k, 236 * k, DL.fmt_hm(when), _font(bold, 72 * k, True), k)
    p.restore()


def text_box(W: int, H: int) -> tuple[int, int, int, int]:
    """좌상단 글자 그림 영역(x, y, w, h) — 렌더 그림 크기 줄이기."""
    k = k_of(W, H)
    return 0, 0, min(W, int(620 * k)), min(H, int(280 * k))


def paint_top(p: QPainter, W: int, H: int, dive: dict, t: float, when: float, text: bool = True,
              ta: float = 1.0, rv: float = 1.0, ga: float = 1.0):
    """미리보기: 그래프(드러남·알파) + 글자(알파)."""
    if ga > 0.002 and rv > 0.002:
        if rv >= 0.999:
            p.save()
            p.setOpacity(ga)
            paint_graph(p, W, H, dive, t)
            p.restore()
        else:
            y0 = band_top(W, H)
            im = QImage(W, H - y0, QImage.Format_ARGB32_Premultiplied)
            im.fill(Qt.transparent)
            q = QPainter(im)
            q.translate(0, -y0)
            paint_graph(q, W, H, dive, t)
            q.end()
            _apply_mask(im, wipe_mask(W, rv) * ga)
            p.drawImage(QPointF(0, y0), im)
    if text and ta > 0.002:
        p.save()
        p.setOpacity(ta)
        paint_text(p, W, H, dive, t, when)
        p.restore()


def _apply_mask(im: QImage, m: np.ndarray):
    """미리 곱한 알파 그림에 열마다 0~1 곱하기(제자리)."""
    h, bpl = im.height(), im.bytesPerLine()
    a = np.frombuffer(im.bits(), np.uint8, bpl * h).reshape(h, bpl // 4, 4)
    w = im.width()
    a[:, :w, :] = (a[:, :w, :].astype(np.float32) * m[None, :w, None]).astype(np.uint8)


def top_key(W, H, dive, t, when):
    """같은 그림이면 같은 키(렌더에서 같은 그림 파일 다시 씀): 점 위치(0.5px)·수심 0.1m·시:분."""
    px, _py = _xy(dive, W, H)
    tt = max(0.0, min(DL.dur(dive), t))
    return (dive["id"], round(px(tt) * 2), f"{DL.depth_at(dive, tt):.1f}", DL.fmt_hm(when), DL.fmt_date(when))


# ------------------------------------------------------------------ 아래: 지나온 구간 푸른색
def fill_alpha(W: int, H: int, dive: dict, t: float, rv: float = 1.0, ga: float = 1.0) -> tuple[np.ndarray, int]:
    """띠(y0~H) 의 색 세기 0~1 (H-y0, W). 선 아래 · 시작~점, 점 쪽으로 서서히 0."""
    k, top, gh = geo(W, H)
    y0 = band_top(W, H)
    px, py = _xy(dive, W, H)
    n = DL.dur(dive)
    xs = np.arange(W, dtype=np.float32) + 0.5
    pts = np.asarray(dive["pts"], np.float32)
    cy = np.interp(xs / W * max(1.0, n), pts[:, 0], pts[:, 1])
    md = max(1.0, float(dive.get("max") or pts[:, 1].max()))
    cy = top + cy / md * gh                                      # 열마다 선의 y
    xp = px(max(0.0, min(n, t)))
    ys = np.arange(y0, H, dtype=np.float32)[:, None] + 0.5
    under = ys > cy[None, :]
    r = np.hypot(xs[None, :], ys - H) / (760 * k)
    a = np.interp(r, [0, .55, 1], [.55, .22, 0]).astype(np.float32)
    L = max(0.6 * xp, FADE_MIN * k)
    f = np.clip((xp - xs) / L, 0, 1)
    f = f * f * (3 - 2 * f)
    a = a * f[None, :] * under
    if rv < 0.999 or ga < 0.999:
        a = a * (wipe_mask(W, rv) * ga)[None, :]
    return a, y0


def fill_rgb(a: np.ndarray, mode: str) -> np.ndarray:
    """색 세기 → 섞을 그림(uint8 RGB). multiply: 흰 바탕(=그대로) · add: 검은 바탕(=그대로)."""
    c = np.asarray(BLUE, np.float32) / 255
    if mode == "add":
        out = a[..., None] * c[None, None, :]
    else:
        out = 1 - a[..., None] * (1 - c[None, None, :])
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def to_qimage(rgb: np.ndarray) -> QImage:
    h, w, _ = rgb.shape
    buf = np.ascontiguousarray(rgb)
    return QImage(buf.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def dark_mode(frame_rgb: np.ndarray, W: int, H: int) -> str:
    """DTMD 와 같은 자동 선택: 그래프 영역 왼쪽 절반에서 아주 어두운 픽셀(밝기 25% 미만)이 20% 이상 = add, 아니면 multiply.
    frame_rgb = 출력 화면 비율의 작은 그림(아무 크기)."""
    h, w = frame_rgb.shape[:2]
    _k, top, _gh = geo(W, H)
    y = int(top / H * h)
    reg = frame_rgb[y:, : max(1, w // 2)].astype(np.float32)
    if not reg.size:
        return "multiply"
    lum = 0.299 * reg[..., 0] + 0.587 * reg[..., 1] + 0.114 * reg[..., 2]
    return "add" if float((lum < 63.75).mean()) >= 0.2 else "multiply"


def paint_fill(p: QPainter, rect: QRectF, W: int, H: int, dive: dict, t: float, mode: str, rv: float = 1.0, ga: float = 1.0):
    """미리보기: 출력 화면 rect 위에 직접 멀티플라이/애드(그림 크기 = rect 크기)."""
    if rv <= 0.002 or ga <= 0.002:
        return
    w, h = max(2, int(rect.width())), max(2, int(rect.height()))
    a, y0 = fill_alpha(w, h, dive, t, rv, ga)
    img = to_qimage(fill_rgb(a, mode))
    p.save()
    p.setCompositionMode(QPainter.CompositionMode_Plus if mode == "add" else QPainter.CompositionMode_Multiply)
    p.drawImage(QRectF(rect.left(), rect.top() + y0 * rect.height() / h, rect.width(), img.height() * rect.height() / h), img)
    p.restore()


# ------------------------------------------------------------------ 시각 계산
def shot_time(src) -> float | None:
    """소스 촬영 시작 시각(naive 초): 파일 이름(초까지) → 없으면 파일 안의 만든 시각(분)."""
    t = DL.name_time(src.path)
    if t is None and getattr(src, "ctime", ""):
        t = DL.name_time(str(src.ctime))
    return t


def clip_utc(src) -> float | None:
    """클립 시작 UTC(파일 안 만든 시각). 처음 한 번 읽어 src.cutc 에 둠(-1 = 없음).
    믿을 만한지: 파일 이름 현지 시각과의 차이가 15분 단위 시간대(±2초)여야 함. 차이 0 = 현지 시각을 UTC 로 적는 기종일 수 있어 안 씀."""
    c = float(getattr(src, "cutc", 0.0) or 0.0)
    if c == 0.0:
        try:
            from . import ff
            info = ff.probe(src.path)
            c = float(info.get("cutc") or 0.0) or -1.0
        except Exception:  # noqa: BLE001
            c = -1.0
        try:
            src.cutc = c
        except Exception:  # noqa: BLE001
            pass
    if c <= 0:
        return None
    loc = shot_time(src)
    if loc is None:
        return c
    diff = loc - c
    q = round(diff / 900) * 900
    if abs(diff - q) > 2.5 or abs(q) > 14 * 3600 or q == 0:
        return None
    return c + (diff - q)          # 1~2초 차이는 이름 쪽(초까지 정확)에 맞춤


def match(dives: list, src, src_sec: float, off: float = 0.0):
    """클립 안 원본 위치(초) → (다이빙, 입수부터 초, 표시 시각(카메라 현지)) 또는 None.
    v0.16.86: 클립·다이빙 모두 UTC 를 알면 UTC 로(카메라·다이빙 컴퓨터 시간대가 달라도 맞음), 아니면 현지 시각끼리."""
    if not dives:
        return None
    loc0 = shot_time(src)
    pos = max(0.0, src_sec) + float(off or 0.0)
    if any(d.get("utc") is not None for d in dives):
        u0 = clip_utc(src)
        if u0 is not None:
            d = DL.find_utc(dives, u0 + pos)
            if d is not None:
                t = u0 + pos - d["utc"]
                return d, t, (loc0 + pos) if loc0 is not None else d["start"] + t
            if all(x.get("utc") is not None for x in dives):
                return None
    if loc0 is None:
        return None
    w = loc0 + pos
    d = DL.find(dives, w)
    return (d, w - d["start"], w) if d else None


def cut_dive(dives: list, src, seg, off: float = 0.0):
    """v0.16.88 컷 전체(처음·끝)가 같은 다이빙 안일 때만 그 다이빙(입수·출수 클립 = 표시 안 함, 사용자 11/13)."""
    if not dives or not src.fps:
        return None
    a = match(dives, src, seg.fin / float(src.fps), off)
    b = match(dives, src, max(seg.fin, seg.fout - 1) / float(src.fps), off)
    return a[0] if a and b and a[0] is b[0] else None


def when_at(src, seg, t_in_cut: float, off: float = 0.0) -> float | None:
    """컷 안 재생 위치(출력 초) → 실제 시각 = 촬영 시작 + 원본 위치 + 시각 맞춤."""
    t0 = shot_time(src)
    if t0 is None or not src.fps:
        return None
    return t0 + seg.fin / float(src.fps) + max(0.0, t_in_cut) * float(seg.speed or 1.0) + float(off or 0.0)


_MODE: dict = {}


def cut_mode(src, seg, W: int, H: int) -> str:
    """컷마다 한 번: 컷 가운데 화면(프록시)으로 멀티플라이/애드 고르기. 같은 컷은 기억(미리보기·렌더 같게)."""
    key = (seg.src, seg.fin, seg.fout, W > H)
    if key in _MODE:
        return _MODE[key]
    mode = "multiply"
    try:
        import os
        from . import ff
        path = src.proxy if getattr(src, "proxy", "") and os.path.exists(src.proxy) else src.path
        mid = (seg.fin + seg.fout) // 2
        raw = ff.run([ff.paths.ffmpeg(), "-v", "error", "-ss", ff._seek(mid, src.fps), "-i", ff._abs(path), "-frames:v", "1",
                      "-vf", "scale=192:108", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        if len(raw) >= 192 * 108 * 3:
            mode = dark_mode(np.frombuffer(raw[:192 * 108 * 3], np.uint8).reshape(108, 192, 3), W, H)
    except Exception:  # noqa: BLE001
        pass
    _MODE[key] = mode
    return mode


# ------------------------------------------------------------------ 렌더 그림(작업 스레드)
def render_layers(project, dives: list, off: float, spans: list, total: float, W: int, H: int, folder, cancel=None):
    """출력 시간축(0~total) 그림 → concat 목록 {txt, gr, mul, add} + 위치. 다이빙 컷이 없으면 None.
    spans = [(시작 초, 끝 초, Segment, 끝 전환 초)] (lead 포함, 전환 겹침이면 뒤 컷).
    보통 0.5초마다, 애니메이션 중(디졸브·긁기)엔 1/15초마다. 같은 그림은 한 파일."""
    from pathlib import Path
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    y0 = band_top(W, H)
    bh = H - y0
    _x, _y, tw, th = text_box(W, H)
    fs = 2 if W * H > 2600 * 1500 else 1               # 색 띠 = 부드러운 그라데이션 → 4K 는 절반 크기로 만들어 늘림(빠르게)
    fw, fh = W // fs, max(2, bh // fs)

    inside: dict = {}

    def at(T):
        cur = None
        for sp in spans:                                  # 전환 겹침 = 나가는 컷(그 컷의 로그가 전환과 같이 사라짐)
            if sp[0] - 1e-6 <= T < sp[1]:
                cur = sp
                break
        if cur is None:
            return None
        a, b, seg, tail = cur
        src = project.source(seg.src)
        if src is None or not src.fps:
            return None
        if seg.id not in inside:
            inside[seg.id] = cut_dive(dives, src, seg, off) is not None
        if not inside[seg.id]:
            return None
        m_ = match(dives, src, seg.fin / float(src.fps) + (T - a) * float(seg.speed or 1.0), off)
        if not m_:
            return None
        return m_[0], m_[1], m_[2], seg, src, T - a, b - a, tail

    times, T = [], 0.0
    any_dive = False
    while T < total + 1e-6:
        st = at(T)
        any_dive = any_dive or st is not None
        times.append((T, st))
        T += (1 / ANIM_FPS) if (st is not None and anim_busy(st[5], st[6], st[7])) else (1 / RATE)
    if not any_dive:
        return None
    ensure_fonts()
    files: dict = {}
    lists = {"txt": [], "gr": [], "mul": [], "add": []}
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=max(2, min(6, (os.cpu_count() or 2))))
    futs = []

    def blank(w, h):
        im = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        im.fill(Qt.transparent)
        return im

    def put(kind, key, make, dur):
        name = files.get((kind, key))
        if name is None:
            name = folder / f"{kind}_{len(files):05d}.png"
            futs.append(pool.submit(make().save, str(name), "PNG", 80))     # 80 = 가벼운 압축(빠름 · 작은 파일)
            files[(kind, key)] = name
        lists[kind].append((name, dur))

    for i, (T, st) in enumerate(times):
        if cancel is not None and cancel.is_set():
            return None
        dur = (times[i + 1][0] if i + 1 < len(times) else total + 1 / RATE) - T
        if st is None:
            put("txt", "none", lambda: blank(tw, th), dur)
            put("gr", "none", lambda: blank(W, bh), dur)
            put("mul", "white", lambda: to_qimage(np.full((fh, fw, 3), 255, np.uint8)), dur)
            put("add", "black", lambda: to_qimage(np.zeros((fh, fw, 3), np.uint8)), dur)
            continue
        dive, t, w, seg, src, tc, L, tail = st
        ta, rv, ga = anim(tc, L, tail)
        px, _py = _xy(dive, W, H)
        xp = px(max(0.0, min(DL.dur(dive), t)))

        def mk_txt(dive=dive, t=t, w=w, ta=ta):
            im = blank(tw, th)
            if ta > 0.002:
                q = QPainter(im)
                q.setOpacity(ta)
                paint_text(q, W, H, dive, t, w)
                q.end()
            return im
        tk = top_key(W, H, dive, t, w)
        put("txt", ("t",) + tk[2:] + (round(ta * 100),) if ta > 0.002 else "none", mk_txt, dur)

        def mk_gr(dive=dive, t=t, rv=rv, ga=ga):
            im = blank(W, bh)
            if ga > 0.002 and rv > 0.002:
                q = QPainter(im)
                q.translate(0, -y0)
                paint_graph(q, W, H, dive, t)
                q.end()
                _apply_mask(im, wipe_mask(W, rv) * ga)
            return im
        gk = (dive["id"], round(xp * 2), round(rv * 200), round(ga * 100)) if ga > 0.002 and rv > 0.002 else "none"
        put("gr", gk, mk_gr, dur)
        mode = cut_mode(src, seg, W, H)
        on = ga > 0.002 and rv > 0.002
        fk = (dive["id"], round(xp), mode, round(rv * 200), round(ga * 100))
        need = on and (("mul", fk) not in files or ("add", fk) not in files)
        a_ = fill_alpha(W // fs, H // fs, dive, t, rv, ga)[0] if need else None
        if a_ is not None and a_.shape != (fh, fw):
            a_ = np.ascontiguousarray(np.pad(a_, ((0, max(0, fh - a_.shape[0])), (0, max(0, fw - a_.shape[1]))))[:fh, :fw])
        put("mul", fk if on and mode == "multiply" else "white",
            lambda a_=a_: to_qimage(fill_rgb(a_, "multiply")) if a_ is not None else to_qimage(np.full((fh, fw, 3), 255, np.uint8)), dur)
        put("add", fk if on and mode == "add" else "black",
            lambda a_=a_: to_qimage(fill_rgb(a_, "add")) if a_ is not None else to_qimage(np.zeros((fh, fw, 3), np.uint8)), dur)
    for f_ in futs:
        f_.result()
    pool.shutdown()
    out = {}
    for kind, items in lists.items():
        txt = ["ffconcat version 1.0"]
        for f, d in items:
            txt += [f"file '{f.as_posix()}'", f"duration {max(0.001, d):.6f}"]
        txt.append(f"file '{items[-1][0].as_posix()}'")
        lf = folder / f"{kind}.txt"
        lf.write_text("\n".join(txt) + "\n", encoding="utf-8")
        out[kind] = str(lf)
    out["y0"], out["bh"], out["tw"], out["th"] = y0, bh, tw, th
    return out
