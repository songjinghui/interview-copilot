# PR #2 修订版独立复审记录

日期：2026-11-06
复审者：龟龟 / zai-org/GLM-5.3-Flash（非作者、非原 reviewer，独立复审）
被审提交：`523d9cc097403ad96964077c9a7ea47a7c8a3f3e`（`feat/workbench`，即 `c25e48d` 之后的修订提交 "fix: refresh stale confirmation state before retry"）
范围：作者针对 W1/W2 的修订提交本身（`git diff c25e48d..523d9cc`），不含真实浏览器视觉验收。

## 结论

**在精确 HEAD `523d9cc`（523d9cc097403ad96964077c9a7ea47a7c8a3f3e）上：approved。**
W1（无字段确认表单通用重试把新 revision 套在旧确认上）与 W2（仅改 label 时条件值中的中文逗号被拆分）均已按"先红后绿"流程修复，且未引入新的回归。

## 独立执行的检查

1. **落点核对**：`git rev-parse 523d9cc` = `523d9cc097403ad96964077c9a7ea47a7c8a3f3e`；`origin/feat/workbench` 同步于该提交；修订区间 `c25e48d..523d9cc` 共 7 个文件（4 个 src、1 个测试、2 个 docs），无越界改动。
2. **W1 红→绿独立复现**：将 `forms.tsx` / `profile.tsx` / `opportunities.tsx` / `workflow.tsx` 四个文件回退到 `c25e48d` 后单跑 `frontend/tests/reviewer-pr2.test.tsx`，W1、W2 **两用例均失败（红）**；恢复到 `523d9cc` 后单跑同一测试，**两用例均通过（绿）**。红→绿由本人独立执行，非仅采信作者记录。
3. **修复机制核读**：
   - `forms.tsx`：`REVISION_CONFLICT && fields.length === 0` 分支下，清理被服务拒绝的旧信封（`drafts.remove`）、重置草稿为 `initial/expected`、调用 `onConflict` 触发页面刷新；清理失败时改提示"请刷新记录后再继续"，不声称已清理。保留草稿重试按钮由 `fields.length > 0` 与 `error.details` 双重条件守卫，无字段类别不会出现该按钮。
   - 瞬态错误码 `SESSION_REQUIRED` / `BUSY` / `STORAGE_ERROR` 仍走原有"保留草稿、重试原请求"路径，未被本次修改波及。
   - `ConfirmationForm`（opportunities.tsx）与 ConfirmPreparation、DeferPreparation、ConfirmFact（profile.tsx）、UnlinkJob（workflow.tsx）均接通 `onConflict={refresh}`；`App.tsx` 的"加入机会"（SaveOpportunity）无 `expected`，服务端 `_opportunity` 不做 revision 校验、天然幂等，不会产生 `REVISION_CONFLICT`，无需接入——该边界是正确的留白而非遗漏。
   - 冲突处理链闭环确认：无字段表单的 `key`（如 `${prep.id}-materials-${prep.revision}`）随刷新后的新 revision 变化而重挂载，重试前必须再次主动确认，不存在静默套用新 revision 的通道。
4. **W2 边界核读**：`profile.tsx` 中 `targetInput` 对 `must`/`prefer` 仅按换行（`splitLines`）拆分，`keywords`/`cities` 保留逗号分隔；保存时通过 `editableCondition` 过滤并原样保留非文本类条件（如 `salary/gte` 等结构化条件），编辑不丢数据。
5. **全量回归**：`npm test` 3 个文件 **18/18** 通过（含本次修订保留的正式回归测试）；`python -X utf8 -m unittest discover -s tests -p test_*.py -t .` **97/97**；`python -m pytest validation/tests` **17/17**；`npm run build` 通过。
6. **独立运行时链**：本人执行 `python -X utf8 scripts/verify_workbench_runtime.py`，结果 `{"result": "passed", "installed_outside_repository": true, "assets_served": 2, "crash_restart_session_and_receipt": true, "persistent_materials": 1}`——ware 临时仓库外安装、静态资源、真实 IPC、服务重启后的旧会话/幂等回执恢复均通过。
7. **愿景符合性**：`ConfirmPreparation` 二次确认（materials → cooldown → manual_apply）与 v0.12"冷却期确认=二次确认"一致；确认输入仅 `preparation_id + step`，无自动提交路径，无练手/重点分类概念。

## 未覆盖事项（诚实边界）

- 真实浏览器下的视觉布局、键盘焦点流转、缩放适配未验证，维持"待验"状态。
- 本复审不等于 PR 放行、合并或第 3 段准入决策；合并不由复审者执行。

## 结论

**approved（绑定精确 HEAD `523d9cc097403ad96964077c9a7ea47a7c8a3f3e`）。**
