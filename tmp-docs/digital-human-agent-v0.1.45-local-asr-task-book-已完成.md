# 数字人 Agent v0.1.45 本地中文流式 ASR 部署任务书

状态：已完成
版本：v0.1.45
日期：2026-09-02

## 原始需求

将实时语音识别部署在本机，优先使用 GPU 推理提升速度，同时保留无 GPU 环境下的 CPU 运行能力。识别范围限定为中文，并接入当前实时 PCM16 WebSocket 链路。

## 实施方案

1. 使用可本地运行的中文流式 ASR 模型服务，模型和运行缓存持久化到 Docker volume。
2. 通过配置选择 `cuda` 或 `cpu`，GPU 不可用时自动降级 CPU。
3. Agent 保持现有实时协议，ASR 服务负责 PCM16 utterance 的 final transcript，不接触账号凭证和业务会话。
4. 保留现有远端 HTTP ASR 配置作为备用路径，ASR 服务不可用时返回结构化降级状态。

## 验收标准

- [x] 本地 ASR 服务健康检查通过。
- [x] CPU 模式可启动并返回结构化中文识别结果；静音输入返回空文本。
- [x] GPU 模式会优先尝试 CUDA；当前镜像缺少 `libcublas.so.12` 时已在首次推理阶段自动回退 CPU，链路保持可用。
- [x] 实时 WebSocket 的现有 PCM16 `audio_start`/二进制帧/`audio_end` 链路已接入本地 final transcript 适配器。
- [x] Agent、ASR 容器健康，模型缓存可复用。
- [x] 相关测试、生产构建、版本提交和运行手册完成。
