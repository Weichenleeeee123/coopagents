# DeepSeek Harness 协作沙箱运行手册

本手册描述 Coopagents 专用的多成员开发协作试验场。默认阿里云区域为新加坡 `ap-southeast-1`，仅作为可覆盖的部署默认值；用户当前云账号、配额、镜像可用性和网络策略尚未通过云端验证。

## 当前阶段

本仓库实现的是可审阅的部署与实验工具，不代表云资源已创建，也不代表模型或原生 DSH 验收通过。完整验收分为 G0 到 G5：G0 验证 API/DSH/MCP 兼容；G1 验证 VM 与身份隔离；G2 验证独立 NAT 和实际 P2P 路径；G3 验证无工具名提示的真实开发剧本；G4 验证对照与证据质量；G5 是之后的独立用户、住宅/移动网络扩展。每个阶段只报告已有观测支持的门槛。

本地协调入口 `experiments/agent-integration/dsh_sandbox/runner.py` 使用注入的 cloud/DSH/operator adapters，并把每次尝试写到新目录。当前测试只使用 fake adapters，结果标为 `harness_only`；它没有可用的云 provider adapter，也不连接真实 DSH。场景顺序、停止/留证、成本边界和人类决定协议已能本地验证，但不代表真实剧本执行。

## 凭据与外部服务

此前在聊天中粘贴过的模型 API key 必须先轮换。新 key 只能由操作者写入受控 secret manager，并在模型代理进程启动时注入 `LLM_API_KEY`；不得放入命令行、DSH VM、Terraform 变量文件、运行清单、提示词、日志、提交或实验输出。当前代码不自动连接模型服务。只有轮换后的凭据注入并通过 G0 后，才可运行一次受预算限制的原生模型探针。

实验模型配置由 `LLM_BASE_URL`、`LLM_MODEL`、代理预算和非敏感配置指纹组成。`LLM_BASE_URL` 使用用户提供的完整 Chat Completions 地址，不再拼接 `/chat/completions`。代理只转发固定模型，usage 不存在时成本保持 `null`。每个 VM 使用独立代理凭据和运行预算。

## 部署边界

拓扑由三台 agent VM 和一台独立 control-plane VM 组成。每个 agent 使用单独 VPC、子网、NAT 出口、成员身份、DSH profile、HOME、工作副本和 Git 分支。owner/host 位于前端成员 VM，Control plane 不运行 DSH 成员身份，也不承载 Coopagents 业务调用。任何 agent VM 都不挂载维护者主机目录、个人 DSH 配置、SSH 私钥或云凭据。

阿里云模板位于 `deploy/dsh-sandbox/iac/alicloud/`。它定义四组独立 VPC/子网/NAT/EIP/ECS、安全组和保留快照，但没有建立各 VPC 到共享代理/Git 的私有路由，也没有验证 agent 到 owner 的 P2P 可达性；这些必须在 apply 前纳入经审阅的网络方案。区域、实例规格、基础镜像及镜像版本需使用已验证输入；禁止直接填入秘密值。云资源只可在操作者审阅计划、预算和资源清单后由其显式运行。执行前必须确认 VM 到期标签、费用上限、无公网管理入口、三组独立 NAT 出口和私有管理通道。当前会话没有创建云资源。

镜像契约位于 `deploy/dsh-sandbox/images/`。由于当前无法从可信运行环境验证 Linux base image、DSH 包和镜像构建 digest，manifest 把这些版本留作必填、可覆盖输入；生成真实镜像前必须把它们解析成锁文件并通过 G0。bootstrap 只创建本机服务帐号和缺省 DSH MCP profile，不启用服务或注入成员/API 凭据。

Terraform 管理源只定义基础设施。不得把 `terraform apply` 放进自动 runner，也不得提供会删除磁盘、快照、证据或历史运行目录的清理动作。停止实例、保留磁盘/快照和保留本地证据是不同操作；每次运行写入新的 UUID 目录，不覆盖既有结果。

## G0 单机兼容探针

正式建三台 agent VM 前，先在一次性 DSH VM 检查：

- 固定版本的 DeepSeek Harness 能设置自定义 OpenAI-compatible provider，并请求完整 Chat Completions endpoint。
- 同一模型能够完成文本、多轮消息、native tool call 和 streaming；记录 DSH 版本、状态分类及确实由 provider 返回的 usage。
- DSH 能加载本机 Coopagents MCP gateway，工具身份只能对应这台 VM；验证 `whoami`、`read_team`、`work_brief` 和一次真实请求/回复。
- 模型代理不会把 provider key 转发给 agent，限制单 VM 预算，拒绝重定向，并且日志不含 prompt、源码、Authorization 或完整响应。

DSH MCP 客户端目前没有已验证的动态 Authorization header 注入契约。本沙箱通过每台 agent VM 的 localhost gateway 将调用交给该机持有的 bridge/P2P session；不得改用控制面业务代理或直接 HTTP 测试来替代 DSH 原生 MCP 验收。若 gateway 无法经真实成员 bridge 转发，G0 停止并记录阻塞。

## 场景执行

每轮由三种角色参与：前端实现依赖接口的 UI，后端从仅自己可读的源码回答 schema 问题，集成成员维护测试并观察责任边界。角色提示只给业务目标，不出现 Coopagents 工具名或调用序列。hidden tests、后端答案和随机 schema marker 留在控制面；agent VM 只拿本角色项目副本。

运行顺序包括：干净开工、跨责任接口问题、后端暂停时继续独立工作、后端重启后新 DSH 会话恢复、责任转交及旧路由回复拒绝、接口约定 v2 审阅、需要人决定的操作暂停、direct/relay/UDP-blocked 网络矩阵、三个私有分支的最终集成。人类接受交接或批准约定必须由实际操作者通过受支持的授权 UI/owner 操作完成。runner 只能观察结果，不能代写回复、回执、批准或成员事件。

control arm 和 Coopagents arm 使用同一模型、DSH 参数、seed、代码快照与隐藏测试；control arm 的人工中继逐次计时计数。臂顺序随机化。所有尝试（包括启动失败、超时、认证失败和预算停止）都进入结果分母。每个实验开始前固定重复次数；不得因为某个 arm 首次成功就提前停止。

## 网络证据和恢复

每个 agent 的 NAT/VPC identity 需要云清单与实际出口观测共同支持。运行时路径必须来自 P2P runtime 的 selected-path 事实：不能凭配置说 direct，也不能把 relay-only 成功说成 direct NAT 穿透。UDP-blocked 是预期不可达的负对照。agent 停止时，owner 服务保持运行并保留 server-side 请求；重启后显式启动新 DSH turn。DSH idle wake 尚无外部 wake 合约，不称为自动唤醒。

每次故障还要验证 cursor 恢复没有漏项/重复、凭据吊销后继续被拒、成员身份未串用、过期路由不接受写入。控制平面不可替代 owner host 或伪造业务数据。Control plane 或 owner host 故障时保存部分证据并停止本轮。

## 证据和指标

私有原始材料写入被 Git 忽略的 `.local/dsh-sandbox-runs/<run-UUID>/`，运行器不得覆写既有目录。提交和维护文档只包含脱敏实现与聚合结果。原始模型提示、源码、响应正文、token 和 cloud credential 不写结构化日志。

报告负责人命中率、首次有效答复时间、人工提醒/中继数、重复或过期请求、答复在后续 patch 中的可验证效果、隐藏测试结果、human-gate 越权次数、direct/relay/恢复路径、DSH tool call 数和 provider 实际 usage/cost。没有观测值时写 `null`，不按 token 估价伪装成实测。

只有真实原生 DSH 会话、成员工具调用、server-side 请求/回复、requester 后续代码效果和精确任务/会话/版本关联才能作为 native 证据。fixture/protocol 测试只证明测试覆盖的逻辑，不得升级成原生协作或用户接受结论。

## 停止条件

遇到 DSH provider/tool-call 不兼容、MCP identity 串用、未预期公网入站、agent 间文件可读、控制面承载业务调用、key 泄漏、预算或时限到达、owner host 不可用时停止当前运行并保留脱敏部分证据。不要静默重试、切模型、补写事件或在同一 run 目录覆盖结果。
