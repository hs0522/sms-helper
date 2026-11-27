"""v1.4.9 검수 스크린샷 — downloads/v1.4.9-pc-t8.png · downloads/v1.4.9-mobile-t8.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v149.py

· 11번 계약 조건 안내(t8) 매매 계약 — 지급 일정 표(약정금·가계약금·계약금·중도금·잔금)
· PC 1440×900 · 폰 390×844, 폰은 가계약금 1차·2차(다차수) 포함
· 항목 이름이 왼쪽 구분 칸 안에서 입력칸 세로 가운데에 오는지, 머리글 '구분'이 왼쪽 정렬인지 확인하는 컷
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8863


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def open_t8(pg, mobile):
    if mobile:
        pg.click('#btn-sheet')
        pg.wait_for_timeout(200)
        pg.click('#sheet-list [data-id="t8"]')
    else:
        pg.click('#tpl-list [data-id="t8"]')
    pg.wait_for_timeout(350)


def fill(pg, mobile):
    pg.fill('#fields [data-prop="prop"][data-key="complex"]', '마포래미안푸르지오')
    pg.fill('#fields [data-prop="prop"][data-key="dong"]', '208')
    pg.fill('#fields [data-prop="prop"][data-key="ho"]', '1103')
    pg.fill('#fields [data-prop="prop"][data-money="amount"]', '76000')
    pg.fill('#fields [data-field="account"]', '국민 123456-01-234567 홍길동')
    pg.click('#fields [data-seg="kind"][data-value="계약"]')
    pg.wait_for_timeout(350)
    pg.fill('#fields [data-pay-amt="yakjeong"][data-pay-idx="0"]', '1000')
    pg.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
    pg.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
    if mobile:
        # 다차수 — 가계약금 1차 · 2차
        pg.eval_on_selector('#fields .pay-row[data-pay-item="jeong"] [data-pay-add]',
                            "e => { e.scrollIntoView({block: 'center'}); e.click(); }")
        pg.wait_for_timeout(300)
    pg.fill('#fields [data-pay-amt="jeong"][data-pay-idx="0"]', '3000')
    if mobile:
        pg.fill('#fields [data-pay-amt="jeong"][data-pay-idx="1"]', '2000')
    pg.evaluate('document.activeElement && document.activeElement.blur()')
    pg.wait_for_timeout(400)


def scroll_to_table(pg, mobile):
    # 지급 일정 표가 화면 가운데 오도록 스크롤한다 (칸을 건드리지 않게 scrollTo만 쓴다)
    if mobile:
        pg.evaluate("""() => {
          const t = document.querySelector('#fields .paytable');
          const top = t.getBoundingClientRect().top + window.scrollY - 90;
          window.scrollTo(0, top);
        }""")
    else:
        pg.evaluate("""() => {
          const t = document.querySelector('#fields .paytable');
          const box = t.closest('.form-panel') || t.closest('.panel') || document.scrollingElement;
          if (box === document.scrollingElement) { window.scrollTo(0, 0); return; }
          box.scrollTop += t.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
        }""")
    pg.wait_for_timeout(350)


def run(browser, w, h, name, mobile):
    ctx = browser.new_context(viewport={'width': w, 'height': h}, is_mobile=mobile, has_touch=mobile,
                              device_scale_factor=2 if mobile else 1)
    pg = ctx.new_page()
    pg.goto(f'http://127.0.0.1:{PORT}/index.html', wait_until='networkidle')
    pg.evaluate('localStorage.clear()')
    pg.reload(wait_until='networkidle')
    pg.wait_for_timeout(300)
    open_t8(pg, mobile)
    fill(pg, mobile)
    scroll_to_table(pg, mobile)
    path = os.path.join(DOWNLOADS, name)
    pg.screenshot(path=path)
    print(path)
    ctx.close()


def main():
    handler = functools.partial(Quiet, directory=ROOT)
    srv = Server(('127.0.0.1', PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        run(browser, 1440, 900, 'v1.4.9-pc-t8.png', False)
        run(browser, 390, 844, 'v1.4.9-mobile-t8.png', True)
        browser.close()
    srv.shutdown()


if __name__ == '__main__':
    main()
