# 第 3 段服务层切片独立审查

日期：2026-11-06  
审查者：砚砚 / gpt-6-astra（非作者）  
结论：**changes_requested**。A1–A4 修复并复审前，不放行本切片合并。

## 被审对象与范围

这是一次未提交工作区快照审查，不是 PR #2 的再次审查，也不是某个新提交的批准。

- 工作区：`C:/Users/Administrator/.local/share/opencode/worktree/fda5e9/phase3-interviews`，detached。
- 基线：`a469edcdc99c49d73fd3e1c0336907d746555b6b`。
- 变化：`workbench.py`、日程/音频服务测试、HTTP 测试及接口契约中的当前边界说明，共 5 个文件（含 2 个未跟踪测试文件）。
- 审查开始和结束两次核对下列 SHA-256，内容未变；未改动作者工作区。
- 第 2 段的 W1/W2 已有修订与龟龟独立复审，PR #2 已合并为 `876bf3a`；本轮不重新打开已解决的问题。

| 文件 | SHA-256（原始文件字节） |
|---|---|
| docs/application-contracts.md | `2003443e150c204c9779700b1c1d68d029319014483eff32d6127fd73d9df962` |
| src/interview_copilot/workbench.py | `1afdcaa1ad92ec317454ad7508b8606aed320ea9502196ae9e68202998fbcf15` |
| tests/test_http.py | `f90342cf63f7c823f8c517b7715cd8c1b95156db73e094778256fa4d66f20d80` |
| tests/test_audio_import.py | `2f518890d99953afb30cfbb5ada858c776f408d08253e11c3b5e12b684bdb23d` |
| tests/test_interviews.py | `abae86153c136ac51035aff84d369f1a8041977f9faec7f9ab2bce3b777b3006` |

## A1 · P2 · 机会查询新增了错误的状态白名单

位置：`src/interview_copilot/workbench.py:756–761`。

本轮新增的校验只允许 `active/paused/closed/archived`，但已有领域服务、SQL 和工作台使用的是 `saved/deferred/applying/applied/interviewing/offer/rejected/withdrawn/archived`。因此保存记录正常，选择页面上的“已收藏”“已投递”“面试中”等筛选却会返回 HTTP 422。

独立探针经真实领域命令依次更新 9 个合法状态，再通过 FastAPI TestClient 查询：8 种返回 422，只有 archived 返回 200。这是对已交付第 2 段的回归，不属于音频后续待实现项。

**修订要求：**查询校验与已有状态定义一致，保留非法状态拒绝。补上逐一覆盖现有页面筛选值的 HTTP 回归，不能只测不带 status 的机会列表。

## A2 · P2 · 时区解析失败被当作可继续排程

位置：`src/interview_copilot/workbench.py:65–77`。

`ZoneInfoNotFoundError` 被无条件转成 `None`。这个异常既可能表示没有时区数据库，也可能表示用户传了不存在的名称；现实现无法区分。即使部署补齐时区库，不存在的名称仍然绕过校验，创建 planned 面试和 pending 提醒。代码中“有 tzdb 就会拒绝未知标识”的注释不成立。

独立探针注入一个能解析 Asia/Shanghai、对 `Not/A_Real_Zone` 抛该异常的 resolver；合法日程成功后，无效名称也成功落库，没有返回 VALIDATION。该注入用于区分“缺依赖”和“坏输入”，并非声称本机已安装真实 tzdb。本机实际 `available_timezones()` 为 0。

**修订要求：**明确区分未知时区与运行依赖未就绪。未知名称应拒绝；无法验证时应有明确的能力失败或经过定义的输入契约，不能把正则匹配等同于 IANA 校验后静默创建正常日程。当前文档坦诚标注限制是正确的，但不能修复运行时的失败后继续行为；也不要仅删除注释来关闭此项。

## A3 · P2 · 有时区数据时，接口拒绝自身返回的 UTC 时间

位置：`src/interview_copilot/workbench.py:120–130`；依据：`application-contracts.md` §1 与 `database-design.md` §1 的 UTC 时间契约。

时区存在时，保存代码要求输入时间的显式 offset 等于 IANA 显示时区在该瞬间的 offset。这把“表示同一瞬间的 UTC 时间”误判为不合法。API 查询返回的时间已经规范化为 Z，因此一条 Asia/Shanghai 的记录读出来后，只修改标题、原样回传时间，反而不能保存。补齐 tzdb 后，该错误会从当前缺数据环境中的隐藏分支变成正常路径问题。

独立探针注入 UTC+08:00 的有效时区对象：
1. 保存 `2030-11-20T10:00:00+08:00` / Asia/Shanghai；
2. 查询得到 `2030-11-20T02:00:00.000Z`；
3. 使用查询结果、当前 revision，仅修改 label；
4. 返回 `VALIDATION: starts_at offset does not match time_zone`。

**修订要求：**按既定接口把绝对时间与显示时区分开处理，UTC 时间应可往返。若另设本地墙上时间输入，应在该专用边界处理 DST/歧义，不能对统一 UTC 契约强加本地 offset。回归同时覆盖 UTC 往返、有效时区、无效时区和缺时区数据环境。

## A4 · P2 · 音频全文件校验占用数据库写锁，阻塞已有查询

位置：`src/interview_copilot/workbench.py:226–274` 及 `_attach_audio_import` 调用处；调用链：`ApplicationService.execute` → `Database.transaction` → 音频校验。

AttachAudioImport 的 handler 在 `BEGIN IMMEDIATE` 之后执行，它在该事务内读取整文件计算哈希，再逐帧读取整段 WAV。大文件或慢磁盘会长时间持有写锁。HTTP 每次查询又新建 Database，而其初始化也要取得写事务；所以不只是别的写命令，连现有 profile 查询都会被阻塞，5 秒后返回 503。

独立探针只使用临时目录中的 100 ms 合成 WAV，在校验入口用 Event 模拟慢 I/O；并发调用同一临时库的鉴权 `GET /api/v1/profile`，实测 503 / STORAGE_ERROR。释放 Event 后音频正常完成，说明失败来自锁的持有范围，不是损坏音频或数据库。该 503 是本次隔离复现，不用来推断用户先前提到的 502 原因。

**修订要求：**将耗时文件读取/哈希/解码移出主数据库写锁；最后用短事务重新验证资产状态、版本/身份及去重条件，并原子写入音频关联、任务和回执。也应避免普通只读请求必须为重复 schema 验证争用写锁。保留现有失败回滚与幂等行为，补充慢 I/O 期间读写响应的并发回归，不能仅延长 busy_timeout。

## 独立验证及边界

| 检查 | 本轮实际结果 |
|---|---|
| `python -X utf8 -m unittest discover -s tests -t . -q` | 111/111 通过 |
| `python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -q` | 17/17 通过 |
| 本报告附带 A1–A4 探针 | 4/4 因目标行为不满足而失败，非环境或语法错误 |
| `git diff --check` | 通过；仅提示既有 LF/CRLF 转换 |
| 前后文件 SHA-256 | 5 个被审文件完全一致 |

复现脚本：[phase3-service-2026-11-06.py](review-probes/phase3-service-2026-11-06.py)。它位于审查文档目录，不属于常规产品测试发现范围；断言表达期望行为，当前返回非零是已复现缺陷的证据，不能写成“全部测试通过”。

从主工作区执行：

```powershell
python -X utf8 docs/review-probes/phase3-service-2026-11-06.py C:/Users/Administrator/.local/share/opencode/worktree/fda5e9/phase3-interviews
```

代码核读确认了：日程与提醒同事务更新；delivered 记录保留；音频部分与任务写入同一命令事务；同 request_id 回执复用；登记资产需 ready、大小/hash 与 WAV 内容校验；缺模型时明确 needs_attention/MODEL_NOT_READY。以上不代表 A1–A4 可忽略。

本次没有安装时区库、使用用户音频或运行库，也没有查询 Cat Cafe 音频服务。未重复第 2 段前端构建和浏览器验收。真实录音、上传、模型转写、提醒送达、系统唤醒和自动恢复仍属于后续未实现/未验范围；本轮不将服务层任务落库称为这些能力已经完成。

## 下一棒

交作者先针对 A1–A4 建立失败回归，再修订实现，运行完整相关测试。请将修订提交到可追溯分支并回传精确 HEAD；本报告只绑定上述未提交快照，不能当作将来提交的放行。审查通过后再走合并与隔离验收。

[砚砚/gpt-6-astra🐾]

