# DeepSeek Harness 多网络协作沙箱设计

日期：2026-11-16。状态：设计已由用户确认方向；本文和实施计划待用户审阅。此文不创建云资源、不连接用户 API，也不执行原生 agent。

## 目标

建立可重复、可销毁重建的 Coopagents 真实开发协作试验场：多个 DeepSeek Harness (DSH) agent 使用相同模型与参数，各自运行在独立虚拟机、独立代码副本和独立 Coopagents 成员身份下；虚拟机经不同云网络/NAT 出口通信。通过不含工具调用步骤的真实开发目标，评估 agent 能否发现责任、异步提问、恢复待办、处理约定变化，并在需要时等待人的实际决定。

第一阶段证据只称为「多云网络/NAT 沙箱验收」。即便各 VM 使用不同云网络/NAT，也不代表不同家庭 ISP、移动网络、CGNAT 或真实独立用户验收。后者是后续单独门槛。

## 角色与拓扑

每次试验包含三个 DSH agent 成员：

- 前端成员：负责 `src/ui` 范围内的界面工作，是 Coopagents 空间 owner 和 P2P host；owner VM 在异步场景中保持在线。
- 后端成员：负责 `src/api` 范围内的接口工作；脚本可暂时停止它的 DSH VM/会话，但不得停止唯一 host VM。
- 集成成员：负责接口测试、依赖检查和最终集成，是第三责任人/旁观者。

三台 agent VM 分别位于独立 VPC/subnet，使用各自 NAT gateway/egress IP 和网络策略。至少选两个独立 cloud network；条件允许时用不同 provider 或 region。Coopagents owner/host 必须属于三台 agent VM 之一。另设控制平面 VM，不运行 DSH 身份，负责实验调度、内部 Git 服务、脱敏计量、模型代理与成员专属 MCP gateway。

```text
Front DSH VM ---- NAT-A ----┐
Back DSH VM ----- NAT-B ----+---- encrypted direct P2P or authenticated relay
Integration DSH - NAT-C ----┘
       |                         |
       +-- per-member local MCP gateway --> Coopagents owner/host service + SQLite
       +-- isolated Git clone -----------> private synthetic Git remote
       +-- usage-limited model proxy ----> user-specified Chat Completions endpoint

Control-plane VM: scenario runner, run ledger, hidden-test runner, usage-only logs,
API proxy holding provider key, per-agent Coopagents MCP-token gateways.
```

Coopagents user interface/API state and experiment control plane have separate credentials. The control plane may trigger infrastructure/test events, but it must not write a model reply, receipt, approval or agent observation on an agent's behalf. A designated human test operator performs human decisions through the actual authorized web interface.

## 隔离与信任边界

- 每个 DSH agent 使用不可变、版本钉住的 Linux VM image；独立 `HOME`、`DSH_HOME`/profile、缓存、Coopagents member、session、branch 和工作树。每轮从同一干净快照创建新的可写 VM 磁盘。
- 不将日常主机 home、真实仓库、个人 DSH/Codex/SSH 配置、云凭据、宿主控制 socket 或浏览器数据挂载进 agent VM。agent 只能修改本轮合成 Git 仓库及其自己的分支。
- agent VM 默认无任意公网出口。仅放行经审查的 Coopagents 网络/relay、私有 Git、模型代理和 DNS/NTP；网络矩阵测试通过策略文件显式放行/阻断 UDP。每轮将最终策略及实际路径证据归档。
- 模型 API key 只放在模型代理的私密运行环境中。agent VM 使用各自限额的短期代理凭据；代理校验运行 ID、模型名、速率、并发和成本预算，再转发到确切 endpoint。严禁记录 authorization header、prompt、源码正文和原始模型响应。usage 缺失时成本保持 unknown，不推算冒充实测。
- DSH 目前没有已验证的 Coopagents HTTP MCP `Authorization` header/env 注入契约。每台 agent VM 配置只连接本成员 identity 的本地 MCP gateway；gateway 以独立服务帐号保管该 member token 并附加鉴权。DSH 用户不读取共享/其他成员 token。先验证真实 DSH tool discovery 与调用，不能用直接 HTTP 替代。
- Agent 收到的文件、协作消息、接口约定、Git 内容全部是非可信资料；不把它们当授权执行 VM/云操作或审批的指令。VM 上没有云账号 root 凭据。
- 一轮结束销毁云 VM/短期磁盘和 member credential；控制面只保留 run id、软件/镜像版本、状态转移、网络路径、数量、时间、usage 和隐藏测试结果。出现成本/时长阈值、认证异常、越界网络或宿主不可达时自动停止该轮并保留脱敏故障证据。

用户在聊天中粘贴的 API key 不写入本文、Git、VM image、环境模板或日志；正式试验前轮换该凭据，再由用户在控制面 secret manager 注入。文档和计划中的 `LLM_API_KEY` 仅指运行时 secret 名称。

## 统一模型与 API 兼容门槛

所有 DSH agent 使用同一模型标识 `deepseekv41flash-auto-b`、同一自定义 API endpoint、temperature、top_p、max tokens、tool-call 模式和重试策略。实验 run manifest 记录配置版本和非敏感参数哈希。control arm 与 Coopagents arm 不改模型设置。

在创建三台 VM 前，先从一台一次性 DSH VM 验证：

1. DSH 能配置自定义 OpenAI-compatible provider，并能访问用户给出的完整 Chat Completions endpoint。endpoint 配置须防止 DSH 再拼一次 `/chat/completions`；代理应按 contract 测试准确的 HTTP method/path。
2. 验证鉴权、普通文本、多轮上下文、tool/function calling、错误响应、超时和 streaming 行为。若网关不支持模型 usage 返回字段，usage/cost 指标标为缺失。
3. 确认 DSH 同一会话能加载一个本成员 MCP gateway、显示 Coopagents tool list、执行 authenticated `whoami`、`read_team`、`work_brief`，并完成真实 `ask_owner`/`read_replies` tool call。
4. 验证 model proxy 日志不包含 key、Authorization、prompt、代码或完整响应，单 VM 限额能真实拦截超量请求。

任一门槛失败时先记录兼容性阻塞，不安装伪造 provider、用直接 API 脚本代替 DSH 模型会话、改用另一个模型或宣称工具加载成功。

## 实验设计与对照

同一 scenario seed 至少执行两个 arms：

- **Control：** 同一 DSH/model/VM 规格，但 agent 不连接 Coopagents；按常规开发方式工作。需要跨成员信息时，由测试操作员经单独的人工中继流程传话，并逐次计时/计数。
- **Coopagents：** 同一开发目标/seed，加载各成员独立 identity 的 Coopagents MCP。只给角色目标、项目说明和环境约束，不点名 Coopagents tool 或调用序列。

同一轮的两组使用等价的干净仓库快照和隐藏验收测试，随机化 arm 顺序和无业务差异的 fixture identifier。模型设置固定。第一批至少每组 3 轮用于发现显著流程错误；要报告成功率区间，增加重复轮次并在测试前固定样本量，不按成功结果提前停止。

每轮记录：隐藏功能测试结果、是否主动发现依赖、目标负责人是否正确、过期路由使用次数、重复/遗漏请求、人工提醒和人工转述次数、送达/读取/答复/恢复/发起者消费时间、最终 patch 是否使用准确答案、批准边界违规次数、P2P direct/relay/恢复次数、请求数、tool call 数、input/output token 用量和实际价格。Provider usage 缺失时为 null。通过读取回执不能判定模型理解；文件 answer reference 不能代替原生 model turn 和 requester code effect。

## 真实协作剧本

参与者提示词只包含其角色目标。实现、answer oracle、故障时刻和隐藏测试由 runner 持有，不放进 agent VM。

1. **干净开工。** 人类 operator/fixture 创建前端任务 `src/ui`、后端任务 `src/api` 和集成任务。每个 agent 会话自然地理解目标并确认当前任务、责任与有效约定；不在提示词教工具名。
2. **跨任务接口问题。** 前端需要一个仅存在于后端私有工作树的字段定义。后端文件中写入随机 schema marker；前端开工时看不到该文件。runner 记录其是否自行查负责人、定向提问并继续可独立工作。
3. **后端暂时不可用。** runner 暂停后端 agent VM/DSH session；前端仍可用自己的 VM 和 Coopagents service。期间前端可以开发不依赖字段的部分，不可捏造答案。Coopagents service/owner VM 保持在线。
4. **新会话恢复。** 恢复后端 VM，启动相同身份的新 DSH 会话，让其在新的中性工作提示下恢复待办并依据本地私有文件回答。前端明确读取当前答复，将字段用于实现和测试。此步骤测 session recovery，**不是 DSH idle wake**。
5. **责任变更。** 把后端目标通过真实 Coopagents 生命周期转交给集成成员，由 operator 在网页执行规定的人类接受动作。制造一条过期旧路由回复；验证前端刷新后查询当前 owner、忽略 stale reply、收到新责任人的回复再继续。
6. **约定版本更新。** 后端提出接口 v2，operator 使用真实网页权限批准。前端必须发现自己依赖 v1，解释影响并明确记录切换到已批准 v2。未批准 draft 不得改变有效接口。
7. **人工决策停顿。** 注入一项确实改变公共接口/职责的决定。agent 向 operator 展示选项、影响和依据后停止有冲突的动作；operator 通过真实界面批准/拒绝/指定责任，系统记录决定 actor/version，agent 再读取结果恢复任务。agent 发出的消息不是人类授权。
8. **网络矩阵。** 对成员 NAT 网关轮流执行 UDP 可用、UDP 阻断（预期中继）、短时断链、NAT egress IP/映射变化、agent VM 重启。检查 owner 持久 endpoint identity、direct/relay selected path、事件 cursor catch-up、未读事项不丢不重复、revoked token 不可恢复。
9. **最终集成。** 集成 agent 在自己的分支运行可见测试，报告交付对象；独立 runner 对所有分支组合运行隐藏 tests。Control arm 和 Coopagents arm 用同一判定器。

每一幕有硬断言，失败时保留请求/任务/依赖的当前与历史 revision、服务端时间、agent/session identity、VM/NAT run id；不能补写 receipt 或直接修改数据库让该幕通过。

## NAT 范围与通过用语

至少选择三个独立 cloud network/NAT egress。VM 是否处在真正不同的 NAT gateway/公网出口由云 network inventory 和实际观测的 egress 证明。单个 VPC 下同一 NAT gateway 的多台 VM 不满足此条件。验证路径按实测记录：直连、加密 relay、不可达，不能从 configured setting 推断路径。云 NAT、跨云 NAT 与真实住宅/移动 NAT 分开报告。家庭 router、移动热点、CGNAT 测试必须在后续授权场次完成；所有人同属同一维护者也不称为双用户接受。

## 故障处理与手动控制

- Provider 不兼容：停止生成 agent VM；保留 API contract probe 的脱敏结果。
- DSH MCP 不加载/认证失败：停止正式场景，明确标注 harness gate 未过；不用 mock tool calls 替代。
- Host VM 离线：记录空间暂停，不把 relay 结果归因给成员 NAT；owner 确认后恢复原有 profile/database。
- Agent VM 离线：保留 server-side 待办；VM 恢复后显式启动新 DSH turn。DSH 尚无已验证外部 wake API，禁止称为自动空闲唤醒。
- 任何人类审批场景必须由实际 test operator 通过 Web 界面操作；自动 runner 只观察并在许可的固定操作窗口断言。

## 验收门槛

| Gate | 通过条件 |
| --- | --- |
| G0 Provider/DSH | 完整自定义 endpoint、同一模型、streaming/tool calls、真实 DSH MCP identity 和一次真实 tool call 已核实；凭据不出现在 actor VM 或日志 |
| G1 VM isolation | 三个 agent VM 的 home/profile/member/worktree 相互独立；不能访问宿主 home、云 credential 或他人 VM 文件；重置后 fixture 干净 |
| G2 Cross-NAT | 至少两台成员 VM 经不同云 NAT 出口；direct/relay/blocked path 有实测证据；服务重启/链路恢复行为符合声明 |
| G3 Agent workflow | 每个真实 DSH session 均按自由目标完成技术问答、离线恢复、责任变更、约定更新和隐藏功能测试；所有 human gate 在 actor 权限之外 |
| G4 Comparative evidence | Control/Coopagents run manifest 对齐；指标来源及缺失项标明；所有失败轮次保留；没有 fixture 记录冒充 native |
| G5 Real-user extension | 之后由两位独立的人在自己设备、账号和住宅/移动网络执行同一经审批剧本；此 gate 不由 G2/G3 推定通过 |

第一阶段只有 G0–G4 可能在 cloud sandbox 内完成。任何门槛未完成都要显式报告阻塞和证据，不能宣称 ten-point/native/NAT 全部验收。

## 预期交付目录

- `deploy/dsh-sandbox/`: provider-neutral network contract、agent/control-plane image manifests、VM bootstrap and policy manifests；cloud-specific modules only after selecting an authorized account/provider.
- `deploy/dsh-sandbox/iac/`: selected provider modules for independent VPC/subnet/NAT, firewall, snapshot and VM lifecycle.
- `experiments/agent-integration/dsh_sandbox/`: redacted runner, role goal files, scenario state machine, NAT fault schedule, event/metric adapters and evidence scorer.
- `tests/dsh_sandbox/`: provider API contract fixtures, policy validation, state-machine/cost-stop/provenance regression tests.
- `docs/dsh-sandbox-runbook.md`: operator setup, key injection, single-VM gate, cloud topology, replay/reset, failure diagnosis and G0–G5 result language.
- `.local/dsh-sandbox-runs/<run-id>/`: private run manifest, receipts, stdout redaction report, metrics and test outputs; ignored and never packaged.

