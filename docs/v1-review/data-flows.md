# 数据边界与跨块交互

状态：草案 v1，待审。返回[总览](README.md)。本文定义逻辑归属与交接，不创建新服务或新数据库。

## 1. 关系与写入归属

一套本地 SQLite 与资产目录即可承载首版。业务块通过应用命令修改所归属数据；跨块使用稳定 ID、明确版本和查询视图，不复制一份可变的“最新资料”到每个页面。

| 归属 | 已有表族 | 关键字段/关系 | 读者与写入限制 |
|---|---|---|---|
| M1 个人资料 | materials / material_versions | 一份简历身份对应多个不可变正文版本；版本→原件；fact_snapshot保存当时事实内容 | M3/M4/M6引用版本；不修改原版本 |
| M1 经历 | profile_facts | kind、content、draft/confirmed/archived、provenance、revision | M2/M3/M6可读；生成材料仅使用已确认事实；修改事实不回写旧简历 |
| M2 目标 | profile_targets | criteria、active、revision | 搜索保存条件快照；履历中出现过某城市不代表目标城市 |
| M2 来源/岗位 | sources、source_capabilities、source_accounts；fetch_runs、jobs、job_versions、job_observations、search_matches | 来源岗位身份→内容版本→每次观察；匹配绑定任务和JD版本 | M3关联岗位；M4复用来源账号但不绕过权限；平台不成为核心代码固定枚举 |
| M3 机会/申请 | opportunities、opportunity_jobs、cooldown_notes、application_preparations、applications、application_events | 机会关联多个来源岗位；准备与申请事实分开；每次申请固定JD/简历版本 | M4通过命令更新机会；反馈不能直接覆盖确认历史；M6只读 |
| M4 反馈/日程 | feedback_items、sync_cursors、interviews、interview_context_versions、reminders | 账号+消息键去重；账号+邀请键识别同场；背景固定岗位名/JD/简历 | M5/M6以interview_id归属；取消日程不删除内容 |
| M5 面试内容 | audio_assets、audio_parts、transcription_jobs、transcript_versions、transcript_segments | 面试→音频→物理片段；面试→文字版本→段落；段落保留音频及原时间 | M6引用固定版本和段落；校对另存版本 |
| M6 分析/行动 | review_runs、review_reports、improvement_items、improvement_origins | run固定背景+文字+模型配置；report与run对应；行动独立、可有多个来源 | M1/M4读未完成行动；新报告不能修改用户进度 |
| G 共用设施 | settings、file_assets、background_tasks、command_receipts、schema_migrations | 配置、相对路径/哈希/文件状态、持久任务、请求回执、迁移校验 | 通过共用仓储/命令使用；不让页面或worker直接任意写表 |

这些表已在现有迁移中定义；该事实不表示全部服务和页面已完成。字段原文见[运行迁移](../../src/interview_copilot/storage/migrations/001_initial.sql)，业务语义见[数据库设计](../database-design.md)。

## 2. 需要补齐的契约

下列是本轮发现的增量设计，均待对应块审阅。优先扩充既有JSON契约和应用操作，确需新增字段或约束时采用新迁移。

| 编号 | 缺口 | 建议承载与约束 | 所属块 |
|---|---|---|---|
| D1 | 导入只得到正文，没有从原文生成经历草稿的完整操作 | 使用background_tasks的material_draft类型，并以input.purpose区分extract_facts/generate_resume；固定source_version_id；结果草稿写profile_facts，provenance指向原文版本及摘录；同任务重试不重复建条目 | M1 |
| D2 | 多份简历没有明确唯一默认选择；“材料身份”和“版本”容易混淆 | settings增加受验证的profile.default_material_id键；只有一份时自动选中，新增另一份不悄悄替换；该材料最新版本供日常查看，投递仍固定version_id；归档/删除与指针修复同事务 | M1 |
| D3 | 简历日期常只有年月，当前事实校验以完整日期为主 | content保留日期原文及精度；有确切日期才存确切日，不虚构月初；老数据兼容，查询/表单/校验一起更新 | M1 |
| D4 | cooldown_notes必须绑定机会，无法独自覆盖“候选即标注” | 候选规则证据先存job_observations.observed_json.cooldown（带结构版本、范围、原文/来源、核验时间）；M3确认适用后RecordCooldown，保存观察ID和判断依据。未建机会也能显示有/无/未知 | M2→M3 |
| D5 | 条件快照之外，资料参与匹配的依据也需固定 | 搜索task.input保存目标内容+revision；使用资料时再固定material_version_id或已确认事实快照；search_matches保留条件结论和JD摘录 | M2 |
| D6 | “下一步”不能靠伪造机会状态表达 | M4查询从待确认反馈、未来面试、到期提醒生成待办视图；自由沟通备注用机会note；笔试作为已确认反馈及后续安排展示，不强造投递成功或面试完成 | M4 |
| D7 | 导入预览、整理草稿与用户取消的恢复规则 | 用户选文件并开始导入后，本机保存staging资产/导入意图和可恢复文字草稿；页面标明未成为正式简历；确认后才建材料版本。取消不产生正式记录，显式丢弃可清除这次暂存；无自动TTL | M1、G |

D1中的事实提取任务在简历正文保存后启动，避免事实引用一个尚不存在的材料版本。确认经历不会反向改写这个原文版本；今后生成的新材料才存所采用事实的快照。外部整理模型的具体服务、文字范围、费用配置须在本块接入前明确。

D1任务去重建议使用源版本、配置哈希和用户主动重做代次组成dedup_key；重试不换代次。发布前核对owner_run_id与可发布状态，同事务保存草稿ID集合到result_json并标记成功，避免进程中断后重复发布。语义相似的已有经历由用户决定复用，不能用任务去重替代事实冲突判断。

## 3. 交互总表：操作如何改变数据

下列沿用现有命令名；“新增”表示待实现契约，不能当作已存在API。

| 操作 | 读取 | 写入/交接 | 事务和失败要求 |
|---|---|---|---|
| 导入并核对简历（M1） | 本机选定文件、已有同文件记录 | staging文件/意图→用户确认→ImportMaterial→材料版本 | 文件最终化与业务发布有恢复日志；重试复用request_id；未确认内容不冒充正式记录 |
| 整理与确认经历（M1，新增） | 固定材料版本、原文 | ExtractProfileFacts→草稿；ConfirmFact→确认事实 | 推理在写事务外；草稿来源校验，发布和任务成功同事务；重复执行同任务不重复生成事实 |
| 发起搜索（M2） | 目标、可用来源、可选资料快照 | SearchJobs→任务→逐源fetch_runs→岗位/版本/观察/匹配 | 网络在事务外；逐源结果可用；条件变化不重写旧搜索 |
| 选岗（M3） | 岗位记录、版本、候选冷却期证据 | SaveOpportunity/LinkJob；RecordCooldown | 同一岗位重复保存返回已有机会；跨渠道合并需确认 |
| 整理申请材料（M3） | 已确认事实、简历基版、目标JD | GenerateMaterialDraft→草稿→用户保存新material_version | 草稿不是正式投递材料；失败保留原材料；外部请求结果未知不自动反复扣费 |
| 确认与记录投递（M3） | 固定JD/简历、渠道、适用冷却期 | SavePreparation/ConfirmPreparation；RecordApplication→申请+event+receipt | 改关键输入清确认；打开链接不创建已提交记录；事实和历史同事务 |
| 接收反馈（M4） | 账号、游标、原消息、可能关联机会 | ImportFeedback/SyncFeedback→待确认；ResolveFeedback→确认结果 | 一页消息与游标推进同事务；冲突留证据；导入不自动发送回复 |
| 邀请转日程/改期（M4） | 明确机会、原邀请身份、已确认信息 | SaveInterview/SaveInterviewContext；提醒改排 | 同场邀请复用ID；日程与待发提醒调整同事务；取消不删材料 |
| 保存音频（M5） | 面试、已验证文件或主动录制结果 | ready文件→audio/parts+transcription task | 文件就绪后，音频登记与唯一入队同事务；页面关闭后任务仍在 |
| 转写/校对/组合（M5） | 固定音频、配置、旧文字版本 | 新transcript_version+segments，任务结果指向版本 | 结果发布核对本次执行身份；旧worker迟到不能覆盖；校对是新版本 |
| 发起复盘（M6） | 背景版本+文字版本+模型设置 | GenerateReview→task/run→report | 固定同一场面试输入；网络不占写锁；报告引用检查通过才发布 |
| 采纳与完成改进（M6） | 报告建议或手填 | Add/UpdateImprovement→item+origins；M4读未完成项 | 同建议重复采纳不重复；重算报告不改item；完成/重新打开保持时间一致 |
| 备份/恢复/清理（G） | DB快照、资产清单、引用关系 | 导出包/恢复到新目录/有范围的显式清理 | 不复制不一致的WAL文件集合；先验证恢复；不能顺带删被其他记录引用的资产 |

## 4. 历史版本示例

简历R的v1用于申请A；后来用户保存R的v2。日常资料页展示v2，A仍引用v1。面试I默认采用A的v1与当时JD，用户改选材料会生成新的背景版本。报告P固定背景C1和文字T1；校对产生T2后，P标注基于旧文字，重新生成得到新报告，已完成改进仍保留完成。

关系：材料身份1:N材料版本；机会M:N来源岗位；机会1:N申请/面试；面试1:N背景版本/文字版本；分析任务1:1报告；改进项1:N来源。

## 5. 跨块不变量

1. 原文、AI解释、用户确认事实分开；待分析文本中的指令不改变应用权限。
2. 可变记录通过revision检测冲突；不可变版本新增时核对parent。不得静默覆盖另一窗口修改。
3. 同request_id同输入返回原结果，改输入复用ID应拒绝；任务重试沿用任务身份，用户主动重做才创建新代次。
4. 查询中/查询失败/真实空数据分开；来源失败不推断无岗位，未收到反馈不推断被拒绝。
5. 文件状态ready才可作为输入；磁盘校验与事务发布要防文件被替换；不信任任意本机路径。
6. 默认持久保留；暂停、取消、归档不等于删除。数据清理需用户明确范围，备份/未来同步不夹带凭据或受限全文。
7. UI关闭与服务停止不同；暂停任务恢复后仍暂停。任务成功必须有已发布结果，健康端点不能证明业务链成功。
8. 共享基础只需一份实现；不为每个业务块再造任务队列、来源注册、资产管理和副本数据库。

## 6. 数据改动审阅与迁移

每块审阅列明新增/复用/修改的表或JSON字段、读写者、历史兼容和恢复方式。本轮只提出D1–D7，不改SQL。实现时先在空库和旧库副本运行测试，确认有针对性的失败，再新增迁移/实现；检查已有申请、面试和报告引用仍可读。无法迁移或会清除已有记录的方案不得悄悄执行。
