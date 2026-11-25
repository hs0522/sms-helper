"""최종 화면 캡처 — downloads/sms-app-*.png · docs/shot-*.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture.py
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
DOCS = os.path.join(ROOT, 'docs')


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def sh(*parts):
    return os.path.join(*parts)


def pick(pg, tid):
    # 모바일은 목록 시트에서, PC는 왼쪽 목록에서
    if pg.is_visible('#list-panel'):
        pg.click(f'#tpl-list [data-id="{tid}"]')
    else:
        pg.click('#btn-sheet')
        pg.wait_for_timeout(150)
        pg.click(f'#sheet-list [data-id="{tid}"]')
    pg.wait_for_timeout(180)


def pay_date(pg, field, year, month, day):
    """지급 일정 표의 날짜 칸을 달력으로 채운다 (다른 달이면 › 로 넘긴다)"""
    pg.click(f'#fields [data-date="{field}"]')
    pg.wait_for_timeout(150)
    for _ in range(24):
        label = pg.inner_text('#calpop .cal-title')          # 예: '2026년 11월'
        y, m = [int(x) for x in label.replace('년', ' ').replace('월', ' ').split()]
        if (y, m) == (year, month):
            break
        pg.click('#calpop [data-cal-nav="%d"]' % (1 if (y, m) < (year, month) else -1))
        pg.wait_for_timeout(90)
    pg.click(f'#calpop [data-cal-day="{day}"]')
    pg.wait_for_timeout(120)
    pg.click('#calpop [data-cal-close]')
    pg.wait_for_timeout(60)


def main():
    port = 8841
    srv = Server(('127.0.0.1', port), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{port}/index.html'
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---------------- PC ----------------
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        ctx.grant_permissions(['clipboard-read', 'clipboard-write'])
        pg = ctx.new_page()
        pg.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        pg.goto(base, wait_until='networkidle')
        pg.evaluate('localStorage.clear()')
        pg.reload(wait_until='networkidle')
        pg.wait_for_timeout(300)

        # 1) 집보기 예약 안내 — 예약 확정 + 매물 208동 208호 + 매매 23억
        pick(pg, 't5')
        pg.click('#fields [data-date="when"]')
        pg.wait_for_timeout(200)
        pg.click('#calpop [data-cal-nav="1"]')
        pg.wait_for_timeout(120)
        pg.click('#calpop [data-cal-day="5"]')
        pg.wait_for_timeout(150)
        pg.select_option('#calpop [data-cal-hour]', '11')
        pg.wait_for_timeout(100)
        pg.select_option('#calpop [data-cal-min]', '30')
        pg.wait_for_timeout(150)
        pg.click('#calpop [data-cal-close]')
        pg.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        pg.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '208')
        pg.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '230000')
        pg.wait_for_timeout(300)
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-pc.png'))
        pg.screenshot(path=sh(DOCS, 'shot-pc.png'))

        # 1-1) 매물 줄 인라인 배지 세 가지 — 동·호 / 동·층 / 단지
        for i, (dong, ho, amount) in enumerate((('307', '802', '185000'), ('404', '1903', '320000'))):
            pg.click('#fields [data-add-item="items"]')
            pg.wait_for_timeout(160)
            idx = i + 1
            pg.fill(f'#fields [data-prop="items"][data-idx="{idx}"][data-key="dong"]', dong)
            pg.fill(f'#fields [data-prop="items"][data-idx="{idx}"][data-key="ho"]', ho)
            pg.fill(f'#fields [data-prop="items"][data-idx="{idx}"][data-money="amount"]', amount)
        pg.click('#fields [data-unit-list="items"][data-idx="1"][data-prop-unit="ho"]')   # 층
        pg.wait_for_timeout(160)
        pg.click('#fields [data-unit-list="items"][data-idx="2"][data-prop-unit="dong"]')  # 단지
        pg.wait_for_timeout(220)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.mouse.move(1300, 840)
        pg.wait_for_timeout(120)
        pg.locator('#fields .field:has(.prop-item)').first.screenshot(path=sh(DOCS, 'shot-exposure.png'))

        # 2) 협력업체·상담사 안내 (연락처 체크)
        pick(pg, 't20')
        pg.wait_for_timeout(250)
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-vendor.png'))
        pg.screenshot(path=sh(DOCS, 'shot-vendor.png'))

        # 2-1) 보낼 상담사 목록 — 3개 높이에서 단독 스크롤 (4개부터 넘친다)
        pg.click('#fields [data-seg="vendorCat"][data-value="대출"]')
        pg.wait_for_timeout(150)
        for name, phone in (('국민 대출 박지훈', '010-2222-3311'),
                            ('우리 대출 이서연', '010-3333-4422'),
                            ('카카오 대출 최민수', '010-4444-5533')):
            pg.fill('#fields [data-contact-new="name"]', name)
            pg.fill('#fields [data-contact-new="phone"]', phone)
            pg.click('#fields [data-contact-add]')
            pg.wait_for_timeout(150)
        pg.wait_for_timeout(2200)   # '연락처를 추가했어요' 토스트가 사라지길 기다린다
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-vendor-scroll.png'))
        pg.evaluate("document.querySelector('#fields .contact-list').scrollTop = 9999")
        pg.wait_for_timeout(250)
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-vendor-scroll-end.png'))
        pg.evaluate("document.querySelector('#fields .contact-list').scrollTop = 0")

        # 3) 집보기 후 감사 인사 (🎲 다른 문구 · 안부)
        pick(pg, 't17')
        pg.click('#fields [data-action="vary"]')
        pg.wait_for_timeout(120)
        pg.click('#fields [data-seg="greet"][data-value="cold"]')
        pg.wait_for_timeout(200)
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-thanks.png'))
        pg.screenshot(path=sh(DOCS, 'shot-thanks.png'))

        # 4) 명단 매칭 매물 의뢰 제안
        pick(pg, 't16')
        pg.wait_for_timeout(200)
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-myungdan.png'))
        pg.screenshot(path=sh(DOCS, 'shot-myungdan.png'))

        # 5) 중개보수 계산기 — 부가세는 기본값(간이 4%) 그대로
        pick(pg, 't14')
        pg.fill('#fields [data-field="calcAmount"]', '230000')
        pg.wait_for_timeout(250)
        pg.evaluate('document.activeElement && document.activeElement.blur()')
        pg.wait_for_timeout(150)
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-calc.png'))
        pg.screenshot(path=sh(DOCS, 'shot-calc.png'))

        # 6) 매매 약정 (긴 폼) — 스파이더 계약 팝업형 지급 일정 표
        pick(pg, 't8')
        pg.fill('#fields [data-field="price"]', '237000')
        pg.click('#fields [data-action="autoFill"]')
        pg.fill('#fields [data-field="account"]', '하나 54791017281007 신동범')
        pg.fill('#fields [data-field="jeongAmount"]', '2370')
        pg.wait_for_timeout(250)
        pg.click('#fields [data-toggle="permit"]')
        pg.wait_for_timeout(250)
        pg.evaluate("""() => { const f = document.querySelector('#fields');
          const t = f.querySelector('.paytable');
          f.scrollTop += t.getBoundingClientRect().top - f.getBoundingClientRect().top - 8; }""")
        pg.evaluate("() => { const l = document.querySelector('#tpl-list'); if (l) l.scrollTop = 0; }")
        pg.wait_for_timeout(2100)   # '계약금 10% …' 토스트가 사라지길 기다린다
        pg.screenshot(path=sh(DOWNLOADS, 'sms-app-pay.png'))
        pg.screenshot(path=sh(DOCS, 'shot-contract.png'))

        # 7) 고정 문자 · 내 정보 설정
        pick(pg, 't6')
        pg.wait_for_timeout(200)
        pg.screenshot(path=sh(DOCS, 'shot-fixed.png'))
        pg.click('#btn-settings')
        pg.wait_for_timeout(200)
        pg.screenshot(path=sh(DOCS, 'shot-settings.png'))
        pg.click('#btn-settings-close')
        ctx.close()

        # ---------------- 작은 PC 창 (1000×720) ----------------
        c = browser.new_context(viewport={'width': 1000, 'height': 720}, device_scale_factor=1.5)
        cp = c.new_page()
        cp.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        cp.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        cp.goto(base, wait_until='networkidle')
        cp.wait_for_timeout(300)
        cp.click('#tpl-list [data-id="t8"]')
        cp.wait_for_timeout(300)
        cp.fill('#fields [data-field="price"]', '247000')
        cp.fill('#fields [data-field="jeongAmount"]', '3000')
        cp.click('#fields [data-action="autoFill"]')
        cp.wait_for_timeout(250)
        # 약정금·계약금·중도금·잔금 일정을 실제 날짜로 채운 상태로 찍는다
        pay_date(cp, 'jeongDate', 2026, 11, 28)
        pay_date(cp, 'gyeyakDate', 2026, 12, 5)
        pay_date(cp, 'jungDate', 2027, 1, 15)
        pay_date(cp, 'janDate', 2027, 2, 26)
        cp.evaluate("document.activeElement && document.activeElement.blur()")
        cp.evaluate("""() => { const f = document.querySelector('#fields');
          const t = f.querySelector('.paytable');
          f.scrollTop += t.getBoundingClientRect().top - f.getBoundingClientRect().top - 8; }""")
        cp.evaluate("() => { const l = document.querySelector('#tpl-list'); if (l) l.scrollTop = 0; }")
        cp.wait_for_timeout(2100)   # 토스트가 사라진 뒤
        cp.screenshot(path=sh(DOWNLOADS, 'sms-app-1000x720.png'))
        c.close()

        # ---------------- 모바일 ----------------
        m = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3,
                                is_mobile=True, has_touch=True)
        mp = m.new_page()
        mp.on('console', lambda msg: errors.append(f'{msg.type}: {msg.text}') if msg.type in ('error', 'warning') else None)
        mp.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        mp.goto(base, wait_until='networkidle')
        mp.wait_for_timeout(300)
        mp.click('#btn-sheet')
        mp.wait_for_timeout(250)
        mp.screenshot(path=sh(DOCS, 'shot-mobile-sheet.png'))
        # 이번에 바뀐 매물 줄(단지명 · 동/단지 배지 · 호/층 배지)이 보이는 화면
        mp.click('#sheet-list [data-id="t7"]')
        mp.wait_for_timeout(350)
        mp.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        mp.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '1103')
        # 금액칸(스파이더형) — 월세 두 칸이 반씩 나란히, 칸마다 아래 환산 줄
        mp.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
        mp.wait_for_timeout(250)
        mp.fill('#fields [data-prop="items"][data-idx="0"][data-money="deposit"]', '10000')
        mp.fill('#fields [data-prop="items"][data-idx="0"][data-money="rent"]', '300')
        mp.evaluate('document.activeElement && document.activeElement.blur()')
        mp.wait_for_timeout(250)
        mp.evaluate('window.scrollTo(0, 0)')
        mp.wait_for_timeout(250)
        mp.screenshot(path=sh(DOWNLOADS, 'sms-app-mobile.png'))
        mp.screenshot(path=sh(DOCS, 'shot-mobile.png'))

        # 협력업체 목록(모바일)
        mp.click('#btn-sheet')
        mp.wait_for_timeout(200)
        mp.click('#sheet-list [data-id="t20"]')
        mp.wait_for_timeout(300)
        mp.evaluate('window.scrollTo(0, 0)')
        mp.wait_for_timeout(200)
        mp.screenshot(path=sh(DOCS, 'shot-mobile-vendor.png'))

        # 모바일 · 간단 집보기 문의 (달력)
        mp.click('#btn-sheet')
        mp.wait_for_timeout(200)
        mp.click('#sheet-list [data-id="t3"]')
        mp.wait_for_timeout(200)
        mp.click('#fields [data-date="when"]')
        mp.wait_for_timeout(300)
        mp.screenshot(path=sh(DOCS, 'shot-mobile-cal.png'))
        mp.click('#calpop [data-cal-close]')

        # 모바일 · 지급 일정 표 (2단 줄바꿈)
        mp.click('#btn-sheet')
        mp.wait_for_timeout(200)
        mp.click('#sheet-list [data-id="t8"]')
        mp.wait_for_timeout(250)
        mp.fill('#fields [data-field="price"]', '247000')
        mp.fill('#fields [data-field="jeongAmount"]', '3000')
        mp.click('#fields [data-action="autoFill"]')
        mp.wait_for_timeout(250)
        mp.evaluate('document.activeElement && document.activeElement.blur()')
        mp.evaluate("document.querySelector('#fields .paytable').scrollIntoView({block:'center'})")
        mp.wait_for_timeout(250)
        mp.screenshot(path=sh(DOCS, 'shot-mobile-pay.png'))
        # 지급 일정 표 좌우 균형 확인용 — 실제 날짜를 채운 390×844 화면
        pay_date(mp, 'jeongDate', 2026, 11, 28)
        pay_date(mp, 'gyeyakDate', 2026, 12, 5)
        pay_date(mp, 'jungDate', 2027, 1, 15)
        pay_date(mp, 'janDate', 2027, 2, 26)
        mp.evaluate('document.activeElement && document.activeElement.blur()')
        mp.evaluate("document.querySelector('#fields .paytable').scrollIntoView({block:'center'})")
        mp.wait_for_timeout(2100)   # 토스트가 사라진 뒤
        mp.screenshot(path=sh(DOWNLOADS, 'sms-app-paytable-t8-390x844.png'))
        m.close()
        browser.close()

    srv.shutdown()
    print('저장 완료:')
    for f in ('sms-app-pc.png', 'sms-app-mobile.png', 'sms-app-vendor.png', 'sms-app-thanks.png',
              'sms-app-myungdan.png', 'sms-app-calc.png', 'sms-app-pay.png',
              'sms-app-vendor-scroll.png', 'sms-app-vendor-scroll-end.png', 'sms-app-1000x720.png',
              'sms-app-paytable-t8-390x844.png'):
        path = sh(DOWNLOADS, f)
        print(' ', path, os.path.getsize(path), 'bytes')
    print('콘솔 오류:', errors if errors else '없음')


if __name__ == '__main__':
    main()
