"""v1.4.4 검수 스크린샷 — downloads/v1.4.4-*.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v144.py

· 지급 일정 기본 빈 화면(항목당 1줄)
· 근저당 1건 / 3건 화면과 미리보기
· 390×844(폰) · 1440×900(PC)
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8852


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def shot(pg, path, sel=None):
    if sel:
        box = pg.query_selector(sel)
        if box:
            box.scroll_into_view_if_needed()
            pg.wait_for_timeout(180)
    pg.screenshot(path=os.path.join(DOWNLOADS, path))


def run_page(browser, w, h, tag):
    ctx = browser.new_context(viewport={'width': w, 'height': h},
                              is_mobile=w < 500, has_touch=w < 500,
                              device_scale_factor=2 if w < 500 else 1)
    pg = ctx.new_page()
    pg.goto(f'http://127.0.0.1:{PORT}/index.html', wait_until='networkidle')
    pg.evaluate('localStorage.clear()')
    pg.reload(wait_until='networkidle')
    pg.evaluate("() => SMSApp.openTemplate('t8', {})")
    pg.wait_for_timeout(300)

    # ① 지급 일정 — 처음엔 항목당 1줄, 모두 빈칸
    shot(pg, f'v1.4.4-paytable-empty-{tag}.png', '#fields .paytable')

    # ② 근저당 1건
    pg.click('#fields [data-toggle="mortgage"]')
    pg.wait_for_timeout(220)
    pg.fill('#fields [data-mtg-holder="0"]', '주식회사 카카오뱅크')
    pg.fill('#fields [data-mtg-amount="0"]', '12000')
    pg.wait_for_timeout(200)
    shot(pg, f'v1.4.4-mortgage-1-{tag}.png', '#fields .field.is-mortgage')

    # ③ 근저당 3건
    for i, (holder, amt) in enumerate((('황호선', '3000'), ('신한은행', '5000')), start=1):
        pg.click('#fields [data-mtg-add]')
        pg.wait_for_timeout(220)
        pg.fill(f'#fields [data-mtg-holder="{i}"]', holder)
        pg.fill(f'#fields [data-mtg-amount="{i}"]', amt)
        pg.wait_for_timeout(200)
    shot(pg, f'v1.4.4-mortgage-3-{tag}.png', '#fields .field.is-mortgage')

    # ④ 미리보기 — 특약의 근저당 3건 목록
    pg.fill('#fields [data-field="price"]', '100000')
    pg.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '10000')
    pg.fill('#fields [data-field="address"]', '서울시 마포구 아현동 777 외 3필지')
    pg.wait_for_timeout(300)
    pg.on('dialog', lambda d: d.accept())
    shot(pg, f'v1.4.4-preview-{tag}.png', '#preview')
    print(tag, 'ok —', pg.input_value('#preview').count('·'), '건 목록')
    ctx.close()


def main():
    srv = Server(('127.0.0.1', PORT), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        run_page(browser, 390, 844, '390')
        run_page(browser, 1440, 900, '1440')
        browser.close()
    srv.shutdown()


if __name__ == '__main__':
    main()
