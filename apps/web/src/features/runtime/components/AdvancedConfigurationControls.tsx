import { Activity, Database, FileScan, Gauge, KeyRound, LoaderCircle, Settings2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { RuntimeConfiguration, RuntimeConfigurationPatch } from '../configuration'

type DialogKind = 'llm' | 'embedding' | 'docling' | 'futureagi' | null

interface Props {
  configuration: RuntimeConfiguration | null
  canManage: boolean
  isLoading: boolean
  isSaving: boolean
  onSave: (payload: RuntimeConfigurationPatch) => Promise<RuntimeConfiguration>
}

export function AdvancedConfigurationControls({ configuration, canManage, isLoading, isSaving, onSave }: Props) {
  const [dialog, setDialog] = useState<DialogKind>(null)
  const [error, setError] = useState<string | null>(null)
  const [llmEnabled, setLlmEnabled] = useState(false)
  const [llmProvider, setLlmProvider] = useState('openai-compatible')
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmModel, setLlmModel] = useState('')
  const [llmTemperature, setLlmTemperature] = useState('0.2')
  const [llmMaxTokens, setLlmMaxTokens] = useState('1024')
  const [embeddingEnabled, setEmbeddingEnabled] = useState(true)
  const [embeddingProvider, setEmbeddingProvider] = useState('local')
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState('')
  const [embeddingApiKey, setEmbeddingApiKey] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState('BAAI/bge-small-zh-v1.5')
  const [embeddingDimensions, setEmbeddingDimensions] = useState('512')
  const [doclingEnabled, setDoclingEnabled] = useState(true)
  const [doclingArtifactsPath, setDoclingArtifactsPath] = useState('')
  const [doclingOcrBackend, setDoclingOcrBackend] = useState('onnxruntime')
  const [doclingLanguages, setDoclingLanguages] = useState('chinese')
  const [doclingOcr, setDoclingOcr] = useState(true)
  const [doclingTables, setDoclingTables] = useState(true)
  const [doclingTableMode, setDoclingTableMode] = useState('accurate')
  const [doclingConcurrency, setDoclingConcurrency] = useState('1')
  const [futureEnabled, setFutureEnabled] = useState(false)
  const [futureEndpoint, setFutureEndpoint] = useState('')
  const [futureApiKey, setFutureApiKey] = useState('')
  const [futureSecretKey, setFutureSecretKey] = useState('')
  const [futureProject, setFutureProject] = useState('digital-human')

  useEffect(() => {
    if (!configuration) return
    const llm = configuration.llm ?? {}
    setLlmEnabled(Boolean(llm.enabled)); setLlmProvider(llm.provider ?? 'openai-compatible'); setLlmBaseUrl(String(llm.baseUrl ?? '')); setLlmModel(String(llm.model ?? ''))
    setLlmTemperature(String(llm.temperature ?? 0.2)); setLlmMaxTokens(String(llm.maxTokens ?? 1024)); setLlmApiKey('')
    const embedding = configuration.embedding ?? {}
    setEmbeddingEnabled(embedding.enabled !== false); setEmbeddingProvider(embedding.provider ?? 'local'); setEmbeddingBaseUrl(String(embedding.baseUrl ?? '')); setEmbeddingModel(String(embedding.model ?? 'BAAI/bge-small-zh-v1.5')); setEmbeddingDimensions(String(embedding.dimensions ?? 512)); setEmbeddingApiKey('')
    const rag = configuration.rag ?? {}
    setDoclingEnabled(rag.enabled !== false); setDoclingArtifactsPath(String(rag.artifactsPath ?? '')); setDoclingOcrBackend(String(rag.ocrBackend ?? 'onnxruntime')); setDoclingLanguages(Array.isArray(rag.ocrLanguages) ? rag.ocrLanguages.join(',') : 'chinese'); setDoclingOcr(rag.doOcr !== false); setDoclingTables(rag.doTableStructure !== false); setDoclingTableMode(String(rag.tableMode ?? 'accurate')); setDoclingConcurrency(String(rag.maxConcurrency ?? 1))
    const future = configuration.futureagi ?? {}
    setFutureEnabled(Boolean(future.enabled)); setFutureEndpoint(String(future.endpoint ?? '')); setFutureProject(String(future.project ?? 'digital-human')); setFutureApiKey(''); setFutureSecretKey('')
  }, [configuration])

  function open(kind: Exclude<DialogKind, null>) { if (canManage) { setError(null); setDialog(kind) } }

  async function save() {
    if (!dialog) return
    try {
      let payload: RuntimeConfigurationPatch
      if (dialog === 'llm') {
        if (llmEnabled && (!llmBaseUrl.trim() || (!configuration?.llm?.configured && !llmApiKey.trim()) || !llmModel.trim())) throw new Error('启用 LLM 前必须填写 Base URL、API Key 和模型名')
        payload = { llm: { enabled: llmEnabled, provider: llmProvider.trim(), baseUrl: llmBaseUrl.trim(), ...(llmApiKey.trim() ? { apiKey: llmApiKey.trim() } : {}), model: llmModel.trim(), temperature: Number(llmTemperature), maxTokens: Number(llmMaxTokens) } }
      } else if (dialog === 'embedding') {
        const isRemoteEmbedding = ['openai', 'openai-compatible', 'compatible'].includes(embeddingProvider.trim().toLowerCase())
        if (isRemoteEmbedding && (!embeddingBaseUrl.trim() || (!configuration?.embedding?.configured && !embeddingApiKey.trim()) || !embeddingModel.trim())) throw new Error('远程 Embedding 必须填写 Base URL、API Key 和模型名')
        if (!isRemoteEmbedding && !embeddingModel.trim()) throw new Error('本地 Embedding 必须填写模型名称或本地模型目录')
        payload = { embedding: { enabled: embeddingEnabled, provider: embeddingProvider.trim(), baseUrl: embeddingBaseUrl.trim(), ...(embeddingApiKey.trim() ? { apiKey: embeddingApiKey.trim() } : {}), model: embeddingModel.trim(), dimensions: Number(embeddingDimensions) } }
      } else if (dialog === 'docling') {
        const languages = doclingLanguages.split(',').map((item) => item.trim()).filter(Boolean)
        if (!languages.length) throw new Error('至少填写一种 OCR 语言')
        payload = { docling: { enabled: doclingEnabled, artifactsPath: doclingArtifactsPath.trim(), ocrBackend: doclingOcrBackend.trim(), ocrLanguages: languages, doOcr: doclingOcr, doTableStructure: doclingTables, tableMode: doclingTableMode, maxConcurrency: Number(doclingConcurrency) } }
      } else {
        if (futureEnabled && ((!configuration?.futureagi?.configured && !futureApiKey.trim()) || (!configuration?.futureagi?.configured && !futureSecretKey.trim()))) throw new Error('启用 FutureAGI 前必须填写 API Key 和 Secret Key')
        payload = { futureagi: { enabled: futureEnabled, endpoint: futureEndpoint.trim(), ...(futureApiKey.trim() ? { apiKey: futureApiKey.trim() } : {}), ...(futureSecretKey.trim() ? { secretKey: futureSecretKey.trim() } : {}), project: futureProject.trim() } }
      }
      await onSave(payload); setDialog(null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '配置保存失败') }
  }

  return <>
    <section className="configuration-summary" aria-labelledby="advanced-config-title">
      <div className="section-heading"><div><p className="eyebrow">MODEL & OBSERVABILITY</p><h2 id="advanced-config-title">模型与可观测性</h2></div><span className="panel-count">{canManage ? '可编辑' : '只读'}</span></div>
      <div className="configuration-summary-grid">
        <ConfigCard icon={<Gauge size={17} />} title="LLM 模型" detail={configuration?.llm?.configured ? `${configuration.llm.provider} · ${configuration.llm.model}` : '使用确定性回退'} onClick={() => open('llm')} disabled={!canManage || isLoading} />
        <ConfigCard icon={<Database size={17} />} title="Embedding" detail={configuration?.embedding?.detail ?? '本地中文模型 · BGE'} onClick={() => open('embedding')} disabled={!canManage || isLoading} />
        <ConfigCard icon={<FileScan size={17} />} title="Docling 解析" detail={configuration?.rag?.localModels?.join('、') ?? '读取中'} onClick={() => open('docling')} disabled={!canManage || isLoading} />
        <ConfigCard icon={<Activity size={17} />} title="FutureAGI 遥测" detail={configuration?.futureagi?.configured ? '实时导出已启用' : '使用本地缓冲'} onClick={() => open('futureagi')} disabled={!canManage || isLoading} />
      </div>
    </section>
    {dialog && <div className="configuration-dialog-backdrop" role="presentation" onMouseDown={() => !isSaving && setDialog(null)}><section className="configuration-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
      <header className="configuration-dialog-header"><div><p className="eyebrow">CONFIGURATION</p><h2>{dialog === 'llm' ? 'LLM 模型' : dialog === 'embedding' ? 'Embedding 模型' : dialog === 'docling' ? 'Docling 文档解析' : 'FutureAGI 实时遥测'}</h2></div><button className="icon-button" type="button" onClick={() => setDialog(null)} disabled={isSaving} aria-label="关闭"><X size={16} /></button></header>
      <div className="configuration-dialog-body">
        {dialog === 'llm' && <div className="configuration-mofa-form"><Switch label="启用 LLM" checked={llmEnabled} onChange={setLlmEnabled} /><Input label="Provider" value={llmProvider} onChange={setLlmProvider} /><Input label="Base URL" value={llmBaseUrl} onChange={setLlmBaseUrl} placeholder="https://api.example.com/v1" /><Input label="API Key" value={llmApiKey} onChange={setLlmApiKey} type="password" placeholder={configuration?.llm?.configured ? '已配置，留空保持不变' : '填写 API Key'} /><Input label="模型名" value={llmModel} onChange={setLlmModel} placeholder="qwen-plus" /><div className="configuration-number-grid"><Input label="Temperature" value={llmTemperature} onChange={setLlmTemperature} type="number" /><Input label="最大输出 Token" value={llmMaxTokens} onChange={setLlmMaxTokens} type="number" /></div></div>}
        {dialog === 'embedding' && <div className="configuration-mofa-form"><Switch label="启用 Embedding" checked={embeddingEnabled} onChange={setEmbeddingEnabled} /><label className="dialog-input"><span>部署方式</span><select value={embeddingProvider} onChange={(event) => setEmbeddingProvider(event.target.value)}><option value="local">本地中文模型（BGE）</option><option value="openai-compatible">远程 OpenAI 兼容服务</option><option value="hash-local">本地特征哈希（仅兜底）</option></select></label><Input label="模型名或本地目录" value={embeddingModel} onChange={setEmbeddingModel} placeholder="BAAI/bge-small-zh-v1.5" /><Input label="Base URL" value={embeddingBaseUrl} onChange={setEmbeddingBaseUrl} placeholder="仅远程服务填写" /><Input label="API Key" value={embeddingApiKey} onChange={setEmbeddingApiKey} type="password" placeholder={configuration?.embedding?.configured ? '已配置，留空保持不变' : '仅远程服务填写'} /><Input label="向量维度" value={embeddingDimensions} onChange={setEmbeddingDimensions} type="number" /></div>}
        {dialog === 'docling' && <div className="configuration-mofa-form"><Switch label="启用 Docling" checked={doclingEnabled} onChange={setDoclingEnabled} /><Input label="本地模型目录" value={doclingArtifactsPath} onChange={setDoclingArtifactsPath} placeholder="留空使用默认缓存" /><Input label="OCR 后端" value={doclingOcrBackend} onChange={setDoclingOcrBackend} /><Input label="OCR 语言（逗号分隔）" value={doclingLanguages} onChange={setDoclingLanguages} /><Switch label="启用 OCR" checked={doclingOcr} onChange={setDoclingOcr} /><Switch label="启用表格结构识别" checked={doclingTables} onChange={setDoclingTables} /><label className="dialog-input"><span>表格模式</span><select value={doclingTableMode} onChange={(event) => setDoclingTableMode(event.target.value)}><option value="accurate">准确</option><option value="fast">快速</option></select></label><Input label="并发数" value={doclingConcurrency} onChange={setDoclingConcurrency} type="number" /></div>}
        {dialog === 'futureagi' && <div className="configuration-mofa-form"><Switch label="启用 FutureAGI" checked={futureEnabled} onChange={setFutureEnabled} /><Input label="Endpoint" value={futureEndpoint} onChange={setFutureEndpoint} placeholder="留空使用默认端点" /><Input label="API Key" value={futureApiKey} onChange={setFutureApiKey} type="password" placeholder={configuration?.futureagi?.configured ? '已配置，留空保持不变' : '填写 API Key'} /><Input label="Secret Key" value={futureSecretKey} onChange={setFutureSecretKey} type="password" placeholder={configuration?.futureagi?.configured ? '已配置，留空保持不变' : '填写 Secret Key'} /><Input label="项目名" value={futureProject} onChange={setFutureProject} /></div>}
        {error && <p className="configuration-form-error" role="alert">{error}</p>}
      </div>
      <footer className="configuration-dialog-footer"><button className="secondary-button" type="button" onClick={() => setDialog(null)} disabled={isSaving}>取消</button><button className="primary-button" type="button" onClick={() => void save()} disabled={isSaving}>{isSaving && <LoaderCircle size={15} className="spin" />}保存配置</button></footer>
    </section></div>}
  </>
}

function ConfigCard({ icon, title, detail, onClick, disabled }: { icon: ReactNode; title: string; detail: string; onClick: () => void; disabled: boolean }) { return <button className="configuration-summary-card" type="button" onClick={onClick} disabled={disabled}><span className="configuration-summary-icon">{icon}</span><span><strong>{title}</strong><small>{detail}</small></span><Settings2 size={16} aria-hidden="true" /></button> }
function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="dialog-switch"><span><strong>{label}</strong></span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /></label> }
function Input({ label, value, onChange, type = 'text', placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string }) { return <label className="dialog-input"><span>{label}</span><input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label> }
