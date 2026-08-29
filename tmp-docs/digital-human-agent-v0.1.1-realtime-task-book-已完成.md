# 数字人 Agent 实时交互增强任务书

## 1. 基本信息

- 项目：ican 通用 Agentic Digital Human 底座
- 版本：v0.1.1
- 日期：2026-08-29
- 状态：已完成（本地链路验收通过；真实云 Provider/Fay 需凭证后再做冒烟）

## 2. 目标

在保持 Agent Core、Presentation Layer 与 DigitalHumanRuntime 解耦的前提下，补强同一会话内的实时流式交互：新输入可以立即取代旧输入，旧 run 的文本、工具结果和数字人输出不得迟到写回；服务镜像采用 CPU-only Docling 依赖策略并可在 Compose 中完成健康启动。

## 3. 实施范围

1. 固化 `AgentResponse -> PresentationLayer -> DigitalHumanRuntime` 契约，并让同步、SSE 和 Provider 事件保持一致。
2. 为运行令牌增加并发安全检查：节点边界、增量输出、Provider 返回后均检查 run 是否仍为当前运行。
3. 前端支持流式期间继续输入；改口时取消旧 SSE、请求服务端中断、隔离迟到事件，并将旧助手消息置为已打断终态。
4. 保留 Provider 适配器的外部 SDK 边界，不在本版引入本地 Fay 进程或伪造云厂商调用。
5. Docling 采用 CPU 版 Torch/Torchvision 约束，避免默认拉取 CUDA 运行时；修复依赖冲突并完成 Compose 构建。

## 4. 验收标准

### 4.1 实时交互

- [x] 同一会话先发送“今天天气怎么样”，在旧响应未结束前发送“不对，是昨天”；前端改口入口和服务端 run supersede 测试覆盖该路径。
- [x] 新输入在旧中断请求完成后启动新 run；旧 run 的迟到 delta、error、provider 结果不会修改当前 UI。
- [x] 旧助手消息不再显示为生成中；时间线能显示已切换/已打断。
- [x] 服务端旧 run 在节点间和 Provider 返回后均被抑制；慢分类器、RAG、MCP、Provider 并发测试证明旧结果不会完成为有效 Provider 输出。
- [x] 中断、关闭、会话过期均可释放连接和后台任务；重复中断不导致新 run 被误伤。

### 4.2 运行时边界

- [x] Graph 节点只产出结构化 `AgentResponse`，数字人 SDK 细节仅出现在 Runtime/Adapter。
- [x] 同步响应和 SSE `done` 包含可供回放的结构化数字人表现信息。

### 4.3 构建与验证

- [x] Agent Python 测试、Ruff、编译检查通过。
- [x] 前端 TypeScript/Vite 构建通过。
- [x] Auth Maven 测试和 MCP 测试通过。
- [x] `docker compose up -d --build` 成功，四个服务健康，宿主机仅暴露 Web 入口。
- [x] 通过 Web 入口完成登录、创建 mock 会话、同步聊天、SSE 聊天和中断冒烟。

## 5. 实现结果

- Agent Core 保持与 `DigitalHumanRuntime` 解耦，同步和流式响应统一输出 `AgentResponse`。
- 同一会话使用 `runId` 和停止令牌实现新消息抢占；分类、RAG、MCP、Provider 外部 I/O 均有取消与迟到结果抑制路径。
- SSE 首帧先返回可中断的听候/填充表现，前端在改口时取消旧连接、请求服务端中断并隔离旧事件。
- 认证网关固定走 HTTP/1.1 代理并逐块刷新 SSE，异常以受控 `event:error` 返回；浏览器不直连 Agent。
- Docling 依赖采用 CPU-only Torch 约束，Compose 仍保持仅 Web 对宿主机暴露。

## 6. 实际验收记录

- Agent：`59 passed, 1 skipped`；Ruff 和 `compileall` 通过，包含慢分类器、RAG、MCP、Provider、同步 supersede、流早期断开和关闭竞态清理回归。
- MCP：`2 passed`；使用项目声明的 MCP 2.x 依赖验证。
- Auth：`mvnw.cmd test -q` 通过；包含请求体转发、SSE 分块刷新和上游错误帧测试。
- Web：`npm run build` 通过。
- Compose：`docker compose config --quiet` 和 `docker compose up -d --build` 通过；`web`、`auth-service`、`agent-service`、`mcp-server` 均为 healthy，宿主机只绑定 `127.0.0.1:8088`。
- Web 入口冒烟：登录、Provider 列表（5 项）、mock 会话、同步聊天、SSE `start/filler/intent/delta/done`、`runId/seq/eventId`、中断和关闭均通过；Agent 停止时 SSE 返回受控 `event:error`，服务恢复后健康检查通过。
- 容器运行时：Agent 版本 `0.1.1`，Torch `2.12.0+cpu`，CUDA 不可用，Docling 依赖可发现。

本版未使用真实阿里云、魔珐星云、讯飞或 Fay 凭证做在线语音/视频冒烟；这些适配器保留在外部 SDK 边界，实际取消效果取决于厂商协议对 `runId` 和可取消 I/O 的支持。

## 7. 风险与后续

- 外部厂商 SDK 的真正语音/视频取消能力取决于其协议；适配器需要在后续版本支持带 run token 的幂等取消和可取消 I/O。
- 当前内存会话在“关闭与新建请求同时到达”的极短窗口仍允许新 run，后续接入持久化会话时增加两阶段 `closing` 状态和分布式幂等锁。
- 本版仍使用确定性响应和内存会话存储，生产部署需在后续版本接入真实模型、Redis/持久化 checkpoint 和连接池。
