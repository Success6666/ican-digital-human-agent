# 数字人 Agent v0.1.26 模型与构建缓存任务书

## 目标

让 Docling、Sentence Transformers、Torch 等依赖在 Docker 重建时复用 BuildKit pip 缓存，让 Hugging Face、Sentence Transformers 与 Docling 运行时模型使用独立持久化卷，避免容器重建或服务重启重复下载模型。

## 实施范围

1. Agent Dockerfile 启用 BuildKit pip 缓存挂载，并设置稳定的 pip 超时与重试参数。
2. Compose 增加独立的 `agent-model-cache` 卷，将模型缓存与运行配置、RAG 数据解耦。
3. 统一 `HF_HOME`、`TRANSFORMERS_CACHE`、`SENTENCE_TRANSFORMERS_HOME`、`DOCLING_ARTIFACTS_PATH` 到模型缓存目录。
4. 保留现有应用逻辑与服务接口，不在本任务中修改模型选择策略。
5. 重新构建 Agent 镜像并验证缓存目录、容器健康状态和 Compose 配置。

## 验收标准

- [x] `docker compose config --quiet` 通过。
- [x] Agent 镜像完成构建并运行。
- [x] `agent-model-cache` 卷存在并挂载到 Agent 容器模型目录。
- [x] Agent 健康检查通过。
- [x] Agent 单元测试通过：164 passed, 1 skipped。
- [x] 第二次构建命中依赖、模型相关构建缓存，模型卷跨容器重建复用。
- [x] 版本号提升到 `0.1.26` 并提交功能变更。
