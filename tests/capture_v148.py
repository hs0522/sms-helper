"""v1.4.8 검수 스크린샷 — downloads/v1.4.8-*.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v148.py

· 11번 계약 조건 안내(t8) — 매매 가계약 / 약정 / 계약, 월세 가계약 · 계약
· 12번 계약 일정 안내(t10) — 매매 약정 / 계약 / 중도금 / 잔금
· PC 1440×900 과 폰 390×844 두 화면
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8858


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def open_tpl(pg, tid, mobile):
    if mobile:
        pg.click('#btn-sheet')
        pg.wait_for_timeout(200)
        pg.click(f'#sheet-list [data-id="{tid}"]')
    else:
        pg.click(f'#tpl-list [data-id="{tid}"]')
    pg.wait_for_timeout(350)


def fill_sale(pg):
    pg.fill('#fields [data-prop="prop"][data-key="complex"]', '마포래미안푸르지오')
    pg.fill('#fields [data-prop="prop"][data-key="dong"]', '208')
    pg.fill('#fields [data-prop="prop"][data-key="ho"]', '1103')
    pg.fill('#fields [data-prop="prop"][data-money="amount"]', '76000')
    pg.fill('#fields [data-field="account"]', '국민 123456-01-234567 홍길동')
    pg.fill('#fields [data-pay-amt="yakjeong"][data-pay-idx="0"]', '1000')
    pg.fill('#fields [data-pay-amt="jeong"][data-pay-idx="0"]', '3000')
    pg.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
    pg.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
    pg.evaluate('document.activeElement && document.activeElement.blur()')
    pg.wait_for_timeout(400)


def kind(pg, value):
    pg.click(f'#fields [data-seg="kind"][data-value="{value}"]')
    pg.wait_for_timeout(400)


def shot(pg, name):
    pg.evaluate("() => { const p = document.querySelector('.panel-form, .form-panel, #form-panel') || document.querySelector('.panel'); if (p) p.scrollTop = 0; window.scrollTo(0, 0); }")
    pg.wait_for_timeout(250)
    path = os.path.join(DOWNLOADS, name)
    pg.screenshot(path=path)
    print(path)


def run(browser, w, h):
    mobile = w < 500
    tag = 'mobile' if mobile else 'pc'
    ctx = browser.new_context(viewport={'width': w, 'height': h}, is_mobile=mobile, has_touch=mobile,
                              device_scale_factor=2 if mobile else 1)
    pg = ctx.new_page()
    pg.goto(f'http://127.0.0.1:{PORT}/index.html', wait_until='networkidle')
    pg.evaluate('localStorage.clear()')
    pg.reload(wait_until='networkidle')
    pg.wait_for_timeout(300)

    # 11번 — 매매 가계약 / 약정 / 계약
    open_tpl(pg, 't8', mobile)
    fill_sale(pg)
    kind(pg, '가계약')
    shot(pg, f'v1.4.8-{tag}-t8-sale-gyeyak.png')
    kind(pg, '약정')
    shot(pg, f'v1.4.8-{tag}-t8-sale-yakjeong.png')
    kind(pg, '계약')
    shot(pg, f'v1.4.8-{tag}-t8-sale-contract.png')
    # 11번 — 월세 가계약 / 계약
    pg.click('#fields [data-prop-trade="prop"][data-value="월세"]')
    pg.wait_for_timeout(400)
    pg.fill('#fields [data-prop="prop"][data-money="deposit"]', '10000')
    pg.fill('#fields [data-prop="prop"][data-money="rent"]', '300')
    pg.evaluate('document.activeElement && document.activeElement.blur()')
    pg.wait_for_timeout(400)
    kind(pg, '가계약')
    shot(pg, f'v1.4.8-{tag}-t8-wolse-gyeyak.png')
    kind(pg, '계약')
    shot(pg, f'v1.4.8-{tag}-t8-wolse-contract.png')

    # 12번 — 매매 약정 / 계약 / 중도금 / 잔금
    open_tpl(pg, 't10', mobile)
    pg.fill('#fields [data-prop="prop"][data-key="complex"]', '마포래미안푸르지오')
    pg.fill('#fields [data-prop="prop"][data-key="dong"]', '208')
    pg.fill('#fields [data-prop="prop"][data-key="ho"]', '1103')
    pg.fill('#fields [data-prop="prop"][data-money="amount"]', '76000')
    pg.evaluate('document.activeElement && document.activeElement.blur()')
    pg.wait_for_timeout(300)
    # 일정 — 달력에서 12월 5일
    pg.click('#fields [data-date="when"]')
    pg.wait_for_timeout(300)
    pg.click('#calpop [data-cal-nav="1"]')
    pg.wait_for_timeout(200)
    pg.click('#calpop [data-cal-day="5"]')
    pg.wait_for_timeout(200)
    pg.click('#calpop [data-cal-close]')
    pg.wait_for_timeout(300)
    for k in ('약정', '계약', '중도금', '잔금'):
        kind(pg, k)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(200)
        shot(pg, f'v1.4.8-{tag}-t10-sale-{"yakjeong" if k == "약정" else ("contract" if k == "계약" else ("jung" if k == "중도금" else "jan"))}.png')
    ctx.close()


def main():
    handler = functools.partial(Quiet, directory=ROOT)
    srv = Server(('127.0.0.1', PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for w, h in ((1440, 900), (390, 844)):
            run(browser, w, h)
        browser.close()
    srv.shutdown()


if __name__ == '__main__':
    main()
