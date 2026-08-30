# ican 数字人 Agent v0.1.2 优化任务书

## 1. 基本信息

- 项目：ican 通用 Agentic Digital Human 底座
- 版本：v0.1.2
- 日期：2026-08-30
- 状态：已完成

## 2. 优化目标

在不改变浏览器 API 和 `AgentResponse` 基础契约的前提下，继续降低实时对话的首响、改口和取消延迟，消除会话关闭并发竞态，控制长运行服务的任务、缓存、Trace 和评测内存占用，并让实时指标可以定位到 Agent、网络流和数字人 Provider 的具体阶段。

## 3. 实施范围

1. 会话生命周期：增加关闭中的明确状态或等价原子占位，禁止关闭窗口创建新 run；关闭、过期、断开连接均释放停止通知和后台任务。
2. 流式运行时：保持首帧快速确认，增加可验证的背压、断开清理、事件去重/顺序保护和取消原因；不得让迟到 Provider 结果污染新 run。
3. Agent 图性能：保留分类、RAG、MCP、Provider 的可取消 I/O；减少重复状态读取和无界任务，确保并发工具调用有上限和超时。
4. 前端体验：改口无需等待旧响应自然结束；按 `runId/seq/eventId` 隔离事件，显示人类可读的阶段状态，并在组件卸载、会话切换时完成清理。
5. 可观测性与评测：区分服务端首事件、服务端首个可见事件、Agent 延迟、数字人延迟和取消延迟；Trace 回放与评测记录保持用户隔离和有界存储。
6. RAG/Docling：保持 CPU-only 默认策略，确认模型按需加载、文档预算和异常降级不会阻塞聊天主链路。

## 4. 非目标

- 不在本版硬编码天气、客服、教育等垂直业务语义。
- 不在无凭证环境伪造阿里云、魔珐星云、讯飞或 Fay 的真实媒体链路。
- 不引入无明确收益的多 Agent 编排或大规模基础设施迁移。

## 5. 验收标准

### 5.1 实时交互

- [x] 首个 `start/filler` 事件先于慢分类器返回，并已接入延迟采集；累计样本达到统计门槛后计算 p50/p95。
- [x] 同一会话连续改口时，旧 run 的 delta、tool、RAG、provider 和 error 事件均不能修改新 run。
- [x] 中断/断开后，所有可取消操作在配置的宽限时间内结束；非协作任务不会产生未处理异常或无界引用。
- [x] 关闭与新建并发请求不会让新 run 被已发起的关闭操作误关闭。
- [x] SSE 事件顺序、去重和终态可验证；客户端网络抖动不会重复渲染消息。

### 5.2 资源与安全

- [x] 会话、停止通知、Trace、评测记录和任务集合均有上限、TTL 或显式清理路径。
- [x] Provider、MCP、RAG 超时和取消均不泄露密钥、堆栈或原始敏感输入。
- [x] Agent 仍只能经认证网关访问，Compose 不新增对外暴露端口。

### 5.3 可观测性与评测

- [x] Trace 回放可区分首事件、服务端首个可见事件、Agent、数字人和取消延迟。
- [x] 评测汇总对取消、错误、降级和注入拦截有明确状态，不把异常 run 计为成功。
- [x] 前端只展示人类可读阶段信息，不展示内部标识、原始 SDK 字段或密钥。

### 5.4 工程交付

- [x] Agent、MCP、Auth、Web 测试与 Docker Compose 健康检查通过。
- [x] 增加实时并发/背压/生命周期回归测试和至少一条可重复的端到端改口冒烟。
- [x] 源码按功能模块组织，新增业务源文件原则上不超过 300 行。
- [x] 完成后将本文件重命名为 `digital-human-agent-v0.1.2-optimization-task-book-已完成.md`，并提交 v0.1.2。

## 6. 验收证据

### 6.1 自动化验证

- `apps/agent-service`：`python -m pytest -q`，107 passed、1 skipped；覆盖关闭/中断并发竞态、Provider 代际切换、SSE 异常中断语义及无扩展名文本入库。
- `apps/agent-service`：`python -m ruff check apps/agent-service` 与 `python -m compileall -q apps/agent-service/app apps/agent-service/tests` 通过。
- `apps/mcp-server`：测试 2 passed。
- `apps/auth-service`：`mvnw.cmd -q test` 通过（16 tests，0 failures）。
- `apps/web`：`npm run build` 通过；Vite 产物生成成功。
- `docker compose config --quiet` 通过；四个服务均报告 healthy。

### 6.2 网关端到端冒烟

- 仅经 Web 网关登录并创建会话后，普通 SSE 事件顺序为 `start → filler → intent → tool_disclosure → security → rag → tool → delta → provider → done`。
- Trace 回放返回单一连续 Trace，回放事件的 `trace_id` 与 SSE Trace 一致；首事件、首个可见事件、Agent、数字人延迟均可读，状态为 `ok`。
- 快速改口冒烟确认旧 run 被中断、新 run 获得独立 `runId` 并返回“昨天”语义；本次中断请求往返约 12.15 ms。
- RAG/Docling 入库、检索和删除闭环通过；无扩展名文本按 `text/plain` 正常入库；评测汇总正确区分 success 与 interrupted；未认证的 `/api/providers` 返回 401。
- Provider 能力接口返回 `interrupt_scope=run`（Mock）及 `interrupt_scope=local`（未实现远端 abort 的适配器），前端转换为可读标签。
- 网关在 Agent 握手/传输失败时生成带 `id`、`traceId`、`runId`、`seq`、`eventId` 的可关联错误帧，并对上游 CRLF、异常标识和未闭合大帧做边界保护。
- 认证网关错误统一返回 JSON；Web Nginx 使用 Docker DNS 动态解析认证服务，强制重建 `auth-service` 后仍可恢复登录与 SSE。
- 最后一轮有效请求后的 3 分钟 Agent/Auth/MCP/Web 日志无 `ERROR`、`Traceback`、未处理异常或 5xx；本次冒烟首事件约 0.06 ms，p50/p95 由评测样本累计计算。

### 6.3 已知边界

- 真实阿里云、魔珐星云、讯飞和 Fay 媒体链路尚未使用生产凭证冒烟；当前验收覆盖 mock 与网关链路。
- `firstVisibleLatencyMs` 是服务端首个可见 SSE 帧时间，不代表浏览器实际绘制时间；后续可增加前端绘制标记形成完整端到端指标。
- 跨进程部署仍需 Redis 等共享存储承载 run ownership；同 ID 的过期清理租约也应在多副本版本补齐。

## 7. 风险记录

- 真实厂商 SDK 的取消语义仍需在其协议支持 `runId` 或幂等取消键后才能完全闭环。
- 非协作 Provider 超过取消宽限时间后只能隔离本地结果，无法保证远端播报立即停止；生产适配器必须实现 run 级 abort 或 WebSocket 关闭。
- 跨进程/多副本部署需要 Redis 或其他共享状态实现原子 run ownership，本版先保证单进程内存实现正确且可替换。
