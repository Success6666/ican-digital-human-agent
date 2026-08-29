# 运行手册

## 无 Docker 的开发方式

1. 启动 MCP：在 `apps/mcp-server` 目录执行 `$env:PYTHONPATH=(Get-Location).Path; python -m uvicorn app.main:app --host 127.0.0.1 --port 9000`。
2. 启动 Agent：在 `apps/agent-service` 目录执行 `$env:PYTHONPATH=(Get-Location).Path; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。
3. 启动认证服务：使用 Maven Wrapper 或容器构建后执行 JAR。
4. 启动前端：在 `apps/web` 执行 `npm install && npm run dev`。

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build
```

浏览器访问 `http://localhost:8088`。演示账号：`demo/demo123`。

## 健康检查

- `GET /api/health`：认证网关。
- `GET /health`：Agent 和 MCP（仅内部网络）。

## 评测与回放

登录后打开“评测中心”，可查看当前用户的质量、安全、成本和 Agent/数字人分段延迟。通过 `POST /api/evaluation/runs` 提交离线样本；Trace 回放只显示本用户事件，字段已做脱敏。若尚无运行样本，指标显示“暂无数据”，数据集仍会展示项目基线。

## FutureAGI 可观测性

在服务端环境注入 `FUTUREAGI_ENABLED=true`、`FUTUREAGI_API_KEY`、
`FUTUREAGI_SECRET_KEY` 和 `FUTUREAGI_PROJECT` 后重启 Agent。需要自定义采集地址时
设置 `FUTUREAGI_ENDPOINT`。适配器使用 `fi-instrumentation-otel` 返回的专用
TracerProvider，不修改进程全局 Provider；缺少任一凭证、依赖不可用或导出失败时，
健康状态显示“本地缓冲”，事件继续保存在有界内存中。

## 真实 Provider 开启顺序

1. 在服务端注入密钥并确认日志脱敏。
2. 先只启用一个 Provider，完成创建、首帧/文本、打断、关闭冒烟。
3. 确认 HTTPS/WSS、CSP、反向代理 Upgrade 和会话 TTL 后再扩大并发。
