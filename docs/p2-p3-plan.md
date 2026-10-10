# Crewmesh P2 / P3 Implementation Plan

> **For agentic workers:** Use subagent-driven-development task by task, with specification review before quality review. Never delete files. Commit each verified stage separately.

**Goal:** 完成可运行的本地共享服务与真实数据网页，保留现有 agent 入口，明确等待消费、人工决定和证据来源。

**Architecture:** 继续使用 SQLite 短连接与 BEGIN IMMEDIATE 写事务。领域模块直接放在 `src/`，认证 HTTP API 与官方 MCP SDK 调用同一套领域服务。网页由同一服务提供静态文件，使用 bearer 凭据；本轮只监听本机，不部署或改动已有实验服务。

**Tech Stack:** Python 3.11+、SQLite、unittest、MCP 2.3.0、Starlette / Uvicorn、原生 HTML/CSS/JavaScript，无网页构建器或第三方分析服务。

所有测试数据写入 `.local/test-evidence/` 的独立 UUID 文件并保留。基础测试命令：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Task 1：P2.3 会话、进展与范围提示

Files: `src/activity.py`、`src/database.py`、`tests/test_activity.py`。

接口：`ActivityStore(identity_store)`；`register_session(agent_token, session_key, tool, repository, branch, task_id=None)`；`list_sessions(token)`；`report_progress(agent_token, task_id, state, summary, evidence='')`；`list_progress(token)`；`overlaps(token)`。

会话键在成员内唯一，身份来自凭据，记录服务器 UTC 更新时间。一人可以拥有多个会话；可用工具为 claude-code / codex-cli / codex-desktop。任务关联必须在本房间且归当前成员所有，不能伪报别人任务。工作进展只有认领者能写；状态 working / blocked / local_done / pushed / pr_open / merged，来源始终为 agent_report，提交说明是自述证据，不自动变为 Git 验证。

同房间不同任务声明的 scope 按 `/` 分段比较，只有相同或父子前缀匹配才提示，返回任务 ID、声明范围和原因。`src/auth` 不匹配 `src/authentication`。不执行路径、不锁文件、不宣称语义重复。会话更新不隐式改变进展。

- [x] 写测试：权限、隔离、同键更新、多会话、任务归属、来源、范围前缀边界和重开持久化；先确认缺少 ActivityStore 的失败。
- [x] 实现领域接口及数据库约束；输入限制为键 200、仓库 500、分支 200、说明 4000、证据 1000 字符，拒绝非法状态和空必填值。
- [x] 运行完整测试；规格审查后质量审查，修复问题，独立提交。

## Task 2：P2.4 技术请求与离线恢复

Files: `src/messages.py`、`src/database.py`、`tests/test_messages.py`。

接口：`MessageStore(identity_store)`；`send_request(agent_token, request_key, receiver_member_id, task_id, context_version, body)`；`list_requests(token)`；`read_inbox(agent_token, after_id=0, limit=50)`；`acknowledge(agent_token, request_id)`；`reply(agent_token, request_id, request_key, context_version, body, evidence='')`；`resolve_request(token, request_id, context_version)`；`assign_receiver(web_token, request_id, receiver_member_id)`。

接收方允许 None，表示待指定负责人；发送/回复只允许 agent，指定负责人只允许 web。目标成员和任务必须属于房间。版本为正整数，正文 1–4000 字符、重试键 1–200；发送和回复的键在房间与作者内唯一，完全相同重试返回原记录，不同内容冲突。

首次绑定接收方时生成唯一、单调递增的投递 ID，读取按投递 ID 分页，返回 requests（包含 delivery_id）与 next_cursor，记录 read_at 但不记录 processed_at 或解决。ack 仅接收者在读取后显式调用，幂等；回应仅接收者与原请求版本匹配，不自动结案。只有发送者成员、明确版本且已有回应才能确认解决。其他成员统一不可见目标请求操作；网页可查看本房间问答与读/处理/解决时间。离线消息与收据重启后保持。

- [x] 写测试并观察缺实现失败：分页、精确重试、不同作者键隔离、跨房间拒绝、接收者约束、read/ack/resolve 分离、错误版本、未分配及指派、老请求在游标推进后才分配仍可读、重启恢复。
- [x] 实现追加式请求/回复、独立读取与确认记录，不删除已有记录；所有写操作在事务内解析身份。
- [x] 完整测试与两阶段审查，独立提交。

## Task 3：P2.5 版本约定与人工决定

Files: `src/contracts.py`、`src/database.py`、`tests/test_contracts.py`。

接口：`ContractStore(identity_store)`；`propose(agent_token, contract_key, expected_version, title, body, source_request_id=None, commit_ref='')`；`list_contracts(token)`；`decide(web_token, contract_id, version, decision)`；`list_events(token)`。

提案创建时 expected_version=0，更新时必须匹配当前头版本，追加不可变版本。key/title 1–200、正文 1–4000、提交说明最多 200 字符。来源消息必须同房间。只有 web 凭据能批准或拒绝当前明确版本；每版本最多一个决定，同决定人相同重试幂等，其他竞争或旧版本冲突。提案、决定各追加来源成员与时间事件。有效版本是最近批准版本，新的待审提案不覆盖旧有效版本；agent 增补细节不能自动生效。

- [x] 写失败测试：版本追加、旧头冲突、人工权限、跨房间、双人并发审批、幂等、有效版本保留、来源校验、事件和持久化。
- [x] 实现提案/版本/决定/事件数据与事务，不修改或删除既有版本。
- [x] 完整测试与两阶段审查，独立提交。

## Task 4：P2.6 邀请、凭据与 HTTP/MCP

Files: `src/identity.py`、`src/database.py`、`src/api.py`、`src/mcp_service.py`、`src/server.py`、`tests/test_access.py`、`tests/test_http.py`、`tests/test_mcp.py`、`pyproject.toml`。

补充单次邀请：owner web 签发随机邀请，存摘要与到期时间；兑换创建普通成员及个人 web/agent 凭据。签发/兑换是原子操作，过期和复用拒绝。web 凭据 30 天、agent 凭据 90 天；升级老数据库时无到期值的既有凭据保留原语义，新凭据全部设到期。个人 web 可轮换自己的 agent 令牌，旧令牌即刻失效；不接受自报身份。

HTTP 路由：`/api/rooms` 创建房间，`/api/join` 兑换邀请，`/api/me` 身份，`/api/invites` 签发，`/api/agent-token` 轮换，`/api/tasks`、`/api/sessions`、`/api/progress`、`/api/overlaps`、`/api/requests`、`/api/inbox`、请求 ack/reply/resolve/assign 操作、`/api/contracts`、约定 decision、`/api/events`、`/api/snapshot` 网页组合数据。除创建/兑换外均要求 Authorization bearer。字段白名单拒绝 author、room_id 等伪造参数；领域错误映射 400/401/404/409，异常不输出凭据或 traceback。

MCP 使用官方 streamable HTTP 和 SDK 认证上下文，工具内部再次用原始凭据解析身份，防止撤销与写入竞争。stateless 请求不跨用户复用会话身份。agent 不能使用邀请、凭据管理和批准工具；提供自查身份、任务认领、会话、进展、消息与提案工具。消息为数据，不提升为用户指令；收件箱拉取不承诺唤醒闲置会话。

服务器支持 `python -m crewmesh.server`，默认 `127.0.0.1:8787`，数据库 `.local/crewmesh.sqlite3`。HTTP 默认同源，禁止跨站写入与宽泛 CORS；限制正文大小与 JSON 类型。凭据不通过 URL 传递。运行说明记录启动、停止、到期与备份路径。

- [x] 邀请/到期/轮换测试先红后绿，覆盖竞争、摘要、过期、撤销与旧库升级。
- [ ] 实现 HTTP/MCP；用实际回环 HTTP 和两个认证成员完成工具调用、请求/回复/确认及越权/撤销检查，保留证据。
- [ ] 完整测试和两阶段审查，独立提交；不计为原生日常入口或双机验收。

## Task 5：P3 网页与浏览器验收

Files: `src/static/index.html`、`src/static/styles.css`、`src/static/app.js`，HTTP 静态路由和包资源声明，`tests/test_web.py`，`docs/app-running.md`、`docs/p2-p3-report.md`。

单网页工作台：创建/加入/凭据登录；团队概览；任务创建和详情；会话、分支、最后更新时间与自述来源；范围提示；技术请求和读取/处理/解决状态；明确版本的批准/拒绝；owner 邀请与个人 agent 凭据轮换；原有工具的一次性配置说明。

界面以墨绿、暖纸色、细线和清晰排版呈现团队工作台，避免聊天产品外观。桌面侧栏和手机窄屏导航共用数据，语义标签、键盘可操作、错误提示与空状态完整。所有内容来自 API，不注入展示数据。网络失败保留最后数据并明确断线与更新时间；收到 401 清除会话。令牌只存当前标签页 sessionStorage，加入/轮换返回值只在必要时展示，不写日志或地址栏。所有用户文本安全渲染。

- [ ] 实现真实 API 表单、详情和人工决定，不改变人和 agent 权限边界。
- [ ] 真实浏览器验证创建/加入/任务/邀请/待审提案、错误和断线恢复、移动视口、键盘及脚本注入文本；保留截图和证据，不删除测试数据。
- [ ] 静态资源与完整服务回归、规格/质量审查，独立提交网页；更新路线、运行文档与报告，工作区清理仅通过提交，不删除文件。

## 完成边界

P2/P3 完成指本地共享服务、认证 MCP 和真实数据网页通过上述验收。公网 HTTPS、第二台电脑、全新原生会话的检查点稳定性和运行中自动消费仍属独立验证；不修改已有用户服务或全局 agent 设置，不自行部署。
