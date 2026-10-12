# 邀请链接与 Skill 接入实施方案

用户已批准：网页邀请链接加入项目，随后把接入 Skill 交给自己的 agent；不要求安装 Crewmesh 本地工具。

## 设计

邀请沿用现有团队角色、项目范围、24 小时单次有效邀请。邀请值放 URL fragment，不进入请求路径或查询串；打开页面读取并清除地址中的值，在注册/登录后由人明确接受，展示团队、角色、项目和失效状态。默认普通成员与当前项目，保留高级范围选择。禁止打开链接自动消费邀请。

Skill 为发行包内公开、无凭据的 SKILL.md，网页提供下载和复制引导。用户进一步明确授权：点击接入后的一段安装指令可包含个人 agent 凭据。服务验证当前项目权限，明确点击才发行额外个人凭据；不轮换已有连接。网页私有弹窗生成一次复制的 Skill 指令，不需要设备授权或轮询；关闭或切换清空，不写持久浏览器存储。身份/项目由当前认证解析。agent 仅配置原生 MCP，不安装 Crewmesh 工具，不绕过信任授权，不覆盖已有配置，不上传仓库或聊天。MCP 调用真实身份检查与 checkpoint 验证；需重启明确提示，未观察到原生自动同步不声称已通过。

## 实施阶段

- [x] 1. 邀请：workspaces.py/account_api.py 返回无副作用邀请预览与加入项目信息；accounts.js/app.js/index.html 生成 fragment 链接、读取/清除、预览、显式接受、新账号与已有账号流程；Python 和 Node 行为回归；阶段提交。
- [x] 2. Skill：新增本人项目接入凭据发行接口；公开 Skill 资源纳入 wheel；网页私有接入指令与 Skill 下载/复制入口；覆盖权限、CSRF、不轮换、异步隔离、无 token 日志；阶段提交。
- [x] 3. 独立规格与质量审查，修复发现；完整 Python/网页回归及发行资源检查；更新 docs/agent-connection.md 与验收报告；提交并推送分支并创建 PR。

验收命令：.venv/Scripts/python.exe -m unittest discover -s tests -v；node tests/account_ui_regression.js src/static/accounts.js；新增专项入口由阶段报告记录。所有原始证据放忽略的 .local/，不删除任何文件。
