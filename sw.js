/* 마래푸중앙부동산 문자 도우미 — 오프라인 캐시 (Service Worker)
   GitHub Pages 서브경로(/sms-helper/)에서도 동작하도록 모든 경로를 상대경로로 계산한다. */
'use strict';

var VERSION = 'v1.0.1';   // 웹 파일을 고칠 때마다 이 값을 올린다 — 폰에 새 버전이 바로 내려간다
var CACHE = 'sms-helper-' + VERSION;

// 이 파일 위치(sw.js가 있는 폴더)를 기준으로 상대경로를 해석한다
var ROOT = new URL('./', self.location.href);
function u(path) { return new URL(path, ROOT).href; }

var PRECACHE = [
  './',
  'index.html',
  'styles.css',
  'manifest.webmanifest',
  'js/icons.js',
  'js/core.js',
  'js/templates.js',
  'js/app.js',
  'assets/fonts/FreesentationVariable.woff2',
  'icons/icon-180.png',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-maskable-512.png'
].map(u);

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // 한 파일이 없어도 설치가 통째로 실패하지 않게 개별로 넣는다
      return Promise.all(PRECACHE.map(function (url) {
        return cache.add(new Request(url, { cache: 'reload' })).catch(function () { /* skip */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 화면 이동: 캐시에 있으면 먼저 보여 주고, 뒤에서 새 버전을 받아 둔다
  if (req.mode === 'navigate') {
    e.respondWith(
      caches.match(u('index.html')).then(function (hit) {
        var net = fetch(req).then(function (res) {
          if (res && res.ok) {
            var copy = res.clone();
            caches.open(CACHE).then(function (c) { c.put(u('index.html'), copy); });
          }
          return res;
        }).catch(function () { return hit; });
        return hit || net;
      })
    );
    return;
  }

  // 그 밖의 파일: 캐시 우선, 없으면 네트워크 → 받은 것은 캐시에 저장
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then(function (hit) {
      if (hit) return hit;
      return fetch(req).then(function (res) {
        if (res && res.ok && res.type === 'basic') {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      });
    })
  );
});
