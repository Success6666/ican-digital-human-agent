import { FileText, FolderOpen, Plus, Search } from 'lucide-react'
import type { ReactNode } from 'react'

export type RagWorkspaceTab = 'collections' | 'documents' | 'search'

interface RagWorkspaceTabsProps {
  activeTab: RagWorkspaceTab
  onTabChange: (tab: RagWorkspaceTab) => void
}

export function RagWorkspaceTabs({ activeTab, onTabChange }: RagWorkspaceTabsProps) {
  return (
    <div className="rag-tabs" role="tablist" aria-label="RAG 工作区视图">
      <Tab icon={<FolderOpen size={14} />} label="知识库管理" value="collections" activeTab={activeTab} onChange={onTabChange} />
      <Tab icon={<FileText size={14} />} label="文档管理" value="documents" activeTab={activeTab} onChange={onTabChange} />
      <Tab icon={<Search size={14} />} label="检索测试" value="search" activeTab={activeTab} onChange={onTabChange} />
      <button className="rag-overview-action" type="button" onClick={() => onTabChange('documents')}><Plus size={14} />导入文档</button>
    </div>
  )
}

function Tab({ icon, label, value, activeTab, onChange }: { icon: ReactNode; label: string; value: RagWorkspaceTab; activeTab: RagWorkspaceTab; onChange: (tab: RagWorkspaceTab) => void }) {
  const selected = activeTab === value
  return <button className={'rag-tab' + (selected ? ' rag-tab--active' : '')} type="button" role="tab" aria-selected={selected} onClick={() => onChange(value)}>{icon}{label}</button>
}
