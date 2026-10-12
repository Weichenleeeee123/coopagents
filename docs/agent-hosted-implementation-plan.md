# Agent 承载空间 L0–L4 实施计划

> **For agentic workers:** 使用 subagent-driven-development，阶段实施后顺序进行设计与质量审查。所有证据保存在 `.local/`，禁止删除文件。

**Goal:** 完成与托管版本共用协作规则的本机空间、异地连接、实时事件、Skill 接入及看板，并合并主分支。

**Architecture:** `CoordinationService` 为共同核心。持久事件在业务事务内生成，HTTP/MCP 执行操作，WebSocket 推送事件。独立本机管理与公开协作入口使用同一核心；主机管理不经过隧道。Skill 管理本机进程和私有配置，不要求用户运行单独客户端。

**Tech Stack:** Python 3.11+、SQLite、Starlette、Uvicorn、MCP、WebSocket；Cloudflare 临时隧道或用户提供的稳定 HTTPS 入口。

## 1. 共用实时事件（L2 基础）

- [ ] 新增 `src/events.py`：事务内事件记录、按空间授权读取、游标与过期恢复；事件仅包含失效通知，不广播消息正文/秘密。
- [ ] 修改 `src/coordination.py` 初始化事件设施，业务领域操作不复制。
- [ ] 新增 `src/realtime.py`：共用 `/api/events`，首帧认证、严格 Host/Origin、帧限额、发送超时、连接限额、定期重新认证与断线恢复。
- [ ] 修改 `src/api.py`：托管入口挂载相同事件路由；增加运行依赖并维护发行约束。
- [ ] 新增 `tests/test_events.py`、`tests/test_realtime.py`。先验证缺失功能失败，再测试事务回滚、跨空间拒绝、认证撤销、无秘密事件、断线恢复。
- [ ] 定向回归、顺序审查、提交并推送。

## 2. 本机空间与异地网络（L0/L1）

- [ ] 新增 `src/spaces.py`、`src/space_server.py`：创建、邀请、加入、重启；将本机管理与公开协作端口分离，公开入口不暴露创建/管理凭据。
- [ ] 新增 `src/space_runtime.py`、`src/tunnels.py`：agent 使用的启动/停止/检查入口，绑定回环、私有状态文件、原子保存、只管理自己启动的进程；临时地址变化必须重新生成邀请。
- [ ] HTTP 路径和 MCP 方法复用共同操作表；远端管理通过本机桥接明确授权并遵循共同权限，不能放宽普通 agent 凭据。
- [ ] 隧道下载来源/校验与故障信息明确；支持已有 HTTPS 入口，不运营维护者中继。不修改用户已有隧道/VPN配置。
- [ ] 测试邀请过期/单次使用/撤销、泄漏限制、端口分离、重启数据保留、并发认领与失败恢复；运行真实互联网 HTTP/WebSocket 往返，异地双机证据单独记录。
- [ ] 审查、提交并推送。

## 3. 原生接入 Skill 与 stdio 桥接（L3）

- [ ] 新增 `src/space_bridge.py`：从私有文件读取成员凭据，调用相同 HTTP/MCP 业务与事件协议；独立缓存事件游标，失败不标任务完成；stdout 只输出 MCP。
- [ ] 新增 `src/skills/crewmesh-space/SKILL.md` 与协议说明，提供创建、邀请、加入、恢复、退出路径，保留已安装配置，不覆盖其他服务器。
- [ ] CLI 参数中只出现私有文件路径，不把秘密放入进程命令行；明确连接在线、模型阅读和业务处理区别。
- [ ] 更新包数据；测试 bridge 协议、事件重连、秘密不输出及 Skill 必需步骤，使用实际 CLI 验证本机 MCP。
- [ ] 审查、提交并推送。

## 4. 复用看板与完整发行（L4）

- [ ] 提取共同看板视图模块，托管与本机均使用；本机只读界面展示自动分列、任务详情、成员进度、约定和消息消费状态。
- [ ] 两版接入相同实时客户端，在故障时显示离线并有轮询恢复；不将 WebSocket 到达当作模型已处理。
- [ ] 更新 README、开发/安装说明、路线与最终报告，不将未取得的外部证据标为通过。
- [ ] 运行完整 Python/网页回归、真实浏览器、发行包安装、原生 MCP 和公网实时验收；停止自己的验收进程并保留证据文件。
- [ ] 最终设计和安全审查后推送，创建 PR，等待 CI，通过后使用 merge commit 合回主分支，保留分支和文件。

## 验证命令

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
node tests/web_session_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/agent_connect_ui_regression.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
node tests/git_ui_regression.js
node tests/collaboration_ui_regression.js
node tests/task_lifecycle_ui_regression.js
node tests/dependencies_ui_regression.js
git diff --check
```

每个新增测试先独立运行并观察预期失败，再实现最小代码使其通过。单机公网隧道往返可以证明公共入口可用，但不能代替另一电脑、另一网络的真实协作。外部网络故障不阻止其他阶段推进，也不能伪造通过结果。
