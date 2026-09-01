# Digital Human Agent v0.1.33 会话清理 Outbox 持久化任务书

## 状态

已完成（2026-09-01）

## 原始问题

过期会话和 Provider teardown 失败快照目前只保存在进程内队列。Agent 进程重启后，待清理的远端数字人运行时没有可恢复记录，可能造成 Provider 资源泄漏。

## 实施方案

1. 为 `InMemorySessionStore` 增加可选的 JSONL cleanup outbox 路径。
2. 在过期快照入队、失败重入队、队列领取和同代际替换时原子刷新 outbox 文件。
3. 进程启动时加载并去重有界快照，损坏行跳过并保留其他可恢复记录。
4. 将 `SESSION_CLEANUP_OUTBOX_PATH` 接入 Settings、Compose 和运行配置，默认使用 Agent 数据卷。
5. 增加重启恢复、失败重入队、去重和损坏记录容错测试。
6. 更新运行手册，明确 outbox 只保存待清理快照，不保存用户输入或凭证。

## 验收标准

1. 过期会话进入 cleanup outbox 后，创建新的 Store 实例可以恢复该快照。
2. Provider teardown 失败重新入队后，重启仍可继续处理，且同一 generation 不重复。
3. outbox 文件有界、JSONL 可读，损坏行不会阻塞其他记录恢复。
4. 默认 Compose Agent 数据卷包含 cleanup outbox 配置，服务启动和健康检查正常。
5. Agent、MCP、认证网关、Web 全量测试和构建通过。
6. 验证记录、基线副本、差异文件和可执行回滚脚本齐全，任务书完成后重命名为已完成。

## 回滚方案

删除 outbox 配置并恢复 `InMemorySessionStore` 原始构造路径即可回到 v0.1.32；验证副本回滚脚本见 `tmp-docs/v0.1.33-artifacts/ROLLBACK.sh`。
