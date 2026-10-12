# 两版共同协作核心实施计划

> **For agentic workers:** 使用 subagent-driven-development 分任务实施与审查。步骤用复选框记录。此计划只覆盖 L-1，其余阶段按空间设计继续拆分。

**Goal:** 从完整 HTTP 服务中提取共同协作核心，使本机与托管入口使用同一套业务操作和权限。

**Architecture:** 将现有协作 `Service` 与字段验证移到无 HTTP 框架依赖的模块。`api.Service` 保持现有导入与构造接口，在共同核心上组合账号和工作区。Git 领域与可选 GitHub 适配器保持现有行为，不引入新的在线依赖。

**Tech Stack:** Python 3.11+、现有 SQLite 领域模块、unittest；完整服务仍使用原有 Starlette/MCP。

## 文件边界

- 新增 `src/protocol.py`：已有 `validate` 与 `fields`，保持错误文本、严格类型和默认值行为。
- 新增 `src/coordination.py`：`CoordinationService`，现有协作操作、快照、Git 与权限分派。
- 修改 `src/api.py`：导入共同验证函数；兼容 `Service` 子类组合 AccountStore、WorkspaceStore；HTTP、OAuth 与账单路由留在原位。
- 新增 `tests/test_coordination_core.py`：共同核心的领域闭环与完整入口兼容验证。
- 更新本计划、空间设计、文档索引及阶段报告。不得删除文件。

## Task 1：先建立失败测试

- [x] 新增核心独立导入测试；从 `crewmesh.coordination` 导入 `CoordinationService`，未实现时必须失败。
- [x] 在 `.local/test-evidence/coordination-<uuid>/` 保留独立数据库，禁止自动删除。
- [x] 创建空间与成员，创建同一任务，两成员竞争认领；失败方必须得到原有 `Conflict`。
- [x] 验证个人身份、跨空间不可见、agent 不可执行管理操作，消息读取不等于处理完成。
- [x] 验证完整 `crewmesh.api.Service` 仍有账号/工作区接口，并使用共同核心类型与共同验证函数。
- [x] 使用独立 Python 子进程拦截导入，确认共同核心不导入 Starlette、MCP、账单、账号与 OAuth。

测试构造约定：

```python
from pathlib import Path
from uuid import uuid4
from crewmesh.coordination import CoordinationService

path = Path('.local/test-evidence') / ('coordination-' + uuid4().hex) / 'room.sqlite3'
service = CoordinationService(path)
owner = service.call('create_room', None, {'name': 'Room', 'owner_name': 'Owner'})
task = service.call('create_task', owner['web_token'],
                    {'intent_key': 'login', 'title': 'Login', 'scope': 'src/auth'})
```

运行：`& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_coordination_core.py' -v`。初次预期缺少核心模块，不允许以其他异常当作预期失败。

## Task 2：提取共同模块并保持兼容

- [x] 将 `validate`、`fields` 按原逻辑提取至 `protocol.py`，不要改默认值、字典验证或整数/布尔类型判断。
- [x] 将完整协作类提取成 `CoordinationService`；移除其账号与工作区组合步骤，其余操作表、领域类型、调用与快照保持一致。
- [x] 在 `api.py` 中使用兼容组合：

```python
from .coordination import CoordinationService
from .protocol import fields, validate

class Service(CoordinationService):
    def __init__(self, database_path, github_app=None):
        super().__init__(database_path, github_app)
        from .accounts import AccountStore
        from .workspaces import WorkspaceStore
        self.accounts = AccountStore(self.identity)
        self.workspaces = WorkspaceStore(self.accounts)
```

- [x] 保留 `crewmesh.api.Service`、`crewmesh.api.fields` 与 `crewmesh.api.validate` 的兼容访问，现有 MCP 和路由调用方无需变更。
- [x] 定向测试通过后运行完整 Python 回归；如初始化顺序暴露依赖，先查明领域关系再修复，不改变权限规则。

## Task 3：审查与阶段交付

- [x] 检查只存在一个共同操作表，未复制业务逻辑，核心无 HTTP 或商业功能依赖。
- [x] 执行 `git diff --check`，新增定向测试及完整 Python 回归。
- [x] 审查行为兼容性与设计一致性；修复问题后仅重跑相关失败和受影响回归。
- [x] 写入 `docs/agent-hosted-core-report.md`，记录真实测试结果及未实现的联网、实时事件、Skill 和看板阶段。
- [x] 更新任务状态，分阶段提交测试/源码/文档并推送 `feat/agent-hosted-spaces`。不自动合并。

## 后续依赖

L0 先验证第三方隧道的实际可用性；L1 创建/加入入口复用此核心；L2 事件必须进入共同事务边界并覆盖两版；L3 配置原生 MCP 和 Skill；L4 复用看板并验证发行包。每一步详细实施计划在对应阶段开始前补充，不能把本次核心提取当作整个轻量版本完成。
