# Digital Human Agent v0.1.29 数字人 SDK 链路修复任务书

## 状态

已完成

## 原始问题

- 数字人画面已能连接，但 Agent 最终回答未稳定触发数字人语音、口型与表情播报。
- 星云 SDK 的 SSML、情绪、动作与客户端打断协议尚未完整映射。
- RabbitMQ 发布链路需要核验持久化、发布确认、故障落盘及死信拓扑。

## 修复范围

1. 对照星云官方 Web SDK 文档校正初始化、播报、情绪、动作和打断调用。
2. 将供应商无关的 `AvatarPerformanceCue` 转换为星云 SSML 与 `extra.emotion`。
3. 保证最终 `AgentResponse` 经过 PresentationLayer、消息总线和浏览器数字人 Runtime。
4. 完善 RabbitMQ 持久化发布、确认、死信交换机和死信队列声明。
5. 增加单元测试，并执行前端构建、后端测试和容器内 RabbitMQ 拓扑验证。

## 验收标准

- [x] `speak()` 收到合法 `<speak>...</speak>` SSML，且文本进行 XML 转义。
- [x] 支持的情绪映射到 `extra.emotion`，动作映射到 `<ue4event>`。
- [x] 用户打断调用 `interrupt('user_speaking')`，SDK 初始化启用客户端打断。
- [x] Agent 最终回答只播报一次，失败时保留可重试状态并展示可读错误。
- [x] RabbitMQ 主交换机、主队列、死信交换机、死信队列均为 durable，消息为 persistent，并启用 publisher confirms。
- [x] 后端测试、前端测试与构建通过；容器内真实发布后可查询到预期拓扑与消息。

## 验证结果

- 后端：`171 passed, 1 skipped`。
- 前端：数字人、聊天、实时音频和布局契约测试全部通过，生产构建通过。
- 外部 Edge：Canvas 渲染成功，Agent 返回目标文本，星云 WebSocket 捕获 2 个播报发送帧，播报后收到 88 个音频/驱动帧。
- RabbitMQ：主消息发布后未增加 outbox；拒绝测试消息后从主队列转入死信队列。
