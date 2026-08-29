# API 契约（v0.1.1）

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

## SSE 事件

当前浏览器 SSE 保持兼容的三段式帧：`id`、`event`、`data`。`data` 至少带 `traceId`、`runId`、`seq` 和 `eventId`；`start`、`filler`、`intent`、`tool_disclosure`、`security`、`rag`、`tool`、`delta`、`provider`、`done`、`interrupted`、`error` 为第一版事件类型。安全门命中时，`security` 事件会给出人类可读原因，并跳过 RAG 与 MCP 工具；性能事件包含人类可读的 `performance`（表情、注视、手势、唇动和可中断标记）。

同步 `/api/chat` 与 SSE `done` 的 `agentResponse` 是 Agent Core 到展示层的稳定契约，包含 `text`、`emotion`、`gesture`、`performance`、`traceId`、`sessionId`、`runId` 和 `interruptible`。浏览器不依赖厂商 SDK 字段；数字人运行时由 Provider 适配器负责渲染。

`packages/contracts/events.schema.json` 定义跨服务事件总线的 envelope（`schema_version/event_id/run_id/seq/ts/type/data`）；它与浏览器 SSE 的兼容 wire 层分开，后续事件桥接时再统一。

## 内部 API

Agent 接口只接受 `X-Internal-Token`、`X-User-Id`、`X-User-Name`，并拒绝缺少任一身份头的请求。认证网关固定转发到内部 Agent 基础地址，不允许客户端传入目标地址。

MCP 工具结果在 Agent 边界统一约束：`MCP_MAX_RESULT_BYTES` 控制 JSON UTF-8 字节上限，`MCP_MAX_RESULT_ITEMS` 控制每个集合最多保留的项数，`MCP_MAX_RESULT_DEPTH` 控制嵌套容器深度。发生裁剪时，工具调用 metadata 会返回截断标记与大小信息，主响应仍保持原有 `toolCalls` 结构。

RAG 文档在解析前受 `RAG_MAX_DOCUMENT_BYTES` 统一约束，JSON 入库和文件上传共用同一预算；Base64 内容会先按编码长度预检，再执行解码，超限请求不会进入 Docling、切分或向量化阶段。`RAG_MAX_METADATA_BYTES`、`RAG_MAX_METADATA_ITEMS`、`RAG_MAX_METADATA_DEPTH` 分别限制元数据估算 JSON 大小、集合项总数和嵌套层级；文件上传入口会在 `json.loads` 前拒绝超限元数据。

Agent 的 POST/PUT/PATCH 请求体还受 `AGENT_MAX_REQUEST_BODY_BYTES`（默认 16 MiB）ASGI 入口限制；Nginx 使用同等上限，给 8 MiB 文档的 Base64/JSON 编码留出余量。

会话、文档、Trace 和评测运行标识在网关侧先通过路径白名单校验；非法路径或查询字符直接返回参数错误，不会被拼接到上游 URL。

## 错误

```json
{"status":401,"message":"请先登录","traceId":"...","timestamp":"..."}
```

错误响应不包含堆栈、密钥、上游完整响应或数据库连接信息。

## 评测指标

评测运行可提供真实模型 usage，也可由服务按字符估算。指标包括：Token 消耗和可配置价格、任务成功率、工具调用 precision/recall/F1、结果关键词正确率、重复回答 Jaccard 一致性、RAG 证据覆盖、注入拦截且无凭据泄露、Agent/数字人平均延迟及 p50/p95。没有足够标注的维度返回“暂无数据”，不会伪造分数。
