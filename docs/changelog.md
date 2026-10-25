# 版本记录

## 0.7.3 — install_wake 工具（2026-10-25）

修复 [0.7.2 唤醒重测](solo-acceptance-2026-10-25.md#唤醒安装重测072同日) 的路径 B：新会话里说"开启唤醒"，agent 拿手边的 MCP 工具注册了会话就谎报已开启。


已发布：[v0.7.3](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.7.3)（正式版，GitHub 的“最新版本”），发行提交 `55642ee`，[CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/40202988373) 通过；[发布工作流](https://github.com/Weichenleeeee123/coopagents/actions/runs/40203268828) 自动上传到 [PyPI](https://pypi.org/project/coopagents/0.7.3/)，SHA256 与下表一致。资产从干净的 `git archive` 构建，`twine check` 通过。

| 资产 | SHA-256 |
| --- | --- |
| `coopagents-0.7.3-py3-none-any.whl` | `3aff5fc1743822174bf9995789366ced1b77f69793d8628ad237437a433b2c2e` |
| `coopagents-0.7.3.tar.gz` | `45aef596535918cb2f4cd6a674314daf5b938e8ed3579573f3ba7a3542a3a1e3` |
| `coopagents-0.7.3-deploy.zip` | `50687a59a3e4d35b15b06172ec83dd4bc32564b6332f70beb34a7e7ff511a238` |

- 桥接新增 MCP 工具 `install_wake`（参数 `tool`、`project_dir`）：由桥接用自己的 Python 和 profile 安装唤醒 hook，项目目录默认是桥接的工作目录；拒绝不支持的工具和不存在的目录；返回 `installed` 和下一步（Claude Code 新会话生效，Codex 在 `/hooks` 里信任）。
- 桥接的服务说明写明"开启唤醒就调用 `install_wake`，返回 installed 才算开启"；`register_session` 的说明写明它不是唤醒。
- README 第 3 步改为"直接说开启唤醒，agent 会调用 `install_wake`"；Skill 同步。

## 0.7.2 — 唤醒安装变成确定的命令（2026-10-25）

修复 [第三轮验收](solo-acceptance-2026-10-25.md#第三轮071同日) 发现的问题：新会话里"安装唤醒"仍靠 agent 发挥（不知道 profile 在哪，或编造配置文件并谎报成功）。


已发布：[v0.7.2](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.7.2)（正式版，GitHub 的“最新版本”），发行提交 `4a3abeb`，[CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/40184012304) 通过；[发布工作流](https://github.com/Weichenleeeee123/coopagents/actions/runs/40197300956) 自动上传到 [PyPI](https://pypi.org/project/coopagents/0.7.2/)，SHA256 与下表一致。资产从干净的 `git archive` 构建，`twine check` 通过；全新环境装 wheel 冒烟通过（`connect --wake` 可用，`space_wake install` 的 `--profile` 可选）。

| 资产 | SHA-256 |
| --- | --- |
| `coopagents-0.7.2-py3-none-any.whl` | `614829d80ba922c2ab34e5995f3b66fa8c5df42a9be2161b1af565906b3ff91a` |
| `coopagents-0.7.2.tar.gz` | `953576e7830961baf60fb3e70cf6bcb46182c3a99fdccf740ff1d274bc2f9319` |
| `coopagents-0.7.2-deploy.zip` | `7239cc11e11efff79b4705eacce638d779d1db50f88904c3c1a0ad34342b231a` |

- `space_runtime connect --wake [--project-dir <repo>]`：接入时一并安装唤醒 hook（项目目录默认是当前目录）；不加 `--wake` 时，输出里给出带好 Python 和 profile 的唤醒安装命令。
- `space_wake install` / `preview` 不再必须传 `--profile`：只读地读取 Claude Code（`.claude.json`，含当前项目的条目）或 Codex（`config.toml`）里已注册的 coopagents 连接，正好一个就用它；没有或有多个时报出原因和服务器名，不去猜。`--project-dir` 默认是当前目录。
- README 第 1 步改为"接入时开启唤醒"，第 3 步给出单条命令；Skill 写明不得手写 hook 或配置文件，命令没有输出 `installed` 就不能报告已安装。

## 0.7.1 — 文件加入、回复去处、单份 Skill、唤醒后直接回答（2026-10-25）

修复 [0.7.0 复测](solo-acceptance-2026-10-25.md#复测070同日) 新发现的四个问题。


已发布：[v0.7.1](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.7.1)（正式版，GitHub 的“最新版本”），发行提交 `b7cf020`，[CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/40177623524) 通过；[发布工作流](https://github.com/Weichenleeeee123/coopagents/actions/runs/40177827325) 自动上传到 [PyPI](https://pypi.org/project/coopagents/0.7.1/)，SHA256 与下表一致。资产从干净的 `git archive` 构建，`twine check` 通过；全新环境装 wheel 冒烟通过（邀请信息写明 `==0.7.1`、让对方阅读 Skill 并从保存的文件加入，用保存的整段信息加入成功）。

| 资产 | SHA-256 |
| --- | --- |
| `coopagents-0.7.1-py3-none-any.whl` | `8ea98ed25d31445c1cc7997cecfe8a64588578c636a52a0227e5b5a80f049c56` |
| `coopagents-0.7.1.tar.gz` | `5cf8ed0788235bc3324c7a85c71ee885e95a6eae4d51e6c85652d2d5d4edef35` |
| `coopagents-0.7.1-deploy.zip` | `a4852ca6b4924505fb63e6a061d12ea966e0829045fa15ea00af15e045429494` |

- 加入改为走文件：`join --invitation-file` 除了私有邀请文件，也接受保存了整段邀请信息或邀请码的文本文件；邀请信息和 Skill 都改为让 agent 先用写文件工具保存再加入，邀请码仍然不进命令参数。`--invitation-code-stdin` 在 15 秒内没收到输入就报错退出，不再一直卡住（实测 16 秒退出）。
- 改正 MCP 工具说明：`read_inbox` 只列出发给你的请求，你发出请求的回复在 `read_team` 的 `requests[].replies` 里；`send_request` 的说明也写明了去哪看回复。0.7.0 的说明写错了，导致 Codex 一直在 `read_inbox` 里等回复。
- `connect` 比较 Skill 时忽略换行符差异（GitHub 下载的是 LF，Windows 构建的包是 CRLF）；确实不同的旧副本改为备份到 skills 目录之外的 `coopagents-backups/`，不会再被当成第二个 Skill 加载。README 和邀请信息里"按链接配置 Skill"改为"阅读链接里的 Skill"，由 `connect` 负责安装。
- 唤醒提示和 Skill 写明：用能读到的信息回答队友的问题、回复、确认属于本职，不必先问用户；改文件、执行会改变东西的命令、接受交接或接新工作仍要问用户。

## 0.7.0 — 接入命令与单人模式修复（2026-10-25）

第一个正式发行版（不再标预发行，以后也不再用 rc）。修复 [单人流程验收](solo-acceptance-2026-10-25.md) 发现的三个阻塞问题。真人双机验收仍未进行。

已发布为正式版：[v0.7.0](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.7.0)（未标预发行，GitHub 的“最新版本”指向它），发行提交 `6410aff`，[CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/40165687019) 通过；[发布工作流](https://github.com/Weichenleeeee123/coopagents/actions/runs/40165899962) 自动上传到 [PyPI](https://pypi.org/project/coopagents/0.7.0/)，PyPI 上的 SHA256 与下表一致，不写版本号的 `pip install "coopagents[space]"` 在全新环境里装到 0.7.0。资产从干净的 `git archive` 构建，`twine check` 通过；全新环境装 wheel 冒烟通过（邀请信息写明 `==0.7.0` 并提到 `connect`，用整段信息加入成功）。用真实 agent 在本版重跑单人验收尚未进行。

| 资产 | SHA-256 |
| --- | --- |
| `coopagents-0.7.0-py3-none-any.whl` | `a8543b5afb9b10ae6b25396f8cdecef04c0890c938954d30fe389de3a72f7dd9` |
| `coopagents-0.7.0.tar.gz` | `1508364320e93656737645457d0feb4e778da6af098d6f40f315af49bcea629c` |
| `coopagents-0.7.0-deploy.zip` | `ad18514a8e527ebb126a987c741aae66ed428c41903123d2a6d0ab08885c50fb` |

- 新增 `space_runtime connect --tool claude|codex --profile <p>`：由程序调用原生 `mcp add` 注册桥接，再用 `claude mcp get` / `codex mcp get --json` 读回核验，并把 Skill 装进工具的 skills 目录（不同的旧副本改名备份，不删除）。同名但命令不同的条目拒绝覆盖。依次尝试多个 CLI，用第一个能读自己配置的：Claude 优先用 `CLAUDE_CODE_EXECPATH`，Codex 在 PATH 上的版本读不了配置时，改用正在运行的 Codex 自带的 `codex.exe`。Skill 和邀请信息改为要求 agent 用这条命令接入，不再自己改配置文件。
- MCP 工具有了真正的说明：`send_request` 写明要填 `receiver_member_id`、不填就没人收到也不会唤醒任何人；`read_team` 写明用来查成员 id。不指定接收人的请求仍然保留（它是等人分派的队列），但返回结果里会明确写出 `not_delivered`。
- 成员命名：单人模式下用 agent 的名字（"Claude"、"Codex"），团队里用"人名 (工具)"。README 的单人示例改为让 Claude 以 "Claude" 建空间。

## 0.7.0rc2 — 邀请信息写明版本、从 PyPI 安装（2026-10-15）

已作为预发行版发布：[v0.7.0rc2](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.7.0rc2)，发行提交 `9794113`，[CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/38743108661) 通过；[发布工作流](https://github.com/Weichenleeeee123/coopagents/actions/runs/38744729456) 自动上传到 [PyPI](https://pypi.org/project/coopagents/0.7.0rc2/)，PyPI 上的 SHA256 与下表一致。资产从干净的 `git archive` 构建，`twine check` 通过；全新环境装 wheel 冒烟通过，生成的邀请信息写明 `coopagents[space]==0.7.0rc2` 和 `v0.7.0rc2` 标签。

| 资产 | SHA-256 |
| --- | --- |
| `coopagents-0.7.0rc2-py3-none-any.whl` | `32e720412660f04cb85a95e3531779088bc10dfb5d6705d9df1e900dd8ecd908` |
| `coopagents-0.7.0rc2.tar.gz` | `56196fd01c1b28dd553a505bf950ad8c488c105cb9f978d1944c5dca3cedf39d` |
| `coopagents-0.7.0rc2-deploy.zip` | `b5486fb1170dc660cf1d6e0c75361719e06665d7eade86d77d74a7f0ebb8f4bb` |

- 邀请信息不再让对方安装“最新发行版”（所有发行版都是预发行版时，GitHub 的“最新版本”链接打不开）。现在写明发起人自己安装的版本，让对方 `pip install "coopagents[space]==<版本>"`，Skill 链接也指向该版本的标签；读不到版本时退回安装 PyPI 上最新的预发行版。
- Skill 改为从 PyPI 安装固定的确切版本（pip 按 PyPI 公布的摘要校验，PyPI 上的文件不能被替换）；PyPI 不可达时改用 GitHub 发行页的 wheel 并按 `SHA256SUMS.txt` 校验。镜像未同步时用 `--index-url https://pypi.org/simple`。
- README、双机验收清单同步改为从 PyPI 安装。

## 0.7.0rc1 — 改名为 Coopagents 候选版（2026-10-15）

在 0.6.0rc2 之上只做改名，并新增 PyPI 发布工作流（`.github/workflows/publish.yml`，Trusted Publishing，上传的就是发行页附带并经 SHA256SUMS 校验的文件）。真人双机验收仍未进行。

已作为预发行版发布：[v0.7.0rc1](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.7.0rc1)，发行提交 `755ed77`，[CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/38687611208) 通过。资产从该提交的干净 `git archive` 构建，`twine check` 通过；全新环境安装 wheel 后冒烟通过（p2p 主机生成邀请信息，成员经标准输入加入并可连通，同一信息第二次使用被拒绝），发布后下载复验 SHA256 与本地一致。已发布到 [PyPI](https://pypi.org/project/coopagents/0.7.0rc1/)：配置 PyPI 待定可信发布者后重跑 [发布工作流](https://github.com/Weichenleeeee123/coopagents/actions/runs/38712739390)（第 2 次运行成功；第 1 次因尚未配置发布者失败）。PyPI 上 wheel 与 sdist 的 SHA256 与下表一致，从官方 PyPI 全新安装得到 0.7.0rc1。

| 资产 | SHA-256 |
| --- | --- |
| `coopagents-0.7.0rc1-py3-none-any.whl` | `b60b81f9c7c1e1623f06cc4c6089716c8e2362e889b5407f3d7f9cc183cf52a7` |
| `coopagents-0.7.0rc1.tar.gz` | `9469d4591ca3942bfc510bb40991214e36a7e09fd4d47edd27d7982a8a11b0f4` |
| `coopagents-0.7.0rc1-deploy.zip` | `70f7371b6c71c9ebcbfc125a4dc5ba96784ee29dcd8bb1f34fdaae6f43bfd252` |

项目由 Crewmesh 改名为 Coopagents：Python 包与导入名 `coopagents`，Skill 目录 `coopagents-space` / `coopagents-connect`，环境变量前缀 `COOPAGENTS_`，网页的请求头与本地存储键同步改名。兼容处理：

- 0.6.0rc2 生成的 `crewmesh-invite-1.` 邀请码仍可加入；新邀请码前缀为 `coopagents-invite-1.`。
- 点对点连接的协议标识保持 `crewmesh/space/1`，0.6 的主机和成员可以互连。
- `space_wake install` 会替换旧的 `crewmesh.space_wake` 钩子，`disable` 也会移除它们。
- 不兼容：原生 MCP 配置里指向 `crewmesh.space_bridge` 的条目需要按 Skill 重新配置；自托管服务的 `CREWMESH_*` 环境变量和默认数据库文件名 `crewmesh.sqlite3` 需改为新名字。

以下为改名前的发布记录，资产文件名保持原样。

## 0.6.0rc2 — 邀请信息候选版（2026-10-15）

在 0.6.0rc1 之上加入一次粘贴就能加入的邀请信息。真人双机验收仍未进行，清单已改为用邀请信息加入，见 [双机验收](two-machine-acceptance.md)。

已作为预发行版发布：[v0.6.0rc2](https://github.com/Weichenleeeee123/crewmesh/releases/tag/v0.6.0rc2)，发行提交 `bc8f1eb`，[CI](https://github.com/Weichenleeeee123/crewmesh/actions/runs/38683997616) 通过。资产都从该提交的干净 `git archive` 构建；全新环境安装 wheel 后冒烟通过（p2p 主机生成中文邀请信息，成员把整段信息经标准输入加入并可连通，同一信息第二次使用被拒绝），发布后下载复验 SHA256 与本地构建一致。用真实 agent 按邀请信息完成安装加入的验收，需要在本版发布后进行，尚未执行。

| 资产 | SHA-256 |
| --- | --- |
| `crewmesh-0.6.0rc2-py3-none-any.whl` | `feedaa97c4744b32293b68367f113f4db3f3b9e8c2e4d027eb03e210530b7e37` |
| `crewmesh-0.6.0rc2.tar.gz` | `16531a53f3deb92c5cb02b77710e8b0f910f18588f610be405dee8111fcd3fb0` |
| `crewmesh-0.6.0rc2-deploy.zip` | `f9c16bd0a2d01b78ecfe008b17f70d0fe4d2331e98abfdad6ce88d39f85a8ff9` |

- 邀请信息：`space_runtime invite --message en|zh` 生成一段可直接转发的文字，包含一句话介绍、项目与 Skill 链接、给对方 agent 的指令和一次性邀请码 `crewmesh-invite-1.…`。对方把整段贴给自己的 agent，由 `join --invitation-code-stdin` 从标准输入读取并加入；邀请码不进命令参数，解析失败只返回固定的、不含输入内容的原因。
- 邀请有效期可设：`--hours 1-72`，默认仍为 1 小时；领域操作 `invite` 新增可选整数字段 `hours` 并校验范围。
- 首页按"Claude Code 和 Codex 的多人模式"重写（英文为主，另有中文版），新增 SECURITY.md，账号服务内容迁至 [自托管服务](self-hosted-service.md)。

## 0.6.0rc1 — 点对点异地入口与 Agent 唤醒候选版（2026-10-14）

首个公开的 Agent 承载空间预发行版，包含下面 0.5.0rc1 记录的全部内容（0.5.0rc1 未单独发布）。真人双机、双方都在家用/移动 NAT 后的验收尚未进行，清单见 [双机验收](two-machine-acceptance.md)。

已作为预发行版发布：[v0.6.0rc1](https://github.com/Weichenleeeee123/crewmesh/releases/tag/v0.6.0rc1)，发行提交 `27f7791`，[CI](https://github.com/Weichenleeeee123/crewmesh/actions/runs/38547959892) 通过。资产都从该提交的干净 `git archive` 构建；全新环境安装 wheel 后冒烟通过，发布后下载复验 SHA256 并安装成功。

| 资产 | SHA-256 |
| --- | --- |
| `crewmesh-0.6.0rc1-py3-none-any.whl` | `caae9c53f26e4d9a67b8efe3b205965d666000f3a8e0ac2c99dd239c4697769b` |
| `crewmesh-0.6.0rc1.tar.gz` | `1e5c482fc4fdae3a33e8506ea71318bdf02637eda90ecd834b1c15a895c23c06` |
| `crewmesh-0.6.0rc1-deploy.zip` | `1dc0629c32c3fdf6222d82c0cb3e2092b43fec5551e6cc4e0839bd3df0a8b6f6` |

- 本机空间默认 `--network p2p`：成员按主机公钥经 iroh 直连，失败时走加密中继；无需公网地址、账号或隧道程序，主机重启后邀请与成员 profile 仍有效。
- 成员链路绑定与主机相同的回环端口，HTTP/MCP/WebSocket 与 Host/Origin 校验不变；`space` 依赖组加入 `iroh==1.1.0`。
- 跨网络产品验收（GitHub Actions 主机 ↔ 本机成员）通过：加入、MCP 桥接、实时事件、主机重启自动恢复。双方都在家用/移动 NAT 后、境内无代理连通性未验证。见 [p2p 报告](agent-hosted-p2p-report.md)。
- 可选唤醒 hook：Claude Code 用 `asyncRewake` 在会话空闲时唤醒；Codex 每轮结束检查，并可由用户开启待命。`crewmesh.space_wake` 负责安装、关闭、待命开关和状态查询，合并现有配置并保留备份。
- 共享核心新增 agent 操作 `wake_digest`：只返回需要该成员处理的请求、回复和交接的编号，不含正文，也不写入已读。
- 每个事项只唤醒一次（跨会话），至少间隔 60 秒、每小时最多 12 次，并合并短时间内的多个事项；唤醒提示是只含计数的固定模板。
- 监听在会话进程退出、被更新的监听接管、hook 超时前或无界面运行时都会退出，不会留下孤儿进程去抢事项。
- 真实 Claude Code 与 Codex 原生验收通过，详见 [Agent 唤醒](agent-wake.md)。

## 0.5.0rc1 — Agent 承载空间候选版（2026-10-12）

- 无账号的本机空间、个人单次邀请、成员撤销、保留数据的重启恢复；主机控制端口与公网协作端口分离。
- 两版共用协作核心、HTTP/MCP 操作与事务内持久事件；WebSocket 提供失效通知、认证撤销和游标重放。
- `crewmesh-space` Skill、私有 stdio 桥接、并发有界事件缓存；人类管理使用明确授权的独立 helper。
- 可选主机本地只读看板与托管看板共用卡片、自动分列和实时客户端；查看不改变消息消费状态。
- 本机使用 `space` 依赖组，完整服务继续使用 `service`；支持经校验的第三方临时隧道或已有 HTTPS，维护者不运营中继。
- 真实 Claude/Codex 与单机公网双成员协作已有独立证据；真实异地双机、稳定公网服务和闲置模型自动唤醒未作为通过项。完整结果见 [本轮发行报告](agent-hosted-release-report.md)。

## 0.4.0rc1 — C2 代码与测试候选版（2026-10-11）

- 可选 cloud 固定月付 Team 订阅，Free / Team 活跃账号成员与绑定项目事务限额；完整 MIT 自托管和无订阅 cloud 保持 Unlimited。
- 持久 billing ledger、出站 idempotency keys、签名 raw webhook、规范当前 invoice/payment/退款/争议核验、backoff/lease 与 bounded 维护 CLI。
- 账号中心 Plan & billing、实际 Price/用量、owner 付款操作、Cookie/CSRF 和失效响应/跳转保护。
- 可选 `deploy/compose.cloud-billing.yaml` 明确要求账号 OAuth、Stripe mode/Price/受保护文件和四项 cap；默认 Compose 不要求提供方密钥。
- 默认自托管 Docker/Caddy TLS smoke 增加 Unlimited、禁用付款、Billing/Git 资产与重启/恢复验证；当前实际结果由 [C2 报告](commercial-c2-report.md) 记录。
- 尚无真实 Stripe 账号/Price/付款、外部 webhook、真实 OAuth 或 C3 官方运营验收；保留 v0.2.0 / v0.3.0rc1 既有发行资产，不宣称付费服务上线。
- 合并以下 Git 仓库集成成果，保留 Billing/Git HTTP、worker 与前端回归共存。

### Git 仓库集成（2026-10-11）

- 本地只读 stdio MCP 适配器，版本化项目约定、实际变更检查点、事务离线队列与精确路径重叠。
- 独立只读 GitHub App，项目管理者授权及负责人 agent 关联提交/分支/PR；签名持久队列、当前 HEAD 检查、限流与补偿同步。
- 看板展示独立证据来源和新鲜度，关联远端状态自动分列；仓库接入与任务详情支持配置及关联。
- 真实本机双克隆、HTTP/stdio 与浏览器验证；真实 GitHub App、跨电脑和公网验收仍待配置。详见 [报告](git-integration-report.md)。

## 0.3.0rc1 — C1 候选版（2026-10-11）

- 完整 MIT 开源账号、团队与多项目入口；自托管本地密码登录、首次密钥初始化和邀请注册，不依赖官方网络或许可服务。
- 七天账号 Cookie 会话、Origin / CSRF 校验、显式项目授权、成员角色管理、会话与成员撤销。
- 历史项目通过有效 owner 网页凭据认领，保留数据及历史协作者身份。
- 配置后可启用 cloud GitHub OAuth；真实提供方登录尚未验收。
- 增加本机文件权限授权的离线密码恢复 CLI；保留备份、新路径恢复和项目 MCP 工作流。
- 当前验收结果及外部阻塞见 [C1 报告](commercial-c1-report.md)。C2 支付与 C3 官方运维尚未交付；保留既有 v0.2.0 发行资产。

## 0.2.0 — 2026-10-11（预发行）

- 增加显式 HTTPS 公网配置、严格 Host / Origin 检查、独立管理员建房密钥和代理信任。
- MCP 保留认证与 DNS rebinding 保护，新增数据库就绪检查。
- 非 root Docker 镜像、Caddy TLS、Compose 持久卷、固定镜像 digest 与运行依赖、GitHub CI。
- 在线 SQLite 一致备份和新路径恢复，拒绝覆盖既有数据。
- 单机多成员抢占、离线请求与重启持久化验收；真实 TLS 容器验收；打包安装验证。
- MIT License 与仓库 Topics。
- Claude 原生正式服务单向接入通过；Codex 原生 MCP 调用取消仍待解决，完整双向闭环与真实公网部署未验收。

## 0.1.0

本机认证 HTTP / MCP、任务与成员、技术请求、不可变约定版本、人工决定与自动任务看板。
