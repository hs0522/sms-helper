"""v1.4.0 검수 스크린샷 — downloads/v1.4.0-*.png (390×844 실제 폰 화면)

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v140.py
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8847


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def pick(pg, tid):
    pg.click('#btn-sheet')
    pg.wait_for_timeout(200)
    pg.click(f'#sheet-list [data-id="{tid}"]')
    pg.wait_for_timeout(250)


def pay(pg, key, man, idx=0):
    pg.fill(f'#fields [data-pay-amt="{key}"][data-pay-idx="{idx}"]', str(man))
    pg.wait_for_timeout(150)


def rate(pg, key, pct, idx=0):
    pg.fill(f'#fields [data-pay-rate="{key}"][data-pay-idx="{idx}"]', str(pct))
    pg.wait_for_timeout(200)


def add_part(pg, key, idx=0):
    sel = f'#fields .pay-row[data-pay-item="{key}"][data-pay-idx="{idx}"] [data-pay-add]'
    pg.eval_on_selector(sel, "e => e.scrollIntoView({block: 'center'})")
    pg.wait_for_timeout(120)
    pg.click(sel)
    pg.wait_for_timeout(220)


def date(pg, field, day, month=None):
    pg.click(f'#fields [data-date="{field}"]')
    pg.wait_for_timeout(200)
    if month:
        for _ in range(3):
            label = pg.inner_text('#calpop .cal-title')
            if f'{month}월' in label:
                break
            pg.evaluate("""() => document.querySelector('#calpop [data-cal-nav="1"]').click()""")
            pg.wait_for_timeout(150)
    # 달력이 화면 밖에 떠도 고를 수 있게 그 버튼을 직접 누른다
    pg.evaluate("""(d) => { const b = document.querySelector('#calpop [data-cal-day="' + d + '"]'); if (b) b.click(); }""", str(day))
    pg.wait_for_timeout(200)
    pg.evaluate("""() => { const b = document.querySelector('#calpop [data-cal-close]'); if (b) b.click(); }""")
    pg.wait_for_timeout(150)


def shot(pg, name, clip=None):
    path = os.path.join(DOWNLOADS, name)
    if clip:
        pg.screenshot(path=path, clip=clip)
    else:
        pg.screenshot(path=path)
    return path


def main():
    srv = Server(('127.0.0.1', PORT), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{PORT}/index.html'
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                  is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        pg.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type == 'error' else None)
        pg.goto(base, wait_until='networkidle')
        pg.evaluate('localStorage.clear()')
        pg.reload(wait_until='networkidle')
        pg.wait_for_timeout(400)

        # 1) 카테고리 탭(같은 크기 다섯 칸) + 특가 매물 (타입·방향 칸 없음)
        pick(pg, 't19')
        pg.click('.stage-tabs .tab:has-text("고객 응대·매물 관리")')
        pg.wait_for_timeout(300)
        pg.click('#sheet-close')
        pg.wait_for_timeout(250)
        shot(pg, 'v1.4.0-mobile-tabs-t19.png')

        # 2) 계약 조건 안내 — 공통 지급 일정 (약정금·가계약금·1·2차·소계)
        pick(pg, 't8')
        pg.click('#fields [data-seg="kind"][data-value="계약"]')
        pg.wait_for_timeout(250)
        pg.fill('#fields [data-field="price"]', '76000')
        pay(pg, 'yakjeong', 1000)
        date(pg, 'pay:yakjeong:0', 28)
        pay(pg, 'jeong', 3000)
        date(pg, 'pay:jeong:0', 10, month=12)
        rate(pg, 'gyeyak', 10)
        date(pg, 'pay:gyeyak:0', 10, month=12)
        rate(pg, 'jung', 15)
        add_part(pg, 'jung')
        pg.fill('#fields [data-pay-amt="jung"][data-pay-idx="1"]', '9500')
        pg.wait_for_timeout(250)
        date(pg, 'pay:jung:1', 15)
        date(pg, 'pay:jan:0', 18)
        pg.wait_for_timeout(300)
        pg.eval_on_selector('.paytable', "e => e.scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(250)
        shot(pg, 'v1.4.0-mobile-t8-schedule.png')
        pg.eval_on_selector('.pay-sub', "e => e.scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(200)
        shot(pg, 'v1.4.0-mobile-t8-subtotal.png')

        # 3) 근저당 말소 특약 — 채권자 | 채권최고액 한 줄
        pg.click('#fields [data-toggle="mortgage"]')
        pg.wait_for_timeout(200)
        pg.fill('#fields [data-field="mortgageHolder"]', '카카오뱅크')
        pg.fill('#fields [data-field="mortgageAmount"]', '12000')
        pg.wait_for_timeout(250)
        pg.eval_on_selector('#fields [data-field="mortgageHolder"]', "e => e.scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(200)
        shot(pg, 'v1.4.0-mobile-t8-mortgage.png')
        # 미리보기(문자 본문)도 함께
        pg.eval_on_selector('#preview', "e => e.scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(200)
        shot(pg, 'v1.4.0-mobile-t8-preview.png')

        # 4) 계약 일정 안내 — [매매][전세][월세] 위아래 간격
        pick(pg, 't10')
        pg.click('#fields [data-seg="kind"][data-value="잔금"]')
        pg.wait_for_timeout(250)
        pg.fill('#fields [data-money="amount"]', '76000')
        rate(pg, 'gyeyak', 10)
        rate(pg, 'jung', 25)
        pg.wait_for_timeout(300)
        pg.eval_on_selector('#fields [data-prop-trade="prop"]', "e => e.scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(250)
        shot(pg, 'v1.4.0-mobile-t10-trade-row.png')
        pg.eval_on_selector('.paytable', "e => e.scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(250)
        shot(pg, 'v1.4.0-mobile-t10-schedule.png')

        # 5) 달력 팝업 — 아래 안내 멘트 없음
        pick(pg, 't5')
        pg.click('#fields [data-date="when"]')
        pg.wait_for_timeout(300)
        shot(pg, 'v1.4.0-mobile-calendar.png')
        pg.click('#calpop [data-cal-close]')
        pg.wait_for_timeout(150)

        # 6) 전문가·협력업체 소개 — 목록 | 비우기
        pick(pg, 't20')
        pg.wait_for_timeout(250)
        shot(pg, 'v1.4.0-mobile-t20-header.png', clip={'x': 0, 'y': 0, 'width': 390, 'height': 300})

        # PC 위젯(1440×900)에서도 같은 화면
        ctx2 = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg2 = ctx2.new_page()
        pg2.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        pg2.goto(base, wait_until='networkidle')
        pg2.click('#tpl-list [data-id="t8"]')
        pg2.wait_for_timeout(250)
        pg2.fill('#fields [data-field="price"]', '76000')
        pg2.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
        pg2.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
        pg2.wait_for_timeout(300)
        shot(pg2, 'v1.4.0-pc-t8-schedule.png')
        ctx2.close()

        browser.close()
    print('errors:', errors)
    for f in sorted(os.listdir(DOWNLOADS)):
        if f.startswith('v1.4.0-'):
            print(' ', f)


main()
