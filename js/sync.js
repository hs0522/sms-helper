/* 마래푸중앙부동산 문자 도우미 — PC·폰 백업/불러오기 · GitHub Gist 동기화
 *   SMSSync.snapshot(store)          내 정보·연락처·즐겨찾기·내 문구·영구 수정 문구를 한 덩어리로
 *   SMSSync.parse(text)              내보낸 JSON 글을 읽어 검사
 *   SMSSync.apply(store, snap)       기기에 되살린다 (바뀌었으면 true)
 *   SMSSync.choose(local, remote)    updatedAt 이 더 새것인 쪽 ('push' / 'pull' / 'same')
 *   SMSSync.createGist / updateGist / readSnapshot   GitHub Gist(비공개) 읽고 쓰기
 * 토큰·Gist ID 는 이 파일을 거쳐 가지 않는다 — 부르는 쪽(화면)이 localStorage 에만 둔다.
 */
(function (global) {
  'use strict';

  var APP = 'maraepu-sms-helper';
  var SNAP_VERSION = 1;
  var FILE_NAME = 'smshelper-backup.json';
  var API = 'https://api.github.com';
  var STAGES = ['1', '2', '3', '4'];

  /* ---------- 값 다듬기 ---------- */
  function clean(v, max) {
    var s = String(v == null ? '' : v).replace(/\s+/g, ' ').trim();
    if (max && s.length > max) s = s.slice(0, max).trim();
    return s;
  }

  function bodyText(v) {
    return String(v == null ? '' : v)
      .replace(/\r\n?/g, '\n')
      .replace(/[ \t]+$/gm, '')
      .replace(/^\n+/, '')
      .replace(/\n+$/, '');
  }

  function stageOf(v) {
    var s = String(v == null ? '' : v).trim();
    return STAGES.indexOf(s) === -1 ? '1' : s;
  }

  function sanitizeCustom(list) {
    if (!Array.isArray(list)) return [];
    var out = [];
    var seen = {};
    list.forEach(function (c, i) {
      if (!c || typeof c !== 'object') return;
      var body = bodyText(c.body);
      if (!body) return;
      var id = clean(c.id, 40).replace(/[^A-Za-z0-9_-]/g, '') || ('c' + (i + 1));
      if (seen[id]) id = id + '_' + (i + 1);
      seen[id] = true;
      out.push({
        id: id,
        stage: stageOf(c.stage),
        title: clean(c.title, 60) || '내 문구',
        desc: clean(c.desc, 80),
        body: body,
        sign: c.sign !== false
      });
    });
    return out;
  }

  function sanitizeOverrides(map) {
    var out = {};
    if (!map || typeof map !== 'object' || Array.isArray(map)) return out;
    Object.keys(map).forEach(function (id) {
      var o = map[id];
      if (!o || typeof o !== 'object') return;
      var body = bodyText(o.body);
      if (!body) return;
      if (!/^t(?:[1-9]|1[0-9]|20)$/.test(id)) return;   // 기본 20종(t1~t20)만 영구 수정한다
      out[id] = { body: body, sign: o.sign !== false };
    });
    return out;
  }

  function sanitizeContacts(map) {
    var out = {};
    if (!map || typeof map !== 'object' || Array.isArray(map)) return out;
    Object.keys(map).forEach(function (cat) {
      if (!Array.isArray(map[cat])) return;
      var rows = [];
      map[cat].forEach(function (c) {
        if (!c || typeof c !== 'object') return;
        var name = clean(c.name, 40);
        var phone = clean(c.phone, 30);
        if (!name && !phone) return;
        rows.push({ id: clean(c.id, 40), name: name, phone: phone });
      });
      out[cat] = rows;
    });
    return out;
  }

  function sanitizeStars(list) {
    if (!Array.isArray(list)) return [];
    var out = [];
    list.forEach(function (s) {
      if (typeof s !== 'string') return;
      var id = s.trim();
      if (id && out.indexOf(id) === -1) out.push(id);
    });
    return out;
  }

  /* ---------- 한 덩어리 만들기 · 되살리기 ---------- */
  function snapshot(store) {
    store = store || {};
    var p = store.profile || {};
    var sync = store.sync || {};
    return {
      app: APP,
      version: SNAP_VERSION,
      updatedAt: Number(sync.updatedAt) || 0,
      profile: {
        office: String(p.office == null ? '' : p.office),
        phones: String(p.phones == null ? '' : p.phones),
        feeAccount: String(p.feeAccount == null ? '' : p.feeAccount),
        amountMode: String(p.amountMode == null ? '' : p.amountMode)
      },
      stars: sanitizeStars(store.stars),
      contacts: sanitizeContacts(store.contacts),
      custom: sanitizeCustom(store.custom),
      overrides: sanitizeOverrides(store.overrides)
    };
  }

  // 내용만 비교할 때 쓰는 열쇠 (updatedAt 은 뺀다)
  function contentKey(store) {
    var s = snapshot(store);
    delete s.updatedAt;
    return JSON.stringify(s);
  }

  function parse(text) {
    if (typeof text !== 'string' || !text.trim()) return null;
    var o;
    try { o = JSON.parse(text); } catch (e) { return null; }
    if (!o || typeof o !== 'object' || Array.isArray(o)) return null;
    if (o.app && o.app !== APP) return null;
    var looksOurs = o.app === APP || o.profile || o.custom || o.overrides || o.contacts || o.stars;
    return looksOurs ? o : null;
  }

  function apply(store, snap) {
    if (!store || !snap) return false;
    var before = contentKey(store);
    var prof = snap.profile || {};
    store.profile = store.profile || {};
    ['office', 'phones', 'feeAccount'].forEach(function (k) {
      if (typeof prof[k] === 'string' && prof[k].trim()) store.profile[k] = prof[k].trim();
    });
    if (typeof prof.amountMode === 'string' && prof.amountMode) store.profile.amountMode = prof.amountMode;
    if (Array.isArray(snap.stars)) store.stars = sanitizeStars(snap.stars);
    if (snap.contacts && typeof snap.contacts === 'object') store.contacts = sanitizeContacts(snap.contacts);
    store.custom = sanitizeCustom(snap.custom);
    store.overrides = sanitizeOverrides(snap.overrides);
    store.sync = store.sync || {};
    store.sync.updatedAt = Number(snap.updatedAt) || Date.now();
    return contentKey(store) !== before;
  }

  // 어느 쪽이 더 새것인가 — 새 기기(updatedAt 0)는 받아 온다
  function choose(local, remote) {
    if (!remote) return 'push';
    var lt = Number(local && local.updatedAt) || 0;
    var rt = Number(remote.updatedAt) || 0;
    if (!lt) return 'pull';
    if (rt > lt) return 'pull';
    if (lt > rt) return 'push';
    return 'same';
  }

  /* ---------- GitHub Gist (비공개) ---------- */
  function errorText(status, data) {
    if (status === 401) return '토큰이 올바르지 않아요 — gist 권한을 확인해 주세요';
    if (status === 403) return '권한이 없어요 — 토큰에 gist 권한이 있는지 확인해 주세요';
    if (status === 404) return 'Gist를 찾을 수 없어요 — Gist ID를 확인해 주세요';
    if (status === 422) return 'Gist에 저장할 수 없어요 — 잠시 뒤 다시 해보세요';
    if (data && data.message) return 'GitHub: ' + data.message;
    return 'GitHub 연결에 실패했어요 (' + status + ')';
  }

  function request(method, url, token, body) {
    var headers = {
      'Accept': 'application/vnd.github+json',
      'Authorization': 'Bearer ' + token
    };
    var opts = { method: method, headers: headers };
    if (body) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!res.ok) {
          var err = new Error(errorText(res.status, data));
          err.status = res.status;
          throw err;
        }
        return data;
      });
    }, function () {
      var err = new Error('인터넷에 연결되어 있지 않아요');
      err.offline = true;
      throw err;
    });
  }

  function gistBody(snap) {
    return {
      description: '마래푸중앙부동산 문자 도우미 자동 동기화 (PC·폰)',
      files: (function () {
        var f = {};
        f[FILE_NAME] = { content: JSON.stringify(snap, null, 2) };
        return f;
      })()
    };
  }

  function createGist(token, snap) {
    var body = gistBody(snap);
    body.public = false;                     // 비공개(Secret) Gist
    return request('POST', API + '/gists', token, body);
  }

  function updateGist(token, gistId, snap) {
    return request('PATCH', API + '/gists/' + encodeURIComponent(gistId), token, gistBody(snap));
  }

  // Gist 안의 백업 파일을 읽는다. 파일이 없으면 null, 깨졌으면 예외.
  function readSnapshot(token, gistId) {
    return request('GET', API + '/gists/' + encodeURIComponent(gistId), token).then(function (data) {
      var file = data && data.files && data.files[FILE_NAME];
      if (!file) return null;
      if (file.truncated && file.raw_url) {
        return fetch(file.raw_url, { headers: { 'Accept': 'application/vnd.github.raw' } })
          .then(function (res) { return res.ok ? res.text() : ''; })
          .then(function (text) { return parse(text); });
      }
      var snap = parse(file.content);
      if (!snap) throw new Error('Gist 안의 백업 내용을 읽을 수 없어요');
      return snap;
    });
  }

  function gistUrl(gistId) {
    return gistId ? 'https://gist.github.com/' + gistId : '';
  }

  global.SMSSync = {
    APP: APP,
    FILE_NAME: FILE_NAME,
    snapshot: snapshot,
    contentKey: contentKey,
    parse: parse,
    apply: apply,
    choose: choose,
    sanitizeCustom: sanitizeCustom,
    sanitizeOverrides: sanitizeOverrides,
    sanitizeContacts: sanitizeContacts,
    createGist: createGist,
    updateGist: updateGist,
    readSnapshot: readSnapshot,
    gistUrl: gistUrl
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = global.SMSSync;
})(typeof window !== 'undefined' ? window : globalThis);
