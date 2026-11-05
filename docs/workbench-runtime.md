# 第 2 段工作台运行说明

本文件描述本分支的运行方式与实现边界；代码审查、合并和发布验收结论由独立记录承载。

## 运行组成

- React / TypeScript 页面构建到包内 `interview_copilot/web`；FastAPI 同源提供页面和 `/api/v1`。静态资源未构建时启动器拒绝启动，不呈现空白工作台。
- `WorkbenchService` 复用第 1 段命令事务与回执，只扩展手工 `ImportJob` 和读取视图。手工记录没有来源 URL 时保存 null；来源仍有明确身份，不生成假链接。缺 JD 的手工记录标为 partial。
- 查询包括 profile、jobs、opportunities、preparations、applications 和材料历史；集合分页最多 100 项。机会详情聚合固定准备、实际申请事件和当前冷却期依据。
- 本段没有安装产品来源适配器，`sources` 返回空集合。页面说明可手工导入；URL 自动抓取返回明确的来源不可用。按需来源注册协议与三态证据模型保持不变，真实来源配置和调度留在第 5 段。

## 本机通信

`serve --data-dir DIR [--port PORT] [--no-browser]` 只监听 `127.0.0.1`。以 Windows 文件字节锁实现数据目录级单实例互斥，操作系统在进程退出时释放锁；保留锁文件不会阻塞重启。端口使用独占 socket，先绑定成功再启动服务，不探测、复用未知进程。

启动入口经 Windows named pipe 取得一次性 nonce。通道进行双向 HMAC challenge，使用从用户凭据密钥派生的独立 IPC key；只传有界字节，不反序列化 pickle。凭据密钥用当前用户 DPAPI 加密持久化，不使用机器共享范围；无法解密时失败关闭，不静默重置。其用户范围来自 [CryptProtectData 官方说明](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。

nonce 放在 fragment，页面在交换前立即移除；60 秒有效且只能使用一次。会话保存在 sessionStorage，签名密钥跨服务重启保持，8 小时有效、活动期间续期。响应含非敏感的稳定工作区标识，供 IndexedDB 草稿隔离使用，不回传数据目录路径或密钥。

Host 严格匹配回环地址及端口；写请求的 Origin 必须相同。所有业务查询和命令鉴权。健康检查不含个人数据。JSON 请求限 1 MiB（流式计数），拒绝重复 JSON 键、非有限数及未知命令字段；静态资源加 CSP/no-store/nosniff，原文只以文本节点显示，外链只允许无凭据 HTTP(S)。没有跨域开放、自动提交或代发消息入口。

实现采用 [FastAPI 官方测试客户端](https://fastapi.tiangolo.com/tutorial/testing/)验证 HTTP 边界，并另有真实 loopback 服务驱动的 DOM 操作链。DOM 操作通过不等于真实浏览器视觉验收。

## 草稿、冲突与恢复

- 表单值先存 IndexedDB；发送前将完整命令信封和 request ID 持久化。网络结果不确定时锁定这次输入，显式重试原信封；不根据缓存自动确认或投递。
- 读写草稿失败时说明实际失败，不显示已保存，不向服务提交尚未持久化的命令。
- 业务字段错误保留输入；revision 冲突不自动套用新版本。用户先核对最新记录，再明确选择保留草稿继续保存。简历草稿保留原 parent version，服务返回当前 parent ID 支持这一选择。
- 资料编辑保留未展示的结构化条件、经历日期/单位/成果、已有事实引用；仅纠正结果说明时保留原时间精度和附件依据。
- 保存成功后清理本地草稿。退出浏览器不会清除服务端记录；同一数据目录重启后请求回执仍存在。

## 构建与当前边界

`npm ci --include=dev` 明确安装测试和构建工具；宿主可能设置 `NODE_ENV=production`，测试入口单独设为 test。`npm run build` 完成类型检查并生成带 hash 的包内静态资源。`npm run dev` 使用 Vite build watch，直接刷新鉴权服务页面，无独立 UI 开发代理端口。这一开发方式维持生产同源安全边界。

制作 wheel 前必须先构建前端。`scripts/verify_workbench_runtime.py` 从当前源代码及构建产物复制到临时打包目录，使用声明的隔离构建依赖；再在仓库外安装并验证静态资源、真实 IPC、未授权拒绝、结束进程后重启、旧会话续期和命令回执重放。

本段页面以粘贴文字入口完成主链；原件分块上传、AI 整理、日程、提醒、录音、转写、系统自动启动/唤醒、复盘、真实来源与备份仍属于后续分段。已有结构化目标条件可保留展示，本段不提供完整的金额/条件运算符编辑器。真实浏览器 1280/960 布局、200% 缩放、键盘焦点与屏幕阅读验收尚须在可用浏览器界面执行。
