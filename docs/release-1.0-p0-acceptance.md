# 1.0 P0 验收执行记录

日期：2026-10-31。起点：`bbb0b60`，开发代码尚未发布。用户授权逐项执行 1.0 P0；本记录区分准备、自动化回归、原生模型和外部设备证据。

## 执行约束

- 所有新运行使用独立目录，保留失败及成功证据，不删除文件。
- 不修改真实用户的原生 agent 配置；原始记录、认证和邀请仅留在忽略的 `.local/`，不提交 Git。
- 配置、协议往返、模型真实工具调用、服务器状态及跨设备结果分别判定，不以其中一种替代另一种。
- 两台设备由同一维护者控制，只计跨设备证据，不能计为两位用户独立使用。

## 当前状态

| P0 | 状态 | 后续条件 |
| --- | --- | --- |
| Claude/Codex 新流程真实冷启动 | 自动化验收器已提交；真实冷启动未通过 | Claude 当前端点持续 503；Codex 原生策略拒绝初始化 shell 命令，未绕过；当前运行基于预装开发 checkout，不能当作发行包安装证据 |
| 双设备 P2P 与恢复 | Windows ↔ Linux 真实中继连接、持久身份和主机重启恢复通过；一方向模型完整问答通过 | Windows 模型发问、Linux 模型读取本地文件回复、Windows 新模型会话消费准确回复；反向问答仍未完成；两位用户及双方家用/移动 NAT 待验 |
| 跨设备 Claude 唤醒与 Codex 待命 | 未通过 | Claude 可用认证/端点、可交互原生会话及正常 hook 信任；需验证 Codex 显式待命、Esc 中断和输入行为 |
| 七种 Harness / Windows、macOS、Linux | Pi 原生同机闭环通过；Codex 跨设备单向闭环通过；OpenCode 原生 MCP 握手通过 | 其余实际闭环及 macOS 待验；OpenCode 所选模型返回 401，Claude 端点返回 503；Cursor/ZCode 仍需实际桌面会话；Kimi 已真实请求/回复但 ACP 完成阶段超时，未完成最终消费/解决 |
| 真实 GitHub App | 安装/实际用户授权/四类关联/实际检查/签名 webhook/去重/卸载撤权/重装重新授权与刷新恢复通过 | 普通 push/PR/check/Release 事件的签名投递与自动同步也通过；组织审批、PR 合并、线上限流等扩展场景不外推 |

## 环境核查

- Windows 原生 CLI：Claude Code 2.1.282、Codex 0.146.0、OpenCode 1.1.65；Cursor desktop 1.2.4。
- 初次清点未发现 Pi/Kimi/ZCode。随后在私有隔离目录安装官方 Pi 1.4.0、Kimi Code 2.4.1；ZCode 桌面仍未验证。
- 真实跨设备模型使用 Windows 桌面内置 Codex 0.165.0-alpha.1.2 与 Linux Codex 0.146.0；PATH 版本清点不能代表实际执行版本。
- Codex 默认用户配置在普通 CLI 启动时有类型错误；验收使用隔离配置，不修写用户文件。
- 远端为 Linux / Python 3.11.6 / Node 22.22.0；最初 PATH 中没有 Claude、Codex 或 OpenCode。
- GitHub CLI 的 OAuth 登录可用，但不是 GitHub App 身份，不能代替 App 安装授权。
- 原工作区 `.venv` 的 editable install 指向另一个 worktree；本轮建立专用 `.venv` 并检查 `coopagents.__file__` 指向当前验收 checkout。

## 判定与取证

每个真实结果记录提交、包版本/哈希、工具版本、操作系统、网络条件、实际操作、原生工具回执与服务端结果。失败保留原始证据并记录原因；修复后新建运行，不覆盖此前结果。维护文档只保留脱敏结论。

完整门槛见 [1.0 发布计划](release-1.0-plan.md)，双机操作见 [双机清单](two-machine-acceptance.md)，App 部署和权限见 [GitHub 接入](git-github-setup.md)。

## 本轮实际发现与修复

- OpenCode 1.1.65 环境变量语法应为 `{env:NAME}`，原 `${NAME}` 配置已修复，真实原生 MCP 连接与工具发现通过。所选模型认证失败，未把握手算作任务闭环。
- GitHub App manifest 不可显式订阅自动提供的 installation 生命周期事件；名称最大 34 字符。已按真实注册错误修复并增加回归。
- GitHub 新授权回调实际包含 `code`、`state`、`iss`。支持可选且严格匹配 `https://github.com/login/oauth` 的 issuer，继续拒绝重复、未知及错误 issuer；真实用户刷新后验证成功，finish 返回 active。
- 注册、安装完成和用户验证页面统一为中文黑白界面、内联 SVG 标识及明确下一步；桌面和 390px 手机视口检查通过，移动无横向溢出、操作区至少 44px、键盘可聚焦。
- 原生验收器在宿主进程未正确退出时不再报告完整成功；配置只复制当前选中的 provider，认证不进入 Git。

## 原生证据的边界

Pi 1.4.0 使用既有自定义 Responses provider / gpt-6-astra，在隔离同机服务完成四次模型会话和 15 次 MCP 调用。原始适配器 `.pi/mcp.json` 被原生加载；真实身份、任务认领、harness session、进度、请求、收件/确认、回复及解决均有独立数据库证据。不是安装 Skill 冷启动、P2P 或唤醒证据。

Windows 与 Linux 由同一维护者操作，连接使用 relay，记录 RTT 约 0.7–1.1 秒。主机重启后既有 Linux 身份无需新邀请即可恢复；模型完成 Windows 发问 → Linux 文件内容回复 → Windows 消费回复。初次出现的暂时传输不可达保留为失败证据，恢复后的协议诊断成功；未据此修改传输代码或声明稳定性达标。反向请求已送达但模型未执行回复，因此不能计作双向闭环。

真实 App 仅安装到专用合成测试仓库，checks/contents/metadata/pull_requests/statuses 均为只读。CLI OAuth 身份仅用于准备合成仓库；验收读取和用户连接使用实际 GitHub App，不能混算身份。

## 回归与发行验证

验收器修复后本轮实验回归 47 项、CI 定义的 31 条 Node 检查通过。发行包成功构建并检查含新增 binding renderer 与 issuer 修复；在全新专用虚拟环境安装 wheel，包导入、绑定页面渲染和文档指定的 space_runtime CLI help 通过。首次无隔离构建因本轮虚拟环境缺少 setuptools 失败，安装声明的构建依赖后通过；未修改产品代码。首次 wheel smoke 使用不存在的 `python -m coopagents` 入口失败，改用文档入口后通过，不将其误报为产品回归。

当前本机 Docker Engine 不可连接，尚未重新运行候选容器 smoke；旧提交 CI 证据不能替代最终候选 CI。完整 Python 首次回归 661 项，1 项退出清理错误、1 项跳过；定位为拒绝响应正文未消费即关闭，在 Windows Proactor 连接重置时阻塞 server.wait_closed。测试先读完响应后关闭，test_web 的 7 项通过；完整回归重新执行中。

Kimi Code 2.4.1 原生使用 default/manual 模式逐次批准 10 个 Coopagents MCP 操作，未启用 auto/yolo 或隐含 Never Ask 的 `-p`。原适配器被加载，实际身份、任务认领、harness session、进度、请求、收件确认和准确回复均有原生记录及数据库证据。回复完成后 ACP `session/prompt` 在 180 秒内没有最终返回；保留超时，不重放写入。请求方最终消费与解决未执行，故不标完整通过。

GitHub 使用真实个人账户专用私有 App。签名 installation.created 投递 HTTP 200，持久队列一次完成并后台刷新；同 delivery 重投返回 duplicate 且未重复执行。installation.deleted 投递处理后连接 revoked，页面不再显示旧交付/Release，数据库仍保留四条历史证据；手动刷新不能复活，GitHub 查询旧安装返回 404。新安装经新的用户授权和 finish 后仍不展示旧缓存，随后 refresh 重新生成四条新鲜证据；保留原任务关联，任务仍 open/unowned。真实 PR/提交分别读取三项成功检查；Release 为 prerelease，不能算 published release 或资产下载验收。

普通仓库事件补测也通过：向合成分支新增测试文件后，真实 push、pull_request.synchronize、check_run、check_suite 和 release.edited 均由 GitHub 投递 HTTP 200，持久队列全部完成，无失败或待处理项。未手动 refresh，后台 worker 已将 branch/PR 更新为新 HEAD，原完整提交关联仍新鲜可读，四条证据仍为 github_verified。未强推、未合并、未删除文件。组织安装审批、强推、合并/关闭 PR、status 专门事件、正式发布/资产截断及线上限流未实测，不从当前结果外推。

验收器复查修正了 Codex 读取提示矛盾，并将非交互 MCP 授权限定到当前私有空间、当前阶段的明确工具；协作沙箱为 read-only，未全局放开工具。唯一一次补测中，原生日志明确拒绝精确 Get-Content 只读命令（blocked by policy），反向回复仍为零；未绕过执行策略，不把提示文字或请求送达算成成功回复。
