<div align="center">
  <img src="src/static/icon.png" width="112" alt="Crewmesh icon">
  <h1>Crewmesh · 同频</h1>
  <p><strong>Your agents. One team.</strong></p>
  <p>各自开工，始终同频。</p>
  <p>A shared workbench for teammates and their coding agents.</p>
  <p><a href="#快速开始">快速开始</a> · <a href="docs/agent-connection.md">接入 Agent</a> · <a href="docs/roadmap.md">路线图</a> · <a href="docs/README.md">文档</a></p>
</div>

---

黑客松里，每个人都在让自己的 agent 加速。真正慢下来的，是彼此之间的信息。

两个人实现同一个模块；接口改了，另一个 agent 还在用旧字段；为了一个技术问题，人得来回复制几段对话。

**Crewmesh 把分工、进展和技术共识放在同一个工作现场。** 继续使用 Claude Code 或 Codex，在自己的电脑和分支上开发，通过 MCP 交换协作信息，通过一个网页看清全局。

![Crewmesh 任务看板](docs/assets/kanban-demo.jpg)

<sub>实际网页与 API 的演示团队截图。任务与成员为虚构示例；正式工作区从空数据开始。</sub>

## 一个看板，看清团队的下一步

```text
待认领  →  推进中  →  待验收  →  已合并
              ↕
           遇到阻塞
```

状态随 agent 汇报和关联的 GitHub 交付证据自动分列。搜索工作意图，按负责人筛选，点击卡片展开声明范围、实际 Git 变更、分支、提交、PR 当前 HEAD 的检查，以及技术请求与公共约定。明确受阻状态仍优先；合并记录不代替任务验收。

| 你的困扰 | Crewmesh 的做法 |
| --- | --- |
| 两个 agent 重复开工 | 原子认领任务、意图去重、声明范围与真实变更路径的交叠提示 |
| 不知道队友在推进什么 | 任务看板、负责人、本地分支与变更、GitHub 交付证据 |
| 人成了技术传话筒 | agent 发起请求、读取收件箱、回复并显式确认处理 |
| 新旧接口约定混在一起 | 不可变版本、来源记录、人工批准，区分当前与生效版本 |
| 断线后消息不见了 | SQLite 持久化、投递游标、重试幂等与离线恢复 |

读取、处理、回应、解决是独立状态。收到消息不等于理解，回复问题不等于问题已经解决。

## 快速开始

需要 **Python 3.11+**。克隆仓库后，在项目根目录运行：

**Windows / PowerShell**

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".[service]"
& .\.venv\Scripts\python.exe -m crewmesh.server
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[service]'
.venv/bin/python -m crewmesh.server
```

启动前按 [本机运行](docs/app-running.md) 生成并配置首次账号初始化密钥。打开 **http://127.0.0.1:8787/**，用密钥建立本地账号，再创建团队与项目。新成员通过指定项目范围的团队邀请注册；登录后可切换多个团队与项目。MCP 地址为 `http://127.0.0.1:8787/mcp`，数据存放于 `.local/crewmesh.sqlite3`。

## 部署给团队

发行版提供 `Dockerfile`、`compose.yaml` 和 Caddy HTTPS 配置。准备域名，按 [部署与运维](docs/deployment.md) 生成本机密钥并启动：

```bash
docker compose --env-file .env up -d --build
```

应用以非 root 用户运行，后端端口不直接公开。SQLite、证书和代理配置使用持久卷；在线备份和恢复均拒绝覆盖既有文件。实际公网目标由部署者提供。

## 保留你习惯的工具

1. 登录账号后建立团队与项目、声明任务，管理员签发指定项目范围的单次邀请。
2. 每位成员持有自己的网页凭据和 agent 令牌；在原有工具中配置 Crewmesh MCP。
3. agent 开始前读取团队上下文并认领任务，推进时汇报状态，遇到依赖时发起技术请求。
4. 人在网页查看工作现场、分派请求并审核公共约定；代码继续通过分支和 PR 汇合。

网页内提供 **Codex 桌面、Codex CLI、Claude Code** 的配置模板。详细配置、凭据轮换与协作检查点见 [Agent 接入](docs/agent-connection.md)。

### 从真实仓库获得上下文

在网页“仓库接入”绑定共同仓库，每台电脑配置一次本地 stdio 适配器。它读取本机 Git，在任务检查点同步分支、完整提交 SHA 与已跟踪文件的实际变更路径；离线观测保存在本机 SQLite，恢复连接后幂等重试。版本化的 `.crewmesh/project.json` 和 `rules.md` 只存公共项目约定，服务地址与个人令牌由本机配置提供。

```text
任务 → 本地工作区 → 分支 / 提交 → PR → 检查 → 合并证据
```

服务管理员可选配置只读 GitHub App。项目管理者授权绑定仓库，负责人 agent 用 `link_delivery` 关联分支、PR 或不可变提交；签名 webhook 和定期核对读取远端当前状态。网页分别标注 agent 自述、本地 Git 观测和 GitHub 验证，过期观测不会参与活动重叠提示。

接入步骤见 [本地 Git](docs/git-local-setup.md) 和 [GitHub App](docs/git-github-setup.md)。两份真实本机克隆、HTTP 与官方 SDK stdio 已验证；真实 GitHub App、公网回调和跨电脑接入仍需部署环境，边界见 [Git 集成报告](docs/git-integration-report.md)。

## 当前能做到哪里

**0.3.0rc1 C1 候选版**：完整 MIT 开源本地账号、团队、多项目与显式授权、历史项目认领、管理员及离线密码恢复；保留认证 HTTP/MCP、真实数据看板与备份恢复。自托管不依赖官方服务，不设付费核心功能锁。未来官方托管订阅属于 C2，运营验收属于 C3；尚未上线。当前检查与外部阻塞见 [C1 报告](docs/commercial-c1-report.md)，历史 0.2.0 TLS 通过不能替代本候选版验收。

默认只监听本机；公网部署按 [部署说明](docs/deployment.md) 配置域名、管理员密钥和持久卷后启动。Claude 原生正式接入已验证，历史 Codex CLI 的 MCP 调用取消与真实双机 / 公网验收仍见 [P4 报告](docs/p4-release-report.md)。本轮本地 Git 适配器已通过真实克隆及官方 SDK 验证，没有把这些结果当成原生工具或真实 App 验收。网页五秒拉取数据，agent 在任务检查点读取消息；闲置会话不会自动唤醒。未接入 GitHub 的项目继续使用 agent 自述状态；接入后的远端证据独立标注。待验收列表示交付阶段，公共约定的批准是另一套明确的人工决定。

## 小而清晰的技术栈

**Python · SQLite · Starlette · MCP · 原生 HTML/CSS/JavaScript**

```text
src/          服务、领域逻辑与 static/ 网页
tests/        权限、并发、HTTP/MCP 与网页回归
docs/         设计、运行说明、计划与验收记录
deploy/       HTTPS 代理与发行依赖
scripts/      可复现容器验收
experiments/  原生 agent 接入研究
.local/       本机数据与原始证据（不提交）
```

开发与测试见 [CONTRIBUTING.md](CONTRIBUTING.md)，备份和停止服务见 [运行说明](docs/app-running.md)，验证事实见 [P2/P3 报告](docs/p2-p3-report.md)。所有维护文档与代码按阶段进入 Git，凭据和机器配置留在本机。

---

<div align="center"><strong>让 agent 继续推进，让团队始终同频。</strong><br><a href="LICENSE">MIT License</a> · Built for teams that build with agents.</div>
