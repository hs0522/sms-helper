"""마래푸중앙부동산 문자 도우미 — 자동 테스트

실행:
    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/test_app.py -v

- 단위 테스트: 화면에 실제로 실린 js/core.js 함수를 브라우저 안에서 그대로 호출해 검증
  (중개보수 계산 · 금액 표기 · 노출 변환 · 계좌 파서 · 날짜 표기)
- 화면 테스트: 20종 템플릿 전환 · 토글 · 달력 · 복사 · 저장(localStorage) · 모바일 레이아웃
- 새 문자: 명단 매칭 · 집보기 일정(간단/상세) · 감사 인사(문구 돌리기) · 공동중개 거절 후 매물 부탁 ·
  특가 안내 · 협력업체·상담사(연락처 저장·추가·삭제)
- 매물 스파이더 연동: URL 쿼리로 값 채워 열기
"""
import functools
import http.server
import json
import os
import re
import socketserver
import threading
import unittest
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8830
BASE = f'http://127.0.0.1:{PORT}/index.html'
DOWNLOADS = '/workspace/downloads'


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(_Quiet, directory=ROOT)
        cls.srv = _Server(('127.0.0.1', PORT), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.srv.shutdown()

    def setUp(self):
        self.ctx = self.browser.new_context(
            viewport={'width': 1440, 'height': 900},
            permissions=['clipboard-read', 'clipboard-write'],
        )
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on('console', lambda m: self.errors.append(f'{m.type}: {m.text}')
                     if m.type in ('error', 'warning') else None)
        self.page.on('pageerror', lambda e: self.errors.append(f'pageerror: {e}'))
        self.page.goto(BASE, wait_until='networkidle')
        self.page.evaluate('localStorage.clear()')
        self.page.reload(wait_until='networkidle')

    def tearDown(self):
        self.assertEqual(self.errors, [], '콘솔 오류가 없어야 한다')
        self.ctx.close()

    # ------------------------------------------------------------------ helpers
    def js(self, expr, arg=None):
        if arg is None:
            return self.page.evaluate(expr)
        return self.page.evaluate(expr, arg)

    def pick(self, tid):
        self.page.click(f'#tpl-list [data-id="{tid}"]')
        self.page.wait_for_timeout(80)

    def pick_with(self, tid, patch=None):
        """템플릿을 열면서 저장값 일부를 미리 채운다 (통합된 화면의 조합 고르기)"""
        self.page.evaluate("a => window.SMSApp.openTemplate(a[0], a[1] || {})", [tid, patch or {}])
        self.wait(120)

    def text(self):
        return self.page.input_value('#preview')

    # 지급 일정 — 항목·차수 칸 (약정금·가계약금·계약금·중도금·잔금)
    def pay_fill(self, key, man, idx=0):
        self.page.fill(f'#fields [data-pay-amt="{key}"][data-pay-idx="{idx}"]', str(man))
        self.wait(120)

    def pay_rate(self, key, pct, idx=0):
        self.page.fill(f'#fields [data-pay-rate="{key}"][data-pay-idx="{idx}"]', str(pct))
        self.wait(150)

    def pay_add(self, key, idx=0):
        sel = f'#fields .pay-row[data-pay-item="{key}"][data-pay-idx="{idx}"] [data-pay-add]'
        self.page.eval_on_selector(sel, "e => e.scrollIntoView({block: 'center'})")
        self.wait(80)
        self.page.click(sel)
        self.wait(150)

    def pay_del(self, key, idx=0):
        sel = f'#fields .pay-row[data-pay-item="{key}"][data-pay-idx="{idx}"] [data-pay-del]'
        self.page.eval_on_selector(sel, "e => e.scrollIntoView({block: 'center'})")
        self.wait(80)
        self.page.click(sel)
        self.wait(150)

    def pay_rows(self):
        return self.js("""() => [...document.querySelectorAll('#fields .pay-row')].map(r => ({
            item: r.dataset.payItem, idx: +r.dataset.payIdx,
            name: r.querySelector('.pay-name-text').textContent.trim(),
            amt: r.querySelector('[data-pay-amt]').value,
            rate: (r.querySelector('[data-pay-rate]') || { value: null }).value }))""")


    def wait(self, ms=120):
        self.page.wait_for_timeout(ms)

    # 금액 칸 한 벌의 모양 — 정렬 · 안쪽 '만원' · 아래 환산 줄
    MONEY_INFO_JS = """(sel) => {
      const inp = document.querySelector(sel);
      if (!inp) return null;
      const field = inp.closest('.money-field');
      const unit = field.querySelector('.money-box .money-unit');
      const hint = field.querySelector('.money-hint');
      const ir = inp.getBoundingClientRect(), ur = unit.getBoundingClientRect(), hr = hint.getBoundingClientRect();
      const cs = getComputedStyle(inp), hs = getComputedStyle(hint);
      return {
        value: inp.value, align: cs.textAlign, padRight: parseFloat(cs.paddingRight),
        unit: unit.textContent.trim(), unitFont: parseFloat(getComputedStyle(unit).fontSize),
        hint: hint.textContent, hintAlign: hs.textAlign, hintColor: hs.color,
        hintClipped: hint.scrollWidth > hint.clientWidth + 1,
        textFits: inp.scrollWidth <= inp.clientWidth + 1 && inp.scrollLeft === 0,
        unitInside: ur.left >= ir.left + 1 && ur.right <= ir.right - 1,
        sameRow: ur.top >= ir.top - 0.5 && ur.bottom <= ir.bottom + 0.5,
        hintBelow: hr.top >= ir.bottom - 0.5,
        hintLeft: +(hr.left - ir.left).toFixed(1),
        hintBottom: hr.bottom, inputBottom: ir.bottom,
        inputRect: {l: ir.left, r: ir.right, t: ir.top, b: ir.bottom},
        hintRect: {l: hr.left, r: hr.right, t: hr.top, b: hr.bottom},
        unitRect: {l: ur.left, r: ur.right, t: ur.top, b: ur.bottom},
        minHintH: parseFloat(hs.minHeight || '0')
      };
    }"""

    def money_info(self, sel):
        return self.js(self.MONEY_INFO_JS, sel)

    def page_with_state(self, state):
        state.setdefault('profile', {'office': '마래푸중앙부동산', 'phones': '010-4585-7365 / 02-312-7365',
                                     'feeAccount': '우리은행 1002-762-106047 황호선', 'amountMode': 'won_eokman'})
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.add_init_script("localStorage.setItem('smshelper.v1', JSON.stringify(%s));" % json.dumps(state))
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(200)
        return ctx, page

    # ================================================================== 금액 표기
    def test_amount_formatting_modes(self):
        cases = [
            # 전체 — 원단위 + (억·만)
            ([27000, 'won_eokman'], '270,000,000원 (2억 7천만 원)'),
            ([20000, 'won_eokman'], '200,000,000원 (2억 원)'),
            ([500, 'won_eokman'], '5,000,000원 (500만 원)'),
            ([1, 'won_eokman'], '10,000원 (1만 원)'),
            ([12345, 'won_eokman'], '123,450,000원 (1억 2,345만 원)'),
            # 만원 단위 — 만 원 단위 쉼표 + '만 원'
            ([27000, 'won'], '27,000만 원'),
            ([160550, 'won'], '160,550만 원'),
            ([0, 'won'], '0만 원'),
            # 끊어읽기 — 띄어쓰기 없이
            ([27000, 'eokman'], '2억7천만 원'),
            ([23700, 'eokman'], '2억3,700만 원'),
            ([3000, 'eokman'], '3천만 원'),
            ([247000, 'eokman'], '24억7천만 원'),
            ([160550, 'eokman'], '16억550만 원'),
            # 예전 저장값도 그대로 받는다
            ([27000, 'won_eok'], '270,000,000원 (2억 7천만 원)'),
            ([27000, 'eok'], '2억7천만 원'),
            ([27000, None], '270,000,000원 (2억 7천만 원)'),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(self.js('(a) => SMSCore.formatAmount(a[0], a[1])', args), want)

    def test_parse_man(self):
        cases = [('23700', 23700), ('23,700', 23700), ('', None), ('  ', None),
                 ('2억', 20000), ('2억 7천만', 27000), ('23억', 230000), ('5천', 5000), ('750만', 750)]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(self.js('(v) => SMSCore.parseMan(v)', raw), want)

    def test_man_hint(self):
        self.assertEqual(self.evaluate_hint(20000), '2억')
        self.assertEqual(self.evaluate_hint(27000), '2억 7천만')
        self.assertEqual(self.evaluate_hint(350), '350만')
        self.assertEqual(self.evaluate_hint(90000), '9억')

    def test_money_hint_line(self):
        # 입력칸 아래 환산 줄 — 원단위 + (억·만)
        cases = [(230000, '2,300,000,000원 (23억)'),
                 (23700, '237,000,000원 (2억 3,700만)'),
                 (10000, '100,000,000원 (1억)'),
                 (300, '3,000,000원 (300만)'),
                 (115000, '1,150,000,000원 (11억 5천만)'),
                 (0, ''),
                 (None, ''),
                 ('', '')]
        for man, want in cases:
            with self.subTest(man=man):
                self.assertEqual(self.page.evaluate('(v) => SMSCore.moneyHintLine(v)', man), want)

    def evaluate_hint(self, man):
        return self.js('(v) => SMSCore.manHint(v)', man)

    # ================================================================== 중개보수
    def fee(self, **kw):
        return self.js('(o) => SMSCore.feeCalc(o)', kw)

    def test_fee_house_sale(self):
        cases = [
            (3000, 180000, 0.6),
            (5000, 250000, 0.5),      # 한도 25만 원
            (20000, 800000, 0.4),
            (90000, 4500000, 0.5),
            (120000, 7200000, 0.6),
            (150000, 10500000, 0.7),
            (237000, 16590000, 0.7),  # 23억 7천만
        ]
        for man, fee, rate in cases:
            with self.subTest(man=man):
                r = self.fee(kind='house', trade='매매', amountMan=man)
                self.assertTrue(r['ok'])
                self.assertEqual(r['fee'], fee)
                self.assertAlmostEqual(r['ratePct'], rate)

    def test_fee_house_lease(self):
        cases = [
            (4900, 200000, 0.5),      # 한도 20만
            (5000, 200000, 0.4),      # 한도 30만 이내
            (8000, 300000, 0.4),      # 32만 → 한도 30만
            (30000, 900000, 0.3),     # 3억
            (70000, 2800000, 0.4),    # 7억
            (130000, 6500000, 0.5),   # 13억
            (160000, 9600000, 0.6),   # 16억
        ]
        for man, fee, rate in cases:
            with self.subTest(man=man):
                r = self.fee(kind='house', trade='전세', amountMan=man)
                self.assertEqual(r['fee'], fee)
                self.assertAlmostEqual(r['ratePct'], rate)

    def test_fee_monthly_conversion(self):
        r = self.fee(kind='house', trade='월세', depositMan=10000, rentMan=50)
        self.assertEqual(r['amountMan'], 15000)
        self.assertTrue(r['converted'])
        self.assertEqual(r['fee'], 450000)

        r2 = self.fee(kind='house', trade='월세', depositMan=1000, rentMan=30)
        self.assertEqual(r2['amountMan'], 3100)
        self.assertEqual(r2['fee'], 155000)

        r3 = self.fee(kind='house', trade='월세', depositMan=2000, rentMan=30)
        self.assertEqual(r3['amountMan'], 5000)

    def test_fee_other_kinds(self):
        self.assertEqual(self.fee(kind='officetel', trade='매매', amountMan=30000)['fee'], 1500000)
        self.assertEqual(self.fee(kind='officetel', trade='전세', amountMan=20000)['fee'], 800000)
        r = self.fee(kind='presale', trade='매매', amountMan=50000)
        self.assertEqual(r['fee'], 2000000)
        self.assertAlmostEqual(r['ratePct'], 0.4)
        self.assertEqual(self.fee(kind='commercial', trade='매매', amountMan=50000)['fee'], 4500000)
        self.assertEqual(self.fee(kind='commercial', trade='월세', depositMan=10000, rentMan=100)['fee'], 1800000)

    def test_fee_vat(self):
        base = self.fee(kind='house', trade='매매', amountMan=20000, vat='none')
        v4 = self.fee(kind='house', trade='매매', amountMan=20000, vat='4')
        v10 = self.fee(kind='house', trade='매매', amountMan=20000, vat='10')
        self.assertEqual(base['total'], 800000)
        self.assertEqual(v4['vat'], 32000)
        self.assertEqual(v4['total'], 832000)
        self.assertEqual(v10['vat'], 80000)
        self.assertEqual(v10['total'], 880000)

    def test_fee_negotiated_rate(self):
        r = self.fee(kind='house', trade='매매', amountMan=20000, ratePct=0.3)
        self.assertEqual(r['fee'], 600000)
        self.assertAlmostEqual(r['ratePct'], 0.3)
        r2 = self.fee(kind='house', trade='매매', amountMan=20000, ratePct=0.9)
        self.assertEqual(r2['fee'], 800000)
        self.assertAlmostEqual(r2['ratePct'], 0.4)
        r3 = self.fee(kind='house', trade='매매', amountMan=20000, ratePct='')
        self.assertEqual(r3['fee'], 800000)

    def test_fee_needs_amount(self):
        self.assertFalse(self.fee(kind='house', trade='매매')['ok'])
        self.assertFalse(self.fee(kind='house', trade='월세')['ok'])

    # ================================================================== 노출 변환
    def test_property_exposure(self):
        cases = [
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'mode': 'ho'},
             '마포래미안푸르지오 208동 208호'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'mode': 'floor'},
             '마포래미안푸르지오 208동 2층'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'mode': 'complex'},
             '마포래미안푸르지오 2단지 208호'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103', 'mode': 'floor'},
             '마포래미안푸르지오 208동 11층'),
            ({'complex': '마포래미안푸르지오', 'dong': '304', 'ho': '1103', 'mode': 'complex'},
             '마포래미안푸르지오 3단지 1103호'),
            ({'complex': '마포래미안푸르지오', 'dong': '105', 'ho': '101', 'mode': 'complex'},
             '마포래미안푸르지오 1단지 101호'),
            ({'complex': '마포래미안푸르지오', 'dong': '402', 'ho': '201', 'mode': 'complex'},
             '마포래미안푸르지오 4단지 201호'),
            # 단지로 가려도 호수 칸에 값이 있으면 층·호수가 붙는다 (비우면 단지까지만)
            ({'complex': '마포래미안푸르지오', 'dong': '404', 'ho': '1903', 'dongMode': 'complex', 'hoMode': 'floor'},
             '마포래미안푸르지오 4단지 19층'),
            ({'complex': '마포래미안푸르지오', 'dong': '201', 'ho': '1203', 'dongMode': 'complex', 'hoMode': 'floor'},
             '마포래미안푸르지오 2단지 12층'),
            ({'complex': '마포래미안푸르지오', 'dong': '201', 'ho': '1203', 'dongMode': 'complex', 'hoMode': 'ho'},
             '마포래미안푸르지오 2단지 1203호'),
            ({'complex': '마포래미안푸르지오', 'dong': '201', 'ho': '', 'dongMode': 'complex', 'hoMode': 'floor'},
             '마포래미안푸르지오 2단지'),
            ({'complex': '마포래미안푸르지오', 'dong': '105', 'ho': '101', 'mode': 'floor'},
             '마포래미안푸르지오 105동 1층'),
            ({'complex': '마포래미안푸르지오', 'dong': '208동', 'ho': '208호', 'mode': 'ho'},
             '마포래미안푸르지오 208동 208호'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '', 'mode': 'ho'},
             '마포래미안푸르지오 208동'),
            # 동·호 → 단지·층 (특가 안내의 빠른 변환)
            ({'complex': '마포래미안푸르지오', 'dong': '404', 'ho': '1903', 'mode': 'complex'},
             '마포래미안푸르지오 4단지 1903호'),
            # 매물 줄의 인라인 배지 (동 ↔ 단지 · 호 ↔ 층)
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'dongMode': 'dong', 'hoMode': 'ho'},
             '마포래미안푸르지오 208동 208호'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'dongMode': 'dong', 'hoMode': 'floor'},
             '마포래미안푸르지오 208동 2층'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103', 'dongMode': 'dong', 'hoMode': 'floor'},
             '마포래미안푸르지오 208동 11층'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103', 'dongMode': 'complex', 'hoMode': 'ho'},
             '마포래미안푸르지오 2단지 1103호'),
            ({'complex': '마포래미안푸르지오', 'dong': '307', 'ho': '802', 'dongMode': 'complex', 'hoMode': 'floor'},
             '마포래미안푸르지오 3단지 8층'),
            # 배지 설정이 있으면 예전 mode 값보다 우선한다
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103', 'mode': 'floor', 'dongMode': 'dong', 'hoMode': 'ho'},
             '마포래미안푸르지오 208동 1103호'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103', 'mode': 'ho', 'dongMode': 'complex'},
             '마포래미안푸르지오 2단지 1103호'),
            ({'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '', 'dongMode': 'dong', 'hoMode': 'floor'},
             '마포래미안푸르지오 208동'),
            # 단지명은 늘 앞에 붙는다
            ({'complex': '마포래미안푸르지오', 'dong': '', 'ho': '', 'dongMode': 'complex'}, '마포래미안푸르지오'),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(self.js('(p) => SMSCore.propertyLabel(p)', args), want)

    # ================================================================== 계좌 파서
    def test_account_parser(self):
        cases = [
            ('국민 479002-01-037629 박소미', '국민은행 479002-01-037629 박소미'),
            ('박소미 하나 54791017281007', '하나은행 54791017281007 박소미'),
            ('우리은행 1002-762-106047 황호선', '우리은행 1002-762-106047 황호선'),
            ('카카오뱅크 3333-01-1234567 김철수', '카카오뱅크 3333-01-1234567 김철수'),
            ('신한 110-123-456789', '신한은행 110-123-456789'),
            ('NH농협 301-1234-5678 홍길동', '농협은행 301-1234-5678 홍길동'),
            ('토스뱅크 1000-1234-5678 이서연', '토스뱅크 1000-1234-5678 이서연'),
            ('우리은행 1002-762-106047황호선', '우리은행 1002-762-106047 황호선'),
            ('우리은행1002-762-106047황호선', '우리은행 1002-762-106047 황호선'),
            ('국민 479002-01-037629박소미', '국민은행 479002-01-037629 박소미'),
            ('', ''),
            ('   ', ''),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(self.js('(v) => SMSCore.accountParse(v)', raw), want)

    # ================================================================== 날짜
    def test_date_formatting(self):
        # 앱 어디서나 24시간 표기 — 휠 피커도 00시~23시
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:11, min:30})"""),
            '2026년 11월 28일 토요일 11:30')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:null, min:0})"""),
            '2026년 11월 28일 토요일')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:0, min:0})"""),
            '2026년 11월 28일 토요일 00:00')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:12, min:0})"""),
            '2026년 11월 28일 토요일 12:00')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:14, min:5})"""),
            '2026년 11월 28일 토요일 14:05')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTimeRange({date:'2026-11-28', hour:10, min:0}, {hour:12, min:0})"""),
            '2026년 11월 28일 토요일 10:00 ~ 12:00')
        self.assertEqual(
            self.js("""() => SMSCore.compactDateTime({date:'2026-11-28', hour:14, min:30})"""),
            '2026.11.28 (토) 14:30')
        self.assertEqual(self.js('() => SMSCore.weekdayOf(2026, 11, 24)'), '화')

    def test_short_datetime_for_simple_ask(self):
        # 문자에 들어가는 짧은 표기: "내일 9/23 (화) 09:30"
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-09-23', hour:9, min:30},
                       new Date(2026, 8, 22))"""),
            '내일 9/23 (수) 09:30')
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-11-25', hour:14, min:0},
                       new Date(2026, 10, 25))"""),
            '오늘 11/25 (수) 14:00')
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-12-05', hour:10, min:0},
                       new Date(2026, 10, 25))"""),
            '12/5 (토) 10:00')
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-11-27', hour:null, min:0},
                       new Date(2026, 10, 25))"""),
            '모레 11/27 (금)')

    def test_phone_format(self):
        cases = [('01047572152', '010-4757-2152'), ('010-4757-2152', '010-4757-2152'),
                 ('023127365', '02-312-7365'), ('', '')]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(self.js('(v) => SMSCore.formatPhone(v)', raw), want)

    # ================================================================== 화면
    def test_all_templates_render(self):
        # 2026-11-26 통합 — 집보기 문의(t3+t4), 계약 일정 안내(t9+t10+t13)로 17종
        ids = self.js('() => SMSTemplates.TEMPLATES.map(t => t.id)')
        self.assertEqual(len(ids), 17)
        self.assertEqual(len(set(ids)), 17, '템플릿 id가 겹치면 안 된다')
        nos = self.js('() => SMSTemplates.TEMPLATES.map(t => t.no)')
        self.assertEqual(sorted(nos), list(range(1, 18)), '번호가 1~17로 이어져야 한다')
        for tid in ids:
            with self.subTest(tid=tid):
                self.pick(tid)
                body = self.text()
                self.assertGreater(len(body), 40, f'{tid} 본문이 너무 짧다')
                self.assertNotIn('\n\n\n', body, f'{tid} 빈 줄이 겹친다')
                # 17종 모두 맨 아래에 한 줄을 띄우고 상호·번호 서명이 늘 들어간다
                self.assertIn('\n\n마래푸중앙부동산', body, f'{tid} 서명 앞에 한 줄이 비지 않았다')
                self.assertTrue(body.endswith('010-4585-7365 / 02-312-7365'), f'{tid} 맨 아래가 연락처가 아니다')
                self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0,
                                 f'{tid} 서명 토글이 남아 있다')

    def test_no_signature_toggle_anywhere(self):
        # 서명 토글 필드는 어느 문구에도 없다
        found = self.js("""() => {
          const out = [];
          SMSTemplates.TEMPLATES.forEach(t => (t.fields || []).forEach(f => {
            if (f.id === 'signature' || f.t === 'toggle' && /\uc11c\uba85/.test(f.label || '')) out.push(t.id + ':' + f.id);
          }));
          return out;
        }""")
        self.assertEqual(found, [])
        # 화면에서도 스위치가 사라졌다 (예전에 토글이 있던 7종)
        for tid in ('t16', 't3', 't17', 't18', 't19', 't20'):
            with self.subTest(tid=tid):
                self.pick(tid)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0)
                self.assertNotIn('상호·번호 서명', self.page.inner_text('#fields'))

    def test_every_template_and_option_ends_with_footer(self):
        # 모든 문구 × 화면에서 고를 수 있는 모든 조합의 맨 아래에 서명이 빠짐없이 붙는다
        bad = self.js(r"""() => {
          const ctx = { office: '마래푸중앙부동산', phones: '010-4585-7365 / 02-312-7365',
                        feeAccount: '우리은행 1002-762-106047 황호선', amountMode: 'won_eokman',
                        contacts: SMSTemplates.defaultContacts() };
          const TAIL = '\n\n마래푸중앙부동산';
          const out = [];
          const check = (t, patch, tag) => {
            const d = Object.assign(SMSTemplates.defaultData(t), patch || {});
            const body = t.build(d, ctx);
            const lines = body.split('\n');
            const tail = lines.slice(-2).join('\n');
            const ok = body.includes(TAIL) && lines[lines.length - 1] === '010-4585-7365 / 02-312-7365'
                       && /^마래푸중앙부동산( 대표 황호선)? 드림$/.test(lines[lines.length - 2]);
            if (!ok) out.push(t.id + ' ' + tag + ' :: ' + tail);
          };
          const combos = {
            t2: [{ moveinMode: '협의' }, { moveinMode: '고정' }, { moveinMode: '기간' }],
            t3: [{ who: 'owner', view: 'simple' }, { who: 'owner', view: 'detail' },
                 { who: 'coagent', view: 'simple' }, { who: 'coagent', view: 'detail' }],
            t5: [{ status: 'confirmed' }, { status: 'pending' }],
            t8: [{ trade: '매매', kind: '약정' }, { trade: '매매', kind: '계약' },
                 { trade: '전세', kind: '계약' }, { trade: '월세', kind: '계약' }],
            t10: [{ trade: '매매', kind: '약정' }, { trade: '매매', kind: '계약' },
                  { trade: '매매', kind: '중도금' }, { trade: '매매', kind: '잔금' },
                  { trade: '전세', kind: '계약' }, { trade: '전세', kind: '중도금' },
                  { trade: '전세', kind: '잔금' }, { trade: '월세', kind: '계약' },
                  { trade: '월세', kind: '중도금' }, { trade: '월세', kind: '잔금' }],
            t11: [{ trade: '매매' }, { trade: '임대차' }],
            t12: [{ owner: '공동' }, { owner: '단독' }],
            t15: [{ role: '임대인' }, { role: '임차인' }],
            t16: [{ trade: '매매' }, { trade: '전세' }, { trade: '월세' }],
            t18: [{ trade: '전세' }, { trade: '매매' }, { trade: '월세', deposit: '10000', rent: '250' }],
            t19: [{ trade: '매매' }, { trade: '전세' }, { trade: '월세' }]
          };
          SMSTemplates.TEMPLATES.forEach(t => {
            (combos[t.id] || [{}]).forEach((patch, i) => check(t, patch, 'combo' + i));
          });
          // 감사 인사는 대상 3 × 문구 7 × 안부 4(날씨·아침·저녁·연휴) 전부
          const t17 = SMSTemplates.TEMPLATES.find(t => t.id === 't17');
          ['resident', 'coagent', 'guest'].forEach(target => {
            SMSTemplates.VARIANTS[target].forEach((_, idx) => {
              SMSTemplates.GREETINGS.forEach(g => {
                check(t17, { target: target, vpick: { resident: idx, coagent: idx, guest: idx }, greets: [g.v] },
                      target + '/' + idx + '/' + g.v);
              });
            });
          });
          return out;
        }""")
        self.assertEqual(bad, [], '서명이 빠지거나 맨 아래가 아닌 조합: %s' % bad)

    def test_no_brackets_in_any_template(self):
        # 어느 조합에서도 문자 본문에 대괄호 [ ] 가 나오지 않는다
        # (빈 값 자리는 소괄호, 섹션 머리말은 ■ 로 바쳤다)
        bad = self.js(r"""() => {
          const ctx = { office: '마래푸중앙부동산', phones: '010-4585-7365 / 02-312-7365',
                        feeAccount: '우리은행 1002-762-106047 황호선', amountMode: 'won_eokman',
                        contacts: SMSTemplates.defaultContacts() };
          const out = [];
          const check = (t, patch, tag) => {
            const d = Object.assign({ mode: 'ho' }, SMSTemplates.defaultData(t), patch || {});
            let body;
            try { body = t.build(d, ctx); } catch (e) { out.push(t.id + ' ' + tag + ' ERROR ' + e.message); return; }
            const hits = body.split('\n').filter(l => l.indexOf('[') !== -1 || l.indexOf(']') !== -1);
            if (hits.length) out.push(t.id + ' ' + tag + ' :: ' + hits.join(' / '));
          };
          const combos = {
            t2: [{}, { moveinMode: '협의' }, { moveinMode: '고정', moveinStart: { date: '2026-11-30' }, moveinFix: '선호' },
                  { moveinMode: '기간', moveinStart: { date: '2026-11-30' }, moveinEnd: { date: '2026-12-15' } }],
            t3: [{ who: 'owner', view: 'simple' }, { who: 'coagent', view: 'simple' },
                  { who: 'owner', view: 'detail', times: '12월 5일 (토) 10:00' },
                  { who: 'coagent', view: 'detail', times: '12월 5일 (토) 10:00 ~ 12:00' }],
            t5: [{ status: 'confirmed' }, { status: 'pending', detail: true }],
            t8: [{ trade: '매매', kind: '약정' },
                  { trade: '매매', kind: '약정', price: '247000', jeongAmount: '3000', gyeyakAmount: '24700',
                    jungAmount: '61750', permit: true, mortgage: true },
                  { trade: '매매', kind: '계약', mortgage: true, mortgageAmount: '12000', mortgageHolder: '카카오뱅크' },
                  { trade: '전세', kind: '계약', price: '115000', gyeyakAmount: '11500' },
                  { trade: '월세', kind: '계약', price: '10000', rent: '300', gyeyakAmount: '1000' }],
            t10: [{ trade: '매매', kind: '약정', when: { date: '2026-11-28', hour: 10, min: 0 } },
                   { trade: '매매', kind: '계약', jeongyakReturn: true },
                   { trade: '매매', kind: '중도금', gyeyak: '24700' },
                   { trade: '매매', kind: '잔금', docs: true, gyeyak: '24700', jung: '61750', jan: '154050' },
                   { trade: '전세', kind: '계약', priority: true },
                   { trade: '전세', kind: '잔금', registry: true, price: '115000' },
                   { trade: '월세', kind: '중도금', price: '10000', rent: '300', registry: true }],
            t11: [{ trade: '매매' }, { trade: '임대차' }],
            t12: [{ owner: '공동' }, { owner: '단독' }],
            t14: [{}, { calcAmount: '230000' }, { calcKind: 'commercial', calcTrade: '월세', calcDeposit: '10000', calcRent: '100' },
                  { calcAmount: '76000', calcTotalWon: '900000' }],
            t15: [{ role: '임대인' }, { role: '임차인' }],
            t16: [{ trade: '매매' }, { trade: '전세' }, { trade: '월세' }],
            t18: [{ trade: '전세' }, { trade: '매매', amount: '90000', area: '34' },
                  { trade: '월세', deposit: '10000', rent: '250' }],
            t19: [{}, { items: [{ complex: '마포래미안푸르지오', dong: '201', ho: '1203', trade: '전세', amount: '210000' }] }],
            t20: [{ vendorCat: '대출' }, { vendorCat: '법무사' }, { vendorCat: '이사' }]
          };
          SMSTemplates.TEMPLATES.forEach(t => {
            check(t, {}, 'blank');
            (combos[t.id] || [{}]).forEach((patch, i) => check(t, patch, 'combo' + i));
          });
          // 감사 인사는 대상 3 × 문구 7 × 안부 4 전부
          const t17 = SMSTemplates.TEMPLATES.find(t => t.id === 't17');
          ['resident', 'coagent', 'guest'].forEach(target => {
            SMSTemplates.VARIANTS[target].forEach((_, idx) => {
              SMSTemplates.GREETINGS.forEach(g => {
                check(t17, { target: target, vpick: { resident: idx, coagent: idx, guest: idx }, greets: [g.v] },
                      target + '/' + idx + '/' + g.v);
              });
            });
          });
          return out;
        }""")
        self.assertEqual(bad, [], '문자 본문에 대괄호가 남아 있다: %s' % bad)

    def test_section_heads_use_square_mark(self):
        # 섹션 머리말은 ■, 아직 넣지 않은 자리는 소괄호로 보인다
        self.pick('t8')
        body = self.text()
        self.assertIn('■ 계약금액 및 지급 일정', body)
        self.assertIn('■ 특약사항', body)
        self.assertIn('(계좌번호)', body)
        self.pick_with('t10', {'trade': '매매', 'kind': '가계약'})
        body = self.text()
        self.assertIn('■ 매도인 준비사항', body)
        self.assertIn('■ 매수인 준비사항', body)
        self.assertIn('(가계약 일시)', body)
        self.pick('t12')
        body = self.text()
        self.assertIn('■ 온라인 제출 절차', body)
        self.assertIn('■ 주요 증빙자료 예시', body)
        self.pick_with('t10', {'trade': '매매', 'kind': '잔금'})
        body = self.text()
        self.assertIn('■ 금액 세부사항', body)
        self.assertIn('(계좌번호)', body)
        self.pick('t14')
        body = self.text()
        self.assertIn('(요율)%', body)
        self.assertIn('(중개보수)', body)
        self.assertIn('(입금 계좌)', body)

    def test_first_greeting_keeps_owner_signature(self):
        # 1번도 공통 하단 서명을 그대로 붙인다 (2차 수정본)
        self.pick('t1')
        body = self.text()
        self.assertTrue(body.endswith('마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'), body)

    def test_only_sms_screen_exists(self):
        # 매물 찾기 · 진행 거래 탭은 없어졌다
        self.assertEqual(len(self.page.query_selector_all('#mode-tabs')), 0)
        self.assertIsNone(self.page.query_selector('#listings-view'))
        self.assertIsNone(self.page.query_selector('#deals-view'))
        self.assertTrue(self.page.is_visible('#sms-view'))
        self.assertTrue(self.page.is_visible('#tpl-list'))
        # 한 화면으로 돌아왔으니 문자가 바로 뜨다
        self.assertGreater(len(self.text()), 40)

    def test_list_shows_stage_counts(self):
        rows = self.page.query_selector_all('#tpl-list .row')
        self.assertGreaterEqual(len(rows), 17)
        self.page.click('[data-stage="3"]')
        self.wait(80)
        titles = [r.inner_text() for r in self.page.query_selector_all('#tpl-list .row')]
        self.assertTrue(any('계약 조건 안내' in t for t in titles))
        self.assertTrue(any('자금조달' in t for t in titles))
        self.assertFalse(any('주차 안내' in t for t in titles))
        self.assertEqual(len(titles), 4, '약정·계약은 4종')
        self.page.click('[data-stage="all"]')

    def test_search(self):
        self.page.fill('#search', '주차')
        self.wait(80)
        titles = [r.inner_text() for r in self.page.query_selector_all('#tpl-list .row')]
        self.assertTrue(any('주차' in t for t in titles))
        self.assertTrue(all(('주차' in t) or ('즐겨찾기' in t) for t in titles))
        self.page.fill('#search', '없는문자')
        self.wait(80)
        self.assertIn('해당하는 문자가 없어요', self.page.inner_text('#tpl-list'))

    def test_toggle_changes_text(self):
        self.pick('t10')
        self.assertIn('매매계약 일정', self.text())
        self.page.click('#fields [data-prop-trade="prop"][data-value="전세"]')
        self.wait(200)
        body = self.text()
        self.assertIn('임대차계약 일정', body)
        self.assertIn('확정일자 부여현황', body)
        self.assertNotIn('등기권리증', body)

        self.pick('t11')
        self.assertIn('매도인·매수인에게', self.text())
        self.page.click('#fields [data-seg="trade"][data-value="임대차"]')
        self.wait(80)
        self.assertIn('임대인·임차인에게', self.text())
        self.assertIn('확정일자 신청', self.text())

        self.pick('t12')
        self.assertIn('공동명의인 경우 명의자별로 각각 작성하시고', self.text())
        self.page.click('#fields [data-seg="owner"][data-value="단독"]')
        self.wait(80)
        self.assertNotIn('공동명의인 경우', self.text())
        self.assertIn('자금조달 항목별 금액과 출처', self.text())

    def test_reservation_status_switch(self):
        self.pick('t5')
        confirmed = self.text()
        self.assertIn('확정되었습니다', confirmed)
        self.page.click('#fields [data-seg="status"][data-value="pending"]')
        self.wait(80)
        pending = self.text()
        self.assertIn('조율 중입니다', pending)
        self.assertNotIn('확정되었습니다', pending)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-date="when"]')), 0)

    def test_property_input_and_exposure(self):
        self.pick('t7')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '1103')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '230000')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 208동 1103호 / 매매 23억', self.text())
        # 호 칸 배지 — 호 ↔ 층
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="ho"]'), '호')
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertIn('마포래미안푸르지오 208동 11층 / 매매 23억', self.text())
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="ho"]'), '층')
        # 동 칸 배지 — 동 ↔ 단지: 호수 칸·호 배지는 그대로 살아 있고 층·호수가 함께 나간다
        self.page.click('#fields [data-prop-unit="dong"]')
        self.wait(80)
        body = self.text()
        self.assertIn('마포래미안푸르지오 2단지 11층 / 매매 23억', body)
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="dong"]'), '단지')
        ho_inp = '#fields [data-prop="items"][data-idx="0"][data-key="ho"]'
        self.assertFalse(self.page.eval_on_selector(ho_inp, 'e => e.disabled'), '단지일 때도 호수 칸은 살아 있다')
        self.assertFalse(self.page.eval_on_selector('#fields [data-prop-unit="ho"]', 'e => e.disabled'))
        # 단지 상태에서 호 ↔ 층 배지도 그대로 돈다
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="ho"]'), '호')
        self.assertIn('마포래미안푸르지오 2단지 1103호 / 매매 23억', self.text())
        # 단지 상태에서 호수 칸을 직접 고칠 수 있고, 비우면 단지까지만 나간다
        self.page.fill(ho_inp, '1203')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 2단지 1203호 / 매매 23억', self.text())
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertIn('마포래미안푸르지오 2단지 12층 / 매매 23억', self.text())
        self.page.fill(ho_inp, '')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 2단지 / 매매 23억', self.text())
        self.assertNotIn('2단지 12층', self.text())
        self.page.fill(ho_inp, '1103')
        self.wait(120)
        # 다시 동으로 — 넣어 둔 호수는 그대로 남아 있다
        self.page.click('#fields [data-prop-unit="dong"]')
        self.wait(80)
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="dong"]'), '동')
        self.assertFalse(self.page.eval_on_selector(ho_inp, 'e => e.disabled'))
        self.assertEqual(self.page.input_value(ho_inp), '1103')
        self.assertIn('마포래미안푸르지오 208동 11층', self.text())
        # 호로 돌려 두면 호수 표기
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertIn('마포래미안푸르지오 208동 1103호', self.text())

    def test_exposure_row_buttons_removed(self):
        # 예전 아래줄의 '노출 [동·호수] [동·층] [단지]' 버튼 줄은 없다
        for tid in ('t7', 't3', 't2', 't8'):
            with self.subTest(tid=tid):
                self.pick(tid)
                self.assertEqual(len(self.page.query_selector_all('#fields .mode-wrap')), 0)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="mode"]')), 0)
                self.assertNotIn('노출', self.page.inner_text('#fields'))

    def test_property_badges_inline_layout(self):
        # 입력칸과 배지가 겹치지도, 줄이 깨지지도 않는다 (1440 · 1000 · 390)
        for w, h in ((1440, 900), (1000, 720), (390, 844)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                if w < 900:
                    page.click('#btn-sheet')
                    page.wait_for_timeout(150)
                    page.click('#sheet-list [data-id="t7"]')
                else:
                    page.click('#tpl-list [data-id="t7"]')
                page.wait_for_timeout(180)
                # 이모지 대신 숫자만 넣어 어느 폭에서도 글자가 잘리지 않게
                for i in range(2):
                    if i:
                        page.click('#fields [data-add-item="items"]')
                        page.wait_for_timeout(120)
                    page.fill(f'#fields [data-prop="items"][data-idx="{i}"][data-key="dong"]', '208')
                    page.fill(f'#fields [data-prop="items"][data-idx="{i}"][data-key="ho"]', '1103')
                page.wait_for_timeout(200)
                info = page.evaluate("""() => {
                  const panel = document.querySelector('.form-panel').getBoundingClientRect();
                  const rows = [...document.querySelectorAll('#fields .prop-top')].map(r => {
                    const rb = r.getBoundingClientRect();
                    const tiles = [...r.querySelectorAll('.unit-field')].map(u => {
                      const i = u.querySelector('.inp'), t = u.querySelector('.unit-toggle');
                      const ib = i.getBoundingClientRect(), tb = t.getBoundingClientRect();
                      return { inside: tb.left >= ib.left - 0.5 && tb.right <= ib.right + 0.5,
                               noOverlap: +getComputedStyle(i).paddingRight.replace('px','') >= +tb.width.toFixed(1),
                               sameRow: Math.abs((tb.top + tb.bottom) / 2 - (ib.top + ib.bottom) / 2) <= 1.5,
                               w: ib.width };
                    });
                    return { right: rb.right, h: rb.height, top: rb.top, tiles,
                             wraps: [...r.children].some(c => c.getBoundingClientRect().top > rb.top + 4) };
                  });
                  return { panelRight: panel.right, panelLeft: panel.left, rows,
                           scrollW: document.documentElement.scrollWidth, winW: window.innerWidth };
                }""")
                self.assertLessEqual(info['scrollW'], info['winW'], '가로 넘침이 없어야 한다')
                self.assertEqual(len(info['rows']), 2)
                heights = {round(r['h'], 1) for r in info['rows']}
                self.assertEqual(len(heights), 1, '매물 줄 높이가 같아야 한다(줄바꿈 없음)')
                for r in info['rows']:
                    self.assertLessEqual(r['right'], info['panelRight'] + 0.5, '줄이 패널 밖으로 나가면 안 된다')
                    self.assertEqual(len(r['tiles']), 2)
                    for t in r['tiles']:
                        self.assertTrue(t['inside'], '배지가 입력칸 안에 있어야 한다')
                        self.assertTrue(t['noOverlap'], '입력 글자 자리와 배지가 겹치면 안 된다')
                        self.assertTrue(t['sameRow'], '배지가 입력칸과 같은 높이에 있어야 한다')
                        self.assertGreaterEqual(t['w'], 55, '동·호 칸이 너무 좁다')
                self.assertEqual(errors, [])
                ctx.close()

    def test_property_trade_pills_and_price(self):
        self.pick('t7')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '208')
        amount = '#fields [data-prop="items"][data-idx="0"][data-money="amount"]'
        self.page.fill(amount, '230000')
        self.wait(120)
        self.assertEqual(self.page.input_value(amount), '230,000')
        self.assertIn('(23억)', self.page.inner_text('#fields'))
        self.assertIn('마포래미안푸르지오 208동 208호 / 매매 23억', self.text())

        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="전세"]')
        self.wait(120)
        self.assertIn('/ 전세 23억', self.text())
        self.page.fill(amount, '115000')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 208동 208호 / 전세 11억 5천만', self.text())

        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
        self.wait(120)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-money="amount"]')), 0)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '300')
        self.wait(150)
        body = self.text()
        self.assertIn('마포래미안푸르지오 208동 208호 / 보증금 1억 / 월세 300만 원', body)

    def test_legacy_price_migrated_on_load(self):
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't7', 'stage': 'all',
            'data': {'t7': {'mode': 'ho', 'items': [
                {'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'price': '매매 23억'}]}}
        })
        self.assertIn('마포래미안푸르지오 208동 208호 / 매매 23억', page.input_value('#preview'))
        self.assertEqual(page.input_value('#fields [data-money="amount"]'), '230,000')
        ctx.close()

    def test_t3_legacy_version_migrated(self):
        # 통합 전 저장값(ver: simple/detail)은 새 화면의 간단·상세로 이어진다
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't3', 'stage': 'all',
            'data': {'t3': {'mode': 'ho', 'ver': 'detail', 'times': '12월 5일 (토) 10:00',
                            'prop': {'complex': '마포래미안푸르지오', 'dong': '304', 'ho': '1103',
                                     'trade': '전세', 'amount': '115000'}}}
        })
        body = page.input_value('#preview')
        self.assertIn('전세 손님께서 집보기를 희망하셔서', body)
        self.assertIn('- 마포래미안푸르지오 304동 1103호 / 전세 11억 5천만', body)
        self.assertEqual(page.inner_text('#fields [data-seg="view"][data-value="detail"]').strip(), '상세')
        ctx.close()

    def test_legacy_exposure_mode_migrated_to_badges(self):
        # 예전 한 줄짜리 노출 설정도 매물 줄의 배지 상태로 옮겨서 보여 준다
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't7', 'stage': 'all',
            'data': {'t7': {'mode': 'floor', 'items': [
                {'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103'}]}}
        })
        self.assertIn('마포래미안푸르지오 208동 11층', page.input_value('#preview'))
        self.assertEqual(page.inner_text('#fields [data-prop-unit="ho"]'), '층')
        self.assertEqual(page.inner_text('#fields [data-prop-unit="dong"]'), '동')
        ctx.close()

        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't7', 'stage': 'all',
            'data': {'t7': {'mode': 'complex', 'items': [
                {'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103'}]}}
        })
        self.assertIn('마포래미안푸르지오 2단지 1103호', page.input_value('#preview'))
        self.assertEqual(page.inner_text('#fields [data-prop-unit="dong"]'), '단지')
        self.assertFalse(page.eval_on_selector('#fields [data-key="ho"]', 'e => e.disabled'),
                         '단지일 때도 호수 칸은 고칠 수 있다')
        self.assertFalse(page.eval_on_selector('#fields [data-prop-unit="ho"]', 'e => e.disabled'))
        ctx.close()

    def test_header_and_panel_alignment(self):
        # 상단 바 좌우 끝선 = 3단 패널 좌우 끝선, 패널 안쪽은 한 줄로 정렬
        for w, h in ((1440, 900), (1000, 720), (390, 844)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                if w < 900:
                    page.click('#btn-sheet')
                    page.wait_for_timeout(150)
                    page.click('#sheet-list [data-id="t7"]')
                else:
                    page.click('#tpl-list [data-id="t7"]')
                page.wait_for_timeout(220)
                info = page.evaluate("""() => {
                  const box = s => { const e = document.querySelector(s);
                    if (e) { const r = e.getBoundingClientRect(); if (r.width || r.height) return {l:+r.left.toFixed(1), r:+r.right.toFixed(1), t:+r.top.toFixed(1)}; }
                    return null; };
                  const innerBox = s => { const e = document.querySelector(s); if (!e) return null;
                    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
                    return {l:+(r.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft)).toFixed(1),
                            r:+(r.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight)).toFixed(1)}; };
                  return {win: window.innerWidth,
                          brand: box('.brand'), actions: box('.top-actions'),
                          listPanel: box('#list-panel'), formPanel: box('.form-panel'), previewPanel: box('.preview-panel'),
                          formInner: innerBox('.form-panel'), previewInner: innerBox('.preview-panel'), listInner: innerBox('#list-panel'),
                          title: box('#form-title'), label: box('#fields .field-label'),
                          firstInput: box('#fields .inp'), addBtn: box('#fields .add-btn'), toggleBox: box('#fields .is-toggle'),
                          previewTitle: box('.preview-panel .card-title'),
                          preview: box('#preview'), foot: box('.preview-foot'), copy: box('#btn-copy'),
                          charCount: box('#char-count'),
                          search: box('#search'), head: box('#tpl-list .list-head'),
                          rowTitle: box('#tpl-list .row-title'), mobileBar: box('#sms-mobile-bar'),
                          mobileInner: innerBox('#sms-mobile-bar'),
                          scrollW: document.documentElement.scrollWidth};
                }""")
                self.assertLessEqual(info['scrollW'], info['win'], '가로 넘침이 없어야 한다')
                # 1) 상단 바 끝선 = 패널 끝선
                first_panel = info['listPanel'] if info['search'] else info['formPanel']
                self.assertAlmostEqual(info['brand']['l'], first_panel['l'], delta=1.0,
                                       msg='제목 줄 왼쪽 끝 = 첫 패널 왼쪽 끝')
                self.assertAlmostEqual(info['actions']['r'], info['previewPanel']['r'], delta=1.0,
                                       msg='오른쪽 버튼 끝 = 미리보기 패널 오른쪽 끝')
                if info['listPanel'] and info['search']:
                    self.assertAlmostEqual(info['brand']['l'], info['listPanel']['l'], delta=1.0)
                # 2) 입력 패널 안쪽 — 제목·라벨·입력칸·추가 버튼이 같은 선
                base = info['formInner']['l']
                for key in ('title', 'label', 'firstInput', 'addBtn'):
                    self.assertAlmostEqual(info[key]['l'], base, delta=1.0, msg=f'{key} 가 패널 내용선과 어긋난다')
                # 3) 미리보기 패널 — 머리글·글상자·하단 바 끝선
                self.assertAlmostEqual(info['previewTitle']['l'], info['previewInner']['l'], delta=1.0)
                self.assertAlmostEqual(info['preview']['l'], info['previewInner']['l'], delta=1.0)
                self.assertAlmostEqual(info['preview']['r'], info['previewInner']['r'], delta=1.0)
                self.assertAlmostEqual(info['foot']['l'], info['previewInner']['l'], delta=1.0)
                if info['copy']:
                    self.assertAlmostEqual(info['copy']['r'], info['previewInner']['r'], delta=1.0)
                else:
                    # 폰에서는 카드 안 복사 버튼을 숨기고 글자수만 오른쪽 끝선에 맞춘다
                    self.assertIsNotNone(info['charCount'], '폰에서 글자수가 보여야 한다')
                    self.assertAlmostEqual(info['charCount']['r'], info['previewInner']['r'], delta=1.0)
                # 4) 목록 패널 — 검색칸·머리글이 같은 선, 줄 제목은 아이콘만큼만 들여쓰기
                if info['search']:
                    lbase = info['listInner']['l']
                    for key in ('search', 'head'):
                        self.assertAlmostEqual(info[key]['l'], lbase, delta=1.0, msg=f'{key} 가 목록 내용선과 어긋난다')
                    self.assertGreater(info['rowTitle']['l'], lbase, '줄 제목은 아이콘 뒤에서 시작한다')
                    self.assertLessEqual(info['rowTitle']['l'] - lbase, 58, '줄 제목 들여쓰기가 과하지 않다(아이콘+번호)')
                # 5) 모바일 하단 바도 같은 끝선 (바 자체는 화면 폭, 안쪽 버튼이 패널 끝선)
                if info['mobileInner'] and info['mobileBar']:
                    self.assertAlmostEqual(info['mobileInner']['l'], info['formPanel']['l'], delta=1.0)
                    self.assertAlmostEqual(info['mobileInner']['r'], info['formPanel']['r'], delta=1.0)
                ctx.close()

    def test_add_and_remove_property_rows(self):
        self.pick('t7')
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '1103')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '230000')
        self.page.click('#fields [data-add-item="items"]')
        self.wait(80)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 2)
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-key="dong"]', '304')
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-key="ho"]', '201')
        self.page.click('#fields [data-prop-trade="items"][data-idx="1"][data-value="전세"]')
        self.wait(80)
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-money="amount"]', '90000')
        self.wait(100)
        body = self.text()
        self.assertIn('/ 매매 23억', body)
        self.assertIn('/ 전세 9억', body)
        # × 대신 늘 보이는 ☑ — 체크한 매물만 「- 선택 제거」로 한 번에 뺀다
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item .icon-btn')), 0, '카드 안 × 버튼은 없다')
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-check')), 2, '매물마다 ☑가 보인다')
        self.page.click('#fields [data-pick-remove="items"]')
        self.wait(80)
        self.assertIn('제거할 매물을 체크해 주세요', self.page.inner_text('#toast'))
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 2)
        self.page.click('#fields [data-prop-pick="items"][data-idx="1"]')
        self.wait(80)
        self.page.click('#fields [data-pick-remove="items"]')
        self.wait(100)
        self.assertNotIn('/ 전세 9억', self.text())
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)

    def test_money_input_formats_and_hint(self):
        self.pick('t2')
        box = self.page.query_selector('#fields [data-money="amount"]')
        box.click()
        box.type('237000')
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-money="amount"]'), '237,000')
        self.assertIn('(23억 7천만)', self.page.inner_text('#fields'))
        self.assertIn('- 거래조건 : 매매 23억 7천만', self.text())


    def test_t8_percent_sets_amount(self):
        # 지급 일정 % 칸 — 매매가 대비 비율로 그 차수 금액을 채우고, 금액을 적으면 %가 따라온다
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '76000')
        self.pay_rate('gyeyak', 10)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]'), '7,600')
        self.pay_fill('jung', 19000)
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="jung"][data-pay-idx="0"]'), '25')
        # 잔금은 저절로 — 76,000 − 7,600 − 19,000
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '49,400')
        body = self.text()
        self.assertIn('- 매매대금 : 760,000,000원 (7억 6천만 원)', body)
        self.assertIn('- 계약금 10% : 76,000,000원 (7,600만 원)', body)
        self.assertIn('- 중도금 25% : 190,000,000원 (1억 9천만 원)', body)
        self.assertIn('- 잔금 : 494,000,000원 (4억 9,400만 원)', body)
        # 매매가를 바꾸면 잔금이 다시 계산된다
        self.page.fill('#fields [data-field="price"]', '80000')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '53,400')

    def test_calendar_pick_date_and_time(self):
        self.pick_with('t10', {'trade': '매매', 'kind': '약정'})
        self.page.click('#fields [data-date="when"]')
        self.wait(100)
        self.assertTrue(self.page.is_visible('#calpop'))
        self.page.click('#calpop [data-cal-nav="1"]')
        self.wait(80)
        self.page.click('#calpop [data-cal-day="5"]')
        self.wait(120)
        self.assertIn('2026년 12월 5일 토요일', self.text())
        self.pick_time('#calpop', None, '10', '30')
        self.assertIn('2026년 12월 5일 토요일 10:30', self.text())
        self.page.click('#calpop [data-cal-close]')
        self.assertFalse(self.page.is_visible('#calpop'))

    def test_clear_date_icon(self):
        self.pick_with('t10', {'trade': '매매', 'kind': '가계약'})
        self.assertIn('(가계약 일시)', self.text())
        self.page.click('#fields [data-date="when"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-day="20"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-close]')
        self.assertIn('2026년 11월 20일 금요일', self.text())
        self.page.click('#fields .date-clear')
        self.wait(120)
        self.assertIn('(가계약 일시)', self.text())
        self.assertFalse(self.page.is_visible('#calpop'))

    def test_no_today_tomorrow_chips(self):
        for tid in ('t5', 't8', 't10', 't2'):
            with self.subTest(tid=tid):
                self.pick(tid)
                body = self.page.inner_text('#fields')
                self.assertNotIn('오늘', body)
                self.assertNotIn('내일', body)

    def test_independent_template_state(self):
        self.pick('t2')
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '402')
        self.wait(100)
        self.assertIn('402동', self.text())
        self.pick('t5')
        self.assertNotIn('402동', self.text())
        self.pick('t2')
        self.assertIn('402동', self.text())

    def test_reset_button(self):
        self.pick('t2')
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '402')
        self.page.fill('#fields [data-prop="prop"][data-key="ho"]', '1201')
        self.page.fill('#fields [data-prop="prop"][data-money="amount"]', '23억')
        self.wait(100)
        self.page.click('#btn-reset')
        self.wait(120)
        self.assertIn('(금액)', self.text())
        self.assertEqual(self.page.input_value('#fields [data-prop="prop"][data-key="dong"]'), '')

    def test_state_saved_across_reload(self):
        self.pick('t2')
        self.page.fill('#fields [data-prop="prop"][data-key="ho"]', '1201')
        self.page.fill('#fields [data-prop="prop"][data-money="amount"]', '23억')
        self.wait(400)
        self.page.reload(wait_until='networkidle')
        self.wait(200)
        self.assertEqual(self.page.inner_text('#form-title'), '매물 접수 확인')
        self.assertIn('1201호', self.text())

    def test_edit_preview_and_restore(self):
        self.pick('t1')
        original = self.text()
        self.page.fill('#preview', original + '\n추가로 남길 말')
        self.wait(150)
        self.assertIn('추가로 남길 말', self.page.input_value('#preview'))
        self.assertFalse(self.page.is_disabled('#btn-restore'))
        self.page.click('#btn-restore')
        self.wait(120)
        self.assertNotIn('추가로 남길 말', self.text())

    def test_edited_body_notice_when_inputs_change(self):
        self.pick('t2')
        self.page.fill('#preview', '직접 고친 본문')
        self.wait(150)
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '402')
        self.wait(200)
        self.assertIn('입력값이 바뀌었어요', self.page.inner_text('#edited-note'))
        self.assertEqual(self.page.input_value('#preview'), '직접 고친 본문')
        self.page.click('#btn-refresh')
        self.wait(150)
        self.assertIn('402동', self.text())
        self.assertTrue(self.page.is_hidden('#edited-note'))

    def test_copy_to_clipboard(self):
        self.pick('t6')
        self.page.click('#btn-copy')
        self.wait(200)
        clip = self.page.evaluate('navigator.clipboard.readText()')
        self.assertIn('아현장로교회', clip)
        self.assertIn('010-4585-7365', clip)

    def test_settings_change_office(self):
        self.pick('t1')
        self.page.click('#btn-settings')
        self.wait(120)
        self.page.fill('#set-office', '마래푸공인중개사')
        self.page.fill('#set-phones', '010-1111-2222')
        self.page.click('#btn-settings-save')
        self.wait(150)
        body = self.text()
        self.assertIn('마래푸공인중개사입니다', body)
        self.assertIn('010-1111-2222', body)
        self.pick('t6')
        self.assertIn('마래푸공인중개사 드림', self.text())

    def test_fee_sms_account_spaced(self):
        # 내 정보 설정에 넣은 계좌는 띄어 써도 '은행 + 계좌 + 예금주' 모양으로 정리돼 문자에 들어간다
        # (개인 계좌는 코드에 넣지 않으므로 화면에서 한 번 넣어 둔다)
        self.pick('t14')
        self.page.click('#btn-settings')
        self.wait(100)
        self.page.fill('#set-account', '우리 1002-762-106047 황호선')
        self.page.click('#btn-settings-save')
        self.wait(150)
        body = self.text()
        self.assertIn('- 입금계좌 : 우리은행 1002-762-106047 황호선', body)
        line = [l for l in body.split('\n') if '우리은행' in l][0]
        self.assertEqual(line, '- 입금계좌 : 우리은행 1002-762-106047 황호선')

    def test_money_input_spider_style(self):
        # 매물 스파이더식 — 숫자는 왼쪽, '만원'은 칸 안 오른쪽, 아래 줄에 원단위·억 환산
        self.pick('t14')
        self.page.fill('#fields [data-field="calcAmount"]', '230000')
        self.wait(200)
        info = self.money_info('#fields [data-field="calcAmount"]')
        self.assertEqual(info['value'], '230,000')
        self.assertEqual(info['align'], 'left', '금액 숫자는 왼쪽 정렬')
        self.assertEqual(info['unit'], '만원', "단위는 '만원'(칸 안)")
        self.assertTrue(info['unitInside'], "'만원'이 입력칸 안쪽 오른쪽 끝에 있어야 한다")
        self.assertTrue(info['sameRow'], "'만원'이 숫자와 같은 높이에 있어야 한다")
        self.assertGreaterEqual(info['padRight'], info['unitRect']['r'] - info['unitRect']['l'] + 4,
                                '단위 자리만큼 오른쪽 여백을 띄워야 한다')
        self.assertTrue(info['textFits'], '오른쪽 여백을 먹고 숫자가 잘리면 안 된다')
        self.assertEqual(info['hint'], '2,300,000,000원 (23억)')
        self.assertTrue(info['hintBelow'], '환산 줄은 입력칸 바로 아래')
        self.assertEqual(info['hintLeft'], 0, '환산 줄은 입력칸 왼쪽 끝에 맞춘다')
        self.assertFalse(info['hintClipped'], '환산 줄이 잘리면 안 된다')

        # 입력칸 바깥에 '만원'·'(23억)' 글자가 따로 남아 있지 않다
        self.assertEqual(self.page.evaluate("""() => {
          const f = document.querySelector('#fields [data-field=\"calcAmount\"]').closest('.field');
          return [...f.querySelectorAll('.field-hint, .pay-hint')].map(e => e.textContent.trim());
        }"""), [], '입력칸 옆 만원·(23억) 도우미는 없어야 한다')

    def test_money_empty_hint_keeps_layout(self):
        # 비어 있을 때도 환산 줄 자리를 잡아 두어 레이아웃이 들썩이지 않는다
        self.pick('t14')
        before = self.js("""() => {
          const i = document.querySelector('#fields [data-field=\"calcAmount\"]');
          return {top: i.getBoundingClientRect().top,
                  hintH: i.closest('.money-field').querySelector('.money-hint').getBoundingClientRect().height};
        }""")
        self.assertEqual(self.money_info('#fields [data-field="calcAmount"]')['hint'], '')
        self.page.fill('#fields [data-field="calcAmount"]', '230000')
        self.wait(150)
        after = self.js("""() => {
          const i = document.querySelector('#fields [data-field=\"calcAmount\"]');
          return {top: i.getBoundingClientRect().top,
                  hintH: i.closest('.money-field').querySelector('.money-hint').getBoundingClientRect().height};
        }""")
        self.assertAlmostEqual(before['hintH'], after['hintH'], delta=0.5, msg='환산 줄 높이가 바뀌면 안 된다')
        self.assertAlmostEqual(before['top'], after['top'], delta=0.5, msg='금액을 친다고 입력칸이 움직이면 안 된다')
        self.assertEqual(self.money_info('#fields [data-field="calcAmount"]')['hint'],
                         '2,300,000,000원 (23억)')

    def test_property_amount_hint_under_input(self):
        self.pick('t7')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '230000')
        self.wait(150)
        info = self.money_info('#fields [data-prop="items"][data-idx="0"][data-money="amount"]')
        self.assertEqual(info['align'], 'left')
        self.assertEqual(info['unit'], '만원')
        self.assertTrue(info['unitInside'])
        self.assertTrue(info['textFits'])
        self.assertEqual(info['hint'], '2,300,000,000원 (23억)')
        self.assertTrue(info['hintBelow'])
        self.assertEqual(info['hintLeft'], 0)
        self.assertFalse(info['hintClipped'])

    def test_property_monthly_two_columns_with_hints(self):
        # 월세는 보증금·월세 두 칸이 나란히, 각 칸 아래에 자기 환산 줄
        self.pick('t7')
        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
        self.wait(120)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '300')
        self.wait(150)
        dep = self.money_info('#fields [data-money="deposit"]')
        rent = self.money_info('#fields [data-money="rent"]')
        self.assertEqual(dep['hint'], '100,000,000원 (1억)')
        self.assertEqual(rent['hint'], '3,000,000원 (300만)')
        self.assertGreater(rent['inputRect']['l'], dep['inputRect']['r'] - 1, '두 칸은 나란히')
        for info in (dep, rent):
            self.assertTrue(info['hintBelow'])
            self.assertEqual(info['hintLeft'], 0)
            self.assertFalse(info['hintClipped'])
            self.assertTrue(info['unitInside'])
            self.assertEqual(info['align'], 'left')
        # 칸 위에 보증금·월세 이름
        labels = self.js("""() => [...document.querySelectorAll('#fields .money-caps .money-cap')].map(e => e.textContent.trim())""")
        self.assertEqual(labels, ['보증금', '월세'])

    def test_monthly_two_columns_in_all_property_blocks(self):
        # 매물 블록을 쓰는 문자 모두 월세를 고르면 보증금·월차임 두 칸 + 각자 환산 줄
        blocks = [('t2', 'prop'), ('t3', 'prop'), ('t7', 'items'), ('t19', 'items')]
        for tid, key in blocks:
            with self.subTest(tid=tid):
                self.pick(tid)
                base = '#fields [data-prop="%s"]' % key
                if key == 'items':
                    base += '[data-idx="0"]'
                self.page.fill(base + '[data-key="dong"]', '208')
                self.page.fill(base + '[data-key="ho"]', '1103')
                trade = '#fields [data-prop-trade="%s"]' % key + ('[data-idx="0"]' if key == 'items' else '')
                self.page.click(trade + '[data-value="월세"]')
                self.wait(150)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-money="deposit"]')), 1)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-money="rent"]')), 1)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-money="amount"]')), 0)
                labels = self.js("""() => [...document.querySelectorAll('#fields .money-caps .money-cap')].map(e => e.textContent.trim())""")
                self.assertEqual(labels, ['보증금', '월세'])
                self.page.fill('#fields [data-money="deposit"]', '10000')
                self.page.fill('#fields [data-money="rent"]', '350')
                self.wait(180)
                self.assertEqual(self.money_info('#fields [data-money="deposit"]')['hint'], '100,000,000원 (1억)')
                self.assertEqual(self.money_info('#fields [data-money="rent"]')['hint'], '3,500,000원 (350만)')
                self.assertIn('보증금 1억 / 월세 350만 원', self.text())
                # 매매로 되돌리면 한 칸으로 돌아온다
                self.page.click(trade + '[data-value="매매"]')
                self.wait(150)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-money="amount"]')), 1)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-money="deposit"]')), 0)

    def test_t2_property_block_and_trade(self):
        # 매물 접수 확인 — 추천 매물 안내와 같은 매물 블록 하나로 거래조건까지 적는다
        self.pick('t2')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="price"]')), 0,
                         '따로 떨어진 금액 칸은 없다')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="trade"]')), 0,
                         '따로 떨어진 거래 유형도 없다')
        for key in ('complex', 'dong', 'ho'):
            self.assertEqual(len(self.page.query_selector_all(f'#fields [data-prop="prop"][data-key="{key}"]')), 1)
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '208')
        self.page.fill('#fields [data-prop="prop"][data-key="ho"]', '1103')
        self.page.fill('#fields [data-prop="prop"][data-money="amount"]', '230000')
        self.wait(180)
        body = self.text()
        self.assertIn('- 마포래미안푸르지오 208동 1103호', body)
        self.assertIn('- 거래조건 : 매매 23억', body)
        # 월세는 보증금·월차임이 한 줄로 조합된다
        self.page.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        self.wait(150)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '350')
        self.wait(180)
        self.assertIn('- 거래조건 : 보증금 1억 / 월세 350만 원', self.text())

    def test_movein_date_modes(self):
        # 입주일 — 협의(즉시입주) · 고정(시작일 + 고정/선호) · 기간(시작~종료) 세 갈래 (t2 · t18)
        for tid in ('t2', 't18'):
            with self.subTest(tid=tid):
                self.pick(tid)
                # 선택과 상관없이 [시작일] ~ [종료일] 두 칸이 늘 같은 자리에 보인다
                self.assertEqual(self.js("""() => [...document.querySelectorAll('#fields .date-range .date-btn')]
                    .map(b => b.dataset.date)"""), ['moveinStart', 'moveinEnd'])
                # 협의 — 입력칸 없이 문자에 '즉시입주(협의)'로 나간다
                self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
                self.wait(150)
                self.assertEqual(self.js("() => document.querySelectorAll('#fields .inp-date-free').length"), 0,
                                 '협의에 글자 입력칸은 없다')
                self.assertTrue(self.js("() => document.querySelector('#fields [data-date=\"moveinStart\"]').disabled"))
                self.assertRegex(self.text(), r'입주\s*:?\s*즉시입주\(협의\)')
                # 고정 — 시작일에서 날짜를 고르고 달력 아래에서 고정/선호
                self.page.click('#fields [data-date-mode="movein"][data-value="고정"]')
                self.wait(150)
                self.page.click('#fields [data-date="moveinStart"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-day="26"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-fix="선호"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                body = self.text()
                self.assertRegex(body, r'입주\s*:?\s*26\.11\.26 \(목\) 선호')
                self.assertNotIn('즉시입주', body)
                self.page.click('#fields [data-date="moveinStart"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-fix="고정"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                self.assertRegex(self.text(), r'입주\s*:?\s*26\.11\.26 \(목\) 고정')
                # 기간 — 시작일 ~ 종료일
                self.page.click('#fields [data-date-mode="movein"][data-value="기간"]')
                self.wait(150)
                self.page.click('#fields [data-date="moveinStart"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-nav="1"]')
                self.wait(120)
                self.page.click('#calpop [data-cal-day="1"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                self.page.click('#fields [data-date="moveinEnd"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-nav="1"]')
                self.wait(120)
                self.page.click('#calpop [data-cal-day="31"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                body = self.text()
                self.assertRegex(body, r'입주\s*:?\s*26\.12\.01 \(화\) ~ 26\.12\.31 \(목\)')

    def test_all_money_fields_spider_style(self):
        # 만원 단위 금액칸이 있는 문자 전부 — 왼쪽 정렬 · 안쪽 '만원' · 아래 환산 줄
        money_placeholders = ('t2', 't3', 't5', 't6', 't7', 't8', 't10', 't11', 't12', 't14')
        seen = 0
        for tid in money_placeholders:
            with self.subTest(tid=tid):
                self.pick(tid)
                boxes = self.page.evaluate("""() => [...document.querySelectorAll('#fields .money-box')]
                    .filter(b => !b.querySelector('.inp-won')).length""")
                if not boxes:
                    continue
                seen += boxes
                report = self.js("""() => [...document.querySelectorAll('#fields .money-box')]
                  .filter(b => !b.querySelector('.inp-won')).map(box => {
                  const inp = box.querySelector('input'), unit = box.querySelector('.money-unit');
                  const field = box.closest('.money-field');
                  const hint = field.querySelector('.money-hint') ||
                    (box.closest('.pay-right') && box.closest('.pay-right').querySelector('.money-hint'));
                  const ir = inp.getBoundingClientRect(), ur = unit.getBoundingClientRect(), hr = hint.getBoundingClientRect();
                  const hs = getComputedStyle(hint);
                  return {unit: unit.textContent.trim(), align: getComputedStyle(inp).textAlign,
                          inside: ur.left >= ir.left + 1 && ur.right <= ir.right - 1,
                          below: hr.top >= ir.bottom - 0.5,
                          left: +(hr.left - ir.left).toFixed(1),
                          minH: parseFloat(hs.minHeight || '0'),
                          hintH: +hr.height.toFixed(1),
                          inTable: !!box.closest('.paytable'),
                          clipped: hint.scrollWidth > hint.clientWidth + 1,
                          wrapInside: hint.querySelectorAll('.hint-ko').length === 1};
                })""")
                for r in report:
                    self.assertEqual(r['align'], 'left', f'{tid} 금액칸 왼쪽 정렬')
                    self.assertEqual(r['unit'], '만원', f'{tid} 칸 안 단위')
                    self.assertTrue(r['inside'], f'{tid} 만원이 칸 안에 있어야 한다')
                    self.assertTrue(r['below'], f'{tid} 환산 줄은 칸 아래')
                    self.assertGreater(r['minH'], 0, f'{tid} 빈 환산 줄도 자리를 잡아 둔다')
                    if r['inTable']:
                        # 지급 일정 표는 오른쪽 칸 전체 폭 아래에 원단위 줄이 붙는다
                        self.assertLessEqual(r['hintH'], r['minH'] * 2 + 2, f'{tid} 환산 줄은 두 줄까지')
                        self.assertLess(r['left'], 1, f'{tid} 환산 줄은 일정·금액 줄 아래')
                    else:
                        self.assertEqual(r['left'], 0, f'{tid} 환산 줄 왼쪽 정렬')
                        self.assertLessEqual(r['hintH'], r['minH'] + 0.5, f'{tid} 빈 줄과 찬 줄 높이가 같아야 한다')
                    self.assertFalse(r['clipped'], f'{tid} 환산 줄이 잘리면 안 된다')
        self.assertGreaterEqual(seen, 12, '금액칸을 한 번에 점검한다')

    def test_money_layout_three_viewports(self):
        # PC 1440×900 · 1000×720 · 모바일 390×844 — 겹침·가로 넘침·잘림 없음
        for w, h in ((1440, 900), (1000, 720), (390, 844)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(220)
                if w < 900:
                    page.click('#btn-sheet')
                    page.wait_for_timeout(150)
                    page.click('#sheet-list [data-id="t7"]')
                else:
                    page.click('#tpl-list [data-id="t7"]')
                page.wait_for_timeout(220)
                page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '230000')
                page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
                page.wait_for_timeout(180)
                page.fill('#fields [data-money="deposit"]', '10000')
                page.fill('#fields [data-money="rent"]', '300')
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.wait_for_timeout(220)
                info = page.evaluate("""() => {
                  const boxes = [...document.querySelectorAll('#fields .money-box')].map(box => {
                    const inp = box.querySelector('input'), unit = box.querySelector('.money-unit');
                    const field = box.closest('.money-field'), hint = field.querySelector('.money-hint');
                    const ir = inp.getBoundingClientRect(), ur = unit.getBoundingClientRect(), hr = hint.getBoundingClientRect();
                    return {align: getComputedStyle(inp).textAlign, unit: unit.textContent.trim(),
                            inside: ur.left >= ir.left + 1 && ur.right <= ir.right - 1,
                            sameRow: ur.top >= ir.top - 0.5 && ur.bottom <= ir.bottom + 0.5,
                            hintBelow: hr.top >= ir.bottom - 0.5,
                            hintLeft: +(hr.left - ir.left).toFixed(1),
                            hint: hint.textContent,
                            clipped: hint.scrollWidth > hint.clientWidth + 1,
                            hintInPanel: hr.right <= document.querySelector('.form-panel').getBoundingClientRect().right + 0.5,
                            overlapUnit: inp.scrollWidth > inp.clientWidth + 1};
                  });
                  const d = document.querySelector('#fields [data-money=\"deposit\"]').getBoundingClientRect();
                  const r = document.querySelector('#fields [data-money=\"rent\"]').getBoundingClientRect();
                  return {boxes, sideBySide: r.left > d.right - 1,
                          scrollW: document.documentElement.scrollWidth, win: window.innerWidth};
                }""")
                self.assertLessEqual(info['scrollW'], info['win'], f'{w} 가로 넘침')
                self.assertTrue(info['sideBySide'], f'{w} 보증금·월세 두 칸이 나란히')
                hints = [b['hint'] for b in info['boxes']]
                self.assertEqual(hints, ['100,000,000원 (1억)', '3,000,000원 (300만)'])
                for b in info['boxes']:
                    self.assertEqual(b['align'], 'left')
                    self.assertEqual(b['unit'], '만원')
                    self.assertTrue(b['inside'], f'{w} 만원이 칸 안')
                    self.assertTrue(b['sameRow'])
                    self.assertTrue(b['hintBelow'])
                    self.assertEqual(b['hintLeft'], 0)
                    self.assertFalse(b['clipped'], f'{w} 환산 줄 잘림')
                    self.assertTrue(b['hintInPanel'], f'{w} 환산 줄이 패널 밖으로')
                    self.assertFalse(b['overlapUnit'], f'{w} 숫자가 만원과 겹침')
                self.assertEqual(errors, [])
                ctx.close()

    # ------------------------------------------- 거래유형 · 금액 한 줄 (v1.1.7)
    # 매물 블록 하나를 통째로 잰다 — 버튼 · 금액칸 · 보증금/월세 이름 · 환산 줄
    PROP_ROW_JS = """() => {
      const pm = document.querySelector('#fields .prop-money');
      if (!pm) return null;
      const panel = document.querySelector('.form-panel').getBoundingClientRect();
      const pmr = pm.getBoundingClientRect();
      const seg = pm.querySelector('.seg.is-trade');
      const sr = seg.getBoundingClientRect();
      const pair = pm.querySelector('.money-pair');
      const one = b => {
        const i = b.querySelector('input'), u = b.querySelector('.money-unit');
        const f = b.closest('.money-field'), hint = f.querySelector('.money-hint');
        const ir = i.getBoundingClientRect(), ur = u.getBoundingClientRect(), hr = hint.getBoundingClientRect();
        const cs = getComputedStyle(i);
        return {key: i.dataset.money, value: i.value, font: parseFloat(cs.fontSize),
                l: ir.left, r: ir.right, w: ir.width, t: ir.top, b: ir.bottom,
                cy: (ir.top + ir.bottom) / 2,
                textFits: i.scrollWidth <= i.clientWidth + 1 && i.scrollLeft === 0,
                unitInside: ur.left >= ir.left + 1 && ur.right <= ir.right - 1,
                unitClear: ur.left >= ir.left + parseFloat(cs.paddingLeft) + 2,
                hint: hint.textContent, hintClipped: hint.scrollWidth > hint.clientWidth + 1,
                hintBelow: hr.top >= ir.bottom - 0.5, hintLeft: +(hr.left - ir.left).toFixed(1),
                inPanel: ir.right <= panel.right + 0.5 && ir.left >= panel.left - 0.5 &&
                         hr.right <= panel.right + 0.5};
      };
      return {segL: sr.left, segR: sr.right, segT: sr.top, segB: sr.bottom,
              segCy: (sr.top + sr.bottom) / 2,
              boxes: [...pm.querySelectorAll('.money-box')].map(one),
              labels: [...pm.querySelectorAll('.money-caps .money-cap')].map(e => e.textContent.trim()),
              pairCols: pair ? getComputedStyle(pair).gridTemplateColumns.split(' ').map(parseFloat) : null,
              pmL: pmr.left, pmR: pmr.right,
              scrollW: document.documentElement.scrollWidth, win: window.innerWidth};
    }"""

    def prop_row(self):
        return self.js(self.PROP_ROW_JS)

    def assert_prop_money_one_row(self, info, tag=''):
        # 거래유형 버튼과 금액칸이 같은 가로 줄에, 금액칸은 남는 폭을 다 쓴다
        self.assertTrue(info['boxes'], f'{tag}: 금액칸이 없다')
        self.assertAlmostEqual(info['segL'], info['pmL'], delta=1.0, msg=f'{tag}: 버튼은 왼쪽 끝')
        for b in info['boxes']:
            self.assertGreaterEqual(b['l'], info['segR'] - 0.5, f'{tag}: 금액칸은 버튼 오른쪽')
            overlap = min(b['b'], info['segB']) - max(b['t'], info['segT'])
            self.assertGreater(overlap, 8, f'{tag}: 버튼과 금액칸이 같은 줄이 아니다')
            self.assertLessEqual(abs(b['cy'] - info['segCy']), 8, f'{tag}: 버튼·금액칸 세로 중심이 어긋났다')
            if b is info['boxes'][-1]:
                self.assertAlmostEqual(b['r'], info['pmR'], delta=1.0,
                                       msg=f'{tag}: 마지막 금액칸이 오른쪽 끝까지 차야 한다')
            self.assertTrue(b['textFits'], f'{tag}: 숫자가 칸 안에서 잘린다 ({b["value"]})')
            self.assertTrue(b['unitInside'], f'{tag}: 만원이 칸 안에 있어야 한다')
            self.assertTrue(b['unitClear'], f'{tag}: 숫자와 만원이 붙었다')
            self.assertTrue(b['hintBelow'], f'{tag}: 환산 줄은 칸 아래')
            self.assertEqual(b['hintLeft'], 0, f'{tag}: 환산 줄은 칸 왼쪽에 맞춘다')
            self.assertFalse(b['hintClipped'], f'{tag}: 환산 줄이 잘린다 ({b["hint"]})')
            self.assertTrue(b['inPanel'], f'{tag}: 금액칸·환산 줄이 패널 밖으로 나갔다')
        self.assertEqual(info['scrollW'], info['win'], f'{tag}: 가로 스크롤이 생겼다')

    def run_prop_row_checks(self, page, key, tag):
        # 한 매물 블록에서 매매(한 칸) → 월세(반반 두 칸) → 전세(한 칸)를 차례로 재 본다
        base = '#fields [data-prop="%s"]' % key + ('[data-idx="0"]' if key == 'items' else '')
        trade = '#fields [data-prop-trade="%s"]' % key + ('[data-idx="0"]' if key == 'items' else '')
        page.fill(base + '[data-key="dong"]', '208')
        page.fill(base + '[data-key="ho"]', '1103')
        # 매매 — 버튼 옆 한 칸
        page.click(trade + '[data-value="매매"]')
        page.wait_for_timeout(150)
        page.fill('#fields [data-money="amount"]', '230000')
        page.wait_for_timeout(160)
        info = page.evaluate(self.PROP_ROW_JS)
        self.assertEqual([b['key'] for b in info['boxes']], ['amount'], f'{tag} 매매는 한 칸')
        self.assert_prop_money_one_row(info, f'{tag} 매매')
        self.assertEqual(info['boxes'][0]['hint'], '2,300,000,000원 (23억)')
        # 월세 — 오른쪽 영역을 정확히 반으로
        page.click(trade + '[data-value="월세"]')
        page.wait_for_timeout(150)
        page.fill('#fields [data-money="deposit"]', '20000')
        page.fill('#fields [data-money="rent"]', '30')
        page.wait_for_timeout(160)
        info = page.evaluate(self.PROP_ROW_JS)
        self.assertEqual([b['key'] for b in info['boxes']], ['deposit', 'rent'], f'{tag} 월세는 두 칸')
        self.assertEqual(info['labels'], ['보증금', '월세'])
        self.assert_prop_money_one_row(info, f'{tag} 월세')
        dep, rent = info['boxes']
        self.assertEqual(dep['hint'], '200,000,000원 (2억)')
        self.assertEqual(rent['hint'], '300,000원 (30만)')
        self.assertGreaterEqual(rent['l'], dep['r'] - 0.5, f'{tag} 두 칸은 나란히')
        self.assertAlmostEqual(dep['w'], rent['w'], delta=1.0, msg=f'{tag} 보증금·월세는 반반')
        self.assertIsNotNone(info['pairCols'], f'{tag} 두 칸 묶음이 없다')
        self.assertEqual(len(info['pairCols']), 2)
        self.assertAlmostEqual(info['pairCols'][0], info['pairCols'][1], delta=1.0,
                               msg=f'{tag} 1fr 1fr 로 반반')
        # 전세 — 다시 한 칸
        page.click(trade + '[data-value="전세"]')
        page.wait_for_timeout(150)
        info = page.evaluate(self.PROP_ROW_JS)
        self.assertEqual([b['key'] for b in info['boxes']], ['amount'], f'{tag} 전세는 한 칸')
        self.assert_prop_money_one_row(info, f'{tag} 전세')

    def test_prop_trade_money_one_row_all_blocks(self):
        # 매물 블록을 쓰는 여섯 문자 모두 — [매매][전세][월세] 옆에 금액칸이 한 줄
        for tid, key in (('t2', 'prop'), ('t3', 'prop'), ('t5', 'items'),
                         ('t7', 'items'), ('t19', 'items')):
            with self.subTest(tid=tid):
                self.pick(tid)
                self.run_prop_row_checks(self.page, key, tid)
        # 집보기 문의(t3) — 소유자/중개사 어느 쪽이든 같은 매물 줄을 쓴다
        with self.subTest(tid='t3-coagent'):
            ctx, page = self.page_with_state({
                'stars': [], 'texts': {}, 'current': 't3', 'stage': 'all',
                'data': {'t3': {'who': 'coagent', 'view': 'simple', 'prop': {
                    'complex': '마포래미안푸르지오', 'dong': '', 'ho': '', 'trade': '매매',
                    'amount': '', 'deposit': '', 'rent': '', 'price': ''}}}
            })
            try:
                self.assertIsNotNone(page.query_selector('#fields .prop-money'),
                                     't3 중개사 버전에도 매물 블록이 나와야 한다')
                self.run_prop_row_checks(page, 'prop', 't3')
            finally:
                ctx.close()

    def test_prop_trade_money_one_row_mobile(self):
        # 폰(390×844) — 버튼과 보증금·월세 두 칸이 한 줄, 16px 글씨 유지, 숫자·만원 겹침 없음
        for tid, key in (('t19', 'items'), ('t2', 'prop')):
            with self.subTest(tid=tid):
                ctx = self.browser.new_context(viewport={'width': 390, 'height': 844},
                                               is_mobile=True, has_touch=True)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(200)
                page.click('#btn-sheet')
                page.wait_for_timeout(150)
                page.click(f'#sheet-list [data-id="{tid}"]')
                page.wait_for_timeout(220)
                base = '#fields [data-prop="%s"]' % key + ('[data-idx="0"]' if key == 'items' else '')
                trade = '#fields [data-prop-trade="%s"]' % key + ('[data-idx="0"]' if key == 'items' else '')
                page.fill(base + '[data-key="dong"]', '208')
                page.fill(base + '[data-key="ho"]', '1103')
                page.click(trade + '[data-value="월세"]')
                page.wait_for_timeout(180)
                page.fill('#fields [data-money="deposit"]', '20000')
                page.fill('#fields [data-money="rent"]', '30')
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.wait_for_timeout(220)
                info = page.evaluate(self.PROP_ROW_JS)
                self.assert_prop_money_one_row(info, f'{tid} 폰')
                dep, rent = info['boxes']
                self.assertEqual([dep['font'], rent['font']], [16, 16], '폰에서는 16px (아이폰 확대 방지)')
                self.assertAlmostEqual(dep['w'], rent['w'], delta=1.0, msg='두 칸은 반반')
                self.assertGreaterEqual(rent['l'], dep['r'] - 0.5, '두 칸은 나란히')
                self.assertEqual([dep['hint'], rent['hint']], ['200,000,000원 (2억)', '300,000원 (30만)'])
                self.assertEqual(errors, [])
                ctx.close()

    def test_prop_trade_money_one_row_small_window(self):
        # 작은 PC 창(1000×720)에서도 한 줄 · 잘림 없음
        ctx = self.browser.new_context(viewport={'width': 1000, 'height': 720})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('#tpl-list [data-id="t19"]')
        page.wait_for_timeout(220)
        page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
        page.wait_for_timeout(180)
        page.fill('#fields [data-money="deposit"]', '20000')
        page.fill('#fields [data-money="rent"]', '30')
        page.evaluate('document.activeElement && document.activeElement.blur()')
        page.wait_for_timeout(200)
        info = page.evaluate(self.PROP_ROW_JS)
        self.assert_prop_money_one_row(info, '1000×720')
        self.assertEqual(errors, [])
        ctx.close()

    def test_fee_calculator_ui(self):
        self.pick('t14')
        # 부가세 기본값은 간이 4%
        self.assertEqual(self.page.inner_text('#fields [data-seg="calcVat"].is-active'), '간이 4%')
        self.assertNotIn('금액 표시', self.page.inner_text('#fields'), '중개보수 계산기에는 금액 표시 줄이 없다')
        self.page.fill('#fields [data-field="calcAmount"]', '230000')
        self.wait(200)
        summary = self.page.inner_text('.calc-summary')
        # 중개보수 합계는 직접 고칠 수 있는 칸 — 기본은 법정 보수로 채워진다
        self.assertEqual(self.page.input_value('#fields [data-field="calcTotalWon"]'), '16,744,000')
        self.assertEqual(self.page.inner_text('.calc-cell .money-unit').strip(), '원')
        self.assertIn('중개보수(공급가액) 16,100,000원', summary)
        self.assertIn('부가세 644,000원 (간이 4%)', summary)
        self.assertIn('상한 0.7%', summary)
        self.assertIn('- 적용 요율 : 0.7%', self.text())
        self.assertIn('- 중개보수 (공급가액) : 16,100,000원', self.text())
        self.assertIn('- 부가가치세 : 644,000원 (간이과세 4%)', self.text())
        self.assertIn('- 합계 : 16,744,000원', self.text())
        self.assertNotIn('중개수수료', self.text())

        # 결과 박스와 적용 요율이 한 줄, 같은 라벨 줄·같은 칸 높이, 계산식은 그 아래 원단위 금액 표시처럼 작고 연한 글씨
        info = self.js("""() => {
          const box = document.querySelector('#fields [data-field="calcTotalWon"]').getBoundingClientRect();
          const rate = document.querySelector('.calc-cell.is-rate .inp.is-rate').getBoundingClientRect();
          const hint = document.querySelector('.calc-hint').getBoundingClientRect();
          const hs = getComputedStyle(document.querySelector('.calc-hint'));
          const ms = getComputedStyle(document.querySelector('#fields .is-calc-deal .money-hint'));
          const labels = [...document.querySelectorAll('.calc-cell-label')];
          const ls = labels.map(e => e.getBoundingClientRect());
          const lstyle = labels.map(e => getComputedStyle(e));
          return {sameRow: Math.abs(box.top - rate.top) < 1.5 && Math.abs(box.bottom - rate.bottom) < 1.5,
                  beside: rate.left >= box.right - 0.5,
                  sameHeight: Math.abs(box.height - rate.height) < 0.6,
                  boxH: box.height, rateH: rate.height,
                  hintBelow: hint.top >= box.bottom - 0.5, hintUnderRate: hint.top >= rate.bottom - 0.5,
                  font: hs.fontSize, color: hs.color, mFont: ms.fontSize, mColor: ms.color,
                  labelTexts: labels.map(e => e.textContent),
                  labelsAbove: ls.every(l => l.bottom <= box.top + 0.5),
                  labelsLevel: ls.length === 2 && Math.abs(ls[0].top - ls[1].top) < 0.6,
                  labelSame: lstyle.length === 2 && ['fontSize', 'fontWeight', 'color'].every(k => lstyle[0][k] === lstyle[1][k]),
                  panel: document.querySelector('.form-panel').getBoundingClientRect().right,
                  hintRight: hint.right,
                  scrollW: document.documentElement.scrollWidth, win: window.innerWidth};
        }""")
        self.assertTrue(info['sameRow'], '결과 박스와 적용 요율이 다른 줄에 있다')
        self.assertTrue(info['beside'], '적용 요율이 결과 박스 오른쪽에 있지 않다')
        self.assertTrue(info['sameHeight'], f"결과 박스와 적용 요율 칸 높이가 다르다 ({info['boxH']} vs {info['rateH']})")
        self.assertGreaterEqual(info['boxH'], 43.5, '결과 박스가 44px 보다 낮다')
        self.assertEqual(info['labelTexts'], ['중개보수 합계', '적용 요율'])
        self.assertTrue(info['labelsAbove'], '라벨이 결과 박스 위에 있지 않다')
        self.assertTrue(info['labelsLevel'], '중개보수 합계·적용 요율 라벨이 나란하지 않다')
        self.assertTrue(info['hintBelow'] and info['hintUnderRate'], '계산식이 한 줄 박스 아래에 있지 않다')
        self.assertEqual(info['font'], info['mFont'], '계산식 글씨 크기가 원단위 표시와 다르다')
        self.assertEqual(info['color'], info['mColor'], '계산식 색이 원단위 표시와 다르다')
        self.assertTrue(info['labelSame'], '중개보수 합계 라벨이 적용 요율 라벨과 다른 모양이다')
        self.assertLessEqual(info['hintRight'], info['panel'] + 0.5, '계산식이 패널 밖으로')
        self.assertLessEqual(info['scrollW'], info['win'])

        # 다른 버튼을 누르면 금액과 계산식이 바로 바뀐다
        self.page.click('#fields [data-seg="calcVat"][data-value="10"]')
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-field="calcTotalWon"]'), '17,710,000')
        self.assertIn('- 부가가치세 : 1,610,000원 (일반과세 10%)', self.text())
        self.assertIn('- 합계 : 17,710,000원', self.text())
        self.assertIn('부가세 1,610,000원 (일반 10%)', self.page.inner_text('.calc-hint'))
        self.page.click('#fields [data-seg="calcVat"][data-value="none"]')
        self.wait(120)
        self.assertEqual(self.page.input_value('#fields [data-field="calcTotalWon"]'), '16,100,000')
        self.assertIn('부가세 별도', self.page.inner_text('.calc-hint'))
        self.page.fill('#fields [data-field="calcRate"]', '0.6')
        self.wait(200)
        self.assertIn('13,800,000원', self.text())
        self.assertIn('적용 요율 : 0.6%', self.text())
        self.page.fill('#fields [data-field="calcRate"]', '')
        self.page.click('#fields [data-seg="calcTrade"][data-value="월세"]')
        self.wait(150)
        self.assertIsNotNone(self.page.query_selector('#fields [data-field="calcDeposit"]'))
        self.page.fill('#fields [data-field="calcDeposit"]', '10000')
        self.page.fill('#fields [data-field="calcRent"]', '50')
        self.wait(250)
        self.assertEqual(self.page.input_value('#fields [data-field="calcTotalWon"]'), '450,000')
        self.assertIn('- 거래금액 : 보증금 100,000,000원 / 월차임 500,000원 (환산 150,000,000원)', self.text())

    def test_fee_calculator_presale_only_sale(self):
        self.pick('t14')
        self.page.click('#fields [data-seg="calcKind"][data-value="presale"]')
        self.wait(150)
        segs = self.page.query_selector_all('#fields [data-seg="calcTrade"]')
        self.assertEqual(len(segs), 1)

    def wheel_pick(self, scope, col, val):
        """3열 휠 피커에서 한 칸을 누른다 (scope: '#calpop' | '#wheelpop')"""
        self.page.click(f'{scope} .wheel [data-wheel-col="{col}"] .wheel-item[data-wheel-val="{val}"]')
        self.wait(110)

    def pick_time(self, scope, period, hour, minute):
        """휠 피커로 시(00~23) · 분을 고른다. period는 예전 호출과 맞추기 위한 자리(지금은 오전/오후 열이 없다)"""
        if hour is not None:
            self.wheel_pick(scope, 'h', hour)
        if minute is not None:
            self.wheel_pick(scope, 'm', minute)
        self.wait(80)

    def range_time(self, which, period, hour, minute):
        """방문 희망 시간 — 시작/종료 칸을 눌러 열린 휠 피커로 고른다"""
        self.page.click(f'#fields [data-time-chip="{which}"]')
        self.wait(200)
        self.pick_time('#wheelpop', period, hour, minute)
        self.page.click('#wheelpop [data-wheel-close]')
        self.wait(120)

    def test_time_range_helper(self):
        # 방문 희망 시간 — 날짜칸 + 시작~종료 + 초기화·저장, 저장하면 미리보기 본문에 바로 한 줄
        self.pick('t3')
        self.page.click('#fields [data-seg="view"][data-value="detail"]')
        self.wait(120)
        # 세그먼트 버튼 없이 날짜·시각 칸만 있다 (종료를 비우면 지정, 둘 다 넣으면 범위)
        self.assertEqual(self.js("() => document.querySelectorAll('#fields .range-add .seg-btn').length"), 0)
        self.page.click('#fields [data-date="times__range"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-nav="1"]')
        self.wait(80)
        self.page.click('#calpop [data-cal-day="5"]')
        self.wait(150)

        # ① 끝 시각을 비워 두고 저장 → 한 시각(12월 5일 (토) 14:15 꼴)
        self.range_time('start', None, '14', '15')
        self.page.click('#fields [data-range-save="times"]')
        self.wait(150)
        body = self.text()
        self.assertIn('- 방문 희망 시간 : 12월 5일 (토) 14:15', body)
        self.assertNotIn('14:15 ~', body)

        # ② 시작·끝을 모두 넣고 저장 → 범위가 다음 줄에 붙는다
        self.range_time('end', None, '15', '30')
        self.page.click('#fields [data-range-save="times"]')
        self.wait(150)
        body = self.text()
        self.assertIn('- 방문 희망 시간 : 12월 5일 (토) 14:15 / 12월 5일 (토) 14:15 ~ 15:30', body)
        self.assertNotIn('마포래미안푸르지오', body)

        # ③ 시각을 비우고 저장 → 날짜 한 줄 (시각 칸의 초기화는 그 시각만 지운다)
        for which in ('start', 'end'):
            self.page.click(f'#fields [data-time-chip="{which}"]')
            self.wait(180)
            self.page.click('#wheelpop [data-wheel-reset]')
            self.wait(120)
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="start"]').strip(), '시작 시각')
        self.page.click('#fields [data-range-save="times"]')
        self.wait(150)
        self.assertIn('/ 12월 5일 (토)\n', self.text())

        # ④ 날짜 없이 저장하면 안내하고 본문은 그대로
        self.page.click('#fields [data-clear-date="times__range"]')
        self.wait(120)
        before = self.text()
        self.page.click('#fields [data-range-save="times"]')
        self.wait(150)
        self.assertIn('날짜를 먼저 골라 주세요', self.page.inner_text('#toast'))
        self.assertEqual(self.text(), before)

        # ⑤ 초기화 → 날짜·시각 입력과 저장해 둔 시간대가 함께 비워진다
        self.page.click('#fields [data-range-reset="times"]')
        self.wait(150)
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="start"]').strip(), '시작 시각')
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="end"]').strip(), '종료 시각')
        self.assertIn('날짜', self.page.inner_text('#fields [data-date="times__range"]'))
        body = self.text()
        self.assertIn('(방문 희망 시간)', body)
        self.assertNotIn('12월 5일', body)

    def test_visit_line_formatter(self):
        # 문자에 들어가는 한 줄 표기 — 끝 시각이 없으면 한 시각만
        self.assertEqual(
            self.js("() => SMSCore.formatVisitLine('2026-11-26', 14, 15, null, 0)"),
            '11월 26일 (목) 14:15')
        self.assertEqual(
            self.js("() => SMSCore.formatVisitLine('2026-11-26', 14, 15, 15, 30)"),
            '11월 26일 (목) 14:15 ~ 15:30')
        self.assertEqual(
            self.js("() => SMSCore.formatVisitLine('2026-11-26', null, 0, null, 0)"),
            '11월 26일 (목)')
        self.assertEqual(self.js('() => SMSCore.slotClock(0, 5)'), '00:05')
        self.assertEqual(self.js('() => SMSCore.slotClock(12, 55)'), '12:55')

    def test_no_native_time_select_and_wheel_steps(self):
        # 시간을 고르는 곳에는 네이티브 <select>가 하나도 없다 — 전부 3열 휠 피커
        expect_min = [str(m) for m in range(0, 60, 5)]
        expect_min_labels = [(m < 10 and '0' + str(m) or str(m)) + '분' for m in range(0, 60, 5)]
        scan = """() => [...document.querySelectorAll('select')]
          .filter(s => s.dataset.calMin || s.dataset.calHour || s.dataset.rangePart)
          .map(s => s.dataset.calMin ? 'cal' : s.dataset.calHour ? 'cal' : 'range')"""

        # ① 달력 + 시간 팝업 — 24시간 2열 휠 (00시~23시 · 분)
        self.pick_with('t10', {'trade': '매매', 'kind': '약정'})
        self.page.click('#fields [data-date="when"]')
        self.wait(180)
        self.assertEqual(self.js(scan), [], '달력 팝업에 시간 셀렉트가 남아 있으면 안 된다')
        cols = self.js("""() => [...document.querySelectorAll('#calpop .wheel .wheel-col')].map(c => c.dataset.wheelCol)""")
        self.assertEqual(cols, ['h', 'm'], '오전/오후 열이 없이 시·분 두 열')
        hours = self.js("""() => [...document.querySelectorAll('#calpop [data-wheel-col="h"] .wheel-item')].map(i => i.dataset.wheelVal)""")
        self.assertEqual(hours, [str(h) for h in range(0, 24)], '시 열은 00시~23시')
        mins = self.js("""() => [...document.querySelectorAll('#calpop [data-wheel-col="m"] .wheel-item')].map(i => i.dataset.wheelVal)""")
        labels = self.js("""() => [...document.querySelectorAll('#calpop [data-wheel-col="m"] .wheel-item')].map(i => i.textContent.trim())""")
        self.assertEqual(mins, expect_min, '분은 앱 어디서나 5분 단위')
        self.assertEqual(labels, expect_min_labels)
        self.page.click('#calpop [data-cal-close]')

        # ② 방문 희망 시간 — 시작·종료 칸을 누르면 뜨는 휠도 같은 5분 단위
        self.pick('t3')
        self.page.click('#fields [data-seg="view"][data-value="detail"]')
        self.wait(150)
        self.assertEqual(self.js(scan), [], '방문 희망 시간에도 시간 셀렉트가 없다')
        for which in ('start', 'end'):
            with self.subTest(which=which):
                self.page.click(f'#fields [data-time-chip="{which}"]')
                self.wait(220)
                labels = self.js("""() => [...document.querySelectorAll('#wheelpop [data-wheel-col="m"] .wheel-item')].map(i => i.textContent.trim())""")
                self.assertEqual(labels, expect_min_labels)
                self.page.click('#wheelpop [data-wheel-close]')
                self.wait(120)

        # ③ 다른 템플릿에도 시간 셀렉트가 따로 남아 있지 않다
        for tid in ('t2', 't3', 't5', 't8', 't10', 't18'):
            with self.subTest(tid=tid):
                self.pick(tid)
                self.wait(80)
                self.assertEqual(self.js(scan), [], '시간 셀렉트는 어디에도 없다')

    # ------------------------------------------------------------ 시간 휠 피커 (v1.1.5)
    WHEEL_INFO_JS = """(scope) => {
      const w = document.querySelector(scope + ' .wheel');
      if (!w) return null;
      const r = w.getBoundingClientRect();
      const col = w.querySelector('.wheel-col');
      const ccs = getComputedStyle(col);
      const item = col.querySelector('.wheel-item');
      const bar = w.querySelector('.wheel-bar');
      const ir = item.getBoundingClientRect();
      return {
        w: +r.width.toFixed(1), h: +r.height.toFixed(1),
        cols: w.querySelectorAll('.wheel-col').length,
        snap: ccs.scrollSnapType,
        mask: ccs.maskImage || ccs.webkitMaskImage || 'none',
        itemH: ir.height, itemLine: getComputedStyle(item).lineHeight,
        barH: bar ? +bar.getBoundingClientRect().height.toFixed(1) : null,
        barTop: bar ? +(bar.getBoundingClientRect().top - r.top).toFixed(1) : null,
        active: (w.querySelector('.wheel-item.is-active') || {}).textContent
      };
    }"""

    def wheel_info(self, scope):
        return self.js(self.WHEEL_INFO_JS, scope)

    def wheel_value(self, scope):
        """각 열의 가운데(고른) 값"""
        return self.js("""(scope) => [...document.querySelectorAll(scope + ' .wheel-col')]
            .map(c => c.querySelector('.wheel-item.is-active').dataset.wheelVal)""", scope)

    def test_calendar_wheel_picker_compact(self):
        # 달력 + 시간 팝업 — 큰 모달이 아니라 달력 폭 안의 컴팩트한 2열 휠
        self.pick_with('t10', {'trade': '매매', 'kind': '약정'})
        self.page.click('#fields [data-date="when"]')
        self.wait(220)
        info = self.wheel_info('#calpop')
        self.assertEqual(info['cols'], 2, '시 · 분 두 열')
        self.assertGreaterEqual(info['h'], 108, '세 줄이 보일 높이')
        self.assertLessEqual(info['h'], 132, '달력 팝업 안에 들어가는 높이')
        self.assertAlmostEqual(info['h'], info['itemH'] * 3, delta=1.5, msg='세 줄만 보인다')
        self.assertIn('mandatory', info['snap'])
        self.assertTrue(info['snap'].startswith('y'))
        self.assertAlmostEqual(info['barH'], info['itemH'], delta=1.0, msg='가운데 강조 띠는 한 줄 높이')
        self.assertAlmostEqual(info['barTop'], info['itemH'], delta=1.5)
        self.assertNotEqual(info['mask'], 'none', '위아래가 흐리게 사라진다')
        pop_w = self.js("() => +document.querySelector('#calpop').getBoundingClientRect().width.toFixed(1)")
        self.assertLessEqual(info['w'], pop_w - 16, '달력 폭 안에 들어간다')

        # 휠을 돌려 고르면 날짜 칸 글자와 미리보기가 바로 바뀐다
        self.page.click('#calpop [data-cal-day="26"]')
        self.wait(220)
        unset = self.wheel_value('#calpop')
        self.assertEqual(unset, ['10', '0'], '시간을 아직 안 골랐으면 10:00 자리에서 시작')
        self.assertNotIn('10:00', self.text(), '휠을 돌리기 전에는 날짜만 나간다')
        self.pick_time('#calpop', None, '14', '30')
        self.assertEqual(self.wheel_value('#calpop'), ['14', '30'])
        self.assertIn('2026년 11월 26일 목요일 14:30', self.text())
        self.assertIn('2026.11.26 (목) 14:30', self.page.inner_text('#fields [data-date="when"]'))

        # 마우스 휠로도 돌아간다 (14시 → 한 칸 아래 15시)
        box = self.page.eval_on_selector('#calpop [data-wheel-col="h"]',
                                         "e => { const r = e.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }")
        self.page.mouse.move(box['x'], box['y'])
        self.page.mouse.wheel(0, 40)
        self.wait(500)
        self.assertEqual(self.wheel_value('#calpop')[0], '15', '휠을 굴리면 값이 따라 움직인다')

        # 초기화 · 닫기는 팝업 우측 아래
        foot = self.js("""() => {
          const pop = document.querySelector('#calpop').getBoundingClientRect();
          const b = [...document.querySelectorAll('#calpop .cal-foot button')].map(x => x.getBoundingClientRect());
          return { mid: pop.left + pop.width / 2, bottom: pop.bottom,
                   names: [...document.querySelectorAll('#calpop .cal-foot button')].map(x => x.textContent.trim()),
                   lefts: b.map(r => +r.left.toFixed(1)), tops: b.map(r => +r.top.toFixed(1)),
                   rights: b.map(r => +r.right.toFixed(1)) };
        }""")
        self.assertEqual(foot['names'], ['초기화', '닫기'])
        self.assertGreater(foot['lefts'][0], foot['mid'], '오른쪽 아래에 초기화·닫기')
        self.assertAlmostEqual(foot['tops'][0], foot['tops'][1], delta=1.0)
        self.assertLess(foot['lefts'][0], foot['lefts'][1], '초기화가 닫기 왼쪽')
        self.page.click('#calpop [data-cal-close]')
        self.assertFalse(self.page.is_visible('#calpop'))

    def test_visit_time_box_layout(self):
        # 방문 희망 시간 — 날짜칸·시작~종료 반반·우측 하단 초기화·저장 세 줄
        self.pick('t3')
        self.page.click('#fields [data-seg="view"][data-value="detail"]')
        self.wait(200)
        geo = self.js("""() => {
          const q = s => document.querySelector(s).getBoundingClientRect();
          const box = q('#fields .range-add'), d = q('#fields [data-date="times__range"]');
          const a = q('#fields [data-time-chip="start"]'), t = q('#fields .range-tilde');
          const b = q('#fields [data-time-chip="end"]');
          const r = q('#fields [data-range-reset]'), s = q('#fields [data-range-save]');
          const o = e => ({l: e.left, r: e.right, t: e.top, b: e.bottom, w: e.width, h: e.height});
          return {box: o(box), date: o(d), start: o(a), end: o(b), reset: o(r), save: o(s),
                  tilde: {l: t.left, r: t.right, c: (t.top + t.bottom) / 2}};
        }""")
        # 1줄 — 날짜 칸이 박스 폭을 거의 다 쓴다 (양옆 여백·테두리만 남는다)
        box = geo['box']
        self.assertGreater(geo['date']['w'], box['w'] * 0.9, '날짜 칸이 전체 폭')
        self.assertLessEqual(geo['date']['b'], geo['start']['t'] + 0.5, '날짜가 시각 줄 위')
        # 2줄 — 시작 · ~ · 종료가 한 줄, 시작·종료는 반반
        self.assertAlmostEqual(geo['end']['t'], geo['start']['t'], delta=1.0)
        self.assertLess(geo['start']['r'], geo['tilde']['l'])
        self.assertLess(geo['tilde']['r'], geo['end']['l'])
        self.assertAlmostEqual(geo['start']['w'], geo['end']['w'], delta=1.0, msg='시작·종료 칸이 반반')
        self.assertGreater(geo['start']['w'], box['w'] * 0.42, '추가 버튼 없이 두 칸이 폭을 나눠 쓴다')
        self.assertAlmostEqual(geo['tilde']['c'], (geo['start']['t'] + geo['start']['b']) / 2, delta=2.0)
        self.assertLessEqual(geo['end']['r'], box['r'] + 0.5, '시각 줄이 박스 안에')
        # 3줄 — 아래쪽 오른쪽에 초기화 · 저장, 다른 버튼 없음
        self.assertGreaterEqual(geo['reset']['t'], geo['start']['b'] - 0.5, '버튼은 시각 줄 아래')
        self.assertAlmostEqual(geo['reset']['t'], geo['save']['t'], delta=1.0)
        self.assertLess(geo['reset']['r'], geo['save']['l'], '초기화가 저장 왼쪽')
        self.assertGreater(geo['reset']['l'], box['l'] + box['w'] / 2, '오른쪽에 붙어 있다')
        self.assertLessEqual(geo['save']['r'], box['r'] + 0.5)
        self.assertEqual(self.js("""() => document.querySelectorAll(
            '#fields [data-range-add], #fields .range-times .add-btn, #fields .range-add textarea').length"""), 0)
        self.assertEqual(self.js("""() => [...document.querySelectorAll('#fields .range-foot button')]
            .map(b => b.textContent.trim())"""), ['초기화', '저장'])
        self.assertLess(geo['box']['h'], 160, '날짜 · 시각 · 버튼 세 줄 높이만큼만')

        # 시작 칸을 누르면 그 칸 폭 그대로 위아래로 펼쳐진 휠 (큰 모달 아님)
        self.page.click('#fields [data-time-chip="start"]')
        self.wait(260)
        pop = self.js("""() => {
          const p = document.querySelector('#wheelpop').getBoundingClientRect();
          const c = document.querySelector('#fields [data-time-chip="start"]').getBoundingClientRect();
          return {pl: p.left, pt: p.top, pw: p.width, ph: p.height, pr: p.right,
                  cl: c.left, ct: c.top, cw: c.width, cb: c.bottom};
        }""")
        self.assertTrue(self.page.is_visible('#wheelpop'))
        self.assertAlmostEqual(pop['pw'], pop['cw'], delta=2.0, msg='누른 칸 폭 그대로 펼쳐진다')
        self.assertAlmostEqual(pop['pl'], pop['cl'], delta=2.0)
        self.assertGreaterEqual(pop['pt'], pop['cb'] - 1, '칸 아래로 펼쳐진다')
        self.assertLessEqual(pop['ph'], 240, '크게 뜨지 않는다')
        info = self.wheel_info('#wheelpop')
        self.assertEqual(info['cols'], 2)
        self.assertAlmostEqual(info['h'], info['itemH'] * 3, delta=1.5)
        self.assertIn('mandatory', info['snap'])
        # 휠 위에 '시작 시각 · 종료 시각' 제목 줄이 없다 — 바로 휠부터
        self.assertEqual(self.js("() => document.querySelectorAll('#wheelpop .wheelpop-head').length"), 0)
        for word in ('시작 시각', '종료 시각'):
            self.assertNotIn(word, self.page.inner_text('#wheelpop'))

        # 고르는 즉시 칸 글자가 바뀐다 (팝업은 열린 채)
        self.pick_time('#wheelpop', None, '14', '15')
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="start"]').strip(), '14:15')
        self.assertTrue(self.page.is_visible('#wheelpop'))
        wf = self.js("""() => {
          const p = document.querySelector('#wheelpop').getBoundingClientRect();
          const b = [...document.querySelectorAll('#wheelpop .wheelpop-foot button')].map(x => x.getBoundingClientRect());
          return {right: p.right, midY: p.top + p.height / 2,
                  lefts: b.map(r => +r.left.toFixed(1)), rights: b.map(r => +r.right.toFixed(1)),
                  tops: b.map(r => +r.top.toFixed(1)),
                  names: [...document.querySelectorAll('#wheelpop .wheelpop-foot button')].map(x => x.textContent.trim())};
        }""")
        self.assertEqual(wf['names'], ['초기화', '닫기'])
        self.assertAlmostEqual(wf['rights'][1], wf['right'], delta=16, msg='우측에 붙어 있다')
        self.assertGreater(wf['tops'][0], wf['midY'], '아래쪽에 있다')
        self.assertAlmostEqual(wf['tops'][0], wf['tops'][1], delta=1.0)

        # 종료 칸도 같은 방식, 초기화는 시각만 지운다
        self.page.click('#wheelpop [data-wheel-close]')
        self.page.click('#fields [data-time-chip="end"]')
        self.wait(240)
        self.pick_time('#wheelpop', None, '15', '30')
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="end"]').strip(), '15:30')
        self.page.click('#wheelpop [data-wheel-reset]')
        self.wait(240)
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="end"]').strip(), '종료 시각')
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="start"]').strip(), '14:15', '반대 칸은 그대로')
        self.assertFalse(self.page.is_visible('#wheelpop'), '초기화하면 시각 칸 팝업은 닫힌다')

        # 바깥을 누르면 닫힌다
        self.page.click('#fields [data-time-chip="start"]')
        self.wait(200)
        self.page.click('#form-title')
        self.wait(200)
        self.assertFalse(self.page.is_visible('#wheelpop'))

    def test_times_box_has_no_example_or_tags(self):
        # 방문 희망 시간 — 예시 textarea·도움말·시간대 태그 목록 없이 날짜칸·시간칸·초기화/저장뿐
        self.pick('t3')
        self.page.click('#fields [data-seg="view"][data-value="detail"]')
        self.wait(150)
        box = self.js("""() => {
          const b = document.querySelector('#fields .time-box');
          return {text: b.innerText,
                  areas: document.querySelectorAll('#fields textarea').length,
                  phs: [...document.querySelectorAll('#fields textarea')].map(t => t.placeholder),
                  chips: b.querySelectorAll('.time-chip').length,
                  h: +b.getBoundingClientRect().height.toFixed(1)};
        }""")
        self.assertEqual(box['areas'], 0, '예시 textarea 가 남아 있으면 안 된다')
        self.assertEqual(box['phs'], [])
        self.assertNotIn('예:', box['text'])
        self.assertNotIn('한 줄에 시간대 하나', box['text'])
        self.assertNotIn('추가', box['text'])
        self.assertEqual(box['chips'], 2, '시작 · 종료 두 칸만')
        self.assertLess(box['h'], 160, '빈 박스나 태그 목록 없이 세 줄만')
        # 양식 라벨은 그대로 남고, 미리보기에는 아직 넣은 시간대가 없다
        self.assertIn('방문 희망 시간', self.page.inner_text('#fields'))
        self.assertIn('(방문 희망 시간)', self.text())

    def test_t3_time_box_same(self):
        # 집보기 문의 — 소유자/중개사 × 간단/상세 어느 조합이든 같은 날짜 + 휠 시간 박스
        BOX_JS = """() => {
          const b = document.querySelector('#fields .time-box');
          const d = b.querySelector('.date-btn');
          const cs = getComputedStyle(b), ds = getComputedStyle(d);
          const br = b.getBoundingClientRect(), dr = d.getBoundingClientRect();
          return {pad: cs.padding, gap: cs.gap, radius: cs.borderRadius, bg: cs.backgroundColor,
                  border: cs.borderTopColor, borderW: cs.borderTopWidth, bw: +br.width.toFixed(1),
                  dbg: ds.backgroundColor, dh: +dr.height.toFixed(1), dw: +dr.width.toFixed(1),
                  dsize: ds.fontSize, dradius: ds.borderRadius};
        }"""
        seen = {}
        for tid, ver, who in (('t3', 'simple', 'owner'), ('t3', 'detail', 'owner'), ('t3', 'simple', 'coagent')):
            with self.subTest(tid=tid, ver=ver, who=who):
                self.pick_with(tid, {'who': who, 'view': ver})
                self.wait(180)
                seen[(tid, ver, who)] = self.js(BOX_JS)
                if (tid, ver) == ('t3', 'detail'):
                    # 방문 희망 시간도 같은 박스 안에 날짜 칸 + 시각 한 줄 + 초기화/저장
                    self.assertIsNotNone(self.page.query_selector('#fields .time-box [data-time-chip="start"]'))
                    self.assertIsNotNone(self.page.query_selector('#fields .time-box [data-date="times__range"]'))
                    chips = self.js("""() => [...document.querySelectorAll('#fields .time-chip')]
                        .map(c => +c.getBoundingClientRect().height.toFixed(1))""")
                    self.assertEqual(len(chips), 2)
                    self.assertAlmostEqual(chips[0], seen[(tid, ver, who)]['dh'], delta=1.0, msg='시각 칸 높이 = 날짜 칸 높이')
                    self.assertEqual(self.js("""() => [...document.querySelectorAll('#fields .range-foot button')]
                        .map(b => b.textContent.trim())"""), ['초기화', '저장'])
                else:
                    self.assertIsNotNone(self.page.query_selector('#fields .time-box .date-btn'))
        base = seen[('t3', 'simple', 'owner')]
        for key, got in seen.items():
            for field in ('pad', 'gap', 'radius', 'bg', 'border', 'borderW', 'bw', 'dbg', 'dh', 'dw', 'dsize', 'dradius'):
                self.assertEqual(got[field], base[field], f'{key} {field}가 소유자/간단과 다르다')

    def test_parking_toggle(self):
        self.pick('t5')
        self.assertIn('주차가 필요하시면', self.text())
        self.page.click('#fields [data-toggle="parking"]')
        self.wait(120)
        body = self.text()
        self.assertNotIn('주차가 필요하시면', body)
        self.assertIn('약속된 일정에 뵙겠습니다.', body)
        self.page.click('#fields [data-toggle="detail"]')
        self.wait(120)
        self.assertNotIn('- 매물 :', self.text())
        self.assertNotIn('- 마포래미안푸르지오', self.text(), '상세를 끄면 매물 줄 자체가 없다')


    def test_amount_display_mode_setting(self):
        self.pick_with('t10', {'trade': '매매', 'kind': '잔금'})
        self.pay_fill('gyeyak', 67500)
        self.assertIn('675,000,000원 (6억 7,500만 원)', self.text())
        # 설정 모달 버튼 이름 — 전체 / 만원 단위 / 끊어읽기
        self.page.click('#btn-settings')
        self.wait(100)
        labels = [b.inner_text().strip() for b in self.page.query_selector_all('[data-set-mode]')]
        self.assertEqual(labels, ['전체', '만원 단위', '끊어읽기'])
        self.page.click('[data-set-mode="won"]')
        self.page.click('#btn-settings-save')
        self.wait(150)
        body = self.text()
        self.assertIn('67,500만 원', body)
        self.assertNotIn('(6억 7,500만 원)', body)
        self.page.click('#btn-settings')
        self.wait(100)
        self.page.click('[data-set-mode="eokman"]')
        self.page.click('#btn-settings-save')
        self.wait(150)
        self.assertIn('6억7,500만 원', self.text())
        self.assertNotIn('675,000,000원', self.text())
        # 다시 '전체'로 두면 처음 모양으로 돌아온다
        self.page.click('#btn-settings')
        self.wait(100)
        self.page.click('[data-set-mode="won_eokman"]')
        self.page.click('#btn-settings-save')
        self.wait(150)
        self.assertIn('675,000,000원 (6억 7,500만 원)', self.text())

    def test_sms_url(self):
        url = self.js("() => SMSUI.smsUrl('안녕 😊')")
        self.assertTrue(url.startswith('sms:&body='))
        from urllib.parse import unquote
        self.assertEqual(unquote(url[len('sms:&body='):]), '안녕 😊')

    # ---------------------------------------------------------------- v1.4.5
    def test_v145_sms_url_never_puts_plus_for_space(self):
        # 문자 앱이 공백을 '+'로 보여 주던 버그 — 띄어쓰기는 %20, 진짜 '+'는 %2B
        text = '안녕하세요, 마래푸중앙부동산입니다. 😊\n010-4585-7365 / 02-312-7365'
        url = self.js("t => SMSUI.smsUrl(t)", text)
        from urllib.parse import unquote
        body = url[url.index('body=') + 5:]
        self.assertIn('%20', body, '공백은 %20으로 인코딩돼야 한다')
        self.assertNotIn('+', body, "본문에 '+'가 남으면 문자 앱에 +가 그대로 보인다")
        self.assertEqual(unquote(body), text)
        plus = self.js("() => SMSUI.smsUrl('A+B')")
        self.assertIn('A%2BB', plus, "진짜 '+' 기호는 %2B로 살아 있어야 한다")
        self.assertNotIn('A+B', plus)

    def test_v145_sms_url_android_uses_question_form(self):
        # 안드로이드(웹)는 sms:?body=, 아이폰은 sms:&body= 형태를 읽는다
        ctx = self.browser.new_context(
            viewport={'width': 390, 'height': 844},
            user_agent=('Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'),
        )
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(200)
        url = page.evaluate("() => SMSUI.smsUrl('안녕하세요, 마래푸중앙부동산입니다.')")
        ctx.close()
        self.assertTrue(url.startswith('sms:?body='), url)
        self.assertIn('%20', url)
        self.assertNotIn('+', url[url.index('body=') + 5:])

    def test_v145_android_sms_intent_never_uses_urlencoder(self):
        # 안드로이드 앱 껍데기는 공백을 URLEncoder(+로 바뀜)로 인코딩하지 않는다
        path = os.path.join(
            ROOT, 'android/app/src/main/java/com/maraepu/smshelper/MainActivity.java')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('URLEncoder.encode', src, 'URLEncoder.encode는 공백을 +로 바꾼다 — 쓰면 안 된다')
        self.assertNotIn('import java.net', src)
        self.assertIn('Uri.encode(text)', src)
        self.assertIn('putExtra("sms_body"', src)
        # 웹 링크 통로와 앱 통로가 같은 헬퍼 하나를 쓴다 (정의 1 + 호출 2)
        self.assertEqual(len(re.findall(r'openSmsApp\(', src)), 3)
        self.assertIn('openSmsApp(smsBodyOf(uri))', src)
        self.assertIn('openSmsApp(text);', src)

    def test_favorite_pinning(self):
        self.pick('t1')
        star = self.page.query_selector('#tpl-list [data-star="t1"]')
        self.assertNotIn('is-on', star.get_attribute('class'))
        star.click()
        self.wait(200)
        star2 = self.page.query_selector('#tpl-list [data-star="t1"]')
        self.assertIn('is-on', star2.get_attribute('class'))
        self.assertIn('★ 즐겨찾기', self.page.inner_text('#tpl-list'))
        self.page.reload(wait_until='networkidle')
        self.wait(150)
        star3 = self.page.query_selector('#tpl-list [data-star="t1"]')
        self.assertIn('is-on', star3.get_attribute('class'))

    def test_edited_body_saved_across_reload(self):
        self.pick('t6')
        self.page.fill('#preview', '주차는 지하 2층입니다')
        self.wait(400)
        self.page.reload(wait_until='networkidle')
        self.wait(200)
        self.assertEqual(self.page.input_value('#preview').strip(), '주차는 지하 2층입니다')

    def test_settings_fee_account_parsed(self):
        self.pick('t14')
        self.page.click('#btn-settings')
        self.wait(100)
        self.page.fill('#set-account', '신한 110-123-456789 황호선')
        self.wait(100)
        self.assertIn('신한은행 110-123-456789 황호선', self.page.inner_text('#set-account-preview'))
        self.page.click('#btn-settings-save')
        self.wait(150)
        self.assertIn('- 입금계좌 : 신한은행 110-123-456789 황호선', self.text())

    def test_mobile_stage_tab_opens_sheet_and_switches_text(self):
        # 폰(390×844)에서 상단 카테고리 탭을 누르면 그 카테고리 첫 문자로 넘어가고
        # 목록 시트가 바로 열린다 (예전에는 목록만 다시 그리고 화면은 첫 문자에 머물렀다)
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        for label, cnt in (('접수·홍보', 5), ('방문·집보기', 5),
                           ('약정·계약', 4), ('잔금·만기', 3)):
            with self.subTest(tab=label):
                page.click(f'.stage-tabs .tab:has-text("{label}")')
                page.wait_for_timeout(200)
                self.assertTrue(page.is_visible('#sheet'), '카테고리 탭을 누르면 목록 시트가 열려야 한다')
                self.assertEqual(len(page.query_selector_all('#sheet-list .row')), cnt, label)
                head = page.inner_text('#form-title .title-text')
                first = page.evaluate("""() => { const s = document.querySelector('#sheet-list .row.is-active .row-title-text');
                    return s ? s.textContent.trim() : null; }""")
                self.assertEqual(first, head.strip(), '카테고리 첫 문자로 바뀌어야 한다')
                # 시트에서 문자를 고르면 시트가 닫힌다 (기존 selectTemplate)
                page.click('#sheet-list .row .row-main')
                page.wait_for_timeout(180)
                self.assertFalse(page.is_visible('#sheet'))
        self.assertEqual(errors, [])
        ctx.close()

    def test_mobile_list_button_shows_all(self):
        # 카테고리를 고른 뒤에도 '목록' 버튼은 전체 17종을 보여 준다 (상단 탭도 '전체'로 돌아간다)
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('.stage-tabs .tab:has-text("약정·계약")')
        page.wait_for_timeout(200)
        self.assertEqual(len(page.query_selector_all('#sheet-list .row')), 4)
        page.click('#sheet-close')
        page.wait_for_timeout(150)
        page.click('#btn-sheet')
        page.wait_for_timeout(220)
        self.assertTrue(page.is_visible('#sheet'))
        self.assertEqual(len(page.query_selector_all('#sheet-list .row')), 17, '목록 버튼은 전체 17종')
        self.assertEqual(page.inner_text('.stage-tabs .tab.is-active').strip(), '전체')
        # 전체 목록에서 다른 카테고리 문자도 바로 고를 수 있다
        page.click('#sheet-list [data-id="t14"]')
        page.wait_for_timeout(200)
        self.assertFalse(page.is_visible('#sheet'))
        self.assertIn('중개보수', page.inner_text('#form-title'))
        self.assertEqual(errors, [])
        ctx.close()

    def test_mobile_layout(self):
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(200)
        self.assertFalse(page.is_visible('#list-panel'))
        self.assertTrue(page.is_visible('#btn-sheet'))
        self.assertTrue(page.is_visible('#btn-sms'))
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        self.assertTrue(page.is_visible('#sheet-list'))
        page.click('#sheet-list [data-id="t14"]')
        page.wait_for_timeout(200)
        self.assertFalse(page.is_visible('#sheet'))
        self.assertIn('중개보수', page.inner_text('#form-title'))
        overflow = page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        self.assertTrue(overflow, '모바일에서 가로 넘침이 없어야 한다')
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t7"]')
        page.wait_for_timeout(200)
        page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '208')
        page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '230000')
        page.wait_for_timeout(200)
        overflow2 = page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        self.assertTrue(overflow2, '모바일 매물 줄에서 가로 넘침이 없어야 한다')
        hint = page.query_selector('.prop-money .money-hint')
        self.assertEqual(hint.inner_text(), '2,300,000,000원 (23억)')
        clipped = page.evaluate("""() => {
          const field = document.querySelector('.prop-money .money-field');
          const h = field.querySelector('.money-hint'), i = field.querySelector('input'), u = field.querySelector('.money-unit');
          const hr = h.getBoundingClientRect(), ir = i.getBoundingClientRect(), ur = u.getBoundingClientRect();
          return {c: h.scrollWidth > h.clientWidth + 1, n: hr.top < ir.bottom - 0.5,
                  inBox: ur.right <= ir.right - 1 && ur.left >= ir.left + 1,
                  inside: hr.right <= document.querySelector('.form-panel').getBoundingClientRect().right};
        }""")
        self.assertFalse(clipped['c'])
        self.assertFalse(clipped['n'], '환산 줄은 입력칸 아래')
        self.assertTrue(clipped['inBox'], "'만원'은 칸 안")
        self.assertTrue(clipped['inside'])
        self.assertEqual(errors, [])
        ctx.close()

    def test_mobile_bottom_not_hidden_behind_mobile_bar(self):
        # 폰(390×844 · 360×740)에서 맨 아래까지 내리면 미리보기 카드의 아래 테두리까지
        # 하단 고정 바('문자 앱 열기 / 복사하기') 위로 다 보이고, 카드 안 중복 복사 버튼은 사라진다.
        for w, h in ((390, 844), (360, 740)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=True, has_touch=True)
                page = ctx.new_page()
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(250)
                page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                page.wait_for_timeout(350)
                info = page.evaluate("""() => {
                  const card = document.querySelector('.preview-panel').getBoundingClientRect();
                  const bar = document.querySelector('#sms-mobile-bar').getBoundingClientRect();
                  const foot = document.querySelector('.preview-foot').getBoundingClientRect();
                  const copy = document.querySelector('#btn-copy').getBoundingClientRect();
                  const cc = document.querySelector('#char-count');
                  const cs = getComputedStyle(document.body);
                  return {cardBottom: card.bottom, barTop: bar.top, footBottom: foot.bottom,
                          copyShown: copy.width > 0 && copy.height > 0,
                          charText: cc.textContent, charShown: cc.getBoundingClientRect().height > 0,
                          bodyPadBottom: parseFloat(cs.paddingBottom),
                          atBottom: Math.abs((document.documentElement.scrollHeight - window.innerHeight) - window.scrollY) <= 2,
                          scrollable: document.documentElement.scrollHeight > window.innerHeight + 40,
                          hOverflow: document.documentElement.scrollWidth - window.innerWidth};
                }""")
                self.assertTrue(info['scrollable'], '폰에서는 세로 스크롤이 되어야 한다')
                self.assertTrue(info['atBottom'], '맨 아래까지 스크롤되어야 한다')
                self.assertGreaterEqual(info['bodyPadBottom'], 100, '하단 고정 바 높이만큼 끝 여백을 둔다')
                self.assertLessEqual(info['cardBottom'], info['barTop'] - 6,
                                     '미리보기 카드 아래 테두리가 하단 바에 가려지면 안 된다')
                self.assertLessEqual(info['footBottom'], info['barTop'] - 6, '글자수 줄도 바 위에 있어야 한다')
                self.assertFalse(info['copyShown'], '폰에서는 카드 안 중복 복사 버튼을 숨긴다')
                self.assertTrue(info['charShown'], '글자수는 남아 있어야 한다')
                self.assertRegex(info['charText'], r'^\d[\d,]*자$')
                self.assertLessEqual(info['hOverflow'], 0, '가로 넘침 없음')
                ctx.close()

        # PC(1440)에서는 카드 안 '문자 전체 복사하기' 버튼을 그대로 쓴다
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(250)
        self.assertTrue(page.is_visible('#btn-copy'))
        self.assertTrue(page.is_hidden('#sms-mobile-bar'))
        ctx.close()

    def test_mobile_bar_hidden_while_keyboard_open(self):
        # 키보드가 열린 채 스크롤해도 '문자 앱 열기 / 복사하기' 바가 화면 가운데에 떠
        # 미리보기 카드를 가르지 않도록, 입력칸에 초점이 들어간 동안에는 바를 감춘다.
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844},
                                      is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(220)
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t7"]')
        page.wait_for_timeout(220)

        kbd = "document.body.classList.contains('kbd-open')"
        bar_box = """() => { const r = document.querySelector('#sms-mobile-bar').getBoundingClientRect();
          return { shown: r.width > 0 && r.height > 0, top: r.top, bottom: r.bottom }; }"""
        self.assertTrue(page.is_visible('#sms-mobile-bar'))
        self.assertFalse(page.evaluate(kbd))

        dong = '#fields [data-prop="items"][data-idx="0"][data-key="dong"]'
        page.click(dong)
        page.wait_for_timeout(180)
        self.assertTrue(page.evaluate(kbd), '입력칸에 초점이 가면 kbd-open')
        self.assertTrue(page.is_hidden('#sms-mobile-bar'), '키보드가 열린 동안에는 하단 바를 감춘다')
        self.assertEqual(page.evaluate('getComputedStyle(document.body).paddingBottom'), '24px')

        # 키보드가 올라온 채로 맨 아래까지 스크롤해도 바가 화면 가운데에 뜨지 않는다
        page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
        page.wait_for_timeout(250)
        self.assertFalse(page.evaluate(bar_box)['shown'], '스크롤해도 바는 그대로 감춰져 있다')
        mid = page.evaluate("""() => {
          const r = document.querySelector('#sms-mobile-bar').getBoundingClientRect();
          return r.top > 0 && r.bottom < window.innerHeight;
        }""")
        self.assertFalse(mid, '바가 화면 가운데에 떠 있지 않다')

        # 초점을 빼면 잠시 뒤 다시 보인다
        page.evaluate('document.activeElement.blur()')
        page.wait_for_timeout(240)
        self.assertFalse(page.evaluate(kbd), '초점을 빼면 kbd-open 을 푼다')
        self.assertTrue(page.is_visible('#sms-mobile-bar'))

        # 다른 입력칸으로 옮겨 다녀도 계속 감춰진다
        money = '#fields [data-prop="items"][data-idx="0"][data-money="amount"]'
        page.click(money)
        page.wait_for_timeout(180)
        self.assertTrue(page.is_hidden('#sms-mobile-bar'))
        page.evaluate('document.activeElement.blur()')
        page.wait_for_timeout(240)
        self.assertTrue(page.is_visible('#sms-mobile-bar'))

        # 화면 보이는 높이(visualViewport)만 줄어도 — 키보드·주소창 — 바를 감춘다
        page.evaluate("""() => {
          Object.defineProperty(window.visualViewport, 'height',
            { configurable: true, get: () => window.innerHeight * 0.6 });
          window.visualViewport.dispatchEvent(new Event('resize'));
        }""")
        page.wait_for_timeout(120)
        self.assertTrue(page.evaluate(kbd))
        self.assertTrue(page.is_hidden('#sms-mobile-bar'))
        page.evaluate("""() => {
          delete window.visualViewport.height;
          window.visualViewport.dispatchEvent(new Event('resize'));
        }""")
        page.wait_for_timeout(120)
        self.assertFalse(page.evaluate(kbd))
        self.assertTrue(page.is_visible('#sms-mobile-bar'))
        self.assertEqual(errors, [])
        ctx.close()

        # PC 에서는 입력칸에 초점이 가도 하단 바 규칙이 끼어들지 않는다
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(220)
        page.click('#tpl-list [data-id="t7"]')
        page.wait_for_timeout(200)
        page.click('#fields [data-prop="items"][data-idx="0"][data-key="dong"]')
        page.wait_for_timeout(150)
        self.assertFalse(page.evaluate(kbd))
        self.assertTrue(page.is_hidden('#sms-mobile-bar'))
        ctx.close()

    def test_mobile_inputs_16px_no_zoom(self):
        # 아이폰 사파리는 입력칸 글자가 16px보다 작으면 초점을 맞을 때 화면을 저절로 확대한다.
        # 모바일(≤900px)에서는 검색창·동·호·금액·퍼센트·모달 입력칸·미리보기까지 모두 16px 이상이다.
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)

        def small(tag):
            return page.evaluate("""() => [...document.querySelectorAll('input, textarea, select')]
                .filter(e => e.offsetParent !== null)
                .map(e => [e.id || e.className || e.tagName, parseFloat(getComputedStyle(e).fontSize)])
                .filter(([, f]) => f < 16)""")

        self.assertEqual(small('처음'), [], '처음 화면에 16px 미만 입력칸이 있다')
        for tid in ('t8', 't10', 't7', 't3', 't14', 't20', 't18', 't19'):
            with self.subTest(tid=tid):
                page.click('#btn-sheet')
                page.wait_for_timeout(120)
                page.click(f'#sheet-list [data-id="{tid}"]')
                page.wait_for_timeout(180)
                self.assertEqual(small(tid), [], f'{tid} 화면에 16px 미만 입력칸이 있다')
        # 설정 모달·목록 시트의 입력칸도
        page.click('#btn-settings')
        page.wait_for_timeout(200)
        self.assertEqual(small('설정'), [], '설정 모달에 16px 미만 입력칸이 있다')
        page.click('#btn-settings-close')
        page.wait_for_timeout(150)
        page.click('#btn-sheet')
        page.wait_for_timeout(200)
        self.assertEqual(small('목록 시트'), [], '목록 시트에 16px 미만 입력칸이 있다')
        self.assertEqual(errors, [])
        ctx.close()


    def test_mobile_pay_table_compact_layout(self):
        # 390×844 — 왼쪽은 라벨·(+)(−)·% 가운데 정렬, 오른쪽은 일정·금액 한 줄 + 환산 줄
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t8"]')
        page.wait_for_timeout(220)
        page.fill('#fields [data-field="price"]', '76000')
        page.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '7600')
        page.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')
        page.evaluate('document.activeElement && document.activeElement.blur()')
        page.wait_for_timeout(250)
        info = page.evaluate("""() => {
          const table = document.querySelector('#fields .paytable');
          const tb = table.getBoundingClientRect();
          const rows = [...table.querySelectorAll('.pay-row')].map(r => {
            const g = s => r.querySelector(s);
            const box = e => { const b = e.getBoundingClientRect();
              return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), t:+b.top.toFixed(1), b:+b.bottom.toFixed(1), w:+b.width.toFixed(1)}; };
            const rate = g('.pay-rate-inp'), date = g('.date-btn'), amount = g('.pay-amount input');
            const nm = g('.pay-name-text');
            const hint = g('.pay-hint');
            const col = g('.pay-name').getBoundingClientRect();
            const rowR = r.getBoundingClientRect();
            return { label: nm.textContent.trim(),
                     rate: rate ? box(rate) : null,
                     date: box(date), amount: box(amount), name: box(nm), hint: hint ? box(hint) : null,
                     nameLeft: +(nm.getBoundingClientRect().left - rowR.left).toFixed(1),
                     nameClipped: nm.scrollWidth > nm.clientWidth + 1,
                     stepsRight: +(rowR.right - g('.pay-steps').getBoundingClientRect().right).toFixed(1),
                     amountFont: parseFloat(getComputedStyle(amount).fontSize),
                     rateFont: rate ? parseFloat(getComputedStyle(rate).fontSize) : null,
                     sameRow: Math.min(date.getBoundingClientRect().bottom, amount.getBoundingClientRect().bottom)
                       - Math.max(date.getBoundingClientRect().top, amount.getBoundingClientRect().top) >= 12,
                     rateBelowName: rate ? rate.getBoundingClientRect().top >= nm.getBoundingClientRect().bottom - 0.5 : true,
                     hintUnderAmount: hint ? Math.abs(hint.getBoundingClientRect().left - amount.getBoundingClientRect().left) <= 1
                       && hint.getBoundingClientRect().top >= amount.getBoundingClientRect().bottom - 0.5 : true,
                     amountNotClipped: amount.scrollWidth <= amount.clientWidth + 1 };
          });
          const cs = getComputedStyle(table);
          const innerRight = tb.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
          const innerLeft = tb.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft);
          return { table: {l:+tb.left.toFixed(1), r:+tb.right.toFixed(1), w:+tb.width.toFixed(1)},
                   innerLeft: +innerLeft.toFixed(1), innerRight: +innerRight.toFixed(1), rows,
                   scrollW: document.documentElement.scrollWidth, winW: window.innerWidth,
                   panelRight: +document.querySelector('.form-panel').getBoundingClientRect().right.toFixed(1)};
        }""")
        self.assertLessEqual(info['scrollW'], info['winW'], '390px 가로 넘침')
        self.assertEqual([r['label'] for r in info['rows']], ['약정금', '가계약금', '계약금', '중도금', '잔금'])
        for r in info['rows']:
            with self.subTest(row=r['label']):
                self.assertGreaterEqual(r['amountFont'], 16, '금액 칸 글씨가 16px 미만')
                self.assertLessEqual(r['amount']['r'], info['panelRight'] + 0.5, '금액 칸이 패널 밖으로')
                # 이름은 행 왼쪽에 한 줄로(잘리지 않게), (+)(−) 는 행 오른쪽 끝 위
                self.assertLessEqual(r['nameLeft'], 1.5, '항목 이름이 왼쪽 정렬이 아니다')
                self.assertFalse(r['nameClipped'], f"{r['label']} 이름이 잘린다")
                self.assertLessEqual(r['stepsRight'], 1.5, '(+)(−) 가 행 오른쪽 끝에 있지 않다')
                self.assertTrue(r['amountNotClipped'], '금액이 잘린다')
                # 일정·금액은 한 줄, 오른쪽은 카드 안쪽 끝까지
                self.assertTrue(r['sameRow'], '일정과 금액이 한 줄이 아니다')
                self.assertAlmostEqual(r['amount']['r'], info['innerRight'], delta=1.0, msg='금액 칸이 카드 오른쪽 끝에 닿지 않는다')
                self.assertGreaterEqual(r['date']['l'], info['innerLeft'] + 40, msg='일정 칸은 왼쪽 % 열 다음')
                self.assertTrue(r['hintUnderAmount'], '환산 줄은 금액 칸 바로 아래')
                # 일정 칸과 금액 칸은 환산 줄이 있든 없든 위쪽 선·높이가 같다
                self.assertAlmostEqual(r['date']['t'], r['amount']['t'], delta=0.6,
                                       msg='일정 칸과 금액 칸의 위쪽이 어긋난다')
                self.assertAlmostEqual(r['date']['b'] - r['date']['t'],
                                       r['amount']['b'] - r['amount']['t'], delta=0.6,
                                       msg='일정 칸과 금액 칸의 높이가 다르다')
                if r['rate']:
                    self.assertGreaterEqual(r['rateFont'], 16, '퍼센트 칸 글씨가 16px 미만')
                    self.assertTrue(r['rateBelowName'], '퍼센트 칸이 라벨 아래줄이 아니다')
                    self.assertIn(r['label'], ('계약금', '중도금'), '비율 칸은 계약금·중도금에만')
                else:
                    self.assertIn(r['label'], ('약정금', '가계약금', '잔금'), '퍼센트가 있으면 안 되는 항목')
        # t10도 같은 다섯 항목
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t10"]')
        page.wait_for_timeout(220)
        info2 = page.evaluate("""() => {
          const rows = [...document.querySelectorAll('#fields .pay-row')].map(r => {
            const rate = r.querySelector('.pay-rate-inp'), amount = r.querySelector('.pay-amount input');
            const date = r.querySelector('.date-btn');
            return { label: r.querySelector('.pay-name-text').textContent.trim(),
                     hasRate: !!rate,
                     sameRow: Math.min(date.getBoundingClientRect().bottom, amount.getBoundingClientRect().bottom)
                       - Math.max(date.getBoundingClientRect().top, amount.getBoundingClientRect().top) >= 12 };
          });
          return { rows, scrollW: document.documentElement.scrollWidth, winW: window.innerWidth };
        }""")
        self.assertLessEqual(info2['scrollW'], info2['winW'], 't10 390px 가로 넘침')
        self.assertEqual([r['label'] for r in info2['rows']], ['약정금', '가계약금', '계약금', '중도금', '잔금'])
        for r in info2['rows']:
            with self.subTest(row='t10 ' + r['label']):
                self.assertTrue(r['sameRow'], 't10 일정·금액 한 줄')
        self.assertEqual(errors, [])
        ctx.close()

    def test_mobile_new_templates_no_overflow(self):
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844})
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        for tid in ('t16', 't3', 't17', 't18', 't19', 't20'):
            with self.subTest(tid=tid):
                page.click('#btn-sheet')
                page.wait_for_timeout(120)
                page.click(f'#sheet-list [data-id="{tid}"]')
                page.wait_for_timeout(180)
                overflow = page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                self.assertTrue(overflow, f'{tid} 모바일 가로 넘침')
        ctx.close()

    def test_pc_no_horizontal_overflow(self):
        for tid in ('t16', 't17', 't18', 't19', 't20'):
            with self.subTest(tid=tid):
                self.pick(tid)
                overflow = self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                self.assertTrue(overflow, f'{tid} PC 가로 넘침')

    def test_pc_compact_widget_layout(self):
        # 1440 모니터에서 사방에 빈 여백만 남지 않도록 최대 1400 × 880으로 넓게 채운다 (v1.4.7)
        info = self.js("""() => {
          const l = document.querySelector('.layout').getBoundingClientRect();
          const panels = [...document.querySelectorAll('.panel')].map(e => {
            const r = e.getBoundingClientRect();
            return { w: r.width, h: r.height, top: r.top, bottom: r.bottom, right: r.right };
          });
          const brand = document.querySelector('.brand').getBoundingClientRect();
          const first = document.querySelector('.panel').getBoundingClientRect();
          const last = document.querySelectorAll('.panel')[document.querySelectorAll('.panel').length - 1].getBoundingClientRect();
          return { w: l.width, h: l.height, left: l.left, right: l.right, panels,
                   brandLeft: brand.left, panelLeft: first.left, panelRight: last.right,
                   winW: window.innerWidth, winH: window.innerHeight,
                   docW: document.documentElement.scrollWidth,
                   docH: document.documentElement.scrollHeight };
        }""")
        self.assertLessEqual(info['w'], 1400.5, 'PC 컨테이너가 1400px를 넘으면 안 된다')
        self.assertGreaterEqual(info['w'], 1200, '1440 화면에서는 넓게 채워야 한다')
        self.assertLessEqual(info['h'], 880.5, '패널 높이가 880px를 넘으면 안 된다')
        self.assertGreaterEqual(info['h'], 780, '패널 높이가 780px 아래로 내려가면 안 된다')
        self.assertAlmostEqual(info['left'], info['winW'] - info['right'], delta=2, msg='가운데 정렬')
        # 상단 바의 좌우 끝선이 3단 패널의 끝선과 같다
        self.assertAlmostEqual(info['brandLeft'], info['panelLeft'], delta=1.5, msg='상단 바와 패널 왼쪽 끝선이 다르다')
        self.assertAlmostEqual(info['panelRight'], info['winW'] - info['brandLeft'], delta=1.5, msg='상단 바와 패널 오른쪽 끝선이 다르다')
        for p in info['panels']:
            self.assertLessEqual(p['bottom'], info['winH'] + 0.5, '패널이 화면 아래로 잘린다')
            self.assertLessEqual(p['right'], info['winW'] + 0.5)
            self.assertGreater(p['h'], 700)
        self.assertLessEqual(info['docW'], info['winW'])
        self.assertLessEqual(info['docH'], info['winH'])

    def test_pc_paytable_head_single_row(self):
        # 지급 일정 머리글 — '구분'과 '일정 · 금액'이 나란히 한 줄 (예전에는 '구분' 자리가 86px 빈 공간)
        self.pick('t8')
        self.wait(200)
        info = self.js("""() => {
          const head = document.querySelector('#fields .paytable-head');
          const cs = getComputedStyle(head);
          const b = e => { const r = e.getBoundingClientRect();
            return {l:+r.left.toFixed(1), r:+r.right.toFixed(1), t:+r.top.toFixed(1), b:+r.bottom.toFixed(1),
                    w:+r.width.toFixed(1), h:+r.height.toFixed(1)}; };
          const hb = b(head);
          const name = b(head.querySelector('.head-name'));
          const right = b(head.querySelector('.head-right'));
          const row = b(document.querySelector('#fields .pay-row'));
          return { dir: cs.flexDirection, head: hb, name: name, right: right, rowTop: row.t,
                   texts: [...head.querySelectorAll('span')].map(s => s.textContent) };
        }""")
        self.assertEqual(info['texts'], ['구분', '일정 · 금액'])
        self.assertEqual(info['dir'], 'row', '머리글 flex 방향이 가로가 아니다')
        self.assertLess(info['head']['h'], 26, f"머리글 높이가 커졌다 {info['head']}")
        self.assertLess(info['name']['h'], 24, f"'구분' 칸 높이가 글자 한 줄을 넘는다 {info['name']}")
        self.assertGreater(info['name']['w'], 50, "'구분' 칸이 사라졌다")
        self.assertLessEqual(info['name']['r'], info['right']['l'] + 0.5, "'일정 · 금액'이 '구분' 오른쪽에 있지 않다")
        self.assertAlmostEqual(info['name']['t'], info['right']['t'], delta=2, msg='두 머리글이 같은 줄이 아니다')
        self.assertGreater(info['rowTop'], info['head']['b'] - 0.5, '첫 항목 줄이 머리글 아래로 내려오지 않았다')

    def test_compact_layout_fits_small_desktop_window(self):
        # 1000×720 같은 작은 창에서도 빈 여백 없이 딱 맞고 잘리지 않는다
        ctx = self.browser.new_context(viewport={'width': 1000, 'height': 720})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(250)
        for tid in ('t20', 't8', 't14'):
            with self.subTest(tid=tid):
                page.click(f'#tpl-list [data-id="{tid}"]')
                page.wait_for_timeout(180)
                info = page.evaluate("""() => {
                  const l = document.querySelector('.layout').getBoundingClientRect();
                  const panels = [...document.querySelectorAll('.panel')].map(e => {
                    const r = e.getBoundingClientRect();
                    return { w: r.width, bottom: r.bottom, right: r.right };
                  });
                  return { layoutBottom: l.bottom, panels,
                           winW: window.innerWidth, winH: window.innerHeight,
                           docW: document.documentElement.scrollWidth,
                           docH: document.documentElement.scrollHeight,
                           copyVisible: !!document.querySelector('#btn-copy').offsetParent,
                           previewVisible: !!document.querySelector('#preview').offsetParent };
                }""")
                self.assertLessEqual(info['docW'], info['winW'], f'{tid} 가로 넘침')
                self.assertLessEqual(info['docH'], info['winH'], f'{tid} 세로 넘침')
                for p in info['panels']:
                    self.assertLessEqual(p['bottom'], info['winH'] + 0.5, f'{tid} 패널 잘림')
                    self.assertGreater(p['w'], 240, f'{tid} 패널이 너무 좁다')
                self.assertTrue(info['copyVisible'], f'{tid} 복사 버튼이 잘렸다')
                self.assertTrue(info['previewVisible'], f'{tid} 미리보기가 잘렸다')
        self.assertEqual(errors, [])
        ctx.close()

    # ============================================================== 화면 다듬기
    def test_list_has_no_chips_and_no_count_head(self):
        # 검색창 아래 빠른 필터 칩은 없고, 목록 머리글도 '전체 문자 · 20개' 없이 즐겨찾기부터
        self.assertEqual(self.page.query_selector_all('.quick-chips'), [])
        self.assertEqual(self.page.query_selector_all('[data-quick]'), [])
        self.assertEqual(self.page.query_selector_all('#quick-chips, #quick-chips-sheet'), [])
        heads = [h.inner_text().strip() for h in self.page.query_selector_all('#tpl-list .list-head')]
        self.assertEqual(heads, ['★ 즐겨찾기'])
        self.assertNotIn('전체 문자', self.page.inner_text('#list-panel'))
        # 검색창 바로 다음 요소가 즐겨찾기 머리글이다
        first = self.js("""() => { const s = document.querySelector('#tpl-list');
            const k = s.firstElementChild; return k ? k.className : null; }""")
        self.assertEqual(first, 'list-head')
        # 검색 중에만 '검색 결과 · N개'
        self.page.fill('#search', '중개보수')
        self.wait(120)
        heads = [h.inner_text().strip() for h in self.page.query_selector_all('#tpl-list .list-head')]
        self.assertEqual(len(heads), 1)
        rows = len(self.page.query_selector_all('#tpl-list .row'))
        self.assertEqual(heads[0], f'검색 결과 · {rows}개')
        # 단계 탭도 그대로 걸러 주고, 개수 줄은 다시 생기지 않는다
        self.page.fill('#search', '')
        self.wait(80)
        self.page.click('[data-stage="1"]')
        self.wait(120)
        self.assertEqual(len(self.page.query_selector_all('#tpl-list .row')), 5)
        self.assertNotIn('전체 문자', self.page.inner_text('#list-panel'))
        # 모바일 목록 시트에도 칩이 없다
        self.assertEqual(self.page.query_selector_all('#sheet-list .chip'), [])

    def test_center_panel_has_no_subtitle(self):
        # 가운데 편집 패널은 제목만 — 부제목(#form-desc)은 20종 모두 없다
        self.assertEqual(self.page.query_selector_all('#form-desc'), [])
        pairs = self.js("() => SMSTemplates.TEMPLATES.map(t => [t.id, t.title, t.desc])")
        for tid, title, desc in pairs:
            with self.subTest(tid=tid):
                self.pick(tid)
                head = self.page.inner_text('.form-panel .panel-head')
                self.assertIn(title, head)
                self.assertNotIn(desc, head, f'{tid} 부제목이 남아 있다')
                # 제목만 남은 제목 줄 — 제목과 '비우기' 버튼이 같은 세로 중심에 오고 위로 붙지 않는다
                pos = self.js("""() => {
                  const hb = document.querySelector('.form-panel .panel-head').getBoundingClientRect();
                  const t = document.querySelector('#form-title').getBoundingClientRect();
                  const b = document.querySelector('#btn-reset').getBoundingClientRect();
                  return {tMid: t.top + t.height / 2 - hb.top, bMid: b.top + b.height / 2 - hb.top,
                          gapTop: t.top - hb.top, gapBottom: hb.bottom - t.bottom};
                }""")
                self.assertLess(abs(pos['tMid'] - pos['bMid']), 1.0, f'{tid} 제목·비우기 버튼 세로 중심이 어긋난다')
                self.assertGreater(pos['gapTop'], 4, f'{tid} 제목이 위에 붙어 있다')
                self.assertGreater(pos['gapBottom'], 4, f'{tid} 제목이 아래에 붙어 있다')
        # 왼쪽 목록의 부제목은 그대로 둔다
        self.assertIn('예약 확정', self.page.inner_text('#tpl-list [data-id="t5"]'))

    def test_preview_panel_title(self):
        title = self.page.inner_text('.preview-panel .card-title')
        self.assertEqual(title.replace('\n', ' ').strip(), '미리보기 (직접 수정 가능)')
        self.assertNotIn('완성 문자', self.page.inner_text('.preview-panel .panel-head'))

    def test_snackbar_undo_reset(self):
        self.pick('t2')
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '402')
        self.page.fill('#fields [data-prop="prop"][data-money="amount"]', '23억')
        self.wait(120)
        self.page.click('#btn-reset')
        self.wait(120)
        self.assertIn('(금액)', self.text())
        self.assertTrue(self.page.is_visible('#snackbar'))
        self.assertIn('입력 내용을 비웠어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(200)
        self.assertIn('23억', self.text())
        self.assertEqual(self.page.input_value('#fields [data-prop="prop"][data-key="dong"]'), '402')
        self.assertFalse(self.page.is_visible('#snackbar'))

    def test_snackbar_undo_restore_text(self):
        self.pick('t6')
        original = self.text()
        self.page.fill('#preview', original + '\n주차는 지하 2층입니다')
        self.wait(150)
        self.page.click('#btn-restore')
        self.wait(150)
        self.assertNotIn('지하 2층입니다', self.text())
        self.assertIn('다시 만들었어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(200)
        self.assertIn('지하 2층입니다', self.text())

    def test_snackbar_undo_remove_property_row(self):
        self.pick('t7')
        self.page.click('#fields [data-add-item="items"]')
        self.wait(80)
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-key="dong"]', '304')
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-key="ho"]', '201')
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-money="amount"]', '90000')
        self.wait(100)
        self.page.click('#fields [data-prop-pick="items"][data-idx="1"]')
        self.wait(100)
        self.page.click('#fields [data-pick-remove="items"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)
        self.assertIn('매물 1개를 뺐어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 2)
        self.assertIn('304동 201호', self.text())

    def test_inline_hint_account(self):
        self.pick('t8')
        self.page.fill('#fields [data-field="account"]', '12')
        self.wait(150)
        hint = self.page.query_selector('#fields .field:has([data-field="account"]) .inline-hint')
        self.assertIsNotNone(hint)
        self.assertFalse(hint.is_hidden())
        self.assertIn('계좌번호를 다시 확인해 주세요', hint.inner_text())
        self.page.fill('#fields [data-field="account"]', '국민 479002-01-037629 박소미')
        self.wait(150)
        hint2 = self.page.query_selector('#fields .field:has([data-field="account"]) .inline-hint')
        self.assertTrue(hint2.is_hidden())

    def test_inline_hint_missing_rent(self):
        self.pick('t7')
        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
        self.wait(100)
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="deposit"]', '10000')
        self.wait(150)
        hint = self.page.query_selector('#fields .prop-item .inline-hint')
        self.assertFalse(hint.is_hidden())
        self.assertIn('월세를 함께 넣어 주세요', hint.inner_text())
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="rent"]', '300')
        self.wait(150)
        self.assertTrue(self.page.query_selector('#fields .prop-item .inline-hint').is_hidden())

    def test_long_press_favorites(self):
        row = self.page.query_selector('#tpl-list [data-id="t1"] .row-main')
        box = row.bounding_box()
        self.page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        self.page.mouse.down()
        self.page.wait_for_timeout(750)
        self.page.mouse.up()
        self.page.wait_for_timeout(250)
        star = self.page.query_selector('#tpl-list [data-star="t1"]')
        self.assertIn('is-on', star.get_attribute('class'))
        self.assertIn('즐겨찾기', self.page.inner_text('#toast'))
        self.assertEqual(self.page.inner_text('#form-title'), '집보기 일정 안내')

    def test_pick_remove_property_row_with_undo(self):
        # 카드 안 × 대신 ☑로 고르고 「- 선택 제거」로 뺀다 (되돌리기 가능)
        self.pick('t7')
        self.page.click('#fields [data-add-item="items"]')
        self.wait(100)
        items = self.page.query_selector_all('#fields .prop-item')
        self.assertEqual(len(items), 2)
        self.page.fill('#fields [data-prop="items"][data-idx="1"][data-key="dong"]', '304')
        self.page.click('#fields [data-prop-pick="items"][data-idx="1"]')
        self.wait(100)
        self.page.click('#fields [data-pick-remove="items"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)
        self.assertIn('매물 1개를 뺐어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 2)
        self.assertIn('304동', self.text())

    # ============================================================== 새 문자 4종
    def test_t16_myeongdan_danji_and_trade(self):
        self.pick('t16')
        body = self.text()
        self.assertIn('마포래미안푸르지오 1단지 내 마래푸중앙부동산입니다.', body)
        self.assertIn('현재 매수를 희망하시는 손님이 계셔서 연락드립니다.', body)
        self.assertIn('혹시 매도 계획이 있으시거나 고려 중이시라면', body)
        self.assertIn('단지 특성과 거래 상황을 살펴 손님께 성실히 안내하겠습니다.', body)
        # 서명은 늘 맨 아래에 들어간다
        self.assertTrue(body.endswith('마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'), body)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0)

        # 단지 버튼은 없애고 문구는 1단지로 고정 — 거래 유형만 고른다
        self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="danji"]')), 0, '단지 선택 버튼은 없다')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="danji"]')), 0, '단지 직접 입력칸도 없다')

        # 전세는 전세/임대 말로 바뀐다
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(120)
        body = self.text()
        self.assertIn('현재 전세를 희망하시는 손님이 계셔서', body)
        self.assertIn('혹시 전세 임대 계획이 있으시거나', body)
        self.assertIn('조건에 맞는 손님과 좋은 거래로 이어질 수 있도록 노력하겠습니다.', body)

        # 종별을 바꿔도 서명은 그대로 맨 아래에 있다
        body = self.text()
        self.assertIn('조건에 맞는 손님과 좋은 거래로 이어질 수 있도록 노력하겠습니다.', body)
        self.assertIn('010-4585-7365', body)
        self.assertTrue(body.endswith('010-4585-7365 / 02-312-7365'))

    def test_t3_simple_and_detail_switch(self):
        # 집보기 문의 — [소유자][중개사] [간단][상세] 네 조합
        self.pick('t3')
        body = self.text()
        self.assertIn('매수 손님이 계셔서 집보기 가능 여부를 여쭙습니다.', body)
        self.assertIn('- 희망 일시 : (방문 일시)', body)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="times"]')), 0)
        self.assertEqual(self.js("""() => [...document.querySelectorAll('#fields .segs .seg-btn')]
            .map(b => b.textContent.trim())"""), ['소유자', '중개사', '간단', '상세'], '버전 네 칸')

        # 달력으로 일시를 고르면 24시간 표기로 들어간다
        self.page.click('#fields [data-date="when"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-day="26"]')
        self.wait(120)
        self.pick_time('#calpop', None, '9', '30')
        self.page.click('#calpop [data-cal-close]')
        body = self.text()
        self.assertIn('- 희망 일시 : 11월 26일 (목) 09:30', body)
        self.assertNotIn('(방문 일시)', body)

        # 매물 카드의 거래 유형으로 전세 / 월세 손님
        self.page.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        self.wait(120)
        self.assertIn('월세 손님이 계셔서', self.text())

        # 상세 버전으로 바꾸면 날짜칸·시간칸·초기화/저장만 있는 방문 희망 시간이 나온다
        self.page.click('#fields [data-seg="view"][data-value="detail"]')
        self.wait(120)
        self.assertIsNotNone(self.page.query_selector('#fields .time-box [data-date="times__range"]'))
        self.assertEqual(self.js("() => document.querySelectorAll('#fields .time-box textarea').length"), 0)
        body = self.text()
        self.assertIn('월세 손님께서 집보기를 희망하셔서', body)
        self.assertIn('- 방문 희망 시간 : (방문 희망 시간)', body)

        # 중개사 버전 — 공동중개로 여쭙는 문구
        self.page.click('#fields [data-seg="view"][data-value="simple"]')
        self.wait(120)
        self.page.click('#fields [data-seg="who"][data-value="coagent"]')
        self.wait(120)
        body = self.text()
        self.assertIn('사장님, 안녕하세요', body)
        self.assertIn('공동중개 및 집보기 가능 여부', body)
        self.assertIn('- 희망 일시 : 11월 26일 (목) 09:30', body)
        # 다시 소유자로 돌아와도 고른 일시는 남아 있다
        self.page.click('#fields [data-seg="who"][data-value="owner"]')
        self.wait(120)
        self.assertIn('- 희망 일시 : 11월 26일 (목) 09:30', self.text())

    def test_t17_thanks_variants(self):
        counts = self.js("""() => Object.keys(SMSTemplates.VARIANTS).map(k => SMSTemplates.VARIANTS[k].length)""")
        self.assertEqual(counts, [7, 7, 7])
        self.pick('t17')
        first = self.text()
        self.assertIn('감사', first)
        self.assertIn('1 / 7', self.page.inner_text('#fields .field.is-variant'))
        # 🎲 다른 문구 → 다음 문구로 바뀐다
        seen = {first}
        for i in range(6):
            self.page.click('#fields [data-action="vary"]')
            self.wait(90)
            seen.add(self.text())
        self.assertEqual(len(seen), 7, '7종이 모두 나와야 한다')
        self.assertIn('7 / 7', self.page.inner_text('#fields .field.is-variant'))
        self.page.click('#fields [data-action="vary"]')
        self.wait(90)
        self.assertEqual(self.text(), first, '7종을 돌면 처음 문구로 돌아온다')
        # 대상별로 문구가 다르다
        owner_list = self.js('() => SMSTemplates.VARIANTS.resident')
        coagent_list = self.js('() => SMSTemplates.VARIANTS.coagent')
        guest_list = self.js('() => SMSTemplates.VARIANTS.guest')
        self.page.click('#fields [data-seg="target"][data-value="coagent"]')
        self.wait(120)
        body = self.text()
        self.assertTrue(any(v.split('\n')[0] in body for v in coagent_list), body)
        self.assertFalse(any(v.split('\n')[0] in body for v in owner_list), body)
        self.assertIn('1 / 7', self.page.inner_text('#fields .field.is-variant'))
        self.page.click('#fields [data-seg="target"][data-value="guest"]')
        self.wait(120)
        body = self.text()
        self.assertTrue(any(v.split('\n')[0] in body for v in guest_list), body)
        self.assertIn('/', self.page.inner_text('#fields .field.is-variant'))
        # 안부 — [교체 1/7] 옆에 여섯 칩(날씨·아침·저녁·주말·연휴·명절), 하나만 골립니다
        self.assertEqual(self.js("""() => [...document.querySelectorAll('#fields .variant-row .chip')]
            .map(b => b.textContent.trim())"""), ['날씨', '아침', '저녁', '주말', '연휴', '명절'])
        self.assertIn('교체', self.page.inner_text('#fields .variant-row .action-btn'))
        self.page.click('#fields [data-greet="weather"]')
        self.wait(120)
        self.assertIn('날씨가 제법 쌀쌀하네요. 감기 조심하시고 따뜻한 하루 보내세요!', self.text())
        # 다른 칩을 누르면 앞의 것은 풀리고 하나만 남는다 (주말/연휴/명절 문구는 섞이지 않는다)
        self.page.click('#fields [data-greet="weekend"]')
        self.wait(120)
        body = self.text()
        self.assertIn('즐거운 주말 보내세요', body)
        self.assertNotIn('날씨가 제법 쌀쌀하네요. 감기 조심하시고 따뜻한 하루 보내세요!', body)
        self.assertEqual(self.js("""() => [...document.querySelectorAll('#fields .variant-row .chip.is-on')]
            .map(b => b.textContent.trim())"""), ['주말'])
        self.page.click('#fields [data-greet="holiday"]')
        self.wait(120)
        body = self.text()
        self.assertIn('모처럼의 연휴, 여유롭고 즐거운 시간 보내세요!', body)
        self.assertNotIn('즐거운 주말 보내세요', body)
        self.page.click('#fields [data-greet="holiday2"]')
        self.wait(120)
        body = self.text()
        self.assertIn('가족분들과 함께 웃음 가득하고 따뜻한 명절 보내세요!', body)
        self.assertNotIn('즐거운 연휴 보내세요', body)
        # 고른 칩을 다시 누르면 해제
        self.page.click('#fields [data-greet="holiday2"]')
        self.wait(120)
        self.assertNotIn('가족분들과 함께 웃음 가득하고 따뜻한 명절 보내세요!', self.text())
        # 문구를 돌려도 서명은 늘 맨 아래에 붙고 토글은 없다
        self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0)
        self.assertTrue(self.text().endswith('마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'))

    def test_t18_coagent_decline_amounts(self):
        self.pick('t18')
        body = self.text()
        self.assertIn('매수 의사가 분명한 손님이 계셔서 조건에 맞는 매물 문의드립니다.', body)
        self.assertIn('- 매매 희망금액 : (금액)까지', body)
        # 고객 특징은 빈 칸으로 시작한다 (v1.4.4)
        self.assertIn('- 고객 참고사항 : (고객 특징)', body)
        self.page.fill('#fields [data-field="guestNote"]', '염리초 보내고 싶은 학부모입니다')
        self.wait(150)
        self.assertIn('염리초 보내고 싶은 학부모입니다', self.text())
        self.page.fill('#fields [data-field="amount"]', '90000')
        self.wait(150)
        self.assertIn('- 매매 희망금액 : 9억까지', self.text())
        self.assertIn('(9억)', self.page.inner_text('#fields'))
        # 거래유형·금액·입주일이 공통 금액박스 하나에 들어 있고, 평형 칸은 없다
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="area"]')), 0,
                         '평형 칸은 없앴다')
        self.assertEqual(len(self.page.query_selector_all('#fields .deal-box, #fields .is-deal-box')), 1,
                         '공통 금액박스로 묶는다')
        self.assertEqual(self.page.inner_text('#fields .field-label').strip(), '조건')
        # 입주 — 협의를 고르면 입력칸 없이 '즉시입주(협의)'로 나간다
        self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
        self.wait(150)
        self.assertIn('- 입주 : 즉시입주(협의)', self.text())

        # 전세 — 보증금 한 칸
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(150)
        body = self.text()
        self.assertIn('전세 매물을 찾는 손님이 계셔서 문의드립니다.', body)
        self.assertIn('- 전세 보증금 : 9억까지', body, '매매에서 적은 금액을 그대로 쓴다')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 0,
                         '전세에는 월차임 칸이 없다')
        self.page.fill('#fields [data-field="amount"]', '70000')
        self.wait(150)
        self.assertIn('- 전세 보증금 : 7억까지', self.text())

        # 월세 — 보증금 + 월차임 두 칸
        self.page.click('#fields [data-seg="trade"][data-value="월세"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 1)
        self.page.fill('#fields [data-field="deposit"]', '10000')
        self.page.fill('#fields [data-field="rent"]', '250')
        self.wait(200)
        self.assertIn('- 보증금 : 1억\n- 월세 : 250만 원까지', self.text())
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="area"]')), 0,
                         '임대 조건에는 평형 칸이 없다')


    def test_t19_promo_property_block_and_type_info(self):
        # 특가 매물 홍보 — 추천 매물 안내와 같은 매물 블록 + 강조 문구, 타입·방향 칸은 없다
        self.pick('t19')
        fields = self.page.inner_text('#fields')
        self.assertIn('강조 문구', fields)
        self.assertIn('+ 매물 추가', fields)
        for gone in ('단지·층', '평형', '빠르게', '자동 변환', '타입·방향'):
            self.assertNotIn(gone, fields)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-action="promoUnit"]')), 0)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-key="typeInfo"]')), 0,
                         '타입·방향 칸은 없앴다')
        # 매물 블록은 추천 매물 안내(t7)와 같은 칸을 쓴다
        self.pick('t7')
        t7_fields = self.js("() => [...document.querySelectorAll('#fields [data-key]')].map(e => e.dataset.key)")
        self.pick('t19')
        t19_fields = self.js("() => [...document.querySelectorAll('#fields [data-key]')].map(e => e.dataset.key)")
        self.assertEqual(t7_fields, t19_fields, '매물 칸 구성이 같다')
        self.assertEqual(t19_fields, ['complex', 'dong', 'ho'], '단지·동·호 세 칸만')
        self.assertIn('🔑 매물 : (매물)\n🔑 거래조건 : (가격)\n✔️ 특징 : (강조 문구)', self.text())
        self.page.fill('#fields [data-field="emphasis"]', '최저가 조율 가능합니다')
        self.wait(150)
        self.assertIn('🔑 매물 : (매물)\n🔑 거래조건 : (가격)\n✔️ 특징 : 최저가 조율 가능합니다', self.text())
        self.assertIn('마포래미안푸르지오 매매 특가 매물 안내드립니다.', self.text())

        # 동·호수를 넣어도 평형·타입·방향 줄이 붙지 않는다 (마래푸밖에 없는 정보)
        dong = '#fields [data-prop="items"][data-idx="0"][data-key="dong"]'
        ho = '#fields [data-prop="items"][data-idx="0"][data-key="ho"]'
        self.page.fill(dong, '205')
        self.page.fill(ho, '1203')
        self.wait(180)
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '210000')
        self.wait(200)
        body = self.text()
        self.assertIn('🔑 매물 : 마포래미안푸르지오 205동 1203호', body)
        self.assertNotIn('34평', body)
        self.assertNotIn('동향', body)
        self.assertNotIn('84E', body)
        self.assertIn('🔑 거래조건 : 매매 21억\n✔️ 특징 : 최저가 조율 가능합니다', body)

        # [단지]로 가려도 호수 칸·배지는 살아 있고, 동·호만 따라온다
        self.page.click('#fields [data-prop-unit="dong"]')
        self.wait(150)
        self.assertIn('🔑 매물 : 마포래미안푸르지오 2단지 1203호', self.text())
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(150)
        self.assertIn('🔑 매물 : 마포래미안푸르지오 2단지 12층', self.text())

        # 강조 문구 · 거래 유형은 매물 줄에서 고른다
        self.page.fill('#fields [data-field="emphasis"]', '급매로 조율 가능합니다')
        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="전세"]')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '115000')
        self.wait(200)
        body = self.text()
        self.assertIn('마포래미안푸르지오 전세 특가 매물 안내드립니다.', body)
        self.assertIn('🔑 거래조건 : 전세 11억 5천만\n✔️ 특징 : 급매로 조율 가능합니다', body)


    def test_t19_promo_other_complex_has_no_type_info(self):
        # 다른 단지 이름을 넣어도 마래푸 타입표를 쓰지 않는다 (타입·방향 줄 자체가 없다)
        self.pick('t19')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="complex"]', '이편한세상신촌')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '205')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '1203')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-key="typeInfo"]')), 0)
        self.assertIn('이편한세상신촌 205동 1203호', self.text())

    def test_maraepu_unit_table(self):
        # 엑셀 동호수 타입표(1~4단지 동·라인)를 그대로 읽는다
        cases = [
            (('마포래미안푸르지오', '102', '1103'), '34평 84C · 남서향'),
            (('마래푸', '205', '1203'), '34평 84E · 동향'),
            (('마포래미안푸르지오', '302', '1502'), '24평 59A · 동향'),
            (('마포래미안푸르지오 2단지', '413', '1905'), '34평 84A · 남서향'),
            # 표에 없는 동·라인·임대 동·다른 단지
            (('마포래미안푸르지오', '201', '1203'), ''),
            (('마포래미안푸르지오', '102', '1108'), ''),
            (('마포래미안푸르지오', '999', '1103'), ''),
            (('이편한세상신촌', '102', '1103'), ''),
            (('마포래미안푸르지오', '', '1103'), ''),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(self.js('(a) => SMSCore.maraepuUnit(a[0], a[1], a[2])', list(args)), want)


    def test_t20_vendor_contacts(self):
        # 2차 수정본: 협력업체 44명이 기본으로 들어 있고, 고른 사람만 문자에 들어간다
        self.pick('t20')
        body = self.text()
        self.assertIn('부동산 대출 상담을 받아보실 수 있는 상담사를 소개드립니다.', body)
        self.assertIn('마래푸중앙부동산 소개로 연락하셨다고 말씀해 주시면 됩니다.', body)
        # 기본 명단 — 대출 33 · 세무사 1 · 법무사 1 · 인테리어 2 · 입주청소 5 · 이사 2 = 44명
        defaults = self.js("() => Object.entries(SMSTemplates.DEFAULT_CONTACTS).map(([k, v]) => [k, v.length])")
        self.assertEqual(defaults, [['대출', 33], ['세무사', 1], ['법무사', 1], ['인테리어', 2], ['입주청소', 5], ['이사', 2]])
        names = self.js("""() => [...document.querySelectorAll('#fields .contact-list .contact:not(.is-new) input[data-contact-edit=\\"name\\"]')].map(e => e.value)""")
        self.assertEqual(len(names), 33, '대출 33명이 화면에 다 보인다')
        for want in ('국민 대출 김동준', '신한 대출 안종미', '삼성생명 대출 박재영'):
            self.assertIn(want, names)
        # 아무도 고르지 않으면 이름·연락처 자리만 남는다
        self.assertIn('- 이름 : (상담사/업체 이름)\n- 연락처 : (전화번호)', body)

        # 한 명을 고르면 그 사람만 문자에 들어간다
        idx = names.index('신한 대출 안종미')
        rows = self.page.query_selector_all('#fields .contact-list .contact:not(.is-new)')
        rows[idx].query_selector('.contact-check').click()
        self.wait(150)
        body = self.text()
        self.assertIn('- 이름 : 신한 대출 안종미\n- 연락처 : 010-4757-2152', body)
        self.assertNotIn('국민 대출 김동준', body)

        # 분야를 바꾸면 도입 문구·명단이 바뀐다
        self.page.click('#fields [data-seg="vendorCat"][data-value="법무사"]')
        self.wait(120)
        body = self.text()
        self.assertIn('소유권이전등기, 근저당권 말소 등 등기 업무를 상담받아 보실 수 있는 법무사를 소개드립니다.', body)
        self.assertEqual(len(self.page.query_selector_all('#fields .contact-list .contact:not(.is-new)')), 1)

        # 업체(인테리어·입주청소·이사)는 '업체명'으로 나간다
        self.page.click('#fields [data-seg="vendorCat"][data-value="이사"]')
        self.wait(150)
        self.page.query_selector_all('#fields .contact-list .contact:not(.is-new)')[0].query_selector('.contact-check').click()
        self.wait(150)
        body = self.text()
        self.assertIn('- 업체명 : 소원아빠 이사\n- 연락처 : 010-9248-4484', body)

        # 새 연락처 추가 → 바로 문자에 들어가고, 새로 고쳐도 남아 있다
        self.page.fill('#fields [data-contact-new="name"]', '박이사 이사')
        self.page.fill('#fields [data-contact-new="phone"]', '01098765432')
        self.page.click('#fields [data-contact-add]')
        self.wait(200)
        body = self.text()
        self.assertIn('- 업체명 : 박이사 이사\n- 연락처 : 010-9876-5432', body)
        self.assertIn('연락처를 추가했어요', self.page.inner_text('#toast'))
        self.wait(400)
        self.page.reload(wait_until='networkidle')
        self.wait(250)
        self.assertEqual(self.page.inner_text('#form-title'), '전문가·협력업체 소개')
        body = self.text()
        self.assertIn('박이사 이사', body)
        # 다시 불러와도 기본 명단이 겹쳐 들어가지 않는다
        contacts = self.js("() => JSON.parse(localStorage.getItem('smshelper.v1')).contacts")
        self.assertEqual(len(contacts['이사']), 3, '기본 2 + 추가 1')
        self.assertEqual(len(contacts['대출']), 33, '기본 33명 그대로')

        # 지우면 문자에서도 빠지고 되돌리기 된다 (★ 즐겨찾기는 위로 올라가므로 이름으로 찾는다)
        rows = self.page.query_selector_all('#fields .contact-list .contact:not(.is-new)')
        target = [r for r in rows if r.query_selector('input[data-contact-edit="name"]').input_value() == '박이사 이사'][0]
        target.query_selector('[data-contact-del]').click()
        self.wait(150)
        self.assertNotIn('박이사 이사', self.text())
        self.assertIn('연락처를 지웠어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(250)
        self.assertIn('박이사 이사', self.text())

        # 분야별로 따로 저장된다
        self.page.click('#fields [data-seg="vendorCat"][data-value="대출"]')
        self.wait(150)
        contacts = self.js("() => JSON.parse(localStorage.getItem('smshelper.v1')).contacts")
        self.assertEqual(len(contacts['대출']), 33)
        self.assertEqual(len(contacts['법무사']), 1)

    def test_t20_default_contacts_seed_into_saved_empty_list(self):
        # 예전 버전에서 빈 연락처가 저장돼 있어도 기본 44명이 빠짐없이 보인다
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't20', 'stage': 'all',
            'contacts': {'대출': [], '세무사': [], '법무사': [], '인테리어': [], '입주청소': [], '이사': []},
            'data': {'t20': {'mode': 'ho', 'vendorCat': '대출', 'vendorSel': {}}}
        })
        names = page.evaluate("""() => [...document.querySelectorAll('#fields .contact-list .contact:not(.is-new) input[data-contact-edit=\\"name\\"]')].map(e => e.value)""")
        self.assertEqual(len(names), 33, '빈 저장값이어도 기본 대출 33명이 보인다')
        saved = page.evaluate("() => JSON.parse(localStorage.getItem('smshelper.v1'))")
        self.assertEqual(len(saved['contacts']['대출']), 33)
        self.assertEqual(saved.get('contactsSeed'), 'v1.4.3')
        # 한 번 합친 뒤에는 지운 사람이 다시 살아나지 않는다 (합침 표시가 남아 있으므로)
        first = page.query_selector_all('#fields .contact-list .contact:not(.is-new)')[0]
        first.query_selector('[data-contact-del]').click()
        page.wait_for_timeout(300)
        left = page.evaluate("() => JSON.parse(localStorage.getItem('smshelper.v1')).contacts['대출'].length")
        self.assertEqual(left, 32, '지운 사람은 저장값에서 빠진다')
        self.assertEqual(page.evaluate("() => JSON.parse(localStorage.getItem('smshelper.v1')).contactsSeed"), 'v1.4.3')
        ctx.close()

    def test_vendor_contact_list_three_on_phone_more_on_pc(self):
        # 폰은 지금처럼 3개 높이만, PC는 목록 버튼 없이 6~8줄이 시원하게 보인다 (v1.4.7)
        self.pick('t20')
        self.page.click('#fields [data-seg="vendorCat"][data-value="법무사"]')
        self.wait(150)
        for i in range(8):
            self.page.fill('#fields [data-contact-new="name"]', '상담사%d' % (i + 1))
            self.page.fill('#fields [data-contact-new="phone"]', '010-1234-567%d' % i)
            self.page.click('#fields [data-contact-add]')
            self.wait(140)
        pc = self.js("""() => {
          const l = document.querySelector('#fields .contact-list');
          const items = [...l.querySelectorAll('.contact')];
          const h = items[0].getBoundingClientRect().height;
          const gap = parseFloat(getComputedStyle(l).rowGap || 6) || 6;
          const lb = l.getBoundingClientRect();
          const visible = items.filter(e => { const r = e.getBoundingClientRect();
            return r.top >= lb.top - 1 && r.bottom <= lb.bottom + 1; }).length;
          return { count: items.length, itemH: h, gap: gap, client: l.clientHeight, scroll: l.scrollHeight,
                   visible: visible, overflow: getComputedStyle(l).overflowY };
        }""")
        self.assertEqual(pc['count'], 10, '기본 1 + 추가 8 + 새 업체 한 줄')
        self.assertEqual(pc['overflow'], 'auto')
        self.assertGreaterEqual(pc['visible'], 6, f"PC에서는 6줄 이상 보여야 한다 {pc}")
        self.assertLessEqual(pc['visible'], 10, f"PC에서 너무 많이 보인다 {pc}")
        self.assertGreater(pc['client'], 300, f"PC에서는 3줄 높이(152)에 갈히지 않는다 {pc}")
        self.assertGreater(pc['scroll'], pc['client'] + 20, '업체가 10개면 넘쳐야 한다')
        # PC에서는 목록 버튼 대신 각 줄의 ★로 바로 즐겨찾기를 켜고 끈다
        self.assertTrue(self.page.query_selector('#btn-vendor-list').is_hidden(), 'PC에는 목록 버튼이 없다')
        stars = self.page.query_selector_all('#fields .contact-fav')
        self.assertEqual(len(stars), 9, 'PC 폼의 모든 업체 줄에 ★가 있다')
        self.assertTrue(self.js("() => [...document.querySelectorAll('#fields .contact-fav')]"
                                ".every(s => s.offsetParent !== null && s.getBoundingClientRect().width > 10)"),
                        'PC 폼의 ★가 보이지 않는다')

        # ★를 누르면 그 업체가 ★ 무리로 올라가고, 보던 스크롤 자리는 그대로
        self.page.evaluate("() => { document.querySelector('#fields .contact-list').scrollTop = 90; }")
        self.wait(80)
        before_top = self.js("() => document.querySelector('#fields .contact-list').scrollTop")
        self.assertGreater(before_top, 0)
        picked = self.js("""() => {
          const row = [...document.querySelectorAll('#fields .contact:not(.is-new)')]
            .find(c => !c.querySelector('.contact-fav').classList.contains('is-on'));
          return row ? row.querySelector('.contact-inp').value : null;
        }""")
        self.assertTrue(picked, '★ 안 된 업체가 있어야 한다')
        self.page.evaluate("""() => {
          const row = [...document.querySelectorAll('#fields .contact:not(.is-new)')]
            .find(c => !c.querySelector('.contact-fav').classList.contains('is-on'));
          row.querySelector('.contact-fav').click();
        }""")
        self.wait(250)
        after = self.js("""() => {
          const l = document.querySelector('#fields .contact-list');
          const rows = [...l.querySelectorAll('.contact:not(.is-new)')];
          const favs = rows.map(c => c.querySelector('.contact-fav').classList.contains('is-on'));
          return { names: rows.map(c => c.querySelector('.contact-inp').value), favs: favs,
                   favCount: favs.filter(Boolean).length, scrollTop: l.scrollTop };
        }""")
        self.assertEqual(after['names'].index(picked), 0, '★한 업체가 맨 위로')
        self.assertEqual(after['favs'], [True] * after['favCount'] + [False] * (len(after['favs']) - after['favCount']),
                         '★한 업체가 ★ 무리에 모여 있다')
        self.assertAlmostEqual(after['scrollTop'], before_top, delta=1, msg='★를 누르면 스크롤이 맨 위로 튄다')

        # 폰은 그대로 3개 높이 + 목록 창으로
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t20"]')
        page.wait_for_timeout(220)
        page.click('#fields [data-seg="vendorCat"][data-value="법무사"]')
        page.wait_for_timeout(150)
        for i in range(4):
            page.fill('#fields [data-contact-new="name"]', '상담사%d' % (i + 1))
            page.fill('#fields [data-contact-new="phone"]', '010-1234-567%d' % i)
            page.click('#fields [data-contact-add]')
            page.wait_for_timeout(140)
        info = page.evaluate("""() => {
          const l = document.querySelector('#fields .contact-list');
          const items = [...l.querySelectorAll('.contact')];
          const hs = items.map(e => e.getBoundingClientRect().height);
          const lb = l.getBoundingClientRect();
          const last = items[3].getBoundingClientRect();
          return { count: items.length, itemH: hs[0], client: l.clientHeight, scroll: l.scrollHeight,
                   overflow: getComputedStyle(l).overflowY, lastBelow: last.bottom > lb.bottom - 1,
                   thirdSeen: items[2].getBoundingClientRect().top < lb.bottom - 1,
                   visible: items.filter(e => { const r = e.getBoundingClientRect();
                     return r.top >= lb.top - 1 && r.bottom <= lb.bottom + 1; }).length };
        }""")
        self.assertEqual(info['count'], 6, '기본 1 + 추가 4 + 새 업체 한 줄')
        self.assertEqual(info['overflow'], 'auto')
        self.assertGreater(info['scroll'], info['client'] + 20, '업체가 4개면 넘쳐야 한다')
        self.assertLessEqual(info['client'], 153, '폰은 지금처럼 3줄 높이(152px) 그대로')
        self.assertTrue(info['thirdSeen'], '3번째 업체는 보여야 한다')
        self.assertLessEqual(info['visible'], 3, '폰에서는 3개보다 많이 보이면 안 된다')
        self.assertGreater(info['scroll'], info['client'] + 40, '목록 안에서만 넘친다')
        # 폰에서는 목록 버튼이 보이고, 여전히 목록 창으로 연다
        self.assertFalse(page.query_selector('#btn-vendor-list').is_hidden(), '폰에는 목록 버튼이 있다')
        self.assertTrue(page.query_selector('#fields .contact-fav').is_hidden(), '폰 폼에는 ★가 없다')
        self.assertEqual(errors, [])
        ctx.close()

    def _center(self, sel):
        box = self.page.query_selector(sel).bounding_box()
        return (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)

    def test_vendor_modal_star_sort_and_scroll_kept(self):
        # 폰 목록 창 — ★한 업체가 맨 위로 오고, ★·삭제 뒤에도 보던 스크롤 자리가 그대로 (v1.4.7)
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t20"]')
        page.wait_for_timeout(220)
        page.click('#fields [data-seg="vendorCat"][data-value="법무사"]')
        page.wait_for_timeout(150)
        for i in range(8):
            page.fill('#fields [data-contact-new="name"]', '업체%d' % (i + 1))
            page.fill('#fields [data-contact-new="phone"]', '010-2222-33%02d' % i)
            page.click('#fields [data-contact-add]')
            page.wait_for_timeout(130)
        page.click('#btn-vendor-list')
        page.wait_for_timeout(250)
        # 새로 추가한 업체는 ★ 켜진 채라 이미 위로 정렬 — 기본 업체 하나에 ★를 켜 본다
        info = page.evaluate("""() => {
          const l = document.querySelector('#vendor-list-body .contact-list');
          const rows = [...l.querySelectorAll('.contact:not(.is-new)')];
          return { scroll: l.scrollHeight, client: l.clientHeight, top: l.scrollTop,
                   names: rows.map(c => c.querySelector('.contact-inp').value),
                   favs: rows.map(c => c.querySelector('.contact-star').classList.contains('is-on')) };
        }""")
        self.assertGreater(info['scroll'], info['client'] + 20, '목록 창이 넘쳐야 한다')
        self.assertEqual(info['favs'][:6], [True] * 6, '★한 업체가 먼저 보인다')
        self.assertEqual(info['names'].index('업체8'), 7, '★끼리는 저장 순서 그대로')
        # 중간으로 스크롤해서 기본 업체에 ★를 켜면 그 업체가 맨 위로, 스크롤은 그 자리에
        page.evaluate("() => { document.querySelector('#vendor-list-body .contact-list').scrollTop = 140; }")
        page.wait_for_timeout(100)
        before = page.evaluate("() => document.querySelector('#vendor-list-body .contact-list').scrollTop")
        self.assertGreater(before, 0)
        page.evaluate("""() => {
          const rows = [...document.querySelectorAll('#vendor-list-body .contact:not(.is-new)')];
          const row = rows.find(c => !c.querySelector('.contact-star').classList.contains('is-on'));
          window.__pickedFav = row.querySelector('.contact-inp').value;
          row.querySelector('.contact-star').click();
        }""")
        page.wait_for_timeout(300)
        after = page.evaluate("""() => {
          const l = document.querySelector('#vendor-list-body .contact-list');
          const rows = [...l.querySelectorAll('.contact:not(.is-new)')];
          const names = rows.map(c => c.querySelector('.contact-inp').value);
          const favs = rows.map(c => c.querySelector('.contact-star').classList.contains('is-on'));
          return { scrollTop: l.scrollTop, index: names.indexOf(window.__pickedFav),
                   favCount: favs.filter(Boolean).length,
                   grouped: favs.every((f, i) => f === (i < favs.filter(Boolean).length)) };
        }""")
        self.assertLess(after['index'], after['favCount'], '★한 업체가 ★ 무리에 모인다')
        self.assertTrue(after['grouped'], '★한 업체가 위로 모여 있어야 한다')
        self.assertEqual(after['favCount'], 9)
        self.assertAlmostEqual(after['scrollTop'], before, delta=1, msg='★ 토글 뒤 스크롤이 맨 위로 튄다')
        # 지워도 스크롤은 그 자리에
        page.evaluate("() => { document.querySelector('#vendor-list-body .contact-list').scrollTop = 120; }")
        page.wait_for_timeout(100)
        before_del = page.evaluate("() => document.querySelector('#vendor-list-body .contact-list').scrollTop")
        page.evaluate("""() => {
          const rows = [...document.querySelectorAll('#vendor-list-body .contact:not(.is-new)')];
          rows[rows.length - 2].querySelector('[data-vl-del]').click();
        }""")
        page.wait_for_timeout(350)
        self.assertAlmostEqual(
            page.evaluate("() => document.querySelector('#vendor-list-body .contact-list').scrollTop"),
            before_del, delta=2, msg='삭제 뒤 스크롤이 맨 위로 튄다')
        self.assertEqual(errors, [])
        ctx.close()

    def test_list_star_keeps_scroll(self):
        # 전체 문자 목록에서 ★를 눌러도 스크롤이 맨 위로 튄지 않는다 (PC 왼쪽 목록 · 폰 시트)
        ctx = self.browser.new_context(viewport={'width': 1280, 'height': 620})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(250)
        base = page.evaluate("""() => {
          const l = document.querySelector('#tpl-list');
          return { scroll: l.scrollHeight, client: l.clientHeight };
        }""")
        self.assertGreater(base['scroll'], base['client'] + 30, '목록이 넘쳐야 검사가 의미 있다')
        page.evaluate("() => { document.querySelector('#tpl-list').scrollTop = 150; }")
        page.wait_for_timeout(100)
        before = page.evaluate("() => document.querySelector('#tpl-list').scrollTop")
        self.assertGreater(before, 0)
        page.evaluate("() => document.querySelector('#tpl-list [data-star=\"t17\"]').click()")
        page.wait_for_timeout(300)
        after = page.evaluate("""() => {
          const l = document.querySelector('#tpl-list');
          return { scrollTop: l.scrollTop,
                   favHeads: [...l.querySelectorAll('.list-head')].map(e => e.textContent),
                   favFirst: l.querySelector('[data-star="t17"]').classList.contains('is-on') };
        }""")
        self.assertTrue(after['favFirst'], '★가 켜져야 한다')
        self.assertIn('★ 즐겨찾기', after['favHeads'])
        self.assertAlmostEqual(after['scrollTop'], before, delta=1, msg='PC 목록 ★ 토글에 스크롤이 튄다')
        ctx.close()

        # 폰 — 목록 시트에서도 같은 방식으로
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(250)
        page.click('#btn-sheet')
        page.wait_for_timeout(200)
        page.evaluate("() => { document.querySelector('#sheet-list').scrollTop = 120; }")
        page.wait_for_timeout(100)
        before = page.evaluate("() => document.querySelector('#sheet-list').scrollTop")
        self.assertGreater(before, 0)
        page.evaluate("() => document.querySelector('#sheet-list [data-star=\"t15\"]').click()")
        page.wait_for_timeout(300)
        after = page.evaluate("""() => ({ scrollTop: document.querySelector('#sheet-list').scrollTop,
            on: document.querySelector('#sheet-list [data-star="t15"]').classList.contains('is-on'),
            open: document.querySelector('#sheet').classList.contains('is-open') })""")
        self.assertTrue(after['on'], '시트에서도 ★가 켜진다')
        self.assertTrue(after['open'], '시트는 열린 채')
        self.assertAlmostEqual(after['scrollTop'], before, delta=1, msg='목록 시트 ★ 토글에 스크롤이 튄다')
        self.assertEqual(errors, [])
        ctx.close()

    def test_t20_contact_requires_name_and_phone(self):
        self.pick('t20')
        self.page.fill('#fields [data-contact-new="name"]', '')
        self.page.click('#fields [data-contact-add]')
        self.wait(150)
        self.assertIn('이름을 먼저 넣어 주세요', self.page.inner_text('#toast'))
        self.page.fill('#fields [data-contact-new="name"]', '전화없는 상담사')
        self.page.fill('#fields [data-contact-new="phone"]', '12')
        self.page.click('#fields [data-contact-add]')
        self.wait(150)
        self.assertIn('전화번호를 확인해 주세요', self.page.inner_text('#toast'))
        contacts = self.js("() => JSON.parse(localStorage.getItem('smshelper.v1')).contacts")
        self.assertEqual(len(contacts.get('대출') or []), 33, '잘못된 입력은 저장되지 않고 기본 33명 그대로다')

    # ============================================================== URL로 값 넘기기
    def open_with_query(self, query):
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.goto(BASE + '?' + query, wait_until='networkidle')
        page.wait_for_timeout(250)
        return ctx, page

    def test_url_params_property_and_price(self):
        q = 'template=t7&complex=' + quote('마포래미안푸르지오') + '&dong=208&ho=1103&dealType=전세&price=11.5억'
        ctx, page = self.open_with_query(q)
        body = page.input_value('#preview')
        self.assertIn('마포래미안푸르지오 208동 1103호 / 전세 11억 5천만', body)
        self.assertEqual(page.input_value('#fields [data-money="amount"]'), '115,000')
        # 넘긴 주소는 지워서 새로 고쳐도 입력값이 덮이지 않는다
        self.assertNotIn('?', page.url)
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        self.assertIn('208동 1103호', page.input_value('#preview'))
        ctx.close()

    def test_url_params_monthly_and_won_price(self):
        q = 'template=t4&dong=304&ho=201&dealType=월세&deposit=10000&monthly=350'
        ctx, page = self.open_with_query(q)
        self.assertIn('/ 보증금 1억 / 월세 350만 원', page.input_value('#preview'))
        ctx.close()

        q2 = 'template=t7&dong=404&ho=2503&price=2300000000'   # 원 단위로 넘어와도 만 원으로
        ctx2, page2 = self.open_with_query(q2)
        self.assertIn('/ 매매 23억', page2.input_value('#preview'))
        ctx2.close()

    def test_url_params_visit_date_and_number_template(self):
        ctx, page = self.open_with_query('template=3&visitDate=2026-11-26T09:30')
        body = page.input_value('#preview')
        self.assertIn('매수 손님이 계셔서 집보기 가능 여부를 여쭙습니다.', body)
        self.assertIn('- 희망 일시 : 11월 26일 (목) 09:30', body)
        ctx.close()

    def test_url_params_without_property_does_not_add_blank_row(self):
        # 값이 하나도 없으면 빈 매물 줄을 만들지 않는다 (집보기 일정 안내의 매물 블록은 늘 한 줄)
        ctx, page = self.open_with_query('template=t5')
        self.assertEqual(page.query_selector_all('#fields .prop-item').__len__(), 1)
        self.assertNotIn('(매물)', page.input_value('#preview').replace('- (매물) / (가격)', ''))
        ctx.close()

    # ============================================================== 수정요청서(2026-11-25) 회귀
    WANT_TEMPLATES = {
        't1': (1, '통화 후 첫 인사', '통화 감사 · 중개 서비스 소개'),
        't2': (2, '매물 접수 확인', '거래조건 · 입주 · 옵션'),
        't16': (3, '매도·임대 의뢰 제안', '대기 고객 매칭 · 매물 확보'),
        't18': (4, '공동중개 매물 요청', '고객 희망 조건 · 매물 확보'),
        't19': (5, '특가 매물 홍보', '매물 정보 · 거래조건 · 강조 문구'),
        't3': (6, '집보기 문의', '소유자·중개사 / 간단·상세'),
        't5': (7, '집보기 일정 안내', '예약 확정 / 조율 중'),
        't6': (8, '주차 안내', '주차 장소 · 주소'),
        't7': (9, '추천 매물 안내', '집보기 후 추천 매물 · 거래조건'),
        't17': (10, '집보기 후 감사 인사', '거주자 / 공동중개 / 고객'),
        't8': (11, '계약 조건 안내', '매매 가계약·계약 / 전세·월세 계약'),
        't10': (12, '계약 일정 안내', '가계약 · 계약 · 중도금 · 잔금'),
        't11': (13, '전자계약 안내', '계약 절차 · 전자서명'),
        't12': (14, '자금조달계획서 안내', '제출 절차 · 증빙서류'),
        't20': (15, '전문가·협력업체 소개', '대출 · 세무 · 법무 · 입주 서비스'),
        't14': (16, '중개보수 안내', '보수 계산 · 입금 정보'),
        't15': (17, '임대차 만기 확인', '만기 일정 · 연장·퇴거 의사'),
    }

    def test_categories_and_titles(self):
        # 카테고리 5/5/4/3 · 표시 순서 · 17종 제목·부제목 · 새 번호
        got = self.js("""() => SMSTemplates.TEMPLATES.map(t => [t.stage, t.id, t.no, t.title, t.desc])""")
        stages = [g[0] for g in got]
        self.assertEqual(stages, [1]*5 + [2]*5 + [3]*4 + [4]*3, '카테고리별 5/5/4/3 순서')
        self.assertEqual([g[1] for g in got],
                         ['t1', 't2', 't16', 't18', 't19',
                          't3', 't5', 't6', 't7', 't17',
                          't8', 't10', 't11', 't12',
                          't20', 't14', 't15'])
        for stage, tid, no, title, desc in got:
            with self.subTest(tid=tid):
                self.assertEqual((no, title, desc), self.WANT_TEMPLATES[tid])

        tabs = [b.inner_text() for b in self.page.query_selector_all('.stage-tabs .tab')]
        self.assertEqual(tabs, ['전체', '접수·홍보', '방문·집보기', '약정·계약', '잔금·만기'])
        for t in tabs:
            self.assertFalse(t[0].isdigit(), '단계 번호를 붙이지 않는다: ' + t)

        # 목록 머리 — 카테고리 이름과 종수
        heads = [e.inner_text() for e in self.page.query_selector_all('#tpl-list .list-stage')]
        self.assertEqual(heads, ['접수·홍보 · 5종', '방문·집보기 · 5종',
                                 '약정·계약 · 4종', '잔금·만기 · 3종'])

        # 목록 줄 제목은 한 글자도 다르지 않다 (즐겨찾기 중복 제외)
        rows = self.js("""() => [...document.querySelectorAll('#tpl-list .row')]
            .map(r => [r.dataset.id, r.querySelector('.row-title-text').textContent, r.querySelector('.row-no').textContent])""")
        seen = {}
        for tid, title, no in rows:
            seen.setdefault(tid, (title, no))
        self.assertEqual(len(seen), 17)
        for tid, (title, no) in seen.items():
            self.assertEqual((title, no), (self.WANT_TEMPLATES[tid][1], str(self.WANT_TEMPLATES[tid][0])))

    def test_ui_terms_unified(self):
        banned = ['공동중개 부동산용', '공동중개 사장님', '공동중개 중개사', '집 본 손님', '보는 분',
                  '방문 고객', '소유자용', '종별', '고객 유형', '예약 진행 중', '다른 문구',
                  '안부 한 줄', '안부 없음', '강조 한 줄', '동·호 → 단지·층', '[폰]', '중개수수료',
                  '신규']
        ids = self.js("() => SMSTemplates.TEMPLATES.map(t => t.id)")
        for tid in ids:
            with self.subTest(tid=tid):
                self.pick(tid)
                ui = self.page.inner_text('#fields') + '\n' + self.page.inner_text('.topbar')
                body = self.text()
                for word in banned:
                    self.assertNotIn(word, ui, f'{tid} 화면에 "{word}"가 남아 있다')
                    self.assertNotIn(word, body, f'{tid} 문자 본문에 "{word}"가 남아 있다')
        # 목록 화면 — 신규·고정 문자 표시 없음
        listing = self.page.inner_text('#tpl-list')
        self.assertNotIn('신규', listing)
        self.assertNotIn('고정 문자', listing)
        # 바뀐 말이 실제로 보인다
        self.pick('t3')
        t3_fields = self.page.inner_text('#fields')
        self.assertIn('간단', t3_fields)
        self.assertIn('상세', t3_fields)
        self.pick('t17')
        self.assertIn('교체', self.page.inner_text('#fields'))
        self.assertIn('연휴', self.page.inner_text('#fields'))
        self.pick('t19')
        t19_fields = self.page.inner_text('#fields')
        self.assertIn('강조 문구', t19_fields)
        # 단지·층 / 평형 / 동·호로 빠르게 / 자동 변환은 매물 블록으로 바뀌며 사라졌다
        for gone in ('단지·층', '평형', '빠르게', '자동 변환'):
            self.assertNotIn(gone, t19_fields)
        self.pick('t20')
        self.assertIn('연락처 :', self.text())

    def test_line_icons_render(self):
        # 20종 모두 라인 아이콘(SVG)이고 컬러 이모지 글자가 남아 있지 않다
        names_ok = self.js("""() => SMSTemplates.TEMPLATES.map(t => [t.id, SMSIcons.has(t.icon), t.icon])""")
        for tid, ok, name in names_ok:
            self.assertTrue(ok, f'{tid} 아이콘 이름이 아이콘 세트에 없다: {name}')
        emoji = self.js("""() => [...document.querySelectorAll('#tpl-list .row .row-icon')]
            .map(e => e.textContent.trim()).filter(Boolean)""")
        self.assertEqual(emoji, [], '목록 아이콘에 글자(이모지)가 남아 있다')
        per_row = self.js("""() => [...document.querySelectorAll('#tpl-list .row')]
            .every(r => !!r.querySelector('.row-icon svg'))""")
        self.assertTrue(per_row)
        self.assertIsNotNone(self.page.query_selector('.brand-mark svg'), '상단 브랜드 아이콘')
        self.assertIsNotNone(self.page.query_selector('#btn-copy svg'), '복사 버튼 아이콘')
        self.assertIsNotNone(self.page.query_selector('#btn-settings svg'), '설정 버튼 아이콘')
        # 화면 제목도 아이콘 + 글자
        self.assertIsNotNone(self.page.query_selector('#form-title .title-text'))
        self.assertIsNotNone(self.page.query_selector('#form-title svg'))

    def test_phrase_swap_button_has_refresh_icon(self):
        self.pick('t17')
        btn = self.page.query_selector('#fields [data-action="vary"]')
        self.assertTrue(btn.inner_text().strip().startswith('교체'), btn.inner_text())
        self.assertIsNotNone(btn.query_selector('svg'), '교체 버튼에 새로고침 아이콘')
        self.assertEqual(btn.query_selector('svg').get_attribute('class').split()[0], 'ico')
        self.assertIn('1 / 7', self.page.inner_text('#fields .field.is-variant'))

    def test_schedule_templates_share_calendar_icon_and_input(self):
        # 달력 아이콘은 SVG 한 벌을 그대로 쓴다 (직렬화 모양이 아니라 안쪽 그림을 비교)
        want = self.js("""() => { const d = document.createElement('div');
            d.innerHTML = SMSIcons.svg('calendar', 13);
            const s = d.querySelector('svg');
            return s.innerHTML + '|' + s.getAttribute('viewBox') + '|' + s.getAttribute('stroke-width'); }""")
        for tid in ('t8', 't10'):
            with self.subTest(tid=tid):
                self.pick(tid)
                htmls = self.js("""() => [...document.querySelectorAll('#fields .date-btn .date-ico svg')]
                    .map(s => s.innerHTML + '|' + s.getAttribute('viewBox') + '|' + s.getAttribute('stroke-width'))""")
                self.assertTrue(htmls, f'{tid} 달력 아이콘 버튼이 없다')
                for h in htmls:
                    self.assertEqual(h, want, f'{tid} 달력 아이콘이 다르다')
                # 달력·시간 입력 방식도 같다 (버튼을 누르면 같은 달력)
                self.page.click('#fields .date-btn')
                self.wait(80)
                self.assertTrue(self.page.is_visible('#calpop'))
                self.assertIsNotNone(self.page.query_selector('#calpop .wheel [data-wheel-col="h"]'))
                self.page.click('#calpop [data-cal-close]')

    def split(self, **kw):
        return self.js('(o) => SMSCore.paymentSplit(o)', kw)

    def test_payment_split_core(self):
        r = self.split(totalMan=67500, gyeyakMan=6750, jungMan=51250)
        self.assertTrue(r['ok'])
        self.assertEqual(r['janMan'], 9500, '675,000,000 − 67,500,000 − 512,500,000 = 95,000,000')
        self.assertEqual(r['paidMan'], 58000)
        r = self.split(totalMan=67500, gyeyakMan=6750)
        self.assertEqual(r['janMan'], 60750, '중도금이 없으면 0원으로 보고 607,500,000')
        r = self.split(totalMan=67500, gyeyakMan=6750, jungMan=0)
        self.assertEqual(r['janMan'], 60750)
        r = self.split(totalMan=67500, gyeyakMan=67500)
        self.assertEqual((r['ok'], r['janMan']), (True, 0))
        # 초과 지급 — 잔금을 내지 않는다
        r = self.split(totalMan=67500, gyeyakMan=6750, jungMan=62000)
        self.assertFalse(r['ok'])
        self.assertTrue(r['over'])
        self.assertIsNone(r['janMan'])
        self.assertEqual(r['overByMan'], 1250)
        # 음수·기준 없음
        self.assertTrue(self.split(totalMan=67500, gyeyakMan=-1)['negative'])
        self.assertEqual(self.split(gyeyakMan=1000)['reason'], 'no-base')


    def test_t8_payment_split_live(self):
        # 지급 일정 — 약정금·가계약금은 총합계에서 빼고, 잔금은 매매가 − 계약금 − 중도금
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '67500')
        self.pay_fill('yakjeong', 1000)
        self.pay_fill('jeong', 3000)
        self.pay_fill('gyeyak', 6750)
        self.pay_fill('jung', 16875)
        self.wait(200)
        total = self.page.inner_text('.pay-total').replace('\n', ' ')
        self.assertIn('총합계', total)
        self.assertIn('675,000,000원', total)
        self.assertIn('(6억 7,500만원)', total)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '43,875')
        body = self.text()
        self.assertIn('- 약정금 : 10,000,000원', body)
        self.assertIn('- 가계약금 : 30,000,000원', body)
        self.assertIn('- 잔금 : 438,750,000원', body)
        # 중도금을 비우면 잔금이 늘어난다
        self.page.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '60,750')
        # 계약금·중도금이 매매가보다 크면 잔금을 계산하지 않고 경고한다
        self.pay_fill('jung', 70000)
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '')
        self.assertIn('많습니다', self.page.inner_text('.pay-total'))

    def test_paytable_layout_and_rate_edit(self):
        # 공통 지급 일정 — 구분(가운데 정렬 + (+)(−) + %) | 일정·금액 한 줄 + 원단위 환산 줄
        self.pick('t8')
        heads = self.js("() => [...document.querySelectorAll('#fields .paytable-head span')].map(e => e.textContent)")
        self.assertEqual(heads, ['구분', '일정 · 금액'])
        title = self.page.query_selector('#fields .paytable-title')
        self.assertIsNotNone(title, '지급 일정 섹션 라벨이 없다')
        self.assertEqual(title.inner_text().strip(), '지급 일정')
        same = self.js("""() => {
          const a = getComputedStyle(document.querySelector('#fields .paytable-title'));
          const b = getComputedStyle(document.querySelector('#fields .group-head'));
          return [a.color === b.color, a.fontSize === b.fontSize, a.fontWeight === b.fontWeight];
        }""")
        self.assertEqual(same, [True, True, True], '섹션 라벨이 특약과 다른 모양이다')
        # 약정금 → 가계약금 → 계약금 → 중도금 → 잔금 다섯 항목이 늘 서 있다
        names = [r['name'] for r in self.pay_rows()]
        self.assertEqual(names, ['약정금', '가계약금', '계약금', '중도금', '잔금'])
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row .date-btn')), 5, '줄마다 일정 버튼')
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row .pay-amount .money-box')), 5)
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row .pay-hint')), 5, '줄마다 원단위 환산 줄')
        # (+)(−) 는 다섯 항목 모두에 있고, 행 오른쪽 끝 위에 나란히 붙는다
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row [data-pay-add]')), 5)
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row [data-pay-del]')), 5)
        layout = self.js("""() => [...document.querySelectorAll('#fields .pay-row')].map(r => {
          const lab = r.querySelector('.pay-name-text').getBoundingClientRect();
          const steps = r.querySelector('.pay-steps').getBoundingClientRect();
          const rate = r.querySelector('.pay-rate');
          const row = r.getBoundingClientRect();
          const rr = rate ? rate.getBoundingClientRect() : null;
          return {labelLeft: +(lab.left - row.left).toFixed(1),
                   labelRight: +(lab.right).toFixed(1),
                   stepsRight: +(row.right - steps.right).toFixed(1),
                   stepsBelowLabel: +(steps.top - lab.bottom).toFixed(1),
                   rateLeft: rr ? +(rr.left - row.left).toFixed(1) : null,
                   rateBelow: rr ? rr.top >= lab.bottom - 0.5 : true};
        })""")
        for c in layout:
            self.assertLessEqual(c['labelLeft'], 1.5, '항목 이름은 왼쪽 정렬')
            self.assertLessEqual(c['stepsRight'], 1.5, '(+)(−) 는 행 오른쪽 끝')
            self.assertLessEqual(c['stepsBelowLabel'], 4, '(+)(−) 는 항목 이름과 같은 윗줄')
            if c['rateLeft'] is not None:
                self.assertLessEqual(c['rateLeft'], 1.5, '% 칸은 왼쪽 정렬')
                self.assertTrue(c['rateBelow'], '% 칸은 항목 이름 아래줄')
        # 금액을 넣으면 비율이 따라오고, 비율을 고치면 그 차수 금액이 바뀐다
        self.page.fill('#fields [data-field="price"]', '67500')
        self.pay_fill('gyeyak', 6750)
        self.pay_fill('jung', 16875)
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="gyeyak"][data-pay-idx="0"]'), '10')
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="jung"][data-pay-idx="0"]'), '25')
        self.pay_rate('gyeyak', 20)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]'), '13,500')
        self.assertIn('- 계약금 20% : 135,000,000원', self.text())
        self.assertEqual(self.page.query_selector_all('#fields .pay-total-note'), [], '맞을 때는 안내 글자 없음')


    def test_paytable_date_column_shows_full_date(self):
        # 일정 칸에 '연.월.일 (요일)'이 잘리지 않고 다 들어간다 (1440·1000 두 창에서)
        for w, h in ((1440, 900), (1000, 720)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h})
                page = ctx.new_page()
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.click('#tpl-list [data-id="t8"]')
                page.wait_for_timeout(200)
                page.fill('#fields [data-field="price"]', '67500')
                page.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '6750')
                page.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '16875')
                page.wait_for_timeout(150)
                # 다섯 항목의 일정을 달력으로 채운다
                for field, day in (('pay:yakjeong:0', 27), ('pay:jeong:0', 28), ('pay:gyeyak:0', 5),
                                   ('pay:jung:0', 15), ('pay:jan:0', 26)):
                    page.click(f'#fields [data-date="{field}"]')
                    page.wait_for_timeout(120)
                    page.click(f'#calpop [data-cal-day="{day}"]')
                    page.wait_for_timeout(120)
                    page.click('#calpop [data-cal-close]')
                    page.wait_for_timeout(80)
                page.evaluate('document.activeElement && document.activeElement.blur()')
                info = page.evaluate("""() => [...document.querySelectorAll('#fields .pay-row')].map(r => {
                    const span = r.querySelector('.date-text');
                    const rg = document.createRange(); rg.selectNodeContents(span);
                    const sr = span.getBoundingClientRect();
                    const btn = r.querySelector('.date-btn').getBoundingClientRect();
                    const money = r.querySelector('.money-box').getBoundingClientRect();
                    const hint = r.querySelector('.pay-hint');
                    return {text: span.textContent, spanW: sr.width, textW: rg.getBoundingClientRect().width,
                            inside: sr.right <= btn.right - 1 && sr.left >= btn.left + 1,
                            moneyW: money.width, dateW: btn.width, moneyRightOfDate: money.left >= btn.right - 0.5,
                            hintClipped: hint.scrollWidth > hint.clientWidth + 1};
                  })""")
                self.assertEqual(len(info), 5)
                for row in info:
                    self.assertRegex(row['text'], r'^\d{4}\.\d{2}\.\d{2} \(\S\)$', '일정이 날짜로 보인다')
                    self.assertGreaterEqual(row['spanW'], row['textW'] - 0.4, f"{row['text']} 가 잘렸다")
                    self.assertTrue(row['inside'], f"{row['text']} 가 버튼 밖으로 나갔다")
                    self.assertFalse(row['hintClipped'], '환산 줄이 잘렸다')
                    self.assertTrue(row['moneyRightOfDate'], '금액 칸은 일정 칸 오른쪽에 나란히')
                ctx.close()


    def test_t10_paytable_rows(self):
        # 계약 일정 안내 — 매매·전세·월세 모두 같은 다섯 항목 줄
        self.pick_with('t10', {'trade': '매매', 'kind': '잔금'})
        self.assertEqual(self.page.inner_text('#fields .paytable-title').strip(), '지급 일정')
        names = [r['name'] for r in self.pay_rows()]
        self.assertEqual(names, ['약정금', '가계약금', '계약금', '중도금', '잔금'])
        kinds = self.js("() => [...document.querySelectorAll('#fields [data-seg=\"kind\"]')].map(b => b.dataset.value)")
        self.assertEqual(kinds, ['가계약', '계약', '중도금', '잔금'], '매매는 네 칸')
        # 거래 유형 줄은 없애고 매물칸의 [매매][전세][월세]로 고른다
        self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="trade"]')), 0,
                         '거래 유형 줄은 매물칸 안에만 있다')
        self.page.click('#fields [data-prop-trade="prop"][data-value="전세"]')
        self.wait(150)
        kinds = self.js("() => [...document.querySelectorAll('#fields [data-seg=\"kind\"]')].map(b => b.dataset.value)")
        self.assertEqual(kinds, ['계약', '중도금', '잔금'], '전세는 세 칸')
        names = [r['name'] for r in self.pay_rows()]
        self.assertEqual(names, ['약정금', '가계약금', '계약금', '중도금', '잔금'], '전세도 같은 포맷')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-money="rent"]')), 0)
        self.page.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-money="rent"]')), 1,
                         '월세일 때만 월차임 칸')
        names = [r['name'] for r in self.pay_rows()]
        self.assertEqual(names, ['약정금', '가계약금', '계약금', '중도금', '잔금'], '월세도 같은 포맷')
        # 매매대금 입력칸은 없고, 지급 일정 금액을 더한 총합계가 아래에 나온다
        self.page.click('#fields [data-prop-trade="prop"][data-value="매매"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-money="amount"]')), 1,
                         '매물칸에 매매 금액 한 칸')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="price"]')), 0,
                         '따로 둔 매매대금 입력칸은 없앴다')
        self.page.fill('#fields [data-money="amount"]', '10000')
        self.page.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '1000')
        self.wait(200)
        self.assertIn('(1억원)', self.page.inner_text('.pay-total').replace(' ', ''))

    def test_contract_templates_show_full_dong_ho(self):
        # 약정·계약·잔금 쪽은 단지·층으로 가리지 않고 동·호수를 그대로 보여 준다
        for tid in ('t8', 't10', 't15'):
            with self.subTest(tid=tid):
                self.pick(tid)
                if not self.page.query_selector('#fields .prop-item'):
                    continue
                self.assertEqual(len(self.page.query_selector_all('#fields .unit-toggle')), 0,
                                 f'{tid} 전환 배지가 남아 있다')
                fixed = self.js("() => [...document.querySelectorAll('#fields .unit-fixed')].map(e => e.textContent)")
                self.assertEqual(fixed, ['동', '호'])
        self.pick('t8')
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '404')
        self.page.fill('#fields [data-prop="prop"][data-key="ho"]', '1903')
        self.wait(200)
        body = self.text()
        self.assertIn('404동 1903호', body)
        self.assertNotIn('4단지', body)
        self.assertNotIn('19층', body)

    def test_legacy_exposure_locked_to_dong_ho(self):
        # 예전에 골라 둔 단지·층 표시가 저장되어 있어도 계약 서류는 동·호수로 나간다
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't8', 'stage': 'all',
            'data': {'t8': {'prop': {'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1103',
                                     'dongMode': 'complex', 'hoMode': 'floor'}}}
        })
        body = page.input_value('#preview')
        self.assertIn('마포래미안푸르지오 208동 1103호', body)
        self.assertNotIn('2단지', body)
        self.assertEqual(page.query_selector_all('#fields .unit-toggle').__len__(), 0)
        ctx.close()

    def test_stage12_templates_keep_inline_badges(self):
        for tid in ('t2', 't3', 't5', 't7'):
            with self.subTest(tid=tid):
                self.pick(tid)
                if not self.page.query_selector('#fields .prop-item'):
                    continue
                self.assertEqual(len(self.page.query_selector_all('#fields .unit-toggle')), 2,
                                 f'{tid} 동·호 전환 배지가 있어야 한다')
                self.assertEqual(len(self.page.query_selector_all('#fields .unit-fixed')), 0)
        # 매물 안내에서만 단지·층으로 가린다
        self.pick('t7')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '208')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '1103')
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(100)
        self.assertIn('208동 11층', self.text())
        self.page.click('#fields [data-prop-unit="dong"]')
        self.wait(100)
        self.assertIn('2단지', self.text())


    def test_paytable_mobile_and_small_window(self):
        for w, h in ((1000, 720), (390, 844)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                if w < 900:
                    page.click('#btn-sheet')
                    page.wait_for_timeout(150)
                    page.click('#sheet-list [data-id="t8"]')
                else:
                    page.click('#tpl-list [data-id="t8"]')
                page.wait_for_timeout(200)
                page.fill('#fields [data-field="price"]', '67500')
                page.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '6750')
                page.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '16875')
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.wait_for_timeout(250)
                info = page.evaluate("""() => {
                  const rows = [...document.querySelectorAll('#fields .pay-row')].map(r => {
                    const nm = r.querySelector('.pay-name-text').getBoundingClientRect();
                    const dt = r.querySelector('.date-btn').getBoundingClientRect();
                    const am = r.querySelector('.money-box').getBoundingClientRect();
                    const hint = r.querySelector('.pay-hint');
                    const hr = hint.getBoundingClientRect();
                    return { sameRow: Math.min(dt.bottom, am.bottom) - Math.max(dt.top, am.top) >= 12,
                             amountRight: am.left >= dt.right - 1,
                             rateBelow: (() => { const rt = r.querySelector('.pay-rate');
                               return rt ? rt.getBoundingClientRect().top >= nm.bottom - 0.5 : true; })(),
                             hintClipped: hint.scrollWidth > hint.clientWidth + 1,
                             hintBelow: hr.top >= am.bottom - 0.5,
                             hintInside: hr.right <= r.getBoundingClientRect().right + 0.5 };
                  });
                  const table = document.querySelector('#fields .paytable').getBoundingClientRect();
                  const panel = document.querySelector('.form-panel').getBoundingClientRect();
                  return { rows, tableRight: table.right, panelRight: panel.right,
                           docW: document.documentElement.scrollWidth, winW: window.innerWidth,
                           docH: document.documentElement.scrollHeight, winH: window.innerHeight };
                }""")
                self.assertLessEqual(info['docW'], info['winW'], f'{w} 가로 넘침')
                self.assertLessEqual(info['tableRight'], info['panelRight'] + 0.5, f'{w} 표가 패널 밖으로')
                self.assertTrue(all(r['sameRow'] for r in info['rows']), f'{w} 일정·금액 한 줄')
                self.assertTrue(all(r['amountRight'] for r in info['rows']), f'{w} 금액은 일정 오른쪽')
                self.assertTrue(all(r['rateBelow'] for r in info['rows']), f'{w} % 는 라벨 아래줄')
                self.assertTrue(all(r['hintBelow'] for r in info['rows']), f'{w} 환산 줄은 금액 아래')
                self.assertFalse(any(r['hintClipped'] for r in info['rows']), f'{w} 환산 줄 잘림')
                self.assertTrue(all(r['hintInside'] for r in info['rows']), f'{w} 환산 줄이 표 밖으로')
                if w >= 900:
                    self.assertLessEqual(info['docH'], info['winH'], '1000 세로 넘침')
                self.assertEqual(errors, [])
                ctx.close()


    def test_t10_payment_sum_live(self):
        # 계약 일정 안내 — 지급 일정 금액을 그대로 더해 총합계(계약금+중도금+잔금)를 보여 준다
        self.pick_with('t10', {'trade': '매매', 'kind': '중도금'})
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="price"]')), 0,
                         '매매대금 입력칸은 없앤다')
        self.page.fill('#fields [data-money="amount"]', '67500')
        self.pay_fill('gyeyak', 6750)
        self.pay_fill('jung', 51250)
        self.assertIn('6억 7,500만', self.page.inner_text('.pay-total'))
        body = self.text()
        self.assertIn('- 계약금 : 67,500,000원', body)
        self.assertIn('- 중도금 : 512,500,000원', body)
        self.assertIn('- 잔금 : 95,000,000원', body)
        self.assertIn('- 합계 : 675,000,000원', body)
        # 약정금·가계약금은 합계에서 빼고 따로 적는다
        self.pay_fill('yakjeong', 3000)
        self.pay_fill('jeong', 5000)
        self.wait(200)
        body = self.text()
        self.assertIn('- 약정금 : 30,000,000원', body)
        self.assertIn('- 가계약금 : 50,000,000원', body)
        self.assertIn('- 합계 : 675,000,000원', body)
        # 전세 — 보증금(매물칸) + 같은 다섯 항목
        self.page.click('#fields [data-prop-trade="prop"][data-value="전세"]')
        self.wait(150)
        self.pay_fill('gyeyak', 1000)
        self.page.fill('#fields [data-money="amount"]', '10000')
        self.wait(250)
        body = self.text()
        self.assertIn('- 보증금 : 100,000,000원', body)
        self.assertNotIn('월차임', body)
        # 월세 — 보증금 + 월차임이 함께 나간다
        self.page.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        self.wait(150)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '50')
        self.wait(300)
        body = self.text()
        self.assertIn('- 보증금 : 100,000,000원 (1억 원)', body)
        self.assertIn('- 월차임 : 500,000원 (50만 원)', body)


    def test_t8_autofill_uses_split(self):
        # 가계약금은 계약금에 포함되므로 계약일에는 계약금에서 가계약금을 뺀 나머지를 입금한다
        self.pick('t8')
        self.page.click('#fields [data-seg="kind"][data-value="계약"]')
        self.wait(150)
        self.page.fill('#fields [data-field="price"]', '67500')
        self.pay_fill('jeong', 3000)
        self.pay_fill('gyeyak', 6750)
        self.wait(200)
        total = self.page.inner_text('.pay-total')
        self.assertIn('675,000,000원', total)
        body = self.text()
        self.assertIn('- 매매대금 : 675,000,000원', body)
        self.assertIn('- 가계약금 : 30,000,000원', body)
        self.assertIn('기지급한 가계약금 30,000,000원은 계약금에 포함하며, 계약일에는 계약금 총액 67,500,000원 중 차액 37,500,000원을 지급합니다.', body)
        self.assertIn('계약금 10% : 67,500,000원', body)
        # 계약일에 실제로 입금하는 금액은 계약금 − 가계약금
        self.assertIn('동의 여부를 회신해 주시기 바랍니다.', body)
        # 약정금이 있으면 계약일에 전액 반환받는다는 안내가 붙는다
        self.pay_fill('yakjeong', 1000)
        self.wait(200)
        self.assertIn('기지급한 약정금 10,000,000원은 계약일에 전액 반환받고, 계약금 67,500,000원은 약정금을 차감하지 않고 전액 입금합니다.',
                      self.text())

    def test_fee_rate_brackets_and_boundaries(self):
        sale = [(4999, 0.6), (5000, 0.5), (19999, 0.5), (20000, 0.4), (89999, 0.4),
                (90000, 0.5), (119999, 0.5), (120000, 0.6), (149999, 0.6), (150000, 0.7)]
        for man, rate in sale:
            with self.subTest(sale=man):
                r = self.fee(kind='house', trade='매매', amountMan=man)
                self.assertEqual(r['ratePct'], rate, f'매매 {man}만 원 구간 요율')
        lease = [(4999, 0.5), (5000, 0.4), (9999, 0.4), (10000, 0.3), (59999, 0.3),
                 (60000, 0.4), (119999, 0.4), (120000, 0.5), (150000, 0.6)]
        for man, rate in lease:
            with self.subTest(lease=man):
                r = self.fee(kind='house', trade='전세', amountMan=man)
                self.assertEqual(r['ratePct'], rate, f'전세 {man}만 원 구간 요율')
        # 한도액 (5천만 미만 매매 25만 · 5천~2억 80만 · 5천만 미만 임대 20만 · 5천~1억 30만)
        self.assertEqual(self.fee(kind='house', trade='매매', amountMan=4999)['fee'], 250000)
        self.assertEqual(self.fee(kind='house', trade='매매', amountMan=19999)['fee'], 800000)
        self.assertEqual(self.fee(kind='house', trade='전세', amountMan=4999)['fee'], 200000)
        self.assertEqual(self.fee(kind='house', trade='전세', amountMan=9999)['fee'], 300000)
        self.assertTrue(self.fee(kind='house', trade='전세', amountMan=8000)['capped'], '32만 원 → 한도 30만 원')

    def test_fee_rate_over_is_blocked(self):
        r = self.fee(kind='house', trade='매매', amountMan=230000, ratePct=0.9)
        self.assertTrue(r['rateOver'], '상한 초과 요율은 플래그')
        self.assertEqual(r['requestedPct'], 0.9)
        self.assertEqual(r['ratePct'], 0.7, '상한요율을 넘겨 적용하지 않는다')
        self.assertEqual(r['fee'], 16100000)
        # 화면 경고 + 문자 안내
        self.pick('t14')
        self.page.fill('#fields [data-field="calcAmount"]', '230000')
        self.page.fill('#fields [data-field="calcRate"]', '0.9')
        self.wait(200)
        self.assertIn('상한요율 0.7%', self.page.inner_text('.calc-summary'))
        self.assertIn('적용 요율 : 0.7%', self.text())
        self.assertIn('상한요율로 계산했습니다', self.text())
        # 상한 이내 협의 요율은 그대로
        self.page.fill('#fields [data-field="calcRate"]', '0.5')
        self.wait(200)
        self.assertIn('적용 요율 : 0.5%', self.text())
        self.assertNotIn('상한요율로 계산했습니다', self.text())

    def test_fee_vat_breakdown_and_bad_input(self):
        for mode, vat in (('none', 0), ('4', 32000), ('10', 80000)):
            with self.subTest(vat=mode):
                r = self.fee(kind='house', trade='매매', amountMan=20000, vat=mode)
                self.assertEqual(r['supply'], 800000, '공급가액')
                self.assertEqual(r['vat'], vat)
                self.assertEqual(r['total'], 800000 + vat)
        self.assertEqual(self.fee(kind='house', trade='매매', amountMan=20000, vat='10')['vatRatePct'], 10)
        self.assertEqual(self.fee(kind='house', trade='매매', amountMan=20000, vat='4')['vatRatePct'], 4)
        # 음수·0·빈칸 차단
        self.assertFalse(self.fee(kind='house', trade='매매', amountMan=-100)['ok'])
        self.assertEqual(self.fee(kind='house', trade='매매', amountMan=-100)['reason'], '음수')
        self.assertFalse(self.fee(kind='house', trade='매매', amountMan=0)['ok'])
        self.assertFalse(self.fee(kind='house', trade='월세', depositMan=-1, rentMan=10)['ok'])
        # 문자와 화면의 합계가 같다
        self.pick('t14')
        self.page.fill('#fields [data-field="calcAmount"]', '20000')
        self.page.click('#fields [data-seg="calcVat"][data-value="4"]')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-field="calcTotalWon"]'), '832,000')
        self.assertIn('- 부가가치세 : 32,000원 (간이과세 4%)', self.text())
        self.assertIn('- 합계 : 832,000원', self.text())

    def test_fee_officetel_85_split(self):
        small = self.fee(kind='officetel', trade='매매', amountMan=30000)
        big = self.fee(kind='officetel', trade='매매', amountMan=30000, officetelUse='business')
        self.assertEqual((small['ratePct'], big['ratePct']), (0.5, 0.9))
        self.assertEqual(small['fee'], 1500000)
        self.assertEqual(big['fee'], 2700000)
        lease = self.fee(kind='officetel', trade='전세', amountMan=20000)
        self.assertEqual(lease['ratePct'], 0.4)
        # 화면: 오피스텔을 고르면 용도 선택이 나오고 문자에 반영된다
        self.pick('t14')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="calcOffice"]')), 0)
        self.page.click('#fields [data-seg="calcKind"][data-value="officetel"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="calcOffice"]')), 2)
        self.page.fill('#fields [data-field="calcAmount"]', '30000')
        self.wait(150)
        self.assertIn('1,500,000원', self.page.inner_text('.calc-summary'))
        self.page.click('#fields [data-seg="calcOffice"][data-value="business"]')
        self.wait(200)
        self.assertIn('2,700,000원', self.page.inner_text('.calc-summary'))
        self.assertIn('85㎡ 초과·업무용', self.text())

    def test_fee_monthly_conversion_boundary(self):
        # 환산보증금 = 보증금 + 월차임×100, 그것이 5천만 원 미만이면 ×70
        self.assertEqual(self.fee(kind='house', trade='월세', depositMan=1000, rentMan=30)['amountMan'], 3100)
        self.assertEqual(self.fee(kind='house', trade='월세', depositMan=2000, rentMan=30)['amountMan'], 5000)
        r = self.fee(kind='house', trade='월세', depositMan=1000, rentMan=39)
        self.assertEqual(r['amountMan'], 3730, '1000 + 39×70 = 3,730 (환산 4,900 < 5,000)')
        r = self.fee(kind='house', trade='월세', depositMan=1000, rentMan=40)
        self.assertEqual(r['amountMan'], 5000, '1000 + 40×100 = 5,000')
        r = self.fee(kind='house', trade='월세', depositMan=10000, rentMan=50)
        self.assertEqual(r['amountMan'], 15000)
        self.assertTrue(r['converted'])

    # ============================================================== 아이폰 홈 화면(PWA)
    def test_pwa_manifest_and_ios_meta(self):
        import struct

        with open(os.path.join(ROOT, 'manifest.webmanifest'), encoding='utf-8') as f:
            mf = json.load(f)
        self.assertEqual(mf['name'], '마래푸 문자 도우미')
        self.assertEqual(mf['short_name'], '문자도우미')
        self.assertEqual(mf['display'], 'standalone')
        self.assertEqual(mf['background_color'], '#f6f7fb')
        self.assertEqual(mf['theme_color'], '#4f46e5')
        # Capacitor/TWA 래딩을 위해 모두 상대경로
        self.assertEqual(mf['start_url'], './index.html')
        self.assertEqual(mf['scope'], './')
        srcs = [i['src'] for i in mf['icons']]
        self.assertIn('icons/icon-192.png', srcs)
        self.assertIn('icons/icon-512.png', srcs)
        for icon in mf['icons']:
            with self.subTest(icon=icon['src']):
                self.assertFalse(icon['src'].startswith('/'), '절대경로 아이콘은 래딩 때 깨진다')
                path = os.path.join(ROOT, icon['src'])
                self.assertTrue(os.path.exists(path), path)
                with open(path, 'rb') as fh:
                    head = fh.read(24)
                self.assertEqual(head[:8], b'\x89PNG\r\n\x1a\n')
                w, h = struct.unpack('>II', head[16:24])
                self.assertEqual(f'{w}x{h}', icon['sizes'])
        self.assertTrue(any(i.get('purpose') == 'maskable' for i in mf['icons']), '안드로이드 maskable 아이콘')

        meta = self.js("""() => ({
          capable: (document.querySelector('meta[name="apple-mobile-web-app-capable"]') || {}).content,
          bar: (document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]') || {}).content,
          title: (document.querySelector('meta[name="apple-mobile-web-app-title"]') || {}).content,
          theme: (document.querySelector('meta[name="theme-color"]') || {}).content,
          manifest: (document.querySelector('link[rel="manifest"]') || {}).getAttribute
                    ? document.querySelector('link[rel="manifest"]').getAttribute('href') : null,
          appleIcon: document.querySelector('link[rel="apple-touch-icon"]')
                     ? document.querySelector('link[rel="apple-touch-icon"]').getAttribute('href') : null
        })""")
        self.assertEqual(meta['capable'], 'yes')
        self.assertEqual(meta['bar'], 'default')
        self.assertEqual(meta['title'], '문자도우미')
        self.assertEqual(meta['theme'], '#4f46e5')
        self.assertEqual(meta['manifest'], 'manifest.webmanifest')
        self.assertEqual(meta['appleIcon'], 'icons/icon-180.png')
        self.assertTrue(os.path.exists(os.path.join(ROOT, meta['appleIcon'])))
        self.assertFalse(meta['appleIcon'].startswith('/'))

        # manifest가 실제로 내려오고 아이콘도 함께 열린다
        status = self.page.evaluate("""async () => {
          const link = document.querySelector('link[rel="manifest"]');
          const r = await fetch(link.href);
          const j = await r.json();
          const ok = await Promise.all(j.icons.map(async i => (await fetch(new URL(i.src, link.href))).ok));
          return { status: r.status, name: j.name, icons: ok };
        }""")
        self.assertEqual(status['status'], 200)
        self.assertEqual(status['name'], '마래푸 문자 도우미')
        self.assertTrue(all(status['icons']), status)

    # ============================================================== 스크린샷 산출물
    def test_screenshots_exist_after_capture(self):
        # capture.py가 만든 결과물이 실제로 있는지 (없으면 capture를 먼저 돌린다)
        for name in ('sms-app-pc.png', 'sms-app-mobile.png', 'sms-app-date-modes.png', 'sms-app-cal-popup.png'):
            path = os.path.join(DOWNLOADS, name)
            self.assertTrue(os.path.exists(path), f'{path} 가 없다 — tests/capture.py를 실행하세요')
            self.assertGreater(os.path.getsize(path), 20000, f'{path} 가 너무 작다')

    # ============================================================== 내 문구 · 문구 편집
    def add_custom(self, title='이사 인사', desc='입주 축하', body='안녕하세요 [고객]님\n이사 잘 마치셨나요?',
                   stage='2'):
        self.page.click('#btn-tpl-new')
        self.page.wait_for_timeout(120)
        self.page.select_option('#te-stage', stage)
        self.page.fill('#te-title', title)
        self.page.fill('#te-desc', desc)
        self.page.fill('#te-body', body)
        self.page.click('#btn-tpl-editor-save')
        self.page.wait_for_timeout(200)

    def test_11_custom_template_add_and_persist(self):
        # 목록 위 버튼 → 편집창 → 저장 → 목록·미리보기에 바로
        self.assertTrue(self.page.is_visible('#btn-tpl-new'))
        self.add_custom()

        self.assertFalse(self.page.is_visible('#tpl-editor.is-open'),
                         '저장하면 편집창이 닫힌다')
        text = self.text()
        self.assertIn('안녕하세요 (고객)님', text, '본문의 대괄호는 소괄호로 바뀐다')
        self.assertNotIn('[', text)
        self.assertNotIn(']', text)
        self.assertIn('마래푸중앙부동산 드림', text, '서명 토글 기본 ON')
        self.assertIn('010-4585-7365', text)

        # 목록: 내 문구 배지 + 제목·부제목, 아이콘은 SVG 라인 아이콘
        row = self.page.query_selector('#tpl-list .row.is-active')
        self.assertIsNotNone(row, '저장한 문구가 바로 선택되어 있다')
        self.assertIn('내 문구', row.inner_text())
        self.assertIn('이사 인사', row.inner_text())
        self.assertIn('입주 축하', row.inner_text())
        self.assertEqual(self.page.eval_on_selector('#tpl-list .row.is-active .row-icon svg',
                                                    'e => e.tagName.toLowerCase()'), 'svg')

        # 입력 항목이 없고 '비우기' 대신 안내가 뜬다
        self.assertEqual(self.page.eval_on_selector_all('#fields .field', 'els => els.length'), 0)
        self.assertTrue(self.page.eval_on_selector('#btn-reset', 'e => e.hidden'))
        self.assertIn('내가 만든 문구', self.page.inner_text('#fields .fixed-note'))

        # 새로 고침해도 남는다 (localStorage)
        self.page.reload(wait_until='networkidle')
        self.page.wait_for_timeout(250)
        self.assertIn('이사 인사', self.page.inner_text('#tpl-list'))
        self.assertIn('안녕하세요 (고객)님', self.text())

        stored = self.page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1'))")
        self.assertEqual(len(stored['custom']), 1)
        self.assertEqual(stored['custom'][0]['title'], '이사 인사')
        self.assertEqual(stored['custom'][0]['stage'], '2')

    def test_12_custom_template_edit_and_delete(self):
        self.add_custom(title='이사 인사', desc='입주 축하', body='처음 본문')
        self.page.click('#btn-tpl-edit')
        self.page.wait_for_timeout(150)
        self.assertEqual(self.page.inner_text('#tpl-editor-title'), '내 문구 편집')
        self.assertEqual(self.page.input_value('#te-title'), '이사 인사')
        self.assertEqual(self.page.input_value('#te-body'), '처음 본문')
        self.assertTrue(self.page.is_visible('#btn-tpl-editor-del'), '내 문구는 삭제할 수 있다')

        self.page.fill('#te-title', '이사 후 안부')
        self.page.fill('#te-body', '고친 본문입니다')
        self.page.select_option('#te-stage', '4')
        self.page.click('#btn-tpl-editor-save')
        self.page.wait_for_timeout(200)
        self.assertIn('고친 본문입니다', self.text())
        self.assertIn('이사 후 안부', self.page.inner_text('#tpl-list'))
        stored = self.page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1'))")
        self.assertEqual(stored['custom'][0]['stage'], '4')
        self.assertEqual(len(stored['custom']), 1, '고치는 것이지 새로 만들지 않는다')

        # 삭제 — 확인창 → 목록에서 사라짐 → 되돌리기
        self.page.on('dialog', lambda d: d.accept())
        self.page.click('#btn-tpl-edit')
        self.page.wait_for_timeout(120)
        self.page.click('#btn-tpl-editor-del')
        self.page.wait_for_timeout(200)
        self.assertNotIn('이사 후 안부', self.page.inner_text('#tpl-list'))
        self.assertEqual(self.page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1')).custom.length"), 0)
        self.assertTrue(self.page.is_visible('#snackbar.is-on'))
        self.page.click('#snackbar-undo')
        self.page.wait_for_timeout(200)
        self.assertIn('이사 후 안부', self.page.inner_text('#tpl-list'))
        self.assertEqual(self.page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1')).custom.length"), 1)

    def test_13_custom_template_mobile_sheet(self):
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844})
        page = ctx.new_page()
        errors = []
        page.on('console', lambda m: errors.append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(250)

        page.click('#btn-sheet')
        page.wait_for_timeout(200)
        self.assertTrue(page.is_visible('#btn-tpl-new-sheet'), '모바일 목록 시트에도 새 문구 버튼')
        page.click('#btn-tpl-new-sheet')
        page.wait_for_timeout(250)
        self.assertTrue(page.is_visible('#tpl-editor.is-open'))
        self.assertFalse(page.is_visible('#sheet.is-open'), '편집창을 열면 목록 시트는 닫힌다')
        self.assertEqual(page.eval_on_selector('#te-body', 'e => getComputedStyle(e).fontSize'), '16px',
                         '아이폰 확대 방지 16px')

        page.fill('#te-title', '모바일 문구')
        page.fill('#te-body', '모바일에서 만든 본문')
        page.click('#btn-tpl-editor-save')
        page.wait_for_timeout(250)
        self.assertIn('모바일에서 만든 본문', page.input_value('#preview'))
        page.click('#btn-sheet')
        page.wait_for_timeout(200)
        self.assertIn('모바일 문구', page.inner_text('#sheet-list'))
        self.assertIn('내 문구', page.inner_text('#sheet-list'))
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'),
                         '가로 넘침 없음')
        self.assertEqual(errors, [])
        ctx.close()

    def test_13b_custom_editor_mobile_no_clip_no_scroll(self):
        # IMG_3965 — 새 문구 추가 편집창에서
        #  ① 카테고리 <select> 글자가 위아래로 잘리지 않고 (scrollHeight <= clientHeight + 2)
        #  ② 폰 화면에서 편집창 안쪽 세로 스크롤이 생기지 않는다 (카드·본문 모두 scrollHeight <= clientHeight + 2)
        for vw, vh in ((390, 844), (390, 740)):
            with self.subTest(viewport=f'{vw}x{vh}'):
                ctx = self.browser.new_context(viewport={'width': vw, 'height': vh},
                                               is_mobile=True, has_touch=True)
                page = ctx.new_page()
                errors = []
                page.on('console', lambda m: errors.append(f'{m.type}: {m.text}')
                        if m.type in ('error', 'warning') else None)
                page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(250)

                page.click('#btn-sheet')
                page.wait_for_timeout(200)
                page.click('#btn-tpl-new-sheet')
                page.wait_for_timeout(300)
                # 가장 긴 카테고리 이름 — 신고된 화면과 같은 상태
                page.select_option('#te-stage', '1')
                page.fill('#te-title', '이사 후 안부')
                page.fill('#te-desc', '입주 축하 · 관리 안내')
                page.wait_for_timeout(200)

                sel = page.eval_on_selector('#te-stage', """e => {
                  const cs = getComputedStyle(e);
                  return {sh: e.scrollHeight, ch: e.clientHeight, sw: e.scrollWidth, cw: e.clientWidth,
                          h: e.getBoundingClientRect().height, minH: cs.minHeight,
                          pad: cs.padding, shrink: cs.flexShrink, text: e.options[e.selectedIndex].text};
                }""")
                self.assertEqual(sel['text'], '접수·홍보')
                self.assertLessEqual(sel['sh'], sel['ch'] + 2,
                                     f'카테고리 글자가 위아래로 잘리지 않는다 (scrollHeight {sel["sh"]} > {sel["ch"]})')
                self.assertLessEqual(sel['sw'], sel['cw'] + 2, '카테고리 글자가 좌우로 잘리지 않는다')
                self.assertGreaterEqual(sel['h'], 44, '셀렉트는 손가락으로 누르기 좋은 44px 이상')
                self.assertEqual(sel['shrink'], '0', 'flex가 셀렉트를 눌러 찌그러뜨리지 않는다')
                self.assertEqual(sel['pad'].split()[0], '10px', '셀렉트 위아래 패딩 10px')

                card = page.eval_on_selector('#tpl-editor .modal-card',
                                             'e => ({sh: e.scrollHeight, ch: e.clientHeight})')
                self.assertLessEqual(card['sh'], card['ch'] + 2,
                                     f'편집창 안쪽 세로 스크롤이 없다 (카드 {card["sh"]} > {card["ch"]})')
                body = page.eval_on_selector('#tpl-editor .modal-body',
                                             'e => ({sh: e.scrollHeight, ch: e.clientHeight, top: e.scrollTop})')
                self.assertLessEqual(body['sh'], body['ch'] + 2,
                                     f'편집창 본문 세로 스크롤이 없다 (본문 {body["sh"]} > {body["ch"]})')
                self.assertEqual(body['top'], 0, '본문이 스크롤된 상태로 열리지 않는다')

                # 카테고리부터 취소/저장까지 모두 화면 안에 들어온다
                fits = page.evaluate("""() => {
                  const ids = ['#te-stage', '#te-title', '#te-desc', '#te-body', '#te-sign',
                               '#btn-tpl-editor-cancel', '#btn-tpl-editor-save'];
                  return ids.map(s => {
                    const r = document.querySelector(s).getBoundingClientRect();
                    return {s, ok: r.top >= 0 && r.bottom <= window.innerHeight + 0.5};
                  });
                }""")
                for item in fits:
                    self.assertTrue(item['ok'], f'{item["s"]} 가 화면 안에 다 보인다')
                self.assertEqual(errors, [])
                ctx.close()

    def test_14_permanent_edit_and_revert(self):
        self.pick('t3')
        original = self.text()
        self.assertIn('방문', original)
        self.assertTrue(self.page.is_hidden('#btn-tpl-revert'))

        self.page.click('#btn-tpl-edit')
        self.page.wait_for_timeout(150)
        self.assertEqual(self.page.inner_text('#tpl-editor-title'), '문구 편집 — 영구 저장')
        body_in_editor = self.page.input_value('#te-body')
        self.assertNotIn('마래푸중앙부동산 드림', body_in_editor, '편집창에는 서명을 빼고 본문만')
        self.assertTrue(self.page.eval_on_selector('#te-title', 'e => e.disabled'), '기존 문구의 제목은 잠금')
        self.assertTrue(self.page.eval_on_selector('#te-stage', 'e => e.disabled'))

        self.page.fill('#te-body', '영구로 고친 본문입니다 [확인]')
        self.page.click('#btn-tpl-editor-save')
        self.page.wait_for_timeout(220)
        text = self.text()
        self.assertIn('영구로 고친 본문입니다 (확인)', text)
        self.assertNotIn('[', text)
        self.assertIn('마래푸중앙부동산 드림', text)
        self.assertTrue(self.page.is_visible('#btn-tpl-revert'))
        self.assertTrue(self.page.eval_on_selector('#btn-reset', 'e => e.hidden'))
        self.assertIn('수정됨', self.page.inner_text('#tpl-list .row.is-active'))
        self.assertIn('영구 수정한 문구', self.page.inner_text('#fields .fixed-note'))

        # 새로 고침해도 유지
        self.page.reload(wait_until='networkidle')
        self.page.wait_for_timeout(250)
        self.assertIn('영구로 고친 본문입니다 (확인)', self.text())

        # 기본값으로 되돌리기 → 원래 20종 문구·입력 항목 복귀
        self.page.click('#btn-tpl-revert')
        self.page.wait_for_timeout(220)
        self.assertNotIn('영구로 고친 본문입니다', self.text())
        self.assertIn('방문', self.text())
        self.assertGreater(self.page.eval_on_selector_all('#fields .field', 'els => els.length'), 0)
        self.assertTrue(self.page.is_hidden('#btn-tpl-revert'))
        self.assertEqual(self.page.evaluate("Object.keys(JSON.parse(localStorage.getItem('smshelper.v1')).overrides || {}).length"), 0)

    def test_15_one_off_edit_stays_separate(self):
        # 미리보기 직접 수정(일회성)과 영구 저장은 서로 다른 버튼·문구로 구분된다
        self.pick('t5')
        self.page.fill('#preview', '일회성으로 고친 본문')
        self.page.wait_for_timeout(120)
        self.assertTrue(self.page.is_visible('#btn-restore'), '일회성 수정은 원상복구로 되돌린다')
        self.assertTrue(self.page.is_hidden('#btn-tpl-revert'))
        self.page.click('#btn-restore')
        self.page.wait_for_timeout(150)
        self.assertNotIn('일회성으로 고친 본문', self.text())
        self.assertIn('집보기', self.text())

        # 일회성으로 고쳐 둔 본문을 영구 저장하면 그 본문이 남는다
        self.page.fill('#preview', '일회성 본문을 영구로')
        self.page.wait_for_timeout(120)
        self.page.click('#btn-tpl-edit')
        self.page.wait_for_timeout(150)
        self.assertEqual(self.page.input_value('#te-body'), '일회성 본문을 영구로')
        self.page.click('#btn-tpl-editor-save')
        self.page.wait_for_timeout(200)
        self.assertIn('일회성 본문을 영구로', self.text())
        self.assertTrue(self.page.is_visible('#btn-tpl-revert'))

    # ============================================================== 백업 · 불러오기
    def context_with_state(self, state):
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900},
                                       permissions=['clipboard-read', 'clipboard-write'])
        page = ctx.new_page()
        page.add_init_script("localStorage.setItem('smshelper.v1', JSON.stringify(%s));"
                             % json.dumps(state, ensure_ascii=False))
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(220)
        return ctx, page

    def test_16_export_copy_json(self):
        state = {
            'profile': {'office': '마래푸중앙부동산', 'phones': '010-4585-7365 / 02-312-7365',
                        'feeAccount': '우리은행 1002-762-106047 황호선', 'amountMode': 'eokman'},
            'stars': ['t3', 't5'],
            'data': {}, 'texts': {},
            'contacts': {'대출': [{'id': 'k1', 'name': '김상담', 'phone': '010-2222-3333'}]},
            'current': 't1', 'stage': 'all',
            'custom': [{'id': 'c1', 'stage': '2', 'title': '이사 인사', 'desc': '입주 축하',
                        'body': '백업 본문', 'sign': True}],
            'overrides': {'t3': {'body': '영구 수정 본문', 'sign': True}},
            'sync': {'token': '', 'gistId': '', 'updatedAt': 123, 'lastSync': 0},
        }
        ctx, page = self.context_with_state(state)
        page.click('#btn-settings')
        page.wait_for_timeout(150)
        page.click('#btn-export')
        page.wait_for_timeout(350)
        clip = page.evaluate('navigator.clipboard.readText()')
        snap = json.loads(clip)
        self.assertEqual(snap['app'], 'maraepu-sms-helper')
        for key in ('profile', 'stars', 'contacts', 'custom', 'overrides', 'updatedAt'):
            self.assertIn(key, snap)
        self.assertEqual(snap['profile']['feeAccount'], '우리은행 1002-762-106047 황호선')
        self.assertEqual(snap['profile']['amountMode'], 'eokman')
        self.assertEqual(snap['stars'], ['t3', 't5'])
        self.assertEqual(snap['contacts']['대출'][0]['name'], '김상담')
        self.assertEqual(len(snap['custom']), 1)
        self.assertEqual(snap['custom'][0]['title'], '이사 인사')
        self.assertIn('t3', snap['overrides'])
        self.assertEqual(snap['overrides']['t3']['body'], '영구 수정 본문')
        # 동기화 설정(토큰·Gist ID)은 백업에 절대 넣지 않는다
        self.assertNotIn('sync', snap)
        self.assertNotIn('"token"', clip)
        self.assertNotIn('gistId', clip)
        ctx.close()

    def test_17_import_restores_on_new_device(self):
        # 이 기기: 문구를 만들고 내보낸다
        self.add_custom(title='옮길 문구', body='옮길 본문')
        self.page.click('#btn-settings')
        self.page.wait_for_timeout(120)
        self.page.click('#btn-export')
        self.page.wait_for_timeout(300)
        clip = self.page.evaluate('navigator.clipboard.readText()')
        self.page.click('#btn-settings-close')

        # 다른 기기(저장값 없는 새 창)에서 붙여넣기로 복원
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(250)
        self.assertNotIn('옮길 문구', page.inner_text('#tpl-list'))
        page.click('#btn-settings')
        page.wait_for_timeout(120)
        page.click('#btn-import')
        page.wait_for_timeout(120)
        page.fill('#import-text', clip)
        page.click('#btn-import-apply')
        page.wait_for_timeout(350)
        self.assertFalse(page.is_visible('#settings.is-open'), '불러오면 설정창이 닫힌다')
        self.assertIn('옮길 문구', page.inner_text('#tpl-list'))
        self.assertIn('내 문구', page.inner_text('#tpl-list'))
        stored = page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1'))")
        self.assertEqual(len(stored['custom']), 1)
        self.assertEqual(stored['custom'][0]['body'], '옮길 본문')
        # 복원한 문구는 그 기기에서도 그대로 문자로 나온다
        page.click('#tpl-list .row-badge')
        page.wait_for_timeout(150)
        self.assertIn('옮길 본문', page.input_value('#preview'))
        ctx.close()

    def test_18_import_rejects_bad_json(self):
        self.page.click('#btn-settings')
        self.page.wait_for_timeout(120)
        self.page.click('#btn-import')
        self.page.wait_for_timeout(100)
        self.page.fill('#import-text', '이건 백업 파일이 아니에요')
        self.page.click('#btn-import-apply')
        self.page.wait_for_timeout(250)
        self.assertEqual(self.page.inner_text('#toast'), '불러올 수 없는 내용이에요')
        self.assertTrue(self.page.is_visible('#settings.is-open'), '실패하면 설정창을 그대로 둔다')

    # ============================================================== PC·폰 자동 동기화 (Gist)
    def test_19_sync_snapshot_helpers(self):
        out = self.js("""() => {
          const store = {
            profile: { office: '가나부동산', phones: '010-1111-2222', feeAccount: '우리 123', amountMode: 'won' },
            stars: ['t3', 't3', 'c1', 5],
            contacts: { '대출': [{ id: 'k1', name: '김', phone: '010-2' }, { name: '', phone: '' }] },
            custom: [
              { id: 'c1', stage: '2', title: '제목', desc: '', body: '본문', sign: false },
              { id: 'c2', stage: '9', title: '', desc: 'x', body: '', sign: true }
            ],
            overrides: { t3: { body: '영구', sign: true }, t99: { body: '무시' }, junk: null },
            sync: { updatedAt: 12345 }
          };
          const s = SMSSync.snapshot(store);
          const target = { profile: {}, stars: [], contacts: {}, custom: [], overrides: {}, sync: {} };
          const changed = SMSSync.apply(target, s);
          return {
            snap: s, changed, target,
            choose_fresh: SMSSync.choose({ updatedAt: 0 }, s),
            choose_pull: SMSSync.choose({ updatedAt: 100 }, Object.assign({}, s, { updatedAt: 200 })),
            choose_push: SMSSync.choose({ updatedAt: 300 }, Object.assign({}, s, { updatedAt: 200 })),
            choose_same: SMSSync.choose({ updatedAt: 200 }, Object.assign({}, s, { updatedAt: 200 })),
            choose_none: SMSSync.choose({ updatedAt: 200 }, null),
            parse_ok: !!SMSSync.parse(JSON.stringify(s)),
            parse_bad: SMSSync.parse('not json'),
            parse_other: SMSSync.parse(JSON.stringify({ app: 'other-app', profile: {} })),
            parse_empty: SMSSync.parse('{}')
          };
        }""")
        snap = out['snap']
        self.assertEqual(snap['app'], 'maraepu-sms-helper')
        self.assertEqual(snap['updatedAt'], 12345)
        self.assertEqual(snap['profile']['office'], '가나부동산')
        self.assertEqual(snap['stars'], ['t3', 'c1'], '중복·숫자는 걸러낸다')
        self.assertEqual(len(snap['contacts']['대출']), 1, '빈 연락처는 뺀다')
        self.assertEqual(len(snap['custom']), 1, '본문 없는 내 문구는 뺀다')
        self.assertEqual(snap['custom'][0]['stage'], '2')
        self.assertEqual(list(snap['overrides'].keys()), ['t3'], '기본 20종만 영구 수정 대상')

        self.assertTrue(out['changed'])
        self.assertEqual(out['target']['profile']['office'], '가나부동산')
        self.assertEqual(out['target']['sync']['updatedAt'], 12345)
        self.assertEqual(out['choose_fresh'], 'pull')
        self.assertEqual(out['choose_pull'], 'pull')
        self.assertEqual(out['choose_push'], 'push')
        self.assertEqual(out['choose_same'], 'same')
        self.assertEqual(out['choose_none'], 'push')
        self.assertTrue(out['parse_ok'])
        self.assertIsNone(out['parse_bad'])
        self.assertIsNone(out['parse_other'])
        self.assertIsNone(out['parse_empty'])

    def gist_mock(self, page):
        mock = {'file': None, 'id': 'gistabc1234567', 'calls': []}

        def handle(route):
            req = route.request
            headers = {
                'access-control-allow-origin': '*',
                'access-control-allow-headers': '*',
                'access-control-allow-methods': 'GET,POST,PATCH,OPTIONS',
                'content-type': 'application/json',
            }
            if req.method == 'OPTIONS':
                route.fulfill(status=204, headers=headers, body='')
                return
            body = None
            try:
                body = json.loads(req.post_data) if req.post_data else None
            except Exception:
                body = None
            mock['calls'].append({'method': req.method, 'url': req.url, 'body': body})
            if req.method == 'POST':
                mock['file'] = body['files']['smshelper-backup.json']['content']
                route.fulfill(status=201, headers=headers, body=json.dumps({'id': mock['id']}))
            elif req.method == 'PATCH':
                mock['file'] = body['files']['smshelper-backup.json']['content']
                route.fulfill(status=200, headers=headers, body=json.dumps({'id': mock['id']}))
            elif req.method == 'GET':
                if mock['file'] is None:
                    route.fulfill(status=404, headers=headers, body=json.dumps({'message': 'Not Found'}))
                else:
                    route.fulfill(status=200, headers=headers, body=json.dumps({
                        'id': mock['id'],
                        'files': {'smshelper-backup.json': {'content': mock['file'], 'truncated': False}},
                    }))
            else:
                route.fulfill(status=200, headers=headers, body='{}')

        page.route('https://api.github.com/**', handle)
        return mock

    def connect_gist(self, token='ghp_testtoken1234'):
        self.page.click('#btn-settings')
        self.page.wait_for_timeout(150)
        self.page.fill('#set-gh-token', token)
        self.page.click('#btn-gh-sync')
        self.page.wait_for_timeout(600)

    def test_20_gist_connect_creates_secret_gist(self):
        mock = self.gist_mock(self.page)
        self.add_custom(title='동기화 문구', body='동기화 본문')
        self.connect_gist()

        self.assertEqual(self.page.input_value('#set-gh-gist'), mock['id'], 'Gist ID가 자동으로 채워진다')
        self.assertTrue(self.page.is_visible('#sync-status'))
        self.assertEqual(self.page.inner_text('#sync-status'), '동기화됨')
        posts = [c for c in mock['calls'] if c['method'] == 'POST']
        self.assertEqual(len(posts), 1, posts)
        self.assertIs(posts[0]['body']['public'], False, '비공개(Secret) Gist로 만든다')
        content = json.loads(posts[0]['body']['files']['smshelper-backup.json']['content'])
        self.assertEqual(content['custom'][0]['title'], '동기화 문구')
        self.assertGreater(content['updatedAt'], 0, '처음 올릴 때도 시각을 붙여 다른 기기가 받아 갈 수 있게')
        self.assertNotIn('ghp_testtoken1234', posts[0]['body']['files']['smshelper-backup.json']['content'],
                         '토큰은 Gist에 올라가지 않는다')

        stored = self.page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1')).sync")
        self.assertEqual(stored['token'], 'ghp_testtoken1234')
        self.assertEqual(stored['gistId'], mock['id'])
        self.assertGreater(stored['lastSync'], 0)

    def test_21_gist_autopush_after_change(self):
        mock = self.gist_mock(self.page)
        self.connect_gist()
        self.page.click('#btn-settings-close')
        self.page.wait_for_timeout(150)
        before = len([c for c in mock['calls'] if c['method'] == 'PATCH'])

        # 내 정보를 고치면 디바운스 뒤 자동으로 올라간다
        self.page.click('#btn-settings')
        self.page.wait_for_timeout(150)
        self.page.fill('#set-office', '마래푸중앙분양')
        self.page.click('#btn-settings-save')
        self.page.wait_for_timeout(3400)
        patches = [c for c in mock['calls'] if c['method'] == 'PATCH']
        self.assertEqual(len(patches), before + 1, 'auto push')
        content = json.loads(mock['file'])
        self.assertEqual(content['profile']['office'], '마래푸중앙분양')
        self.assertEqual(self.page.inner_text('#sync-status'), '동기화됨')

    def test_22_gist_pulls_newer_remote_on_open(self):
        # 다른 기기에서 올려 둔 최신 백업을 열자마자 받아 온다
        remote = {
            'app': 'maraepu-sms-helper', 'version': 1, 'updatedAt': 9999999999999,
            'profile': {'office': '마래푸중앙분양', 'phones': '010-9999-8888', 'feeAccount': '', 'amountMode': 'won_eokman'},
            'stars': ['t5'],
            'contacts': {},
            'custom': [{'id': 'c_remote', 'stage': '1', 'title': '다른 기기 문구', 'desc': '', 'body': '원격 본문', 'sign': True}],
            'overrides': {},
        }
        mock = {'file': json.dumps(remote, ensure_ascii=False), 'id': 'gistremote', 'calls': []}

        def handle(route):
            req = route.request
            headers = {'access-control-allow-origin': '*', 'access-control-allow-headers': '*',
                       'access-control-allow-methods': 'GET,POST,PATCH,OPTIONS',
                       'content-type': 'application/json'}
            if req.method == 'OPTIONS':
                route.fulfill(status=204, headers=headers, body='')
                return
            mock['calls'].append(req.method)
            if req.method == 'GET':
                route.fulfill(status=200, headers=headers, body=json.dumps({
                    'id': mock['id'],
                    'files': {'smshelper-backup.json': {'content': mock['file'], 'truncated': False}}}))
            else:
                route.fulfill(status=200, headers=headers, body=json.dumps({'id': mock['id']}))

        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.route('https://api.github.com/**', handle)
        page.add_init_script("localStorage.setItem('smshelper.v1', JSON.stringify(%s));" % json.dumps({
            'profile': {'office': '마래푸중앙부동산', 'phones': '010-4585-7365 / 02-312-7365',
                        'feeAccount': '', 'amountMode': 'won_eokman'},
            'stars': [], 'data': {}, 'texts': {}, 'contacts': {}, 'current': 't5', 'stage': 'all',
            'custom': [], 'overrides': {},
            'sync': {'token': 'ghp_x', 'gistId': 'gistremote', 'updatedAt': 1, 'lastSync': 0},
        }))
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(1400)
        self.assertIn('다른 기기 문구', page.inner_text('#tpl-list'))
        self.assertEqual(page.inner_text('#sync-status'), '동기화됨')
        stored = page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1'))")
        self.assertEqual(stored['profile']['office'], '마래푸중앙분양')
        self.assertEqual(stored['sync']['updatedAt'], 9999999999999)
        self.assertIn('GET', mock['calls'])
        ctx.close()

    def test_23_gist_offline_badge_and_leave_token_local(self):
        mock = self.gist_mock(self.page)
        self.connect_gist()
        self.page.click('#btn-settings-close')
        self.page.wait_for_timeout(150)
        # 연결을 끊고(네트워크 실패) 다시 동기화 → '오프라인'
        self.page.route('https://api.github.com/**', lambda route: route.abort())
        self.page.click('#btn-settings')
        self.page.wait_for_timeout(150)
        self.page.click('#btn-gh-sync')
        self.page.wait_for_timeout(700)
        self.assertEqual(self.page.inner_text('#sync-status'), '오프라인')
        self.assertTrue(self.page.is_visible('#btn-gh-off'), '연결 해제 버튼이 보인다')
        self.page.click('#btn-gh-off')
        self.page.wait_for_timeout(150)
        self.assertTrue(self.page.is_hidden('#sync-status'))
        stored = self.page.evaluate("JSON.parse(localStorage.getItem('smshelper.v1')).sync")
        self.assertEqual(stored['token'], '')
        self.assertEqual(stored['gistId'], '')
        # 끊긴 네트워크에서 생기는 브라우저 리소스 오류만 걸러 낸다
        self.errors = [e for e in self.errors if 'ERR_' not in e and 'Failed to load resource' not in e]

    # ============================================================== 날짜 칸 (v1.1.3)
    def date_widths(self, sel='#fields .date-btn'):
        return self.js("(s) => [...document.querySelectorAll(s)].map(b => +b.getBoundingClientRect().width.toFixed(1))", sel)

    def date_heights(self, sel='#fields .date-btn'):
        return self.js("(s) => [...document.querySelectorAll(s)].map(b => +b.getBoundingClientRect().height.toFixed(1))", sel)

    def cal_time_widths(self):
        return self.js("""() => {
          const cols = [...document.querySelectorAll('#calpop .wheel .wheel-col')];
          if (cols.length !== 3) return null;
          return cols.map(c => +c.getBoundingClientRect().width.toFixed(1));
        }""")

    def cal_foot(self):
        return self.js("""() => {
          const f = document.querySelector('#calpop .cal-foot');
          if (!f) return null;
          const b = [...f.children];
          const r = b.map(x => x.getBoundingClientRect());
          return { names: b.map(x => x.textContent.trim()),
                   left: r.map(x => +x.left.toFixed(1)), top: r.map(x => +x.top.toFixed(1)) };
        }""")

    def test_date_mode_segment_layout_stable(self):
        # 입주 — 협의 | 고정 | 기간 3단 세그먼트, 모드를 바꿔도 글자칸 폭이 그대로
        for tid in ('t2', 't18'):
            with self.subTest(tid=tid):
                self.pick(tid)
                modes = self.js("""() => [...document.querySelectorAll('#fields .date-mode .seg-btn')]
                    .map(b => b.textContent.trim())""")
                self.assertEqual(modes, ['협의', '고정', '기간'])

                def active():
                    return self.js("""() => { const b = document.querySelector('#fields .date-mode .seg-btn.is-active');
                        return b ? b.textContent.trim() : null; }""")

                self.assertEqual(active(), '고정', '처음에는 달력(고정)이 골라져 있다')
                # [시작일] ~ [종료일] 두 칸이 늘 같은 자리·같은 폭으로 보인다
                pair = self.date_widths('#fields .date-range .date-btn')
                self.assertEqual(len(pair), 2)
                self.assertAlmostEqual(pair[0], pair[1], delta=0.6)
                self.assertEqual(self.date_heights()[0], 38, '값이 없어도 칸 높이가 같다')
                self.assertEqual([self.page.inner_text(s).strip() for s in
                                  ('#fields [data-date="moveinStart"]', '#fields [data-date="moveinEnd"]')],
                                 ['시작일', '종료일'])

                # 협의 — 입력칸 없이 두 칸 모두 잠기고, 선택 모양만 바뀐다
                self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
                self.wait(150)
                self.assertEqual(active(), '협의')
                self.assertEqual(self.js("() => document.querySelectorAll('#fields .inp-date-free').length"), 0)
                self.assertTrue(self.js("() => document.querySelector('#fields [data-date=\"moveinStart\"]').disabled"))
                self.assertEqual(self.date_widths('#fields .date-range .date-btn'), pair, '칸 폭 그대로')
                self.assertRegex(self.text(), r'입주\s*:?\s*즉시입주\(협의\)')

                # 고정 — 시작일에서 날짜를 골라도 칸 폭·높이가 같다
                self.page.click('#fields [data-date-mode="movein"][data-value="고정"]')
                self.wait(150)
                self.assertEqual(active(), '고정')
                self.page.click('#fields [data-date="moveinStart"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-day="26"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                self.assertEqual(self.date_widths('#fields .date-range .date-btn'), pair, '날짜를 골라도 칸 폭이 그대로')
                self.assertEqual(self.date_heights(), [38, 38], '날짜를 골라도 칸 높이가 그대로')
                self.assertIn('2026.11.26 (목)', self.page.inner_text('#fields [data-date="moveinStart"]'))
                self.assertRegex(self.text(), r'입주\s*:?\s*26\.11\.26 \(목\) 고정')

                # 기간 — 같은 두 칸을 그대로 쓰고 종료일이 열린다
                self.page.click('#fields [data-date-mode="movein"][data-value="기간"]')
                self.wait(150)
                self.assertEqual(active(), '기간')
                self.assertEqual(self.date_widths('#fields .date-range .date-btn'), pair, '칸 폭 그대로')
                for field, day in (('moveinStart', 1), ('moveinEnd', 31)):
                    self.page.click(f'#fields [data-date="{field}"]')
                    self.wait(160)
                    self.page.click('#calpop [data-cal-nav="1"]')
                    self.wait(120)
                    self.page.click(f'#calpop [data-cal-day="{day}"]')
                    self.wait(160)
                    self.page.click('#calpop [data-cal-close]')
                    self.wait(150)
                self.assertEqual(self.date_widths('#fields .date-range .date-btn'), pair,
                                 '기간 두 칸도 값이 들어가면 폭이 그대로')
                self.assertRegex(self.text(), r'입주\s*:?\s*26\.12\.01 \(화\) ~ 26\.12\.31 \(목\)')

    def test_every_date_trigger_width_fixed(self):
        # 모든 문구 어디서든 — 날짜·일정 단추 폭/높이와 팝업 시·분 칸 폭이 선택 전후로 같다
        tids = ('t2', 't3', 't5', 't7', 't8', 't10', 't18')
        checked = 0
        for tid in tids:
            with self.subTest(tid=tid):
                self.pick(tid)
                if tid in ('t2', 't18'):
                    self.page.click('#fields [data-date-mode="movein"][data-value="고정"]')
                    self.wait(140)
                if not self.page.query_selector('#fields .date-btn'):
                    continue
                checked += 1
                before, hbefore = self.date_widths(), self.date_heights()
                self.page.click('#fields .date-btn')
                self.wait(160)
                pop_empty = self.cal_time_widths()
                self.page.click('#calpop [data-cal-day="26"]')
                self.wait(160)
                pop_day = self.cal_time_widths()
                if pop_day:
                    self.pick_time('#calpop', None, '10', '30')
                pop_time = self.cal_time_widths()
                if pop_day:
                    self.assertEqual(pop_day, pop_empty, f'{tid} 날짜를 골라 팝업 시·분 칸 폭이 밀렸다')
                    self.assertEqual(pop_time, pop_empty, f'{tid} 시간을 골라 팝업 시·분 칸 폭이 밀렸다')
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                self.assertEqual(self.date_widths(), before, f'{tid} 값이 들어가면 날짜 칸 폭이 흔들린다')
                self.assertEqual(self.date_heights(), hbefore, f'{tid} 값이 들어가면 날짜 칸 높이가 흔들린다')
        self.assertGreaterEqual(checked, 6, '날짜 칸이 있는 문자를 충분히 훑었다')

    def test_calendar_popup_reset_beside_close(self):
        # 팝업 하단 — 초기화가 닫기 왼쪽 옆에 나란히 있고, 누르면 날짜·시간이 모두 지워진다
        self.pick('t5')
        self.page.click('#fields .date-btn')
        self.wait(160)
        foot = self.cal_foot()
        self.assertEqual(foot['names'], ['초기화', '닫기'])
        self.assertLess(foot['left'][0], foot['left'][1])
        self.assertAlmostEqual(foot['top'][0], foot['top'][1], delta=1.0, msg='같은 줄에 있어야 한다')
        self.page.click('#calpop [data-cal-day="26"]')
        self.wait(160)
        self.pick_time('#calpop', None, '10', '30')
        # 시간을 골라도 버튼 자리·시분 칸 폭이 그대로 (예전의 '시간 지우기'는 없다)
        self.assertEqual(self.cal_foot(), foot)
        self.assertEqual(len(self.page.query_selector_all('#calpop .link')), 0)
        self.assertIn('2026.11.26 (목) 10:30', self.page.inner_text('#fields .date-btn'))
        # 초기화 — 날짜·시간이 함께 지워지고 팝업은 열린 채 남는다
        self.page.click('#calpop [data-cal-reset]')
        self.wait(200)
        self.assertIn('(방문 일시)', self.text())
        self.assertEqual(self.page.inner_text('#fields .date-btn').strip(), '날짜 · 시간 선택')
        self.assertTrue(self.page.is_visible('#calpop'))
        self.page.reload(wait_until='networkidle')
        self.pick('t5')
        self.assertEqual(self.page.inner_text('#fields .date-btn').strip(), '날짜 · 시간 선택', '지운 값이 저장되어야 한다')
        self.assertIn('(방문 일시)', self.text())

    def test_option_placeholder_common(self):
        self.pick('t2')
        self.assertEqual(self.page.get_attribute('#fields [data-field="option"]', 'placeholder'),
                         '예: 시스템에어컨, 올수리 등')

    def test_legacy_movein_values_open_in_right_mode(self):
        # 예전 저장값(글자만 · 날짜만)도 그대로 살아난다 (mode 키가 없어도)
        cases = [
            ({'movein': {'date': '2026-12-03', 'hour': None, 'min': 0}, 'moveinText': ''}, '고정'),
            ({'movein': {'date': '', 'hour': None, 'min': 0}, 'moveinText': '즉시'}, '협의'),
        ]
        for saved, want_mode in cases:
            with self.subTest(want_mode=want_mode):
                ctx, page = self.page_with_state({
                    'stars': [], 'texts': {}, 'current': 't2', 'stage': 'all',
                    'data': {'t2': dict(saved)}
                })
                try:
                    active = page.evaluate("""() => { const b = document.querySelector('#fields .date-mode .seg-btn.is-active');
                        return b ? b.textContent.trim() : null; }""")
                    self.assertEqual(active, want_mode)
                    if want_mode == '고정':
                        self.assertIn('2026.12.03 (목)', page.inner_text('#fields [data-date="moveinStart"]'))
                        self.assertIn('26.12.03 (목) 고정', page.input_value('#preview'))
                    else:
                        self.assertRegex(page.input_value('#preview'), r'입주\s*:?\s*즉시입주\(협의\)')
                finally:
                    ctx.close()

    # ============================================================== 버전 · 배포 파일

    def test_24_version_bumped_to_1_4_7(self):
        # 서비스 워커 · 화면 캐시 주소 · 안드로이드 빌드 번호가 모두 같은 버전을 가리킨다
        with open(os.path.join(ROOT, 'sw.js'), encoding='utf-8') as f:
            sw = f.read()
        m = re.search(r"var VERSION = '(v\d+\.\d+\.\d+)';", sw)
        self.assertIsNotNone(m, 'sw.js에 VERSION이 있다')
        ver = m.group(1)
        self.assertEqual(ver, 'v1.4.7')
        self.assertIn("'js/sync.js'", sw)
        # 새 파일(동호수 타입표)도 오프라인 캐시에 들어간다
        self.assertIn("'js/maraepu-types.js'", sw)
        with open(os.path.join(ROOT, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        for f_ in ('icons', 'maraepu-types', 'core', 'templates', 'sync', 'app'):
            self.assertIn(f'js/{f_}.js?v=1.4.7', html)
        self.assertIn('styles.css?v=1.4.7', html)
        gradle = open(os.path.join(ROOT, 'android/app/build.gradle'), encoding='utf-8').read()
        self.assertIn('versionCode 22', gradle)
        self.assertIn("versionName '1.4.7'", gradle)

    def test_t8_deal_combos_and_labels(self):
        # 계약 조건 안내 — [매매][전세][월세] | [가계약][계약], 다섯 버튼이 한 줄·같은 크기
        self.pick('t8')
        self.assertEqual(self.page.inner_text('#form-title').strip(), '계약 조건 안내')
        self.assertNotIn('계약 구분', self.page.inner_text('#fields'))
        self.assertIn('입금계좌', self.page.inner_text('#fields'))
        self.assertEqual(len(self.page.query_selector_all('#fields .account-preview')), 0,
                         '계좌 아래 → 파싱 미리보기 줄은 없앤다')
        self.assertNotIn('은행·계좌·예금주 순서 상관없이 붙여넣기', self.page.inner_text('#fields'),
                         '입금계좌 옆 회색 안내는 없앤다')
        btns = self.js("""() => {
          const d = document.querySelector('#fields .seg.is-deal');
          const list = [...d.querySelectorAll('.seg-btn')].map(b => ({v: b.dataset.value, w: +b.getBoundingClientRect().width.toFixed(1),
            h: +b.getBoundingClientRect().height.toFixed(1), t: +b.getBoundingClientRect().top.toFixed(1)}));
          const div = d.querySelector('.seg-divider');
          const dr = div.getBoundingClientRect();
          const mid = list[2].w;
          return {list, divW: dr.width, divTall: dr.height > 10, dividerAfter: dr.left > d.querySelectorAll('.seg-btn')[2].getBoundingClientRect().right - 0.5};
        }""")
        self.assertEqual([b['v'] for b in btns['list']], ['매매', '전세', '월세', '가계약', '계약'])
        widths = [b['w'] for b in btns['list']]
        self.assertLessEqual(max(widths) - min(widths), 1.0, '다섯 버튼 크기가 다르다')
        self.assertEqual(len(set(b['t'] for b in btns['list'])), 1, '다섯 버튼이 한 줄이 아니다')
        self.assertLessEqual(btns['divW'], 2, '거래유형·계약구분 사이 얇은 구분선')
        self.assertTrue(btns['divTall'], '구분선이 세로로 서지 않는다')
        self.assertTrue(btns['dividerAfter'], '구분선은 거래유형과 계약구분 사이')
        # 매매가(기준 금액)는 지급 일정 위 한 칸에서 적는다 — 잔금 자동 계산의 기준
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="price"]')), 1,
                         '매매가 입력칸이 있어야 잔금을 계산한다')
        self.assertIn('매매가', self.page.inner_text('#fields'))
        body = self.text()
        self.assertIn('매매 가계약 주요 내용', body)
        self.assertIn('- 입금계좌 :', body)
        self.page.fill('#fields [data-field="address"]', '서울시 마포구 아현동 777 외 3필지')
        self.wait(150)
        body = self.text()
        self.assertIn('- 물건지 : 서울시 마포구 아현동 777 외 3필지', body)
        self.page.click('#fields [data-seg="kind"][data-value="계약"]')
        self.wait(120)
        body = self.text()
        self.assertIn('매매계약 주요 내용', body)
        self.assertNotIn('가계약금 :', body)
        # 물건지 아래 주소·단지명·동/호수는 줄 간격이 균일하다
        gaps = self.js("""() => {
          const box = s => document.querySelector('#fields ' + s).getBoundingClientRect();
          const a = box('[data-field="address"]'), c = box('.prop-top .is-complex'), d = box('[data-key="dong"]'), h = box('[data-key="ho"]');
          return {addrGap: +(c.top - a.bottom).toFixed(1), sameRow: Math.abs(c.top - d.top) < 1 && Math.abs(d.top - h.top) < 1};
        }""")
        self.assertGreaterEqual(gaps['addrGap'], 6, f"물건지 주소와 단지명이 붙어 있다 {gaps}")
        self.assertLessEqual(gaps['addrGap'], 12, f"물건지 주소와 단지명 간격이 넓다 {gaps}")
        self.assertTrue(gaps['sameRow'], '단지명·동·호는 한 줄')
        # 전세·월세도 가계약·계약 둘 다 고를 수 있다
        for m in ('전세', '월세'):
            with self.subTest(trade=m):
                self.page.click('#fields [data-seg="trade"][data-value="%s"]' % m)
                self.wait(150)
                kinds = self.js("""() => [...document.querySelectorAll('#fields [data-seg="kind"]')].map(b => b.dataset.value)""")
                self.assertEqual(kinds, ['가계약', '계약'], f'{m}도 두 갈래')
                self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 1 if m == '월세' else 0)
                self.page.click('#fields [data-seg="kind"][data-value="계약"]')
                self.wait(150)
                self.assertIn('%s 계약 주요 내용' % m, self.text())
                self.page.click('#fields [data-seg="kind"][data-value="가계약"]')
                self.wait(150)
                self.assertIn('%s 가계약 주요 내용' % m, self.text())
                self.assertIn('- 가계약금 :', self.text())

    def test_t14_total_edit_keeps_legal_rate(self):
        # 중개보수 합계를 직접 고치면 문자에는 그 금액, 적용 요율은 법정 요율 그대로
        self.pick('t14')
        self.page.fill('#fields [data-field="calcAmount"]', '76000')
        self.wait(200)
        auto = self.page.input_value('#fields [data-field="calcTotalWon"]')
        self.assertEqual(auto, '3,161,600')
        self.assertIn('- 합계 : 3,161,600원', self.text())
        self.page.fill('#fields [data-field="calcTotalWon"]', '2500000')
        self.wait(200)
        body = self.text()
        self.assertIn('- 적용 요율 : 0.4%', body, '적용 요율은 법정 요율 그대로')
        self.assertIn('- 합계 : 2,500,000원', body)
        self.assertIn('- 중개보수 (공급가액) : 2,403,846원', body)
        self.assertIn('- 부가가치세 : 96,154원 (간이과세 4%)', body)
        # 다시 비우면 자동 계산으로 돌아온다
        self.page.fill('#fields [data-field="calcTotalWon"]', '')
        self.wait(200)
        self.assertIn('- 합계 : 3,161,600원', self.text())
        # 안내문 두 줄은 사라졌다
        fields = self.page.inner_text('#fields')
        self.assertNotIn('계산하면 중개보수가 바로 나옵니다', fields)
        self.assertNotIn('금액을 입력해주세요', fields)

    def test_t15_role_counterpart_fixed(self):
        # 임대인에게 보내면 '임차인분과는', 임차인에게 보내면 '임대인분과는'
        self.pick('t15')
        body = self.text()
        self.assertIn('임차인분과 미리 협의하신 내용이 있으실지', body)
        self.assertIn('퇴거 예정이시면 일정과 필요한 사항을 확인해', body)
        self.assertNotIn('임대인분과', body)
        self.page.click('#fields [data-seg="role"][data-value="임차인"]')
        self.wait(120)
        body = self.text()
        self.assertIn('임대인분과 미리 협의하신 내용이 있으실지', body)
        # 상대방 버튼과 남은 기간이 한 줄
        geo = self.js("""() => {
          const s = document.querySelector('#fields .seg.is-role').getBoundingClientRect();
          const m = document.querySelector('#fields .money-wrap.is-months').getBoundingClientRect();
          return { sameRow: Math.abs((s.top + s.height / 2) - (m.top + m.height / 2)) < 3,
                   left: s.right <= m.left + 1 };
        }""")
        self.assertTrue(geo['sameRow'], '상대방 버튼과 남은 기간이 같은 줄에 있어야 한다')
        self.assertTrue(geo['left'])
        self.assertNotIn('금액 표시', self.page.inner_text('#fields'), '금액 표시 줄은 없다')

    def test_t20_vendor_categories_one_row_and_add(self):
        self.pick('t20')
        cats = self.js("""() => [...document.querySelectorAll('#fields [data-seg="vendorCat"]')].map(b => b.textContent.trim())""")
        self.assertEqual(cats, ['대출', '세무사', '법무사', '인테리어', '입주청소', '이사'])
        rows = self.js("""() => {
          const btns = [...document.querySelectorAll('#fields [data-seg="vendorCat"]')];
          const tops = [...new Set(btns.map(b => Math.round(b.getBoundingClientRect().top)))];
          return { rows: tops.length, first: btns.slice(0, 5).map(b => b.textContent.trim()),
                   firstRow: tops[0] === Math.round(btns[0].getBoundingClientRect().top) };
        }""")
        self.assertEqual(rows['first'], ['대출', '세무사', '법무사', '인테리어', '입주청소'], '첫 줄에 5개')
        self.assertEqual(rows['rows'], 2, '둘째 줄에 이사 + 업체 추가')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-contact-add]')), 1,
                         '+ 업체 추가 버튼 하나')
        self.assertEqual(self.page.inner_text('#fields [data-contact-add]').strip(), '+ 업체 추가')
        # 안내문·연락처 추가 버튼은 사라졌다
        fields = self.page.inner_text('#fields')
        self.assertNotIn('체크한 상담사만 문자에 들어갑니다', fields)
        self.assertNotIn('저장된 연락처가 없어요', fields)
        self.assertNotIn('+ 연락처 추가', fields)
        self.assertIn('연락처', fields)
        # 체크박스 + 이름 + 연락처 반반
        widths = self.js("""() => [...document.querySelectorAll('#fields .contact.is-new .contact-inp')]
            .map(i => +i.getBoundingClientRect().width.toFixed(1))""")
        self.assertEqual(len(widths), 2)
        self.assertAlmostEqual(widths[0], widths[1], delta=1.5, msg='이름·연락처 반반')
        # + 업체 추가로 저장된다
        self.page.fill('#fields [data-contact-new="name"]', '신한대출 담당자')
        self.page.fill('#fields [data-contact-new="phone"]', '010-1111-2222')
        self.page.click('#fields [data-contact-add]')
        self.wait(200)
        body = self.text()
        self.assertIn('이름 : 신한대출 담당자', body)
        self.assertIn('연락처 : 010-1111-2222', body)
        # 저장된 연락처는 그 자리에서 고칠 수 있다
        self.page.fill('#fields [data-contact-edit="name"]', '신한대출 김과장')
        self.wait(200)
        self.assertIn('이름 : 신한대출 김과장', self.text())

    def test_time_wheel_defaults_to_1000(self):
        # 시간 칸을 열면 10:00 에서 시작하고, 초기화하면 빈칸으로 돌아간다
        self.pick('t3')
        self.page.click('#fields [data-seg="view"][data-value="detail"]')
        self.wait(150)
        self.page.click('#fields [data-time-chip="start"]')
        self.wait(200)
        self.assertEqual(self.wheel_value('#wheelpop'), ['10', '0'])
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="start"]').strip(), '10:00')
        hours = self.js("""() => [...document.querySelectorAll('#wheelpop [data-wheel-col="h"] .wheel-item')]
            .map(i => i.dataset.wheelVal)""")
        self.assertEqual(hours, [str(h) for h in range(0, 24)], '시 열은 00~23시')
        self.page.click('#wheelpop [data-wheel-reset]')
        self.wait(150)
        self.assertEqual(self.page.inner_text('#fields [data-time-chip="start"]').strip(), '시작 시각')

    # ============================================================== v1.3.0 피드백(9장) 회귀
    def test_t20_vendor_list_button_and_modal(self):
        # PC에서는 「목록」 버튼 없이 폼에서 다 보고, 폰에서는 비우기 바로 왼쪽 「목록」으로 창을 연다
        self.pick('t2')
        self.assertTrue(self.page.query_selector('#btn-vendor-list').is_hidden(), '다른 문자에는 목록이 없다')
        self.pick('t20')
        self.assertTrue(self.page.query_selector('#btn-vendor-list').is_hidden(), 'PC에서는 목록 버튼을 두지 않는다')
        self.page.wait_for_timeout(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .contact-list .contact:not(.is-new)')), 33,
                         'PC는 폼에서 기본 대출 33명이 다 보인다')

        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t20"]')
        page.wait_for_timeout(220)
        self.assertFalse(page.query_selector('#btn-vendor-list').is_hidden(), '폰에는 목록 버튼이 있다')
        self.assertEqual(page.inner_text('#btn-vendor-list').strip(), '목록', '글자는 「목록」만')
        gap = page.evaluate("""() => {
          const a = document.querySelector('#btn-vendor-list').getBoundingClientRect();
          const b = document.querySelector('#btn-reset').getBoundingClientRect();
          const head = document.querySelector('.form-panel .panel-head').getBoundingClientRect();
          return {gap: b.left - a.right, right: head.right - b.right, w: a.width, h: a.height};
        }""")
        self.assertGreaterEqual(gap['gap'], 0, '목록은 비우기 왼쪽')
        self.assertLessEqual(gap['gap'], 8, f"목록과 비우기 사이가 멀다 {gap}")
        self.assertLessEqual(gap['w'], 78, f"목록 버튼이 넓다 {gap}")
        self.assertLessEqual(gap['right'], 18, '머리 오른쪽 끝에 붙어 있다')
        page.click('#btn-vendor-list')
        page.wait_for_timeout(220)
        self.assertTrue(page.is_visible('#vendor-list .modal-card'))
        self.assertIn('대출', page.inner_text('#vendor-list-body'), '지금 고른 분야의 목록')
        # 기본 명단(대출 33명) 위에 세 곳을 더하고 두 곳을 지운다
        rows = page.query_selector_all('#vendor-list .contact:not(.is-new)')
        self.assertEqual(len(rows), 33, '기본 대출 33명이 목록에 다 보인다')
        for n, ph in (('A상담사', '010-1111-2222'), ('B상담사', '010-3333-4444'), ('C상담사', '010-5555-6666')):
            page.fill('#vendor-list [data-vl-new="name"]', n)
            page.fill('#vendor-list [data-vl-new="phone"]', ph)
            page.click('#vendor-list [data-vl-add]')
            page.wait_for_timeout(180)
        names = page.evaluate("""() => [...document.querySelectorAll('#vendor-list .contact:not(.is-new)')]
            .map(c => c.querySelector('.contact-inp').value)""")
        self.assertEqual(len(names), 36)
        self.assertEqual(names[:3], ['A상담사', 'B상담사', 'C상담사'], '★한 새 업체가 목록 창에서도 맨 위')
        # 지우면 ★한 색이 먼저 사라지고 스크롤은 그대로
        page.click('#vendor-list [data-vl-del]')
        page.wait_for_timeout(280)
        page.click('#vendor-list [data-vl-del]')
        page.wait_for_timeout(280)
        self.assertEqual(len(page.query_selector_all('#vendor-list .contact:not(.is-new)')), 34)
        self.assertEqual(len(page.query_selector_all('#vendor-list .contact-star.is-on')), 1)
        # 남은 C상담사의 ★를 껐다 켜도 그대로 센다
        page.evaluate("""() => {
          const row = [...document.querySelectorAll('#vendor-list .contact:not(.is-new)')]
            .find(c => c.querySelector('.contact-inp').value === 'C상담사');
          row.querySelector('.contact-star').click();
        }""")
        page.wait_for_timeout(250)
        self.assertEqual(len(page.query_selector_all('#vendor-list .contact-star.is-on')), 0)
        page.evaluate("""() => {
          const row = [...document.querySelectorAll('#vendor-list .contact:not(.is-new)')]
            .find(c => c.querySelector('.contact-inp').value === 'C상담사');
          row.querySelector('.contact-star').click();
        }""")
        page.wait_for_timeout(250)
        self.assertEqual(len(page.query_selector_all('#vendor-list .contact-star.is-on')), 1)
        # 목록에서 지운 것은 연락처에도 바로 반영
        page.click('#btn-vendor-list-done')
        page.wait_for_timeout(220)
        self.assertFalse(page.is_visible('#vendor-list .modal-card'))
        self.assertTrue(page.query_selector('#btn-vendor-list-close'))
        self.assertEqual(errors, [])
        ctx.close()

    def test_t20_favorites_show_in_contacts(self):
        # 분야별 즐겨찾기 두 곳이 「연락처」에 기본으로 보이고, 체크는 풀린 상태
        contacts = {'대출': [
            {'id': 'c1', 'name': '신한 김과장', 'phone': '01011112222', 'fav': True},
            {'id': 'c2', 'name': '국민 이대리', 'phone': '01033334444', 'fav': True},
            {'id': 'c3', 'name': '우리 박주임', 'phone': '01055556666', 'fav': False},
        ]}
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't20', 'stage': 'all', 'contacts': contacts,
            'data': {}
        })
        try:
            page.wait_for_timeout(200)
            rows = page.evaluate("""() => [...document.querySelectorAll('#fields .contact-list .contact:not(.is-new)')].map(c => ({
                name: c.querySelector('.contact-inp').value,
                checked: c.querySelector('.contact-check').classList.contains('is-on')}))""")
            names = [r['name'] for r in rows]
            self.assertEqual(names[:3], ['신한 김과장', '국민 이대리', '우리 박주임'], '★ 즐겨찾기가 위로')
            self.assertEqual(len(names), 36, '기본 33명도 함께 보인다 (숨기지 않는다)')
            self.assertTrue(all(not r['checked'] for r in rows), '기본은 체크 해제')
            # 체크하면 문자에 들어간다
            page.query_selector('#fields .contact-list .contact-check').click()
            page.wait_for_timeout(200)
            body = page.input_value('#preview')
            self.assertIn('이름 : 신한 김과장', body)
            self.assertNotIn('우리 박주임', body)
        finally:
            ctx.close()

    def test_t18_common_deal_box(self):
        # 공동중개 매물 요청 — [매매][전세][월세] + 금액(+입주일)이 한 박스
        self.pick('t18')
        self.assertGreaterEqual(len(self.page.query_selector_all('#fields [data-seg="trade"]')), 3)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-date-mode="movein"]')), 3,
                         '입주일 협의·고정·기간')
        self.assertIn('고객 특징', self.page.inner_text('#fields'))
        self.assertNotIn('손님 특징', self.page.inner_text('#fields'))
        self.page.click('#fields [data-seg="trade"][data-value="월세"]')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="deposit"]')), 1)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 1)
        self.page.fill('#fields [data-field="deposit"]', '10000')
        self.page.fill('#fields [data-field="rent"]', '250')
        self.wait(200)
        self.assertIn('- 보증금 : 1억\n- 월세 : 250만 원까지', self.text())

    # ============================================================== v1.4.0 피드백(8장) 회귀
    def test_v140_common_schedule_parts_add_remove_subtotal(self):
        # 약정금·가계약금·계약금·중도금·잔금 모두 (+)(−) 로 차수를 더하고 뺄 수 있다
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '76000')
        self.pay_fill('gyeyak', 7600)
        self.pay_fill('jung', 19000)
        self.pay_add('jung')
        rows = self.pay_rows()
        self.assertEqual([(r['item'], r['idx'], r['name']) for r in rows if r['item'] == 'jung'],
                         [('jung', 0, '중도금 1차'), ('jung', 1, '중도금 2차')])
        self.pay_fill('jung', 9500, idx=1)
        # 소계는 그 항목의 마지막 차수 오른쪽 아래에
        subs = self.js("""() => [...document.querySelectorAll('#fields .pay-sub')].map(e => ({
            key: e.dataset.paySub, text: e.textContent,
            row: e.closest('.pay-row').dataset.payItem + e.closest('.pay-row').dataset.payIdx,
            last: e.closest('.pay-row').nextElementSibling === null ||
                  e.closest('.pay-row').nextElementSibling.dataset.payItem !== 'jung'}))""")
        self.assertEqual(len(subs), 1, '차수가 둘 이상인 항목만 소계를 보인다')
        self.assertEqual(subs[0]['key'], 'jung')
        self.assertIn('285,000,000', subs[0]['text'])
        self.assertIn('2억 8,500만', subs[0]['text'])
        self.assertEqual(subs[0]['row'], 'jung1', '마지막 차수 줄에 붙는다')
        # 잔금은 중도금 합계를 뺀 나머지
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '39,900')
        body = self.text()
        self.assertIn('- 중도금 1차 25% : 190,000,000원', body)
        self.assertIn('- 중도금 2차 12.5% : 95,000,000원', body)
        # (−) 는 그 차수만 뺀다
        self.pay_del('jung', idx=1)
        self.assertEqual(len([r for r in self.pay_rows() if r['item'] == 'jung']), 1)
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-sub')), 0)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '49,400')
        # 1차를 빼면 2차가 1차로 올라온다
        self.pay_add('gyeyak')
        self.pay_fill('gyeyak', 2000, idx=1)
        self.pay_fill('gyeyak', 7600, idx=0)
        self.pay_del('gyeyak', idx=0)
        rows = [r for r in self.pay_rows() if r['item'] == 'gyeyak']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['amt'], '2,000', '2차가 1차로 올라온다')
        # 다섯 항목 모두 (+)(−) 가 늘 있다
        for key in ('yakjeong', 'jeong', 'gyeyak', 'jung', 'jan'):
            with self.subTest(item=key):
                self.assertEqual(len(self.page.query_selector_all(f'#fields [data-pay-add="{key}"]')), 1)
                self.assertEqual(len(self.page.query_selector_all(f'#fields [data-pay-del="{key}"]')), 1)

    def test_v140_schedule_total_excludes_deposits(self):
        # 총합계 = 계약금 + 중도금 + 잔금 (약정금·가계약금은 빼고), 잔금 = 매매가 − 계약금 − 중도금
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '76000')
        self.pay_fill('gyeyak', 7600)
        self.pay_fill('jung', 19000)
        self.assertEqual(self.page.inner_text('.pay-total').replace('\n', ' '), '총합계 760,000,000원 (7억 6천만원)')
        self.pay_fill('yakjeong', 1000)
        self.pay_fill('jeong', 3000)
        self.assertIn('760,000,000원', self.page.inner_text('.pay-total'), '약정금·가계약금은 총합계에 안 들어간다')
        body = self.text()
        # 계약일 안내 — 약정금 전액 반환 + 계약금 전액 / 가계약금 제외한 나머지
        self.assertIn('기지급한 약정금 10,000,000원은 계약일에 전액 반환받고, 계약금 76,000,000원은 약정금을 차감하지 않고 전액 입금합니다.', body)
        self.assertIn('기지급한 가계약금 30,000,000원은 계약금에 포함하며, 계약일에는 계약금 총액 76,000,000원 중 차액 46,000,000원을 지급합니다.', body)
        self.assertNotIn('[', body)
        self.assertNotIn(']', body)

    def test_v140_schedule_percent_two_way(self):
        # 퍼센트 먼저 → 금액 자동, 금액 먼저 → 퍼센트 자동 (기준 = 매매가)
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '50000')
        self.pay_rate('gyeyak', 10)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]'), '5,000')
        self.pay_rate('jung', 20)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jung"][data-pay-idx="0"]'), '10,000')
        self.pay_fill('jung', 7500)
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="jung"][data-pay-idx="0"]'), '15')
        # 전세·월세는 보증금이 기준
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(150)
        self.page.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '')
        self.page.fill('#fields [data-field="price"]', '10000')
        self.pay_rate('gyeyak', 10)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]'), '1,000')
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '9,000')

    def test_v140_t10_same_schedule_format(self):
        # 계약 일정 안내도 매매·전세·월세 모두 같은 다섯 항목 포맷을 쓴다
        for trade, base_field, base in (('매매', 'amount', '76000'), ('전세', 'amount', '10000'), ('월세', 'deposit', '10000')):
            with self.subTest(trade=trade):
                self.pick_with('t10', {'kind': '잔금'})
                self.page.click(f'#fields [data-prop-trade="prop"][data-value="{trade}"]')
                self.wait(180)
                self.page.fill(f'#fields [data-money="{base_field}"]', base)
                self.wait(150)
                names = [r['name'] for r in self.pay_rows()]
                self.assertEqual(names, ['약정금', '가계약금', '계약금', '중도금', '잔금'])
                self.pay_rate('gyeyak', 10)
                expect = '7,600' if trade == '매매' else '1,000'
                self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]'), expect)

    def test_v140_mortgage_holder_and_amount_one_row(self):
        # 근저당 말소 특약 — 채권자 | 채권최고액 한 줄 반반 (기본 1줄, 빈 값)
        self.pick('t8')
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 0,
                         '근저당 토글을 켜기 전에는 줄이 없어야 한다')
        self.page.click('#fields [data-toggle="mortgage"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 1, '기본은 1줄')
        box = self.js("""() => {
          const holder = document.querySelector('#fields [data-mtg-holder="0"]');
          const amount = document.querySelector('#fields [data-mtg-amount="0"]');
          if (!holder || !amount) return null;
          const h = holder.getBoundingClientRect(), a = amount.getBoundingClientRect();
          const cells = [...holder.closest('.pair-row').querySelectorAll('.pair-cell')].map(c => c.getBoundingClientRect().width);
          return {holder: {l: h.left, r: h.right, t: h.top}, amount: {l: a.left, r: a.right, t: a.top},
                  sameRow: Math.abs(h.top - a.top) < 6, leftFirst: h.left < a.left, cells,
                  holderValue: holder.value, amountValue: amount.value};
        }""")
        self.assertIsNotNone(box, '채권자·채권최고액 칸이 없다')
        self.assertTrue(box['sameRow'], '두 칸이 한 줄이 아니다')
        self.assertTrue(box['leftFirst'], '채권자가 왼쪽')
        self.assertEqual(box['holderValue'], '', '채권자 칸이 빈 값으로 시작해야 한다')
        self.assertEqual(box['amountValue'], '', '채권최고액 칸이 빈 값으로 시작해야 한다')
        self.assertEqual(len(box['cells']), 2)
        self.assertAlmostEqual(box['cells'][0], box['cells'][1], delta=2.0, msg='반반이 아니다')
        self.page.fill('#fields [data-mtg-holder="0"]', '카카오뱅크')
        self.page.fill('#fields [data-mtg-amount="0"]', '12000')
        self.wait(200)
        self.assertIn('등기사항전부증명서상 카카오뱅크를 채권자로 하는 채권최고액 120,000,000원 (1억 2천만 원)의 근저당권 1건이 설정된 상태이며', self.text())

    def test_v140_stage_tabs_uniform(self):
        # 상단 카테고리 탭 — 다섯 개가 같은 폭·높이·글자 크기로 한 줄에 다 보인다
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                page.goto(BASE, wait_until='networkidle')
                page.wait_for_timeout(200)
                tabs = page.evaluate("""() => [...document.querySelectorAll('.stage-tabs .tab')].map(t => {
                    const r = t.getBoundingClientRect(), cs = getComputedStyle(t);
                    return {w: +r.width.toFixed(1), h: +r.height.toFixed(1), t: +r.top.toFixed(1),
                            fs: cs.fontSize, pad: cs.padding, bw: cs.borderWidth}; })""")
                self.assertEqual(len(tabs), 5)
                self.assertEqual(len(set(t['h'] for t in tabs)), 1, f'탭 높이가 다르다 {tabs}')
                self.assertEqual(len(set(t['fs'] for t in tabs)), 1, f'글자 크기가 다르다 {tabs}')
                self.assertEqual(len(set(t['pad'] for t in tabs)), 1, f'패딩이 다르다 {tabs}')
                self.assertEqual(len(set(t['bw'] for t in tabs)), 1, f'테두리가 다르다 {tabs}')
                self.assertEqual(len(set(t['t'] for t in tabs)), 1, f'한 줄이 아니다 {tabs}')
                if w < 900:
                    self.assertEqual(len(set(t['w'] for t in tabs)), 1, f'폭이 다르다 {tabs}')
                    bar = page.evaluate("""() => { const b = document.querySelector('.stage-tabs');
                        return {scroll: b.scrollWidth, client: b.clientWidth}; }""")
                    self.assertLessEqual(bar['scroll'], bar['client'] + 1, '가로로 잘려 스크롤된다')
                ctx.close()

    def test_v140_no_type_direction_field_anywhere(self):
        # 타입·방향(동·호수를 넣으면 자동) 칸은 모든 매물 입력칸에서 사라졌다
        for tid in ('t2', 't3', 't5', 't7', 't19', 't8', 't10'):
            with self.subTest(tid=tid):
                self.pick(tid)
                self.assertNotIn('타입·방향', self.page.inner_text('#fields'))
                self.assertEqual(len(self.page.query_selector_all('#fields [data-key="typeInfo"]')), 0)
                self.assertEqual(len(self.page.query_selector_all('#fields .prop-type')), 0)

    def test_v140_calendar_popup_has_no_tip(self):
        # 달력 팝업 아래 안내 멘트는 없다 (입주일 기간 칸 포함)
        self.pick('t2')
        self.page.click('#fields [data-date-mode="movein"][data-value="기간"]')
        self.wait(150)
        self.page.click('#fields [data-date="moveinStart"]')
        self.wait(200)
        self.assertTrue(self.page.is_visible('#calpop'))
        self.assertEqual(len(self.page.query_selector_all('#calpop .cal-tip')), 0)
        self.assertNotIn('날짜를 고르면', self.page.inner_text('#calpop'))
        self.page.click('#calpop [data-cal-close]')

    def test_v140_trade_row_spacing_compact(self):
        # [매매][전세][월세] 줄 위아래 여백은 일반 폼 간격 — 위아래로 벌어지지 않는다
        self.pick('t10')
        gaps = self.js("""() => {
          const blk = document.querySelector('#fields .prop-money').getBoundingClientRect();
          const seg = document.querySelector('#fields [data-prop-trade="prop"]').closest('.seg').getBoundingClientRect();
          const dong = document.querySelector('#fields [data-key="dong"]').getBoundingClientRect();
          const whenField = document.querySelector('#fields [data-date="when"]').closest('.field').getBoundingClientRect();
          return {above: blk.top - dong.bottom, below: whenField.top - blk.bottom,
                  segInBlock: +(seg.top - blk.top).toFixed(1)};
        }""")
        self.assertLessEqual(gaps['above'], 20, f"거래유형 위 여백이 넓다 {gaps}")
        self.assertLessEqual(gaps['below'], 40, f"거래유형 아래 여백이 넓다 {gaps}")
        self.assertGreaterEqual(gaps['segInBlock'], 0, '거래유형 버튼은 블록 안에 있다')


    # ============================================================== v1.4.1 레이아웃 수정(5가지) 회귀

    def _open(self, page, tid, mobile=True):
        if mobile:
            page.click('#btn-sheet')
            page.wait_for_timeout(150)
            page.click(f'#sheet-list [data-id="{tid}"]')
        else:
            page.click(f'#tpl-list [data-id="{tid}"]')
        page.wait_for_timeout(220)

    def test_v141_category_names_and_one_line(self):
        # 카테고리 이름 4종 간소화 + 390px에서 다섯 탭이 같은 크기로 줄바꿈 없이 한 줄
        want = ['전체', '접수·홍보', '방문·집보기', '약정·계약', '잔금·만기']
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(220)
                info = page.evaluate("""() => {
                  const tabs = [...document.querySelectorAll('.stage-tabs .tab')];
                  const bar = document.querySelector('.stage-tabs');
                  return {texts: tabs.map(t => t.textContent.trim()),
                    sizes: tabs.map(t => { const r = t.getBoundingClientRect(); const cs = getComputedStyle(t);
                      const rg = document.createRange(); rg.selectNodeContents(t);
                      const rects = [...rg.getClientRects()].filter(x => x.width > 0.5);
                      const lines = new Set(rects.map(x => Math.round(x.top))).size;
                      const textW = Math.max(...rects.map(x => x.width));
                      return {w: +r.width.toFixed(1), h: +r.height.toFixed(1), top: +r.top.toFixed(1),
                              fs: cs.fontSize, ws: cs.whiteSpace, lines, textW: +textW.toFixed(1),
                              inner: +(r.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
                                - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth)).toFixed(1)};
                    }),
                    scroll: bar.scrollWidth, client: bar.clientWidth};
                }""")
                self.assertEqual(info['texts'], want)
                for t, s in zip(info['texts'], info['sizes']):
                    with self.subTest(tab=t):
                        self.assertEqual(s['lines'], 1, f'{t} 탭이 한 줄이 아니다 {s}')
                        self.assertEqual(s['ws'], 'nowrap', f'{t} 탭에 nowrap이 없다')
                        self.assertLessEqual(s['textW'], s['inner'] + 0.5, f'{t} 탭 글자가 칸보다 넓다 {s}')
                self.assertEqual(len(set(s['h'] for s in info['sizes'])), 1, '탭 높이가 다르다')
                self.assertEqual(len(set(s['fs'] for s in info['sizes'])), 1, '탭 글자 크기가 다르다')
                self.assertEqual(len(set(s['top'] for s in info['sizes'])), 1, '탭이 한 줄에 있지 않다')
                if w < 900:
                    self.assertEqual(len(set(s['w'] for s in info['sizes'])), 1, '탭 폭이 다르다')
                    self.assertLessEqual(info['scroll'], info['client'] + 1, '탭 줄이 가로로 넘친다')
                # 목록 머리·문구 편집 카테고리도 같은 이름
                heads = page.evaluate("""() => [...document.querySelectorAll('#tpl-list .list-stage')]
                    .map(e => e.textContent.trim())""")
                self.assertEqual(heads, ['접수·홍보 · 5종', '방문·집보기 · 5종',
                                         '약정·계약 · 4종', '잔금·만기 · 3종'])
                opts = page.evaluate("""() => [...document.querySelectorAll('#te-stage option')].map(o => o.textContent.trim())""")
                self.assertEqual(opts, ['접수·홍보', '방문·집보기', '약정·계약', '잔금·만기'])
                self.assertEqual(errors, [])
                ctx.close()

    def test_v141_trade_labels_keep_height(self):
        # 매매·전세·월세 어느 쪽이든 금액칸 위 이름표가 늘 있어 버튼·입력칸 Y가 1px도 안 움직인다
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(220)
                self._open(page, 't10', mobile=w < 900)
                seen = {}
                for trade, caps in (('매매', ['매매가']), ('전세', ['보증금']), ('월세', ['보증금', '월세'])):
                    page.click(f'#fields [data-prop-trade="prop"][data-value="{trade}"]')
                    page.wait_for_timeout(180)
                    info = page.evaluate("""() => {
                      const pm = document.querySelector('#fields .prop-money');
                      const box = e => { const r = e.getBoundingClientRect();
                        return {t: +r.top.toFixed(1), b: +r.bottom.toFixed(1), l: +r.left.toFixed(1), w: +r.width.toFixed(1)}; };
                      const capsBox = pm.querySelector('.money-caps');
                      return {seg: box(pm.querySelector('.seg.is-trade')),
                              caps: [...pm.querySelectorAll('.money-cap')].map(e => e.textContent.trim()),
                              capsBox: box(capsBox),
                              inputs: [...pm.querySelectorAll('.money-box')].map(box)};
                    }""")
                    seen[trade] = info
                    self.assertEqual(info['caps'], caps, f'{trade} 이름표')
                tops = [s['seg']['t'] for s in seen.values()]
                self.assertEqual(len(set(tops)), 1, f'거래유형 버튼 세로 위치가 흘들린다 {tops}')
                firstInputTops = [s['inputs'][0]['t'] for s in seen.values()]
                self.assertEqual(len(set(firstInputTops)), 1, f'금액칸 세로 위치가 흘들린다 {firstInputTops}')
                capTops = [s['capsBox']['t'] for s in seen.values()]
                capHeights = [s['capsBox']['b'] - s['capsBox']['t'] for s in seen.values()]
                self.assertEqual(len(set(capTops)), 1, f'이름표 자리가 흘들린다 {capTops}')
                self.assertEqual(len(set(capHeights)), 1, f'이름표 높이가 다르다 {capHeights}')
                # 이름표는 금액칸 바로 위에 붙어 있다
                for trade, s in seen.items():
                    self.assertAlmostEqual(s['capsBox']['b'], s['inputs'][0]['t'], delta=0.5,
                                           msg=f'{trade} 이름표와 금액칸 사이가 벌어짐')
                # 월세는 두 칸을 번갈아 쓴다
                pair = seen['월세']['inputs']
                self.assertEqual(len(pair), 2, '월세는 보증금·월세 두 칸')
                self.assertAlmostEqual(pair[0]['w'], pair[1]['w'], delta=1.0, msg='두 칸 폭이 다르다')
                self.assertLess(pair[0]['l'] + pair[0]['w'], pair[1]['l'] + 0.5, '두 칸이 나란하지 않다')
                self.assertEqual(errors, [])
                ctx.close()

    def test_v141_pay_row_head_and_steps(self):
        # 지급 일정 — 이름은 행 맨 위 왼쪽 한 줄, (+)(−)는 행 오른쪽 끝 위
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                               is_mobile=w < 500, has_touch=w < 500)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE, wait_until='networkidle')
                page.evaluate('localStorage.clear()')
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(220)
                self._open(page, 't8', mobile=w < 900)
                page.evaluate("""() => { const b = document.querySelector('#fields .pay-row[data-pay-item="jeong"] [data-pay-add]');
                    b.scrollIntoView({block: 'center'}); b.click(); }""")
                page.wait_for_timeout(250)
                info = page.evaluate("""() => {
                  const box = e => { const r = e.getBoundingClientRect();
                    return {t: +r.top.toFixed(1), b: +r.bottom.toFixed(1), l: +r.left.toFixed(1), rt: +r.right.toFixed(1)}; };
                  return [...document.querySelectorAll('#fields .pay-row')].map(r => {
                    const row = r.getBoundingClientRect();
                    const nm = r.querySelector('.pay-name-text'), steps = r.querySelector('.pay-steps');
                    const date = r.querySelector('.date-btn'), amount = r.querySelector('.money-box');
                    const hint = r.querySelector('.pay-hint'), rate = r.querySelector('.pay-rate');
                    const nw = nm.getBoundingClientRect(), sw = steps.getBoundingClientRect();
                    return {label: nm.textContent.trim(), name: box(nm), steps: box(steps),
                            row: box(r), date: box(date), amount: box(amount), hint: box(hint),
                            rate: rate ? box(rate) : null,
                            nameClipped: nm.scrollWidth > nm.clientWidth + 1,
                            nameW: +nw.width.toFixed(1), stepsW: +sw.width.toFixed(1),
                            nameLeft: +(nw.left - row.left).toFixed(1),
                            stepsRight: +(row.right - sw.right).toFixed(1),
                            stepsAboveInput: sw.bottom <= r.querySelector('.money-box').getBoundingClientRect().top + 0.5};
                  });
                }""")
                labels = [r['label'] for r in info]
                self.assertEqual(labels, ['약정금', '가계약금 1차', '가계약금 2차', '계약금', '중도금', '잔금'])
                for r in info:
                    with self.subTest(row=r['label']):
                        self.assertFalse(r['nameClipped'], f"{r['label']} 이름이 잘린다")
                        self.assertLessEqual(r['nameLeft'], 1.5, '이름은 왼쪽 정렬')
                        self.assertLessEqual(r['stepsRight'], 1.5, '(+)(−)는 행 오른쪽 끝')
                        self.assertTrue(r['stepsAboveInput'], '(+)(−)는 입력칸 위 윗줄')
                        # 이름과 (+)(−)가 겹치지 않고 사이가 벌어져 있다
                        self.assertLess(r['name']['rt'] + r['stepsW'], r['steps']['l'] + 0.5,
                                        f"{r['label']} 이름과 단추가 겹진다")
                        # 일정 칸과 금액 칸은 환산 줄이 있든 없든 위쪽 선과 높이가 같다
                        self.assertAlmostEqual(r['date']['t'], r['amount']['t'], delta=0.6,
                                               msg=f"{r['label']} 일정 칸과 금액 칸의 위쪽이 어긋난다")
                        self.assertAlmostEqual(r['date']['b'] - r['date']['t'],
                                               r['amount']['b'] - r['amount']['t'], delta=0.6,
                                               msg=f"{r['label']} 일정 칸과 금액 칸의 높이가 다르다")
                        # 환산 줄은 금액칸 바로 아래, 칸 너비를 그대로 쓴다
                        self.assertAlmostEqual(r['hint']['l'], r['amount']['l'], delta=1.0,
                                               msg='환산 줄이 금액칸 왼쪽에 맞춰지지 않았다')
                        self.assertGreaterEqual(r['hint']['t'], r['amount']['b'] - 0.5, '환산 줄은 금액칸 아래')
                        self.assertLessEqual(r['hint']['rt'], r['amount']['rt'] + 1.0, '환산 줄이 금액칸 밖으로')
                        if r['rate']:
                            self.assertAlmostEqual((r['rate']['t'] + r['rate']['b']) / 2,
                                                   (r['amount']['t'] + r['amount']['b']) / 2, delta=1.5,
                                                   msg='% 칸이 금액칸 세로 가운데가 아니다')
                            self.assertLessEqual(r['rate']['l'] - r['row']['l'], 1.5, '% 칸은 왼쪽 정렬')
                # 소계 줄은 마지막 차수 오른쪽 아래에 붙고 행을 흘들리지 않는다
                sub = page.evaluate("""() => { const s = document.querySelector('#fields .pay-sub');
                  if (!s) return null; const r = s.getBoundingClientRect();
                  const row = s.closest('.pay-row').getBoundingClientRect();
                  return {right: +(row.right - r.right).toFixed(1), left: +(r.left - row.left).toFixed(1)}; }""")
                self.assertIsNotNone(sub, '다차수 소계 줄이 없다')
                self.assertLessEqual(sub['right'], 1.5, '소계는 행 오른쪽 끝')
                self.assertEqual(errors, [])
                ctx.close()

    def test_v141_pay_hint_under_amount_only(self):
        # 환산 글자는 일정 칸 아래가 아니라 금액 칸 바로 아래에 있다
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '76000')
        self.pay_fill('jeong', 7600)
        self.pay_fill('jung', 19000)
        self.page.evaluate('document.activeElement && document.activeElement.blur()')
        self.wait(250)
        info = self.js("""() => [...document.querySelectorAll('#fields .pay-row')].map(r => {
          const hint = r.querySelector('.pay-hint'), amt = r.querySelector('.money-box');
          const date = r.querySelector('.date-btn');
          const hr = hint.getBoundingClientRect(), ar = amt.getBoundingClientRect(), dr = date.getBoundingClientRect();
          return {inField: !!hint.closest('.pay-amount'), text: hint.textContent.trim(),
                  leftDiff: +(hr.left - ar.left).toFixed(1), below: hr.top >= ar.bottom - 0.5,
                  underAmount: hr.left >= ar.left - 0.5 && hr.right <= ar.right + 0.5,
                  overlapsDate: hr.right > dr.left && hr.top < dr.bottom};
        })""")
        for r in info:
            with self.subTest(text=r['text']):
                self.assertTrue(r['inField'], '환산 줄이 금액 칸 안에 있지 않다')
                self.assertLessEqual(abs(r['leftDiff']), 1.0, '환산 줄이 금액칸 왼쪽에 맞춰지지 않았다')
                self.assertTrue(r['below'], '환산 줄이 금액칸 아래가 아니다')
                self.assertTrue(r['underAmount'], '환산 줄이 금액칸 폭을 벗어난다')
        self.assertIn('원', info[-1]['text'], '잔금 환산 줄이 비어 있다')

    # ============================================== v1.4.2 지급 일정 일직선 · 우측하단 환산 · 목록 버튼

    def _v142_page(self, w, h):
        ctx = self.browser.new_context(viewport={'width': w, 'height': h},
                                       is_mobile=w < 500, has_touch=w < 500)
        page = ctx.new_page()
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        return ctx, page, errs

    def test_v142_pay_row_straight_line(self):
        # 지급 일정 — 환산 줄이 한 줄·두 줄·없음 어느 경우에도 % · 일정 · 금액이 같은 위쪽 선, 같은 높이
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx, page, errs = self._v142_page(w, h)
                self._open(page, 't8', mobile=w < 900)
                page.fill('#fields [data-field="price"]', '76000')
                page.fill('#fields [data-pay-amt="jeong"][data-pay-idx="0"]', '1000')   # 환산 한 줄
                page.fill('#fields [data-pay-amt="jung"][data-pay-idx="0"]', '19000')   # 환산 한 줄
                page.eval_on_selector('#fields .pay-row[data-pay-item="jung"] [data-pay-add]',
                                      "e => { e.scrollIntoView({block: 'center'}); e.click(); }")  # 두 번째 차수
                page.wait_for_timeout(240)
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.wait_for_timeout(220)
                info = page.evaluate("""() => {
                  const box = e => { const r = e.getBoundingClientRect();
                    return {t: +r.top.toFixed(1), b: +r.bottom.toFixed(1), h: +r.height.toFixed(1)}; };
                  return [...document.querySelectorAll('#fields .pay-row')].map(r => {
                    const d = r.querySelector('.date-btn'), a = r.querySelector('.money-box');
                    const hint = r.querySelector('.pay-hint'), rate = r.querySelector('.pay-rate-inp');
                    return {label: r.querySelector('.pay-name-text').textContent.trim(),
                            date: box(d), amount: box(a), hintText: hint.textContent.trim(),
                            rate: rate ? box(rate) : null};
                  });
                }""")
                self.assertEqual(len(info), 6, '지급 일정 행 수')
                self.assertEqual([r['label'] for r in info],
                                 ['약정금', '가계약금', '계약금', '중도금 1차', '중도금 2차', '잔금'])
                for r in info:
                    with self.subTest(row=r['label']):
                        self.assertAlmostEqual(r['date']['t'], r['amount']['t'], delta=0.6,
                                               msg=f"{r['label']} 일정 칸과 금액 칸 위쪽이 어긋난다")
                        self.assertAlmostEqual(r['date']['h'], r['amount']['h'], delta=0.6,
                                               msg=f"{r['label']} 일정 칸과 금액 칸 높이가 다르다")
                        if r['rate']:
                            self.assertAlmostEqual((r['rate']['t'] + r['rate']['b']) / 2,
                                                   (r['amount']['t'] + r['amount']['b']) / 2, delta=1.5,
                                                   msg=f"{r['label']} % 칸이 금액 칸 세로 가운데가 아니다")
                self.assertEqual(errs, [])
                ctx.close()

    def test_v142_money_hints_right_bottom(self):
        # 앱 전체의 환산 줄(.money-hint)은 언제나 자기 금액칸의 우측 하단에 붙는다
        self.pick('t2')
        self.page.fill('#fields [data-money="amount"]', '17000')
        self.wait(200)
        aligned = self.js("""() => [...document.querySelectorAll('#fields .money-hint')].map(h => {
          const bx = h.closest('.money-field').querySelector('.money-box').getBoundingClientRect();
          const rg = document.createRange(); rg.selectNodeContents(h);
          const rects = [...rg.getClientRects()].filter(x => x.width > 0.5);
          const textRight = rects.length ? Math.max(...rects.map(x => x.right)) : bx.right;
          const hr = h.getBoundingClientRect();
          return {text: h.textContent.trim(), align: getComputedStyle(h).textAlign,
                  rightGap: +(bx.right - textRight).toFixed(1),
                  belowGap: +(hr.top - bx.bottom).toFixed(1), widthGap: +(bx.width - hr.width).toFixed(1)};
        })""")
        self.assertTrue(aligned, '환산 줄이 있는 화면에서 찾지 못했다')
        for a in aligned:
            with self.subTest(text=a['text']):
                self.assertEqual(a['align'], 'right', '환산 줄이 우측 정렬이 아니다')
                self.assertLessEqual(abs(a['rightGap']), 2.0, f"환산 글자가 칸 오른쪽 끝에 닿지 않는다 {a}")
                self.assertGreaterEqual(a['belowGap'], -0.5, '환산 줄이 금액칸 아래가 아니다')
                self.assertLessEqual(abs(a['widthGap']), 1.0, '환산 줄 폭이 금액칸과 다르다')
        # 월세 두 칸 · 계산기 금액칸도 같은 규칙
        self.pick('t14')
        self.page.fill('#fields [data-field="calcAmount"]', '76000')
        self.wait(200)
        calc = self.js("""() => [...document.querySelectorAll('#fields .money-hint')].map(h => ({
            align: getComputedStyle(h).textAlign, text: h.textContent.trim()}))""")
        self.assertTrue(calc, '계산기에 환산 줄이 없다')
        for a in calc:
            self.assertEqual(a['align'], 'right', f"계산기 환산 줄 {a}")
        self.pick('t2')
        self.page.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        self.wait(180)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '300')
        self.wait(200)
        pair = self.js("""() => [...document.querySelectorAll('#fields .money-pair .money-hint')].map(h => {
            const bx = h.closest('.money-field').querySelector('.money-box').getBoundingClientRect();
            const rg = document.createRange(); rg.selectNodeContents(h);
            const rects = [...rg.getClientRects()].filter(x => x.width > 0.5);
            return {align: getComputedStyle(h).textAlign, text: h.textContent.trim(),
                    rightGap: +(bx.right - Math.max(...rects.map(x => x.right))).toFixed(1)}; })""")
        self.assertEqual(len(pair), 2, '월세 보증금·월세 두 환산 줄')
        for a in pair:
            self.assertEqual(a['align'], 'right', f"월세 {a}")
            self.assertLessEqual(abs(a['rightGap']), 2.0, f"월세 환산 글자 위치 {a}")

    def test_v142_list_buttons_same_size(self):
        # 상단 헤더 「목록」과 전문가·협력업체 소개 「목록」은 높이·폭·패딩·글자·아이콘까지 같다
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx, page, errs = self._v142_page(w, h)
                self._open(page, 't20', mobile=w < 900)
                m = page.evaluate("""() => {
                  const of = sel => { const e = document.querySelector(sel); if (!e) return null;
                    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
                    const svg = e.querySelector('svg');
                    return {h: +r.height.toFixed(1), w: +r.width.toFixed(1), pad: cs.padding,
                            font: cs.fontSize, gap: cs.gap, radius: cs.borderRadius,
                            icon: svg ? +svg.getBoundingClientRect().width.toFixed(1) : null,
                            label: e.querySelector('.btn-label') ?
                              getComputedStyle(e.querySelector('.btn-label')).fontSize : null}; };
                  return {sheet: of('#btn-sheet'), vendor: of('#btn-vendor-list'), reset: of('#btn-reset')};
                }""")
                if w < 900:   # 폰에서는 헤더 「목록」이 보인다
                    for k in ('h', 'w', 'pad', 'font', 'gap', 'radius', 'icon', 'label'):
                        self.assertEqual(m['sheet'][k], m['vendor'][k], f'{k}가 다르다 {m}')
                    # 카드 머리에서 「목록」과 「비우기」도 같은 높이
                    self.assertAlmostEqual(m['vendor']['h'], m['reset']['h'], delta=0.5,
                                           msg=f"목록·비우기 높이가 다르다 {m}")
                else:
                    # PC에서는 폼에서 바로 다 보이므로 「목록」 버튼이 없다
                    self.assertEqual(m['vendor']['w'], 0, f"PC에는 목록 버튼이 없어야 한다 {m}")
                self.assertEqual(errs, [])
                ctx.close()

    def test_v142_vendor_placeholders(self):
        # 업체 입력칸은 예시 대신 「이름」·「연락처」
        self.pick('t20')
        ph = self.js("""() => [...document.querySelectorAll('#fields .contact-inp')]
            .map(e => e.placeholder)""")
        self.assertTrue(ph, '업체 입력칸이 없다')
        self.assertTrue(all(v in ('이름', '연락처') for v in ph), f'플레이스홀더 {ph}')
        self.assertEqual(ph[0], '이름')
        self.assertEqual(ph[1], '연락처')
        # 목록 창은 폰에서만 열리는 창이라 폰 화면으로 확인한다
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t20"]')
        page.wait_for_timeout(220)
        page.click('#btn-vendor-list')
        page.wait_for_timeout(250)
        mph = page.evaluate("""() => [...document.querySelectorAll('#vendor-list-body .contact-inp')]
            .map(e => e.placeholder)""")
        self.assertTrue(mph, '목록 모달 입력칸이 없다')
        self.assertTrue(all(v in ('이름', '연락처') for v in mph), f'모달 플레이스홀더 {mph}')
        ctx.close()

    def test_v142_trade_and_role_rows_match_input_height(self):
        # 거래유형·임대차 만기 버튼은 옆 금액칸과 같은 높이·같은 위쪽 선
        for w, h in ((390, 844), (1440, 900)):
            with self.subTest(viewport=f'{w}x{h}'):
                ctx, page, errs = self._v142_page(w, h)
                for tid in ('t2', 't19', 't10', 't14'):
                    self._open(page, tid, mobile=w < 900)
                    for trade in ('매매', '전세', '월세'):
                        sel = f'#fields [data-prop-trade][data-value="{trade}"]'
                        if page.query_selector(sel):
                            page.click(sel)
                        else:
                            sel2 = f'#fields [data-seg="calcTrade"][data-value="{trade}"]'
                            if page.query_selector(sel2):
                                page.click(sel2)
                        page.wait_for_timeout(150)
                        info = page.evaluate("""() => {
                          const pm = document.querySelector('#fields .prop-money');
                          if (!pm) return null;
                          const b = e => { const r = e.getBoundingClientRect();
                            return {t: +r.top.toFixed(1), h: +r.height.toFixed(1)}; };
                          const seg = pm.querySelector('.seg.is-trade');
                          const boxes = [...pm.querySelectorAll('.money-box')].map(b);
                          return {seg: b(seg), boxes: boxes};
                        }""")
                        if not info:
                            continue
                        with self.subTest(tid=tid, trade=trade):
                            for bx in info['boxes']:
                                self.assertAlmostEqual(info['seg']['t'], bx['t'], delta=0.6,
                                                       msg=f'{tid} {trade} 버튼과 금액칸 위쪽이 어긋난다')
                                self.assertAlmostEqual(info['seg']['h'], bx['h'], delta=0.6,
                                                       msg=f'{tid} {trade} 버튼과 금액칸 높이가 다르다')
                self._v142_open(page, 't15', w)
                info = page.evaluate("""() => {
                  const row = document.querySelector('#fields .field.is-role-months');
                  const b = e => { const r = e.getBoundingClientRect();
                    return {t: +r.top.toFixed(1), h: +r.height.toFixed(1)}; };
                  return {seg: b(row.querySelector('.seg.is-role')),
                          wrap: b(row.querySelector('.money-wrap.is-months'))};
                }""")
                self.assertAlmostEqual(info['seg']['t'], info['wrap']['t'], delta=0.6,
                                       msg=f'임대차 만기 버튼 {info}')
                self.assertAlmostEqual(info['seg']['h'], info['wrap']['h'], delta=0.6,
                                       msg=f'임대차 만기 버튼 높이 {info}')
                self.assertEqual(errs, [])
                ctx.close()

    def _v142_open(self, page, tid, w):
        page.evaluate("t => SMSApp.openTemplate(t, {})", tid)
        page.wait_for_timeout(220)


    # ============================================================== v1.4.3 전수 검증
    def build_body(self, tid, patch, ctx_extra=None):
        return self.js("""a => {
            const T = window.SMSTemplates;
            const t = T.TEMPLATES.find(x => x.id === a[0]);
            const d = Object.assign(T.defaultData(t), a[1] || {});
            const ctx = Object.assign({ office: '마래푸중앙부동산', phones: '010-4585-7365 / 02-312-7365',
                feeAccount: '우리은행 1002-762-106047 황호선', amountMode: 'won_eokman',
                contacts: T.defaultContacts() }, a[2] || {});
            return t.build(d, ctx);
        }""", [tid, patch, ctx_extra or {}])

    def test_v143_all_branches_fill_variables(self):
        # 17종 전 분기 — 넣은 값이 2차 수정본 문구 속에 그대로 들어가고, 빠진 자리·대괄호가 없다
        S = '마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'
        prop = {'complex': '마포래미안푸르지오', 'dong': '404', 'ho': '1903',
                'trade': '매매', 'amount': '247000', 'deposit': '', 'rent': '', 'price': ''}
        rent_prop = {'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '1203',
                     'trade': '전세', 'amount': '115000', 'deposit': '115000', 'rent': '', 'price': ''}
        wolse_prop = {'complex': '마포래미안푸르지오', 'dong': '101', 'ho': '302',
                      'trade': '월세', 'amount': '', 'deposit': '10000', 'rent': '300', 'price': ''}
        day = lambda y, m, d: {'date': '%s-%02d-%02d' % (y, m, d)}
        cases = [
            # (id, patch, 반드시 있어야 할 문구, 있으면 안 되는 문구)
            ('t1', {}, ['바쁘신 중에 통화해 주셔서 감사합니다.', '성심껏 도와드리겠습니다.', S], []),
            ('t2', {'prop': prop, 'moveinMode': '협의', 'option': '시스템에어컨, 올수리'},
             ['- 마포래미안푸르지오 404동 1903호', '- 거래조건 : 매매 24억 7천만',
              '- 입주 : 즉시입주(협의)', '- 옵션 : 시스템에어컨, 올수리', S],
             ['(매물)', '(금액)', '(입주)', '(옵션)']),
            ('t2', {'prop': prop, 'moveinMode': '고정', 'moveinStart': day(2026, 12, 1), 'moveinFix': '선호'},
             ['- 입주 : 26.12.01 (화) 선호'], ['(입주)']),
            ('t2', {'prop': prop, 'moveinMode': '기간', 'moveinStart': day(2026, 12, 1), 'moveinEnd': day(2026, 12, 31)},
             ['- 입주 : 26.12.01 (화) ~ 26.12.31 (목)'], ['(입주)']),
            ('t16', {'trade': '매매'}, ['마포래미안푸르지오 1단지 내 마래푸중앙부동산입니다.', '현재 매수를 희망하시는 손님이',
                                       '매도 의향이 있으시면', S], []),
            ('t16', {'trade': '전세'}, ['현재 전세를 희망하시는 손님이', '혹시 전세 임대 계획이 있으시거나', '임대 의향이 있으시면'], []),
            ('t16', {'trade': '월세'}, ['현재 월세를 희망하시는 손님이', '혹시 월세 임대 계획이 있으시거나', '임대 의향이 있으시면'], []),
            ('t18', {'trade': '매매', 'amount': '90000', 'area': '34', 'guestNote': '염리초 학부모'},
             ['- 매매 희망금액 : 9억까지', '- 희망 평형 : 34평', '- 고객 참고사항 : 염리초 학부모', S],
             ['(금액)', '(평형)', '(고객 특징)']),
            ('t18', {'trade': '전세', 'amount': '70000', 'moveinMode': '협의'},
             ['- 전세 보증금 : 7억까지', '- 입주 : 즉시입주(협의)'], ['(금액)', '(입주)']),
            ('t18', {'trade': '월세', 'deposit': '10000', 'rent': '250'},
             ['- 보증금 : 1억', '- 월세 : 250만 원까지'], ['(금액)원']),
            ('t19', {'items': [prop, rent_prop], 'emphasis': '급매 조율 가능'},
             ['🔑 매물 : 마포래미안푸르지오 404동 1903호', '🔑 거래조건 : 매매 24억 7천만',
              '✔️ 특징 : 급매 조율 가능', S], ['(매물)', '(가격)', '(강조 문구)']),
            ('t3', {'who': 'owner', 'view': 'simple', 'prop': rent_prop,
                    'when': dict(day(2026, 11, 28), hour=10, min=0)},
             ['전세 손님이 계셔서 집보기 가능 여부를 여쭙습니다.',
              '- 마포래미안푸르지오 208동 1203호 / 전세 11억 5천만',
              '- 희망 일시 : 11월 28일 (토) 10:00'], ['(방문 일시)', '(매물)']),
            ('t3', {'who': 'coagent', 'view': 'simple', 'prop': prop,
                    'when': dict(day(2026, 11, 28), hour=14, min=30)},
             ['사장님, 안녕하세요. 😊', '공동중개 및 집보기 가능 여부 여쭙습니다.',
              '- 희망 일시 : 11월 28일 (토) 14:30'], ['(방문 일시)']),
            ('t3', {'who': 'owner', 'view': 'detail', 'prop': prop, 'times': '11월 28일 (토) 10:00\n11월 29일 (일) 14:00'},
             ['매수 손님께서 집보기를 희망하셔서 방문 일정을 여쭙습니다.',
              '- 방문 희망 시간 : 11월 28일 (토) 10:00 / 11월 29일 (일) 14:00',
              '최대한 맞춰 조율하겠습니다.'], ['(방문 희망 시간)']),
            ('t3', {'who': 'coagent', 'view': 'detail', 'prop': prop, 'times': '11월 28일 (토) 10:00'},
             ['공동중개 및 집보기 일정을 문의드립니다.', '감사합니다, 사장님.'], ['(방문 희망 시간)']),
            ('t5', {'status': 'confirmed', 'detail': True, 'parking': True,
                    'when': dict(day(2026, 11, 28), hour=10, min=0), 'items': [prop]},
             ['- 방문 일시 : 2026년 11월 28일 토요일 10:00',
              '- 마포래미안푸르지오 404동 1903호 / 매매 24억 7천만',
              '주차가 필요하시면 미리 말씀해 주시기 바랍니다.', '약속된 일정에 뵙겠습니다.'], ['(방문 일시)', '(가격)']),
            ('t5', {'status': 'confirmed', 'detail': False, 'parking': False, 'when': dict(day(2026, 11, 28))},
             ['약속된 일정에 뵙겠습니다.'], ['- 마포래미안푸르지오', '주차가 필요하시면']),
            ('t5', {'status': 'pending', 'items': [rent_prop]},
             ['아래 매물의 집보기 일정을 현재 조율 중입니다.',
              '- 마포래미안푸르지오 208동 1203호 / 전세 11억 5천만'], ['(매물)', '- 매물 :']),
            ('t6', {}, ['🚘 주차 장소 안내드립니다.', '- 주차 장소 : 아현장로교회',
                        '- 주소 : 서울 마포구 마포대로 197-1', S], []),
            ('t7', {'items': [prop, rent_prop]},
             ['- 마포래미안푸르지오 404동 1903호 / 매매 24억 7천만',
              '- 마포래미안푸르지오 208동 1203호 / 전세 11억 5천만', S], ['(가격)', '- 매물 :']),
            ('t8', {'trade': '매매', 'kind': '가계약', 'price': '247000',
                    'address': '서울시 마포구 아현동 777 외 3필지',
                    'account': '국민 123456-01-234567 홍길동', 'prop': prop,
                    'yakjeongAmount': '1000', 'yakjeongDate': day(2026, 11, 27),
                    'jeongAmount': '3000', 'jeongDate': day(2026, 11, 28),
                    'gyeyakAmount': '24700', 'gyeyakDate': day(2026, 12, 5),
                    'jungAmount': '61750', 'jungDate': day(2027, 1, 10),
                    'janDate': day(2027, 2, 20), 'permit': True, 'mortgage': True,
                    'mortgageHolder': '주식회사 카카오뱅크', 'mortgageAmount': '12000'},
             ['아래 부동산의 매매 가계약 주요 내용을 안내드립니다.',
              '- 물건지 : 서울시 마포구 아현동 777 외 3필지 마포래미안푸르지오 404동 1903호',
              '- 입금계좌 : 국민은행 123456-01-234567 홍길동',
              '■ 계약금액 및 지급 일정', '- 매매대금 : 2,470,000,000원',
              '- 약정금 : 10,000,000원', '- 가계약금 : 30,000,000원',
              '- 계약금 10% : 247,000,000원', '- 중도금 25% : 617,500,000원',
              '- 잔금 : 1,605,500,000원',
              '계약금 지급 일정은 토지거래허가 진행 상황에 따라 쌍방이 협의하여 조정할 수 있습니다.',
              '기지급한 약정금 10,000,000원은 계약일에 전액 반환받고',
              '기지급한 가계약금 30,000,000원은 계약금에 포함하며',
              '■ 특약사항', '1. 본 부동산은 토지거래허가구역에 소재하므로',
              '4. 가계약 성립 후 정당한 사유 없이',
              '등기사항전부증명서상 주식회사 카카오뱅크를 채권자로 하는 채권최고액 120,000,000원',
              '위 내용에 동의하시는 경우 매도인께서는 입금계좌를 회신해 주시기 바랍니다.', S],
             ['[', ']']),
            ('t8', {'trade': '매매', 'kind': '계약', 'price': '247000', 'mortgage': True,
                    'mortgageHolder': '카카오뱅크', 'mortgageAmount': '12000'},
             ['아래 부동산의 매매계약 주요 내용을 안내드립니다.', '1. 계약 해제 시 계약금의 귀속 및 배액배상',
              '잔금일에 잔금 지급과 소유권이전등기 절차를 진행하며'], ['[', ']']),
            ('t8', {'trade': '전세', 'kind': '계약', 'price': '115000', 'rent': '',
                    'gyeyakAmount': '11500', 'gyeyakDate': day(2026, 12, 5), 'janDate': day(2026, 12, 20)},
             ['아래 부동산의 전세 계약 주요 내용을 안내드립니다.', '- 보증금 : 1,150,000,000원',
              '- 계약금 10% : 115,000,000원', '- 잔금 : 1,035,000,000원',
              '임대인은 임차인이 주택을 인도받은 후 전입신고 및 확정일자 부여 절차를 진행할 수 있도록 협조합니다.',
              '위 내용 확인 후 동의 여부를 회신해 주시면 감사하겠습니다.'], ['[', ']', '월차임']),
            ('t8', {'trade': '월세', 'kind': '가계약', 'price': '10000', 'rent': '300',
                    'jeongAmount': '1000', 'jeongDate': day(2026, 12, 1)},
             ['아래 부동산의 월세 가계약 주요 내용을 안내드립니다.', '- 보증금 : 100,000,000원',
              '- 월차임 : 3,000,000원', '위 내용에 동의하시는 경우 임대인께서는 입금계좌를 회신해 주시기 바랍니다.'],
             ['[', ']']),
            ('t10', {'prop': prop, 'kind': '가계약', 'when': dict(day(2026, 11, 28), hour=10, min=0)},
             ['마포래미안푸르지오 404동 1903호 가계약서 작성 일정과 준비사항을 안내드립니다.',
              '- 일시 : 2026년 11월 28일 토요일 10:00', '■ 매도인 준비사항', '■ 매수인 준비사항',
              '5. 가계약금', 'OTP와 1일 이체한도를 미리 확인해 주시기 바랍니다.',
              '공동명의 취득 시 각 명의자별 준비서류', S], ['(가계약 일시)']),
            ('t10', {'prop': prop, 'kind': '계약', 'jeongyakReturn': True, 'when': dict(day(2026, 12, 5))},
             ['매매계약 일정과 준비사항을 안내드립니다.', '3. 등기권리증\n4. 가계약금 반환 준비',
              '■ 매수인 준비사항'], ['[', ']']),
            ('t10', {'prop': rent_prop, 'trade': '전세', 'kind': '계약', 'priority': True, 'when': dict(day(2026, 12, 5))},
             ['임대차계약 일정과 준비사항을 안내드립니다.', '1. 확정일자 부여현황 (주민센터)',
              '기존 임대차계약서 등 선순위 임차인의 보증금과 임대차 기간을 확인할 수 있는 자료도 준비 부탁드립니다.',
              '■ 임차인 준비사항'], ['[', ']']),
            ('t10', {'prop': prop, 'trade': '매매', 'kind': '잔금', 'docs': True, 'when': dict(day(2027, 2, 20)),
                    'gyeyak': '24700', 'gyeyakDate': day(2026, 12, 5), 'jung': '61750',
                    'jan': '160550', 'account': '국민 123456-01-234567 홍길동'},
             ['잔금 일정 및 입금 내역을 안내드립니다.', '■ 금액 세부사항',
              '- 계약금 : 247,000,000원', '- 중도금 : 617,500,000원', '- 잔금 : 1,605,500,000원',
              '- 합계 : 2,470,000,000원', '- 입금계좌 : 국민은행 123456-01-234567 홍길동',
              '■ 매도인 준비사항', '2. 부동산 매도용 인감증명서 1통', '■ 매수인 준비사항',
              '※ 잔금 이체한도와 자금 준비 상황을 사전에 확인해 주시기 바랍니다.'], ['[', ']']),
            ('t10', {'prop': wolse_prop, 'trade': '월세', 'kind': '중도금', 'registry': True},
             ['중도금 일정 및 입금 내역을 안내드립니다.', '- 보증금 : 100,000,000원',
              '- 월차임 : 3,000,000원', '당일 입금 전 등기사항전부증명서를 다시 발급하여'], ['[', ']']),
            ('t11', {'trade': '매매'}, ['전자계약 진행 절차를 안내드립니다.', '매도인·매수인에게 문자 또는 카카오톡',
                                      '매매계약서를 확인하고 전자서명해 주시기 바랍니다.', '6. 계약 완료 후', S], []),
            ('t11', {'trade': '임대차'}, ['임대인·임차인에게 문자 또는 카카오톡', '임대차계약서를 확인하고 전자서명'], []),
            ('t12', {'owner': '공동'}, ['공동명의인 경우 명의자별로 각각 작성하시고', '■ 온라인 제출 절차',
                                      '■ 주요 증빙자료 예시', '- 가족 등으로부터 차입 : 차용증 등',
                                      '두 분 모두 제출하신 후 완료 여부를 알려주시면 감사하겠습니다.', S], ['[', ']']),
            ('t12', {'owner': '단독'}, ['자금조달 항목별 금액과 출처를 작성하시고',
                                      '제출하신 후 완료 여부를 알려주시면 감사하겠습니다.'], ['공동명의인 경우']),
            ('t15', {'role': '임대인', 'months': 2}, ['임대차계약 만기까지 약 2개월 남아 있어',
                                                    '임차인분과 미리 협의하신 내용이 있으실지',
                                                    '- 퇴거 예정이시면', '- 연장 예정이시면', S], ['임대인분과']),
            ('t15', {'role': '임차인', 'months': 5}, ['약 5개월 남아 있어', '임대인분과 미리 협의하신 내용이 있으실지'],
             ['임차인분과']),
        ]
        for tid, patch, want, forbid in cases:
            with self.subTest(tpl=tid, patch=str(patch)[:40]):
                body = self.build_body(tid, patch)
                for w in want:
                    self.assertIn(w, body, f'{tid} — {w!r} 가 없다')
                for f in forbid:
                    self.assertNotIn(f, body, f'{tid} — {f!r} 가 남아 있다')

    def test_v143_thanks_all_variants_and_greetings(self):
        # 10번 — 거주자·공동중개·고객 7종 × 안부 6종 전부 문구가 그대로 나오고 서명이 붙는다
        S = '마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'
        bad = self.js("""() => {
            const T = window.SMSTemplates, out = [];
            const ctx = { office: '마래푸중앙부동산', phones: '010-4585-7365 / 02-312-7365',
                          feeAccount: '', amountMode: 'won_eokman', contacts: T.defaultContacts() };
            const t = T.TEMPLATES.find(x => x.id === 't17');
            ['resident', 'coagent', 'guest'].forEach(target => {
              T.VARIANTS[target].forEach((text, i) => {
                T.GREETINGS.forEach(g => {
                  const d = T.defaultData(t);
                  d.target = target;
                  d.vpick = { resident: i, coagent: i, guest: i };
                  d.greets = [g.v];
                  const body = t.build(d, ctx);
                  if (body.indexOf(text) === -1) out.push(target + '/' + i + ' 문구');
                  if (body.indexOf(g.text) === -1) out.push(target + '/' + i + '/' + g.v + ' 안부');
                  if (!body.endsWith('마래푸중앙부동산 드림\\n010-4585-7365 / 02-312-7365')) out.push(target + '/' + i + ' 서명');
                  if (body.indexOf('[') !== -1 || body.indexOf(']') !== -1) out.push(target + '/' + i + ' 대괄호');
                });
              });
            });
            return out;
        }""")
        self.assertEqual(bad, [])
        body = self.build_body('t17', {'target': 'coagent', 'vpick': {'coagent': 4}, 'greets': ['weekend']})
        self.assertIn('오늘 함께해 주셔서 감사드립니다, 사장님.', body)
        self.assertIn('즐거운 주말 보내세요!', body)
        self.assertIn(S, body)

    def test_v143_vendor_all_categories_with_contacts(self):
        # 15번 — 6분야 전부, 상담사는 '이름', 업체는 '업체명'으로 44명 중 고른 사람이 그대로 들어간다
        S = '마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'
        picks = {
            '대출': ['d01', 'd33'], '세무사': ['s01'], '법무사': ['l01'],
            '인테리어': ['i01', 'i02'], '입주청소': ['c03'], '이사': ['m01', 'm02'],
        }
        intro = {
            '대출': '부동산 대출 상담을 받아보실 수 있는 상담사를 소개드립니다.',
            '세무사': '양도소득세·취득세 등 부동산 세금 관련 상담을 받아보실 수 있는 세무사를 소개드립니다.',
            '법무사': '소유권이전등기, 근저당권 말소 등 등기 업무를 상담받아 보실 수 있는 법무사를 소개드립니다.',
            '인테리어': '입주 전 인테리어 공사에 관해 상담 및 견적을 받아보실 수 있는 업체를 소개드립니다.',
            '입주청소': '입주청소 상담 및 견적을 받아보실 수 있는 업체를 소개드립니다.',
            '이사': '이사 일정과 비용에 관해 상담 및 견적을 받아보실 수 있는 업체를 소개드립니다.',
        }
        for cat, ids in picks.items():
            with self.subTest(cat=cat):
                body = self.build_body('t20', {'vendorCat': cat, 'vendorSel': {cat: ids}})
                self.assertIn(intro[cat], body)
                label = '업체명' if cat in ('인테리어', '입주청소', '이사') else '이름'
                self.assertIn('- %s : ' % label, body)
                self.assertNotIn('- 이름 : (상담사/업체 이름)', body)
                self.assertIn('마래푸중앙부동산 소개로 연락하셨다고 말씀해 주시면 됩니다. 감사합니다.', body)
                self.assertIn(S, body)
        body = self.build_body('t20', {'vendorCat': '대출', 'vendorSel': {'대출': ['d01', 'd33']}})
        self.assertIn('- 이름 : 국민 대출 김동준\n- 연락처 : 010-3704-2417', body)
        self.assertIn('- 이름 : 삼성생명 대출 박재영\n- 연락처 : 010-3361-5793', body)
        body = self.build_body('t20', {'vendorCat': '이사', 'vendorSel': {'이사': ['m01', 'm02']}})
        self.assertIn('- 업체명 : 소원아빠 이사\n- 연락처 : 010-9248-4484', body)
        self.assertIn('- 업체명 : KGB주식회사 소장 민병권\n- 연락처 : 010-4155-3011', body)
        # 44명 전원이 분야별로 들어 있다
        counts = self.js("() => Object.fromEntries(Object.entries(SMSTemplates.DEFAULT_CONTACTS).map(([k, v]) => [k, v.length]))")
        self.assertEqual(counts, {'대출': 33, '세무사': 1, '법무사': 1, '인테리어': 2, '입주청소': 5, '이사': 2})
        phones = self.js("""() => Object.values(SMSTemplates.DEFAULT_CONTACTS).flat().map(c => c.phone)""")
        self.assertEqual(len(phones), 44)
        self.assertEqual(len(set(phones)), 44, '번호가 겹치지 않는다')
        self.assertTrue(all(re.match(r'^010-\d{4}-\d{4}$', p) for p in phones), phones)
        # 8번 주차 안내처럼 값이 없는 문자도 서명은 늘 붙는다
        for tid in ('t1', 't6'):
            self.assertTrue(self.build_body(tid, {}).endswith(S), tid)

    def test_v143_pay_schedule_percent_and_amount_two_way(self):
        # 11번 지급 일정 — % ↔ 금액 양방향, 잔금 자동, 약정금·가계약금 문구까지 본문에 반영
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '76000')
        self.pay_rate('gyeyak', 10)
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]'), '7,600')
        self.pay_fill('jung', 19000)
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="jung"][data-pay-idx="0"]'), '25')
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '49,400')
        body = self.text()
        self.assertIn('- 매매대금 : 760,000,000원 (7억 6천만 원)', body)
        self.assertIn('- 계약금 10% : 76,000,000원 (7,600만 원)', body)
        self.assertIn('- 중도금 25% : 190,000,000원 (1억 9천만 원)', body)
        self.assertIn('- 잔금 : 494,000,000원 (4억 9,400만 원)', body)
        # 금액을 고치면 % 가 따라온다
        self.pay_fill('gyeyak', 7600 * 2)
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="gyeyak"][data-pay-idx="0"]'), '20')
        # 약정금·가계약금을 넣으면 계약일 안내 문장의 숫자가 따라온다
        self.pay_fill('yakjeong', 1000)
        self.pay_fill('jeong', 3000)
        self.wait(200)
        body = self.text()
        self.assertIn('기지급한 약정금 10,000,000원은 계약일에 전액 반환받고, 계약금 152,000,000원은 약정금을 차감하지 않고 전액 입금합니다.', body)
        self.assertIn('기지급한 가계약금 30,000,000원은 계약금에 포함하며, 계약일에는 계약금 총액 152,000,000원 중 차액 122,000,000원을 지급합니다.', body)
        self.assertIn('가계약금 30,000,000원 (3천만 원)을 지급하며', body)

    def test_v143_pay_schedule_parts_two_and_dates(self):
        # 중도금 1·2차 — 소계·잔금·본문 줄까지
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '76000')
        self.pay_fill('gyeyak', 7600)
        self.pay_fill('jung', 19000)
        self.pay_add('jung')
        self.pay_fill('jung', 9500, idx=1)
        self.wait(200)
        body = self.text()
        self.assertIn('- 중도금 1차 25% : 190,000,000원', body)
        self.assertIn('- 중도금 2차 12.5% : 95,000,000원', body)
        # 잔금 = 76,000 − 7,600 − (19,000 + 9,500) = 39,900
        self.assertIn('- 잔금 : 399,000,000원', body)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '39,900')
        # 날짜를 넣으면 '/ 날짜' 로 붙는다
        self.page.evaluate("""() => {
            const t = SMSApp; return 0;
        }""")
        self.page.click('#fields [data-date="pay:gyeyak:0"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-day="5"]')
        self.wait(150)
        self.page.click('#calpop [data-cal-close]')
        self.wait(150)
        body = self.text()
        self.assertRegex(body, r'- 계약금 10% : 76,000,000원 \(7,600만 원\) / 2026년 \d+월 5일 \S+요일')

    def test_v143_t10_schedule_amounts_and_total(self):
        # 12번 계약 일정 — 중도금·잔금·합계가 본문에 그대로
        self.pick_with('t10', {'trade': '매매', 'kind': '잔금'})
        self.page.fill('#fields [data-prop="prop"][data-key="dong"]', '404')
        self.page.fill('#fields [data-prop="prop"][data-key="ho"]', '1903')
        self.page.fill('#fields [data-prop="prop"][data-money="amount"]', '247000')
        self.wait(150)
        self.pay_fill('gyeyak', 24700)
        self.pay_fill('jung', 61750)
        self.wait(200)
        body = self.text()
        self.assertIn('마포래미안푸르지오 404동 1903호 잔금 일정 및 입금 내역을 안내드립니다.', body)
        self.assertIn('- 계약금 : 247,000,000원', body)
        self.assertIn('- 중도금 : 617,500,000원', body)
        self.assertIn('- 잔금 : 1,605,500,000원', body)
        self.assertIn('- 합계 : 2,470,000,000원', body)
        self.assertEqual(self.page.input_value('#fields [data-pay-amt="jan"][data-pay-idx="0"]'), '160,550')

    def test_v143_fee_calculator_matches_core(self):
        # 16번 중개보수 — 코어 계산값(요율·공급가액·부가세·합계)이 본문에 그대로
        cases = [
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '230000', 'calcVat': '4'},
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '230000', 'calcVat': 'none'},
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '230000', 'calcVat': '10'},
            {'calcKind': 'house', 'calcTrade': '전세', 'calcAmount': '76000', 'calcVat': '4'},
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '3000', 'calcVat': 'none'},
            {'calcKind': 'house', 'calcTrade': '전세', 'calcAmount': '9000', 'calcVat': '4'},
            {'calcKind': 'officetel', 'calcTrade': '매매', 'calcAmount': '30000', 'calcVat': '4', 'calcOffice': 'resident'},
            {'calcKind': 'officetel', 'calcTrade': '전세', 'calcAmount': '30000', 'calcVat': '4', 'calcOffice': 'business'},
            {'calcKind': 'commercial', 'calcTrade': '매매', 'calcAmount': '50000', 'calcVat': '10'},
            {'calcKind': 'commercial', 'calcTrade': '월세', 'calcDeposit': '10000', 'calcRent': '100', 'calcVat': '4'},
            {'calcKind': 'house', 'calcTrade': '월세', 'calcDeposit': '10000', 'calcRent': '50', 'calcVat': 'none'},
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '230000', 'calcVat': '4', 'calcRate': '0.5'},
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '230000', 'calcVat': '4', 'calcRate': '0.9'},
            {'calcKind': 'house', 'calcTrade': '매매', 'calcAmount': '20000', 'calcVat': '4', 'calcTotalWon': '900000'},
        ]
        ctx = {'feeAccount': '우리은행 1002-762-106047 황호선'}
        for patch in cases:
            with self.subTest(patch=str(patch)):
                got = self.js("""a => {
                    const C = window.SMSCore, T = window.SMSTemplates;
                    const patch = a[0], ctx = a[1];
                    const r = C.feeCalc({ kind: patch.calcKind, trade: patch.calcTrade,
                        officetelUse: patch.calcOffice || 'resident',
                        amountMan: C.parseMan(patch.calcAmount), depositMan: C.parseMan(patch.calcDeposit),
                        rentMan: C.parseMan(patch.calcRent), ratePct: patch.calcRate,
                        vat: patch.calcVat || '4' });
                    const t = T.TEMPLATES.find(x => x.id === 't14');
                    const d = Object.assign(T.defaultData(t), patch);
                    const body = t.build(d, Object.assign({ office: '마래푸중앙부동산',
                        phones: '010-4585-7365 / 02-312-7365', amountMode: 'won_eokman',
                        contacts: T.defaultContacts() }, ctx));
                    const money = C.feeBreakdown(r, C.wonOrNull(patch.calcTotalWon));
                    return { rate: C.rateLabel(r.ratePct), supply: C.formatWonPlain(money.supply),
                             vat: C.formatWonPlain(money.vat), total: C.formatWonPlain(money.total),
                             vatMode: money.vatMode, body: body,
                             conv: r.converted ? C.formatWonPlain(r.amountWon) : '',
                             capped: !!r.capped && !money.custom, capWon: r.capWon };
                }""", [patch, ctx])
                body = got['body']
                self.assertIn('- 적용 요율 : %s%%' % got['rate'], body)
                self.assertIn('- 중개보수 (공급가액) : %s' % got['supply'], body)
                self.assertIn('- 합계 : %s' % got['total'], body)
                if got['vatMode'] == 'none':
                    self.assertIn('- 부가가치세 : 별도', body)
                else:
                    pct = '간이과세 4%' if got['vatMode'] == '4' else '일반과세 10%'
                    self.assertIn('- 부가가치세 : %s (%s)' % (got['vat'], pct), body)
                if got['conv']:
                    self.assertIn('(환산 %s)' % got['conv'], body)
                if got['capped']:
                    self.assertIn('- 한도액', body)
                self.assertIn('- 입금계좌 : 우리은행 1002-762-106047 황호선', body)
                self.assertIn('믿고 맡겨주셔서 진심으로 감사드립니다.', body)
                self.assertNotIn('[', body)
                self.assertNotIn(']', body)

    def test_v143_fee_calculator_ui_text(self):
        # 화면에서 고른 값이 그대로 본문에 (주택 매매 23억 4% → 0.7% · 16,100,000 · 644,000 · 16,744,000)
        self.pick('t14')
        self.page.fill('#fields [data-field="calcAmount"]', '230000')
        self.wait(200)
        body = self.text()
        self.assertIn('- 거래 유형 : 주택 · 매매', body)
        self.assertIn('- 거래금액 : 2,300,000,000원', body)
        self.assertIn('- 적용 요율 : 0.7%', body)
        self.assertIn('- 중개보수 (공급가액) : 16,100,000원', body)
        self.assertIn('- 부가가치세 : 644,000원 (간이과세 4%)', body)
        self.assertIn('- 합계 : 16,744,000원', body)
        # 합계 직접 수정 — 나눠서 표시하고 요율은 법정 그대로
        self.page.fill('#fields [data-field="calcTotalWon"]', '900000')
        self.wait(200)
        body = self.text()
        self.assertIn('- 적용 요율 : 0.7%', body)
        self.assertIn('- 중개보수 (공급가액) : 865,385원', body)
        self.assertIn('- 부가가치세 : 34,615원 (간이과세 4%)', body)
        self.assertIn('- 합계 : 900,000원', body)

    # ---------------------------------------------------------------- v1.4.4 (빈 기본값 · 근저당 다건)
    def test_v144_all_inputs_empty_by_default(self):
        # 처음 연 모든 문구는 직접 입력칸·날짜·금액이 빈 상태로 시작한다
        ids = self.js("() => window.SMSTemplates.TEMPLATES.map(t => t.id).filter(i => i !== 't20')")
        for tid in ids:
            with self.subTest(template=tid):
                self.page.evaluate("t => window.SMSApp.openTemplate(t, {})", tid)
                self.wait(150)
                vals = self.js("""() => [...document.querySelectorAll('#fields input, #fields textarea')]
                    .filter(i => i.value && !i.readOnly)
                    .map(i => ({key: i.dataset.key || '', f: i.dataset.field || i.dataset.payAmt ||
                        i.dataset.mtgHolder || i.dataset.mtgAmount || i.dataset.prop || '', v: i.value}))
                    .filter(x => !(x.key === 'complex'))""")
                self.assertEqual(vals, [], f'{tid} 에 미리 채워진 칸이 있다: {vals}')

    def test_v144_paytable_one_row_empty(self):
        # 지급 일정 — 항목마다 1줄씩, %·일정·금액 모두 빈 상태
        for tid in ('t8', 't10'):
            with self.subTest(template=tid):
                self.page.evaluate("t => window.SMSApp.openTemplate(t, {})", tid)
                self.wait(150)
                rows = self.pay_rows()
                self.assertEqual([r['name'] for r in rows], ['약정금', '가계약금', '계약금', '중도금', '잔금'])
                self.assertEqual([r['idx'] for r in rows], [0, 0, 0, 0, 0], '2차 이상이 미리 열려 있다')
                self.assertEqual([r['amt'] for r in rows], ['', '', '', '', ''], '금액이 미리 채워져 있다')
                self.assertEqual([r['rate'] for r in rows], [None, None, '', '', None], '비율이 미리 채워져 있다')
                dates = self.js("""() => [...document.querySelectorAll('#fields .pay-row .date-text')]
                    .map(e => e.textContent.trim())""")
                self.assertEqual(dates, ['일정', '일정', '일정', '일정', '일정'], '일정이 미리 채워져 있다')
                # (+) 로 한 줄 늘리고 (−) 로 다시 1줄로 — 늘어난 줄도 빈 값
                self.pay_add('gyeyak')
                self.assertEqual(len([r for r in self.pay_rows() if r['item'] == 'gyeyak']), 2)
                self.assertEqual(self.page.input_value('#fields [data-pay-amt="gyeyak"][data-pay-idx="1"]'), '')
                self.pay_del('gyeyak', 1)
                self.assertEqual(len([r for r in self.pay_rows() if r['item'] == 'gyeyak']), 1)
                # 비우기(초기화)도 다시 1줄·빈 값
                self.page.fill('#fields [data-pay-amt="gyeyak"][data-pay-idx="0"]', '10000')
                self.wait(150)
                self.page.click('#btn-reset')
                self.wait(200)
                rows = self.pay_rows()
                self.assertEqual([r['idx'] for r in rows], [0, 0, 0, 0, 0])
                self.assertEqual([r['amt'] for r in rows], ['', '', '', '', ''])

    def test_v144_mortgage_count_follows_rows(self):
        # 근저당 1건 → 2건 → 3건 — 본문의 건수와 목록이 입력한 만큼 따라온다
        self.page.evaluate("() => window.SMSApp.openTemplate('t8', {})")
        self.wait(150)
        self.page.click('#fields [data-toggle="mortgage"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 1)
        # 1건
        self.page.fill('#fields [data-mtg-holder="0"]', '주식회사 카카오뱅크')
        self.page.fill('#fields [data-mtg-amount="0"]', '12000')
        self.wait(200)
        body = self.text()
        self.assertIn('근저당권 1건이 설정된 상태이며', body)
        self.assertIn('주식회사 카카오뱅크를 채권자로 하는 채권최고액 120,000,000원 (1억 2천만 원)', body)
        # 2건
        self.page.click('#fields [data-mtg-add]')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 2)
        self.assertEqual(self.page.input_value('#fields [data-mtg-holder="1"]'), '', '새 줄은 빈 값')
        self.page.fill('#fields [data-mtg-holder="1"]', '국민은행')
        self.page.fill('#fields [data-mtg-amount="1"]', '5000')
        self.wait(200)
        body = self.text()
        self.assertIn('근저당권 2건이 설정된 상태이며', body)
        self.assertNotIn('근저당권 1건', body)
        self.assertIn('· 주식회사 카카오뱅크 / 채권최고액 120,000,000원 (1억 2천만 원)', body)
        self.assertIn('· 국민은행 / 채권최고액 50,000,000원 (5천만 원)', body)
        self.assertIn('근저당권을 모두 말소합니다', body)
        # 3건
        self.page.click('#fields [data-mtg-add]')
        self.wait(200)
        self.page.fill('#fields [data-mtg-holder="2"]', '신한은행')
        self.page.fill('#fields [data-mtg-amount="2"]', '3000')
        self.wait(200)
        body = self.text()
        self.assertIn('근저당권 3건이 설정된 상태이며', body)
        self.assertEqual(body.count('· '), 3, '3건 목록이 모두 나간다')
        self.assertIn('· 신한은행 / 채권최고액 30,000,000원 (3천만 원)', body)
        # (−) 로 한 건 빼면 건수도 줄어든다
        self.page.click('#fields [data-mtg-del="2"]')
        self.wait(200)
        body = self.text()
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 2)
        self.assertIn('근저당권 2건이 설정된 상태이며', body)
        self.assertNotIn('신한은행', body)
        # 둘 다 빼면 1줄만 남고 값이 비워진다
        self.page.click('#fields [data-mtg-del="1"]')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 1)
        self.page.click('#fields [data-mtg-del="0"]')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .mtg-row')), 1)
        self.assertEqual(self.page.input_value('#fields [data-mtg-holder="0"]'), '')
        self.assertEqual(self.page.input_value('#fields [data-mtg-amount="0"]'), '')
        self.assertIn('근저당권 1건이 설정된 상태이며', self.text())

    def test_v144_mortgage_legacy_saved_value_reads_as_first_row(self):
        # 예전 한 건짜리 저장값(채권자 · 채권최고액)은 첫 줄로 읽힌다
        self.pick_with('t8', {'mortgage': True, 'mortgageHolder': '카카오뱅크', 'mortgageAmount': '12000'})
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-mtg-holder="0"]'), '카카오뱅크')
        self.assertEqual(self.page.input_value('#fields [data-mtg-amount="0"]'), '12,000')
        self.assertIn('근저당권 1건이 설정된 상태이며', self.text())
    def test_v144_legacy_default_values_cleared_only_once(self):
        # 예전 기본 예시값·빈 차수는 한 번만 정리하고, 그 뒤에 직접 친 값은 그대로 둔다
        seed = {
            'profile': {'office': '마래푸중앙부동산', 'phones': '010-4585-7365 / 02-312-7365',
                        'feeAccount': '', 'amountMode': 'won_eokman'},
            'stars': ['t3', 't4', 't5', 't14'],
            'data': {
                't8': {'trade': '매매', 'kind': '가계약', 'address': '서울시 마포구 아현동 777 외 3필지'},
                't15': {'role': '임대인', 'months': 2},
                't10': {'trade': '매매', 'kind': '계약',
                        'payExtra': {'gyeyak': [{'amount': '', 'date': None}],
                                     'jung': [{'amount': '', 'date': None}]}},
            },
            'texts': {}, 'current': 't8', 'stage': 'all', 'custom': [], 'overrides': {},
            'sync': {'token': '', 'gistId': '', 'updatedAt': 0, 'lastSync': 0},
        }
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        ctx.add_init_script("try { if (!localStorage.getItem('smshelper.v1')) localStorage.setItem('smshelper.v1', %s); } catch (e) {}"
                            % json.dumps(json.dumps(seed, ensure_ascii=False)))
        page = ctx.new_page()
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_timeout(300)
        # ① 한 번 정리 — 주소·남은 기간·빈 차수가 사라진다
        page.evaluate("() => SMSApp.openTemplate('t8', {})")
        page.wait_for_timeout(250)
        self.assertEqual(page.input_value('#fields [data-field="address"]'), '')
        page.evaluate("() => SMSApp.openTemplate('t15', {})")
        page.wait_for_timeout(250)
        self.assertEqual(page.input_value('#fields [data-field="months"]'), '')
        page.evaluate("() => SMSApp.openTemplate('t10', {})")
        page.wait_for_timeout(250)
        gy = page.evaluate("() => document.querySelectorAll('#fields .pay-row[data-pay-item=\"gyeyak\"]').length")
        jung = page.evaluate("() => document.querySelectorAll('#fields .pay-row[data-pay-item=\"jung\"]').length")
        self.assertEqual((gy, jung), (1, 1), '빈 2차 줄은 지운다')
        # ② 같은 주소를 다시 처도 새로 고친 뒤에 지워지지 않는다 (정리는 한 번만)
        page.evaluate("() => SMSApp.openTemplate('t8', {})")
        page.wait_for_timeout(200)
        page.fill('#fields [data-field="address"]', '서울시 마포구 아현동 777 외 3필지')
        page.wait_for_timeout(250)
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(300)
        page.evaluate("() => SMSApp.openTemplate('t8', {})")
        page.wait_for_timeout(250)
        self.assertEqual(page.input_value('#fields [data-field="address"]'), '서울시 마포구 아현동 777 외 3필지')
        ctx.close()

    # ============================================================== v1.4.6 — 매물 줄 표기
    def test_v146_no_property_label_anywhere(self):
        # `- 매물 : ` 접두어를 전 템플릿에서 없앴다 (🔑 매물 : 같은 이모지 라벨은 그대로)
        prop = {'complex': '마포래미안푸르지오', 'dong': '404', 'ho': '1903',
                'trade': '매매', 'amount': '247000', 'deposit': '', 'rent': '', 'price': ''}
        when = {'date': '2026-11-28', 'hour': 11, 'min': 0}
        bad = self.js("""a => {
            const props = a[0], when = a[1];
            const T = window.SMSTemplates;
            const ctx = { office: '마래푸중앙부동산', phones: '010-4585-7365 / 02-312-7365',
                feeAccount: '우리은행 1002-762-106047 황호선', amountMode: 'won_eokman',
                contacts: T.defaultContacts() };
            const out = [];
            const cases = [];
            T.TEMPLATES.forEach(t => {
                ['default', 'filled'].forEach(kind => cases.push([t, kind, {}]));
            });
            // 갈래가 있는 문자는 한 번씩 더 돌린다
            [['t5', { status: 'pending' }], ['t5', { status: 'confirmed', detail: true }],
             ['t3', { view: 'simple' }], ['t3', { view: 'detail', times: '11월 28일 (토) 10:00' }],
             ['t19', { emphasis: '급매' }], ['t7', {}]].forEach(([tid, patch]) => {
                const t = T.TEMPLATES.find(x => x.id === tid);
                cases.push([t, 'branch', patch]);
            });
            cases.forEach(([t, kind, patch]) => {
                const d = Object.assign(T.defaultData(t), kind === 'default' ? {} : {
                    prop: props, items: [props, props], when: when, times: '11월 28일 (토) 10:00'
                }, patch);
                const body = t.build(d, ctx);
                if (body.indexOf('- 매물 : ') !== -1) out.push(t.id + '/' + kind + '/' + JSON.stringify(patch));
            });
            return out;
        }""", [prop, when])
        self.assertEqual(bad, [], '`- 매물 : ` 접두어가 남아 있다')
        # 특가 매물 홍보의 🔑 매물 : 은 문맥상 필요한 라벨이라 남긴다
        self.assertIn('🔑 매물 : 마포래미안푸르지오 404동 1903호', self.build_body('t19', {'items': [prop]}))

    def test_v146_reservation_confirmed_multiple_props_one_per_line(self):
        # 예약 확정 — 매물을 여러 건 넣으면 조율 중과 똑같이 한 줄에 하나씩 `- ` 로 나온다
        prop1 = {'complex': '마포그랑자이', 'dong': '111', 'ho': '19', 'trade': '매매',
                 'amount': '230000', 'deposit': '', 'rent': '', 'price': ''}
        prop2 = {'complex': '마포그랑자이', 'dong': '110', 'ho': '1302', 'trade': '매매',
                 'amount': '230000', 'deposit': '', 'rent': '', 'price': ''}
        when = {'date': '2026-11-28', 'hour': 11, 'min': 0}
        confirmed = self.build_body('t5', {'status': 'confirmed', 'detail': True, 'parking': False,
                                           'when': when, 'items': [prop1, prop2]})
        self.assertIn('- 방문 일시 : 2026년 11월 28일 토요일 11:00\n'
                      '- 마포그랑자이 111동 19호 / 매매 23억\n'
                      '- 마포그랑자이 110동 1302호 / 매매 23억', confirmed)
        self.assertNotIn(' · ', confirmed, '매물을 ` · `로 한 줄에 붙이지 않는다')
        self.assertNotIn('- 매물 :', confirmed)
        # 조율 중도 같은 모양 — 매물 한 건당 한 줄
        pending = self.build_body('t5', {'status': 'pending', 'items': [prop1, prop2]})
        self.assertIn('- 마포그랑자이 111동 19호 / 매매 23억\n- 마포그랑자이 110동 1302호 / 매매 23억', pending)
        self.assertNotIn('- 매물 :', pending)
        # 화면에서도 같다 — 미리보기에도 `- 매물 :` 없이 한 줄에 한 건
        self.pick_with('t5', {'status': 'confirmed', 'detail': True, 'items': [prop1, prop2]})
        body = self.text()
        self.assertIn('- 마포그랑자이 111동 19호 / 매매 23억\n- 마포그랑자이 110동 1302호 / 매매 23억', body)
        self.assertNotIn('- 매물 :', body)
        self.assertNotIn(' · ', body)

if __name__ == '__main__':
    unittest.main(verbosity=2)
