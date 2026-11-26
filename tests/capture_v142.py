"""v1.4.2 검수 스크린샷 — downloads/v1.4.2-*.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v142.py
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8849


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def pick(pg, tid):
    pg.click('#btn-sheet')
    pg.wait_for_timeout(200)
    pg.click(f'#sheet-list [data-id="{tid}"]')
    pg.wait_for_timeout(260)


def money(pg, sel, v):
    pg.fill(sel, str(v))
    pg.wait_for_timeout(160)


def date(pg, field, day, month=None):
    pg.evaluate("""(f) => { const b = document.querySelector('#fields [data-date="' + f + '"]');
        if (b) { b.scrollIntoView({block: 'center'}); b.click(); } }""", field)
    pg.wait_for_timeout(220)
    if month:
        for _ in range(4):
            if f'{month}월' in pg.inner_text('#calpop .cal-title'):
                break
            pg.evaluate("""() => { const nav = document.querySelector('#calpop [data-cal-nav="1"]');
                if (nav) nav.click(); }""")
            pg.wait_for_timeout(160)
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
        pg.wait_for_timeout(400)

        # 1) 지급 일정 — 일정·금액 위쪽 선/높이 일직선 + 우측하단 환산
        pick(pg, 't8')
        money(pg, '#fields [data-field="price"]', 76000)
        money(pg, '#fields [data-pay-amt="yakjeong"][data-pay-idx="0"]', 1000)
        date(pg, 'pay:yakjeong:0', 26)
        money(pg, '#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', 4000)
        date(pg, 'pay:gyeyak:0', 28)
        pg.fill('#fields [data-pay-rate="gyeyak"][data-pay-idx="0"]', '10')
        pg.wait_for_timeout(250)
        date(pg, 'pay:gyeyak:0', 28)
        pg.fill('#fields [data-pay-rate="jung"][data-pay-idx="0"]', '15')
        pg.wait_for_timeout(250)
        pg.evaluate("""() => { const b = document.querySelector('#fields .pay-row[data-pay-item="jung"] [data-pay-add]');
            if (b) { b.scrollIntoView({block: 'center'}); b.click(); } }""")
        pg.wait_for_timeout(260)
        money(pg, '#fields [data-pay-amt="jung"][data-pay-idx="1"]', 9500)
        date(pg, 'pay:jung:1', 15)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(300)
        pg.eval_on_selector('.paytable', "e => e.scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(320)
        made.append('v1.4.2-pay-straight-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 2) 한 줄 확대 — % · 일정 · 금액 상단/높이, 우측하단 환산
        clip = pg.evaluate("""() => { const r = document.querySelector('#fields .pay-row[data-pay-item="gyeyak"]').getBoundingClientRect();
            return {x: Math.max(0, r.left - 14), y: Math.max(0, r.top - 34), width: Math.min(390, r.width + 30), height: r.height + 60}; }""")
        made.append('v1.4.2-pay-row-zoom-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]), clip=clip)

        # 3) 매물 카드 — 매매 금액칸 우측하단 환산
        pick(pg, 't2')
        pg.click('#fields [data-prop-trade="prop"][data-value="매매"]')
        pg.wait_for_timeout(200)
        money(pg, '#fields [data-money="amount"]', 17000)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(250)
        pg.evaluate("""() => { const p = document.querySelector('#fields .prop-money');
            p.scrollIntoView({block: 'center'}); }""")
        pg.wait_for_timeout(260)
        made.append('v1.4.2-trade-sale-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 4) 월세 — 보증금·월세 각 칸 우측하단 환산
        pg.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        pg.wait_for_timeout(220)
        money(pg, '#fields [data-money="deposit"]', 3000)
        money(pg, '#fields [data-money="rent"]', 120)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(250)
        pg.evaluate("""() => { document.querySelector('#fields .prop-money').scrollIntoView({block: 'center'}); }""")
        pg.wait_for_timeout(260)
        made.append('v1.4.2-trade-monthly-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 5) 전문가·협력업체 소개 — 목록 버튼(헤더와 같은 크기) · 이름/연락처
        pick(pg, 't20')
        pg.wait_for_timeout(300)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(200)
        made.append('v1.4.2-vendor-list-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]),
                      clip={'x': 0, 'y': 0, 'width': 390, 'height': 420})

        # 6) 협력업체 목록 모달 — 이름 · 연락처
        pg.click('#btn-vendor-list')
        pg.wait_for_timeout(350)
        made.append('v1.4.2-vendor-modal-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))
        pg.click('#btn-vendor-list-close')
        pg.wait_for_timeout(200)

        # 7) 중개보수 — 금액칸 우측하단 환산 + 요율·합계 높이
        pick(pg, 't14')
        money(pg, '#fields [data-field="calcAmount"]', 76000)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(300)
        pg.evaluate("""() => { document.querySelector('.calc-summary').scrollIntoView({block: 'center'}); }""")
        pg.wait_for_timeout(260)
        made.append('v1.4.2-calc-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]))

        # 8) 거래유형 버튼이 금액칸과 같은 높이 (임대차 만기)
        pick(pg, 't15')
        money(pg, '#fields [data-field="months"]', 12)
        pg.wait_for_timeout(250)
        made.append('v1.4.2-lease-390.png')
        pg.screenshot(path=os.path.join(DOWNLOADS, made[-1]),
                      clip={'x': 0, 'y': 0, 'width': 390, 'height': 380})
        ctx.close()

        # PC 1440 — 지급 일정 일직선 + 우측하단 환산
        ctx2 = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg2 = ctx2.new_page()
        pg2.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        pg2.goto(base, wait_until='networkidle')
        pg2.click('#tpl-list [data-id="t8"]')
        pg2.wait_for_timeout(300)
        pg2.fill('#fields [data-field="price"]', '76000')
        pg2.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
        pg2.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
        pg2.evaluate('document.activeElement && document.activeElement.blur()')
        pg2.wait_for_timeout(300)
        pg2.eval_on_selector('.paytable', "e => e.scrollIntoView({block: 'center'})")
        pg2.wait_for_timeout(300)
        made.append('v1.4.2-pc-pay-1440.png')
        pg2.screenshot(path=os.path.join(DOWNLOADS, made[-1]))
        ctx2.close()
        browser.close()

    print('errors:', errors)
    for f in made:
        print(' ', os.path.join(DOWNLOADS, f), os.path.getsize(os.path.join(DOWNLOADS, f)))


main()
