# 开发说明

正式 Python 源码直接放在 `src/`，网页资源在 `src/static/`，行为测试在 `tests/`，持续维护的文档在 `docs/`。原生接入实验在 `experiments/agent-integration/`，不与产品源码混用。

本机 agent 承载空间和托管服务共用 `CoordinationService`、领域存储、HTTP/MCP 操作及 WebSocket 事件。入口差异集中在 `space_runtime.py` / `space_server.py` 和账号组合层；修改任务、消息、约定或权限时只修改共同领域实现。开发本机入口见 [本机空间运行](docs/agent-hosted-runtime.md) 和 [实施计划](docs/agent-hosted-implementation-plan.md)。

## 本地环境

在仓库根目录使用 Python 3.11 或以上版本：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".[service]"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

领域包只使用 Python 标准库；仅开发领域代码时可以用 `pip install -e .`。完整测试和正式服务使用 `service` 依赖组；仅运行原生接入实验可用 `integration` 组。依赖声明以 `pyproject.toml` 为准。正式启动与备份见 [本机运行](docs/app-running.md)。

`pyproject.toml` 将逻辑包名 `coopagents` 映射到 `src/`，不增加同名物理子目录。安装后直接 `import coopagents`，无需手动设置 `PYTHONPATH`。实验脚本仍从实验目录运行，接入步骤见 [实验说明](docs/integration-lab.md)。

## 数据与提交

`.local/` 保存本机测试数据库、实验数据和迁移归档；`.venv/` 保存当前环境。两者均不提交 Git。实验生成的 agent 配置同样不提交。

按功能阶段提交源码、测试和文档，不提交令牌、机器配置或真实会话记录。**永远不要删除任何文件**；若确需删除，停止并由用户执行。测试产生的数据库和证据始终保留，禁止使用自动清理的临时目录。

## 发行验证

发行依赖固定在 `deploy/constraints.txt`，完整安装可使用 `pip install -c deploy/constraints.txt -e '.[service]'`。GitHub CI 覆盖 Python 3.11 / 3.13、网页脚本、发行包、镜像与 TLS smoke。

本地容器验收：`docker build -t coopagents:0.7.0rc1 .`，然后 `python scripts/deployment_smoke.py --image coopagents:0.7.0rc1`。需要运行的 Docker 引擎；测试只停止自己的容器并保留证据。原生 CLI 验收入口为 `experiments/agent-integration/p4_native_check.py`，需要已认证的实际工具，失败不能用模拟数据代替。

候选版 0.4.0rc1 的默认自托管 TLS smoke 同时覆盖账号、项目、MCP、禁用订阅的 Unlimited/实际用量、付款操作拒绝、Billing/Git 静态资源及重启/恢复。Docker CLI 存在不等于 Engine 可用；执行失败必须保留原始失败记录，不沿用历史版本通过结果。

网页回归入口（需 Node）：

```powershell
node tests/web_session_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
node tests/git_ui_regression.js
```

默认与可选覆盖配置均使用 `docker compose ... config --quiet` 验证，避免输出展开配置和密钥路径。覆盖文件缺少任一 OAuth/Stripe/cap 必填项必须失败；可用保留在独立 `.local/` 目录的明确合成 env 验证语法，不能视作真实 OAuth/Stripe 验收。

部署、密钥及备份恢复见 [部署与运维](docs/deployment.md)、[C2 运维](docs/c2-operations.md)，当前验收边界见 [C2 报告](docs/commercial-c2-report.md)，历史记录保留于 [P4 报告](docs/p4-release-report.md)。
