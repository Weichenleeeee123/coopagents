# Agent-first 首次配置与 Doctor 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Coopagents 提供不依赖网页的首次 agent 接入与只读 doctor 诊断，让用户在当前仓库只需表达目标，agent 就能完成安全配置并准确说明连接状态。

**Architecture:** 新建纯 Python 诊断模块，统一检查项结构和 overall 状态；CLI 负责解析环境、原生配置、profile、网络和 challenge round-trip；既有 create/join/connect 在写入成功后复用同一诊断结果。Skill 负责按 invitation、已有项目资料、既有配置或无上下文四种情况路由。不改网页。

**Tech Stack:** Python 3.11 标准库、现有 MCP/HTTP/P2P 实现、unittest、Node 回归。

---

## 文件职责

- Create: `src/onboarding_doctor.py` — 诊断结果 schema、聚合状态、只读本地和 profile 检查。
- Modify: `src/space_connect.py` — 公开无副作用的 native entry / Skill 只读检查函数，供 doctor 复用。
- Modify: `src/space_runtime.py` — doctor CLI、profile 远端身份和挑战诊断、接入后结构化结果。
- Modify: `src/skills/coopagents-space/SKILL.md` — agent-first 意图路由、依赖安装、默认 P2P 创建、状态解释。
- Modify: `src/skills/coopagents-space/protocol.md` — doctor CLI 契约、安全输出、恢复流程。
- Create: `tests/test_onboarding_doctor.py` — 状态聚合和只读本地检查的行为测试。
- Modify: `tests/test_space_connect.py` — native entry 和 Skill 检查的行为回归。
- Modify: `tests/test_space_runtime.py` — doctor 命令、身份、网络、challenge 和安全输出回归。
- Create: `docs/agent-first-setup.md` — 英文默认使用指南。
- Create: `docs/agent-first-setup.zh-CN.md` — 中文同步指南。
- Modify: `README.md`、`README.zh-CN.md`、`docs/README.md` — 增加简短启动提示和文档入口，不重复完整协议。

### Task 1: 诊断结果核心与本地只读检查

**Files:**
- Create: `src/onboarding_doctor.py`
- Test: `tests/test_onboarding_doctor.py`
- Modify: `src/space_connect.py`
- Test: `tests/test_space_connect.py`

- [ ] **Step 1: 写失败测试**

新增最小测试覆盖：
1. 诊断项包含固定字段 `id/status/summary/next/evidence)，status 仅可取 `pass/fail/needs_user/unknown/skipped`。
2. overall 聚合：必需项有 fail → blocked；无 fail 但有 needs_user → needs_user；必需项通过、仅可选项 skipped/unknown → ready。
3. 未知 status 被拒绝；只读检查结果不包含测试中的 bearer token、邀请码或 profile JSON。
4. Python 检查返回版本、解释器路径类别和是否处于 user site，不输出完整环境变量。
5. tool 未传且无法从当前 agent 环境唯一识别时返回 needs_user；传入 Claude/Codex 时只检查被选中的工具。
6. MCP 配置和 Skill 检查只读：entry 不存在、匹配、冲突、Skill 缺失、Skill 内容不同分别返回准确状态，不调用 add、不移动文件、不创建目录。

运行：
~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_onboarding_doctor.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_space_connect.py -v
~~~
预期：新增测试因 API 或实现不存在而失败；已有连接测试行为不变。

- [ ] **Step 2: 实现稳定结果和聚合器**

在 `src/onboarding_doctor.py` 定义稳定结果结构和 overall 聚合。结果只使用固定摘要与 allowlist evidence；错误消息、异常 repr、命令完整输出和环境变量值一律不复制到结果。

~~~python
STATUSES = frozenset(("pass", "fail", "needs_user", "unknown", "skipped"))
REQUIRED_CHECKS = frozenset((
    "python_runtime", "native_tool", "mcp_configuration",
    "skill_installation", "project_context",
    "runtime_reachability", "challenge_round_trip",
))

def make_check(identifier, status, summary, next_step="", evidence=None): ...
def aggregate(checks): ...
def render_text(result): ...
def local_checks(tool=None, project_dir=None, cli=None): ...
~~~

将 helper 切为小型、纯函数可测；CLI 检测和路径读取通过现有 `space_connect.cli_candidates`、`registered_spaces` 与 Skill 文件路径，不引入新依赖。

- [ ] **Step 3: 增加 native 配置只读检查**

在 `src/space_connect.py` 增加只读检查函数：找到候选原生 CLI 后调用现有 get 逻辑，比较预期 profile command；不匹配时只返回 server name 和冲突状态。Skill 检查比较 packaged Skill 与目标文件内容；不调用 install、move、mkdir 或 add。

- [ ] **Step 4: 验证绿色**

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_onboarding_doctor.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_space_connect.py -v
~~~
预期：新增与既有测试全部通过，测试目录外不生成诊断文件。

- [ ] **Step 5: 提交阶段一**

~~~powershell
git add src/onboarding_doctor.py src/space_connect.py tests/test_onboarding_doctor.py tests/test_space_connect.py
git commit -m "feat: add onboarding doctor checks"
~~~

### Task 2: Profile doctor、挑战验证与接入 Skill 路由

**Files:**
- Modify: `src/space_runtime.py`
- Modify: `tests/test_space_runtime.py`
- Modify: `src/skills/coopagents-space/SKILL.md`
- Modify: `src/skills/coopagents-space/protocol.md`

- [ ] **Step 1: 写 CLI 失败测试**

新增 CLI 回归：
- `doctor --json` 无 profile 时返回本地 checks、overall 和 next；只读且不泄漏环境变量。
- 有效 profile 时通过现有 `member_link` 验证空间身份，再按 start/read/complete 顺序完成 challenge；验证 challenge、diagnostic ID 和 proof 绑定一致。
- host 停止、身份不匹配、MCP 冲突、无效 profile、网络超时分别返回固定安全状态；诊断结果不包含 token、远端响应正文或 traceback。
- P2P profile 如已有连接状态则报告 direct/relay/disconnected；未知路径保持 unknown。
- CLI tool 与当前 Claude/Codex agent 冲突或无法唯一识别时返回 needs_user，不改配置。
- `create --connect`、`join --connect` 和 standalone `connect` 配置后都返回 configuration、verification、next；写入成功但当前 session 未重载时不得报告 ready。
- connect 失败仍保留已创建的空间/profile，并返回现有 retry 信息。

先运行：
~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_space_runtime.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_space_connect.py -v
~~~
预期：新增断言因 doctor 子命令/诊断字段缺失而失败；现有回归结果可辨认。

- [ ] **Step 2: 增加 profile 诊断函数**

在 `src/onboarding_doctor.py` 增加 profile 检查：
~~~python
def profile_checks(profile_path, *, tool=None, project_dir=None, cli=None): ...
~~~
调用现有 profile validator、空间请求、P2P member link、native entry 检查；challenge 使用现有 `/api/diagnostics/start`、`read`、`complete`。整个流程不记录或输出 token、challenge proof 或 profile 原文。challenge 请求前后用同一 member link 上下文，且限定每个 HTTP 请求的现有超时和响应体上限。

- [ ] **Step 3: 增加只读 doctor 命令**

在 `space_runtime.main` 注册：
~~~text
doctor [--profile <private-profile>] [--tool claude|codex]
       [--project-dir <repo>] [--cli <path>] [--json]
~~~
无 profile 只运行本地环境、tool、MCP entry、Skill 检查，并将需要连接 profile 的检查标为 skipped；有 profile 时追加 project identity、runtime reachability、transport path 和 challenge。默认输出英文摘要，`--json` 输出稳定对象。存在 fail 或 needs_user 时退出码为 1，ready 为 0。doctor 不写文件、不安装依赖、不安装 Skill、不修改 MCP、不启动/停止空间、不打开 wake。

- [ ] **Step 4: 接入现有 create/join/connect**

给 standalone `connect` 与 `connect_after` 成功分支复用 profile checks，结果结构包含：
~~~json
{
  "configuration": {"config": "added", "skill": "installed", "verified": true},
  "verification": {"overall": "needs_user", "checks": []},
  "next": "Start a new session and verify whoami."
}
~~~
保持现有顶层 identity/profile/retry 字段兼容。Connect 返回后若 MCP 配置已保存但 challenge 只可在新 session 执行，则显式标为 pending/needs_user，不在当前旧 session 伪造 MCP 已加载。

- [ ] **Step 5: 更新 Skill 与协议**

Skill 的自然语言路由：
1. 有用户给出的 invitation → 安全保存原文、join 并 connect 当前 harness。
2. 有用户给出的项目接入 prompt → 只使用其中指定 origin/project/agent credential，验证项目身份后接入。
3. 有现存 profile/entry → 先运行只读 doctor；匹配则复用，不匹配则说明冲突并要求用户选择名称。
4. 无上述上下文 → 当前仓库创建默认 P2P 空间、当前工具接入自己，不自动邀请、不启动 wake。
5. 所有路径分别报告配置写入、身份/网络验证、challenge、session reload 与 wake 状态；无需网页；新 session 中用真实 whoami/read_team 确认。

协议文档记录 doctor 参数、退出码、JSON 字段、状态聚合、诊断输出不含秘密和仅支持经实测 harness 的边界。

- [ ] **Step 6: 验证阶段二**

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_onboarding_doctor.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_space_runtime.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_space_connect.py -v
git diff --check
~~~
预期：三组 Python 测试通过；diff check 无输出。

- [ ] **Step 7: 提交阶段二**

~~~powershell
git add src/onboarding_doctor.py src/space_runtime.py src/space_connect.py src/skills/coopagents-space/SKILL.md src/skills/coopagents-space/protocol.md tests/test_onboarding_doctor.py tests/test_space_runtime.py tests/test_space_connect.py
git commit -m "feat: route agent setup through doctor"
~~~

### Task 3: 发布指南、README 入口和发行验证

**Files:**
- Create: `docs/agent-first-setup.md`
- Create: `docs/agent-first-setup.zh-CN.md`
- Modify: `docs/README.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: 写英文默认用户指南**

指南包含：
- 最短启动提示：告诉 agent 读取当前已发布版本的 Coopagents space Skill，再按用户目标配置当前项目；提示必须带公开 Skill URL，但不要求用户先手工执行 shell 安装命令。
- invitation、已有 profile/项目接入 prompt、无上下文三种路由。
- agent 在私有 venv 安装 pinned release；复用合适环境；PyPI 失败时按现有校验流程处理。
- doctor 输出的 overall/checks/next、配置已保存与 session 已加载的区别。
- P2P direct/relay/disconnected、主机离线、空间重启、Codex hook trust 和 wake 的独立恢复操作。
- 令牌和 profile 私有保存、不提交 Git、不删除旧配置的安全说明。
- 明确真实支持矩阵和未知项。

- [ ] **Step 2: 写中文同步指南和导航**

中文文档与英文默认版保持命令、状态、失败恢复和安全边界一致。README.md 和 README.zh-CN.md 只加清晰的首次配置入口链接与一句话体验，不复制完整运维说明。docs/README.md 加两份用户指南链接。

- [ ] **Step 3: 执行完整验证**

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/workspace_navigation_regression.js
node tests/collaboration_ui_regression.js
node --check src/static/app.js
node --check src/static/collaboration.js
git diff --check
~~~
预期：Python 与网页回归通过，文档不含本机凭据、路径或未验证的 harness 能力声明。

- [ ] **Step 4: 构建 sdist 和 wheel**

运行 `python -m build --sdist --wheel`（若环境没有 build 模块，使用仓库已配置的 build 命令安装/调用，不修改运行时依赖）；检查两个发行包包含新 doctor 模块和 Skill 文档，且不包含 `.local` 数据、数据库、runtime log、profile 或原始会话。

- [ ] **Step 5: 提交阶段三**

~~~powershell
git add docs/agent-first-setup.md docs/agent-first-setup.zh-CN.md docs/README.md README.md README.zh-CN.md
git commit -m "docs: publish agent-first setup and diagnostics"
~~~

## 计划自检

- 覆盖设计中的本地检查、profile/身份验证、网络路径、挑战往返、session reload、wake 边界、Skill 路由、用户指南和安全测试。
- 每个新增行为先写测试并确认失败，再实现。
- 所有本机测试数据留在忽略的 .local；无文件删除；无网页代码更改。
- 所有提交按阶段拆分；提交前运行阶段测试。

