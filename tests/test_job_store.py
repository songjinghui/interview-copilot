"""存储测试：同岗位重复获取幂等，内容变化留历史版本。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interview_copilot.jobs.model import JobRecord  # noqa: E402
from interview_copilot.jobs.store import SqliteJobStore, content_hash  # noqa: E402


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


class UpsertTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SqliteJobStore(":memory:")
        self.addCleanup(self.store.close)

    def test_首次写入为新建(self) -> None:
        result = self.store.upsert(make_record())
        self.assertTrue(result.created)
        self.assertTrue(result.changed)

    def test_同内容重复获取不重复建档(self) -> None:
        self.store.upsert(make_record())
        again = self.store.upsert(make_record(fetched_at="2026-11-04T09:00:00+08:00"))

        self.assertFalse(again.created)
        self.assertFalse(again.changed)
        self.assertTrue(again.is_noop)
        self.assertEqual(len(self.store.versions("meituan", "4697320043")), 1)
        self.assertEqual(len(self.store.list()), 1)

    def test_内容变化留历史版本且最新生效(self) -> None:
        self.store.upsert(make_record())
        changed = self.store.upsert(
            make_record(
                requirements="硕士及以上，3 年以上经验",
                fetched_at="2026-11-05T09:00:00+08:00",
            )
        )

        self.assertFalse(changed.created)
        self.assertTrue(changed.changed)
        versions = self.store.versions("meituan", "4697320043")
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].requirements, "计算机相关专业本科及以上")
        self.assertEqual(
            self.store.get("meituan", "4697320043").requirements,  # type: ignore[union-attr]
            "硕士及以上，3 年以上经验",
        )

    def test_不同来源同编号互不覆盖(self) -> None:
        self.store.upsert(make_record())
        self.store.upsert(make_record(source_key="liepin"))
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(len(self.store.list("liepin")), 1)

    def test_缺失字段入库后仍为未知(self) -> None:
        record = make_record(company=None, salary_raw=None, experience_raw=None)
        self.store.upsert(record)
        loaded = self.store.get("meituan", "4697320043")

        self.assertIsNone(loaded.company)  # type: ignore[union-attr]
        self.assertIsNone(loaded.salary_raw)  # type: ignore[union-attr]
        self.assertIn("salary", loaded.missing_fields)  # type: ignore[union-attr]

    def test_未写入的岗位返回空(self) -> None:
        self.assertIsNone(self.store.get("meituan", "not-exist"))


class ContentHashTest(unittest.TestCase):
    def test_抓取时间不影响内容指纹(self) -> None:
        first = make_record(fetched_at="2026-11-03T12:00:00+08:00")
        second = make_record(fetched_at="2026-11-09T12:00:00+08:00")
        self.assertEqual(content_hash(first), content_hash(second))

    def test_内容变化会改变指纹(self) -> None:
        first = make_record()
        second = make_record(title="AI 应用开发工程师")
        self.assertNotEqual(content_hash(first), content_hash(second))


if __name__ == "__main__":
    unittest.main()
