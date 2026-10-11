# 自动协作检查点与接入诊断

F1 在服务收到个人 agent 的调用时记录协作检查点，并返回当前成员的任务、相关待解决请求及回复、已批准约定的有限摘要。网页把项目读取、真实诊断、入口报告的 hook 检查点分别显示。检查点不是在线状态，也不能单独证明模型已经消费上下文。

## 一次接入

在已安装 Crewmesh 的 Python 环境内，设置启动原生 agent 时会继承的三个环境变量。使用个人 **agent** 令牌；网页令牌不能调用检查点或诊断。

```powershell
$env:CREWMESH_SERVICE_URL = 'http://127.0.0.1:8787'
$env:CREWMESH_PROJECT_ID = 'YOUR_PROJECT_ID'
$env:CREWMESH_AGENT_TOKEN = 'YOUR_PERSONAL_AGENT_TOKEN'
python -m crewmesh.checkpoint_hook --tool codex-cli --config-preview
python -m crewmesh.checkpoint_hook --tool codex-cli --doctor
```

`--tool` 支持 `claude-code`、`codex-cli`、`codex-desktop`。每种模板都有 `SessionStart`、`UserPromptSubmit`、`PostToolUse` 三个 command hook。模板使用生成时的 `sys.executable`；Python `-I` 避免工作目录中的同名模块覆盖已安装入口。Windows 使用带正确单引号的 PowerShell 命令，经 UTF-16LE `EncodedCommand` 传递，因此带空格的 Python 路径不会拆开。编码内容仅为固定 Python 入口及工具名，不含令牌或用户输入。

`--config-preview` 只打印 JSON。`--export NEW_FILE` 以独占方式创建新片段，文件已存在就失败。两者不写入任何原生工具设置，也不建立已接入记录。

审阅并手动合并片段到 Claude Code 的 `.claude/settings.local.json`，或本地 Codex 的 `.codex/hooks.json`；保留已有 hook。Codex 需要在原生 `/hooks` 中审阅、批准准确版本，配置生成器不会替用户批准或修改信任。Codex 桌面仅指支持本地 command hook 的本地会话，云端编排不能据此保证可用。

配置结构参考 [Claude Code Hooks](https://code.claude.com/docs/en/hooks) 与 [Codex Hooks](https://learn.chatgpt.com/docs/hooks)。本实现只用三个通知事件及 `hookSpecificOutput.additionalContext`，不会输出 permission / approval 决策，不改变审批规则，不唤醒空闲会话。

## 状态与接口

| 操作 | HTTP POST | 输入与结果 |
| --- | --- | --- |
| `checkpoint` | `/api/checkpoints` | `session_key`、`tool`、`event`，可选 `task_id`；返回 `checkpoint` 与 `brief` |
| `diagnostic_start` | `/api/diagnostics/start` | `challenge`（最多 128 字符）；返回诊断 ID 与 `sent` |
| `diagnostic_read` | `/api/diagnostics/read` | `diagnostic_id`；只能由同项目同成员读回 challenge 和服务端 proof，状态 `read_back` |
| `diagnostic_complete` | `/api/diagnostics/complete` | `diagnostic_id`、读回的 `proof`；核验成功后才为 `completed` |

以上操作均要求个人 agent 鉴权，同时通过 HTTP MCP 和可选本地 Git stdio 适配器公开。MCP 指引要求在 `startup`、`blocker`、`completion` 调用检查点；原生入口也可以在三种 hook 事件自动调用。可选 `task_id` 必须属于当前成员已认领的任务。

服务端按项目、成员、会话、工具存储检查点；时间来自服务端。三个原生事件标记 `source=hook`，`manual` 标记手动调用，`startup/blocker/completion` 标记工具调用。来源说明入口报告类型，不是对原生工具或模型消费的独立证明。手动调用保留此前 `last_hook_at`，不会把手动新鲜度冒充为原生新鲜度。记录满 300 秒即过期，网页每次读取快照重新计算。

`/api/snapshot` 增加 `collaboration`，包含项目最近 200 条会话记录，以及当前成员最近 5 次诊断状态。挑战和 proof 不进入网页快照。不同成员和项目不能读回彼此的诊断。

`--doctor` 校验服务地址、令牌身份、项目一致性，再进行发送挑战、读回 challenge 与服务端 proof、确认完成的真实 HTTP 过程。只有配置文件或一次连接成功都不能产生 `completed`。doctor 自身不制造 hook 检查点，也不声称原生 agent 已消费上下文。诊断失败返回非零退出码；hook 失败写入不含凭据的警告并返回 0，让原生工作继续。

## 数据与执行边界

- 入口仅从 stdin 使用 `session_id`、`hook_event_name`。不转发 prompt、cwd、transcript 路径/正文、tool 输入或输出，不读取这些字段指向的文件。输入超过 64 KiB 时跳过并警告。
- 服务地址只能来自显式 `CREWMESH_SERVICE_URL`，支持 HTTPS 或 loopback HTTP origin，禁止重定向。每个 HTTP 响应最多 64 KiB，每请求默认 2 秒、可设 0.05–3 秒；hook 的网络与节流操作整体 8 秒截止，生成配置 timeout 为 10 秒。独立 doctor 整体 12 秒截止。
- 摘要最多 10 项本人任务、6 条相关待解决请求、每请求 2 条回复、4 份最新已批准版本。请求正文 400 字符，回复 300 字符，证据 150 字符，约定正文 800 字符；序列化摘要最多 16,000 UTF-8 字节。字段/列表截断标记 `excerpted` / `truncated`，明确要求用 `read_team` 或显式 `read_inbox` 查看完整数据。Hook 输出另有字节上限。
- 自动检查点只 peek，不写入已读、处理、回复或解决状态。显式 `read_inbox` 等工具维持原有语义。本地 Git `repo_checkpoint` 是独立既有操作，不作为自动 hook 的入口。
- `PostToolUse` 按服务、项目、鉴权成员、会话、工具节流 30 秒；每次仍先校验身份，过期或撤销令牌不能凭节流缓存继续被视作有效。`SessionStart` 和 `UserPromptSubmit` 强制检查。跨进程 SQLite 事务协调节流，只有服务成功才更新成功时间。
- 节流数据库放在操作系统用户状态目录的 `Crewmesh/hook-state/`，只持久化键哈希和成功时间，不保存令牌、prompt 或 brief。不会删除状态文件。服务数据库以新增表升级，保留已有任务、消息及账户数据。
- 网页使用文本 DOM，退出或切换项目即清理接入上下文；不保存个人 agent 令牌。项目网页读取成功与 agent 的真实报告分开显示。

## 本阶段证据（2026-10-11）

测试先失败再实现：新增检查点操作、诊断路由、hook 入口、MCP/stdio 工具、网页模块分别验证了缺失行为；整体截止、字段截断和工作目录模块覆盖另有先红后绿回归。

- 完整 Python：`python -m unittest discover -s tests -v`，371 项通过（基线 350，新增 21）。原始结果保留 `.local/f1-full-tests.log`。
- 自查额外加入了 hook 嵌套 JSON 转义后的输出字节上限回归，并在独立 hook 专项中验证；当前总计 372 项用例。实验目录 21 项测试通过。
- 新增用例覆盖真实 HTTP + hook 子进程、错误项目/令牌、跨项目隔离、不同成员及会话、无自动已读回执、挑战完整顺序、300 秒边界、超时/重定向/响应大小、prompt 不泄漏、跨进程节流、配置保留、旧数据库升级。
- 网页：`collaboration_ui_regression.js`、`web_session_regression.js`、`git_ui_regression.js`、`account_ui_regression.js`、`billing_ui_regression.js` 均通过；包括过期状态、诊断不冒充 hook、安全文本渲染、切换项目后的异步结果和工具选择保留。新增网页测试已加入 CI。
- 真实浏览器验收确认仓库接入页显示自动协作面板，390px 宽度无横向溢出；未发现新增脚本错误。步骤展开和工具选择在刷新时保留，退出/切换项目重置。
- Windows 含空格的真实 `sys.executable` 命令完成本机 shell 执行。另从含同名 `crewmesh.py` 的工作目录执行，确认生成入口使用已安装包。
- 实际 Claude 新会话触发了 `SessionStart` 与 `UserPromptSubmit`；客户端调试日志确认接受带 `additionalContext` 的 JSON。但模型未复述只存在于上下文的随机标识。极小 literal-context 对照同样未复述，因此**模型消费验收未通过**，不能声称完成端到端上下文注入。
- 隔离 Codex CLI 项目尚未产生原生 hook 记录；没有修改用户个人配置或绕过 `/hooks` 信任。Codex 桌面尚未独立验收。

原生实验与令牌等本机证据仅保留在忽略目录 `.local/native-checkpoints/`，不提交 Git。CI 验证程序接口与子进程，不替代不同原生客户端的真实模型消费验收。
