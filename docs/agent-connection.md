# Agent 接入说明

正式服务使用 Streamable HTTP MCP 和成员个人 agent 令牌。网页凭据只用于网页操作，不能作为 MCP 凭据。正式本机地址为 `http://127.0.0.1:8787/mcp`；已有实验服务 `8768` 是另一套数据。

## 推荐：复制 Skill 接入指令

进入项目后点击侧栏「接入 agent」，选择 Claude Code、Codex CLI 或 Codex 桌面，点击「生成接入指令」再「复制接入指令」，交给自己的 agent。指令包含公开 Skill 地址、项目与服务地址以及本人的个人 agent 凭据。agent 按 Skill 安装公开说明、配置原生 HTTP MCP，并验证身份与协作调用；不需要安装 Crewmesh 本地客户端或 Python 包。

凭据仅在该私有弹窗中生成与展示，关闭或切换后清空，不写浏览器持久存储。生成指令不会轮换已有 agent 凭据。公开 Skill 与协议说明为 `/skills/crewmesh-connect/SKILL.md` 和相邻 `protocol.md`，不包含成员秘密；不要把私有接入指令保存到 Skill 文件或 Git。个人凭据有效 90 天，最多 32 个未过期凭据；需要统一撤销时使用现有个人令牌轮换。

当前原生会话无法热加载配置时，agent 应明确提示启动新会话。HTTP 身份验证、原生 MCP 调用和原生自动检查点是不同证据，不能互相代替。下述手动配置与 Python hook 仅为高级已有安装环境的选项，不是 Skill 接入前置条件。

## Codex

本机 `codex mcp add --help` 已确认支持 `--url` 和 `--bearer-token-env-var`。在启动 Codex CLI 的同一个 PowerShell 会话中设置环境变量，然后添加服务：

```powershell
$env:CREWMESH_AGENT_TOKEN = '在此填写自己的 agent 令牌'
codex mcp add crewmesh --url http://127.0.0.1:8787/mcp --bearer-token-env-var CREWMESH_AGENT_TOKEN
```

环境变量必须能被实际启动的 Codex 进程读取。已经启动的桌面应用不会继承另一个终端后来设置的变量。桌面用户可在 MCP 设置里配置地址与 Authorization 头；也可在受信任项目的 `.codex/config.toml` 中配置：

```toml
[mcp_servers.crewmesh]
url = "http://127.0.0.1:8787/mcp"
http_headers = { Authorization = "Bearer 在此填写自己的 agent 令牌" }
```

含令牌的文件是本机配置，不提交 Git。保存后重新启动 MCP 连接，并在新会话检查工具是否出现。配置语法依据 [官方 MCP 说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 和 [配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。本项目不会自动修改用户的 Codex 配置。

## Claude Code

本机 `claude mcp add --help` 已确认支持 HTTP、local 范围及 Authorization 头。可在项目目录执行：

```powershell
claude mcp add --transport http --scope local crewmesh http://127.0.0.1:8787/mcp --header "Authorization: Bearer 在此填写自己的 agent 令牌"
```

输入自己的令牌后重新建立连接。这是一次性接入配置，平时仍按原来的方式启动 Claude Code。令牌不放到聊天提示词或 Git 提交中。

## 协作检查点

接入后，在开始任务时让 agent 读取团队分工、认领任务并登记会话；遇到技术依赖时发送请求；推进阶段和结束前读取收件箱、明确处理并回复。读取不等于处理，回复不等于请求已解决。公共技术约定先提出版本，再由人在网页上批准。

服务提供检查点拉取能力。闲置会话不会因为一条消息自行唤醒；Claude 原生正式接入已有验收证据，Codex CLI 调用取消与原生双向闭环仍待解决，详见 [P4 原生报告](p4-native-report.md)；真实双机仍需要独立验收。网页显示的是最后同步时间及 agent 自述进展，不把它们当作实时在线状态或 Git 验证。

## 令牌轮换

在网页轮换自己的 agent 令牌后，原令牌立即失效。更新接入配置并重建 MCP 连接。新 agent 令牌有效 90 天；新网页凭据有效 30 天。网页令牌与 agent 令牌相互独立。

## 接手任务与会话隔离

认领时传新的 `session_key`；保存返回的 `ownership_epoch`，在 register_session、report_progress、带任务的 checkpoint、repo_checkpoint、link_delivery 中一并传回。网页接受交接后，新 owner 的 agent 使用 claim_task 绑定自己的新 session。旧会话不可跨责任周期复用，原生 hook 的成员级检查点继续兼容。释放、转交、重试及完整调用见 [任务交接与恢复](task-lifecycle.md)。

## 显式依赖与自动检查点

遇到任务间技术问题，先用 lookup_owner(task_id 或 scope) 查负责人；多候选必须明确选目标任务。create_dependency 建立 source → target 依赖，expected_revision 使用 source 任务版本。目标当前会话调用 reply_dependency；source 当前会话先 read_dependency，再以最新 dependency revision 和 reply_id 调用 resolve_dependency。没有负责人时明确排队，转交后生成新请求，旧回复不会解除新路由。详细 HTTP/MCP 参数、网页流程和权限见 [任务依赖](dependencies.md)。

checkpoint(session_key,tool,event) 可在 startup / blocker / completion / manual 阶段读取有界任务、消息、约定、交接及依赖摘要。成员级检查点不要求绑定某个任务；带 task_id 时遵守该任务执行会话与 ownership_epoch。网页“仓库接入”提供接入诊断，配置片段使用可信环境变量并保留已有配置；失败明确提示而不阻止开发。检查点不算依赖回复已读，闲置会话不自动唤醒。

F1 实际原生验收：Claude 客户端收到了 773 字符上下文并记录开始/提示事件，模型未报告验收标记；Codex exec 正常退出但没观察到 hook。原生自动消费仍未通过，桌面 hook 未额外验收。详见 [协作闭环报告](collaboration-flow-report.md)。
