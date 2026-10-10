# 开发说明

正式 Python 源码直接放在 `src/`，网页资源在 `src/static/`，行为测试在 `tests/`，持续维护的文档在 `docs/`。原生接入实验在 `experiments/agent-integration/`，不与产品源码混用。

## 本地环境

在仓库根目录使用 Python 3.11 或以上版本：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".[service]"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
```

领域包只使用 Python 标准库；仅开发领域代码时可以用 `pip install -e .`。完整测试和正式服务使用 `service` 依赖组；仅运行原生接入实验可用 `integration` 组。依赖声明以 `pyproject.toml` 为准。正式启动与备份见 [本机运行](docs/app-running.md)。

`pyproject.toml` 将逻辑包名 `crewmesh` 映射到 `src/`，不增加同名物理子目录。安装后直接 `import crewmesh`，无需手动设置 `PYTHONPATH`。实验脚本仍从实验目录运行，接入步骤见 [实验说明](docs/integration-lab.md)。

## 数据与提交

`.local/` 保存本机测试数据库、实验数据和迁移归档；`.venv/` 保存当前环境。两者均不提交 Git。实验生成的 agent 配置同样不提交。

按功能阶段提交源码、测试和文档，不提交令牌、机器配置或真实会话记录。**永远不要删除任何文件**；若确需删除，停止并由用户执行。测试产生的数据库和证据始终保留，禁止使用自动清理的临时目录。
