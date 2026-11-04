# 第 1 段仓储与应用服务审查

审查者：砚砚 / gpt-6-astra

PR：[interview-copilot #1](https://github.com/songjinghui/interview-copilot/pull/1)

被审 HEAD：`dae96d55018ee7f349df0ea6bb7383c929f9e89c`；实现基线：`e99aa01c9cd6d4f5b248e96a4cb79f73a70fedc8`。

**Verdict：changes_requested。** 两项 P2 行为问题已用隔离临时库复现，需要修复并补测试后再审。本结论绑定上述实现提交，不撤销此前的设计开工批准。本轮没有修改 feature checkout 的产品或测试代码，没有合并 PR。

## S1 · P2 · 纠正历史投递结果会重新采样后来修改的准备材料

位置：[application.py L765–770](https://github.com/songjinghui/interview-copilot/blob/dae96d55018ee7f349df0ea6bb7383c929f9e89c/src/interview_copilot/application.py#L765-L770)、[L817–828](https://github.com/songjinghui/interview-copilot/blob/dae96d55018ee7f349df0ea6bb7383c929f9e89c/src/interview_copilot/application.py#L817-L828)。

`RecordApplication` 每次执行都通过 `get_preparation(preparation_id)` 读取当前准备，然后将它写入本次申请事件。纠正旧申请时，即使准备 ID、岗位、简历和渠道未变，也不会沿用先前已经固定的准备快照。

复现顺序：准备填写无需简历说明 A → 确认材料 → 补记实际结果为 unknown → 为后续操作把同一准备说明改成 B（清除确认）→ 收到原投递回执，只把旧申请结果纠正为 submitted。

实际：第一个事件的准备快照仍是 A/已确认，但第二个事件变成 B/未确认。用户没有纠正当时的准备依据，最新历史事件却带入了未来编辑。旧事件没有被原地覆盖；问题是后续历史快照对“当时说明和确认”的记录已经漂移。这与数据库设计 L98、L127 的当时快照约定不一致。

修订要求：仅纠正结果、时间或回执时，沿用该申请已固定的准备快照。若确实需要纠正历史准备关联，应有明确输入和校验，不能隐式读取可变准备代替历史。已有事件继续保持不可变。

补测：同一申请经历“未知 → 后改准备 → 回执确认”，第二个事件仍保留原准备说明、材料版本与确认时间；多次纠正及重开数据库保持这一结果。原来的 `test_resume_exception_snapshot_does_not_follow_later_preparation` 只回读第一个事件，没有覆盖再追加纠正事件。

## S2 · P2 · 解除岗位关联后，未使用准备仍能被确认成可投递

位置：[application.py L553–562](https://github.com/songjinghui/interview-copilot/blob/dae96d55018ee7f349df0ea6bb7383c929f9e89c/src/interview_copilot/application.py#L553-L562)、[L720–740](https://github.com/songjinghui/interview-copilot/blob/dae96d55018ee7f349df0ea6bb7383c929f9e89c/src/interview_copilot/application.py#L720-L740)。

`UnlinkJob` 删除当前关联并递增机会 revision，但不处理依赖这条关联的未使用准备；`ConfirmPreparation` 仅检查准备本身的 revision/步骤，不重新验证岗位是否仍属于该机会。

复现顺序：保存准备 P → 用户确认此来源岗位其实不属于本机会并执行 `UnlinkJob` → 另一窗口仍以 P 的旧 revision 确认材料。

实际：确认成功，返回 `ready_for_manual_apply`；机会的 `job_ids` 已为空。若随后按这份准备补记实际结果，`RecordApplication` 又因 `Job is not linked to this opportunity` 拒绝。相同业务关系在准备确认和结果记录两端不一致，也没有向旧窗口报修订冲突。

修订要求：解除关联时，在同一事务内失效相关未使用准备的确认和 revision，或明确拒绝尚有活动准备的解除操作；确认入口也须校验该准备当前可用。保留历史 JD/申请引用，不能用删除历史记录解决这一问题。

补测：覆盖 draft、第一步已确认及 ready 三种准备；解除关联后旧 revision 不能继续，重新读取也不能显示可直接投递。另核对已发生申请的历史可追溯性与允许的纠正路径，避免把当前来源关联变动等同于删除历史事实。

## 实际验证

- 在 `C:/Users/Administrator/projects/interview-copilot-storage` 验证 HEAD 与 PR 头均为 `dae96d5`；审查前工作区干净。
- 独立运行 `python -X utf8 -m unittest discover -s tests -t . -v`：69/69 通过。
- 独立运行 `python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -v`：17/17 通过。
- 新增的两个审查断言均因目标业务行为失败：S1 快照不等；S2 预期拒绝却没有抛出领域异常。不是导入、配置或环境故障。执行时 unittest 同时发现了导入的 17 个原有测试，实际输出为 19 项、2 项失败；下面重现代码限定只运行两个新增审查用例。
- 已阅读运行迁移、Database 事务、旧库迁移、CLI、岗位仓储、应用服务、来源协议/注册及相关测试。现有迁移测试验证了 WAL 快照、坏 JSON、未知 schema、目标存在和发布失败；本轮未发现新的迁移覆盖/发布问题。
- 没有重做作者的 wheel 安装实验，也没有把作者的打包记录写成审查者独立验证。浏览器、硬件、真实来源与后台 worker 仍不在本段实现范围。

### 两个失败断言的重现代码

在被审 feature checkout 根目录执行以下 Python 代码。复用测试 fixture，只创建临时数据库，结束时关闭连接并清理；不要指向真实运行库。

```python
import unittest
from tests.test_application import ApplicationTest

class ReviewRegression(unittest.TestCase):
    setUp = ApplicationTest.setUp
    command = ApplicationTest.command
    prep = ApplicationTest.prep

    def test_outcome_correction_preserves_original_preparation(self):
        p = self.prep(resume=False)
        ready = self.command(
            'ConfirmPreparation', p['revision'],
            preparation_id=p['id'], step='materials',
        )
        fields = dict(
            opportunity_id=self.opportunity['id'], preparation_id=p['id'],
            job_version_id=self.job.version_id, channel='Company website',
            evidence={'kind': 'user_attestation', 'statement': 'Checking receipt'},
        )
        original = self.command('RecordApplication', **fields, outcome='unknown')
        self.command(
            'SavePreparation', ready['revision'], id=p['id'],
            opportunity_id=self.opportunity['id'],
            job_version_id=self.job.version_id,
            resume_exception='Future application explanation',
            channel='Company website',
        )
        corrected = self.command(
            'RecordApplication', original['revision'], id=original['id'],
            **fields, outcome='submitted', submitted_at='2026-11-04T04:00:00Z',
            reason='Receipt now verified',
        )
        self.assertEqual(
            corrected['events'][-1]['snapshot']['preparation'],
            original['events'][0]['snapshot']['preparation'],
        )

    def test_unlink_invalidates_unused_preparation(self):
        p = self.prep()
        self.command(
            'UnlinkJob', self.opportunity['revision'],
            opportunity_id=self.opportunity['id'], job_id=self.job.job_id,
            basis={'kind': 'user_confirmed', 'description': 'This is a different job'},
        )
        with self.assertRaises(self.module.ApplicationError):
            self.command(
                'ConfirmPreparation', p['revision'],
                preparation_id=p['id'], step='materials',
            )

unittest.main(defaultTest='ReviewRegression', verbosity=2)
```

## 交接

宪宪先补上上述行为测试并确认失败，再修实现；运行相关测试和两套完整回归后，交新的精确 HEAD 复审。本轮不放行合并或进入后续实现段。
