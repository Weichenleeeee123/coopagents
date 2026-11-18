# 自建中继（self-hosted relay）

日期：2026-11-18。分支：`feat/self-hosted-relay`。

实现 [点对点异地入口](agent-hosted-p2p-report.md) 中留下的“后续应支持配置自建中继”一项。默认行为不变：不配置时仍用 n0 公共中继；本分支只加配置面，不带任何常驻部署。

## 设计

- `create --relay-url <URL>`（可重复，最多 4 个），仅 p2p 模式接受；写入私有 `host.json` 的 `relay_urls`，`serve()` 传给 `HostLink`，`space_link()` 写进邀请链接，成员侧 `member_link()` 传给 `MemberLink`。JSON 描述文件原样携带；短邀请码（v2 编码只接受 `endpoint_id` 一个键）遇到带中继的邀请时回落到 v1 长码。
- 校验（`validate_relay_urls`）：只接受裸 origin（允许根路径 `/`，根路径以下的 path 不接受），不带 userinfo、query、fragment、控制字符；主机名先经 Python 规则校验（括号内只接受 IPv6 字面量，拒绝带 scope 的写法与 IPvFuture；非 ASCII 名称先经 IDNA 转换再校验，转换后成非法数字地址的拒绝、成合法数字地址的接受，joiner 直接拒绝；数字结尾的主机名按 WHATWG IPv4 规则校验，含空十六进制分量为 0、无效八进制拒绝；`xn--` label 须能解出非 ASCII 文本），再经 iroh 构造校验（装了 iroh 绑定时）：URL 必须能构造出 relay mode，否则拒绝——这是 IDNA 有效性的最终裁决，Python 规则只是近似；另有收窄：拒绝下划线、空 label、首尾连字符 label、百分号编码主机名、端口 0，转换后主机名 ≤253 字符、单个 label ≤63 字节，以及部分 iroh 接受但 Python IDNA 不兼容的拼写；非回环地址必须 HTTPS，HTTP 只允许回环（`localhost` 与 IP 回环地址，含 `::1` 的展开写法）；单条 ≤2048 字符，四个 URL 的 JSON 转义后内容之和 ≤1024 字符，保证邀请码可解码。
- iroh 映射：`RelayMode.custom_from_urls(urls)` + `preset_n0`。`RelayMode.relay_map(m)` 在 iroh 1.1.0 会段错误（exit 139），永不使用（代码中有注释）。
- 未配置中继时，`HostLink` / `MemberLink` 的构造调用与原来逐字节相同：`relay_urls` 只在配置了才传参，避免破坏已有 fake 与子类。
- iroh 上报的 `addr().relay_url()` 带尾部斜杠（`http://127.0.0.1:3340/`），与配置字符串比较时需先去掉斜杠。

## 运行一个中继

二进制：n0-computer/iroh 的 v1.1.0 release 有各平台的 `iroh-relay` 包（验证用的是 `iroh-relay-v1.1.0-x86_64-unknown-linux-gnu.tar.gz`）。`--help` 确认的全部选项只有 `--dev`、`-c/--config-path`、`-h`、`-V`：

- `iroh-relay --dev`：本机开发模式，plain HTTP，默认 3340 端口，忽略一切 TLS 配置字段。只适合回环验证。
- `-c/--config-path <CONFIG_PATH>`：生产用配置文件启动。按 iroh 文档，中继内置 ACME TLS，限流默认关闭（文档说法，本次未验证）。

背景（iroh 文档）：n0 公共中继免费但限流、仅供开发测试、无可用性保证，且没有中国区域；中继只看到密文包与元数据。生产路径是付费共享/独占中继，或自建。

## 验证（2026-11-18，VPS 临时中继，验证后已拆除）

临时中继 `iroh-relay --dev` 跑在 VPS 回环 3340 端口；scratch clone（`feat/self-hosted-relay`）+ venv，验证后中继进程、clone、venv、冒烟空间状态全部清除，VPS 无残留。

| 项目 | 结果 |
| --- | --- |
| 主机 home relay | `addr().relay_url()` 为自定义 URL，`online()` 为真 |
| 成员 home relay | 轮询后 `addr().relay_url()` 为自定义 URL（绑定后立即读可能是 `None`，需等端点连上 home relay） |
| 成员连接路径 | `path()` 为 `relay`，rtt 3–6 ms（拨号地址只带中继 URL、不带直连地址，强制走中继） |
| 字节往返 | 经成员回环端口 → 中继 → 主机 echo，`ping-relay` 原样返回 |
| 非对称拨号 | 成员用 n0 默认配置、目标地址带自定义中继 URL → 连通，路径为 `relay`；拨号用的是目标地址里的中继 URL |
| 发现拨号 | 只给端点 ID、不给地址（与正式邀请一致）→ 连通，路径为 `relay`；主机把带自定义中继的地址发布到了发现服务 |
| 全栈冒烟 | `create --relay-url` → `start` → `serve` → `space_link` 带中继 URL → 成员 `/health` 200 且 room_id 一致 → `stop` 干净 |
| 中继日志 | 默认日志级别下 0 行；路径证据以 `connection.paths()` 为准 |

回归对比（VM 上 `test_space_p2p`，前后同一 baseline）：基线 21 项，失败 1、错误 5；改动后失败集与错误集的测试名完全相同（均为 VM 沙箱禁 UDP 导致的 QUIC 错误），无回归。对比中发现并修掉一个真回归：无条件传 `relay_urls=None` 破坏了严格 fake 的构造签名，已改为仅配置时传参，并补了两个直通测试。

## 边界

- 成员侧配置的作用：拨号只看目标地址里的中继 URL；成员自己的 home relay 配置影响的是它自身的可达性与发现发布。配置了中继时，邀请携带 `relay_urls`，成员侧用同一组 URL；未配置时邀请只有 `endpoint_id`，两侧走默认 n0 中继。
- 验证时主机与成员在同一台机器上，中继在回环；跨 NAT 的中继承载未在此重测。强制中继的拨号（`addresses=[]`）+ `path()` 断言隔离了中继路径，但真实跨 NAT 部署仍需在目标网络复测。
- 生产中继需要 HTTPS（校验强制）；ACME 与配置文件细节以 iroh 官方文档为准，本次只验证了 `--dev` 形态。
- 无常驻部署：验证用的临时中继已拆除，何时为生产部署中继是后续决策。
