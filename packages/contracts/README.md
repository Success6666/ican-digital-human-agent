# 跨服务契约

`types.ts` 对齐 Agent 服务的 camelCase JSON 响应：

- `ProviderDescriptor` 对应 `GET /internal/providers` 的 `ProviderResponse`，主标识使用 `provider`，状态与 `detail` 原样保留；`name`、`displayName`、`label` 等字段仅作为旧版前端展示兼容别名。
- `AvatarSession` 对应 `POST /internal/sessions` 的 `SessionResponse`，包含 `userId`、`createdAt`、`expiresAt`、`status` 和 `clientParams`。旧 SDK 配置字段通过可选 `sdkConfig` 兼容，不应在新接口中继续写入。
- `ProviderName` 保留已内置的五个 Provider，同时允许新增适配器标识，避免每接入一家供应商就修改公共类型。

浏览器侧可以将 `capabilities` 转换为可读标签；跨服务传输保留布尔能力键，避免把内部 SDK 配置或密钥暴露到 UI。
