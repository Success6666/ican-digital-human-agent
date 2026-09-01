# Digital Human Agent v0.1.34 Redis、真实 ASR 与音频输出任务书

## 状态

已完成（2026-09-01）

## 原始问题

当前 Agent 会话状态主要保存在单进程内存，多个 Agent 副本之间无法共享会话、运行代际和清理队列。实时语音链路只校验 PCM16 帧并返回 `asr_unconfigured`，没有可配置的服务端 ASR 输入适配；文本结果也没有统一的音频输出通道，无法验证真实语音闭环。已有 RabbitMQ 仅覆盖基础事件投递，缺少发布背压、确认、重试和幂等边界；账号上下文也没有形成租户、偏好和答案复用的隔离键。

## 目标

1. 提供 Redis 共享 SessionStore，支持多副本下的会话租约、运行代际、中断和 cleanup outbox。
2. 提供可配置的 HTTP ASR 适配，保持 PCM16 输入、超时、大小上限和明确的降级状态。
3. 提供可配置的 HTTP TTS 音频输出适配，支持流式音频帧、代际过滤、背压和中断清理。
4. 保持 Mock/内存模式可用，未配置真实端点时服务仍可启动。
5. 记录首帧、ASR、TTS、队列深度和中断延迟，避免无界缓存和阻塞主事件循环。
6. 以租户为第一隔离边界、账号为个性化绑定边界，保存沟通风格、语言、声音和约束偏好。
7. 对成功且无私有上下文的回答建立 Redis 多级缓存，并用分布式 single-flight 避免同一问题并发击穿 LLM。
8. 让 RabbitMQ 使用发布确认、有限并发、幂等消息键、重试和死信，形成可扩展的异步处理边界；以 10,000 连接级并发为容量目标，用基准记录实际 p95 和资源占用。

## 实施方案

1. 引入 `redis.asyncio` 可选依赖、`SESSION_STORE_BACKEND`、`REDIS_URL`、键前缀和 Redis 操作超时配置。
2. 实现按会话键/用户索引分片的 Redis SessionStore，使用短时分布式锁和原子 Lua/事务更新保护会话代际与清理队列；所有读取和列表接口按租户、用户隔离。
3. 把过期快照和 teardown 失败记录写入 Redis 有界列表；Redis 不可用时按配置降级到本地 outbox，并输出可观测告警。
4. 增加 `HTTP_ASR_ENDPOINT` 与 `HTTP_TTS_ENDPOINT` 适配器，使用复用连接池、连接/读取超时和响应体上限，不记录原始音频或凭证。
5. ASR 完成后返回 `transcript`；TTS 按 PCM16 或厂商返回格式转发二进制帧，并沿用 `runId + utteranceId + revision` 过滤旧输出。
6. 通过单元、协议、性能和 Compose 测试验证冷启动、重启恢复、并发竞争、超时、背压和降级行为。
7. 增加租户上下文、账号偏好 API 和版本化缓存键；缓存键不得包含跨租户可复用的私有数据，缓存命中不写入原始音频或凭证。
8. 为 RabbitMQ 增加 publisher confirm、prefetch/并发上限、重试/死信和幂等键；为 HTTP 入口增加有界 in-flight gate，执行 10,000 连接级合成基准并记录 p50/p95、错误率、Redis 命中率和 LLM 调用次数。

## 验收标准

1. 两个独立 Store 实例连接同一 Redis 时，可以读取、更新并隔离同一租户内的用户会话；不同租户同名用户的键空间互不相交。
2. 同一会话的并发创建、begin_run、interrupt、close 只保留一个有效代际，旧代际不能覆盖新状态。
3. Redis cleanup 队列有界、去重、可重启恢复；Redis 暂时不可用时服务保持可用并有明确指标。
4. 配置 ASR endpoint 后，真实 PCM16 请求返回转写文本；超时、非 2xx、超限响应返回结构化错误且不阻塞连接。
5. 配置 TTS endpoint 后，文本结果能输出音频帧；中断或新 revision 会停止旧音频，队列深度保持在上限内。
6. 未配置真实端点时，健康检查和 Mock 测试仍通过，能力字段准确显示 `unsupported`。
7. Agent、MCP、认证网关、Web 全量测试通过；Compose 启动 Redis/RabbitMQ 后所有服务 healthy。
8. 相同租户的重复问题可直接命中 Redis，跨租户不命中；并发重复请求只产生一次 LLM 推理，缓存失效后可恢复推理。
9. 账号偏好读写持久化且只对所属租户/账号生效；流式和实时音频链路沿用同一上下文。
10. 任务书完成后重命名为 `...-已完成.md`，并生成基线副本、修改副本、差异文件、验证记录和可执行回滚脚本。

## 回滚方案

将 `SESSION_STORE_BACKEND` 恢复为 `memory`，移除 ASR/TTS endpoint 配置并恢复 v0.1.33 依赖和入口；回滚脚本只操作验证副本，不覆盖当前工作树源码。

## 验收结果

- Agent 全量测试：188 passed，2 skipped。
- Auth Maven 测试：退出码 0。
- Redis 双实例 smoke：共享运行代际和中断状态通过。
- 10,000 连接级健康基准：10,000 成功、0 错误，p50 2374.34 ms，p95 5558.50 ms。
- Compose：Agent、MCP、认证网关、Web、Redis、RabbitMQ 全部 healthy。
- 验收 artifacts：`tmp-docs/v0.1.34-artifacts/VERIFICATION.txt`、`DIFF_FILE.diff`、`ROLLBACK.sh` 和基线/修改/回滚副本。
