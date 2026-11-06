"""버튼 견본 그림 = design/button_ref.png (DTME ui_style 의 실제 그리기 코드로).
색 종류 × 상태(보통 · 마우스 · 눌림 · 켜짐 · 꺼짐). 다른 프로그램(MOSCO 등)에 적용한 뒤 이 그림과 나란히 비교.
사용: python design/gen/make_buttons.py  (PySide6 필요, 화면 없어도 됨)"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication
from dtme import ui_style as S

app = QApplication(sys.argv)
rows = [("기본", S.BASE, "#e6e6e6", False)] + [(k, *S.TONES[k]) for k in ("red", "orange", "light", "blue", "navy", "cut", "key_on", "overlay")]
cols = [("보통", "normal"), ("마우스", "hover"), ("눌림", "pressed"), ("켜짐", "on"), ("꺼짐", "disabled")]
BW, BH, GX, GY, LW, TOP = 120, 32, 16, 14, 120, 48
W = LW + len(cols) * (BW + GX) + 16
H = TOP + len(rows) * (BH + GY) + 16
img = QImage(W * 2, H * 2, QImage.Format_RGB32)
img.setDevicePixelRatio(2)
img.fill(QColor("#232323"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
f = QFont("Pretendard")
f.setPixelSize(13)
p.setFont(f)
p.setPen(QColor("#9a9a9a"))
for j, (t, _k) in enumerate(cols):
    p.drawText(QRectF(LW + j * (BW + GX), 14, BW, 20), Qt.AlignCenter, t)
for i, (name, bg, fg, bold) in enumerate(rows):
    y = TOP + i * (BH + GY)
    p.setPen(QColor("#c8c8c8"))
    p.drawText(QRectF(10, y, LW - 16, BH), Qt.AlignVCenter | Qt.AlignLeft, name)
    for j, (_t, st) in enumerate(cols):
        r = QRectF(LW + j * (BW + GX), y, BW, BH)
        alpha = 225 if name == "overlay" else 255
        if name == "overlay":                      # 반투명 = 화면 위에 얹힘(줄무늬 바탕 위에서 보이게)
            for k in range(0, int(BW), 8):
                p.fillRect(QRectF(r.left() + k, r.top(), 4, BH), QColor("#3d6a8a"))
        if st == "on":
            S.paint_bevel(p, r, S.SEL_BLUE, "normal", alpha, edge=S.EDGE_BLUE)
            col = "#ffffff"
        else:
            S.paint_bevel(p, r, bg, st, alpha)
            col = S.disabled_fg(fg) if st == "disabled" else fg
        ff = QFont(f)
        ff.setBold(bold or st == "on" and False)
        p.setFont(ff)
        p.setPen(QColor(col))
        p.drawText(r, Qt.AlignCenter, "버튼")
        p.setFont(f)
p.end()
out = os.path.join(HERE, "..", "button_ref.png")
img.save(out)
print(out, img.width(), img.height())
