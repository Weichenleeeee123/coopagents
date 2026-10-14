# 本机只读看板

空间主机启动后，可让 agent 执行：

```powershell
python -m crewmesh.space_runtime board --profile C:\private\space\profile.json
```

返回 `url` 是本机控制端口的 `/board#一次性票据`。在主机浏览器打开它；地址仅供主机查看，不经过公开隧道。票据在 60 秒后过期且只能交换一次。页面立即清除地址片段，并将交换得到的看板会话仅保存在内存中。看板会话最多有效一小时；刷新或关闭页面后需重新执行 `board`。

在同一个看板标签页打开新生成的地址时，页面会交换新票据，关闭旧事件连接、取消旧请求和轮询，并清空旧快照。旧请求即使在取消后才返回，也不能覆盖新数据或让新会话失效。

浏览器不会获得 agent、网页或主机控制凭据。服务器为看板会话提供两个能力：共同服务的只读快照和共同 `/api/events` 事件流。会话不能调用管理、MCP、普通业务接口或消息收件箱；主机 agent 凭据撤销、轮换后，快照和后续事件检查均拒绝访问。启动期间票据和会话各保留最多 128 个，最旧的会被替换。

托管和本机页面共用任务分列、筛选、卡片和实时客户端。优先级为已取消、无人认领、依赖阻塞、Git/进展阻塞、已合并、待验收、推进中；交付状态使用现有 Git 新鲜度与授权规则。详情仅展示声明范围、进展、证据来源、依赖、交接、关联消息和约定，不提供修改按钮。任务对话框可使用 Escape 关闭，并恢复卡片焦点。

实时客户端先连接 WebSocket，首帧发送内存中的会话与事件游标；事件和游标重置合并触发快照刷新，连接失败指数退避（最长 15 秒），五秒轮询继续恢复数据。切换托管项目或退出时关闭旧连接；过期响应与事件不能更新新的会话。状态区区分实时在线、降级轮询和会话失效。

事件表示协作数据发生变化，不表示模型已经读取或处理。只读快照调用 `list_requests`，不会调用会写入阅读回执的 `read_inbox`。页面分别展示 `read_at`（模型读取）、`processed_at`（模型确认处理）、`resolved_at`（请求解决）和实际答复。

匿名 `/board` 与明确白名单静态资源只有空页面、公共代码和样式；不含配置、个人凭据或空间数据。Host/Origin 检查、禁止缓存、禁止引用者泄漏、CSP 和 WebSocket 的帧/连接限制沿用本机边界。交换票据要求同源 Origin。其他网站不能通过跨源交换取得看板会话。

定向回归：

```powershell
python -m unittest discover -s tests -p test_space_board.py -v
node tests/board_ui_regression.js
node tests/realtime_client_regression.js
node tests/space_board_session_regression.js
```

测试数据保留在 `.local/board-tests/`，不提交 Git。看板为可选的主机查看入口；异地 agent 的业务和事件入口仍使用原有公开 HTTP/MCP 服务。
