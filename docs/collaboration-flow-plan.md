# 协作闭环分阶段实施计划

> 执行：使用 subagent-driven-development，逐阶段实现、规格审查和代码审查。用户已批准此前提出的前三项功能并要求提交、推送。禁止删除文件；源码在 src/，文档在 docs/，凭据和原始证据仅存忽略的 .local/。

**目标：** 保持 Claude Code / Codex 与网页使用方式，让同步自动发生、任务能交接恢复、依赖能找到负责人。

**架构：** 在现有身份、SQLite、HTTP/MCP 与原生网页上增量扩展。检查点模块记录真实入口证据；任务生命周期用版本条件与审计事件防止竞争；显式依赖复用技术请求与解决确认。所有跨项目访问继续由个人凭据约束，hook 不改变工具权限或替人批准公共约定。

**技术：** Python 3.11+、SQLite、Starlette、MCP SDK、原生 JavaScript、Claude/Codex command hooks。

## 当前依据与边界

基线 46fdf61 已合入 Git 集成。第六项功能已实现：本地 Git 观测、GitHub App 授权/签名事件/补偿同步、当前 HEAD 的 PR 与检查证据、看板来源与新鲜度。真实 App 安装及公网部署验收仍需外部配置。本轮不替代那些验收。

主工作区有未提交发行配置，隔离工作区为 .local/worktrees/collaboration-flow，分支 feat/collaboration-flow。不复制、暂存或覆盖主工作区未提交改动。通过 Git 合入同期已提交主线，再推送功能分支和 PR。

## F1 接入诊断与自动检查点

- [x] 新增 src/checkpoints.py：agent-only checkpoint(session_key, tool, event, task_id=None)，会话开始、提示提交、工具后及手动阶段合法枚举。返回当前成员任务、相关待处理请求/回复、已批准约定、后续阶段的交接与依赖摘要；记录服务端收到时间。返回消息只作为不可信协作数据，不自动确认处理、回复或解决。
- [x] 新增独立诊断发送/回读记录（随机 challenge，绑定成员与项目，有限输入）；检测凭据、项目匹配和确实回读，不能拿网页轮询或本地配置存在声称 agent 已接入。快照提供成员/会话最后检查点及诊断状态。超过五分钟明确陈旧。
- [x] src/checkpoint_hook.py 使用明确的环境变量 CREWMESH_SERVICE_URL、CREWMESH_PROJECT_ID、CREWMESH_AGENT_TOKEN；从 stdin 只提取事件/session_id，不上传 prompt、transcript 或工具正文。固定可信 origin、禁止跳转、限时、限体积，失败返回简明可见警告而不阻止工作；工具后检查节流，开始/新提示强制刷新。输出兼容两客户端的 hookSpecificOutput.additionalContext，外部内容清楚包裹为数据并限制长度；不返回 allow/deny，不自动解决请求。
- [x] 提供配置预览与 doctor 命令，Claude 的 settings.local.json 与 Codex 的 hooks.json 只提供可合并片段/新文件导出，保留既有配置和信任。SessionStart/UserPromptSubmit/PostToolUse 触发；缺少支持或信任时显示尚未观察到 hook，保留 MCP 手动检查点。官方来源：https://code.claude.com/docs/en/hooks 与 https://learn.chatgpt.com/docs/hooks（2026-10-11）。
- [x] HTTP/MCP、本地 Git 适配器接入新检查点；网页增加接入向导、诊断与会话检查点状态。使用新模块 src/static/collaboration.js，避免继续向 app.js 塞入整套业务逻辑；轻量桥接生命周期、详情和总览。
- [x] tests/test_checkpoints.py、test_checkpoint_hook.py、test_collaboration_http.py 和网页回归：真实 HTTP 诊断、错误项目/令牌、轮换、隔离、hook subprocess 输入输出、节流/断网、隐私、消息不自动确认、旧数据库升级。先验证新行为失败，再实现、回归、提交。

F1 已完成实现及独立审查；已推送 83958e1，CI 38128638038 通过。原生模型实际消费 hook 上下文仍未承诺。

## F2 任务交接、释放、取消与恢复

- [x] 新增 src/task_lifecycle.py 与增量 schema，保留原 tasks 的兼容行为。网页本人/项目负责人可释放、转交、取消、重新打开；agent 可释放自己的任务和提出交接，不可自行给其他成员强加所有权。交接请求由目标成员通过网页接受，或项目负责人明确执行转交。每次变更带 expected_revision、request_key 和交接摘要，幂等重试，旧版本冲突可见。
- [x] 原任务认领仍保持原子独占；新增可选 session_key 标识实际负责会话。已关联任务的其他会话不能报告冒充当前执行会话；旧客户端无 session_key 只对没有会话独占的新/旧任务保留兼容。释放/交接后旧会话失效，重新接手可读取分支、最新进度、未解决请求、约定和交接记录。
- [x] 处理现有 sessions/progress 对 owner 的组合外键：在同一事务保存旧进度/关联审计再更新或解除活动投影，不能损失历史。取消状态不能被认领或继续上报；重新打开回到待认领，不沿用前任进度自动显示完成。保留 Git 证据历史但只有本次责任周期证据能驱动当前看板。
- [x] 网页卡片/详情支持生命周期操作、交接摘要、接受/拒绝和历史；会话展示实际负责人；已取消任务可单独查看/重新打开。快照和检查点返回待我接受的交接。
- [x] tests/test_task_lifecycle.py + HTTP/MCP + 网页：竞争交接/认领、跨项目与权限、同成员双会话、幂等/过期版本、已有进度和仓库证据任务转移、旧数据库迁移/重启保留。阶段通过后提交。

F2 实际协议、兼容边界与验证见 [任务交接与恢复](task-lifecycle.md)。实现包含独立网页模块、任务历史分页、session + epoch 隔离和 Git 历史归档；6f7c635 / 733863b 已由 controller 独立规格/质量审查通过并推送，阶段 CI 38130103147 成功。

## F3 显式依赖与负责人路由

- [x] 新增 src/dependencies.py：任务依赖任务，记录需要什么与请求上下文；禁止自身和跨项目依赖，拒绝循环并返回可理解的冲突。创建时复用 durable 技术请求，接收方由被依赖任务当前负责人解析；无负责人明确待分派。
- [x] 支持按任务或声明模块范围查找负责人。范围按路径段匹配，返回证据；多个候选时返回歧义而非随意选人。由网页或 agent 明确选目标任务；不引入语义猜测或后台执行任意任务。
- [x] 负责人交接后依赖可继续找到当前负责人；旧消息与已读回执保留，通过新的关联请求转达而非改写旧消息身份。依赖要求发起方在读到回复后明确确认满足，消息已读、PR 合并和 agent 自述完成不能自动解除依赖。可有权限撤销依赖并记录原因。受阻投影保留人工/agent 其他阻塞，避免错误恢复。
- [x] 网页详情显示“我在等谁/谁在等我”、回答与确认入口、无负责人/歧义提示；总览统一“需要我处理”汇总请求、交接、待分派依赖和公共约定确认。MCP/本地适配器暴露查负责人、建立与完成依赖，检查点返回相关上下文。
- [x] tests/test_dependencies.py、真实 HTTP/官方 MCP 验收与网页：双成员后端/前端交换接口问题、答复、确认后继续；无负责人后认领、负责人转交、循环、取消、重试/并发、跨项目隔离、重启。记录 SDK 与真实原生工具测试的不同证据，不混报。
- [x] 更新 docs/agent-connection.md、docs/roadmap.md、docs/README.md 与 docs/collaboration-flow-report.md。
- [x] controller 独立规格/质量审查；合入主线，412 项 Python、21 项实验、七组网页回归及发行构建通过；阶段提交 a0bf495 / c5d7099 已推送。
- [x] PR #2 与最终 GitHub CI 链接已记录在验证报告；执行结果以 PR Checks 为准。

## 验收命令与证据

隔离工作区 .venv 独立安装，不改变主工作区 Python 映射。各阶段先运行新增的 unittest 文件，确认未实现时失败；完成后运行领域/HTTP/MCP受影响测试与 Node 回归。最终：

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
& ./.venv/Scripts/python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
node tests/web_session_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
node tests/git_ui_regression.js
node tests/collaboration_ui_regression.js
node tests/task_lifecycle_ui_regression.js
node tests/dependencies_ui_regression.js
git diff --check
```

外部原生 hook 信任、模型账号或公网配置不足时，完成可执行接入包和真实本地协议验收，记录具体未通过项，不能声称原生自主闭环已通过。
