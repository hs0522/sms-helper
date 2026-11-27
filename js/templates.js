/* 마래푸중앙부동산 문자 도우미 — 17종 템플릿 정의 (2026-11-26 v1.2.0 통합)
 * 각 템플릿: 필드 스키마(fields) + 문자 조립 함수(build).
 * build(data, ctx) -> 완성 문자. ctx = {office, phones, feeAccount, amountMode, contacts}
 */
(function (global) {
  'use strict';

  var C = global.SMSCore;

  function amt(man, ctx) { return C.formatAmount(man, ctx.amountMode); }
  // 아직 채우지 않은 자리는 대괄호 대신 소괄호로 둔다 — 문자 본문에 [ ] 가 나오지 않게
  function txt(v, ph) {
    var s = String(v == null ? '' : v).trim();
    return s || (ph ? '(' + ph + ')' : '');
  }
  function dt(v, ph) {
    var s = C.formatDateTime(v);
    return s || '(' + (ph || '일시') + ')';
  }
  function money(man, ph, ctx) {
    var s = amt(C.parseMan(man), ctx);
    return s || '(' + (ph || '금액') + ')';
  }
  // 모든 문자는 맨 아래에 상호·번호 서명을 한 줄 띄워 항상 넣는다 (토글 없음)
  function sign(ctx) { return ctx.office + ' 드림\n' + ctx.phones; }
  // 인사말 — 2차 수정본은 "안녕하세요, 마래푸중앙부동산입니다. 😊"로 통일
  function hello(ctx) { return '안녕하세요, ' + ctx.office + '입니다. 😊'; }
  function helloPlain(ctx) { return '안녕하세요, ' + ctx.office + '입니다.'; }
  function join(blocks) {
    return blocks.filter(function (b) { return b != null && b !== ''; }).join('\n\n');
  }
  function hint(v) { var s = C.manHint(C.parseMan(v)); return s || ''; }
  // 안내 문장 안의 금액 — 괄호 환산 없이 원단위만
  function won(man) { return man == null ? '' : C.formatWonPlain(man * 10000); }
  function wonOr(man, ph) { return won(man) || ph; }
  // 금액이 매매가의 몇 % 인지 (예: 25 → " 25%")
  function pctOf(part, whole) {
    var p = C.parseMan(part), w = C.parseMan(whole);
    if (p == null || !w) return null;
    return Math.round((p / w) * 1000) / 10;
  }
  function pctLabel(p, fallback) {
    return ' ' + (p == null ? fallback : p) + '%';
  }

  /* ---------------- 공통 지급 일정 (약정금 · 가계약금 · 계약금 · 중도금 · 잔금) -------------
     계약 조건 안내(t8)와 계약 일정 안내(t10)가 같은 포맷을 쓴다.
     · 1차 금액·일정은 평면 칸(amountId·dateId), 2차부터는 data.payExtra[항목] 배열에 담는다.
     · 약정금·가계약금은 총합계에서 빼고, 잔금은 기준금액(매매가·보증금) − 계약금 − 중도금으로 자동 계산한다. */
  var PAY_ITEM_DEFS = [
    { key: 'yakjeong', label: '약정금', excludeSum: true },
    { key: 'jeong', label: '가계약금', excludeSum: true },
    { key: 'gyeyak', label: '계약금', rate: true },
    { key: 'jung', label: '중도금', rate: true },
    { key: 'jan', label: '잔금', auto: true }
  ];

  // suffix: t8 은 'Amount'(gyeyakAmount) · t10 은 접미사 없이(gyeyak)
  function payItems(suffix) {
    return PAY_ITEM_DEFS.map(function (it) {
      return {
        key: it.key, label: it.label,
        excludeSum: !!it.excludeSum, rate: !!it.rate, auto: !!it.auto,
        amountId: it.key + (suffix || ''),
        dateId: it.key + 'Date'
      };
    });
  }
  function payItemOf(items, key) {
    return (items || []).filter(function (it) { return it.key === key; })[0] || null;
  }
  function payExtraOf(d, key) {
    var e = d && d.payExtra;
    var list = e && Array.isArray(e[key]) ? e[key] : [];
    return list;
  }
  // 그 항목의 차수 개수 (1차는 늘 있다)
  function payPartCount(d, item) {
    return item ? 1 + payExtraOf(d, item.key).length : 0;
  }
  function payPartAmount(d, item, idx) {
    if (!item) return null;
    if (idx === 0) return C.parseMan(d && d[item.amountId]);
    var p = payExtraOf(d, item.key)[idx - 1];
    return C.parseMan(p && p.amount);
  }
  function payPartDate(d, item, idx) {
    if (!item) return null;
    if (idx === 0) return (d && d[item.dateId]) || null;
    var p = payExtraOf(d, item.key)[idx - 1];
    return (p && p.date) || null;
  }
  // 한 항목의 합계 (1차 + 2차 …)
  function payItemSum(d, item) {
    if (!item) return null;
    var total = 0, any = false;
    for (var i = 0; i < payPartCount(d, item); i++) {
      var m = payPartAmount(d, item, i);
      if (m != null) { total += m; any = true; }
    }
    return any ? total : null;
  }
  // 기준 금액 — 매매가는 매매가 칸, 보증금은 매물칸(전세·월세)
  function payScheduleBase(t, d) {
    if (!d) return null;
    var id = (t && typeof t === 'object') ? t.id : t;
    if (id === 't10') {
      var p = (d.prop && typeof d.prop === 'object') ? d.prop : {};
      var trade = p.trade || d.trade || '매매';
      return C.parseMan(trade === '월세' ? p.deposit : p.amount);
    }
    return C.parseMan(d.price);
  }
  // 잔금 합계 (자동) = 기준금액 − 계약금 합계 − 중도금 합계
  function payJanTotal(t, d, items) {
    var base = payScheduleBase(t, d);
    if (base == null) return null;
    var used = 0;
    (items || []).forEach(function (it) {
      if (it.key === 'jan' || it.excludeSum) return;
      var s = payItemSum(d, it);
      if (s != null) used += s;
    });
    return base - used;
  }
  // 화면·문자에 쓰는 값 — 잔금 마지막 차수는 자동 계산 값
  function payPartValue(t, d, items, item, idx) {
    var n = payPartCount(d, item);
    if (item && item.auto && idx === n - 1) {
      var jt = payJanTotal(t, d, items);
      if (jt == null) return payPartAmount(d, item, idx);
      var earlier = 0;
      for (var i = 0; i < n - 1; i++) {
        var m = payPartAmount(d, item, i);
        if (m != null) earlier += m;
      }
      return jt - earlier;
    }
    return payPartAmount(d, item, idx);
  }
  // 총합계 = 계약금 + 중도금 + 잔금 (약정금·가계약금은 빼고)
  function payScheduleMan(t, d, items) {
    var total = 0, any = false;
    (items || []).forEach(function (it) {
      if (it.excludeSum) return;
      if (it.auto) {
        var jt = payJanTotal(t, d, items);
        var janSum = payItemSum(d, it);
        if (jt != null) { total += Math.max(0, jt); any = true; }
        else if (janSum != null) { total += janSum; any = true; }
        return;
      }
      var s = payItemSum(d, it);
      if (s != null) { total += s; any = true; }
    });
    return any ? total : null;
  }
  // 계약일에 실제로 입금하는 금액 — 가계약금은 계약금에서 빼고 채운다
  function payDepositMan(t, d, items, kind) {
    var jeong = payItemOf(items, 'jeong');
    var gyeyak = payItemOf(items, 'gyeyak');
    var jeongSum = payItemSum(d, jeong);
    var gySum = payItemSum(d, gyeyak);
    if (kind === '가계약') return jeongSum != null ? jeongSum : gySum;
    if (gySum != null) return gySum - (jeongSum || 0);
    return jeongSum;
  }
  // 한 항목의 줄 — 차수가 여럿이면 1차·2차로 나눠 적는다 (지급 일정 표의 라벨과 같은 모양)
  function payLines(t, d, items, item, ctx, o) {
    o = o || {};
    var out = [];
    var n = payPartCount(d, item);
    var base = payScheduleBase(t, d);
    for (var i = 0; i < n; i++) {
      var man = payPartValue(t, d, items, item, i);
      var dv = payPartDate(d, item, i);
      if (man == null && !dv) continue;
      var label = item.label + (n > 1 ? ' ' + (i + 1) + '차' : '');
      var pct = '';
      if (item.rate && base && man != null && o.rate !== false) {
        var p = Math.round((man / base) * 1000) / 10;
        pct = ' ' + p + '%';
      }
      var line = '- ' + label + pct + ' : ' + (amt(man, ctx) || '(' + item.label + ')');
      var when = C.formatDateTime(dv);
      if (o.date !== false) line += ' / ' + (when || o.blankDate || '(일정)');
      out.push(line);
    }
    // 아직 안 적은 항목도 자리는 보여 준다 (가계약금·계약금·잔금)
    if (!out.length && o.force) out.push('- ' + item.label + ' : (' + item.label + ')');
    return out;
  }
  function prop(p, mode) {
    var o = Object.assign({}, p || {});
    o.mode = mode || o.mode || 'ho';
    var label = C.propertyLabel(o);
    // 단지명만 있고 동·호수가 비어 있으면 아직 채우지 않은 것으로 본다
    var complex = String(o.complex || '').trim();
    if (label && complex && label === complex) return '(매물)';
    return label || '(매물)';
  }
  function propWithPrice(p, mode) {
    var base = prop(p, mode);
    var price = C.propPrice(p);
    return base + ' / ' + (price || '(가격)');
  }
  function itemsOf(data, key, mode) {
    var list = data[key];
    if (!Array.isArray(list) || !list.length) return [];
    return list.filter(function (p) {
      return p && (p.dong || p.ho || p.complex || p.price || p.amount || p.deposit || p.rent);
    });
  }
  // 매매 / 전세 / 월세 — 저장값이 없으면 매매
  function tradeOf(d) {
    var t = d && d.trade;
    return t === '전세' || t === '월세' ? t : '매매';
  }
  function isRentTrade(d) { var t = tradeOf(d); return t === '전세' || t === '월세'; }
  // 매수 / 전세 / 월세 (손님 쪽 표현)
  function guestOf(t) { return t === '매매' ? '매수' : (t === '전세' ? '전세' : '월세'); }
  // 방문 희망 한 줄 — "11월 26일 (목) 10:00" (시각을 비우면 날짜만)
  function visitLine(v) {
    if (!v || !v.date) return '';
    return C.formatVisitLine(v.date, v.hour, v.min);
  }

  /* ---------------- 집보기 후 감사 인사 — 대상별 문구 ---------------- */
  var VARIANTS = {
    resident: [
      '오늘 집을 보여주시느라 불편하셨을 텐데 협조해 주셔서 진심으로 감사드립니다. 덕분에 손님께 잘 안내해 드릴 수 있었습니다.',
      '바쁘신 중에 시간 내어 집을 보여주셔서 감사드립니다. 손님께서도 긍정적으로 살펴보셔서 좋은 결과로 이어지도록 노력하겠습니다.',
      '오늘 방문 잘 마쳤습니다. 집에 대해 자세히 설명해 주신 덕분에 손님께 필요한 내용을 잘 전달할 수 있었습니다. 감사합니다.',
      '오늘 집 보여주시느라 수고 많으셨습니다. 손님께서 관심 있게 살펴보신 만큼 좋은 소식 전해드릴 수 있도록 노력하겠습니다.',
      '오늘 따뜻하게 맞아주시고 방문에 협조해 주셔서 감사드립니다. 추후 진행사항이 있으면 다시 연락드리겠습니다.',
      '오늘 귀한 시간 내주셔서 감사드립니다. 덕분에 방문 일정을 잘 마쳤습니다. 추가로 확인할 사항이 생기면 연락드리겠습니다.',
      '집을 잘 관리해 주신 덕분에 손님께도 좋은 인상으로 안내해 드릴 수 있었습니다. 방문에 협조해 주셔서 감사드립니다.'
    ],
    coagent: [
      '사장님, 오늘 집보기 잘 마쳤습니다. 바쁘신 중에 시간 내어 현장까지 챙겨주셔서 진심으로 감사드립니다.',
      '사장님 덕분에 손님을 편안하게 모시고 왔습니다. 좋은 결과로 이어질 수 있도록 잘 진행해 보겠습니다. 감사합니다.',
      '사장님, 매물에 대해 자세히 설명해 주셔서 손님께 큰 도움이 되었습니다. 친절하게 안내해 주셔서 감사드립니다.',
      '사장님, 집보기 일정에 협조해 주셔서 감사드립니다. 손님께서도 긍정적으로 살펴보셔서 진행사항이 있으면 다시 연락드리겠습니다.',
      '오늘 함께해 주셔서 감사드립니다, 사장님. 앞으로도 좋은 매물로 함께 협력할 기회가 있기를 바랍니다.',
      '사장님, 현장에서 세심하게 안내해 주신 덕분에 손님께서도 편안히 살펴보셨습니다. 감사드립니다.',
      '사장님, 오늘 집보기 잘 마쳤습니다. 일정 조율부터 현장 안내까지 도와주신 덕분에 원활하게 진행됐습니다. 감사합니다.'
    ],
    guest: [
      '오늘 바쁘신 중에 집을 보러 와주셔서 감사합니다. 천천히 살펴보시고 궁금하신 점이 있으시면 편하게 연락 주세요.',
      '오늘 여러 집을 함께 보시느라 고생 많으셨습니다. 충분히 비교해 보시고 관심 있는 매물이 있으시면 말씀해 주세요.',
      '오늘 방문해 주셔서 감사합니다. 마음에 드셨던 매물은 거래조건도 원만히 협의될 수 있도록 노력하겠습니다.',
      '오늘 집 보시느라 고생 많으셨습니다. 추가로 확인하고 싶으신 부분이나 더 보고 싶은 매물이 있으시면 편하게 말씀해 주세요.',
      '오늘 귀한 시간 내주셔서 감사합니다. 중요한 결정인 만큼 충분히 비교해 보시고 편하실 때 의견 주시면 감사하겠습니다.',
      '오늘 함께 집을 살펴보며 희망 조건을 자세히 들을 수 있어 감사했습니다. 말씀해 주신 내용을 참고하여 좋은 매물을 찾아드리겠습니다.',
      '오늘 집보기는 잘 마치셨는지요? 시간 내어 방문해 주셔서 감사합니다. 추가 방문이 필요하시면 편하신 일정에 맞춰 안내해 드리겠습니다.'
    ]
  };

  // 안부 인사 — 하나만 고를 수 있다 (다른 것을 누르면 바뀌고, 고른 것을 다시 누르면 꺼진다)
  // 주말 / 연휴 / 명절은 각각 다른 문구로 따로 둔다 (섞여 나가지 않게)
  var GREETINGS = [
    { v: 'weather', l: '날씨', text: '날씨가 제법 쌀쌀하네요. 감기 조심하시고 따뜻한 하루 보내세요!' },
    { v: 'morning', l: '아침', text: '좋은 아침입니다! 오늘도 기분 좋은 하루 보내세요.' },
    { v: 'evening', l: '저녁', text: '오늘 하루도 수고 많으셨습니다. 편안한 저녁 보내세요!' },
    { v: 'weekend', l: '주말', text: '한 주 동안 수고 많으셨습니다. 즐거운 주말 보내세요!' },
    { v: 'holiday', l: '연휴', text: '모처럼의 연휴, 여유롭고 즐거운 시간 보내세요!' },
    { v: 'holiday2', l: '명절', text: '가족분들과 함께 웃음 가득하고 따뜻한 명절 보내세요!' }
  ];

  var GREET_KEYS = GREETINGS.map(function (g) { return g.v; });

  function greetList(d) {
    var g = d && d.greets;
    var arr = Array.isArray(g) ? g : (g ? [g] : []);
    // 하나만 고를 수 있으므로 저장값에 여럿이 남아 있어도 첫 하나만 쓴다
    return GREET_KEYS.filter(function (k) { return arr.indexOf(k) !== -1; }).slice(0, 1);
  }

  function greetingText(list) {
    return list.map(function (k) {
      var g = GREETINGS.filter(function (x) { return x.v === k; })[0];
      return g ? g.text : '';
    }).filter(Boolean).join('\n');
  }

  /* ---------------- 협력업체·상담사 ---------------- */
  var VENDOR_CATS = ['대출', '세무사', '법무사', '인테리어', '입주청소', '이사'];

  var VENDOR_INTRO = {
    '대출': '부동산 대출 상담을 받아보실 수 있는 상담사를 소개드립니다.\n자금계획에 맞춰 대출 가능 여부와 금리 등 세부 조건을 상담받아 보시기 바랍니다. 실제 조건은 금융기관 심사에 따라 달라질 수 있습니다.',
    '세무사': '양도소득세·취득세 등 부동산 세금 관련 상담을 받아보실 수 있는 세무사를 소개드립니다.',
    '법무사': '소유권이전등기, 근저당권 말소 등 등기 업무를 상담받아 보실 수 있는 법무사를 소개드립니다.',
    '인테리어': '입주 전 인테리어 공사에 관해 상담 및 견적을 받아보실 수 있는 업체를 소개드립니다.',
    '입주청소': '입주청소 상담 및 견적을 받아보실 수 있는 업체를 소개드립니다.',
    '이사': '이사 일정과 비용에 관해 상담 및 견적을 받아보실 수 있는 업체를 소개드립니다.'
  };

  // 처음 열었을 때 들어 있는 협력업체·상담사 44명 (2026-11-27 호선 님 명단·공개 업로드 승인)
  // id 는 사람이 바뀌지 않는 한 고정 — 저장된 연락처와 id 로 합쳐서 빠지지 않게 한다
  var DEFAULT_CONTACTS = {
    '대출': [
      { id: 'd01', name: '국민 대출 김동준', phone: '010-3704-2417' },
      { id: 'd02', name: '국민 대출 김현민', phone: '010-9903-5217' },
      { id: 'd03', name: '국민 대출 정대영', phone: '010-3051-6668' },
      { id: 'd04', name: '국민 대출 허진석', phone: '010-9795-9511' },
      { id: 'd05', name: '기업 대출 곽호경', phone: '010-4213-7441' },
      { id: 'd06', name: '기업 대출 신현철', phone: '010-3442-5610' },
      { id: 'd07', name: '기업 대출 조광현', phone: '010-9002-2229' },
      { id: 'd08', name: '농협 대출 박흥찬', phone: '010-8455-9222' },
      { id: 'd09', name: '농협 대출 송동원', phone: '010-9955-7654' },
      { id: 'd10', name: '농협 대출 이용중', phone: '010-5440-9666' },
      { id: 'd11', name: '농협 대출 이정준', phone: '010-7654-9832' },
      { id: 'd12', name: '농협 대출 장래형', phone: '010-4015-4905' },
      { id: 'd13', name: '농협 대출 정광열', phone: '010-2934-6599' },
      { id: 'd14', name: '신한 대출 김보경', phone: '010-5397-3183' },
      { id: 'd15', name: '신한 대출 안종미', phone: '010-4757-2152' },
      { id: 'd16', name: '신한 대출 조주몽', phone: '010-5247-3127' },
      { id: 'd17', name: '신협 대출 김지훈', phone: '010-5529-4755' },
      { id: 'd18', name: '신협 대출 백태선', phone: '010-4396-6534' },
      { id: 'd19', name: '신협 대출 신우재', phone: '010-7733-6977' },
      { id: 'd20', name: '신협 대출 한현호', phone: '010-5752-5914' },
      { id: 'd21', name: '우리 대출 박영훈', phone: '010-3194-1781' },
      { id: 'd22', name: '우리 대출 오준식', phone: '010-9666-4088' },
      { id: 'd23', name: '우리 대출 조광연', phone: '010-8678-6201' },
      { id: 'd24', name: '우리 대출 조종훈', phone: '010-9232-6354' },
      { id: 'd25', name: '우리 대출 홍승원', phone: '010-5228-3366' },
      { id: 'd26', name: '하나 대출 권정민', phone: '010-5278-1579' },
      { id: 'd27', name: '하나 대출 김효원', phone: '010-5241-5262' },
      { id: 'd28', name: '하나 대출 송주석', phone: '010-5760-6242' },
      { id: 'd29', name: '하나 대출 유선아', phone: '010-8033-0143' },
      { id: 'd30', name: '하나 대출 이재란', phone: '010-9135-7485' },
      { id: 'd31', name: '하나 대출 이희진', phone: '010-5300-3966' },
      { id: 'd32', name: 'SC 대출 이창길', phone: '010-2927-4771' },
      { id: 'd33', name: '삼성생명 대출 박재영', phone: '010-3361-5793' }
    ],
    '세무사': [
      { id: 's01', name: '곽승현 세무사', phone: '010-7741-5615' }
    ],
    '법무사': [
      { id: 'l01', name: '다울 법무사', phone: '010-3959-1710' }
    ],
    '인테리어': [
      { id: 'i01', name: '한성디자인 박윤희', phone: '010-7174-2423' },
      { id: 'i02', name: '한샘 리하우스 정형균과장', phone: '010-2943-0186' }
    ],
    '입주청소': [
      { id: 'c01', name: '새집향기 입주청소', phone: '010-2220-3163' },
      { id: 'c02', name: '참클린', phone: '010-5839-0544' },
      { id: 'c03', name: '더크린 김봉주', phone: '010-3167-8824' },
      { id: 'c04', name: '깔끔이 청소박사', phone: '010-8960-0067' },
      { id: 'c05', name: '세화청소', phone: '010-3247-1475' }
    ],
    '이사': [
      { id: 'm01', name: '소원아빠 이사', phone: '010-9248-4484' },
      { id: 'm02', name: 'KGB주식회사 소장 민병권', phone: '010-4155-3011' }
    ]
  };

  function contactsFor(ctx, cat) {
    var all = (ctx && ctx.contacts) || {};
    var list = all[cat];
    if (!Array.isArray(list)) list = DEFAULT_CONTACTS[cat] || [];
    return list;
  }

  function selectedFor(data, cat) {
    var sel = (data && data.vendorSel) || {};
    var ids = sel[cat];
    if (!Array.isArray(ids)) return [];
    return ids;
  }

  function contactBlock(cat, list, ids) {
    // 상담사(대출·세무사·법무사)는 이름, 업체(인테리어·입주청소·이사)는 업체명
    var label = (cat === '인테리어' || cat === '입주청소' || cat === '이사') ? '업체명' : '이름';
    var picked = list.filter(function (c) { return ids.indexOf(c.id) !== -1; });
    if (!picked.length) return '- ' + label + ' : (상담사/업체 이름)\n- 연락처 : (전화번호)';
    return picked.map(function (c) {
      return '- ' + label + ' : ' + String(c.name || '').trim() + '\n- 연락처 : ' + C.formatPhone(c.phone);
    }).join('\n\n');
  }

  /* 카테고리(stage) · 표시 순서(order) · 제목 · 부제목 — 2026-11-26 피드백 반영(17종)
     내부 ID는 그대로 두고(저장값 유지) 화면은 번호를 다시 매긴다. */
  var TEMPLATES = [
    /* ---------------- 접수·홍보 ---------------- */
    {
      id: 't1',
      no: 1,
      stage: 1,
      order: 1,
      icon: 'message',
      title: '통화 후 첫 인사',
      desc: '통화 감사 · 중개 서비스 소개',
      fixed: true,
      fields: [],
      build: function (d, ctx) {
        return join([
          hello(ctx),
          '바쁘신 중에 통화해 주셔서 감사합니다.\n말씀 나눈 내용은 충분히 검토해 보시고, 궁금하신 점이 있으시면 언제든 편하게 연락 주시기 바랍니다.',
          '고객님께 적합한 조건을 꼼꼼히 살펴 좋은 거래로 이어질 수 있도록 성심껏 도와드리겠습니다. 감사합니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't2',
      no: 2,
      stage: 1,
      order: 2,
      icon: 'clipboard',
      title: '매물 접수 확인',
      desc: '거래조건 · 입주 · 옵션',
      fields: [
        { t: 'property', id: 'prop', label: '매물', price: true },
        { t: 'date', id: 'movein', label: '입주일', mode3: true },
        { t: 'text', id: 'option', label: '옵션', ph: '예: 시스템에어컨, 올수리 등' }
      ],
      build: function (d, ctx) {
        var p = d.prop || {};
        var price = C.propPrice(p);
        var movein = C.dateFieldText(d, 'movein') || txt(null, '입주');
        return join([
          hello(ctx),
          '소중한 매물을 의뢰해 주셔서 진심으로 감사드립니다.\n접수해 주신 내용을 아래와 같이 안내드리오니 확인 부탁드립니다.',
          '- 매물 : ' + prop(p, d.mode) + '\n' +
          '- 거래조건 : ' + (price || '(금액)') + '\n' +
          '- 입주 : ' + movein + '\n' +
          '- 옵션 : ' + txt(d.option, '옵션'),
          '수정하거나 추가하실 내용이 있으시면 편하게 말씀해 주시기 바랍니다.\n단지 내 부동산으로서 좋은 거래로 이어질 수 있도록 꼼꼼히 진행하겠습니다. 감사합니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't16',
      no: 3,
      stage: 1,
      order: 3,
      icon: 'briefcase',
      title: '매도·임대 의뢰 제안',
      desc: '대기 고객 매칭 · 매물 확보',
      fields: [
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '전세', l: '전세' }, { v: '월세', l: '월세' }] }
      ],
      build: function (d, ctx) {
        var trade = tradeOf(d);
        var first = '안녕하세요, 마포래미안푸르지오 1단지 내 ' + ctx.office + '입니다. 😊';
        var body;
        if (trade === '매매') {
          body = [
            '현재 매수를 희망하시는 손님이 계셔서 연락드립니다.\n혹시 매도 계획이 있으시거나 고려 중이시라면 저희에게도 매물을 소개할 기회를 주실 수 있을지 여쭙습니다.',
            '단지 특성과 거래 상황을 살펴 손님께 성실히 안내하겠습니다.\n매도 의향이 있으시면 편하실 때 회신 부탁드립니다. 감사합니다.'
          ];
        } else {
          body = [
            '현재 ' + trade + '를 희망하시는 손님이 계셔서 연락드립니다.\n혹시 ' + trade + ' 임대 계획이 있으시거나 고려 중이시라면 저희에게도 매물을 소개할 기회를 주실 수 있을지 여쭙습니다.',
            '조건에 맞는 손님과 좋은 거래로 이어질 수 있도록 노력하겠습니다.\n임대 의향이 있으시면 편하실 때 회신 부탁드립니다. 감사합니다.'
          ];
        }
        return join([first].concat(body).concat([sign(ctx)]));
      }
    },
    {
      id: 't18',
      no: 4,
      stage: 1,
      order: 4,
      icon: 'send',
      title: '공동중개 매물 요청',
      desc: '고객 희망 조건 · 매물 확보',
      fields: [
        // 거래유형~입주일을 공통 금액박스 하나로 — [매매][전세][월세] + 금액 + 입주일
        { t: 'dealBox', id: 'deal', label: '조건', area: true, movein: true },
        { t: 'text', id: 'guestNote', label: '고객 특징', ph: '예: 염리초 보내고 싶은 학부모입니다' }
      ],
      build: function (d, ctx) {
        var trade = tradeOf(d);
        var depMan = C.parseMan(trade === '월세' ? d.deposit : d.amount);
        var rentMan = C.parseMan(d.rent);
        var amount = hint(depMan) || '(금액)';
        var area = String(d.area == null ? '' : d.area).trim().replace(/평$/, '');
        var movein = C.dateFieldText(d, 'movein') || txt(null, '입주');
        var note = txt(d.guestNote, '고객 특징');
        var intro, lines;
        if (trade === '월세') {
          intro = '월세 매물을 찾는 손님이 계셔서 문의드립니다.';
          lines = [
            '- 보증금 : ' + amount,
            '- 월세 : ' + (rentMan != null ? hint(rentMan) + ' 원' : '(금액)원') + '까지',
            '- 입주 : ' + movein,
            '- 고객 참고사항 : ' + note
          ];
        } else if (trade === '전세') {
          intro = '전세 매물을 찾는 손님이 계셔서 문의드립니다.';
          lines = [
            '- 전세 보증금 : ' + amount + '까지',
            '- 입주 : ' + movein,
            '- 고객 참고사항 : ' + note
          ];
        } else {
          intro = '매수 의사가 분명한 손님이 계셔서 조건에 맞는 매물 문의드립니다.';
          lines = ['- 매매 희망금액 : ' + amount + '까지'];
          if (area) lines.push('- 희망 평형 : ' + area + '평');
          lines.push('- 입주 : ' + movein);
          lines.push('- 고객 참고사항 : ' + note);
        }
        return join([
          '사장님, 안녕하세요. 😊',
          intro,
          lines.join('\n'),
          '보유 중이시거나 새로 접수되는 매물이 있으시면 소개 부탁드리겠습니다.\n바쁘신 중에도 확인해 주셔서 감사합니다, 사장님.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't19',
      no: 5,
      stage: 1,
      order: 5,
      icon: 'tag',
      title: '특가 매물 홍보',
      desc: '매물 정보 · 거래조건 · 강조 문구',
      fields: [
        { t: 'props', id: 'items', label: '매물', price: true },
        { t: 'text', id: 'emphasis', label: '강조 문구', ph: '예: 최저가 조율 가능합니다' }
      ],
      build: function (d, ctx) {
        var list = itemsOf(d, 'items', d.mode);
        var first = list[0] || {};
        var headTrade = first.trade === '전세' || first.trade === '월세' ? first.trade : '매매';
        var emph = String(d.emphasis == null ? '' : d.emphasis).trim() || '(강조 문구)';
        var blocks = [hello(ctx), '마포래미안푸르지오 ' + headTrade + ' 특가 매물 안내드립니다.'];
        // 매물마다 매물·거래조건·특징 세 줄
        if (list.length) {
          list.forEach(function (p) {
            var head = prop(p, d.mode);
            var price = C.propPrice(p);
            blocks.push('🔑 매물 : ' + head + '\n🔑 거래조건 : ' + (price || '(가격)') + '\n✔️ 특징 : ' + emph);
          });
        } else {
          blocks.push('🔑 매물 : (매물)\n🔑 거래조건 : (가격)\n✔️ 특징 : ' + emph);
        }
        blocks.push('관심 있으시거나 자세한 내용이 궁금하시면 편하게 연락 주시기 바랍니다.\n감사합니다. 좋은 하루 보내세요!');
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },

    /* ---------------- 방문·집보기 ---------------- */
    {
      // 소유자 집보기 문의 + 공동중개 집보기 문의 → 집보기 문의 (소유자/중개사 × 간단/상세)
      id: 't3',
      no: 6,
      stage: 2,
      order: 1,
      icon: 'home',
      title: '집보기 문의',
      desc: '소유자·중개사 / 간단·상세',
      fields: [
        { t: 'segs', id: 'ver', label: '버전', groups: [
          { id: 'who', options: [{ v: 'owner', l: '소유자' }, { v: 'coagent', l: '중개사' }] },
          { id: 'view', options: [{ v: 'simple', l: '간단' }, { v: 'detail', l: '상세' }] }
        ] },
        { t: 'property', id: 'prop', label: '매물', price: true },
        { t: 'times', id: 'times', label: '방문 희망 시간', showIf: function (d) { return d.view === 'detail'; } },
        { t: 'date', id: 'when', label: '방문 희망 시간', showIf: function (d) { return d.view !== 'detail'; } }
      ],
      build: function (d, ctx) {
        var p = d.prop || {};
        var trade = p.trade === '전세' || p.trade === '월세' ? p.trade : '매매';
        var guest = guestOf(trade);
        var co = d.who === 'coagent';
        var place = propWithPrice(p, d.mode);
        var first = co ? '사장님, 안녕하세요. 😊' : hello(ctx);
        if (d.view !== 'detail') {
          var when = visitLine(d.when) || '(방문 일시)';
          var simple = [
            first,
            guest + ' 손님이 계셔서 ' + (co ? '공동중개 및 ' : '') + '집보기 가능 여부' + (co ? ' 여쭙습니다.' : '를 여쭙습니다.'),
            '- 매물 : ' + place + '\n- 희망 일시 : ' + when,
            co
              ? '해당 시간에 집보기가 가능할지 확인 부탁드립니다.\n어려우시다면 가능하신 시간을 알려주시면 손님과 조율하겠습니다. 감사합니다.'
              : '해당 시간에 방문이 가능하실지 확인 부탁드립니다.\n어려우시다면 편하신 시간을 알려주시면 조율하겠습니다. 감사합니다.'
          ];
          simple.push(sign(ctx));
          return join(simple);
        }
        var lines = String(d.times || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
        var when2 = lines.length ? lines.join(' / ') : '(방문 희망 시간)';
        var blocks = [
          first,
          co
            ? guest + ' 손님이 계셔서 공동중개 및 집보기 일정을 문의드립니다.'
            : guest + ' 손님께서 집보기를 희망하셔서 방문 일정을 여쭙습니다.',
          '- 매물 : ' + place + '\n- 방문 희망 시간 : ' + when2
        ];
        blocks.push(co
          ? '번거로우시겠지만 위 시간 중 집보기가 가능할지 확인 부탁드립니다.\n어려우시다면 가능하신 시간을 알려주시면 손님과 조율하겠습니다.\n감사합니다, 사장님.'
          : '번거로우시겠지만 위 시간 중 가능한 시간이 있으실지 확인 부탁드립니다.\n어려우시다면 편하신 시간을 말씀해 주시면 최대한 맞춰 조율하겠습니다.\n바쁘신 중에 협조해 주셔서 감사합니다.');
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't5',
      no: 7,
      stage: 2,
      order: 2,
      icon: 'calendar-check',
      title: '집보기 일정 안내',
      desc: '예약 확정 / 조율 중',
      fields: [
        { t: 'seg', id: 'status', label: '예약 상태', options: [{ v: 'confirmed', l: '예약 확정' }, { v: 'pending', l: '조율 중' }] },
        { t: 'date', id: 'when', label: '방문 일시', showIf: function (d) { return d.status !== 'pending'; } },
        { t: 'toggle', id: 'detail', label: '매물 상세 포함', showIf: function (d) { return d.status !== 'pending'; } },
        { t: 'toggle', id: 'parking', label: '주차 안내 포함', showIf: function (d) { return d.status !== 'pending'; } },
        { t: 'props', id: 'items', label: '매물', price: true, showIf: function (d) { return d.status === 'pending' || d.detail; } }
      ],
      build: function (d, ctx) {
        var list = itemsOf(d, 'items', d.mode);
        if (d.status === 'pending') {
          var plines = list.length
            ? list.map(function (p) { return '- 매물 : ' + propWithPrice(p, d.mode); }).join('\n')
            : '- 매물 : (매물) / (가격)';
          return join([
            hello(ctx),
            '아래 매물의 집보기 일정을 현재 조율 중입니다.',
            plines,
            '방문 가능 여부가 확인되는 대로 다시 연락드리겠습니다.\n양해해 주셔서 감사합니다.',
            sign(ctx)
          ]);
        }
        var blocks = [
          hello(ctx),
          '요청하신 집보기 일정이 아래와 같이 확정되었습니다.',
          '- 방문 일시 : ' + dt(d.when, '방문 일시') +
            (d.detail
              ? '\n- 매물 : ' + (list.length
                ? list.map(function (p) { return propWithPrice(p, d.mode); }).join(' · ')
                : '(매물) / (가격)')
              : '')
        ];
        blocks.push(d.parking
          ? '주차가 필요하시면 미리 말씀해 주시기 바랍니다.\n약속된 일정에 뵙겠습니다. 감사합니다.'
          : '약속된 일정에 뵙겠습니다. 감사합니다.');
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't6',
      no: 8,
      stage: 2,
      order: 3,
      icon: 'car',
      title: '주차 안내',
      desc: '주차 장소 · 주소',
      fixed: true,
      fields: [],
      build: function (d, ctx) {
        return join([
          '🚘 주차 장소 안내드립니다.',
          '- 주차 장소 : 아현장로교회\n- 주소 : 서울 마포구 마포대로 197-1',
          '도착하신 후 연락 주시면 안내해 드리겠습니다.\n조심히 오시기 바랍니다. 감사합니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't7',
      no: 9,
      stage: 2,
      order: 4,
      icon: 'layers',
      title: '추천 매물 안내',
      desc: '집보기 후 추천 매물 · 거래조건',
      fields: [
        { t: 'props', id: 'items', label: '매물', price: true }
      ],
      build: function (d, ctx) {
        var list = itemsOf(d, 'items', d.mode);
        var lines = list.length
          ? list.map(function (p) { return '- 매물 : ' + propWithPrice(p, d.mode); }).join('\n')
          : '- 매물 : (매물) / (가격)';
        return join([
          hello(ctx),
          '오늘 함께 보신 매물 정보를 정리해 보내드립니다.',
          lines,
          '바쁘신 중에 시간 내어 집 보시느라 고생 많으셨습니다.\n내용 살펴보시고 궁금하신 점이나 의견이 있으시면 언제든 편하게 말씀해 주세요.\n거래조건 협의도 꼼꼼히 도와드리겠습니다. 감사합니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't17',
      no: 10,
      stage: 2,
      order: 5,
      icon: 'heart',
      title: '집보기 후 감사 인사',
      desc: '거주자 / 공동중개 / 고객',
      fields: [
        { t: 'seg', id: 'target', label: '대상', options: [
          { v: 'resident', l: '거주자' }, { v: 'coagent', l: '공동중개' }, { v: 'guest', l: '고객' }
        ] },
        { t: 'variant', id: 'variant', label: '문구' }
      ],
      build: function (d, ctx) {
        var target = VARIANTS[d.target] ? d.target : 'resident';
        var list = VARIANTS[target];
        var idx = variantIndex(d, target);
        var blocks = [list[idx % list.length]];
        var greet = greetingText(greetList(d));
        if (greet) blocks.push(greet);
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },

    /* ---------------- 약정·계약 ---------------- */
    {
      // 매매조건·약정 안내 → 계약 조건 안내 (매매 약정 / 매매 계약 / 전세 계약 / 월세 계약)
      id: 't8',
      no: 11,
      stage: 3,
      order: 1,
      icon: 'calendar',
      title: '계약 조건 안내',
      desc: '매매 가계약·계약 / 전세·월세 계약',
      fields: [
        { t: 'segs', id: 'deal', label: '거래 유형', deal: true, groups: [
          { id: 'trade', options: [{ v: '매매', l: '매매' }, { v: '전세', l: '전세' }, { v: '월세', l: '월세' }] },
          { id: 'kind', options: [{ v: '가계약', l: '가계약' }, { v: '계약', l: '계약' }] }
        ] },
        // 기준 금액 — 매매는 매매가, 전세·월세는 보증금(월세는 월차임까지)
        { t: 'price', id: 'price', label: '금액' },
        { t: 'account', id: 'account', label: '입금계좌', ph: '예: 국민 123456-01-234567 홍길동' },
        { t: 'property', id: 'prop', label: '물건지', address: true },
        // 공통 지급 일정 — 약정금 → 가계약금 → 계약금 → 중도금 → 잔금 (차수별 추가·제거)
        { t: 'paytable', id: 'pay', sum: true, items: payItems('Amount') },
        { t: 'group', label: '특약' },
        { t: 'toggle', id: 'permit', label: '토지거래허가구역 (특약 자동 포함)', showIf: function (d) { return isSaleAgreement(d); } },
        { t: 'toggle', id: 'mortgage', label: '근저당 말소 특약 포함' },
        // 채권자 · 채권최고액은 한 줄 반반
        { t: 'moneyPair', id: 'mortgageInfo', showIf: function (d) { return d.mortgage; },
          left: { t: 'text', id: 'mortgageHolder', label: '채권자', ph: '예: 주식회사 카카오뱅크' },
          right: { t: 'money', id: 'mortgageAmount', label: '채권최고액' } }
      ],
      build: function (d, ctx) {
        var trade = tradeOf(d);
        var kind = dealKind(d);                     // 가계약 / 계약
        var place = [String(d.address || '').trim(), prop(d.prop, d.mode) === '(매물)' ? '' : prop(d.prop, d.mode)]
          .filter(Boolean).join(' ');
        var items = payItems('Amount');
        var yakjeong = payItemOf(items, 'yakjeong');
        var jeong = payItemOf(items, 'jeong');
        var gyeyak = payItemOf(items, 'gyeyak');
        var jung = payItemOf(items, 'jung');
        var jan = payItemOf(items, 'jan');
        var yakSum = payItemSum(d, yakjeong);
        var jeongSum = payItemSum(d, jeong);
        var gySum = payItemSum(d, gyeyak);
        var baseMan = payScheduleBase(null, d);
        var totalMan = payScheduleMan(null, d, items);
        var dealMan = baseMan != null ? baseMan : totalMan;
        var askAmt = amt(payDepositMan(null, d, items, kind), ctx);
        var mAmt = amt(C.parseMan(d.mortgageAmount), ctx) || '(채권최고액)';
        var holder = String(d.mortgageHolder || '').trim();
        var party = trade === '매매' ? '매도인' : '임대인';
        var basics = '- 물건지 : ' + (place || '(물건지)') +
          '\n- 입금계좌 : ' + (C.accountParse(d.account) || '(계좌번호)');

        // ■ 계약금액 및 지급 일정 — 약정금 → 가계약금 → 계약금 → 중도금 → 잔금
        var money = [];
        if (trade === '매매') {
          money.push('- 매매대금 : ' + (amt(dealMan, ctx) || '(금액)'));
        } else {
          var depAmt = baseMan != null ? amt(baseMan, ctx) : '';
          money.push('- 보증금 : ' + (depAmt || '(보증금)'));
          if (trade === '월세') money.push('- 월차임 : ' + (amt(C.parseMan(d.rent), ctx) || '(월차임)'));
        }
        money = money
          .concat(payLines(null, d, items, yakjeong, ctx))
          .concat(payLines(null, d, items, jeong, ctx, { force: kind === '가계약' }))
          .concat(payLines(null, d, items, gyeyak, ctx, { force: true }))
          .concat(payLines(null, d, items, jung, ctx))
          .concat(payLines(null, d, items, jan, ctx, { force: true }));
        var moneyBlock = '■ 계약금액 및 지급 일정\n' + money.join('\n');

        if (trade === '매매') {
          var blocks = [
            helloPlain(ctx),
            '아래 부동산의 ' + (kind === '가계약' ? '매매 가계약' : '매매계약') +
              ' 주요 내용을 안내드립니다.\n협의된 내용과 일치하는지 확인하시고, 동의 여부를 회신해 주시기 바랍니다.',
            basics,
            moneyBlock
          ];
          if (kind === '가계약' && d.permit) {
            blocks.push('계약금 지급 일정은 토지거래허가 진행 상황에 따라 쌍방이 협의하여 조정할 수 있습니다.');
          }
          if (yakSum != null) {
            blocks.push('기지급한 약정금 ' + won(yakSum) + '은 계약일에 전액 반환받고, 계약금 ' +
              wonOr(gySum, '(계약금)') + '은 약정금을 차감하지 않고 전액 입금합니다.');
          }
          if (jeongSum != null) {
            var gyLeft = (gySum != null ? gySum : 0) - jeongSum;
            blocks.push('기지급한 가계약금 ' + won(jeongSum) + '은 계약금에 포함하며, 계약일에는 계약금 총액 ' +
              wonOr(gySum, '(계약금)') + ' 중 차액 ' + wonOr(gyLeft, '(차액)') + '을 지급합니다.');
          }
          if (kind === '가계약') {
            var jd = C.formatDateTime(payPartDate(d, jeong, 0));
            blocks.push((jd ? jd + '에 ' : '') + '가계약금 ' + (askAmt || '(금액)') +
              '을 지급하며, 계약 성립 및 효력은 당사자가 합의한 내용에 따릅니다.');
          } else {
            blocks.push('잔금일에 잔금 지급과 소유권이전등기 절차를 진행하며, 매도인은 이에 필요한 사항에 협조합니다.');
          }
          // ■ 특약사항 — 토지거래허가(가계약) · 계약 해제(계약) · 공통
          var clauses = [];
          var n = 0;
          if (kind === '가계약' && d.permit) {
            clauses.push(++n + '. 본 부동산은 토지거래허가구역에 소재하므로 매도인과 매수인은 허가 신청에 필요한 서류 제출 등 관련 절차에 협조하기로 합니다.');
            clauses.push(++n + '. 쌍방의 귀책사유 없이 허가를 받지 못하는 경우 계약은 효력이 없는 것으로 확정되며, 기지급한 가계약금은 반환합니다. 일방의 귀책사유로 허가를 받지 못한 경우의 책임은 별도로 합의한 위약금 및 손해배상 약정에 따릅니다.');
            clauses.push(++n + '. 토지거래허가일로부터 5일 이내에 본계약서를 작성하기로 합니다.');
            clauses.push(++n + '. 가계약 성립 후 정당한 사유 없이 본계약 체결을 거부하거나 일방적으로 철회하는 경우, 매수인 귀책 시 가계약금을 포기하고 매도인 귀책 시 가계약금의 배액을 반환하기로 합니다. 중개보수는 관계 법령 및 약정에 따라 정산합니다.');
          }
          if (kind === '계약') {
            clauses.push(++n + '. 계약 해제 시 계약금의 귀속 및 배액배상 등은 당사자 간 약정과 관계 법령에 따릅니다.');
          }
          if (d.mortgage) {
            clauses.push('- 등기사항전부증명서상 ' + (holder || '(채권자)') + '를 채권자로 하는 채권최고액 ' + mAmt +
              '의 근저당권 1건이 설정된 상태이며, 매도인은 잔금일까지 해당 채무를 상환하고 근저당권을 말소합니다. 말소비용은 매도인이 부담합니다.');
          }
          clauses.push('- 매도인은 잔금일까지 매수인의 권리 취득에 지장을 줄 수 있는 새로운 권리변동을 발생시키지 않기로 합니다.');
          clauses.push('- 명시되지 않은 사항은 민법 등 관계 법령 및 일반적인 거래 관례에 따릅니다.');
          blocks.push('■ 특약사항\n' + clauses.join('\n'));
          blocks.push(kind === '가계약'
            ? '위 내용에 동의하시는 경우 매도인께서는 입금계좌를 회신해 주시기 바랍니다.\n확인 후 진행하겠습니다. 감사합니다.'
            : '위 내용 확인 후 동의 여부를 회신해 주시면 감사하겠습니다.\n추가로 협의하실 사항이 있으시면 말씀해 주시기 바랍니다.');
          blocks.push(sign(ctx));
          return join(blocks);
        }

        // 전세 · 월세 — 같은 계약금액·지급 일정 포맷, 특약은 임대차 기준
        var rentBlocks = [
          helloPlain(ctx),
          '아래 부동산의 ' + trade + (kind === '가계약' ? ' 가계약' : ' 계약') +
            ' 주요 내용을 안내드립니다.\n협의된 내용과 일치하는지 확인하시고, 동의 여부를 회신해 주시기 바랍니다.',
          basics,
          moneyBlock
        ];
        var rclauses = [];
        if (d.mortgage) {
          rclauses.push('- 등기사항전부증명서상 ' + (holder || '(채권자)') + '를 채권자로 하는 채권최고액 ' + mAmt +
            '의 근저당권 1건이 설정된 상태이며, 임대인은 잔금일까지 해당 채무를 상환하고 근저당권을 말소합니다. 말소비용은 임대인이 부담합니다.');
        }
        rclauses.push('- 임대인은 잔금일까지 임차인의 권리 보호에 지장을 줄 수 있는 새로운 근저당권 설정, 가압류 등의 권리변동을 발생시키지 않기로 합니다.');
        rclauses.push('- 임대인은 임차인이 주택을 인도받은 후 전입신고 및 확정일자 부여 절차를 진행할 수 있도록 협조합니다.');
        rclauses.push('- 명시되지 않은 사항은 주택임대차보호법 및 민법 등 관계 법령에 따릅니다.');
        rentBlocks.push('■ 특약사항\n' + rclauses.join('\n'));
        rentBlocks.push(kind === '가계약'
          ? '위 내용에 동의하시는 경우 임대인께서는 입금계좌를 회신해 주시기 바랍니다.\n확인 후 진행하겠습니다. 감사합니다.'
          : '위 내용 확인 후 동의 여부를 회신해 주시면 감사하겠습니다.\n추가로 협의하실 사항이 있으시면 말씀해 주시기 바랍니다.');
        rentBlocks.push(sign(ctx));
        return join(rentBlocks);
      }
    },
    {
      // 약정 일정 안내 · 계약 일정 안내 · 중도금·잔금 일정 안내 → 계약 일정 안내 하나로
      id: 't10',
      no: 12,
      stage: 3,
      order: 2,
      icon: 'calendar',
      title: '계약 일정 안내',
      desc: '가계약 · 계약 · 중도금 · 잔금',
      fields: [
        // 일정을 맨 위로 — 거래 유형은 아래 매물칸의 [매매][전세][월세]로 고른다
        { t: 'seg', id: 'kind', label: '일정', grid: 4, optionsFn: schedKinds },
        { t: 'property', id: 'prop', label: '매물', price: true },
        { t: 'date', id: 'when', label: '일시' },
        { t: 'toggle', id: 'jeongyakReturn', label: '가계약금 반환 안내 포함', showIf: function (d) { return !isRentTrade(d) && schedKind(d) === '계약'; } },
        { t: 'toggle', id: 'priority', label: '선순위 권리내역 안내 포함', showIf: function (d) { return isRentTrade(d) && schedKind(d) === '계약'; } },
        { t: 'toggle', id: 'registry', label: '당일 등기부 확인 안내 포함', showIf: function (d) { return isRentTrade(d) && schedKind(d) !== '계약'; } },
        { t: 'toggle', id: 'docs', label: '잔금 구비서류 포함', showIf: function (d) { return !isRentTrade(d) && schedKind(d) === '잔금'; } },
        // 공통 지급 일정 — 약정금 → 가계약금 → 계약금 → 중도금 → 잔금 (차수별 추가·제거)
        { t: 'paytable', id: 'pay', sum: true, showIf: function (d) { return schedKind(d) !== '가계약'; }, items: payItems('') },
        { t: 'account', id: 'account', label: '입금 계좌', ph: '예: 국민은행 123456-01-234567 홍길동', showIf: function (d) { var k = schedKind(d); return k !== '가계약' && k !== '계약'; } }
      ],
      build: function (d, ctx) {
        var place = prop(d.prop, d.mode);
        var kind = schedKind(d);
        var when = C.formatDateTime(d.when) || String(d.whenText || '').trim();
        var tail = '준비사항 확인 부탁드리며, 궁금하신 점은 편하게 연락 주시기 바랍니다. 감사합니다.';
        if (kind === '가계약') {
          return join([
            helloPlain(ctx),
            place + ' 가계약서 작성 일정과 준비사항을 안내드립니다.',
            '- 일시 : ' + (when || '(가계약 일시)'),
            '■ 매도인 준비사항\n1. 신분증\n2. 도장\n3. 주민등록등본 (세대원 전원의 주민등록번호 전체 공개)',
            '■ 매수인 준비사항\n1. 신분증\n2. 도장\n3. 주민등록등본 (세대원 전원의 주민등록번호 전체 공개)\n4. 가족관계증명서 (상세)\n5. 가계약금',
            '※ 가계약금 이체에 차질이 없도록 OTP와 1일 이체한도를 미리 확인해 주시기 바랍니다.\n※ 공동명의 취득 시 각 명의자별 준비서류를 지참해 주시기 바랍니다.',
            tail,
            sign(ctx)
          ]);
        }
        if (kind === '계약') {
          if (isRentTrade(d)) {
            var seller = '■ 임대인 준비사항\n1. 확정일자 부여현황 (주민센터)\n2. 전입세대 확인서 (주민센터, 신분증 및 관련 서류 지참)\n3. 국세 납세증명서 (정부24·홈택스·세무서 등)\n4. 지방세 납세증명서 (정부24·주민센터 등)\n5. 관리비 세부 내역 (관리사무소)\n6. 신분증\n7. 도장 (서명 가능)';
            var blocks = [
              helloPlain(ctx),
              place + ' 임대차계약 일정과 준비사항을 안내드립니다.',
              '- 일시 : ' + (when || '(계약 일시)'),
              seller
            ];
            if (d.priority) {
              blocks.push('기존 임대차계약서 등 선순위 임차인의 보증금과 임대차 기간을 확인할 수 있는 자료도 준비 부탁드립니다.');
            }
            blocks.push('■ 임차인 준비사항\n1. 신분증\n2. 도장 (서명 가능)\n3. 계약금');
            blocks.push('※ 계약금 이체에 차질이 없도록 방문 전 OTP와 1일 이체한도를 확인해 주시기 바랍니다.');
            blocks.push(tail);
            blocks.push(sign(ctx));
            return join(blocks);
          }
          var sellerSale = '■ 매도인 준비사항\n1. 신분증\n2. 도장 (서명 가능)\n3. 등기권리증' +
            (d.jeongyakReturn ? '\n4. 가계약금 반환 준비' : '');
          return join([
            helloPlain(ctx),
            place + ' 매매계약 일정과 준비사항을 안내드립니다.',
            '- 일시 : ' + (when || '(계약 일시)'),
            sellerSale,
            '■ 매수인 준비사항\n1. 신분증\n2. 도장 (서명 가능)\n3. 계약금',
            '※ 이체에 차질이 없도록 방문 전 OTP와 1일 이체한도를 확인해 주시기 바랍니다.',
            tail,
            sign(ctx)
          ]);
        }
        // 중도금 · 잔금 — 일정과 입금 내역
        var rentTrade = isRentTrade(d);
        var blocks2 = [
          helloPlain(ctx),
          place + ' ' + kind + ' 일정 및 입금 내역을 안내드립니다.',
          '- 일시 : ' + (when || '(입금 일시)')
        ];
        if (rentTrade && d.registry) {
          blocks2.push('당일 입금 전 등기사항전부증명서를 다시 발급하여 새로운 권리변동이 있는지 확인 후 안내드리겠습니다.');
        }
        var rows = [];
        var items10 = payItems('');
        if (rentTrade) {
          // 금액은 매물칸에서 — 매매·전세는 amount, 월세는 보증금(deposit)·월차임(rent)
          var pp = (d.prop && typeof d.prop === 'object') ? d.prop : {};
          var depMan10 = C.parseMan(pp.trade === '월세' ? pp.deposit : pp.amount);
          var dep = amt(depMan10, ctx);
          var rentAmt2 = pp.trade === '월세' ? amt(C.parseMan(pp.rent), ctx) : '';
          var totalMan2 = payScheduleMan('t10', d, items10);
          if (!dep && totalMan2) dep = amt(totalMan2, ctx);
          rows.push('- 보증금 : ' + (dep || '(보증금)'));
          if (pp.trade === '월세') rows.push('- 월차임 : ' + (rentAmt2 || '(월차임)'));
        }
        // 약정금 → 가계약금 → 계약금 → 중도금 → 잔금 (차수가 여럿이면 1차·2차로)
        items10.forEach(function (item) {
          // 12번은 요율 없이 항목명만 — 2차 수정본의 금액 세부사항 모양
          rows = rows.concat(payLines('t10', d, items10, item, ctx,
            { date: false, rate: false, force: item.key === 'gyeyak' || item.key === 'jan' }));
        });
        var sumMan = payScheduleMan('t10', d, items10);
        if (sumMan) rows.push('- 합계 : ' + amt(sumMan, ctx));
        blocks2.push('■ 금액 세부사항\n' + rows.join('\n'));
        blocks2.push('- 입금계좌 : ' + (C.accountParse(d.account) || '(계좌번호)'));
        if (!rentTrade && kind === '잔금' && d.docs) {
          blocks2.push('■ 매도인 준비사항\n1. 인감도장, 신분증\n2. 부동산 매도용 인감증명서 1통 (매수인 인적사항 기재)\n3. 등기권리증\n4. 주민등록초본 1통 (전체 주소변동 이력 포함)\n5. 관리비·가스요금 정산 내역\n6. 리모컨, 카드키 등 인도할 물품');
          blocks2.push('■ 매수인 준비사항\n1. 도장\n2. 매매계약서 원본\n3. 가족관계증명서 (상세, 각 매수인 기준)\n4. 주민등록등본 1통 (세대원 전원 주민등록번호 뒷자리 공개)\n5. 취득세 및 소유권이전등기 관련 비용');
          blocks2.push('※ 잔금 이체한도와 자금 준비 상황을 사전에 확인해 주시기 바랍니다.\n※ 등기 구비서류는 거래 방식에 따라 달라질 수 있으므로 최종 안내를 확인해 주시기 바랍니다.');
        }
        blocks2.push('원활한 진행을 위해 협조 부탁드리며, 궁금하신 사항은 언제든 연락 주시기 바랍니다. 감사합니다.');
        blocks2.push(sign(ctx));
        return join(blocks2);
      }
    },
    {
      id: 't11',
      no: 13,
      stage: 3,
      order: 3,
      icon: 'pen',
      title: '전자계약 안내',
      desc: '계약 절차 · 전자서명',
      fixed: true,
      fields: [
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '임대차', l: '임대차' }] }
      ],
      build: function (d, ctx) {
        var sale = d.trade !== '임대차';
        var parties = sale ? '매도인·매수인' : '임대인·임차인';
        var doc = sale ? '매매계약서' : '임대차계약서';
        return join([
          helloPlain(ctx),
          '전자계약 진행 절차를 안내드립니다.',
          '1. ' + ctx.office + '에서 협의된 내용으로 계약서를 작성합니다.\n' +
          '2. ' + parties + '에게 문자 또는 카카오톡으로 안내가 발송됩니다.\n' +
          '3. 안내에 따라 본인인증 후 ' + doc + '를 확인하고 전자서명해 주시기 바랍니다. 신분증 촬영 등 추가 절차는 시스템 안내를 따라주시면 됩니다.\n' +
          '4. 계약 당사자 서명 후 저희가 최종 확인 및 전자서명을 진행합니다.\n' +
          '5. 해당 거래의 신고 또는 확정일자 신청 등 연계 절차가 시스템을 통해 진행되며, 실제 접수·처리 상태를 별도로 확인합니다.\n' +
          '6. 계약 완료 후 계약서를 온라인으로 열람하거나 출력하실 수 있습니다.',
          '진행 중 어려운 점이 있으시면 연락 주시기 바랍니다. 감사합니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't12',
      no: 14,
      stage: 3,
      order: 4,
      icon: 'file-text',
      title: '자금조달계획서 안내',
      desc: '제출 절차 · 증빙서류',
      fixed: true,
      fields: [
        { t: 'seg', id: 'owner', label: '명의', options: [{ v: '공동', l: '공동명의' }, { v: '단독', l: '단독명의' }] }
      ],
      build: function (d, ctx) {
        var joint = d.owner !== '단독';
        var body = joint
          ? '공동명의인 경우 명의자별로 각각 작성하시고, 두 분의 자금조달 금액 합계가 매매대금과 일치하는지 확인 부탁드립니다.'
          : '자금조달 항목별 금액과 출처를 작성하시고, 합계가 매매대금과 일치하는지 확인 부탁드립니다.';
        var closing = joint
          ? '두 분 모두 제출하신 후 완료 여부를 알려주시면 감사하겠습니다.'
          : '제출하신 후 완료 여부를 알려주시면 감사하겠습니다.';
        return join([
          helloPlain(ctx),
          '주택취득자금 조달 및 입주계획서 제출에 관해 안내드립니다.\n자금조달계획서 제출 대상인 경우 전자계약과 별도로 작성·제출해야 하므로, 제출 기한과 준비서류를 확인해 주시기 바랍니다.',
          body,
          '■ 온라인 제출 절차\n부동산거래관리시스템 접속 및 본인인증 → 해당 계약 확인 → 자금조달 및 입주계획 입력 → 해당 증빙자료 첨부 → 접수 여부 확인',
          '■ 주요 증빙자료 예시\n' + [
            '- 예금·적금 : 예금잔액증명서 등',
            '- 주식 매도대금 : 주식거래내역서 등',
            '- 기존 주택 매도대금 : 매매계약서 등',
            '- 전세보증금 반환금 : 기존 임대차계약서 등',
            '- 금융기관 대출 : 금융거래확인서·대출 관련 서류 등',
            '- 증여·상속 : 관련 신고서 등',
            '- 가족 등으로부터 차입 : 차용증 등'
          ].join('\n'),
          '※ 실제 제출 대상, 기한, 증빙서류는 거래 및 자금조달 방식에 따라 확인이 필요합니다.',
          closing,
          '진행 중 궁금하신 점이 있으시면 편하게 연락 주시기 바랍니다.',
          sign(ctx)
        ]);
      }
    },

    /* ---------------- 잔금·만기 ---------------- */
    {
      id: 't20',
      no: 15,
      stage: 4,
      order: 1,
      icon: 'phone',
      title: '전문가·협력업체 소개',
      desc: '대출 · 세무 · 법무 · 입주 서비스',
      fields: [
        { t: 'seg', id: 'vendorCat', label: '분야', row5: true, options: VENDOR_CATS.map(function (c) { return { v: c, l: c }; }) },
        { t: 'contacts', id: 'vendorContacts', label: '연락처' }
      ],
      build: function (d, ctx) {
        var cat = VENDOR_CATS.indexOf(d.vendorCat) !== -1 ? d.vendorCat : '대출';
        var intro = VENDOR_INTRO[cat];
        var blocks = [
          hello(ctx),
          intro,
          contactBlock(cat, contactsFor(ctx, cat), selectedFor(d, cat)),
          '마래푸중앙부동산 소개로 연락하셨다고 말씀해 주시면 됩니다. 감사합니다.'
        ];
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't14',
      no: 16,
      stage: 4,
      order: 2,
      icon: 'calculator',
      title: '중개보수 안내',
      desc: '보수 계산 · 입금 정보',
      fields: [
        { t: 'calc', id: 'calc' }
      ],
      build: function (d, ctx) {
        var r = C.feeCalc({
          kind: d.calcKind || 'house',
          trade: d.calcTrade || '매매',
          officetelUse: d.calcOffice || 'resident',
          amountMan: C.parseMan(d.calcAmount),
          depositMan: C.parseMan(d.calcDeposit),
          rentMan: C.parseMan(d.calcRent),
          ratePct: d.calcRate,
          vat: d.calcVat || '4'
        });
        var kindLabel = C.FEE_KINDS[d.calcKind || 'house'] || '주택';
        var useLabel = r.ok && r.kind === 'officetel'
          ? (r.officetelUse === 'business' ? ' · 85㎡ 초과·업무용' : ' · 85㎡ 이하 주거용')
          : '';
        var depositMan = C.parseMan(d.calcDeposit);
        var rentMan = C.parseMan(d.calcRent);
        var amountLine = '';
        if (r.ok && r.converted) {
          amountLine = '- 거래금액 : 보증금 ' + C.formatWonPlain((depositMan || 0) * 10000) +
            ' / 월차임 ' + C.formatWonPlain((rentMan || 0) * 10000) + ' (환산 ' + C.formatWonPlain(r.amountWon) + ')';
        } else if (r.ok) {
          amountLine = '- 거래금액 : ' + C.formatWonPlain(r.amountWon);
        }
        // 중개보수 합계에 직접 적은 금액이 있으면 그 금액으로 나간다 (적용 요율은 법정 요율 그대로)
        var customWon = C.wonOrNull(d.calcTotalWon);
        var money = C.feeBreakdown(r, customWon);
        var moneyLines = r.ok ? [
          '- 거래 유형 : ' + kindLabel + useLabel + ' · ' + r.trade,
          amountLine,
          '- 적용 요율 : ' + C.rateLabel(r.ratePct) + '%',
          '- 중개보수 (공급가액) : ' + C.formatWonPlain(money.supply),
          money.vatMode === 'none'
            ? '- 부가가치세 : 별도'
            : '- 부가가치세 : ' + C.formatWonPlain(money.vat) + ' (' + (money.vatMode === '4' ? '간이과세 4%' : '일반과세 10%') + ')',
          '- 합계 : ' + C.formatWonPlain(money.total) + (money.vatMode === 'none' ? ' (부가세 별도)' : '')
        ].concat(r.capped && !money.custom ? ['- 한도액 ' + C.formatWonPlain(r.capWon) + ' 적용'] : []).join('\n') : [
          '- 거래 유형 : ' + kindLabel + ' · ' + (d.calcTrade || '매매'),
          '- 거래금액 : (금액)',
          '- 적용 요율 : (요율)%',
          '- 중개보수 (공급가액) : (중개보수)',
          '- 부가가치세 : (부가세)',
          '- 합계 : (중개보수)'
        ].join('\n');
        var overLine = r.ok && r.rateOver
          ? '요청하신 ' + C.rateLabel(r.requestedPct) + '%는 상한요율 ' + C.rateLabel(r.capRatePct) +
            '%를 넘어 상한요율로 계산했습니다.'
          : '';
        return join([
          helloPlain(ctx),
          '이번 거래의 중개보수 내역을 안내드립니다.',
          moneyLines,
          overLine,
          '- 입금계좌 : ' + (ctx.feeAccount || '(입금 계좌)'),
          '내역 확인 후 입금해 주시면 감사하겠습니다.\n현금영수증 발급에 사용하실 휴대전화번호 또는 사업자등록번호를 알려주시면 발급 처리하겠습니다.',
          '믿고 맡겨주셔서 진심으로 감사드립니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't15',
      no: 17,
      stage: 4,
      order: 3,
      icon: 'key',
      title: '임대차 만기 확인',
      desc: '만기 일정 · 연장·퇴거 의사',
      fields: [
        { t: 'roleMonths', id: 'months', label: '상대방 · 남은 기간' }
      ],
      build: function (d, ctx) {
        var role = d.role === '임차인' ? '임차인' : '임대인';
        // 임대인에게 보내면 '임차인분과는', 임차인에게 보내면 '임대인분과는'
        var other = role === '임대인' ? '임차인' : '임대인';
        var months = String(d.months == null || d.months === '' ? '' : d.months).trim() || '(N)';
        return join([
          hello(ctx),
          '그동안 안녕히 잘 지내셨는지요?\n임대차계약 만기까지 약 ' + months + '개월 남아 있어 안부 겸 연락드립니다.',
          '만기 이후 계약 연장이나 퇴거 계획이 있으실지, ' + other + '분과 미리 협의하신 내용이 있으실지 여쭙습니다.',
          '- 퇴거 예정이시면 일정과 필요한 사항을 확인해 원활히 진행될 수 있도록 돕겠습니다.\n- 연장 예정이시면 조건 협의와 연장계약서 작성을 안내해 드리겠습니다.',
          '아직 정해지지 않으셨다면 충분히 검토하신 후 편하실 때 말씀해 주세요.\n언제든 연락 주시거나 마포래미안푸르지오 단지 내 상가로 들러주셔도 좋습니다. 감사합니다.',
          sign(ctx)
        ]);
      }
    }
  ];

  /* ---------------- 거래 유형 · 일정 도우미 ---------------- */
  // 가계약(예전 이름 약정) · 계약 — 전세·월세도 둘 다 고를 수 있다
  function dealKind(d) {
    if (isRentTrade(d)) return d && d.kind === '가계약' ? '가계약' : '계약';
    return d && d.kind === '계약' ? '계약' : '가계약';
  }
  function isSaleAgreement(d) { return !isRentTrade(d) && dealKind(d) === '가계약'; }
  function isSaleContract(d) { return !isRentTrade(d) && dealKind(d) === '계약'; }
  function schedKinds(d) {
    if (isRentTrade(d)) {
      return [{ v: '계약', l: '계약' }, { v: '중도금', l: '중도금' }, { v: '잔금', l: '잔금' }];
    }
    return [{ v: '가계약', l: '가계약' }, { v: '계약', l: '계약' }, { v: '중도금', l: '중도금' }, { v: '잔금', l: '잔금' }];
  }
  function schedKind(d) {
    var list = schedKinds(d);
    var pick = d && d.kind;
    var hit = list.filter(function (o) { return o.v === pick; })[0];
    return hit ? hit.v : '계약';
  }

  var STAGES = [
    { v: 'all', l: '전체' },
    { v: '1', l: '접수·홍보' },
    { v: '2', l: '방문·집보기' },
    { v: '3', l: '약정·계약' },
    { v: '4', l: '잔금·만기' }
  ];

  // 화면 표시 순서 = 카테고리(stage) → 카테고리 안 순서(order)
  TEMPLATES.sort(function (a, b) {
    if (a.stage !== b.stage) return a.stage - b.stage;
    return (a.order || 0) - (b.order || 0);
  });

  // 감사 인사 문구 순번 (대상별로 따로 기억)
  function variantIndex(data, target) {
    var vp = (data && data.vpick) || {};
    var n = Number(vp[target]);
    return isNaN(n) || n < 0 ? 0 : Math.floor(n);
  }

  // "404동 1903호" → "4단지 19층"
  function spotFromUnit(unit) {
    var s = String(unit == null ? '' : unit).trim();
    if (!s) return '';
    var dm = /(\d+)\s*동/.exec(s);
    var hm = /(\d{3,4})\s*호/.exec(s);
    if (!dm && !hm) {
      var nums = s.match(/\d{3,4}/g) || [];
      if (nums.length >= 2) { dm = [null, nums[0]]; hm = [null, nums[1]]; }
      else if (nums.length === 1) hm = [null, nums[0]];
    }
    var parts = [];
    if (dm) parts.push(Math.floor(parseInt(dm[1], 10) / 100) + '단지');
    if (hm) parts.push(Math.floor(parseInt(hm[1], 10) / 100) + '층');
    return parts.join(' ');
  }

  // 템플릿별 초기값 (complex는 실제 단지명을 기본값으로)
  function defaultProp() {
    return { complex: '마포래미안푸르지오', dong: '', ho: '', trade: '매매', amount: '', deposit: '', rent: '', price: '' };
  }

  var DEFAULT_SEL = { '대출': [], '세무사': [], '법무사': [], '인테리어': [], '입주청소': [], '이사': [] };

  function defaultVendorSel() {
    return JSON.parse(JSON.stringify(DEFAULT_SEL));
  }

  // 저장된 연락처가 없을 때 처음 넣어 둘 값
  function defaultContacts() {
    return JSON.parse(JSON.stringify(DEFAULT_CONTACTS));
  }

  function emptyMovein(d) {
    d.movein = { date: '', hour: null, min: 0 };
    d.moveinText = '';
    d.moveinMode = '고정';
    d.moveinFix = '고정';
    d.moveinStart = { date: '', hour: null, min: 0 };
    d.moveinEnd = { date: '', hour: null, min: 0 };
  }

  function defaultData(t) {
    var d = { mode: 'ho' };
    if (t.id === 't2' || t.id === 't10' || t.id === 't8') d.prop = defaultProp();
    if (t.id === 't5' || t.id === 't7' || t.id === 't19') d.items = [defaultProp()];
    if (t.id === 't5') { d.status = 'confirmed'; d.detail = true; d.parking = true; }
    if (t.id === 't2') emptyMovein(d);
    if (t.id === 't3') { d.who = 'owner'; d.view = 'simple'; d.times = ''; d.prop = defaultProp(); }
    if (t.id === 't10') { d.trade = '매매'; d.kind = '계약'; }
    if (t.id === 't8') { d.trade = '매매'; d.kind = '가계약'; d.address = '서울시 마포구 아현동 777 외 3필지'; }
    if (t.id === 't11') d.trade = '매매';
    if (t.id === 't12') d.owner = '공동';
    if (t.id === 't15') { d.role = '임대인'; d.months = 2; }
    if (t.id === 't14') { d.calcKind = 'house'; d.calcTrade = '매매'; d.calcVat = '4'; d.calcTotal = ''; }
    if (t.id === 't16') { d.trade = '매매'; }
    if (t.id === 't17') { d.target = 'resident'; d.vpick = { resident: 0, coagent: 0, guest: 0 }; d.greets = []; }
    if (t.id === 't18') { d.trade = '매매'; emptyMovein(d); d.guestNote = '염리초 보내고 싶은 학부모입니다'; }
    if (t.id === 't19') { d.emphasis = '최저가 조율 가능합니다'; }
    if (t.id === 't20') { d.vendorCat = '대출'; d.vendorSel = defaultVendorSel(); }
    return d;
  }

  global.SMSTemplates = {
    TEMPLATES: TEMPLATES,
    STAGES: STAGES,
    defaultData: defaultData,
    defaultProp: defaultProp,
    VARIANTS: VARIANTS,
    GREETINGS: GREETINGS,
    GREET_KEYS: GREET_KEYS,
    greetList: greetList,
    greetingText: greetingText,
    variantIndex: variantIndex,
    spotFromUnit: spotFromUnit,
    VENDOR_CATS: VENDOR_CATS,
    VENDOR_INTRO: VENDOR_INTRO,
    DEFAULT_CONTACTS: DEFAULT_CONTACTS,
    defaultContacts: defaultContacts,
    defaultVendorSel: defaultVendorSel,
    selectedFor: selectedFor,
    contactsFor: contactsFor,
    contactBlock: contactBlock,
    dealKind: dealKind,
    schedKinds: schedKinds,
    schedKind: schedKind,
    isRentTrade: isRentTrade,
    tradeOf: tradeOf,
    // 공통 지급 일정 (약정금·가계약금·계약금·중도금·잔금)
    payItems: payItems,
    payItemOf: payItemOf,
    payPartCount: payPartCount,
    payPartAmount: payPartAmount,
    payPartDate: payPartDate,
    payItemSum: payItemSum,
    payScheduleBase: payScheduleBase,
    payJanTotal: payJanTotal,
    payPartValue: payPartValue,
    payScheduleMan: payScheduleMan,
    payDepositMan: payDepositMan,
    payLines: payLines
  };
})(typeof window !== 'undefined' ? window : globalThis);
