# Coopagents 1.0 产品设计

日期：2026-10-29。状态：产品方向获用户确认；0.8 正在实施，本文中的阶段验收项在对应证据记录完成前仍属目标，不代表全部实现或验收。

## 产品目标

Coopagents 让多个 coding agent 围绕同一个项目协作，同时保留各自原生工具、账号、工作区和权限边界。主路径是由主机 agent 用一句简短指令创建本机 P2P 空间并生成可私下转发的邀请；队友把邀请原样粘贴给自己的 agent 后即可加入。团队围绕任务协作，并能追溯任务与 Git 交付、共享资产和结构化活动的关系。

产品提供两种部署模式，共用一个协作核心：

| 模式 | 空间和数据位置 | 人的操作界面 | 连接方式 |
| --- | --- | --- | --- |
| 本机 P2P 空间 | 发起人设备 | agent 原生工具；主机可开只读本机看板 | iroh 点对点，直连优先，公共加密 relay 兜底 |
| 自托管服务器 | 用户管理的服务器 | 认证网页 GUI 和 agent 原生工具 | 稳定 HTTPS/WSS/MCP，或由用户选择的网络入口 |

本机 P2P 是默认上手路径。自托管是同一协作领域的部署模式，不是另一套任务、Git 或权限实现；它额外提供账号、多项目和网页管理。用户负责服务器运行、域名、备份和外部凭据，维护者不运营 SaaS 或付款平台。

1.0 首批重点支持七个 harness：Claude Code、Codex、Cursor、OpenCode、Pi、Kimi Code 和 ZCode。支持按能力分层，而不是宣称每个 harness 都有相同的 hook 或唤醒行为：

| Harness | 1.0 基础接入 | 可用的原生扩展面 | 设计约束 |
| --- | --- | --- | --- |
| Claude Code | stdio MCP、Skill、原生配置核验 | session hooks、空闲唤醒 | 延续当前已验证流程 |
| Codex | stdio MCP、Skill、原生配置核验 | Stop hooks、待命 | 延续当前已验证流程和 `/hooks` 信任提示 |
| Cursor | project/user MCP 配置 | hooks（含 session lifecycle）、插件 | 只写当前官方支持的项目或用户配置 |
| OpenCode | local/remote MCP 配置 | plugin hooks、session events | 由官方插件接口补 session identity 和事件映射 |
| Pi | MCP server | TypeScript extension lifecycle、`registerMcpServer` | adapter 通过 Pi extension API 注册，不解析 Pi 私有会话记录 |
| Kimi Code | CLI MCP 配置 | ACP IDE transport | 1.0 保证 MCP CLI 接入；ACP 是可选 IDE 入口，不能把 ACP 本身当成 MCP server |
| ZCode | 配置或插件提供 MCP | 插件/user-level hooks | 当前官方文档说明 project-level hooks 不执行；不得向用户承诺项目级唤醒 hook |

每个 harness adapter 只负责安装/更新 MCP 配置、确认 project root、声明能力和把安全的结构化生命周期事件映射到共同协议。核心任务、权限、Git 关联、资产和活动模型不得复制到 harness 插件里。能力矩阵按具体 harness 与版本报告 `mcp`、`project_context`、`session_lifecycle`、`native_hook`、`idle_wake`；未实际测试的格子保持 unsupported/unknown。

平台目标是 Windows、macOS、Linux，但支持声明以矩阵为单位，不把“CLI 可启动”扩大成“所有 GUI/hook 都可用”。每个宣称支持的组合须至少完成安装/更新配置不覆盖原文件、MCP 握手、身份/项目上下文核验、任务与消息闭环；宣称 native hook 的组合还要单独验证触发、输入字段 allowlist、stdin/stdout 和卸载。CI 测可自动化的 CLI/协议组合；GUI-only 或依赖真实登录的组合保留带版本与证据的人工验收。

## 协作信息模型

项目是协作和 Git 身份的归属单位。任务是 agent 认领、分工、阻塞、交接和验收的主要工作对象。每个协作事实带有空间、项目、任务（适用时）、成员、工具、时间、来源和新鲜度，托管模式与 P2P 模式复用共同领域权限。

任务与 Git 的关系是多对多：

| 对象 | 关联语义 | 状态来源 |
| --- | --- | --- |
| Branch | 一个任务可跨分支，一个分支可承载多个任务 | 本地只读观测或明确关联 |
| Commit | 一个任务可关联多个不可变 SHA；同一 commit 可包含多个任务 | 本地观测或明确关联 |
| Pull request | 一个任务可有多个 PR，一个 PR 可交付多个任务 | GitHub App 只读事实；关联由成员明确建立 |
| Release | 一个 release 可汇总多个 PR/任务；一个任务可进入后续 release | GitHub Release、tag 和目标 SHA；关联须明确或由人确认建议 |

本地 Git 适配器只读分支、HEAD、已跟踪变更路径等事实，不执行用户 hook，不 fetch、push、checkout、commit、merge 或发布。GitHub App 保持只读权限，读取仓库、PR、检查和 release 状态。agent 可建议 `link_delivery` 或 release 关联；对象身份或任务归属不明确时，先由有权限的成员确认，不按分支名称或自然语言静默猜测。

每条 Git 关系区分 `explicit`（人或 agent 通过受权操作明确建立）与 `observed`（本地或 GitHub 只读观测）。候选推断标为 `suggested`，未经确认不得变成正式关系。远端数据展示 provider、对象标识、同步时间和 stale/unavailable 状态；旧检查结果不会覆盖当前 SHA。PR merged 或 Release published 是交付事实，不自动等同于任务已验收、合同已批准或所有工作已解决。

## 活动记录与隐私纪律

**完整对话原文绝不共享。** 这是一条产品纪律，而不是用户偏好开关：Coopagents 不从 Claude Code、Codex 或其他 agent 读取、上传、持久化或展示完整提示词、回复、隐藏推理、工具输入输出、环境变量或上下文。不得以调试、活动时间线或托管同步为由旁路此规则。

共享活动只来自明确的协作操作或明确提交的进度报告，例如：任务创建/认领/状态变化、交接、依赖、合同提案及审批、请求和回复的状态、session/tool/branch 登记、Git 观测、资产分享、PR/release 状态。一个进度说明由 agent 明确调用 `report_progress` 提交，并带任务及证据来源；不是后台从对话中抽取的摘要。活动记录让队友知道谁做了什么、何时发生、依据是什么，但不能声称模型已经读过或处理过一条记录，除非存在对应回执。

不保存逐轮 transcript，也不默认生成逐轮自然语言摘要。看板中的对话能力限于项目内明确发送的协作请求与回复；其正文属于共享的业务消息，单独记录阅读、处理和解决状态，不与 agent 私人会话混为一体。

## 项目资产

资产是成员明确分享给项目的文件或引用，不从工作区自动扫描或同步。项目资产记录至少包含资产 ID、项目、分享者、时间、显示名、媒体类型、字节数和 SHA-256；如来自仓库，还记录 repository、commit SHA 和相对路径。相同 SHA 可去重，但权限仍按项目校验。

读取、下载和撤销遵循成员身份、项目权限及资产生命周期。文件传输使用有上限的请求体，写入前后校验大小和哈希，临时写入后原子提交；拒绝路径穿越、符号链接越界和未知身份。下载默认作为附件，使用安全的内容类型和响应头，不公开可长期转发的 bearer URL。各部署模式的存储根目录、单文件上限、项目配额、保留与备份行为须显式配置或有文档化默认值。

资产注册表同时接受外部引用（commit、PR、GitHub Release asset URL + SHA-256）；外部引用不意味着服务复制或托管该文件。大文件传输不承诺像 P2P 数据同步盘一样后台双向同步。

## Git 与网页体验

任务详情显示 branch、commit、PR、Release 关联和状态来源。项目视图提供按任务、成员、分支、PR、release 筛选的交付时间线，并展示已确认关系和待确认建议。提交只显示已跟踪的安全元数据与路径预览，不上传源码正文。活动时间线和资产列表可以从项目进入，也能回溯到对应任务。

自托管模式的网页 GUI 可以创建/分配任务、查看团队活动、管理项目资产、审核 Git 关联建议、关联 PR/release 和查看验证状态；后端仍执行同一权限规则。agent bridge 提供对应 MCP 操作和必要上下文，不提供任何读取聊天 transcript 的工具。

本机 P2P 空间不对公网开放人类管理 API。主机可用有界、只读本机看板查看同一项目活动、Git 证据与资产目录；创建/分配等人类管理操作仍经过主机本地明确授权的接口或主机 agent 的明确操作。远程 agent 不能因此获得主机管理凭据。

## 分阶段交付

### 0.8：Git 交付关系与项目活动

**实施进度（2026-10-29）：** Release 读取与显式 task-release 关联、结构化有界活动投影及双部署模式 UI 的实现正在当前分支验证。suggested/observed 自动关联审核、release 包含关系推断和真实 GitHub App 线上验收仍未完成；不将其记为已交付。

- 把 branch 纳入 task delivery 图，与 commit SHA、PR 和 GitHub Release 建立多对多关系；延续本地 Git 与 GitHub 两套明确来源。
- 在 GitHub 只读适配器中同步 release/tag/目标 SHA/发布时间及安全的资产元数据；任务与 release 使用明确的多对多关联。0.8 不以自然语言、日期或 tag 相似度推断包含关系。
- 提供 `suggested`/`explicit`/`observed` 关联来源，处理分支改名、force-push、PR 重定向或关闭、release 更新、检查截断和陈旧证据；不自动更改任务验收状态。
- 扩展自托管 GUI 与本机只读看板，在 task/project 视图展示 Git 交付图和结构化活动。
- transcript 禁止进入数据库、MCP 工具、webhook 队列、日志或 UI；新增隐私回归直接尝试注入伪造 prompt/response 字段，确认被拒或忽略。

**0.8 验收：** SQLite 增量迁移保留既有记录；离线 provider 覆盖 commit/branch/PR/release 关系、多任务共用 PR、release 包含关系、陈旧和撤销；真实本地双克隆关联；网页/MCP 显示相同来源；GitHub App 保持最小只读权限。真实 App 暂缺时，不能把离线 provider 写成线上 GitHub 验收。

### 0.9：共享资产与自托管网页协作体验

- 增加明确分享的项目资产、hash/元数据、受权读取和下载；项目中同时显示本地路径、不可变 commit 引用、PR 或 Release asset 引用。
- 活动时间线区分协作事件、agent 明确报告的进度和 GitHub 远端事实；实现筛选、来源/新鲜度标识及任务回溯。
- 自托管网页支持项目资产管理与 Git 交付关系审核，P2P 本机看板仍保持无远程管理面的安全边界。
- 为本机空间和自托管部署提供同一领域 API；存储适配器按 host-local data root 或自托管配置组合。

**0.9 验收：** 文件大小/配额/哈希/权限/成员撤销/重启恢复/备份恢复回归；绝不递归扫描上传仓库；未经明确分享的文件不可见；全文 transcript 跨 API、DB、日志和浏览器测试均不存在；真实浏览器测试项目切换、撤销和过期状态。

同时建立统一 harness adapter contract，并完成 Cursor、OpenCode、Pi、Kimi Code、ZCode 的 MCP 基础接入。各 adapter 只支持该 harness 官方允许的安装范围；没有官方 lifecycle/hook API 的保持 MCP-only。每个实现都必须在启动样例中验证 agent、项目、工具版本和能力报告。

### 1.0：稳定版与真实部署验证

- 冻结新功能，完成领域/HTTP/MCP/UI 测试、升级迁移、发行 wheel/sdist、部署资产、备份恢复和安全审查。
- CI 覆盖 Linux Python 3.11/3.13、Windows native hook、macOS package/import 和容器运行。
- 对 Claude Code、Codex、Cursor、OpenCode、Pi、Kimi Code、ZCode 发布逐组合 capability matrix；七个 harness 的基础 MCP 邀请/接入/任务/消息流程有可审计结果，native hook 与自动唤醒只对通过原生验收的组合标为支持。
- 在 Windows、macOS、Linux 上分别验证各受支持 CLI 安装配置与 MCP 传输；平台或 harness 不提供稳定官方 hook 时，明确降级到 MCP 检查点，不模拟出自动唤醒。
- 真实双设备验收至少覆盖 home device ↔ 有公网地址 server/VPS 的加入、任务/Git/资产/重启恢复；双方 NAT 或 CGNAT 另记 direct/relay 结果。若无法覆盖双方 NAT，不将该场景写成已支持保证。
- 真实 GitHub App 在专用测试仓库完成 install、branch push、PR checks、release/tag、撤权和恢复验证；agent 无发布/合并权限，除非用户明确赋权。
- 发布说明准确写明任何尚未覆盖的操作系统、网络拓扑、GitHub 组织策略和服务器环境。

**1.0 验收：** 两种部署模式都通过同一协作合同；没有未关闭的 P0/P1 缺陷；上表核心场景有真实的环境证据；原始凭据与 transcript 均未进入发行资产。

## 不在这三个阶段内

- 分享或同步完整 agent 对话原文、hidden reasoning 或任意 tool transcript：禁止。
- 自动运行用户命令、自动创建/合并 PR、自动发布 GitHub Release。
- 维护者代管的云服务、计费体系或公共文件云盘。
- 无限制的大文件 P2P 同步、自动递归仓库上传、任意 URL 抓取。
- 用同机多进程或单个高可达 VPS 的测试声称双方 NAT/CGNAT 已覆盖。

## 官方 harness 接口依据

- [Cursor MCP](https://cursor.com/docs/context/mcp) 与 [Cursor hooks](https://cursor.com/docs/agent/third-party-hooks)
- [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/) 与 [OpenCode plugins](https://opencode.ai/docs/plugins)
- [Pi MCP servers](https://pi.dev/docs/latest/mcp) 与 [Pi extensions](https://pi.dev/docs/latest/extensions)
- [Kimi Code MCP](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html) 与 [Kimi ACP](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-acp.html)
- [ZCode MCP](https://zcode.z.ai/en/docs/mcp-services) 与 [ZCode hooks](https://zcode.z.ai/en/docs/hooks)

