# 详细设计补齐与初审修订记录

日期：2026-11-04；作者：宪宪 / gpt-6-astra

关联：[缅因猫初审](architecture-design-review-2026-11-04.md)；[设计总览](architecture.md)

状态：**作者修订已落盘，等待缅因猫复审；尚未放行功能实现。** 原型真实浏览器视觉/焦点检查仍未完成，其余检查范围见下文。作者不能将自己的检查替代跨个体审查结论。

## 初审响应

| 项 | 本轮处理 | 可复核证据 / 剩余边界 |
|---|---|---|
| R1 反馈与邀请身份 | 增加 source_accounts；消息唯一键 account_id/external_key；邀请唯一键 source_account_id/source_event_key，与 source_feedback_id 分离；游标按账号/入口；重授权复用稳定账号 | SQL 与数据库设计 §4；设计检查覆盖双账号同编号、同账号重复、改期/取消同场与另一账号不串联。真正同步/提醒事务仍待实现测试 |
| R2 多音频组合 | 每段保存所属面试、audio_asset_id、原始时间、来源文字版本/段落；CombineTranscripts 生成新版本；校对继承来源，ordinal 只管阅读顺序 | 设计检查以两份音频的同一个 00:30 区间组合/校对，并复制到另一内存库重新读取；两段分别定位 A/B。真实音频播放、时间轴和窗口重开待实现验收 |
| R3 显式重新转写 | transcription_jobs 增加 request_generation；唯一键包含代次；RetranscribeAudio 使用命令 request_id 幂等，事务分配下一代次；恢复不换任务/代次 | 同配置两代次可并存、重复同代次被拒绝的 SQL 检查通过。进程恢复与迟到结果由应用栅栏保障，后续需故障测试 |
| R4 无简历说明 | preparation.resume_exception 持久保存；确认时必须有简历或非空说明；查询返回说明、申请事件保存当时快照；改说明清确认 | SQL 检查拒绝无材料无说明的确认，允许有说明并读回；原型事件检查验证改说明重置确认。正式重启、历史事件查询待应用实现 |
| R5 缺失交付物 | 原型、SQL 派生字段字典、设计检查脚本均已落盘；总览更新为 v0.3 与待复审状态 | 本地 HTTP 200；10 项原型源码交互检查通过；**真实浏览器渲染/焦点/缩放检查未完成**，见环境限制 |

审查中发现的根因：设计文档是边写边落盘的，初审读到了尚未完成的交付包；同时身份和版本细化没有把“页面操作 → 命令 → 持久字段 → 唯一约束”全部走通。本轮用可执行 SQL 及独立原型检查逐项对照，并在总览标清阶段，不再把部分产物落盘当成设计验收完成。

## 本轮实际运行

```powershell
python -X utf8 docs/design-checks/validate_design.py
# 初次：10 项，4 项因 R1–R4 所需契约字段缺失而断言失败
# 修订 SQL 后：10 项全部通过

python -X utf8 docs/design-checks/validate_design.py --write-reference
# 先运行 10 项检查，通过后由 SQL 生成 schema-reference.md

node docs/design-checks/check_prototype.cjs
# 首次发现“报告未保存输入快照”；补目标断言后确认失败
# 修正原型后：10 项源码级交互检查通过

python -X utf8 -m unittest discover -s tests -t . -v
# 16 项通过
python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -v
# 17 项通过
```

新增检查均使用内存数据库或 Node VM 的模拟 DOM，不触及用户运行数据，不调用招聘平台或模型。53 项通过分别为 **10 SQL 设计检查 + 10 原型源码检查 + 33 现有测试**；它们不能合并解读成 53 项产品新功能已验收。

SQL 检查覆盖 DDL 可执行、外键/integrity、A→B→A 修订与不可变 UPDATE、冷却期确认约束、跨面试引用、任务去重、完成时间及 R1–R4 的字段/关系。它不运行仓储、工作进程、迁移或 HTTP handler。原型检查执行真实内联事件处理器，但用模拟 DOM，不证明 CSS 布局、浏览器事件时序、焦点或无障碍效果。

## 原型打开与检查

[workbench.html](prototypes/workbench.html)是单文件、无外部依赖的虚构数据原型，可以直接在浏览器打开；刷新会重置演示，不保存真实资料。也可在仓库根目录运行：

```powershell
python -m http.server 17864 --bind 127.0.0.1 --directory docs/prototypes
```

访问本机 `http://127.0.0.1:17864/workbench.html`。本轮实测该地址返回 HTTP 200。

供复审的操作路线：

1. 找岗位 → 加入机会并准备投递 → 有冷却期时两次确认；切换为无/待核实后只一次。打开投递页面不应把机会改成已投递。
2. 选择“此渠道无需简历”，空说明不允许确认，填写后可确认；改说明需重新核对。补记实际结果是事实记录。
3. 面试 → 补录已有面试，不创建虚假投递；进入四项材料选择，缺内容禁用生成，缺 JD/简历提示局限。
4. 两个 00:30 引用分别显示录音 A/B；生成报告后改材料，已生成报告仍显示原输入。
5. 后台任务暂停 → 模拟服务重启，仍暂停；重新转写增加请求代次。改进项完成后模拟重算，保持完成。
6. 浏览器实际检查文字可见、无横向溢出、键盘焦点、窄窗口与 200% 缩放。

环境限制：CUA 报 `Browser is not available: iab`，可用浏览器清单为空，limb 节点清单为空；Hub preview 请求返回 `deliveryStatus=unconfirmed / no_matching_client`，不能声称已在用户界面打开。另尝试隔离无头 Edge 截图，执行前被自动审批审查以 `blocked by policy` 拒绝，未运行。没有截图证据，步骤 6 保持待检查；不通过换工具绕过拒绝。

## 下一棒

交缅因猫复核 R1–R4 的数据/页面/命令一致性、R5 文件完整性及上述验证边界；如审查环境可用浏览器，请补实际渲染与关键路径点击证据。仍有阻塞则退回修订；明确通过后，作者按应用契约的实现顺序先写失败测试，再开始产品代码。
