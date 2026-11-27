"""위젯 화면 미리보기 캡처 — 420×760, 상단 바 포함.

    python desktop/tests/capture_widget.py

결과: downloads/sms-helper-widget-preview.png
pywebview 없이 브라우저에서 위젯과 같은 조건(420×760, 브리지 모형)으로 찍는다.
"""

import functools
import http.server
import os
import socketserver
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
ROOT = os.path.dirname(DESKTOP)
if DESKTOP not in sys.path:
    sys.path.insert(0, DESKTOP)

import prepare_www  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8831
OUT = "/workspace/downloads/sms-helper-widget-preview.png"

BRIDGE_MOCK = """
window.pywebview = {
  api: {
    copy: function (text) { window.__copied = text; return true; },
    get_window_state: function () { return { always_on_top: true, width: 420, height: 760 }; },
    set_on_top: function (v) { window.__onTop = v; return v; },
    check_update: function () { return { ok: true, current: '1.0.0', available: false }; },
    open_release: function () { return true; },
    minimize: function () { return true; },
    close: function () { return true; },
    version: function () { return { version: '1.0.0', web: '1.4.9' }; }
  }
};
"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main() -> int:
    www = os.path.join(DESKTOP, "www")
    prepare_www.prepare(www)

    handler = functools.partial(Quiet, directory=www)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 420, "height": 760}, device_scale_factor=2)
            page.add_init_script(BRIDGE_MOCK)
            page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="networkidle")
            page.wait_for_selector("#wbar")
            page.wait_for_selector("#form-title")
            page.wait_for_timeout(500)
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            page.screenshot(path=OUT)
            print("saved", OUT)
            print("title:", page.title())
            print("bar:", page.eval_on_selector("#wbar", "el => el.innerText.replace(/\\s+/g,' ').trim()"))
            browser.close()
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
