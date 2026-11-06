"""DTME 시안: 전체자동보정·추천 보정·RGB 도움 (v0.15 안). project/Auto.dc.html, project/AutoPop.dc.html 생성."""
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "project")

STYLE = """
body{margin:0}
a{color:#9cc3f0}a:hover{color:#cfe2f8}
.b{height:26px;min-width:56px;padding:0 8px;box-sizing:border-box;background:#3a3a3a;color:#e6e6e6;border:1px solid #555;border-radius:3px;font:12px 'Malgun Gothic',system-ui,sans-serif;display:inline-flex;align-items:center;justify-content:center}
.m{height:30px;min-width:68px}
.s{min-width:22px;width:22px;height:20px;padding:0;font-size:10px}
.red{background:#cf3b2b;border-color:#e0574a;color:#fff}
.on{background:#2f4f78;border-color:#4a8fe0;color:#fff}
.lbl{color:#d0d0d0;font-size:12px}
.val{color:#d0d0d0;font-size:12px;width:40px;flex:none;text-align:right;padding:1px 4px;box-sizing:border-box}
.sl{flex:1;height:4px;background:#3c3c3c;border-radius:2px;position:relative}
.sl span{position:absolute;left:0;top:0;bottom:0;background:#4f7fb8;border-radius:2px}
.sl i{position:absolute;top:-5px;width:10px;height:14px;background:#5a5a5a;border:1px solid #777;border-radius:2px}
.cb{height:24px;background:#2a2a2a;border:1px solid #4a4a4a;border-radius:3px;color:#ddd;font-size:12px;display:flex;align-items:center;justify-content:space-between;padding:0 8px;box-sizing:border-box}
.sec{height:22px;background:#2b2b2b;border-radius:3px;display:flex;align-items:center;padding:0 8px;font-size:12px;color:#e0e0e0;font-weight:700;gap:6px}
.chip{display:inline-flex;align-items:center;height:16px;padding:0 5px;border-radius:2px;background:#3a3a3a;color:#fff;font-size:10px;font-weight:400;white-space:nowrap}
.mi{padding:3px 10px 3px 22px;position:relative}
.new{outline:2px dashed #e5484d;outline-offset:2px}
.pill{height:26px;padding:0 12px;border-radius:13px;border:1px solid #555;background:#2e2e2e;color:#e6e6e6;font:12px 'Malgun Gothic',system-ui,sans-serif;display:inline-flex;align-items:center;white-space:nowrap}
.pill.auto{border-style:dashed;border-color:#666;color:#bbb}
.pill.autoon{border:1px solid #f2c94c;color:#f2c94c;background:#3a3420}
.pill.sel{background:#2f4f78;border-color:#4a8fe0;color:#fff}
.tag{display:inline-flex;align-items:center;height:20px;padding:0 6px;border-radius:2px;background:#3a3a3a;color:#eee;font-size:11px;white-space:nowrap}
.tag.main{background:#2f4f78;color:#fff}
.th{color:#aaa;font-size:11px}
"""

HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<style>{style}</style>
</helmet>
"""

TAIL = """
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":{w},"height":{h}}}}}'>
class Component extends DCLogic {{
renderVals() {{
return {{}};
}}
}}
</script>
</body>
</html>
"""


def slider(name, pct, val, key_state="", new=False):
    ks = {"on": "background:#5a4a1a;border-color:#f2c94c;color:#f2c94c", "has": "color:#f2c94c", "": "color:#777"}[key_state]
    cls = ' class="new"' if new else ""
    return (f'<div{cls} style="display:flex;gap:6px;align-items:center"><span class="lbl" style="width:30px;flex:none;white-space:nowrap">{name}</span>'
            f'<div class="sl"><span style="width:{pct}%"></span><i style="left:{pct - 2}%"></i></div><span class="val">{val}</span>'
            f'<button class="b s" aria-label="{name} 키프레임" style="{ks}">◆</button></div>')


def parade(w, h, lines=True, dots=True):
    """R·G·B 3칸 파레이드(세로 = 밝기). 목표선 5%·95%, 넘침/부족 점."""
    pw = (w - 8) / 3
    out = [f'<svg aria-hidden="true" width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="position:absolute;left:0;top:0">']
    cols = [("#e5484d", 0.18, 0.62), ("#5fd17a", 0.22, 0.85), ("#4a8fe0", 0.30, 0.97)]
    import random
    random.seed(3)
    for i, (c, lo, hi) in enumerate(cols):
        x0 = 2 + i * (pw + 2)
        out.append(f'<rect x="{x0:.1f}" y="1" width="{pw:.1f}" height="{h - 2}" fill="#0b0b0b" stroke="#2a2a2a"/>')
        for k in range(int(pw / 2)):
            x = x0 + 1 + k * 2
            for _ in range(9):
                v = lo + (hi - lo) * random.random() ** (0.8 + 0.4 * random.random())
                y = 1 + (h - 2) * (1 - v)
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="1.6" height="1.6" fill="{c}" opacity="0.55"/>')
        if lines:
            for frac in (0.05, 0.95):
                y = 1 + (h - 2) * (1 - frac)
                out.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x0 + pw:.1f}" y2="{y:.1f}" stroke="#ffffff" stroke-opacity="0.35" stroke-dasharray="3 3"/>')
    if dots:
        # 빨강: 암부 부족(파랑 점, 위로 떠 있음) / 파랑: 명부 넘침(빨강 점)
        out.append(f'<circle cx="{2 + pw / 2:.1f}" cy="{h - 4}" r="3" fill="#4a8fe0"/>')
        out.append(f'<circle cx="{2 + 2 * (pw + 2) + pw / 2:.1f}" cy="4" r="3" fill="#e5484d"/>')
    out.append("</svg>")
    return "".join(out)


def src_row(name, preset, auto, out, sel=False, prog=None, wait=False, c=False, keys=0):
    bg = "#3c3c3c;color:#ddd" if wait else "#6b6b6b;color:#f2f2f2"
    sh = "box-shadow:inset 0 0 0 2px #4a8fe0;" if sel else ""
    fill = ""
    if prog:      # 분석 중: 진행만큼 밝아짐(파랑 기운) / 렌더 중: 빨강 기운
        col = "#5d7896" if prog[1] == "#4a8fe0" else "#8a5a54"
        fill = f'<span style="position:absolute;left:0;top:0;bottom:0;width:{prog[0]}%;background:{col}"></span>'
    ctag = '<span style="color:#f2c94c;font-size:11px;position:relative">C</span>' if c else ""
    k = f'<span style="color:#f2c94c;font-size:10px;position:relative">◆{keys}</span>' if keys else ""
    pl = (f'<span style="font-size:11px;font-weight:400;color:{"#c4cad1" if auto else "#fff"};position:relative;white-space:nowrap">{preset}</span>' if preset else "")
    return (f'<div class="new" style="height:22px;background:{bg};{sh}border-radius:3px;font-size:12px;font-weight:700;display:flex;'
            f'align-items:center;gap:5px;padding:0 6px 0 8px;position:relative;overflow:hidden">{fill}'
            f'<span style="flex:1;white-space:nowrap;overflow:hidden;position:relative">{name}</span>{ctag}{k}{pl}'
            f'</div>')


def auto_board():
    w, h = 1536, 864
    left = f"""
<div style="width:300px;background:#202020;padding:6px;box-sizing:border-box;display:flex;flex-direction:column;gap:5px;font-size:12px;overflow:hidden">
<div style="display:flex;gap:4px"><button class="b">리셋</button><button class="b">기본값</button><span style="flex:1"></span><button class="b">기본값으로 저장</button></div>
<div class="new" style="display:flex;gap:6px;align-items:center"><button class="b" style="flex:1;justify-content:space-between;height:24px"><span>프리셋: 얕은 수심 · 산호초</span><span>▾</span></button><button class="b" style="width:60px;min-width:60px">저장…</button></div>
<div style="display:flex;gap:6px;align-items:center"><div class="cb" style="flex:1"><span>1920×1080</span><span>▾</span></div><button class="b on" style="width:60px;min-width:60px">오디오</button></div>
<div style="display:flex;gap:6px;align-items:center"><div style="flex:1;display:flex;border:1px solid #555;border-radius:3px;overflow:hidden;height:24px;font-size:12px"><span style="flex:1;display:flex;align-items:center;justify-content:center;background:#2a2a2a">보정</span><span style="flex:1;display:flex;align-items:center;justify-content:center;background:#2a2a2a;border-left:1px solid #555">원본</span><span style="flex:1;display:flex;align-items:center;justify-content:center;background:#2f4f78;border-left:1px solid #555;color:#fff">반반</span></div><button class="b on" style="width:60px;min-width:60px">RGB</button></div>
<div class="sec"><span>▾</span><span>색</span></div>
<div class="cb"><span>DJI_OSMO_Action_4_D-Log_M…</span><span>▾</span></div>
<div style="display:flex;gap:4px;justify-content:flex-end"><button class="b">흰색 찍기</button><button class="b">LUT 추가…</button></div>
{slider("빨강", 58, "1.42", "has")}
{slider("파랑", 46, "0.96", "has")}
{slider("색조", 58, "+5.0°")}
{slider("채도", 56, "1.12")}
{slider("물빛", 66, "+12°", new=True)}
{slider("녹황", 40, "40", new=True)}
<div style="display:flex;gap:6px"><div aria-label="커브" style="flex:1;height:92px;background:#151515;position:relative"><svg aria-hidden="true" width="100%" height="92" viewBox="0 0 230 128" preserveAspectRatio="none" style="position:absolute;inset:0"><g stroke="#2c2c2c"><line x1="57" y1="0" x2="57" y2="128"/><line x1="115" y1="0" x2="115" y2="128"/><line x1="172" y1="0" x2="172" y2="128"/><line x1="0" y1="32" x2="230" y2="32"/><line x1="0" y1="64" x2="230" y2="64"/><line x1="0" y1="96" x2="230" y2="96"/></g><path d="M2 126 C 40 124, 60 110, 80 92 S 150 30, 180 14 S 220 3, 228 2" fill="none" stroke="#fff" stroke-width="2"/></svg></div><span style="width:22px"></span></div>
<div style="display:flex;justify-content:flex-end;padding-right:28px"><button class="b">커브리셋</button></div>
<div class="sec"><span>▸</span><span>디테일</span></div>
<div class="sec"><span>▸</span><span>렌즈 · 흔들림</span></div>
<div class="sec"><span>▾</span><span>샘플</span></div>
<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:3px">{''.join(f'<div style="height:44px;background:linear-gradient(180deg,{c},#3f86a8)"></div>' for c in ("#123f74", "#0f3d72", "#14467c", "#103a6a", "#154a80", "#0e3866"))}</div>
</div>"""
    scope_w, scope_h = 210, 108
    mon = f"""
<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">
<div style="height:440px;background:#0e0e0e;display:flex;align-items:center;justify-content:center;position:relative">
<div style="width:782px;height:440px;position:relative;overflow:hidden;background:linear-gradient(180deg,#0f3f78 0%,#1f6a9a 50%,#c99a72 100%)">
<div style="position:absolute;left:0;top:0;bottom:0;width:391px;background:linear-gradient(180deg,#24445a 0%,#2f5262 45%,#5c6658 100%)"></div>
<div style="position:absolute;left:390px;top:0;bottom:0;width:2px;background:#fff"></div>
<div style="position:absolute;left:381px;top:210px;width:20px;height:20px;border-radius:10px;background:#fff;border:2px solid #1b1b1b;box-sizing:border-box"></div>
<div style="position:absolute;left:8px;top:8px;display:flex;border:1px solid #666;border-radius:3px;overflow:hidden;font-size:11px"><span style="padding:3px 10px;background:#2f4f78;color:#fff">소스</span><span style="padding:3px 10px;background:rgba(30,30,30,.85);color:#bbb">타임라인</span></div>
<div class="new" style="position:absolute;right:8px;top:8px;width:{scope_w}px;display:flex;flex-direction:column;gap:3px;align-items:flex-end">
<div style="width:{scope_w}px;height:{scope_h}px;background:rgba(10,10,10,.85);border:1px solid #444;position:relative">{parade(scope_w, scope_h)}</div>
<div style="display:flex;gap:3px"><button class="b" style="height:22px;min-width:52px;font-size:11px;background:rgba(40,40,40,.92)">명암</button><button class="b" style="height:22px;min-width:52px;font-size:11px;background:rgba(40,40,40,.92)">색 균형</button></div>
</div>
</div></div>
<div style="height:24px;background:#202020;position:relative">
<div style="position:absolute;left:96px;width:400px;top:0;bottom:0;background:#5b7fa6;color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center">x1</div>
<div style="position:absolute;left:96px;top:0;width:0;height:0;border-top:14px solid #f2c94c;border-right:14px solid transparent"></div>
<div style="position:absolute;left:250px;top:0;bottom:0;width:2px;background:#e5484d"></div>
<div style="position:absolute;left:180px;top:2px;width:7px;height:7px;background:#f2c94c;transform:rotate(45deg)"></div>
<div style="position:absolute;left:330px;top:2px;width:7px;height:7px;background:#f2c94c;transform:rotate(45deg)"></div>
</div>
<div style="display:flex;align-items:center;gap:4px;justify-content:center">
<button class="b">I◀</button><button class="b">◀◀</button><button class="b">◀|</button><button class="b m" style="width:88px;height:32px">▶ / ❚❚</button><button class="b">|▶</button><button class="b">▶▶</button><button class="b">▶I</button>
<div style="margin-left:10px;background:#000;color:#e8e8e8;font:300 14px Consolas,monospace;padding:4px 10px;border-radius:2px">00:12.30</div></div>
<div style="display:flex;align-items:center;gap:4px;justify-content:center">
<button class="b" style="background:#3a3a26">[ 컷인</button><button class="b" style="background:#3a3a26">컷아웃 ]</button><button class="b">IO 해제</button><button class="b">삭제</button>
<span style="width:6px"></span><button class="b">x2</button><button class="b" style="box-shadow:inset 0 0 0 2px #4a8fe0">x1</button><button class="b">x1/2</button>
<span style="width:6px"></span><button class="b">스틸</button><button class="b">샘플</button><button class="b">★</button><button class="b">글자</button>
<span style="width:6px"></span><button class="b m red" style="width:88px;height:32px;box-shadow:0 2px 6px rgba(0,0,0,.6)" aria-label="렌더리스트로">➜</button></div>
<div style="height:20px;background:#1c1c1c;border-radius:3px;font-size:12px;color:#7fd18b;display:flex;align-items:center;padding-left:8px">프리셋 → 얕은 수심 · 산호초</div>
<div style="display:flex;align-items:center;gap:6px">
<button class="b">컷편집</button><span style="font-size:12px;color:#aaa"></span><span style="flex:1"></span>
<button class="b m" style="background:#2f3b4d;width:88px;height:32px" aria-label="타임라인으로">▼</button><span style="flex:1"></span>
<div style="width:90px;height:4px;background:#3c3c3c;border-radius:2px;position:relative"><span style="position:absolute;left:0;width:30px;top:0;bottom:0;background:#4f7fb8"></span></div>
<button class="b">전체 삭제</button><button class="b m red" style="width:88px;height:32px;box-shadow:0 2px 6px rgba(0,0,0,.6)" aria-label="타임라인 전체를 렌더리스트로">➜</button></div>
<div style="height:132px;background:#1b1b1b;border:1px solid #2a2a2a"></div>
</div>"""
    rows = "".join([
        src_row("1025 1207", "라이트·거북이", False, "1080", sel=True, c=True),
        src_row("1025 1213", "얕은·산호초", True, "세로", sel=True, c=True, keys=3),
        src_row("1025 1218", "깊은·물고기", True, "1080", c=True),
        src_row("1025 1224", "", True, "4K", prog=(45, "#4a8fe0")),
        src_row("1025 1231", "", True, "1080"),
        src_row("1025 1240", "", True, "1080", wait=True),
    ])
    right = f"""
<div style="width:220px;display:flex;flex-direction:column;gap:3px;background:#1a1a1a">
<div class="new" style="display:flex;justify-content:center"><button class="b m red" style="width:88px;height:32px;font-weight:700;letter-spacing:1px;box-shadow:0 2px 6px rgba(0,0,0,.6)">AUTO</button></div>
<div style="height:3px;background:#2a2a2a;border-radius:2px;position:relative"><span style="position:absolute;left:0;top:0;bottom:0;width:62%;background:#4a8fe0;border-radius:2px"></span></div>
<div style="flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:3px">{rows}</div>
<div style="display:flex;gap:4px;padding-top:4px"><button class="b" style="flex:1">영상 추가</button><button class="b" style="flex:1">삭제</button></div>
<div style="height:340px;border-top:1px solid #333;padding-top:4px;display:flex;flex-direction:column;gap:3px;box-sizing:border-box"><div style="display:flex;gap:4px"><button class="b m" style="flex:1;min-width:0;height:32px">미리보기 렌더</button><button class="b m" style="min-width:34px;height:32px" aria-label="렌더 설정">⚙</button><button class="b m red" style="width:88px;min-width:88px;height:32px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.6)">렌더</button></div>
<div style="height:22px;background:#6b6b6b;border-radius:3px;color:#f2f2f2;font-size:11px;display:flex;align-items:center;justify-content:space-between;padding:0 6px"><span style="font-weight:700">DTME_202610251207</span><span>가로 48.2초</span></div>
<div style="height:22px;background:#6b6b6b;border-radius:3px;color:#f2f2f2;font-size:11px;display:flex;align-items:center;justify-content:space-between;padding:0 6px"><span style="font-weight:700">DTME_202610251213</span><span>세로 31.0초</span></div>
<div style="height:22px;background:#3c3c3c;border-radius:3px;color:#ddd;font-size:11px;display:flex;align-items:center;justify-content:space-between;padding:0 6px;position:relative;overflow:hidden"><span style="position:absolute;left:0;bottom:0;height:3px;width:35%;background:#cf3b2b"></span><span style="font-weight:700;position:relative">DTME_202610251231</span><span style="position:relative">가로 22.4초</span></div>
<div style="flex:1"></div></div>
</div>"""
    body = (f'<div style="width:{w}px;height:{h}px;background:#1b1b1b;font-family:\'Malgun Gothic\',system-ui,sans-serif;color:#ddd;display:flex;flex-direction:column;overflow:hidden">'
            '<div style="height:30px;display:flex;align-items:center;gap:22px;padding:0 14px;background:#232323;border-bottom:1px solid #333;font-size:12px"><span>새 프로젝트</span><span style="color:#666">|</span><span>저장하기</span><span>불러오기</span><span>실행취소</span></div>'
            f'<div style="flex:1;display:flex;gap:4px;padding:4px;min-height:0">{left}{mon}{right}</div></div>')
    return HEAD.format(title="DTME 전체자동보정·추천·RGB", style=STYLE) + body + TAIL.format(w=w, h=h)


def grid_block(tip=False):
    """오른쪽: [자동 인식] / 줄마다 [자동](장면 고정·피사체 자동) + 피사체 4 / 기타. 세부 값은 툴팁."""
    g = '<div style="display:grid;grid-template-columns:70px 52px repeat(4,1fr);gap:5px;align-items:center;position:relative">'
    g += '<span></span><button class="b on" style="grid-column:span 5;min-width:0;height:32px;font-weight:700">모두 자동</button>'
    for lab, sel, auto in (("라이트", 2, False), ("얕은 수심", -1, True), ("깊은 수심", -1, False)):
        g += f'<span class="lbl" style="text-align:right;padding-right:4px">{lab}</span>'
        g += f'<button class="b" style="min-width:0;height:30px;border-style:dashed;{"border:1px solid #f2c94c;color:#f2c94c;background:#3a3420;" if auto else "color:#bbb;"}">자동</button>'
        g += "".join(f'<button class="b{" on" if i == sel else ""}" style="min-width:0;height:30px">{n}</button>'
                     for i, n in enumerate(("물고기", "산호초", "거북이", "다이버")))
    g += ('<span class="lbl" style="text-align:right;padding-right:4px">기타</span><span></span>'
          '<button class="b" style="min-width:0;height:30px;grid-column:span 2">블루워터</button>'
          '<button class="b" style="min-width:0;height:30px;grid-column:span 2">야간</button>')
    if tip:   # 툴팁 예: 깊은 수심 · 다이버 에 마우스
        g += ('<div style="position:absolute;right:-6px;top:150px;background:#111;border:1px solid #666;border-radius:3px;padding:6px 9px;'
              'font-size:11px;color:#ddd;line-height:1.5;box-shadow:0 4px 12px rgba(0,0,0,.6);z-index:2;white-space:nowrap">'
              '빨강 1.85 · 파랑 0.95 · 채도 1.10<br>물빛 +8° · 녹황 15 · 명암 S 5<br>색 노이즈 45 · 밝기 노이즈 35 · 디헤이즈 25</div>')
    return g + '</div>'


def detail_box(title="깊은 수심 · 다이버"):
    vals = [("빨강", "1.85"), ("파랑", "0.95"), ("색조", "0.0°"), ("채도", "1.10"), ("물빛", "+8°"), ("녹황", "15"),
            ("명암 S", "5"), ("디헤이즈", "25"), ("색 노이즈", "45"), ("밝기 노이즈", "35")]
    cells = "".join(f'<div style="display:flex;justify-content:space-between;font-size:12px"><span style="color:#aaa">{k}</span><span>{v}</span></div>' for k, v in vals)
    return (f'<div style="margin-top:auto;display:grid;grid-template-columns:76px 1fr;gap:5px"><span></span>'
            f'<div style="background:#1c1c1c;border:1px solid #333;border-radius:3px;padding:8px 12px;display:flex;flex-direction:column;gap:6px">'
            f'<div style="font-size:12px;font-weight:700">{title}</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;column-gap:22px;row-gap:3px">{cells}</div></div></div>')


def seg(label, opts, on, lw=76):
    bs = "".join(f'<span style="flex:1;display:flex;align-items:center;justify-content:center;{"background:#2f4f78;color:#fff;" if i == on else "background:#2a2a2a;"}'
                 f'{"border-left:1px solid #555;" if i else ""}">{o}</span>' for i, o in enumerate(opts))
    return (f'<div style="display:grid;grid-template-columns:{lw}px 1fr;gap:5px;align-items:center"><span class="lbl" style="text-align:right;padding-right:4px">{label}</span>'
            f'<div style="display:flex;border:1px solid #555;border-radius:3px;overflow:hidden;height:28px;font-size:12px">{bs}</div></div>')


def auto_popup():
    """교집합: DTME 틀(왼쪽 목록 · 오른쪽 버튼 · 아래 시작 2개) + MOSCO(줄마다 자동 · 인식 결과 작은 글씨 · 진행 배경 · 툴팁 값)."""
    # (포함, 이름, C, 프리셋, 직접 지정, 인식 결과 줄, 출력, 선택, 진행)
    clips = [(True, "1025 1207", False, "라이트 · 거북이", True, "인식: 라이트 · 물고기", "1080", False, None),
             (True, "1025 1213", True, "얕은 수심 · 산호초", False, "◆3", "세로", True, None),
             (True, "1025 1218", False, "깊은 수심 · 물고기", False, "", "1080", True, None),
             (True, "1025 1224", False, "자동", False, "", "1080", False, 45),
             (True, "1025 1231", False, "얕은 수심 · 자동", True, "", "1080", False, None),
             (False, "1025 1240", True, "자동", False, "", "4K", False, None)]
    rows = []
    for inc, n, c, pr, fixed, sub, out, sel, prog in clips:
        ck = (f'<span style="width:14px;height:14px;flex:none;border:1px solid #777;border-radius:2px;display:inline-flex;align-items:center;'
              f'justify-content:center;font-size:11px;color:#fff;background:{"#4a8fe0" if inc else "transparent"};position:relative">{"✓" if inc else ""}</span>')
        tag = '<span style="color:#f2c94c;font-size:11px;width:10px;flex:none;position:relative">C</span>' if c else '<span style="width:10px;flex:none"></span>'
        pc = "#fff" if fixed else "#c4cad1"
        bg = "#2f4f78" if sel else "#6b6b6b" if inc else "#3c3c3c"
        pb = (f'<span style="position:absolute;left:0;top:0;bottom:0;width:{prog}%;background:#5d7896"></span>' if prog else "")
        sb = f'<span style="font-size:11px;color:#c4cad1;white-space:nowrap;position:relative">{sub}</span>' if sub else ""
        rows.append(f'<div style="height:28px;background:{bg};border-radius:3px;position:relative;overflow:hidden;display:flex;align-items:center;gap:8px;padding:0 8px;font-size:12px">{pb}'
                    f'{ck}<span style="font-weight:700;width:72px;flex:none;position:relative;color:{"#fff" if inc else "#8a8a8a"}">{n}</span>{tag}'
                    f'<span style="color:{pc};white-space:nowrap;position:relative">{pr}</span>{sb}<span style="flex:1"></span>'
                    f'<span class="chip" style="width:34px;justify-content:center;height:18px;position:relative">{out}</span></div>')
    left = f'<div style="flex:1;display:flex;flex-direction:column;gap:4px;background:#1e1e1e;border:1px solid #333;border-radius:3px;padding:6px">{"".join(rows)}</div>'
    right = (f'<div style="width:470px;display:flex;flex-direction:column;gap:12px">{grid_block()}'
             '<div style="border-top:1px solid #3a3a3a"></div>'
             f'{seg("강도", ("약", "중", "강"), 1)}{seg("출력", ("1080", "1440", "4K", "세로"), 0)}'
             '<div class="new" style="display:grid;grid-template-columns:76px 1fr;gap:5px;align-items:center"><span class="lbl" style="text-align:right;padding-right:4px">이름</span>'
             '<div style="display:flex;gap:8px;align-items:center"><div style="width:160px;height:28px;box-sizing:border-box;background:#1a1a1a;border:1px solid #555;border-radius:3px;display:flex;align-items:center;padding:0 8px;font-size:12px">DTME</div>'
             '<span style="font-size:12px;color:#c4cad1;font-family:Consolas,monospace">DTME_202610251207.mp4</span></div></div>'
             f'{detail_box()}</div>')
    def btns(opts, on):
        return ('<div style="display:flex;border:1px solid #555;border-radius:3px;overflow:hidden;height:32px">' + "".join(
            f'<span style="padding:0 16px;display:flex;align-items:center;{"background:#2f4f78;color:#fff;" if k in on else "background:#2a2a2a;"}'
            f'{"border-left:1px solid #555;" if i else ""}">{t}</span>' for i, (k, t) in enumerate(opts)) + '</div>')
    bottom = ('<div style="display:flex;flex-direction:column;gap:8px;font-size:12px">'
              '<div style="height:6px;background:#2a2a2a;border-radius:3px;position:relative">'
              '<span style="position:absolute;left:0;top:0;bottom:0;width:58%;background:#4a8fe0;border-radius:3px"></span></div>'
              '<div style="display:flex;gap:10px;align-items:center;padding-top:4px"><span class="lbl" style="width:52px;text-align:right">기존 값</span>'
              + btns((("keep", "기존 보정 유지"), ("drop", "기존 보정 무시")), ("keep",)) + '<span style="width:6px"></span>'
              + btns((("keys", "키프레임 유지"), ("autok", "키프레임 자동")), ("keys",)) + '</div>'
              '<div style="display:flex;gap:10px;align-items:center"><span class="lbl" style="width:52px;text-align:right">이후</span>'
              + btns((("render", "자동 보정 후 바로 렌더"), ("each", "자동 보정 후 개별 보정")), ("render",)) +
              '<span style="flex:1"></span><button class="b" style="height:32px;width:88px;min-width:88px">취소</button>'
              '<button class="b new" style="height:32px;width:88px;min-width:88px;background:#d9822b;border-color:#e8964a;color:#fff;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.6)">샘플</button>'
              '<button class="b red" style="height:32px;width:88px;min-width:88px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.6)">시작</button></div></div>')
    return (f'<div style="width:1040px;height:720px;background:#262626;border:1px solid #555;border-radius:6px;box-sizing:border-box;padding:16px;'
            f'display:flex;flex-direction:column;gap:14px;box-shadow:0 10px 30px rgba(0,0,0,.6)">'
            f'<div style="flex:1;display:flex;gap:16px;min-height:0">{left}{right}</div>{bottom}</div>')


def preset_popup():
    """보정 탭 프리셋 창 = AUTO 오른쪽과 같은 모양 + 사용자 프리셋. 누르면 바로 적용(이 클립 · 선택한 클립)."""
    user = "".join(f'<button class="b" style="height:28px">{n}</button>' for n in ("기본값", "잭피쉬 20m", "보홀 오후"))
    return (f'<div style="width:520px;background:#262626;border:1px solid #555;border-radius:6px;box-sizing:border-box;padding:16px;display:flex;flex-direction:column;gap:12px;box-shadow:0 10px 30px rgba(0,0,0,.6)">'
            f'{grid_block(tip=False)}<div style="border-top:1px solid #3a3a3a"></div>{seg("강도", ("약", "중", "강"), 1)}{detail_box()}'
            f'<div style="border-top:1px solid #3a3a3a"></div><div style="display:flex;gap:5px;flex-wrap:wrap;padding-left:81px">{user}</div></div>')


def pop_board():
    w, h = 2500, 800
    items = ['<div style="padding:4px 10px">기본값</div>', '<div style="border-top:1px solid #3a3a3a;margin:3px 0"></div>']
    for grp in ("라이트", "얕은 수심", "깊은 수심"):
        items.append(f'<div style="padding:2px 10px;color:#888;font-size:11px">{grp}</div>')
        for n in ("물고기", "산호초", "거북이", "다이버"):
            hl = ' style="background:#2f4f78;color:#fff"' if (grp, n) == ("얕은 수심", "산호초") else ""
            items.append(f'<div class="mi"{hl}>{grp} · {n}</div>')
    items.append('<div class="new" style="margin:2px 0"><div style="padding:2px 10px;color:#888;font-size:11px">기타</div>'
                 '<div class="mi">블루워터</div><div class="mi">야간</div></div>')
    items += ['<div style="border-top:1px solid #3a3a3a;margin:3px 0"></div>',
              '<div style="padding:3px 10px">잭피쉬 20m</div>', '<div style="padding:3px 10px">보홀 오후</div>']
    plist = (f'<div style="width:210px;display:flex;flex-direction:column;gap:2px"><div class="cb"><span>얕은 수심 · 산호초</span><span>▾</span></div>'
             f'<div style="background:#262626;border:1px solid #555;border-radius:3px;font-size:12px;color:#ddd;padding:3px 0;box-shadow:0 6px 18px rgba(0,0,0,.5)">{"".join(items)}</div></div>')
    menu_items = [("장면", None), ("자동", True), ("라이트", False), ("얕은 수심", False), ("깊은 수심", False),
                  ("블루워터", False), ("야간", False), ("-", None), ("강도", None), ("약", False), ("중", True), ("강", False)]
    mh = []
    for n, chk in menu_items:
        if n == "-":
            mh.append('<div style="border-top:1px solid #3a3a3a;margin:3px 0"></div>')
        elif chk is None:
            mh.append(f'<div style="padding:2px 10px;color:#888;font-size:11px">{n}</div>')
        else:
            dot = '<span style="position:absolute;left:8px;color:#f2c94c">●</span>' if chk else ""
            mh.append(f'<div class="mi">{dot}{n}</div>')
    menu = (f'<div class="new" style="width:150px;display:flex;flex-direction:column;gap:2px">'
            f'<div style="display:flex;justify-content:flex-start"><button class="b" style="border-radius:3px 0 0 3px;min-width:46px">추천</button><button class="b on" style="border-radius:0 3px 3px 0;border-left:none;min-width:18px;width:18px;padding:0">▾</button></div>'
            f'<div style="background:#262626;border:1px solid #555;border-radius:3px;font-size:12px;color:#ddd;padding:3px 0;box-shadow:0 6px 18px rgba(0,0,0,.5)">{"".join(mh)}</div></div>')
    sw, sh = 330, 170
    # 겹침(히스토그램) 모드: 가로 = 밝기, 목표선 세로
    hist = [f'<svg aria-hidden="true" width="{sw}" height="{sh}" viewBox="0 0 150 80" preserveAspectRatio="none" style="position:absolute;left:0;top:0">',
            '<line x1="7.5" y1="0" x2="7.5" y2="80" stroke="#fff" stroke-opacity=".35" stroke-dasharray="2 2"/>',
            '<line x1="142.5" y1="0" x2="142.5" y2="80" stroke="#fff" stroke-opacity=".35" stroke-dasharray="2 2"/>',
            '<path d="M0 80 L10 74 L25 50 L40 60 L60 72 L80 78 L150 80" fill="none" stroke="#e5484d" stroke-width="1.5"/>',
            '<path d="M0 80 L20 76 L40 52 L60 40 L80 58 L110 74 L150 80" fill="none" stroke="#5fd17a" stroke-width="1.5"/>',
            '<path d="M0 80 L30 78 L60 60 L90 30 L120 40 L145 66 L150 70" fill="none" stroke="#4a8fe0" stroke-width="1.5"/>',
            '<circle cx="5" cy="76" r="1.8" fill="#4a8fe0"/><circle cx="145" cy="66" r="1.8" fill="#e5484d"/></svg>']
    scopes = f"""
<div class="new" style="display:flex;flex-direction:column;gap:6px">
<div style="display:flex;gap:10px">
<div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end"><div style="width:{sw}px;height:{sh}px;background:rgba(10,10,10,.92);border:1px solid #444;position:relative">{''.join(hist)}</div></div>
<div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end"><div style="width:{sw}px;height:{sh}px;background:rgba(10,10,10,.92);border:1px solid #444;position:relative">{parade(sw, sh)}</div>
<div style="display:flex;gap:3px"><button class="b" style="height:22px;min-width:52px;font-size:11px">명암</button><button class="b" style="height:22px;min-width:52px;font-size:11px">색 균형</button></div></div>
</div>
<div style="display:flex;gap:10px;align-items:center;font-size:12px;color:#aaa"><span class="b on" style="height:22px">RGB</span><span>→</span><span class="b on" style="height:22px">RGB</span><span>→</span><span class="b" style="height:22px">RGB</span></div>
</div>"""
    body = (f'<div style="width:{w}px;height:{h}px;background:#1b1b1b;font-family:\'Malgun Gothic\',system-ui,sans-serif;color:#ddd;'
            f'display:flex;gap:36px;padding:24px;box-sizing:border-box">'
            f'<div class="new">{auto_popup()}</div><div class="new" style="align-self:flex-start">{preset_popup()}</div>{scopes}</div>')
    return HEAD.format(title="DTME 칩 창·프리셋·추천 메뉴·RGB", style=STYLE) + body + TAIL.format(w=w, h=h)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "Auto.dc.html"), "w", encoding="utf-8").write(auto_board())
    open(os.path.join(OUT, "AutoPop.dc.html"), "w", encoding="utf-8").write(pop_board())
    print("ok")
