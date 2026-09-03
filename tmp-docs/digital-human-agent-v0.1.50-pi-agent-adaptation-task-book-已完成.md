# v0.1.50 Pi Agent 设计适配任务书

日期：2026-09-03  
对象：Python Agent 服务、React Web 控制台、工具循环与人工确认链路

## 目标

参考 pi-agent-core 的事件流、工具循环、steering message、状态管理和前端事件消费模式，将可迁移的架构思想适配到现有 Python + React 项目；不直接搬运 TypeScript 实现，不改变现有认证、租户隔离、RAG、Mofa Provider 合同。

## 实施范围

1. 梳理 Pi 的 React 消息事件与状态消费模式，映射到现有 SSE 事件模型。
2. 梳理 Pi 的 loop engine：LLM 流式响应、工具调用、工具结果回填、继续循环、取消和 steering message。
3. 梳理工具注册、参数校验、超时、结果截断和错误转化边界，适配 Python MCP 工具执行器。
4. 增加 HITL 暂停/批准/拒绝/超时状态机，复用现有会话和实时事件通道。

## 验收标准

- [x] 参考仓库、许可证和适配边界有记录。
- [x] Python loop engine 支持有界并发工具执行、取消检查、steering/follow-up 队列和事件序列。
- [x] React 能展示工具执行状态和 HITL 待确认状态，不阻塞数字人流式播报。
- [x] 工具参数校验、超时、错误和租户上下文保持隔离；审批作用域绑定会话。
- [x] 现有 Agent 全量测试、Web 实时/语音测试和生产构建通过。
- [x] 认证网关 Maven 测试通过，审批代理已随容器重新部署。
- [x] 真实链路基准和回滚材料保存到 `tmp-docs/v0.1.50-pi-agent-artifacts/`。
- [x] TTSA 网关统一规范为 `ws/wss`，重连时保留已播报消息游标，避免重复播报。

## 状态

已完成（2026-09-03）
