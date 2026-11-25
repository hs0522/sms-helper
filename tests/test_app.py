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

    def text(self):
        return self.page.input_value('#preview')

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
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:11, min:30})"""),
            '2026년 11월 28일 토요일 오전 11시 30분')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:null, min:0})"""),
            '2026년 11월 28일 토요일')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:0, min:0})"""),
            '2026년 11월 28일 토요일 오전 12시')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:12, min:0})"""),
            '2026년 11월 28일 토요일 오후 12시')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTime({date:'2026-11-28', hour:14, min:5})"""),
            '2026년 11월 28일 토요일 오후 2시 5분')
        self.assertEqual(
            self.js("""() => SMSCore.formatDateTimeRange({date:'2026-11-28', hour:10, min:0}, {hour:12, min:0})"""),
            '2026년 11월 28일 토요일 오전 10시 ~ 오후 12시')
        self.assertEqual(
            self.js("""() => SMSCore.compactDateTime({date:'2026-11-28', hour:14, min:30})"""),
            '2026.11.28 (토) 오후 2:30')
        self.assertEqual(self.js('() => SMSCore.weekdayOf(2026, 11, 24)'), '화')

    def test_short_datetime_for_simple_ask(self):
        # 문자에 들어가는 짧은 표기: "내일 9/23 (화) 오전 9시30분"
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-09-23', hour:9, min:30},
                       new Date(2026, 8, 22))"""),
            '내일 9/23 (수) 오전 9시30분')
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-11-25', hour:14, min:0},
                       new Date(2026, 10, 25))"""),
            '오늘 11/25 (수) 오후 2시')
        self.assertEqual(
            self.js("""() => SMSCore.formatShortDateTime({date:'2026-12-05', hour:10, min:0},
                       new Date(2026, 10, 25))"""),
            '12/5 (토) 오전 10시')
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
    def test_all_20_templates_render(self):
        ids = self.js('() => SMSTemplates.TEMPLATES.map(t => t.id)')
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20, '템플릿 id가 겹치면 안 된다')
        nos = self.js('() => SMSTemplates.TEMPLATES.map(t => t.no)')
        self.assertEqual(sorted(nos), list(range(1, 21)), '번호가 1~20으로 이어져야 한다')
        for tid in ids:
            with self.subTest(tid=tid):
                self.pick(tid)
                body = self.text()
                self.assertGreater(len(body), 40, f'{tid} 본문이 너무 짧다')
                self.assertNotIn('\n\n\n', body, f'{tid} 빈 줄이 겹친다')
                # 20종 모두 맨 아래에 한 줄을 띄우고 상호·번호 서명이 늘 들어간다
                self.assertIn('\n\n마래푸중앙부동산', body, f'{tid} 서명 앞에 한 줄이 비지 않았다')
                self.assertTrue(body.endswith('010-4585-7365 / 02-312-7365'), f'{tid} 맨 아래가 연락처가 아니다')
                self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0,
                                 f'{tid} 서명 토글이 남아 있다')

    def test_no_signature_toggle_anywhere(self):
        # 서명 토글 필드는 20종 어디에도 없다
        found = self.js("""() => {
          const out = [];
          SMSTemplates.TEMPLATES.forEach(t => (t.fields || []).forEach(f => {
            if (f.id === 'signature' || f.t === 'toggle' && /\uc11c\uba85/.test(f.label || '')) out.push(t.id + ':' + f.id);
          }));
          return out;
        }""")
        self.assertEqual(found, [])
        # 화면에서도 스위치가 사라졌다 (예전에 토글이 있던 7종)
        for tid in ('t16', 't3', 't4', 't17', 't18', 't19', 't20'):
            with self.subTest(tid=tid):
                self.pick(tid)
                self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0)
                self.assertNotIn('상호·번호 서명', self.page.inner_text('#fields'))

    def test_every_template_and_option_ends_with_footer(self):
        # 20종 × 화면에서 고를 수 있는 모든 조합의 맨 아래에 서명이 빠짐없이 붙는다
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
            t3: [{ ver: 'simple' }, { ver: 'detail' }],
            t5: [{ status: 'confirmed' }, { status: 'pending' }],
            t10: [{ trade: '매매' }, { trade: '임대차' }],
            t11: [{ trade: '매매' }, { trade: '임대차' }],
            t12: [{ owner: '공동' }, { owner: '단독' }],
            t13: [{ trade: '매매', kind: '중도금' }, { trade: '매매', kind: '잔금' },
                  { trade: '전세', deposit: '10000', gyeyak: '1000' },
                  { trade: '월세', deposit: '10000', rent: '50', gyeyak: '1000' }],
            t15: [{ role: '임대인' }, { role: '임차인' }],
            t16: [{ trade: '매매' }, { trade: '전세' }, { trade: '월세' }],
            t18: [{ trade: '전세' }, { trade: '매매' }, { trade: '월세', deposit: '10000', rent: '250' }],
            t19: [{ trade: '매매' }, { trade: '전세' }, { trade: '월세' }]
          };
          SMSTemplates.TEMPLATES.forEach(t => {
            (combos[t.id] || [{}]).forEach((patch, i) => check(t, patch, 'combo' + i));
          });
          // 감사 인사는 대상 3 × 문구 7 × 안부 5 전부
          const t17 = SMSTemplates.TEMPLATES.find(t => t.id === 't17');
          ['owner', 'coagent', 'guest'].forEach(target => {
            SMSTemplates.VARIANTS[target].forEach((_, idx) => {
              SMSTemplates.GREETINGS.forEach(g => {
                check(t17, { target: target, vpick: { owner: idx, coagent: idx, guest: idx }, greet: g.v },
                      target + '/' + idx + '/' + g.v);
              });
            });
          });
          return out;
        }""")
        self.assertEqual(bad, [], '서명이 빠지거나 맨 아래가 아닌 조합: %s' % bad)

    def test_no_brackets_in_any_template(self):
        # 20종 어느 조합에서도 문자 본문에 대괄호 [ ] 가 나오지 않는다
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
            t2: [{}, { trade: '전세', price: '11억 5천만' }],
            t3: [{ ver: 'simple' }, { ver: 'detail' }, { ver: 'detail', times: '2026년 12월 5일 토요일 오전 10시' }],
            t5: [{ status: 'confirmed' }, { status: 'pending', detail: true }],
            t8: [{}, { price: '247000', jeongAmount: '3000', gyeyakAmount: '24700', jungAmount: '61750',
                   permit: true, mortgage: true }, { mortgage: true, mortgageAmount: '12000', mortgageHolder: '카카오뱅크' }],
            t9: [{}, { when: { date: '2026-11-28', hour: 10, min: 0 } }],
            t10: [{ trade: '매매' }, { trade: '임대차', priority: true }, { trade: '매매', jeongyakReturn: true }],
            t11: [{ trade: '매매' }, { trade: '임대차' }],
            t12: [{ owner: '공동' }, { owner: '단독' }],
            t13: [{ trade: '매매', kind: '중도금' }, { trade: '매매', kind: '잔금', docs: true },
                  { trade: '전세', kind: '잔금', registry: true, deposit: '10000' },
                  { trade: '월세', deposit: '10000', rent: '50', registry: true },
                  { trade: '매매', kind: '잔금', price: '247000', gyeyak: '24700', jung: '61750' }],
            t14: [{}, { calcAmount: '230000' }, { calcKind: 'commercial', calcTrade: '월세', calcDeposit: '10000', calcRent: '100' }],
            t15: [{ role: '임대인' }, { role: '임차인' }],
            t16: [{ trade: '매매' }, { trade: '전세' }, { trade: '월세' }],
            t18: [{ trade: '전세' }, { trade: '매매', amount: '90000', area: '34' },
                  { trade: '월세', deposit: '10000', rent: '250' }],
            t19: [{}, { items: [{ complex: '마포래미안푸르지오', dong: '201', ho: '1203', trade: '전세', amount: '210000' }] }],
            t20: [{ vendorCat: '대출' }, { vendorCat: '법무사' }]
          };
          SMSTemplates.TEMPLATES.forEach(t => {
            check(t, {}, 'blank');
            (combos[t.id] || [{}]).forEach((patch, i) => check(t, patch, 'combo' + i));
          });
          // 감사 인사는 대상 3 × 문구 7 × 안부 5 전부
          const t17 = SMSTemplates.TEMPLATES.find(t => t.id === 't17');
          ['owner', 'coagent', 'guest'].forEach(target => {
            SMSTemplates.VARIANTS[target].forEach((_, idx) => {
              SMSTemplates.GREETINGS.forEach(g => {
                check(t17, { target: target, vpick: { owner: idx, coagent: idx, guest: idx }, greet: g.v },
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
        self.assertIn('■ 계약 구성', body)
        self.assertIn('■ 특약', body)
        self.assertIn('(계좌번호)', body)
        self.pick('t9')
        body = self.text()
        self.assertIn('■ 매도인 준비사항', body)
        self.assertIn('■ 매수인 준비사항', body)
        self.assertIn('(약정 일시)', body)
        self.pick('t12')
        body = self.text()
        self.assertIn('■ 온라인 제출 방법', body)
        self.assertIn('■ 준비하실 증빙서류', body)
        self.pick('t13')
        body = self.text()
        self.assertIn('■ 금액 세부사항', body)
        self.assertIn('(계좌번호)', body)
        self.pick('t14')
        body = self.text()
        self.assertIn('(요율)%', body)
        self.assertIn('(중개보수)', body)
        self.assertIn('(입금 계좌)', body)

    def test_first_greeting_keeps_owner_signature(self):
        self.pick('t1')
        body = self.text()
        self.assertTrue(body.endswith('마래푸중앙부동산 대표 황호선 드림\n010-4585-7365 / 02-312-7365'), body)

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
        self.assertGreaterEqual(len(rows), 20)
        self.page.click('[data-stage="3"]')
        self.wait(80)
        titles = [r.inner_text() for r in self.page.query_selector_all('#tpl-list .row')]
        self.assertTrue(any('매매조건' in t for t in titles))
        self.assertTrue(any('자금조달' in t for t in titles))
        self.assertFalse(any('주차 안내' in t for t in titles))
        self.assertEqual(len(titles), 5, '약정·계약 진행은 5종')
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
        self.page.click('#fields [data-seg="trade"][data-value="임대차"]')
        self.wait(80)
        body = self.text()
        self.assertIn('임대차계약 일정', body)
        self.assertIn('확정일자 부여현황', body)
        self.assertNotIn('등기권리증', body)

        self.pick('t11')
        self.assertIn('매도인과 매수인에게', self.text())
        self.page.click('#fields [data-seg="trade"][data-value="임대차"]')
        self.wait(80)
        self.assertIn('임대인과 임차인에게', self.text())
        self.assertIn('임대차계약신고', self.text())

        self.pick('t12')
        self.assertIn('공동명의이므로 두 분 각각', self.text())
        self.page.click('#fields [data-seg="owner"][data-value="단독"]')
        self.wait(80)
        self.assertNotIn('공동명의이므로', self.text())
        self.assertIn('조달하실 금액과 자금 출처', self.text())

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
        self.assertIn('마포래미안푸르지오 208동 1103호 (매매 23억)', self.text())
        # 호 칸 배지 — 호 ↔ 층
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="ho"]'), '호')
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertIn('마포래미안푸르지오 208동 11층 (매매 23억)', self.text())
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="ho"]'), '층')
        # 동 칸 배지 — 동 ↔ 단지: 호수 칸·호 배지는 그대로 살아 있고 층·호수가 함께 나간다
        self.page.click('#fields [data-prop-unit="dong"]')
        self.wait(80)
        body = self.text()
        self.assertIn('마포래미안푸르지오 2단지 11층 (매매 23억)', body)
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="dong"]'), '단지')
        ho_inp = '#fields [data-prop="items"][data-idx="0"][data-key="ho"]'
        self.assertFalse(self.page.eval_on_selector(ho_inp, 'e => e.disabled'), '단지일 때도 호수 칸은 살아 있다')
        self.assertFalse(self.page.eval_on_selector('#fields [data-prop-unit="ho"]', 'e => e.disabled'))
        # 단지 상태에서 호 ↔ 층 배지도 그대로 돈다
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertEqual(self.page.inner_text('#fields [data-prop-unit="ho"]'), '호')
        self.assertIn('마포래미안푸르지오 2단지 1103호 (매매 23억)', self.text())
        # 단지 상태에서 호수 칸을 직접 고칠 수 있고, 비우면 단지까지만 나간다
        self.page.fill(ho_inp, '1203')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 2단지 1203호 (매매 23억)', self.text())
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(80)
        self.assertIn('마포래미안푸르지오 2단지 12층 (매매 23억)', self.text())
        self.page.fill(ho_inp, '')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 2단지 (매매 23억)', self.text())
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
        for tid in ('t7', 't4', 't2', 't8'):
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
        self.assertIn('마포래미안푸르지오 208동 208호 (매매 23억)', self.text())

        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="전세"]')
        self.wait(120)
        self.assertIn('(전세 23억)', self.text())
        self.page.fill(amount, '115000')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 208동 208호 (전세 11억 5천만)', self.text())

        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="월세"]')
        self.wait(120)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-money="amount"]')), 0)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '300')
        self.wait(150)
        body = self.text()
        self.assertIn('마포래미안푸르지오 208동 208호 (보증금 1억 / 월세 300만 원)', body)

    def test_legacy_price_migrated_on_load(self):
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't7', 'stage': 'all',
            'data': {'t7': {'mode': 'ho', 'items': [
                {'complex': '마포래미안푸르지오', 'dong': '208', 'ho': '208', 'price': '매매 23억'}]}}
        })
        self.assertIn('마포래미안푸르지오 208동 208호 (매매 23억)', page.input_value('#preview'))
        self.assertEqual(page.input_value('#fields [data-money="amount"]'), '230,000')
        ctx.close()

    def test_t4_legacy_trade_and_price_migrated(self):
        ctx, page = self.page_with_state({
            'stars': [], 'texts': {}, 'current': 't4', 'stage': 'all',
            'data': {'t4': {'mode': 'ho', 'signature': True, 'trade': '전세', 'price': '11억 5천만',
                            'prop': {'complex': '마포래미안푸르지오', 'dong': '304', 'ho': '1103'}}}
        })
        body = page.input_value('#preview')
        self.assertIn('전세 문의 손님이', body)
        self.assertIn('* 마포래미안푸르지오 304동 1103호 (전세 11억 5천만)', body)
        self.assertEqual(page.input_value('#fields [data-money="amount"]'), '115,000')
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
        self.assertIn('(매매 23억)', body)
        self.assertIn('(전세 9억)', body)
        self.page.click('#fields [data-remove-item="items"][data-idx="1"]')
        self.wait(80)
        self.assertNotIn('(전세 9억)', self.text())
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)

    def test_money_input_formats_and_hint(self):
        self.pick('t8')
        box = self.page.query_selector('#fields [data-field="price"]')
        box.click()
        box.type('237000')
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-field="price"]'), '237,000')
        self.assertIn('(23억 7천만)', self.page.inner_text('#fields'))
        self.assertIn('2,370,000,000원 (23억 7천만 원)', self.text())

    def test_auto_fill_contract_amounts(self):
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '237000')
        self.wait(100)
        self.page.click('#fields [data-action="autoFill"]')
        self.wait(120)
        body = self.text()
        self.assertIn('계약금 10% : 237,000,000원', body)
        self.assertIn('중도금 25% : 592,500,000원', body)
        self.assertIn('잔금 : 1,540,500,000원', body)

    def test_calendar_pick_date_and_time(self):
        self.pick('t9')
        self.page.click('#fields [data-date="when"]')
        self.wait(100)
        self.assertTrue(self.page.is_visible('#calpop'))
        self.page.click('#calpop [data-cal-nav="1"]')
        self.wait(80)
        self.page.click('#calpop [data-cal-day="5"]')
        self.wait(120)
        self.assertIn('2026년 12월 5일 토요일', self.text())
        self.page.select_option('#calpop [data-cal-hour]', '10')
        self.wait(100)
        self.page.select_option('#calpop [data-cal-min]', '30')
        self.wait(120)
        self.assertIn('2026년 12월 5일 토요일 오전 10시 30분', self.text())
        self.page.click('#calpop [data-cal-close]')
        self.assertFalse(self.page.is_visible('#calpop'))

    def test_clear_date_icon(self):
        self.pick('t9')
        self.assertIn('(약정 일시)', self.text())
        self.page.click('#fields [data-date="when"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-day="20"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-close]')
        self.assertIn('2026년 11월 20일 금요일', self.text())
        self.page.click('#fields .date-clear')
        self.wait(120)
        self.assertIn('(약정 일시)', self.text())
        self.assertFalse(self.page.is_visible('#calpop'))

    def test_no_today_tomorrow_chips(self):
        for tid in ('t5', 't9', 't10', 't13'):
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
        self.assertIn('* 우리은행 1002-762-106047 황호선', body)
        line = [l for l in body.split('\n') if '우리은행' in l][0]
        self.assertEqual(line, '* 우리은행 1002-762-106047 황호선')

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
        self.pick('t8')
        before = self.js("""() => {
          const i = document.querySelector('#fields [data-field=\"price\"]');
          return {top: i.getBoundingClientRect().top,
                  hintH: i.closest('.money-field').querySelector('.money-hint').getBoundingClientRect().height};
        }""")
        self.assertEqual(self.money_info('#fields [data-field="price"]')['hint'], '')
        self.page.fill('#fields [data-field="price"]', '237000')
        self.wait(150)
        after = self.js("""() => {
          const i = document.querySelector('#fields [data-field=\"price\"]');
          return {top: i.getBoundingClientRect().top,
                  hintH: i.closest('.money-field').querySelector('.money-hint').getBoundingClientRect().height};
        }""")
        self.assertAlmostEqual(before['hintH'], after['hintH'], delta=0.5, msg='환산 줄 높이가 바뀌면 안 된다')
        self.assertAlmostEqual(before['top'], after['top'], delta=0.5, msg='금액을 친다고 입력칸이 움직이면 안 된다')
        self.assertEqual(self.money_info('#fields [data-field="price"]')['hint'],
                         '2,370,000,000원 (23억 7천만)')

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
        labels = self.js("""() => [...document.querySelectorAll('.money-pair .money-label')].map(e => e.textContent)""")
        self.assertEqual(labels, ['보증금', '월세'])

    def test_monthly_two_columns_in_all_property_blocks(self):
        # 매물 블록을 쓰는 문자 모두 월세를 고르면 보증금·월차임 두 칸 + 각자 환산 줄
        blocks = [('t2', 'prop'), ('t4', 'prop'), ('t7', 'items'), ('t19', 'items')]
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
                labels = self.js("""() => [...document.querySelectorAll('.money-pair .money-label')].map(e => e.textContent)""")
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
        self.assertIn('* 마포래미안푸르지오 208동 1103호', body)
        self.assertIn('* 거래조건 : 매매 23억', body)
        # 월세는 보증금·월차임이 한 줄로 조합된다
        self.page.click('#fields [data-prop-trade="prop"][data-value="월세"]')
        self.wait(150)
        self.page.fill('#fields [data-money="deposit"]', '10000')
        self.page.fill('#fields [data-money="rent"]', '350')
        self.wait(180)
        self.assertIn('* 거래조건 : 보증금 1억 / 월세 350만 원', self.text())

    def test_movein_date_and_free_text(self):
        # 입주 — 협의(글자) · 고정(하루) · 기간(시작~종료) 세 갈래 (t2 · t18)
        for tid in ('t2', 't18'):
            with self.subTest(tid=tid):
                self.pick(tid)
                # 협의 — 글자로 적는다
                self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
                self.wait(150)
                self.page.fill('#fields [data-field="moveinText"]', '즉시')
                self.wait(150)
                self.assertRegex(self.text(), r'입주\s*:?\s*즉시')
                # 고정 — 달력으로 하루
                self.page.click('#fields [data-date-mode="movein"][data-value="고정"]')
                self.wait(150)
                self.page.click('#fields [data-date="movein"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-day="26"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                body = self.text()
                self.assertRegex(body, r'입주\s*:?\s*2026년 11월 26일 목요일')
                self.assertNotIn('즉시', body)
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
                self.assertRegex(body, r'입주\s*:?\s*2026\.12\.01 ~ 2026\.12\.31')
                self.assertNotIn('2026년 11월 26일', body)
                # 글자를 다시 적으면 기간 값은 지워진다
                self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
                self.wait(150)
                self.page.fill('#fields [data-field="moveinText"]', '협의')
                self.wait(150)
                body = self.text()
                self.assertRegex(body, r'입주\s*:?\s*협의')
                self.assertNotIn('2026.12.01', body)

    def test_all_money_fields_spider_style(self):
        # 만원 단위 금액칸이 있는 문자 전부 — 왼쪽 정렬 · 안쪽 '만원' · 아래 환산 줄
        money_placeholders = ('t2', 't5', 't6', 't7', 't8', 't10', 't11', 't12', 't13', 't14')
        seen = 0
        for tid in money_placeholders:
            with self.subTest(tid=tid):
                self.pick(tid)
                boxes = self.page.query_selector_all('#fields .money-box')
                if not boxes:
                    continue
                seen += len(boxes)
                report = self.js("""() => [...document.querySelectorAll('#fields .money-box')].map(box => {
                  const inp = box.querySelector('input'), unit = box.querySelector('.money-unit');
                  const field = box.closest('.money-field'), hint = field.querySelector('.money-hint');
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
                    self.assertEqual(r['left'], 0, f'{tid} 환산 줄 왼쪽 정렬')
                    self.assertGreater(r['minH'], 0, f'{tid} 빈 환산 줄도 자리를 잡아 둔다')
                    if r['inTable']:
                        # 지급 일정 표는 좁아서 원단위 / (억·만) 두 줄까지 내려간다
                        self.assertLessEqual(r['hintH'], r['minH'] * 2 + 2, f'{tid} 환산 줄은 두 줄까지')
                    else:
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

    def test_fee_calculator_ui(self):
        self.pick('t14')
        # 부가세 기본값은 간이 4%
        self.assertEqual(self.page.inner_text('#fields [data-seg="calcVat"].is-active'), '간이 4%')
        self.assertNotIn('금액 표시', self.page.inner_text('#fields'), '중개보수 계산기에는 금액 표시 줄이 없다')
        self.page.fill('#fields [data-field="calcAmount"]', '230000')
        self.wait(200)
        summary = self.page.inner_text('.calc-summary')
        self.assertIn('16,744,000원', self.page.inner_text('.calc-result'))
        self.assertIn('중개보수(공급가액) 16,100,000원', summary)
        self.assertIn('부가세 644,000원 (간이 4%)', summary)
        self.assertIn('상한 0.7%', summary)
        self.assertIn('* 중개보수 요율 : 0.7%', self.text())
        self.assertIn('* 중개보수(공급가액) : 16,100,000원', self.text())
        self.assertIn('* 부가세 : 644,000원 (간이과세 4%)', self.text())
        self.assertIn('* 합계 : 16,744,000원', self.text())
        self.assertNotIn('중개수수료', self.text())

        # 결과 박스와 적용 요율이 한 줄, 같은 라벨 줄·같은 칸 높이, 계산식은 그 아래 원단위 금액 표시처럼 작고 연한 글씨
        info = self.js("""() => {
          const box = document.querySelector('.calc-result').getBoundingClientRect();
          const rate = document.querySelector('.calc-cell.is-rate .inp.is-rate').getBoundingClientRect();
          const hint = document.querySelector('.calc-hint').getBoundingClientRect();
          const hs = getComputedStyle(document.querySelector('.calc-hint'));
          const ms = getComputedStyle(document.querySelector('.money-hint'));
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
        self.assertIn('17,710,000원', self.page.inner_text('.calc-result'))
        self.assertIn('* 부가세 : 1,610,000원 (일반과세 10%)', self.text())
        self.assertIn('* 합계 : 17,710,000원', self.text())
        self.assertIn('부가세 1,610,000원 (일반 10%)', self.page.inner_text('.calc-hint'))
        self.page.click('#fields [data-seg="calcVat"][data-value="none"]')
        self.wait(120)
        self.assertIn('16,100,000원', self.page.inner_text('.calc-result'))
        self.assertIn('부가세 별도', self.page.inner_text('.calc-hint'))
        self.page.fill('#fields [data-field="calcRate"]', '0.6')
        self.wait(200)
        self.assertIn('13,800,000원', self.text())
        self.assertIn('중개보수 요율 : 0.6%', self.text())
        self.page.fill('#fields [data-field="calcRate"]', '')
        self.page.click('#fields [data-seg="calcTrade"][data-value="월세"]')
        self.wait(150)
        self.assertIsNotNone(self.page.query_selector('#fields [data-field="calcDeposit"]'))
        self.page.fill('#fields [data-field="calcDeposit"]', '10000')
        self.page.fill('#fields [data-field="calcRent"]', '50')
        self.wait(250)
        self.assertIn('450,000원', self.page.inner_text('.calc-result'))
        self.assertIn('* 거래금액 : 보증금 100,000,000원 / 월차임 500,000원 (환산 150,000,000원)', self.text())

    def test_fee_calculator_presale_only_sale(self):
        self.pick('t14')
        self.page.click('#fields [data-seg="calcKind"][data-value="presale"]')
        self.wait(150)
        segs = self.page.query_selector_all('#fields [data-seg="calcTrade"]')
        self.assertEqual(len(segs), 1)

    def test_time_range_helper(self):
        self.pick('t3')
        self.page.click('#fields [data-seg="ver"][data-value="detail"]')
        self.wait(120)
        self.page.click('#fields [data-date="times__range"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-nav="1"]')
        self.wait(80)
        self.page.click('#calpop [data-cal-day="5"]')
        self.wait(120)
        self.page.select_option('#fields [data-range-time="start"]', '10:0')
        self.page.select_option('#fields [data-range-time="end"]', '12:0')
        self.page.click('#fields [data-range-add="times"]')
        self.wait(150)
        body = self.text()
        self.assertIn('* 2026년 12월 5일 토요일 오전 10시 ~ 오후 12시', body)
        ta = self.page.query_selector('#fields [data-field="times"]')
        self.assertIn('2026년 12월 5일', ta.input_value())
        self.assertNotIn('마포래미안푸르지오', body)

    def test_parking_toggle(self):
        self.pick('t5')
        self.assertIn('주차가 필요하신 경우', self.text())
        self.page.click('#fields [data-toggle="parking"]')
        self.wait(120)
        body = self.text()
        self.assertNotIn('주차가 필요하신 경우', body)
        self.assertIn('감사합니다!', body)
        self.page.click('#fields [data-toggle="detail"]')
        self.wait(120)
        self.assertNotIn('* 매물 :', self.text())

    def test_amount_display_mode_setting(self):
        self.pick('t13')
        self.page.fill('#fields [data-field="price"]', '67500')
        self.wait(120)
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
        self.assertIn('* 신한은행 110-123-456789 황호선', self.text())

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
        for label, cnt in (('고객 응대·매물 관리', 5), ('집보기·방문 안내', 6),
                           ('약정·계약 진행', 5), ('잔금·사후관리', 4)):
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

    def test_mobile_list_button_shows_all_twenty(self):
        # 카테고리를 고른 뒤에도 '목록' 버튼은 전체 20종을 보여 준다 (상단 탭도 '전체'로 돌아간다)
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_timeout(200)
        page.click('.stage-tabs .tab:has-text("약정·계약 진행")')
        page.wait_for_timeout(200)
        self.assertEqual(len(page.query_selector_all('#sheet-list .row')), 5)
        page.click('#sheet-close')
        page.wait_for_timeout(150)
        page.click('#btn-sheet')
        page.wait_for_timeout(220)
        self.assertTrue(page.is_visible('#sheet'))
        self.assertEqual(len(page.query_selector_all('#sheet-list .row')), 20, '목록 버튼은 전체 20종')
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
        for tid in ('t8', 't13', 't7', 't3', 't14', 't20', 't18', 't19'):
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
        # 390×844 — 지급 일정 표는 위줄 라벨+일정, 아래줄 퍼센트+금액으로 놓인다.
        # 왼쪽 열은 라벨·퍼센트 폭(76px)만, 오른쪽 열은 카드 오른쪽 끝까지 채워 좌우가 균형을 이룬다
        # (오른쪽을 200px로 묶어 두면 카드 오른쪽에 빈 여백이 남아 왼쪽으로 쏠려 보인다).
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
        page.fill('#fields [data-field="price"]', '247000')
        page.fill('#fields [data-field="jeongAmount"]', '3000')
        page.click('#fields [data-action="autoFill"]')
        page.wait_for_timeout(250)
        info = page.evaluate("""() => {
          const table = document.querySelector('#fields .paytable');
          const tb = table.getBoundingClientRect();
          const rows = [...table.querySelectorAll('.pay-row')].map(r => {
            const g = s => r.querySelector(s);
            const box = e => { const b = e.getBoundingClientRect();
              return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), t:+b.top.toFixed(1), w:+b.width.toFixed(1)}; };
            const rate = g('.pay-rate-inp'), rateWrap = g('.pay-rate'), date = g('.date-btn'), amount = g('.pay-amount input');
            const nm = g('.pay-name-text');
            return { label: nm.textContent.trim(),
                     rate: rate ? box(rate) : null, rateWrap: rateWrap ? box(rateWrap) : null,
                     date: box(date), amount: box(amount), name: box(nm),
                     nameLines: Math.round(nm.getBoundingClientRect().height /
                       parseFloat(getComputedStyle(nm).lineHeight || '16')),
                     amountFont: parseFloat(getComputedStyle(amount).fontSize),
                     rateFont: rate ? parseFloat(getComputedStyle(rate).fontSize) : null,
                     rateSameRowAsAmount: rate ? (Math.abs(rate.getBoundingClientRect().top - amount.getBoundingClientRect().top) < 20) : null,
                     rateLeftOfAmount: rate ? (rate.getBoundingClientRect().right <= amount.getBoundingClientRect().left + 0.5) : null };
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
        self.assertEqual([r['label'] for r in info['rows']], ['약정금', '계약금', '중도금', '잔금'])
        for r in info['rows']:
            with self.subTest(row=r['label']):
                self.assertGreaterEqual(r['amountFont'], 16, '금액 칸 글씨가 16px 미만')
                self.assertLessEqual(r['amount']['r'], info['panelRight'] + 0.5, '금액 칸이 패널 밖으로')
                # 오른쪽 칸(1fr)은 카드 안쪽 오른쪽 끝까지 꽉 찬다 — 오른쪽 빈 여백·왼쪽 쏠림 없음
                self.assertAlmostEqual(r['date']['r'], info['innerRight'], delta=1.0, msg='일정 칸이 카드 오른쪽 끝에 닿지 않는다')
                self.assertAlmostEqual(r['amount']['r'], info['innerRight'], delta=1.0, msg='금액 칸이 카드 오른쪽 끝에 닿지 않는다')
                # 두 줄의 왼쪽 끝을 맞춘다 (같은 76px 열 다음 10px 간격)
                self.assertAlmostEqual(r['date']['l'], r['amount']['l'], delta=1.0, msg='일정·금액 칸 왼쪽 끝이 어긋난다')
                self.assertAlmostEqual(r['date']['l'], info['innerLeft'] + 76 + 10, delta=1.0,
                                       msg='왼쪽 라벨 열이 76px + 10px 간격이 아니다')
                self.assertEqual(r['nameLines'], 1, f"{r['label']} 라벨이 줄바꿈됐다")
                if r['rate']:
                    self.assertGreaterEqual(r['rateFont'], 16, '퍼센트 칸 글씨가 16px 미만')
                    self.assertTrue(r['rateLeftOfAmount'], '퍼센트 칸이 금액 칸 왼쪽에 있지 않다')
                    self.assertTrue(r['rateSameRowAsAmount'], '퍼센트 칸이 금액 칸과 같은 줄이 아니다')
                    # 퍼센트 칸은 왼쪽 열 오른쪽 끝에 맞춰 금액 칸과 10px 간격으로 붙는다
                    self.assertAlmostEqual(r['rateWrap']['r'], info['innerLeft'] + 76, delta=1.0,
                                           msg='퍼센트 칸이 왼쪽 열 끝에 맞지 않는다')
                    self.assertAlmostEqual(r['amount']['l'] - r['rateWrap']['r'], 10, delta=1.0,
                                           msg='퍼센트와 금액 사이 간격이 10px가 아니다')
                else:
                    self.assertIn(r['label'], ('약정금', '잔금'), '퍼센트가 필요한 항목에 퍼센트 칸이 없다')
        # t13도 같은 규칙
        page.click('#btn-sheet')
        page.wait_for_timeout(150)
        page.click('#sheet-list [data-id="t13"]')
        page.wait_for_timeout(220)
        info2 = page.evaluate("""() => {
          const rows = [...document.querySelectorAll('#fields .pay-row')].map(r => {
            const rate = r.querySelector('.pay-rate-inp'), amount = r.querySelector('.pay-amount input');
            return { label: r.querySelector('.pay-name-text').textContent.trim(),
                     hasRate: !!rate,
                     rateLeftOfAmount: rate ? rate.getBoundingClientRect().right <= amount.getBoundingClientRect().left + 0.5 : null };
          });
          return { rows, scrollW: document.documentElement.scrollWidth, winW: window.innerWidth };
        }""")
        self.assertLessEqual(info2['scrollW'], info2['winW'], 't13 390px 가로 넘침')
        self.assertEqual([r['label'] for r in info2['rows']], ['계약금', '중도금', '잔금'])
        for r in info2['rows']:
            with self.subTest(row='t13 ' + r['label']):
                self.assertEqual(r['hasRate'], r['label'] != '잔금', '퍼센트 칸 자리')
                if r['hasRate']:
                    self.assertTrue(r['rateLeftOfAmount'])
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
        # 1440 넓이에서도 컴팩트 위젯 크기(최대 1040 × 700)로 가운데에 놓인다
        info = self.js("""() => {
          const l = document.querySelector('.layout').getBoundingClientRect();
          const panels = [...document.querySelectorAll('.panel')].map(e => {
            const r = e.getBoundingClientRect();
            return { w: r.width, h: r.height, top: r.top, bottom: r.bottom, right: r.right };
          });
          return { w: l.width, h: l.height, left: l.left, right: l.right, panels,
                   winW: window.innerWidth, winH: window.innerHeight,
                   docW: document.documentElement.scrollWidth,
                   docH: document.documentElement.scrollHeight };
        }""")
        self.assertLessEqual(info['w'], 1040.5, 'PC 컨테이너가 1040px를 넘으면 안 된다')
        self.assertGreaterEqual(info['w'], 860, '너무 좁아 내용이 눌리면 안 된다')
        self.assertLessEqual(info['h'], 700.5, '패널 높이가 700px를 넘으면 안 된다')
        self.assertGreaterEqual(info['h'], 640, '패널 높이가 640px 아래로 내려가면 안 된다')
        self.assertAlmostEqual(info['left'], info['winW'] - info['right'], delta=2, msg='가운데 정렬')
        for p in info['panels']:
            self.assertLessEqual(p['bottom'], info['winH'] + 0.5, '패널이 화면 아래로 잘린다')
            self.assertLessEqual(p['right'], info['winW'] + 0.5)
            self.assertGreater(p['h'], 560)
        self.assertLessEqual(info['docW'], info['winW'])
        self.assertLessEqual(info['docH'], info['winH'])

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
        self.page.click('#fields [data-remove-item="items"][data-idx="1"]')
        self.wait(100)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)
        self.assertIn('매물 한 줄을 뺐어요', self.page.inner_text('#snackbar'))
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

    def test_swipe_to_delete_property(self):
        self.pick('t7')
        self.page.click('#fields [data-add-item="items"]')
        self.wait(100)
        items = self.page.query_selector_all('#fields .prop-item')
        self.assertEqual(len(items), 2)
        box = items[1].bounding_box()
        x = box['x'] + box['width'] - 24
        y = box['y'] + box['height'] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x - 50, y, steps=6)
        self.page.mouse.move(x - 100, y, steps=6)
        self.page.mouse.up()
        self.page.wait_for_timeout(250)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 1)
        self.assertIn('매물 한 줄을 뺐어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(200)
        self.assertEqual(len(self.page.query_selector_all('#fields .prop-item')), 2)

    # ============================================================== 새 문자 4종
    def test_t16_myeongdan_danji_and_trade(self):
        self.pick('t16')
        body = self.text()
        self.assertIn('마포래미안푸르지오 1단지의 마래푸중앙부동산입니다', body)
        self.assertIn('현재 매수를 알아보는 손님이 있어', body)
        self.assertIn('매도 계획이 확정되셨다면', body)
        self.assertIn('매수 손님을 잘 끌어낼 수 있습니다', body)
        # 서명은 늘 맨 아래에 들어간다
        self.assertTrue(body.endswith('마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'), body)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0)

        # 버튼으로 단지 선택
        self.page.click('#fields [data-seg="danji"][data-value="2단지"]')
        self.wait(100)
        self.assertIn('마포래미안푸르지오 2단지의', self.text())

        # 직접 입력
        self.page.fill('#fields [data-field="danji"]', '5단지')
        self.wait(120)
        self.assertIn('마포래미안푸르지오 5단지의', self.text())
        self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="danji"].is-active')), 0)

        # 전세는 전세/임대 말로 바뀐다
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(120)
        body = self.text()
        self.assertIn('현재 전세를 알아보는 손님이', body)
        self.assertIn('임대 계획이 확정되셨다면', body)
        self.assertIn('전세 손님을 잘 끌어낼 수 있습니다', body)

        # 종별을 바꿔도 서명은 그대로 맨 아래에 있다
        body = self.text()
        self.assertIn('전세 손님을 잘 끌어낼 수 있습니다', body)
        self.assertIn('010-4585-7365', body)
        self.assertTrue(body.endswith('010-4585-7365 / 02-312-7365'))

    def test_t3_simple_and_detail_switch(self):
        self.pick('t3')
        body = self.text()
        self.assertIn('매수 손님이 있어서 연락드렸습니다', body)
        self.assertIn('방문 일시에 손님 모시고 방문드릴 수 있을까요?', body)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="times"]')), 0)

        # 달력으로 일시를 고르면 짧은 표기로 들어간다 (오늘/내일/모레 또는 M/D)
        self.page.click('#fields [data-date="when"]')
        self.wait(120)
        self.page.click('#calpop [data-cal-day="26"]')
        self.wait(120)
        self.page.select_option('#calpop [data-cal-hour]', '9')
        self.wait(100)
        self.page.select_option('#calpop [data-cal-min]', '30')
        self.wait(120)
        self.page.click('#calpop [data-cal-close]')
        body = self.text()
        self.assertIn('오전 9시30분에 손님 모시고 방문드릴 수 있을까요?', body)
        self.assertNotIn('(방문 일시)', body)

        # 전세 / 월세
        self.page.click('#fields [data-seg="guest"][data-value="월세"]')
        self.wait(100)
        self.assertIn('월세 손님이 있어서', self.text())

        # 상세 버전으로 바꾸면 후보 시간대 입력이 나온다
        self.page.click('#fields [data-seg="ver"][data-value="detail"]')
        self.wait(120)
        self.assertIsNotNone(self.page.query_selector('#fields [data-field="times"]'))
        body = self.text()
        self.assertIn('집을 보시고자 하는 월세 손님이 계셔서', body)
        self.assertIn('* (방문 희망 시간)', body)
        # 다시 간단으로 돌아와도 고른 일시는 남아 있다
        self.page.click('#fields [data-seg="ver"][data-value="simple"]')
        self.wait(120)
        self.assertIn('오전 9시30분에 손님 모시고', self.text())

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
        owner_list = self.js('() => SMSTemplates.VARIANTS.owner')
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
        # 안부 한 줄
        self.page.click('#fields [data-seg="greet"][data-value="cold"]')
        self.wait(120)
        self.assertIn('쌀쌀한 날씨에 감기 조심하세요', self.text())
        self.page.click('#fields [data-seg="greet"][data-value="none"]')
        self.wait(120)
        self.assertNotIn('쌀쌀한 날씨에 감기 조심하세요', self.text())
        # 문구를 돌려도 서명은 늘 맨 아래에 붙고 토글은 없다
        self.assertEqual(len(self.page.query_selector_all('#fields [data-toggle="signature"]')), 0)
        self.assertTrue(self.text().endswith('마래푸중앙부동산 드림\n010-4585-7365 / 02-312-7365'))

    def test_t18_coagent_decline_amounts(self):
        self.pick('t18')
        body = self.text()
        self.assertIn('매수 의사 확실한 손님이라 조심스레 여쭤봤어요', body)
        self.assertIn('매매 (금액)까지', body)
        self.assertIn('염리초 보내고 싶은 학부모입니다', body)
        self.page.fill('#fields [data-field="amount"]', '90000')
        self.wait(150)
        self.assertIn('매매 9억까지', self.text())
        self.assertIn('(9억)', self.page.inner_text('#fields'))
        self.page.fill('#fields [data-field="area"]', '34')
        self.wait(150)
        self.assertIn('매매 9억까지 (34평)', self.text())
        # 입주 — 협의로 적는다
        self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
        self.wait(150)
        self.page.fill('#fields [data-field="moveinText"]', '27년 8월')
        self.wait(150)
        self.assertIn('입주 27년 8월', self.text())

        # 전세 — 보증금 한 칸
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(150)
        body = self.text()
        self.assertIn('요즘 임대매물 귀한데, 염치없이 전화드렸어요', body)
        self.assertIn('보증금 (금액)까지', body)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 0,
                         '전세에는 월차임 칸이 없다')
        self.page.fill('#fields [data-field="deposit"]', '90000')
        self.wait(150)
        self.assertIn('보증금 9억까지', self.text())

        # 월세 — 보증금 + 월차임 두 칸
        self.page.click('#fields [data-seg="trade"][data-value="월세"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 1)
        self.page.fill('#fields [data-field="deposit"]', '10000')
        self.page.fill('#fields [data-field="rent"]', '250')
        self.wait(200)
        self.assertIn('보증금 1억 / 월세 250만 원까지', self.text())
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="area"]')), 0,
                         '임대 조건에는 평형 칸이 없다')

    def test_t19_promo_property_block_and_type_info(self):
        # 특가 매물 홍보 — 추천 매물 안내와 같은 매물 블록 + 강조 문구
        self.pick('t19')
        fields = self.page.inner_text('#fields')
        self.assertIn('강조 문구', fields)
        self.assertIn('+ 매물 추가', fields)
        # 예전 단지·층 / 평형 / 동·호로 빠르게 / 자동 변환 버튼은 없다
        for gone in ('단지·층', '평형', '빠르게', '자동 변환'):
            self.assertNotIn(gone, fields)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-action="promoUnit"]')), 0)
        # 매물 블록은 추천 매물 안내(t7)와 같은 칸을 쓴다
        self.pick('t7')
        t7_fields = self.js("""() => [...document.querySelectorAll('#fields [data-key]')]
            .map(e => e.dataset.key)""")
        self.pick('t19')
        t19_fields = self.js("""() => [...document.querySelectorAll('#fields [data-key]')]
            .map(e => e.dataset.key)""")
        for key in ('complex', 'dong', 'ho'):
            self.assertIn(key, t7_fields)
            self.assertIn(key, t19_fields)
        self.assertIn('🔑(매물)\n🔑최저가 조율 가능합니다', self.text())
        self.assertIn('마포래미안푸르지오 매매 특가 소식 전해드립니다!', self.text())

        # 동·호수를 넣으면 그 동·라인의 평형·타입·방향이 자동으로 들어간다
        dong = '#fields [data-prop="items"][data-idx="0"][data-key="dong"]'
        ho = '#fields [data-prop="items"][data-idx="0"][data-key="ho"]'
        self.page.fill(dong, '205')
        self.page.fill(ho, '1203')
        self.wait(180)
        type_inp = '#fields [data-prop="items"][data-idx="0"][data-key="typeInfo"]'
        self.assertEqual(self.page.input_value(type_inp), '34평 84E · 동향')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '210000')
        self.wait(200)
        body = self.text()
        self.assertIn('🔑마포래미안푸르지오 205동 1203호 34평 84E · 동향', body)
        self.assertIn('🔑매매 21억으로 최저가 조율 가능합니다', body)

        # [단지]로 가려도 호수 칸·배지는 살아 있고, 평형·타입은 그대로 따라온다
        self.page.click('#fields [data-prop-unit="dong"]')
        self.wait(150)
        self.assertIn('🔑마포래미안푸르지오 2단지 1203호 34평 84E · 동향', self.text())
        self.page.click('#fields [data-prop-unit="ho"]')
        self.wait(150)
        self.assertIn('🔑마포래미안푸르지오 2단지 12층 34평 84E · 동향', self.text())
        self.page.fill(ho, '1002')
        self.wait(180)
        self.assertEqual(self.page.input_value(type_inp), '34평 84A · 동향')

        # 강조 문구 · 거래 유형은 매물 줄에서 고른다
        self.page.fill('#fields [data-field="emphasis"]', '급매로 조율 가능합니다')
        self.page.click('#fields [data-prop-trade="items"][data-idx="0"][data-value="전세"]')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-money="amount"]', '115000')
        self.wait(200)
        body = self.text()
        self.assertIn('마포래미안푸르지오 전세 특가 소식 전해드립니다!', body)
        self.assertIn('🔑전세 11억 5천만으로 급매로 조율 가능합니다', body)

        # 표에 없는 동이면 빈 칸 — 직접 적은 값은 동·호를 바꿔도 그대로 둔다
        self.page.fill(dong, '999')
        self.wait(180)
        self.assertEqual(self.page.input_value(type_inp), '')
        self.page.fill(type_inp, '34평 84A · 남향')
        self.wait(150)
        self.page.fill(ho, '1203')
        self.wait(180)
        self.assertEqual(self.page.input_value(type_inp), '34평 84A · 남향')
        self.assertIn('34평 84A · 남향', self.text())

    def test_t19_promo_other_complex_has_no_type_info(self):
        # 다른 단지 이름을 넣으면 마래푸 타입표를 쓰지 않는다
        self.pick('t19')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="complex"]', '이편한세상신촌')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="dong"]', '205')
        self.page.fill('#fields [data-prop="items"][data-idx="0"][data-key="ho"]', '1203')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-prop="items"][data-idx="0"][data-key="typeInfo"]'), '')
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
        # 협력업체 연락처는 코드에 넣지 않는다 — 화면에서 한 번 추가해 두고 쓴다
        self.pick('t20')
        body = self.text()
        self.assertIn('마포구 일대를 잘 아는 대출 상담사분들입니다', body)
        self.assertIn('이름 : 상담사 이름\n연락처 : 전화번호', body)   # 저장된 연락처가 없을 때

        # 두 명을 추가하면 바로 문자에 들어간다
        for name, phone in (('신한 대출 안종미', '01047572152'), ('하나 대출 김효원', '01052415262')):
            self.page.fill('#fields [data-contact-new="name"]', name)
            self.page.fill('#fields [data-contact-new="phone"]', phone)
            self.page.click('#fields [data-contact-add]')
            self.wait(150)
        body = self.text()
        self.assertIn('이름 : 신한 대출 안종미\n연락처 : 010-4757-2152', body)
        self.assertIn('이름 : 하나 대출 김효원\n연락처 : 010-5241-5262', body)

        # 한 명 빼기 — 체크를 끄면 문자에서 빠진다 (체크 버튼과 이름 영역 둘 다 고를 수 있다)
        picks = self.page.query_selector_all('#fields .contact-list .contact')
        self.assertEqual(len(picks), 2)
        picks[1].query_selector('.contact-check').click()
        self.wait(120)
        body = self.text()
        self.assertIn('안종미', body)
        self.assertNotIn('김효원', body)
        # 다시 넣기
        self.page.query_selector_all('#fields .contact-list .contact')[1].query_selector('.contact-check').click()
        self.wait(120)
        self.assertIn('김효원', self.text())

        # 분야를 바꾸면 도입 문구가 바뀐다
        self.page.click('#fields [data-seg="vendorCat"][data-value="법무사"]')
        self.wait(120)
        body = self.text()
        self.assertIn('등기 업무를 도와드리는 법무사입니다', body)
        self.assertIn('이름 : 상담사 이름\n연락처 : 전화번호', body)   # 저장된 연락처가 없을 때

        # 새 연락처 추가
        self.page.fill('#fields [data-contact-new="name"]', '박법무 법무사')
        self.page.fill('#fields [data-contact-new="phone"]', '01098765432')
        self.page.click('#fields [data-contact-add]')
        self.wait(200)
        body = self.text()
        self.assertIn('이름 : 박법무 법무사\n연락처 : 010-9876-5432', body)
        self.assertIn('연락처를 추가했어요', self.page.inner_text('#toast'))

        # 새로 고쳐도 남아 있다
        self.wait(400)
        self.page.reload(wait_until='networkidle')
        self.wait(250)
        self.assertEqual(self.page.inner_text('#form-title'), '전문가·협력업체 소개')
        body = self.text()
        self.assertIn('박법무 법무사', body)
        self.assertIn('등기 업무를 도와드리는 법무사입니다', body)

        # 지우면 문자에서도 빠지고 되돌리기 된다
        self.page.click('#fields [data-contact-del]')
        self.wait(150)
        self.assertNotIn('박법무 법무사', self.text())
        self.assertIn('연락처를 지웠어요', self.page.inner_text('#snackbar'))
        self.page.click('#snackbar-undo')
        self.wait(250)
        self.assertIn('박법무 법무사', self.text())

        # 대출 목록은 그대로 (분야별로 따로 저장)
        self.page.click('#fields [data-seg="vendorCat"][data-value="대출"]')
        self.wait(150)
        contacts = self.js("() => JSON.parse(localStorage.getItem('smshelper.v1')).contacts")
        self.assertEqual(len(contacts['대출']), 2)
        self.assertEqual(len(contacts['법무사']), 1)

    def test_vendor_contact_list_scrolls_at_three_items(self):
        # 보낼 상담사 목록은 3개 높이에서 단독으로 스크롤된다
        self.pick('t20')
        self.page.click('#fields [data-seg="vendorCat"][data-value="법무사"]')
        self.wait(150)
        for i in range(4):
            self.page.fill('#fields [data-contact-new="name"]', '상담사%d' % (i + 1))
            self.page.fill('#fields [data-contact-new="phone"]', '010-1234-567%d' % i)
            self.page.click('#fields [data-contact-add]')
            self.wait(140)
        info = self.js("""() => {
          const l = document.querySelector('#fields .contact-list');
          const items = [...l.querySelectorAll('.contact')].map(e => e.getBoundingClientRect().height);
          const lb = l.getBoundingClientRect();
          const last = l.querySelectorAll('.contact')[3].getBoundingClientRect();
          return { count: items.length, itemH: items[0], client: l.clientHeight, scroll: l.scrollHeight,
                   overflow: getComputedStyle(l).overflowY,
                   lastBelow: last.bottom > lb.bottom - 1, scrollTop: l.scrollTop };
        }""")
        self.assertEqual(info['count'], 4)
        self.assertEqual(info['overflow'], 'auto')
        self.assertGreater(info['scroll'], info['client'] + 20, '업체가 4개면 넘쳐야 한다')
        three = info['itemH'] * 3 + 12  # 항목 3개 + 간격 2번
        self.assertGreaterEqual(info['client'], three - 2, '3개는 보여야 한다')
        self.assertLessEqual(info['client'], three + 3, '3개보다 많이 보이면 안 된다')
        self.assertTrue(info['lastBelow'], '4번째는 목록 밖으로 나가 있어야 한다')
        # 목록 안에서만 스크롤되고 페이지는 움직이지 않는다
        head_top = self.js("() => document.querySelector('#form-title').getBoundingClientRect().top")
        self.page.mouse.move(*self._center('#fields .contact-list'))
        self.page.mouse.wheel(0, 240)
        self.wait(200)
        after = self.js("""() => {
          const l = document.querySelector('#fields .contact-list');
          const c = l.querySelectorAll('.contact')[3];
          const lb = l.getBoundingClientRect(), cb = c.getBoundingClientRect();
          return { scrollTop: l.scrollTop, inView: cb.top >= lb.top - 1 && cb.bottom <= lb.bottom + 1,
                   headTop: document.querySelector('#form-title').getBoundingClientRect().top };
        }""")
        self.assertGreater(after['scrollTop'], 0, '목록이 스크롤돼야 한다')
        self.assertTrue(after['inView'], '스크롤하면 4번째가 보여야 한다')
        self.assertAlmostEqual(after['headTop'], head_top, delta=1)
        # 스크롤한 목록 안에서 체크를 눌러 뺄 수 있다 (4번째 상담사)
        self.page.locator('#fields .contact-list .contact').nth(3).locator('.contact-check').click()
        self.wait(200)
        self.assertNotIn('상담사4', self.text())
        self.assertIn('상담사1', self.text())

    def _center(self, sel):
        box = self.page.query_selector(sel).bounding_box()
        return (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)

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
        self.assertEqual(len(contacts.get('대출') or []), 0, '잘못된 입력은 저장되지 않는다')

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
        self.assertIn('마포래미안푸르지오 208동 1103호 (전세 11억 5천만)', body)
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
        self.assertIn('(보증금 1억 / 월세 350만 원)', page.input_value('#preview'))
        ctx.close()

        q2 = 'template=t7&dong=404&ho=2503&price=2300000000'   # 원 단위로 넘어와도 만 원으로
        ctx2, page2 = self.open_with_query(q2)
        self.assertIn('(매매 23억)', page2.input_value('#preview'))
        ctx2.close()

    def test_url_params_visit_date_and_number_template(self):
        ctx, page = self.open_with_query('template=3&visitDate=2026-11-26T09:30')
        body = page.input_value('#preview')
        self.assertIn('매수 손님이 있어서 연락드렸습니다', body)
        self.assertIn('오전 9시30분에 손님 모시고', body)
        ctx.close()

    def test_url_params_without_property_does_not_add_blank_row(self):
        ctx, page = self.open_with_query('template=t3')
        self.assertEqual(page.query_selector_all('#fields .prop-item').__len__(), 0)
        self.assertNotIn('(매물)', page.input_value('#preview'))
        ctx.close()

    # ============================================================== 수정요청서(2026-11-25) 회귀
    WANT_TEMPLATES = {
        't1': (1, '통화 후 첫 인사', '통화 감사 · 중개 서비스 소개'),
        't2': (2, '매물 접수 확인', '거래조건 · 입주 · 옵션'),
        't16': (3, '매도·임대 의뢰 제안', '대기 고객 매칭 · 매물 확보'),
        't18': (10, '공동중개 매물 요청', '고객 희망 조건 · 매물 확보'),
        't19': (11, '특가 매물 홍보', '매물 정보 · 거래조건 · 강조 문구'),
        't3': (4, '소유자 집보기 문의', '방문 일정 · 간단형 / 상세형'),
        't4': (5, '공동중개 집보기 문의', '방문 일정 · 공동중개 가능 여부'),
        't5': (6, '집보기 일정 안내', '예약 확정 / 조율 중'),
        't6': (7, '주차 안내', '주차 장소 · 주소'),
        't7': (8, '추천 매물 안내', '집보기 후 추천 매물 · 거래조건'),
        't17': (9, '집보기 후 감사 인사', '소유자·거주자 / 공동중개 / 고객'),
        't8': (12, '매매조건·약정 안내', '거래조건 · 지급 일정 · 특약'),
        't9': (13, '약정 일정 안내', '일시 · 준비물'),
        't10': (14, '계약 일정 안내', '일시 · 준비물'),
        't11': (15, '전자계약 안내', '계약 절차 · 전자서명'),
        't12': (16, '자금조달계획서 안내', '제출 절차 · 증빙서류'),
        't13': (18, '중도금·잔금 일정 안내', '일시 · 준비물 · 입금 정보'),
        't14': (19, '중개보수 안내', '보수 계산 · 입금 정보'),
        't20': (17, '전문가·협력업체 소개', '대출 · 세무 · 법무 · 입주 서비스'),
        't15': (20, '임대차 만기 확인', '만기 일정 · 연장·퇴거 의사'),
    }

    def test_categories_and_titles(self):
        # 카테고리 5/6/5/4 · 표시 순서 · 20종 제목·부제목 · 기존 번호
        got = self.js("""() => SMSTemplates.TEMPLATES.map(t => [t.stage, t.id, t.no, t.title, t.desc])""")
        stages = [g[0] for g in got]
        self.assertEqual(stages, [1]*5 + [2]*6 + [3]*5 + [4]*4, '카테고리별 5/6/5/4 순서')
        self.assertEqual([g[1] for g in got],
                         ['t1', 't2', 't16', 't18', 't19',
                          't3', 't4', 't5', 't6', 't7', 't17',
                          't8', 't9', 't10', 't11', 't12',
                          't13', 't14', 't20', 't15'])
        for stage, tid, no, title, desc in got:
            with self.subTest(tid=tid):
                self.assertEqual((no, title, desc), self.WANT_TEMPLATES[tid])

        tabs = [b.inner_text() for b in self.page.query_selector_all('.stage-tabs .tab')]
        self.assertEqual(tabs, ['전체', '고객 응대·매물 관리', '집보기·방문 안내', '약정·계약 진행', '잔금·사후관리'])
        for t in tabs:
            self.assertFalse(t[0].isdigit(), '단계 번호를 붙이지 않는다: ' + t)

        # 목록 머리 — 카테고리 이름과 종수
        heads = [e.inner_text() for e in self.page.query_selector_all('#tpl-list .list-stage')]
        self.assertEqual(heads, ['고객 응대·매물 관리 · 5종', '집보기·방문 안내 · 6종',
                                 '약정·계약 진행 · 5종', '잔금·사후관리 · 4종'])

        # 목록 줄 제목은 한 글자도 다르지 않다 (즐겨찾기 중복 제외)
        rows = self.js("""() => [...document.querySelectorAll('#tpl-list .row')]
            .map(r => [r.dataset.id, r.querySelector('.row-title-text').textContent, r.querySelector('.row-no').textContent])""")
        seen = {}
        for tid, title, no in rows:
            seen.setdefault(tid, (title, no))
        self.assertEqual(len(seen), 20)
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
        self.assertIn('간단형', self.page.inner_text('#fields'))
        self.assertIn('상세형', self.page.inner_text('#fields'))
        self.pick('t17')
        self.assertIn('추가 안 함', self.page.inner_text('#fields'))
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
        self.assertEqual(btn.inner_text().strip(), '문구 교체')
        self.assertIsNotNone(btn.query_selector('svg'), '문구 교체 버튼에 새로고침 아이콘')
        self.assertEqual(btn.query_selector('svg').get_attribute('class').split()[0], 'ico')
        self.assertIn('1 / 7', self.page.inner_text('#fields .field.is-variant'))

    def test_schedule_templates_share_calendar_icon_and_input(self):
        # 달력 아이콘은 SVG 한 벌을 그대로 쓴다 (직렬화 모양이 아니라 안쪽 그림을 비교)
        want = self.js("""() => { const d = document.createElement('div');
            d.innerHTML = SMSIcons.svg('calendar', 13);
            const s = d.querySelector('svg');
            return s.innerHTML + '|' + s.getAttribute('viewBox') + '|' + s.getAttribute('stroke-width'); }""")
        for tid in ('t8', 't9', 't10', 't13'):
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
                self.assertIsNotNone(self.page.query_selector('#calpop [data-cal-hour]'))
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
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '67500')
        self.page.fill('#fields [data-field="gyeyakAmount"]', '6750')
        self.page.fill('#fields [data-field="jungAmount"]', '51250')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-auto="janAmount"]'), '9,500')
        self.assertIn('* 잔금 : 95,000,000원', self.text())
        total = self.page.inner_text('.pay-total').replace('\n', ' ')
        self.assertIn('총합계', total)
        self.assertIn('675,000,000원', total)
        self.assertIn('(6억 7,500만원)', total)
        # 정상 일치 때는 안내 글자를 두지 않는다
        self.assertNotIn('일치', total)
        self.assertEqual(self.page.query_selector_all('#fields .pay-total-note'), [])
        # 중도금을 비우면 잔금 = 매매대금 − 계약금
        self.page.fill('#fields [data-field="jungAmount"]', '')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-auto="janAmount"]'), '60,750')
        self.assertIn('* 잔금 : 607,500,000원', self.text())
        # 초과 지급 — 빨간 경고 + 문자에도 음수 금액 없음
        self.page.fill('#fields [data-field="jungAmount"]', '62000')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-auto="janAmount"]'), '')
        total = self.page.inner_text('.pay-total')
        self.assertIn('많습니다', total)
        self.assertIn('is-bad', self.page.get_attribute('.pay-total', 'class'))
        color = self.js("""() => getComputedStyle(document.querySelector('.pay-total .pay-total-value')).color""")
        self.assertEqual(color, 'rgb(209, 67, 67)', '빨간 경고색')
        body = self.text()
        self.assertIn('* 잔금 : 확인 필요', body)
        self.assertIn('※', body)
        self.assertNotIn('잔금 : -', body)

    def test_paytable_layout_and_rate_edit(self):
        # 스파이더 계약 팝업형 표 — 구분 | 일정 | 금액
        self.pick('t8')
        heads = self.js("() => [...document.querySelectorAll('#fields .paytable-head span')].map(e => e.textContent)""")
        self.assertEqual(heads, ['구분', '일정', '금액'])
        # 박스 왼쪽 위 섹션 라벨 — 아래 '특약'(.group-head)과 같은 모양
        title = self.page.query_selector('#fields .paytable-title')
        self.assertIsNotNone(title, '지급 일정 섹션 라벨이 없다')
        self.assertEqual(title.inner_text().strip(), '지급 일정')
        same = self.js("""() => {
          const a = getComputedStyle(document.querySelector('#fields .paytable-title'));
          const b = getComputedStyle(document.querySelector('#fields .group-head'));
          return [a.color === b.color, a.fontSize === b.fontSize, a.fontWeight === b.fontWeight];
        }""")
        self.assertEqual(same, [True, True, True], '섹션 라벨이 특약과 다른 모양이다')
        pos = self.js("""() => {
          const t = document.querySelector('#fields .paytable-title').getBoundingClientRect();
          const b = document.querySelector('#fields .paytable').getBoundingClientRect();
          return {top: t.top - b.top, left: t.left - b.left};
        }""")
        self.assertLess(pos['top'], 14, '섹션 라벨은 박스 위쪽')
        self.assertLess(pos['left'], 20, '섹션 라벨은 박스 왼쪽')
        names = self.js("""() => [...document.querySelectorAll('#fields .pay-name-text')].map(e => e.textContent)""")
        self.assertEqual(names, ['약정금', '계약금', '중도금', '잔금'])
        # 구분 열은 '약정금/계약금' 글자 폭 정도, % 칸은 라벨 아래줄
        cols = self.js("""() => {
          const row = document.querySelector('#fields .pay-row');
          const nameCol = parseFloat(getComputedStyle(row).gridTemplateColumns.split(' ')[0]);
          const r = [...document.querySelectorAll('#fields .pay-row')][1];
          const label = r.querySelector('.pay-name-text');
          const lb = label.getBoundingClientRect(), rb = r.querySelector('.pay-rate').getBoundingClientRect();
          const amount = r.querySelector('.money-box').getBoundingClientRect();
          const date = r.querySelector('.date-btn').getBoundingClientRect();
          return {nameCol, rateBelow: rb.top >= lb.bottom - 0.5,
                  nameFits: label.scrollWidth <= nameCol + 2,
                  amountW: amount.width, dateW: date.width};
        }""")
        self.assertLessEqual(cols['nameCol'], 60, '구분 열이 너무 넓다')
        self.assertTrue(cols['rateBelow'], '% 칸이 라벨 옆에 남아 있다')
        self.assertTrue(cols['nameFits'], '구분 글자가 잘린다')
        self.assertGreaterEqual(cols['amountW'], 100, '금액 칸이 너무 좁다')
        self.assertGreater(cols['dateW'], 120, '일정 칸이 넓다')
        self.assertGreater(cols['dateW'], cols['amountW'], '일정 칸이 금액 칸보다 넓어야 한다')
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row .date-btn')), 4, '줄마다 일정 버튼')
        self.assertEqual(len(self.page.query_selector_all('#fields .pay-row .pay-amount .money-box')), 4)
        # 1차 입금·상세 메모는 덜어냈다 — 접힌 상세도, 그 입력칸도 없다
        self.assertEqual(self.page.query_selector_all('#fields .pay-more'), [], '1차 입금 상세가 남아 있다')
        self.assertEqual(self.page.query_selector_all('#fields [data-field="jeongFirst"]'), [])
        self.assertNotIn('1차 입금', self.page.inner_text('#fields .paytable'))
        # 잔금은 점선 테두리 읽기 전용
        jan = '#fields [data-auto="janAmount"]'
        self.assertTrue(self.page.eval_on_selector(jan, 'e => e.readOnly'))
        self.assertEqual(self.page.eval_on_selector(jan, "e => getComputedStyle(e).borderTopStyle"), 'dashed')
        # 매매가를 넣으면 비율 배지가 따라오고, 비율을 고치면 금액이 바뀐다
        self.page.fill('#fields [data-field="price"]', '67500')
        self.page.fill('#fields [data-field="gyeyakAmount"]', '6750')
        self.page.fill('#fields [data-field="jungAmount"]', '16875')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="gyeyakAmount"]'), '10')
        self.assertEqual(self.page.input_value('#fields [data-pay-rate="jungAmount"]'), '25')
        self.page.fill('#fields [data-pay-rate="gyeyakAmount"]', '20')
        self.wait(250)
        self.assertEqual(self.page.input_value('#fields [data-field="gyeyakAmount"]'), '13,500')
        self.assertEqual(self.page.input_value('#fields [data-auto="janAmount"]'), '37,125')
        self.assertIn('* 계약금 20% : 135,000,000원', self.text())
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
                page.fill('#fields [data-field="price"]', '247000')
                page.click('#fields [data-action="autoFill"]')
                page.wait_for_timeout(200)
                # 약정금·계약금·중도금·잔금 일정을 달력으로 채운다
                for field, day in (('jeongDate', 28), ('gyeyakDate', 5), ('jungDate', 15), ('janDate', 26)):
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
                    const hint = r.querySelector('.money-hint');
                    return {text: span.textContent, spanW: sr.width, textW: rg.getBoundingClientRect().width,
                            inside: sr.right <= btn.right - 1 && sr.left >= btn.left + 1,
                            moneyW: money.width, dateW: btn.width,
                            hintClipped: hint.scrollWidth > hint.clientWidth + 1};
                  })""")
                self.assertEqual(len(info), 4)
                for row in info:
                    self.assertRegex(row['text'], r'^\d{4}\.\d{2}\.\d{2} \(\S\)$', '일정이 날짜로 보인다')
                    self.assertGreaterEqual(row['spanW'], row['textW'] - 0.4, f"{row['text']} 가 잘렸다")
                    self.assertTrue(row['inside'], f"{row['text']} 가 버튼 밖으로 나갔다")
                    self.assertFalse(row['hintClipped'], '환산 줄이 잘렸다')
                    self.assertGreater(row['dateW'], row['moneyW'], '일정 칸이 금액 칸보다 넓어야 한다')
                ctx.close()

    def test_t13_paytable_rows(self):
        self.pick('t13')
        self.assertEqual(self.page.inner_text('#fields .paytable-title').strip(), '지급 일정')
        names = self.js("""() => [...document.querySelectorAll('#fields .pay-name-text')].map(e => e.textContent)""")
        self.assertEqual(names, ['계약금', '중도금', '잔금'])
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(150)
        names = self.js("""() => [...document.querySelectorAll('#fields .pay-name-text')].map(e => e.textContent)""")
        self.assertEqual(names, ['계약금', '잔금'], '전세에는 중도금 줄이 없다')
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 0)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-seg="kind"]')), 0,
                         '전세·월세는 일정이 잔금 하나뿐이다')
        self.page.click('#fields [data-seg="trade"][data-value="월세"]')
        self.wait(150)
        self.assertEqual(len(self.page.query_selector_all('#fields [data-field="rent"]')), 1,
                         '월세일 때만 월차임 칸')
        self.page.fill('#fields [data-field="deposit"]', '10000')
        self.page.fill('#fields [data-field="gyeyak"]', '1000')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-auto="jan"]'), '9,000')
        self.assertIn('(1억원)', self.page.inner_text('.pay-total').replace(' ', ''))

    def test_contract_templates_show_full_dong_ho(self):
        # 약정·계약·잔금 쪽은 단지·층으로 가리지 않고 동·호수를 그대로 보여 준다
        for tid in ('t8', 't9', 't10', 't13', 't15'):
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
        for tid in ('t2', 't3', 't4', 't5', 't7'):
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
                page.fill('#fields [data-field="gyeyakAmount"]', '6750')
                page.fill('#fields [data-field="jungAmount"]', '51250')
                page.evaluate('document.activeElement && document.activeElement.blur()')
                page.wait_for_timeout(250)
                info = page.evaluate("""() => {
                  const rows = [...document.querySelectorAll('#fields .pay-row')].map(r => {
                    const nm = r.querySelector('.pay-name-text').getBoundingClientRect();
                    const dt = r.querySelector('.date-btn').getBoundingClientRect();
                    const am = r.querySelector('.money-field').getBoundingClientRect();
                    const hint = r.querySelector('.money-hint');
                    const hr = hint.getBoundingClientRect();
                    return { sameLine: Math.abs(nm.top - dt.top) < 30, amountBelow: am.top >= dt.bottom - 1,
                             amountRight: am.left >= dt.right - 1,
                             hintClipped: hint.scrollWidth > hint.clientWidth + 1,
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
                self.assertTrue(all(r['sameLine'] for r in info['rows']), f'{w} 구분·일정 한 줄')
                self.assertFalse(any(r['hintClipped'] for r in info['rows']), f'{w} 환산 줄 잘림')
                if w < 900:
                    self.assertTrue(all(r['amountBelow'] for r in info['rows']), '390 금액은 아랫줄')
                else:
                    self.assertTrue(all(r['amountRight'] for r in info['rows']), '1000 금액은 오른쪽 칸')
                    self.assertLessEqual(info['docH'], info['winH'], '1000 세로 넘침')
                self.assertEqual(errors, [])
                ctx.close()

    def test_t13_payment_split_live(self):
        self.pick('t13')
        self.page.fill('#fields [data-field="price"]', '67500')
        self.page.fill('#fields [data-field="gyeyak"]', '6750')
        self.page.fill('#fields [data-field="jung"]', '51250')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-auto="jan"]'), '9,500')
        self.assertIn('* 잔금 : 95,000,000원', self.text())
        # 전세 — 보증금 − 계약금 (월차임 칸은 없다)
        self.page.click('#fields [data-seg="trade"][data-value="전세"]')
        self.wait(150)
        self.page.fill('#fields [data-field="deposit"]', '10000')
        self.page.fill('#fields [data-field="gyeyak"]', '1000')
        self.wait(200)
        self.assertEqual(self.page.input_value('#fields [data-auto="jan"]'), '9,000')
        body = self.text()
        self.assertIn('* 잔금 : 90,000,000원', body)
        self.assertIn('* 보증금 : 100,000,000원', body)
        self.assertNotIn('월차임', body)
        # 월세 — 보증금 + 월차임이 함께 나간다
        self.page.click('#fields [data-seg="trade"][data-value="월세"]')
        self.wait(150)
        self.page.fill('#fields [data-field="rent"]', '50')
        self.wait(200)
        self.assertIn('월차임 : 500,000원', self.text())

    def test_t8_autofill_uses_split(self):
        self.pick('t8')
        self.page.fill('#fields [data-field="price"]', '67500')
        self.wait(100)
        self.page.click('#fields [data-action="autoFill"]')
        self.wait(150)
        self.assertEqual(self.page.input_value('#fields [data-field="gyeyakAmount"]'), '6,750')
        self.assertEqual(self.page.input_value('#fields [data-field="jungAmount"]'), '16,875')
        self.assertEqual(self.page.input_value('#fields [data-auto="janAmount"]'), '43,875')
        body = self.text()
        self.assertIn('계약금 10% : 67,500,000원', body)
        self.assertIn('중도금 25% : 168,750,000원', body)
        self.assertIn('잔금 : 438,750,000원', body)

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
        self.assertIn('중개보수 요율 : 0.7%', self.text())
        self.assertIn('상한요율로 계산했습니다', self.text())
        # 상한 이내 협의 요율은 그대로
        self.page.fill('#fields [data-field="calcRate"]', '0.5')
        self.wait(200)
        self.assertIn('중개보수 요율 : 0.5%', self.text())
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
        self.assertIn('832,000원', self.page.inner_text('.calc-result'))
        self.assertIn('* 부가세 : 32,000원 (간이과세 4%)', self.text())
        self.assertIn('* 합계 : 832,000원', self.text())

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
            'stars': ['t3', 't4'],
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
        self.assertEqual(snap['stars'], ['t3', 't4'])
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
          const h = document.querySelector('#calpop [data-cal-hour]');
          const m = document.querySelector('#calpop [data-cal-min]');
          if (!h || !m) return null;
          return [+h.getBoundingClientRect().width.toFixed(1), +m.getBoundingClientRect().width.toFixed(1)];
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
                full = self.date_widths()[0]
                self.assertEqual(self.date_heights()[0], 38, '값이 없어도 칸 높이가 같다')

                # 협의 — 글자칸도 같은 폭
                self.page.click('#fields [data-date-mode="movein"][data-value="협의"]')
                self.wait(150)
                self.assertEqual(active(), '협의')
                self.assertEqual(self.date_widths('#fields .inp-date-free'), [full])
                self.assertEqual(self.page.get_attribute('#fields [data-field="moveinText"]', 'placeholder'),
                                 '예: 협의 / 즉시 / 26.12 말')
                self.page.fill('#fields [data-field="moveinText"]', '협의')
                self.wait(150)
                self.assertRegex(self.text(), r'입주\s*:?\s*협의')

                # 고정 — 날짜를 골라도 단추 폭·높이가 같다
                self.page.click('#fields [data-date-mode="movein"][data-value="고정"]')
                self.wait(150)
                self.assertEqual(active(), '고정')
                self.assertEqual(self.date_widths(), [full])
                self.page.click('#fields [data-date="movein"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-day="26"]')
                self.wait(160)
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                self.assertEqual(self.date_widths(), [full], '날짜를 골라도 칸 폭이 그대로')
                self.assertEqual(self.date_heights(), [38], '날짜를 골라도 칸 높이가 그대로')
                self.assertIn('2026.11.26 (목)', self.page.inner_text('#fields [data-date="movein"]'))

                # 기간 — 시작일 · 종료일 두 칸이 반씩, 값이 들어도 폭 그대로
                self.page.click('#fields [data-date-mode="movein"][data-value="기간"]')
                self.wait(150)
                self.assertEqual(active(), '기간')
                pair = self.date_widths('#fields .date-range .date-btn')
                self.assertEqual(len(pair), 2)
                self.assertAlmostEqual(pair[0], pair[1], delta=0.6)
                self.assertAlmostEqual(pair[0] + pair[1] + 18, full, delta=1.5)
                self.assertEqual([self.page.inner_text(s).strip() for s in
                                  ('#fields [data-date="moveinStart"]', '#fields [data-date="moveinEnd"]')],
                                 ['시작일', '종료일'])
                for field, days, day in (('moveinStart', 1, 1), ('moveinEnd', 1, 31)):
                    self.page.click(f'#fields [data-date="{field}"]')
                    self.wait(160)
                    for _ in range(days):
                        self.page.click('#calpop [data-cal-nav="1"]')
                        self.wait(120)
                    self.page.click(f'#calpop [data-cal-day="{day}"]')
                    self.wait(160)
                    self.page.click('#calpop [data-cal-close]')
                    self.wait(150)
                self.assertEqual(self.date_widths('#fields .date-range .date-btn'), pair,
                                 '기간 두 칸도 값이 들어가면 폭이 그대로')
                self.assertRegex(self.text(), r'입주\s*:?\s*2026\.12\.01 ~ 2026\.12\.31')

    def test_every_date_trigger_width_fixed(self):
        # 20종 어디서든 — 날짜·일정 단추 폭/높이와 팝업 시·분 칸 폭이 선택 전후로 같다
        tids = ('t2', 't3', 't4', 't5', 't7', 't8', 't9', 't10', 't13', 't18')
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
                    self.page.select_option('#calpop [data-cal-hour]', '10')
                    self.wait(160)
                    self.page.select_option('#calpop [data-cal-min]', '30')
                    self.wait(160)
                pop_time = self.cal_time_widths()
                if pop_day:
                    self.assertEqual(pop_day, pop_empty, f'{tid} 날짜를 골라 팝업 시·분 칸 폭이 밀렸다')
                    self.assertEqual(pop_time, pop_empty, f'{tid} 시간을 골라 팝업 시·분 칸 폭이 밀렸다')
                self.page.click('#calpop [data-cal-close]')
                self.wait(150)
                self.assertEqual(self.date_widths(), before, f'{tid} 값이 들어가면 날짜 칸 폭이 흔들린다')
                self.assertEqual(self.date_heights(), hbefore, f'{tid} 값이 들어가면 날짜 칸 높이가 흔들린다')
        self.assertGreaterEqual(checked, 8, '날짜 칸이 있는 문자를 충분히 훑었다')

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
        self.page.select_option('#calpop [data-cal-hour]', '10')
        self.wait(160)
        self.page.select_option('#calpop [data-cal-min]', '30')
        self.wait(160)
        # 시간을 골라도 버튼 자리·시분 칸 폭이 그대로 (예전의 '시간 지우기'는 없다)
        self.assertEqual(self.cal_foot(), foot)
        self.assertEqual(len(self.page.query_selector_all('#calpop .link')), 0)
        self.assertIn('2026.11.26 (목) 오전 10:30', self.page.inner_text('#fields .date-btn'))
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

    # ============================================================== 버전 · 배포 파일
    def test_24_version_bumped_to_1_1_3(self):
        with open(os.path.join(ROOT, 'sw.js'), encoding='utf-8') as f:
            sw = f.read()
        self.assertIn("'v1.1.3'", sw)
        self.assertIn("'js/sync.js'", sw)
        # 새 파일(동호수 타입표)도 오프라인 캐시에 들어간다
        self.assertIn("'js/maraepu-types.js'", sw)
        with open(os.path.join(ROOT, 'index.html'), encoding='utf-8') as f:
            html = f.read()
        for f_ in ('icons', 'maraepu-types', 'core', 'templates', 'sync', 'app'):
            self.assertIn(f'js/{f_}.js?v=1.1.3', html)
        self.assertIn('styles.css?v=1.1.3', html)
        gradle = open(os.path.join(ROOT, 'android/app/build.gradle'), encoding='utf-8').read()
        self.assertIn('versionCode 8', gradle)
        self.assertIn("versionName '1.1.3'", gradle)


if __name__ == '__main__':
    unittest.main(verbosity=2)
