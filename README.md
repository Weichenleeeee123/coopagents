# Crewmesh · 同频

Your agents. One team. / 各自开工，始终同频。

帮助各自使用 Claude Code 和 Codex 的队友共享分工、交换技术信息并跟踪依赖。本机版本包含认证 MCP 服务和网页工作台：任务认领、进展、范围提示、技术请求与人工审核约定。跨电脑部署与原生自动检查点稳定性留待 P4 验证。

在本目录运行 `& .\.venv\Scripts\python.exe -m crewmesh.server`，打开 <http://127.0.0.1:8787/>。首次安装、接入与备份见 [运行说明](docs/app-running.md)。

所有持续维护的设计、计划、运行说明和验证记录统一存放在 [docs/](docs/README.md)，随代码分阶段提交。

此目录就是项目仓库根目录，正式代码直接放在 `src/`。

```text
.
├── src/                         # 正式 Python 源码与 static/ 网页资源
├── tests/                       # 领域、HTTP/MCP 与网页回归测试
├── docs/                        # 设计、计划和验证记录
├── experiments/agent-integration/ # 原生 agent 接入实验
├── pyproject.toml               # 包配置与依赖声明
├── CONTRIBUTING.md              # 环境、测试和提交说明
├── AGENTS.md                    # 仓库工作约束
├── .venv/                       # 当前本机环境，Git 忽略
└── .local/                      # 本机数据、证据与归档，Git 忽略
```

开发命令见 [CONTRIBUTING.md](CONTRIBUTING.md)，任务安排见 [后续路线](docs/roadmap.md)，原生接入步骤见 [实验说明](docs/integration-lab.md)。历史实验源码包归档在 `experiments/agent-integration/archive/`。
