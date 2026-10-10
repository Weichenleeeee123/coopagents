# 本机运行

在项目仓库根目录使用 Python 3.11 或以上版本：

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[service]"
& .\.venv\Scripts\python.exe -m crewmesh.server
```

默认监听 `127.0.0.1:8787`。正式 MCP 地址为 `http://127.0.0.1:8787/mcp`；健康检查为 `http://127.0.0.1:8787/health`。服务数据保存在仓库的 `.local/crewmesh.sqlite3`。从其他工作目录启动时，使用绝对数据库路径，避免生成另一份数据库。

可用 `--port 8789 --database '绝对路径.sqlite3'` 指定另一份独立实例。服务始终绑定本机回环地址，当前不供第二台电脑访问。启动失败时先检查端口占用；不要停止不属于当前实例的进程。

## 身份与接入

创建房间会签发当前成员的网页凭据与 agent 凭据。owner 可以生成一小时内有效、仅可兑换一次的邀请，队友兑换后获得自己的凭据。操作身份来自凭据，不能填写 author 冒充另一成员。

新网页凭据有效 30 天，agent 凭据有效 90 天。个人可用网页凭据轮换自己的 agent 令牌；旧 agent 令牌立即失效，随后需要更新 MCP 配置并重建连接。已有老库中到期值为空的历史凭据保留此前行为。接入步骤见 [Agent 接入](agent-connection.md)。

凭据只存本机必要位置，不放进地址栏、聊天提示或 Git。数据库保存凭据摘要；持有网页凭据的人具有对应成员的人工决定权限。当前没有邮件登录、忘记凭据恢复或第三方账号认证。

## 数据与停止

在运行服务的终端按 Ctrl+C 正常停止，然后复制 `.local/crewmesh.sqlite3` 到自己指定的备份位置。服务停止后再备份，避免在写入过程中复制不完整状态。不要删除原数据库。测试生成独立 UUID 数据库，保留在 `.local/test-evidence/`。

已有原生接入实验使用端口 `8768` 和 `.local/agent-integration/runtime/`，与正式服务相互独立。不要把实验消息当作正式房间任务或约定。

## 验证

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

实施状态与实际通过的检查见 [P2/P3 验证报告](p2-p3-report.md)。本机 HTTP/MCP 通过不表示公网部署、双机连通或原生闲置会话自动唤醒已完成。
