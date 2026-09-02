# API 契约（v0.1.42）

## 浏览器 API

所有路径由 `auth-service` 提供，除登录、健康检查外都需要 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录，演示账号 `demo/demo123`、`admin/admin123` |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/logout` | 注销 |
| GET | `/api/providers` | Provider 能力与配置状态 |
| POST | `/api/sessions` | 创建数字人会话，body `{provider}` |
| DELETE | `/api/sessions/{id}` | 关闭会话，幂等 |
| POST | `/api/chat` | 同步聊天，body `{sessionId,message}`，返回 `runId` |
| POST | `/api/chat/stream` | SSE 聊天，body `{sessionId,message}` |
| POST | `/api/sessions/{id}/interrupt` | 中断当前运行；可选 body `{runId}`，只中断指定 run |
| GET | `/api/rag/health` | RAG 与 Docling 状态 |
| POST | `/api/rag/ingest` | 文本或 Base64 文档入库 |
| POST | `/api/rag/search` | 用户隔离的语义检索 |
| GET | `/api/observability/traces` | 当前用户 Trace 摘要 |
| GET | `/api/observability/traces/{traceId}` | 当前用户 Trace 回放 |
| GET | `/api/evaluation/overview` | 评测汇总指标 |
| GET | `/api/evaluation/datasets` | 项目自建评测集 |
| POST | `/api/evaluation/runs` | 记录评测样本和分数 |
| GET | `/api/evaluation/runs` | 当前用户评测运行 |

## WebSocket 实时契约

浏览器使用 `WS /api/realtime` 建立实时连接。握手沿用 Sa-Token 登录态（同源浏览器会自动携带认证 Cookie）；浏览器不设置 `X-Internal-Token`、`X-User-Id` 或 `X-User-Name`，这些字段只由认证网关注入到 Agent 内部连接。

连接建立后，客户端必须先发送一帧 JSON `hello`：

```json
{"type":"hello","protocol":"realtime.v1","sessionId":"mock-...","requestId":"hello-1"}
```

服务端返回 `ready`，其中包含 `connectionId`、心跳周期、当前能力和资源上限。之后可发送 `text`、`interrupt`、`audio_start`、`audio_end`、`ping`、`pong` 和 `close` 控制帧；每个事件带递增 `seq`，运行相关事件同时带 `runId`、`utteranceId` 和 `revision`。新一轮改口使用更大的 `revision`，旧代际事件会在服务端和浏览器两侧丢弃。

语音输入使用二进制 PCM16 little-endian 帧：16 kHz、单声道、20 ms，默认每帧 640 bytes。配置 `HTTP_ASR_ENDPOINT` 后，Agent 将有界音频段以 HTTP 请求发送至 ASR，并返回 `transcript.status=final` 和文本；未配置时仍返回 `unsupported`，超时或上游错误返回结构化错误。`interrupt` 先确认本地运行令牌，再异步通知 Provider，随后返回 `ack` 与 `interrupted/run_done`，用于前端立即清空播放队列并切换到最新 revision。

聊天上下文按 `X-Tenant-Id + X-User-Id` 隔离，账号偏好通过 `/api/profile` 读写；成功且无工具调用的答案进入 Redis 滑动 TTL 缓存，响应包含 `cacheHit`。命中会续期，闲置答案由 Redis 自动回收；并发 miss 使用 single-flight，避免重复 LLM 推理。

配置 `HTTP_TTS_ENDPOINT` 后，文本增量会异步转换为 PCM16 二进制帧，通过同一 WebSocket 单写者队列输出；新 revision 或 `interrupt` 会丢弃旧代际音频。未配置 TTS 时能力字段保持 `unsupported`。WebRTC 和厂商视频渲染仍通过 Provider/Runtime 端口接入。

## SSE 事件

当前浏览器 SSE 保持兼容的三段式帧：`id`、`event`、`data`。`data` 至少带 `traceId`、`runId`、`seq` 和 `eventId`；`start`、`filler`、`intent`、`tool_disclosure`、`security`、`rag`、`tool`、`delta`、`provider`、`done`、`interrupted`、`error` 为第一版事件类型。安全门命中时，`security` 事件会给出人类可读原因，并跳过 RAG 与 MCP 工具；性能事件包含人类可读的 `performance`（表情、注视、手势、唇动和可中断标记）。

认证网关在 Agent 尚未写出首帧就发生上游错误或传输中断时，会生成同样带 `id`、`traceId`、`runId`、`seq`、`eventId` 的 `error` 帧；这些标识用于前端去重、恢复和问题定位，不代表 Agent 已成功创建业务 Trace。若上游已经写出部分帧，网关会沿用首个有效的 Trace/Run 标识并递增序号。

同步 `/api/chat` 与 SSE `done` 的 `agentResponse` 是 Agent Core 到展示层的稳定契约，包含 `text`、`emotion`、`gesture`、`performance`、`traceId`、`sessionId`、`runId` 和 `interruptible`。SSE 终态数据还可携带 `firstEventLatencyMs`、`firstVisibleLatencyMs`、`agentLatencyMs`、`digitalHumanLatencyMs` 和 `cancellationLatencyMs`，用于 Trace 回放与评测汇总；其中 `firstVisibleLatencyMs` 表示服务端写出首个可见 SSE 帧前的耗时，不等同于浏览器绘制完成时间；缺少某一阶段数据时保持为空，不伪造延迟。浏览器不依赖厂商 SDK 字段；数字人运行时由 Provider 适配器负责渲染。

`packages/contracts/events.schema.json` 定义跨服务事件总线的 envelope（`schema_version/event_id/run_id/seq/ts/type/data`）；它与浏览器 SSE 的兼容 wire 层分开，后续事件桥接时再统一。

## 内部 API

Agent 接口只接受 `X-Internal-Token`、`X-User-Id`、`X-User-Name`，并拒绝缺少任一身份头的请求。认证网关固定转发到内部 Agent 基础地址，不允许客户端传入目标地址。

MCP 工具结果在 Agent 边界统一约束：`MCP_MAX_RESULT_BYTES` 控制 JSON UTF-8 字节上限，`MCP_MAX_RESULT_ITEMS` 控制每个集合最多保留的项数，`MCP_MAX_RESULT_DEPTH` 控制嵌套容器深度。发生裁剪时，工具调用 metadata 会返回截断标记与大小信息，主响应仍保持原有 `toolCalls` 结构。

RAG 文档在解析前受 `RAG_MAX_DOCUMENT_BYTES` 统一约束，JSON 入库和文件上传共用同一预算；Base64 内容会先按编码长度预检，再执行解码，超限请求不会进入 Docling、切分或向量化阶段。`RAG_MAX_METADATA_BYTES`、`RAG_MAX_METADATA_ITEMS`、`RAG_MAX_METADATA_DEPTH` 分别限制元数据估算 JSON 大小、集合项总数和嵌套层级；文件上传入口会在 `json.loads` 前拒绝超限元数据。

Agent 的 POST/PUT/PATCH 请求体还受 `AGENT_MAX_REQUEST_BODY_BYTES`（默认 16 MiB）ASGI 入口限制；Nginx 使用同等上限，给 8 MiB 文档的 Base64/JSON 编码留出余量。

Provider 能力中的 `interrupt_scope` 取值为 `run`、`session`、`local` 或 `unsupported`。`local` 只保证服务端抑制旧 run 的结果，不代表远端数字人已经停止播报；接入真实 SDK 时只有实现 run 级 abort 或 WebSocket 关闭后才能声明 `run`。

Docling 解析和 FutureAGI 异步导出均有并发上限：`DOCLING_MAX_CONCURRENCY` 控制转换器调用，`OBSERVABILITY_MAX_PENDING_TASKS` 与 `OBSERVABILITY_PENDING_FLUSH_TIMEOUT_SECONDS` 控制遥测导出队列。关闭服务时只等待有限时长，超时任务会取消，已经写入本地缓冲的事件仍可回放。

会话、文档、Trace 和评测运行标识在网关侧先通过路径白名单校验；非法路径或查询字符直接返回参数错误，不会被拼接到上游 URL。

## 错误

```json
{"status":401,"message":"请先登录","traceId":"...","timestamp":"..."}
```

错误响应不包含堆栈、密钥、上游完整响应或数据库连接信息。
认证网关即使收到不匹配的 `Accept` 头，也会返回结构化 JSON 错误；成功的 `/api/chat/stream` 仍只返回 `text/event-stream`。Web 入口通过 Docker DNS 动态解析认证服务，容器滚动重建不会固定旧的上游地址。

## 评测指标

评测运行可提供真实模型 usage，也可由服务按字符估算。指标包括：Token 消耗和可配置价格、任务成功率、工具调用 precision/recall/F1、结果关键词正确率、重复回答 Jaccard 一致性、RAG 证据覆盖、注入拦截且无凭据泄露、Agent/数字人平均延迟及 p50/p95。没有足够标注的维度返回“暂无数据”，不会伪造分数。
