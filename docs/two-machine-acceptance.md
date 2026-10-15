# 真人双机验收清单（0.6.0rc2）

目的：验证此前单机测试无法证明的三件事。

- 双方都在家用或移动网络后面时，点对点能否连通，走的是直连还是中继
- 能否跨电脑唤醒
- 实际使用中，Codex 待命时的交互

需要两个人、两台电脑、两个不同的网络，例如一方用家里的 Wi-Fi，另一方用手机热点。双方都不开代理，以覆盖国内无代理的情况。如果实在需要代理，记下来。

## 准备

1. 双方都从 [0.6.0rc2 发行页](https://github.com/Weichenleeeee123/crewmesh/releases/tag/v0.6.0rc2) 下载 wheel 和 `SHA256SUMS.txt`。
2. 把下面这句话交给自己的 Claude Code 或 Codex，让 agent 按 `crewmesh-space` Skill 去做：“安装 Crewmesh 0.6.0rc2（校验 SHA256），把 crewmesh-space Skill 装到我的 agent 里。”
3. 用一个不重要的仓库做测试，两边的 agent 都在这个仓库里工作。

## 步骤与记录

| # | 谁 | 操作（对自己的 agent 说） | 记录 |
| --- | --- | --- | --- |
| 1 | 主机 A | “用 Crewmesh 给这个项目创建协作空间，生成一条给队友的中文邀请信息，24 小时有效。” | 创建耗时；把邀请信息整段私聊发给 B |
| 2 | 成员 B | 把 A 发来的邀请信息整段贴给自己的 agent，不加任何说明 | 是否加入成功、耗时；agent 是否自己装好了 Crewmesh |
| 3 | 双方 | “安装 Crewmesh 唤醒。” Codex 用户随后在 `/hooks` 里信任新 hook | 是否装上；Codex 是否需要信任 |
| 4 | 双方 | 运行 `python scripts/two_machine_check.py report --profile <profile> --out start.json` | `runtime.p2p` 是 direct 还是 relay |
| 5 | B | 让自己的 agent 处于空闲状态，什么都不做 | — |
| 6 | A | `python scripts/two_machine_check.py ping --profile <A profile> --to <B member id> --marker ALPHA` | 发送时间 |
| 7 | B | 观察 agent 有没有自己醒来、回复 `Received ALPHA` | 从发送到回复的时间；没醒的话，看 `space_wake status` |
| 8 | 交换 | B 给 A 发 `BRAVO`，重复 6–7 | 同上 |
| 9 | Codex 用户 | 对 agent 说“开启 Crewmesh 待命”，然后对方发 `CHARLIE` | 是否在待命中继续；待命时按 Esc 是否立即中断；待命时直接打字会怎样 |
| 10 | A | 关掉主机 agent 和终端，再重新开一个 agent，让它“启动 Crewmesh 空间” | 重启后 B 是否无需新邀请就能恢复（再 ping 一次） |
| 11 | 双方 | 再跑一次 `report --out end.json` | 把两份报告发回维护者 |

两份报告都不含任何凭据，可以直接分享。报告里的回复正文最多截取 200 字，测试时不要发敏感内容。

## 通过标准

- 第 2 步加入成功，第 4 步报告里能看到直连或中继路径。
- 第 7、8 步双方都能在空闲时被唤醒并回复，并记下从发送到回复的耗时。
- 第 10 步主机重启后，成员不需要新邀请就能恢复。
- 任何一步失败，保留报告和 agent 的原话，不要重试到成功了才记录。
