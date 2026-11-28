# 윈도우 미니 위젯 — 마래푸 문자 도우미

`projects/sms-helper` 의 웹 앱(v1.4.10)을 pywebview 창에 그대로 넣은 데스크톱 프로그램입니다.
필라테스 계산기(`projects/pilates-calculator/`)와 같은 frameless 미니 위젯 방식입니다.

- **창** 420×760 (최소 380×620) · 리사이즈 가능 · 마지막 위치·크기 기억 (`%APPDATA%\MaraepuSmsHelper\state.json`)
- **상단 바** `.pywebview-drag-region` 드래그 이동 · `📌` 항상 위 고정(아이콘만, 툴팁 `항상 위 고정`) · `—` 최소화 · `×` 닫기
- **업데이트** 실행할 때 GitHub Releases 의 `widget-v*` 중 최신만 골라 비교, 새 버전일 때만 `업데이트` 버튼
- **복사** `window.pywebview.api.copy` → Win32 `ctypes`(`argtypes`/`restype` 지정) → PowerShell `Set-Clipboard` 폴백.
  대표 `복사하기` 버튼은 브리지로 바로 처리하고, 웹 앱의 `AndroidCopy` 통로도 브리지에 연결합니다.
- **문자 앱 열기** 데스크톱에는 문자 앱이 없으므로 문구를 클립보드에 넣고 “문자 앱에 붙여넣어 보내세요” 안내만 띄웁니다.
- **저장** 웹 앱의 localStorage(내 정보·문구 수정·연락처)는 `private_mode=False` + `%APPDATA%\MaraepuSmsHelper\webview` 에 남습니다.
  저장소 출처가 바뀌면 설정이 사라지므로 로컬 서버 포트를 `48231` 로 고정합니다(이미 쓰이면 그때만 빈 포트).

## 구조

```
desktop/
  widget.py              pywebview 창 · 상태 저장 · 클립보드 · 업데이트 확인 · Api 브리지
  version.py             WIDGET_VERSION (릴리즈 태그 widget-v<버전>)
  prepare_www.py         웹 앱 복사 + index.html 에 상단 바·widget.css·widget.js 주입
  web/widget.css         상단 바 스타일 (웹 앱 CSS 는 건드리지 않음)
  web/widget.js          상단 바 동작 + 복사/문자 앱 브리지
  build.spec             PyInstaller (onedir · windowed · icon)
  installer.iss          Inno Setup (MaraepuSmsHelper-Setup.exe)
  assets/icon.ico        앱 아이콘 (icons/icon-512.png 에서 변환)
  tests/test_widget.py   단위 테스트 28개 (GUI·pywebview 없이)
  tests/capture_widget.py 420×760 미리보기 캡처 → downloads/sms-helper-widget-preview.png
```

`desktop/www/` 는 빌드할 때마다 새로 만들어지는 산출물입니다(저장소에 올리지 않음). 웹 앱을 고치면
`prepare_www` 가 다음 빌드에서 그대로 가져가므로 위젯이 웹·폰과 어긋나지 않습니다.

## 빌드

```bash
python desktop/prepare_www.py
python desktop/widget.py --selftest          # GUI 없이 확인
python -m PyInstaller --noconfirm --clean desktop/build.spec
dist\MaraepuSmsHelper\MaraepuSmsHelper.exe --selftest --strict
ISCC.exe desktop\installer.iss               # dist\installer\MaraepuSmsHelper-Setup.exe
```

- `Api` 는 public 속성을 두지 않고 위젯 참조를 `self._widget` 으로만 보관합니다.
  (pywebview 5.4 가 public 속성을 재귀 탐색하다 죽으면 `window.pywebview.api` 가 비어 복사·닫기가 먹통이 됨)
- 설치 파일은 Microsoft Edge WebView2 런타임을 사용합니다(윈도우 11 기본 포함).

## 릴리즈

`.github/workflows/windows-widget.yml` 이 `widget-v*` 태그에서 빌드해 Release 에
`MaraepuSmsHelper-Setup.exe` · `MaraepuSmsHelper-Windows.zip` 을 올립니다.
현재 GitHub 연결 토큰에 `workflows` 쓰기 권한이 없어 같은 내용을 **`ci/windows-widget.yml`** 에 두었습니다.
GitHub 웹에서 아래 주소로 파일을 만들고 `ci/windows-widget.yml` 내용을 그대로 붙여 넣으면 됩니다.

https://github.com/hs0522/sms-helper/new/main?filename=.github/workflows/windows-widget.yml

```bash
git tag widget-v1.0.0 && git push origin widget-v1.0.0
```
