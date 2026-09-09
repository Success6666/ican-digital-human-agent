# 数字人 Agent v0.1.53 魔珐 SDK 调试日志与本机 Docker 部署任务书

日期：2026-09-09
状态：已完成

## 原始问题

本机控制台的魔珐数字人连接失败时，页面只能显示简短错误，浏览器 Console 未开启官方 SDK 调试日志，难以定位 TTSA 会话和网络问题；源码更新后还需要确认本机 Docker Web 服务实际运行最新构建。

## 修复方案

1. 按当前加载的官方 XmovAvatar SDK 能力开启 `enableLogger: true`，保持 `enableDebugger: false`。
2. 记录初始化、会话消息、播报状态、语音状态、动作状态、网络信息、渲染状态和失败路径。
3. 对诊断对象、URL、Authorization、Secret、Token、Password、Cookie 和 API Key 做脱敏与长度限制。
4. 仅保留官方构造与播报 API 中可验证的字段；移除未在官方文档中声明的会话查询字段。
5. 用 `docker compose build agent-service web` 与 `docker compose up -d --no-deps --force-recreate agent-service web` 重建本机服务，并检查健康状态、会话接口和容器内静态产物。

## 验收标准

- 官方 SDK 的 `enableLogger` 在生产 Web 构建中为真，`enableDebugger` 为假。
- 运行时日志覆盖关键初始化、网络、会话、播报和失败分支，且不输出凭证。
- Agent 全量测试、Avatar 测试和 Web 构建通过。
- Docker Compose 配置有效，`web`、`agent-service` 及其依赖均健康，`/healthz` 返回 `ok`。
- 运行中 Web 容器的静态 JavaScript 包含 `enableLogger:!0` 与 `enableDebugger:!1`。
- 首页建立会话时使用前端已选中的可用 Provider，不能意外回退到服务端默认 Mock Provider。

## 完成内容

- 已按官方 `speak(ssml, is_start?, is_end?, extra?) : void` 调整流式播报：最后一段由 `is_end=true` 关闭流，并由 `onSpeakStateChange` 驱动结束处理。
- 已开启 `enableLogger`，保留 `enableDebugger=false`，诊断日志覆盖初始化、会话、播报、网络、渲染和失败路径。
- 已扩展敏感信息脱敏范围，覆盖凭证、签名和会话标识；未在官方文档中声明的会话查询字段已从接口、配置和部署清单移除。
- 首页建会话未显式指定 Provider 时，会使用当前已选 Provider，避免服务端默认 Mock Provider 覆盖魔珐 Runtime 选择。

## 新增回归问题

截图中的“当前会话未提供可视化数字人 Runtime”来自首页建会话时忽略前端已选中的魔珐 Provider，导致后端按默认 Provider 创建 Mock 会话。Mock 会话不提供浏览器数字人运行时参数，前端因此拒绝挂载 SDK。

修复方式：会话模型在调用方未指定 Provider 时使用 `selectedProvider`，并以现有前端链路测试验证请求会显式携带该选择。

## 验收记录

- `PYTHONPATH=app python -m pytest -q`：214 passed、2 skipped、1 warning。
- `npm run test:avatar`：10 passed；`npm run test:chat`：6 passed；`npm run build` 成功。
- `docker compose config --quiet` 通过；`agent-service` 与 `web` 镜像已重新构建并替换运行容器。
- `web`、`agent-service`、`auth-service` 及依赖容器均处于 healthy；`http://127.0.0.1:8088/healthz` 返回 `ok`。
- 运行中 Web 静态产物包含 `enableLogger:!0` 与 `enableDebugger:!1`；认证会话显式创建 `mofa` Provider 时返回 `runtime=mofa-web-sdk` 及 SDK 必需参数。
- 浏览器端已验证数字人 Runtime 正常挂载，控制台输出官方 SDK 日志和经脱敏的运行时诊断。

## 范围说明

- 本地 `.env`、运行卷、模型缓存与第三方原始脚本不纳入版本库。
