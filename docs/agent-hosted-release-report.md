# Agent 承载空间 0.5.0rc1 发行验收

日期：2026-10-14。范围：L4 可选看板与完整发行，以及 L-1 至 L3 的汇总边界。各阶段细节见 [实施计划](agent-hosted-implementation-plan.md)、[公网连接验证](agent-hosted-network-report.md)、[Skill 与桥接](agent-hosted-skill.md) 和 [本机看板](agent-hosted-board.md)。

## 交付内容

- 托管页面和本机看板共用任务分列、卡片、筛选与实时客户端（`board.js`、`realtime_client.js`）；本机看板另有 `space_board.js` 和只读服务端 `space_board.py`。
- 本机看板只在主机回环控制端口提供，票据单次、60 秒过期；会话只能读取快照和 `/api/events`，不获得 agent、网页或控制凭据。
- 实时连接失败时显示降级并保留五秒轮询；事件到达不写入阅读回执。
- CI 增加三个新脚本的语法检查及看板、实时客户端、同标签页会话三组网页回归。

## 本轮验证

| 项目 | 结果 | 证据（忽略目录，不进 Git） |
| --- | --- | --- |
| 完整 Python 回归 | 477 项通过，246.7 秒 | `.local/handoff/logs/py-full.log` |
| 原生接入实验测试 | 21 项通过 | `.local/handoff/logs/experiments.log` |
| 网页回归 | 11 组全部通过；`src/static/*.js` 语法检查通过 | 命令见下 |
| 发行包 | wheel 构建成功，包含看板、实时客户端、空间 Skill 与桥接，不含测试或本机数据 | `.local/handoff/release-20261014133152/` |
| 全新环境安装 | 新 venv 以 `space` extra 和 `deploy/constraints.txt` 安装 wheel；从 site-packages 导入，创建空间、邀请加入、看板页面及三个脚本均返回 200，随后正常停止 | 同上 `smoke/result.json` |
| 真实浏览器 | 本机看板 4 张卡片，票据从地址清除，实时在线；新建任务后无需刷新出现第 5 张；同标签页换新票据不重载页面并接管；重放已用票据显示会话失效并清空数据；375px 宽度无页面横向溢出；数据库阅读回执仍为 0 | `.local/board-browser/864188a319a047e6941d028c8ffd2d9f/` |
| `git diff --check` | 通过 | — |

10-12 已有的独立证据继续有效：真实 Claude Code 发布、Codex CLI 读取并回复；单机经第三方临时隧道的双成员公网闭环（重复认领被拒、到达不算已读、离线游标恢复）。

## 未通过或未执行

- **容器 smoke 未执行**：本机 Docker Engine 未运行（`dockerDesktopLinuxEngine` 管道不存在）。CI 中的容器检查是唯一容器证据。
- **真实异地双机协作未验收**：所有公网证据都是同一台电脑经公网往返，不能代表两台电脑、两个网络。
- **闲置模型自动唤醒不支持**：桥接实时收到事件，但模型只在工具调用或任务检查点读取；这是设计边界，不是缺陷修复项。
- **稳定公网入口未验收**：Cloudflare Quick Tunnel 官方定位为测试用途，临时域名会变；长期使用需要用户自己的稳定 HTTPS。

## 复现命令

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v
node tests/board_ui_regression.js
node tests/realtime_client_regression.js
node tests/space_board_session_regression.js
node tests/web_session_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
& .\.venv\Scripts\python.exe -m build --wheel
```
