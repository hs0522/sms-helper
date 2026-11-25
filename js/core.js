/* 마래푸중앙부동산 문자 도우미 — 순수 계산/포맷 로직
 * 브라우저(window.SMSCore)와 테스트(module.exports)에서 같은 코드를 쓴다.
 */
(function (global) {
  'use strict';

  /* ---------- 숫자 · 금액 ---------- */
  function digits(v) { return String(v == null ? '' : v).replace(/[^0-9]/g, ''); }

  // "2억 7천만" 같은 한글 단위도 만원 단위 숫자로 바꿔 준다. 잘못 치면 0원대가 되지 않게.
  function koreanToMan(text) {
    var s = String(text).replace(/[,\s]/g, '');
    var total = 0;
    var eok = /(\d+(?:\.\d+)?)억/.exec(s);
    if (eok) {
      total += parseFloat(eok[1]) * 10000;
      s = s.replace(eok[0], '');
    }
    var re = /(\d+(?:\.\d+)?)(천|백|십|만)?/g;
    var m;
    while ((m = re.exec(s)) !== null) {
      if (!m[0]) break;
      var n = parseFloat(m[1]);
      var unit = m[2];
      if (unit === '천') total += n * 1000;
      else if (unit === '백') total += n * 100;
      else if (unit === '십') total += n * 10;
      else total += n;
    }
    return Math.round(total);
  }

  function parseMan(v) {
    var s = String(v == null ? '' : v).trim();
    if (!s) return null;
    if (/[억만천백십]/.test(s)) {
      var man = koreanToMan(s);
      return man || null;
    }
    var d = digits(s);
    if (!d) return null;
    return parseInt(d, 10);
  }

  function group(n) { return Number(n).toLocaleString('en-US'); }

  // 270,000,000 -> "2억 7천만" / 237,000,000 -> "2억 3,700만" / 30,000,000 -> "3천만"
  function koreanAmount(wonValue, opts) {
    opts = opts || {};
    var n = Math.round(Math.abs(Number(wonValue) || 0));
    var sign = Number(wonValue) < 0 ? '-' : '';
    if (!n) return '0' + (opts.omitWon ? '' : '원');
    var eok = Math.floor(n / 100000000);
    var man = Math.floor((n % 100000000) / 10000);
    var wonPart = n % 10000;
    var parts = [];
    if (eok) parts.push(group(eok) + '억');
    if (man) parts.push((man % 1000 === 0 ? group(man / 1000) + '천' : group(man)) + '만');
    if (wonPart) parts.push(group(wonPart) + '원');
    var out = parts.join(' ');
    if (!wonPart && !opts.omitWon) out += ' 원';
    return sign + out;
  }

  function formatWonPlain(wonValue) { return group(Math.round(Number(wonValue) || 0)) + '원'; }

  // mode: 'won_eokman'(기본) | 'won' | 'eokman'
  function formatAmount(manValue, mode) {
    if (manValue == null || manValue === '' || isNaN(manValue)) return '';
    var w = Math.round(Number(manValue) * 10000);
    var plain = formatWonPlain(w);
    var km = koreanAmount(w, { omitWon: true });
    if (mode === 'eokman') return km + ' 원';
    if (mode === 'won') return plain;
    return plain + ' (' + km + ' 원)';
  }

  // 만원 입력 옆 도우미: 27000 -> "2억 7천만"
  function manHint(manValue) {
    if (manValue == null || manValue === '' || isNaN(manValue)) return '';
    return koreanAmount(Number(manValue) * 10000, { omitWon: true });
  }

  // 금액 입력칸 아래 환산 줄: 230000 -> "2,300,000,000원 (23억)"
  // 비었거나 0이면 빈 글자(자리는 CSS가 잡아 둔다)
  function moneyHintLine(manValue) {
    if (manValue == null || manValue === '' || isNaN(manValue)) return '';
    var man = Number(manValue);
    if (!man) return '';
    return formatWonPlain(man * 10000) + ' (' + manHint(man) + ')';
  }

  function numOrNull(v) {
    if (v == null || v === '') return null;
    var n = Number(v);
    return isNaN(n) ? null : n;
  }

  /* ---------- 매물 가격 (매매 / 전세 / 월세 · 만 원 입력) ---------- */
  // 예전에 가격칸에 직접 친 "매매 23억", "보증금 1억·월세 350" 같은 글을 구조화한다.
  function legacyPrice(text) {
    var s = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
    if (!s) return null;
    var trade = '';
    var m = /^(매매|전세|월세)\s*/.exec(s);
    if (m) { trade = m[1]; s = s.slice(m[0].length); }
    s = s.replace(/^[:\-]\s*/, '').trim();
    var monthly = trade === '월세' || /보증금|월세/.test(s) || s.indexOf('/') !== -1 || s.indexOf('·') !== -1;
    if (monthly) {
      var parts = s.split(/\s*(?:\/|·|,)\s*/);
      if (parts.length < 2) {
        var mm = /보증금\s*([0-9억만천백십,.]+)\s*월세\s*([0-9억만천백십,.]+)/.exec(s);
        parts = mm ? [mm[1], mm[2]] : [s, ''];
      }
      var dep = parseMan(String(parts[0] || '').replace(/^보증금\s*/, ''));
      var rent = parseMan(String(parts[1] || '').replace(/^월세\s*/, ''));
      return { trade: '월세', amount: '', deposit: dep == null ? '' : dep, rent: rent == null ? '' : rent };
    }
    var amt = parseMan(s.replace(/^(금액|가격)\s*/, ''));
    return { trade: trade, amount: amt == null ? '' : amt, deposit: '', rent: '' };
  }

  // 매물 하나의 가격 문구: "매매 23억" / "전세 11억 5천만" / "월세 1억/300만"
  function propPrice(p) {
    p = p || {};
    var trade = String(p.trade || '').trim() || '매매';
    var amount = numOrNull(p.amount);
    var dep = numOrNull(p.deposit);
    var rent = numOrNull(p.rent);
    var legacy = String(p.price == null ? '' : p.price).trim();
    if (amount == null && dep == null && rent == null) return legacy;
    if (trade === '월세') {
      return '월세 ' + (dep == null ? '0' : manHint(dep)) + '/' + (rent == null ? '0' : manHint(rent));
    }
    if (amount == null) return legacy;
    return trade + ' ' + manHint(amount);
  }

  // 예전 저장값(가격을 글로 친 것)을 새 입력칸 값으로 옮긴다
  function propMoneyPatch(p) {
    if (!p) return null;
    var out = {};
    var has = numOrNull(p.amount) != null || numOrNull(p.deposit) != null || numOrNull(p.rent) != null;
    var legacy = String(p.price == null ? '' : p.price).trim();
    // 범위("20.5억~21억")나 단기처럼 한 숫자로 줄일 수 없는 금액은 원문을 살린다
    if (!has && legacy && legacy.indexOf('~') === -1 && !/^단기/.test(legacy)) {
      var lg = legacyPrice(legacy);
      if (lg) {
        if (lg.trade) out.trade = lg.trade;
        if (lg.amount !== '' && lg.amount != null) out.amount = lg.amount;
        if (lg.deposit !== '' && lg.deposit != null) out.deposit = lg.deposit;
        if (lg.rent !== '' && lg.rent != null) out.rent = lg.rent;
        if (numOrNull(out.amount) != null || numOrNull(out.deposit) != null || numOrNull(out.rent) != null) out.price = '';
      }
    }
    if (!p.trade) out.trade = out.trade || '매매';
    return Object.keys(out).length ? out : null;
  }

  /* ---------- 중개보수 (서울특별시 주택중개보수 등에 관한 조례 별표1 · 2021.10.19 시행) ---------- */
  var HOUSE_SALE = [
    [0, 0.006, 250000],
    [5000, 0.005, 800000],
    [20000, 0.004, null],
    [90000, 0.005, null],
    [120000, 0.006, null],
    [150000, 0.007, null]
  ];
  var HOUSE_LEASE = [
    [0, 0.005, 200000],
    [5000, 0.004, 300000],
    [10000, 0.003, null],
    [60000, 0.004, null],
    [120000, 0.005, null],
    [150000, 0.006, null]
  ];

  var FEE_KINDS = {
    house: '주택',
    officetel: '오피스텔',
    presale: '분양권',
    commercial: '상가·토지'
  };

  function bracketFor(table, man) {
    var pick = table[0];
    for (var i = 0; i < table.length; i++) {
      if (man >= table[i][0]) pick = table[i];
    }
    return pick;
  }

  // 오피스텔: 전용 85㎡ 이하 주거용만 0.5%(매매)/0.4%(임대),
  // 85㎡ 초과 또는 업무용은 주택 외(0.9% 이내 협의)로 본다.
  function feeTableFor(kind, trade, officetelUse) {
    if (kind === 'presale') return HOUSE_SALE.slice();          // 주택분양권 = 주택 매매 요율
    if (kind === 'officetel') {
      if (officetelUse === 'business') return [[0, 0.009, null]];
      return trade === '매매' ? [[0, 0.005, null]] : [[0, 0.004, null]];
    }
    if (kind === 'commercial') return [[0, 0.009, null]];       // 주택·오피스텔 외 = 0.9%
    return (trade === '매매' ? HOUSE_SALE : HOUSE_LEASE).slice();
  }

  function round3(x) { return Math.round(x * 1000) / 1000; }

  function feeCalc(input) {
    input = input || {};
    var kind = input.kind || 'house';
    var trade = input.trade || '매매';
    if (kind === 'presale') trade = '매매';
    var officetelUse = input.officetelUse === 'business' ? 'business' : 'resident';
    var amountMan = input.amountMan == null || input.amountMan === '' ? null : Number(input.amountMan);
    var converted = false;

    if (trade === '월세') {
      var dep = input.depositMan == null || input.depositMan === '' ? 0 : Number(input.depositMan);
      var rent = input.rentMan == null || input.rentMan === '' ? 0 : Number(input.rentMan);
      if (isNaN(dep) || isNaN(rent) || dep < 0 || rent < 0) return { ok: false, reason: '음수' };
      if (!dep && !rent) return { ok: false, reason: '금액 없음' };
      var conv = dep + rent * 100;
      if (conv < 5000) conv = dep + rent * 70;
      amountMan = conv;
      converted = true;
    }
    if (amountMan == null || isNaN(amountMan)) return { ok: false, reason: '금액 없음' };
    if (amountMan < 0) return { ok: false, reason: '음수' };
    if (amountMan <= 0) return { ok: false, reason: '금액 없음' };

    var table = feeTableFor(kind, trade, officetelUse);
    var b = bracketFor(table, amountMan);
    var capRate = b[1];
    var rate = capRate;
    var wanted = input.ratePct == null || input.ratePct === '' ? null : Number(input.ratePct);
    var rateOver = false;
    if (wanted != null && !isNaN(wanted) && wanted > 0) {
      // 상한요율을 넘는 협의 요율은 적용하지 않고 상한요율로 계산한다(rateOver)
      if (wanted / 100 > capRate + 1e-9) { rateOver = true; rate = capRate; }
      else rate = wanted / 100;
    }

    var baseWon = Math.round(amountMan * 10000);
    var fee = Math.round(baseWon * rate);
    var capped = false;
    if (b[2] != null && fee > b[2]) { fee = b[2]; capped = true; }

    var vatMode = input.vat || 'none';
    var vatRate = vatMode === '10' ? 0.1 : vatMode === '4' ? 0.04 : 0;
    var vat = Math.round(fee * vatRate);

    return {
      ok: true,
      kind: kind,
      kindLabel: FEE_KINDS[kind] || kind,
      officetelUse: officetelUse,
      trade: trade,
      amountMan: amountMan,
      amountWon: baseWon,
      depositMan: converted ? Number(input.depositMan || 0) : null,
      rentMan: converted ? Number(input.rentMan || 0) : null,
      converted: converted,
      capRatePct: round3(capRate * 100),
      ratePct: round3(rate * 100),
      requestedPct: wanted == null || isNaN(wanted) ? null : round3(wanted),
      rateOver: rateOver,
      fee: fee,
      supply: fee,
      capWon: b[2],
      capped: capped,
      vatMode: vatMode,
      vat: vat,
      vatRatePct: Math.round(vatRate * 1000) / 10,
      total: fee + vat
    };
  }

  /* ---------- 지급액 분할 (계약금 · 중도금 · 잔금) ----------
     잔금 = 매매대금(임대차는 보증금) − 계약금 − 중도금.
     중도금이 비면 0원으로 보고, 계약금+중도금이 매매대금을 넘거나 음수가 들어오면
     잔금을 내지 않고(over/negative) 화면·문자에서 확인을 요청한다. */
  function paymentSplit(input) {
    input = input || {};
    var base = numOrNull(input.totalMan);
    var gyeyak = numOrNull(input.gyeyakMan);
    var jung = numOrNull(input.jungMan);
    var out = {
      ok: false,
      baseMan: base,
      gyeyakMan: gyeyak == null ? 0 : gyeyak,
      jungMan: jung == null ? 0 : jung,
      paidMan: null,
      janMan: null,
      over: false,
      overByMan: 0,
      negative: false,
      reason: ''
    };
    if (base == null || base <= 0) { out.reason = 'no-base'; return out; }
    if (base < 0 || out.gyeyakMan < 0 || out.jungMan < 0) {
      out.negative = true;
      out.reason = 'negative';
      return out;
    }
    out.paidMan = out.gyeyakMan + out.jungMan;
    out.janMan = base - out.paidMan;
    if (out.janMan < 0) {
      out.over = true;
      out.overByMan = -out.janMan;
      out.janMan = null;
      out.reason = 'over';
      return out;
    }
    out.ok = true;
    return out;
  }

  function rateLabel(pct) {
    if (pct == null || isNaN(pct)) return '';
    var s = Number(pct).toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  /* ---------- 매물 노출 (단지명 + 동/단지 + 호/층) ----------
     매물 줄마다 동 칸의 배지로 '동 ↔ 단지', 호 칸의 배지로 '호 ↔ 층'을 고른다.
     단지로 볼 때는 뒤의 호수·층을 붙이지 않는다.
     예전 저장값의 한 줄짜리 노출 설정(p.mode)도 그대로 읽는다. */
  function propertyLabel(p) {
    p = p || {};
    var complex = String(p.complex || '').trim();
    var dongNum = parseInt(digits(p.dong), 10);
    var hoNum = parseInt(digits(p.ho), 10);
    var mode = p.mode || 'ho';
    var dongMode = p.dongMode || (mode === 'complex' ? 'complex' : 'dong');
    var hoMode = p.hoMode || (mode === 'floor' ? 'floor' : 'ho');
    var parts = [];
    if (complex) parts.push(complex);
    if (dongMode === 'complex') {
      if (!isNaN(dongNum)) parts.push(Math.floor(dongNum / 100) + '단지');
    } else {
      if (!isNaN(dongNum)) parts.push(dongNum + '동');
      if (hoMode === 'floor') {
        if (!isNaN(hoNum)) parts.push(Math.floor(hoNum / 100) + '층');
        else if (String(p.grade || '').trim()) parts.push(String(p.grade).trim());
      } else if (!isNaN(hoNum)) {
        parts.push(hoNum + '호');
      }
    }
    return parts.join(' ');
  }

  /* ---------- 계좌 파서 ---------- */
  var BANK_ALIASES = {
    '국민': '국민은행', 'kb국민': '국민은행', 'kb': '국민은행', '국민은행': '국민은행',
    '신한': '신한은행', '신한은행': '신한은행', '신한은행주식회사': '신한은행',
    '우리': '우리은행', '우리은행': '우리은행',
    '하나': '하나은행', '하나은행': '하나은행', 'keb하나': '하나은행', '외환': '하나은행',
    '농협': '농협은행', 'nh농협': '농협은행', 'nh': '농협은행', '농협은행': '농협은행',
    '기업': 'IBK기업은행', 'ibk기업': 'IBK기업은행', 'ibk': 'IBK기업은행', '기업은행': 'IBK기업은행',
    '산업': '한국산업은행', '한국산업': '한국산업은행', '산업은행': '한국산업은행',
    '카카오': '카카오뱅크', '카카오뱅크': '카카오뱅크', '카뱅': '카카오뱅크',
    '케이': '케이뱅크', '케이뱅크': '케이뱅크', 'k뱅크': '케이뱅크',
    '토스': '토스뱅크', '토스뱅크': '토스뱅크',
    '제일': 'SC제일은행', 'sc제일': 'SC제일은행', 'sc': 'SC제일은행', '제일은행': 'SC제일은행',
    '씨티': '한국씨티은행', '한국씨티': '한국씨티은행', '씨티은행': '한국씨티은행', 'citi': '한국씨티은행',
    '우체국': '우체국예금', '우체국예금': '우체국예금',
    '수협': '수협은행', '수협은행': '수협은행', '신협': '신협', '새마을': '새마을금고', '새마을금고': '새마을금고',
    '대구': '대구은행', '대구은행': '대구은행', '부산': '부산은행', '부산은행': '부산은행',
    '경남': '경남은행', '경남은행': '경남은행', '광주': '광주은행', '광주은행': '광주은행',
    '전북': '전북은행', '전북은행': '전북은행', '제주': '제주은행', '제주은행': '제주은행'
  };

  function bankLookup(token) {
    var bare = String(token || '').replace(/\s/g, '');
    if (!bare) return null;
    var key = bare.toLowerCase().replace(/\(주\)|주식회사|㈜/g, '');
    if (BANK_ALIASES[key]) return BANK_ALIASES[key];
    var stripped = key.replace(/(은행|뱅크)$/, '');
    if (BANK_ALIASES[stripped]) return BANK_ALIASES[stripped];
    return null;
  }

  // "국민 123456-01-234567 홍길동" / "홍길동 하나 12345678901234" -> "하나은행 12345678901234 홍길동"
  function accountParse(text) {
    var raw = String(text == null ? '' : text).trim();
    if (!raw) return '';
    // "123456-01-234567홍길동"처럼 계좌와 예금주가 붙어 있으면 먼저 띄운다
    raw = raw.replace(/([0-9])([가-힣])/g, '$1 $2').replace(/([가-힣])([0-9])/g, '$1 $2');
    var tokens = raw.split(/\s+/).filter(Boolean);
    var bank = null, acct = null, holder = null, rest = [];
    for (var i = 0; i < tokens.length; i++) {
      var tok = tokens[i];
      if (!bank) {
        var b = bankLookup(tok);
        if (b) { bank = b; continue; }
      }
      var dg = digits(tok);
      if (!acct && dg.length >= 6) { acct = tok; continue; }
      if (!holder && /^[가-힣]{2,5}$/.test(tok)) { holder = tok; continue; }
      rest.push(tok);
    }
    var out = [];
    if (bank) out.push(bank);
    if (acct) out.push(acct);
    if (holder) out.push(holder);
    if (rest.length) out.push(rest.join(' '));
    return out.join(' ');
  }

  /* ---------- 날짜 · 시간 ---------- */
  var WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

  function pad2(n) { return String(n).padStart(2, '0'); }

  function parseDateValue(v) {
    if (!v || !v.date) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v.date);
    if (!m) return null;
    return { y: +m[1], m: +m[2], d: +m[3] };
  }

  function weekdayOf(y, m, d) { return WEEKDAYS[new Date(y, m - 1, d).getDay()]; }

  function hasTime(v) { return v && v.hour != null && v.hour !== ''; }

  // 14:30 -> "오후 2시 30분"
  function formatTime(hour, min) {
    if (hour == null || hour === '') return '';
    var h = Number(hour);
    var p = h < 12 ? '오전' : '오후';
    var h12 = h % 12 === 0 ? 12 : h % 12;
    var mm = Number(min || 0);
    return p + ' ' + h12 + '시' + (mm ? ' ' + mm + '분' : '');
  }

  // "2026년 11월 28일 토요일 오전 11시 30분"
  function formatDateTime(v) {
    var d = parseDateValue(v);
    if (!d) return '';
    var head = d.y + '년 ' + d.m + '월 ' + d.d + '일 ' + weekdayOf(d.y, d.m, d.d) + '요일';
    var t = formatTime(v.hour, v.min);
    return head + (t ? ' ' + t : '');
  }

  // "2026년 11월 28일 토요일 오전 10시 ~ 오후 12시"
  function formatDateTimeRange(start, end) {
    var a = formatDateTime(start);
    if (!a) return '';
    var t = formatTime(end && end.hour, end && end.min);
    return a + (t ? ' ~ ' + t : '');
  }

  // 문자에 넣는 짧은 표기: "내일 9/23 (화) 오전 9시30분" (오늘·내일·모레는 말로)
  function shortDate(v, now) {
    var d = parseDateValue(v);
    if (!d) return '';
    var today = now || new Date();
    var t0 = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    var t1 = new Date(d.y, d.m - 1, d.d);
    var diff = Math.round((t1 - t0) / 86400000);
    var rel = diff === 0 ? '오늘' : diff === 1 ? '내일' : diff === 2 ? '모레' : '';
    var head = d.m + '/' + d.d + ' (' + weekdayOf(d.y, d.m, d.d) + ')';
    return (rel ? rel + ' ' : '') + head;
  }

  function formatShortDateTime(v, now) {
    var s = shortDate(v, now);
    if (!s) return '';
    if (!hasTime(v)) return s;
    var h = Number(v.hour);
    var m = Number(v.min || 0);
    var p = h < 12 ? '오전' : '오후';
    var h12 = h % 12 === 0 ? 12 : h % 12;
    return s + ' ' + p + ' ' + h12 + '시' + (m ? m + '분' : '');
  }

  // 전화번호를 010-0000-0000 꼴로 (이미 하이픈이 있으면 그대로)
  function formatPhone(v) {
    var raw = String(v == null ? '' : v).trim();
    var d = digits(raw);
    if (raw.indexOf('-') !== -1 && d.length >= 9) return raw;
    if (d.length === 11) return d.slice(0, 3) + '-' + d.slice(3, 7) + '-' + d.slice(7);
    if (d.length === 10) return d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6);
    if (d.length === 9) return d.slice(0, 2) + '-' + d.slice(2, 5) + '-' + d.slice(5);
    if (d.length === 8) return d.slice(0, 4) + '-' + d.slice(4);
    return raw;
  }

  // 입력칸에 보이는 짧은 표기: "2026.11.28 (토) 오후 2:30"
  function compactDateTime(v) {
    var d = parseDateValue(v);
    if (!d) return '';
    var head = d.y + '.' + pad2(d.m) + '.' + pad2(d.d) + ' (' + weekdayOf(d.y, d.m, d.d) + ')';
    if (!hasTime(v)) return head;
    var h = Number(v.hour);
    return head + ' ' + (h < 12 ? '오전' : '오후') + ' ' + (h % 12 === 0 ? 12 : h % 12) + ':' + pad2(v.min || 0);
  }

  var API = {
    digits: digits,
    parseMan: parseMan,
    koreanToMan: koreanToMan,
    group: group,
    koreanAmount: koreanAmount,
    formatWonPlain: formatWonPlain,
    formatAmount: formatAmount,
    manHint: manHint,
    moneyHintLine: moneyHintLine,
    propPrice: propPrice,
    legacyPrice: legacyPrice,
    propMoneyPatch: propMoneyPatch,
    feeCalc: feeCalc,
    feeTableFor: feeTableFor,
    paymentSplit: paymentSplit,
    rateLabel: rateLabel,
    propertyLabel: propertyLabel,
    accountParse: accountParse,
    parseDateValue: parseDateValue,
    weekdayOf: weekdayOf,
    formatTime: formatTime,
    formatDateTime: formatDateTime,
    formatDateTimeRange: formatDateTimeRange,
    compactDateTime: compactDateTime,
    shortDate: shortDate,
    formatShortDateTime: formatShortDateTime,
    formatPhone: formatPhone,
    hasTime: hasTime,
    FEE_KINDS: FEE_KINDS
  };

  global.SMSCore = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})(typeof window !== 'undefined' ? window : globalThis);
