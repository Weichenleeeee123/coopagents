# 单机真实 agent 验收（2026-10-29）

## 结果

在一台 Windows 11 电脑上，使用真实 Claude Code 与 Codex 桌面 CLI，按 README 的四步流程完成一次从创建空间到空闲唤醒问答的验收。测试 wheel 从提交 `63ace14` 的 Git 快照构建，版本为 `0.7.3.dev20261029124422`。17 项状态检查全部通过。

| 步骤 | 结果 |
| --- | --- |
| Claude 安装并创建空间 | 单一 MCP 注册；目标版本安装在独立 venv；Skill 仅一份；仓库 hook 存在；成员显示为 Claude；生成邀请信息 |
| Codex 从邀请加入 | 单一 MCP 注册；安装版本与邀请方相同且位于独立 venv；空间成员为 Claude 和 Codex；Codex profile 位于仓库外 |
| 分别安装唤醒 | Claude 在第二个仓库安装 SessionStart/Stop hooks；Codex 安装 Stop hook |
| 空闲问答 | Claude watcher 进入 watching；Codex 请求指定 Claude；服务记录 Claude 被唤醒和回复；Codex 收到答案 |

验收使用 Claude Code 2.1.282 和 `claude-opus-5`，Codex 桌面 CLI 0.165.0-alpha.1.2 和已配置的 `gpt-6.1-sol`。邀请使用 v2 格式。真实 agent 结果与空间服务中的成员、请求、回复和 watcher 状态交叉核对。

## 失败与重试记录

本机 Kiro 网关默认模型两次返回 HTTP 503。显式选择 `sonnet5` 后，网关报告该模型在当前组下没有可用 channel；模型目录接口也返回 403。改用用户指定且在该网关可用的 `claude-opus-5` 后，完整流程通过。以上失败轮次均保留，未纳入通过统计。

## 验收边界

本轮在同一台电脑上运行两个 agent，证明单机邀请、接入、hook 和空闲 Claude 问答闭环。它没有验证两位用户使用两台设备、双方位于家庭/移动 NAT、跨电脑唤醒或 macOS 原生接入。既有 GitHub Actions runner 到家用电脑的 P2P 证据见[跨网络 P2P 报告](agent-hosted-p2p-report.md)，不能替代双方都在 NAT 后的双机验收。

所有现场和原始输出保留在被 Git 忽略的 `D:\coop-e2e\runs\`。本轮结束时测试空间已停止，测试创建的 Codex MCP 项已移除；没有删除旧验收文件或修改全局工具配置。
