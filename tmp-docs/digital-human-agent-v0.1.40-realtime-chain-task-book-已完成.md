# Digital Human Agent v0.1.40 实时语音链路与交互门禁任务书

## 状态

已完成（2026-09-02）

## 原始问题

1. 数字人未连接时仍可能显示可用输入控件，实时模式和打字入口缺少统一门禁。
2. 用户反馈实时语音“没有反应”，需要沿浏览器输入、实时控制器、WebSocket、Agent ASR/LLM/TTS、音频播放和数字人表达完整核对。
3. 数字人按分句表达时句间等待过长，出现说到一半突然停顿的体验。

## 目标

1. 未建立有效数字人会话前，禁止进入实时对话，禁止发送文字，并明确显示连接状态。
2. 确认实时链路每个阶段的状态、事件、错误和结束信号可以闭环，避免只采集不提交、只生成不播放或播放状态丢失。
3. 优化数字人分句队列和边界调度，降低句间空档，同时保留可中断、可恢复和错误清理能力。

## 运行态诊断与实现结果

1. 当前 Compose 配置未提供服务端 `HTTP_ASR_ENDPOINT` 和 `HTTP_TTS_ENDPOINT`，Agent 会分别使用 `MockPcmIngress` 与 `NullAudioOutput`；PCM 上传因此返回 `asr_unconfigured`，这解释了“语音功能无法使用”。
2. 浏览器本机语音识别作为可用回退：识别到最终文本后优先发送到实时 WebSocket 的 `text` 分支，连接尚未就绪时才回退到普通 SSE；不再要求额外部署 ASR 服务即可验证实时 Agent 链路。
3. 文本输入和实时语音统一依赖 `session && avatarReady`；未连接数字人、运行时异常或会话创建中均保持禁用，不再从打字入口隐式创建数字人会话。
4. Mofa 数字人按流式分句发送：首句打开流、尾句关闭流，中间句复用同一表达流，避免每句重新建流导致的长间隔，并在中断、销毁和尾句完成后清理状态。
5. 远端 ASR 继续通过 `HTTP_ASR_ENDPOINT` 配置；服务端本地 Whisper/Vosk 模型属于可选部署形态，本版本不强制引入大模型依赖，避免增加基础镜像体积和启动成本。

## 验收标准

1. `session`、实时连接和数字人运行时未就绪时，实时按钮与文本输入均不可操作；会话创建中也不得提交隐藏消息。
2. 链路测试覆盖 `speech_start/audio_start/audio_end`、ASR final、文本运行、`audio_queue/audio_end/run_done`、数字人 speak/complete，以及断线和中断清理。
3. 分句播放不等待前一句完整结束后才创建下一句；队列有稳定的短间隔策略，且不会重复表达、乱序或吞掉尾句。
4. Web、Agent、Auth 测试和生产构建通过，Compose 服务健康检查通过。
5. 生成原始修改文件、差异文件、验证记录和可执行回滚脚本；版本升级到 v0.1.40 并提交。

## 验收记录

- Web：`npm run test:chat`（3/3）、`npm run test:realtime`（8/8）、`npm run test:layout`（6/6）、`npm run test:avatar`（4/4）、`npm run build`（通过）。
- Agent：`python -m pytest -q`（192 passed, 2 skipped, 1 warning）。
- Auth：`.\\mvnw.cmd -q test`（通过）。
- Compose：Web 镜像构建通过；`docker compose up -d --no-build` 后 Agent、Auth、MCP、RabbitMQ、Redis、Web 均健康，`http://127.0.0.1:8088/api/health` 返回 200。
- 证据文件：`tmp-docs/v0.1.40-realtime-chain-artifacts/`。

## 回滚方案

恢复 v0.1.39 的实时模式门禁和分句播放调度；回滚脚本仅作用于验证副本，不覆盖工作树源码。
