import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from validation import probe


def response(html, status=200, url="https://careers.tencent.com/", content_type="text/html"):
    result = requests.Response()
    result.status_code = status
    result._content = html.encode("utf-8")
    result.encoding = "utf-8"
    result.url = url
    result.headers["Content-Type"] = content_type
    return result


class PublicPageProbeTests(unittest.TestCase):
    def fetch_page(self, html, **kwargs):
        with patch.object(probe.requests, "get", return_value=response(html, **kwargs)) as get:
            result = probe.fetch("https://careers.tencent.com/")
        get.assert_called_once()
        return result

    def test_200_verification_page_is_not_search_success(self):
        result = self.fetch_page("<title>安全验证</title><body>请完成安全验证后继续</body>")
        self.assertTrue(result["ok"])  # HTTP succeeded, content verification did not.
        self.assertEqual(result.get("page_state"), "verification_required")
        summary = probe.summarize({"type": "company", "name": "样本", "career_home": result, "job_search": result})
        self.assertIn("验证页", summary["search"])
        self.assertNotEqual(summary["search"], "可达")

    def test_app_shell_is_not_a_job_listing(self):
        result = self.fetch_page('<title>招聘</title><body><div id="app"></div><script src="app.js"></script></body>')
        self.assertEqual(result.get("page_state"), "html_shell")
        self.assertEqual(result.get("job_content_status"), "not_verified")

    def test_script_keywords_are_not_visible_auth_evidence(self):
        html = '<body><script>const strings = ["captcha", "login", "blocked"];</script><p>公开招聘内容</p></body>'
        result = self.fetch_page(html)
        self.assertFalse(result["indicators"]["has_captcha_keyword"])
        self.assertFalse(result["indicators"]["has_login_keyword"])
        self.assertFalse(result["indicators"]["has_block_keyword"])

    def test_visible_content_does_not_prove_full_jd_or_submission(self):
        result = self.fetch_page('<body><h1>工程师</h1><p>岗位职责：开发服务</p><a href="/apply">申请岗位</a></body>')
        self.assertEqual(result.get("page_state"), "html_content")
        self.assertEqual(result.get("job_content_status"), "not_verified")
        self.assertEqual(result.get("application_status"), "not_tested")
        self.assertEqual(result.get("feedback_status"), "not_tested")

    def test_redirect_destination_and_body_fingerprint_are_recorded(self):
        result = self.fetch_page("<body>招聘首页</body>", url="https://careers.tencent.com/zh-cn/")
        self.assertEqual(result.get("final_url"), "https://careers.tencent.com/zh-cn/")
        self.assertRegex(result.get("body_sha256", ""), r"^[0-9a-f]{64}$")

    def test_http_error_is_not_parsable_success(self):
        result = self.fetch_page("<body>Forbidden</body>", status=403)
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("page_state"), "http_error")

    def test_json_is_not_claimed_as_rendered_html(self):
        result = self.fetch_page('{"ok":false}', content_type="application/json")
        self.assertEqual(result.get("page_state"), "non_html")

    def test_timeout_is_explicit(self):
        with patch.object(probe.requests, "get", side_effect=requests.exceptions.Timeout):
            result = probe.fetch("https://careers.tencent.com/")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")
        self.assertEqual(result.get("page_state"), "request_failed")

    def test_company_selection_does_not_query_unselected_sources(self):
        page = {"ok": True, "status_code": 200, "elapsed_ms": 1, "page_state": "html_shell", "error": None}
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(probe, "RESULTS_DIR", directory),
                patch.object(probe, "fetch", return_value=page),
                patch.object(probe.time, "sleep"),
                patch("sys.argv", ["probe.py", "--companies", "腾讯", "--skip-platforms"]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                probe.main()
            report = json.loads((Path(directory) / "probe_report.json").read_text(encoding="utf-8"))
        self.assertEqual([company["name"] for company in report["companies"]], ["腾讯"])
        self.assertEqual(report["platforms"], [])


if __name__ == "__main__":
    unittest.main()
