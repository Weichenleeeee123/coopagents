# Crewmesh · 同频

Your agents. One team. / 各自开工，始终同频。

帮助各自使用 Claude Code 和 Codex 的队友共享分工、交换技术信息并跟踪依赖。原有入口的本地消息链已通过，共享服务已有身份与原子任务认领的领域实现；网页与跨电脑传输尚未实现。

所有持续维护的设计、计划、运行说明和验证记录统一存放在 [docs/](docs/README.md)，随代码分阶段提交。

此目录就是项目仓库根目录，正式代码直接放在 `src/`。

```text
.
├── src/                         # 正式 Python 源码
├── tests/                       # 领域行为测试
├── docs/                        # 设计、计划和验证记录
├── experiments/agent-integration/ # 原生 agent 接入实验
├── pyproject.toml               # 包配置与依赖声明
├── CONTRIBUTING.md              # 环境、测试和提交说明
├── AGENTS.md                    # 仓库工作约束
├── .venv/                       # 当前本机环境，Git 忽略
└── .local/                      # 本机数据、证据与归档，Git 忽略
```

开发命令见 [CONTRIBUTING.md](CONTRIBUTING.md)，任务安排见 [后续路线](docs/roadmap.md)，原生接入步骤见 [实验说明](docs/integration-lab.md)。历史实验源码包归档在 `experiments/agent-integration/archive/`。
