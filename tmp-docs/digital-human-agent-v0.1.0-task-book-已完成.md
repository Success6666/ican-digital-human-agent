# 数字人 Agent 第一版任务书

## 1. 基本信息

- 项目：数字人 Agent 底层链路
- 版本：v0.1.0
- 日期：2026-08-29
- 状态：已完成（本地链路验收通过；真实云 Provider 需凭证后再做冒烟）
- 目标：先建立可运行、可替换、可验收的底层链路，不实现具体数字人的人格、业务知识和业务工具。

## 2. 本版范围

### 2.1 必须完成

1. 浏览器到服务端的完整链路：React/TypeScript 前端 -> Spring Boot 认证网关 -> FastAPI Agent。
2. Spring Boot 接入 Sa-Token，实现登录、登出、当前用户查询和登录态校验。
3. FastAPI 接入 LangGraph，提供确定性的 Agent 状态图、会话管理、同步响应和 SSE 流式响应。
4. 工具调用统一通过 MCP；第一版提供 `system_status`、`echo` 两个基础工具作为链路探针。
5. 建立统一数字人 Provider 协议，并提供：
   - `mock`：默认可运行，完成端到端验收。
   - `aliyun`：阿里云适配器骨架，服务端会话初始化和密钥配置入口。
   - `mofa`：魔珐星云适配器骨架，服务端会话初始化和长连接代理入口。
   - `iflytek`：讯飞适配器骨架，文本驱动/中断/关闭入口。
   - `fay`：Fay 外部运行时适配器，默认不拉起本地 Fay 进程。
6. 建立独立 RAG 基础模块：使用 Docling 解析 PDF/DOCX/HTML/Markdown，规范化为文档块，写入可替换的向量存储端口；第一版提供内存存储和检索接口，不绑定具体向量数据库。
7. 接入 FutureAGI 可观测性适配层：统一记录 trace、span、LangGraph 节点、MCP 调用、RAG 检索、Provider 事件；无凭证时使用本地 JSON 日志，不阻断主链路。
8. 会话生命周期：创建、发送文本、打断、关闭、过期清理；会话与用户绑定。
9. 本地编排：Docker Compose 只发布前端入口，认证网关、Agent、MCP 在内部网络通信。
10. 安全基线：前端不持有 AK/SK/AppSecret；Agent 只接受认证网关注入的内部令牌和用户上下文；输入长度限制、CORS 白名单、敏感日志脱敏。
11. 文档、接口契约、健康检查、单元测试和最小链路测试。
12. Agent 复杂任务基础策略：意图识别、按类别路由、工具渐进式披露、并发独立工具、运行令牌中断和后续恢复。
13. 数字人体验基础策略：首响 filler、性能/微表情语义指令，以及 Agent 与数字人 Provider 分段延迟。
14. 评测中心基础设施：项目自建数据集、可解释评分器、token/价格、成功率、工具准确率、正确性/一致性、事实有据性、注入防护和延迟 p50/p95。

RAG 解析还统一受 `RAG_MAX_DOCUMENT_BYTES` 约束；`DOCLING_ENABLED`、OCR、表格结构和本地权重目录均由服务端配置控制，超限文档不会进入解析和向量化。
Agent HTTP 请求体还受 `AGENT_MAX_REQUEST_BODY_BYTES` 统一硬上限保护，避免 Base64/JSON 输入在 FastAPI 解析前造成异常内存峰值。

### 2.2 明确不做

- 不实现具体行业场景、人格设定、长期记忆和业务知识库。
- 不实现真实业务工具；不把工具逻辑塞进前端。
- 不在本机部署云厂商数字人 SDK 的运行时；真实 SDK 通过服务端签发短期会话参数或外部网关接入。
- 不把 Fay 内置 Agent 与 LangGraph 叠加编排；Fay 仅作为可替换的驱动层。
- 不在没有云账号/凭证时伪造真实厂商调用结果；默认使用 mock 并显式标注 provider 状态。

## 3. 目标架构

```text
Browser
  |
  v
React + TypeScript (Vite)
  |  /api/*, satoken header
  v
Spring Boot 3 + Sa-Token (auth-service)
  |  X-Internal-Token + X-User-Id + X-User-Name
  v
FastAPI + LangGraph (agent-service)
  |                         \
  |                          \ provider adapter
  v                           \
MCP Server (mcp-server)       Alibaba / Mofa / iFlytek / Fay / Mock
```

### 3.1 服务边界

| 服务 | 默认端口 | 责任 | 对外暴露 |
| --- | ---: | --- | --- |
| web | 5173/80 | 登录页、会话页、状态展示 | 是（唯一入口） |
| auth-service | 8080 | 登录、Sa-Token、反向代理、用户上下文 | 仅 Compose 内部 |
| agent-service | 8000 | LangGraph、会话、Provider 编排、SSE | 否 |
| mcp-server | 9000 | MCP 工具注册和执行 | 否 |

## 4. 接口契约

### 4.1 浏览器入口（认证网关）

- `POST /api/auth/login`：`{username,password}` -> `{token, user}`
- `POST /api/auth/logout`：注销当前 token
- `GET /api/auth/me`：返回当前用户
- `GET /api/providers`：返回 Provider 能力和可用状态
- `POST /api/sessions`：`{provider}` -> `{sessionId, provider, capabilities, expiresAt}`
- `DELETE /api/sessions/{sessionId}`：幂等关闭会话
- `POST /api/chat`：`{sessionId,message}` -> `{reply, traceId, toolCalls}`
- `POST /api/chat/stream`：同上，返回 `text/event-stream`

### 4.2 Agent 内部接口

所有请求必须带：

- `X-Internal-Token`
- `X-User-Id`
- `X-User-Name`

内部接口与浏览器入口一一对应，不允许浏览器绕过认证网关直连 Agent。

### 4.3 统一数字人协议

```python
class AvatarProvider(Protocol):
    name: str
    async def capabilities(self) -> AvatarCapabilities: ...
    async def create_session(self, request, user_id) -> AvatarSession: ...
    async def send_text(self, session_id, text, *, mode="text") -> ProviderResult: ...
    async def interrupt(self, session_id) -> ProviderResult: ...
    async def close_session(self, session_id) -> ProviderResult: ...
    async def health(self) -> ProviderHealth: ...
```

返回给前端的会话初始化数据只能包含短期/一次性参数，不得包含长期密钥。

## 5. 实现策略

1. 先实现 mock Provider 和 MCP 探针，确保无外部账号也能跑通。
2. 再实现三家云厂商与 Fay 的配置型适配器，所有真实请求通过服务端配置开关启用。
3. Agent 采用 LangGraph 的 `security -> receive -> retrieve -> tool -> respond -> provider` 状态图；没有 LLM 时使用确定性回显，后续只替换模型节点。
4. 意图识别先走可替换模型端口，超时后回退规则分类；工具按核心能力和意图类别分层披露，独立调用并发执行。
5. 流式请求先发 `start`/`filler`，每个图节点和文本片段检查 run token；中断只终止当前运行，新消息可在同一会话重新开始。
6. 评测评分默认使用确定性规则，缺少标注的维度显示暂无数据；实时聊天自动写入脱敏运行记录，离线 runner 可通过接口补充人工标注和重复样本。
7. 认证网关使用 allow-list 转发，禁止任意 URL 代理，防止 SSRF。
8. 会话使用内存存储加 TTL 清理，接口保持幂等；后续可替换 Redis，不改变契约。

### 5.1 模块化约束

- 每个服务按 `api`（HTTP/DTO）、`application`（用例编排）、`domain`（协议/实体）、`infrastructure`（外部系统）分层。
- Provider 只能通过统一端口调用，厂商 SDK、HTTP 客户端和签名逻辑不得泄漏到 Agent 图节点或前端。
- MCP 工具按工具域拆分文件，工具注册集中在 `registry`，工具执行不得直接修改会话状态。
- 前端按 `pages`、`features`、`shared`、`services` 拆分；请求、鉴权状态和视图状态分离。
- 单文件原则上不超过 300 行；超过时必须按职责拆分并补充模块说明。
- 配置集中在环境变量/配置文件，禁止在业务代码中散落供应商密钥、URL 和超时常量。
- 长连接、会话、队列和缓存都必须有超时、关闭和清理路径；流式输出需要背压和取消信号。
- 用户体验要求：登录/请求/连接状态可见，错误可恢复，流式输出逐步呈现，移动端不出现横向滚动。

### 5.2 第一版目录基线

```text
apps/
  web/                         # React + TypeScript
    src/app/                   # 应用入口与路由
    src/features/auth/         # 登录与用户状态
    src/features/chat/         # 对话与 SSE
    src/features/avatar/       # 数字人会话与 provider UI
    src/shared/                # API、类型、通用组件
  auth-service/                # Spring Boot + Sa-Token
    src/main/java/.../auth/    # 登录与用户
    src/main/java/.../gateway/ # Agent 代理
    src/main/java/.../common/  # DTO、异常、配置
  agent-service/               # FastAPI + LangGraph
    app/api/                   # 路由与请求模型
    app/application/           # 用例编排
    app/graph/                 # LangGraph 状态图与节点
    app/agent/                 # 意图、路由、filler、性能和 steering 策略
    app/avatar/                # Provider 端口、注册表、适配器
    app/mcp/                   # MCP 客户端与工具目录
    app/rag/                   # Docling 解析、切分、索引、检索端口
    app/observability/         # FutureAGI/本地观测适配器
    app/evaluation/            # 数据集、指标、运行记录和评测接口
    app/infrastructure/        # 配置、存储、清理任务
  mcp-server/                  # 独立 MCP 工具服务
packages/contracts/            # 跨服务 JSON Schema/TypeScript 类型
deploy/                        # Compose、反向代理与启动脚本
docs/                          # 架构、API、Provider、运行手册
tmp-docs/                      # 任务书与验收记录，不放业务源代码
```

MCP 传输层以官方 SDK 的当前稳定接口为准。浏览器 SSE 保持 `id/event/data` 兼容帧，内部事件总线使用 `event_id/seq` envelope 做重连；不得把厂商 SDK 或 MCP 连接细节放进 LangGraph 节点。
RAG 与观测均采用端口/适配器：Docling 只负责解析，向量存储和 FutureAGI 发送器可替换；网络故障或未配置凭证不得拖垮对话主链路。

## 6. 验收标准

### 6.1 功能验收

- [x] `docker compose config` 成功。
- [x] Compose 仅发布前端端口；认证、Agent、MCP 使用内部网络。
- [x] 未登录访问受保护 API 返回 401；用户上下文和会话按 owner 隔离。
- [x] 使用演示账号登录后能创建 mock 会话。
- [x] 发送文本能经过 LangGraph，执行 MCP 工具，并返回结构化响应。
- [x] SSE 能收到 `start`、`filler`、`intent`、`tool_disclosure`、`security`、`tool`、`delta`、`provider`、`done` 事件；安全门命中时跳过 RAG 与 MCP 工具。
- [x] 会话可打断、关闭，关闭后重复关闭不报错；关闭记录会按 TTL 回收。
- [x] Provider 列表包含 mock、aliyun、mofa、iflytek、fay，并显示配置状态。
- [x] Docling 能将示例文档解析成带来源元数据的文档块，并通过检索接口返回结果。
- [x] RAG JSON 入库与文件上传共用单文档字节预算，超限在解析前拒绝。
- [x] Agent 运行产生结构化 trace/span；FutureAGI 未配置时本地有界日志仍可用；Trace 支持用户隔离回放。
- [x] 评测接口提供项目自建不少于 10 个基线样本（当前 25 条）及运行记录，覆盖 Token/价格、成功率、工具准确率、正确性/一致性、事实有据性、注入防护和 Agent/数字人延迟。

### 6.2 安全验收

- [x] 前端构建产物和网络响应中不存在 AK/SK/AppSecret。
- [x] 直接请求 Agent（无内部令牌）被拒绝。
- [x] 认证网关不接受任意目标地址转发。
- [x] 超长输入被拒绝，错误信息不泄露内部堆栈和密钥；评测预览和遥测字段脱敏。
- [x] 注入样本要求拒绝/拦截且不出现 token、密钥等凭据模式。

### 6.3 工程验收

- [x] Python 单元测试、Java 测试、前端构建均通过；Docker 配置通过静态验收。
- [x] README 能让新开发者在 10 分钟内启动 mock 链路。
- [x] 目录按功能模块组织，无根目录散落业务源文件；关键模块有边界说明。
- [x] 关键路径包含超时、取消、幂等、用户隔离和资源清理测试。
- [x] RAG 解析失败、观测上报失败、MCP 不可用均有降级路径，不影响健康检查与聊天响应。
- [x] 任务书完成后重命名为 `digital-human-agent-v0.1.0-task-book-已完成.md`。

## 7. 风险与后续版本

- 云厂商 SDK、签名和 WebRTC 参数依赖控制台开通项；真实冒烟需凭证和 HTTPS/WSS 环境。
- Fay 使用 GPL-3.0，正式商用前需要做许可证边界评估；推荐独立进程或仅使用协议适配。
- v0.2.0 再引入真实 LLM、事件总线、Redis、持久化审计、模型裁判和真实 SDK 冒烟，不在本版扩大范围。
