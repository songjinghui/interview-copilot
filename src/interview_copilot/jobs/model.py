"""求职机会的领域模型：岗位记录与来源能力声明。

设计依据（单一真相源）：
- `VISION.md` §4.2 来源、岗位质量与跨渠道管理
- `VISION.md` §4.2 可扩展接入原则（按能力声明支持范围）

两条硬规则：
1. 缺失字段保留“未知”，不得由 AI 补写成已取得。
2. 来源能力必须分项声明状态并附依据；未验证不等于不支持。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class JdCompleteness(str, Enum):
    """JD 完整度。只有职责与任职要求两部分都有原文才算完整。"""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class CapabilityStatus(str, Enum):
    """能力状态。三态而不是布尔值，避免“未验证”被写成“不支持”。"""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Capability:
    """单项能力的声明，必须带依据与验证范围。"""

    status: CapabilityStatus
    basis: str
    evidence_ref: str | None = None
    verified_at: str | None = None
    environment: str | None = None

    def __post_init__(self) -> None:
        if not self.basis.strip():
            raise ValueError("能力声明必须写明依据，不接受空 basis")
        if self.status is CapabilityStatus.VERIFIED and not self.evidence_ref:
            raise ValueError("声明为已验证时必须提供 evidence_ref")


@dataclass(frozen=True)
class JobRecord:
    """一条来源岗位记录。

    只保存来源给出的原文与元数据；AI 的判断与匹配理由不进入本记录。
    """

    source_key: str
    source_job_id: str
    source_url: str | None
    title: str
    fetched_at: str
    fetch_method: str
    company: str | None = None
    publisher: str | None = None
    locations: tuple[str, ...] = field(default_factory=tuple)
    salary_raw: str | None = None
    experience_raw: str | None = None
    education_raw: str | None = None
    recruitment_project: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    source_refreshed_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_key", "source_job_id", "title"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        if self.source_url is None:
            if self.source_key != "manual" or self.fetch_method != "manual":
                raise ValueError("只有手工记录可以没有原始网址")
        elif not isinstance(self.source_url, str) or not self.source_url.strip():
            raise ValueError("source_url 不能为空字符串")
        if not isinstance(self.locations, tuple):
            raise ValueError("locations 必须是 tuple，避免可变默认值被共享")

    @property
    def missing_fields(self) -> tuple[str, ...]:
        """列出缺失的关键字段，供界面显示“未知”而不是静默补全。"""
        checks = {
            "company": self.company,
            "salary": self.salary_raw,
            "experience": self.experience_raw,
            "responsibilities": self.responsibilities,
            "requirements": self.requirements,
        }
        return tuple(name for name, value in checks.items() if not _has_text(value))

    @property
    def jd_completeness(self) -> JdCompleteness:
        if _has_text(self.responsibilities) and _has_text(self.requirements):
            return JdCompleteness.COMPLETE
        return JdCompleteness.INCOMPLETE


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())
