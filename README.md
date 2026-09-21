# 数字人 Agent（Digital Human Agent）

这是一个面向真实产品演进的数字人 Agent 底层骨架（当前版本 v0.1.54）。第一版先打通浏览器、认证网关、LangGraph 编排、MCP、RAG、数字人 Provider 和可观测性，不绑定具体行业人格或业务工具。

## 目录

```text
apps/
  web/                 React + TypeScript 控制台
  auth-service/        Spring Boot + Sa-Token 认证网关
  agent-service/       FastAPI + LangGraph Agent、RAG、评测
  mcp-server/          MCP 2.x 工具服务
  asr-service/         faster-whisper 本地中文 ASR
packages/contracts/    跨服务事件契约
docs/                  架构、接口、Provider、运行手册
tmp-docs/              任务书与阶段验收记录
```

`asr-service` 是可选的独立推理服务，容器内暴露 `7000` 端口，只与 `agent-service` 在内部网络互通。它按 `ASR_MODEL_SIZE` 加载 faster-whisper 模型（默认 `tiny`），优先尝试 CUDA float16、失败回退 CPU int8；`ASR_INTERNAL_TOKEN` 必须与 Agent 侧的 `HTTP_ASR_API_KEY` 一致。未部署该服务时，Agent 会走其它已配置的语音识别通道。

## 十分钟启动 Mock 链路

### Docker Compose

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build
```

浏览器访问 `http://localhost:8088`，演示账号为 `demo/demo123`，管理员账号为 `admin/admin123`。Compose 只把 Web 入口绑定到宿主机，认证、Agent、MCP、ASR 位于内部网络。

Compose 共 7 个服务：`web`、`auth-service`、`agent-service`、`mcp-server`、`asr-service`、`rabbitmq`、`redis`。RabbitMQ 承载跨会话消息总线，Redis 承载会话存储；两者均只在内部网络可达，不对外暴露端口。

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
- RAG 检索采用分阶段流水线：稠密向量与 BM25 双路召回，按排名（而非分数）做 RRF 融合，随后按融合位次、词法一致度和数值佐证打分，最后以字符 n-gram 包含度抑制近重复分块。各阶段均可独立开关，全部关闭时退化为纯向量排序。
- 中文分词带 bigram 兜底；量级比较支持 `4K` 与 `3840x2160` 跨记法匹配，矛盾陈述不会被当作佐证；每轮检索可输出归因漏斗（selected / rank_too_low / filtered_out / dropped_in_fusion / not_recalled），用于区分召回问题与排序问题。
- 离线检索评测提供 recall、precision、MRR、MAP、nDCG@k，并以配对 bootstrap 比较两套配置在同一批 query 上的差异显著性。
- Provider 能力会区分单轮中断、会话中断和本地隔离，避免把服务端抑制旧结果误认为远端播报已停止。
- FutureAGI 适配器；未配置时使用有界本地 JSON 缓冲。
- 评测中心：项目自建 64 条链路场景基线集（19 个分类：MCP、RAG、个性化、会话控制、可观测性、可靠性、复杂任务、安全、实时音频、对话、工具治理、性能、意图识别、成本、数字人表达、用户体验、租户隔离、质量、边界），记录 token、价格、任务成功率、工具调用准确率、结果正确性/一致性、事实有据性、提示词注入防护，以及 Agent/数字人分段延迟和 p50/p95。
- 审计与 Trace 回放：只展示当前用户可见、已脱敏的人类可读信息。
- 后台运行配置：管理员可通过紧凑弹窗调整默认数字人和会话策略，变更会原子持久化并同步到新会话。

## 评测、检索与可观测性接口（经认证网关）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/evaluation/overview` | 当前用户的汇总指标 |
| GET | `/api/evaluation/datasets` | 项目自建数据集和样本元信息 |
| POST | `/api/evaluation/datasets/{datasetId}/run` | 按数据集批量跑评测，返回 `202` |
| POST | `/api/evaluation/runs` | 提交一条离线或实时评测样本 |
| GET | `/api/evaluation/runs` | 查看当前用户的评测运行 |
| GET | `/api/evaluation/runs/{runId}` | 查看某轮评测详情 |
| GET | `/api/evaluation/runs/{runId}/raw` | 查看当前用户某轮评测的完整原始归档 |
| GET | `/api/observability/traces` | 当前用户 Trace 摘要 |
| GET | `/api/observability/traces/{traceId}` | 脱敏 Trace 回放 |
| GET | `/api/rag/health` | RAG 与 Docling 状态 |
| POST | `/api/rag/ingest` | 文本或 Base64 文档入库 |
| POST | `/api/rag/search` | 用户隔离的混合检索 |
| DELETE | `/api/rag/documents/{documentId}` | 删除某文档的全部块 |

评测服务以内存索引提供快速汇总，同时将每轮完整请求、输出、评分和元数据追加写入 `EVALUATION_RAW_ARCHIVE_PATH`；服务重启后会恢复索引，原始归档持续保留。价格通过 `EVAL_INPUT_PRICE_PER_1K`、`EVAL_OUTPUT_PRICE_PER_1K` 和 `EVAL_CURRENCY` 配置。

`POST /api/rag/search` 走混合检索流水线，按操作者与 collection 隔离命名空间；结果缓存由 `RAG_SEARCH_CACHE_TTL_SECONDS`（默认 30 秒）和 `RAG_SEARCH_CACHE_MAX_ENTRIES` 控制，入库或删除同一命名空间时会使其失效。

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

## RAG 检索调优

检索流水线的每个阶段都可独立开关与调参，默认值面向通用中文知识库，不下发任何环境变量即可工作。生产环境应先在离线评测集上比较再固化。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `RAG_LEXICAL_ENABLED` | `true` | 是否启用 BM25 词法召回 |
| `RAG_LEXICAL_TOP_K` | `50` | 词法路由返回条数 |
| `RAG_CANDIDATE_MULTIPLIER` | `8` | 稠密探测深度 = `top_k × 该值` |
| `RAG_RRF_K` | `60` | RRF 平滑常数，越大越压低头部优势 |
| `RAG_RRF_VECTOR_WEIGHT` | `1.0` | 向量路由在融合中的权重 |
| `RAG_RRF_LEXICAL_WEIGHT` | `1.0` | 词法路由在融合中的权重 |
| `RAG_FUSION_POOL_SIZE` | `50` | 融合后进入打分的候选上限 |
| `RAG_REDUNDANCY_THRESHOLD` | `0.8` | 近重复判定阈值，越高越宽松 |
| `RAG_SHORT_TEXT_EXEMPT_CHARS` | `24` | 低于该字数的文本豁免去重 |
| `RAG_NUMERIC_BOOST_ENABLED` | `true` | 是否启用数值佐证加权 |
| `RAG_NUMERIC_TOLERANCE` | `0.05` | 数值相对容差，超出记为 conflict |

两点使用提醒：

- 提高 `RAG_CANDIDATE_MULTIPLIER` 或 `RAG_FUSION_POOL_SIZE` 会同时增加打分开销，属于线性成本；若召回本就不足，应优先检查 `RAG_LEXICAL_ENABLED` 与分词效果，而不是无限加深候选池。
- `RAG_SHORT_TEXT_EXEMPT_CHARS` 不是越小越好。短文本的字符 n-gram 不稳定，编号、错误码一类的短片段往往高度相似但语义不同，设得过低会把它们误去重。

## 评测数据

### 项目化评测集

Agent 侧内置一套工程化评测样本，随服务启动即可查看，无需外部依赖：

| 指标 | 值 |
| --- | --- |
| 数据集 ID | `digital-human-core` |
| 数据集名称 | 数字人 Agent 核心评测集 |
| 样本条数 | 64 |
| 分类数 | 19 |
| 覆盖分类 | MCP、RAG、个性化、会话控制、可观测性、可靠性、复杂任务、安全、实时音频、对话、工具治理、性能、意图识别、成本、数字人表达、用户体验、租户隔离、质量、边界 |

每个样本声明六类可自动断言的期望：`expected_tools`（应调用的工具）、`expected_keywords`（回答须包含的关键词）、`expected_evidence`（须引用的证据）、`injection_attempt` 与 `expected_blocked`（提示注入防护）、`difficulty`（难度分层）。`injection_attempt` 类样本用于验证提示注入会被拦截而非被模型顺从执行。

评测走 `POST /api/evaluation/datasets/{datasetId}/run` 批量触发，结果与原始归档分别通过 `GET /api/evaluation/runs` 与 `.../runs/{runId}/raw` 取回；每轮完整请求、输出、评分和元数据追加写入 `EVALUATION_RAW_ARCHIVE_PATH`，服务重启后索引自动恢复。

### 检索链路离线指标

RAG 侧在 `tmp-docs/rag-evaluations/` 下留存两套可复现的基准：

| 文件 | 内容 | 关键结论 |
| --- | --- | --- |
| `v0.1.46-local-bge-benchmark.json` | 本机 BGE 中文模型（`BAAI/bge-small-zh-v1.5`，512 维）在 CPU 上的端到端表现 | recall@5 = 1.0，MRR = 1.0；冷启动 p50 30.4 ms / p95 31.5 ms，热缓存 p50 0.79 ms / p95 0.90 ms |
| `v0.1.46-hierarchical-cache-baseline.json` | 无模型环境下的 hash 向量历史对照 | 冷启动 p50 6.97 ms；**仅作对照，不代表生产默认链路** |

冷热差距约 38×，说明缓存命中与否是首字延迟的主导因素，与 `RAG_SEARCH_CACHE_TTL_SECONDS` 的取值直接相关。

### 调优参数 A/B 对照

`v0.1.54-tuning-ab.json` 记录了一次完整 A/B：固定 34 篇语料 / 15 个判定查询 / `top_k = 5`，只改一个参数、其余保持默认，用配对 bootstrap（2000 次重采样，95% 置信区间）判断差异是否显著。语料刻意构造了近重复簇、记法变体（`4K` ↔ `3840x2160`）、短编码片段和同词异义干扰项。

各配置的整体指标：

| 配置 | recall@5 | precision@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- |
| `baseline`（默认） | 0.933 | 0.280 | 1.000 | 0.953 |
| `lexical-off` | 0.933 | 0.280 | 1.000 | 0.948 |
| `no-dedup` | 0.817 | 0.200 | 1.000 | 0.852 |
| `no-numeric-boost` | 0.933 | 0.280 | 1.000 | 0.953 |
| `wide-pool` | 0.933 | 0.280 | 1.000 | 0.953 |
| `lexical-heavy` | 0.933 | 0.280 | 1.000 | 0.953 |
| `rrf-k-10` | 0.933 | 0.280 | 1.000 | 0.953 |
| `dedup-tight` | 0.833 | 0.213 | 1.000 | 0.869 |

配对显著性检验中**只有两组差异成立**（其余置信区间都跨零，视为噪声）：

| 对照 | 指标 | Δ | 95% CI | 胜负 | 显著 |
| --- | --- | --- | --- | --- | --- |
| `no-dedup` | recall@5 | −0.117 | [−0.233, −0.033] | 0 胜 / 4 负 | ✅ |
| `no-dedup` | nDCG@5 | −0.101 | [−0.199, −0.026] | 0 胜 / 4 负 | ✅ |
| `dedup-tight` | recall@5 | −0.100 | [−0.200, −0.017] | 0 胜 / 4 负 | ✅ |
| `dedup-tight` | nDCG@5 | −0.085 | [−0.166, −0.016] | 0 胜 / 4 负 | ✅ |

结论分三条，都指向同一件事——**去重阈值是这套参数里唯一被证明有效的一档**：

1. **关掉去重代价明确**（recall@5 掉 11.7 个百分点，4 个查询变差、0 个变好）。近重复簇会把 `top_k` 名额占满，同一事实的多份改写挤掉了其它相关段落。
2. **收紧去重同样有害**（recall@5 掉 10.0 个百分点）。阈值从 0.8 降到 0.6 并下调短文本豁免后，语义相关但字面不同的段落被误判为重复而丢弃，方向与关掉去重相反、幅度相近，说明 0.8 附近是这一档的合理区间。
3. **其余六个参数在当前规模下不产生可测量差异**。`lexical-off`、`no-numeric-boost`、`wide-pool`、`lexical-heavy`、`rrf-k-10` 相对默认值的置信区间全部跨零。这不代表这些开关无效，而是本语料与查询规模（34 篇 / 15 查询）不足以把它们的效应从采样噪声里分离出来——**样本量扩大或查询换成真实业务分布后需要重跑**，不要据此认为词法召回或数值佐证可以删掉。

复现方式：参数由 `RetrievalTuning` 承载，全部支持 `RAG_*` 环境变量覆盖；评测函数取自 `app.rag.tuning`，`evaluate_retrieval` 出指标、`compare_configurations` 出配对显著性。压测脚本产出的 JSON 即上表来源，字段含每个配置的完整参数快照与逐查询明细。

## 验证命令

```powershell
Set-Location apps\agent-service
$env:PYTHONPATH=(Get-Location).Path
python -m pytest -q --basetemp="$env:TEMP\pt-agent"

Set-Location ..\mcp-server
$env:PYTHONPATH=(Get-Location).Path
python -m pytest -q --basetemp="$env:TEMP\pt-mcp"

Set-Location ..\auth-service
./mvnw.cmd -q clean test

Set-Location ..\web
npm run build
npm run test:chat
npm run test:realtime
npm run test:layout
npm run test:avatar
npm run test:observability
```

> **Windows 注意**：`--basetemp` 必须指向**纯 ASCII 路径**（如上例的 `%TEMP%`）。项目路径若含中文，pytest 默认在项目内建临时目录，会使 FAISS 的底层文件写入失败并报 `could not open ... for writing`，看起来像业务代码出错，实为路径编码问题。首次使用还需确保 `%TEMP%` 下该父目录已存在。

本版本 RAG 全链路优化验收记录见 [`tmp-docs/digital-human-agent-v0.1.46-rag-optimization-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.46-rag-optimization-task-book-已完成.md)；本地中文 ASR 部署验收记录见 [`tmp-docs/digital-human-agent-v0.1.45-local-asr-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.45-local-asr-task-book-已完成.md)；流式语音顺序播报验收记录见 [`tmp-docs/digital-human-agent-v0.1.44-speech-sequence-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.44-speech-sequence-task-book-已完成.md)；HTTP 到 HTTPS 端口跳转记录见 [`tmp-docs/digital-human-agent-v0.1.43-http-to-https-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.43-http-to-https-task-book-已完成.md)；会话历史、HTTPS 公网入口与流式稳定性记录见 [`tmp-docs/digital-human-agent-v0.1.42-conversation-history-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.42-conversation-history-task-book-已完成.md)。
本版本真实 LLM 与数字人 Provider 调优验收记录见 [`tmp-docs/digital-human-agent-v0.1.49-llm-avatar-tuning-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.49-llm-avatar-tuning-task-book-已完成.md)。本次魔珐 SDK 日志、TTSA 诊断与官方会话上下文验收记录见 [`tmp-docs/digital-human-agent-v0.1.53-avatar-debug-logging-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.53-avatar-debug-logging-task-book-已完成.md)。
本版本 Pi Agent 架构适配与 TTSA 修复验收记录见 [`tmp-docs/digital-human-agent-v0.1.50-pi-agent-adaptation-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.50-pi-agent-adaptation-task-book-已完成.md)；本次会话启动协议修复验收记录见 [`tmp-docs/digital-human-agent-v0.1.52-session-start-fix-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.52-session-start-fix-task-book-已完成.md)；本次官方动作与情感能力验收记录见 [`tmp-docs/digital-human-agent-v0.1.53-official-avatar-capabilities-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.53-official-avatar-capabilities-task-book-已完成.md)。
控制台视觉与页面验收记录见 [`tmp-docs/digital-human-agent-v0.1.3-console-reference-task-book-已完成.md`](tmp-docs/digital-human-agent-v0.1.3-console-reference-task-book-已完成.md)。
