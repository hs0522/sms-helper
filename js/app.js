/* 마래푸중앙부동산 문자 도우미 — 화면 동작 */
(function () {
  'use strict';

  var C = window.SMSCore;
  var T = window.SMSTemplates;
  var SYNC = window.SMSSync;
  // 화면에 보이는 문구 — 기본 20종 + 영구 수정한 문구 + 내가 만든 문구 (rebuildTemplates 가 채운다)
  var TEMPLATES = [];
  var STAGES = T.STAGES;
  var KEY = 'smshelper.v1';

  var DEFAULT_PROFILE = {
    office: '마래푸중앙부동산',
    phones: '010-4585-7365 / 02-312-7365',
    feeAccount: '',   // 개인 계좌는 기본값에 넣지 않는다 — 내 정보 설정에서 1회 입력(이 기기에만 저장)
    amountMode: 'won_eokman'
  };

  var editDirty = {};   // 본문을 직접 고친 뒤 입력값이 또 바뀐 템플릿 (메모리 전용)
  var rangeState = {};  // 시간대 추가 임시값
  // 약정·계약·잔금 쪽 서류에는 동·호수를 그대로 보여 준다 (단지·층으로 가리지 않음)
  var PLAIN_PROP = { t8: 1, t9: 1, t10: 1, t13: 1, t15: 1 };

  /* ---------------- 저장소 ---------------- */
  var store = {
    profile: Object.assign({}, DEFAULT_PROFILE),
    stars: ['t3', 't4', 't5', 't14'],
    data: {}, texts: {}, contacts: T.defaultContacts(),
    current: 't5', stage: 'all',
    custom: [],          // 내가 만든 문구
    overrides: {},       // 기존 20종을 영구 수정한 본문 (id -> {body, sign})
    sync: { token: '', gistId: '', updatedAt: 0, lastSync: 0 }
  };

  var applyingRemote = false;   // PC·폰에서 받아 온 내용을 넣는 중 (다시 저장하지 않게)
  var lastContent = null;       // 마지막으로 저장한 내용의 열쇠 — 바뀔 때만 동기화한다

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return;
      var o = JSON.parse(raw);
      if (o.profile) store.profile = Object.assign({}, DEFAULT_PROFILE, o.profile);
      if (Array.isArray(o.stars)) store.stars = o.stars;
      if (o.data && typeof o.data === 'object') store.data = o.data;
      if (o.texts && typeof o.texts === 'object') store.texts = o.texts;
      if (o.contacts && typeof o.contacts === 'object') store.contacts = mergeContacts(o.contacts);
      store.custom = SYNC.sanitizeCustom(o.custom);
      store.overrides = SYNC.sanitizeOverrides(o.overrides);
      // 문구 목록은 이 함수가 끝난 뒤 rebuildTemplates 로 만들어진다 — 고른 문구 검사는 그 뒤에 한다
      if (o.current) store.current = String(o.current);
      if (o.stage) store.stage = o.stage;
      if (o.sync && typeof o.sync === 'object') {
        store.sync = {
          token: String(o.sync.token == null ? '' : o.sync.token),
          gistId: String(o.sync.gistId == null ? '' : o.sync.gistId),
          updatedAt: Number(o.sync.updatedAt) || 0,
          lastSync: Number(o.sync.lastSync) || 0
        };
      }
      // 2026-11-25: 중개보수 부가세 기본값이 '미포함(별도)'에서 '간이 4%'로 바뀌었다.
      // 예전 기본값(none)이 저장되어 있으면 한 번만 4%로 옮긴다 (이후 고른 값은 그대로 둔다).
      if (!o.vatDefault4) {
        var d14 = store.data && store.data.t14;
        if (d14 && (d14.calcVat === 'none' || d14.calcVat == null)) d14.calcVat = '4';
        store.vatDefault4 = true;
        save();
      }
    } catch (e) { /* 저장값이 깨졌으면 기본값으로 시작 */ }
  }

  // 저장된 연락처에 빠진 분야(새로 추가된 분야 포함)는 기본값으로 채운다
  function mergeContacts(saved) {
    var base = T.defaultContacts();
    var out = {};
    T.VENDOR_CATS.forEach(function (cat) {
      out[cat] = Array.isArray(saved[cat]) ? saved[cat] : (base[cat] || []);
    });
    return out;
  }

  var saveTimer = null;
  function saveNow() {
    clearTimeout(saveTimer);
    saveTimer = null;
    try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { /* 저장 공간 부족 등은 무시 */ }
  }
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 120);
    noteChange();
  }
  // 내용이 실제로 바뀌었을 때만 updatedAt을 올리고 PC·폰 동기화를 예약한다
  function noteChange() {
    if (applyingRemote) return;
    var key = SYNC.contentKey(store);
    if (key === lastContent) return;
    lastContent = key;
    store.sync.updatedAt = Date.now();
    schedulePush();
  }
  window.addEventListener('beforeunload', saveNow);
  window.addEventListener('pagehide', saveNow);

  /* ---------------- 유틸 ---------------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function tplById(id) {
    for (var i = 0; i < TEMPLATES.length; i++) if (TEMPLATES[i].id === id) return TEMPLATES[i];
    return null;
  }

  /* ---------------- 문구 목록 만들기 (기본 20종 + 영구 수정 + 내 문구) ---------------- */
  function composeBody(item, c) {
    var body = String(item.body == null ? '' : item.body).replace(/\r\n/g, '\n').replace(/\s+$/, '');
    if (item.sign === false) return body;
    return body + (body ? '\n\n' : '') + c.office + ' 드림\n' + c.phones;
  }

  function rebuildTemplates() {
    var list = [];
    T.TEMPLATES.forEach(function (base) {
      var ov = store.overrides ? store.overrides[base.id] : null;
      if (!ov) { list.push(base); return; }
      list.push({
        id: base.id, no: base.no, stage: base.stage, order: base.order,
        icon: base.icon, title: base.title, desc: base.desc,
        fields: [], edited: true, override: ov,
        build: (function (o) { return function (d, c) { return composeBody(o, c); }; })(ov)
      });
    });
    (store.custom || []).forEach(function (ct, i) {
      list.push({
        id: ct.id, no: '', stage: Number(ct.stage) || 1, order: 500 + i,
        icon: 'message', title: ct.title, desc: ct.desc || '내가 만든 문구',
        fields: [], custom: true, entry: ct,
        build: (function (e) { return function (d, c) { return composeBody(e, c); }; })(ct)
      });
    });
    list.sort(function (a, b) {
      if (a.stage !== b.stage) return a.stage - b.stage;
      return (a.order || 0) - (b.order || 0);
    });
    TEMPLATES.length = 0;
    Array.prototype.push.apply(TEMPLATES, list);
  }

  function customById(id) {
    for (var i = 0; i < (store.custom || []).length; i++) if (store.custom[i].id === id) return store.custom[i];
    return null;
  }

  function dataOf(t) {
    // 입력 항목이 없는 문구(내 문구·영구 수정)는 저장할 입력값이 없다
    if (t && (t.custom || t.edited)) return {};
    if (!store.data[t.id]) {
      store.data[t.id] = T.defaultData(t);
    } else {
      // 기본값을 채우기 전에 예전 저장값부터 매물 줄 구조로 옮긴다
      migrateProps(t, store.data[t.id]);
      migrateTrades(t, store.data[t.id]);
      var d = T.defaultData(t);
      for (var k in d) if (!(k in store.data[t.id])) store.data[t.id][k] = d[k];
    }
    if (PLAIN_PROP[t.id]) lockPropModes(t, store.data[t.id]);
    return store.data[t.id];
  }

  // 동·호수를 그대로 노출하는 템플릿 — 예전에 골라 둔 단지·층 표시를 되돌린다
  function lockPropModes(t, data) {
    t.fields.forEach(function (f) {
      var items = [];
      if (f.t === 'props' && Array.isArray(data[f.id])) items = data[f.id];
      else if (f.t === 'property' && data[f.id] && typeof data[f.id] === 'object') items = [data[f.id]];
      items.forEach(function (item) {
        if (item.dongMode !== 'dong') item.dongMode = 'dong';
        if (item.hoMode !== 'ho') item.hoMode = 'ho';
      });
    });
  }

  // 예전에 가격칸에 글로 쳐 둔 값("매매 23억")을 매매/전세/월세 + 만 원 입력값으로 옮긴다
  function migrateProps(t, data) {
    t.fields.forEach(function (f) {
      if (f.t === 'props' && Array.isArray(data[f.id])) {
        data[f.id].forEach(function (item) {
          var patch = C.propMoneyPatch(item);
          if (patch) Object.assign(item, patch);
        });
      } else if (f.t === 'property' && data[f.id] && typeof data[f.id] === 'object') {
        // 예전 t4는 매물 위아래에 따로 있던 거래유형·가격을 매물 줄로 옮긴다
        if (f.price) {
          if (!data[f.id].trade && data.trade) data[f.id].trade = data.trade;
          if (!data[f.id].amount && !data[f.id].deposit && data[f.id].price == null && data.price) data[f.id].price = data.price;
        }
        var patch2 = C.propMoneyPatch(data[f.id]);
        if (patch2) Object.assign(data[f.id], patch2);
      }
    });
    migratePromoProps(t, data);
    migratePropMode(t, data);
  }

  // 예전 "임대차" 하나짜리 거래 유형을 전세/월세로 나눈다 (t13 · t18)
  function migrateTrades(t, data) {
    if (!t || (t.id !== 't13' && t.id !== 't18') || data.trade !== '임대차') return;
    data.trade = C.parseMan(data.rent) != null ? '월세' : '전세';
    if (t.id === 't18' && (data.deposit == null || data.deposit === '') && data.amount != null) data.deposit = data.amount;
  }

  // 예전 특가 매물 홍보(단지·층 + 평형 + 동·호로 빠르게)를 매물 줄 하나로 옮긴다
  function migratePromoProps(t, data) {
    if (t.id !== 't19' || Array.isArray(data.items)) return;
    var item = T.defaultProp();
    if (data.trade === '전세' || data.trade === '월세') item.trade = data.trade;
    if (data.price != null && data.price !== '') item.price = String(data.price);
    var unit = String(data.unit == null ? '' : data.unit);
    var dm = /(\d{2,4})\s*동/.exec(unit);
    var hm = /(\d{2,4})\s*호/.exec(unit);
    if (!dm && !hm) {
      var nums = unit.match(/\d{3,4}/g) || [];
      if (nums.length >= 2) { dm = [0, nums[0]]; hm = [0, nums[1]]; }
    }
    if (dm && hm) {
      item.dong = dm[1];
      item.ho = hm[1];
    } else {
      // 동·호를 못 읽으면 예전 단지·층·평형 글자를 그대로 살려 둔다
      var area = String(data.area == null ? '' : data.area).trim().replace(/\s*(평형|평)$/, '');
      var spot = String(data.spot == null ? '' : data.spot).trim();
      var keep = [spot, area ? area + '평형' : ''].filter(Boolean).join(' ');
      if (keep) { item.typeInfo = keep; item.typeInfoManual = true; }
      item.complex = '';
    }
    data.items = [item];
  }

  // 예전 한 줄짜리 노출 설정(동·호수 / 동·층 / 단지)을 매물 줄의 동·호 배지로 옮긴다
  function migratePropMode(t, data) {
    var mode = data.mode;
    if (!mode || mode === 'ho') return;
    t.fields.forEach(function (f) {
      var items = [];
      if (f.t === 'props' && Array.isArray(data[f.id])) items = data[f.id];
      else if (f.t === 'property' && data[f.id] && typeof data[f.id] === 'object') items = [data[f.id]];
      items.forEach(function (item) {
        if (!item.dongMode) item.dongMode = mode === 'complex' ? 'complex' : 'dong';
        if (!item.hoMode) item.hoMode = mode === 'floor' ? 'floor' : 'ho';
      });
    });
    data.mode = 'ho';
  }
  function ctx() {
    return {
      office: store.profile.office || DEFAULT_PROFILE.office,
      phones: store.profile.phones || DEFAULT_PROFILE.phones,
      feeAccount: store.profile.feeAccount || DEFAULT_PROFILE.feeAccount,
      amountMode: C.normMode(store.profile.amountMode || 'won_eokman'),
      contacts: store.contacts
    };
  }
  function buildText(t) { return t.build(dataOf(t), ctx()); }

  var ICON = window.SMSIcons;
  function iconSvg(name, size) { return ICON ? ICON.svg(name, size || 15) : ''; }
  function dateIcon() { return ICON ? ICON.el('calendar', 13, 'date-ico') : el('span', 'date-ico'); }

  function setCaretByDigits(input, digitIndex) {
    var val = input.value;
    if (digitIndex <= 0) { input.setSelectionRange(0, 0); return; }
    var seen = 0;
    for (var i = 0; i < val.length; i++) {
      if (/[0-9]/.test(val[i])) seen++;
      if (seen === digitIndex) { input.setSelectionRange(i + 1, i + 1); return; }
    }
    input.setSelectionRange(val.length, val.length);
  }

  // 금액 환산 줄 — 원단위와 (억·만) 묶음을 따로 두어 좁은 칸에서도 괄호가 쪼개지지 않게
  function setHint(node, text) {
    if (!node) return;
    node.textContent = '';
    if (!text) return;
    var m = /^(.*?)\s*(\(.*\))$/.exec(text);
    if (!m) { node.textContent = text; return; }
    node.appendChild(document.createTextNode(m[1]));
    node.appendChild(document.createTextNode(' '));
    node.appendChild(el('span', 'hint-ko', m[2]));
  }

  // 금액 칸에 친 글을 만 원 숫자로 바꾸고 자릿수 쉼표·도우미를 다시 그린다
  function formatMoneyInput(inp) {
    var caret = inp.selectionStart;
    var before = String(inp.value).slice(0, caret).replace(/[^0-9]/g, '').length;
    var man = C.parseMan(inp.value);
    inp.value = man == null ? '' : C.group(man);
    if (man != null && document.activeElement === inp) setCaretByDigits(inp, before);
    var field = inp.closest ? inp.closest('.money-field') : null;
    var hint = field && field.querySelector('.money-hint');
    setHint(hint, C.moneyHintLine(man));
    return man;
  }

  function toast(msg) {
    var box = $('#toast');
    box.textContent = msg;
    box.classList.add('is-on');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { box.classList.remove('is-on'); }, 1800);
  }

  /* ---------------- 스낵바 (되돌리기) ---------------- */
  var snackUndo = null;

  function showSnack(msg, undo) {
    var box = $('#snackbar');
    if (!box) return;
    $('#snackbar-text').textContent = msg;
    snackUndo = typeof undo === 'function' ? undo : null;
    $('#snackbar-undo').hidden = !snackUndo;
    box.classList.add('is-on');
    clearTimeout(showSnack._t);
    showSnack._t = setTimeout(hideSnack, 5000);
  }

  function hideSnack() {
    clearTimeout(showSnack._t);
    var box = $('#snackbar');
    if (box) box.classList.remove('is-on');
    snackUndo = null;
  }

  /* ---------------- 화면 준비 ---------------- */

  /* ---------------- 목록 ---------------- */
  // 왼쪽 목록에는 개수·단계 이름 같은 머리글을 두지 않는다.
  // 검색 중일 때만 '검색 결과 · N개'를 보여 준다.
  function renderList(container, opts) {
    opts = opts || {};
    container.innerHTML = '';
    var q = ($('#search') && $('#search').value || '').trim();
    var stage = opts.ignoreStage ? 'all' : store.stage;
    var list = TEMPLATES.filter(function (t) {
      if (stage !== 'all' && String(t.stage) !== stage) return false;
      if (!q) return true;
      var hay = (t.icon + ' ' + t.title + ' ' + t.desc + ' ' + t.no).toLowerCase();
      return hay.indexOf(q.toLowerCase()) !== -1;
    });

    if (opts.withFavorites && !opts.ignoreStage && stage === 'all' && !q) {
      var favs = TEMPLATES.filter(function (t) { return store.stars.indexOf(t.id) !== -1; });
      if (favs.length) {
        container.appendChild(el('div', 'list-head', '★ 즐겨찾기'));
        favs.forEach(function (t) { container.appendChild(listRow(t)); });
      }
    }
    if (q) container.appendChild(el('div', 'list-head', '검색 결과 · ' + list.length + '개'));
    if (!list.length) container.appendChild(el('div', 'list-empty', '해당하는 문자가 없어요'));
    var lastStage = null;
    list.forEach(function (t) {
      if (stage === 'all' && !q && t.stage !== lastStage) {
        lastStage = t.stage;
        container.appendChild(el('div', 'list-stage', stageLabel(t.stage) + ' · ' + stageCount(t.stage) + '종'));
      }
      container.appendChild(listRow(t));
    });
  }

  function stageLabel(v) {
    var s = STAGES.filter(function (x) { return x.v === String(v); })[0];
    return s ? s.l : '';
  }

  function stageCount(v) {
    return TEMPLATES.filter(function (t) { return String(t.stage) === String(v); }).length;
  }

  function listRow(t) {
    var row = el('div', 'row' + (t.id === store.current ? ' is-active' : ''));
    row.setAttribute('role', 'button');
    row.tabIndex = 0;
    row.dataset.id = t.id;
    var main = el('button', 'row-main');
    main.dataset.id = t.id;
    main.setAttribute('aria-label', (t.no ? t.no + '번 ' : '') + t.title);
    if (ICON) main.appendChild(ICON.el(t.icon, 15, 'row-icon'));
    else main.appendChild(el('span', 'row-icon', ''));
    var wrap = el('span', 'row-text');
    var titleLine = el('span', 'row-title');
    if (t.no !== '' && t.no != null) titleLine.appendChild(el('span', 'row-no', String(t.no)));
    titleLine.appendChild(el('span', 'row-title-text', t.title));
    if (t.custom || t.edited) titleLine.appendChild(el('span', 'row-badge', t.custom ? '내 문구' : '수정됨'));
    wrap.appendChild(titleLine);
    wrap.appendChild(el('span', 'row-desc', t.desc || ''));
    main.appendChild(wrap);
    var star = el('button', 'row-star' + (store.stars.indexOf(t.id) !== -1 ? ' is-on' : ''), '★');
    star.dataset.star = t.id;
    star.setAttribute('aria-label', '즐겨찾기');
    row.appendChild(main);
    row.appendChild(star);
    return row;
  }

  function selectTemplate(id) {
    if (!tplById(id)) return;
    store.current = id;
    save();
    closeSheet();
    renderAll();
  }

  /* ---------------- 상단 탭 ---------------- */
  function renderTabs() {
    var box = $('#stage-tabs');
    box.innerHTML = '';
    STAGES.forEach(function (s) {
      var b = el('button', 'tab' + (store.stage === s.v ? ' is-active' : ''), s.l);
      b.dataset.stage = s.v;
      box.appendChild(b);
    });
  }

  /* ---------------- 입력 폼 ---------------- */
  function renderForm() {
    var t = tplById(store.current);
    var data = dataOf(t);
    var box = $('#fields');
    box.innerHTML = '';
    $('#form-title').innerHTML = iconSvg(t.icon, 15) + '<span class="title-text"></span>';
    var titleText = $('#form-title .title-text');
    if (titleText) titleText.textContent = t.title;

    if (t.custom || t.edited) {
      var note = el('div', 'fixed-note');
      note.appendChild(el('div', 'fixed-note-title', t.custom ? '내가 만든 문구' : '영구 수정한 문구입니다'));
      note.appendChild(el('div', 'fixed-note-body', t.custom
        ? '오른쪽 미리보기 그대로 문자로 나갑니다. 본문은 미리보기 머리의 「문구 편집」에서 고칠 수 있어요.'
        : '이 문구는 「문구 편집」으로 저장한 본문을 그대로 보냅니다. 「기본값으로」를 누르면 원래 20종 문구로 돌아갑니다.'));
      box.appendChild(note);
    } else if (t.fixed) {
      var fixedNote = el('div', 'fixed-note');
      fixedNote.appendChild(el('div', 'fixed-note-title', '입력할 항목이 없습니다'));
      fixedNote.appendChild(el('div', 'fixed-note-body', '오른쪽 미리보기를 그대로 복사하거나, 필요한 부분만 직접 고쳐서 보내세요.'));
      box.appendChild(fixedNote);
    }

    var resetBtn = $('#btn-reset');
    if (resetBtn) resetBtn.hidden = !!(t.custom || t.edited);

    t.fields.forEach(function (f) {
      if (f.showIf && !f.showIf(data)) return;
      box.appendChild(renderField(t, f, data));
    });

    if (t.fixed || t.fields.length) { /* 인라인 안내는 아래에서 한번에 */ }

    if (t.id === 't8' || t.id === 't13' || t.id === 't15') {
      // 금액 표시 형식 안내 (설정값)
      var hint = el('div', 'form-hint');
      var modeLabel = { won: '만원 단위', eokman: '끊어읽기' }[C.normMode(store.profile.amountMode)] || '전체';
      hint.innerHTML = '금액 표시 : <b>' + modeLabel + '</b> · <button class="link" id="open-settings-2" type="button">변경</button>';
      box.appendChild(hint);
      var b2 = $('#open-settings-2');
      if (b2) b2.addEventListener('click', openSettings);
    }
    validateInline();
  }

  function fieldRow(label, opts) {
    opts = opts || {};
    var row = el('div', 'field' + (opts.wide ? ' is-wide' : ''));
    if (label) {
      var head = el('div', 'field-head');
      head.appendChild(el('label', 'field-label', label));
      if (opts.hintText) head.appendChild(el('span', 'field-hint', opts.hintText));
      row.appendChild(head);
    }
    return row;
  }

  // 금액 칸 한 벌 — 숫자는 왼쪽, 칸 안 오른쪽에 '만원', 바로 아래 줄에 원단위·억 환산
  function moneyField(o) {
    var field = el('div', 'money-field' + (o.small ? ' is-sm' : ''));
    var box = el('div', 'money-box');
    var inp = el('input', 'inp inp-money');
    inp.type = 'text';
    inp.inputMode = 'numeric';
    inp.autocomplete = 'off';
    inp.placeholder = o.ph || '0';
    if (o.field) inp.dataset.field = o.field;
    if (o.prop) {
      inp.dataset.prop = o.prop;
      if (o.idx != null) inp.dataset.idx = o.idx;
      inp.dataset.money = o.money;
    }
    var man = C.parseMan(o.value);
    inp.value = man == null ? '' : C.group(man);
    box.appendChild(inp);
    box.appendChild(el('span', 'money-unit', '만원'));
    field.appendChild(box);
    var hintEl = el('div', 'money-hint');
    setHint(hintEl, C.moneyHintLine(man));
    field.appendChild(hintEl);
    return field;
  }

  function moneyWrap(t, f, data) {
    return moneyField({ field: f.id, value: data[f.id], ph: f.ph });
  }

  /* ---------------- 중도금·잔금 자동 계산 ---------------- */
  // t8(약정) · t13(중도금·잔금)의 잔금은 core.paymentSplit 하나로만 계산한다
  function paySplitOf(t, data) {
    if (!t || !data) return null;
    if (t.id === 't8') {
      return C.paymentSplit({
        totalMan: C.parseMan(data.price),
        gyeyakMan: C.parseMan(data.gyeyakAmount),
        jungMan: C.parseMan(data.jungAmount)
      });
    }
    if (t.id === 't13') {
      var rentTrade = data.trade === '전세' || data.trade === '월세';
      return C.paymentSplit({
        totalMan: C.parseMan(rentTrade ? data.deposit : data.price),
        gyeyakMan: C.parseMan(data.gyeyak),
        jungMan: rentTrade ? null : C.parseMan(data.jung)
      });
    }
    return null;
  }

  function payBaseLabel(t, data) {
    var rent = data && (data.trade === '전세' || data.trade === '월세');
    return t && t.id === 't13' && rent ? '보증금' : '매매대금';
  }

  // 읽기 전용 잔금 칸 (자동 계산 결과)
  function autoMoneyField(o) {
    var man = o.value == null || o.value === '' || isNaN(Number(o.value)) ? null : Number(o.value);
    var field = el('div', 'money-field is-auto');
    var box = el('div', 'money-box');
    var inp = el('input', 'inp inp-money');
    inp.type = 'text';
    inp.readOnly = true;
    inp.tabIndex = -1;
    inp.setAttribute('aria-label', o.label || '자동 계산 금액');
    inp.dataset.auto = o.id;
    inp.value = man == null ? '' : C.group(man);
    inp.placeholder = o.placeholder || '자동';
    box.appendChild(inp);
    box.appendChild(el('span', 'money-unit', '만원'));
    field.appendChild(box);
    var hintEl2 = el('div', 'money-hint');
    setHint(hintEl2, man == null ? '' : C.moneyHintLine(man));
    field.appendChild(hintEl2);
    return field;
  }

  // 지급 합계 확인 줄 — 맞으면 회색, 넘치면 빨간색
  function payCheck(t, data) {
    var s = paySplitOf(t, data);
    var base = payBaseLabel(t, data);
    var wrap = el('div', 'pay-check');
    wrap.dataset.autofill = '1';
    if (!s || s.reason === 'no-base') {
      wrap.appendChild(el('div', 'pay-check-line', base + '을 넣으면 잔금이 자동으로 계산됩니다'));
      return wrap;
    }
    if (s.negative) {
      wrap.classList.add('is-bad');
      wrap.appendChild(el('div', 'pay-check-line', '음수 금액은 계산할 수 없습니다 · 지급액을 확인해 주세요'));
      return wrap;
    }
    var parts = '계약금 ' + C.formatWonPlain(s.gyeyakMan * 10000);
    if (s.jungMan) parts += ' + 중도금 ' + C.formatWonPlain(s.jungMan * 10000);
    if (s.ok) {
      parts += ' + 잔금 ' + C.formatWonPlain(s.janMan * 10000);
      wrap.appendChild(el('div', 'pay-check-line', parts));
      wrap.appendChild(el('div', 'pay-check-line is-sum',
        '합계 ' + C.formatWonPlain((s.paidMan + s.janMan) * 10000) + ' · ' + base + '과 일치'));
    } else {
      wrap.classList.add('is-bad');
      wrap.appendChild(el('div', 'pay-check-line', parts));
      wrap.appendChild(el('div', 'pay-check-line is-sum',
        '계약금·중도금이 ' + base + '보다 ' + C.formatWonPlain(s.overByMan * 10000) + ' 많아 잔금을 계산할 수 없습니다'));
    }
    return wrap;
  }

  // 입력 중에는 잔금 칸·확인 줄만 다시 그린다(포커스 유지)
  function syncPayUI() {
    var t = tplById(store.current);
    if (!t || (t.id !== 't8' && t.id !== 't13')) return;
    var data = dataOf(t);
    var s = paySplitOf(t, data);
    var man = s && s.ok ? s.janMan : null;
    var inp = $('#fields [data-auto]');
    if (inp) {
      inp.value = man == null ? '' : C.group(man);
      inp.placeholder = s && s.over ? '확인 필요' : '자동';
      var field = inp.closest('.money-field');
      var hint = field && field.querySelector('.money-hint');
      setHint(hint, man == null ? '' : C.moneyHintLine(man));
    }
    // 비율(%) 배지도 금액에 맞춰 다시
    payRows(t).forEach(function (r) {
      if (!r.rate) return;
      var ri = $('#fields [data-pay-rate="' + r.amountId + '"]');
      if (ri && document.activeElement !== ri) ri.value = payRowRate(t, data, r);
    });
    var old = $('#fields [data-paytotal]');
    if (old) old.replaceWith(payTotal(t, data));
    var oldCheck = $('#fields [data-autofill]');
    if (oldCheck) oldCheck.replaceWith(payCheck(t, data));
    // 저장되는 값도 계산 결과로 맞춰 둔다 (음수·초과면 비운다)
    data[t.id === 't8' ? 'janAmount' : 'jan'] = man == null ? '' : man;
  }

  /* ---------------- 지급 일정 표 (매물 스파이더 계약 팝업형) ---------------- */
  function payRows(t) {
    var f = (t.fields || []).filter(function (x) { return x.t === 'paytable'; })[0];
    return (f && f.rows) || [];
  }

  function payBaseMan(t, data) {
    if (!t || !data) return null;
    if (t.id === 't13') {
      var rent = data.trade === '전세' || data.trade === '월세';
      return C.parseMan(rent ? data.deposit : data.price);
    }
    return C.parseMan(data.price);
  }

  function payRowRate(t, data, row) {
    var base = payBaseMan(t, data);
    var man = C.parseMan(data[row.amountId]);
    if (base && man != null) return String(Math.round((man / base) * 1000) / 10);
    return row.id === 'jung' ? '25' : '10';
  }

  // 달력 입력칸 — 값이 있든 없든 폭이 변하지 않게 늘 칸 폭 그대로(100%)로 그린다
  function dateTrigger(fieldId, value, emptyLabel, cls, opts) {
    opts = opts || {};
    var db = el('button', 'date-btn' + (cls ? ' ' + cls : ''));
    db.type = 'button';
    db.dataset.date = fieldId;
    if (opts.dateOnly) db.dataset.dateOnly = '1';
    var label = opts.dateOnly ? C.compactDate(value) : C.compactDateTime(value);
    db.appendChild(dateIcon());
    db.appendChild(el('span', 'date-text' + (label ? '' : ' is-empty'), label || emptyLabel));
    if (label) {
      var clr = el('span', 'date-clear', '×');
      clr.dataset.clearDate = fieldId;
      clr.title = opts.clearTitle || '일시 지우기';
      db.appendChild(clr);
    }
    return db;
  }

  function dateButton(fieldId, value, emptyLabel) {
    return dateTrigger(fieldId, value, emptyLabel, 'is-compact');
  }

  /* 날짜 칸 — 협의 | 고정 | 기간 (매물 스파이더 방식)
     모드를 바꿔도 칸 폭이 흘러가지 않게 본문은 늘 같은 자리·같은 폭으로 그린다. */
  function dateModeField(f, data) {
    var row = fieldRow(f.label);
    var mode = C.dateModeOf(data, f.id);
    var seg = el('div', 'seg is-grid3 date-mode');
    ['협의', '고정', '기간'].forEach(function (m) {
      var b = el('button', 'seg-btn' + (mode === m ? ' is-active' : ''), m);
      b.type = 'button';
      b.dataset.dateMode = f.id;
      b.dataset.value = m;
      b.setAttribute('aria-pressed', mode === m ? 'true' : 'false');
      seg.appendChild(b);
    });
    row.appendChild(seg);
    var body = el('div', 'date-mode-body');
    if (mode === '협의') {
      // 달력 대신 "협의" / "즉시" / "26.12 말"처럼 글자로 적는 칸
      var ft = el('input', 'inp inp-date-free');
      ft.type = 'text';
      ft.autocomplete = 'off';
      ft.placeholder = f.ph || '예: 협의 / 즉시 / 26.12 말';
      ft.dataset.field = f.id + 'Text';
      ft.dataset.dateField = f.id;
      ft.value = data[f.id + 'Text'] == null ? '' : data[f.id + 'Text'];
      body.appendChild(ft);
    } else if (mode === '기간') {
      var rg = el('div', 'date-range');
      rg.appendChild(dateTrigger(f.id + 'Start', data[f.id + 'Start'], '시작일', null,
        { dateOnly: true, clearTitle: '시작일 지우기' }));
      rg.appendChild(el('span', 'range-tilde', '~'));
      rg.appendChild(dateTrigger(f.id + 'End', data[f.id + 'End'], '종료일', null,
        { dateOnly: true, clearTitle: '종료일 지우기' }));
      body.appendChild(rg);
    } else {
      body.appendChild(dateTrigger(f.id, data[f.id], '날짜'));
    }
    row.appendChild(body);
    return row;
  }

  function rateBadge(t, data, r) {
    var wrap = el('span', 'pay-rate');
    var inp = el('input', 'inp pay-rate-inp');
    inp.type = 'text';
    inp.inputMode = 'decimal';
    inp.autocomplete = 'off';
    inp.dataset.payRate = r.amountId;
    inp.setAttribute('aria-label', r.label + ' 비율');
    inp.value = payRowRate(t, data, r);
    wrap.appendChild(inp);
    wrap.appendChild(el('span', 'pay-rate-pct', '%'));
    return wrap;
  }

  function payTotal(t, data) {
    var s = paySplitOf(t, data);
    var base = payBaseLabel(t, data);
    var box = el('div', 'pay-total');
    box.dataset.paytotal = '1';
    var man = null, note = '';
    if (s && s.ok) {
      // 금액이 정확히 맞으면 안내 글자를 두지 않는다 (맞지 않을 때만 빨간 경고)
      man = s.baseMan;
    } else if (s && s.over) {
      man = s.paidMan;
      note = '계약금·중도금이 ' + base + '보다 ' + C.formatWonPlain(s.overByMan * 10000) + ' 많습니다';
      box.classList.add('is-bad');
    } else if (s && s.negative) {
      note = '음수 금액은 계산할 수 없습니다 · 지급액을 확인해 주세요';
      box.classList.add('is-bad');
    } else if (s) {
      man = s.paidMan || null;
      note = base + '을 넣으면 잔금이 자동으로 계산됩니다';
    }
    var line = el('div', 'pay-total-line');
    line.appendChild(el('span', 'pay-total-label', '총합계'));
    line.appendChild(el('b', 'pay-total-value', man == null ? '—' : C.formatWonPlain(man * 10000)));
    box.appendChild(line);
    if (man != null) {
      box.appendChild(el('div', 'pay-total-ko', '(' + C.koreanAmount(man * 10000, { omitWon: true }) + '원)'));
    }
    if (note) box.appendChild(el('div', 'pay-total-note', note));
    return box;
  }

  function renderPayTable(t, data) {
    var box = el('div', 'paytable');
    // 섹션 라벨은 표 박스 왼쪽 위에, 아래 '특약'과 같은 모양으로
    box.appendChild(el('div', 'paytable-title', '지급 일정'));
    var head = el('div', 'paytable-head');
    ['구분', '일정', '금액'].forEach(function (h) { head.appendChild(el('span', null, h)); });
    box.appendChild(head);
    var split = paySplitOf(t, data);
    payRows(t).forEach(function (r) {
      if (r.showIf && !r.showIf(data)) return;
      var line = el('div', 'pay-row' + (r.auto ? ' is-auto' : ''));
      var name = el('div', 'pay-name');
      name.appendChild(el('span', 'pay-name-text', r.label));
      if (r.rate) name.appendChild(rateBadge(t, data, r));
      line.appendChild(name);
      line.appendChild(dateButton(r.dateId, data[r.dateId], '일정'));
      var amount = el('div', 'pay-amount');
      amount.appendChild(r.auto
        ? autoMoneyField({
          id: r.amountId,
          value: split && split.ok ? split.janMan : null,
          placeholder: split && split.over ? '확인 필요' : '자동',
          label: r.label + ' (자동 계산)'
        })
        : moneyWrap(t, { id: r.amountId, ph: '' }, data));
      line.appendChild(amount);
      box.appendChild(line);
    });
    box.appendChild(payTotal(t, data));
    return box;
  }

  function renderField(t, f, data) {
    var row;
    switch (f.t) {
      case 'group':
        row = el('div', 'group-head', f.label);
        return row;

      case 'text': {
        row = fieldRow(f.label);
        var inp = el('input', 'inp');
        inp.type = 'text';
        inp.autocomplete = 'off';
        inp.placeholder = f.ph || '';
        inp.dataset.field = f.id;
        inp.value = data[f.id] == null ? '' : data[f.id];
        row.appendChild(inp);
        return row;
      }

      case 'textarea': {
        row = fieldRow(f.label);
        var ta = el('textarea', 'inp inp-area');
        ta.rows = f.rows || 3;
        ta.placeholder = f.ph || '';
        ta.dataset.field = f.id;
        ta.value = data[f.id] == null ? '' : data[f.id];
        row.appendChild(ta);
        return row;
      }

      case 'money': {
        row = fieldRow(f.label);
        row.appendChild(moneyWrap(t, f, data));
        return row;
      }

      // 잔금처럼 자동으로 계산되는 금액 (t13)
      case 'autoMoney': {
        var sp = paySplitOf(t, data);
        row = fieldRow(f.label, { hintText: (t.id === 't13' && (data.trade === '전세' || data.trade === '월세') ? '보증금 − 계약금' : '매매대금 − 계약금 − 중도금') + ' 자동 계산' });
        row.appendChild(autoMoneyField({
          id: f.id,
          value: sp && sp.ok ? sp.janMan : null,
          placeholder: sp && sp.over ? '확인 필요' : '자동',
          label: f.label
        }));
        row.appendChild(payCheck(t, data));
        return row;
      }

      case 'number': {
        row = fieldRow(f.label);
        var nw = el('div', 'money-wrap');
        var ni = el('input', 'inp inp-money');
        ni.type = 'text';
        ni.inputMode = 'numeric';
        ni.dataset.field = f.id;
        ni.value = data[f.id] == null ? '' : data[f.id];
        nw.appendChild(ni);
        nw.appendChild(el('span', 'money-unit', f.unit || ''));
        row.appendChild(nw);
        return row;
      }

      case 'account': {
        row = fieldRow(f.label, { hintText: '은행·계좌·예금주 순서 상관없이 붙여넣기' });
        var ai = el('input', 'inp');
        ai.type = 'text';
        ai.autocomplete = 'off';
        ai.placeholder = f.ph || '';
        ai.dataset.field = f.id;
        ai.value = data[f.id] == null ? '' : data[f.id];
        row.appendChild(ai);
        var parsed = C.accountParse(data[f.id]);
        if (parsed) {
          var pv = el('div', 'account-preview', '→ ' + parsed);
          row.appendChild(pv);
        }
        return row;
      }

      case 'seg': {
        row = fieldRow(f.label);
        var seg = el('div', 'seg' + (f.wrap ? ' is-wrap' : ''));
        f.options.forEach(function (o) {
          var b = el('button', 'seg-btn' + (data[f.id] === o.v ? ' is-active' : ''), o.l);
          b.type = 'button';
          b.dataset.seg = f.id;
          b.dataset.value = o.v;
          seg.appendChild(b);
        });
        row.appendChild(seg);
        return row;
      }

      // 단지처럼 몇 가지 중에 고르거나 직접 적을 수 있는 칸
      case 'segplus': {
        row = fieldRow(f.label);
        var segp = el('div', 'seg');
        var isPreset = function (v) {
          return f.options.some(function (o) { return o.v === v; });
        };
        f.options.forEach(function (o) {
          var b = el('button', 'seg-btn' + (data[f.id] === o.v ? ' is-active' : ''), o.l);
          b.type = 'button';
          b.dataset.seg = f.id;
          b.dataset.value = o.v;
          segp.appendChild(b);
        });
        row.appendChild(segp);
        var pin = el('input', 'inp is-etc');
        pin.type = 'text';
        pin.autocomplete = 'off';
        pin.placeholder = f.ph || '직접 입력';
        pin.dataset.field = f.id;
        pin.dataset.freeText = '1';
        pin.value = data[f.id] && !isPreset(data[f.id]) ? data[f.id] : '';
        row.appendChild(pin);
        return row;
      }

      case 'variant': {
        var vTarget = T.VARIANTS[data.target] ? data.target : 'owner';
        var vList = T.VARIANTS[vTarget];
        var vIdx = T.variantIndex(data, vTarget) % vList.length;
        row = el('div', 'field is-variant');
        var vHead = el('div', 'field-head');
        vHead.appendChild(el('label', 'field-label', f.label || '문구'));
        vHead.appendChild(el('span', 'field-hint variant-no', (vIdx + 1) + ' / ' + vList.length));
        row.appendChild(vHead);
        var vBtn = el('button', 'ghost action-btn has-ico');
        vBtn.type = 'button';
        vBtn.dataset.action = 'vary';
        vBtn.innerHTML = iconSvg('refresh', 14) + '<span>문구 교체</span>';
        row.appendChild(vBtn);
        return row;
      }

      // 협력업체·상담사 — 저장된 연락처에서 체크해서 보낸다
      case 'contacts': {
        var cat = T.VENDOR_CATS.indexOf(data.vendorCat) !== -1 ? data.vendorCat : '대출';
        var all = (store.contacts && store.contacts[cat]) || [];
        var picked = T.selectedFor(data, cat);
        row = fieldRow(f.label, { hintText: '체크한 상담사만 문자에 들어갑니다' });
        var listBox = el('div', 'contact-list');
        if (!all.length) {
          listBox.appendChild(el('div', 'contact-empty', '저장된 연락처가 없어요 · 아래에서 추가해 주세요'));
        }
        all.forEach(function (c) {
          var on = picked.indexOf(c.id) !== -1;
          var item = el('div', 'contact' + (on ? ' is-on' : ''));
          var chk = el('button', 'contact-check' + (on ? ' is-on' : ''), on ? '✓' : '');
          chk.type = 'button';
          chk.dataset.contactPick = c.id;
          chk.dataset.cat = cat;
          chk.setAttribute('role', 'checkbox');
          chk.setAttribute('aria-checked', on ? 'true' : 'false');
          chk.setAttribute('aria-label', c.name + ' 선택');
          item.appendChild(chk);
          var info = el('div', 'contact-info');
          info.dataset.contactPick = c.id;
          info.dataset.cat = cat;
          info.appendChild(el('div', 'contact-name', c.name));
          info.appendChild(el('div', 'contact-phone', C.formatPhone(c.phone)));
          item.appendChild(info);
          var del = el('button', 'icon-btn contact-del', '×');
          del.type = 'button';
          del.title = '이 연락처 지우기';
          del.dataset.contactDel = c.id;
          del.dataset.cat = cat;
          item.appendChild(del);
          listBox.appendChild(item);
        });
        row.appendChild(listBox);

        var addBox = el('div', 'contact-add');
        var nameInp = el('input', 'inp');
        nameInp.type = 'text';
        nameInp.autocomplete = 'off';
        nameInp.placeholder = '이름 (예: 신한 대출 담당자)';
        nameInp.dataset.contactNew = 'name';
        var phoneInp = el('input', 'inp');
        phoneInp.type = 'tel';
        phoneInp.inputMode = 'tel';
        phoneInp.autocomplete = 'off';
        phoneInp.placeholder = '010-0000-0000';
        phoneInp.dataset.contactNew = 'phone';
        addBox.appendChild(nameInp);
        addBox.appendChild(phoneInp);
        var addBtn = el('button', 'ghost add-btn', '+ 연락처 추가');
        addBtn.type = 'button';
        addBtn.dataset.contactAdd = cat;
        addBox.appendChild(addBtn);
        row.appendChild(addBox);
        return row;
      }

      case 'toggle': {
        row = el('div', 'field is-toggle');
        var lab = el('div', 'toggle-text');
        lab.appendChild(el('div', 'field-label', f.label));
        row.appendChild(lab);
        var tg = el('button', 'switch' + (data[f.id] ? ' is-on' : ''));
        tg.type = 'button';
        tg.dataset.toggle = f.id;
        tg.setAttribute('role', 'switch');
        tg.setAttribute('aria-checked', data[f.id] ? 'true' : 'false');
        tg.appendChild(el('span', 'knob'));
        row.appendChild(tg);
        return row;
      }

      case 'date': {
        if (f.mode3 || f.freeText) return dateModeField(f, data);
        row = fieldRow(f.label);
        row.appendChild(dateTrigger(f.id, data[f.id], '날짜 · 시간 선택'));
        return row;
      }

      case 'property': {
        row = fieldRow(f.label);
        if (!data[f.id] || typeof data[f.id] !== 'object') data[f.id] = T.defaultProp();
        row.appendChild(propItem(f, data[f.id], null, 1, !!PLAIN_PROP[t.id]));
        return row;
      }

      case 'props': {
        row = fieldRow(f.label);
        var list = data[f.id] || [];
        list.forEach(function (item, idx) {
          row.appendChild(propItem(f, item, idx, list.length, !!PLAIN_PROP[t.id]));
        });
        var add = el('button', 'ghost add-btn', '+ 매물 추가');
        add.type = 'button';
        add.dataset.addItem = f.id;
        row.appendChild(add);
        return row;
      }

      case 'times': {
        row = fieldRow(f.label, { hintText: '한 줄에 시간대 하나' });
        var ta2 = el('textarea', 'inp inp-area');
        ta2.rows = 3;
        ta2.placeholder = '예: 2026년 11월 28일 토요일 오전 10시 ~ 오후 12시';
        ta2.dataset.field = f.id;
        ta2.value = data[f.id] == null ? '' : data[f.id];
        row.appendChild(ta2);
        row.appendChild(renderRangeAdd(t, f));
        return row;
      }

      case 'payment': {
        var grp = el('div', 'pay');
        var head = el('div', 'pay-head');
        head.appendChild(el('span', 'pay-label', f.label));
        if (f.auto) head.appendChild(el('span', 'pay-auto-tag', '자동 계산'));
        grp.appendChild(head);
        var main = el('div', 'pay-main');
        var splitAuto = f.auto ? paySplitOf(t, data) : null;
        main.appendChild(f.auto
          ? autoMoneyField({
            id: f.amountId,
            value: splitAuto && splitAuto.ok ? splitAuto.janMan : null,
            placeholder: splitAuto && splitAuto.over ? '확인 필요' : '자동',
            label: f.label + ' (자동 계산)'
          })
          : moneyWrap(t, { id: f.amountId, ph: '' }, data));
        var db2 = dateTrigger(f.dateId, data[f.dateId], '일정', 'is-compact');
        main.appendChild(db2);
        grp.appendChild(main);
        (f.extras || []).forEach(function (x) {
          var sub = el('div', 'pay-extra');
          var lab = el('div', 'field-label', x.label);
          sub.appendChild(lab);
          if (x.t === 'money') sub.appendChild(moneyWrap(t, { id: x.id, ph: '' }, data));
          else {
            var xi = el('input', 'inp');
            xi.type = 'text';
            xi.autocomplete = 'off';
            xi.placeholder = x.ph || '';
            xi.dataset.field = x.id;
            xi.value = data[x.id] == null ? '' : data[x.id];
            sub.appendChild(xi);
          }
          grp.appendChild(sub);
        });
        if (f.auto) grp.appendChild(payCheck(t, data));
        return grp;
      }

      case 'action': {
        row = el('div', 'field is-row');
        var ab = el('button', 'ghost action-btn', f.label);
        ab.type = 'button';
        ab.dataset.action = f.id;
        row.appendChild(ab);
        return row;
      }

      case 'calc':
        return renderCalc(data);

      case 'paytable':
        return renderPayTable(t, data);

      default:
        return el('div', 'field', '');
    }
  }

  function propItem(f, item, idx, count, plain) {
    var box = el('div', 'prop-item');
    var top = el('div', 'prop-top' + (count > 1 ? ' is-removable' : ''));
    top.appendChild(propInput(f, item, idx, 'complex', '단지명', 'is-complex', '예: 마포래미안푸르지오'));
    top.appendChild(propUnitField(f, item, idx, 'dong', plain));
    top.appendChild(propUnitField(f, item, idx, 'ho', plain));
    if (count > 1) {
      var rm = el('button', 'icon-btn', '×');
      rm.type = 'button';
      rm.title = '이 매물 빼기';
      rm.dataset.removeItem = f.id;
      rm.dataset.idx = idx;
      top.appendChild(rm);
    }
    box.appendChild(top);
    if (f.price) box.appendChild(propMoney(f.id, idx, item));
    // 동·호수로 찾은 평형·타입·방향 — 자동으로 채우고, 표에 없으면 직접 적는다
    if (f.typeInfo) box.appendChild(propTypeInfo(f, item, idx));
    return box;
  }

  function propTypeInfo(f, item, idx) {
    var line = el('div', 'prop-type');
    var i = el('input', 'inp inp-type');
    i.type = 'text';
    i.autocomplete = 'off';
    i.placeholder = '평형·타입·방향 (동·호수를 넣으면 자동)';
    i.title = '마래푸 1~4단지 동·라인 표에서 평형·타입·방향을 채웁니다 · 다르면 직접 고쳐 쓰세요';
    i.dataset.prop = f.id;
    if (idx != null) i.dataset.idx = idx;
    i.dataset.key = 'typeInfo';
    var stored = item.typeInfo == null ? '' : String(item.typeInfo).trim();
    i.value = stored || C.maraepuUnit(item.complex, item.dong, item.ho);
    line.appendChild(i);
    return line;
  }

  // 동·호수가 바뀌면 평형·타입·방향을 다시 찾아 칸에 넣는다 (직접 고친 값은 건드리지 않는다)
  function fillTypeInfo(item, box) {
    if (!item || item.typeInfoManual) return;
    var info = C.maraepuUnit(item.complex, item.dong, item.ho);
    if (!info) {
      if (item.typeInfoAuto) { item.typeInfo = ''; item.typeInfoAuto = false; }
    } else {
      item.typeInfo = info;
      item.typeInfoAuto = true;
    }
    var inp = box && box.querySelector('[data-key="typeInfo"]');
    if (inp && document.activeElement !== inp) inp.value = item.typeInfo || '';
  }

  function propInput(f, item, idx, key, ph, cls, title) {
    var i = el('input', 'inp ' + cls);
    i.type = 'text';
    i.autocomplete = 'off';
    i.placeholder = ph;
    i.title = title;
    i.dataset.prop = f.id;
    if (idx != null) i.dataset.idx = idx;
    i.dataset.key = key;
    i.value = item[key] == null ? '' : item[key];
    return i;
  }

  // 동·호 칸 안쪽 오른쪽에 붙는 단위 배지 — 동 ↔ 단지 / 호 ↔ 층
  function propUnitField(f, item, idx, key, plain) {
    var isDong = key === 'dong';
    var wrap = el('div', 'unit-field' + (plain ? ' is-fixed' : ''));
    var inp = propInput(f, item, idx, key, isDong ? '동' : '호수', isDong ? 'is-dong' : 'is-ho',
      isDong ? '동 번호 (예: 208)' : '호수 (예: 1103)');
    inp.inputMode = 'numeric';
    wrap.appendChild(inp);
    if (plain) {
      wrap.appendChild(el('span', 'unit-fixed', isDong ? '동' : '호'));
      return wrap;
    }
    var asComplex = item.dongMode === 'complex';
    var asFloor = item.hoMode === 'floor';
    var alt = isDong ? asComplex : asFloor;

    var btn = el('button', 'unit-toggle' + (alt ? ' is-alt' : ''), isDong ? (asComplex ? '단지' : '동') : (asFloor ? '층' : '호'));
    btn.type = 'button';
    btn.dataset.propUnit = key;
    btn.dataset.unitList = f.id;
    if (idx != null) btn.dataset.idx = idx;
    btn.setAttribute('aria-pressed', alt ? 'true' : 'false');
    btn.setAttribute('aria-label', isDong ? '동·단지 전환' : '호수·층 전환');
    btn.title = isDong
      ? (asComplex ? '지금은 단지로 나갑니다 (208 → 2단지) · 눌러서 동으로' : '지금은 동으로 나갑니다 (208 → 208동) · 눌러서 단지로')
      : (asFloor ? '지금은 층으로 나갑니다 (1203 → 12층) · 눌러서 호수로' : '지금은 호수로 나갑니다 (1203 → 1203호) · 눌러서 층으로');
    wrap.appendChild(btn);
    return wrap;
  }

  // 매매 / 전세 / 월세 + 만 원 금액 (월세는 보증금·월세 두 칸)
  function propMoney(listId, idx, item) {
    var trade = item.trade === '전세' || item.trade === '월세' ? item.trade : '매매';
    var box = el('div', 'prop-money' + (trade === '월세' ? ' is-monthly' : ''));
    var seg = el('div', 'seg is-small is-trade');
    ['매매', '전세', '월세'].forEach(function (v) {
      var b = el('button', 'seg-btn' + (trade === v ? ' is-active' : ''), v);
      b.type = 'button';
      // 숫자 입력이 바로 이어지도록 탭 순서에서는 건너뛴다(마우스로 고른다)
      b.tabIndex = -1;
      b.dataset.propTrade = listId;
      if (idx != null) b.dataset.idx = idx;
      b.dataset.value = v;
      seg.appendChild(b);
    });
    box.appendChild(seg);
    if (trade === '월세') {
      var pair = el('div', 'money-pair');
      pair.appendChild(propMoneyLine(listId, idx, 'deposit', '보증금', item.deposit));
      pair.appendChild(propMoneyLine(listId, idx, 'rent', '월세', item.rent));
      box.appendChild(pair);
    } else {
      box.appendChild(propMoneyWrap(listId, idx, 'amount', item.amount));
    }
    return box;
  }

  function propMoneyLine(listId, idx, key, label, value) {
    var line = el('div', 'money-line');
    line.appendChild(el('span', 'money-label', label));
    line.appendChild(propMoneyWrap(listId, idx, key, value));
    return line;
  }

  function propMoneyWrap(listId, idx, key, value) {
    return moneyField({ prop: listId, idx: idx, money: key, value: value, small: true });
  }

  function hourOptions(sel) {
    var out = [];
    for (var h = 0; h < 24; h++) {
      for (var m = 0; m < 60; m += 30) {
        out.push({ v: h + ':' + m, l: C.formatTime(h, m) });
      }
    }
    return out;
  }

  function renderRangeAdd(t, f) {
    var rs = rangeState[t.id] = rangeState[t.id] || { date: null, start: '10:0', end: '12:0' };
    var box = el('div', 'range-add');
    var db = dateTrigger(f.id + '__range', rs.date ? { date: rs.date } : null, '날짜', 'is-compact', { dateOnly: true });
    box.appendChild(db);

    ['start', 'end'].forEach(function (k, i) {
      if (i === 1) box.appendChild(el('span', 'range-tilde', '~'));
      var sel = el('select', 'sel');
      sel.dataset.rangeTime = k;
      hourOptions().forEach(function (o) {
        var op = el('option', null, o.l);
        op.value = o.v;
        if (rs[k] === o.v) op.selected = true;
        sel.appendChild(op);
      });
      box.appendChild(sel);
    });

    var add = el('button', 'ghost add-btn', '추가');
    add.type = 'button';
    add.dataset.rangeAdd = f.id;
    box.appendChild(add);
    return box;
  }

  /* ---------------- 중개보수 계산기 ---------------- */
  function calcResultData(data) {
    return C.feeCalc({
      kind: data.calcKind || 'house',
      trade: data.calcTrade || '매매',
      officetelUse: data.calcOffice || 'resident',
      amountMan: C.parseMan(data.calcAmount),
      depositMan: C.parseMan(data.calcDeposit),
      rentMan: C.parseMan(data.calcRent),
      ratePct: data.calcRate,
      vat: data.calcVat || '4'
    });
  }

  function fillCalcResult(summary, res) {
    var strip = summary.querySelector('.calc-result');
    var hint = summary.querySelector('.calc-hint');
    if (!strip || !hint) return;
    strip.innerHTML = '';
    hint.innerHTML = '';
    strip.classList.toggle('is-empty', !res.ok);
    if (res.ok) {
      strip.appendChild(el('div', 'calc-fee', C.formatWonPlain(res.total)));
      // 계산식은 결과 박스 아래에 원단위 금액 표시(.money-hint)처럼 작고 연하게
      var eq = ['중개보수(공급가액) ' + C.formatWonPlain(res.fee)];
      eq.push(res.vatMode === 'none'
        ? '부가세 별도'
        : '부가세 ' + C.formatWonPlain(res.vat) + ' (' + (res.vatMode === '4' ? '간이 4%' : '일반 10%') + ')');
      hint.appendChild(el('div', 'calc-hint-line', eq.join(' · ')));
      var meta = [];
      meta.push('상한 ' + res.capRatePct + '%');
      meta.push(res.converted ? '환산 ' + C.formatWonPlain(res.amountWon) : (res.kindLabel || '주택') + ' ' + res.trade);
      if (res.capped) meta.push('한도액 ' + C.formatWonPlain(res.capWon) + ' 적용');
      hint.appendChild(el('div', 'calc-hint-line', meta.join(' · ')));
      if (res.rateOver) {
        hint.appendChild(el('div', 'calc-hint-line is-warn',
          '상한요율 ' + res.capRatePct + '%를 넘어 요청하신 ' + C.rateLabel(res.requestedPct) + '% 대신 상한요율로 계산했어요'));
      }
    } else {
      strip.appendChild(el('div', 'calc-fee', res.reason === '음수' ? '음수 금액은 계산할 수 없어요' : '금액을 입력해 주세요'));
      hint.appendChild(el('div', 'calc-hint-line', res.reason === '음수' ? '금액을 다시 확인해 주세요' : '계산하면 중개보수가 바로 나옵니다'));
    }
  }

  // 계산기 화면에서 금액을 치는 동안 결과·계산식만 다시 그린다(입력 포커스 유지)
  function syncCalc() {
    var t = tplById(store.current);
    if (!t || !t.fields.some(function (f) { return f.t === 'calc'; })) return;
    var data = dataOf(t);
    var res = calcResultData(data);
    var summary = $('.calc-summary');
    if (summary) fillCalcResult(summary, res);
    var ri = $('[data-field="calcRate"]');
    if (ri) ri.placeholder = res.ok ? String(res.capRatePct) : '0.4';
  }

  function renderCalc(data) {
    var box = el('div', 'calc');

    // 매물 종류
    var kindRow = fieldRow('매물 종류');
    var kseg = el('div', 'seg is-grid4');
    [['house', '주택'], ['officetel', '오피스텔'], ['presale', '분양권'], ['commercial', '상가·토지']].forEach(function (k) {
      var b = el('button', 'seg-btn' + ((data.calcKind || 'house') === k[0] ? ' is-active' : ''), k[1]);
      b.type = 'button';
      b.dataset.seg = 'calcKind';
      b.dataset.value = k[0];
      kseg.appendChild(b);
    });
    kindRow.appendChild(kseg);
    box.appendChild(kindRow);

    // 오피스텔은 전용면적·용도에 따라 요율이 다르다
    if ((data.calcKind || 'house') === 'officetel') {
      var useRow = fieldRow('오피스텔 용도', { hintText: '85㎡ 초과·업무용은 0.9% 이내 협의' });
      var useg = el('div', 'seg');
      [['resident', '85㎡ 이하 주거용'], ['business', '85㎡ 초과·업무용']].forEach(function (k) {
        var b = el('button', 'seg-btn' + ((data.calcOffice || 'resident') === k[0] ? ' is-active' : ''), k[1]);
        b.type = 'button';
        b.dataset.seg = 'calcOffice';
        b.dataset.value = k[0];
        useg.appendChild(b);
      });
      useRow.appendChild(useg);
      box.appendChild(useRow);
    }

    // 거래 유형
    var tradeRow = fieldRow('거래 유형');
    var tseg = el('div', 'seg');
    var trades = data.calcKind === 'presale' ? [['매매', '매매']] : [['매매', '매매'], ['전세', '전세'], ['월세', '월세']];
    trades.forEach(function (k) {
      var b = el('button', 'seg-btn' + ((data.calcTrade || '매매') === k[0] ? ' is-active' : ''), k[1]);
      b.type = 'button';
      b.dataset.seg = 'calcTrade';
      b.dataset.value = k[0];
      tseg.appendChild(b);
    });
    tradeRow.appendChild(tseg);
    box.appendChild(tradeRow);

    // 금액
    if (data.calcTrade === '월세') {
      var dRow = fieldRow('보증금');
      dRow.appendChild(moneyWrap({}, { id: 'calcDeposit' }, data));
      box.appendChild(dRow);
      var rRow = fieldRow('월세');
      rRow.appendChild(moneyWrap({}, { id: 'calcRent' }, data));
      box.appendChild(rRow);
    } else {
      var aRow = fieldRow('거래 금액');
      aRow.appendChild(moneyWrap({}, { id: 'calcAmount' }, data));
      box.appendChild(aRow);
    }

    // 계산 결과 + 적용 요율 — 같은 라벨 줄·같은 높이로 한 줄에 나란히, 계산식은 그 아래 작은 글씨로
    var res = calcResultData(data);
    var summary = el('div', 'calc-summary');
    var top = el('div', 'calc-top');
    var resultCell = el('div', 'calc-cell');
    resultCell.appendChild(el('span', 'calc-cell-label', '중개보수 합계'));
    resultCell.appendChild(el('div', 'calc-result'));
    top.appendChild(resultCell);

    var rateCell = el('div', 'calc-cell is-rate');
    rateCell.appendChild(el('span', 'calc-cell-label', '적용 요율'));
    var rw = el('div', 'money-wrap');
    var ri = el('input', 'inp is-rate');
    ri.type = 'text';
    ri.inputMode = 'decimal';
    ri.autocomplete = 'off';
    ri.placeholder = res.ok ? String(res.capRatePct) : '0.4';
    ri.dataset.field = 'calcRate';
    ri.setAttribute('aria-label', '적용 요율');
    ri.value = data.calcRate == null ? '' : data.calcRate;
    rw.appendChild(ri);
    rw.appendChild(el('span', 'money-unit', '%'));
    rateCell.appendChild(rw);
    top.appendChild(rateCell);
    summary.appendChild(top);
    summary.appendChild(el('div', 'calc-hint'));
    fillCalcResult(summary, res);
    box.appendChild(summary);

    // 부가세 — 고르지 않으면 간이 4%
    var vatRow = fieldRow('부가세', { hintText: '기본 간이 4% · 미포함(별도) / 일반 10%로 바꿀 수 있어요' });
    var vseg = el('div', 'seg is-grid3');
    [['none', '미포함(별도)'], ['4', '간이 4%'], ['10', '일반 10%']].forEach(function (k) {
      var b = el('button', 'seg-btn' + ((data.calcVat || '4') === k[0] ? ' is-active' : ''), k[1]);
      b.type = 'button';
      b.dataset.seg = 'calcVat';
      b.dataset.value = k[0];
      vseg.appendChild(b);
    });
    vatRow.appendChild(vseg);
    box.appendChild(vatRow);

    return box;
  }

  /* ---------------- 미리보기 ---------------- */
  function renderPreview() {
    var t = tplById(store.current);
    var ta = $('#preview');
    var edited = store.texts[t.id] != null;
    ta.value = edited ? store.texts[t.id] : buildText(t);
    $('#btn-restore').disabled = !edited;
    $('#btn-tpl-revert').hidden = !t.edited;
    $('#btn-tpl-edit').textContent = '문구 편집';
    var note = $('#edited-note');
    if (note) {
      note.hidden = !edited;
      if (edited) {
        var head = editDirty[t.id]
          ? '입력값이 바뀌었어요 · 지금은 직접 수정한 본문입니다'
          : '직접 수정한 본문입니다';
        note.innerHTML = head + ' · <button class="link" id="btn-refresh" type="button">입력값으로 새로 만들기</button>';
        var rf = $('#btn-refresh');
        if (rf) rf.addEventListener('click', function () { refreshFromInputs({ snack: true }); });
      }
    }
    var len = ta.value.length;
    $('#char-count').textContent = len ? len.toLocaleString('en-US') + '자' : '';
  }

  function refreshFromInputs(opts) {
    var t = tplById(store.current);
    var before = store.texts[t.id];
    delete store.texts[t.id];
    delete editDirty[t.id];
    save();
    renderPreview();
    if (opts && opts.snack) {
      showSnack('입력값 기준으로 다시 만들었어요', function () {
        if (before == null) return;
        store.texts[t.id] = before;
        save();
        renderPreview();
      });
    }
  }

  function updatePreviewOnly() {
    var t = tplById(store.current);
    if (store.texts[t.id] != null) return;
    var ta = $('#preview');
    ta.value = buildText(t);
    $('#char-count').textContent = ta.value.length ? ta.value.length.toLocaleString('en-US') + '자' : '';
  }

  function renderAll() {
    renderTabs();
    renderList($('#tpl-list'), { withFavorites: true });
    renderList($('#sheet-list'), { ignoreStage: false, withFavorites: false });
    renderForm();
    renderPreview();
    $$('#tpl-list .row').forEach(function (r) { r.classList.toggle('is-active', r.dataset.id === store.current); });
    $$('#sheet-list .row').forEach(function (r) { r.classList.toggle('is-active', r.dataset.id === store.current); });
    // 새 문구를 만들거나 골랐을 때 왼쪽 목록에서 그 줄이 보이게
    var activeRow = $('#tpl-list .row.is-active');
    if (activeRow && activeRow.scrollIntoView) {
      try { activeRow.scrollIntoView({ block: 'nearest' }); } catch (e) { /* 구형 브라우저는 그냥 둔다 */ }
    }
  }

  /* ---------------- 달력 ---------------- */
  var cal = { open: false, fieldId: null, y: 0, m: 0, anchor: null, rangeMode: false, dateOnly: false };

  function openCal(anchor, fieldId) {
    var t = tplById(store.current);
    var data = dataOf(t);
    var value;
    if (fieldId.indexOf('__range') !== -1) {
      cal.rangeMode = true;
      var rs = rangeState[t.id] || {};
      value = rs.date || null;
      cal.fieldId = fieldId.replace('__range', '');
    } else {
      cal.rangeMode = false;
      value = data[fieldId] || null;
      cal.fieldId = fieldId;
    }
    var d = value && value.date ? C.parseDateValue(value) : null;
    var now = new Date();
    cal.y = d ? d.y : now.getFullYear();
    cal.m = d ? d.m : now.getMonth() + 1;
    cal.anchor = anchor;
    cal.dateOnly = !!(anchor && anchor.dataset && anchor.dataset.dateOnly === '1');
    cal.open = true;
    renderCal();
    var pop = $('#calpop');
    pop.hidden = false;
    positionPop(pop, anchor);
  }

  function closeCal() {
    cal.open = false;
    $('#calpop').hidden = true;
  }

  function positionPop(pop, anchor) {
    pop.style.visibility = 'hidden';
    pop.style.left = '0px';
    pop.style.top = '0px';
    var r = anchor.getBoundingClientRect();
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
    var top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
    pop.style.visibility = 'visible';
  }

  function currentCalValue() {
    var t = tplById(store.current);
    var data = dataOf(t);
    if (cal.rangeMode) {
      var rs = rangeState[t.id] || {};
      return rs.date ? { date: rs.date } : null;
    }
    return data[cal.fieldId] || null;
  }

  function renderCal() {
    var pop = $('#calpop');
    pop.innerHTML = '';
    var head = el('div', 'cal-head');
    var prev = el('button', 'cal-nav', '‹');
    prev.type = 'button';
    prev.dataset.calNav = '-1';
    var title = el('div', 'cal-title', cal.y + '년 ' + cal.m + '월');
    var next = el('button', 'cal-nav', '›');
    next.type = 'button';
    next.dataset.calNav = '1';
    head.appendChild(prev);
    head.appendChild(title);
    head.appendChild(next);
    pop.appendChild(head);

    var week = el('div', 'cal-week');
    ['일', '월', '화', '수', '목', '금', '토'].forEach(function (w, i) {
      var c = el('span', 'cal-wd' + (i === 0 ? ' is-sun' : i === 6 ? ' is-sat' : ''), w);
      week.appendChild(c);
    });
    pop.appendChild(week);

    var grid = el('div', 'cal-grid');
    var first = new Date(cal.y, cal.m - 1, 1).getDay();
    var days = new Date(cal.y, cal.m, 0).getDate();
    var today = new Date();
    var val = currentCalValue();
    var vd = val && val.date ? C.parseDateValue(val) : null;
    for (var i = 0; i < first; i++) grid.appendChild(el('span', 'cal-cell is-out'));
    for (var day = 1; day <= days; day++) {
      var dow = new Date(cal.y, cal.m - 1, day).getDay();
      var b = el('button', 'cal-cell' + (dow === 0 ? ' is-sun' : '') + (dow === 6 ? ' is-sat' : ''), String(day));
      b.type = 'button';
      b.dataset.calDay = day;
      if (vd && vd.y === cal.y && vd.m === cal.m && vd.d === day) b.classList.add('is-sel');
      if (today.getFullYear() === cal.y && today.getMonth() + 1 === cal.m && today.getDate() === day) b.classList.add('is-today');
      grid.appendChild(b);
    }
    pop.appendChild(grid);

    if (!cal.rangeMode && !cal.dateOnly) {
      var time = el('div', 'cal-time');
      var cur = (val && typeof val === 'object') ? val : { hour: null, min: 0 };
      var hour = cur.hour == null ? null : Number(cur.hour);
      var period = hour == null ? (new Date().getHours() < 12 ? '오전' : '오후') : (hour < 12 ? '오전' : '오후');
      var pseg = el('div', 'seg is-small');
      ['오전', '오후'].forEach(function (p) {
        var pb = el('button', 'seg-btn' + (period === p ? ' is-active' : ''), p);
        pb.type = 'button';
        pb.dataset.calPeriod = p;
        pseg.appendChild(pb);
      });
      time.appendChild(pseg);

      var hsel = el('select', 'sel is-time');
      hsel.dataset.calHour = '1';
      // 시각을 아직 고르지 않았으면 '1시'로 보이지 않게 빈 칸을 먼저 둔다
      if (hour == null) {
        var hph = el('option', null, '시');
        hph.value = '';
        hph.selected = true;
        hsel.appendChild(hph);
      }
      for (var hh = 1; hh <= 12; hh++) {
        var op = el('option', null, hh + '시');
        op.value = String(hh);
        var h12 = hour == null ? null : (hour % 12 === 0 ? 12 : hour % 12);
        if (h12 === hh) op.selected = true;
        hsel.appendChild(op);
      }
      time.appendChild(hsel);

      var msel = el('select', 'sel is-time');
      msel.dataset.calMin = '1';
      ['0', '10', '20', '30', '40', '50'].forEach(function (mm) {
        var op2 = el('option', null, mm === '0' ? '' : mm + '분');
        op2.value = mm;
        if (String(cur.min || 0) === mm) op2.selected = true;
        msel.appendChild(op2);
      });
      time.appendChild(msel);
      pop.appendChild(time);
    } else if (cal.rangeMode) {
      pop.appendChild(el('div', 'cal-tip', '날짜를 고르면 아래 시간 선택과 함께 문구가 만들어집니다'));
    }

    var foot = el('div', 'cal-foot');
    var reset = el('button', 'ghost cal-reset', '초기화');
    reset.type = 'button';
    reset.dataset.calReset = '1';
    var done = el('button', 'ghost', '닫기');
    done.type = 'button';
    done.dataset.calClose = '1';
    foot.appendChild(reset);
    foot.appendChild(done);
    pop.appendChild(foot);
  }

  function setCalDateTime(fieldId, patch) {
    var t = tplById(store.current);
    var data = dataOf(t);
    if (!data[fieldId] || typeof data[fieldId] !== 'object') data[fieldId] = { date: '', hour: null, min: 0 };
    Object.assign(data[fieldId], patch);
    // 달력으로 날짜를 골랐으면 직접 적은 글자(협의·즉시)는 지운다
    if (patch.date) data[fieldId + 'Text'] = '';
    save();
  }

  /* ---------------- 복사 · 문자 앱 ---------------- */
  function copyText(text, btn) {
    function done() {
      toast('복사했어요');
      if (btn) {
        var lab = btn.querySelector('.btn-label');
        var labelBox = lab || btn;
        var old = labelBox.textContent;
        labelBox.textContent = '복사 완료';
        setTimeout(function () { labelBox.textContent = old; }, 1400);
      }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    // 안드로이드 앱(.apk) 껍데기가 열어 둔 복사 통로
    if (!ok && window.AndroidCopy && window.AndroidCopy.copy) {
      try { window.AndroidCopy.copy(text); ok = true; } catch (e) { ok = false; }
    }
    if (ok) done();
    else toast('복사에 실패했어요. 본문을 길게 눌러 복사해 주세요.');
  }

  // 아이폰·안드로이드 모두 '문자 앱'에 완성 문자가 채워진 채로 열린다
  function smsUrl(text) { return 'sms:&body=' + encodeURIComponent(text); }

  function openSms() {
    var text = $('#preview').value;
    if (!text) { toast('문자 내용이 비어 있어요'); return; }
    // 안드로이드 앱(.apk) 안에서는 인텐트를 직접 띄운다
    if (window.AndroidSms && window.AndroidSms.open) {
      try { window.AndroidSms.open(text); return; } catch (e) { /* 아래 기본 방식으로 */ }
    }
    var a = document.createElement('a');
    a.href = smsUrl(text);
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  /* ---------------- 설정 모달 ---------------- */
  function openSettings() {
    var m = $('#settings');
    $('#set-office').value = store.profile.office;
    $('#set-phones').value = store.profile.phones;
    $('#set-account').value = store.profile.feeAccount;
    $$('[data-set-mode]').forEach(function (b) {
      b.classList.toggle('is-active', b.dataset.setMode === C.normMode(store.profile.amountMode));
    });
    $('#set-account-preview').textContent = C.accountParse(store.profile.feeAccount) ? '→ ' + C.accountParse(store.profile.feeAccount) : '';
    $('#set-gh-token').value = store.sync.token || '';
    $('#set-gh-gist').value = store.sync.gistId || '';
    $('#import-box').hidden = true;
    refreshSyncUi();
    m.classList.add('is-open');
    m.setAttribute('aria-hidden', 'false');
  }

  function closeSettings() {
    var m = $('#settings');
    m.classList.remove('is-open');
    m.setAttribute('aria-hidden', 'true');
  }

  function applySettings() {
    store.profile.office = $('#set-office').value.trim() || DEFAULT_PROFILE.office;
    store.profile.phones = $('#set-phones').value.trim() || DEFAULT_PROFILE.phones;
    store.profile.feeAccount = C.accountParse($('#set-account').value) || DEFAULT_PROFILE.feeAccount;
    save();
    closeSettings();
    renderAll();
    toast('내 정보를 저장했어요');
  }

  /* ---------------- 문구 편집 (내 문구 · 기존 문구 영구 수정) ---------------- */
  var editor = { mode: 'new', id: null };   // mode: new | custom | override

  // 본문 끝에 붙어 있는 '상호 드림 / 연락처' 서명을 떼어 낸다 (편집창에는 본문만 보이게)
  function stripSign(text) {
    var s = String(text == null ? '' : text).replace(/\r\n/g, '\n');
    var c = ctx();
    var tail = '\n\n' + c.office + ' 드림\n' + c.phones;
    if (s.slice(-tail.length) === tail) return s.slice(0, -tail.length).replace(/\s+$/, '');
    var m = /\n\n[^\n]{1,40} 드림\n[0-9+()\- ]{7,30}\s*$/.exec(s);
    if (m) return s.slice(0, m.index).replace(/\s+$/, '');
    return s;
  }

  function cleanBody(text) {
    // 문자 본문에는 대괄호가 나가지 않는 규칙을 그대로 지킨다
    return String(text == null ? '' : text)
      .replace(/\r\n/g, '\n')
      .replace(/\[/g, '(')
      .replace(/\]/g, ')')
      .replace(/\s+$/, '');
  }

  function defaultStageForNew() {
    if (store.stage && store.stage !== 'all') return String(store.stage);
    var cur = tplById(store.current);
    return cur ? String(cur.stage) : '1';
  }

  function openTemplateEditor(mode, id) {
    var m = $('#tpl-editor');
    if (!m) return;
    editor.mode = mode;
    editor.id = id || null;
    var stageSel = $('#te-stage');
    var delBtn = $('#btn-tpl-editor-del');
    var tip = $('#te-tip');

    if (mode === 'override') {
      var t = tplById(id);
      if (!t) return;
      var ov = store.overrides[id];
      var body, sign;
      if (ov) {
        body = ov.body;
        sign = ov.sign !== false;
      } else {
        var full = $('#preview').value || buildText(t);
        body = stripSign(full);
        sign = body !== full;
      }
      $('#tpl-editor-title').textContent = '문구 편집 — 영구 저장';
      stageSel.value = String(t.stage);
      stageSel.disabled = true;
      $('#te-title').value = t.title;
      $('#te-title').disabled = true;
      $('#te-desc').value = t.desc || '';
      $('#te-desc').disabled = true;
      $('#te-body').value = body;
      $('#te-sign').checked = sign;
      delBtn.hidden = true;
      tip.textContent = '저장하면 이 문구는 고정 본문으로 바뀝니다(입력 항목은 숨겨짐). 미리보기에서 한 번만 고치는 것과 달리 계속 남습니다 — 「기본값으로」로 언제든 되돌릴 수 있어요. 대괄호 [ ]는 소괄호 ( )로 바뀌어 저장됩니다.';
    } else {
      var cur = mode === 'custom' ? customById(id) : null;
      $('#tpl-editor-title').textContent = cur ? '내 문구 편집' : '새 문구 추가';
      stageSel.value = cur ? String(cur.stage) : defaultStageForNew();
      stageSel.disabled = false;
      $('#te-title').value = cur ? cur.title : '';
      $('#te-title').disabled = false;
      $('#te-desc').value = cur ? cur.desc : '';
      $('#te-desc').disabled = false;
      $('#te-body').value = cur ? cur.body : '';
      $('#te-sign').checked = cur ? cur.sign !== false : true;
      delBtn.hidden = !cur;
      tip.textContent = '저장하면 목록에 바로 나오고, 이 기기에 저장됩니다. 대괄호 [ ]는 소괄호 ( )로 바뀌어 저장됩니다.';
    }

    closeSheet();
    m.classList.add('is-open');
    m.setAttribute('aria-hidden', 'false');
    setTimeout(function () {
      if (mode === 'override') { $('#te-body').focus(); }
      else { $('#te-title').focus(); }
    }, 40);
  }

  function closeTemplateEditor() {
    var m = $('#tpl-editor');
    if (!m) return;
    m.classList.remove('is-open');
    m.setAttribute('aria-hidden', 'true');
  }

  function afterTemplateChange() {
    rebuildTemplates();
    if (!tplById(store.current)) store.current = TEMPLATES[0] ? TEMPLATES[0].id : 't1';
    // 지금 고른 카테고리에 없는 문구라면 전체 목록으로 돌려 목록에서 보이게 한다
    var cur = tplById(store.current);
    if (cur && cur.custom && store.stage !== 'all' && String(store.stage) !== String(cur.stage)) {
      store.stage = 'all';
    }
    save();
    renderAll();
  }

  function saveTemplateEditor() {
    var body = cleanBody($('#te-body').value);
    if (!body.trim()) { toast('본문을 먼저 적어 주세요'); $('#te-body').focus(); return; }
    var sign = $('#te-sign').checked;

    if (editor.mode === 'override') {
      var t = tplById(editor.id);
      if (!t) return;
      var before = store.overrides[editor.id]
        ? JSON.parse(JSON.stringify(store.overrides[editor.id])) : null;
      store.overrides[editor.id] = { body: body, sign: sign };
      delete store.texts[editor.id];
      delete editDirty[editor.id];
      closeTemplateEditor();
      afterTemplateChange();
      showSnack('「' + t.title + '」 문구를 영구 저장했어요', function () {
        if (before) store.overrides[editor.id] = before;
        else delete store.overrides[editor.id];
        afterTemplateChange();
      });
      return;
    }

    var title = $('#te-title').value.trim();
    if (!title) { toast('제목을 먼저 적어 주세요'); $('#te-title').focus(); return; }
    var stage = String($('#te-stage').value || '1');
    var desc = $('#te-desc').value.trim();

    if (editor.mode === 'custom' && customById(editor.id)) {
      var cur = customById(editor.id);
      cur.stage = stage;
      cur.title = title;
      cur.desc = desc;
      cur.body = body;
      cur.sign = sign;
      closeTemplateEditor();
      afterTemplateChange();
      toast('문구를 고쳤어요');
      return;
    }

    var id = 'c' + Date.now().toString(36) + Math.floor(Math.random() * 1000).toString(36);
    store.custom.push({ id: id, stage: stage, title: title, desc: desc, body: body, sign: sign });
    store.current = id;
    closeTemplateEditor();
    afterTemplateChange();
    toast('새 문구를 저장했어요');
  }

  function deleteCustomTemplate() {
    var ct = editor.id ? customById(editor.id) : null;
    if (!ct) return;
    if (!window.confirm('「' + ct.title + '」 문구를 삭제할까요?')) return;
    var idx = store.custom.indexOf(ct);
    var snap = JSON.parse(JSON.stringify(ct));
    var starIdx = store.stars.indexOf(ct.id);
    store.custom.splice(idx, 1);
    if (starIdx !== -1) store.stars.splice(starIdx, 1);
    if (store.current === ct.id) store.current = 't1';
    closeTemplateEditor();
    afterTemplateChange();
    showSnack('문구를 삭제했어요', function () {
      store.custom.splice(Math.min(idx, store.custom.length), 0, snap);
      if (starIdx !== -1) store.stars.splice(Math.min(starIdx, store.stars.length), 0, snap.id);
      store.current = snap.id;
      afterTemplateChange();
    });
  }

  function revertTemplate() {
    var t = tplById(store.current);
    if (!t || !t.edited) return;
    var before = JSON.parse(JSON.stringify(store.overrides[t.id]));
    var title = t.title;
    delete store.overrides[t.id];
    afterTemplateChange();
    showSnack('「' + title + '」을 기본 문구로 되돌렸어요', function () {
      store.overrides[t.id] = before;
      afterTemplateChange();
    });
  }

  /* ---------------- PC·폰 백업 · 불러오기 ---------------- */
  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function exportJson() {
    var snap = SYNC.snapshot(store);
    if (!snap.updatedAt) snap.updatedAt = Date.now();
    return JSON.stringify(snap, null, 2);
  }

  function exportCopy(btn) {
    copyText(exportJson(), btn);
  }

  function exportFile() {
    var text = exportJson();
    var d = new Date();
    var name = '문자도우미_백업_' + d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + '.json';
    var blob = new Blob([text], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
    toast('백업 파일을 내려받았어요');
  }

  function applyImport(text) {
    var snap = SYNC.parse(text);
    if (!snap) { toast('불러올 수 없는 내용이에요'); return false; }
    applyingRemote = true;
    var changed = false;
    try {
      changed = SYNC.apply(store, snap);
      store.contacts = mergeContacts(store.contacts);
    } finally {
      applyingRemote = false;
    }
    lastContent = SYNC.contentKey(store);
    rebuildTemplates();
    if (!tplById(store.current)) store.current = TEMPLATES[0] ? TEMPLATES[0].id : 't1';
    saveNow();
    renderAll();
    $('#import-box').hidden = true;
    $('#import-text').value = '';
    closeSettings();
    if (ghConnected()) schedulePush();
    toast(changed ? '불러왔어요' : '이미 같은 내용이에요');
    return true;
  }

  /* ---------------- PC·폰 자동 동기화 (GitHub Gist) ---------------- */
  var syncUi = { timer: null, busy: false, again: false };

  function ghConnected() { return !!(store.sync && store.sync.token && store.sync.gistId); }

  function shortId(id) {
    var s = String(id || '');
    return s.length > 10 ? s.slice(0, 6) + '…' : s;
  }

  function timeLabel(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function syncBadge(state, label) {
    var b = $('#sync-status');
    if (!b) return;
    if (!state) { b.hidden = true; return; }
    b.hidden = false;
    b.dataset.state = state;
    b.textContent = label;
  }

  function syncLine(msg) {
    var n = $('#gh-status');
    if (n) n.textContent = msg;
  }

  function refreshSyncUi() {
    var off = $('#btn-gh-off');
    if (off) off.hidden = !ghConnected();
    if (ghConnected()) {
      if (store.sync.lastSync) {
        syncBadge('ok', '동기화됨');
        syncLine('연결됨 · Gist ' + shortId(store.sync.gistId) + ' · 마지막 동기화 ' + timeLabel(store.sync.lastSync));
      } else {
        syncBadge('pending', '연결됨');
        syncLine('연결됨 · Gist ' + shortId(store.sync.gistId) + ' · 아직 동기화 전');
      }
    } else {
      syncBadge(null);
      syncLine('연결하면 앱을 열 때 자동으로 불러오고, 문구를 고치면 자동으로 저장합니다.');
    }
  }

  function syncFail(err) {
    var offline = !!(err && err.offline);
    syncBadge('off', offline ? '오프라인' : '동기화 실패');
    syncLine((err && err.message) || '동기화에 실패했어요');
    return false;
  }

  function markSynced() {
    store.sync.lastSync = Date.now();
    saveNow();
    syncBadge('ok', '동기화됨');
    syncLine('연결됨 · Gist ' + shortId(store.sync.gistId) + ' · 마지막 동기화 ' + timeLabel(store.sync.lastSync));
  }

  // 기기에서 한 번도 안 바뀐 저장값(updatedAt 0)도 처음 올릴 때 시각을 붙여 둔다
  function stampedSnapshot() {
    if (!store.sync.updatedAt) store.sync.updatedAt = Date.now();
    return SYNC.snapshot(store);
  }

  function pushSnapshot() {
    return SYNC.updateGist(store.sync.token, store.sync.gistId, stampedSnapshot()).then(function () {
      markSynced();
      return true;
    });
  }

  function applyRemote(snap, opts) {
    applyingRemote = true;
    try {
      SYNC.apply(store, snap);
      store.contacts = mergeContacts(store.contacts);
    } finally {
      applyingRemote = false;
    }
    lastContent = SYNC.contentKey(store);
    rebuildTemplates();
    if (!tplById(store.current)) store.current = TEMPLATES[0] ? TEMPLATES[0].id : 't1';
    markSynced();
    renderAll();
    if (!(opts && opts.silent)) toast('PC·폰의 최신 내용으로 맞췄어요');
    return true;
  }

  // 최신(updatedAt) 쪽으로 맞춘다 — 받아 올 것이 없으면 올린다
  function syncNow(opts) {
    opts = opts || {};
    if (!ghConnected()) return Promise.resolve(false);
    if (syncUi.busy) { syncUi.again = true; return Promise.resolve(false); }
    syncUi.busy = true;
    syncBadge('syncing', '동기화 중');
    return SYNC.readSnapshot(store.sync.token, store.sync.gistId).then(function (remote) {
      if (!remote) return pushSnapshot();
      var who = SYNC.choose(SYNC.snapshot(store), remote);
      if (who === 'pull') return applyRemote(remote, opts);
      if (who === 'push') return pushSnapshot();
      markSynced();
      return true;
    }).catch(syncFail).then(function (res) {
      syncUi.busy = false;
      if (syncUi.again) { syncUi.again = false; schedulePush(); }
      return res;
    });
  }

  function schedulePush() {
    if (!ghConnected() || applyingRemote) return;
    syncBadge('pending', '저장 대기');
    clearTimeout(syncUi.timer);
    syncUi.timer = setTimeout(function () { syncNow({ silent: true }); }, 2500);
  }

  function connectSync() {
    var token = $('#set-gh-token').value.trim();
    var gistId = $('#set-gh-gist').value.trim();
    if (!token) { toast('GitHub 토큰을 먼저 넣어 주세요'); $('#set-gh-token').focus(); return; }
    if (gistId && !/^[A-Za-z0-9]+$/.test(gistId)) { toast('Gist ID를 확인해 주세요'); $('#set-gh-gist').focus(); return; }
    store.sync.token = token;
    store.sync.gistId = gistId;
    saveNow();
    var btn = $('#btn-gh-sync');
    btn.disabled = true;
    syncBadge('syncing', '연결 중');
    syncLine('GitHub에 연결하는 중…');
    var job;
    if (!gistId) {
      job = SYNC.createGist(token, stampedSnapshot()).then(function (data) {
        if (!data || !data.id) throw new Error('비공개 Gist를 만들지 못했어요');
        store.sync.gistId = data.id;
        $('#set-gh-gist').value = data.id;
        markSynced();
        toast('연결했어요 · 이제 PC·폰이 자동으로 맞춰집니다');
        return true;
      });
    } else {
      job = syncNow({});
    }
    job.catch(syncFail).then(function (ok) {
      btn.disabled = false;
      // 실패했으면 실패 표시(오프라인 등)를 그대로 둔다
      if (ok !== false) refreshSyncUi();
    });
  }

  function disconnectSync() {
    store.sync.token = '';
    store.sync.gistId = '';
    saveNow();
    $('#set-gh-token').value = '';
    $('#set-gh-gist').value = '';
    refreshSyncUi();
    toast('PC·폰 연결을 해제했어요');
  }

  /* ---------------- 모바일 목록 시트 ---------------- */
  function openSheet() {
    $('#sheet').classList.add('is-open');
    $('#sheet').setAttribute('aria-hidden', 'false');
    renderList($('#sheet-list'), { withFavorites: false });
  }
  function closeSheet() {
    $('#sheet').classList.remove('is-open');
    $('#sheet').setAttribute('aria-hidden', 'true');
  }

  // 목록 버튼 — 이전에 고른 카테고리와 상관없이 전체 20종을 보여 준다
  function openFullList() {
    if (store.stage !== 'all') {
      store.stage = 'all';
      save();
      renderTabs();
      renderList($('#tpl-list'), { withFavorites: true });
    }
    openSheet();
  }

  /* ---------------- 이벤트 ---------------- */
  function bind() {
    // 목록
    $('#tpl-list').addEventListener('click', onListClick);
    $('#sheet-list').addEventListener('click', onListClick);
    $('#search').addEventListener('input', function () {
      renderList($('#tpl-list'), { withFavorites: true });
      renderList($('#sheet-list'), { withFavorites: false });
    });
    $('#search-sheet').addEventListener('input', function () {
      var q = $('#search-sheet').value;
      $('#search').value = q;
      renderList($('#tpl-list'), { withFavorites: true });
      renderList($('#sheet-list'), { withFavorites: false });
    });

    // 단계 탭 — 카테고리를 고르면 그 카테고리의 첫 문자로 넘어가고,
    // 폰(≤ 900px)에서는 목록 시트를 바로 열어 그 카테고리 문자를 고르게 한다.
    $('#stage-tabs').addEventListener('click', function (e) {
      var b = e.target.closest('[data-stage]');
      if (!b) return;
      var v = b.dataset.stage;
      store.stage = v;
      var cur = tplById(store.current);
      if (v !== 'all' && (!cur || String(cur.stage) !== String(v))) {
        var first = TEMPLATES.filter(function (t) { return String(t.stage) === String(v); })[0];
        if (first) store.current = first.id;
      }
      save();
      renderAll();
      if (window.innerWidth <= 900) openSheet();
    });

    // 화면 모드 탭 없음 (문자 도우미 한 화면)


    // 스낵바 되돌리기
    $('#snackbar-undo').addEventListener('click', function () {
      var fn = snackUndo;
      hideSnack();
      if (fn) { fn(); toast('되돌렸어요'); }
    });

    // 폼: 입력
    $('#fields').addEventListener('input', function (e) {
      var t = e.target;
      var data = dataOf(tplById(store.current));
      // 비율(%)을 고치면 그 줄 금액을 매매가 기준으로 다시 채운다
      if (t.dataset.payRate) {
        var pct = parseFloat(String(t.value).replace(/[^0-9.]/g, ''));
        var base = payBaseMan(tplById(store.current), data);
        if (!isNaN(pct) && base) {
          data[t.dataset.payRate] = Math.round(base * pct / 100);
          var mi = $('#fields [data-field="' + t.dataset.payRate + '"]');
          if (mi) {
            mi.value = C.group(data[t.dataset.payRate]);
            var mf = mi.closest('.money-field');
            var mh = mf && mf.querySelector('.money-hint');
            setHint(mh, C.moneyHintLine(data[t.dataset.payRate]));
          }
        }
        markEdited();
        syncPayUI();
        updatePreviewOnly();
        validateInline();
        save();
        return;
      }
      if (t.dataset.prop) {
        var pid = t.dataset.prop;
        var pitem = t.dataset.idx != null
          ? data[pid][Number(t.dataset.idx)]
          : (data[pid] = (data[pid] && typeof data[pid] === 'object') ? data[pid] : T.defaultProp());
        if (!pitem) return;
        if (t.dataset.money) {
          var pman = formatMoneyInput(t);
          pitem[t.dataset.money] = pman == null ? '' : pman;
        } else {
          pitem[t.dataset.key] = t.value;
          if (t.dataset.key === 'typeInfo') {
            // 직접 고친 값은 동·호수를 다시 넣어도 그대로 둔다
            pitem.typeInfoManual = !!String(t.value).trim();
            pitem.typeInfoAuto = false;
          }
        }
        if (t.dataset.key === 'dong' || t.dataset.key === 'ho' || t.dataset.key === 'complex') {
          fillTypeInfo(pitem, t.closest('.prop-item'));
        }
        markEdited();
        updatePreviewOnly();
        validateInline();
        save();
        return;
      }
      if (t.dataset.field) {
        var v = t.value;
        if (t.classList.contains('inp-money')) {
          var man = formatMoneyInput(t);
          data[t.dataset.field] = man == null ? '' : man;
        } else {
          data[t.dataset.field] = v;
        }
        // 날짜 칸에 글자(협의·즉시)를 쓰면 달력으로 고른 값은 지운다
        if (t.dataset.dateField && String(v).trim()) data[t.dataset.dateField] = null;
        // 단지처럼 직접 적는 칸에 글을 치면 옆의 선택 버튼은 꺼진다
        if (t.dataset.freeText) {
          var rowBox = t.parentNode;
          var presets = rowBox ? rowBox.querySelectorAll('[data-seg]') : [];
          for (var pi = 0; pi < presets.length; pi++) presets[pi].classList.remove('is-active');
        }
        if (t.parentNode.classList.contains('field') && t.parentNode.querySelector('.account-preview')) {
          var pv = t.parentNode.querySelector('.account-preview');
          var parsed = C.accountParse(v);
          pv.textContent = parsed ? '→ ' + parsed : '';
        }
        markEdited();
        syncPayUI();
        updatePreviewOnly();
        syncCalc();
        validateInline();
        save();
      } else if (t.dataset.rangeTime) {
        var rs = rangeState[store.current] = rangeState[store.current] || {};
        rs[t.dataset.rangeTime] = t.value;
      }
    });

    // 폼: 클릭
    $('#fields').addEventListener('click', function (e) {
      // 협력업체 연락처
      var cdel = e.target.closest('[data-contact-del]');
      if (cdel) { removeContact(cdel.dataset.cat, cdel.dataset.contactDel); return; }
      var cpick = e.target.closest('[data-contact-pick]');
      if (cpick) { toggleContact(cpick.dataset.cat, cpick.dataset.contactPick); return; }
      var cadd = e.target.closest('[data-contact-add]');
      if (cadd) { addContact(cadd.dataset.contactAdd); return; }

      var pt = e.target.closest('[data-prop-trade]');
      if (pt) {
        var tp = tplById(store.current);
        var dp = dataOf(tp);
        var pid2 = pt.dataset.propTrade;
        var item2 = pt.dataset.idx != null
          ? dp[pid2][Number(pt.dataset.idx)]
          : (dp[pid2] = (dp[pid2] && typeof dp[pid2] === 'object') ? dp[pid2] : T.defaultProp());
        if (!item2) return;
        item2.trade = pt.dataset.value;
        var pick = pt.dataset.value === '월세' ? 'deposit' : 'amount';
        save();
        renderForm();
        renderPreview();
        var sel = '[data-prop="' + pid2 + '"]' +
          (pt.dataset.idx != null ? '[data-idx="' + pt.dataset.idx + '"]' : '') +
          '[data-money="' + pick + '"]';
        var focusInp = document.querySelector('#fields ' + sel);
        if (focusInp) focusInp.focus();
        return;
      }
      var unitBtn = e.target.closest('[data-prop-unit]');
      if (unitBtn) {
        var tu = tplById(store.current);
        var du = dataOf(tu);
        var listId = unitBtn.dataset.unitList;
        var itemU = unitBtn.dataset.idx != null
          ? (du[listId] || [])[Number(unitBtn.dataset.idx)]
          : (du[listId] = (du[listId] && typeof du[listId] === 'object') ? du[listId] : T.defaultProp());
        if (!itemU) return;
        var uk = unitBtn.dataset.propUnit;
        if (uk === 'dong') {
          itemU.dongMode = itemU.dongMode === 'complex' ? 'dong' : 'complex';
        } else {
          itemU.hoMode = itemU.hoMode === 'floor' ? 'ho' : 'floor';
        }
        save();
        renderForm();
        renderPreview();
        var focusSel = '#fields [data-prop="' + listId + '"]' +
          (unitBtn.dataset.idx != null ? '[data-idx="' + unitBtn.dataset.idx + '"]' : '') +
          '[data-key="' + uk + '"]';
        var focusInp = document.querySelector(focusSel);
        if (focusInp && !focusInp.disabled) focusInp.focus();
        return;
      }
      var segBtn = e.target.closest('[data-seg]');
      if (segBtn) {
        var t = tplById(store.current);
        var data = dataOf(t);
        var key = segBtn.dataset.seg;
        var val = segBtn.dataset.value;
        data[key] = val;
        if (key === 'calcKind' && val === 'presale') data.calcTrade = '매매';
        if (key === 'calcKind' || key === 'calcTrade' || key === 'calcOffice') data.calcRate = '';
        save();
        renderForm();
        renderPreview();
        return;
      }
      var tg = e.target.closest('[data-toggle]');
      if (tg) {
        var t2 = tplById(store.current);
        var d2 = dataOf(t2);
        d2[tg.dataset.toggle] = !d2[tg.dataset.toggle];
        save();
        renderForm();
        renderPreview();
        return;
      }
      var star = e.target.closest('[data-star]');
      if (star) { toggleStar(star.dataset.star); return; }

      var add = e.target.closest('[data-add-item]');
      if (add) {
        var t3 = tplById(store.current);
        var d3 = dataOf(t3);
        var key3 = add.dataset.addItem;
        d3[key3] = d3[key3] || [];
        if (d3[key3].length < 5) {
          var np = T.defaultProp();
          np.complex = (d3[key3][0] || {}).complex || np.complex;
          d3[key3].push(np);
          save();
          renderForm();
          renderPreview();
        }
        return;
      }
      var rm = e.target.closest('[data-remove-item]');
      if (rm) {
        removePropRow(rm.dataset.removeItem, Number(rm.dataset.idx));
        return;
      }
      var clr = e.target.closest('[data-clear-date]');
      if (clr) {
        e.stopPropagation();
        var t5 = tplById(store.current);
        dataOf(t5)[clr.dataset.clearDate] = { date: '', hour: null, min: 0 };
        save();
        renderForm();
        renderPreview();
        return;
      }
      var dateBtn = e.target.closest('[data-date]');
      if (dateBtn) { openCal(dateBtn, dateBtn.dataset.date); return; }
      // 날짜 칸의 협의 | 고정 | 기간
      var modeBtn = e.target.closest('[data-date-mode]');
      if (modeBtn) {
        var tm = tplById(store.current);
        var dm = dataOf(tm);
        dm[modeBtn.dataset.dateMode + 'Mode'] = modeBtn.dataset.value;
        save();
        renderForm();
        renderPreview();
        if (modeBtn.dataset.value === '협의') {
          var fin = $('#fields [data-field="' + modeBtn.dataset.dateMode + 'Text"]');
          if (fin) { try { fin.focus({ preventScroll: true }); } catch (e2) { fin.focus(); } }
        }
        return;
      }
      var act = e.target.closest('[data-action]');
      if (act) {
        if (act.dataset.action === 'vary') { varyPhrase(); return; }
        var t6 = tplById(store.current);
        var d6 = dataOf(t6);
        var price = C.parseMan(d6.price);
        if (price == null) { toast('매매가를 먼저 입력해 주세요'); return; }
        var g = Math.round(price * 0.1);
        var j = Math.round(price * 0.25);
        d6.gyeyakAmount = g;
        d6.jungAmount = j;
        var sp = paySplitOf(t6, d6);
        d6.janAmount = sp && sp.ok ? sp.janMan : '';
        save();
        renderForm();
        renderPreview();
        toast('계약금 10% · 중도금 25%를 채웠어요 · 잔금은 자동 계산');
        return;
      }
      var rangeAdd = e.target.closest('[data-range-add]');
      if (rangeAdd) {
        var t7 = tplById(store.current);
        var d7 = dataOf(t7);
        var rs = rangeState[t7.id] || {};
        if (!rs.date) { toast('날짜를 먼저 골라 주세요'); return; }
        var s = String(rs.start || '10:0').split(':');
        var en = String(rs.end || '12:0').split(':');
        var line = C.formatDateTimeRange({ date: rs.date, hour: Number(s[0]), min: Number(s[1]) }, { hour: Number(en[0]), min: Number(en[1]) });
        var cur = String(d7[rangeAdd.dataset.rangeAdd] || '');
        d7[rangeAdd.dataset.rangeAdd] = (cur ? cur.replace(/\s+$/, '') + '\n' : '') + line;
        save();
        renderForm();
        renderPreview();
        return;
      }
    });

    // 달력
    $('#calpop').addEventListener('click', function (e) {
      var nav = e.target.closest('[data-cal-nav]');
      if (nav) {
        cal.m += Number(nav.dataset.calNav);
        if (cal.m < 1) { cal.m = 12; cal.y--; }
        if (cal.m > 12) { cal.m = 1; cal.y++; }
        renderCal();
        return;
      }
      var dayBtn = e.target.closest('[data-cal-day]');
      if (dayBtn) {
        var dateStr = cal.y + '-' + String(cal.m).padStart(2, '0') + '-' + String(dayBtn.dataset.calDay).padStart(2, '0');
        if (cal.rangeMode) {
          var t = tplById(store.current);
          rangeState[t.id] = rangeState[t.id] || {};
          rangeState[t.id].date = dateStr;
          closeCal();
          renderForm();
        } else {
          var old = currentCalValue() || {};
          setCalDateTime(cal.fieldId, { date: dateStr, hour: old.hour == null ? null : old.hour, min: old.min || 0 });
          renderCal();
          renderForm();
          renderPreview();
        }
        return;
      }
      var per = e.target.closest('[data-cal-period]');
      if (per) {
        var cur2 = currentCalValue() || {};
        var h = cur2.hour == null ? 9 : Number(cur2.hour);
        var p = per.dataset.calPeriod;
        var isPM = h >= 12;
        if (p === '오후' && !isPM) h = h + 12;
        if (p === '오전' && isPM) h = h - 12;
        setCalDateTime(cal.fieldId, { hour: h });
        renderCal();
        renderForm();
        renderPreview();
        return;
      }
      var clrT = e.target.closest('[data-cal-clear-time]');
      if (clrT) {
        setCalDateTime(cal.fieldId, { hour: null, min: 0 });
        renderCal();
        renderForm();
        renderPreview();
        return;
      }
      if (e.target.closest('[data-cal-reset]')) {
        // 날짜·시간을 함께 지운다 (기간 칸은 그 날짜만)
        if (cal.rangeMode) {
          var tr = tplById(store.current);
          rangeState[tr.id] = rangeState[tr.id] || {};
          rangeState[tr.id].date = null;
        } else {
          setCalDateTime(cal.fieldId, { date: '', hour: null, min: 0 });
        }
        renderCal();
        renderForm();
        renderPreview();
        return;
      }
      if (e.target.closest('[data-cal-close]')) closeCal();
    });

    $('#calpop').addEventListener('change', function (e) {
      var hourSel = e.target.closest('[data-cal-hour]');
      var minSel = e.target.closest('[data-cal-min]');
      if (!hourSel && !minSel) return;
      var cur = currentCalValue() || {};
      var h = cur.hour == null ? 9 : Number(cur.hour);
      var period = h < 12 ? '오전' : '오후';
      var h12 = h % 12 === 0 ? 12 : h % 12;
      if (hourSel) h12 = Number(hourSel.value);
      else h12 = Number($('[data-cal-hour]').value);
      if (!h12) return;  // '시' 빈 칸을 다시 골랐을 때는 시간을 바꾸지 않는다
      var min = minSel ? Number(minSel.value) : Number(cur.min || 0);
      var h24 = h12 % 12 + (period === '오후' ? 12 : 0);
      setCalDateTime(cal.fieldId, { hour: h24, min: min });
      renderCal();
      renderForm();
      renderPreview();
    });

    // 바깥을 누르면 달력을 닫는다. (달력 내부를 다시 그려도 클릭이 새지 않도록 pointerdown에서 판단)
    document.addEventListener('pointerdown', function (e) {
      if (!cal.open) return;
      if (e.target.closest && (e.target.closest('#calpop') || e.target.closest('[data-date]'))) return;
      closeCal();
    }, true);

    // 상단/하단 버튼
    $('#btn-copy').addEventListener('click', function () { copyText($('#preview').value, this); });
    $('#btn-copy2').addEventListener('click', function () { copyText($('#preview').value, this); });
    $('#btn-sms').addEventListener('click', openSms);
    $('#btn-reset').addEventListener('click', function () {
      var t = tplById(store.current);
      var before = { data: JSON.parse(JSON.stringify(store.data[t.id] || {})), text: store.texts[t.id] };
      store.data[t.id] = T.defaultData(t);
      delete store.texts[t.id];
      delete editDirty[t.id];
      save();
      renderForm();
      renderPreview();
      showSnack('입력 내용을 비웠어요', function () {
        store.data[t.id] = before.data;
        if (before.text != null) store.texts[t.id] = before.text;
        save();
        renderForm();
        renderPreview();
      });
    });
    $('#btn-restore').addEventListener('click', function () { refreshFromInputs({ snack: true }); });
    $('#preview').addEventListener('input', function () {
      var t = tplById(store.current);
      store.texts[t.id] = this.value;
      $('#btn-restore').disabled = false;
      delete editDirty[t.id];
      var note = $('#edited-note');
      if (note) {
        note.hidden = false;
        note.innerHTML = '직접 수정한 본문입니다 · <button class="link" id="btn-refresh" type="button">입력값으로 새로 만들기</button>';
        $('#btn-refresh').addEventListener('click', refreshFromInputs);
      }
      $('#char-count').textContent = this.value.length ? this.value.length.toLocaleString('en-US') + '자' : '';
      save();
    });

    // 설정
    $('#btn-settings').addEventListener('click', openSettings);
    $('#btn-settings-close').addEventListener('click', closeSettings);
    $('#btn-settings-save').addEventListener('click', applySettings);
    $('#settings').addEventListener('click', function (e) {
      if (e.target === this) closeSettings();
    });
    $('#settings').addEventListener('click', function (e) {
      var b = e.target.closest('[data-set-mode]');
      if (!b) return;
      $$('[data-set-mode]', this).forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      store.profile.amountMode = b.dataset.setMode;
    });
    $('#set-account').addEventListener('input', function () {
      var p = C.accountParse(this.value);
      $('#set-account-preview').textContent = p ? '→ ' + p : '';
    });

    // 모바일 시트
    $('#btn-sheet').addEventListener('click', openFullList);
    $('#sheet-close').addEventListener('click', closeSheet);
    $('#sheet').addEventListener('click', function (e) { if (e.target === this) closeSheet(); });

    // 문구 편집 · 새 문구
    $('#btn-tpl-new').addEventListener('click', function () { openTemplateEditor('new'); });
    $('#btn-tpl-new-sheet').addEventListener('click', function () { openTemplateEditor('new'); });
    $('#btn-tpl-edit').addEventListener('click', function () {
      var t = tplById(store.current);
      if (!t) return;
      openTemplateEditor(t.custom ? 'custom' : 'override', t.id);
    });
    $('#btn-tpl-revert').addEventListener('click', revertTemplate);
    $('#btn-tpl-editor-close').addEventListener('click', closeTemplateEditor);
    $('#btn-tpl-editor-cancel').addEventListener('click', closeTemplateEditor);
    $('#btn-tpl-editor-save').addEventListener('click', saveTemplateEditor);
    $('#btn-tpl-editor-del').addEventListener('click', deleteCustomTemplate);
    $('#tpl-editor').addEventListener('click', function (e) { if (e.target === this) closeTemplateEditor(); });

    // 백업 · 불러오기
    $('#btn-export').addEventListener('click', function () { exportCopy(this); });
    $('#btn-export-file').addEventListener('click', exportFile);
    $('#btn-import').addEventListener('click', function () {
      var box = $('#import-box');
      box.hidden = !box.hidden;
      if (!box.hidden) $('#import-text').focus();
    });
    $('#btn-import-apply').addEventListener('click', function () { applyImport($('#import-text').value); });
    $('#btn-import-file').addEventListener('click', function () { $('#import-file').click(); });
    $('#import-file').addEventListener('change', function () {
      var f = this.files && this.files[0];
      this.value = '';
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () { applyImport(String(reader.result || '')); };
      reader.readAsText(f);
    });

    // PC·폰 자동 동기화
    $('#btn-gh-sync').addEventListener('click', connectSync);
    $('#btn-gh-off').addEventListener('click', disconnectSync);
    $('#sync-status').addEventListener('click', openSettings);
    window.addEventListener('online', function () { if (ghConnected()) syncNow({ silent: true }); });
    window.addEventListener('offline', function () { if (ghConnected()) syncBadge('off', '오프라인'); });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { closeCal(); closeSettings(); closeSheet(); closeTemplateEditor(); }
    });

    bindKeyboardGuard();
  }

  // 아이폰 숫자·문자 키보드가 열린 채 스크롤해도 하단 고정 바가 화면 가운데에 떠
  // 미리보기 카드를 가로지르지 않게, 키보드가 올라온 동안에는 바를 감춘다.
  function bindKeyboardGuard() {
    var isMobile = function () { return window.matchMedia('(max-width: 900px)').matches; };
    var isField = function (el) {
      if (!el) return false;
      var tag = (el.tagName || '').toLowerCase();
      return tag === 'input' || tag === 'textarea' || tag === 'select';
    };
    var shrunk = function () {
      var vv = window.visualViewport;
      return !!(vv && vv.height && vv.height < window.innerHeight * 0.78);
    };
    function sync() {
      var open = isMobile() && (shrunk() || isField(document.activeElement));
      document.body.classList.toggle('kbd-open', open);
    }
    document.addEventListener('focusin', sync);
    document.addEventListener('focusout', function () { setTimeout(sync, 120); });
    if (window.visualViewport) window.visualViewport.addEventListener('resize', sync);
    window.addEventListener('resize', sync);
    window.addEventListener('orientationchange', function () { setTimeout(sync, 200); });
    sync();
  }

  function onListClick(e) {
    var star = e.target.closest('[data-star]');
    if (star) { toggleStar(star.dataset.star); return; }
    var row = e.target.closest('[data-id]');
    if (row) selectTemplate(row.dataset.id);
  }

  function markEdited() {
    // 직접 고친 본문이 있는 상태에서 입력값이 또 바뀌면 알려 준다
    var t = tplById(store.current);
    if (store.texts[t.id] != null) {
      editDirty[t.id] = true;
      var note = $('#edited-note');
      if (note) {
        note.hidden = false;
        note.innerHTML = '입력값이 바뀌었어요 · 지금은 직접 수정한 본문입니다 · <button class="link" id="btn-refresh" type="button">입력값으로 새로 만들기</button>';
        var rf = $('#btn-refresh');
        if (rf) rf.addEventListener('click', refreshFromInputs);
      }
    }
  }

  /* ---------------- 인라인 안내 (막지 않고 살짝만) ---------------- */
  function hintFor(container, key, msg) {
    if (!container) return;
    var h = container.querySelector('[data-hint="' + key + '"]');
    if (!h) {
      h = el('p', 'inline-hint');
      h.dataset.hint = key;
      container.appendChild(h);
    }
    h.textContent = msg || '';
    h.hidden = !msg;
    container.classList.toggle('has-hint', !!msg);
  }

  function validatePropRow(f, item, idx, isList) {
    if (!item) return;
    var sel = '[data-prop="' + f.id + '"]';
    var inp = document.querySelector('#fields ' + sel + (isList ? '[data-idx="' + idx + '"]' : '') + '[data-key="dong"]');
    var box = inp && inp.closest('.prop-item');
    if (!box) return;
    var msg = '';
    if (item.trade === '월세') {
      if (C.parseMan(item.deposit) && !C.parseMan(item.rent)) msg = '월세를 함께 넣어 주세요';
      else if (!C.parseMan(item.deposit) && C.parseMan(item.rent)) msg = '보증금을 함께 넣어 주세요';
    }
    if (!msg && item.dongMode !== 'complex' && ((item.dong && !item.ho) || (!item.dong && item.ho))) msg = '동과 호수를 함께 넣으면 표기가 정확해요';
    hintFor(box, 'prop', msg);
  }

  function validateInline() {
    var t = tplById(store.current);
    if (!t) return;
    var data = dataOf(t);
    t.fields.forEach(function (f) {
      if (f.showIf && !f.showIf(data)) return;
      if (f.t === 'account') {
        var inp = $('[data-field="' + f.id + '"]');
        var row = inp && inp.closest('.field');
        var v = String(data[f.id] == null ? '' : data[f.id]).trim();
        var msg = '';
        if (v) {
          var parsed = C.accountParse(v);
          if (!/\d{4,}/.test(parsed)) msg = '계좌번호를 다시 확인해 주세요 (예: 국민 123456-01-234567 홍길동)';
          else if (!/[가-힣]/.test(parsed)) msg = '은행 이름을 함께 넣으면 정리하기 쉬워요';
        }
        hintFor(row, f.id, msg);
      }
      if (f.t === 'props' || f.t === 'property') {
        var list = f.t === 'props' ? (data[f.id] || []) : [data[f.id]];
        (list || []).forEach(function (item, idx) { validatePropRow(f, item, idx, f.t === 'props'); });
      }
      if (f.t === 'money' && f.id === 'price' && t.id === 't8') {
        var mi = $('[data-field="price"]');
        var mrow = mi && mi.closest('.field');
        var missing = !C.parseMan(data.price);
        hintFor(mrow, 'price', missing && (C.parseMan(data.gyeyakAmount) || C.parseMan(data.jungAmount))
          ? '매매가를 넣으면 계약금·중도금·잔금이 바로 맞춰져요' : '');
      }
    });
  }

  /* ---------------- 매물 한 줄 빼기 (되돌리기 포함) ---------------- */
  function removePropRow(listId, idx) {
    var t = tplById(store.current);
    var d = dataOf(t);
    var list = d[listId] || [];
    var item = list[idx];
    if (!item) return;
    var snap = JSON.parse(JSON.stringify(item));
    list.splice(idx, 1);
    save();
    renderForm();
    renderPreview();
    validateInline();
    showSnack('매물 한 줄을 뺐어요', function () {
      var d2 = dataOf(t);
      if (!Array.isArray(d2[listId])) d2[listId] = [];
      d2[listId].splice(Math.min(idx, d2[listId].length), 0, snap);
      save();
      renderForm();
      renderPreview();
    });
  }

  function toggleStar(id, fromLongPress) {
    var i = store.stars.indexOf(id);
    var on = i === -1;
    if (on) store.stars.push(id);
    else store.stars.splice(i, 1);
    save();
    renderList($('#tpl-list'), { withFavorites: true });
    renderList($('#sheet-list'), { withFavorites: false });
    if (fromLongPress) toast(on ? '★ 즐겨찾기에 넣었어요' : '즐겨찾기에서 뺐어요');
  }

  /* ---------------- 모바일 제스처 ---------------- */
  // 목록을 길게 누르면 ★ 즐겨찾기 (누르고 있기 0.55초)
  function bindLongPress() {
    var timer = null;
    var suppressUntil = 0;
    var start = null;
    function cancel() { clearTimeout(timer); timer = null; }
    ['#tpl-list', '#sheet-list'].forEach(function (sel) {
      var box = $(sel);
      if (!box) return;
      box.addEventListener('pointerdown', function (e) {
        var row = e.target.closest('.row');
        if (!row || e.target.closest('[data-star]')) return;
        start = { x: e.clientX, y: e.clientY };
        cancel();
        timer = setTimeout(function () {
          timer = null;
          suppressUntil = Date.now() + 800;
          toggleStar(row.dataset.id, true);
        }, 550);
      });
      box.addEventListener('pointermove', function (e) {
        if (!timer || !start) return;
        if (Math.abs(e.clientX - start.x) > 8 || Math.abs(e.clientY - start.y) > 8) cancel();
      });
      ['pointerup', 'pointercancel', 'pointerleave', 'scroll'].forEach(function (ev) {
        box.addEventListener(ev, cancel);
      });
    });
    document.addEventListener('click', function (e) {
      if (Date.now() < suppressUntil && e.target.closest && e.target.closest('#tpl-list .row, #sheet-list .row')) {
        suppressUntil = 0;
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);
  }

  // 매물 줄을 왼쪽으로 밀면 삭제 (되돌리기 가능)
  function bindSwipe() {
    var st = null;
    var box = $('#fields');
    if (!box) return;

    function reset(item) {
      if (!item) return;
      item.classList.remove('is-swiping');
      item.style.transform = '';
      item.style.opacity = '';
    }

    box.addEventListener('pointerdown', function (e) {
      var item = e.target.closest('.prop-item');
      if (!item || e.target.closest('button')) return;
      var rm = item.querySelector('[data-remove-item]');
      if (!rm) return;                        // 한 줄뿐이면 밀어서 지우기 없음
      st = { item: item, x: e.clientX, y: e.clientY, dx: 0, active: false, rm: rm };
    });

    box.addEventListener('pointermove', function (e) {
      if (!st) return;
      var dx = e.clientX - st.x;
      var dy = e.clientY - st.y;
      if (!st.active) {
        if (Math.abs(dy) > 16) { reset(st.item); st = null; return; }
        if (Math.abs(dx) < 12 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
        st.active = true;
        st.item.classList.add('is-swiping');
      }
      st.dx = Math.max(-150, Math.min(0, dx));
      st.item.style.transform = 'translateX(' + st.dx + 'px)';
      st.item.style.opacity = String(Math.max(0.35, 1 + st.dx / 320));
    });

    function end() {
      if (!st) return;
      var cur = st;
      st = null;
      reset(cur.item);
      if (cur.active && cur.dx <= -64) removePropRow(cur.rm.dataset.removeItem, Number(cur.rm.dataset.idx));
    }

    box.addEventListener('pointerup', end);
    box.addEventListener('pointercancel', end);
    box.addEventListener('pointerleave', end);
  }

  /* ---------------- 협력업체 연락처 ---------------- */
  function selMapOf(d) {
    if (!d.vendorSel || typeof d.vendorSel !== 'object') d.vendorSel = T.defaultVendorSel();
    return d.vendorSel;
  }

  function toggleContact(cat, id) {
    var t = tplById(store.current);
    var d = dataOf(t);
    var sel = selMapOf(d);
    if (!Array.isArray(sel[cat])) sel[cat] = [];
    var i = sel[cat].indexOf(id);
    if (i === -1) sel[cat].push(id);
    else sel[cat].splice(i, 1);
    markEdited();
    save();
    renderForm();
    updatePreviewOnly();
  }

  function addContact(cat) {
    var nameInp = $('#fields [data-contact-new="name"]');
    var phoneInp = $('#fields [data-contact-new="phone"]');
    var name = nameInp ? nameInp.value.trim() : '';
    var phone = phoneInp ? phoneInp.value.trim() : '';
    if (!name) { toast('이름을 먼저 넣어 주세요'); if (nameInp) nameInp.focus(); return; }
    if (C.digits(phone).length < 8) { toast('전화번호를 확인해 주세요'); if (phoneInp) phoneInp.focus(); return; }
    store.contacts[cat] = store.contacts[cat] || [];
    var id = 'c' + Date.now().toString(36) + Math.floor(Math.random() * 1000).toString(36);
    store.contacts[cat].push({ id: id, name: name, phone: phone });
    var t = tplById(store.current);
    var d = dataOf(t);
    var sel = selMapOf(d);
    if (!Array.isArray(sel[cat])) sel[cat] = [];
    sel[cat].push(id);
    markEdited();
    save();
    renderForm();
    updatePreviewOnly();
    toast('연락처를 추가했어요');
  }

  function removeContact(cat, id) {
    var list = store.contacts[cat] || [];
    var idx = -1;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) idx = i;
    if (idx === -1) return;
    var snap = list[idx];
    list.splice(idx, 1);
    var t = tplById(store.current);
    var d = dataOf(t);
    var sel = selMapOf(d);
    var selIdx = Array.isArray(sel[cat]) ? sel[cat].indexOf(id) : -1;
    if (selIdx !== -1) sel[cat].splice(selIdx, 1);
    save();
    renderForm();
    updatePreviewOnly();
    showSnack('연락처를 지웠어요', function () {
      store.contacts[cat] = store.contacts[cat] || [];
      store.contacts[cat].splice(Math.min(idx, store.contacts[cat].length), 0, snap);
      if (selIdx !== -1) {
        var d2 = dataOf(t);
        var sel2 = selMapOf(d2);
        if (!Array.isArray(sel2[cat])) sel2[cat] = [];
        sel2[cat].splice(Math.min(selIdx, sel2[cat].length), 0, id);
      }
      save();
      renderForm();
      updatePreviewOnly();
    });
  }

  /* ---------------- 다른 문구 · 동호 변환 ---------------- */
  function varyPhrase() {
    var t = tplById(store.current);
    var d = dataOf(t);
    var target = T.VARIANTS[d.target] ? d.target : 'owner';
    if (!d.vpick || typeof d.vpick !== 'object') d.vpick = { owner: 0, coagent: 0, guest: 0 };
    var len = T.VARIANTS[target].length;
    var cur = Number(d.vpick[target]) || 0;
    d.vpick[target] = (cur + 1) % len;
    markEdited();
    save();
    renderForm();
    updatePreviewOnly();
  }

  /* ---------------- 매물 스파이더에서 값 넘겨 열기 (?template=...) ---------------- */
  var URL_ALIAS = {
    'property': 't7', 'listing': 't7', 'info': 't7',
    'owner': 't3', 'coagent': 't4', 'reservation': 't5', 'parking': 't6',
    'contract': 't8', 'fee': 't14', 'thanks': 't17', 'promo': 't19', 'vendor': 't20'
  };

  // 가격은 "23억" / 230000(만 원) / 2300000000(원) 모두 받는다
  function paramMan(v) {
    var raw = String(v == null ? '' : v).trim();
    if (!raw) return '';
    var man = C.parseMan(raw);
    if (man == null) return '';
    if (/^[0-9,]+$/.test(raw) && man >= 1000000) man = Math.round(man / 10000);
    return man;
  }

  function paramDateTime(v) {
    var s = String(v == null ? '' : v).trim();
    if (!s) return null;
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s](\d{1,2}):(\d{2}))?/.exec(s);
    if (!m) return null;
    return {
      date: m[1] + '-' + String(m[2]).padStart(2, '0') + '-' + String(m[3]).padStart(2, '0'),
      hour: m[4] == null ? null : Number(m[4]),
      min: m[5] == null ? 0 : Number(m[5])
    };
  }

  function fillPropFromParams(p, q) {
    if (!p || typeof p !== 'object') return false;
    var changed = false;
    var complex = q.get('complex'), dong = q.get('dong'), ho = q.get('ho');
    var trade = q.get('dealType') || q.get('trade');
    var price = q.get('price'), deposit = q.get('deposit'), monthly = q.get('monthly') || q.get('rent');
    if (complex) { p.complex = complex; changed = true; }
    if (dong) { p.dong = dong; changed = true; }
    if (ho) { p.ho = ho; changed = true; }
    if (trade === '매매' || trade === '전세' || trade === '월세') { p.trade = trade; changed = true; }
    if (deposit || monthly) {
      p.trade = '월세';
      if (deposit) p.deposit = paramMan(deposit);
      if (monthly) p.rent = paramMan(monthly);
      changed = true;
    } else if (price) {
      p.amount = paramMan(price);
      changed = true;
    }
    return changed;
  }

  function applyUrlParams() {
    var q;
    try { q = new URLSearchParams(window.location.search || ''); } catch (e) { return; }
    if (!q.toString()) return;

    var tid = String(q.get('template') || q.get('t') || '').trim();
    if (tid) {
      var t = tplById(tid.charAt(0) === 't' ? tid : 't' + tid) || tplById(URL_ALIAS[tid.toLowerCase()] || '');
      if (t) store.current = t.id;
    }
    var cur = tplById(store.current);
    if (!cur) return;
    var d = dataOf(cur);
    // 매물 관련 값이 하나도 없으면 빈 매물 줄을 만들지 않는다
    var hasPropParams = false;
    ['complex', 'dong', 'ho', 'dealType', 'trade', 'price', 'deposit', 'monthly', 'rent'].forEach(function (k) {
      if (q.get(k)) hasPropParams = true;
    });
    if (hasPropParams) {
      cur.fields.forEach(function (f) {
        if (f.t === 'property' && d[f.id] && typeof d[f.id] === 'object') fillPropFromParams(d[f.id], q);
        if (f.t === 'props') {
          if (!Array.isArray(d[f.id]) || !d[f.id].length) d[f.id] = [T.defaultProp()];
          fillPropFromParams(d[f.id][0], q);
        }
      });
    }

    var when = paramDateTime(q.get('visitDate') || q.get('when') || q.get('date'));
    if (when) {
      var dateField = cur.fields.filter(function (f) { return f.t === 'date'; })[0];
      if (dateField) {
        d[dateField.id] = when;
        // 협의·기간으로 열려 있었어도 달력 날짜를 받았으면 고정으로 보여 준다
        if (dateField.mode3 || dateField.freeText) d[dateField.id + 'Mode'] = '고정';
      }
    }

    if (q.get('customerName')) d.customerName = q.get('customerName');
    if (q.get('phone')) d.phone = q.get('phone');

    delete store.texts[cur.id];
    delete editDirty[cur.id];
    saveNow();
    try { window.history.replaceState(null, '', window.location.pathname); } catch (e) { /* file:// 등은 그냥 둔다 */ }
  }

  window.SMSUI = { smsUrl: smsUrl, copyText: copyText };
  window.SMSApp = {
    openTemplate: function (tid, patch) {
      var t = tplById(tid);
      if (!t) return;
      var d = dataOf(t);
      if (patch) {
        Object.keys(patch).forEach(function (k) { d[k] = patch[k]; });
      }
      delete store.texts[tid];
      delete editDirty[tid];
      selectTemplate(tid);
    },
    ctx: ctx,
    toast: toast,
    snackbar: showSnack
  };

  /* ---------------- 시작 ---------------- */
  load();
  rebuildTemplates();
  if (!tplById(store.current)) store.current = 't5';
  lastContent = SYNC.contentKey(store);
  bind();
  bindLongPress();
  bindSwipe();
  applyUrlParams();
  renderAll();
  refreshSyncUi();
  // 연결돼 있으면 앱을 열 때 최신 내용을 받아 온다
  if (ghConnected()) setTimeout(function () { syncNow({ silent: true }); }, 350);
})();
