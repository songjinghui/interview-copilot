"""岗位来源接入的公共约定。

新增来源只应新增一个适配器与配置，不改动机会管理、投递、面试等核心流程
（VISION §4.2 可扩展接入原则）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..jobs.model import Capability, CapabilityStatus, JobRecord, SourceCapabilities


class SourceError(Exception):
    """来源获取失败。区分失败类型，避免把“没取到数据”写成“没有岗位”。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class JobSource(ABC):
    """岗位来源适配器。

    能力声明与实现分开：`capabilities()` 说明当前验证到什么程度，调用方据此
    决定是否展示该来源，而不是假设“有代码”等于“已验证可用”。
    """

    key: str

    @abstractmethod
    def capabilities(self) -> SourceCapabilities:
        """分项声明搜索、详情、投递、反馈的当前状态与依据。"""

    @abstractmethod
    def search(self, keyword: str, city: str | None = None) -> list[JobRecord]:
        """按条件搜索岗位。未声明支持搜索的来源必须抛 SourceError。"""

    @abstractmethod
    def fetch_detail(self, source_job_id: str) -> JobRecord:
        """按来源岗位标识获取完整记录。未声明支持详情的来源必须抛 SourceError。"""

    def require(self, capability: Capability, action: str) -> None:
        """在执行动作前检查能力状态；未验证就拒绝执行，不做降级猜测。"""
        if capability.status is not CapabilityStatus.VERIFIED:
            raise SourceError(
                "capability_not_verified",
                f"{self.key} 的{action}当前状态为 {capability.status.value}，依据：{capability.basis}",
            )
