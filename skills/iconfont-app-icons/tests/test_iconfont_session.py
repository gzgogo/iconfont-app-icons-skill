import importlib.util
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "iconfont_session.py"
SPEC = importlib.util.spec_from_file_location("iconfont_session", MODULE_PATH)
iconfont_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(iconfont_session)


class SessionStoreTests(unittest.TestCase):
    def sample_state(self):
        return {
            "cookies": [
                {
                    "name": "EGG_SESS_ICONFONT",
                    "value": "test-session-value",
                    "domain": ".iconfont.cn",
                    "path": "/",
                    "expires": time.time() + 3600,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "ctoken",
                    "value": "test-csrf-value",
                    "domain": "www.iconfont.cn",
                    "path": "/",
                    "expires": time.time() + 3600,
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "analytics_cookie",
                    "value": "unrelated-browser-state",
                    "domain": ".iconfont.cn",
                    "path": "/",
                    "expires": time.time() + 3600,
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                },
            ],
            "origins": [],
        }

    def test_import_storage_state_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "state.json"
            target = Path(tmp) / "private" / "iconfont" / "session.json"
            source.write_text(json.dumps(self.sample_state()), encoding="utf-8")

            result = iconfont_session.import_storage_state(source, target)

            self.assertEqual(result["cookie_count"], 2)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
            stored = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(stored["version"], 1)
            self.assertEqual(len(stored["cookies"]), 2)
            self.assertEqual(
                {cookie["name"] for cookie in stored["cookies"]},
                {"EGG_SESS_ICONFONT", "ctoken"},
            )

    def test_status_never_reveals_cookie_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "state.json"
            target = Path(tmp) / "session.json"
            source.write_text(json.dumps(self.sample_state()), encoding="utf-8")
            iconfont_session.import_storage_state(source, target)

            status = iconfont_session.session_status(target)
            serialized = json.dumps(status, ensure_ascii=False)

            self.assertTrue(status["authenticated_cookie_present"])
            self.assertNotIn("test-session-value", serialized)
            self.assertNotIn("test-csrf-value", serialized)
            self.assertIn("EGG_SESS_ICONFONT", status["cookie_names"])

    def test_cookie_header_filters_expired_and_wrong_domain(self):
        cookies = self.sample_state()["cookies"] + [
            {
                "name": "expired",
                "value": "bad",
                "domain": ".iconfont.cn",
                "path": "/",
                "expires": time.time() - 10,
                "secure": True,
            },
            {
                "name": "other",
                "value": "bad2",
                "domain": ".example.com",
                "path": "/",
                "expires": time.time() + 3600,
                "secure": True,
            },
        ]

        header = iconfont_session.build_cookie_header(
            cookies, "https://www.iconfont.cn/api/user/myprojects.json"
        )

        self.assertIn(
            f"{iconfont_session.AUTH_COOKIE_NAME}=test-session-value", header
        )
        self.assertIn(
            f"{iconfont_session.CSRF_COOKIE_NAME}=test-csrf-value", header
        )
        self.assertNotIn("expired", header)
        self.assertNotIn("other", header)

    def test_csrf_token_comes_from_ctoken_cookie(self):
        token = iconfont_session.find_csrf_token(self.sample_state()["cookies"])
        self.assertEqual(token, "test-csrf-value")


class ApiShapeTests(unittest.TestCase):
    def test_add_icons_payload_matches_iconfont_cart_shape(self):
        payload = iconfont_session.build_add_icons_payload(
            "12345",
            [
                {"id": "11", "project_id": "-1"},
                {"id": "22", "project_id": "987"},
            ],
            "csrf-token",
            now_ms=1700000000000,
        )

        self.assertEqual(payload["pid"], "12345")
        self.assertEqual(payload["ids"], "11|-1,22|987")
        self.assertEqual(payload["ctoken"], "csrf-token")
        self.assertEqual(payload["t"], "1700000000000")

    def test_discover_endpoints_from_manager_bundle(self):
        source = (
            'e.add([{name:"add_icons",url:"/api/project/addIcons.json",method:"POST"},'
            '{name:"project_lists",url:"/api/user/myprojects.json"},'
            '{name:"search_icons",url:"/api/icon/search.json",method:"POST"}])'
        )

        endpoints = iconfont_session.parse_endpoint_map(source)

        self.assertEqual(endpoints["add_icons"]["url"], "/api/project/addIcons.json")
        self.assertEqual(endpoints["add_icons"]["method"], "POST")
        self.assertEqual(endpoints["project_lists"]["method"], "GET")


if __name__ == "__main__":
    unittest.main()
