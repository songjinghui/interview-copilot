# 第 1 段合并后的独立愿景核对

日期：2026-11-05
核对者：龟龟 / zai-org/GLM-5.3-Flash
角色：独立愿景核对（非作者、非代码审查者），按家规在合并后交由非作者、非 reviewer 的愿景守护猫执行
范围：第 1 段（仓储与应用服务）合并后的愿景符合性、交付表述准确性、以及第 2 段准入。**不是**重做全套代码审查、设计复审或验收。

## 核对依据（本次实际读取）

- `VISION.md` v0.12（版本行明确"范围已按用户决定更新；设计已审，第 1 段仓储/应用服务已合并（进度同步 2026-11-05，愿景范围不变）"）
- `docs/application-contracts.md` v0.3（含 §3 命令清单、§6 运行生命周期与实现顺序）
- `docs/storage-review-2026-11-04.md`（砚砚初审 changes_requested S1/S2 + 2026-11-05 复审 approved，S1/S2 关闭）
- `docs/storage-acceptance-2026-11-05.md`（宪宪合并后隔离验收）
- 仓库实况：`git status` 干净，main 在 a444d86，PR #1 MERGED（合并提交 0f7b679）
- 直接重跑测试套件（见下）

## 实际执行的独立检查

1. 仓库状态：工作区干净，`main...origin/main` 同步，HEAD = a444d86。
2. PR #1 状态：GitHub API 确认 MERGED，merge commit 与转交所述一致（0f7b679…），base = main。
3. 合并后增量：`git diff 0f7b679..a444d86` 仅动了 VISION 与 7 个 docs 文件（进度同步/验收记录），**没有任何产品代码改动**，与"产品代码未变"的说法一致。
4. 测试：当前 main 上重跑 `tests/` → **79/79 OK**（本人独立执行），`validation/tests` → **17/17 OK**（本人独立执行）。合计 96 通过，与验收记录所述 79+17=96 一致。
5. 代码扫描：`src/` 的实际文件集（application.py、jobs/model+store、sources/base+registry、storage/database+legacy+001_initial.sql）与"仓储、来源协议/注册、应用服务"的交付描述一致；grep 全 `src/` 无 "练手"、"代投"、"自动投递"、"auto-submit" 概念。
6. `application.py` 的确认/申请路径：outcome 由用户补记、要求 submitted 带时间与依据（evidence），**没有任何自动提交路径**——纯手动流程。
7. 能力建模：JobRecord/Capability/SourceCapabilities 与三态（verified/unverified/unsupported）、必填 basis、verified 必须带 evidence_ref——来自本人的初版 spike，合并版保持不变，与愿景的能力声明要求一致。

## 与 v0.12 用户决定的逐条对照

| v0.12 决定 | 第 1 段体现 | 结论 |
|---|---|---|
| 首版手动投递（自动投递移出） | RecordApplication 只记录用户补记的 outcome+evidence；无任何提交路径 | ✅ 一致 |
| 冷却期：有则二次确认，无/待核实仅提示一次 | ConfirmPreparation 的 step 为 materials/cooldown；present 才走第二步，其余一步到 ready_for_manual_apply；待核实不强制第二次确认 | ✅ 一致 |
| 不设练手/重点、无跨岗推演 | 代码与命令清单中无练手/重点概念；无次数规则引擎 | ✅ 一致 |
| 来源按独立能力增加 | SourceCapabilities 分项四能力；registry 独立注册 | ✅ 一致 |
| 后台转写 + 四项输入复盘在后续段 | `src/` 中无 ASR/复盘代码；命令清单中属于后段 | ✅ 范围未溢出 |
| 信息输入是系统能力、本地数据 | SQLite 主库 + 迁移、幂等历史版本 | ✅ 一致 |

## 交接所述事实的核对

- "砚砚独立 approved 精确 b5b1237…"：与 `storage-review-2026-11-04.md` 文末 2026-11-05 approved 记录一致，S1/S2 关闭，原始初审事实保留。✅
- "GitHub COMMENT 是共享账号限制，不是原生批准"：审查记录明确说了这一点。✅
- "main 当前 a444d86…产品代码未变"：本次 git diff 核对证实（docs-only）。✅
- "验收详情 docs/storage-acceptance-2026-11-05.md…96 测试通过"：与文件内容一致；测试计数本人已重跑证实。✅
- 验收的 wheel/临时安装/仓库外合成链部分：按记录读取核对，**本人未重复执行**（该链路属验收记录的独立执行，不在本核对职责内重复跑）。诚实说明此点。

## 结论

1. **第 1 段符合已定愿景 v0.12**，未夹带旧愿景的自动投递或复杂冷却规则，范围未溢出到第 2 段以后。
2. **交付表述准确**：各记录文件（审查、验收、进度同步）与仓库与 GitHub 实况一致；测试计数本人复核通过。
3. **第 2 段（可运行工作台：目标/资料 → 来源搜索或导入 → 机会 → 简单确认 → 人工结果；API 与页面同段交付）按 application-contracts §6 的分段可以先红测开工。** 本核对不是放行"验收完成"，是放行"进入下一段"；真实浏览器渲染、硬件、ASR、真实来源仍属各自段落的验收。

## 处理建议（非范围决策）

- 第 2 段开工先按惯例红测：目标/资料录入、机会创建、简单确认、人工结果，每个命令先有失败测试。
- 本核对不改变 VISION 的任何已确认项；后续如用户再改范围，以 VISION 修订为准，不从代码回追。
