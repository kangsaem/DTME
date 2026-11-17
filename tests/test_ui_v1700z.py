"""v0.17.0 줌 + 위치(화면): 보정 패널 "렌즈 · 흔들림 · 줌" 묶음의 줌 줄(컷 안 고름 = 흐림 '—' · 한도 · 자석 · 이름 = ×1.00 ·
전부 고름 = 모든 컷 각자 한도까지) · 모니터(잘린 결과만 · 끌기 = 위치 · 더블클릭 = 가운데) · 가로·세로 섞임(화면비 = 많은 쪽) ·
편집 창 소스 목록 여행 머리줄(누르면 그 여행 전체 선택).
사용: python tests/test_ui_v1700z.py"""
import os, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import ff  # noqa: E402
from dtme.project import Project, Segment, Source  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)


st, e = w.state, w.edit
p = Project()
mk = lambda n, ww, hh: Source(path=f"/nope/{n}", fps_num=30, fps_den=1, frames=900, width=ww, height=hh)  # noqa: E731
a, b, c, hd = mk("DJI_20251020094016_0010_D.MP4", 3840, 2160), mk("DJI_20251021101500_0011_D.MP4", 3840, 2160), \
    mk("DJI_20260320141000_0020_D.MP4", 2160, 3840), mk("DJI_20260321101000_0021_D.MP4", 1920, 1080)
p.sources += [a, b, c, hd]
p.segments = [Segment(a.id, 0, 150), Segment(b.id, 0, 150), Segment(c.id, 0, 150), Segment(hd.id, 0, 150)]
st.project = p
e._refresh_sources(); e._refresh_timeline(); wait(0.2)
ga, gb, gc, gh = p.segments
G = e.grade
# ---------------------------------------------------------------- 0) 소스 목록 여행 머리줄
rows = [(e.src_list.item(i).data(Qt.UserRole), e.src_list.item(i).text()) for i in range(e.src_list.count())]
heads = [t for sid, t in rows if sid is None]
assert heads == ["2025.10.20 ~ 10.21", "2026.03.20 ~ 03.21"], heads
e._src_clicked(e.src_list.item(0)); wait(0.1)
assert e._selected_sids() == [a.id, b.id], "머리줄 = 그 여행 클립 전체 선택"
print("소스 목록 머리줄:", heads)
# ---------------------------------------------------------------- 1) 줌 줄: 묶음 이름 · 타임라인 모드에서 고른 컷만
assert any(s_.title == "렌즈 · 흔들림 · 줌" for s_ in G.sections)
assert G.zoom_name.text() == "줌" and not G.zoom_s.isEnabled() and G.zoom_v.text() == "—"
e.mode = "timeline"
e.sel_cut = ga.id; e._sync_zoom()
assert G.zoom_s.isEnabled() and G.zoom_v.text() == "×1.00" and G.zoom_s.maximum() == 200, (G.zoom_v.text(), G.zoom_s.maximum())
assert e._tl_out_key() == "horizontal" and e._zoom_max(ga) == 2.0
n0 = len(st._undo)
G.zoomPressed.emit(); G.zoom_s.setValue(147); wait(0.05)
assert ga.zoom == 1.5 and G.zoom_v.text() == "×1.50" and G.zoom_s.value() == 150, (ga.zoom, G.zoom_s.value())     # 자석
G.zoom_s.setValue(163)
assert ga.zoom == 1.63 and gb.zoom == 1.0
assert len(st._undo) == n0 + 1, "슬라이드바 = 실행취소 1번"
G.zoom_name.clicked.emit()
assert ga.zoom == 1.0 and G.zoom_v.text() == "×1.00", "이름 누르면 ×1.00"
e.sel_cut = gh.id; e._sync_zoom()                    # 1080 → 1080 = ×1 고정·흐림
assert not G.zoom_s.isEnabled() and G.zoom_v.text() == "×1.00"
e.sel_cut = ""; e._sync_zoom()
assert not G.zoom_s.isEnabled() and G.zoom_v.text() == "—"
e.timeline.all_cuts = True; e._sync_zoom()           # 전부 고름 = 모든 컷(각자 한도까지)
assert G.zoom_s.isEnabled() and G.zoom_s.maximum() == 200
G.zoom_s.setValue(200)
zc = ff.zoom_max(c, "horizontal")
print("전부 고름 ×2:", [g.zoom for g in p.segments], "· 세로 클립 한도", zc)
assert [ga.zoom, gb.zoom, gh.zoom] == [2.0, 2.0, 1.0] and gc.zoom == zc and 1.0 < zc < 2.0
e.timeline.all_cuts = False
e.mode = "source"; e._sync_zoom()
assert not G.zoom_s.isEnabled() and G.zoom_v.text() == "—", "타임라인 모드에서만"
# ---------------------------------------------------------------- 2) 모니터: 잘린 결과만 · 끌기 · 더블클릭
e.mode = "timeline"
mon = e.player.mon
img = QImage(384, 216, QImage.Format_RGB32); img.fill(QColor("#101010"))
qp = QPainter(img); qp.fillRect(96, 54, 192, 108, QColor("#ff0000")); qp.end()      # 가운데 절반 = 빨강(줌 ×2 사각형)
mon.set_image(img); mon.set_aspect(16 / 9)
for g_ in p.segments:
    g_.zoom, g_.dx, g_.dy = 1.0, 0.0, 0.0
e.sel_cut = ga.id; e._tl_seg = ga; e._sync_zoom(); wait(0.1)
assert mon.cut_view is not None and mon.cut_view[0] == 1.0 and not mon._cut_pannable(), mon.cut_view
G.zoom_s.setValue(200); wait(0.1)
assert mon.cut_view[:5] == (2.0, 0.0, 0.0, 960.0, 540.0) and mon._cut_pannable()
shot = mon.grab().toImage()
o = mon._out_rect
reds = sum(1 for fx, fy in ((0.3, 0.2), (0.97, 0.3), (0.03, 0.7), (0.7, 0.8), (0.5, 0.15))      # (버튼·로딩 상자 자리는 피함)
           if QColor(shot.pixel(int(o.left() + fx * o.width()), int(o.top() + fy * o.height()))).red() > 200)
assert reds == 5, f"줌 ×2 = 가운데 사각형이 화면에 꽉(빨강 {reds}/5)"
n1 = len(st._undo)
c0 = o.center().toPoint()
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, c0); wait(0.05)
assert mon._drag and mon._drag[0] == "pan" and len(st._undo) == n1 + 1
QTest.mouseMove(mon, c0 + QPoint(40, 20)); wait(0.05)
QTest.mouseMove(mon, c0 + QPoint(80, 30)); wait(0.05)
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, c0 + QPoint(80, 30)); wait(0.1)
print("끌기:", round(ga.dx), round(ga.dy), "· 한도", mon.cut_view[3:5])
assert ga.dx > 100 and ga.dy > 30 and abs(ga.dx) <= 960 and abs(ga.dy) <= 540 and gb.dx == 0
assert ff.seg_view(a, ga, "horizontal")[2] > 960
QTest.mouseDClick(mon, Qt.LeftButton, Qt.NoModifier, mon._out_rect.center().toPoint()); wait(0.1)
assert (ga.dx, ga.dy) == (0.0, 0.0), "더블클릭 = 가운데"
G.zoom_s.setValue(100); wait(0.05)
assert not mon._cut_pannable()
# 세로 클립 → 가로 영상: 줌 없이도 위아래 끌기
e.sel_cut = gc.id; e._tl_seg = gc; e._sync_zoom(); wait(0.05)
assert mon.cut_view[3] == 0.0 and mon.cut_view[4] == 540.0 and mon._cut_pannable()
pimg = QImage(216, 384, QImage.Format_RGB32); pimg.fill(QColor("#203040")); mon.set_image(pimg); wait(0.05)
o = mon._out_rect
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, o.center().toPoint()); wait(0.05)
QTest.mouseMove(mon, o.center().toPoint() + QPoint(30, 25)); wait(0.05)
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, o.center().toPoint() + QPoint(30, 25)); wait(0.1)
print("세로 클립 위아래:", gc.dx, round(gc.dy))
assert gc.dx == 0.0 and 0 < gc.dy <= 540.0
# 고르지 않은 컷이 보일 때 = 못 끎
e.sel_cut = ga.id; e._tl_seg = gc; e._sync_zoom()
assert not mon.cut_edit and not mon._cut_pannable()
# ---------------------------------------------------------------- 3) 가로·세로 섞임: 화면비·출력 = 많은 쪽
e._apply_aspect()
assert mon.out_aspect > 1 and e._tl_out_key() == "horizontal"
p.segments = [gc, ga]                                # 세로 첫 컷이어도(1:1 = 가로)
assert e._tl_out_key() == "horizontal" and e._new_item(list(p.segments), tl=True).orientation == "horizontal"
c2 = mk("DJI_20260322101000_0022_D.MP4", 2160, 3840); p.sources.append(c2)
p.segments = [ga, gc, Segment(c2.id, 0, 150)]
e._apply_aspect()
assert e._tl_out_key() == "vertical" and mon.out_aspect < 1, "세로 2 · 가로 1 = 세로"
# 실행취소 = 줌·위치도
ga.zoom = 1.0; st.checkpoint(label="t"); ga.zoom = 1.7
st.undo(); wait(0.1)
assert st.project.segments[0].zoom == 1.0
st.dirty = False
print("OK test_ui_v1700z", flush=True); os._exit(0)
