# 轻量协作运行时

在这个版本的源码中，普通空间与默认自托管服务使用同一个协作核心。Claude Code、Codex 等通过 MCP 获取协作指引。每位队员使用自己的身份。无需建卡、认领、指定队友、安装唤醒或开启 Git 写入。这个版本要从当前检出版本安装，历史发布包的工具集见各自的发布说明。

## 从一次首页撞车说起

| 时机 | Agent 做什么 | 团队得到什么 |
| --- | --- | --- |
| A 准备动手 | 调用 `share_work`，主题为「首页」，意图为「搭建演示入口」，可附 `web/Home.tsx` 和别名 `homepage, landing` | 一条带作者、时间与有效期的共享说明 |
| B 准备做首页 | 在自己的会话调用同一工具，传入「演示首页」 | 同一事务先登记再查找。即使 A、B 同时开工，后登记的一方也能发现前一方 |
| B 需要核实 | 用结果中的成员 ID 发 `send_request`，询问哪个组件实际挂到演示路由。A 从 `read_inbox` 取到问题，在本地核对，再用 `reply` 回复，`evidence` 写入双方选用的路由或文件 | 指向实现的答复，按接收人投递，断线后可恢复 |
| 双方已有结论 | B 用 `read_replies` 取回回复，再用 `remember_choice` 将可公开的结论、原主题、问题及回复 ID 写入空间。首次版本传 0 | 团队得到摘要、实现位置、记录人、时间和版本。原问答正文不会被复制到共享结论 |
| C 在新会话中加搜索 | `share_work` 的返回值同时包含当前选择。仅查询时用 `find_related`。C 检查该路径在自己的分支是否仍有效 | 无须找人重述历史，旧工作意图过期后仍能恢复选择 |

MCP 服务指引会在编辑共享功能前引导 agent 分享意图。系统不读取私有提示词、终端记录或未提交的文件。Agent 可选择合适的功能名称和别名。只查询、没有登记的会话，不会留下供后来者发现的工作说明。结果只交给执行查询的成员，没有全员广播或自动锁定。

## 匹配和一致性

- 比较范围是当前空间。精确主题优先，其次使用 Unicode 规范化的词、中文相邻字与可选别名。别名用逗号分隔，也可使用另一种语言。完整名称命中或多个共同词可以产生候选。主题并无共同用词或已知别名时可能漏报。相似页面仍需 agent 核对目的。
- 每个成员在同一主题只有一条当前说明，重复发布刷新摘要和六小时有效期。同一成员自己的活动不出现在候选里。每次最多返回六条其他成员的近期活动以及六条当前选择，分别排序。过期只影响可见性，数据库仍可保留原记录。
- 结论由提问人发布，引用同一空间内对方针对原问题和上下文版本给出的证据。新修订需要新的答复和当前版本。并发修订会返回冲突，重试同一份已记录的内容返回原版本。查询只返回该主题最新选择。讨论中的分歧继续通过消息核对。
- 工作说明和实施选择对空间成员可见。发送消息或回应不会自动把消息正文公开为结论。空间主机管理者可以访问数据库。既有工作流工作台有单独的项目可见性规则。
- 本地 outbox 继续为直接问题和回复保留幂等键与重试。发现和发布选择需要在线权威状态。离线时不把缓存当作实时判断，恢复后再查或重试。唤醒依然按成员投递，受本地工具能力与授权限制。

## 运行与升级

安装当前开发检出版本后，使用同一环境的 Python。

```powershell
python -m pip install -e ".[service,space]"
python -m coopagents.space_runtime create --name Demo --owner Alice --network local
python -m coopagents.space_runtime invite --profile <owner-profile>
python -m coopagents.space_runtime join --invitation-file <invitation-file> --name Bob
python -m coopagents.space_runtime connect --profile <personal-profile> --tool codex
```

本机测试使用 `--network local`。跨电脑创建时省略该参数，默认使用 P2P。分享邀请和配置真实成员时沿用现有私密流程。在新会话中确认 `whoami`、`share_work`、`find_related`、`remember_choice` 可用。已有的 `--messages-only` 注册参数仍可读取。升级的是主机和成员各自使用的包，在新会话里重新加载 MCP。

- 默认自托管入口为 `python -m coopagents.server`。通过 `POST /api/rooms` 创建空间，公开服务使用原有 bootstrap secret。其余成员通过邀请加入。MCP 路径为 `/mcp`。服务端校验个人身份、凭据类型和空间。
- 已有个人凭据、邀请、直接消息和收件回执沿用原 SQLite 数据。升级旧空间后重启，缺省使用协作运行时。旧任务、交接、Git 和审批数据保留在原库内。与任务绑定的历史问答仍从工作流模式读取。切换前可用既有备份流程保存数据库。
- 继续原有任务时，空间主机先执行 `stop --profile <owner-profile>`，再执行 `start --profile <owner-profile> --runtime workflow`，后续启动会记住该选择。切回时使用 `--runtime collaboration`。原本未设置运行模式的主机按新默认值启动。`create --runtime workflow` 可建立工作流空间。工作流原生注册使用 `connect --workflow-tools`，主机本地看板只在此模式启动。
- 带账号、工作台或 GitHub 的自托管部署显式设置 `--mode workflow` 或 `COOPAGENTS_MODE=workflow`。云端账号及计费仍由 `cloud` 模式提供。切换前确认服务仍使用同一个数据库路径。由账号管理的团队应继续用工作流或云端部署管理成员。

## 可复验范围

运行 `python -m unittest discover -s tests -p test_collaboration_core.py -v`。测试覆盖同时开工、别名、无关页面保持安静、过期、成员权限、跨空间隔离、竞争修订、旧库和默认建库。传输测试启动实际本机空间，在两个 stdio MCP 会话中发现、问答和保存选择，重启后由第三个成员的新 stdio 会话读回。协议测试用确定性客户端控制工具调用顺序。跨设备网络条件和自然语言模型是否会主动采用工具需要单独观察。
