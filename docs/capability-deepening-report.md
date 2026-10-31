# 0.9.1–0.9.3 能力深化记录

日期：2026-10-30。代码阶段在 `codex/pre-0-9-abilities` 实现并分别提交；此文只记录本次代码与自动化验证，不把本机测试作为跨设备或真实 Harness 验收。

## 0.9.1 共享上下文

`read_context` 提供共同服务、HTTP、MCP 和本地 Git adapter 的只读上下文入口；快照包含 `shared_context`。来源、作用域、观测时间、新鲜度和共享结构化隐私边界明确，不创建消息已读回执。查询覆盖约定的生效/待确认版本、依赖、明确分享的资产、请求和回复、协作活动以及 Git 交付引用。支持任务、成员、声明范围、分支、交付对象、来源、文本、更新时间与引用标识过滤，并提供 offset/next_offset 分页。托管工作台和本机只读看板共用查询组件；上游数据被截断时明确返回 source_truncated。引用可放入已有共享技术请求，不额外规定团队流程。

## 0.9.2 成员与 Harness 能力发现

旧 session 表及返回形状保留；五种新增 Harness 会话保存在加法迁移表，并与旧会话合并查询。多 agent、版本、平台、仓库、分支、任务和登记时间可见。能力矩阵包含七种目标 Harness；配置适配能力、agent 自报和项目成员确认的具体版本/平台证据分别保存。未知组合不外推，凭据撤销显示不可用，登记和验证证据按各自期限标为陈旧。成员验证通过 `record_capability` 项目管理操作记录，agent MCP 不暴露此操作。最近出现只依据匹配 member/session/tool 的检查点；连接、事件送达与模型处理缺少回执时分别为 unknown，不从登记或消息路由推断。旧调用刷新登记时保留省略的工具版本、平台和自报能力。

## 0.9.3 交付关联

`read_deliveries` / `GET /api/deliveries` 将现有 branch、commit、PR、Release 关系与本地 Git 观测组织为多对多对象，并支持任务反查。未同步的明确关联也可见，建立者、来源、状态同步和陈旧/不可用状态分别展示。Agent 使用 `suggest_delivery` 提出候选；项目管理成员通过 `decide_delivery` 确认或拒绝。确认与现有 GitHub 关联写入同一事务；ownership epoch 改变后的建议不能确认。所有操作均不自动关闭或验收任务。

托管工作台与本机只读看板复用交付展示组件；托管工作台提供建议确认。项目活动添加结构化交付关联事件，保留来源和新鲜度。

阶段验证：交付追溯、GitHub Sync、本地 Git adapter、Git HTTP 与项目活动共 40 项 Python 回归通过；交付组件、既有 Git UI、任务看板、网页会话与本机看板会话回归通过。新增 HTTP/MCP 用例验证 agent 提议、查询与网页管理者决策边界。

## 验证环境

最初基线在全局 Python 3.13 的 user-site 可编辑安装下运行：620 通过、7 失败、1 跳过。失败涉及隔离子进程无法访问 user-site，以及继承 Codex 运行环境导致 Claude 安装测试的预期错误顺序不同。专用虚拟环境复验已消除安装问题；两个唤醒测试改用既有 wake_cli helper 的中性子进程身份环境，保留实际产品的调用者身份检查。最终 Windows / Python 3.13 完整回归：**649 通过、1 跳过**；**27 条 JavaScript CI 命令全部通过**。Python 编译与 git diff --check 通过。原生接入实验回归 21 项通过；wheel 构建通过，并核对六个新增模块/网页资源均包含在包内。最终独立复查补充的跨工具同 session key 回归已完成红绿验证；该修正后能力发现 9 项回归通过。既有 P2P 测试仍产生一次 RecvStream.stop 协程未等待警告；本阶段未更改 P2P 实现。独立代码审查指出的登记/出现/送达/处理状态区分已修复，并增加回归。所有测试证据保留在忽略的 `.local/`；不提交凭据或原始会话内容。


## 使用入口与边界

- 读取共享上下文：`GET /api/context` 或 MCP `read_context`；可选 `task_id`、`member_id`、`scope`、`branch`、`delivery_kind`、`delivery_value`、`source`、`query`、`reference`、`after`、`offset`、`limit`。`after` 是带时区的 ISO 时间，返回发生在其后的记录；默认每页 50、最多 100。分页反映当前共享状态，项目变化时可重新查询第一页。
- 发现成员与能力：`GET /api/capabilities` 或 MCP `read_capabilities`。`register_session` 新增可选 `harness`、`harness_version`、`platform`、`capabilities`；允许真实工具名 `claude-code`、`codex-cli`、`codex-desktop`、`cursor`、`opencode`、`pi`、`kimi-code`、`zcode`。自报能力放在 `reported_capabilities`，不会成为已验证支持。
- 记录验证证据：网页管理凭据通过 `POST /api/operations/record_capability`，字段为 `harness`、字符串 `version`、`platform`（windows/macos/linux）、`capability`、`status`、`evidence` 和可选 `constraints`。版本/平台必须具体。证据按项目保存，不扩大到其他版本或平台。成员上传证据由成员负责，产品不会把它说成平台自动完成了真实验收。
- 查交付与反查任务：`GET /api/deliveries?kind=pr&value=7` 或 `read_deliveries(kind="pr", value="7")`；可单独按 `task_id` 或 `kind` 查询。`kind` 为 branch/commit/pr/release，明确关联与观测各自保留建立者和时间。引用身份与状态同步分别记录。
- 提交建议：`suggest_delivery(task_id, request_key, evidence, branch/pr_number/commit_sha/release_id)` 一次指定一个对象；绑定执行会话的任务照常提供 `session_key` 和 `ownership_epoch`。建议不是 GitHub 事实。
- 审核建议：项目管理成员通过 `POST /api/operations/decide_delivery`，传 `suggestion_id` 和 `decision`（confirmed/rejected）。确认复用原有 GitHub 授权与显式关联；仓库未授权时不会半成功。网页管理调用通用操作端点需要同源 `Origin`。
- 本机只读看板通过受限 `GET /board/context` 查询，使用看板会话凭据；不接收管理操作或主机 agent 凭据，也不会为主机创建消息阅读回执。

登记新鲜度为 15 分钟、本地 Git 为 5 分钟、GitHub 状态为 15 分钟，成员验证证据 30 天后标记过期；这些时间只决定展示语义。跨电脑、七种 Harness 实际闭环、真实 GitHub App 和多平台验收仍依照 [1.0 发布就绪计划](release-1.0-plan.md)执行。本轮不修改发行版本号或对外发布支持声明。
