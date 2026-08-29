# Docling 本地模型配置

## 默认组合

| 能力 | 本版配置 | 适用范围 | 说明 |
| --- | --- | --- | --- |
| 页面布局识别 | Layout Heron | PDF、图片、扫描件 | PDF 链路的基础模型，建议预取到本地权重目录。 |
| 表格结构识别 | TableFormer accurate | 含表格的 PDF | 优先保证表头、行列和单元格关系；对延迟敏感时可切换 `fast`。 |
| OCR | RapidOCR + ONNXRuntime（中文） | 扫描 PDF、图片 | 只在 `DOCLING_DO_OCR=true` 时加载；纯文本 PDF 可以关闭以降低延迟。 |

图片分类、图片描述/VLM、公式增强、图表增强在 v0.1 默认关闭。它们会增加模型体积、内存和首个文档的初始化时间，应在有明确数据需求和评测基线后单独开启。

## 服务端配置

```dotenv
DOCLING_ENABLED=true
DOCLING_ARTIFACTS_PATH=/models/docling
DOCLING_OCR_BACKEND=onnxruntime
DOCLING_OCR_LANG=chinese
DOCLING_DO_OCR=true
DOCLING_DO_TABLE_STRUCTURE=true
DOCLING_TABLE_MODE=accurate
RAG_MAX_DOCUMENT_BYTES=8388608
```

`DOCLING_ENABLED=false` 时，Markdown、HTML 和纯文本仍可通过文本解析回退入库；PDF/DOCX 等二进制文档会按 `RAG_STRICT_BINARY` 策略返回可读错误。解析器采用懒加载，聊天请求不会因为尚未使用 RAG 而提前下载或初始化模型。

## 预取与运行建议

1. 在构建镜像或挂载模型卷时预取所需权重，不把权重提交到 Git。
2. 生产先使用 `accurate` 建立正确性基线，再用 `fast` 做延迟对照；两种结果都写入评测运行。
3. 中文扫描件开启 OCR；文本型 PDF 关闭 OCR 可减少 CPU 占用。
4. 首次解析应单独观察内存峰值和首文档延迟，后续依靠有界文档大小、并发控制和 Trace 做容量规划。

## 与代码的边界

Docling 只负责把输入转换成带来源信息的 Markdown 文本；切分、Embedding、向量存储和用户命名空间由 `app/rag` 的其他端口负责。替换模型或向量库不需要修改 LangGraph 节点。
