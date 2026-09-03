# Pi Agent 适配记录

日期：2026-09-03

## 参考来源

- 本地参考副本：`tmp-docs/pi-agent-reference/`
- 参考提交：`4e69b0c28060f0f02fbe38bfa7c21a2e2eb25057`
- 许可证：MIT（版权声明 Mario Zechner，2025）

## 迁移映射

| Pi Agent 设计 | 本项目适配 |
| --- | --- |
| `packages/agent/src/agent-loop.ts` 的 outer follow-up / inner tool loop | `apps/agent-service/app/agent/loop_engine.py` 的批次工具循环 |
| `getSteeringMessages`、`getFollowUpMessages` | `MessageQueue`，分别提供 steering 单条消费和 follow-up 全量消费 |
| `tool_execution_start/update/end` 生命周期 | `LoopEvent` 经 LangGraph stream writer 映射为 SSE 事件 |
| `beforeToolCall` 阻断语义 | `ToolSpec.requires_confirmation` + `ApprovalStore` HITL 审批门 |
| React 事件订阅与状态隔离 | 现有 `streamEventPresenter`/timeline reducer，新增工具执行和待确认事件 |

## 边界

保留现有 Python、LangGraph、MCP、租户上下文和认证边界；Pi 的 TypeScript 运行时未直接复制。工具执行仍由现有 `ToolClient` 承担，loop engine 只负责顺序、并发上限、生命周期事件和审批状态。
