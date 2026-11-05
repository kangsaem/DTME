# HANDOFF — DTME

다음 대화에서 이어 작업할 때 이 문서를 기준으로 한다.

## 현재 상태 (v0.3.0, 2026-11-05)

1단계 전체 구현 완료. Linux에서 엔진·화면 검증, GitHub Actions(Windows)에서 빌드·엔진·exe 실행 점검 통과. **사용자 PC 실기 테스트 대기.**

다운로드: Actions → 최신 성공한 "Windows build" → Artifacts `DTME-windows` (약 200MB, 30일 보관).
Release zip 이 필요하면 GitHub 웹에서 `v0.1.0` 같은 태그로 Release 를 만들면 자동 빌드됨(Claude 세션에서는 태그 push 가 막혀 있음).

## 변경 이력

- v0.3.0: 사용자 기준으로 화면 재구성
  - 작업 방식 변경: 소스마다 인/아웃·배속 1개(소스 바) → ▼(↓) 타임라인 끝에 붙임 / ▶(Enter) 렌더 리스트로 바로
  - 타임라인: 결과 길이 비례 블록, 드래그 순서 변경, 확대 슬라이더, 결과 시간 눈금, 30초 선, 전체 삭제, 렌더 리스트로
  - 렌더 탭(인코더·비트레이트·디코딩·저장폴더 + 렌더 리스트 + 렌더 버튼). 기존 출력 탭·구간 표·스틸 보정 대상 삭제
  - 모니터: 정지·이동·드래그·역재생은 프록시 프레임을 ffmpeg로 한 장씩 뽑아 즉시 표시(검은 화면 해결), J/L 2배속 고정, K 삭제
  - 스틸 = 즉시 4K 16bit PNG 저장. 샘플 = 현재 클립 전체에서 6장 PNG, 클릭 시 이동·재렌더 없이 모니터에 표시
  - E/C 코너 표시(소스 바·타임라인 컷), 용어 정리(소스·보정·기본값·R·B·디노이즈·리셋·기본값으로 저장)
  - 상단 저장하기·불러오기·실행취소(스냅샷 방식, 80단계)
  - 단축키: [ ] 추가, ↓ / Enter, Ctrl+Z/S/O
  - 확인 필요: 요청 원문에 Enter 가 ‘타임라인으로’와 ‘렌더 리스트로’ 두 번 나옴 → 버튼 정의대로 ↓=타임라인, Enter=렌더 리스트로 구현

- v0.2.0: 사용자 피드백 반영
  - 영상 추가 즉시 목록 등록(0.002초), 분석(4병렬)·프록시(1개씩)는 백그라운드, 진행 막대, 선택 파일 프록시 우선
  - 분석 끝나면 첫 장면 바로 표시. 프록시 전에도 정지화면 모드로 프레임 이동·컷 지정 가능
  - 단축키를 Windows 스캔코드(물리 키)로 인식 → 한/영·포커스 무관. 앱 전체 이벤트 필터
  - 모든 동작 버튼화, 상태줄 안내, 컷인 대기 줄을 구간 목록에 노란색으로 표시
  - 보정을 편집 화면 오른쪽 패널로 통합(탭 2개). 정지 시 화면 = 원본 기준 정확한 보정 미리보기
  - 미리보기 프레임 캐시 동시 생성 경쟁 수정(락 + 임시파일 rename), 시작 시 프레임 캐시 비움
- v0.1.0: 1단계 최초 구현

## 확정된 요구사항

- 원본: DJI Osmo Action 4, D-Log M, HEVC 10bit 3840×2160 **59.94fps CFR**, AAC 스테레오
- 사용 PC: Threadripper PRO 5975WX 32코어 / RAM 256GB / RTX 4090 / Windows
- 결과 영상 30초 이하, 29.97fps, 1920×1080 또는 1080×1920(중앙 크롭 고정)
- 출력: 소스마다 1개(기본) 또는 전체 이어붙이기, 장면 전환은 컷
- 보정: 기본값 + 클립별 전 항목 덮어쓰기, 스틸은 클립 위에 추가 조정 후 4K 16bit TIFF
- 커브 마스터 1개(중간 포인트 최대 5), Hue 회전 ±15°, R/B 게인 0.70~1.50
- 노이즈: 영상은 축소 후 끔/약/중, 스틸은 강까지
- 오디오 유지(배속 시 atempo), 문제 있으면 끌 수 있음
- 설치 없이 실행(PyInstaller onedir + bin/ffmpeg)

## 구조

```
app/main.py              진입점(다크 테마)
app/dtme/paths.py        exe 위치 기준 bin/ luts/ cache/ settings.json
app/dtme/project.py      데이터 구조(JSON 저장), 보정 병합, 결과 길이 계산
app/dtme/ff.py           FFmpeg: probe, 프록시, 필터 체인, 렌더, 스틸, 미리보기, 선명도
app/dtme/state.py        공유 상태, 불러오기, 프록시 작업
app/dtme/jobs.py         스레드 풀(프록시 1 / 미리보기 6 / 렌더 1)
app/dtme/ui_edit.py      편집·보정 화면(소스 | 모니터·소스 바·조작·타임라인 | 보정), 키 입력 필터, 스틸 PNG
app/dtme/ui_grade.py     보정 패널(GradePanel), 샘플 6장 PNG
app/dtme/ui_bars.py      SourceBar(현재 클립), SeqTimeline(컷 이어붙이기)
app/dtme/ui_render.py    렌더 탭
app/dtme/ui_player.py    모니터(재생=QMediaPlayer, 정지=프록시 프레임 grab)
tests/test_core.py       실제 샘플로 점검 (python tests/test_core.py 샘플.MP4 LUT.cube)
tests/test_engine_min.py CI용 합성 4K 점검
.github/workflows/build.yml  Windows 빌드 → Artifacts "DTME-windows" (v* 태그 시 Release zip)
```

## 핵심 기술 결정과 근거

- 위치는 전부 **원본 프레임 번호**. 탐색은 `-ss (n-0.5)/fps` → n번 프레임 정확히 잡힘(실측 확인)
- 프록시: 960px, libx264 `-g 1`(전 프레임 키프레임), 기본 LUT를 입혀 보기 좋게
- 렌더 체인: trim → setpts(배속) → fps 29.97 → 크롭/축소 → hqdn3d → gbrp16 → lut3d → colorchannelmixer → curves(m) → huesaturation → cas → BT.709 YUV
- **RGB→YUV 변환 시 BT.709 명시 필수** (`TO_YUV709`). 안 하면 BT.601로 변환돼 색 틀어짐(평균 차이 4.8 → 2.5)
- nlmeans는 8bit로 떨어져 사용 안 함 → hqdn3d. hue 필터 대신 huesaturation(RGB 16bit 유지)
- LUT 경로 이스케이프 문제 회피: cache/lut 에 해시 이름으로 복사 후 cwd 지정
- 미리보기: 원본 프레임을 1280px 10bit ffv1로 캐시 → 같은 체인 적용 → PNG
- GPU 디코딩(-hwaccel cuda) 실패 시 자동 CPU 재시도. NVENC 불가 시 출력 탭에서 x264 선택
- 플레이어: Qt QMediaPlayer(FFmpeg 백엔드). J(역재생)는 탐색 반복. 이동 직후엔 프록시 화면 → 350ms 멈추면 원본 보정 화면

## 검증된 것 (Linux, CPU 2코어, x264)

- 샘플 3.4초: 프록시 프레임 수 일치, 2x/1x/½x 프레임 수·길이 정확, 가로/세로, 오디오, 4K TIFF, 선명도
- UI(오프스크린): 불러오기 → I/O/배속 → 스틸 → 렌더 → 저장/다시 열기
- 미리보기 vs 렌더 색 차이: 평균 약 2.5/255

## 미검증 (Windows 실기에서 확인 필요)

- [x] Actions 빌드 성공, exe 실행 점검 통과(창 생성 + Qt 멀티미디어 로드), Windows에서 엔진 점검 통과 (FFmpeg master 2026-11-04)
- [ ] QMediaPlayer 재생·프레임 이동·J/K/L 체감 (오프스크린이라 영상 표시 미확인)
- [ ] NVENC / CUDA 디코딩 동작과 속도
- [ ] 실제 4K 장시간 파일에서 프록시 생성 시간
- [ ] Mavic 3 Pro용으로 표기된 D-Log M LUT 가 액션4 에서 맞는지 (샘플로는 정상으로 보임)

## 다음 할 일 후보

- Windows 실기 피드백 반영
- 타임라인에서 구간 가장자리 드래그로 길이 조정
- 보정 프리셋 저장/불러오기(파일)
- 스틸 미리보기 100% 확대 보기
