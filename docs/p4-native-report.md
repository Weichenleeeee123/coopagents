# P4 原生 CLI 验收报告

2026-10-10 最新重跑结果：**Claude 原生接入通过，Codex 仍受阻，双向闭环未通过**。本报告没有把 CLI 的成功退出或自然语言声明当作业务成功证据。首次失败证据保留如下，最新重跑详情见最后一节。

验收运行标识：`bf68f525-f549-4b5c-a390-e2a001dfb0e8`。原始证据保留在忽略目录 `.local/P4/<运行标识>/`，不提交令牌、机器配置、原始会话或数据库。

## 首次运行环境与边界

- Claude Code 原生可执行文件：`2.1.282`。
- Codex CLI 原生可执行文件：`0.146.0`。
- 独立启动正式 `crewmesh.server`，绑定随机 loopback 端口；独立 SQLite 数据库，不使用实验 probe 服务。
- 通过正式 HTTP 创建 owner、邀请、第二位成员及两个任务。原生 agent 操作没有由 harness 代写。
- 从同一 Git 仓库克隆两个独立目录，真实检出不同 `p4/claude-<运行标识>`、`p4/codex-<运行标识>` 分支。
- 每次 CLI 最多 120 秒。此次 Claude 运行 5.9 秒，Codex 运行 38.3 秒，均未超时。
- 没有修改用户全局配置、目录信任、组织策略或 `CODEX_HOME`，没有删除文件。

## 观察到的阻碍

Claude 退出码 `1`，首次模型请求返回 HTTP `403`，错误码 `oauth_not_allowed_for_organization`。原始错误说明组织已禁用 Claude Code 的订阅访问，需要组织管理员启用，或使用组织允许的 Anthropic API 凭据。本次未更换认证来源或绕过策略。

Codex 退出码 `0`，但首个 Crewmesh MCP `whoami` 调用的结构化结果为：

```json
{"type":"mcp_tool_call","server":"crewmesh","tool":"whoami","status":"failed","error":{"message":"user cancelled MCP tool call"}}
```

随后 Codex 明确停止，没有执行后续动作。此条证据只证明原生调用被取消，不能据此断言具体审批配置或人工取消来源。stderr 另有模型缓存缺少 `base_instructions`、PowerShell shell snapshot 不支持的警告；这两条不是业务验收成功证据，也没有证明为取消的原因。

## 数据库与网页快照证据

观察者使用 SQLite `mode=ro` 与 `PRAGMA query_only=ON` 读取正式数据库，并获取 owner 的 `/api/snapshot`。观察者从未调用 `read_inbox`，因此没有替 agent 写入 `read_at`。

| 正式记录 | 数量 | 意义 |
|---|---:|---|
| tasks | 2 | HTTP bootstrap 创建，均未由 agent 认领 |
| sessions | 0 | 没有原生会话登记 |
| progress | 0 | 没有 agent 进度报告 |
| message_requests | 0 | Claude 未发出虚构 schema 请求 |
| message_deliveries | 0 | 没有投递 |
| message_receipts | 0 | 没有读取或处理回执 |
| message_replies | 0 | Codex 未回复 |

两个真实 Git 分支的验证通过；请求、读取、acknowledge、回复、resolve、任务认领、会话登记与进度报告均未通过。闭环没有发生，P4 尚不能作为部署验收通过项。

## 可复现入口

在仓库根目录使用已有虚拟环境：

```powershell
& .\.venv\Scripts\python.exe experiments/agent-integration/p4_native_check.py --timeout 120
```

可通过 `--claude-exe`、`--codex-exe` 指定已安装的原生可执行文件。每次运行新建 UUID 证据目录、随机端口、独立数据库与两个分支，保留所有文件。Claude 保留默认用户设置来源，通过严格 MCP 配置及精确 MCP allowed-tools 限制执行；Codex 使用 `--ignore-user-config`、只读 sandbox、单次 MCP 配置及环境中的 agent token，继续使用现有认证目录。

CLI stdout JSONL、stderr、版本输出、服务日志、只读 audit、网页 snapshot 与脱敏结果均保留。令牌只进入子进程环境或忽略目录配置/凭据文件。`redacted-result.json` 是首次运行生成的结果；它的 Codex diagnostics 仅含 stderr，取消证据来自保留的 `codex-repo/codex-reply.stdout.jsonl`。后续 harness 已增加结构化 MCP 失败提取。

此 harness 已通过 Python 语法编译检查，实际运行完成，并核对最终正式数据库及网页 snapshot。解除上述认证/原生调用阻碍后，应重新执行同一入口；不应补写 agent 记录使本次结果变成通过。本次仅验证同一台机器上的两个独立工作目录，不证明物理双机协作，也不证明 idle wakeup；正式 MCP 仍通过任务检查点拉取消息。

## 用户更新认证后的实际重跑

用户说明 Claude CLI 现在应当可用后，原样运行同一入口。新的运行标识为 `6af60b5e-da2b-45e2-a3ca-47bfbac28965`，证据保留于 `.local/P4/<新运行标识>/`。原先运行目录及本节之前的观察未删除。两个原生 CLI 的版本保持一致；没有修改设置来源、审批策略、信任配置、认证目录或全局配置。

Claude 退出码 `0`，14.5 秒，无超时。结构化日志包含真实的 `whoami`、`claim_task`、`register_session`、`report_progress`、`send_request` 调用。正式数据库确认 Claude member 认领任务、登记 `claude-code` 会话、报告 `working` 进度，并发出正文为 `Fictional schema v1: should invoice.preview_color be a string?` 的请求。stderr 提示既有 API key 或另一认证来源优先于 Claude 登录；harness 继承现有环境，没有读取、输出或更换该凭据。

Codex 退出码 `0`，78.7 秒，无超时，但首次 `whoami` 再次返回 `user cancelled MCP tool call`，随后停止。stderr 此次还记录了模型目录刷新超时、推荐插件目录网络失败、模型 websocket 的 `tls handshake eof` 及内置重试。最终 CLI 已产生 agent 消息并尝试 MCP，不能将网络诊断直接当作此次取消的已证实原因。

对已安装 CLI 的 `exec --help`、主命令帮助、`mcp --help` 和 `doctor --help` 做了只读检查。`--sandbox` 的帮助明确描述它控制模型生成的 shell 命令执行策略；这些帮助没有证明 MCP 取消来自只读 sandbox。没有使用跳过审批、跳过 hooks 信任、忽略 rules 或关闭 sandbox 的参数，也没有为消除取消而放宽策略。

| 最新正式记录 | 数量 | 数据库与网页 snapshot 观察 |
|---|---:|---|
| members | 2 | owner 与邀请加入的成员 |
| tasks | 2 | Claude 认领一个，Codex 的任务未认领 |
| sessions | 1 | Claude 原生会话、实际 Claude 分支 |
| progress | 1 | Claude 报告 working |
| message_requests | 1 | Claude 原生发出虚构 schema 请求 |
| message_deliveries | 1 | 投递给 Codex member |
| message_receipts | 0 | Codex 未读取/acknowledge |
| message_replies | 0 | 没有 Codex 回复 |

请求 `resolved_at` 为空，未运行 Claude resolve 阶段。最新只读 audit 与 `/api/snapshot` 的任务、会话、进度、消息数量相符，观察者仍没有调用 `read_inbox`。因此 Claude 单向原生接入已有正式证据，Codex 原生接入和完整闭环仍未通过。

此轮在保存 `final.audit.json`、`web-snapshot.json`、`redacted-result.json` 后，harness 最后的终端打印遇到 Windows GBK 无法编码 stderr 警告符号的 `UnicodeEncodeError`；证据已完整写入 UTF-8 文件，服务已由 `finally` 停止。harness 已将终端 JSON 改为 ASCII 转义并通过语法检查。此输出修正没有触发另一轮原生运行，也不改变上述业务结论。
