"""领域模型测试：缺失字段保留未知、JD 完整度、能力声明必须有依据。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interview_copilot.jobs.model import (  # noqa: E402
    Capability,
    CapabilityStatus,
    JdCompleteness,
    JobRecord,
)


def make_record(**overrides) -> JobRecord:
    base = dict(
        source_key="meituan",
        source_job_id="4697320043",
        source_url="https://example.com/job/4697320043",
        title="AI 全栈工程师",
        fetched_at="2026-11-03T12:00:00+08:00",
        fetch_method="public_query_post",
        company="美团",
        responsibilities="负责 AI 应用的设计与实现",
        requirements="计算机相关专业本科及以上",
    )
    base.update(overrides)
    return JobRecord(**base)


class JobRecordCompletenessTest(unittest.TestCase):
    def test_职责与要求都有时为完整(self) -> None:
        self.assertIs(make_record().jd_completeness, JdCompleteness.COMPLETE)

    def test_缺少任职要求时为不完整(self) -> None:
        record = make_record(requirements=None)
        self.assertIs(record.jd_completeness, JdCompleteness.INCOMPLETE)
        self.assertIn("requirements", record.missing_fields)

    def test_空白字符串不算已取得(self) -> None:
        record = make_record(responsibilities="   ")
        self.assertIs(record.jd_completeness, JdCompleteness.INCOMPLETE)

    def test_缺失薪资保留未知而不是补全(self) -> None:
        record = make_record(salary_raw=None, experience_raw=None)
        self.assertIn("salary", record.missing_fields)
        self.assertIn("experience", record.missing_fields)
        self.assertIsNone(record.salary_raw)

    def test_必填字段为空时拒绝构造(self) -> None:
        with self.assertRaises(ValueError):
            make_record(title="  ")


class CapabilityDeclarationTest(unittest.TestCase):
    def test_已验证必须给依据(self) -> None:
        with self.assertRaises(ValueError):
            Capability(status=CapabilityStatus.VERIFIED, basis="另一 Agent 实测")

    def test_未验证可以不带证据但必须写依据(self) -> None:
        capability = Capability(
            status=CapabilityStatus.UNVERIFIED, basis="本轮未执行真实搜索"
        )
        self.assertIs(capability.status, CapabilityStatus.UNVERIFIED)

    def test_依据为空时拒绝声明(self) -> None:
        with self.assertRaises(ValueError):
            Capability(status=CapabilityStatus.UNVERIFIED, basis="  ")


if __name__ == "__main__":
    unittest.main()
