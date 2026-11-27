/* 마래푸 문자 도우미 — 윈도우 미니 위젯 상단 바 동작
 *
 * 웹 앱 화면은 그대로 두고, 위젯에서만 필요한 것만 브리지(window.pywebview.api)로 잇는다.
 *   - 📌 핀(항상 위 고정) / — 최소화 / × 닫기
 *     핀 버튼은 글자 없이 아이콘만이고, 이름은 aria-label·title 로 전한다.
 *   - 실행할 때 한 번 새 버전(widget-v*) 확인 → 새 버전이 있을 때만 `업데이트`
 *   - `복사하기`·`문자 앱 열기` → 윈도우 클립보드에 확실히 넣는다
 *     (웹 앱의 navigator.clipboard → execCommand → AndroidCopy 순서에서 마지막 단계도
 *      브리지로 연결하고, 대표 복사 버튼은 브리지로 바로 처리한다.)
 */
(function () {
  'use strict';

  var booted = false;
  var updateInfo = null;

  function $(id) { return document.getElementById(id); }

  function bridge() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  function asPromise(value) {
    return value && typeof value.then === 'function' ? value : Promise.resolve(value);
  }

  function call(name) {
    var api = bridge();
    if (!api || typeof api[name] !== 'function') return Promise.resolve(null);
    var args = Array.prototype.slice.call(arguments, 1);
    try {
      return asPromise(api[name].apply(api, args));
    } catch (e) {
      return Promise.resolve(null);
    }
  }

  /* 웹 앱과 같은 모양의 안내 문구 */
  function toast(msg) {
    var box = $('toast');
    if (!box) {
      box = document.createElement('div');
      box.id = 'toast';
      box.className = 'toast';
      document.body.appendChild(box);
    }
    box.textContent = msg;
    box.classList.add('is-on');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { box.classList.remove('is-on'); }, 1800);
  }

  function previewText() {
    var box = $('preview');
    return box ? String(box.value || '') : '';
  }

  function copyViaBridge(text, done) {
    if (!text) { toast('문자 내용이 비어 있어요'); return; }
    call('copy', text).then(function (ok) {
      if (ok === false) { toast('복사에 실패했어요. 본문을 길게 눌러 복사해 주세요.'); return; }
      if (done) done();
    }, function () {
      toast('복사에 실패했어요. 본문을 길게 눌러 복사해 주세요.');
    });
  }

  /* 웹 앱이 마지막 단계에서 부르는 통로 — 위젯에서는 윈도우 클립보드로 */
  function installHooks() {
    window.AndroidCopy = {
      copy: function (text) {
        call('copy', String(text || ''));
        return true;
      }
    };
    // 데스크톱에는 문자 앱이 없다 — 완성 문구를 클립보드에 넣고 안내만 한다
    window.AndroidSms = {
      open: function (text) {
        copyViaBridge(String(text || ''), function () {
          toast('문자 내용을 복사했어요. 문자 앱에 붙여넣어 보내세요.');
        });
      }
    };
  }

  /* 대표 복사 버튼은 브리지로 바로 — 웹뷰의 클립보드 권한과 무관하게 100% */
  function installCopyShortcut() {
    document.addEventListener('click', function (e) {
      var btn = e.target && e.target.closest ? e.target.closest('#btn-copy, #btn-copy2') : null;
      if (!btn || !bridge()) return;
      e.preventDefault();
      e.stopPropagation();
      var label = btn.querySelector('.btn-label') || btn;
      var old = label.textContent;
      copyViaBridge(previewText(), function () {
        toast('복사했어요');
        label.textContent = '복사 완료';
        setTimeout(function () { label.textContent = old; }, 1400);
      });
    }, true);
  }

  function setPin(on) {
    var btn = $('wbtn-pin');
    if (!btn) return;
    btn.classList.toggle('is-on', !!on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function showUpdate(info) {
    var btn = $('wbtn-update');
    if (!btn || !info || !info.available) return;
    updateInfo = info;
    btn.textContent = '업데이트';
    btn.title = '새 버전 ' + (info.latest || '') + ' — 내려받기';
    btn.hidden = false;
  }

  function wire() {
    var pin = $('wbtn-pin');
    var min = $('wbtn-min');
    var close = $('wbtn-close');
    var upd = $('wbtn-update');

    if (pin) pin.addEventListener('click', function () {
      var now = !pin.classList.contains('is-on');
      setPin(now);
      call('set_on_top', now).then(function (value) {
        if (typeof value === 'boolean') setPin(value);
      });
    });
    if (min) min.addEventListener('click', function () { call('minimize'); });
    if (close) close.addEventListener('click', function () { call('close'); });
    if (upd) upd.addEventListener('click', function () {
      call('open_release', updateInfo && updateInfo.url ? updateInfo.url : '');
    });

    call('get_window_state').then(function (state) {
      if (state && typeof state.always_on_top === 'boolean') setPin(state.always_on_top);
    });
    // 실행할 때 한 번만 확인한다 — 이미 열어 둔 창에는 새 버전 안내가 뜨지 않는다
    call('check_update').then(showUpdate);
  }

  function boot() {
    if (booted) return;
    booted = true;

    var web = document.documentElement.getAttribute('data-widget-web-version') || '';
    var label = $('wbar-web');
    if (label && web) label.textContent = 'v' + web;

    installHooks();
    installCopyShortcut();
    wire();

    document.body.classList.add('is-widget');
  }

  function whenBridge() {
    if (bridge()) { boot(); return; }
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (bridge()) { clearInterval(timer); boot(); }
      else if (tries > 100) clearInterval(timer);   // 8초까지만 기다린다
    }, 80);
    window.addEventListener('pywebviewready', function () {
      if (bridge()) { clearInterval(timer); boot(); }
    });
    document.addEventListener('pywebviewready', function () {
      if (bridge()) { clearInterval(timer); boot(); }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', whenBridge);
  } else {
    whenBridge();
  }
})();
