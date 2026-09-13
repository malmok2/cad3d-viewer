# CAD 3D 뷰어

논문 그림용 형상 확인 도구. 브라우저에서 STL · OBJ · PLY 를 열어 돌려 보고, 축 정면샷을 직교투영으로 찍고,
전체 치수와 단면을 걸어 PNG(3×)로 저장한다. **HTML 파일 하나로 완결** — 서버·설치·인터넷 연결이 필요 없다.

**열기:** `https://<계정>.github.io/cad3d-viewer/` (GitHub Pages) 또는 `docs/index.html` 을 내려받아 더블클릭.

## 할 수 있는 것

| | |
|---|---|
| 열기 | STL(ASCII/바이너리) · OBJ(`o`/`g` 그룹은 각각 파트로) · PLY(ASCII/바이너리). 창에 끌어다 놓아도 된다 |
| 보기 | 드래그 회전 · 휠 확대 · Shift+드래그 이동. ±X ±Y ±Z 정면(직교투영) · ISO |
| 표시 | 불투명도(숫자+슬라이더) · 전체 치수선 · 격자선(와이어프레임, 사각 격자는 대각선 없이) |
| 단면 | 축 수직 / 시점 방향 / 임의 법선. 여러 개를 동시에 — 남기는 쪽의 교집합 |
| 저장 | PNG 3× (배경 투명 옵션) · 설정이 담긴 링크 복사 (불투명도·치수·단면; 카메라 제외) |
| 언어 | 한국어 / English |

## 변환 도구 (`tools/`, 파이썬 필요)

브라우저가 직접 못 읽는 포맷은 먼저 STL/OBJ 로 바꾼다.

```bash
pip install -r requirements.txt

# STEP · IGES · BREP · SALOME HDF  →  STL   (OpenCASCADE)
python tools/cad2stl.py model.step

# Fluent .msh / .cas (gzip, 바이너리 섹션 포함)  →  OBJ (경계면 zone 별 그룹)
python tools/fluent2obj.py mesh.msh
```

- SpaceClaim: STEP 이나 STL 로 내보낸 뒤 위 절차.
- `fluent2obj.py` 는 interior 면을 뺀 경계면(inlet · outlet · wall …)만 쓴다. `--all` 이면 전부.
- `.cas.h5` / `.msh.h5`(CFF) 는 시험 파일 없이 문서대로 짠 것이라 **실행해 보지 못했다.** 구조가 다르면 파일 트리를 찍고 멈춘다 — 그 출력을 이슈로 올려 주면 맞춘다.

## 뷰어 다시 굽기

`tools/viewer_template.html` 이 소스다. 형상을 파일 안에 내장한 판을 만들려면:

```bash
python tools/build_viewer.py tools/viewer_template.html docs/index.html "이름=파일.stl" "이름2=파일2.stl"
```

인자 없이 굽으면 빈 뷰어(파일 열기만)가 된다. Pretendard 글꼴(`tools/PretendardVariable.woff2`, SIL OFL)은 항상 내장된다.

## 확인한 것 / 못 한 것

- 렌더링은 화면 픽셀을 읽어 검사했다 — 테두리 0, 색상 HSV 검사, WCAG 대비(본문 17.8 · 보조 15.2 · 액센트 8.9), 스무딩 후 평면의 밝기 표준편차 0.
- Fluent ASCII `.msh`(3D hex, zone 9개)로 변환·로드를 확인했다. 바이너리 섹션과 CFF(h5)는 시험 파일이 없어 미확인.
- 2D Fluent 메시(`(2 2)`)는 다루지 않는다.
- 앱 안 미리보기처럼 iframe 에 갇힌 창은 파일 다운로드를 막는다. 그때는 클립보드 복사나 그림 우클릭 저장을 쓴다 — 뷰어가 이 상황을 알려 준다.

## 라이선스

MIT. 내장 글꼴 Pretendard 는 SIL OFL 1.1 — `LICENSE` 참고.
