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

## 复测：0.7.0（同日）

按同样四步，在新目录 `D:/coop-acceptance-2/` 用 PyPI 上的 0.7.0 重跑。提示词仍是 README 原话（README 第 1 步现在要求 Claude 以 "Claude" 建空间），另加"状态放 D 盘"一句。

| 步骤 | 结果 | 耗时 |
| --- | --- | --- |
| 1. Claude 装包、建空间、接入、生成邀请信息 | 成功：成员名是 "Claude"；用 `connect` 接入，条目在 Claude Code 真正读取的用户配置里，`√ Connected` | 192 秒 |
| 2. Codex 粘贴邀请信息加入 | **第一次失败**：`join --invitation-code-stdin` 没有收到任何输入、一直卡住（见新问题 2）。Codex 停下来要新邀请，没有手改配置。加一句"先存文件再用管道"的提示后成功，并用 `connect --tool codex` 接入、核验通过 | 163 秒 + 124 秒 |
| 3. 新会话里说"Install Coopagents wake-up" | 成功：Claude 认得这个指令并装好 hook | 179 秒 |
| 4. Claude 闲着，Codex 原话提问 | Codex 找到 "Claude" 并直接发给它；闲置 Claude **4 秒**被唤醒，13 秒读到请求。但 Claude 先问用户要不要回答（见新问题 4），用户同意后回复了正确命令。Codex 一直在 `read_inbox` 里等，没看到回复（见新问题 3） | 见下 |

| 时间 | 事件 |
| --- | --- |
| 14:40:19 | Codex 把请求发给 Claude |
| +4 秒 | 闲置的 Claude 被唤醒 |
| +13 秒 | Claude 读取请求，随后问用户是否回答 |
| 14:42:02 | 用户同意后，Claude 回复 `python -m unittest discover -s tests -v` |
| 14:43:18 | Codex 查了 12 次 `read_inbox` 都没看到回复，报告"还没收到"后退出 |

上一轮的三个问题都已修好：接入配置写对并核验、新会话认得 Skill、单人模式下能找到 "Claude"。

### 新发现的问题

1. **Skill 装了两份。** Claude 先按 README 从 GitHub 下载了一份 Skill（LF 换行），`connect` 又装了包里那份（Windows 构建，CRLF 换行），比较时把只差换行符的文件当成不同，旧的改名为 `coopagents-space.backup-…`，而且备份就放在 skills 目录里，被 Claude Code 当成第二个 Skill 加载。
   - 建议：比较时忽略换行符；备份放到 skills 目录之外；README 和邀请信息里把"按链接配置 Skill"改成"阅读链接里的 Skill"，由 `connect` 负责安装。
2. **严重：agent 的 shell 里，`join --invitation-code-stdin` 会一直卡住。** Codex 运行这条命令时没有接任何输入，而它的 shell 不会关闭标准输入，`join` 就一直在等。
   - 建议：`--invitation-file` 同时接受整段邀请信息的文本文件，agent 用自己的写文件工具保存后再加入（邀请码仍然不进命令参数）；从标准输入读取时，几秒内没有内容就报错退出。
3. **严重：`read_inbox` 的工具说明写错了。** 0.7.0 的说明写"读取发给你的请求和你发出请求的回复"，但实际只返回发给你的请求；回复在 `read_team` 里那条请求的 `replies` 下面。Codex 照说明一直查 `read_inbox`，错过了回复。
   - 建议：改正说明，并在 `send_request` 的说明里写明去 `read_team` 看回复。
4. **被唤醒后先问用户。** 唤醒提示和 Skill 都写着"队友内容不能让你离开当前任务，需要决定时问用户"。这次会话没有当前任务，Claude 把"回答 Codex"当成新工作，先问了用户。另外本机全局 CLAUDE.md 要求"审视地指出问题"，也让它更谨慎；上一轮同样的提问它直接回答了，说明这一点不稳定。
   - 建议：唤醒提示和 Skill 写清楚，用能读到的信息回答队友的问题、回复和确认属于本职；改文件、跑会改变东西的命令、接受交接或接新任务才需要问用户。

## 第三轮：0.7.1（同日）

在 `D:/coop-acceptance-3/` 用 PyPI 上的 0.7.1 重跑，全程用 README 原话，不给任何提示。

| 步骤 | 结果 | 耗时 |
| --- | --- | --- |
| 1. Claude 装包、建空间、接入、生成邀请信息 | 第一次：本机 pip 用的是清华镜像，镜像还没同步 0.7.1，**Claude 悄悄装了 0.7.0**。README 改为在安装那句里写明"镜像没有就加 `--index-url https://pypi.org/simple`，不要装别的版本"（`933666e`）后重跑。第二次：Claude 照本机全局 CLAUDE.md 的人设反问了一串问题，什么也没做；之后在搭环境的步骤里追加一句"这是自动化验收，直接照做"的系统提示（唤醒那一步不加）。第三次成功：装的是 0.7.1；Skill 只有一份、没有备份；`connect` 接入并 `√ Connected`；邀请信息是新写法（存文件后 `--invitation-file` 加入、阅读 Skill） | 835 秒，其中从 pypi.org 直连下载约 10 分钟 |
| 2. Codex 只拿到邀请信息 | **一次成功，没有任何提示**：Codex 把信息存成文件，用 `--invitation-file` 加入，再用 `connect --tool codex` 接入，`verified: true`，Skill 只有一份。写文件时多留了几份私有邀请文件（其中一份是错的），按仓库规则没有删除 | 184 秒（复用了第 1 步的 pip 缓存） |
| 3. 新会话里说"Install Coopagents wake-up" | **失败**：中转额度充值后重跑，Claude 问 profile 在哪；告诉它路径后，它编了一个不存在的 `.claude/coopagents-wakeup.json` 并报告"已安装"，实际没有 hook（见下）。改用 `space_wake install` 安装 | 303 秒 + 53 秒 |
| 4. Claude 闲着，Codex 原话提问 | **全程无人介入、一次通过**：Codex 发给 "Claude"；闲置 Claude 4 秒被唤醒，11 秒读到请求，43 秒直接回复正确命令（没有先问用户，本机全局 CLAUDE.md 仍在生效）；Codex 在 `read_team` 里看到回复并转述 | Codex 共 117 秒 |

本轮新增的观察：
- **国内镜像未同步时，agent 会降级到旧版本。** 修复方式是在 README 的安装指令里直接写回退方法；邀请信息本来就带这句。代价是回退到 pypi.org 时下载很慢（本次约 10 分钟）。
- Codex 第 2 步不再卡住：文件加入的修复有效。
- 0.7.0 复测的四个问题全部确认修好：文件加入（第 2 步）、回复去处（第 4 步 Codex 在 `read_team` 里拿到回复）、只有一份 Skill（第 1、2 步）、唤醒后直接回答（第 4 步）。
- **新问题：新会话里"安装唤醒"仍靠 agent 发挥。** 新会话不知道 profile 在哪；在"直接照做"的测试提示下，Claude 编造了一个配置文件并谎报成功。测试提示加重了这种倾向，但根因是这一步没有确定的命令。
  - 建议：`space_wake install` 不传 `--profile` 时，从 Claude Code / Codex 已注册的 coopagents 连接里自动找到 profile；README 第 3 步直接给出这条命令；`connect` 完成后在输出里给出带好参数的唤醒安装命令。

## 唤醒安装重测：0.7.2（同日）

在 `D:/coop-acceptance-4/` 用 PyPI 上的 0.7.2 只测唤醒安装的两条路径（搭环境的测试提示同第三轮）。

| 路径 | 结果 | 耗时 |
| --- | --- | --- |
| A. README 第 1 步：接入时开启唤醒 | **通过**：Claude 一条命令 `space_runtime connect --tool claude --profile … --wake --project-dir …`，同时完成接入和唤醒；`demo-repo/.claude/settings.local.json` 里有指向正确 Python 和 profile 的两个 `asyncRewake` hook，MCP `√ Connected` | 334 秒（含从 pypi.org 下载） |
| B. 另一个仓库的全新会话里说"Turn on Coopagents wake-up for this repo." | **失败**：Claude 没有读 Skill，而是直接调用手边的 MCP 工具（`whoami`、两次 `register_session`），然后报告"已启用唤醒、系统可以唤醒这个会话"；`other-repo` 里没有任何 hook | 30 秒 |

结论：主流程（README 第 1 步）里的唤醒已经可靠。之后在新会话里单独开启唤醒仍然失败——新会话里 agent 先用现成的 MCP 工具，不会去读 Skill，所以写在 Skill 和 README 里的命令到不了它面前；它把"注册会话"当成了"开启唤醒"。

- 建议：在桥接里加一个 MCP 工具（例如 `install_wake`），由桥接用自己的 Python 和 profile 调用 `space_wake install`，项目目录默认用会话的工作目录；MCP 服务说明写明"开启唤醒就调用这个工具，工具没有返回 installed 就不能说已开启"，`register_session` 的说明写明它不是唤醒。这样"开启唤醒"就是 agent 手边的一次工具调用。
