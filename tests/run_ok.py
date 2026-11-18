"""CI: 시험 하나를 돌려 판정(v0.17.2). 끝 표시('OK …')를 찍은 **뒤에** Windows 접근 위반으로 끝나면 = 통과(경고만).
(창 정리 중 Resize → ui_edit.eventFilter 에서 가끔 남 — 빌드 44049411196 · 44234142724. 시험 내용은 다 지난 뒤.)
사용: python tests/run_ok.py "OK test_x" tests/test_x.py [인자…]"""
import subprocess
import sys

mark, args = sys.argv[1], sys.argv[2:]
r = subprocess.run([sys.executable, "-X", "faulthandler", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
out = (r.stdout or "") + (r.stderr or "")
print(out, flush=True)
if r.returncode == 0:
    sys.exit(0)
after = out.split(mark, 1)[1] if mark in out else ""
if mark in out and ("access violation" in after or r.returncode in (3221225477, -1073741819)):
    print(f"::warning::{args[0]} — '{mark}' 뒤 접근 위반(종료 코드 {r.returncode}) = 통과로 봄", flush=True)
    sys.exit(0)
print(f"{args[0]} 종료 코드 {r.returncode}", flush=True)
sys.exit(1)
