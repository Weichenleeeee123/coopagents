# 唤醒与点对点入口原型实测

日期：2026-10-14。目的：在实现前确认三条路线在真实工具上可行。原型代码与证据保留在忽略目录 `.local/prototypes/`，不进入主线。

## 1. Claude Code：空闲唤醒（`asyncRewake`）

版本：Claude Code 2.1.282，交互终端，模型 Haiku 4.5。配置：`SessionStart` 与 `Stop` 各一个 `type: command`、`asyncRewake: true` 的 hook，监听程序收到触发后把提示写到 stderr 并以退出码 2 结束。

| 检查 | 结果 |
| --- | --- |
| 空闲 105 秒后触发 | 通过：无用户输入，Claude 自行开始新一轮并回复 `WOKE ALPHA-7Q2` |
| 空闲 625 秒后触发（超过 600 秒默认超时） | 通过：`timeout: 3600` 生效，回复 `WOKE CHARLIE-3ZX` |
| 唤醒后重新监听 | 通过：每轮结束 `Stop` 再次启动监听，输入里 `stop_hook_active=true` |
| 超时行为 | 到达 `timeout` 后监听进程被**静默杀掉**，不唤醒、无提示；必须由下一轮重新挂起 |
| 重复监听 | `SessionStart` 与 `Stop` 会同时存在两个监听；“先到先得”会让长时监听退出，改为“最新者接管”后正确 |
| 注入形式 | 会话中显示为 “Stop hook feedback”；模型收到的系统提醒前缀为 “Stop hook blocking error from command …” |

## 2. Codex：待命续跑（`Stop` hook 阻塞）

版本：Codex 桌面版自带 CLI 0.162.0-alpha.17.2，模型 gpt-5.6-luna。配置：测试目录 `.codex/hooks.json` 的同步 `Stop` hook，等待触发；收到后输出 `{"decision":"block","reason":…}`。

| 检查 | 结果 |
| --- | --- |
| `codex exec` 待命 79 秒后触发 | 通过：Codex 以 reason 作为新提示继续，回复 `WOKE BRAVO-K81` |
| 交互 TUI 待命 37 秒后触发 | 通过：界面显示 “Blocked by hook” 和提示，随后回复 `WOKE DELTA-5MW` |
| 再次待命 | 通过：续跑结束后 `Stop` 再次挂起；无消息时按监听程序自身期限正常结束 |
| 待命时的界面 | 显示 “Working · Running hook”，提示 Esc 可中断，输入框可见；Esc 中断与待命中输入的行为**未测** |
| 空闲唤醒 | 不支持：官方说明后台 hook 结束不开启新一轮；只能用“待命”占住会话 |

环境问题：全局 npm 的 Codex CLI 是 0.146.0，无法解析桌面版写入的 `[features.context_management]`，任何 `codex` 命令都启动失败；本机默认模型 `gpt-6.1-sol` 在 ChatGPT 账号下被拒绝。本测试改用桌面版自带 CLI 并显式指定模型，未修改全局配置。

## 3. iroh：按公钥直连的异地入口

版本：iroh 1.1.0（PyPI，Windows 预编译包），独立 venv。原型把本机 TCP 端口经 iroh 双向流转发到主机，等同未来桥接的职责。主机密钥持久保存，身份跨重启不变。

| 检查 | 结果 |
| --- | --- |
| 本机两端 | TCP 往返中位 0.6 ms，1 MiB 回显 0.36 s；WebSocket 往返 0.9 ms |
| 只凭公钥 ID 拨号 | 通过：发现服务找到地址；先经新加坡 n0 中继（573 ms）建立，随后升级直连 |
| 异地：GitHub Actions（Azure）↔ 家中主机 | 通过：0.95–3.1 s 建立；约 10 s 内从中继（783 ms）升级为 UDP 直连；3 分钟 6 轮探测全部成功 |
| 异地性能 | TCP 往返中位约 275 ms，WebSocket 约 190 ms，1 MiB 回显 0.67–0.78 s（首轮预热 2.26 s）|
| 日志隐私 | 远端日志隐去地址，公开仓库日志中无 IP |

边界：远端是有公网地址的机房主机，属于容易打洞的情况。两端都在家用 NAT 或移动网络 CGNAT 后的情况未测，可能只能走中继。n0 公共中继都在境外，延迟高且可能受网络限制，需要支持自建中继。主机网络中出现 `198.18.0.1`，说明有代理软件 TUN 模式接管流量，iroh 仍然成功。

原型分支 `proto/iroh-remote` 仅用于这次远端测试，不合并。

## 对实现的结论

- Claude Code 采用 `asyncRewake` 的“空闲唤醒”；Codex 采用 `Stop` hook 的“待命续跑”。两边体验不对等，需在 Skill 中说明。
- 监听需要：最新者接管、超时前自行退出、唤醒提示只用固定模板、按可处理事件过滤并合并、限制唤醒频率，并用 `stop_hook_active` 防止循环。
- 异地入口改用 iroh：邀请携带主机公钥，桥接在本机开端口转发；现有 HTTP/MCP/WebSocket 代码不变，但本机空间的 Host/Origin 检查要适配转发后的本机地址。Quick Tunnel 保留为兜底。
