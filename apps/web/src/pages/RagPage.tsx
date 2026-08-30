import { Database, FileText, RefreshCw, X } from 'lucide-react'
import { IngestForm } from '../features/rag/components/IngestForm'
import { SearchForm } from '../features/rag/components/SearchForm'
import { RagOverview } from '../features/rag/components/RagOverview'
import { useRagWorkspace } from '../features/rag/model'
import { PageHeader } from '../shared/components/PageHeader'
import { MetricTile } from '../shared/components/MetricTile'
import { StatusPill } from '../shared/components/StatusPill'

export function RagPage() {
  const rag = useRagWorkspace()
  const doclingAvailable = rag.health?.docling_available ?? rag.health?.doclingAvailable
  const ragStatus = !rag.health ? 'pending' : rag.health.status === 'ok' ? 'online' : 'pending'
  const scrollTo = (id: string) => {
    const behavior = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
    document.getElementById(id)?.scrollIntoView({ behavior, block: 'center' })
  }
  return (
    <div className="page-stack">
      <PageHeader eyebrow="KNOWLEDGE" title="RAG 记忆与检索增强" description="用 Docling 解析文档，按集合写入并检索可复用上下文。" actions={<button className="icon-button" type="button" onClick={() => void rag.refresh()} disabled={rag.isLoading} aria-label="刷新 RAG 状态" title="刷新 RAG 状态"><RefreshCw size={16} className={rag.isLoading ? 'spin' : undefined} /></button>} />
      <div className="metric-grid metric-grid--three"><MetricTile label="知识文档" value={rag.health?.documents ?? '—'} detail={`当前用户 · ${rag.health?.chunks ?? 0} 个切片`} icon={<FileText size={15} />} tone="accent" /><MetricTile label="文档解析" value={doclingAvailable === false ? '回退' : doclingAvailable ? 'Docling' : '检查中'} detail="解析器状态" icon={<Database size={15} />} tone={doclingAvailable === false ? 'warning' : 'neutral'} /><MetricTile label="服务状态" value={<StatusPill status={ragStatus} label={ragStatus === 'online' ? '在线' : ragStatus === 'pending' ? '检查中' : '离线'} />} detail="RAG 服务" icon={<Database size={15} />} tone="neutral" /></div>
      {rag.error && <div className="page-alert" role="alert">{rag.error}<button className="icon-button" type="button" onClick={rag.clearError} aria-label="关闭错误提示" title="关闭错误提示"><X size={15} /></button></div>}
      <RagOverview health={rag.health} onIngest={() => scrollTo('ingest-title')} onFocusSearch={() => scrollTo('search-title')} />
      <div className="rag-grid"><IngestForm isBusy={rag.isBusy} result={rag.ingestResult} onSubmit={rag.ingest} /><SearchForm isBusy={rag.isBusy} hits={rag.hits} onSubmit={rag.search} /></div>
    </div>
  )
}
