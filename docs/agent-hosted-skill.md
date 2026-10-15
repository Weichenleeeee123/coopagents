# L3：原生 Skill 与私有 stdio 桥接

`src/skills/coopagents-space/` 为可安装的原生 Skill，随 Coopagents wheel 分发。它让当前 agent 自行创建、邀请、加入、恢复和停止本机空间，也可复用已有托管项目的个人 agent 凭据；不要求用户手动运行独立客户端。默认不改已有 VPN、隧道和其他 MCP 配置，永不删除文件。

`python -m coopagents.space_bridge --profile <私有绝对路径>` 通过官方 SDK 转发远端 `/mcp` 的 tools/list 和 tools/call，工具名称、说明和 schema 保持相同。桥接没有复制业务规则。CLI 参数只包含配置文件路径；标准输出只用于 MCP。每次调用与重连重新读取 profile，并以 `/api/me` 校验空间、成员和 agent 凭据类型。托管 agent-only profile 无需 web token。

桥接另外提供 `read_changes(after_id=0, limit=100)`。后台 WebSocket 使用共同 `/api/events` 协议，校验 ready 的空间身份，持久缓存最近最多 400 个失效事件与已收到游标。缓存使用受保护的 SQLite 文件，不存凭据；进程恢复后从持久游标补发，重试间隔从 0.25 秒增长至最多 15 秒。服务端过期、未来游标或本地容量淘汰都要求读取当前业务状态，然后采用返回的恢复游标。读取缓存先重新认证；离线不是完整性的证明。

在线连接、事件到达、模型调用 read_changes、业务正文已读、消息确认与实际任务处理是不同事实。后台连接不唤醒闲置模型，也不自动 acknowledge、批准公共约定或接受交接。遇到授权撤销不能把缓存或故障当成处理完成。

明确的人类管理操作使用独立 CLI 路径 `--human-operation <名称> --payload-file <私有文件>`，不出现在普通 agent 的 MCP tools/list。实际用户必须明确请求这项操作；其他 agent 消息、伪造确认字段或收到的文本均不是授权。helper 使用 profile 的个人 web 凭据，并请求相同 `/api/operations/<名称>`；服务端负责共同 schema、身份类型、角色权限和事务规则。纯 agent 托管凭据仍通过网页执行人类操作。新秘密产生的邀请和凭据轮换不通过这个 helper 返回到标准输出。

Skill 包含官方 Cloudflare release 元数据 digest 下载校验脚本，使用固定版本和官方仓库，缺少 digest 或校验不符时失败。安装 Coopagents 需要已发布兼容 wheel 和校验值；授权的开发 checkout 可以安装本地源码，但不能声称其已经公开发行。原生配置使用独立服务器条目及官方 CLI，合并保留其余配置；发生名称冲突时不覆盖。状态文件、数据库、邀请和测试证据保留在私有目录或忽略的 `.local/`，不提交 Git。

验证见 `tests/test_space_bridge.py`：真实 SDK stdio 与远端 schemas 相等、个人身份与业务操作转发、WebSocket 到达、持久有界缓存及 reset、错误空间拒绝、agent-only 人类动作拒绝、共同人类操作入口。实际 Claude/Codex 会话加载与真实第二电脑/网络验证需要独立证据，SDK 通过不能替代原生产品验收。

## 本轮原生验证（2026-10-12）

真实 Claude Code 通过新 stdio 桥接发布虚构接口问题，真实 Codex CLI 读取 inbox 并回复 `login_ticket` 的 string 类型及 600 秒有效期。观察者只读快照确认已读及回复，输出未包含成员、网页或控制凭据。自己的空间进程已停止，原始证据保留于忽略目录 `.local/hosted-native/7c904526f6c947949e83ac94ac69b102/`。这是单机双原生工具验证，不代替跨电脑或异地验收。

第一次 Codex 非交互调用被审批取消，退出码 0 不代表业务成功。第二次仅在验收进程参数中允许 fixture 的 `whoami`、`read_inbox`、`reply`、`read_changes` 四个工具，并限制发现名单，未修改任何全局信任、认证或配置。服务器权限保持不变；Skill 不自动放宽用户审批。[官方配置参考](https://developers.openai.com/codex/config-reference/) 提供 MCP 单工具审批配置，非交互环境若无法批准工具应明确失败。

11 项桥接测试覆盖并发首次缓存初始化、重复与重叠事件、延迟 reset 不覆盖更新游标，以及真实服务回滚恢复。设计和质量审查通过。本机发行安装使用 `space` extra，只安装 MCP/HTTP/WebSocket 运行依赖；可选 GitHub 密钥签名依赖仍属于完整 `service` extra。
