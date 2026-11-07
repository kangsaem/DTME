"""AUTO 창 · 프리셋 창 · RGB 그래프 도움 · 반반 샘플 화면 점검(오프스크린).
사용: python tests/test_ui_auto.py <4K테스트.mp4> <작업폴더>   (합성 수중 영상은 test_auto 와 같은 방식으로 만듦)"""
import os, sys, time, shutil
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication, QDialog
import main as M
import test_auto as TA
from dtme import paths, ui_auto, project as P
from dtme.ui_main import MainWindow
T4K, WORK = sys.argv[1:3]
work = Path(WORK); work.mkdir(parents=True, exist_ok=True)
shutil.rmtree(paths.app_dir() / "presets", ignore_errors=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


st, e, gp = w.state, w.edit, w.edit.grade
v1 = TA.make_video(work / "shallow.mp4", ["shallow", "shallow"], 2.0)
v2 = TA.make_video(work / "deep.mp4", ["deep", "deep"], 2.0)
v3 = TA.make_video(work / "change.mp4", ["shallow", "deep", "deep", "shallow"], 2.0)
e.import_files([v1.path, v2.path, v3.path, T4K])
assert wait(120, lambda: len(st.project.sources) == 4 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
p = st.project
p.grade["lut"] = ""                      # 합성 영상은 Log 가 아님
p.output.encoder, p.output.gpu_decode = "x264", False
a, b, c, d = p.sources
# 4K 테스트 영상은 미리 손보정(C) → '기존 보정 유지' 면 제외
d.grade = {"r_gain": 1.3}

# ---------------- AUTO 창: 분석 · 인식 · 직접 지정 · 개별 보정
dlg = e.make_auto_dialog(); dlg.show()
wait(1.0)
print("창 열기만 → 작업 없음:", [r.prog for r in dlg.rows], st.work, repr(dlg.state_lab.text()))
assert all(r.prog == 0 and r.result is None for r in dlg.rows) and not st.work and not dlg.jobs
print("체크:", [r.checked for r in dlg.rows], "(기본 = 기존 보정 무시·키프레임 자동 → 모두)")
assert [r.checked for r in dlg.rows] == [True] * 4 and dlg.keep.value() == "drop" and dlg.keys.value() == "auto"
dlg.keep.btns["keep"].click(); wait(0.1)
assert [r.checked for r in dlg.rows] == [True, True, True, False]      # C 인 4번째는 제외
assert dlg.b_each.text() == "보정+편집"
dlg.start_analysis()
assert wait(60, lambda: any(0 < r.prog < 1 for r in dlg.rows))
print("분석 중:", repr(dlg.state_lab.text()), {k: v[:2] for k, v in st.work.items()})
dlg.grab().save(str(work / "shot_auto_analyzing.png")); e.src_list.grab().save(str(work / "shot_src_analyzing.png"))
assert wait(120, lambda: not dlg.pending())
assert not any(w_[0] == "analyze" for w_ in st.work.values()), st.work
print("분석 끝:", repr(dlg.state_lab.text()))
for r in dlg.rows[:3]:
    print("  인식:", r.rec, "→", r.result["preset"], "키", len(r.result["gkeys"].get("r_gain", [])), dlg.row_text(r))
assert dlg.rows[0].result["scene"] == "shallow" and dlg.rows[1].result["scene"] == "deep" and dlg.rows[2].result["gkeys"]
# 2번째 줄 선택 → 깊은 수심 · 거북이 직접 지정, 출력 세로
dlg.list.setCurrentRow(1); wait(0.1)
dlg.grid.btns["night"].click(); dlg.out.btns["vertical"].click(); wait(0.1)
lab, fixed, sub = dlg.row_text(dlg.rows[1])
print("직접 지정:", lab, fixed, sub, dlg.rows[1].out)
assert lab == "야간" and fixed and dlg.rows[1].out == "vertical"
print("세부 정보:", dlg.detail.title.text(), dlg.detail.vals["r_gain"].text(), dlg.detail.vals["gy"].text(), "물 노이즈", dlg.detail.vals["wnr"].text())
# 버튼 글자 가운데 정렬·크기
for bt in (dlg.b_cancel, dlg.b_sample, dlg.b_each, dlg.b_start):
    assert bt.size().toTuple() == (88, 32), bt.text()
print("아래 버튼:", [bt.text() for bt in (dlg.b_cancel, dlg.b_sample, dlg.b_each, dlg.b_start)], "격자 맨 위:", dlg.grid.btns["auto"].text())
# 기존 보정 무시 → 4번째도 체크
dlg.keep.btns["drop"].click(); wait(0.1); assert dlg.rows[3].checked
dlg.keep.btns["keep"].click(); wait(0.1); assert not dlg.rows[3].checked
dlg.keys.btns["auto"].click()
dlg.name.setText("BOHOL"); wait(0.1); print("이름 예:", dlg.name_eg.text())
dlg.grab().save(str(work / "shot_auto.png"))
# [샘플]: 저장 창 대신 설정 직접
ui_auto.SampleDialog.exec = lambda self: QDialog.Accepted
ui_auto.SampleDialog.folder_text = None
sdir = work / "samples"; shutil.rmtree(sdir, ignore_errors=True)
orig_init = ui_auto.SampleDialog.__init__
def init(self, name, folder, parent=None, layout=""):
    orig_init(self, name, str(sdir), parent, layout)
    self.size.btns["1280"].click(); self.fmt.btns["jpg"].click(); self.att["preset"].setChecked(True)
ui_auto.SampleDialog.__init__ = init
e._auto_sample(dlg)
assert wait(60, lambda: any(w_[0] == "sample" and w_[1] >= 0 for w_ in st.work.values()))
print("샘플 중:", repr(dlg.state_lab.text()), {k: v for k, v in st.work.items()})
e.src_list.grab().save(str(work / "shot_src_sample.png"))
assert wait(240, lambda: sdir.exists() and len(list(sdir.glob("*.jpg"))) >= 18 and not dlg.busy)
assert not st.work, st.work
names = sorted(x.name for x in sdir.glob("*.jpg"))
print("샘플:", len(names), names[:2], "… 클립 값 그대로:", P.is_plain(a))
assert len(names) == 18 and P.is_plain(a) and names[0].startswith("BOHOL_")
# [시작] 개별 보정
def _no_ask(title=""):
    raise AssertionError("[보정+편집]은 저장폴더를 묻지 않아야 함")
e._ask_folder = _no_ask
dlg.b_each.click(); wait(1)                           # [보정+편집]: 폴더 안 물음
e._ask_folder = lambda title="": str(work / "out")
print("적용:", [(s.auto.get("preset"), s.auto.get("by"), len(s.gkeys.get("r_gain", [])), s.out) for s in (a, b, c)])
for s_ in (a, b, c):
    g_ = st.project.grade_for_source(s_.id)
    assert g_["b_gain"] >= 0.9 * g_["r_gain"] - 1e-6 and g_["hue"] == 5.0, (g_["r_gain"], g_["b_gain"], g_["hue"])
assert a.auto["preset"] == "shallow" and b.auto == {**b.auto, "preset": "night", "by": "user"} and b.out == "vertical"
assert c.gkeys and d.grade == {"r_gain": 1.3} and p.output.prefix == "BOHOL"
assert gp.view_mode() == "split"
w.undo(); wait(0.5); print("실행취소 → 보정 없음:", P.is_plain(st.project.sources[0])); assert P.is_plain(st.project.sources[0])
w.redo = None
p = st.project; a, b, c, d = p.sources

# ---------------- AUTO 바로 렌더 (2개만)
dlg2 = e.make_auto_dialog(); dlg2.show()
dlg2.keep.btns["keep"].click(); wait(0.1)              # 기본은 무시 → 손보정(C) 4번째 제외
dlg2.rows[2].checked = False
assert wait(5, lambda: not dlg2.pending()), "이미 분석한 영상 = 바로 결과"
dlg2.b_start.click()                                   # [보정+렌더]
assert wait(120, lambda: any(w_[0] == "render" for w_ in st.work.values()))
e.src_list.grab().save(str(work / "shot_src_render.png"))
assert wait(300, lambda: not e.render_panel.running and len(list((work / "out").glob("*.mp4"))) >= 2)
outs = sorted(x.name for x in (work / "out").glob("*.mp4"))
print("렌더:", outs, "막대 숨김:", not e.auto_bar.isVisible())
assert len(outs) == 2
w.grab().save(str(work / "shot_main_auto.png"))

# ---------------- 보정 탭 프리셋 창(고정값) · 추천(자동)
e._select_source(p.sources[1].id); wait(1.0)
gp.apply_choice("night", "mid"); wait(0.3)
g = p.grade_for_source(p.sources[1].id)
print("프리셋 야간:", g["r_gain"], g["water"], g["nr_chroma"], gp.preset.text())
assert g["water"] == 0 and "야간" in gp.preset.text()
# 옛 키로 저장된 프로젝트도 이름이 나옴
p.sources[1].auto = {"preset": "shallow/turtle", "by": "user"}; gp._fill_presets(); print("옛 키 →", gp.preset.text()); assert "얕은 수심" in gp.preset.text()
pd = ui_auto.PresetDialog(p.grade, "night", "mid", gp); pd.show(); wait(0.2)
pd.grid.hovered.emit("deep"); wait(0.1); print("프리셋 창 세부:", pd.detail.title.text(), pd.detail.vals["r_gain"].text())
pd.grab().save(str(work / "shot_preset.png")); pd.close()
gp.apply_choice("auto", "strong")
assert wait(60, lambda: "추천 →" in e.status.text())
print("추천:", e.status.text()[-40:], p.sources[1].auto)
# 물빛·녹황 슬라이더 표시
print("물빛/녹황 슬라이더:", gp.sliders["water"].value(), gp.sliders["gy"].value())
# ---------------- RGB: 겹침 → 파레이드 → 끔, [명암] [색 균형]
e.player.seek(30); wait(2)
gp.rgb.click(); wait(0.3); assert e.player.mon.scope == 1 and e.player.mon.sbox.isVisible()
gp.rgb.click(); wait(1.0); assert e.player.mon.scope == 2
w.grab().save(str(work / "shot_parade.png"))
e.fix_contrast(); assert wait(20, lambda: "명암 →" in e.status.text())
cv = p.grade_for_source(p.sources[1].id)["curve"]; print("명암 커브:", cv)
e.fix_balance(); assert wait(20, lambda: "색 균형 →" in e.status.text()); print(e.status.text()[-30:])
gp.rgb.click(); wait(0.2); assert e.player.mon.scope == 0 and not e.player.mon.sbox.isVisible()
# ---------------- 반반 샘플 타일
gp.make_samples(); assert wait(30, lambda: len(gp.pix) >= 6)
print("샘플 타일:", len(gp.pix))
w.grab().save(str(work / "shot_samples.png"))
# ---------------- 영상을 넣자마자 AUTO: 로딩이 끝나는 대로 분석(분석 실패 없음)
v4 = TA.make_video(work / "fresh.mp4", ["shallow", "deep"], 3.0)
v5 = TA.make_video(work / "fresh2.mp4", ["deep", "deep"], 3.0)
e.import_files([v4.path, v5.path]); wait(0.05)
dlg3 = e.make_auto_dialog(); dlg3.show()
fresh = [r for r in dlg3.rows if st.project.source(r.sid).path.endswith(("fresh.mp4", "fresh2.mp4"))]
print("바로 연 AUTO:", [(dlg3.row_text(r)[2], r.checked) for r in fresh])
assert all(r.checked for r in fresh)
wait(3); assert not any(r.result or r.prog for r in fresh), "버튼 전에는 분석 안 함"
dlg3.start_analysis()
assert wait(180, lambda: all(r.result for r in fresh)), [r.error for r in fresh]
print("로딩 후 분석:", [r.result["preset"] for r in fresh], "실패", [r.error for r in fresh])
assert not any(r.error for r in fresh)
dlg3.grab().save(str(work / "shot_auto_fresh.png")); dlg3.cancel()
print("UI AUTO OK")
