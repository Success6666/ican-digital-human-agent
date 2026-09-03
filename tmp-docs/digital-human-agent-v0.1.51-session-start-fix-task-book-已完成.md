# v0.1.51 会话启动链路修复任务书

## 原始问题

浏览器启动数字人会话时反复出现 `Fetch API cannot load wss://... URL scheme "wss" is not supported`，同时认证接口可能返回 `401`，导致会话无法建立。

## 修复方案

1. 按魔珐 SDK 2.1.3 的真实调用链，将 `gatewayServer` 固定为可被 `fetch` 调用的 `http/https` 会话地址。
2. 对历史配置中的 `ws/wss` 地址做兼容转换，避免旧配置继续触发浏览器协议错误。
3. 增加前后端回归测试，验证默认网关、协议归一化和会话参数。
4. 通过认证登录、当前用户和会话创建接口做真实链路冒烟，重建容器并检查健康状态。

## 验收标准

- [x] 前端源码不再把 `gatewayServer` 转成 `ws/wss` 后传给 SDK。
- [x] Agent 返回的默认 `gatewayServer` 为 `https://.../ttsa/session`。
- [x] 无认证请求仍明确返回 401，登录后 `/api/auth/me` 返回 200。
- [x] 登录态下可创建 Mock 与 Mofa 会话并返回会话 ID。
- [x] Agent、Web、Auth 测试通过，容器健康检查通过。
- [x] 原始文件哈希、差异、回滚脚本和验证结果已保存。

## 实际验收结果（2026-09-03）

- Agent：`207 passed, 2 skipped`。
- Web：魔珐链路 `8 passed`，生产构建成功。
- Auth：`31 passed, 0 failures`。
- 未登录 `/api/auth/me`：`401`；登录 `demo/demo123` 后 `/api/auth/me`：`200`。
- 登录态创建 `mofa` 会话：`200`，返回 `gatewayServer=https://nebula-agent.xingyun3d.com/user/v1/ttsa/session`。
- 容器重建后 Agent、Auth、Web 及依赖服务均为 healthy。
