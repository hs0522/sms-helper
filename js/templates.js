/* 마래푸중앙부동산 문자 도우미 — 20종 템플릿 정의
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
  function join(blocks) {
    return blocks.filter(function (b) { return b != null && b !== ''; }).join('\n\n');
  }
  function hint(v) { var s = C.manHint(C.parseMan(v)); return s || ''; }
  // 금액이 매매가의 몇 % 인지 (예: 25 → " 25%")
  function pctOf(part, whole) {
    var p = C.parseMan(part), w = C.parseMan(whole);
    if (p == null || !w) return null;
    return Math.round((p / w) * 1000) / 10;
  }
  function pctLabel(p, fallback) {
    return ' ' + (p == null ? fallback : p) + '%';
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
    return price ? base + ' (' + price + ')' : base + ' (가격)';
  }
  // 동·호수로 찾은 평형·타입·방향 → " 34평 84A · 남동향" (표에 없으면 직접 적은 값, 그것도 없으면 빈칸)
  function typeLine(p) {
    var s = String((p && p.typeInfo) || '').trim() || C.maraepuUnit(p && p.complex, p && p.dong, p && p.ho);
    return s ? ' ' + s : '';
  }
  function itemsOf(data, key, mode) {
    var list = data[key];
    if (!Array.isArray(list) || !list.length) return [];
    return list.filter(function (p) {
      return p && (p.dong || p.ho || p.complex || p.price || p.amount || p.deposit || p.rent);
    });
  }

  /* ---------------- 집보기 후 감사 인사 — 대상별 문구 ---------------- */
  var VARIANTS = {
    owner: [
      '오늘 집 보여드리느라 잠시 불편을 드렸는데, 흔쾌히 응해주셔서 감사합니다.\n덕분에 손님도 편안하게 잘 둘러보고 갔습니다.',
      '바쁘신 중에 시간 내주시고 집까지 열어주셔서 정말 감사했습니다.\n손님 반응이 좋았으니 좋은 결과로 이어지도록 잘 챙겨보겠습니다.',
      '오늘 방문 잘 마쳤습니다.\n집 상태를 꼼꼼히 설명해 주셔서 손님께도 잘 전달됐습니다. 감사합니다.',
      '집 보여주시느라 고생 많으셨습니다.\n손님께서 만족해 하셔서 좋은 소식 전해드릴 수 있도록 노력하겠습니다.',
      '잠깐 들렀는데도 따뜻하게 맞아주셔서 감사했습니다.\n손님과 일정 잘 조율해서 다시 연락드리겠습니다.',
      '오늘 시간 내주셔서 감사합니다.\n집 관련해서 궁금한 점 생기시면 언제든 편하게 연락 주세요.',
      '방문 잘 마치고 나왔습니다.\n집을 잘 관리해 두신 덕분에 손님도 좋게 봤습니다. 감사한 마음 전합니다.'
    ],
    coagent: [
      '오늘 집보기 잘 마쳤습니다.\n시간 내주시고 현장까지 챙겨주셔서 감사했습니다.',
      '사장님 덕분에 손님 편하게 잘 모시고 왔습니다.\n좋은 결과로 이어지도록 잘 챙겨보겠습니다.',
      '오늘 공동중개 잘 진행됐습니다.\n자세히 설명해 주셔서 손님께 도움이 많이 됐습니다. 감사합니다.',
      '바쁘신 중에 집 열어주셔서 감사합니다.\n손님 반응이 좋았으니 좋은 소식 전해드리겠습니다.',
      '오늘 함께해 주셔서 감사했습니다.\n다음에도 좋은 매물로 다시 인사드리겠습니다.',
      '현장에서 친절하게 안내해 주셔서 손님도 만족하고 갔습니다.\n감사합니다, 사장님.',
      '오늘 집보기 잘 마쳤습니다.\n덕분에 수월하게 진행됐습니다. 감사합니다!'
    ],
    guest: [
      '오늘 바쁘신 중에 시간 내주시고 집 보러 와주셔서 감사합니다.\n천천히 살펴보시고 궁금한 점 있으면 언제든 연락 주세요.',
      '오늘 함께 집 보러 다니시느라 고생 많으셨습니다.\n비교해 보시고 마음에 드시는 곳 있으면 편하게 말씀해 주세요.',
      '오늘 집 보러 와주셔서 감사합니다.\n사진보다 실제가 더 좋다고 하셔서 저도 기분이 좋네요. 조건 조율 최선을 다해 도와드리겠습니다.',
      '오늘 고생 많으셨습니다.\n보신 집 중에서 궁금한 점이나 더 보고 싶은 집 있으면 편하게 연락 주세요.',
      '오늘 시간 내주셔서 감사합니다.\n결정 서두르지 마시고 천천히 비교해 보세요. 언제든 도와드리겠습니다.',
      '함께 집 보러 다니며 이야기 나눠서 즐거웠습니다.\n좋은 집으로 연결되도록 끝까지 챙기겠습니다. 감사합니다!',
      '오늘 방문 잘 마치셨죠?\n집 보시느라 수고 많으셨습니다. 다음 일정은 편하실 때 맞춰 드리겠습니다.'
    ]
  };

  var GREETINGS = [
    { v: 'none', l: '추가 안 함', text: '' },
    { v: 'cold', l: '감기 조심', text: '쌀쌀한 날씨에 감기 조심하세요' },
    { v: 'evening', l: '편안한 저녁', text: '편안한 저녁 보내세요' },
    { v: 'weekend', l: '주말 잘 보내세요', text: '주말 잘 보내세요' },
    { v: 'day', l: '좋은 하루', text: '오늘도 좋은 하루 보내세요' }
  ];

  function greetingOf(v) {
    var g = GREETINGS.filter(function (x) { return x.v === v; })[0];
    return g ? g.text : '';
  }

  /* ---------------- 협력업체·상담사 ---------------- */
  var VENDOR_CATS = ['대출', '세무', '법무사', '인테리어', '입주청소', '이사업체'];

  var VENDOR_INTRO = {
    '대출': '마포구 일대를 잘 아는 대출 상담사분들입니다 😊\n거래시점 기준 가장 유리한(저렴한) 조건으로 안내해 드리니, 마래푸중앙부동산 소개라고 말씀하시고 편하게 상담받아 보셔요!',
    '세무': '양도소득세·취득세를 도와드리는 세무사입니다 😊\n마래푸중앙부동산 소개라고 말씀하시고, 궁금한 점 편하게 상담받아 보셔요!',
    '법무사': '등기 업무를 도와드리는 법무사입니다 😊\n잔금 후 소유권 이전 등기나 근저당 말소가 필요하시면, 마래푸중앙부동산 소개라고 말씀하시고 편하게 문의해 보셔요!',
    '인테리어': '입주 전 인테리어를 도와드리는 업체입니다 😊\n마래푸중앙부동산 소개라고 말씀하시면 상담과 견적을 편하게 받아보실 수 있습니다!',
    '입주청소': '입주청소를 도와드리는 업체입니다 😊\n마래푸중앙부동산 소개라고 말씀하시고 편하게 견적 받아보셔요!',
    '이사업체': '이사를 도와드리는 업체입니다 😊\n마래푸중앙부동산 소개라고 말씀하시고 편하게 견적 받아보셔요!'
  };

  // 처음 열었을 때 들어 있는 연락처 (비움 — 실제 연락처는 화면에서 추가해 이 기기에만 저장한다)
  var DEFAULT_CONTACTS = {
    '대출': []
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

  function contactBlock(list, ids) {
    var picked = list.filter(function (c) { return ids.indexOf(c.id) !== -1; });
    if (!picked.length) return '이름 : 상담사 이름\n연락처 : 전화번호';
    return picked.map(function (c) {
      return '이름 : ' + String(c.name || '').trim() + '\n연락처 : ' + C.formatPhone(c.phone);
    }).join('\n\n');
  }

  /* 카테고리(stage) · 표시 순서(order) · 제목 · 부제목 — 2026-11-25 수정요청서 반영
     내부 ID(t1~t20)와 기존 번호(no)는 그대로 두고, 화면은 4개 업무 카테고리 순서로 보여 준다. */
  var TEMPLATES = [
    /* ---------------- 고객 응대·매물 관리 ---------------- */
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
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '방금 통화 감사드리며, 편하실 때 천천히 고민해 보시고 연락 주세요.\n마포구 일대의 다양한 매물을 보유하고 있어 조건에 맞는 집으로 꼼꼼히 찾아드리겠습니다.',
          '고객님의 소중한 재산을 정성껏 중개하겠습니다. 감사합니다!',
          ctx.office + ' 대표 황호선 드림\n' + ctx.phones
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
        { t: 'date', id: 'movein', label: '입주', mode3: true, ph: '예: 협의 / 즉시 / 26.12 말' },
        { t: 'text', id: 'option', label: '옵션', ph: '예: 시스템에어컨, 올수리 등' }
      ],
      build: function (d, ctx) {
        var p = d.prop || {};
        var price = C.propPrice(p);
        var movein = C.dateFieldText(d, 'movein') || txt(null, '입주');
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '소중한 매물을 접수해 주셔서 진심으로 감사드립니다.\n저희가 마포래미안푸르지오 단지 내 상가에 자리하고 있는 만큼, 더욱 신경 써서 좋은 인연으로 연결해 드리겠습니다.',
          '접수해 주신 매물 내용 확인 부탁드립니다.',
          '* ' + prop(p, d.mode) + '\n' +
          '* 거래조건 : ' + (price || '(금액)') + '\n' +
          '* 입주 : ' + movein + '\n' +
          '* 옵션 : ' + txt(d.option, '옵션'),
          '혹시 변동 사항이 있으시면 언제든 편하게 연락 주세요. 감사합니다!',
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
        { t: 'segplus', id: 'danji', label: '단지', options: [
          { v: '1단지', l: '1단지' }, { v: '2단지', l: '2단지' },
          { v: '3단지', l: '3단지' }, { v: '4단지', l: '4단지' }
        ], ph: '직접 입력 (예: 5단지)' },
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '전세', l: '전세' }, { v: '월세', l: '월세' }] }
      ],
      build: function (d, ctx) {
        var trade = d.trade === '전세' || d.trade === '월세' ? d.trade : '매매';
        var guest = trade === '매매' ? '매수' : trade;     // 매수 / 전세 / 월세
        var owner = trade === '매매' ? '매도' : '임대';    // 매도 / 임대
        var danji = String(d.danji == null ? '' : d.danji).trim() || '1단지';
        var blocks = [
          '안녕하세요, 마포래미안푸르지오 ' + danji + '의 ' + ctx.office + '입니다😊',
          '현재 ' + guest + '를 알아보는 손님이 있어 조심스럽게 연락드렸습니다',
          owner + ' 계획이 확정되셨다면, 저희 쪽에서도 손님께 브리핑드리고 적극적으로 소개해보고 싶습니다',
          '단지 내 부동산인 만큼 단지 특성을 잘 알고 있어 ' + guest + ' 손님을 잘 끌어낼 수 있습니다',
          '답장 주시면 바로 추진해보겠습니다\n감사합니다!'
        ];
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },

    /* ---------------- 집보기·방문 안내 ---------------- */
    {
      id: 't3',
      no: 4,
      stage: 2,
      order: 1,
      icon: 'home',
      title: '소유자 집보기 문의',
      desc: '방문 일정 · 간단형 / 상세형',
      fields: [
        { t: 'seg', id: 'ver', label: '버전', options: [{ v: 'simple', l: '간단형' }, { v: 'detail', l: '상세형' }] },
        { t: 'seg', id: 'guest', label: '거래 유형', options: [{ v: '매수', l: '매수' }, { v: '전세', l: '전세' }, { v: '월세', l: '월세' }] },
        { t: 'date', id: 'when', label: '방문 일시', showIf: function (d) { return d.ver !== 'detail'; } },
        { t: 'times', id: 'times', label: '방문 희망 시간', showIf: function (d) { return d.ver === 'detail'; } },
        { t: 'props', id: 'items', label: '매물', price: true, showIf: function (d) { return d.ver === 'detail' && Array.isArray(d.items) && d.items.length > 0; } }
      ],
      build: function (d, ctx) {
        var guest = d.guest === '전세' || d.guest === '월세' ? d.guest : '매수';
        if (d.ver !== 'detail') {
          var when = C.formatShortDateTime(d.when) || '방문 일시';
          var simple = [
            '안녕하세요, ' + ctx.office + '입니다 😊',
            guest + ' 손님이 있어서 연락드렸습니다',
            when + '에 손님 모시고 방문드릴 수 있을까요?'
          ];
          simple.push(sign(ctx));
          return join(simple);
        }
        var lines = String(d.times || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
        var when2 = lines.length ? lines.map(function (l) { return '* ' + l; }).join('\n') : '* (방문 희망 시간)';
        var blocks = [
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '집을 보시고자 하는 ' + guest + ' 손님이 계셔서 일정 여쭙고자 연락드립니다.\n방문 희망 시간은 아래와 같습니다.',
          when2
        ];
        var list = itemsOf(d, 'items', d.mode);
        if (list.length) {
          blocks.push('* 매물 : ' + list.map(function (p) { return propWithPrice(p, d.mode); }).join(' · '));
        }
        blocks.push('위 시간대 중 가능한 시간이 있으실지 여쭙습니다.\n혹시 해당 시간대가 어려우시다면 편하신 시간을 말씀해 주셔도 좋습니다. 최대한 일정에 맞춰 조율해 보겠습니다.');
        blocks.push('바쁜 와중에 확인해 주셔서 감사드리며, 회신 부탁드리겠습니다.');
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't4',
      no: 5,
      stage: 2,
      order: 2,
      icon: 'users',
      title: '공동중개 집보기 문의',
      desc: '방문 일정 · 공동중개 가능 여부',
      fields: [
        { t: 'property', id: 'prop', label: '매물', price: true },
        { t: 'date', id: 'when', label: '방문 희망 일시' }
      ],
      build: function (d, ctx) {
        var p = d.prop || {};
        var trade = p.trade === '전세' || p.trade === '월세' ? p.trade : '매매';
        var blocks = [
          '사장님, 안녕하세요 😊',
          trade + ' 문의 손님이 계셔서 공동중개 및 집보기 가능 여부 여쭙고자 연락드립니다.',
          '* ' + propWithPrice(p, d.mode),
          '손님께서는 ' + (C.formatDateTime(d.when) || '방문 희망 일시') + ' 방문을 희망하고 계십니다.\n해당 시간에 집보기가 가능하실지 확인 부탁드리며, 혹시 어려우시다면 가능하신 시간을 알려주시면 손님과 조율해 보겠습니다.',
          '감사합니다!'
        ];
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't5',
      no: 6,
      stage: 2,
      order: 3,
      icon: 'calendar-check',
      title: '집보기 일정 안내',
      desc: '예약 확정 / 조율 중',
      fields: [
        { t: 'seg', id: 'status', label: '예약 상태', options: [{ v: 'confirmed', l: '예약 확정' }, { v: 'pending', l: '조율 중' }] },
        { t: 'date', id: 'when', label: '방문 일시', showIf: function (d) { return d.status !== 'pending'; } },
        { t: 'toggle', id: 'detail', label: '매물 상세 포함', showIf: function (d) { return d.status !== 'pending'; } },
        { t: 'toggle', id: 'parking', label: '주차 안내 포함', showIf: function (d) { return d.status !== 'pending'; } },
        { t: 'props', id: 'items', label: '매물', price: true, showIf: function (d) { return d.status === 'pending' || d.detail; } },
      ],
      build: function (d, ctx) {
        var list = itemsOf(d, 'items', d.mode);
        if (d.status === 'pending') {
          var lines = list.length
            ? list.map(function (p) { return '* ' + propWithPrice(p, d.mode); }).join('\n')
            : '* (매물)';
          return join([
            '안녕하세요, ' + ctx.office + '입니다 😊',
            '아래 매물은 현재 집보기 조율 중입니다.',
            lines,
            '일정이 확정되는 대로 다시 문자드리겠습니다. 감사합니다!',
            sign(ctx)
          ]);
        }
        var blocks = [
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '요청하신 집보기 일정이 아래와 같이 확정되었습니다.',
          '* 일시 : ' + dt(d.when, '방문 일시')
        ];
        if (d.detail) {
          var mlines = list.length
            ? list.map(function (p) { return propWithPrice(p, d.mode); }).join(' · ')
            : '(매물)';
          blocks.push('* 매물 : ' + mlines);
        }
        blocks.push(d.parking
          ? '주차가 필요하신 경우 미리 알려주시면 안내해 드리겠습니다. 감사합니다!'
          : '감사합니다!');
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't6',
      no: 7,
      stage: 2,
      order: 4,
      icon: 'car',
      title: '주차 안내',
      desc: '주차 장소 · 주소',
      fixed: true,
      fields: [],
      build: function (d, ctx) {
        return join([
          '🚘 주차 안내드립니다 😊',
          '* 아현장로교회\n* 주소 : 서울 마포구 마포대로 197-1',
          '도착 후 연락 주시면 안내해 드리겠습니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't7',
      no: 8,
      stage: 2,
      order: 5,
      icon: 'layers',
      title: '추천 매물 안내',
      desc: '집보기 후 추천 매물 · 거래조건',
      fields: [
        { t: 'props', id: 'items', label: '매물', price: true }
      ],
      build: function (d, ctx) {
        var list = itemsOf(d, 'items', d.mode);
        var lines = list.length
          ? list.map(function (p) { return '* ' + propWithPrice(p, d.mode); }).join('\n')
          : '* (매물) (가격)';
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '함께 보신 매물 핵심 내용 정리해서 보내드립니다.',
          lines,
          '오늘 매물 보러 다니시느라 고생 많으셨습니다.\n천천히 살펴보시고 마음 정해지시면 편하게 연락 주세요. 조건 조율은 최선을 다해 도와드리겠습니다!',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't17',
      no: 9,
      stage: 2,
      order: 6,
      icon: 'heart',
      title: '집보기 후 감사 인사',
      desc: '소유자·거주자 / 공동중개 / 고객',
      fields: [
        { t: 'seg', id: 'target', label: '대상', options: [
          { v: 'owner', l: '소유자·거주자' }, { v: 'coagent', l: '공동중개' }, { v: 'guest', l: '고객' }
        ] },
        { t: 'variant', id: 'variant', label: '문구' },
        { t: 'seg', id: 'greet', label: '안부 문구', wrap: true, options: GREETINGS.map(function (g) { return { v: g.v, l: g.l }; }) }
      ],
      build: function (d, ctx) {
        var target = VARIANTS[d.target] ? d.target : 'owner';
        var list = VARIANTS[target];
        var idx = variantIndex(d, target);
        var blocks = [list[idx % list.length]];
        var greet = greetingOf(d.greet);
        if (greet) blocks.push(greet);
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't18',
      no: 10,
      stage: 1,
      order: 4,
      icon: 'send',
      title: '공동중개 매물 요청',
      desc: '고객 희망 조건 · 매물 확보',
      fields: [
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '전세', l: '전세' }, { v: '월세', l: '월세' }] },
        { t: 'money', id: 'amount', label: '금액 (매매가)', showIf: function (d) { return d.trade !== '전세' && d.trade !== '월세'; } },
        { t: 'money', id: 'deposit', label: '보증금', showIf: function (d) { return d.trade === '전세' || d.trade === '월세'; } },
        { t: 'money', id: 'rent', label: '월차임 (월세일 때만)', showIf: function (d) { return d.trade === '월세'; } },
        { t: 'text', id: 'area', label: '평형', ph: '예: 34 (매매일 때만)', showIf: function (d) { return d.trade !== '전세' && d.trade !== '월세'; } },
        { t: 'date', id: 'movein', label: '입주', mode3: true, ph: '예: 협의 / 즉시 / 26.12 말' },
        { t: 'text', id: 'guestNote', label: '손님 특징 한 줄', ph: '예: 염리초 보내고 싶은 학부모입니다' }
      ],
      build: function (d, ctx) {
        // 예전 저장값(임대차 · 금액 한 칸)도 그대로 읽는다
        var rent = d.trade === '전세' || d.trade === '월세';
        var trade = d.trade === '월세' ? '월세' : (rent ? '전세' : '매매');
        var depMan = C.parseMan(rent ? d.deposit : d.amount);
        var rentMan = C.parseMan(d.rent);
        var amount = hint(depMan) || '(금액)';
        var area = String(d.area == null ? '' : d.area).trim().replace(/평$/, '');
        var first = rent
          ? '요즘 임대매물 귀한데, 염치없이 전화드렸어요 🥲\n혹시 매물 나오면 꼭 부탁드립니다~!'
          : '매수 의사 확실한 손님이라 조심스레 여쭤봤어요 😊\n혹시 조건 맞는 매물 나오면 꼭 부탁드립니다~!';
        var cond;
        if (trade === '월세') {
          cond = '보증금 ' + amount + (rentMan != null ? ' / 월세 ' + hint(rentMan) + ' 원' : '') + '까지';
        } else if (trade === '전세') {
          cond = '보증금 ' + amount + '까지';
        } else {
          cond = '매매 ' + amount + '까지' + (area ? ' (' + area + '평)' : '');
        }
        var movein = C.dateFieldText(d, 'movein') || txt(null, '입주');
        var blocks = [
          first,
          [cond, '입주 ' + movein, txt(d.guestNote, '손님 특징')].join('\n'),
          '친절하게 설명해주셔서 감사합니다!'
        ];
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't19',
      no: 11,
      stage: 1,
      order: 5,
      icon: 'tag',
      title: '특가 매물 홍보',
      desc: '매물 정보 · 거래조건 · 강조 문구',
      fields: [
        { t: 'props', id: 'items', label: '매물', price: true, typeInfo: true },
        { t: 'text', id: 'emphasis', label: '강조 문구', ph: '예: 최저가 조율 가능합니다' }
      ],
      build: function (d, ctx) {
        var list = itemsOf(d, 'items', d.mode);
        var first = list[0] || {};
        var headTrade = first.trade === '전세' || first.trade === '월세' ? first.trade : '매매';
        var emph = String(d.emphasis == null ? '' : d.emphasis).trim() || '최저가 조율 가능합니다';
        // 매물이 여럿이면 한 줄씩: 단지·동·호 + 평형·타입·방향, 그 아래 거래조건 한 줄
        var lines = list.length ? list.map(function (p) {
          var head = prop(p, d.mode);
          var tl = typeLine(p).trim();
          if (head === '(매물)' && tl) head = tl;
          else if (tl) head += ' ' + tl;
          var price = C.propPrice(p);
          return '🔑' + head + '\n🔑' + (price ? price + '으로 ' : '') + emph;
        }).join('\n') : '🔑(매물) (가격)';
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '마포래미안푸르지오 ' + headTrade + ' 특가 소식 전해드립니다!',
          lines,
          '관심있으시면 편하게 연락주시고, 오늘도 좋은 하루 보내세요!',
          sign(ctx)
        ]);
      }
    },

    /* ---------------- 3단계 ---------------- */
    {
      id: 't8',
      no: 12,
      stage: 3,
      order: 1,
      icon: 'calendar',
      title: '매매조건·약정 안내',
      desc: '거래조건 · 지급 일정 · 특약',
      fields: [
        { t: 'group', label: '계약 기본' },
        { t: 'account', id: 'account', label: '매도인 계좌', ph: '예: 국민 123456-01-234567 홍길동' },
        { t: 'text', id: 'address', label: '물건지 주소', ph: '서울시 마포구 아현동 777 외 3필지' },
        { t: 'property', id: 'prop', label: '물건지' },
        { t: 'money', id: 'price', label: '매매가' },
        { t: 'paytable', id: 'pay', rows: [
          { id: 'jeong', label: '약정금', amountId: 'jeongAmount', dateId: 'jeongDate' },
          { id: 'gyeyak', label: '계약금', amountId: 'gyeyakAmount', dateId: 'gyeyakDate', rate: true },
          { id: 'jung', label: '중도금', amountId: 'jungAmount', dateId: 'jungDate', rate: true },
          { id: 'jan', label: '잔금', amountId: 'janAmount', dateId: 'janDate', auto: true }
        ] },
        { t: 'action', id: 'autoFill', label: '매매가로 계약금·중도금 자동 계산' },
        { t: 'group', label: '특약' },
        { t: 'toggle', id: 'permit', label: '토지거래허가구역 (특약 자동 포함)' },
        { t: 'toggle', id: 'mortgage', label: '근저당 말소 특약 포함' },
        { t: 'money', id: 'mortgageAmount', label: '채권최고액', showIf: function (d) { return d.mortgage; } },
        { t: 'text', id: 'mortgageHolder', label: '채권자', ph: '예: 주식회사 카카오뱅크', showIf: function (d) { return d.mortgage; } }
      ],
      build: function (d, ctx) {
        var jeongAmt = amt(C.parseMan(d.jeongAmount), ctx);
        var intro = '아래 표시부동산의 매매계약 주요내용을 보내드리오니, 내용 확인 후 동의하시면 아래 계좌로 ' + (jeongAmt || '(약정금)') + '을 입금해 주세요.';

        var jeongLine = '* 약정금 : ' + (jeongAmt || '(약정금)');
        var jd = C.formatDateTime(d.jeongDate);
        if (jd) jeongLine += ' (' + jd + ')';

        var gyeyakLine = '* 계약금' + pctLabel(pctOf(d.gyeyakAmount, d.price), '10') + ' : ' + (amt(C.parseMan(d.gyeyakAmount), ctx) || '(계약금)');
        var gd = C.formatDateTime(d.gyeyakDate);
        // 날짜 대신 "토지허가받은후" 같은 글자 일정도 넣을 수 있다 (진행 거래 엑셀에서 옮겨 온 값)
        gyeyakLine += ' (' + (gd || String(d.gyeyakText || '').trim() || '일정') + ')';        var sub = [];
        if (d.permit) sub.push('  - 단, 토지거래허가 일정에 맞춰 쌍방이 협의할 수 있다.');
        if (jeongAmt) sub.push('  - 약정금 ' + jeongAmt + '은 반환받고, 계약금 전체를 입금하기로 한다.');

        var jungLine = '* 중도금' + pctLabel(pctOf(d.jungAmount, d.price), '25') + ' : ' + (amt(C.parseMan(d.jungAmount), ctx) || '(중도금)') + ' (' + (C.formatDateTime(d.jungDate) || String(d.jungText || '').trim() || '일정') + ')';
        // 잔금 = 매매대금 − 계약금 − 중도금 (중도금이 비면 0원) — core.paymentSplit 하나로 계산한다
        var split = C.paymentSplit({
          totalMan: C.parseMan(d.price),
          gyeyakMan: C.parseMan(d.gyeyakAmount),
          jungMan: C.parseMan(d.jungAmount)
        });
        var janAmtText = split.ok ? amt(split.janMan, ctx) : '';
        var janLabel = janAmtText || (split.over ? '확인 필요 (계약금·중도금이 매매대금을 넘음)' : '(잔금)');
        var janWhen = C.formatDateTime(d.janDate) || String(d.janText || '').trim();
        var janParen = (split.over || split.negative) ? '' : ' (' + (janWhen || '일정') + ')';        var janLine = '* 잔금 : ' + janLabel + janParen;
        var splitWarn = '';
        if (split.over) {
          splitWarn = '※ 계약금·중도금 합계 ' + amt(split.paidMan, ctx) + '이 매매대금 ' + amt(split.baseMan, ctx) +
            '보다 ' + amt(split.overByMan, ctx) + ' 많습니다. 지급액을 다시 확인해 주세요.';
        } else if (split.negative) {
          splitWarn = '※ 지급액에 음수가 있어 잔금을 계산하지 않았습니다. 금액을 다시 확인해 주세요.';
        }

        var clauses = [];
        var n = 0;
        if (d.permit) {
          clauses.push(++n + '. 토지거래허가구역이므로 토지거래허가를 받기 위한 제반 서류는 매도인, 매수인 모두 제출하기로 한다.');
          clauses.push(++n + '. 쌍방의 귀책사유 없이 토지거래허가가 나지 않을 경우 계약은 원천무효이며, 기 입금된 약정금은 반환한다.\n단, 매수약정인의 귀책이면 매수약정인은 기 입금된 약정금을 포기하고, 매도약정인의 귀책이면 매도약정인은 약정계약금의 배액을 반환하기로 한다.');
          clauses.push(++n + '. 토지거래허가일로부터 5일 이내에 본계약서를 작성하며, 계약서 미체결 시 아래 조항에 따른다.');
        }
        clauses.push(++n + '. 매수인이 약정금 입금 후 계약 효력이 발생하며, 정당한 사유 없이 본계약 체결에 응하지 않거나 본 약정을 일방적으로 철회할 경우, 매수약정인의 귀책이면 매수약정인은 입금된 금액을 포기하고 매도약정인의 귀책이면 매도약정인은 약정계약금의 배액을 배상하기로 한다. 중개사의 과실 없는 해제 시 중개보수는 지급하여야 한다.');
        if (d.mortgage) {
          var mAmt = amt(C.parseMan(d.mortgageAmount), ctx) || '(채권최고액)';
          var holder = String(d.mortgageHolder || '').trim();
          clauses.push(++n + '. 현 등기부등본상 채권최고액 1건 금 ' + mAmt + (holder ? ' (' + holder + ')' : '') + ' 상태의 계약이며, 매도인은 잔금 시 전액 상환 말소한다. (설정해지비용 매도인 부담)');
        }
        clauses.push(++n + '. 매도인은 잔금일까지 채무를 부담하는 등의 새로운 권리변동을 일으키지 않도록 한다.');
        clauses.push(++n + '. 본 특약사항에 기재되지 않은 사항은 민법상 계약에 관한 규정과 부동산매매 일반 관례에 따른다.');

        var address = String(d.address || '').trim();
        var place = prop(d.prop, d.mode);
        var placeLine = [address, place === '(매물)' ? '' : place].filter(Boolean).join(' ');

        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          intro,
          '* 매도인 계좌번호 : ' + (C.accountParse(d.account) || '(계좌번호)') + '\n* 물건지 : ' + (placeLine || '(물건지)'),
          '■ 계약 구성\n' + [
            '* 매매가 : ' + (amt(C.parseMan(d.price), ctx) || '(매매가)'),
            jeongLine,
            gyeyakLine
          ].concat(sub).concat([
            jungLine,
            janLine
          ]).join('\n'),
          splitWarn,
          (C.formatDateTime(d.jeongDate) ? C.formatDateTime(d.jeongDate) + '에 ' + (jeongAmt || '(약정금)') + '을 입금하면 계약의 효력이 발생합니다.'
            : (jeongAmt || '(약정금)') + '을 입금하면 계약의 효력이 발생합니다.'),
          '■ 특약\n' + clauses.join('\n'),
          '위 계약 내용에 동의하시면 매도인께서는 계좌번호를 회신해 주시기 바랍니다.',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't9',
      no: 13,
      stage: 3,
      order: 2,
      icon: 'calendar',
      title: '약정 일정 안내',
      desc: '일시 · 준비물',
      fields: [
        { t: 'property', id: 'prop', label: '매물' },
        { t: 'date', id: 'when', label: '약정 일시' }
      ],
      build: function (d, ctx) {
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          prop(d.prop, d.mode) + ' 약정서 작성 일정 및 준비물을 안내드립니다.',
          '* 일시 : ' + dt(d.when, '약정 일시'),
          '■ 매도인 준비사항\n1. 신분증\n2. 도장\n3. 주민등록등본 (세대원 전원의 주민등록번호 전체 공개)',
          '■ 매수인 준비사항\n1. 신분증\n2. 도장\n3. 주민등록등본 (세대원 전원의 주민등록번호 전체 공개)\n4. 가족관계증명서(상세)\n5. 약정금 (OTP 배터리·이체한도 1일 전 확인 부탁드립니다)\n☆ 공동명의로 취득하시는 경우, 명의자 각각 위 매수인 준비물을 지참해 주시기 바랍니다.',
          '궁금하신 점이 있으시면 언제든 편하게 연락 주세요. 감사합니다!',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't10',
      no: 14,
      stage: 3,
      order: 3,
      icon: 'calendar',
      title: '계약 일정 안내',
      desc: '일시 · 준비물',
      fields: [
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '임대차', l: '임대차' }] },
        { t: 'property', id: 'prop', label: '매물' },
        { t: 'date', id: 'when', label: '계약 일시' },
        { t: 'toggle', id: 'jeongyakReturn', label: '약정금 반환 안내 포함', showIf: function (d) { return d.trade !== '임대차'; } },
        { t: 'toggle', id: 'priority', label: '선순위 권리내역 안내 포함', showIf: function (d) { return d.trade === '임대차'; } }
      ],
      build: function (d, ctx) {
        var place = prop(d.prop, d.mode);
        if (d.trade === '임대차') {
          var seller = '■ 임대인 준비사항\n1. 확정일자 부여현황 (주민센터 발급)\n2. 전입세대 확인서 (전국 주민센터 / 신분증, 기존 임대차계약서 등 지참)\n3. 국세 납세증명서 (주민센터, 무인민원발급기, 정부24, 세무서, 홈택스)\n4. 지방세 납세증명서 (주민센터, 무인민원발급기, 정부24)\n5. 관리비 세부 내역 (관리사무소)\n6. 신분증\n7. 도장 (서명 가능)';
          var blocks = [
            '안녕하세요, ' + ctx.office + '입니다 😊',
            place + ' 임대차계약 일정 및 준비물을 안내드립니다.',
            '* 일시 : ' + dt(d.when, '계약 일시'),
            seller
          ];
          if (d.priority) {
            blocks.push('■ 선순위 권리내역 추가\n* 기존 임대차계약서를 첨부하여 선순위 임차인들의 보증금액 및 임대차 기간 확인이 필요합니다.');
          }
          blocks.push('■ 임차인 준비사항\n1. 신분증\n2. 도장 (서명 가능)\n3. 계약금 (OTP 배터리·이체한도 1일 전 확인 부탁드립니다)');
          blocks.push('궁금하신 점이 있으시면 언제든 편하게 연락 주세요. 감사합니다!');
          blocks.push(sign(ctx));
          return join(blocks);
        }
        var sellerSale = '■ 매도인 준비사항\n1. 신분증\n2. 도장 (서명 가능)\n3. 등기권리증' +
          (d.jeongyakReturn ? '\n4. 약정금 반환 (OTP 배터리·이체한도 1일 전 확인 부탁드립니다)' : '');
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          place + ' 매매계약 일정 및 준비물을 안내드립니다.',
          '* 일시 : ' + dt(d.when, '계약 일시'),
          sellerSale,
          '■ 매수인 준비사항\n1. 신분증\n2. 도장 (서명 가능)\n3. 계약금 (OTP 배터리·이체한도 1일 전 확인 부탁드립니다)',
          '궁금하신 점이 있으시면 언제든 편하게 연락 주세요. 감사합니다!',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't11',
      no: 15,
      stage: 3,
      order: 4,
      icon: 'pen',
      title: '전자계약 안내',
      desc: '계약 절차 · 전자서명',
      fixed: true,
      fields: [
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '임대차', l: '임대차' }] }
      ],
      build: function (d, ctx) {
        var sale = d.trade !== '임대차';
        var parties = sale ? '매도인과 매수인' : '임대인과 임차인';
        var doc = sale ? '매매계약서' : '임대차계약서';
        var report = sale ? '부동산거래신고' : '임대차계약신고';
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊\n전자계약 진행 순서를 안내드립니다.',
          '1. ' + ctx.office + '에서 계약서를 생성합니다.\n' +
          '2. ' + parties + '에게 카카오톡 또는 문자가 발송됩니다.\n' +
          '본인 명의의 휴대폰에서 부동산 전자계약 앱을 설치하신 뒤 링크를 누르시면 자동으로 ' + doc + '가 열립니다.\n' +
          '내용을 확인하시고, 성함 정자 서명 후 신분증을 촬영해 주시면 됩니다.\n' +
          '3. ' + ctx.office + '에서 전자서명을 진행합니다.\n' +
          '4. ' + report + '가 자동으로 접수됩니다.\n' +
          '5. 계약 완료 후 각자 출력 및 열람이 가능합니다.',
          '진행 중 어려운 점이 있으시면 바로 연락 주세요!',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't12',
      no: 16,
      stage: 3,
      order: 5,
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
          ? '이번 계약은 공동명의이므로 두 분 각각의 자금조달계획서를 작성해 주셔야 합니다. 각자 조달하실 금액과 자금 출처를 기재하시고, 두 분의 합산 총액이 매매대금과 일치하는지 확인해 주세요.'
          : '조달하실 금액과 자금 출처를 기재하시고, 총액이 매매대금과 일치하는지 확인해 주세요.';
        var closing = (joint ? '두 분 모두 제출을' : '제출을') + ' 마치시면 저희에게도 완료 여부를 알려주시면 감사하겠습니다.';
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊\n전자계약 후 자금조달계획서 제출 절차를 안내드립니다.',
          '전자계약을 완료하셨더라도 ‘주택취득자금 조달 및 입주계획서’는 별도로 제출하셔야 하며, 제출 기한은 계약체결일로부터 30일 이내입니다.',
          body,
          '■ 온라인 제출 방법\n국토교통부 부동산거래관리시스템 접속 및 본인인증 로그인 → 해당 계약 조회 → 자금조달 및 입주계획 입력 → 증빙서류 첨부 → 제출 및 접수 상태 확인',
          '■ 준비하실 증빙서류\n' + [
            '* 예금·적금 : 예금잔액증명서 등',
            '* 주식 매도대금 : 주식거래내역서 등',
            '* 기존 주택 매도대금 : 해당 매매계약서',
            '* 전세보증금 반환금 : 기존 임대차계약서',
            '* 금융기관 대출 : 금융거래확인서, 부채증명서 또는 대출신청서 등',
            '* 증여·상속 : 증여세·상속세 신고서 등 관련 증빙자료',
            '* 가족 등 차입금 : 차용증 등 차입 사실과 금액을 확인할 수 있는 자료'
          ].join('\n'),
          closing,
          '진행 중 궁금하신 점이 있으시면 편하게 연락 주세요!',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't20',
      no: 17,
      stage: 4,
      order: 3,
      icon: 'phone',
      title: '전문가·협력업체 소개',
      desc: '대출 · 세무 · 법무 · 입주 서비스',
      fields: [
        { t: 'seg', id: 'vendorCat', label: '분야', wrap: true, options: VENDOR_CATS.map(function (c) { return { v: c, l: c }; }) },
        { t: 'contacts', id: 'vendorContacts', label: '보낼 상담사' }
      ],
      build: function (d, ctx) {
        var cat = VENDOR_CATS.indexOf(d.vendorCat) !== -1 ? d.vendorCat : '대출';
        var intro = VENDOR_INTRO[cat];
        var blocks = [
          '안녕하세요, ' + ctx.office + '입니다 😊',
          intro,
          contactBlock(contactsFor(ctx, cat), selectedFor(d, cat))
        ];
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },

    /* ---------------- 잔금·사후관리 ---------------- */
    {
      id: 't13',
      no: 18,
      stage: 4,
      order: 1,
      icon: 'calendar',
      title: '중도금·잔금 일정 안내',
      desc: '일시 · 준비물 · 입금 정보',
      fields: [
        { t: 'seg', id: 'trade', label: '거래 유형', options: [{ v: '매매', l: '매매' }, { v: '전세', l: '전세' }, { v: '월세', l: '월세' }] },
        { t: 'seg', id: 'kind', label: '일정', options: [{ v: '중도금', l: '중도금' }, { v: '잔금', l: '잔금' }], showIf: function (d) { return d.trade !== '전세' && d.trade !== '월세'; } },
        { t: 'property', id: 'prop', label: '매물' },
        { t: 'toggle', id: 'registry', label: '당일 등기부 확인 안내 포함', showIf: function (d) { return d.trade === '전세' || d.trade === '월세'; } },
        { t: 'toggle', id: 'docs', label: '잔금 구비서류 포함', showIf: function (d) { return d.trade !== '전세' && d.trade !== '월세' && d.kind === '잔금'; } },
        { t: 'group', label: '거래금액' },
        { t: 'money', id: 'price', label: '매매대금', showIf: function (d) { return d.trade !== '전세' && d.trade !== '월세'; } },
        { t: 'money', id: 'deposit', label: '보증금', showIf: function (d) { return d.trade === '전세' || d.trade === '월세'; } },
        { t: 'money', id: 'rent', label: '월차임 (월세일 때만)', showIf: function (d) { return d.trade === '월세'; } },
        { t: 'paytable', id: 'pay', rows: [
          { id: 'gyeyak', label: '계약금', amountId: 'gyeyak', dateId: 'gyeyakDate', rate: true },
          { id: 'jung', label: '중도금', amountId: 'jung', dateId: 'jungDate', rate: true, showIf: function (d) { return d.trade !== '전세' && d.trade !== '월세'; } },
          { id: 'jan', label: '잔금', amountId: 'jan', dateId: 'janDate', auto: true }
        ] },
        { t: 'account', id: 'account', label: '입금 계좌', ph: '예: 국민은행 123456-01-234567 홍길동' }
      ],
      build: function (d, ctx) {
        var place = prop(d.prop, d.mode);
        // 매매가 아니면 중도금이 없으니 일정은 늘 잔금이다
        var isRent = d.trade === '전세' || d.trade === '월세';
        var kind = isRent ? '잔금' : (d.kind || '중도금');
        // 일시는 고른 일정(중도금/잔금) 줄의 날짜를 쓴다. 예전 저장값(d.when)도 그대로 읽는다.
        var whenVal = C.formatDateTime(d.when) || String(d.whenText || '').trim();
        if (!whenVal) {
          whenVal = kind === '잔금'
            ? (C.formatDateTime(d.janDate) || C.formatDateTime(d.jungDate))
            : (C.formatDateTime(d.jungDate) || C.formatDateTime(d.janDate));
        }
        var blocks = [
          '안녕하세요, ' + ctx.office + '입니다 😊',
          place + ' ' + kind + ' 일정 안내드립니다.',
          '* 일시 : ' + (whenVal || '(입금 일시)') +
            (isRent && d.registry
              ? '\n* 당일 제가 본 소재지 등기부를 발급해 새로운 권리변동이 없음을 확인시켜 드린 후 입금 진행하시면 됩니다.'
              : '')
        ];
        // 잔금 = 매매대금(전세·월세는 보증금) − 계약금 − 중도금 — core.paymentSplit 하나로 계산한다
        var split = C.paymentSplit({
          totalMan: C.parseMan(isRent ? d.deposit : d.price),
          gyeyakMan: C.parseMan(d.gyeyak),
          jungMan: isRent ? null : C.parseMan(d.jung)
        });
        var janAmt = split.ok ? amt(split.janMan, ctx) : '';
        var janText = janAmt || (split.over ? '확인 필요 (계약금이 보증금을 넘음)' : '(잔금)');
        var warn = '';
        if (split.over) {
          warn = '※ 계약금' + (isRent ? '' : '·중도금') + ' 합계 ' + amt(split.paidMan, ctx) +
            '이 ' + (isRent ? '보증금 ' : '매매대금 ') + amt(split.baseMan, ctx) + '보다 ' +
            amt(split.overByMan, ctx) + ' 많습니다. 지급액을 다시 확인해 주세요.';
        } else if (split.negative) {
          warn = '※ 지급액에 음수가 있어 잔금을 계산하지 않았습니다. 금액을 다시 확인해 주세요.';
        }
        var rows;
        if (isRent) {
          var dep = amt(C.parseMan(d.deposit), ctx);
          var rent = d.trade === '월세' ? amt(C.parseMan(d.rent), ctx) : '';
          rows = [
            '* 보증금 : ' + (dep || '(보증금)') + (rent ? ' / 월차임 : ' + rent : ''),
            '* 계약금 : ' + (amt(C.parseMan(d.gyeyak), ctx) || '(계약금)'),
            '* 잔금 : ' + janText
          ];
        } else {
          rows = [
            '* 매매대금 : ' + (amt(C.parseMan(d.price), ctx) || '(매매대금)'),
            '* 계약금 : ' + (amt(C.parseMan(d.gyeyak), ctx) || '(계약금)'),
            '* 중도금 : ' + (amt(C.parseMan(d.jung), ctx) || '(중도금)'),
            '* 잔금 : ' + janText
          ];
        }
        blocks.push('■ 금액 세부사항\n' + rows.join('\n'));
        if (warn) blocks.push(warn);
        blocks.push('* 입금 계좌 : ' + (C.accountParse(d.account) || '(계좌번호)'));
        if (d.trade !== '전세' && d.trade !== '월세' && kind === '잔금' && d.docs) {
          blocks.push('■ 매도인 구비서류\n1. 인감도장, 신분증\n2. 매도용 인감증명서 1통 (매수인 인적사항 기재)\n3. 등기권리증\n4. 주민등록초본 1통 (전체 주소 이력 포함)\n5. 관리비·가스비 정산서\n6. 각종 리모컨, 카드키 등 전달품');
          blocks.push('■ 매수인 구비서류\n1. 도장\n2. 매매계약서 원본\n3. 가족관계증명서(상세) : 매수인 각각 본인 기준 발급\n4. 주민등록등본 1통 (세대원 전원 주민등록번호 뒷자리 공개)\n5. 취득세 등 이전비용');
        }
        blocks.push('궁금하신 점이 있으시면 언제든 편하게 연락 주세요. 감사합니다!');
        blocks.push(sign(ctx));
        return join(blocks);
      }
    },
    {
      id: 't14',
      no: 19,
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
          amountLine = '* 거래금액 : 보증금 ' + C.formatWonPlain((depositMan || 0) * 10000) +
            ' / 월차임 ' + C.formatWonPlain((rentMan || 0) * 10000) + ' (환산 ' + C.formatWonPlain(r.amountWon) + ')';
        } else if (r.ok) {
          amountLine = '* 거래금액 : ' + C.formatWonPlain(r.amountWon);
        }
        var moneyLines = r.ok ? [
          '* 거래 유형 : ' + kindLabel + useLabel + ' · ' + r.trade,
          amountLine,
          '* 중개보수 요율 : ' + C.rateLabel(r.ratePct) + '%',
          '* 중개보수(공급가액) : ' + C.formatWonPlain(r.fee),
          r.vatMode === 'none'
            ? '* 부가세 : 별도'
            : '* 부가세 : ' + C.formatWonPlain(r.vat) + ' (' + (r.vatMode === '4' ? '간이과세 4%' : '일반과세 10%') + ')',
          '* 합계 : ' + C.formatWonPlain(r.total) + (r.vatMode === 'none' ? ' (부가세 별도)' : '')
        ].concat(r.capped ? ['* 한도액 ' + C.formatWonPlain(r.capWon) + ' 적용'] : []).join('\n') : [
          '* 거래 유형 : ' + kindLabel + ' · ' + (d.calcTrade || '매매'),
          '* 중개보수 요율 : (요율)%',
          '* 중개보수(공급가액) : (중개보수)',
          '* 부가세 : (부가세)',
          '* 합계 : (중개보수)'
        ].join('\n');
        var overLine = r.ok && r.rateOver
          ? '* 요청하신 ' + C.rateLabel(r.requestedPct) + '%는 상한요율 ' + C.rateLabel(r.capRatePct) +
            '%를 넘어 상한요율로 계산했습니다.'
          : '';
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '거래 관련 중개보수 안내드립니다.',
          moneyLines,
          overLine,
          '아래 계좌로 입금해 주시면 됩니다.\n* ' + (ctx.feeAccount || '(입금 계좌)'),
          '입금 후 현금영수증 발행받으실 번호를 문자로 알려주시면 바로 처리해 드리겠습니다. 감사합니다!',
          sign(ctx)
        ]);
      }
    },
    {
      id: 't15',
      no: 20,
      stage: 4,
      order: 4,
      icon: 'key',
      title: '임대차 만기 확인',
      desc: '만기 일정 · 연장·퇴거 의사',
      fields: [
        { t: 'seg', id: 'role', label: '상대방', options: [{ v: '임대인', l: '임대인' }, { v: '임차인', l: '임차인' }] },
        { t: 'number', id: 'months', label: '남은 기간', unit: '개월', min: 1, max: 60 }
      ],
      build: function (d, ctx) {
        var role = d.role === '임차인' ? '임차인' : '임대인';
        var months = String(d.months == null || d.months === '' ? '' : d.months).trim() || '(N)';
        return join([
          '안녕하세요, ' + ctx.office + '입니다 😊',
          '그동안 잘 지내고 계시죠?\n어느새 시간이 흘러 약 ' + months + '개월 후 임대차 만기가 다가오고 있어 안부 겸 연락드렸습니다.',
          '앞으로의 계획이 어떻게 되시는지, ' + role + '분과는 이야기 나눠보셨는지 여쭙고자 합니다.',
          '* 퇴거를 계획 중이시라면 ' + role + '분과 일정 및 조건 조율을 도와드리겠습니다.\n* 연장을 계획 중이시라면 연장계약서 작성을 깔끔히 도와드리겠습니다.',
          '마포래미안푸르지오 단지 내 상가에 있으니 편하게 차 한잔하시러 들러주셔도 좋고, 편하신 시간에 연락 주셔도 좋습니다. 감사합니다!',
          sign(ctx)
        ]);
      }
    }
  ];

  var STAGES = [
    { v: 'all', l: '전체' },
    { v: '1', l: '고객 응대·매물 관리' },
    { v: '2', l: '집보기·방문 안내' },
    { v: '3', l: '약정·계약 진행' },
    { v: '4', l: '잔금·사후관리' }
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

  var DEFAULT_SEL = { '대출': [], '세무': [], '법무사': [], '인테리어': [], '입주청소': [], '이사업체': [] };

  function defaultVendorSel() {
    return JSON.parse(JSON.stringify(DEFAULT_SEL));
  }

  // 저장된 연락처가 없을 때 처음 넣어 둘 값
  function defaultContacts() {
    return JSON.parse(JSON.stringify(DEFAULT_CONTACTS));
  }

  function defaultData(t) {
    var d = { mode: 'ho' };
    if (t.id === 't4' || t.id === 't2' || t.id === 't9' || t.id === 't10' || t.id === 't13' || t.id === 't8') d.prop = defaultProp();
    if (t.id === 't5' || t.id === 't7' || t.id === 't19') d.items = [defaultProp()];
    if (t.id === 't5') { d.status = 'confirmed'; d.detail = true; d.parking = true; }
    if (t.id === 't2') { d.moveinMode = '고정'; d.movein = { date: '', hour: null, min: 0 }; d.moveinText = ''; d.moveinStart = { date: '', hour: null, min: 0 }; d.moveinEnd = { date: '', hour: null, min: 0 }; }
    if (t.id === 't3') { d.ver = 'simple'; d.guest = '매수'; d.times = ''; }
    if (t.id === 't10' || t.id === 't13') d.trade = '매매';
    if (t.id === 't13') d.kind = '중도금';
    if (t.id === 't8') d.address = '서울시 마포구 아현동 777 외 3필지';
    if (t.id === 't11') d.trade = '매매';
    if (t.id === 't12') d.owner = '공동';
    if (t.id === 't15') { d.role = '임대인'; d.months = 2; }
    if (t.id === 't14') { d.calcKind = 'house'; d.calcTrade = '매매'; d.calcVat = '4'; }
    if (t.id === 't16') { d.danji = '1단지'; d.trade = '매매'; }
    if (t.id === 't17') { d.target = 'owner'; d.vpick = { owner: 0, coagent: 0, guest: 0 }; d.greet = 'none'; }
    if (t.id === 't18') { d.trade = '매매'; d.moveinMode = '고정'; d.movein = { date: '', hour: null, min: 0 }; d.moveinText = ''; d.moveinStart = { date: '', hour: null, min: 0 }; d.moveinEnd = { date: '', hour: null, min: 0 }; d.guestNote = '염리초 보내고 싶은 학부모입니다'; }
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
    greetingOf: greetingOf,
    variantIndex: variantIndex,
    spotFromUnit: spotFromUnit,
    VENDOR_CATS: VENDOR_CATS,
    VENDOR_INTRO: VENDOR_INTRO,
    DEFAULT_CONTACTS: DEFAULT_CONTACTS,
    defaultContacts: defaultContacts,
    defaultVendorSel: defaultVendorSel,
    selectedFor: selectedFor,
    contactsFor: contactsFor,
    contactBlock: contactBlock
  };
})(typeof window !== 'undefined' ? window : globalThis);
