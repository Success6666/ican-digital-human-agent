import { FileText, FolderOpen, Layers3, Plus, Search, TrendingUp } from 'lucide-react'
import { type ReactNode } from 'react'
import type { RagCollectionStatistics, RagHealth } from '../types'

interface RagOverviewProps {
  health: RagHealth | null
  activeTab: 'collections' | 'documents' | 'search'
  onTabChange: (tab: 'collections' | 'documents' | 'search') => void
  onIngest: () => void
  onFocusSearch: () => void
}

export function RagOverview({ health, activeTab, onTabChange, onIngest, onFocusSearch }: RagOverviewProps) {
  const documents = health?.documents
  const collections = health?.collections ?? []
  const parserReady = health?.docling_available ?? health?.doclingAvailable
  const selectTab = (tab: 'collections' | 'documents' | 'search') => {
    onTabChange(tab)
    if (tab === 'documents') onIngest()
    if (tab === 'search') onFocusSearch()
  }
  return (
    <section className="rag-overview" aria-labelledby="rag-overview-title">
      <div className="rag-tabs" role="tablist" aria-label="RAG 工作区视图">
        <button className={'rag-tab' + (activeTab === 'collections' ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={activeTab === 'collections'} onClick={() => selectTab('collections')}><FolderOpen size={14} />知识库管理</button>
        <button className={'rag-tab' + (activeTab === 'documents' ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={activeTab === 'documents'} onClick={() => selectTab('documents')}><FileText size={14} />文档管理</button>
        <button className={'rag-tab' + (activeTab === 'search' ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={activeTab === 'search'} onClick={() => selectTab('search')}><Search size={14} />检索测试</button>
        <button className="rag-overview-action" type="button" onClick={onIngest}><Plus size={14} />导入文档</button>
      </div>
      <div className="rag-overview-grid">
        <section className="rag-collections" aria-labelledby="rag-overview-title">
          <div className="panel-heading-row"><div><p className="panel-kicker">COLLECTIONS</p><h2 id="rag-overview-title">知识库管理</h2></div><span className="panel-muted">{documents === undefined ? '等待同步' : String(documents) + ' 个文档'}</span></div>
          <div className="collection-list">
            {collections.length ? collections.map((collection, index) => (
              <CollectionRow
                key={collection.name}
                collection={collection}
                icon={index % 3 === 0 ? <Layers3 size={17} /> : index % 3 === 1 ? <FileText size={17} /> : <FolderOpen size={17} />}
                tone={index % 3 === 0 ? 'blue' : index % 3 === 1 ? 'green' : 'violet'}
              />
            )) : (
              <div className="collection-empty">
                <FolderOpen size={20} />
                <strong>暂无知识库数据</strong>
                <span>导入首份文档后将按集合自动汇总</span>
              </div>
            )}
          </div>
          <button className="collection-add" type="button" onClick={onIngest}><Plus size={15} />导入文档</button>
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

function CollectionRow({ icon, tone, collection }: { icon: ReactNode; tone: string; collection: RagCollectionStatistics }) {
  return (
    <article className="collection-row">
      <span className={'collection-icon collection-icon--' + tone}>{icon}</span>
      <div className="collection-copy"><strong>{collection.name}</strong><small>当前用户可检索集合</small></div>
      <div className="collection-count"><span>文档</span><strong>{collection.documents}</strong></div>
      <div className="collection-count"><span>切片</span><strong>{collection.chunks}</strong></div>
      <span className="collection-state">可用</span>
    </article>
  )
}
