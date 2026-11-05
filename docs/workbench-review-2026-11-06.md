# PR #2 修订版独立复审（workbench）

日期：2026-11-06
复审者：龟龟 / zai-org/GLM-5.3-Flash（非作者、非原 reviewer 的独立复审）
被审提交：`523d9cc097403ad96964077c9a7ea47a7c8a3f3e`（`fix: refresh stale confirmation state before retry`，修订前 HEAD `c25e48d`）
范围：作者针对 W1/W2 审查发现的修订提交本身，重点是修复有效性、冲突边界与相关回归。**不含**真实浏览器视觉/焦点/缩放验收，**不涉及**合并或第 3 段准入决策，**未改动**任何产品代码。

## 结论

**在精确 HEAD `523d9cc`（523d9cc097403ad96964077c9a7ea47a7c8a3f3e）上：approved。**
W1（无字段确认表单通用重试把新 revision 套在旧确认上）与 W2（仅改 label 时条件值中的中文逗号被拆分）均已按"先红后绿"流程修复，且未引入新的回归。

## 独立执行的检查

1. **落点核对**：`git rev-parse 523d9cc` = `523d9cc097403ad96964077c9a7ea47a7c8a3f3e`；`origin/feat/workbench` 同步于该提交；修订区间 `c25e48d..523d9cc` 共 7 个文件（4 个 src、1 个测试、2 个 docs），无越界改动。
2. **W1 红→绿独立复现**：将 `forms.tsx` / `profile.tsx` / `opportunities.tsx` / `workflow.tsx` 四个文件回退到 `c25e48d` 后单跑 `frontend/tests/reviewer-pr2.test.tsx`，W1、W2 **两用例均失败（红）**；恢复到 `523d9cc` 后单跑同一测试，**两用例均通过（绿）**。红→绿由本人独立执行，非仅采信作者记录。
3. **修复机制核读**：
   - `forms.tsx`：`REVISION_CONFLICT && fields.length === 0` 分支下，清理被服务拒绝的旧信封（`drafts.remove`）、重置草稿为 `initial/expected`、调用 `onConflict` 触发页面刷新；清理失败时改提示"请刷新记录后再继续"，不声称已清理——提示文案准确、UTF-8 完好。
   - 瞬态错误码 `SESSION_REQUIRED` / `BUSY` / `STORAGE_ERROR` 仍走原有"保留草稿、重试原请求"路径，未被本次修改波及。
   - ConfirmPreparation、DeferPreparation（opportunities.tsx）、ConfirmFact（profile.tsx）、UnlinkJob（workflow.tsx）均接通 `onConflict={refresh}`；`App.tsx` 的"加入机会"（SaveOpportunity）无 `expected`，服务端 `_opportunity` 不做 revision 校验、天然幂等，不会产生 `REVISION_CONFLICT`，无需接入——该边界是正确的留白而非遗漏。
   - 冲突后链路闭环：无字段确认表单的 `key` 随刷新后的新 revision 变化而重挂载，重试前必须再次主动确认，不存在静默套用新 revision 的通道。
4. **W2 边界核读**：`targetInput` 对 `must`/`prefer` 仅按换行（`splitLines`）拆分，`keywords`/`cities` 保留逗号分隔（与字段帮助文案一致）；保存时通过 `editableCondition` 过滤并原样保留非文本结构化条件，编辑不丢数据。
5. **全量回归**：`npm test` 3 个文件 **18/18** 通过（含本次修订保留为正式回归的审查测试）；Python `tests/` **97/97**；`validation/tests` 经 `python -m pytest` **17/17**；`npm run build` 通过。
6. **独立运行时链**：本人执行 `python -X utf8 scripts/verify_workbench_runtime.py`，结果 `{"result": "passed", "installed_outside_repository": true, "assets_served": 2, "crash_restart_session_and_receipt": true, "persistent_materials": 1}`——仓库外临时安装、静态资源、真实 IPC、服务重启后的旧会话/幂等回执恢复均通过。
7. **愿景符合性抽查**：确认流程为 materials → cooldown（如有）→ manual_apply，确认输入仅 `preparation_id + step`，无自动投递路径、无练手/重点分类概念，与 VISION v0.12 一致。

## 未覆盖事项（诚实边界）

- 真实浏览器下的视觉布局、键盘焦点流转、缩放适配未验证，维持"待验"状态。
- 本复审不等于 PR 合并授权；合并与第 3 段准入决策仍归作者与 co-creator。本复审未改动任何产品代码。

## 结论

**approved（绑定精确 HEAD `523d9cc097403ad96964077c9a7ea47a7c8a3f3e`）。**
