# 第 1 段合并后隔离验收

2026-11-05 · 宪宪 / gpt-6-astra

**PR #1 已合并，第 1 段仓储与应用服务的合并后隔离验收通过。** 这不是完整首版、页面或后台转写验收；合并后的愿景核对另交非作者、非代码审查者。

## 提交与审查依据

- PR：[interview-copilot #1](https://github.com/songjinghui/interview-copilot/pull/1)，GitHub 确认 `MERGED`，时间 `2026-11-05T00:17:18Z`。
- 精确被审提交：`b5b123746fdf6717e394d6c823276d2694800a45`；砚砚的 [approved 记录](storage-review-2026-11-04.md) 已在 main/`16645c4` 落盘，S1/S2 关闭。[GitHub 审查评论](https://github.com/songjinghui/interview-copilot/pull/1#pullrequestreview-5777873374) 绑定同一 HEAD；共享 GitHub 身份使它是 COMMENT，而非原生 APPROVED。
- 合并前 PR 为 CLEAN/MERGEABLE，分支保护未配置，适用 rules 返回空数组，无必需 CI 检查。使用 `gh pr merge --merge --match-head-commit b5b123746fdf6717e394d6c823276d2694800a45` 合并，未使用管理员绕过。
- 合并提交：`0f7b679589f871148a555be7c789d8b6e1d6b4e5`。主工作区已 fast-forward；与被审 HEAD 比较 `src/`、`tests/`、`pyproject.toml` 无差异，保留 main 上的初审和复审文档。

## 验收环境与实际结果

新建独立 detached worktree：`C:/Users/Administrator/projects/interview-copilot-acceptance-0f7b679`，固定到合并提交。没有在原 feature checkout 或真实运行数据上冒充合并后验收。

| 检查 | 结果 |
|---|---|
| `python -X utf8 -m unittest discover -s tests -t . -q` | 79/79 通过，含 S1/S2 跨操作回归和隔离迁移故障用例 |
| `python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -q` | 17/17 通过；固定样本，不宣称平台实测 |
| 合并提交构建 wheel、临时目录安装、工作区外运行 `init-db` | 通过；安装包内有 `storage/migrations/001_initial.sql`，运行目录没有 docs |
| 已安装包的合成数据完整操作链 | 通过，见下文 |
| SQLite `integrity_check` / `foreign_key_check` | `ok` / 空集 |

安装包验收仅复制已合并源码及 pyproject 到临时构建目录，以 `pip wheel --no-deps` 构建，再以 `pip install --no-deps --target` 安装到新的临时目录。子进程工作目录在代码仓库外，显式确认实际模块路径属于该安装目录。所有岗位、简历、证据均为合成样本；所有数据库在临时目录，结束后关闭并清理，没有切换应用数据根目录。

实际走通的操作链：JD A→B→A 三次修订 → 保存机会和简历 → 记录有依据的冷却期 → 材料/冷却期两次确认（此时申请行仍为零）→ 人工补记 unknown 结果 → 编辑准备 → 解除岗位关联（未使用准备 revision 增加并返回 relink_job）→ 纠正已发生申请为 submitted（保留原准备快照）→ 关闭/重开数据库 → 回读固定历史 → 重发原导入请求（仍只有一份材料）。

验收脚本第一次执行在安装目录归属断言处停止：Windows 使用 `ADMINI~1` 短路径表示当前目录，而模块路径已解析为 `Administrator` 长路径。查证两者指向同一目录后，将比较双方都 `resolve()`，保留原归属断言重跑，整条安装包流程通过。没有修改产品代码，没有把第一次中断记录为通过。

本轮未重复无变化的设计 SQL、原型源码检查；它们也不提供浏览器视觉或硬件证据。

## 边界与下一棒

已交付：仓储、观察/修订、固定材料、简单准备确认、人工结果与纠正、独立只读来源协议、隔离旧库迁移和维护 CLI。

尚未交付：可运行页面/HTTP、真实来源适配器、录音/ASR worker、系统唤醒恢复、四项输入复盘与独立改进流程。浏览器渲染/焦点/缩放、录音硬件和真实渠道仍待对应阶段验收。建好 37 张表不代表上述功能已实现。

按既定流程把合并提交、代码复审和本报告交给非作者、非代码审查者做愿景核对；之后继续应用契约 §6 的第 2 段。无需重新决定已确认的手动投递、简单冷却期和按需扩展来源范围。
