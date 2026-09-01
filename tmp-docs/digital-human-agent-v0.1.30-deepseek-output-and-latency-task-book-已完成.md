# Digital Human Agent v0.1.30 DeepSeek 输出与延迟修复任务书

## 状态

已完成（2026-09-01）

## 原始问题

1. DeepSeek 返回结构化 JSON 时，`presentation.lipSync` 可能返回 `"speaking"` 等非布尔值，当前解析器会让整个结构校验失败，并把原始 JSON 当作普通回复展示和播报。
2. 当前 `deepseek-v4-flash` 请求未显式关闭思考模式，简单问句的完整 Agent 执行耗时达到 13.73 秒。
3. LLM 客户端每次请求都新建 HTTP 客户端，无法复用连接。
4. “你是谁”“能做什么”等稳定身份问句仍进入 MCP 与 LLM 链路，产生无意义延迟。

## 基线证据

- 运行配置：`baseUrl=https://api.deepseek.com/v1`，`model=deepseek-v4-flash`，`maxTokens=1024`。
- Trace `2cb7990cca9e49b2a589d0461a71157c`：Agent 13727.27 ms，MCP 约 50 ms，数字人 16.76 ms。
- 用户可见结果包含原始 `reply/presentation` JSON，数字人也收到同一段错误文本。

## 修复方案

1. 为 DeepSeek V4 请求显式发送非思考模式参数，并保留不支持参数时的兼容回退。
2. 复用带 keep-alive 的异步 HTTP 客户端，在重配置和应用关闭时正确释放连接。
3. 独立解析 `reply` 与 `presentation`：优先保留有效回复，对表情、动作、布尔值和数值做受控归一化，异常字段回退为安全播报动作。
4. 支持代码围栏、前后说明文本、双重编码 JSON 和截断但已完成 `reply` 字段的输出。
5. 增加身份与能力类快速响应，并阻止这类请求调用 MCP。
6. 增加单元、集成和真实 DeepSeek 链路验证，记录首次有效回复与完整 Agent 延迟。

## 验收标准

1. 截图中的 DeepSeek JSON 样例只展示并播报 `reply` 文本，不出现原始 JSON。
2. `lipSync: "speaking"` 被归一化为可用布尔值，微表情与动作仍进入数字人表现层。
3. DeepSeek V4 请求默认关闭思考模式；其他 OpenAI 兼容服务遇到不支持参数时可自动兼容。
4. “你是谁”“你能做什么”真实 Agent 完整耗时均低于 3000 ms。
5. 普通 DeepSeek 请求首次有效文本低于 3000 ms；完整耗时如受上游输出长度影响，必须在 trace 中独立保留真实数值。
6. Agent 服务测试、前端测试与构建通过，Docker 服务健康，真实数字人链路能展示、播报清洗后的回复。

## 验收结果

1. DeepSeek 结构化响应按字段解析，`reply` 仅作为用户可见文本，`presentation` 独立进入微表情、动作和口型层。
2. 非布尔 `lipSync`、异常表现字段、代码围栏、说明前缀、双重编码和截断尾部均有回归覆盖。
3. 请求显式启用 JSON 输出并关闭 DeepSeek 思考模式；不兼容网关自动去除可选参数重试。
4. 身份类真实链路首段 43.87 ms、完整 96.82 ms、Agent 32.84 ms。
5. 普通问题在约 20 ms 内返回 listening/thinking/filler 并进入数字人播报；接入 Docker 主机代理并预热连接后，真实首 token 1712.55 ms、Agent 2354.84 ms、端到端 2386.90 ms，收到 token 后立即分段排队播报。
6. Agent 测试 177 passed、1 skipped；前端构建与 11 个契约测试通过；Docker 五个服务健康。

详细命令、输入、输出、哈希及回滚验证见 `tmp-docs/v0.1.30-artifacts/VERIFICATION.txt`。

## 回滚方案

通过本次提交的父提交恢复 LLM 请求参数、解析器、快速路由及版本号；运行 `tmp-docs/v0.1.30-artifacts/ROLLBACK.sh` 可在验证副本中复现回滚结果。
