# 1.0 P0 验收执行记录

更新：2026-11-01。起点：`bbb0b60`，开发代码尚未发布。用户授权逐项执行 1.0 P0；本记录区分准备、自动化回归、原生模型和外部设备证据。

## 执行约束

- 所有新运行使用独立目录，保留失败及成功证据，不删除文件。
- 不修改真实用户的原生 agent 配置；原始记录、认证和邀请仅留在忽略的 `.local/`，不提交 Git。
- 配置、协议往返、模型真实工具调用、服务器状态及跨设备结果分别判定，不以其中一种替代另一种。
- 两台设备由同一维护者控制，只计跨设备证据，不能计为两位用户独立使用。

## 当前状态

| P0 | 状态 | 后续条件 |
| --- | --- | --- |
| Claude/Codex 新流程真实冷启动 | Claude 创建、Codex 加入及新会话文件问答经恢复完成；Codex 创建、跨会话宿主恢复与原生身份读取通过 | Windows 私有文件发布与宿主生命周期已修复；干净开发提交完成 Codex P2P 创建、注册、已完成诊断挑战及新会话 whoami/read_team。仍需发行包首次安装与完整冷启动问答重验，不能将 host-only 验收算作全部冷启动通过 |
| 双设备 P2P 与恢复 | Windows ↔ Linux 真实中继连接、持久身份和主机重启恢复通过；两个方向真实模型问答经恢复完成 | Windows 模型发问、Linux 模型读取本地文件回复、Windows 新模型会话消费准确回复；反向 Windows 原生回复已验证，Linux 升级官方 Codex 0.166.0 后新会话消费准确答案；两位用户及双方家用/移动 NAT 待验 |
| 跨设备 Claude 唤醒与 Codex 待命 | 两者实际跨设备事件触发的模型回复通过；Codex Esc/后续输入通过 | Linux 合成 MCP 驱动发送，Windows 原生会话读取请求并 reply 准确文件内容，服务端独立核对。Codex 正常界面审查唯一 Stop hook、显式待命 120 秒；Esc 后输入标记获准确回应，恢复待命后处理远端请求。不算 Linux 模型发问通过 |
| 七种 Harness / Windows、macOS、Linux | Pi 原生同机闭环通过；Kimi 经请求方恢复完成同机闭环；Codex 跨设备两个方向经恢复完成；OpenCode 原生 MCP 握手通过 | 其余实际闭环及 macOS 待验；OpenCode 旧配置所选模型返回 401，官方免费模型受额度限制，Claude 旧模型返回 503、有效模型已完成文件问答，但后续交互调用仍有 API 错误；Cursor/ZCode 仍需实际桌面会话；Kimi 原回复会话超时保留；恢复会话已消费并解决；OpenCode 官方最新免费模型被上游明确拒绝（额度耗尽） |
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

Windows 与 Linux 由同一维护者操作，连接使用 relay，记录 RTT 约 0.7–1.1 秒。主机重启后既有 Linux 身份无需新邀请即可恢复；模型完成 Windows 发问 → Linux 文件内容回复 → Windows 消费回复。初次出现的暂时传输不可达保留为失败证据，恢复后的协议诊断成功；未据此修改传输代码或声明稳定性达标。反向补验中 Windows 模型通过原生 reply 回复自己的本地文件，Linux 新会话已消费准确答案；旧客户端失败与恢复过程保留，不能描述为首次顺畅通过。

真实 App 仅安装到专用合成测试仓库，checks/contents/metadata/pull_requests/statuses 均为只读。CLI OAuth 身份仅用于准备合成仓库；验收读取和用户连接使用实际 GitHub App，不能混算身份。

## 回归与发行验证

当前候选 a8ac75d 的本轮实验回归 52 项、CI 定义的 31 条 Node 检查通过。发行包成功构建并检查含新增 binding renderer 与 issuer 修复；在全新专用虚拟环境安装 wheel，包导入、绑定页面渲染和文档指定的 space_runtime CLI help 通过。首次无隔离构建因本轮虚拟环境缺少 setuptools 失败，安装声明的构建依赖后通过；未修改产品代码。首次 wheel smoke 使用不存在的 `python -m coopagents` 入口失败，改用文档入口后通过，不将其误报为产品回归。

当前本机 Docker Engine 不可连接；9ffdc77 的 CI 已通过容器启动/TLS、Python 3.11/3.13 核心及实验、Node 和发行构建。后续提示修复候选仍以对应 CI 为准。完整 Python 首次回归 661 项，1 项退出清理错误、1 项跳过；定位为拒绝响应正文未消费即关闭，在 Windows Proactor 连接重置时阻塞 server.wait_closed。测试先读完响应后关闭，test_web 的 7 项通过；完整回归重跑 661 项通过、1 项跳过（403.336 秒）。

Kimi Code 2.4.1 原生使用 default/manual 模式逐次批准 10 个 Coopagents MCP 操作，未启用 auto/yolo 或隐含 Never Ask 的 `-p`。原适配器被加载，实际身份、任务认领、harness session、进度、请求、收件确认和准确回复均有原生记录及数据库证据。回复完成后 ACP `session/prompt` 在 180 秒内没有最终返回；保留超时，不重放写入。请求方最终消费与解决未执行，故不标完整通过。

GitHub 使用真实个人账户专用私有 App。签名 installation.created 投递 HTTP 200，持久队列一次完成并后台刷新；同 delivery 重投返回 duplicate 且未重复执行。installation.deleted 投递处理后连接 revoked，页面不再显示旧交付/Release，数据库仍保留四条历史证据；手动刷新不能复活，GitHub 查询旧安装返回 404。新安装经新的用户授权和 finish 后仍不展示旧缓存，随后 refresh 重新生成四条新鲜证据；保留原任务关联，任务仍 open/unowned。真实 PR/提交分别读取三项成功检查；Release 为 prerelease，不能算 published release 或资产下载验收。

普通仓库事件补测也通过：向合成分支新增测试文件后，真实 push、pull_request.synchronize、check_run、check_suite 和 release.edited 均由 GitHub 投递 HTTP 200，持久队列全部完成，无失败或待处理项。未手动 refresh，后台 worker 已将 branch/PR 更新为新 HEAD，原完整提交关联仍新鲜可读，四条证据仍为 github_verified。未强推、未合并、未删除文件。组织安装审批、强推、合并/关闭 PR、status 专门事件、正式发布/资产截断及线上限流未实测，不从当前结果外推。

验收器复查修正了 Codex 读取提示矛盾，并将非交互 MCP 授权限定到当前私有空间、当前阶段的明确工具；协作沙箱为 read-only，未全局放开工具。唯一一次补测中，原生日志明确拒绝精确 Get-Content 只读命令（blocked by policy），反向回复仍为零；未绕过执行策略，不把提示文字或请求送达算成成功回复。

候选 `1e05f44` 的 GitHub CI 中，容器构建/启动/TLS smoke 作业通过，Python 3.11 核心测试及 Node 检查通过；实验测试因 CI 使用全局 Python 而验收器坚持隔离环境失败，另一版本作业被矩阵 fail-fast 取消。修复方向是在 CI 为实验建立继承已安装依赖的独立 venv，测试显式传入合成可执行占位路径，不依赖真实 Claude/Codex PATH，不放宽实际验收器的环境校验；修复提交 `324903f` 的 [CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/41193460098) 全部通过：Python 3.11/3.13 核心与实验、Node、发行构建，以及容器启动/TLS smoke。

维护者确认暂时没有 macOS。Claude 配置已更新，重新执行真实预检；OpenCode 改为尝试官方免费模型。此前 503/401 保留为历史失败，新结果另记，不覆盖旧证据。

Kimi 后续仅启动一次新的请求方恢复会话，沿用保留的请求与准确回复，未重放写操作。default/manual 模式四次逐工具 allow_once 完成 whoami、read_team、resolve_request、report_progress；原生 end_turn 正常，最终模型输出消费准确回复，数据库显示请求 resolved、进度 local_done、请求/回复行数不变；11 项独立检查通过。原回复会话的 180 秒超时继续保留。私有恢复脚本在原生成功后的汇总收尾误用 update 导致 ValueError，原始失败汇总保留并由独立证据文件纠正，未改产品代码或伪装成原流程无失败。

Claude 模型问题已用单变量预检定位：同一 provider/认证，默认 sonnet[1m] 解析为 sonnet-4-5-20250929[1m] 并 503；仅本次调用改为 sonnet 后解析为 claude-sonnet-5，预检 exit 0。不能继续称为已证实的整端点故障。正在用有效的模型选择重测完整路径，真实用户配置未修改。

OpenCode 按维护者要求改测官方免费模型：保留 1.1.65 的旧模型不存在/超时证据，随后隔离安装官方稳定版 1.19.5，下载资产 SHA256 与官方发布值一致。当前 native inventory 明确标记 glm-5.3-flash-free 为 active、支持 tool call、输入/输出/cache 费用为零；无认证复制、无付费凭据。客户端成功进入实际 model stream，官方上游明确返回 Free usage limit reached，停止预检，未开始完整 MCP 工作流。该限制不能算 Coopagents 适配器失败，也不能算原生模型验收通过。

Claude 冷启动在有效模型下暴露两处验收器问题：Git Bash 将 Python 路径规范化为 /c/...，精确 runtime-helper 授权缺少这个等价拼写；原生 permission_denied 的 message 为字符串，解析器错误地假设字典。提交 9cce8c9 增加同一 Python 路径的 Windows/slash/MSYS 等价写法（仍只允许指定模块），并安全解析非结构化消息。红绿回归后 23 项针对性、50 项实验测试通过；新完整真实流程与候选 CI 继续执行。

## 2026-11-01 收尾补验

Claude 创建/Codex 加入原流程基于干净源码 9ffdc77，前五阶段实际完成原生注册、双方 doctor、持久身份核对、发问、Read 文件及 MCP reply。原最后消费阶段中断，保留原 prepared 状态，不改写成一次完整成功。恢复使用 Windows 桌面 Codex 0.166.0-alpha.5.1，原生 whoami/read_team 均成功并消费准确答案；独立只读验算确认双方身份、服务端请求/回复及双方已完成诊断，六项检查全部通过。恢复脚本最初汇总错误地把 list 传给要求 set 的诊断校验器，原失败保留；随后只重做独立验算，没有重放模型或写操作。

Linux Codex 0.146.0 的 app-server 启动诊断已发现原生注册的 whoami/read_team 工具；旧模型会话却只访问资源列表，并伴随模型目录缺少 base_instructions 的格式错误。因此不能将问题直接判为桥未启动。隔离安装官方 @openai/codex 0.166.0，保留旧版本、配置及失败日志后，沿用既有反向请求与 Windows 的准确原生回复，仅新建 Linux 消费会话。原生 whoami/read_team、身份及准确答案消费全部通过，主机已正常停止。该结果支持两个方向的跨设备问答经恢复完成；不证明双用户或双 NAT。

Codex 主机创建路径另行补验未通过：当前 Windows 原生沙箱中 space_runtime create 在 profile.json 的原子硬链接发布处返回 WinError 5，MCP 未注册、doctor 未通过。未扩大权限、未绕过沙箱，保留 pending 文件与失败流程。普通只读文件访问已通过 prefer_mxc 与运行环境 SYSTEMDRIVE 的修正恢复，不能再把读取失败与本次创建硬链接限制混为一谈。

Claude 唤醒补验使用独立 home、正常原生目录信任及助手命令安装的 SessionStart/Stop hooks。交互会话显示 Sonnet 5，但初始模型调用出现 API 错误并重试，尚未进入可验收的空闲阶段；hooks 安装和界面启动不能算唤醒通过。

Claude 空闲唤醒随后取得真实证据：首次原生调用多传 _noargs 而被严格拒绝；明确使用空对象后 whoami/read_team 真实成功，Read 已读取本地合成文件。Stop watcher 进入 watching。Linux 新模型会话此时未暴露原生工具，没有发送请求；随后使用 Linux 合成 MCP 驱动，在持有真实 P2P member_link 时发送唯一测试请求。没有再向 Windows 会话输入任何内容，watcher 记录 woke，Claude 实际被 asyncRewake 唤醒并通过原生 MCP 读取请求、回复准确文件文本，服务端独立核对通过。保留初始 API 重试、参数错误及驱动首次未持有链路的失败；只计跨设备事件驱动的 Claude 模型唤醒回复，不计 Linux 模型发问通过。

当前源码 a8ac75d 本机实验回归 52 项通过；对应 [CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/41266895397) 全部成功。原始配置、运行记录与恢复脚本仍只保留在忽略目录，没有提交认证或实验数据。

Codex 交互验收也完成：独立配置及正常沙箱，在原生界面审查 helper 生成的唯一 Stop hook，确认解码命令仅指向本轮 Python、space_wake watch 及 owner profile 后信任。明确启用 120 秒待命。初始模型将待命理解成自行轮询/sleep，保留记录；澄清后模型立即 final，由 Stop hook 等待。READY 后 watcher 进入 watching，Esc 中断留下 turn_aborted(interrupted)，随后输入 INPUT_AFTER_ESC_OK 得到准确回应并再次进入待命。Linux 合成驱动第一次仅在身份读取阶段超时，没有发送请求；新运行持有同一 P2P link，限定三次只读预热后发送唯一请求。Codex watcher 记录 woke，模型读取本地 answer.txt 并 native reply 准确文本，六项独立检查通过。测试后关闭原生会话、standby off，并停止本轮 P2P 主机；GitHub App 服务继续保留。

Windows 私有文件发布问题已定位并修复（ebec0b6）：同一实际原生沙箱内，不含凭据的最小样本硬链接返回 WinError 5，原子重命名成功。Windows 改为写入第二份受保护且 fsync 完成的 publication 文件，再通过不覆盖目标的原子 rename 发布，原 pending 文件保留；其他平台继续使用原硬链接。原代码在禁止硬链接及并发竞争两个回归测试中失败，修复后 14 项 Profiles 回归通过，覆盖不可覆盖并发赢家、保留 pending 和原有身份边界。对应 [CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/41268150786) 已全部成功。

修复后的真实 Codex 创建补验基于干净 ebec0b6：已创建空间与原生 MCP 配置，随后独立 doctor 发现宿主不可达，正常 start 恢复后仍未通过，不能计为 Codex 冷启动通过。运行日志只有服务启动，没有运行时异常；原生日志确认使用 Windows MXC 沙箱。当前证据指向原生命令结束后的后台进程生命周期限制，但尚未完成因果验证。原验收器记录 shutdown_failed，独立复核确认 owner runtime 不可达且运行锁已释放；原失败摘要保留，没有存活宿主。

随后用无网络、无凭据的最小子进程实验进一步确认生命周期差异：Windows 原生沙箱命令只启动一个 sleep 子进程并返回；命令结束后该子进程已退出，而同参数从普通宿主启动的对照子进程仍存活。对照进程已由本轮实验停止。该证据确认当前 Windows Codex 沙箱不会保留这种后台宿主，后续需验收正常的进程托管或针对运行时启动的明确原生权限审批；不能把硬链接修复算作完整创建路径已通过。

本轮还尝试进入 Cursor 桌面验收，但电脑控制工具初始化报本地资源路径不存在，未能进入实际 GUI；本机 Cursor CLI 也没有 agent/chat 子命令。没有因此宣称 Cursor 模型或认证失败，仍保留为原生桌面流程待验。

ebec0b6 完整 Windows Python 回归 663 项通过、1 项跳过（452.226 秒）；发行 sdist/wheel 构建通过。该候选对应 CI 的 Python 3.11、3.13 及 container 作业均成功，包含实验、Node、构建与容器/TLS 检查。版本字符串仍为 0.9.0；这是未发布候选构建，不是 1.0 发布证明。

## Windows 原生命令宿主生命周期修复

`e74bb04` 实现显式注册的 local/P2P owner 原生 MCP 连接恢复宿主：使用原 profile、数据库、端口及 P2P key，跨进程管理锁串行化启动，失败锁定防止反复拉起。显式 stop 持久暂停，重连不会解除；显式 start 恢复。成员、未注册 owner、quick tunnel 和外部部署不自动启动。doctor 只报告当前离线与下一步，不替调用者启动宿主。[设计与边界](windows-native-host-lifecycle.md)说明关闭所有 owner 原生会话后可能离线，协作时须保持 owner 会话打开。

干净 `3d1edc3` 使用 Windows 原生 Codex `0.166.0-alpha.5.1`、正常 MXC 沙箱及既有默认模型，完成全新 P2P 创建、原生注册、持久诊断挑战和新模型会话 whoami/read_team 的保存身份匹配。结果为 `host_verified_partial`，测试后主动停止原空间，未由验收器替原生 MCP 执行恢复。会话退出后离线的已完成挑战，仅用绑定 room/member 的 owner 数据库只读核对；这不是当前在线证明。

独立真实生命周期验收完成 9 项检查：先模拟意外进程退出，原生新会话恢复并 whoami/read_team；会话存活期间独立 HTTP doctor 完成身份和挑战；profile 字节不变；显式 stop 后新会话无成功工具访问、运行锁释放且没有宿主；显式 start 后新模型会话再次 whoami/read_team、在线 doctor 及身份保留。全部通过，随后停止合成宿主。未修改真实配置、模型、沙箱权限或 GitHub App 服务。

失败过程保留：首次验收器在整个 Codex 会话结束后要求宿主在线，导致诊断失败；调整为会话存活期间验证在线挑战，会话结束后只核对历史证据。另外两次原生会话没有提供 Coopagents 工具，其中一次在显式恢复阶段；局部 MCP 连接诊断下重跑全部通过。尚未证明这些原生工具发现差异的原因，不能把一次完整通过外推为所有客户端会话均稳定。

本机完整核心回归 670 项通过、1 项跳过（500.220 秒）；实验回归 53 项通过；sdist/wheel 构建成功，wheel 包含新的宿主恢复模块和 Skill。`3d1edc3` 对应 [CI](https://github.com/Weichenleeeee123/coopagents/actions/runs/41270097304) 的 Python 3.11/3.13、实验、Node、构建及容器/TLS 均通过。独立代码审查未发现确定的产品正确性或安全缺陷，提出的跨进程竞争、quick/external 排除及数据保留覆盖随后补验；本轮仍不发布 1.0。
