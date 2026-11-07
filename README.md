# 求职助手 · Interview Copilot

把求职目标、真实经历、岗位原文和实际进度保存在本机，按固定版本核对材料，再由自己完成投递。

本仓库已交付第 2 段工作台：目标与资料、手工导入岗位、机会管理、简单确认、人工结果记录。整体产品范围以 [VISION.md](VISION.md) 为准；真实浏览器视觉/焦点/缩放验收、面试录音、转写、复盘、真实来源接入和备份恢复仍按后续分段实现。

2026-11-07 新增[首版需求分块与审阅入口](docs/v1-review/README.md)：按使用结果拆分功能、数据及跨块交互，当前全部待逐块审阅，通过后再实施；不将既有局部实现等同于整块可用。

## 本机运行

当前启动器面向 Windows。需要 Python ≥3.10、Node.js 20.19+ 或 22.12+；本次开发验证使用 Python 3.13 / Node 24。

在仓库根目录执行：

```powershell
python -m pip install -e '.[test,validation]'
Set-Location frontend
npm ci --include=dev
npm run build
Set-Location ..
python -m interview_copilot serve --data-dir "$env:LOCALAPPDATA/InterviewCopilot"
```

启动器默认打开浏览器，地址为 `127.0.0.1:17863`。数据目录必须显式指定，重复启动同一目录会被拒绝。端口被占用时可用 `--port 17864`；不会连接未知服务。关闭浏览器不停止服务，结束运行窗口会停止服务。重新打开一个已经运行的工作台：

```powershell
python -m interview_copilot open --data-dir "$env:LOCALAPPDATA/InterviewCopilot"
```

第 2 段不注册开机启动或更改系统任务计划。开发时可在另一个终端运行 `npm run dev`，它持续构建静态资源；刷新上述本机页面查看变化，鉴权与服务端口保持一致。

## 使用路径

1. 在“目标与资料”保存求职方向、真实经历和粘贴的简历；经历核实后再确认。
2. 在“岗位”粘贴取得的 JD。当前尚未安装来源搜索适配器，缺失内容会明确显示为未知。
3. 将岗位加入机会，选择固定 JD 与简历版本；无需简历时写明原因。
4. 有冷却期时确认材料，再确认已了解冷却期；无或待核实只确认材料。自己完成外部投递。
5. 单独记录实际结果、时间与依据。历史结果可直接补录；纠正保留原事件。

未保存表单和待重试请求保存在此浏览器的 IndexedDB，按本地工作区隔离。会话过期时从启动入口重新打开；保存结果不确定时用“重试保存”继续原请求。

## 验证与开发

```powershell
python -X utf8 -m unittest discover -s tests -t . -v
python -X utf8 -m unittest discover -s validation/tests -p 'test_*.py' -v
Set-Location frontend
npm test
npm run build
Set-Location ..
python -X utf8 scripts/verify_workbench_runtime.py
```

最后一条命令在临时目录制作 wheel、安装、启动独立服务，并验证崩溃重启后的会话与幂等回执，随后清理临时数据。测试不读取用户工作目录下的数据。

[架构](docs/architecture.md) · [第 2 段合并后隔离验收](docs/workbench-acceptance-2026-11-06.md) · [前端设计](docs/frontend-design.md) · [数据库设计](docs/database-design.md) · [接口契约](docs/application-contracts.md) · [工作台运行说明](docs/workbench-runtime.md)
