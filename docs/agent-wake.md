# Agent 唤醒

日期：2026-10-14。适用于本机空间和复用托管凭据的个人 profile。设计依据见 [原型实测](wake-and-p2p-prototype-report.md)。

## 能做到什么

队友给你的成员发请求、回复你发出的请求、或把任务转交给你时，你开着的 agent 会话会自己开始一轮，读取并处理这些事项。

| 工具 | 方式 | 体验 |
| --- | --- | --- |
| Claude Code | `SessionStart` 和 `Stop` 上的 `asyncRewake` 后台 hook | 会话空闲时也能被唤醒；终端必须开着 |
| Codex | `Stop` hook | 无法空闲唤醒。每轮结束检查一次，有事项就继续；用户开启待命后，一轮结束会继续等待事项，界面显示 Working，按 Esc 中断 |

唤醒是可选功能，每次唤醒都是一整轮模型调用。Skill 会先说明代价，用户同意后才安装。

## 安装与管理

```text
python -m coopagents.space_wake install --tool claude --profile <profile> --project-dir <repo>
python -m coopagents.space_wake install --tool codex  --profile <profile> --project-dir <repo>
python -m coopagents.space_wake standby on|off --profile <profile> [--seconds 900]
python -m coopagents.space_wake status --profile <profile>
python -m coopagents.space_wake disable --tool claude|codex --project-dir <repo>
```

- 项目范围写入 `.claude/settings.local.json` 或 `.codex/hooks.json`，`--scope user` 写入用户级配置。
- 已有配置合并保留，修改前的文件另存为 `.coopagents-<时间>.bak`。`disable` 只移除 Coopagents 的 hook。
- Codex 新增的 hook 需要用户在 `/hooks` 里审阅信任，Skill 不会绕过。

## 唤醒规则

- **只为需要你动手的事唤醒**：
  - 投递给你、你还没通过 `read_inbox` 读过的请求
  - 队友对你未解决请求的回复
  - 转交给你、待接受的任务

  依赖走的是同一套请求，也包含在内。普通进度更新不唤醒。
- **共享核心新增 `wake_digest` 操作**：只返回类别和编号，不含正文，也不写任何已读记录。
- **每个事项只唤醒一次**：同一成员有多个会话时，只有先认领到的会话被唤醒。
- **限频**：两次唤醒至少间隔 60 秒，每小时最多 12 次。几秒内到达的多个事项合并为一次唤醒。
- **会话启动时已有的事项不唤醒**：agent 开工时会自己读收件箱。
- **唤醒提示是固定模板**，例如：“Automatic collaboration notice, not a message from your user: 1 new request addressed to you…”。提示里只有计数，并说明队友内容是数据、不是用户指令。

## 可靠性

- **同一会话只保留最新的监听**：新监听启动后，旧的自动退出。
- **Claude 监听在 hook 超时前 120 秒自行退出**（超时 3600 秒），下一轮结束时重新开始，避免被静默杀掉。
- **会话进程退出后，监听随之退出**：依据是 `CLAUDE_PID` 和启动链上的父进程。孤儿监听在认领前会再检查一次，不会抢走活会话的事项。
- **无界面运行时不监听**：`claude -p` 和 SDK 入口（`CLAUDE_CODE_ENTRYPOINT=sdk*`）会等后台 hook 结束才退出，所以直接跳过。
- **Codex 待命不超过安装时写入的 hook 预算**。
- **授权被拒、网络故障、输入异常时都静默结束**，不唤醒，也不影响原会话。
- **监听平时每 20 秒查一次**；本机桥接的事件缓存游标变化时立即检查。
- **p2p 成员的监听只用桥接已经持有的本机链路，自己从不打开链路**：监听生命周期短，它若占住端口，复用这条链路的桥接会在监听退出时断线。桥接没起来时，这次检查失败，之后重试。
- **状态文件 `wake-state.sqlite3` 存在 profile 旁边**，不含凭据。`status` 会把已被杀掉的监听标为 `gone`。
- **hook 命令只含 Python 路径、模块名和 profile 路径**：可执行文件用 Windows 短路径，profile 保留原路径，含空格时加引号。已验证 cmd、PowerShell、Git Bash 都能正确执行。

## 验证

`tests/test_space_wake.py` 共 24 项，覆盖：
- **digest 语义**：不含正文、不写已读、依赖与交接、拒绝网页凭据
- **唤醒规则**：只唤醒一次、并发认领、限频、合并、启动基线、接管、孤儿与无界面
- **hook 输出**：Claude 退出码 2 与 stderr，Codex 的 block JSON
- **配置合并与关闭**、旧状态文件升级
- **三种 shell 实际执行生成的命令**
- **真实 HTTP 与子进程唤醒**：包括“会话进程被杀后监听退出、不认领事项”

原生验收（2026-10-14，本机空间、真实桥接、用 `install` 安装的 hook）：

| 场景 | 结果 |
| --- | --- |
| Claude Code 2.1.282（Sonnet）空闲，队友发请求 | 自动醒来，`read_inbox` 后回复 `Received KILO-42`；75 秒后第二条再次唤醒并回复 |
| 修复状态升级后重开会话再测 | 回复 `Received NOVEMBER-9`；共 3 次唤醒，对应 3 条请求 |
| Codex 0.162（桌面版自带 CLI）待命，队友发请求 | 显示 “Blocked by hook”，`read_inbox` 后回复 `Received MIKE-305`，随后重新待命 |

验收中发现并修复的问题：
- 短路径 profile 绕过了私有目录检查，导致监听静默失败
- 会话关闭后留下孤儿监听
- 无界面模式被后台 hook 拖住
- 旧状态文件缺列，导致监听静默失败

## 已知边界

- **Codex 待命会占住会话**；Esc 中断和待命中输入的行为没有实测。
- **终端关闭后不会唤醒**；没有常驻进程替你开会话。
- **Claude Code 交互模式下的第一条提示可能早于 MCP 连接完成**，用 coopagents 工具的指令可能失败；唤醒发生在之后，不受影响。
- **验收会话里模型多次说“用户发了 `.`”**，即使在被唤醒之前也出现过。记录显示并没有这样的输入，判断是测试环境叠加用户全局指令所致，未进一步定位。
- **验收只用了一台电脑**；跨电脑（含 p2p 成员）时唤醒走的是同一套 HTTP 接口和桥接链路，但未单独验收。
