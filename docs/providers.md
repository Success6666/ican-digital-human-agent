# 数字人 Provider 接入说明

第一版默认使用 `mock`，真实厂商没有凭证时显示为 `disabled`，不会阻断主链路。

## 统一生命周期

`create_session -> send_text/send_text_chunk -> interrupt -> close_session`。

Provider 返回的 `sdk_config` 只能包含短时会话参数、媒体地址和能力信息；长期 AK/SK、AppSecret、API Secret 只能留在服务端环境变量或密钥管理系统。

## 阿里云

适配器预留万相数字人云渲染 Web SDK 的会话初始化和文本驱动入口。服务端负责申请短时 RTC 参数，前端只负责加载 SDK 和渲染。开启前配置 `ALIYUN_AVATAR_*`。

## 魔珐星云

适配器预留 XmovAvatar 的 session/gateway、流式文本、打断和销毁入口。生产必须通过 HTTPS/WSS 或受控网关，不能把长期 `appSecret` 下发浏览器。开启前配置 `MOFA_*`。

## 讯飞

适配器预留 VMS Web SDK 2.0 的文本驱动、流式发送、暂停和停止入口。跨域场景需要由网关代理厂商路径，开启前配置 `IFLYTEK_*`。

## Fay

Fay 作为外部驱动层接入，不在本项目内启动第二套 Agent。配置 `FAY_BASE_URL` 后由适配器发送标准文本/控制指令。正式商用前需审查 Fay 的 GPL-3.0 许可证边界。
