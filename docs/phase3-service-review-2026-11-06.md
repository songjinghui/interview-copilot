# 第 3 段服务层切片独立审查

> 最新复审：`bfa892a6ee013c40e458514be31361722135d859` 为 **changes_requested**；A1–A3、原 A4 长写锁及 A4-R1 已关闭，剩余 A4-R2：等待数据库写锁期间文件变化仍能发布。详见文末复审段，以下历史审查事实保留。

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

## 2026-11-06 复审 · 790da15

**结论：changes_requested。** 绑定精确提交 `790da15fa25394c42d47f6b7c58d28cba2140cb8`（`fix/phase3-service-review`）。本地 HEAD 与远端分支一致，作者工作区干净。没有该分支的 PR；本节记录代码复审，不提交 GitHub 原生 PR verdict。

A1、A2、A3 关闭；A4 的长事务阻塞已修复，但该修订的文件身份校验存在下述 A4-R1，仍需修复后再放行。前文保留初审事实，不表示旧问题仍全部存在。

### 已核对的修订

- **A1：**机会查询与领域服务的 9 个真实状态一致；原 HTTP 探针全部返回 200。
- **A2：**未知名称在有时区数据时返回 VALIDATION，缺数据返回 TIMEZONE_DATA_UNAVAILABLE（HTTP 映射 503）；不再静默创建日程。
- **A3：**UTC instant 与显示时区分开，查询时间原样回传、仅修改 label 的探针通过。
- **A4 原阻塞：**execute 在写事务之前调用 prepare_command，音频哈希/解码已移出 BEGIN IMMEDIATE；事务内再次检查回执。现有库初始化改为只读 schema 验证，只有新库初始化需要写事务；已处于 WAL 的库不再重复切换。原慢 I/O 期间 profile 查询通过，作者新增并发写入回归也通过。
- **回执：**成功导入后删除合成测试文件，同 request_id 仍返回原回执；在 preflight 已返回后再修改文件会被拒绝，未写入音频记录。两项由本轮独立探针验证。
- 初始 SQL 迁移未改，现有迁移与仓储回归仍通过。

### A4-R1 · P2 · 校验结束后才记录文件身份，可能发布未经校验的替换内容

位置：[workbench.py:284–292](https://github.com/songjinghui/interview-copilot/blob/790da15fa25394c42d47f6b7c58d28cba2140cb8/src/interview_copilot/workbench.py#L284)，最终对比在 311–321 行。

`prepare_command` 先调用 `_audio_file` 完成哈希/解码并关闭文件，然后才用 `path.stat()` 取得 file_identity。这一身份可能已经属于校验后被改写或替换的内容。事务里比较“当前 stat”与“校验结束后的 stat”，两者相同不能证明该内容通过了先前校验。

独立复现只使用临时目录的合成 WAV：
1. 实际执行原 `_audio_file`，哈希与 WAV 解码成功；
2. 在返回到 `prepare_command` 的 stat 之前，用普通文件写入将整个 WAV 覆盖为同长度的 `x` 字节；不伪造时间戳，也不修改数据库 hash；
3. 继续原流程，导入成功，没有抛 ApplicationError。坏内容被关联为 finalized/complete 音频，并创建转写任务；
4. 新增“应拒绝该变化”断言失败。对照用例在 preflight **已经返回后**修改文件则正常拒绝，定位到身份采样与已验证文件不绑定这一具体窗口。

**修订要求：**从实际被校验的打开文件句柄取得身份，在读取/哈希/解码前后验证稳定性，将该身份与校验结果一起返回；最终发布复核同一已验证身份。文件发布/共享策略应阻止或检测校验期间及发布前的普通替换和改写。不能仅把现在的最后一次 path.stat 当作已验证身份，也不要把整段文件 I/O 放回写事务。

先保留本失败用例，再修复；至少覆盖校验过程中变化、校验结束到事务开始之间变化、事务前资产字段变化，以及慢 I/O 下并发读写和回执重放。

### 本轮独立执行结果

| 检查 | 结果 |
|---|---|
| 完整 tests | 116/116 通过 |
| validation/tests | 17/17 通过 |
| 原 A1–A4 探针 | 4/4 通过；仅给夹具提供明确的测试时区 resolver，原断言未改 |
| 新增音频身份/回执探针 | 2/3 通过，A4-R1 因目标行为失败 |
| git diff --check、作者工作区及远端 HEAD | 通过 / 干净 / 均为 790da15 |
| 001_initial.sql 相对基线差异 | 无 |

共 133 项既有测试通过，另 7 项独立复审探针为 6 绿 1 红。不能将此表述为“全部测试通过”或本轮已放行。

新增复现入口：[phase3-recheck-790da15.py](review-probes/phase3-recheck-790da15.py)：

```powershell
python -X utf8 docs/review-probes/phase3-recheck-790da15.py C:/Users/Administrator/.local/share/opencode/worktree/fda5e9/phase3-interviews
```

该脚本复用原审查断言，追加竞态与回执探针；只访问临时数据，不修改作者代码。时区使用注入的测试 resolver，本机实际时区库仍缺失；未声称真实日程运行、录音、ASR、提醒送达、浏览器或系统唤醒已验收。

下一棒：作者修复 A4-R1，提供新精确 HEAD 复审。此节不授予合并放行。

[砚砚/gpt-6-astra🐾]

## 2026-11-06 再复审 · bfa892a

**结论：changes_requested。** 绑定精确提交 `bfa892a6ee013c40e458514be31361722135d859`，分支 `fix/phase3-service-review`。本轮检查起止 HEAD 一致，作者工作区干净；送审消息称尚未推送，但本轮 `git ls-remote` 已确认远端同名分支为该提交，以实查结果为准。本轮仅审查相对 `790da15` 的 4 文件修订及相关回归，未修改产品实现。

### 已关闭 A4-R1

`_audio_file` 现在从实际打开句柄执行读前/读后 `fstat`，身份包含 dev/ino/size/mtime_ns/ctime_ns；完整哈希与 WAV 读取期间须保持稳定，并核对路径对应身份。preflight 沿用该已验证身份，增加 media_type 快照。Windows 路径 stat 与句柄 fstat 的 ctime 不直接混比，句柄前后仍比较 ctime。

上轮 7 项独立探针全部通过，包括“校验返回后、preflight 保存身份前覆盖文件”的原 A4-R1 复现。作者新增的读取期间覆盖、preflight 后覆盖和资产元数据变化测试也通过。慢文件读取仍位于数据库写事务外，既有并发读写回归通过。

### A4-R2 · P2 · 最终文件检查早于写锁等待，等待期间变化仍会被发布

位置：[application.py:139–141](https://github.com/songjinghui/interview-copilot/blob/bfa892a6ee013c40e458514be31361722135d859/src/interview_copilot/application.py#L139)，关联 [workbench.py:312–338](https://github.com/songjinghui/interview-copilot/blob/bfa892a6ee013c40e458514be31361722135d859/src/interview_copilot/workbench.py#L312) 与 [workbench.py:357](https://github.com/songjinghui/interview-copilot/blob/bfa892a6ee013c40e458514be31361722135d859/src/interview_copilot/workbench.py#L357)。

本次把最终路径身份检查从事务内移到了 `verify_prepared_command`，它在 `BEGIN IMMEDIATE` **之前**执行。随后申请写锁可等待最多约 5 秒。等待期间文件没有保护；取得写锁后 `_attach_audio_import` 仅复核数据库资产字段，不再检查文件。于是验证过的内容和最终发布的内容仍可能不同。

新增探针不 mock 产品函数，使用两条真实 SQLite 连接与临时合成 WAV：

1. 连接 A 持有 `BEGIN IMMEDIATE` 写锁；连接 B 正常执行 `AttachAudioImport`。
2. SQLite trace 确认 B 已发起 `BEGIN IMMEDIATE`，且在 A 未释放时尚未完成；此时 B 的文件校验和最终身份检查已完成。
3. A 仍持锁时，用普通写入把 WAV 覆盖为同长度坏字节，不伪造时间戳，不修改登记 hash。
4. A 释放写锁，B 返回成功回执，`created=True`，创建音频与任务。文件 hash 与登记内容已不相同，“应拒绝变化”断言失败。
5. 对照探针在同样的锁等待窗口修改 status/path/size/hash/media_type 五种数据库字段，均返回 `INVALID_STATE` 且无音频、任务或该请求回执写入，说明数据库内复核有效，缺口在文件发布边界。

**修订要求：**写锁取得后、写入持久行之前复核已验证文件身份，或在校验结束至提交期间保有能防止改写/替换的文件保护。哈希/完整解码继续留在写事务外；常数级身份复核和长时间内容读取应分别处理。不能让一次可阻塞的写锁申请隔在最后复核与发布之间而不再检查。

请先将本锁等待复现纳入回归，再修实现，同时保留原慢 I/O 并发读写、元数据变化、回执重放与回滚用例。此项是本轮剩余唯一阻塞发现；不重新打开已关闭项。

### 本轮独立执行证据

| 检查 | 结果 |
|---|---|
| `python -X utf8 -m unittest discover -s tests -t . -q` | 119/119 通过 |
| `python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -q` | 17/17 通过 |
| 上轮独立复审入口 `phase3-recheck-790da15.py` | 7/7 通过 |
| 新锁等待探针 `phase3-publication-bfa892a.py` | 1/2 通过；文件变化用例因目标行为失败，元数据对照 5 个子场景通过 |
| 修订 `git diff --check` | 通过 |
| `001_initial.sql` 相对 790da15 | 无差异 |

共 136 项既有测试通过；独立审查探针合计 8/9 通过、1 项失败。未重复没有改动的前端构建、打包和真实浏览器验收。未将作者的重复 15 次运行计作本轮独立执行。

复现脚本：[phase3-publication-bfa892a.py](review-probes/phase3-publication-bfa892a.py)。从主工作区运行：

```powershell
python -X utf8 docs/review-probes/phase3-publication-bfa892a.py C:/Users/Administrator/.local/share/opencode/worktree/fda5e9/phase3-interviews
```

全部探针仅使用隔离临时库和合成音频，未触及真实运行库。实际时区库、录音/ASR、提醒送达、系统唤醒及浏览器验收边界保持前文记录。下一棒交作者修复 A4-R2，回传新精确 HEAD；本结论不放行合并。

[砚砚/gpt-6-astra🐾]
