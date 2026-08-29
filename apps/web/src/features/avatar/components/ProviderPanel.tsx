import { Bot, ChevronDown, CircleHelp, LoaderCircle, Plus, RefreshCw, ShieldCheck, X } from 'lucide-react'
import type { AvatarSession, ProviderName, ProviderStatus } from '../../../shared/api/types'
import { formatExpiry } from '../../../shared/lib/format'
import { StatusPill } from '../../../shared/components/StatusPill'

interface ProviderPanelProps {
  providers: ProviderStatus[]
  selectedProvider: ProviderName
  selected: ProviderStatus | null
  session: AvatarSession | null
  isLoading: boolean
  isCreating: boolean
  error: string | null
  onSelect: (name: ProviderName) => void
  onCreate: () => void
  onClose: () => void
  onRefresh: () => void
  onClearError: () => void
}

function providerStatus(provider: ProviderStatus): 'online' | 'offline' | 'pending' {
  if (!provider.available) return 'offline'
  return provider.configured ? 'online' : 'pending'
}

export function ProviderPanel(props: ProviderPanelProps) {
  const {
    providers, selectedProvider, selected, session, isLoading, isCreating, error,
    onSelect, onCreate, onClose, onRefresh, onClearError,
  } = props

  return (
    <section className="provider-panel" aria-labelledby="provider-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">AVATAR RUNTIME</p>
          <h2 id="provider-title">数字人 Provider</h2>
        </div>
        <button className="icon-button" type="button" onClick={onRefresh} disabled={isLoading} aria-label="刷新 Provider" title="刷新 Provider">
          <RefreshCw size={16} className={isLoading ? 'spin' : undefined} />
        </button>
      </div>
      {error && (
        <div className="inline-alert" role="alert">
          <CircleHelp size={16} />
          <span>{error}</span>
          <button className="icon-button" type="button" onClick={onClearError} aria-label="关闭提示" title="关闭提示"><X size={15} /></button>
        </div>
      )}
      <div className="provider-select-wrap">
        <label htmlFor="provider-select">当前运行时</label>
        <div className="select-shell">
          <Bot size={17} aria-hidden="true" />
          <select id="provider-select" value={selectedProvider} onChange={(event) => onSelect(event.target.value)} disabled={isLoading || isCreating}>
            {providers.length === 0 && <option value="mock">Mock Runtime</option>}
            {providers.map((provider) => <option key={provider.name} value={provider.name}>{provider.label}</option>)}
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </div>
      </div>
      {selected && (
        <div className="provider-detail">
          <div className="provider-detail-head">
            <span className="provider-name">{selected.label}</span>
            <StatusPill status={providerStatus(selected)} label={selected.available ? (selected.configured ? '可用' : '待配置') : '不可用'} />
          </div>
          <p>{selected.description || '可替换的数字人驱动适配器。'}</p>
          <div className="capability-list">
            {selected.capabilities.length ? selected.capabilities.map((capability) => <span key={capability}>{capability}</span>) : <span>基础文本会话</span>}
          </div>
        </div>
      )}
      {session ? (
        <div className="session-card">
          <div className="session-card-top">
            <div className="session-live"><span className="live-dot" />会话已连接</div>
            <StatusPill status="active" label="ACTIVE" />
          </div>
          <div className="session-scope"><ShieldCheck size={14} /><span>认证网关已接通 Agent</span></div>
          <p>{formatExpiry(session.expiresAt)}</p>
          <button className="secondary-button full-width" type="button" onClick={onClose}><X size={16} />关闭会话</button>
        </div>
      ) : (
        <button className="primary-button full-width" type="button" onClick={onCreate} disabled={isCreating || isLoading}>
          {isCreating ? <LoaderCircle size={17} className="spin" /> : <Plus size={17} />}
          {isCreating ? '正在建立会话…' : '建立数字人会话'}
        </button>
      )}
      <div className="security-note"><ShieldCheck size={15} /><span>凭证只在服务端使用</span></div>
    </section>
  )
}
