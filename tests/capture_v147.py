"""v1.4.7 검수 스크린샷 — downloads/v1.4.7-*.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v147.py

· PC 1440×900 — 15번 계약조건안내(t8) 지급 일정 머리글 한 줄, 넓어진 화면
· PC 1440×900 — 15번 전문가·협력업체 소개(t20) 목록 버튼 없이 펼친 연락처(★)
· 폰 390×844 — 같은 두 화면(3줄 연락처 + 목록 버튼 그대로)
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8857


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def fill_contract(pg):
    pg.fill('#fields [data-field="price"]', '76000')
    pg.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
    pg.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
    pg.fill('#fields [data-field="address"]', '서울시 마포구 아현동 777')
    pg.evaluate('document.activeElement && document.activeElement.blur()')
    pg.wait_for_timeout(400)


def open_tpl(pg, tid, mobile):
    if mobile:
        pg.click('#btn-sheet')
        pg.wait_for_timeout(200)
        pg.click(f'#sheet-list [data-id="{tid}"]')
    else:
        pg.click(f'#tpl-list [data-id="{tid}"]')
    pg.wait_for_timeout(350)


def run(browser, w, h, tag):
    mobile = w < 500
    ctx = browser.new_context(viewport={'width': w, 'height': h}, is_mobile=mobile, has_touch=mobile,
                              device_scale_factor=2 if mobile else 1)
    pg = ctx.new_page()
    pg.goto(f'http://127.0.0.1:{PORT}/index.html', wait_until='networkidle')
    pg.evaluate('localStorage.clear()')
    pg.reload(wait_until='networkidle')
    pg.wait_for_timeout(300)

    # ① 계약조건안내 — 지급 일정 머리글과 표
    open_tpl(pg, 't8', mobile)
    fill_contract(pg)
    pg.screenshot(path=os.path.join(DOWNLOADS, f'v1.4.7-pc-t8-{tag}.png' if not mobile else f'v1.4.7-mobile-t8-{tag}.png'))
    head = pg.evaluate("""() => {
      const h = document.querySelector('#fields .paytable-head');
      if (!h) return null;
      const r = h.getBoundingClientRect();
      return {dir: getComputedStyle(h).flexDirection, h: +r.height.toFixed(1)};
    }""")
    print(tag, 't8 머리글', head)

    # ② 전문가·협력업체 소개 — PC는 폼에서 다 보이고 ★, 폰은 3줄 + 목록 버튼
    open_tpl(pg, 't20', mobile)
    pg.wait_for_timeout(300)
    lst = pg.evaluate("""() => {
      const l = document.querySelector('#fields .contact-list');
      if (!l) return null;
      const lb = l.getBoundingClientRect();
      const rows = [...l.querySelectorAll('.contact')];
      const visible = rows.filter(e => { const r = e.getBoundingClientRect();
        return r.top >= lb.top - 1 && r.bottom <= lb.bottom + 1; }).length;
      const btn = document.querySelector('#btn-vendor-list');
      const star = document.querySelector('#fields .contact-fav');
      return {rows: rows.length, visible: visible, client: l.clientHeight,
              btnHidden: !btn || getComputedStyle(btn).display === 'none' || btn.hidden,
              starShown: !!star && getComputedStyle(star).display !== 'none'};
    }""")
    name = 'v1.4.7-pc-t20' if not mobile else 'v1.4.7-mobile-t20'
    pg.screenshot(path=os.path.join(DOWNLOADS, f'{name}-{tag}.png'))
    print(tag, 't20', lst)
    ctx.close()


def main():
    srv = Server(('127.0.0.1', PORT), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        run(browser, 1440, 900, '1440')
        run(browser, 390, 844, '390')
        browser.close()
    srv.shutdown()


if __name__ == '__main__':
    main()
