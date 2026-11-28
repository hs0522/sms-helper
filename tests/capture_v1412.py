"""v1.4.12 검수 컷 — 새 아이콘이 실제 화면(폰·PC·윈도우 위젯)에 어떻게 보이는지

    LD_LIBRARY_PATH=... python3 tests/capture_v1412.py

만드는 파일
    downloads/v1.4.12-mobile.png   폰 390×844 — 상단 바 로고
    downloads/v1.4.12-pc.png       PC 1440×900 — 상단 바 로고
    downloads/v1.4.12-widget.png   윈도우 위젯 420×760 — 위젯 상단 바 로고
    downloads/v1.4.12-header.png   상단 바 확대 컷 (폰·PC·위젯 나란히)
"""
import functools
import http.server
import os
import socketserver
import threading

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = "/workspace/downloads"
PORT = 8867


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


srv = Server(("127.0.0.1", PORT), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
pw = sync_playwright().start()
br = pw.chromium.launch()
URL = f"http://127.0.0.1:{PORT}/index.html"
shots = {}

# ---------- 폰 ----------
ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                     device_scale_factor=2)
pg = ctx.new_page()
pg.goto(URL, wait_until="networkidle")
pg.evaluate("localStorage.clear()")
pg.reload(wait_until="networkidle")
pg.wait_for_timeout(400)
path = os.path.join(DOWNLOADS, "v1.4.12-mobile.png")
pg.screenshot(path=path)
shots["phone"] = pg.locator(".topbar").screenshot()
print(path)
ctx.close()

# ---------- PC ----------
ctx = br.new_context(viewport={"width": 1440, "height": 900})
pg = ctx.new_page()
pg.goto(URL, wait_until="networkidle")
pg.evaluate("localStorage.clear()")
pg.reload(wait_until="networkidle")
pg.wait_for_timeout(400)
path = os.path.join(DOWNLOADS, "v1.4.12-pc.png")
pg.screenshot(path=path)
shots["pc"] = pg.locator(".topbar").screenshot()
print(path)
ctx.close()

# ---------- 윈도우 위젯(420×760) ----------
import sys
sys.path.insert(0, os.path.join(ROOT, "desktop"))
import prepare_www  # noqa: E402

prepared = prepare_www.prepare(os.path.join(ROOT, "desktop", "www"))
ctx = br.new_context(viewport={"width": 420, "height": 760})
pg = ctx.new_page()
pg.goto(f"http://127.0.0.1:{PORT}/desktop/www/index.html", wait_until="networkidle")
pg.wait_for_timeout(500)
path = os.path.join(DOWNLOADS, "v1.4.12-widget.png")
pg.screenshot(path=path)
shots["widget"] = pg.locator("#wbar").screenshot()
print(path, prepared)
ctx.close()

br.close()
pw.stop()
srv.shutdown()

# ---------- 상단 바 확대 컷 ----------
for key, im in shots.items():
    im.save(f"/workspace/tmp/iconwork/topbar_{key}.png")
    print(key, im.size)
