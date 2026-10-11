# Git 集成实施与验收

日期：2026-10-11。范围：用户批准的本地 Git + GitHub，按 G1 → G2 → G3 全部实施。真实 App 安装、公网与跨电脑验收尚未完成。

## 交付

| 阶段 | 已实现行为 | 提交 |
| --- | --- | --- |
| G1 | 共同仓库绑定、只读 Git 观测、实际变更路径重叠、事务离线队列、stdio 检查点 | `83f2fc7` |
| G2 | 独立只读 GitHub App、提交/分支/PR 关联、当前 HEAD 检查、签名队列、限流和补偿同步 | `b3d88be` |
| G3 | 仓库入口、卡片交付来源及新鲜度、自动分列、详情与记录、实际重叠展示 | `941f036` |

实施计划先提交为 `c7820d4`。新增源码保持在 `src/*.py`；维护文档在 `docs/`，原始证据和凭据仅在忽略的 `.local/`。没有删除文件、清理测试目录、切换商业化主工作区或提交其未完成改动。

### 本地 Git

适配器由成员在原有 Claude Code / Codex 的 MCP 配置中接入，服务地址必须由本机明确指定，个人令牌来自环境变量。Git 进程不执行 shell、hook 或 fsmonitor，不 fetch/push，不读取源码正文，不上传绝对路径或带凭据的 remote URL。默认只上报已跟踪文件的工作区变更。

同仓库项目采用 `.crewmesh/project.json` 的版本化公共标识；服务地址、令牌、agent 私有配置和原始数据不能提交。`repo_checkpoint(task_id)` 返回团队上下文、共享约定和收件箱；`link_delivery` 供任务负责人 agent 明确关联分支、PR 或完整不可变提交。

本地 SQLite 队列在网络校验前提交观测，保留请求键并幂等重放。非法任务 ID、无效 Unicode、超限路径和观测在入队前拒绝。并发调用只返回各自的检查点结果。快照保留有限工作区及路径预览；完整单条记录可按项目授权读取。观测超过五分钟不参与活动重叠提示。

### GitHub 与网页

账号 GitHub 登录与仓库 GitHub App 使用不同配置。管理员发起一次、十分钟内有效的授权；回调和完成连接均核验访问交集与当前权限。App 安装 token 限制到单个稳定仓库 ID 的只读权限。私钥、secret、用户和安装 token 不写版本库，用户 token 不持久化。

签名合法事件先保存持久队列再确认接受。worker 每五秒消费一条事件批次，每五分钟补偿同步；关闭时停止开始后续事件或项目，未完成事件保持待处理。网络失败或限流重试，不沿用 webhook 声称的旧 HEAD；重新授权必须成功核对后才恢复交付证据。

发现未关联 PR 时只读近期最多 50 个开放 PR 摘要；明确关联对象单独核对，保留已匹配 PR 的关闭/合并检查。每 SHA 的 checks/statuses 各限 100 项并标明截断，截断不能证明全部检查通过；项目关联最多 100 个，操作最多 150 请求/60 秒，GitHub 快照最多 500 KB。超限同步保留上次证据及时间。

看板区分 agent 自述、本地 Git 观测和 GitHub 验证。过期远端记录保留来源及时间但不驱动分列；明确受阻优先。独立历史提交不会把已合并 PR 的任务退回“已推送”。合并只记录交付，不替代任务验收或公共约定审核。

## 实测

- `python -m unittest discover -s tests -v`：Git 集成独立回归 **245 项通过**（86.388 秒），含 worker 停止信号及应用集成测试。随后通过 Git 合入商业化的已提交 `b57c72d`，合并结果完整回归 **319 项通过**（96.729 秒）；三组网页回归再次通过。
- `python -m unittest discover -s tests -p 'test_github_*.py' -v`：39 项通过，使用离线 HTTP transport / provider；路由专项 4 项通过。
- `python -m unittest discover -s experiments/agent-integration -p 'test_*.py' -v`：21 项通过，不代表原生双向协作实际通过。
- 三组 Node 回归通过：Git 证据、新鲜度、安全 DOM、授权控制、项目切换、历史排序；延迟响应的会话隔离；既有账号及项目界面。
- 两份从同一源真实 `git clone` 的工作区使用不同成员 token，在真实 HTTP 服务和官方 MCP SDK stdio 下汇报同一变更路径、得到重叠提示。共享约定从 v1 审批到 v2 后被另一成员读取；本地适配器完成提问、处理确认、回复和解决闭环。
- 官方 SDK 检查了 MCP 原始参数校验，布尔任务 ID 不能被转换后执行；离线/并发重放及错项目拒绝通过。
- 真实应用边界、OAuth callback 路由和 lifespan worker 接受离线签名事件、自动核对并完成队列记录。测试没有绕过正式 host/origin 或认证边界。
- Playwright 实际 Chromium 检查了自动合并列、任务详情、实际路径重叠、输入跨轮询保留、授权按钮跨重渲染保留、回调与 finish、切换项目后清空上下文；390px 页面未横向溢出。数据为明确的演示成员和离线 GitHub provider。
- 最终源码包与 Wheel 构建成功，`pip check` 无损坏依赖。Wheel 在独立 target 安装后通过实际模块导入、增量数据库迁移、ready 和 Git 静态资源检查。新增 `compose.github.yaml` 显式挂载 GitHub secrets，默认 Compose 保持 App 可选。

本机原始记录位于隔离工作区 `.local/`：`git-final-tests.log`、`git-release-tests.log`、专项日志、`.local/test-evidence/`、浏览器截图及 `.local/release/git-integration/`。这些文件不提交。浏览器未登录的 `/account/session` 401 为既有会话探测；未发现新增脚本异常。

## 外部验收边界

当前没有真实 GitHub App 配置及部署目标。尚不能确认实际安装与组织批准、公网 HTTPS callback/webhook、实际检查事件、在线限流和权限移除恢复。新本地 Git 适配器的 Claude / Codex 原生入口及真实跨电脑验收也尚未完成；官方 SDK、同机双克隆及历史入口截图不能替代它们。

本机 Docker daemon 未运行，未声称本机构建容器。代码提交 `fafb06b` 的 [GitHub CI](https://github.com/Weichenleeeee123/crewmesh/actions/runs/38124665616) 已于 2026-10-11 完成并全部通过：Python 3.11/3.13、245 项测试、21 项实验回归、三组网页回归、源码包/Wheel、实际 Docker 构建、容器启动及 deployment smoke。这里的 smoke 仍不包含真实 App 与公网验收。

部署步骤见 [本地 Git 接入](git-local-setup.md)、[GitHub App 配置](git-github-setup.md) 和 [部署运维](deployment.md)。回调与 finish 需落到同一服务进程；本轮没有跨进程用户授权 token 共享。

## 并行商业化工作

基于已提交的 `176bb50`（含主线账单领域 `fe5b431`）在 `feat/git-repository-integration` 隔离实现。初次发布前远端 main 为 `fe5b431`，主工作区的支付模块仍未提交。发布期间商业化对话将 `b57c72d` 推送 main；本分支用 Git 合并为 `658aaf8`，文档索引自动合并且完整 319 项回归通过。其仍未提交的 API 测试和报告没有被复制、暂存或覆盖。本 PR 相对 main 只包含 Git 集成变化；后续共同 API 或页面改动继续通过 Git 汇合。

公开交付：[PR #1](https://github.com/Weichenleeeee123/crewmesh/pull/1)。主工作区和隔离工作树及所有原始证据均保留。

### 合并前的商业化 API 兼容验收

用户选择 Create a merge commit 后，远端 main 已推进至 `3004c73`，包含支付 HTTP API 和持久事件 worker。本分支再次合入已提交主线，解决 `src/api.py` 的共同服务初始化冲突：保留 `github_app` 与 `billing_config` 两个配置入口、两组路由，以及各自后台任务的启动、停止和资源关闭。`src/server.py` 同时传递两组配置。商业化主工作区中的网页和其他未提交改动没有被暂存、复制或覆盖。

合并结果完整 Python 回归 **348 项通过**（124.972 秒）；随后新增的 Git 与支付共存专项 **1 项通过**。专项使用离线 provider，检查两个 worker 同时执行、账号账单与 Git 快照路由、Git OAuth 回调边界、无关查询拒绝及退出后两个任务停止和账单执行器关闭。独立审查未发现合并阻塞问题。三组 Node 网页回归和 **21 项**实验回归通过，`pip check` 无损坏依赖，源码包和 Wheel 重新构建成功。

原始记录保留在 `.local/git-final-merge-tests.log`、`.local/git-final-merge-experiments.log`、`.local/git-merge-build.log` 和 `.local/release/git-merge-final/`。GitHub 最终 CI 与 merge commit 以 PR 的检查和合并记录为准；以上离线验收没有扩大真实 App、公网或跨电脑验收的声明范围。
