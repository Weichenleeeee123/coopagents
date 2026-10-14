# 点对点异地入口（iroh）实现与验收

日期：2026-10-14。分支：`feat/iroh-direct`。原型结论见 [唤醒与点对点原型](wake-and-p2p-prototype-report.md)（位于 `feat/agent-wake` 分支）。

## 设计

- `create` 默认 `--network p2p`。主机在私有 `host.json` 保存 iroh 端点密钥；公开的端点 ID（公钥）写入邀请和成员 profile，跨重启不变，成员无需 reconnect。
- 主机的 `HostLink` 接受指向该密钥的 QUIC 连接，把每条双向流转发到本机公开协作端口。成员的 `MemberLink` 在自己电脑上**绑定与主机相同的回环端口号**，每条本地 TCP 连接对应一条 QUIC 流。因此 HTTP 的 Host/Origin 与本机访问逐字节相同，`LocalBoundary`、MCP 的 allowed hosts、WebSocket 的 Origin 校验和全部业务代码不变。
- 连接由主机密钥认证并端到端加密；网络允许时直连，否则经 n0 公共中继，中继只看到密文。
- `join`、`status`、`invite`、撤销命令、`human_operation` 和 stdio 桥接按需拉起成员链路；端口已被同一空间占用（桥接持有链路，或主机就在本机）时，先用 `/health` 核对空间 ID 再复用，被其他程序占用则明确报错，不换端口。
- 主机控制端 `/status` 报告端点 ID、是否在线和当前连接数；成员 `status` 报告直连还是中继。
- 依赖：`space` 依赖组加入 `iroh==1.1.0`（Windows/macOS/glibc Linux 有预编译包，musl 不支持）。Quick Tunnel 和 external 模式保留为兜底。

## 实现中发现并修正的问题

1. 转发任务需要强引用：asyncio 只弱引用任务，未引用的转发任务可能被回收。
2. QUIC 流结束时只能半关闭本地 TCP（`write_eof`），不能整条关闭，否则对端回复被截断。第一条流碰巧能通，第二条流必现失败。
3. Windows 连接已关闭的回环端口会反复重试，主机连接目标端口加 5 秒上限。
4. iroh 1.1 中，对端未读的 `reset` 不会让成员端挂起的读取结束；拒绝时改为停止读取并正常结束发送方向。

## 验证

| 项目 | 结果 |
| --- | --- |
| 传输测试（真实 iroh 端点，关闭中继与发现） | 1 MiB 全字节值往返、8 路并发共用一条 QUIC 连接、HTTP 与 WebSocket、密钥持久、主机重启后重连、目标不可达、错误公钥不可达；连续 5 遍稳定 |
| 运行时测试（真实进程） | p2p 创建、控制端报告端点、邀请携带公钥且不含密钥、同机加入复用端口、重启后端点不变、CLI 输出无密钥、畸形链接在联网前被拒 |
| 完整 Python 回归 | 490 项通过（原 477 + 新增 13） |
| Linux CI | 验收分支推送触发的完整 CI（3.11 / 3.13、网页、打包、容器）通过 |
| **跨网络产品验收** | 见下 |

### 跨网络产品验收（GitHub Actions 主机 ↔ 本机成员）

GitHub Actions 云主机（Azure 机房）用真实 `space_runtime create` 建 p2p 空间。邀请用本机公钥加密后以 artifact 交付，凭据不进日志也不进 Git。本机用真实 `join` 和 stdio MCP 桥接接入：

| 步骤 | 结果 |
| --- | --- |
| 加入 | 7.3 s |
| 首次 `status` 短链路 | 中继，1043 ms（建立后约 10 s 才升级直连，短命令来不及） |
| 桥接 `whoami`、`read_team` | 通过 |
| 实时事件（加入后新任务） | 2.0 s 内经 WebSocket 到达 |
| 认领任务 → 主机停止并重启 | 端点 ID 不变；桥接中断 8.8 s 后自动恢复，失败 1 次调用 |
| 重启后的新任务 | 实时收到 |
| `/api/me` 往返 | 中位 358 ms，最大 375 ms |
| 完成消息 | 主机收到后正常停止 |

证据：本机 `.local/accept/remote-member/member.jsonl`、`.local/accept/remote-host.log`（忽略目录）。验收用分支 `proto/iroh-space-acceptance` 和原型分支 `proto/iroh-remote` 不合并。

## 边界

- 远端是有公网地址的机房主机，打洞容易。两端都在家用 NAT 或移动网络 CGNAT 后的情况仍未测，可能只能走中继。
- n0 公共中继和发现服务在境外；没有代理时能否连通未验证。后续应支持配置自建中继（iroh 提供 `RelayMode`/`insert_relay`）。
- 桥接长期持有的链路当前不报告路径，只有短命令的 `status` 报告；且短命令通常在升级直连前就结束了。
- 所有 p2p 成员连接在主机上都表现为来自 127.0.0.1，`/api/join` 的按地址限流被共享。
- 两个空间恰好选中同一端口时，同一成员无法同时加入两者（报端口冲突）。
