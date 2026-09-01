# 运行手册

## 无 Docker 的开发方式

1. 启动 MCP：在 `apps/mcp-server` 目录执行 `$env:PYTHONPATH=(Get-Location).Path; python -m uvicorn app.main:app --host 127.0.0.1 --port 9000`。
2. 启动 Agent：在 `apps/agent-service` 目录执行 `$env:PYTHONPATH=(Get-Location).Path; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。
3. 启动认证服务：使用 Maven Wrapper 或容器构建后执行 JAR。
4. 启动前端：在 `apps/web` 执行 `npm install && npm run dev`。

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build
```

浏览器访问 `http://localhost:8088`。演示账号：`demo/demo123`。

生产环境将 `ENVIRONMENT` 设置为 `production`，并为 Agent、MCP 和认证网关提供至少 32
字符的随机内部令牌；公开占位值会被启动校验拒绝。HTTPS 部署时将
`AUTH_COOKIE_SECURE=true`，认证 Cookie 默认使用 `HttpOnly` 和 `SameSite=Lax`。

首页建立数字人会话后会自动挂载文本实时通道。浏览器使用同源登录 Cookie 访问 `/api/realtime`；麦克风按钮只在当前 Provider 声明语音输入能力且浏览器支持采集时启用。改口或停止表达会先清空本地播放队列，再发送当前运行的中断请求。

默认 Mock Provider 只验证实时连接、PCM16 帧边界、心跳和中断生命周期。配置 `SESSION_STORE_BACKEND=redis` 后会话与 cleanup 队列进入 Redis；配置 `HTTP_ASR_ENDPOINT`、`HTTP_TTS_ENDPOINT` 后启用真实媒体适配，适配器使用复用连接、超时和响应体上限，故障时保留协议连接并报告降级状态。

### 会话资源参数

- `SESSION_MAX_SESSIONS`：单个 Agent 进程可跟踪的会话上限，默认 `1024`。
- `SESSION_CLEANUP_BATCH_SIZE`：每轮后台清理最多处理的记录数，默认 `100`。
- `SESSION_IDLE_TIMEOUT_SECONDS`：无活动会话租约时长，默认 `1800` 秒。
- `SESSION_HEARTBEAT_INTERVAL_SECONDS`：客户端建议心跳周期，默认 `15` 秒；心跳会校验运行代号并续租。
- `REALTIME_HANDSHAKE_TIMEOUT_SECONDS`：实时 WebSocket 握手超时，默认 `5` 秒。
- `REALTIME_IDLE_TIMEOUT_SECONDS`：实时连接断线探测窗口，默认 `45` 秒；用于回收无响应的 WebSocket，不延长会话租约。
- `REALTIME_INTERRUPT_TIMEOUT_SECONDS`：实时中断确认的服务端等待上限，默认 `0.25` 秒。
- `SESSION_IDLE_TIMEOUT_SECONDS` 必须满足 `SESSION_HEARTBEAT_INTERVAL_SECONDS < REALTIME_IDLE_TIMEOUT_SECONDS <= SESSION_IDLE_TIMEOUT_SECONDS`，否则服务不会启动。

默认会话状态使用进程内 Store；多进程或多副本部署将 `SESSION_STORE_BACKEND` 设置为 `redis`，并配置 `REDIS_URL`、`REDIS_KEY_PREFIX` 和操作超时。过期 Provider 快照在 Redis 中进入有界 cleanup 队列；Redis 暂时不可用时保留本地内存语义并记录降级。答案缓存采用滑动 TTL、大小/条目上限和 single-flight；租户键空间、账号偏好和 RabbitMQ 消息幂等键由 Agent 侧维护。`HTTP_ASR_ENDPOINT` 和 `HTTP_TTS_ENDPOINT` 只接受服务端配置，原始音频与凭证不写入日志或会话状态。

容量基线：`AGENT_MAX_IN_FLIGHT_REQUESTS=4096`、`RABBITMQ_MAX_IN_FLIGHT=512`、`RABBITMQ_PREFETCH_COUNT=256`。使用 `tmp-docs/v0.1.34-concurrency-benchmark.py` 对健康入口执行连接级压测，记录 p50/p95、错误率和 wall time；10,000 是连接级容量目标，LLM 并发仍由供应商配额和 `max_in_flight` 共同约束。
远端 Provider 清理失败时，当前版本只记录并继续处理其他会话；生产部署需在共享存储版本增加带退避的关闭重试或 outbox，避免进程重启后丢失待清理状态。

## 健康检查

- `GET /api/health`：认证网关。
- `GET /health`：Agent 和 MCP（仅内部网络）。

## 评测与回放

登录后打开“评测中心”，可查看当前用户的质量、安全、成本和 Agent/数字人分段延迟。数据集按分类筛选，运行列表可查看某轮完整原始归档。通过 `POST /api/evaluation/runs` 提交离线样本；Trace 回放只显示本用户事件，字段已做脱敏。原始评测数据追加写入 `EVALUATION_RAW_ARCHIVE_PATH`，服务重启后仍可查询。

## FutureAGI 可观测性

在服务端环境注入 `FUTUREAGI_ENABLED=true`、`FUTUREAGI_API_KEY`、
`FUTUREAGI_SECRET_KEY` 和 `FUTUREAGI_PROJECT` 后重启 Agent。需要自定义采集地址时
设置 `FUTUREAGI_ENDPOINT`。适配器使用 `fi-instrumentation-otel` 返回的专用
TracerProvider，不修改进程全局 Provider；缺少任一凭证、依赖不可用或导出失败时，
健康状态显示“本地缓冲”，事件继续保存在有界内存中。

RAG 文档与向量默认写入 Agent 容器的 `/app/data/rag.sqlite3`，该路径由 `agent-runtime-config` 数据卷持久化。迁移或备份时需要同时保留该数据卷。

## 真实 Provider 开启顺序

1. 在服务端注入密钥并确认日志脱敏。
2. 先只启用一个 Provider，完成创建、首帧/文本、打断、关闭冒烟。
3. 确认 HTTPS/WSS、CSP、反向代理 Upgrade 和会话 TTL 后再扩大并发。
