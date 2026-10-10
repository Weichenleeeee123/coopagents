# 仓库结构整理记录

日期：2026-10-10。仓库根目录就是 Crewmesh 项目目录，不再沿用 GPT Work 的 `work/` 和 `outputs/` 作为源码组织方式。用户要求正式代码直接放在 `src/`，已通过包映射实现，无 `src/crewmesh/` 子目录。

## 迁移对应关系

| 原位置 | 当前位置 |
| --- | --- |
| `src/crewmesh/*.py` | `src/*.py` |
| `work/crewmesh-integration-lab/*.py` | `experiments/agent-integration/*.py` |
| 实验 `runtime/`、`evidence/` | `.local/agent-integration/runtime/`、`evidence/` |
| `work/crewmesh-shared-evidence/` | `.local/test-evidence/` |
| 实验 `.venv/`、旧 agent 配置和缓存 | `.local/archive/work/crewmesh-integration-lab/` |
| 原 Python 包子目录的缓存 | `.local/archive/source-package-layout/` |
| `outputs/crewmesh-integration-lab-source.zip` | `experiments/agent-integration/archive/crewmesh-integration-lab-source.zip` |

所有文件保留，使用移动和配置编辑完成整理；未删除文件。部分目录移动因 Windows 占用中断，留下的空归档目录也保留在 `.local/archive/`。

## 项目配置

新增 `pyproject.toml`：项目元数据、Python 版本、包映射和可选 MCP 实验依赖。领域包只依赖标准库，`crewmesh` 逻辑包映射到 `src/`，安装后测试不需要手工配置 PYTHONPATH。开发命令在根目录 `CONTRIBUTING.md`。

新建根目录 `.venv/`。旧虚拟环境包含绝对路径，保留归档但不复用。新实验配置使用当前解释器与新脚本路径生成，旧配置原样保留；机器配置、凭据和数据库均由 `.gitignore` 排除。

## 验证与服务恢复

- 25 项领域测试通过；21 项实验测试通过。
- 项目配置 JSON/TOML 校验通过；重复生成拒绝覆盖，内容保持不变。
- `import crewmesh` 解析到根目录 `src/__init__.py`。
- 原服务经用户授权停止；从新目录恢复至 8768 端口，进程和日志信息记录于 `.local/agent-integration/service.json`。
- 迁移数据库保留原消息 ID 1、2、3 和两条处理确认；新增 HTTP 检查消息 ID 4，SDK 往返通过，run_id 为 `67928857-8a2e-4296-9de9-3b26bc41ab66`。

## 空目录处理记录

整理时旧 `work/crewmesh-integration-lab/` 已无文件，但被 Windows 进程占用，移动也被系统拒绝；代理没有强制关闭其他应用或删除目录。用户随后自行清理了空 `work/`。正式源码、测试、数据库和运行方式均不再依赖旧路径。

P2/P3 功能范围不因结构整理改变；后续源码继续直接放在 `src/`。

结构阶段提交：`753a3bf`（源码平铺、实验迁移、包配置与本机数据路径）。
