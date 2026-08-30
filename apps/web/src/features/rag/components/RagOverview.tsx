import { FileText, FolderOpen, Layers3, Plus, Search, TrendingUp } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { RagHealth } from '../types'

interface RagOverviewProps {
  health: RagHealth | null
  onIngest: () => void
  onFocusSearch: () => void
}

export function RagOverview({ health, onIngest, onFocusSearch }: RagOverviewProps) {
  const [activeTab, setActiveTab] = useState<'collections' | 'documents' | 'search'>('collections')
  const documents = health?.documents
  const parserReady = health?.docling_available ?? health?.doclingAvailable
  const selectTab = (tab: 'collections' | 'documents' | 'search') => {
    setActiveTab(tab)
    if (tab === 'documents') onIngest()
    if (tab === 'search') onFocusSearch()
  }
  return (
    <section className="rag-overview" aria-labelledby="rag-overview-title">
      <div className="rag-tabs" role="tablist" aria-label="RAG 工作区视图">
        <button className={'rag-tab' + (activeTab === 'collections' ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={activeTab === 'collections'} onClick={() => selectTab('collections')}><FolderOpen size={14} />知识库管理</button>
        <button className={'rag-tab' + (activeTab === 'documents' ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={activeTab === 'documents'} onClick={() => selectTab('documents')}><FileText size={14} />文档管理</button>
        <button className={'rag-tab' + (activeTab === 'search' ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={activeTab === 'search'} onClick={() => selectTab('search')}><Search size={14} />检索测试</button>
        <button className="rag-overview-action" type="button" onClick={onIngest}><Plus size={14} />新建知识库</button>
      </div>
      <div className="rag-overview-grid">
        <section className="rag-collections" aria-labelledby="rag-overview-title">
          <div className="panel-heading-row"><div><p className="panel-kicker">COLLECTIONS</p><h2 id="rag-overview-title">知识库管理</h2></div><span className="panel-muted">{documents === undefined ? '等待同步' : String(documents) + ' 个文档'}</span></div>
          <div className="collection-list">
            <CollectionRow icon={<Layers3 size={17} />} tone="blue" name="默认知识库" detail="通用对话与运行手册" docs={documents} active />
            <CollectionRow icon={<FileText size={17} />} tone="green" name="项目文档" detail="接口、架构与交付资料" docs={undefined} />
            <CollectionRow icon={<FolderOpen size={17} />} tone="violet" name="待接入集合" detail="新增文档后自动创建" docs={undefined} />
          </div>
          <button className="collection-add" type="button" onClick={onIngest}><Plus size={15} />新建知识库</button>
        </section>
        <section className="rag-trend" aria-labelledby="rag-trend-title">
          <div className="panel-heading-row"><div><p className="panel-kicker">ACTIVITY</p><h2 id="rag-trend-title">切片趋势 <small>近 7 天</small></h2></div><TrendingUp size={16} /></div>
          <div className="rag-chart" role="img" aria-label="近七天文档切片趋势，当前暂无数据">
            <div className="rag-chart-area">
              <div className="rag-chart-gridlines"><i /><i /><i /><i /></div>
              <svg viewBox="0 0 420 150" preserveAspectRatio="none" aria-hidden="true"><path d="M0 149H420" fill="none" stroke="var(--line-strong)" strokeDasharray="4 6" strokeWidth="1.5" /></svg>
              <div className="rag-chart-empty">接入数据后更新趋势</div>
            </div>
          </div>
          <p className="chart-note"><span className={'health-dot' + (parserReady === false ? ' health-dot--warning' : '')} />{parserReady === false ? '当前使用文本回退解析' : 'Docling 解析状态将随入库任务更新'}</p>
        </section>
      </div>
    </section>
  )
}

function CollectionRow({ icon, tone, name, detail, docs, chunks, active = false }: { icon: ReactNode; tone: string; name: string; detail: string; docs?: number; chunks?: number; active?: boolean }) {
  return (
    <article className={'collection-row' + (active ? ' collection-row--active' : '')}>
      <span className={'collection-icon collection-icon--' + tone}>{icon}</span>
      <div className="collection-copy"><strong>{name}</strong><small>{detail}</small></div>
      <div className="collection-count"><span>文档</span><strong>{docs === undefined ? '—' : docs}</strong></div>
      <div className="collection-count"><span>切片</span><strong>{chunks === undefined ? '—' : chunks}</strong></div>
      <span className={'collection-switch' + (active ? ' collection-switch--on' : '')} aria-label={active ? '已启用' : '未启用'}><i /></span>
    </article>
  )
}
