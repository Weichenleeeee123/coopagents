# 任务交接、释放与恢复

任务始终只有一个负责人。交接分成“提出”和“接受”：原负责人继续持有任务，直到接收成员在网页明确接受；项目负责人也可以在网页明确强制转交。agent 可以释放自己的任务、提出交接和读取历史，不能代替接收方接受、拒绝、取消或恢复任务。

## 网页使用

打开任务卡片，在“任务交接与恢复”填写摘要。摘要应说明分支、已完成内容、未解决问题和下一步；再选择释放、目标成员与转交，或取消任务。接收方可在同一任务详情看到待接手摘要，并明确接受或拒绝。项目负责人的权限由服务器返回：旧项目创建者，或具有有效项目访问权限的商业团队 owner/admin。

交接期间看板仍显示原负责人和当前进度。接受、强制转交、释放和取消会归档原进度、会话关联和交付证据，清空活动投影。接手后，新负责人需要绑定自己的执行会话并重新上报。看板不会将前一周期的 local_done 或 merged 当作新周期的进展。

任务状态筛选提供进行中、已取消和全部。已取消任务不可认领或上报；本人或项目负责人可在详情填写原因后重新打开，恢复为待认领。未认领任务的创建者可以取消；取消后保留创建者和前任负责人作为恢复授权依据。旧数据库中无法确认创建者的开放任务由项目负责人处理。

“交接与恢复记录”显示历史操作、摘要、原进度、分支和历史交付。更多记录按任务分页读取，完整交接证据由单独按钮读取。轮询保留摘要与目标成员草稿；切换项目会清空草稿和旧请求结果。操作发现版本已变化时返回冲突，须刷新、阅读当前上下文后再次提交。

## agent 会话与责任周期

凭据仍然标识项目成员；`session_key` 只是同一成员多个 agent 之间的执行标识，不能用来冒充另一成员。建议每次接手生成新的 session key：

```text
claim_task(task_id=42, session_key="codex-session-new-uuid")
```

返回任务的 `ownership_epoch`、`revision` 和 `execution_session_key`。相同成员、相同 session 的认领重试返回相同任务；不同 session 会收到冲突。网页接受交接之后，接收方 agent 也用这一调用绑定新 session。

任务绑定 session 后，所有带任务的活动必须传当前 session 和返回的 epoch：

```text
register_session(session_key="codex-session-new-uuid", tool="codex-cli",
  repository="github.com/team/repo", branch="feature/auth", task_id=42,
  ownership_epoch=3)
report_progress(task_id=42, state="working", summary="正在补充接口测试",
  session_key="codex-session-new-uuid", ownership_epoch=3)
checkpoint(session_key="codex-session-new-uuid", tool="codex-cli",
  event="startup", task_id=42, ownership_epoch=3)
repo_checkpoint(task_id=42, session_key="codex-session-new-uuid", ownership_epoch=3)
link_delivery(task_id=42, branch="feature/auth",
  session_key="codex-session-new-uuid", ownership_epoch=3)
```

上面的 `repo_checkpoint` 是本地 Git adapter 形式。远端 HTTP/MCP 形式还需要 `observation`，由本地 Git 适配器生成，不伪造仓库事实。返回的 epoch 是唯一依据，不要自行增加或从客户端时间推算。

释放后即使同一成员再次认领，也必须使用新的 session key。已退休的 key 无法再次绑定该成员的同一任务。旧版尚未独占绑定的 sessions 和带任务检查点，也会在责任切换时登记为已退休 key；未经历切换的 legacy 会话保持原兼容行为。旧会话、旧 epoch、没有 session 的迟到上报不能污染新周期。旧客户端省略 session 仅兼容尚未绑定且没有经历责任切换的任务；经历切换后先用新的 session 认领/绑定。原生 hook 默认不附 task_id，其成员级检查点仍可读取上下文；带任务的 MCP 检查点遵守相同隔离规则。

本地 adapter 把采集时的 session 和 epoch 一起持久化到队列，重放时保持原值。不同执行周期使用独立队列，旧队列留存供排查，不会阻塞新会话。旧版无 session 队列保留原定位方式；升级后重放不会自动改成新 epoch。

## 生命周期协议

每项生命周期变更需要 `task_id`、`expected_revision`、`request_key`、`summary`。`request_key` 在同一项目、同一成员范围唯一；重试相同 payload 和身份类型返回原结果，不重复交接。改变 payload 必须使用新 key。旧 revision 返回 HTTP 409 / MCP Conflict。原有 `claim_task` 保持原子排他接口，不需要这三项字段；首次认领另留审计事件。

| 操作 | HTTP POST（task_id 在路径） | 允许身份 | 额外字段 |
| --- | --- | --- | --- |
| release_task | /api/tasks/{id}/release-task | 任务本人或项目负责人网页；当前 owner agent | agent 需当前 session_key / ownership_epoch |
| propose_handoff | /api/tasks/{id}/propose-handoff | 同上 | target_member_id；agent 需当前 session / epoch |
| accept_handoff | /api/tasks/{id}/accept-handoff | 被提议接收方网页 | 无 |
| reject_handoff | /api/tasks/{id}/reject-handoff | 被提议接收方网页 | 无 |
| force_handoff | /api/tasks/{id}/force-handoff | 项目负责人网页 | target_member_id |
| cancel_task | /api/tasks/{id}/cancel-task | 任务本人、开放任务创建者或项目负责人网页 | 无 |
| reopen_task | /api/tasks/{id}/reopen-task | 创建者、前任负责人或项目负责人网页 | 无 |

MCP 与本地 adapter 暴露 `release_task`、`propose_handoff`、`read_task_history`；接受、拒绝、强制转交、取消和恢复不注册为 agent 工具。项目外的任务或目标不可访问；已映射账号的商业项目目标须同时保持团队和项目有效成员资格。迁入团队后仍有效的未映射 legacy 协作者延续既有成员权限，不获得负责人权限。

```text
propose_handoff(task_id=42, target_member_id="project-member-id",
  expected_revision=4, request_key="handoff-new-uuid",
  summary="feature/auth 已补齐实现，剩余失败用例见请求 #12；请继续验证",
  session_key="codex-session-new-uuid", ownership_epoch=3)
read_task_history(task_id=42, limit=20, before_id=None)
```

`read_task_history` 返回当前 `task`、待接手 `handoff`（没有时为 null）、`events` 和 `next_before_id`，下一页原样传回后者。HTTP 为 `POST /api/tasks/{id}/history`，body 包含可选的 `before_id`、`limit`（1–50）。完整单条审计为 `GET /api/tasks/{id}/history/{event_id}`，同样验证项目成员身份。

## 数据迁移、历史与边界

迁移只增加 tasks 列和新表，不重建原 tasks CHECK。数据库仍保存 open/claimed，API 根据 `cancelled_at` 投影 cancelled。`revision` 控制生命周期竞争；`ownership_epoch` 隔离责任周期；新建任务保存创建者。初始化由 Database 执行，直接使用 TaskStore、旧库重启和完整 Service 都获得相同 schema。

SQLite 使用 BEGIN IMMEDIATE：先记录完整审计上下文，再移除 progress 活动行、解除 sessions/checkpoints 的任务关联、归档并清理旧 Git refs，最后变更 owner。原组合外键继续启用。历史进度、会话关联、refs 和交付上下文在不可变审计中保留；不可变 Git observations 留在原表，审计只保留当前周期最近分支摘要，避免每次交接复制全部历史。

Git observations 的 epoch 在服务器接收时取当前任务周期，不由 agent 的 captured_at 决定。快照只让当前周期的观测进入活动工作区；历史事件明确标记 historical。同一周期内仍保留按 captured_at 选择最新观测的既有规则，避免离线旧观测覆盖新观测。GitHub ref 与缓存证据携带 epoch，快照同时核对当前 ref、任务 epoch 和服务器关联/同步时间；责任变化使在途核对失效。同一分支、PR 或 SHA 可在接手后重新关联，旧内容保留在审计历史。

默认快照至多 50 条历史概览、200 条待交接，优先当前接收成员并返回截断标记；旧关闭交接不会淹没待接手请求。按任务分页不受全项目概览范围限制。网页按项目、成员、任务和事件保留历史展开、已加载分页与完整证据，轮询恢复对应历史标题的键盘焦点；退出或切换项目清空缓存，迟到响应不可重新写入。取消任务不参与声明范围交叠提示，重新打开后恢复参与；当项目待交接超过概览上限时，详情提供按任务查询当前交接的入口。checkpoint 的待我接手摘要至多 4 项，仍受整体 16 KB UTF-8 上限约束，hook 输出仍受 9,000 字符 ASCII 上限约束。检查点不自动已读、确认、回复或解决技术请求。

本阶段不实现任务依赖或负责人消息路由；`ownership_changed` 留有同一事务内的后续扩展入口。HTTP/官方 MCP/本地队列及网页测试是本机协议与行为证据，不等于真实 Claude/Codex 原生工具已经消费 hook 上下文，也不等于公网双机协作或 GitHub App 真实安装验收。

## 验证

先观察新增行为测试失败，再实现；专项覆盖生命周期竞争、同成员双会话、旧 session/epoch、幂等 payload、权限、商业管理员/离队目标、历史分页、旧库迁移/重启、Git 证据隔离、真实 HTTP/官方 MCP 和离线队列隔离。网页 Node 回归覆盖安全 DOM、摘要草稿、版本参数、接受/拒绝权限和异步项目切换。

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_task*.py' -v
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
node tests/task_lifecycle_ui_regression.js
node tests/web_session_regression.js src/static/app.js
node tests/git_ui_regression.js
```

测试数据库与原始输出只保留在忽略的 `.local/`；不提交凭据、原生工具配置或机器原始数据。
## 本阶段独立验收记录（2026-10-11）

controller 使用 F1 运行时创建的同一 SQLite 数据库重启升级，通过真实网页执行原 owner 提出交接、目标成员接受、取消筛选和重新打开。原 local_done 清除，历史保留旧进度和分支；390px 页面与详情未出现横向溢出，取消文案明确恢复后才可认领。

同一数据库的真实 HTTP 与官方 MCP SDK 复验通过：仍在推进的 legacy 任务保持可读，释放后旧登记 session key 无法再次认领，新 session 接手并正常报告 progress / register_session / checkpoint；旧 session 的迟到 merged 上报被拒绝。原始脚本和结果在 controller 的 `.local/`，不纳入 Git。以上是协议和网页验收，不是原生 LLM 自主消费 hook 的验收。

本阶段最终全量回归为 394 项 Python 测试通过；最后的团队迁入兼容修正后，任务/HTTP/MCP 29 项及工作区身份 17 项定向回归通过。实验目录 21 项通过，六组网页脚本回归与相关脚本语法检查通过。CI 新增生命周期脚本检查；本阶段本地提交后由 controller 完成独立规格/质量审查与推送。

F2 独立审查后的两项修正先以行为测试复现失败：取消任务仍出现在范围提示，以及实际 app 轮询丢失历史展开。定向回归覆盖取消/重开、历史分页与完整证据保留、相同标题事件的 summary 焦点、分页请求跨轮询完成、成员/任务/项目隔离和清空后的迟到响应。修正后生命周期 16 项、活动 10 项 Python 定向测试，以及生命周期、网页会话和 Git UI 三组 Node 回归与脚本语法检查通过。
