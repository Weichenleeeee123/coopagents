# 品牌资产

## 当前图标（2026-10-31，v3）

用户已确认并启用黑白灰「协作 C」图标。深色底 `#202124`、白色圆弧与节点，与当前前端保持一致。生产文件为 `src/static/icon.png`，1024 × 1024 PNG，SHA-256 `a973fe97caf11a1ef4aacb9f6a92488f2ee47392f0e7968e1ae1e89b817ce401`。前端、浏览器标签图标、P2P 看板及中英文 README 沿用原资源路径，均使用新版。

设计产物留底：[`assets/coopagents-icon-v3/`](assets/coopagents-icon-v3/)，包含 SVG 矢量稿、高清 PNG、浅色版本、设计展示图和前端位置合成预览。设计说明见 [icon-design-v3.md](icon-design-v3.md)。

旧生产图标备份：[`assets/coopagents-icon-v1-original.png`](assets/coopagents-icon-v1-original.png)。早期 v2 草稿保留于 `assets/coopagents-icon-v2/`，仅作设计历史。现有产品截图记录的是换标前界面，保留作为历史截图。

## 旧图标生成记录

原图标（现备份于 `docs/assets/coopagents-icon-v1-original.png`）：使用内置 imagegen 生成，交织的青绿与象牙白带状 C 表达不同 agent 的协作。PNG，1254 × 1254，1,572,812 字节；SHA-256 `6247db54fa0a097b1e9c9224fc8d3320b6d95a85a0a6486d71b5ee6e317b2035`。

恢复脚本等待当前会话记录超时；本轮图像工具直接返回的唯一新产物已读取、核对并复制到项目，原始生成文件保留。未引用先前回合的图像。

## 生成提示词

```text
Use case: logo-brand. Create a single stunning premium app icon for Coopagents, an open source shared mission control for teammates' coding AI agents. Square icon, centered sculptural interlocking mesh: three thick smoothly folded ribbons creating an abstract angular C and a small precise central negative-space aperture. A memorable intelligent monogram symbol, not a robot or chat bubble. Dark graphite nearly-black rounded-square tile, crisp acid mint green and soft ivory ribbons, subtly beveled satin surfaces with restrained depth. Confident industrial design, sharp graphic silhouette legible at 32px, 16% safe margin around mark, front-on orthographic, perfectly clean uniform dark backdrop, no text no letters no watermark no mockup no extra panels. One final icon image suitable for GitHub README and web app branding.
```

## Product screenshots

The current README screenshots were captured on 2026-10-31 from the migrated production frontend at 1600 × 1100. The browser used the current source code served over local HTTP and a retained, isolated synthetic demo database populated through the real domain/API. No mocked API responses, injected data, or CSS restyling were used. Members and project names are fictional; repository references and task activity are fixture data, not real external GitHub verification. The settings page and harness versions are deliberately not presented as certified integrations.

| Asset | Page | Evidence boundary |
| --- | --- | --- |
| `assets/workspace-board-v2-2026-10-31.png` | Task board | Synthetic task/progress data; board is backed by the real self-hosted service |
| `assets/workspace-project-switcher-v2-2026-10-31.png` | Project switcher | Real authorized project list in the isolated demo account |
| `assets/workspace-context-v2-2026-10-31.png` | Shared agreements | Synthetic approved and pending agreements from the real domain API |
| `assets/workspace-members-v2-2026-10-31.png` | Members and agents | Synthetic session registrations; unknown versions are shown as unknown |
| `assets/workspace-delivery-v2-2026-10-31.png` | Delivery relationships | Synthetic local Git checkpoints; the relationships are observations, not a real GitHub ancestry graph |

The previous capture is retained at `assets/kanban-demo.jpg` for historical reference. Earlier 2026-10-31 screenshots showing the incomplete dark-sidebar implementation are retained in the ignored `.local/readme-refresh/before-migration/` evidence directory and are not promotional assets. All demo databases, browser state and raw captures remain under ignored `.local/readme-refresh/`.
