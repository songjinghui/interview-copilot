# 第 1 段实现与验证记录

2026-11-04 · 宪宪 / gpt-6-astra · 分支 `feat/storage-services` · 2026-11-05 更新：代码复审 approved，PR #1 已合并；[合并后隔离验收](storage-acceptance-2026-11-05.md)通过。下文保留实现与送审时的事实。

开工依据：[设计复审](architecture-design-review-2026-11-04.md)的 approved，基线提交 `e99aa01`。本段交付本地仓储、隔离迁移和不依赖 HTTP 的应用服务。设计放行与本段作者测试均不代表代码审查通过或首版产品完成。

## 已实现的行为

- 新库使用已批准的 37 表结构，开启外键、WAL、FULL 同步；迁移版本与校验和入库。运行时 SQL 随安装包发布，不读取工作区设计文件。测试逐项比较运行时与设计 SQL 的表、索引、触发器定义。未知库、旧格式库及错误校验和拒绝直接打开。
- JD 内容修订与观察分开。A→A 新增观察、更新获取时间；A→B→A 保留三次修订。获取方式、来源更新时间不制造内容修订。新的不完整观察不会被旧完整正文冒充；另有带独立观察时间的 `last_complete_version`。
- 简历版本、所用事实快照不可变。准备与申请引用固定 JD/简历版本；事实先 draft、显式确认后才可选入简历。文本编辑检查 parent version，防止覆盖并行修改。
- 准备只有材料确认，以及存在冷却期时的一次额外确认；unknown/有依据 absent 均一次。修改材料或更新未使用准备的冷却期会清确认。无简历说明持久保存并写进申请事件快照。
- 实际投递单独补记。确认准备、浏览外部链接不创建申请；历史补录不要求追补准备步骤。submitted 必须有实际时间与用户声明或回执依据。修正追加事件，旧事件保持原样。
- 命令变更、回执与响应在同一事务完成。相同 request ID 重试返回原结果；不同请求内容复用 ID 拒绝。可变实体使用 revision 检查，错误整体回滚。未声明字段、非法 JSON 版本、证据类型、UUID、日期与链接在写入前拒绝。
- 来源通过 `SearchJobs` / `ReadJob` / `ReadFeedback` 三个独立协议注册，没有投递端口。来源键不枚举平台；每项能力分别检查开关、证据阶段与连接状态。外部样本或独立脚本验证不会变成产品可用。注册表保存已安装代码；后续组合入口从数据库读取用户配置组装 descriptor，本段没有真实来源适配器或设置页面。

应用命令入口在 [application.py](../src/interview_copilot/application.py)：`SaveTarget`、`SaveFact`、`ConfirmFact`、`ImportMaterial`、`SaveMaterialVersion`、`SaveOpportunity`、`UpdateOpportunity`、`LinkJob`、`UnlinkJob`、`RecordCooldown`、`SavePreparation`、`ConfirmPreparation`、`DeferPreparation`、`RecordApplication`。领域异常供后续 HTTP 层映射；这里不创建 HTTP 会话、启动常驻服务或对外发送信息。

## 独立使用与迁移

安装包要求 Python ≥3.10，Python 自带 SQLite 须支持 JSON 函数。当前实测环境是 Windows / Python 3.13。开发环境可在本分支目录执行 `python -m pip install -e .`。所有数据库路径均由调用者显式提供，不扫描或切换用户正在使用的数据目录。

```powershell
python -m interview_copilot init-db --path C:\isolated-test\new.sqlite
python -m interview_copilot migrate-legacy --source C:\isolated-test\legacy.sqlite --output C:\isolated-test\migrated-bundle
```

上述为维护命令，不是应用启动命令。`init-db` 拒绝已存在路径；初始化失败可能保留本次创建的空文件，需检查后选新路径重试。库 API `Database(path)` 可以重开已知 v1 库。

`migrate-legacy` 只识别旧的 `jobs/job_versions` 两表格式，使用只读连接和 SQLite backup API 取得一致副本（包括已提交 WAL），再校验、迁移副本。目标目录必须不存在。成功发布的目录包含：

| 文件 | 含义 |
|---|---|
| `legacy-backup.sqlite` | 一致的旧库快照，可供核对 |
| `app.sqlite` | 独立的新库，含旧岗位、内容版本及观察 |
| `migration-report.json` | 旧版本 ID 到新版本的映射、岗位映射、计数与可检测的历史缺口警告 |

迁移先在目标父目录的新暂存目录内完成，并校验外键与完整性，关闭连接后通过 Windows 目录 rename 一起发布。目标已存在、数据损坏或发布失败不会覆盖源库或发布半成品；目录发布的拒绝覆盖行为以当前 Windows 平台为验收范围。没有修改真实运行库，也没有自动切换数据根目录。

旧程序已丢失的往返变化无法完整恢复。如果保存的当前内容与最后历史内容不同，迁移重建当前修订并标记时间不确定、记录 `LEGACY_HISTORY_GAP`；即使没有检测到缺口，也不能据此证明旧历史完整。备份与映射可供人工核对。

## 测试先行证据

实现前已有测试入口为 `tests/` 与 `validation/tests/`，均使用 unittest。先增加目标断言并运行，再修改对应实现：

1. JD 四个红测复现旧实现缺陷：A→B→A 仅两条历史、获取方式改变误增修订、重复内容仍读取旧获取时间、重开仍缺第三次修订。
2. 新仓储/迁移、应用服务、来源注册和维护 CLI 在入口未实现时，用明确的“目标功能缺失”断言失败；未用 import/config/syntax 错误冒充行为红测。随后实现同一批契约。
3. 结构化输入检查先证明错误证据、未知字段、非法日期、无来源的提取事实等会被错误保存或返回错误类型，再补校验并验证拒绝且不落盘。
4. 另增故障覆盖：JD 观察写入失败不残留新修订、回执写入失败回滚整次命令、两个连接重复请求只写一次、迁移 WAL、坏数据及发布失败。部分为已有事务行为的验证，未冒称全部经历红绿。

开发中发现过测试 fixture 的 SQLite context manager 未关闭连接，导致 Windows 临时目录清理报文件占用；已修正 fixture 显式 close。该环境清理问题不计入产品缺陷红测。

首次提交 `dae96d5` 的代码格式化后实际执行结果（保留初次验证事实；修订后结果见下节）：

| 检查 | 结果 | 边界 |
|---|---|---|
| `python -X utf8 -m unittest discover -s tests -t . -v` | 69/69 通过 | 领域模型、JD、事务命令、独立来源、迁移、CLI |
| `python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -v` | 17/17 通过 | 既有来源探测与固定样本回归，不代表真实平台可用 |
| `python -X utf8 docs/design-checks/validate_design.py` | 10/10 通过 | 设计 DDL 与跨表约束 |
| `node docs/design-checks/check_prototype.cjs` | 10/10 通过 | 原型源码交互，不是浏览器渲染 |
| `git diff --check` | 通过 | 空白检查 |
| 隔离复制源码 → 构建 wheel → 临时目录安装 → 工作区外 `init-db` | 通过 | wheel 内含运行时 SQL；不依赖 docs 或当前工作目录 |

总计 86 项 Python 测试与 20 项设计检查通过；打包检查单独计。所有数据库测试使用内存或临时目录。安装包验证只复制源码和 pyproject 到临时目录，未在项目里留下构建输出或新运行时依赖。

## 后续验收范围

本段没有页面工作台、HTTP 传输、真实来源调用、录音/ASR worker、反馈同步或复盘生成。浏览器渲染、焦点、缩放与点击，系统唤醒、录音硬件及外部平台验收保持待验，未重试此前被策略拒绝的浏览器命令。37 表建库不表示这些后续功能已经实现。

交缅因猫审查本分支的事务边界、历史保真、输入验证和迁移拒绝覆盖行为，通过后再进入下一段与合并流程。

## 2026-11-05 · S1/S2 审查修订

依据砚砚写入 main 的[审查报告](https://github.com/songjinghui/interview-copilot/blob/911cb8b/docs/storage-review-2026-11-04.md)，首次提交仍为 changes_requested。本节是作者修订证据，不代替复审 verdict。

- **S1：历史准备快照漂移。** `RecordApplication` 在准备关联未变时读取该申请当前 revision 的事件快照。结果、时间、回执纠正不再采样可变准备。显式更换 preparation_id 才校验并固定新准备，显式 null 解除关联；后续纠正沿用最近一次明确选择，旧事件完全保留。
- **S2：解除关联后旧准备仍可确认。** 删除关联与相关未使用准备清确认、revision+1 在同一事务。旧窗口收到修订冲突；重新读取返回 `relink_job`，确认入口再次检查关联。恢复关联后按原有一/两步重新确认，deferred 不被自动恢复。其他岗位的准备不受影响。
- **历史纠正路径。** 已发生申请及其事件不随解除当前关联而删除或变化。保留原 JD 修订可以继续纠正结果，改选另一个 JD 或新建申请仍需当前关联。已使用准备的保存状态保留，但当前查询动作同样受 relink_job 限制。
- **接口与页面设计同步。** application-contracts、database-design 和 frontend-design 已说明历史快照选择、解绑事务、relink_job 和重新确认行为；没有更改 SQL 或增加投递审批步骤。

新增 [test_application_review.py](../tests/test_application_review.py) 的 10 个用例。先在旧实现运行，确认历史快照漂移、重新关联跳过确认、旧 revision 未失效、重新读取后仍可确认等目标断言失败；历史纠正在解除关联后被错误拒绝也单独复现。另有跨机会拒绝、其他岗位不受影响及事务回滚等防退化用例，旧实现原本通过，不冒称这些用例先红。然后修改实现，10/10 通过。

格式化后完整回归：`python -X utf8 -m unittest discover -s tests -t . -v` **79/79**；`python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -v` **17/17**；合计 **96 项 Python 测试通过**。`git diff --check` 通过。数据库仍为内存/隔离临时目录。SQL、原型源码和打包配置未变，本轮没有重跑此前通过的设计检查或 wheel 实验，也未把其结果当作本轮独立重验。

修订后交精确新 HEAD 复审；未合并 PR，未进入第 2 段。
