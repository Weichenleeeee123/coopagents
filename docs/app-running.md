# 本机运行

在项目仓库根目录使用 Python 3.11 或以上版本：

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[service]"
```

完成下面的密钥配置后启动服务。默认监听 `127.0.0.1:8787`。正式 MCP 地址为 `http://127.0.0.1:8787/mcp`；健康检查为 `http://127.0.0.1:8787/health`。服务数据保存在仓库的 `.local/crewmesh.sqlite3`。从其他工作目录启动时，使用绝对数据库路径，避免生成另一份数据库。

## 网页使用

首次启动前生成密钥并配置到环境；即使回环访问，账号初始化也需要明确密钥：

```powershell
& .\.venv\Scripts\python.exe -c "import pathlib,secrets; p=pathlib.Path('.local'); p.mkdir(exist_ok=True); f=(p/'bootstrap-secret.txt').open('x'); f.write(secrets.token_urlsafe(32)); f.close()"
$env:CREWMESH_BOOTSTRAP_SECRET_FILE = (Resolve-Path .local/bootstrap-secret.txt).Path
& .\.venv\Scripts\python.exe -m crewmesh.server
```

已有密钥文件时直接配置路径，不重新生成。打开 <http://127.0.0.1:8787/>，首次初始化账号，输入密钥、用户名和 12–256 字符密码；初始化后关闭该入口。登录后建立团队与项目。团队邀请明确选择角色和项目，24 小时有效且单次使用；新成员通过邀请注册，已有账号登录后接受。新项目初始仅创建者可访问，团队成员身份不会自动授权所有项目。

账号会话由七天 HttpOnly Cookie 保存，刷新页面从服务端恢复。密码和账号 Cookie 不存浏览器 storage。选中项目后获得该会话绑定的临时网页凭据；切换团队/项目或退出清除原项目界面与过期响应。独立 agent 令牌在「接入自己的 agent」轮换并安全保存。

旧版个人网页凭据可通过「旧版凭据访问」继续使用。要迁入账号团队，在团队界面用有效 owner 网页凭据认领旧项目；数据保留，历史协作者继续持有原项目权限，不自动绑定账号。当前地址只用于同机验收，第二台电脑不能直接连接回环地址。

默认进入「任务看板」，通过「新建任务」声明工作；让自己的 agent 通过 MCP 认领、登记会话和汇报进展。任务自动分为待认领、推进中、遇到阻塞、待验收和已合并，支持搜索与负责人组合筛选，点击卡片查看详情与关联记录。待验收对应 local_done / pushed / pr_open，已合并对应 merged，均为 agent 自述，不新增网页完成审批或拖拽状态操作。

在「技术请求」查看读取、处理与回应记录，对未分派请求指定成员，由原发起人成员确认已有回复的请求解决。「公共约定」针对明确版本批准或拒绝，待审或被拒绝的新版本不会覆盖旧生效版本。

「接入自己的 agent」提供 Codex 桌面、CLI 和 Claude Code 配置模板。模板中的 TOKEN 需替换为个人 agent 令牌；网页可以轮换令牌，但必须随后更新工具配置。具体步骤见 [Agent 接入](agent-connection.md)。

网页每五秒拉取一次数据，断线保留最后记录并提示最后同步时间；这不是实时在线检测，也不会唤醒 agent。401 凭据失效会清除当前会话和私密展示。进展属于 agent 自述，范围交叠提示依据声明路径，均不代替 Git 验证。

可用 `--port 8789 --database '绝对路径.sqlite3'` 指定另一份独立实例。服务默认绑定本机回环地址；跨电脑使用时按 [部署与运维](deployment.md) 显式配置 HTTPS 公网模式。启动失败时先检查端口占用；不要停止不属于当前实例的进程。

## 身份与接入

创建房间会签发当前成员的网页凭据与 agent 凭据。owner 可以生成一小时内有效、仅可兑换一次的邀请，队友兑换后获得自己的凭据。操作身份来自凭据，不能填写 author 冒充另一成员。

旧版 / 独立项目新签发的网页凭据有效 30 天，agent 凭据有效 90 天。账号选择项目生成的网页凭据还受父账号会话到期与撤销约束，最长七天。个人可用网页凭据轮换自己的 agent 令牌；旧 agent 令牌立即失效，随后需要更新 MCP 配置并重建连接。已有老库中到期值为空的历史凭据保留此前行为。接入步骤见 [Agent 接入](agent-connection.md)。

凭据只存本机必要位置，不放进地址栏、聊天提示或 Git。数据库保存凭据摘要；持有网页凭据的人具有对应成员的人工决定权限。本地账号支持本人改密、团队管理员按角色限制重置；忘记最后一个管理员密码时使用下面的离线恢复。没有邮件恢复。cloud GitHub OAuth 需显式配置，默认自托管无提供方依赖。

## 数据与停止

在运行服务的终端按 Ctrl+C 正常停止。备份可在服务运行时通过 SQLite 一致备份命令完成，目标使用未存在的新路径：

```powershell
& .\.venv\Scripts\python.exe -m crewmesh.backup backup .local/crewmesh.sqlite3 .local/crewmesh-backup-20261011-01.sqlite3
```

恢复同样写入新文件：将 `backup` 改为 `restore`，指定备份来源和新的数据库路径，停止服务后用 `--database` 指向恢复文件。详细验收、备份权限及恢复后令牌状态见 [部署与运维](deployment.md)。不要删除原数据库。测试生成独立 UUID 数据库，保留在 `.local/test-evidence/`。

已有原生接入实验使用端口 `8768` 和 `.local/agent-integration/runtime/`，与正式服务相互独立。不要把实验消息当作正式房间任务或约定。

## 验证

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

实施状态与实际通过的检查见 [P2/P3 验证报告](p2-p3-report.md)。本机 HTTP/MCP 通过不表示公网部署、双机连通或原生闲置会话自动唤醒已完成。

## 离线密码恢复

停止服务并先备份。具有数据库本机读写权限的运维人员运行：

```powershell
& .\.venv\Scripts\python.exe -m crewmesh.account_recovery --database .local/crewmesh.sqlite3 --username owner
```

终端隐藏输入两次新密码。CLI 只访问已有文件与已有本地账号，用户名使用与登录相同的规范化规则；密码没有命令参数，不记录日志。事务撤销全部账号会话及其派生项目网页访问。GitHub-only 账号不能离线设置本地密码。独立 agent 令牌未因改密自动轮换，需要在重新登录后按情况轮换。保护数据库和备份的文件权限，保留全部文件，详见 [部署与运维](deployment.md)。
