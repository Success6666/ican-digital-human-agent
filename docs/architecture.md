# 架构说明

## 运行边界

浏览器只访问 `web`，由 Nginx 将 `/api/*` 转给 `auth-service`。认证网关校验 Sa-Token 后，使用内部令牌和用户上下文调用 `agent-service`。Agent 再调用 MCP 和数字人 Provider。`agent-service`、`mcp-server` 没有宿主机端口映射，不能被浏览器绕过认证直接访问。

## 模块职责

### web

- `features/auth`：登录态和用户信息。
- `features/chat`：消息输入、SSE 解析、运行事件时间线。
- `features/avatar`：Provider 能力、会话状态和 SDK 适配器入口。
- `shared`：HTTP 客户端、类型、通用视图组件。

### auth-service

- `auth`：演示用户、密码校验、Sa-Token 登录/注销。
- `gateway`：固定目标的 Agent 代理，不接受用户提供的 URL。
- `config`：环境变量绑定、CORS、生命周期配置。
- `common`：统一错误模型和异常映射。

### agent-service

- `api`：内部 HTTP 契约和 SSE 编码。
- `application`：聊天、会话、文档摄取用例。
- `graph`：LangGraph 状态、运行器和安全门节点。
- `agent`：提示词注入安全门、意图识别、工具分类路由、渐进式披露、filler 和微表情语义指令。
- `avatar`：Provider 端口、注册表和厂商适配器。
- `mcp`：MCP 连接生命周期、工具目录、调用超时和结果资源边界。
- `rag`：Docling 解析器、块切分、向量存储端口和检索。
- `observability`：trace/span 端口、FutureAGI 适配器、本地降级记录器。
- `evaluation`：项目自建数据集、确定性评分器、运行记录和汇总指标。
- `realtime`：认证 WebSocket 连接、控制/PCM16 帧协议、运行代际、改口中断、背压和心跳租约。
- `infrastructure`：配置、内存存储、后台清理任务。

## 可扩展点

1. 增加 Provider：实现 `AvatarProvider`，在注册表注册，无需修改图节点。
2. 替换模型：只替换 Graph 的 responder 节点，状态和事件契约保持不变。
3. 替换向量库：实现 `VectorStore`，不改 Docling 解析和检索用例。
4. 替换观测后端：实现 `TelemetrySink`，FutureAGI 不可用时自动回退本地 JSON。
5. 持久化：将内存会话/索引替换为 Redis/Postgres，保留现有端口。
6. 评测裁判：保留 `EvaluationRunRequest` 和 `MetricScore`，可接入离线模型裁判、人工标注或批处理队列。

## 性能与生命周期

- Provider 会话、MCP 连接和 HTTP 客户端均有超时与关闭路径。
- 会话采用有界内存存储：`SESSION_MAX_SESSIONS` 限制进程内状态规模，`SESSION_CLEANUP_BATCH_SIZE` 限制单轮回收量，避免清理任务阻塞事件循环。
- 会话同时维护空闲租约和运行代号；心跳只为当前运行续租，陈旧运行的续租请求会被拒绝。关闭状态可优先回收，过期状态由清理用例先处理远端 Provider 后释放。
- `SessionStore` 端口提供批量清理、心跳、运行代号和资源统计接口。当前计数器是进程内观测，后续接 Redis 时沿用同一端口并改用原子条件更新。
- 关闭操作幂等，避免云端并发泄漏。
- 关闭会话时先发布当前 `runId` 的停止令牌，再执行远端 Provider teardown；慢关闭期间旧图运行立即失效，避免迟到输出写回。关闭与新建请求的两阶段 `closing` 状态和分布式幂等锁留给持久化会话版本。
- SSE 使用小块增量事件，客户端支持取消；日志不记录密钥和完整用户输入。每个请求都有独立 `runId`，同一会话的新 run 会原子地使旧 run 失效。
- 会话存储为每个 run 提供停止通知；Provider 展示任务与停止通知并行等待，改口或断开连接时会取消在途 I/O，并在 Provider 返回后再次校验令牌，禁止旧结果迟到写回。
- 中断接口可携带 `runId`，迟到的旧中断只会被视为幂等空操作，不会误伤新 run；Provider 适配器应将该令牌映射为厂商侧幂等取消键。
- 首响先发送 `start`/`filler`，意图和工具目录随后分层披露；每个图节点、工具和 Provider 阶段都检查运行令牌，支持中断后续跑。
- 安全门在分类器、RAG 和工具之前执行；命中明显的指令覆盖、凭据索取或越权模式时固定拒答，并在 Trace 中记录原因码，不把原始输入写入遥测。
- Agent 与数字人 Provider 延迟分别记录；Provider 性能指令采用 `PerformanceCue`，由各厂商适配器映射到微表情、注视和唇动。
- 实时 WebSocket 采用单写者和有界队列；`runId + utteranceId + revision` 是输出过滤的共同代际键，改口先停止本地播放，再取消旧图运行。
- 音频入口只接受完整 PCM16 帧，连接心跳同时续订会话租约；租约失效或连接空闲超时会主动关闭，避免后台任务和会话引用长期滞留。
- 工具目录按 TTL 缓存，单工具调用限制超时、输出大小和重试次数。结果在客户端边界按 UTF-8 字节数、集合项数和嵌套深度裁剪，并通过 metadata 给出截断原因；图节点无需感知具体限制实现。
- Agent 请求体在 ASGI 接收边界设有统一硬上限；RAG 再按文档字节预算和元数据预算做业务级预检，避免异常大包进入 JSON 解码、Docling 或向量化。
- RAG 入库在服务边界先校验文档字节预算和元数据资源上限；Base64 先做编码长度预检，文本按分块 UTF-8 编码，避免超大请求在解码或编码阶段产生峰值分配。
