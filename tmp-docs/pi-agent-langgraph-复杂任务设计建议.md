# Pi Agent 思路在 Python LangGraph 中的落地建议

> 目标：在现有 `FastAPI + LangGraph + MCP + RAG + Provider` 底座上，为后续复杂任务、意图识别、分类路由、渐进式工具披露和低延迟运行预留清晰边界。本文件只给出设计建议，不改变当前 v0.1.1 实现。

## 一、可复用的核心思想

参考 pi-agent-core 的职责划分，建议只借鉴运行时思想，不直接移植 TypeScript 实现：

- **运行状态与事件分离**：Agent 状态保存会话消息、当前步骤、工具调用和错误；事件只用于 SSE、审计和可观测性。
- **工具执行前后都有策略钩子**：执行前做权限、风险、租户和参数校验；执行后统一做结果裁剪、脱敏和错误归一化。
- **工具执行支持并行/串行**：纯查询工具可并行；写操作、Provider 控制和具有顺序依赖的工具必须串行。
- **上下文变换独立成接口**：在进入模型或分类器前做历史裁剪、RAG 注入、摘要和敏感信息过滤。
- **渐进式消息队列**：用户打断进入 steering 队列，后续要求进入 follow-up 队列；当前步骤完成后再决定是否继续。
- **遥测是旁路能力**：trace/span 记录不能改变业务结果，导出失败不能阻塞主链路。

## 二、建议的 LangGraph 运行图

当前确定性图可保留作为 `simple` 路由；复杂任务增加一个受限子图，避免把所有逻辑塞进单个节点。

```text
ingress
  -> normalize
  -> classify_intent
  -> route
       ├─ simple      -> retrieve_if_needed -> disclose_tools -> execute_once -> compose
       ├─ complex     -> plan -> [disclose -> execute -> observe] x N -> verify -> compose
       └─ clarify     -> ask_user
  -> provider_output
  -> finish
```

### 状态建议

将 `AgentGraphState` 拆成稳定字段和可扩展字段，避免节点互相写入任意键：

```python
class RunState(TypedDict, total=False):
    run_id: str
    user_id: str
    session_id: str
    message: str
    intent: IntentDecision
    route: Literal["simple", "complex", "clarify"]
    retrieved_context: list[RetrievalHit]
    visible_tools: list[ToolDescriptor]
    plan: list[TaskStep]
    completed_steps: list[StepResult]
    budget: RunBudget
    cancelled: bool
    final_reply: str
```

`RunBudget` 至少包含 `deadline_ms`、`max_steps`、`max_tool_calls`、`max_parallelism` 和 `max_output_chars`。每个循环节点开始前检查预算和取消信号，不能仅依赖模型自行停止。

## 三、意图识别与分类路由

### 1. 接口边界

新增 `IntentClassifier`、`TaskRouter` 两个端口，不让 HTTP、MCP 或 Provider 代码直接判断意图：

```text
IntentClassifier.classify(message, context) -> IntentDecision
TaskRouter.route(decision, session, capabilities) -> RouteDecision
```

`IntentDecision` 包含 `name`、`confidence`、`requires_rag`、`requires_tools`、`risk_level` 和 `reason_code`，不要保存模型的完整思维链。

### 2. 分层策略

1. 先用低成本规则识别控制类请求：停止、重试、关闭会话、查询状态。
2. 再用轻量模型或结构化分类器处理领域意图，输出固定枚举和置信度。
3. 置信度低于阈值时进入 `clarify`，而不是盲目调用工具。
4. 分类器超时或不可用时回退 `simple`，并在 trace 中标记 `classifier_fallback=true`。

### 3. 路由原则

- 只需要短文本回应时跳过 RAG、工具发现和 Provider 控制。
- 需要知识依据时才检索 RAG；检索为空仍可继续，但必须记录降级状态。
- 需要外部动作时进入复杂子图，Provider 仅在最终回复确定后执行。
- 高风险动作必须经过显式确认节点；确认信息不能从 RAG 文档或模型自由文本中推断。

## 四、渐进式工具披露

MCP 工具数量增长后，不应把全部 schema 一次性放入模型上下文。建议分三层：

1. **目录层**：只返回工具名、短描述、领域、风险等级、是否只读。
2. **候选层**：分类器根据意图筛选最多 `N` 个候选工具，并按租户/用户权限过滤。
3. **Schema 层**：只有即将执行的工具才加载完整参数 schema，执行前再次校验。

工具策略由 `ToolPolicy` 统一实现：

```text
candidate_tools(intent, capabilities, user_scope)
authorize(tool, arguments, user_scope)
sanitize_result(tool, result)
```

MCP `list_tools` 结果应做短 TTL 缓存，并按服务器地址、工具目录版本和权限范围分 key。禁止把客户端传入的 MCP URL、任意工具名或未经校验的 schema 直接透传给模型。

## 五、复杂任务与并行策略

- 计划节点只产生结构化 `TaskStep`，每一步必须有目标、依赖、输入和完成条件。
- 无依赖的只读步骤使用受控并行；有副作用或依赖关系的步骤串行。
- 每一步写入 checkpoint，支持断点恢复、用户打断和失败重试。
- 重试使用指数退避和次数上限；不可重试错误直接进入 `verify/compose`，向用户说明降级结果。
- 复杂任务结束前不发送 Provider 播报，避免把中间态误播给用户。

建议将 LangGraph 的条件边集中在 `routing/edges.py`，节点实现只负责一个动作；循环子图通过 `max_steps` 和 deadline 强制收敛。

## 六、低延迟落地顺序

1. HTTP 请求收到后立即发送 SSE `start`，并生成 `run_id`。
2. 会话 touch、意图分类和轻量健康检查并发执行；分类结果未完成时不阻塞连接建立。
3. MCP 客户端复用 HTTP 连接和 MCP session，缓存工具目录；当前“每次调用新建 ClientSession”适合探针，不适合生产高频调用。
4. RAG 检索、工具执行设置独立超时，使用有界并发，不在事件循环中执行阻塞解析。
5. 回复生成采用增量事件；首个可展示片段到达后立即推送，遥测异步入队。
6. 远程 MCP 失败使用短暂熔断和明确的本地 fallback 标记，避免每个请求都等待完整连接超时。

性能指标建议记录：分类耗时、RAG 耗时、工具发现耗时、工具排队耗时、工具执行 p50/p95、首字节延迟、首个文本片段延迟、取消成功率和 fallback 比例。

## 七、与现有模块的映射

| 建议模块 | 现有落点 | 后续动作 |
|---|---|---|
| 运行状态 | `app/graph/state.py` | 引入 `RunBudget`、`IntentDecision`、`TaskStep` 类型 |
| 分类路由 | `app/graph/` | 新建 `routing/`，不改 Provider/MCP 端口 |
| 工具策略 | `app/mcp/client.py` | 增加目录缓存、候选筛选和授权策略 |
| 上下文变换 | `app/rag/` + graph | 将 RAG 注入做成可插拔 `ContextTransformer` |
| 事件/遥测 | `app/observability/` | 为每个 run/step/tool 统一 `run_id` 和 `step_id` |
| 会话恢复 | `app/infrastructure/` | 将内存 store 替换为可插拔 checkpoint/session backend |
| Provider 输出 | `app/avatar/` | 只消费最终 `ProviderCommand`，不参与任务规划 |

## 八、分阶段验收建议

### v0.2：分类与工具策略

- 规则分类、置信度阈值和 `simple/complex/clarify` 路由可测试。
- MCP 目录缓存、候选工具上限、权限过滤和执行前校验有单元测试。
- SSE 能看到 `classify`、`route`、`tool_discovery` 事件。

### v0.3：复杂任务子图

- 具备结构化计划、有限循环、checkpoint、取消、重试和确认节点。
- 并行只读工具与串行副作用工具均有测试，超过预算时能稳定收敛。

### v0.4：生产低延迟

- MCP 连接池/会话复用、RAG 异步解析队列、FutureAGI 指标和 p95 告警可用。
- 任何遥测或可选 Provider 故障都不阻断文本回复和会话关闭。
