# 单人流程真实 agent 验收（2026-10-25）

按 README「Try it on your own machine」四步，用真实的 Claude Code 和 Codex 从零走一遍：Claude 建空间并生成邀请信息，Codex 粘贴加入，Claude 闲着时由 Codex 提问。这是第一次用真实 agent 走完整条邀请链路。

## 环境

- Windows 11，同一台电脑；空间为默认 p2p 模式。
- Claude Code 2.1.282（无界面 `-p` 跑第 1、3 步，交互窗口跑第 4 步的空闲唤醒）；Codex 桌面版自带 CLI 0.164（`codex exec`，模型 `gpt-6-luna`）。
- 测试仓库是一个小计算器库，README 写明测试命令 `python -m unittest discover -s tests -v`。
- 因 C 盘只剩不到 1GB，提示词里多加一句"环境和状态放在 D:/coop-acceptance/"。其余全部是 README 原话。

## 结果

| 步骤 | 结果 | 耗时 |
| --- | --- | --- |
| 1. Claude：从 PyPI 装 0.7.0rc2、建空间、接入自己、生成邀请信息 | 装包、建空间、生成邀请信息成功；**接入自己失败但报告成功**（见问题 1） | 171 秒 |
| 2. Codex：粘贴整段邀请信息，"Join as Codex" | 成功：邀请码走标准输入，Skill 装好，MCP 条目写对，改配置前做了备份，并如实提示"需要新会话才能加载" | 188 秒 |
| 3. 新会话里对 Claude 说"Install Coopagents wake-up" | **失败**：Claude 不知道这是什么（见问题 2）；改用 `space_wake install` 直接安装 | 16 秒 |
| 4. Claude 闲着，让 Codex 提问并等回答 | Codex 的问题**没有发给任何人**（见问题 3）；改为以 Codex 身份发一条指定给 Claude 的请求后，链路完整跑通 | 见下 |

第 4 步唤醒链路（空间记录的时间）：

| 时间 | 事件 |
| --- | --- |
| 13:08:17 | 请求发给 Claude 的成员 |
| +6 秒 | 闲置的 Claude 会话被 `asyncRewake` 唤醒 |
| +11 秒 | Claude 读取请求 |
| +34 秒 | Claude 回复 `python -m unittest discover tests`（能跑通测试） |

Codex 在等待中收到这条回复，最终输出 "Claude replied: `python -m unittest discover tests`"。

## 发现的问题

1. **严重：Claude 把 MCP 配置写进了 Claude Code 不读的文件，并报告成功。** 条目写进 `~/.claude/mcp_settings.json`（文件原有的 notion 条目保留），`claude mcp list` 里没有 coopagents。Skill 也没装进 `~/.claude/skills`，而是把整个仓库克隆到 D 盘读说明。用户要到下次打开 Claude 才发现连不上。验收中改用 `claude mcp add --scope user` 补上。
   - 建议：提供确定性的接入命令（例如 `space_runtime connect --tool claude|codex --profile …`），由程序调用原生 `mcp add`、复制 Skill 文件，再用 `claude mcp get` / `codex mcp get` 验证，失败就明确报错。Skill 只让 agent 调这条命令，不再让它自己改配置文件。
2. **严重：新会话里"安装唤醒"无从下手。** 根因同问题 1：Skill 没装好，新会话里没有任何 Coopagents 说明。接入命令可以顺带询问并安装唤醒。
3. **严重：单人模式里没有叫"Claude"的成员，Codex 把问题发给了没人。** 第 1 步 Claude 用用户名 `weichen.li` 创建空间，Codex 找不到 Claude，于是发了一条不指定接收人的请求，正文是"请帮我问一下 Claude"。不指定接收人、也不关联任务的请求没人收、也不会唤醒任何人，Codex 会一直等。
   - 建议：`read_team` 里显示每个成员当前接入的工具（Claude Code / Codex）；单人模式下成员名带上工具名；没有接收人也没有任务的 `send_request` 直接拒绝，并在错误里列出可选成员。
4. 次要：在新目录第一次打开交互式 Claude 会弹出信任对话框，默认选项是"No, exit"，启动时带的第一句指令会被吞掉。这是 Claude Code 自身的行为，README 可以提醒一句。
5. 与产品无关：本机 Codex 配置里的默认模型 `gpt-6.1-sol` 不能用于 ChatGPT 账号，验收时用 `-m gpt-6-luna`。

## 结论

底层机制都能工作：PyPI 固定版本安装、邀请信息、标准输入加入、p2p 连接、空闲唤醒（6 秒）、问答闭环（34 秒）。断掉的地方都在"让 agent 自己去配置"这一层：三个严重问题里有两个是 agent 自由发挥配置出错，一个是单人模式下身份对不上。下一步应先修问题 1 和问题 3，再发 0.7.0，然后才适合找真人试用。

验收现场保留在 `D:/coop-acceptance/`（不进 Git）：运行脚本、各步输出（邀请码只在原始输出里）、空间状态。
