# Digital Human Agent v0.1.37 页面缓存与数字人连接保持任务书

## 状态

已完成（2026-09-02）

## 原始问题

当前 `AuthenticatedApp` 依据当前页面条件渲染内容。离开首页时，`HomePage`、数字人渲染容器和实时运行时一起卸载；星云 SDK 被销毁，用户切回首页后会重新加载资源、重新建连，打断正在进行的数字人体验。

## 目标

1. 页面切换时保持数字人会话、星云 SDK 容器和实时连接实例不卸载。
2. 离开首页后隐藏数字人画面，并按星云 SDK 的隐身 API 暂停渲染/推送，降低后台 CPU、GPU 和带宽占用。
3. 返回首页时恢复画面与推送，不重复创建会话、不重复加载外部 SDK。
4. 保持用户主动断开、退出登录、会话替换时的完整清理语义。

## 验收标准

1. 页面从首页切换到评测、RAG、审计、设置再返回时，`AvatarRuntimeSurface` 不卸载，`sessionId` 不变，SDK `destroy()` 不被调用。
2. 首页隐藏期间调用一次 `switchInvisibleMode()` 和 `changeAvatarVisible(false)`；返回时按相反顺序恢复，重复切换不产生额外开关调用。
3. 用户主动断开或退出登录仍调用后端关闭会话并销毁 SDK/实时资源。
4. 外部 SDK 脚本继续使用进程内 pending cache，页面切换不重复插入脚本标签。
5. Web 构建、聊天/实时/布局/数字人测试，Agent/Auth 回归和 Compose 健康检查通过。
6. 生成基线、修改、差异、验证、可执行回滚 artifacts；任务书完成后重命名为 `...-已完成.md` 并提交 v0.1.37。

## 回滚方案

恢复 v0.1.36 的条件渲染和页面卸载逻辑；回滚脚本只操作验证副本，不覆盖工作树源码。

## 验收结果

- `AuthenticatedApp` 始终挂载首页工作区，路由切换只改变缓存层可见性；`AvatarRuntimeSurface` 的卸载边界仍只由会话替换、显式断开和退出登录触发。
- `MofaBrowserRuntime.setVisibility()` 对同一目标状态去重；隐藏调用 `changeAvatarVisible(false)` + `switchInvisibleMode()`，恢复调用 `changeAvatarVisible(true)` + `switchInvisibleMode()`，首次可见连接不会误切换。
- SDK 脚本继续使用模块级 pending cache；切页不重复创建脚本、会话或 SDK 实例。
- Web：构建通过；聊天 3/3、实时 5/5、布局 6/6、数字人 3/3。
- Agent：`190 passed, 2 skipped, 1 warning`；Auth：Maven 测试通过。
- Compose：四个应用容器、Redis、RabbitMQ 均 healthy；`GET http://127.0.0.1:8088/api/health` 返回 HTTP 200。
- 基线、修改、差异、验证和可执行回滚材料位于 `tmp-docs/v0.1.37-page-cache-artifacts/`；回滚副本恢复后 SHA-256 与基线一致。
