# 首次配置与 Doctor 诊断设计

日期：2026-10-31

状态：设计已确认，等待实现计划。

## 目标

让用户可以直接对自己的 coding agent 说“帮我配置好 Coopagents”，由 agent 完成本机环境发现、隔离安装、原生 MCP 配置、Skill 安装、身份验证和诊断；同时让自托管网页提供一个可观察的首次接入向导。两种入口使用相同的诊断语义，但不共享本机配置写入权限。

1.0 的用户承诺是：

- agent 负责发现、安装、连接、验证和解释结果；
- 网页负责准备当前项目的私有接入指令、展示服务端证据和下一步；
- 用户仍决定是否信任新 MCP 配置、是否开启唤醒、是否批准 native hook，以及是否接受任何需要人工判断的操作；
- “配置已保存”“服务身份已验证”“当前会话已加载”“模型已消费共享上下文”是四个不同状态，界面和输出必须分开表达。

没有邀请、私有接入指令或已存在空间上下文时，agent 在当前仓库创建本机 P2P 空间，并使用当前 harness 的默认显示名接入自己。创建空间不自动开启唤醒。

## 非目标

- 不增加常驻桌面客户端、后台守护进程或新的账号体系。
- 不让网页修改用户电脑上的 Claude Code、Codex 或其他 harness 配置。
- 不通过配置脚本绕过原生 CLI 的信任确认、权限提示或 Codex `/hooks` 审阅。
- 不把所有 harness 的 native hook、空闲唤醒或自动上下文消费包装成同等支持。
- 不删除旧配置、旧 Skill、旧 profile、数据库或诊断证据。发生配置冲突时保留原文件并明确要求用户选择新的名称或人工处理。
- 不把一次成功的 HTTP/MCP 身份请求描述为模型已经读取、理解或回复共享上下文。

## 用户入口与路由

### Agent 入口

`coopagents-space` Skill 增加一条以用户目标为中心的自助配置路径。agent 先识别当前上下文，再选择已有能力：

| 上下文 | 动作 | 完成判定 |
| --- | --- | --- |
| 用户提供邀请消息、邀请码或私有邀请文件 | 私下保存原文，执行 `join --connect <当前工具>`，随后运行 doctor | 成员 profile 写入、MCP 配置核验、身份请求通过 |
| 用户提供网页生成的项目接入指令 | 使用指令中的可信 origin、项目 ID 和个人 agent 凭据生成 agent-only profile，安装 Skill，注册 MCP，随后运行 doctor | 项目/成员身份匹配，凭据权限正确，MCP entry 回读一致 |
| 当前工具已有 Coopagents entry 或 profile | 先只读检查并运行 doctor；配置一致时不重复写入，配置冲突时保留原 entry 并给出 `--name` 选择 | 现有 entry、profile 和服务身份一致 |
| 没有上述上下文 | 在当前仓库创建默认 P2P 空间，以当前工具名作为本机 agent 名称，接入自己，随后运行 doctor | 空间启动、profile 安全写入、MCP entry 回读、服务身份验证 |

agent 需要显示每一步的结果和下一步，但不得回显邀请、agent token、web token、control token、profile JSON 或完整命令中的秘密。只有用户明确要求时才生成或展示邀请信息；创建空间本身不默认邀请别人。

### Web 入口

项目设置中的“接入 agent”升级为首次接入向导，继续沿用当前页面的私有凭据展示和复制机制：

1. 用户选择自己的 harness。
2. 网页验证当前项目成员身份并发行本人的 agent 凭据。
3. 网页生成可直接交给 agent 的私有接入指令，凭据只在当前页面内存中短暂存在。
4. 用户把指令交给自己的 agent；agent 在本机执行安装、配置和 doctor。
5. 用户返回网页刷新接入证据，查看身份验证、诊断往返和最近检查点的实际时间。

网页只显示服务端已观察到的证据及其新鲜度，不轮询或猜测用户电脑上的配置状态。刷新、关闭弹窗、切换项目、退出登录和旧请求迟到都不能恢复私有凭据或旧项目状态。

网页状态至少分为：

- 指令已生成：只表示服务端发出了个人凭据；
- 身份已验证：服务端收到匹配项目和成员的 agent 调用；
- 诊断已完成：agent 完成挑战写入、读回和证明；
- 当前会话待重启：原生配置已保存，但当前 harness 尚未重新加载 MCP；
- 需要用户处理：例如 Codex hook 信任、工具未安装、MCP 名称冲突、凭据过期或网络不可达。

## 共享诊断语义

新增一个只负责检查与格式化结果的诊断核心，供 CLI、Skill 指令和网页文案共同使用。它不保存秘密，不修改业务数据，不自动修复破坏性配置。

### 检查项

每一项返回 `id`、`status`、`summary`、`next` 和不含秘密的 `evidence`。`status` 只允许：`pass`、`fail`、`needs_user`、`unknown`、`skipped`。

固定检查顺序如下：

1. `python_runtime`：Python 版本、解释器路径是否属于隔离环境、Coopagents 包版本和 `space` extra 是否可导入。
2. `project_context`：当前仓库路径、profile 所属空间和本次目标项目是否一致；不输出 profile 内容。
3. `native_tool`：调用 agent 自己的 harness 检测结果，确认对应 CLI 可发现、版本可读取；检测不到时给出显式的 `needs_user`。
4. `mcp_configuration`：读取并核对原生配置中的 Coopagents entry；不存在时报告待执行 connect，存在冲突时报告冲突且不覆盖。
5. `skill_installation`：Skill 文件是否存在、版本是否匹配；不同版本保留备份并报告路径，不删除旧版本。
6. `runtime_reachability`：profile 的 loopback、HTTPS 或 P2P 目标是否可达，空间 ID 是否匹配，凭据是否为 agent 身份。
7. `transport_path`：P2P 报告 `direct`、`relay`、`connecting`、`disconnected` 或 `loopback`，自托管 HTTPS 报告 `https`；路径未知时为 `unknown`，不推测。
8. `challenge_round_trip`：执行现有诊断挑战的 start/read/complete，并验证 challenge、diagnostic ID 和 proof 关联一致。
9. `session_reload`：说明配置已被原生 CLI 核验，但新 MCP 是否进入当前会话只能由用户新建会话后调用 `whoami` 验证。
10. `wake_up`：只报告是否已经安装、是否待用户信任以及当前 harness 的实际能力；默认 `skipped`，不会因为运行 doctor 自动开启。

整体结果按以下规则计算：存在 `fail` 为 `blocked`；没有 `fail` 但存在 `needs_user` 为 `needs_user`；所有必要检查为 `pass` 且只有可选项 `skipped/unknown` 为 `ready`；没有 profile 时只返回本地环境和工具检查，整体为 `needs_user` 或 `unknown`，不伪造连接成功。

### CLI 接口

增加：

```text
<python> -m coopagents.space_runtime doctor [--profile <private-profile>] [--tool claude|codex] [--project-dir <repo>] [--json]
```

- 无 `--profile` 时只做本地环境、工具、Skill 根目录和已注册 Coopagents entry 的只读检查。
- 有 `--profile` 时增加 profile、服务身份、P2P/HTTPS 可达性和挑战诊断。
- `--tool` 缺省时按当前 agent 环境自动识别；无法唯一识别时返回 `needs_user`，不猜测工具。
- `--json` 输出稳定的机器可读对象；默认输出英文简报，内容与 JSON 的状态一致。凭据、邀请原文、环境变量值和远端响应正文永不出现在两种输出中。
- doctor 的非零退出码只表示存在 `fail` 或需要用户完成的阻断步骤；`unknown` 和可选 `skipped` 不单独导致失败。

`connect`、`create --connect` 和 `join --connect` 在完成已有配置动作后调用同一诊断核心，返回 `configuration`、`verification` 和 `next` 三个明确区段；不得把配置写成功直接映射为 `ready`。

## Web 与服务端边界

复用现有 `/api/agent-connect`、`/api/me`、`/api/diagnostics/*`、checkpoint 和 capability 证据，不为网页复制一套本机配置数据库。必要的服务端变更只扩展诊断记录的来源、时间和关联信息，保持 agent-only 凭据隔离。

服务端输出给网页的诊断摘要只包含：空间/成员非秘密标识、harness 名称与版本、检查状态、证据来源、时间、新鲜度、传输状态和下一步。不得返回 agent token、web token、control token、邀请 token、完整 profile、命令行环境或原始错误响应。

网页向导的刷新只读取当前选定项目；所有异步响应必须带项目和页面世代校验。项目切换、退出、关闭弹窗时立即清空内存中的私有内容并中止或忽略旧请求。

## 错误与恢复

| 情况 | 用户看到的结果 | 允许的恢复 |
| --- | --- | --- |
| 未发现 Claude/Codex CLI | `needs_user`，说明安装或指定 CLI 路径 | 用户安装对应工具或明确提供路径后重跑 doctor |
| 当前 Python 位于 user site 或缺少 space extra | `fail`，说明创建隔离环境和精确版本安装命令 | agent 按 Skill 重新安装；保留旧环境 |
| MCP 名称已被其他命令占用 | `needs_user`，给出冲突名称 | 用户选择新的 `--name`；不覆盖旧 entry |
| 服务不可达或空间 ID 不匹配 | `fail`，区分网络、停止、权限和身份不匹配 | 检查运行时、网络或重新生成当前项目接入信息；不自动换目标 |
| P2P 直连失败但 relay 可用 | `pass` + `relay`，展示 relay 状态和延迟 | 继续使用；若 relay 也失败，给出网络/代理诊断 |
| Codex hook 尚未信任或唤醒未开启 | `needs_user` 或可选 `skipped` | 用户在 `/hooks` 审阅或明确要求安装 wake；不自动绕过 |
| 当前会话尚未加载新 MCP | `needs_user` | 用户启动新会话并执行 `whoami`、`read_team`；保留配置和空间 |
| 旧请求在项目切换后返回 | 丢弃响应，不更新页面 | 用户刷新当前项目；不显示旧项目秘密 |

所有失败都保留现有 profile、配置备份、数据库和诊断证据。任何需要删除文件、撤销成员或轮换凭据的动作都不由 doctor 自动执行。

## 安全与隐私要求

- 诊断结果使用固定错误摘要和 allowlist 字段，不转发远端响应正文、traceback、命令输出中的 token 或环境变量。
- agent token 只用于私有 profile/native 配置和同源认证；不写 URL、日志、MCP 参数、Skill 文件或 Git。
- 网页凭据只存在当前页面内存；不写持久浏览器存储，不进入 URL，不由诊断接口返回。
- P2P 诊断只展示当前选择的 transport path，不向用户承诺直连一定可用；relay 元数据和中继依赖写入发布限制。
- 检查点、挑战诊断、hook 到达和模型实际消费分别记录；任何一项不能替代另一项。
- 新增检查必须在 Windows、macOS、Linux 的能力矩阵中分别记录，未知组合保持 `unknown`。

## 验收

### 自动化

- 为诊断核心新增单元测试：每个检查项的通过、失败、待用户处理、未知、秘密脱敏和整体状态聚合。
- 为 `space_runtime doctor` 新增 CLI 回归：无 profile、有效 profile、P2P relay/direct、服务停止、身份不匹配、MCP 冲突、user-site 环境和当前会话待重启。
- 扩展接入回归：`create --connect`、`join --connect`、已有配置重复运行和 connect 失败后的保留/重试输出。
- 新增网页回归：生成私有指令、刷新诊断证据、项目切换/退出/关闭后的旧响应隔离，以及不展示任何凭据。
- 对构建包执行 Skill 资源、JSON schema、版本和无本机数据检查。

### 真实验收

- Windows 上分别用 Claude Code 和 Codex 完成“帮我配置好 Coopagents”：一个已有邀请路径，一个无上下文创建 P2P 路径。
- 两台真实设备执行一次 P2P 成员接入和 doctor，记录 direct/relay、加入时间、重启恢复和失败时的诊断输出。
- 自托管网页生成接入指令后，由真实 agent 完成配置和挑战诊断；网页只显示实际服务端证据。
- Codex 的 hook 信任、Claude 的可选 wake-up 和当前会话重启分别记录，不能合并成一个“已接入”结论。

## 分阶段提交

1. `feat: add shared onboarding doctor checks`：诊断核心、CLI doctor、单元和 CLI 回归。
2. `feat: route agent setup through doctor`：Skill、create/join/connect 后置验证和真实 agent 入口。
3. `feat: add web onboarding evidence`：网页首次接入向导、诊断摘要和异步世代隔离。
4. `docs: document first-run setup and diagnostics`：英文默认用户文档、中文同步文档、故障排查和支持边界。

每阶段都运行对应测试并保留失败证据；不删除任何文件，不提交本机凭据、配置、数据库或原始会话记录。
