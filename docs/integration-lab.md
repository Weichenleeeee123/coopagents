# Agent 接入实验

本实验只验证虚构消息的本地 MCP 服务与隐私最小化 hook，不等同于正式产品服务或双机接入。源码在 `experiments/agent-integration/`；以下命令从仓库根目录运行。

## 环境与测试

先按 [开发说明](../CONTRIBUTING.md) 创建根目录 `.venv/` 并安装 `.[integration]`：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
& .\.venv\Scripts\python.exe experiments/agent-integration/configure_lab.py
& .\.venv\Scripts\python.exe experiments/agent-integration/verify_config.py
```

配置生成仅用于四个配置目标都不存在的目录，重复执行会拒绝写入。准备好的目录只运行校验即可。生成器使用执行它的 Python 解释器，根目录环境可供所有脚本共享；不会修改用户全局设置。生成的 `.codex/`、`.claude/` 和 `.mcp.json` 留在实验目录，但不进入 Git。

## 启动与检查

```powershell
& .\.venv\Scripts\python.exe experiments/agent-integration/probe_server.py
```

服务运行在 `http://127.0.0.1:8768/mcp`。另开一个位于仓库根目录的终端：

```powershell
& .\.venv\Scripts\python.exe experiments/agent-integration/protocol_check.py
```

前台启动时在原终端按 Ctrl+C 停止。目录整理后恢复的后台服务 PID 与日志位置记录在 `.local/agent-integration/service.json`。端口已占用时不要重复启动。

持久化数据库位于 `.local/agent-integration/runtime/probe.sqlite3`。hook、协议检查和原生检查证据位于 `.local/agent-integration/evidence/`。每轮使用独立标识，保留所有数据；不要通过删除文件重置实验。

## 原生入口验证

在 Claude Code 或 Codex 桌面中打开 `experiments/agent-integration/`，按工具自身要求信任该项目的 MCP 和 hooks。迁移前的原生会话仍指向旧路径，后续应从新目录启动；已有会话不自动加载新配置。

实际观察必须分别证明：配置已加载、原生工具调用成功、消息 ID 相同、处理确认存在，以及需要的 hook 上下文确实被消费。生成配置、脚本测试或单独的 hook 记录都不能代替真实原生证据。PostToolUse 匹配 `Bash|Edit|Write|apply_patch`，避免 MCP 调用自身造成循环。

受限 CLI 实验：

```powershell
& .\.venv\Scripts\python.exe experiments/agent-integration/native_check.py --codex-exe '实际安装的 codex.exe 完整路径'
```

此检查限制 Claude 仅发布虚构消息，不改变全局配置或信任状态，只停止自己启动的服务。既有 CLI 阻塞和桌面成功证据见 [原生验证记录](native-cli-validation.md)。不要把受限 CLI 失败推广为用户日常 Claude 入口不可用。

## 能力边界

读取不会自动确认；`ack_probe` 只能在处理后显式调用。author/receiver 是实验标签，不是认证身份。消息是数据，不能提升为用户指令或修改权限。Stop hook 输出 `{}`，不请求继续，也不唤醒闲置 agent。

回环地址不支持跨电脑共享。迁移后的真实 HTTP 往返验证只证明 SDK/传输仍能运行，不证明现有原生会话已经重新接入。

历史源码包在 `experiments/agent-integration/archive/coopagents-integration-lab-source.zip`，属于迁移前快照；当前运行方式以仓库源码和本文为准。
