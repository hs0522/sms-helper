"""마래푸중앙부동산 문자 도우미 — 윈도우 미니 위젯 (pywebview).

필라테스 계산기(projects/pilates-calculator/app.py)와 같은 방식의 frameless 데스크톱 창이다.
    · 기본 420×760 (최소 380×620) · 리사이즈 가능 · 마지막 위치/크기 기억
    · 상단 드래그 바 · 📌 항상 위 · — 최소화 · × 닫기
    · 실행할 때 한 번 widget-v* 릴리즈를 확인해 새 버전일 때만 `업데이트` 버튼
    · `복사하기` → Win32 클립보드(ctypes) → PowerShell Set-Clipboard 폴백

실행:
    python desktop/widget.py                 # 위젯 창
    python desktop/widget.py --selftest      # GUI 없이 확인
    python desktop/widget.py --selftest --strict   # pywebview 로딩까지 확인
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser

from version import WIDGET_VERSION


def _ensure_std_streams() -> None:
    """--windowed(PyInstaller) 빌드에서 print 가 창 모드 오류로 뜨지 않게 한다."""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        stream = getattr(sys, name)
        if stream is None:
            try:
                stream = open(fd, "w", encoding="utf-8", errors="replace", closefd=False)
            except OSError:
                stream = open(os.devnull, "w", encoding="utf-8")
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
        setattr(sys, name, stream)


def _say(text: str) -> None:
    try:
        print(text)
    except Exception:  # noqa: BLE001
        pass


_ensure_std_streams()

WINDOW_TITLE = "마래푸 문자 도우미"
DEFAULT_SIZE = (420, 760)
MIN_SIZE = (380, 620)

# 위젯 안의 내 정보·문구 수정·연락처는 웹 앱 localStorage 에 남는다.
# pywebview 는 기본이 private_mode(저장 안 됨)이고, 매번 다른 포트로 열면 저장소 출처가
# 바뀌어 설정이 사라진다. 그래서 로컬 서버를 고정 포트로 열고 개인정보 보호 모드를 끈다.
HTTP_PORT = 48231

REPO = "hs0522/sms-helper"
TAG_PREFIX = "widget-v"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_URL = f"https://github.com/{REPO}/releases"

HERE = os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    """PyInstaller(_MEIPASS)와 소스 실행 모두에서 동작하는 경로."""
    base = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(base, *parts)


def ensure_www() -> str:
    """묶인 www/index.html 경로. 소스 실행이면 그 자리에서 새로 만든다."""
    if getattr(sys, "_MEIPASS", None):
        return resource_path("www", "index.html")
    target = os.path.join(HERE, "www")
    index = os.path.join(target, "index.html")
    try:
        import prepare_www
    except Exception:  # noqa: BLE001
        return index
    if not os.path.exists(index):
        prepare_www.prepare(target)
    return index


# ---------------------------------------------------------------------------
# 상태 저장 (%APPDATA%/MaraepuSmsHelper/state.json)
# ---------------------------------------------------------------------------


def state_dir() -> str:
    base = os.getenv("APPDATA") or os.path.expanduser("~/.config")
    path = os.path.join(base, "MaraepuSmsHelper")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def state_path() -> str:
    return os.path.join(state_dir(), "state.json")


def load_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(**values) -> dict:
    state = load_state()
    state.update(values)
    try:
        tmp = state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, state_path())
    except Exception:  # noqa: BLE001
        pass
    return state


def webview_storage() -> str:
    """위젯 안에서 쓴 내 정보·문구·연락처(localStorage)를 보관하는 폴더."""
    path = os.path.join(state_dir(), "webview")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def pick_http_port() -> int | None:
    """고정 포트가 이미 쓰이면 None 을 줘 pywebview 가 빈 포트를 고르게 한다."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", HTTP_PORT))
        except OSError:
            return None
    return HTTP_PORT


# ---------------------------------------------------------------------------
# 클립보드 (Win32 ctypes → PowerShell Set-Clipboard)
# ---------------------------------------------------------------------------

CLIPBOARD_OPEN_RETRIES = 3
CLIPBOARD_RETRY_SLEEP = 0.03
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
CREATE_NO_WINDOW = 0x08000000


def _clipboard_payload(text: str) -> bytes:
    """CF_UNICODETEXT 는 UTF-16LE + 널 종료다."""
    return str(text).encode("utf-16-le") + b"\x00\x00"


def _set_clipboard_win32(text: str) -> bool:
    """Win32 클립보드에 UTF-16 문자열을 바로 넣는다.

    64비트 윈도우에서 ctypes 기본 인자 타입(int) 때문에 핸들이 잘리면
    GlobalLock·SetClipboardData 가 조용히 실패해 복사가 안 된 것처럼 보인다.
    모든 함수의 argtypes/restype 을 정확히 지정한다.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
        kernel32.GlobalFree.restype = wintypes.HANDLE
    except Exception:  # noqa: BLE001
        return False

    data = _clipboard_payload(text)

    opened = False
    for _ in range(CLIPBOARD_OPEN_RETRIES):
        try:
            if user32.OpenClipboard(None):
                opened = True
                break
        except Exception:  # noqa: BLE001
            return False
        time.sleep(CLIPBOARD_RETRY_SLEEP)
    if not opened:
        return False

    handle = None
    try:
        if not user32.EmptyClipboard():
            return False
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            return False
        handle = None  # 성공하면 클립보드가 메모리를 넘겨받는다
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if handle:
            try:
                kernel32.GlobalFree(handle)
            except Exception:  # noqa: BLE001
                pass
        try:
            user32.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


def _set_clipboard_powershell(text: str) -> bool:
    """ctypes 경로가 막힌 윈도우를 위한 마지막 수단.

    clip.exe 는 콘솔 코드페이지(cp949)로 해석해 한글이 깨지기 쉬워 쓰지 않는다.
    UTF-8 파일로 떨어 두고 PowerShell 이 그 파일을 읽어 Set-Clipboard 하게 한다.
    """
    if sys.platform != "win32":
        return False
    path = None
    try:
        import subprocess

        fd, path = tempfile.mkstemp(suffix=".txt", prefix="maraepu-sms-")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
            fp.write(text)
        literal = path.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop';"
            f"Get-Content -LiteralPath '{literal}' -Raw -Encoding UTF8 | Set-Clipboard"
        )
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return completed.returncode == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


def set_clipboard(text: str) -> bool:
    text = "" if text is None else str(text)
    if not text:
        return False

    if sys.platform == "win32":
        if _set_clipboard_win32(text):
            return True
        if _set_clipboard_powershell(text):
            return True

    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 업데이트 확인 — widget-v* 릴리즈만 본다 (안드로이드 APK v1.4.x 와 섞이지 않게)
# ---------------------------------------------------------------------------


def _version_tuple(text: str) -> tuple:
    parts = []
    for chunk in str(text).lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    a, b = _version_tuple(latest), _version_tuple(current)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def tag_version(tag: str, prefix: str = TAG_PREFIX) -> str:
    """`widget-v1.0.2` → `1.0.2`. 다른 태그(v1.4.9 APK 등)는 빈 문자열."""
    tag = str(tag or "")
    if prefix and tag.startswith(prefix):
        tag = tag[len(prefix):]
    elif prefix:
        return ""
    return tag.lstrip("vV")


def pick_latest_widget_release(releases, prefix: str = TAG_PREFIX):
    """릴리즈 목록에서 widget-v* 중 가장 높은 버전을 고른다 (초안·사전배포 제외)."""
    best = None
    best_key = None
    for item in releases or []:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        version = tag_version(item.get("tag_name", ""), prefix)
        if not version:
            continue
        key = _version_tuple(version)
        if best_key is None or key > best_key:
            best, best_key = (item, version), key
    return best


def github_token() -> str:
    token = os.getenv("MARAEPU_SMS_GH_TOKEN", "")
    if token:
        return token
    try:
        with open(os.path.join(state_dir(), "config.json"), encoding="utf-8") as fp:
            return str(json.load(fp).get("github_token", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def check_update(timeout: float = 5.0) -> dict:
    """최신 위젯 릴리즈를 확인한다. 실패해도 앱 동작에는 영향이 없다."""
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "MaraepuSmsHelper"},
    )
    token = github_token()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "current": WIDGET_VERSION, "available": False, "error": str(exc)}

    picked = pick_latest_widget_release(data)
    if not picked:
        return {"ok": True, "current": WIDGET_VERSION, "available": False}

    release, latest = picked
    return {
        "ok": True,
        "current": WIDGET_VERSION,
        "latest": latest,
        "tag": release.get("tag_name", ""),
        "available": is_newer(latest, WIDGET_VERSION),
        "url": release.get("html_url") or RELEASES_URL,
    }


# ---------------------------------------------------------------------------
# 위젯 / JS 브리지
# ---------------------------------------------------------------------------


class Widget:
    def __init__(self) -> None:
        self.window = None
        state = load_state()
        self.always_on_top = bool(state.get("always_on_top", True))
        self.x = state.get("x")
        self.y = state.get("y")
        width = state.get("width")
        height = state.get("height")
        self.width = max(int(width), MIN_SIZE[0]) if isinstance(width, int) else DEFAULT_SIZE[0]
        self.height = max(int(height), MIN_SIZE[1]) if isinstance(height, int) else DEFAULT_SIZE[1]

    # 창 위치·크기 기억 ------------------------------------------------
    def on_moved(self, *args) -> None:
        if len(args) >= 2 and all(isinstance(v, int) for v in args[:2]):
            self.x, self.y = int(args[0]), int(args[1])
            save_state(x=self.x, y=self.y)

    def on_resized(self, *args) -> None:
        if len(args) >= 2 and all(isinstance(v, int) for v in args[:2]):
            self.width = max(int(args[0]), MIN_SIZE[0])
            self.height = max(int(args[1]), MIN_SIZE[1])
            save_state(width=self.width, height=self.height)

    def on_closing(self, *_args) -> None:
        window = self.window
        if window is None:
            return
        values = {}
        try:
            x, y = window.x, window.y
            if isinstance(x, int) and isinstance(y, int):
                values.update(x=x, y=y)
        except Exception:  # noqa: BLE001
            pass
        try:
            width, height = window.width, window.height
            if isinstance(width, int) and isinstance(height, int):
                values.update(width=width, height=height)
        except Exception:  # noqa: BLE001
            pass
        if values:
            save_state(**values)

    def apply_on_top(self, value: bool) -> bool:
        self.always_on_top = bool(value)
        save_state(always_on_top=self.always_on_top)
        if self.window is not None:
            try:
                self.window.on_top = self.always_on_top
            except Exception:  # noqa: BLE001
                pass
        return self.always_on_top

    def create_window(self):
        import webview

        kwargs = dict(
            js_api=Api(self),
            width=self.width,
            height=self.height,
            min_size=MIN_SIZE,
            frameless=True,
            easy_drag=False,
            resizable=True,
            text_select=True,
            on_top=self.always_on_top,
        )
        if isinstance(self.x, int) and isinstance(self.y, int):
            kwargs.update(x=self.x, y=self.y)

        self.window = webview.create_window(
            WINDOW_TITLE, ensure_www(), **kwargs
        )

        for name, handler in (("moved", self.on_moved), ("resized", self.on_resized),
                              ("closing", self.on_closing)):
            event = getattr(self.window.events, name, None)
            if event is None:
                continue
            try:
                event += handler
            except Exception:  # noqa: BLE001
                pass
        return self.window

    def run(self) -> None:
        import webview

        self.create_window()
        webview.start(
            lambda: self.apply_on_top(self.always_on_top),
            http_server=True,
            http_port=pick_http_port(),
            private_mode=False,
            storage_path=webview_storage(),
        )


class Api:
    """desktop/www 의 index.html 이 window.pywebview.api 로 호출한다.

    pywebview 5.4 는 `dir(js_api)` 를 훑어 public 멤버를 함수 목록으로 만든다.
    `_` 로 시작하지 않는 속성이 있으면 그 객체를 재귀 탐색하다 실패해
    `window.pywebview.api` 가 통째로 비어 버린다(복사·닫기 모두 먹통).
    그래서 이 클래스는 메서드 말고 public 속성을 하나도 두지 않고,
    위젯 참조는 `self._widget` 으로만 보관한다.
    """

    def __init__(self, widget) -> None:
        self._widget = widget

    def _window(self):
        return getattr(self._widget, "window", None)

    # 창 제어 ----------------------------------------------------------
    def version(self):
        return {"version": WIDGET_VERSION, "repo": REPO, "web": web_version()}

    def minimize(self):
        window = self._window()
        if window is None:
            return False
        try:
            window.minimize()
        except Exception:  # noqa: BLE001
            return False
        return True

    def close(self):
        """JS 응답을 돌려주는 스레드에서 바로 destroy 하지 않고 조금 뒤에 닫는다."""
        window = self._window()
        if window is None:
            return False
        if getattr(self, "_close_requested", False):
            return True
        self._close_requested = True

        def _destroy() -> None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass

        timer = threading.Timer(0.05, _destroy)
        timer.daemon = False
        timer.start()
        return True

    def set_on_top(self, value=True):
        return self._widget.apply_on_top(bool(value))

    def get_window_state(self):
        return {
            "always_on_top": bool(getattr(self._widget, "always_on_top", True)),
            "width": getattr(self._widget, "width", DEFAULT_SIZE[0]),
            "height": getattr(self._widget, "height", DEFAULT_SIZE[1]),
        }

    def check_update(self):
        return check_update()

    def open_release(self, url=""):
        target = url if isinstance(url, str) and url.startswith("https://") else RELEASES_URL
        try:
            webbrowser.open(target)
        except Exception:  # noqa: BLE001
            return False
        return True

    # 복사 --------------------------------------------------------------
    def copy(self, text):
        return set_clipboard(str(text or ""))


# ---------------------------------------------------------------------------
# 실행 확인
# ---------------------------------------------------------------------------


def web_version() -> str:
    """묶인 index.html 이 어느 웹 버전(v1.4.9)인지."""
    try:
        with open(ensure_www(), encoding="utf-8") as fp:
            match = re.search(r'data-widget-web-version="([^"]+)"', fp.read())
        return match.group(1) if match else ""
    except Exception:  # noqa: BLE001
        return ""


def api_public_members() -> list:
    """pywebview 가 재귀 탐색할 위험이 있는 Api 의 public 비메서드 멤버."""
    class _StandIn:
        window = None
        always_on_top = True
        width = DEFAULT_SIZE[0]
        height = DEFAULT_SIZE[1]

    api = Api(_StandIn())
    return [
        name
        for name in dir(api)
        if not name.startswith("_") and not callable(getattr(api, name, None))
    ]


def api_has_no_public_attributes() -> bool:
    return not api_public_members()


def selftest(strict: bool = False) -> int:
    index = ensure_www()
    try:
        with open(index, encoding="utf-8") as fp:
            html = fp.read()
    except OSError:
        html = ""

    fake_releases = [
        {"tag_name": "v1.4.9", "html_url": "x"},
        {"tag_name": "widget-v1.0.0", "html_url": "a"},
        {"tag_name": "widget-v1.0.2", "html_url": "b"},
        {"tag_name": "widget-v1.0.1", "html_url": "c", "draft": True},
    ]
    picked = pick_latest_widget_release(fake_releases)

    checks = {
        "www/index.html": os.path.exists(index),
        "위젯 상단 바 주입": 'id="wbar"' in html and "widget/widget.js" in html,
        "위젯 스타일·스크립트": os.path.exists(os.path.join(os.path.dirname(index), "widget", "widget.js"))
        and os.path.exists(os.path.join(os.path.dirname(index), "widget", "widget.css")),
        "웹 버전": bool(web_version()),
        "widget-v* 만 고르기": bool(picked) and picked[1] == "1.0.2",
        "버전 비교": is_newer("1.0.1", "1.0.0") and not is_newer("1.0.0", "1.0.0"),
        "기본 크기 420×760": DEFAULT_SIZE == (420, 760),
        "최소 크기 380×620": MIN_SIZE == (380, 620),
        "클립보드 UTF-16": _clipboard_payload("가")[:2] == "가".encode("utf-16-le"),
        "Api public 속성 없음": api_has_no_public_attributes(),
        "JS 브리지 메서드": all(
            callable(getattr(Api, name, None))
            for name in ("version", "minimize", "close", "set_on_top", "get_window_state",
                         "check_update", "open_release", "copy")
        ),
    }
    ok = all(checks.values())

    webview_ok = False
    webview_note = ""
    try:
        import webview  # noqa: F401

        webview_ok = True
        webview_note = getattr(webview, "__version__", "unknown")
    except Exception as exc:  # noqa: BLE001
        webview_note = f"{type(exc).__name__}: {exc}"

    for name, passed in checks.items():
        _say(f"  [{'OK' if passed else 'FAIL'}] {name}")
    _say(f"  [{'OK' if webview_ok else 'FAIL'}] pywebview {webview_note}")
    _say(f"  version: {WIDGET_VERSION} | web: {web_version()} | state: {state_path()}")
    _say("selftest: " + ("OK" if ok and (webview_ok or not strict) else "FAIL"))
    return 0 if ok and (webview_ok or not strict) else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest(strict="--strict" in sys.argv)
    Widget().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
