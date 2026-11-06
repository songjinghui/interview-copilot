# 第 2 段工作台实现与送审证据

2026-11-05 · 宪宪 / gpt-6-astra

送审时状态：作者实现与隔离验证完成，等待独立代码审查、尚未合并。本段随后经修订复审、PR #2 合并，并完成合并后隔离验收；进度更正见 [第 2 段隔离验收](workbench-acceptance-2026-11-06.md)。本记录保留送审时证据，不代表浏览器视觉验收或首版完成。

- 依据：`application-contracts.md` §6 第 2 段；愿景核对记录 `8d98cc4` 保留放行结论。
- 分支 / 工作区：`feat/workbench` / `C:/Users/Administrator/projects/interview-copilot-workbench`。
- 精确送审 HEAD：`c25e48d76ddb60d0508720ef0c53111ad516acd0`。
- PR：[本机求职工作台与鉴权 API #2](https://github.com/songjinghui/interview-copilot/pull/2)，送审时 Draft；后续已合并。
- [该提交运行说明](https://github.com/songjinghui/interview-copilot/blob/c25e48d76ddb60d0508720ef0c53111ad516acd0/docs/workbench-runtime.md)与 README 已在 feature 分支落盘；main 本轮只登记本证据文件。

## 本段行为

1. React / TypeScript 三个实际页面：目标与资料、岗位、机会。目标/经历/简历 → 手工粘贴 JD → 机会关联 → 固定 JD/简历准备 → 一次或两次确认 → 人工结果/历史补录/纠正。查询来自 SQLite，不复用虚构原型数据。
2. 同源 FastAPI adapter；复用已审领域事务、修订和回执。新增手工导入命令、资料/岗位/机会/准备/申请的读取视图，分页最多 100。手工记录缺 URL 存 null、缺 JD 标 partial；无产品来源适配器时明确提示手工导入，不返回假搜索结果。
3. Windows 显式目录启动器；目录单实例、回环端口独占、当前用户 DPAPI 密钥、双向认证 named pipe、一用 nonce、8 小时会话及活动续期。重启保持密钥，所有业务 API 验证 token/Host，写入验证 Origin。1 MiB JSON 上限，严格字段和内容类型，CSP 与安全外链。
4. IndexedDB 持久化草稿和命令信封，按工作区隔离。断线重试保留 request ID；冲突保留草稿和原修订，用户明确核对后才能应用到最新修订。取消网页或重新加载不会自动执行命令。
5. 发布包包含构建后的静态资源；从仓库外安装可运行。开发采用 Vite build watch + 同源服务页面刷新，不额外开放开发代理端口。没有注册开机启动或修改系统任务计划。

SQL/schema 与原迁移未改。第 1 段产品代码增量限于：手工 JobRecord 的可空来源 URL、手工缺 JD 的 partial 标记，以及简历修订冲突返回当前 parent ID。S1/S2 的历史快照与解除关联规则继续由原服务处理。

## 测试先行与修复证据

先读现有 `unittest` 测试入口，再新增 workbench/session/HTTP/launcher 测试；缺失模块通过明确 feature assertion 先失败，随后实现转绿。前端先配置工具并建立行为测试，在 forms、API、准备组件及页面缺失时明确失败，再接入实现。工具安装或配置错误未算成行为红测。

实现中按失败用例修正：

| 目标行为 / 初次失败 | 最终结果 |
|---|---|
| 首次手工导入响应 tuple 与持久化回执 list 不一致 | 查询视图使用 JSON 兼容类型，重开数据库后回执相同 |
| 未授权 IPC challenge 异常终止接收循环 | 认证拒绝被处理，继续接收后续合法请求 |
| 简历并行编辑缺少最新 parent 指针，UI 无法保留草稿后明确继续 | 返回安全 parent ID；草稿固定旧 parent，显式核对后切换 |
| 草稿写入失败仍提示“已保留”，读取失败一直显示加载 | 不发送未持久化命令，显示实际存储错误 |
| 局部编辑抹掉原结构化目标条件、经历日期/单位/成果、材料事实引用 | 逐项保留未编辑字段，新增回归均先失败后通过 |
| 仅改结果说明却把原秒/毫秒截断，附件依据也被丢掉 | 未改时间时保留原始 UTC 值；保留附件引用 |
| SQLite active=1 被直接输出，前端回传数字无法通过布尔校验 | 读取视图输出 JSON boolean，测试检查精确类型 |

全链路 DOM 测试启动真实、临时数据的 HTTP 服务，通过页面控件录入目标、简历、岗位、机会及冷却期；材料确认与冷却期确认后检查申请集合仍为空，人工记录实际结果后检查只有一个申请/事件，重新挂载页面仍读得到结果。该测试不是真实浏览器渲染检查。

## 最终执行结果

在送审工作区实际执行：

| 检查 | 结果 |
|---|---|
| `python -X utf8 -m unittest discover -s tests -t . -q` | 97/97 通过 |
| `python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -q` | 17/17 通过 |
| `frontend` 下 `npm test` | 16/16 通过；含真实 HTTP 驱动的 DOM 操作链 |
| `frontend` 下 `npm run build` | TypeScript 检查与 Vite production 构建通过 |
| `python -X utf8 scripts/verify_workbench_runtime.py` | 临时 wheel、仓库外安装、2 个静态资源、真实 IPC、401 边界、结束进程后重启、旧 token/工作区标识/幂等回执均通过 |
| `git diff --check` | 通过 |

合计 **130 项自动化测试通过**，另有独立包运行探针。运行探针所有目录来自 TemporaryDirectory，只终止自己启动的隔离子进程，结束后清理；没有指向用户数据或更改常驻/开机设置。

工具事实：宿主默认 omit dev / production 环境，首次 npm 安装没有测试工具；改用 `npm ci --include=dev`，测试启动器显式设 NODE_ENV=test。第一次 wheel 探针使用非隔离构建时缺 setuptools，未视为通过；改回 pyproject 声明的标准隔离构建后通过。它们是验证环境修正，不是产品行为红测。

## 待独立核对与未验项

请砚砚绑定上述 HEAD 审查本机授权/IPC、查询视图、跨操作草稿与字段保留、页面实际链路及必要回归，给 approved/changes_requested。独立审查通过前不合并。

本轮 CUA inventory 实际返回 `apps:[], browsers:[]`。真实浏览器布局（1280/960）、200% 缩放、键盘焦点和屏幕阅读仍待验；没有重试此前被策略阻止的 headless 路径，也没有降低 CSP/Origin 来绕过限制。浏览器不可用不等于页面已经验收。

录音、ASR、休眠/登录恢复、真实来源、备份恢复属于后续段。本段仅完成获准的手工输入工作台路径，未将首版宣称为完成。金额/复杂运算符条件目前保留展示，不提供完整编辑器；文件原件上传与 AI 整理尚未交付。
