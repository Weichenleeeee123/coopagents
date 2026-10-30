# 项目信息架构原型实施计划

日期：2026-10-30。按已确认的信息架构先实现独立原型，当前会话内执行。

**Goal:** 用可点击页面验证六项导航、项目切换和跨对象查找，不迁移正式前端。

**Architecture:** 静态 HTML/CSS/JavaScript，合成数据保存在独立 data.js；app.js 负责 hash 路由、渲染、筛选与对象详情。直接打开 HTML 即可运行，不需要后端或外部字体、脚本服务。

**Tech Stack:** 原生 DOM、原生 dialog、Lucide 图标路径、已有品牌 PNG、Node、Playwright CLI。

## 文件

- `docs/prototypes/project-workspace/index.html`：统一壳层、页面容器和对象抽屉。
- `docs/prototypes/project-workspace/styles.css`：轻量黑白布局、列表与手机菜单。
- `docs/prototypes/project-workspace/data.js`：三个合成项目，以及关联任务、请求、约定、文件、交付和多工具成员。
- `docs/prototypes/project-workspace/app.js`：可恢复的项目/页面/tab/对象路由和有限的本地演示操作。
- `docs/prototypes/project-workspace/icons.js`：从 Lucide 原始图标获取的本地路径与授权。
- `docs/prototypes/project-workspace/README.md`：原型边界、打开方式、查找任务和验证结果。
- `tests/workspace_prototype_regression.js`：纯路由/筛选/关联测试。

## 阶段

- [x] 检查正式页面与批准设计，确认独立原型范围并记录本计划。
- [ ] 实现稳定 hash 路由、合成对象关系和基本筛选，检查项目切换与越界对象。
- [ ] 实现概览、任务、协作、共享上下文、交付、成员六页，提供页内标签、详情与返回。
- [ ] 实现项目选择、项目设置、团队/个人入口和只读展示；所有演示修改仅在内存发生。
- [ ] 验证任务到 PR 再回任务、约定版本、队友 agent、共享文件、活动与诊断查找。
- [ ] Playwright 检查 1440/1280/768/390/320px、键盘关闭与焦点、前进后退/刷新、只读、空项目及长文本，检查截图。
- [ ] 记录验证及正式迁移边界，按阶段提交并提供 HTML 链接。

原型不使用真实凭据，不发起项目 API 请求，不代替 Harness/双机验收。保留所有文件；截图与原始浏览器记录放在被忽略的 `.local/`。
