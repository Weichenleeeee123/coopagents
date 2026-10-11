# 任务依赖与负责人路由

依赖表达“任务 A 需要任务 B 提供什么”。它复用持久化技术请求，并跟随双方任务当前负责人。查找仅依据已声明的任务与范围；不根据模型猜测谁负责。

## 网页流程

在任务详情的“任务依赖”查看“我在等谁 / 谁在等我”。当前责任人、项目管理员或未认领任务的创建者可添加依赖、填写所需内容及上下文；任务可在规划阶段尚未认领。直接明确选择目标任务，或按声明范围查找。多个范围匹配会显示歧义，仍须明确选定一个任务。

双方任务都有负责人时，问题发送给目标任务当前负责人。目标负责人可从网页明确以人身份答复，或让执行会话通过 agent 工具答复。网页与 agent 的身份来源单独保留。

等待方的当前负责人先点击“查看最新回复与记录”，再填写说明并点击“确认依赖已满足”。普通快照、检查点、消息已读/已处理、PR 合并、agent 的 local_done 均不能代替这两个动作。新回复或负责人变化会使此前阅读证据失效。网页和 agent 各自记录阅读证据；网页看过不代表 agent 看过。

任务看板将有活动依赖且已认领的任务分入阻塞列；这只是派生投影，不改写 agent 上报的进度。确认满足只移除该依赖的阻塞；agent 自己报告的其他 blocked 原因仍会保留。未认领任务仍在待认领列，同时显示等待内容。

团队现场“需要我处理”汇总当前依赖答复/确认、相关普通技术请求、交接请求、待分派依赖以及公共约定审核。历史依赖路由保留在技术请求与依赖记录中，不混入当前待办。

## HTTP / MCP / 本地适配器

MCP 和 Git 本地适配器使用下表工具名；HTTP 使用个人网页或 agent bearer 凭据。身份由令牌解析，不接受自报 sender 或 receiver。

| 工具 | HTTP POST | 核心参数 |
| --- | --- | --- |
| lookup_owner | /api/owners/lookup | task_id 或 scope，二选一 |
| create_dependency | /api/dependencies | source_task_id、target_task_id、need、expected_revision、request_key；context 可选 |
| read_dependency | /api/dependencies/{dependency_id}/read | dependency_id 在 URL；agent 阅读自己负责的 source 回复时传执行凭据 |
| reply_dependency | /api/dependencies/{dependency_id}/reply | expected_revision、request_key、body；evidence 可选 |
| resolve_dependency | /api/dependencies/{dependency_id}/resolve | expected_revision、reply_id、request_key、summary |
| cancel_dependency | /api/dependencies/{dependency_id}/cancel | expected_revision、request_key、summary |

MCP 调用需将 URL 中的 dependency_id 作为参数传入。`GET /api/dependencies` 和项目快照的 `dependencies` 为无副作用读取。

创建时 `expected_revision` 是 **source task 的 revision**；答复、确认、撤销时是 **dependency 的 revision**。写操作的 request_key 同一成员内不得复用于不同操作或内容；相同载荷重试返回首次结果。重试结果可能是历史版本，继续操作前刷新。

Agent 创建/撤销/确认依赖须是 source 的当前执行会话；答复须是 target 的当前执行会话，携带 `session_key` 与 `ownership_epoch`。F2 的旧客户端兼容范围仍适用。网页管理员能规划和撤销依赖，不能冒充当前 target 答复或代替当前 source 确认满足。任何同项目成员可以查看记录；只有 source 当前负责人明确读取最新回复，才生成可用于确认的证据。

返回值包括：

- `id`、`revision`、`route_version`、`source_task_id`、`target_task_id`、`need`、`context`。
- `status`：active / satisfied / cancelled；`blocked` 表示依赖是否仍活动。
- `routing_state`：waiting_source（source 待认领）、unassigned（target 待认领）、target_cancelled（target 已取消）、routed（已发送当前负责人）。
- `source` / `target`：任务标题、范围、当前负责人和取消信息。
- `current_request_id`、`latest_reply`；回复含原始 author_member_id 和 actor_kind（web / agent）。
- read_dependency 另返回 `read_recorded`、路由记录与最近 100 条审计事件；当前 source 阅读最新回复会产生明确阅读证据，其他查看不产生可确认凭据。

`lookup_owner` 返回 status（owned / unassigned / ambiguous / not_found）和全部候选及 evidence。scope 将反斜线规范为斜线，按完整路径段判断相同或上下级范围，不做 glob 或语义推断；排除已取消任务。

## 责任更替、取消和历史

SQLite 写事务使用 BEGIN IMMEDIATE：建立依赖、查环、投递消息、版本与审计一同提交。拒绝自己依赖自己、跨项目、重复活动边和活动图循环；循环错误列出任务编号路径，并发建立相反依赖只有一个成功。

任务认领/释放/转交/取消/恢复会在同一任务事务内重新计算活动依赖路由。source 或 target 换人后生成全新的技术请求；source 新 owner 是新请求的 sender。旧 request、reply、receipt 及原 sender/receiver 保留，旧回复不能完成新路由。暂无负责人时明确排队，不指定猜测收件人。

取消 source 会在同一事务撤销它的全部活动出边，记录取消者和原因；重新打开 source 不自动复活这些依赖。取消 target 则保留阻塞，显示 target_cancelled；target 恢复并重新认领后生成新路由。source owner 或项目管理员也可填写原因撤销单条依赖。

普通 `reply`、`assign`、`resolve_request` 禁止操作依赖关联消息（包括历史路由），返回冲突并指向专用依赖操作。这样不会绕过执行会话、最新回复或明确阅读检查。普通 read_inbox / acknowledge 仍保留原消息回执语义，不能确认依赖满足。

请求快照的 `dependency_id` 和 `dependency_route_state`（current / historical / closed）解释其当前用途。检查点只返回活动依赖摘要、当前消息及任务；外部正文始终视为不可信数据，原有 16 KB UTF-8 brief 和 9000 ASCII 字符原生 hook 上限保持不变。
