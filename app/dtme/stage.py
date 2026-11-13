"""소스별 진행 단계(MOSCO 와 같은 줄 색). 프록시 = 파랑, 분석(보정) = 청록, 샘플 = 호박색, 렌더 = 빨강, 편집 = 보라, 음악 = 분홍.
줄 바탕이 단계 색으로 차오르고 오른쪽에 지금 하는 일을 그 단계의 밝은 색 글자로."""
from __future__ import annotations

ROW_BG = "#2d2d2c"        # 줄 바탕(MOSCO)
ROW_OFF = "#242424"       # 체크 해제 줄
OFF_TXT = "#737373"       # 체크 해제 이름
CHK_BG = "#1e1e1e"        # 체크 상자
CHIP_AUTO = "#3a3a3a"     # AUTO 줄 오른쪽 칩(출력)
CHIP_SRC = "#555555"      # 소스 목록 칩(프리셋)
SUB_TXT = "#8f9499"       # 보조 글씨
ERR_BG = "#c9c9c9"        # 읽기 실패 줄 = 밝은 회색
ERR_NAME = "#222222"
ERR_TXT = "#c0392b"
SEL_EDGE = "#4a8fe0"      # 선택 = 파란 테두리

# 단계: (줄 채움, 밝은 색 = 막대·글자, 이름)
STAGE = {
    "proxy": ("#2f3a4a", "#4a8fe0", "프록시"),
    "analyze": ("#24443e", "#3fb8a0", "분석"),
    "sample": ("#4a4128", "#d9a646", "샘플"),
    "render": ("#4a2e2c", "#d9604f", "렌더"),
    "edit": ("#36304a", "#8a7fe0", "편집"),      # v0.16.82 자동 편집 = 보라
    "music": ("#4a2c40", "#d97fb8", "음악"),     # v0.16.82 음악 = 분홍(샘플 호박색과 겹치지 않게)
}
# [전부 자동] 단계 순서(이름은 사용자 말: 보정 = 분석 색)
FULL_STEPS = [("analyze", "보정"), ("edit", "편집"), ("music", "음악"), ("render", "렌더")]

ERRORS = {"읽기 오류": "읽기 실패", "원본 없음": "원본 없음", "프록시 오류": "프록시 실패"}


def stage_of(state, sid: str, skip: tuple = ()):
    """(단계, 진행 0~1 | None = 대기, 글자) | ("error", None, 글자) | None.
    우선순위: 오류 > 진행 중인 작업(분석·샘플·렌더) > 진행 중인 프록시 > 작업 대기 > 정보 읽기·프록시 대기.
    skip = 표시하지 않을 작업 종류(v0.16.39 소스 목록 = ("render",) — 렌더 진행은 렌더 목록 바에만)."""
    st = state.status.get(sid, "")
    if st in ERRORS:
        return "error", None, ERRORS[st]
    w = state.work.get(sid)
    if w and w[0] in skip:
        w = None
    if w and w[1] is not None and w[1] >= 0:
        kind, v, txt = w
        return kind, max(0.0, min(1.0, v)), txt or f"{STAGE[kind][2]} {int(v * 100)}%"
    if st.startswith("프록시 ") and st != "프록시 대기":       # 대기 중인 작업보다 지금 돌아가는 프록시를 먼저
        v = state.proxy_pct.get(sid, 0.0)
        return "proxy", v, f"프록시 {int(v * 100)}%"
    if w:
        return w[0], None, w[2] or f"{STAGE[w[0]][2]} 대기"
    if st == "분석 대기":                         # ffprobe 대기(파일 정보 읽기)
        return "proxy", None, "읽는 중"
    if st == "프록시 대기":
        return "proxy", None, "프록시 대기"
    return None
