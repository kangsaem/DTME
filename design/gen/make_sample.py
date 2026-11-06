"""AUTO [샘플] 누르면 뜨는 창: 저장폴더 · 크기 · 형식 · 파일 이름."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from make_auto import HEAD, TAIL, STYLE, seg

def field(label, inner):
    return (f'<div style="display:grid;grid-template-columns:76px 1fr;gap:5px;align-items:center"><span class="lbl" style="text-align:right;padding-right:4px">{label}</span>{inner}</div>')

def inp(text, w="100%", ph=False):
    return (f'<div style="width:{w};height:28px;box-sizing:border-box;background:#1a1a1a;border:1px solid #555;border-radius:3px;display:flex;align-items:center;'
            f'padding:0 8px;font-size:12px;color:{"#777" if ph else "#eee"}">{text}</div>')

def toggles(opts):
    return ('<div style="display:flex;gap:6px">' + "".join(
        f'<span class="b{" on" if on else ""}" style="height:28px">{t}</span>' for t, on in opts) + '</div>')

def dialog():
    rows = [
        field("저장폴더", '<div style="display:flex;gap:6px">' + inp("D:/Dive/2026 Bohol/DTME_출력") + '<button class="b" style="height:28px">선택…</button></div>'),
        seg("크기", ("1280", "1920", "2560", "4K"), 1),
        seg("형식", ("PNG 8bit", "PNG 16bit", "JPG"), 0),
        '<div style="border-top:1px solid #3a3a3a"></div>',
        field("이름", inp("DTME", "180px")),
        field("붙이기", toggles((("날짜시간", True), ("프리셋", False), ("번호", True)))),
        field("", '<div style="font-size:12px;color:#c4cad1;font-family:Consolas,monospace">DTME_202610251207_1.png … _6.png</div>'),
    ]
    bottom = ('<div style="display:flex;gap:8px;justify-content:flex-end;padding-top:6px"><button class="b" style="height:32px;width:88px">취소</button>'
              '<button class="b" style="height:32px;width:88px;background:#d9822b;border-color:#e8964a;color:#fff;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.6)">샘플</button></div>')
    return (f'<div style="width:560px;background:#262626;border:1px solid #555;border-radius:6px;box-sizing:border-box;padding:16px;display:flex;flex-direction:column;gap:10px;'
            f'box-shadow:0 10px 30px rgba(0,0,0,.6)">{"".join(rows)}{bottom}</div>')

w, h = 640, 480
body = (f'<div style="width:{w}px;height:{h}px;background:#1b1b1b;font-family:\'Malgun Gothic\',system-ui,sans-serif;color:#ddd;padding:24px;box-sizing:border-box">'
        f'<div class="new" style="display:inline-block">{dialog()}</div></div>')
open(os.path.join(os.path.dirname(__file__), "..", "project", "SampleDlg.dc.html"), "w", encoding="utf-8").write(
    HEAD.format(title="DTME 샘플 저장 창", style=STYLE) + body + TAIL.format(w=w, h=h))
print("ok")
