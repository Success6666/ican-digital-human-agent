# ican 数字人 Agent v0.1.3 实时传输任务书

## 1. 基本信息

- 项目：ican 通用 Agentic Digital Human 底座
- 版本：v0.1.3
- 日期：2026-08-30
- 状态：已完成（2026-08-30）

## 2. 背景与目标

v0.1.2 已完成文本 SSE 的首响、取消、事件关联和会话生命周期加固，但浏览器到数字人的实时交互仍是单向文本流：没有双向控制通道、音频帧边界、服务端 endpointing 或播放队列。因此用户改口时只能中断文本生成，无法同时快速停止音频表现。

本版目标是建立一个可替换、可压测、经过认证网关的实时传输底座：

1. 浏览器通过认证网关建立单一 WebSocket 连接，传输文本控制和有界音频帧。
2. Agent 统一处理连接级鉴权、帧限额、心跳、运行代际和中断确认。
3. 音频输入使用 PCM16、16 kHz、单声道、20 ms 帧作为默认规范；未配置 ASR 时也能返回明确的能力状态，不伪造转写结果。
4. 文本 Agent 继续复用 LangGraph；输出事件沿用 v0.1.2 的可读事件语义，并增加连接级确认和音频队列状态。
5. 前端支持麦克风权限、录音状态、改口、停止播放和连接恢复，旧 run 的文本与音频都不能污染新 run。

## 3. 架构边界

```text
Browser
  ├─ JSON control/text frames
  └─ PCM16 binary frames
          │
          ▼
Web/Nginx Upgrade
          │
          ▼
Auth Service WebSocket Relay
  ├─ Sa-Token handshake authentication
  ├─ bounded outbound queue
  └─ internal identity headers/ticket
          │
          ▼
Agent Realtime Gateway
  ├─ frame validation and heartbeat
  ├─ run/utterance/revision ownership
  ├─ AudioIngress port
  └─ LangGraph stream + ProviderRuntime
```

网关只转发认证后的连接和受限身份上下文；浏览器不能直连 Agent，长期厂商密钥不进入浏览器。Agent 的音频处理通过端口隔离，当前提供 deterministic mock ingress，真实 ASR/TTS/厂商流媒体在后续适配器实现。

## 4. 实施范围

### 4.1 Agent 实时协议

- 新增 `app/realtime` 模块，拆分协议模型、连接状态、帧限额、音频 ingress、事件桥接和 WebSocket 路由。
- 文本帧：`hello`、`text`、`interrupt`、`ping`、`close`。
- 二进制帧：PCM16 音频块，单帧默认 640 bytes（20 ms），最大输入帧和单连接累计缓冲均有硬上限。
- 服务端事件：`ready`、`ack`、`transcript`、`run_started`、既有 Agent 事件、`audio_queue`、`interrupted`、`run_done`、`pong`、`error`。
- 每条运行绑定 `runId + utteranceId + revision`；旧运行的文本、音频和 Provider 事件必须在发送前再次校验。
- 空闲心跳、连接关闭和异常路径必须释放任务、队列和运行令牌。

### 4.2 认证网关代理

- Auth Service 增加明确的 `/api/realtime` WebSocket handler。
- 握手阶段校验 Sa-Token，连接 Agent 时只发送固定内部地址、内部令牌和当前用户标识。
- 上下行分别使用有界队列和单写者，禁止无限堆积；浏览器断开时取消 Agent 连接和运行。
- 保持现有 `/api/chat/stream` SSE 兼容，不修改普通 REST 代理的目标校验。
- Nginx 为 `/api/realtime` 配置 Upgrade、读写超时和连接头，其他 `/api` 行为不变。

### 4.3 前端实时交互

- 新增 `features/realtime`，封装连接状态机、协议编码、音频采集和重连退避。
- 使用 `AudioContext` 将麦克风帧转换为 PCM16；权限拒绝、浏览器不支持和连接断开都显示人类可读状态。
- 录音/播放状态与 Chat 状态分离；改口时先清空本地播放队列，再发送带 `runId` 的 interrupt。
- 只渲染当前 `revision` 的转写、文本和性能事件；连接重连后不得重复提交旧文本。
- 保持前端信息密度和现有导航，不把原始二进制、内部 ticket 或 SDK 字段展示给用户。

### 4.4 可观测性与评测

- 增加连接建立、首个 `ready`、首个转写、首个 Agent delta、首个音频块、interrupt ack、队列深度和丢帧计数。
- Trace 关联 `connectionId`、`runId`、`utteranceId`，对外只展示短 ID 和人类可读阶段。
- 评测增加音频帧完整率、改口成功率、首音频块延迟和中断确认延迟；缺失 ASR/TTS 时标记 `unsupported`，不得计为成功。

## 5. 非目标

- 不在本版接入生产 WebRTC、TURN、回声消除或多路视频编解码。
- 不在无凭证环境伪造阿里云、魔珐星云、讯飞或 Fay 的真实 ASR/TTS/视频效果。
- 不在本版把内存会话切换为 Redis 多副本；仅保留连接/会话端口和代际字段，下一版按契约接入共享状态。
- 不新增垂直领域人格、复杂多 Agent 或业务工具。

## 6. 验收标准

### 6.1 协议与安全

- [x] 未登录 WebSocket 握手返回结构化 401，Agent 直连仍被拒绝。
- [x] 非法 JSON、超限文本、错误音频长度、未知消息类型和错误 revision 返回可读错误并关闭或隔离当前帧。
- [x] 单连接待发送队列、音频缓冲和后台任务均有上限；断开后无 pending task 和未消费异常。
- [x] 生产环境拒绝默认、公开占位和过短的内部令牌；认证 Cookie 默认启用 HttpOnly 与 SameSite=Lax，HTTPS 部署可打开 Secure。
- [x] 现有 REST/SSE、Trace 用户隔离和内部令牌测试全部保持通过。

### 6.2 实时体验

- [x] 热连接 `ready` p95 < 100 ms（本地 Compose 10 次样本：19.39 ms）。
- [x] `speech_start` 到 `interrupt_ack` p95 < 100 ms；本地中断确认样本为 8.90 ms，前端中断会先清空播放队列。
- [x] 连续 20 ms 音频帧运行 30 秒不产生无界堆积；单元测试模拟 1,500 帧，缓冲保持在上限内并记录丢帧。
- [x] 连续改口场景只保留最新 `runId + revision` 的文本、转写、音频和 Provider 事件；覆盖状态、协议和 WebSocket 回归测试。
- [x] ASR/TTS 未配置时明确显示“当前仅支持文本实时链路”，不能伪造音频或转写成功。

### 6.3 工程交付

- [x] Agent、Auth、MCP、Web 单元测试和 Compose 健康检查通过。
- [x] 增加 WebSocket 协议、帧限额、背压、断开清理、改口和认证代理回归测试。
- [x] 生产业务源文件原则上不超过 300 行，实时协议按功能模块组织。
- [x] 完成后将本文件重命名为 `digital-human-agent-v0.1.3-realtime-transport-task-book-已完成.md`，提交 v0.1.3。

## 8. 实际验收记录

- Agent：`153 passed, 1 skipped`；Ruff 检查通过。
- MCP：`6 passed`。
- Auth：`mvnw.cmd -q test` 退出码 0；新增 Cookie-only 鉴权、WebSocket relay、URI 归一化和发送异常测试。
- Web：`npm run build` 通过；`npm run test:realtime` 通过（2/2）。
- Compose：四个服务均为 healthy；同源 Cookie REST 创建会话返回 200，WebSocket `ready`、`ack`、`run_started`、Agent 事件和 `run_done` 完整；无 Cookie REST/WS 均返回 401。
- 生命周期：新增 Provider 级引用计数锁、会话代际标识、关闭/过期清理协调和生产默认内部令牌保护；实时握手会拒绝已关闭会话。
- 安全配置：Agent、MCP、Auth 对生产内部令牌统一执行占位/长度校验；Auth 登录 Cookie 已验证 `HttpOnly` 与 `SameSite=Lax` 属性。
- 交付边界：真实 ASR/TTS、厂商流媒体仍通过 Provider 端口接入，当前未配置时只返回明确的 `unsupported` 能力状态。

## 7. 风险与后续

- 当前 mock ingress 只验证帧和生命周期，不代表真实语音识别质量；真实 ASR/TTS 适配器必须提供明确的取消语义和 run 级幂等键。
- Spring MVC WebSocket relay 使用阻塞式厂商无关桥接时需要限制连接数和写队列；规模化部署前应切换到专用异步 WebSocket/消息层。
- 会话 ID 在旧代际过期后被立即复用时，清理任务会主动避让新代际，旧 Provider runtime 可能需要后续 outbox/drain 机制补偿回收；多副本版本必须纳入共享租约和待清理状态。
- 文本容量拒绝或真实 ASR 启动失败发生在 revision 接受之后时，同 revision 重试需要由客户端递增 revision；后续版本应补事务化回滚语义。
- `SESSION_IDLE_TIMEOUT_SECONDS` 当前表示滑动租约窗口，若产品需要绝对 TTL，应在持久化会话版本统一命名并增加上限校验。
- 多副本运行状态、持久化 Trace/RAG/评测和 Provider teardown outbox 在 Redis/数据库版本单独验收。
