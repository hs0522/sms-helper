"""v1.4.11 검수 컷 — downloads/v1.4.11-mobile-kbd-return.png · downloads/v1.4.11-widget.png

    LD_LIBRARY_PATH=/workspace/.libs/root/usr/lib/x86_64-linux-gnu python3 tests/capture_v1411.py

· 폰 390×844 — 본문을 직접 고친 뒤 키보드를 내렸을 때 하단 바만 깔끔하게 돌아오는 화면
· 윈도우 위젯 420×760 — 미리보기에 초점이 가도 하단 바(문자 앱 열기 · 복사하기)가 남는 화면
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS = '/workspace/downloads'
PORT = 8866


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def type_keyboard(pg, open_):
    if open_:
        pg.evaluate("""() => {
          Object.defineProperty(window.visualViewport, 'height',
            { configurable: true, get: () => window.innerHeight * 0.6 });
          window.visualViewport.dispatchEvent(new Event('resize'));
        }""")
    else:
        pg.evaluate("""() => {
          delete window.visualViewport.height;
          window.visualViewport.dispatchEvent(new Event('resize'));
        }""")
    pg.wait_for_timeout(200)


srv = Server(('127.0.0.1', PORT), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
pw = sync_playwright().start()
br = pw.chromium.launch()

# ---------- 폰: 본문 직접 수정 → 키보드 내림 ----------
ctx = br.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
pg = ctx.new_page()
pg.goto(f'http://127.0.0.1:{PORT}/index.html', wait_until='networkidle')
pg.evaluate('localStorage.clear()')
pg.reload(wait_until='networkidle')
pg.wait_for_timeout(300)
pg.click('#btn-sheet')
pg.wait_for_timeout(200)
pg.click('#sheet-list [data-id="t2"]')
pg.wait_for_timeout(350)
pg.fill('#fields [data-prop="prop"][data-key="dong"]', '404')
pg.fill('#fields [data-prop="prop"][data-key="ho"]', '1903')
pg.fill('#fields [data-prop="prop"][data-money="amount"]', '24억')
pg.wait_for_timeout(350)
pg.evaluate("""() => { document.querySelector('#preview').scrollIntoView({block: 'center'}); }""")
pg.wait_for_timeout(250)
pg.click('#preview')
pg.wait_for_timeout(200)
type_keyboard(pg, True)
pg.wait_for_timeout(250)
pg.screenshot(path=os.path.join(DOWNLOADS, 'v1.4.11-mobile-kbd-open.png'), full_page=False)
type_keyboard(pg, False)
pg.fill('#preview', pg.input_value('#preview') + '\n직접 고친 문장입니다')
pg.wait_for_timeout(200)
pg.evaluate("""() => { document.querySelector('#preview').scrollIntoView({block: 'center'}); }""")
pg.wait_for_timeout(200)
pg.screenshot(path=os.path.join(DOWNLOADS, 'v1.4.11-mobile-kbd-return.png'), full_page=False)
print('mobile note:', pg.inner_text('#edited-note'))
ctx.close()

# ---------- 윈도우 위젯 420×760 ----------
ctx = br.new_context(viewport={'width': 420, 'height': 760})
ctx.add_init_script('window.__WIDGET__ = true;')
pg = ctx.new_page()
pg.goto(f'http://127.0.0.1:{PORT}/index.html', wait_until='networkidle')
pg.evaluate('localStorage.clear()')
pg.reload(wait_until='networkidle')
pg.wait_for_timeout(300)
pg.evaluate("() => window.SMSApp.openTemplate('t8', {})")
pg.wait_for_timeout(350)
pg.fill('#fields [data-prop="prop"][data-key="dong"]', '208')
pg.fill('#fields [data-prop="prop"][data-key="ho"]', '1103')
pg.fill('#fields [data-prop="prop"][data-money="amount"]', '76000')
pg.wait_for_timeout(300)
pg.click('#preview')
pg.wait_for_timeout(300)
pg.screenshot(path=os.path.join(DOWNLOADS, 'v1.4.11-widget.png'), full_page=False)
print('widget bar visible:', pg.is_visible('#sms-mobile-bar'))
ctx.close()

br.close()
pw.stop()
srv.shutdown()
