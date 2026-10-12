# 异地连接适配器验证

2026-10-12，L0。使用官方 cloudflared 2026.10.0 Windows AMD64 发行文件，SHA256 `86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c`，下载后与官方发布信息核验一致。工具文件只保留在本机 `.local/tools/`。

在独立回环端口启动只包含虚构 health 与 WebSocket echo 的服务，再经临时公共 HTTPS 地址请求并完成 WebSocket echo。测试服务不包含项目数据或管理接口；验收结束后只停止本次测试的服务和隧道，保留日志和文件。

首次强制 HTTP/2 时失败：隧道诊断显示 TCP 7844 不通，而 QUIC 探测成功，客户端请求出现 TLS EOF。随后改用自动传输选择，并等待实际注册连接后才访问公共地址；HTTP 与 WebSocket 往返均通过。产品启动应等待隧道连接就绪，不把获得 URL 当作公网已连通。

本机证据：`.local/network-probe-aa38974e98804a03b32cd0fa3edeba98/` 保存失败记录；`.local/network-probe-95e102cff79b44f69bcf8b6bd199b7b4/` 保存成功记录。原始日志不进入 Git。

边界：这是同一电脑经过第三方公网入口的真实往返，不是两台电脑、两个网络的协作验收。临时域名在重新创建隧道后会变化；长期使用仍需用户配置稳定 HTTPS 入口。此验证不证明端到端加密、服务 SLA 或空闲模型自动唤醒。
