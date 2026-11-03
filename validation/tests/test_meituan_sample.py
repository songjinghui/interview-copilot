import copy
import unittest
from unittest.mock import patch

import requests

from validation import probe
from validation.tests.test_probe import response


COMPANY = {
    "name": "美团",
    "career_home": "https://zhaopin.meituan.com/",
    "job_search": "https://zhaopin.meituan.com/web/social",
    "public_job_sample": True,
}
DETAIL = {"jobUnionId": "sample-42", "name": "测试岗位", "jobDuty": "测试职责", "jobRequirement": "测试要求", "cityList": []}


def api_response(data, status=200):
    import json
    return response(json.dumps(data, ensure_ascii=False), status=status, content_type="application/json")


class MeituanPublicSampleTests(unittest.TestCase):
    def run_sample(self, replies):
        with (
            patch.object(probe.requests, "get", return_value=response("<body>公开页面</body>")),
            patch.object(probe.requests, "post", side_effect=replies) as post,
        ):
            record = probe.probe_company(COMPANY)
        sample = record.get("job_sample")
        self.assertIsInstance(sample, dict, "开启公开岗位样本后应返回实际列表与详情的验证结果")
        return sample, post

    def listing(self):
        return api_response({"status": 1, "data": {"list": [{"jobUnionId": "sample-42"}]}})

    def test_list_to_detail_preserves_jd_and_uses_only_read_endpoints(self):
        sample, post = self.run_sample([self.listing(), api_response({"status": 1, "data": DETAIL})])
        self.assertEqual(sample["status"], "jd_sample_obtained")
        self.assertEqual(sample["job"]["source_id"], "sample-42")
        self.assertEqual(sample["job"]["requirements"], "测试要求")
        self.assertEqual(sample["application_status"], "not_tested")
        self.assertEqual(sample["feedback_status"], "not_tested")
        self.assertEqual(post.call_count, 2)
        first, second = post.call_args_list
        self.assertEqual(first.args[0], "https://zhaopin.meituan.com/api/official/job/getJobList")
        self.assertEqual(first.kwargs["json"]["page"], {"pageNo": 1, "pageSize": 1})
        self.assertEqual(second.args[0], "https://zhaopin.meituan.com/api/official/job/getJobDetail")
        self.assertEqual(second.kwargs["json"]["jobUnionId"], "sample-42")
        for call in post.call_args_list:
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertNotIn("cookies", call.kwargs)
            self.assertNotIn("auth", call.kwargs)
        self.assertEqual(len(sample["evidence"]), 2)
        self.assertRegex(sample["evidence"][1]["body_sha256"], r"^[0-9a-f]{64}$")

    def test_http_200_business_failure_stops_before_detail(self):
        sample, post = self.run_sample([api_response({"status": 0, "message": "需要登录"})])
        self.assertEqual(sample["status"], "not_verified")
        self.assertEqual(post.call_count, 1)
        self.assertIn("business_status", sample["error"])

    def test_empty_list_is_explicit_and_not_a_completed_search(self):
        sample, post = self.run_sample([api_response({"status": 1, "data": {"list": []}})])
        self.assertEqual(sample["status"], "no_jobs_returned")
        self.assertEqual(post.call_count, 1)

    def test_missing_requirements_does_not_pass_jd_validation(self):
        detail = copy.deepcopy(DETAIL)
        detail["jobRequirement"] = " "
        sample, _ = self.run_sample([self.listing(), api_response({"status": 1, "data": detail})])
        self.assertEqual(sample["status"], "incomplete_jd")
        self.assertIn("requirements", sample["missing_fields"])

    def test_detail_for_another_id_is_not_attached_to_selected_job(self):
        detail = {**DETAIL, "jobUnionId": "another-job"}
        sample, _ = self.run_sample([self.listing(), api_response({"status": 1, "data": detail})])
        self.assertEqual(sample["status"], "not_verified")
        self.assertIn("job_id_mismatch", sample["error"])

    def test_http_failure_does_not_retry_or_fetch_detail(self):
        sample, post = self.run_sample([api_response({}, status=403)])
        self.assertEqual(sample["status"], "not_verified")
        self.assertIn("HTTP 403", sample["error"])
        self.assertEqual(post.call_count, 1)

    def test_timeout_is_not_success(self):
        sample, post = self.run_sample([requests.exceptions.Timeout()])
        self.assertEqual(sample["status"], "not_verified")
        self.assertIn("Timeout", sample["error"])
        self.assertEqual(post.call_count, 1)

    def test_html_response_is_not_a_successful_job_list(self):
        sample, post = self.run_sample([response("<body>安全验证</body>")])
        self.assertEqual(sample["status"], "not_verified")
        self.assertIn("non_json", sample["error"])
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
