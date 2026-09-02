# Digital Human Agent v0.1.38 实时语音响应与音量反馈任务书

## 状态

已完成（2026-09-02）

## 原始问题

实时语音链路在 `audio_end` 后只返回 ASR transcript，没有继续触发 Agent run，用户说话后看不到回答。前端没有音量级别反馈；录音必须依赖手动结束，端到端等待感明显。

## 目标

1. 最终 ASR transcript 自动进入当前实时会话的 Agent 执行链路。
2. 录音期间持续计算归一化音量，前端麦克风按钮按声音大小显示动态波纹。
3. 检测到说话后在约 650ms 静音时自动结束本轮，减少等待；单轮最长 15s，避免资源长期占用。
4. 保留显式结束、打断、断线和权限失败的清理语义；状态文案让用户能判断正在采集、等待识别还是执行。
5. 以首个可见 Agent 事件约 2s 作为体验目标，真实 ASR/LLM 上游耗时纳入观测，不伪造延迟。

## 验收标准

1. `audio_end` 得到非空 final transcript 时，服务端创建一个实时 Agent run，并发送 `ack/run_started/delta/run_done` 链路；unsupported/empty 不启动空请求。
2. `Pcm16Recorder` 通过 `onLevel` 输出 0..1 音量，静音自动收口只触发一次，停止/断线清理计时器。
3. 前端状态包含 audioLevel，语音按钮波纹随音量变化，非录音时回落并不阻挡点击；减少动画偏好下仍可操作。
4. Web 与 Agent/Auth 测试、构建、Compose 健康检查通过。
5. 完成基线、修改、差异、验证和可执行回滚材料；任务书验收后改名为 `...-已完成.md` 并提交版本。

## 回滚方案

恢复 v0.1.37 的音频处理和前端按钮逻辑；回滚脚本只操作验证副本，不覆盖工作树源码。

## 验收结果

- `audio_end` 收到非空 `final` transcript 后复用原 utterance/revision 调用 `_text`，自动创建 Agent run；空结果和 unsupported 不发起空请求。
- PCM16 采集计算 0..1 RMS 音量；检测到语音后静音 650ms 自动结束，单轮 15 秒封顶，停止、打断、断线和销毁均清理计时器与音量状态。
- 首页和实时面板麦克风按钮使用 `--voice-level` 驱动双层动态波纹；浏览器识别回退同时启用独立音量计，降低“按钮已开但没有采集”的不确定感。
- Web：实时 6/6、聊天 3/3、布局 6/6、数字人 3/3，构建通过。
- Agent：`191 passed, 2 skipped, 1 warning`；Auth：Maven 测试通过。
- Compose：Agent、Auth、MCP、Web、Redis、RabbitMQ 均 healthy；`GET http://127.0.0.1:8088/api/health` 返回 HTTP 200。
- 基线、修改、差异、验证和回滚材料位于 `tmp-docs/v0.1.38-realtime-voice-artifacts/`，回滚副本 SHA-256 与基线一致。
