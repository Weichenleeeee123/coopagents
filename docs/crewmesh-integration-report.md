# Crewmesh · 同频：接入验证记录

日期：2026-10-10（Asia/Taipei）

本报告区分本地环境事实、代码测试、真实 agent 调用和双机协作。项目仍处于接入实验阶段，尚未构建用户网页。

## 首次预检事实

以下是首次预检记录。本轮桌面包已更新为 `26.1007.2314.0`，附带引擎为 `0.162.0-alpha.17.2`；当前原生实验见 [详细记录](native-cli-validation.md)。

| 检查对象 | 结果 |
| --- | --- |
| Codex 桌面应用包 | 26.1002.7124.0 |
| Codex 桌面附带引擎 | 0.162.0-alpha.2 |
| 桌面附带引擎的 hooks feature | stable，true |
| 独立 Codex CLI | 0.146.0 |
| Claude Code | 2.1.282 |
| Python | 3.13.3 |
| Node.js | 22.16.0 |

独立旧 CLI 默认读取当前配置时，遇到 `features.context_management` 对象类型不兼容。仅在诊断命令中使用 `-c 'features.context_management=false'` 后，feature 检查成功。未更改用户全局配置；桌面附带引擎可以直接完成相同检查。

`hooks=true` 仅代表引擎报告该能力开启，不能据此认定桌面已经执行了本项目的 hook。

## 验证状态

| 验证层级 | 当前结果 | 能证明什么 |
| --- | --- | --- |
| 本机版本与 feature 检查 | 已完成 | 确定入口和版本差异 |
| 消息服务单元测试 | 10 项通过 | 存储、并发重试、分页、持久化与显式确认 |
| HTTP MCP 协议检查 | 已通过 | 两个独立进程之间的真实 HTTP 工具调用 |
| hook 脚本测试 | 4 项通过 | 三种上下文事件、Stop、必填参数及隐私边界 |
| 项目接入配置 | 已生成并校验 | 四个配置可解析；重复生成拒绝写入且哈希不变 |
| 原生检查器测试 | 7 项通过 | 检查原生调用成功、消息关联、工具错误、处理结果和失败报告；不代表原生实验通过 |
| Claude Code CLI 原生启动及 hook | 有条件通过 | 显式配置的 CLI 已连接 MCP，两个启动事件输出上下文；消费未验证 |
| Claude 普通交互模型调用 | 已通过（用户截图） | 当前普通入口已能回复；实验检查器的隔离配置仍需区分 |
| Claude Code 原生消息发布 | 已通过 | 正常入口发布消息 2，用户截图与数据库保存记录相互印证 |
| Codex CLI 原生消息调用 | 失败 | 本机另一个 MCP 的 transport 配置阻止会话创建 |
| Codex 桌面原生读取调用 | 已通过 | 已核实 read_probes 的 completed 事件；读取 SDK 留下的消息，未确认 |
| Claude → Codex 桌面消息链 | 已通过（显式任务） | 消息 2 的读取、处理说明、确认调用及数据库接收者记录相互印证 |
| 普通任务自行发现新消息 | 有条件通过 | 既有桌面会话自行读到消息 3；提示未包含新字段或工具名，未确认处理 |
| Codex hook 触发消费 | 尚未验证 | 实验目录没有对应 Codex hook 事件，不能归因于 hook |
| 运行中自动消费消息 | 尚未执行 | 需要发送、工作事件、读取及确认的时间顺序 |
| 两台电脑协作 | 尚未执行 | 需要第二台电脑和经过身份验证的共享服务 |

## 开发与 Git

工作分支：`feat/crewmesh-integration`。

- `59d3b06`：确认产品设计、名称、分阶段路线和实验计划。
- `8ec7165`：持久化 MCP 消息服务与 10 项测试。
- `ba71511`：真实 HTTP 协议验证脚本。
- `2cdca1f`：hook 探针与 4 项测试。
- `8ca88c6`：项目级配置生成、校验与复现说明。
- `00f83da`：首次证据报告与源码交付包。
- `8507a1c`：持续维护文档统一迁入 `docs/` 并建立导航。
- `45b4b71`：限时原生 CLI 检查器与 7 项行为测试。

代码按验证阶段分别提交。虚拟环境、数据库及原始实验记录保留在本地，不加入 Git。没有删除文件。

## 实际协议证据

本次 HTTP 检查 run_id：`702b7f19-f11d-4d71-84d6-2048fe6a7f89`，消息 id：`1`，协商协议版本：`2026-07-28`，结果：`passed=true`。原始 JSON 保存在`.local/agent-integration/evidence/702b7f19-f11d-4d71-84d6-2048fe6a7f89-protocol.json`。

检查覆盖工具发现、幂等发送、消息读取、读取后仍无确认、两次显式确认后只有一个接收者记录。该次实验启动的服务已停止，本机数据库继续保留。这份证据标记为 `sdk-http-only`。用户随后自行启动服务并完成桌面读取，详见 [补充原生证据](native-cli-validation.md)。

## 下一步：原生入口实测

实验目录：`C:/Users/Weichen Li/Documents/Codex/2026-10-10/wo-zhe/experiments/agent-integration`。在仓库根目录运行 `.venv/Scripts/python.exe experiments/agent-integration/probe_server.py`，再通过原有 Claude Code 与 Codex 桌面入口打开此项目，完成工具自身的项目/MCP/hook 信任检查。项目级配置已准备；本机全局配置未改变。

最新复现步骤见 [实验运行说明](integration-lab.md)。`../experiments/agent-integration/archive/crewmesh-integration-lab-source.zip` 是首次接入实验的历史快照；最新源码以仓库为准。新目录需按运行说明创建环境并生成本机配置。原生验收需要两边实际调用同一消息源的工具、处理后留下确认记录，以及对应会话的 hook 事件和上下文消费证据。仅生成配置或 shell 模拟 hook 不计为完成。原生接入验证完成后，再实施经过身份验证的共享服务与用户网页。

当前普通入口已完成消息 2 的发布、读取与处理确认。下一步聚焦全新消息和新接收会话的普通任务检查点，用户提示不再要求调用收件箱；必须与本轮显式工具任务分开验收。详细证据见 [原生消息链记录](native-cli-validation.md)。

后续消息 3 已被普通任务自行读取，接收方仍是既有会话，且未执行处理确认。产品方向可继续以任务检查点拉取为基础；全新会话、hook 归因和运行中消费尚未通过，不能将 P1 标为全部完成。

## 官方资料

- [Codex hooks](https://learn.chatgpt.com/docs/hooks)：项目级配置、原生事件和 hook 信任。
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：工具接入和客户端边界。
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)：工作事件与上下文机制。
- [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)：实验服务与协议客户端。

## 仓库结构迁移

源码、数据库和配置已迁移，旧路径不再作为启动入口。当前命令见 [实验说明](integration-lab.md)，迁移与服务恢复证据见 [结构记录](repository-layout.md)。原生会话应从新实验目录重新启动，不将迁移后的 SDK 检查视为原生入口重新验收。
