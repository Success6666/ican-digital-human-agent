# 数字人 Agent v0.1.12 默认运行时选择任务书

## 目标

确保首页新建会话时优先使用服务端声明的默认且健康 Provider；只有无可用真实 Provider 时才回退到 Mock，且用户手动选择后刷新状态不会覆盖选择。

## 验收标准

- [x] Provider 接口返回默认 Provider 标识。
- [x] 前端首次加载选择默认且健康 Provider。
- [x] 没有真实 Provider 时回退 Mock。
- [x] 用户手动选择后刷新 Provider 不覆盖选择。
- [x] Web 构建和实时测试通过。

## 状态

已完成（2026-08-31）。
