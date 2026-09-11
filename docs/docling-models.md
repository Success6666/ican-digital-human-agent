# Docling 本地模型配置

## 默认组合

| 能力 | 本版配置 | 适用范围 | 说明 |
| --- | --- | --- | --- |
| 页面布局识别 | Layout Heron | PDF、图片、扫描件 | PDF 链路的基础模型，建议预取到本地权重目录。 |
| 表格结构识别 | TableFormer accurate | 含表格的 PDF | 优先保证表头、行列和单元格关系；对延迟敏感时可切换 `fast`。 |
| OCR | RapidOCR + ONNXRuntime（中文） | 扫描 PDF、图片 | 只在 `DOCLING_DO_OCR=true` 时加载；纯文本 PDF 可以关闭以降低延迟。 |

> **ONNXRuntime 是必装依赖。** `rapidocr` 只带 ONNX 权重（PP-OCRv6），推理运行时由 `onnxruntime` 提供，而 Docling 把它当可选 extra。缺了它时 `DocumentConverter` 仍能构造成功、健康检查仍是绿的，只有真正 `convert()` 才会在 OCR 阶段抛 `ImportError`。容器镜像通过 `requirements-container.txt` 固定了 `onnxruntime>=1.18,<2.0`，本地开发需要单独 `pip install onnxruntime`。
>
> **opencv 的系统库同样必须装。** `rapidocr` 依赖完整的 `opencv-python`（不是 headless 版），它链接 X11/GL。在 `python:3.12-slim` 上 `import cv2` 会失败于 `libxcb.so.1: cannot open shared object file`，而 Docling 把这条 ImportError 一律改写成 "RapidOCR is not installed"，非常误导。Dockerfile 里已装 `libgl1 libglib2.0-0 libxcb1`。
>
> 这两类问题现在都能提前看到：`/rag/health` 会返回 `docling_ocr_ready` / `docling_ocr_error`，RAG 页面也会显示。

图片分类、图片描述/VLM、公式增强、图表增强在 v0.1 默认关闭。它们会增加模型体积、内存和首个文档的初始化时间，应在有明确数据需求和评测基线后单独开启。

## 服务端配置

```dotenv
DOCLING_ENABLED=true
DOCLING_OCR_BACKEND=onnxruntime
DOCLING_OCR_LANG=chinese
DOCLING_DO_OCR=true
DOCLING_DO_TABLE_STRUCTURE=true
DOCLING_TABLE_MODE=accurate
RAG_MAX_DOCUMENT_BYTES=8388608
```

### 不要设置 `DOCLING_ARTIFACTS_PATH`

一旦设置，Docling 2.1xx 就把该目录当成**完整的离线预取仓库**，并且**不再回退到 Hugging Face 缓存**：
layout、tableformer、RapidOCR 三套权重都必须躺在它下面。目录只要缺一样，每个 PDF 都会
`FileNotFoundError`，而不是去下载。

不设置时，实际解析路径是：

- Layout Heron / TableFormer → `HF_HOME`（容器内 `/app/model-cache/huggingface`，在
  `agent-model-cache` 卷里，重建容器不会丢）
- RapidOCR PP-OCRv6 → 直接用 `rapidocr` wheel 自带的 `site-packages/rapidocr/models/*.onnx`，无需下载

所以容器部署**保持该变量为空**即可。只有在确有离线预取需求时，才把它指向一个已经用
`docling-tools models download-hf-repo` 和 `docling-tools models download rapidocr`
完整填充过的目录。

`DOCLING_ENABLED=false` 时，Markdown、HTML 和纯文本仍可通过文本解析回退入库；PDF/DOCX 等二进制文档会按 `RAG_STRICT_BINARY` 策略返回可读错误。解析器采用懒加载，聊天请求不会因为尚未使用 RAG 而提前下载或初始化模型。

## 预取与运行建议

1. 不把权重提交到 Git；容器部署依赖 `agent-model-cache` 卷（HF 缓存）而非构建期预取。
2. 生产先使用 `accurate` 建立正确性基线，再用 `fast` 做延迟对照；两种结果都写入评测运行。
3. 中文扫描件开启 OCR；文本型 PDF 关闭 OCR 可减少 CPU 占用。
4. 首次解析应单独观察内存峰值和首文档延迟，后续依靠有界文档大小、并发控制和 Trace 做容量规划。

## 与代码的边界

Docling 只负责把输入转换成带来源信息的 Markdown 文本；切分、Embedding、向量存储和用户命名空间由 `app/rag` 的其他端口负责。替换模型或向量库不需要修改 LangGraph 节点。
