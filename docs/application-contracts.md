# 应用接口与页面操作契约

版本：v0.3 · 2026-11-04 · 设计已审；第 1 段领域服务、第 2 段工作台 HTTP/页面已合并并隔离验收；第 3 段日程/提醒及已登记 WAV 资产自动建转写任务的服务层在独立工作区实现与测试中；上传、真实 ASR、录音采集与恢复待实现；宪宪 / gpt-6-astra（进度同步 2026-11-06）

本文件是前端与 Python 后台共同遵守的设计契约；第 1、2 段已实现其工作台范围内的领域调用和 HTTP 端点。第 3 段当前工作区新增日程/提醒持久化命令及查询，并可将已登记、校验通过的本机 WAV 资产事务性关联到面试并自动建立转写任务，尚未合并。该切片没有上传端点；任务因本机尚无转写模型/worker 而明确停在 `needs_attention`，不能称为已自动转写。真实提醒送达、录音、上传与其它格式导入、ASR、后台执行和重启恢复仍待实现和验收。当前 Windows 执行环境没有 IANA 时区数据库，日程命令会以 `TIMEZONE_DATA_UNAVAILABLE` 明确失败，不会仅凭名称格式放行；提供/部署时区数据的方案仍待确定，本切片未引入新依赖。时间戳按 UTC 绝对时刻保存，`time_zone` 是展示元数据，两者不要求输入字符串的 offset 相同。实体列见 [schema.sql](schema.sql)，页面见[前端设计](frontend-design.md)。领域服务不依赖 HTTP；HTTP 只是本机传输。合并后证据见[第 2 段隔离验收](workbench-acceptance-2026-11-06.md)。

## 1. 本机通信与请求通则

FastAPI 提供静态构建产物与 `/api/v1`，监听 `127.0.0.1:17863`（设置可改端口），禁止绑定所有网卡。Windows 用户级互斥锁保证一个服务/数据目录；端口冲突给出占用错误，不连接未知进程、不自动开放公网。开发 UI 通过 Vite 本机代理，生产同源，无通配 CORS。

启动入口通过当前用户 IPC 取得一次性 bootstrap nonce，将其放在 UI URL fragment；页面立即移除 fragment，经同源 `/session/exchange` 换取会话 token。nonce 有效期 60 秒且只用一次；token 保存 sessionStorage，仅属于当前页签会话，签名密钥放用户凭据设施，服务重启保持可验证。token 8 小时滑动有效，有效会话可续期；过期显示“重新打开求职助手”恢复。首次配置和重新授权由启动入口完成，不以没有凭据的健康检查放行。

所有 API（除无敏感数据的 health 和 nonce exchange）验证 Bearer token；严格校验 Host，写操作校验 Origin；只接受 JSON 命令与限定上传 content type。会话配置、外部 API key、文件路径不进入来源适配器日志。CSP 限制脚本到本机包，禁止第三方脚本/iframe；原始网页只保存为不可执行文本。外链允许 http/https 并带 noopener/noreferrer，阻止 javascript/file/custom scheme；浏览外链不赋予提交能力。

`GET /health` → `{service:'interview-copilot',api_version:1,state:'ready|starting|migration_required'}`，不返回用户数据。UI 断线指数退避 1/2/5/10 秒，恢复后重新查询；不会根据缓存自行执行确认或任务重试。

### 命令与返回

```json
POST /api/v1/commands
{
  "request_id": "uuid",
  "command": "ConfirmPreparation",
  "expected_revision": 3,
  "input": {"preparation_id": "uuid", "step": "materials"}
}
```

成功短命令 HTTP 200/201：`{data:{...},request_id}`；持久后台任务 HTTP 202：`{data:{task_id,status:'queued'},request_id}`。每次用户动作一个 request_id，断线重试复用；同 ID 不同规范化请求 hash 返回 `409 REQUEST_ID_REUSED`。命令结果与数据库修改、回执同事务提交；响应丢失时客户端以原 ID 重发得到原结果。长任务的“创建成功”和“工作成功”是两个状态。

修改已存在可变实体必须带 expected_revision；`UPDATE ... WHERE id=? AND revision=?`，不匹配返回 `409 REVISION_CONFLICT` 含最新 revision 和可公开当前字段。确认 step 不允许前端附“已成功”状态；由服务计算。新增默认期望无实体，存在时按该命令去重规则处理。幂等回执不自动过期。

错误：`{error:{code,message,fields?:{path:reason},retryable,details?:{}},request_id}`。HTTP 400 格式/未知命令；401 会话；403 来源/越权；404 资源；409 并发/状态/请求键冲突；422 业务字段；413 上传大小；429 速率；503 本机依赖未就绪。错误中不得夹带凭据、完整简历或转写原文。

所有时间 UTC，页面按保存时区展示。金额为 `{amount,currency,period}`。实体 ID 为 UUID 字符串，nullable 字段明确返回 null。集合 GET 参数 `limit` 默认 30，最大 100，`cursor` 为服务生成的不透明游标；响应 `{items,next_cursor,as_of}`。不能把无结果、尚未加载、查询失败混为一个空数组。

## 2. 查询端点及响应视图

| GET 路径 | 参数 / 核心响应 |
|---|---|
| `/dashboard` | `next_interviews,unlinked_feedback,attention_tasks,recent_opportunities,capabilities`；每组有更新时间 |
| `/profile` | `targets,facts,materials:[{id,label,latest_version}]`；draft/confirmed 分开 |
| `/materials/:id/versions` | 各修订文本摘要、文件元数据、事实引用；原件经资产端点获取 |
| `/sources` | 每来源 `key,display_name,enabled,capabilities:[name,enabled,evidence_status,stage,scope,available,unavailable_reason],connection_state,last_success_at` |
| `/jobs` | `search_task_id?,source_key?,completeness?,filter?`；结果包含岗位版本、匹配依据、观察时间与可用动作 |
| `/jobs/:id` | `current_observation,current_version,last_complete_version,versions,opportunities`；当前与历史完整内容明确分开 |
| `/opportunities` | `status?,query?,cursor?`；状态、最新事件、下一场面试 |
| `/opportunities/:id` | 聚合 jobs/preparations/applications/feedback/interviews，cooldown 为 latest notes 的可解释判断，附 revision |
| `/preparations/:id` | `job,resume,resume_exception,channel,cooldown_snapshot,status,revision,next_step:materials/cooldown/manual_apply/deferred/relink_job`；岗位已解除关联时返回 relink_job，不可确认或直接投递 |
| `/interviews` | `from?,to?,status?,cursor?`；有时间和时间未知分组 |
| `/interviews/:id` | `schedule,current_context,contexts,audio_assets,current_transcript,transcript_versions,reports,improvements`；大正文独立读 |
| `/transcripts/:version_id` | `interview_id,revision,origin,audio_asset_id,segments:[key,ordinal,speaker,text,audio_asset_id,source_version_id,source_segment_key,start_ms,end_ms]` |
| `/reports/:id` | 固定四项 inputs、body、引用链接、`stale,reasons`；正文不可变，stale 动态计算 |
| `/feedback` | `status?,cursor?`；待关联/待确认消息，原文和提取建议分开 |
| `/improvements` | `status?,priority?,opportunity_id?,cursor?`；独立事项与来源标签，不默认加载原文证据 |
| `/tasks`、`/tasks/:id` | `id,kind,status,stage,progress,attempt,queued_at,updated_at,can_pause,can_retry,error,result`；不暴露 worker 路径/内部凭据 |
| `/settings` | 已保存公开设置、凭据是否配置、系统可用能力、后台状态 |
| `/assets/:id/content` | 鉴权流，音频支持 Range；原件下载用受控 Content-Disposition，未知 HTML 不内联执行 |
| `/reminders` | pending/missed/delivered 与所属面试；页面可确认已读 |

可用动作由服务根据状态和能力计算，UI 同步显示；服务仍逐次校验命令，不能依赖按钮是否隐藏。

## 3. 命令清单

下表 input 中 `?` 为可省略；create/edit 共用命令的 `id?` 为空即新建。带已有 id 的编辑必须 expected_revision；不可变版本新增需 parent/version 指针，防止覆盖并行编辑。

| 命令 | input 必要字段 / 输出 | 关键校验与落库 |
|---|---|---|
| SaveTarget | `id?,label,criteria,active` → target | 验证关键词/城市及硬条件；profile_targets |
| SaveFact / ConfirmFact | `id?,kind,content,provenance` / `id` → fact | 生成内容先 draft；确认才 confirmed；profile_facts |
| ImportMaterial | `material_id?,label,asset_id?,text` → version | 原件 ready；至少有可用正文；material+version；事实快照 |
| SaveMaterialVersion | `material_id,parent_version_id,text,fact_ids` → version | 新增版本不覆盖历史，未确认 fact 拒绝 |
| GenerateMaterialDraft | `target_id,job_version_id?,confirmed_fact_ids,base_version_id?` → task | 明确外发文字设置；任务保存事实快照，生成结果为草稿，用户保存为版本 |
| SearchJobs | `target_id,source_keys?` → task | target 快照；仅可用 search_jobs；逐源 fetch_runs，部分失败继续 |
| ImportJob | `url?` 或 `text_fields` → task 或 job | URL 按注册表路由；不支持可手工输入；纯文本需 title/company，缺JD标 partial |
| RefreshJob | `job_id` → task | 仅可用 read_job，保留旧详情；不改变历史应用材料 |
| SaveOpportunity | `job_id?,title?,company_name?` → opportunity | 同岗位已关联给现有机会；直接补录允许无 job，后补 JD |
| UpdateOpportunity | `id,status?,note?,title?` → opportunity | 合法状态、revision；保存用户明确结果 |
| LinkJob / UnlinkJob | `opportunity_id,job_id,basis` → opportunity | 用户确认，已有版本引用仍保留；关联修订+1；解除时同事务清除相关未使用准备的确认并增加其 revision |
| RecordCooldown | `opportunity_id,scope,status,explanation,evidence,known_until?,supersedes_id?` → note | absent 需要依据；同机会 revision 检查；追加 note，更新未使用准备的确认快照/清确认 |
| SavePreparation | `id?,opportunity_id,job_version_id,resume_version_id?,resume_exception?,channel,apply_url?` → preparation | job 属于该机会；缺 resume 需明确无需材料的说明；冷却期快照服务生成；改变输入重置确认 |
| ConfirmPreparation | `preparation_id,step:materials/cooldown` → preparation | 校验岗位仍关联本机会及当前 revision/步骤；present 两步，其余一步；不创建申请 |
| DeferPreparation | `preparation_id` → preparation | deferred，保留选材；继续须核对当前 revision |
| RecordApplication | `id?,opportunity_id,preparation_id?,job_version_id,resume_version_id?,channel,outcome,submitted_at?,evidence,reason?` → application | 历史补录不追确认；当前事实+event+回执；outcome=submitted 必须时间/依据 |
| ImportFeedback | `text,asset_id?,occurred_at?,opportunity_id?` → feedback | manual 来源 UUID；截图不假定已OCR成功，允许文字补充 |
| SyncFeedback | `source_key,account_id,stream_key` → task | 只有 read_feedback；持久游标；逐页写入和推进游标同事务 |
| ResolveFeedback | `feedback_id,opportunity_id?,decision:accept/ignore,corrected_proposal?` → feedback+affected resource | 复核时区/日程/冲突，明确变化才更新机会或日程；不发送回复 |
| SaveInterview | `id?,opportunity_id,application_id?,label,starts_at?,ends_at?,time_zone,format,location?,status,reminder_offsets` → interview | 新日程实际时间、时区；过去时间未知允许；同事务改提醒 |
| SaveInterviewContext | `interview_id,parent_version_id?,job_title,job_version_id?,resume_version_id?` → context version | 从关联申请默认选择；missing 自动计算；新版本不改旧报告 |
| StartRecording | `interview_id,device_ids,consent:true` → recording | 用户主动；设备测试已通过；先持久 intent 后开启采集，失败明确关闭并回报 |
| StopRecording | `audio_asset_id` → audio+task | 落盘校验、finalize+唯一转写入队；重复停止返回原结果 |
| AttachAudioImport | `interview_id,asset_id` → audio+task | 目标契约：ready/可解码；保存与入队事务；原数据不上传外部。当前工作区仅服务层支持已登记 WAV 文件及自动建持久任务；没有上传端点或 ASR worker，模型未就绪时任务为 needs_attention |
| SaveTranscript | `interview_id,parent_version_id?,audio_asset_id?,origin:manual/correction,segments` → transcript version | 每段 key 唯一；音频属于本场；手工无时间戳；组合校对继承逐段来源；全量新修订 |
| CombineTranscripts | `interview_id,ordered_segments:[{version_id,segment_key}]` → transcript version | 同一场面试、逐段复制音频ID/原始时间/来源，ordinal 是阅读顺序，生成 combined 版本 |
| RetranscribeAudio | `audio_asset_id,config_hash` → 新 task | 用户明确要求；同配置 request_generation+1；同 request_id 重试只建一次；保留旧结果 |
| GenerateReview | `interview_id,context_version_id,transcript_version_id` → task+run | 四项引用固定；缺JD/简历允许且注明；无内容拒绝；外发设置已确认 |
| AddImprovement | `review_run_id?,suggestion_key?,existing_item_id?,title?,action?,priority?` → item | 有来源时校验建议存在；同来源重复返回同一项；用户可直接手填 |
| UpdateImprovement | `id,title?,action?,priority?,status?,category?,user_note?,usefulness?` → item | done 设置 completed_at，重开清空；revision检查，不改报告 |
| ControlTask | `task_id,action:pause/resume/cancel/retry` → task | 当前状态合法；取消/暂停栅栏迟到结果；succeeded 不允许重跑 |
| ConfigureSource | `key,config,enabled,capability_switches` → source | 仅已安装注册来源；不能通过此端点加载任意代码；历史保留 |
| ConnectSourceAccount | `source_key,provider_account_key,credential_input` → account | 验证提供方稳定身份；重授权复用 account_id，换账号保留旧记录；不回传凭据 |
| SaveSettings | `key,value` → setting | 按key验证；凭据单独 `SetCredential(provider,value)`，响应仅 configured |
| AcknowledgeReminder | `reminder_id` → reminder | 幂等确认，不改原送达/错过时间 |
| ExportBackup | `include_assets:true` → task | 一致快照与清单；不支持会漏音频的“成功备份” |
| PreviewRestore / ApplyRestore | `backup_asset_id` / `preview_id,manifest_hash` → preview / operation | 先验证再替换；本机维护模式；用户明确选择恢复及范围，原目录保留 |

常规归档使用机会/事实/材料的状态接口。首版不提供通用任意删除 API；显式清理作为维护命令须先返回依赖预览，再凭 preview ID 执行同一范围。复盘来源清理遵守改进项保留规则。创建材料的内容解析或AI整理是后台任务，不能在 HTTP handler 里阻塞。

### 确认接口示例

```json
{
  "data": {
    "id": "prep-uuid", "revision": 4,
    "status": "draft", "next_step": "cooldown",
    "material_confirmed_at": "2026-11-04T06:44:00.000Z",
    "cooldown_confirmed_at": null,
    "cooldown": {"status": "present", "known_until": null,
      "explanation": "招聘方说明再次申请需等待，期限尚未明确", "evidence": [{"kind":"user","text":"用户补录招聘方的说明"}]}
  },
  "request_id": "request-uuid"
}
```

实际 present/absent 必须有依据；示例为虚构的用户补录，用于说明结构。第二步成功返回 ready/manual_apply，不返回 submitted。外部链接由浏览器用户点击，后台没有自动填表/提交/发消息端口。

解除岗位关联后，相关未使用准备清除两个确认时间并回 draft（主动 deferred 保持暂缓），revision 增加；旧窗口确认返回 `REVISION_CONFLICT`，重新读取显示 `next_step=relink_job`。已使用准备保留当时状态，但查询同样返回 relink_job，不能仅凭保存的 ready 状态显示投递入口。恢复关联后，未使用准备须重新按原有一/两步确认，不增加新的投递审批。

修正 `RecordApplication` 时必须提供 reason。`preparation_id` 省略或与原 ID 相同，沿用该申请上一事件的准备快照，不重读后来修改的准备。显式换为另一个 ID 时验证同机会且岗位仍关联，然后固定新快照；显式 null 取消准备关联。纠正后续结果仍沿用最近一次明确选择的快照。当前岗位关联解除后，已有申请可继续使用原 `job_version_id` 纠正结果/时间/依据；新建申请或改选 JD 仍需当前关联。历史事件不被改写。

## 4. 文件传输与录音边界

`POST /uploads` 输入 `{request_id,kind,filename,media_type,byte_size,purpose,entity_id?}` → `{upload_id,offset:0,max_chunk_bytes}`；创建 staging asset。`PUT /uploads/:id` 发送字节并带 `Upload-Offset`，服务仅接受准确偏移，返回已持久 offset；响应丢失先 GET 查询 offset，不盲追加。完成 `POST /uploads/:id/finalize` 校验大小/hash/解码结果并原子 rename，返回 ready asset。首版单文件上限 2 GiB、每块最多 8 MiB，可在本地配置降低；不足空间先失败，不把压缩包任意展开。

前端用浏览器选择文件并流上传，不直接提交任意文件系统路径。已选 interview 的音频 upload intent 包含 attach intent，finalize **自动**创建 audio+ASR；独立上传素材时才另用 AttachAudioImport。客户端不需要通过第二个易丢失请求触发自动转写。

录音使用本机采集适配器，Windows WASAPI 系统回放 + 麦克风分别采集后标注/混合（[Windows 回放采集文档](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)），双轨时间基准必须校验；不依赖网页标签页 MediaRecorder 持续存活。录音适配器尚待隔离硬件验证，未通过前 UI 明确禁用录制并提供音频导入，不能宣称完整录音交付。来源和 ASR 都不获得麦克风权限。

录音每片段落盘，UI 仅控制与显示；转写 worker 无直接 DB 写权限，通过内部本机通道上报。长任务由 SQLite 调度器和独立进程承担，不依赖 FastAPI `BackgroundTasks` 在一次 HTTP 进程内保证恢复。FastAPI 官方说明重型计算应考虑独立执行方案，本项目针对单机选择持久队列而不是引入分布式队列。[FastAPI 文档](https://fastapi.tiangolo.com/tutorial/background-tasks/)。

## 5. 来源端口细化

| 类型 | 字段 |
|---|---|
| SourceDescriptor | key, display_name, adapter_version, config_schema, url_matchers, implemented_capabilities, evidence |
| SearchQuery | keywords, cities/any_city, conditions, request_id；所有传入已规范化，无用户凭据 |
| JobRef | source_key, external_id? / url?（至少一种） |
| JobObservation | source_key, external_key, original_url, apply_url?, fetched_at, method, fields, field_presence, completeness, raw_evidence? |
| JobPage | observations[], next_cursor?, applied_filters, unsupported_filters, fetched_at |
| FeedbackPage | account_id, items:[external_key,text,evidence?,occurred_at?,invitation_key?], next_cursor?, fetched_at |
| SourceError | code:AUTH_REQUIRED/AUTH_EXPIRED/CHALLENGE/RATE_LIMITED/NETWORK/PARSE/NOT_FOUND/UNSUPPORTED, retry_after?, safe_evidence_ref? |

单页调用超时与速率由适配器配置；调度器保存 cursor、尝试和已完成页。`SearchJobs` / `ReadJob` / `ReadFeedback` 独立协议，只有实际安装且本产品验证的能力才能启用；第二来源契约测试用固定样本验证“核心无需加平台分支”。不绕过验证码或将用户浏览器登录状态默认转授权。

反馈页按 `(account_id,external_key)` 幂等；account_id 由 `(source_key,provider_account_key)` 稳定映射，重授权不变，换账号另建。stream_key 只区分该账号的读取入口。页内全部写入成功才推进对应游标，失败原游标重试。邀请按 `(account_id,invitation_key)` 查找同一面试，与消息ID独立；改期/取消更新原面试及提醒，原始消息各自保留。无稳定邀请键只做待确认建议，不以标题+时间强行自动合并改期。ReadFeedback 接收 account context 与 cursor，凭据在适配器内部通过受控 credential_ref 获取。

## 6. 运行生命周期与实现顺序

Windows 用户级后台启动器负责登录启动和进程崩溃后重启；推荐 Task Scheduler 的“用户登录时运行”与故障重启策略（[登录触发器](https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--scripting-)、[RestartCount](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-restartcount)），服务常驻时响应系统恢复/定时活性检查。用户主动停止后台写入设置，监督器不得当作崩溃复活；关闭自动启动后重启电脑需手动打开应用，界面说明这一影响。关机/睡眠期间不计算，恢复运行才续作。

发布前必须在隔离数据目录实测：关闭浏览器、结束 worker、结束服务、休眠恢复、注销/重新登录、重启电脑、禁用自动启动、主动暂停/取消。测试完成前仅可说“设计支持自动恢复”，不能说系统唤醒一定成功。Task Scheduler、音频后端的具体注册/卸载代码在架构审查后通过本机验证定稿，不在设计阶段改用户开机配置。

审查通过后的实现按完整路径分段，每段先红测：

1. 数据仓储与迁移：JD 修订缺陷、固定材料版本、申请事实/准备隔离、来源独立能力；新库及旧库副本迁移。
2. 可运行工作台：目标/资料 → 来源搜索或导入 → 机会 → 简单确认 → 人工结果；API 与页面同段交付。
3. 面试与本地音频：日程/提醒、导入即自动转写、校对、关闭/重启恢复；隔离验证录音双声道与系统生命周期。
4. 四项输入复盘与独立改进：输入固定、引用校验、外部失败、重算/用户编辑不覆盖。
5. 来源扩展、只读反馈与备份恢复：按实际渠道可用性逐项接入，未验证能力不冒充可用。

这是实现顺序，不是再次砍需求。每段记录验收证据，最终全路径和故障恢复通过才称首版完成。
