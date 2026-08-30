# ICAN 数字人 Agent

ICAN 是一个面向真实产品演进的数字人 Agent 底层骨架（当前版本 v0.1.5）。第一版先打通浏览器、认证网关、LangGraph 编排、MCP、RAG、数字人 Provider 和可观测性，不绑定具体行业人格或业务工具。

## 目录

```text
apps/
  web/                 React + TypeScript 控制台
  auth-service/        Spring Boot + Sa-Token 认证网关
  agent-service/       FastAPI + LangGraph Agent、RAG、评测
  mcp-server/          MCP 2.x 工具服务
packages/contracts/    跨服务事件契约
docs/                  架构、接口、Provider、运行手册
tmp-docs/              任务书与阶段验收记录
```

## 十分钟启动 Mock 链路

### Docker Compose

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build
```

浏览器访问 `http://localhost:8088`，演示账号为 `demo/demo123`，管理员账号为 `admin/admin123`。Compose 只把 Web 入口绑定到宿主机，认证、Agent 和 MCP 位于内部网络。

### 本地开发

在 PowerShell 中分别打开终端：

```powershell
# MCP
Set-Location apps\mcp-server
$env:PYTHONPATH=(Get-Location).Path
python -m uvicorn app.main:app --host 127.0.0.1 --port 9000

# Agent
Set-Location ..\agent-service
$env:PYTHONPATH=(Get-Location).Path
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Web
Set-Location ..\web
npm install
npm run dev
```

认证网关可使用 `apps/auth-service/mvnw.cmd spring-boot:run` 启动，并将 `AGENT_BASE_URL` 指向 `http://localhost:8000`。生产环境应替换演示账号、内部令牌和所有 Provider 配置；内部令牌需使用至少 32 字符的随机值，HTTPS 部署时设置 `AUTH_COOKIE_SECURE=true`。

## 已实现链路

- Sa-Token 登录态、用户隔离、固定目标反向代理和统一错误脱敏。
- LangGraph `security -> receive -> retrieve -> tool -> respond -> provider` 图；意图识别、分类路由、工具渐进式披露、注入安全门、并发 MCP 调用、首响 filler、微表情语义指令和可中断运行令牌。
- MCP 2.x Streamable HTTP，远端不可用时可配置本地探针降级，并带快速 TCP 探测。
- MCP 结果在进入图状态前受 `MCP_MAX_RESULT_BYTES`、`MCP_MAX_RESULT_ITEMS`、`MCP_MAX_RESULT_DEPTH` 三层边界约束；发生截断时会在工具元数据中标记原因，避免大 payload 扩散到 Trace 和前端。
- Docling 文档解析、切分、向量检索端口和用户命名空间隔离。
- Provider 能力会区分单轮中断、会话中断和本地隔离，避免把服务端抑制旧结果误认为远端播报已停止。
- FutureAGI 适配器；未配置时使用有界本地 JSON 缓冲。
- 评测中心：项目自建 25 条链路场景基线集，记录 token、价格、任务成功率、工具调用准确率、结果正确性/一致性、事实有据性、提示词注入防护，以及 Agent/数字人分段延迟和 p50/p95。
- 审计与 Trace 回放：只展示当前用户可见、已脱敏的人类可读信息。
- 后台运行配置：管理员可通过紧凑弹窗调整默认数字人和会话策略，变更会原子持久化并同步到新会话。

## 评测接口（经认证网关）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/evaluation/overview` | 当前用户的汇总指标 |
| GET | `/api/evaluation/datasets` | 项目自建数据集和样本元信息 |
| POST | `/api/evaluation/runs` | 提交一条离线或实时评测样本 |
| GET | `/api/evaluation/runs` | 查看当前用户的评测运行 |
| GET | `/api/observability/traces/{traceId}` | 脱敏 Trace 回放 |

评测服务默认只保存有限条内存记录，价格通过 `EVAL_INPUT_PRICE_PER_1K`、`EVAL_OUTPUT_PRICE_PER_1K` 和 `EVAL_CURRENCY` 配置。后续可把存储替换为数据库或队列而不改变 HTTP 契约。

实时链路会分别记录服务端首事件、服务端首个可见事件、Agent、数字人和取消延迟，并在 Trace 回放与评测汇总中提供平均值及 p50/p95。首个可见事件以服务端写出首个可见 SSE 帧前的时间戳为准，不冒充浏览器实际绘制时间。FutureAGI 导出采用有界异步队列；`OBSERVABILITY_MAX_PENDING_TASKS` 和 `OBSERVABILITY_PENDING_FLUSH_TIMEOUT_SECONDS` 用于控制积压和关闭等待，队列满时保留本地记录并计入丢弃计数。

MCP 工具结果默认最多保留 64 KiB、256 个集合项和 8 层嵌套，可在 `.env` 中按工具复杂度调整；生产环境应保留硬上限并结合 Trace 观察截断比例。

Agent 入口默认限制请求体为 16 MiB（`AGENT_MAX_REQUEST_BODY_BYTES`），RAG 文档默认限制为 8 MiB；该余量用于容纳 Base64/JSON 编码开销，超限请求在解析前拒绝。

### FutureAGI 可观测性配置

生产镜像（Python 3.12）通过 `fi-instrumentation-otel` 的 `register()` 创建
非全局 `TracerProvider`，使用 `FUTUREAGI_API_KEY`、`FUTUREAGI_SECRET_KEY` 和
`FUTUREAGI_PROJECT`。可选的 `FUTUREAGI_ENDPOINT` 会在注册期间映射为
`FI_BASE_URL`，注册完成后立即恢复进程环境。未安装该 OTel 包、凭证不完整或导出器
异常时，事件自动写入有界本地 JSON 缓冲，不影响聊天请求。

当前 `fi-instrumentation-otel` 1.1.x 要求 Python `<3.14`；Python 3.14 环境会跳过
该可选依赖并保持本地降级路径。`futureagi` 是另一个评测/数据 SDK，不作为 OTel
注册入口使用。

## Docling 本地模型策略

首版 PDF 链路建议准备 layout Heron；包含表格时启用 TableFormer accurate；扫描 PDF 或图片再启用 RapidOCR ONNXRuntime（中文）。图片分类、图片描述/VLM、公式和图表模型默认关闭，按数据类型和延迟预算按需启用。通过 `DOCLING_ARTIFACTS_PATH` 指向本地权重目录，保持离线可复现；`DOCLING_MAX_CONCURRENCY` 控制解析并发，CPU-only 环境建议保持为 `1`；`DOCLING_ENABLED=false` 可强制使用文本回退，`RAG_MAX_DOCUMENT_BYTES` 统一限制单文档解析预算。

## 验证命令

```powershell
Set-Location apps\agent-service
$env:PYTHONPATH=(Get-Location).Path
python -m pytest -q

Set-Location ..\mcp-server
$env:PYTHONPATH=(Get-Location).Path
python -m pytest -q

Set-Location ..\auth-service
./mvnw.cmd -q clean test

Set-Location ..\web
npm run build
```

本版本实时交互验收记录见 [`tmp-docs/digital-human-agent-v0.1.3-realtime-transport-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.3-realtime-transport-task-book-已完成.md)，上一版记录见 [`tmp-docs/digital-human-agent-v0.1.2-optimization-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.2-optimization-task-book-已完成.md)。
控制台视觉与页面验收记录见 [`tmp-docs/digital-human-agent-v0.1.3-console-reference-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.3-console-reference-task-book-已完成.md)。
