# 贡献指南

[English](../CONTRIBUTING.md)

Coopagents 让不同电脑、不同工具里的 coding agent 围绕同一项目协作。贡献应提供可组合的能力，不要求团队遵守固定流程。配置成功、网络连接、agent 活动与经过验证的交付证据必须分开表达。

## 仓库结构

| 路径 | 职责 |
| --- | --- |
| `src/` | 正式 Python 源码，导入名映射为 `coopagents` |
| `src/static/` | 正式网页工作台与只读看板，原生 HTML/CSS/JavaScript |
| `src/skills/` | 随包分发的接入 Skill |
| `tests/` | 领域、HTTP、连接及 JavaScript 回归 |
| `docs/` | 持续维护的指南、设计、计划与验收记录 |
| `docs/prototypes/` | 设计参照，不是正式前端 |
| `experiments/agent-integration/` | 原生 agent 接入实验 |
| `deploy/` | 部署配置与依赖约束 |
| `.local/` | 不提交的本机数据库、私密证据与运行状态 |

本机 P2P 空间和自托管服务共用 `CoordinationService`、领域存储、HTTP/MCP 操作及实时事件。业务规则应在共同实现中修改；入口差异集中在 `space_runtime.py`、`space_server.py` 和账号组合层。

## 开发环境

使用 Python 3.11+ 和 Node.js（CI 使用 Node 22）。每个 checkout 使用独立环境，显式调用解释器，无需激活。

Windows PowerShell：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -c deploy/constraints.txt -e ".[service,space]" build
& .\.venv\Scripts\python.exe -c "import coopagents; print(coopagents.__file__)"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c deploy/constraints.txt -e '.[service,space]' build
.venv/bin/python -c 'import coopagents; print(coopagents.__file__)'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

先核对输出路径确实属于当前 checkout，避免 editable install 指向另一个 worktree。仅领域代码可用 `pip install -e .`；完整测试需要 `service,space` 两组依赖。依赖声明在 `pyproject.toml`，发行约束在 `deploy/constraints.txt`。

启动参见[本机服务](app-running.md)或[空间运行](agent-hosted-runtime.md)。凭据保存在私密路径，界面实验使用独立的合成数据，不能改真实团队数据库。

## 网页验证

前端无需构建。执行 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 中的 JavaScript 检查，其中以下脚本需要传入源码参数：

```text
node tests/web_session_regression.js src/static/app.js
node tests/agent_connect_ui_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
```

其他 `tests/*_regression.js` 无需参数。修改的浏览器脚本也要用 `node --check <文件>` 检查。界面改动必须在真实浏览器中，对照已确认的[工作台原型](prototypes/project-workspace/index.html)检查桌面与手机布局。结构测试不能代替视觉对照；真实后端、权限、空状态和项目切换都需验证，截图使用合成数据。

## 提交与证据

- 源码、测试和文档按阶段提交，说明用户可见变化及实际运行的检查。
- 持续维护文档放在 `docs/`。README 和贡献指南默认英文，同步维护中文版本。
- 保留无关 agent 配置。配置写入成功不代表当前会话已加载 MCP、信任 hook 或读取消息。
- 不宣称所有 harness 都支持唤醒；在[支持矩阵](harness-adapters-0.9.md)和验收记录中写明实际工具与平台边界。
- 不提交令牌、本机配置、真实对话、测试数据库或原始实验记录。
- **永远不要删除任何文件。** 确需删除时停下来，由仓库所有者执行。数据库和证据始终保留，禁止使用自动清理的临时目录。

## 发行验证

CI 覆盖 Python 3.11/3.13、JavaScript 回归、接入实验、发行包、容器启动和 TLS smoke。按改动运行相应检查，明确未验证的部分。

使用当前环境解释器执行 `<python> -m build`。部署改动需要实际运行的 Docker 引擎：

```text
docker build -t coopagents:local-check .
python scripts/deployment_smoke.py --image coopagents:local-check
```

用 `docker compose ... config --quiet` 检查配置，避免打印展开后的密钥。Docker CLI 存在不等于引擎可用。原生验收必须使用已认证的真实工具；合成数据不能代替模型消费或双机连通证据。

参见[部署与恢复](deployment.md)、[首次配置验收](agent-first-setup-acceptance.md)、[双机验收](two-machine-acceptance.md)和[文档索引](README.md)。安全问题按 [SECURITY.md](../SECURITY.md) 私密报告。
