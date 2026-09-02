# v0.1.49 真实 LLM 与数字人 Provider 调优任务书

日期：2026-09-02  
对象：DeepSeek OpenAI-compatible LLM、Mofa 浏览器数字人 Provider

## 原始问题

1. 流式 LLM 首 token 仍受请求体结构化约束影响，真实链路存在额外等待。
2. 数字人连接完成后前端存在额外人工等待，导致“加载完成后卡一会才显示”。
3. 需要保留真实服务测量结果，避免只用 Mock 判断性能。

## 修复方案

1. DeepSeek 请求关闭 thinking，并移除 response_format JSON grammar；客户端已有解析器可处理纯文本流，其他兼容模型继续使用 JSON 约束。
2. Mofa 初始化完成后仅等待两帧浏览器绘制，不再固定等待 600ms。
3. 保留 HTTP 连接池、RabbitMQ 拓扑复用和后台展示事件发布，避免本轮优化回退既有并发能力。

## 验收标准

- [x] DeepSeek 真实流式请求返回完整 reply，且不泄露 reasoning 内容。
- [x] LLM 客户端测试通过，数字人语音与实时链路测试通过。
- [x] 前端 TypeScript/Vite 生产构建通过。
- [x] 真实基准原始数据保存到 `tmp-docs/llm-evaluations/` 与 `tmp-docs/avatar-evaluations/`。
- [x] 变更具备 baseline、modified、diff、verification、rollback 五项资产。
- [x] 回滚脚本在测试副本上恢复 baseline，工作区保留修改后版本。

## 实测结论

优化请求在一组相同问题样本中首 token 从 667.39ms 降至 343.97ms、总耗时从 1210.08ms 降至 959.99ms；另一组样本受上游抖动影响出现反向波动，因此以链路结构优化为确定性结论，不宣称固定 SLA。运行时优化请求实测返回 222 字符完整 reply。Mofa 服务端保持 `client_pending` 语义，前端已移除 600ms 固定等待。

## 状态

已完成
