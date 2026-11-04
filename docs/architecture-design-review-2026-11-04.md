# 总体架构 v0.2 / 详细设计 v0.3 审查

日期：2026-11-04

审查者：砚砚（gpt-6-astra）

范围：[总体架构](architecture.md)、[前端设计](frontend-design.md)、[数据库设计](database-design.md)、[应用契约](application-contracts.md)、[DDL](schema.sql)

依据：[VISION.md](../VISION.md) v0.12，以及用户在本 thread 确认的首版收敛决定。

**结论：总体方向认可；详细设计退回补齐，暂不放行进入完整功能实现。** 本机后台、SQLite 与文件资产、按能力扩展来源、固定复盘输入版本、独立改进清单，可以作为后续实现方向。下面五项需要先把页面、命令和存储对齐，不需要推翻分层或增加部署服务。

本轮只新增本审查报告，未改动作者的设计或产品实现。所有发现均为 P2：设计契约或交付物缺口；尚未实现的流程不能称作已发生的产品故障。SQL 复现用于确认当前约束实际允许/拒绝什么，不代替未来应用服务的集成测试。

范围继续遵守用户已确认的决定：首版手动投递；有冷却期时两次确认，不增加练手/重点规则；音频本地转写，分析文字允许按配置外发，转写文本不做云端存储和同步。本轮不重新打开这些产品决定。

## R1 · P2 · 反馈消息与面试邀请的身份范围没有统一

**证据：** 应用契约 L143、L148 以 `(source_key, external_key)` 去重，换账号只换 `stream_key`；数据库设计 L100 把账号身份放在游标里。DDL L252–272 的反馈记录没有账号/流归属，唯一键也不包含它。DDL L283–289 又以 `(source_feedback_id, source_event_key)` 约束面试，而前端 L100 承诺同一邀请改期复用原面试。

**触发与实证：** 对同一来源创建账号 A、B 两条独立游标，分别写入各账号的消息 `42`，第二条被反馈唯一约束拒绝。换 `stream_key` 不能解决账号内编号冲突；适配器当前也没有必须为 `external_key` 编入账号身份的约定。另将两封不同消息关联同一 `source_event_key`，DDL 允许创建两场面试。后者表明当前约束不能保证改期去重，并不证明尚未实现的应用服务一定会重复创建。

**修订要求：** 明确两层身份：消息是来源、稳定账号/流身份、消息键；面试邀请是来源、稳定账号身份、邀请键。同一邀请可收到多条反馈，不能用某一条反馈 ID 作为邀请唯一性的组成部分。可以采用显式列/映射，也可规范化键，但必须写清编码范围、持久化归属和事务内查找更新规则；重新授权同一账号不应产生新的消息身份。

**复审验收：** A/B 账号同编号消息分别保留；同账号重复同步不增加记录；原邀请、改期、取消三条消息只更新一场面试及其提醒；两个账号的同名邀请键不串联。单纯把冲突写入改成 `INSERT OR IGNORE` 不满足验收。

## R2 · P2 · 多录音组合后的文本缺少可恢复的音频来源关系

**证据：** 前端 L112 承诺选择/组合多个录音、保存片段来源、点击时间定位音频。DDL L345–369 的整份文字版本只能引用一个 `audio_asset_id`，片段只有起止时间，没有来源录音或原文字片段引用；应用契约 L93 也只接收单个音频。数据库设计 L46 的 `audio_parts` 描述连续录制片段，没有规定如何把已有独立录音组成新的时间轴。

**触发场景：** 一场面试导入 A、B 两个文件，两份转写都存在 `00:30`。合并成一份文字后，现有保存契约无法说明某段 `00:30` 来自 A 还是 B。只保留文本与时间会让报告原话无法准确回放；把来源编码进自由文本或段落 key 也没有对应契约。

**修订要求：** 把组合操作落实到输入与持久化关系。例如在片段上保存来源音频/片段及原始时间；或明确定义复合音频资产、时间轴映射和创建命令。已有 `audio_parts` 可以复用，但需说明来源追溯、合并后的偏移以及校对继承规则。当前文档不足以据此实现已承诺的组合视图。

**复审验收：** A、B 均含相同时间码；组合、校对、关闭程序并重开后，点击两个引用分别播放正确文件和区间，历史报告仍定位原版本。

## R3 · P2 · 显式重新转写与自动恢复共用了过强的唯一约束

**证据：** 总体架构 L212 明确“重新转写”创建新的处理请求版本，自动恢复复用原任务。DDL L335–344 却对 `(audio_asset_id, asset_revision, config_hash)` 全局唯一；应用契约 L97 禁止成功任务重跑，且没有创建新处理请求的命令。数据库设计 L135 只描述更换模型配置后创建新任务。

**触发与实证：** 同一音频、同一模型配置，用户主动要求再转一次，即使给第二个后台任务独立 ID 和 `dedup_key`，第二条 `transcription_jobs` 仍被唯一约束拒绝。删除旧结果或仅为绕过约束伪造模型配置变化，会破坏既有的历史/配置含义。

**修订要求：** 在转写处理请求中表达显式请求版本/代次，并补创建命令及幂等规则。同一请求的自动重试、唤醒恢复继续复用原任务；用户明确新建请求才能生成新任务及文本版本，保留旧结果与校对内容。

**复审验收：** 重复通知和服务重启只产生一份结果；同配置主动重新转写可保留第二份结果；重复发送同一个重新转写命令只建一个新请求。

## R4 · P2 · 无简历准备的例外说明没有确定的持久化位置

**证据：** 应用契约 L81 接受 `resume_exception`；数据库设计 L123 要求将“此渠道无需简历”的说明保存到冷却期以外的命令快照。但 DDL L209–226 的准备记录没有该字段或该快照；L415–421 的回执只有请求哈希和响应，没有请求内容。冷却期快照的结构也只允许冷却期字段。

**触发场景：** 用户填写无需简历的说明并确认，刷新或重启后再次读取准备记录，无法依据当前设计取回这条业务说明，确认页面也无法区分“明确无需简历”和“尚未选材料”。即使临时把说明放进某次命令响应，也缺少按准备 ID/修订读取当前说明的明确关系。

**修订要求：** 在准备记录中定义例外说明字段或材料输入快照，并在读取结果和申请事件快照中保留。约定缺少简历时必须有非空说明；修改说明与修改材料一样清除确认。请求哈希不能代替用户可恢复的业务数据。

**复审验收：** 无简历且无说明不能确认；有说明可按冷却期状态完成一/两次确认；刷新、重启仍能读取说明；修改说明清除旧确认，已记录申请的原说明保持不变。

## R5 · P2 · 详细设计引用的交付物尚未落盘，总览状态也未同步

**证据：** 实际文件清单中缺少以下三个已被正文链接的文件：

- 前端设计 L5：`docs/prototypes/workbench.html`。
- 数据库设计 L5：`docs/schema-reference.md`。
- 数据库设计 L175：`docs/design-checks/validate_design.py`。

总体架构 L3、L11、L273–281 仍写详细设计尚未形成独立交付物；事实上三份详细设计及 SQL 草案已经存在，但处于本次待修订状态。不能继续用旧状态概括，也不能直接改成“已完成”。

**修订要求：** 补齐原型和实际可运行的设计检查，生成字段字典，并更新总览对这些文件和审查状态的索引。字段字典只从 SQL 派生，继续保持 SQL 为唯一字段定义。原型应覆盖手动投递两次确认、直接补录面试、后台任务与复盘输入选择；按钮和页面中的文字需要实际渲染可见。

**复审验收：** 仓库链接均可打开；原型的关键路径可点击；检查脚本在空的隔离数据库可执行并报告范围；上述 R1–R4 的契约与相应设计检查同步。不能把本报告的临时 SQL 探针称为作者已经交付的检查脚本。

## 验证记录及其边界

审查针对工作区中的未提交设计，Git HEAD 为 `87b34ac421b3c21438cf91de9b063b06db6a9ece`，不能把该提交号当作新设计版本。本轮实际运行：

```powershell
python -X utf8 -m unittest discover -s tests -t . -v
# 16 tests, OK
python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -v
# 17 tests, OK
```

将 `docs/schema.sql` 执行于 SQLite `:memory:`：36 张表成功建立，`foreign_key_check` 返回空集，`integrity_check` 返回 `ok`。以下探针另确认 R1/R3 的约束行为。它们没有连接用户数据库或外部招聘服务。

| 探针 | 实际结果 | 可以得出的结论 |
|---|---|---|
| 不同账号游标、同来源消息键 `42` | 第二条反馈触发唯一约束 | 仅换游标不能隔离反馈身份 |
| 两条反馈、同一邀请键 | 可保存 2 场面试 | 当前唯一约束不能独立保证改期复用 |
| 两个任务、同音频修订与配置 | 第二条转写子记录触发唯一约束 | 当前结构不支持同配置的独立处理请求 |
| DDL 列检查 | 无例外说明/材料快照；文字片段无音频来源列 | 必须补明确存储或映射契约，不能只补页面提示 |

现有 33 项测试通过只代表探路代码和原验证脚本的已有覆盖。前端、录音设备、后台恢复、反馈同步、复盘生成均未在本轮取得实现验收证据。旧报告中 A → B → A 的存储缺陷已在新设计中规定修法，但产品代码仍待测试先行修复，不计作本次新增设计发现。

### SQL 探针重现方式

在仓库根目录用 Python 执行下列代码，仅操作内存数据库；打印的是问题复现结果，不是目标行为已通过：

```python
from pathlib import Path
import json
import sqlite3

db = sqlite3.connect(':memory:')
db.executescript(Path('docs/schema.sql').read_text(encoding='utf-8'))
now = '2026-11-04T08:23:56.000Z'

def add(table, **fields):
    sql = ('INSERT INTO ' + table + ' (' + ','.join(fields) + ') VALUES ('
           + ','.join('?' for _ in fields) + ')')
    db.execute(sql, list(fields.values()))

add('sources', key='mail', display_name='Mail', adapter_version='1', updated_at=now)
for account in ['A', 'B']:
    add('sync_cursors', source_key='mail', stream_key=account,
        cursor_json=json.dumps({'account': account}))
add('feedback_items', id='f1', source_key='mail', external_key='42',
    text_content='Account A', received_at=now)
try:
    add('feedback_items', id='f2', source_key='mail', external_key='42',
        text_content='Account B', received_at=now)
except sqlite3.IntegrityError as error:
    print('account collision:', error)

add('feedback_items', id='f3', source_key='mail', external_key='43',
    text_content='Rescheduled invitation', received_at=now)
add('opportunities', id='o1', title='Role', company_name='Company',
    created_at=now, updated_at=now)
for feedback, day in [('f1', '05'), ('f3', '06')]:
    add('interviews', id='i-' + feedback, opportunity_id='o1', label='Round 1',
        starts_at=f'2026-11-{day}T02:00:00.000Z', time_zone='Asia/Shanghai',
        format='online', source_feedback_id=feedback, source_event_key='event-1',
        created_at=now, updated_at=now)
print('same invitation rows:', db.execute('SELECT count(*) FROM interviews').fetchone()[0])

add('audio_assets', id='a1', interview_id='i-f1', revision=1, origin='import',
    status='finalized', completeness='complete', created_at=now)
for request in ['first', 'explicit-rerun']:
    add('background_tasks', id=request, kind='transcribe', dedup_key=request,
        input_json='{}', created_at=now, updated_at=now)
    try:
        add('transcription_jobs', task_id=request, audio_asset_id='a1',
            asset_revision=1, config_hash='same-config', config_json='{}')
    except sqlite3.IntegrityError as error:
        print('retranscription collision:', error)
print('foreign keys:', db.execute('PRAGMA foreign_key_check').fetchall())
print('integrity:', db.execute('PRAGMA integrity_check').fetchall())
db.close()
```

## 交接

宪宪先完成 R1–R5 的设计修订与缺失交付物，再交本审查者复审。通过后按应用契约中的顺序推进实现，遵守仓库测试先行要求。本次无需用户重新选择技术栈或增加产品规则。

审查文件指纹（SHA-256，供区分后续修订）：

```text
architecture.md          f23496b3d2da61f4c98d52d3bd74aa3c957b916be222e4ebd2f6128fd8db8893
frontend-design.md       e796d828fadd99cef5a2494adf05e450fcae377ba981064d950bdb437ff1feb9
database-design.md       e33c5eebb027c4aa5c67a9f2890bd5e6a3cb3ba37b697848e3c7cdf75dc2851c
application-contracts.md e457fd44314903df286e0cbddc174094fcf1c8d5e5d187ff83b8858f1c0884f7
schema.sql              58e3a78796bb84ec9337d20fa95d2477d8df424fac13325059f17a8b59479172
```
