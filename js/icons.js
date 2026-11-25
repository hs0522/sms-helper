/* 마래푸중앙부동산 문자 도우미 — 라인 아이콘 세트
 * 컬러 이모지 대신 24×24 격자에 그린 SVG 선 아이콘을 쓴다.
 *   SMSIcons.svg('home', 15)      -> 문자열
 *   SMSIcons.el('home', 15, 'x')  -> 엘리먼트
 *   SMSIcons.mount(document)      -> <span data-icon="home"> 안을 채운다
 */
(function (global) {
  'use strict';

  var P = {
    /* 브랜드 · 문자 */
    message: '<path d="M20.4 11.4c0 3.9-3.8 7.1-8.4 7.1-1 0-2-.16-2.9-.44L4.6 19.6l1.2-3.3a6.7 6.7 0 0 1-2.2-4.9c0-3.9 3.8-7.1 8.4-7.1s8.4 3.2 8.4 7.1Z"/><path d="M8.6 10.4h.01M12 10.4h.01M15.4 10.4h.01"/>',
    clipboard: '<rect x="5" y="4.4" width="14" height="16.2" rx="2.6"/><path d="M9 4.4v-.8c0-.6.5-1.1 1.1-1.1h3.8c.6 0 1.1.5 1.1 1.1v.8"/><path d="M8.6 9.9h6.8M8.6 13.4h6.8M8.6 16.9h4.4"/>',
    briefcase: '<rect x="3.4" y="7.4" width="17.2" height="12.2" rx="2.6"/><path d="M9 7.4V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.4M3.4 12.4h17.2"/>',
    send: '<path d="M20.6 3.4 10.2 13.8"/><path d="M20.6 3.4 14.2 20.6l-4-6.8-6.8-4 17.2-6.4Z"/>',
    tag: '<path d="M20.4 12.9 12.9 20.4a2 2 0 0 1-2.8 0L3.5 13.8V3.5h10.3l6.6 6.6a2 2 0 0 1 0 2.8Z"/><circle cx="8" cy="8" r="1.3"/>',

    /* 집 · 방문 */
    home: '<path d="M3.9 10.2 12 3.5l8.1 6.7v9.6a1 1 0 0 1-1 1h-4.6v-6.1h-5v6.1H4.9a1 1 0 0 1-1-1v-9.6Z"/>',
    users: '<circle cx="9.2" cy="8.6" r="3.1"/><path d="M3.4 19.4c.5-3 2.9-5 5.8-5s5.3 2 5.8 5"/><path d="M16.1 5.7a3 3 0 0 1 0 5.8"/><path d="M17.5 14.7c2 .7 3.3 2.3 3.6 4.7"/>',
    car: '<path d="M4 16.4V12l1.6-4.1A2 2 0 0 1 7.5 6.6h9a2 2 0 0 1 1.9 1.3L20 12v4.4"/><path d="M4 12h16"/><circle cx="7.6" cy="16.6" r="1.5"/><circle cx="16.4" cy="16.6" r="1.5"/>',
    layers: '<path d="M12 3.4 21 8l-9 4.6L3 8l9-4.6Z"/><path d="M3 12.2l9 4.6 9-4.6"/><path d="M3 16.4l9 4.6 9-4.6"/>',
    heart: '<path d="M12 20.1s-7.5-4.6-7.5-10A4.2 4.2 0 0 1 12 7.2a4.2 4.2 0 0 1 7.5 3c0 5.4-7.5 9.9-7.5 9.9Z"/>',

    /* 계약 */
    calendar: '<rect x="3.6" y="5.3" width="16.8" height="15.1" rx="2.4"/><path d="M3.6 9.9h16.8M8 3.2v4.2M16 3.2v4.2"/>',
    'calendar-check': '<rect x="3.6" y="5.3" width="16.8" height="15.1" rx="2.4"/><path d="M3.6 9.9h16.8M8 3.2v4.2M16 3.2v4.2"/><path d="M9 15.4l2 2 4-4"/>',
    pen: '<path d="M15.4 4.6 19.4 8.6 9 19H5v-4L15.4 4.6Z"/><path d="M13.4 6.6 17.4 10.6"/>',
    'file-text': '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5l-5-5Z"/><path d="M14 3.5v5h5"/><path d="M8.4 13h7.2M8.4 16.5h4.6"/>',
    calculator: '<rect x="4.6" y="3.4" width="14.8" height="17.2" rx="2.6"/><rect x="7.6" y="6.2" width="8.8" height="3.1" rx="1"/><path d="M8.2 12.9h.01M12 12.9h.01M15.8 12.9h.01M8.2 16.4h.01M12 16.4h.01M15.8 16.4h.01"/>',
    key: '<circle cx="8.6" cy="15.4" r="3.9"/><path d="M11.4 12.6 20 4M17.2 6.8l1.9 1.9M15 9l1.9 1.9"/>',
    phone: '<path d="M7.8 3.9h-1A2.5 2.5 0 0 0 4.3 6.6c.5 6.8 5.8 12.1 12.6 12.6a2.5 2.5 0 0 0 2.7-2.5v-1a1.6 1.6 0 0 0-1.2-1.6l-2.3-.6a1.6 1.6 0 0 0-1.6.5l-.8.9a12 12 0 0 1-5.3-5.3l.9-.8a1.6 1.6 0 0 0 .5-1.6l-.6-2.3a1.6 1.6 0 0 0-1.4-1Z"/>',

    /* 화면 버튼 */
    refresh: '<path d="M4.9 9.4A8 8 0 0 1 19.4 8"/><path d="M19.5 4.1v3.9h-3.9"/><path d="M19.1 14.6A8 8 0 0 1 4.6 16"/><path d="M4.5 19.9V16h3.9"/>',
    settings: '<circle cx="12" cy="12" r="3.1"/><path d="M12 3.4v2.2M12 18.4v2.2M3.4 12h2.2M18.4 12h2.2M6 6l1.6 1.6M16.4 16.4 18 18M18 6l-1.6 1.6M7.6 16.4 6 18"/>',
    copy: '<rect x="8.4" y="8.4" width="11.2" height="11.2" rx="2.6"/><path d="M15.6 8.4V6.4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.6a2 2 0 0 0 2 2h2"/>',
    list: '<path d="M8.4 6.5h11.2M8.4 12h11.2M8.4 17.5h11.2"/><path d="M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>',
    search: '<circle cx="11" cy="11" r="6.2"/><path d="M15.6 15.6 20 20"/>',
    dot: '<circle cx="12" cy="12" r="7"/>'
  };

  function svg(name, size, cls) {
    var body = P[name] || P.dot;
    var s = size || 16;
    return '<svg class="ico' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" width="' + s + '" height="' + s +
      '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false">' + body + '</svg>';
  }

  function el(name, size, cls) {
    var wrap = document.createElement('span');
    wrap.className = 'ico-wrap' + (cls ? ' ' + cls : '');
    wrap.innerHTML = svg(name, size);
    return wrap;
  }

  function mount(root) {
    var box = root || document;
    var list = box.querySelectorAll('[data-icon]');
    for (var i = 0; i < list.length; i++) {
      var node = list[i];
      if (node.getAttribute('data-icon-done') === '1') continue;
      var size = Number(node.getAttribute('data-icon-size')) || 16;
      node.innerHTML = svg(node.getAttribute('data-icon'), size);
      node.setAttribute('data-icon-done', '1');
      node.classList.add('ico-wrap');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mount(document); });
  } else {
    mount(document);
  }

  global.SMSIcons = { svg: svg, el: el, mount: mount, has: function (n) { return !!P[n]; }, NAMES: Object.keys(P) };
})(typeof window !== 'undefined' ? window : globalThis);
