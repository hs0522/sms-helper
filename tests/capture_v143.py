"""v1.4.3 검수 스크린샷 — downloads/v1.4.3-*.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v143.py
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8851


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def pick(pg, tid):
    pg.click('#btn-sheet')
    pg.wait_for_timeout(220)
    pg.click(f'#sheet-list [data-id="{tid}"]')
    pg.wait_for_timeout(300)


def open_tpl(pg, tid):
    pg.evaluate("t => SMSApp.openTemplate(t, {})", tid)
    pg.wait_for_timeout(260)


def money(pg, sel, v):
    pg.fill(sel, str(v))
    pg.wait_for_timeout(180)


def date(pg, field, day):
    pg.evaluate("""(f) => { const b = document.querySelector('#fields [data-date="' + f + '"]');
        if (b) { b.scrollIntoView({block: 'center'}); b.click(); } }""", field)
    pg.wait_for_timeout(240)
    pg.evaluate("""(d) => { const b = document.querySelector('#calpop [data-cal-day="' + d + '"]');
        if (b) b.click(); }""", str(day))
    pg.wait_for_timeout(220)
    pg.evaluate("""() => { const b = document.querySelector('#calpop [data-cal-close]'); if (b) b.click(); }""")
    pg.wait_for_timeout(150)


def main():
    srv = Server(('127.0.0.1', PORT), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{PORT}/index.html'
    errors = []
    made = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                  is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg.goto(base, wait_until='networkidle')
        pg.evaluate('localStorage.clear()')
        pg.reload(wait_until='networkidle')
        pg.wait_for_timeout(450)

        # 1) 전문가·협력업체 — 기본 44명이 들어 있는 연락처 칸 (대출 33명)
        pick(pg, 't20')
        pg.wait_for_timeout(400)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(200)
        made.append('v1.4.3-vendor-contacts-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]),
                      clip={'x': 0, 'y': 0, 'width': 390, 'height': 560})

        # 2) 협력업체 목록 모달 — 기본 명단 · 이름/연락처
        pg.click('#btn-vendor-list')
        pg.wait_for_timeout(420)
        made.append('v1.4.3-vendor-modal-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))
        pg.click('#btn-vendor-list-close')
        pg.wait_for_timeout(220)

        # 3) 미리보기 — 대출 3명을 고른 문자 (이름/연락처)
        for name in ('국민 대출 김동준', '신한 대출 안종미', '삼성생명 대출 박재영'):
            pg.evaluate("""n => {
                const row = [...document.querySelectorAll('#fields .contact-list .contact:not(.is-new)')]
                  .find(r => r.querySelector('input[data-contact-edit="name"]').value === n);
                if (row) row.querySelector('.contact-check').click();
            }""", name)
            pg.wait_for_timeout(200)
        pg.evaluate("() => document.querySelector('#preview').scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(250)
        made.append('v1.4.3-vendor-preview-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 4) 계약 조건 안내 — 매매 가계약 · 토지거래허가 · 근저당
        open_tpl(pg, 't8')
        money(pg, '#fields [data-field="price"]', 247000)
        pg.fill('#fields [data-field="account"]', '국민 123456-01-234567 홍길동')
        money(pg, '#fields [data-pay-amt="yakjeong"][data-pay-idx="0"]', 1000)
        date(pg, 'pay:yakjeong:0', 27)
        money(pg, '#fields [data-pay-amt="jeong"][data-pay-idx="0"]', 3000)
        date(pg, 'pay:jeong:0', 28)
        money(pg, '#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', 24700)
        date(pg, 'pay:gyeyak:0', 5)
        money(pg, '#fields [data-pay-amt="jung"][data-pay-idx="0"]', 61750)
        pg.click('#fields [data-toggle="permit"]')
        pg.wait_for_timeout(200)
        pg.click('#fields [data-toggle="mortgage"]')
        pg.wait_for_timeout(200)
        pg.fill('#fields [data-field="mortgageHolder"]', '주식회사 카카오뱅크')
        money(pg, '#fields [data-field="mortgageAmount"]', 12000)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(300)
        pg.evaluate("() => document.querySelector('#preview').scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(260)
        made.append('v1.4.3-t8-contract-preview-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))
        pg.evaluate("() => document.querySelector('#fields .paytable').scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(280)
        made.append('v1.4.3-t8-paytable-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 5) 계약 일정 안내 — 매매 잔금 + 구비서류
        open_tpl(pg, 't10')
        pg.click('#fields [data-seg="kind"][data-value="잔금"]')
        pg.wait_for_timeout(250)
        pg.fill('#fields [data-prop="prop"][data-key="dong"]', '404')
        pg.fill('#fields [data-prop="prop"][data-key="ho"]', '1903')
        money(pg, '#fields [data-prop="prop"][data-money="amount"]', 247000)
        money(pg, '#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', 24700)
        money(pg, '#fields [data-pay-amt="jung"][data-pay-idx="0"]', 61750)
        pg.wait_for_timeout(250)
        pg.evaluate("() => document.querySelector('#preview').scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(280)
        made.append('v1.4.3-t10-schedule-preview-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 6) 중개보수 안내
        pick(pg, 't14')
        money(pg, '#fields [data-field="calcAmount"]', 230000)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(320)
        pg.evaluate("() => document.querySelector('#preview').scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(280)
        made.append('v1.4.3-t14-fee-preview-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 7) 집보기 후 감사 인사 — 고객 · 주말 안부
        open_tpl(pg, 't17')
        pg.click('#fields [data-seg="target"][data-value="guest"]')
        pg.wait_for_timeout(250)
        pg.click('#fields [data-greet="weekend"]')
        pg.wait_for_timeout(300)
        pg.evaluate("() => document.querySelector('#preview').scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(280)
        made.append('v1.4.3-t17-thanks-preview-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 8) 화면 맨 위 — 목록(17종)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(250)
        made.append('v1.4.3-home-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]),
                      clip={'x': 0, 'y': 0, 'width': 390, 'height': 500})
        ctx.close()

        # PC 1440 — 협력업체 연락처 · 계약 조건 미리보기
        ctx2 = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg2 = ctx2.new_page()
        pg2.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        pg2.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg2.goto(base, wait_until='networkidle')
        pg2.wait_for_timeout(300)
        pg2.click('#tpl-list [data-id="t20"]')
        pg2.wait_for_timeout(400)
        made.append('v1.4.3-pc-vendor-1440.png')
        pg2.screenshot(path=os.path.join(DOWNLOADS, made[-1]))
        pg2.click('#tpl-list [data-id="t8"]')
        pg2.wait_for_timeout(300)
        pg2.fill('#fields [data-field="price"]', '76000')
        pg2.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
        pg2.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
        pg2.evaluate('document.activeElement && document.activeElement.blur()')
        pg2.wait_for_timeout(350)
        made.append('v1.4.3-pc-contract-1440.png')
        pg2.screenshot(path=os.path.join(DOWNLOADS, made[-1]))
        ctx2.close()
        browser.close()

    print('errors:', errors)
    for f in made:
        path = os.path.join(DOWNLOADS, f)
        print(' ', path, os.path.getsize(path))


main()
