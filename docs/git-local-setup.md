# 本地 Git 接入

网页仍是工作台；本地适配器只为现有 agent 提供 Git 观测与协作检查点。默认只观测：Git 命令不会修改、提交或推送代码。项目管理者在网页启用 Git 写入路径后，认领创建任务分支、交付提交并推送、打开草稿 PR；合并始终由人工确认。默认上传仓库标识、分支、完整 HEAD、已跟踪文件的变更路径与时间，不上传源码、diff 或绝对路径。

## Git 写入路径（可选，默认关闭）

项目管理者在网页仓库接入区域启用 Git 写入后，agent 才能使用写入工具：`create_task_branch` 在认领时创建 `coopagents/task-<id>-<epoch>-<slug>` 分支，`deliver_task` 提交并推送后打开草稿 PR，`check_overlap` 检查路径重叠，`request_merge` 请求人工合并。未启用时这些工具不在 MCP 发现中出现，调用也会失败。

写入有三道门：认领时工作区必须干净；交付前必须有五分钟内的新检查点；两道门都检查路径重叠——另一任务的最新观测涉及同一文件时，认领或交付被拦截，等待对方完成或由项目管理者覆写（覆写需写理由并记入审计）。提交作者来自成员身份，提交邮箱只从 `COOPAGENTS_GIT_AUTHOR_EMAIL` 环境变量读取，不写进仓库或服务数据库。禁止 force push；PR 一律以草稿打开；合并只由项目管理者在网页决策卡上执行，合并的 PR 不自动验收任务。`preview` 模式只描述将执行的命令和 API 调用，不写任何内容。doctor 的 `git_write_ready` 检查只报告就绪状态，从不启用写入。

## 一次配置

1. 在项目网页的仓库接入区域，由项目管理者绑定共同仓库。HTTPS 和 SSH 地址会规范化到同一标识。绑定后保留身份与历史；另一个仓库使用另一个项目。
2. 在各成员电脑安装包含 service 依赖的 Coopagents，保存自己的 agent 令牌到启动 agent 的环境。不要把令牌写到版本化配置；令牌决定项目和成员权限。
3. 先检查连接。下面的值均是占位符，项目 ID 可从网页接入区域取得。

```powershell
$env:COOPAGENTS_AGENT_TOKEN = '个人 agent 令牌'
python -m coopagents.git_adapter --repository 'C:\code\demo' --service 'https://coopagents.example.com' --project '项目 UUID' --inspect
```

服务地址必须由成员明确指定，只接受 HTTPS 或本机 loopback HTTP，不从仓库文件中读取。适配器拒绝重定向，避免把凭据发往不同目的地。输出只有安全元数据；origin 不匹配、项目凭据不匹配、没有 origin 都会停止采集。

4. 将本地 stdio MCP 加到当前 agent 的配置。已有 remote Coopagents MCP 可替换成这个适配器，避免两个同名工具；按工具现有方式编辑配置，保留其他 MCP 和个人规则。Codex 项目配置示例：

```toml
[mcp_servers.coopagents_git]
command = "python"
args = ["-m", "coopagents.git_adapter", "--repository", "C:/code/demo", "--service", "https://coopagents.example.com", "--project", "项目 UUID"]
env_vars = ["COOPAGENTS_AGENT_TOKEN"]
```

Python 必须指向已经安装 Coopagents 的解释器；Codex 桌面继承环境的具体行为须在实际启动方式下验证。也可用 Python 解释器绝对路径。Claude Code 使用 stdio MCP：

```powershell
claude mcp add --transport stdio --scope local coopagents_git -- python -m coopagents.git_adapter --repository 'C:\code\demo' --service 'https://coopagents.example.com' --project '项目 UUID'
```

CLI 命令与配置模板是接入方法；真实 Codex 桌面、Codex CLI、Claude Code 的运行结果分别记录，不能把 SDK 测试当作这三个入口的验收。

## 仓库内约定

可以创建不含本机设置的版本化配置：

```powershell
python -m coopagents.git_adapter --repository 'C:\code\demo' --service 'https://coopagents.example.com' --project '项目 UUID' --init-project
```

该命令先校验连接，只在不存在时新建 `.coopagents/project.json` 和 `.coopagents/rules.md`，保留现有文件，不自动修改 `AGENTS.md`、`CLAUDE.md` 或 hooks。检查内容后，将这两个公共文件提交 Git。可在现有仓库规则中引用 `.coopagents/rules.md`。`project.json` 是数据，不能授予访问权限或执行命令。

## 日常协作

让 agent 先调用 `read_team` 了解任务和约定，再认领任务。在开始工作、需要协商技术细节、准备交付时调用 `repo_checkpoint(task_id)`。该工具读取实际工作区并一次返回 Git 观测、团队上下文和收件箱；读取消息不表示已处理，处理后再确认。它也提供原有的认领、进展、问答和约定工具。

变更路径重叠表示两个最新工作区涉及同一文件，需要协商；它不是文件锁，也不能证明重复实现。观测超过五分钟显示过期，历史仍保留。已提交的干净工作区通过 HEAD 保留交付引用，不冒充正在修改文件。

检查点响应只展示最近 50 个工作区与 50 条摘要，路径按数量及字节数限制显示，包含完整数量和截断标识。重叠在所展示工作区的完整路径上计算，摘要有界；单条完整历史可通过有权限的 `GET /api/git/observations/{id}` 读取。原始历史保留服务数据库，不能因响应大小持续增长而断开接入。

断网时，待发送观测保留在本机用户数据目录 `Coopagents/git-state/` 的事务型 SQLite 队列，下次检查点重试同一个请求键。并发会话不会互相覆盖，已完成记录仍保留；队列不含令牌。移除项目访问或更换任务所有者可能使旧待发送观测被拒绝；保留文件并检查权限，勿把它提交 Git。
