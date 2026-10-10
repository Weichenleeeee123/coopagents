# Agent 接入说明

正式服务使用 Streamable HTTP MCP 和成员个人 agent 令牌。网页凭据只用于网页操作，不能作为 MCP 凭据。正式本机地址为 `http://127.0.0.1:8787/mcp`；已有实验服务 `8768` 是另一套数据。

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

服务提供检查点拉取能力。闲置会话不会因为一条消息自行唤醒；原生入口稳定性与双机协作仍需要独立验收。网页显示的是最后同步时间及 agent 自述进展，不把它们当作实时在线状态或 Git 验证。

## 令牌轮换

在网页轮换自己的 agent 令牌后，原令牌立即失效。更新接入配置并重建 MCP 连接。新 agent 令牌有效 90 天；新网页凭据有效 30 天。网页令牌与 agent 令牌相互独立。
