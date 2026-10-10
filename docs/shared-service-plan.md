# Crewmesh 最小共享服务 Implementation Plan

> **For agentic workers:** Use subagent-driven-development task by task, with spec review before quality review. Follow the user's no-file-deletion rule and phase-by-phase Git commits.

**Goal:** 给来自不同电脑的成员和 agent 提供带身份的房间、唯一任务归属与可恢复技术协作；本轮先实现身份与任务认领的领域基础。

**Architecture:** Python 标准库 SQLite 领域服务，短连接、外键和服务端事务保证隔离与竞争安全。HTTP API 和 MCP 共用领域服务，由服务端凭据解析成员；网页凭据与 agent 凭据分开。领域基础先在本机测试，不开放网络或修改现有实验服务。

**Tech Stack:** Python 3.13、SQLite、unittest；后续传输采用已有官方 MCP SDK。网页 API 和部署方式在入口任务中确定，不提前绑定托管平台。

## 目录与职责

```text
src/__init__.py          # 包入口
src/database.py          # 短连接、事务、共享 schema
src/errors.py            # ValidationError / AccessDenied / NotFound / Conflict
src/identity.py          # 房间、成员、散列凭据及撤销
src/tasks.py             # 创建、查看、原子认领任务
tests/test_identity.py            # 隔离、权限、凭据、持久化测试
tests/test_tasks.py               # 并发认领、幂等、冲突及权限测试
docs/shared-service-report.md     # 已实现能力、测试和边界
```

测试使用 `.local/test-evidence/identity-<uuid>.sqlite3` 和 `tasks-<uuid>.sqlite3`，始终保留，不使用自动清理临时目录。领域包暂不依赖实验虚拟环境，运行命令在仓库根目录执行：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

先按 CONTRIBUTING.md 安装项目环境；无需设置 PYTHONPATH，不修改用户全局设置。`.local/` 数据不提交 Git。

## Task 1：房间、成员和分离的凭据

**Files:** 创建 database.py、errors.py、identity.py、包入口与 test_identity.py。

接口约定：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Principal:
    room_id: str
    member_id: str
    display_name: str
    role: str                # owner / member
    kind: str                # web / agent

# IdentityStore(path) 初始化持久化 schema。
# create_room(name, owner_name) -> {room_id, member_id, web_token, agent_token}
# add_member(owner_web_token, display_name) -> 同上
# authenticate(token, required_kind=None) -> Principal
# list_members(token) -> 本房间成员字典列表（无凭据字段）
# revoke_agent(web_token, member_id) -> None
# resolve(connection, token, required_kind=None) -> Principal
# resolve 是内部事务接口，让后续写操作在同一事务内检查凭据。
```

身份必须由随机凭据解析，HTTP/MCP 不从 `author` 参数确定身份。令牌使用 `secrets.token_urlsafe(32)`，数据库只存 SHA-256 摘要；明文仅在创建结果中返回。成员 ID 与房间 ID 使用 UUID。这里的网页身份代表持有者，不宣称已完成邮箱或第三方账号认证。

建房时创建一个 owner 成员及独立 web/agent 令牌。只有本房间 owner 的 web 令牌能增加成员；普通成员的 web 令牌能撤销自己的 agent 凭据，owner 能撤销本房间其他成员的 agent 凭据。任何 agent 令牌不能添加成员或撤销凭据。邀请兑换、凭据轮换和浏览器登录会话在入口阶段实现，不把此层的成员创建结果直接当作公共邀请链接。

schema 使用 rooms、members、credentials 三张表；成员外键关联房间，凭据外键关联成员。credentials 保存 kind、token_hash、revoked_at，不重复保存客户端可写的 room_id。解析身份通过 JOIN 成员获得房间；角色和值使用 CHECK 约束。所有连接设置 foreign_keys=ON，写事务使用 BEGIN IMMEDIATE，退出关闭连接；任何异常回滚。

- [x] **Step 1：编写行为测试。** 覆盖无效/空凭据、身份解析、web/agent 分离、agent 无法管理、owner/普通成员权限、跨房间不可见、撤销与重开数据库后仍有效的记录、SQLite 文件无明文凭据。核心例子：

```python
def test_agent_cannot_add_member(self):
    room = self.store.create_room('hackathon', 'Alice')
    with self.assertRaises(AccessDenied):
        self.store.add_member(room['agent_token'], 'Bob')
    self.assertEqual(len(self.store.list_members(room['web_token'])), 1)
```

- [x] **Step 2：执行 identity 测试确认缺少实现导致失败。**

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_identity.py -v
```

- [x] **Step 3：实现上述接口与事务。** 名称去掉首尾空白，要求 1–120 字符；无效输入使用 ValidationError，不回显凭据。不存在或撤销的凭据用 AccessDenied；跨房间目标成员用 NotFound，不泄露目标房间。示例中的 helper 实际实现须符合以下散列约定：

```python
import hashlib
import secrets

def issue_token():
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    return token, digest
```

- [x] **Step 4：运行全部 identity 测试，检查独立事务与关闭连接。** 预期全部通过；错误权限尝试不得增加成员或使他人的凭据失效。
- [x] **Step 5：先规格审查，再代码质量审查；修复后验证并提交 identity 阶段。**

## Task 2：原子任务认领

**Files:** 创建 tasks.py、test_tasks.py；扩展 database.py schema 和共享服务报告。

```python
# TaskStore(identity_store)
# create_task(web_token, intent_key, title, scope) -> task dict
# list_tasks(token) -> 本房间任务 dict 列表，按 ID 升序
# claim_task(agent_token, task_id) -> task dict
# task dict: id, room_id, intent_key, title, scope, state,
#            owner_member_id, created_at, claimed_at
```

只有 web 令牌能创建任务，只有 agent 令牌能认领；两种凭据都能查看自己的房间。任务 state 只在本阶段支持 `open` / `claimed`，认领表示归属声明，不表示正在开发。scope 是长度限制的模块说明字符串，不用于执行文件操作。TaskStore 和 IdentityStore 共用一个 Database；认领时在同一个 BEGIN IMMEDIATE 事务内解析身份、读取任务、写入负责人，避免凭据检查和写入之间的撤销竞争。

tasks 以整数 ID 为主键，room_id 外键关联房间，owner_member_id 关联同一房间成员；`UNIQUE(room_id,intent_key)` 保证相同意图只建一条任务。成员和房间匹配必须由复合外键或等价约束保证。intent_key 去首尾空白，1–200 字符；title 1–200，scope 1–500。相同 key 与相同 title/scope 返回原任务；同 key 不同内容用 Conflict。此为精确重复，不宣称语义重复识别。

- [x] **Step 1：写任务测试。** 覆盖跨房间隐藏、web/agent 创建与认领权限、相同意图幂等、同 key 不同内容拒绝、同成员重复认领返回同一归属、撤销凭据不能认领、独立连接四个成员同时认领只有一个成功。
- [x] **Step 2：运行测试确认缺少任务实现而失败。**

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_tasks.py -v
```

- [x] **Step 3：实现任务接口。** 找不到本房间任务时统一 NotFound。已由另一个成员认领时 Conflict，异常的结构化 owner_member_id 只针对已核实属于调用方房间的任务返回。不自动抢占、更换负责人或释放任务。原子更新必须包含 room_id 和未认领条件：

```sql
UPDATE tasks
SET owner_member_id = ?, state = 'claimed', claimed_at = ?
WHERE id = ? AND room_id = ? AND owner_member_id IS NULL;
```

- [x] **Step 4：执行身份和任务测试。** 检查并发失败方拿到本房间冲突、最终数据库只有一个负责人，重复请求不更改认领时间。
- [x] **Step 5：两阶段审查，验证并单独提交任务认领阶段。** 报告只写领域实现通过，不写 MCP、网页或双机已完成。

## 后续工作包的明确验收

以下工作包在各自开始前细化代码级计划；本轮不将未实现 API 或 UI 写成完成。

| 工作包 | 实现与验收 |
| --- | --- |
| 会话与范围提示 | 登记成员绑定的工具/入口、仓库、分支、更新时间；同房间模块前缀重叠返回依据；仅提示，不锁文件；连接活跃不自动改任务为执行中 |
| 技术消息 | 请求绑定接收成员与上下文版本；request_key 在发送成员内幂等；接收者分页取消息；读取证据和处理确认分开；响应不会直接关闭请求；服务重启及离线恢复后消息仍在 |
| 人工决定 | 提案版本不可变；批准需要 web 身份及明确当前版本；同版本并发批准唯一；旧版本回复不解决新问题；每次状态变更有来源事件与时间 |
| HTTP/MCP | HTTP bearer 校验绑定身份；agent 接口不接受管理权限或伪造发送者；无效/过期/撤销拒绝；每房间接口隔离；真实 HTTP 测试覆盖越权、冲突与重试；本地默认监听 loopback |
| 网页与共享部署 | 在真实 API 上制作加入、团队任务、问题和决定页面；随后选择 HTTPS 部署方式，配置两台电脑的原有 agent；发布前完成具体可审阅结果与批准 |

## 完成记录

本计划在源码实施前提交。Task 1 与 Task 2 已实现并通过两阶段审查，25 项测试全部通过；Git 提交号进入 [共享服务验证报告](shared-service-report.md)。
