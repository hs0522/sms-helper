"""데스크톱 위젯용 웹 자산 묶음(www)을 만든다.

`projects/sms-helper/` 의 웹 앱(v1.4.9)을 그대로 복사하고, 위젯 창에 필요한
상단 드래그 바·버튼·브리지 스크립트만 index.html 에 끼워 넣는다. 웹 앱 본체
(index.html·styles.css·js/)는 한 줄도 고치지 않으므로 웹·폰 화면과 항상 같다.

쓰는 곳
    python desktop/prepare_www.py            # desktop/www 새로 만들기
    desktop/build.spec                       # PyInstaller 빌드 직전에 자동 실행

만들어지는 구조
    desktop/www/
        index.html          (상단 바가 주입된 사본)
        styles.css
        manifest.webmanifest
        js/ icons/ assets/
        widget/widget.css   (위젯 상단 바 스타일)
        widget/widget.js    (위젯 상단 바 동작 + pywebview 브리지)
"""

from __future__ import annotations

import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 웹 앱에서 그대로 가져오는 것들 (desktop/, tests/, docs/, .tmp/ 는 제외)
WEB_FILES = ("index.html", "styles.css", "manifest.webmanifest")
WEB_DIRS = ("js", "icons", "assets")

WIDGET_BAR = """<div id="wbar" role="banner">
  <div class="wbar-drag pywebview-drag-region" id="wbar-drag">
    <span class="wbar-mark" data-icon="message" aria-hidden="true"></span>
    <span class="wbar-title">문자 도우미</span>
    <span class="wbar-web" id="wbar-web"></span>
  </div>
  <button class="wbar-update" id="wbtn-update" type="button" hidden>업데이트</button>
  <button class="wbar-btn wbar-pin is-on" id="wbtn-pin" type="button" aria-pressed="true" title="항상 위">📌<span class="pin-label"> 항상 위</span></button>
  <button class="wbar-btn" id="wbtn-min" type="button" title="최소화" aria-label="최소화">—</button>
  <button class="wbar-btn is-close" id="wbtn-close" type="button" title="닫기" aria-label="닫기">×</button>
</div>
"""

WIDGET_CSS_LINK = '<link rel="stylesheet" href="widget/widget.css">'
WIDGET_SCRIPT = '<script src="widget/widget.js" defer></script>'


def web_version(root: str = ROOT) -> str:
    """sw.js 의 VERSION('v1.4.9')을 읽어 위젯에 묶인 웹 버전을 남긴다."""
    try:
        with open(os.path.join(root, "sw.js"), encoding="utf-8") as fp:
            match = re.search(r"VERSION\s*=\s*['\"]v?([0-9][^'\"]*)['\"]", fp.read())
        return match.group(1) if match else ""
    except OSError:
        return ""


def inject_widget(html: str, version: str = "") -> str:
    """index.html 에 위젯 상단 바·스타일·스크립트를 끼워 넣는다.

    이미 넣은 파일을 다시 넣어도 결과가 같아야 한다(빌드를 두 번 돌려도 안전).
    위젯은 pywebview 의 로컬 서버(http://127.0.0.1)로 열리므로 웹용 Service Worker 는
    걷어낸다 — 앱을 새로 깔 때 예전 캐시가 남아 화면이 섞이지 않게.
    """
    if 'id="wbar"' in html:
        return html

    html = re.sub(
        r"<script>\s*/\* 오프라인 캐시.*?</script>\s*",
        "",
        html,
        count=1,
        flags=re.S,
    )
    if version:
        html = html.replace(
            "<html lang=\"ko\">",
            f'<html lang="ko" data-widget-web-version="{version}">',
            1,
        )
    html = html.replace("</head>", WIDGET_CSS_LINK + "\n</head>", 1)
    html = html.replace("<body>", "<body>\n" + WIDGET_BAR, 1)
    html = html.replace("</body>", WIDGET_SCRIPT + "\n</body>", 1)
    return html


def prepare(dest: str, root: str = ROOT) -> str:
    """dest(예: desktop/www)를 새로 만들어 위젯용 웹 자산을 채운다."""
    dest = os.path.abspath(dest)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)

    version = web_version(root)
    for name in WEB_FILES:
        src = os.path.join(root, name)
        if not os.path.exists(src):
            continue
        if name == "index.html":
            with open(src, encoding="utf-8") as fp:
                html = fp.read()
            with open(os.path.join(dest, name), "w", encoding="utf-8") as fp:
                fp.write(inject_widget(html, version))
        else:
            shutil.copy2(src, os.path.join(dest, name))

    for name in WEB_DIRS:
        src = os.path.join(root, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, name))

    widget_src = os.path.join(HERE, "web")
    widget_dest = os.path.join(dest, "widget")
    os.makedirs(widget_dest, exist_ok=True)
    for name in ("widget.css", "widget.js"):
        shutil.copy2(os.path.join(widget_src, name), os.path.join(widget_dest, name))

    return os.path.join(dest, "index.html")


def main(argv: list[str]) -> int:
    dest = argv[1] if len(argv) > 1 else os.path.join(HERE, "www")
    index = prepare(dest)
    print(f"www 준비 완료: {index}  (웹 버전 v{web_version() or '?'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
