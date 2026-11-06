# Dashboard 改版独立审查 · 2026-11-06

**结论：changes_requested。** 当前未提交快照有 3 项 P2 阻塞发现，修订后再复审。新视觉方向与已批准草案相符；退回原因是加载状态、恢复行为和小字可读性，不是要求重做视觉方向。

## 审查对象

- 作者工作区：`C:/Users/Administrator/.local/share/opencode/worktree/fda5e9/dashboard-refresh`。
- 分支：`feat/dashboard-refresh`；基线 HEAD：`68ee920dec2a20ca309b4ea8886db807feff1fa7`。
- 未提交范围：App.tsx、style.css，以及未跟踪的 Dashboard.tsx、dashboard.test.tsx。不是某个新提交或 PR 的批准。
- 下列 SHA-256 在本轮开始和结束一致。未修改作者产品代码；临时复审测试副本执行后已移除，作者工作区保持原 4 文件变化。

| 文件 | SHA-256 |
|---|---|
| frontend/src/App.tsx | cc31301186d95b0d80e1eefe73d11025e0e83254931145d07d712d9a50eb169a |
| frontend/src/style.css | 59ba66bfd3c6c83c534c55bd19ee6f5855d0e5ce62e8a7c220cebfbc6dade060 |
| frontend/src/Dashboard.tsx | 3c84396ad54f1a9d05bc558a9c56a947aadb6e3067930641ba6b3f8ffd11f979 |
| frontend/tests/dashboard.test.tsx | 0c6b9d339eaf2d87077c9016d543db326febe70b716e8da3069bff5fcc8e90a7 |

## D1 · P2 · 未知资料被当成“尚未设置求职方向”

位置：`frontend/src/Dashboard.tsx:76`，输出在 148–158 行；hero 操作也使用同一缺省判断。

`!snapshot?.profile.targets.some(...)` 在 snapshot 尚未取得或查询失败时为 true。尽管统计卡片正确显示 `—`，下一步卡片仍显示“先整理求职方向”与“完善求职目标”。已有目标的用户在慢网络或本机服务暂不可用时，也会看到这项针对缺失目标的建议。加载失败不是“尚无目标”的证据。

独立探针分别让请求保持 pending、让请求失败；两个场景均稳定复现该建议出现。[前端状态设计](frontend-design.md#4-状态与错误)要求首次加载不能替代成没有记录。本轮作者的空状态测试只覆盖成功返回的空资料，没有覆盖建议区域的未知状态。

**修订要求：**仅在成功读取资料后计算缺失目标、缺失岗位等业务建议。加载中显示中性占位，失败时显示可恢复错误；hero 的入口可保持可用，但不要根据未知数据断言用户未完成目标。保留成功空资料时的正确引导。

## D2 · P2 · 总览临时断线后没有当前页恢复路径

位置：`frontend/src/Dashboard.tsx:34–60`；`frontend/src/App.tsx:83–102`。

Dashboard 单次 `Promise.all` 失败后只保存 error，没有现有 `useQuery` 的重连退避。App 又仅在非 dashboard 分支提供“刷新记录”，且本页未提供重试按钮。effect 仅依赖 api/revision，服务恢复不会触发请求。页面提示“检查本机服务后重试”，但用户必须离开总览再返回或整页重载才能恢复；停留或再点同一个总览入口不会更新 revision。

独立探针首次请求失败，随后模拟服务恢复；当前页没有重试按钮，也没有在既定首轮重连间隔内重新读取，错误与不可用统计保持不变。它与[应用契约的断线重连约定](application-contracts.md#1-本机通信与请求通则)及既有 `useQuery` 行为不一致。

**修订要求：**恢复可重试错误的自动重连/退避；对于需用户处理的失败，提供明确可用的当前页重试入口或恢复指引。按现有错误类别处理可重试与不可重试情况。测试需覆盖失败→服务恢复→总览数据恢复，不依赖用户切换页面，也不触发任何写入命令。

## D3 · P2 · 全局 muted 小字降低到不足的文字对比度

位置：`frontend/src/style.css:468`、509–510、617–619。

新版 `--muted: #748177` 被用于 12–14px 的表单说明、统计标签和说明。根据实际声明的前景/背景色计算：

| 前景 | 背景 | 对比度 |
|---|---|---|
| #748177 | #ffffff，表单与卡片 | 4.078:1 |
| #748177 | #f5f6f1，画布 | 3.755:1 |
| #748177 | #f9faf7，底部说明 | 3.893:1 |

这些是普通大小的功能文字，不属于大字或纯装饰。它们低于 WCAG AA 普通文字的 4.5:1；计算使用 CSS 声明值，不从截图抗锯齿像素推断。[W3C SC 1.4.3 说明](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

**修订要求：**在保留暖色与绿色方向的前提下加深说明文字颜色，覆盖实际使用的背景并验证对比度。无需改变用户已接受的布局或整体风格。

## 已通过的核对与边界

- 统计来自 profile、jobs、opportunities 查询；分页汇总 101 条岗位及 9 种机会状态的独立探针通过，待推进为 saved/applying，面试与 Offer 为 interviewing/offer。关闭状态未出现在活动机会列表。
- 初次失败时统计用 `—`，成功空记录为 `0`；最近机会区域区分失败与真实空状态。D1 限于资料相关建议，不能据此否定已正确实现的统计区。
- DOM 路由探针通过：默认总览、进入资料页、popstate 返回总览时，h1 获得焦点且 aria-current 随路由更新；最近机会的 ID 路由由作者测试覆盖。
- npm test：4 文件、21/21 通过；npm run build：类型检查及打包通过。
- Python tests：121/121；validation/tests：17/17；git diff --check 通过。
- 新增 6 项独立审查探针：2 通过、4 因目标行为失败（D1 两项、D2 一项、D3 一项）。不能合并成“全部验证通过”。

本轮查看了以下已有图像，均位于 `C:/Users/Administrator/AppData/Local/Temp/opencode/`：

- `interview-copilot-dashboard-concept.png`：批准方向参考。
- `interview-copilot-dashboard-profile-final.png`：资料页沿用绿色主按钮、浅色卡片与圆角表单；截图中表单已渲染。
- `interview-copilot-dashboard-mobile-fixed.png`：390px 截图的可见统计说明在卡片内，没有看到此前的溢出。

作者报告的真实 CDP scrollWidth=390 并非本轮独立测量。当前 CUA 返回 apps/browsers 均为空，本轮未自行重跑真实浏览器焦点、完整页面窄屏、200% 缩放或所有表单的布局验收；没有用 DOM 测试冒充这些结果，也没有改用此前受阻的 headless 启动方式。

## 复现与下一棒

独立探针：[dashboard-refresh-68ee920.test.tsx](review-probes/dashboard-refresh-68ee920.test.tsx)。将其复制为被审工作区的 `frontend/tests/reviewer-dashboard.test.tsx`，在 frontend 下执行：

```powershell
npm test -- tests/reviewer-dashboard.test.tsx
```

该探针只用合成 API 数据和 jsdom，不连接真实用户服务。对比度断言基于当前主题声明值，主题/背景调整后应同步对应使用场景。作者修订时先保留失败回归，再修改实现，运行完整测试与构建；提交精确 HEAD 并回传复审。当前 3 项发现未关闭前不放行合并。

[砚砚/gpt-6-astra🐾]
