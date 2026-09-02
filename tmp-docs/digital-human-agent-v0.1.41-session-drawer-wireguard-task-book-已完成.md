# Digital Human Agent v0.1.41 会话记录与公网映射任务书

## 状态

已完成（2026-09-02）

## 原始问题

1. 数字人持续回复时打开会话记录，页面出现卡死或无法继续交互。
2. 当前延迟已足够低，不再需要预设“我先理解一下你的意思”这类首响 filler。
3. 需要通过 WireGuard 将本机项目映射到云服务器 `39.97.253.99:6666`，并验证公网访问。

## 实现结果

1. 会话记录抽屉使用 `useDeferredValue` 消化流式消息更新，稳定消息组件使用 `memo`，列表启用 `contain: content` 和 `content-visibility: auto`，避免数字人回复期间整段历史同步重绘阻塞主线程。
2. Agent UNKNOWN 首响 filler 改为空文本且不发送事件，移除“我先理解一下你的意思”预设句；真实回复文本仍按原链路流式播报。
3. Compose Web 服务同时保留 `127.0.0.1:8088` 和 WireGuard `10.66.66.2:8088` 监听；云服务器 Nginx 通过 `/www/server/panel/vhost/nginx/ican-digital-human-6666.conf` 监听 `6666`，代理 HTTP、SSE 和 WebSocket 到本机 WireGuard 地址。

## 验收记录

- Web：`test:layout`（7/7）、`test:chat`（3/3）、`test:realtime`（8/8）、`test:avatar`（4/4）、`npm run build`（通过）。
- Agent：`python -m pytest -q`（192 passed, 2 skipped, 1 warning）。
- Compose：Agent、Auth、MCP、RabbitMQ、Redis、Web 均为 `healthy`。
- WireGuard：云端访问 `http://10.66.66.2:8088/healthz` 返回 200；云端 `http://127.0.0.1:6666/healthz` 返回 200；云端访问 `http://39.97.253.99:6666/healthz` 返回 200；本机访问公网地址同样返回 200。
- Nginx：`nginx -t -c /www/server/nginx/conf/nginx.conf` 成功，`0.0.0.0:6666` 和 `[::]:6666` 已监听。

## 验收标准

1. 回复流持续产生增量时打开、关闭会话记录不会阻塞主线程、不会重复建立连接、不会中断当前回复。
2. Agent 不再发送默认 UNKNOWN filler；前端和数字人链路不再展示该句。
3. 本地服务只通过 WireGuard 隧道暴露到云端 6666，云端端口可访问本项目健康接口和页面。
4. 前后端相关测试、生产构建、Compose 健康检查和公网访问检查全部完成。
5. 生成基线、修改、差异、验证和回滚材料；版本升级到 v0.1.41 并提交。

## 回滚方案

恢复 v0.1.40 的会话记录渲染与 filler 策略；撤销 WireGuard 转发规则和云端 6666 监听，不覆盖原始源码备份。
