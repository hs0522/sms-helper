"""윈도우 미니 위젯 — 단위 테스트 (GUI·pywebview 없이 실행).

    python -m pytest desktop/tests -q
    python desktop/tests/test_widget.py -v
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
ROOT = os.path.dirname(DESKTOP)
if DESKTOP not in sys.path:
    sys.path.insert(0, DESKTOP)

import prepare_www  # noqa: E402
import widget  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as fp:
        return fp.read()


class InjectionTest(unittest.TestCase):
    def setUp(self):
        self.html = read(os.path.join(ROOT, "index.html"))

    def test_bar_is_injected_before_app_header(self):
        out = prepare_www.inject_widget(self.html, "1.4.9")
        self.assertIn('id="wbar"', out)
        self.assertIn('data-widget-web-version="1.4.9"', out)
        self.assertIn("widget/widget.css", out)
        self.assertIn("widget/widget.js", out)
        self.assertLess(out.index('id="wbar"'), out.index('<header class="topbar">'))
        self.assertLess(out.index("widget/widget.css"), out.index("</head>"))
        self.assertLess(out.index("widget/widget.js"), out.index("</body>"))

    def test_bar_has_all_window_buttons(self):
        out = prepare_www.inject_widget(self.html, "1.4.9")
        for element in ('wbtn-pin', 'wbtn-min', 'wbtn-close', 'wbtn-update', 'wbar-drag',
                        'pywebview-drag-region'):
            self.assertIn(element, out)

    def test_pin_button_is_icon_only(self):
        """핀 버튼은 글자 없이 📌 만 — 이름은 aria-label·title 로 전한다."""
        out = prepare_www.inject_widget(self.html, "1.4.9")
        self.assertNotIn("pin-label", out)
        start = out.index('id="wbtn-pin"')
        opening = out.rindex("<button", 0, start)
        closing = out.index("</button>", start)
        button = out[opening:closing]
        self.assertIn('aria-label="항상 위 고정"', button)
        self.assertIn('title="항상 위 고정"', button)
        self.assertIn('aria-pressed=', button)
        self.assertEqual(button[button.index(">") + 1:].strip(), "📌")

    def test_injection_is_idempotent(self):
        once = prepare_www.inject_widget(self.html, "1.4.9")
        twice = prepare_www.inject_widget(once, "1.4.9")
        self.assertEqual(once, twice)
        self.assertEqual(twice.count('id="wbar"'), 1)
        self.assertEqual(twice.count("widget/widget.js"), 1)

    def test_web_service_worker_is_stripped(self):
        # 위젯은 로컬 서버로 열리므로 웹용 SW 캐시를 걷어낸다
        out = prepare_www.inject_widget(self.html, "1.4.9")
        self.assertIn("serviceWorker", self.html)
        self.assertNotIn("serviceWorker", out)

    def test_web_version_matches_bundled_app(self):
        version = prepare_www.web_version(ROOT)
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        sw = read(os.path.join(ROOT, "sw.js"))
        self.assertIn("'v%s'" % version, sw)


class PrepareWwwTest(unittest.TestCase):
    def test_prepare_copies_web_assets_and_widget_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "www")
            index = prepare_www.prepare(dest, ROOT)
            self.assertEqual(index, os.path.join(dest, "index.html"))

            html = read(index)
            self.assertIn('id="wbar"', html)
            self.assertIn('data-widget-web-version="%s"' % prepare_www.web_version(ROOT), html)

            for rel in ("styles.css", "manifest.webmanifest", "js/app.js", "js/templates.js",
                        "js/core.js", "icons/icon-192.png", "widget/widget.css", "widget/widget.js"):
                self.assertTrue(os.path.exists(os.path.join(dest, rel)), rel)

            # 데스크톱 소스·테스트가 www 안으로 새지 않는다
            self.assertFalse(os.path.exists(os.path.join(dest, "desktop")))
            self.assertFalse(os.path.exists(os.path.join(dest, "tests")))

    def test_prepare_rebuilds_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "www")
            prepare_www.prepare(dest, ROOT)
            stale = os.path.join(dest, "stale.txt")
            with open(stale, "w", encoding="utf-8") as fp:
                fp.write("old")
            prepare_www.prepare(dest, ROOT)
            self.assertFalse(os.path.exists(stale))


class ApiTest(unittest.TestCase):
    class _Stub:
        window = None
        always_on_top = True
        width = 420
        height = 760

    def test_widget_reference_is_private(self):
        api = widget.Api(self._Stub())
        self.assertIs(api._widget, api.__dict__["_widget"])
        self.assertFalse(hasattr(api, "widget"))

    def test_no_public_attributes_for_pywebview(self):
        # pywebview 5.4 의 get_functions 가 public 속성을 재귀 탐색하다 죽지 않게
        self.assertEqual(widget.api_public_members(), [])
        self.assertTrue(widget.api_has_no_public_attributes())

    def test_bridge_methods_exist(self):
        for name in ("version", "minimize", "close", "set_on_top", "get_window_state",
                     "check_update", "open_release", "copy"):
            self.assertTrue(callable(getattr(widget.Api, name, None)), name)

    def test_window_state(self):
        api = widget.Api(self._Stub())
        state = api.get_window_state()
        self.assertTrue(state["always_on_top"])
        self.assertEqual((state["width"], state["height"]), (420, 760))

    def test_set_on_top_delegates(self):
        calls = []

        class _W(self._Stub):
            def apply_on_top(self, value):
                calls.append(value)
                return value

        api = widget.Api(_W())
        self.assertTrue(api.set_on_top(True))
        self.assertEqual(calls, [True])

    def test_copy_uses_clipboard(self):
        original = widget.set_clipboard
        seen = []
        widget.set_clipboard = lambda text: seen.append(text) or True
        try:
            api = widget.Api(self._Stub())
            self.assertTrue(api.copy("안녕하세요"))
        finally:
            widget.set_clipboard = original
        self.assertEqual(seen, ["안녕하세요"])

    def test_close_without_window_is_safe(self):
        api = widget.Api(self._Stub())
        self.assertFalse(api.close())
        self.assertFalse(api.minimize())


class VersionTest(unittest.TestCase):
    def test_tag_only_accepts_widget_prefix(self):
        self.assertEqual(widget.tag_version("widget-v1.2.3"), "1.2.3")
        self.assertEqual(widget.tag_version("widget-v2.0"), "2.0")
        self.assertEqual(widget.tag_version("v1.4.9"), "")
        self.assertEqual(widget.tag_version("anything"), "")

    def test_is_newer(self):
        self.assertTrue(widget.is_newer("1.0.1", "1.0.0"))
        self.assertFalse(widget.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(widget.is_newer("0.9.9", "1.0.0"))
        self.assertTrue(widget.is_newer("1.0.10", "1.0.9"))

    def test_pick_latest_ignores_apk_tags_drafts_prereleases(self):
        releases = [
            {"tag_name": "v1.4.9"},
            {"tag_name": "widget-v1.0.0"},
            {"tag_name": "widget-v1.0.10"},
            {"tag_name": "widget-v1.0.2"},
            {"tag_name": "widget-v9.9.9", "draft": True},
            {"tag_name": "widget-v8.8.8", "prerelease": True},
        ]
        release, version = widget.pick_latest_widget_release(releases)
        self.assertEqual(version, "1.0.10")
        self.assertEqual(release["tag_name"], "widget-v1.0.10")

    def test_pick_latest_returns_none_without_widget_release(self):
        self.assertIsNone(widget.pick_latest_widget_release([{"tag_name": "v1.4.9"}]))
        self.assertIsNone(widget.pick_latest_widget_release([]))

    def test_default_and_min_sizes(self):
        self.assertEqual(widget.DEFAULT_SIZE, (420, 760))
        self.assertEqual(widget.MIN_SIZE, (380, 620))


class ClipboardTest(unittest.TestCase):
    def test_payload_is_utf16le_with_null(self):
        payload = widget._clipboard_payload("마래푸")
        self.assertEqual(payload, "마래푸".encode("utf-16-le") + b"\x00\x00")

    def test_empty_text_is_not_copied(self):
        self.assertFalse(widget.set_clipboard(""))


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self.old
        self.tmp.cleanup()

    def test_state_roundtrip(self):
        widget.save_state(x=-980, y=120, width=430, height=770, always_on_top=False)
        state = widget.load_state()
        self.assertEqual((state["x"], state["y"]), (-980, 120))
        self.assertEqual((state["width"], state["height"]), (430, 770))
        self.assertFalse(state["always_on_top"])
        with open(widget.state_path(), encoding="utf-8") as fp:
            self.assertTrue(json.load(fp))

    def test_widget_restores_size_and_never_below_min(self):
        widget.save_state(x=10, y=20, width=480, height=800, always_on_top=True)
        w = widget.Widget()
        self.assertEqual((w.width, w.height), (480, 800))
        self.assertEqual((w.x, w.y), (10, 20))

        widget.save_state(width=200, height=200)
        w = widget.Widget()
        self.assertEqual((w.width, w.height), widget.MIN_SIZE)

    def test_moved_and_resized_are_saved(self):
        w = widget.Widget()
        w.on_moved(300, 240)
        w.on_resized(500, 820)
        state = widget.load_state()
        self.assertEqual((state["x"], state["y"]), (300, 240))
        self.assertEqual((state["width"], state["height"]), (500, 820))

    def test_webview_storage_folder_is_under_appdata(self):
        path = widget.webview_storage()
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(path.startswith(self.tmp.name))

    def test_http_port_is_fixed_or_none(self):
        port = widget.pick_http_port()
        self.assertIn(port, (widget.HTTP_PORT, None))


class WidgetScriptTest(unittest.TestCase):
    def setUp(self):
        self.js = read(os.path.join(DESKTOP, "web", "widget.js"))
        self.css = read(os.path.join(DESKTOP, "web", "widget.css"))

    def test_copy_and_sms_hooks(self):
        for token in ("AndroidCopy", "AndroidSms", "#btn-copy, #btn-copy2", "call('copy'",
                      "check_update", "open_release", "set_on_top", "get_window_state"):
            self.assertIn(token, self.js)

    def test_drag_bar_css(self):
        self.assertIn("-webkit-app-region: drag", self.css)
        self.assertIn("padding-top", self.css)
        self.assertIn(".modal, .sheet", self.css)

    def test_pin_styles_are_icon_only(self):
        self.assertNotIn("pin-label", self.css)
        self.assertIn("#wbtn-pin", self.css)
        self.assertIn(".wbar-pin.is-on", self.css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
