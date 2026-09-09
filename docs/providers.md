# 数字人 Provider 接入说明

第一版默认使用 `mock`，真实厂商没有凭证时显示为 `disabled`，不会阻断主链路。

## 运行时边界

LangGraph 只产出 provider-neutral 的 `AgentResponse`（文本、情绪、手势、性能语义和会话标识）。`PresentationLayer` 将它转换为统一的 `send_text(..., mode="agent_response")` 调用，再交给 Fay 或厂商 Provider 适配器。Provider SDK 字段不得回流到 Agent Core；替换 Fay 或接入其他数字人运行时只需要新增或替换适配器。

响应同时携带 `runId`。适配器应把它作为发送和取消操作的幂等键：当同一会话出现新 run 时，旧 run 的在途语音、唇动和微表情应尽快停止；即使厂商回调迟到，也不得覆盖新 run 的表现状态。

## 统一生命周期

`create_session -> send_text/send_text_chunk -> interrupt -> close_session`。

Provider 返回的 `sdk_config` 只能包含短时会话参数、媒体地址和能力信息；长期 AK/SK、AppSecret、API Secret 只能留在服务端环境变量或密钥管理系统。

## 阿里云

适配器预留万相数字人云渲染 Web SDK 的会话初始化和文本驱动入口。服务端负责申请短时 RTC 参数，前端只负责加载 SDK 和渲染。开启前配置 `ALIYUN_AVATAR_*`。

## 魔珐星云

适配器通过官方 XmovAvatar Web SDK 建立 TTSA 会话，支持连续文本、官方 70 个全局动作意图的严格发送、5 个官方情感值、打断、隐藏渲染和销毁；每个角色实际可执行的动作意图数量以星云资源为准。会话参数只经认证后的 Provider 会话接口下发；生产入口必须使用 HTTPS，并限制会话接口访问。开启前配置 `MOFA_APP_ID`、`MOFA_APP_SECRET`，角色已开通多情感能力时再设置 `MOFA_EMOTION_ENABLED=true`。会话上下文由官方 SDK 根据会话响应自动处理，业务层不拼接未在构造/API 文档中声明的查询字段。运行时开启官方 `enableLogger`，并对浏览器 Console 诊断做脱敏；`enableDebugger` 保持关闭，避免调试回放下载入口和额外资源缓存。

## 讯飞

适配器预留 VMS Web SDK 2.0 的文本驱动、流式发送、暂停和停止入口。跨域场景需要由网关代理厂商路径，开启前配置 `IFLYTEK_*`。

## Fay

Fay 作为外部驱动层接入，不在本项目内启动第二套 Agent。配置 `FAY_BASE_URL` 后由适配器发送标准文本/控制指令。正式商用前需审查 Fay 的 GPL-3.0 许可证边界。
