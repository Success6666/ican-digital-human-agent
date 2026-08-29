import { Database, RefreshCw, Sparkles, Radio, Route } from 'lucide-react'
import type { ProviderStatus } from '../../../shared/api/types'
import { StatusPill } from '../../../shared/components/StatusPill'
import { useRuntimeStatus, type RuntimeServiceState, type RuntimeStatus } from '../model'

interface RuntimeStripProps {
  provider: ProviderStatus | null
}

const statusLabels: Record<RuntimeStatus, string> = {
  online: '在线',
  degraded: '降级',
  offline: '离线',
  pending: '检查中',
}

function pillStatus(status: RuntimeStatus): 'online' | 'offline' | 'pending' | 'active' | 'idle' | 'error' {
  if (status === 'online') return 'online'
  if (status === 'degraded') return 'pending'
  if (status === 'pending') return 'pending'
  return 'offline'
}

function ServiceBadge({ service, icon }: { service: RuntimeServiceState; icon: 'rag' | 'telemetry' }) {
  const Icon = icon === 'rag' ? Database : Radio
  const detail = service.documents === undefined ? service.detail : `${service.detail} · ${service.documents} 份`
  return (
    <span className="runtime-service" title={detail}>
      <Icon size={13} aria-hidden="true" />
      <span>{service.label}</span>
      <StatusPill status={pillStatus(service.status)} label={statusLabels[service.status]} />
    </span>
  )
}

export function RuntimeStrip({ provider }: RuntimeStripProps) {
  const runtime = useRuntimeStatus()
  const providerStatus: RuntimeStatus = !provider ? 'pending' : provider.available ? 'online' : 'offline'

  return (
    <div className="runtime-strip" aria-label="运行链路状态" title={runtime.lastCheckedAt ? `最近检查：${new Date(runtime.lastCheckedAt).toLocaleTimeString('zh-CN')}` : '正在检查运行状态'}>
      <div className="runtime-strip-title"><Sparkles size={17} /><span>Runtime 链路</span></div>
      <div className="runtime-strip-items">
        <span><Route size={12} />Auth</span><i /><span>LangGraph</span><i /><span>MCP</span><i /><span>Provider</span>
      </div>
      <div className="runtime-services" aria-live="polite">
        <ServiceBadge service={runtime.rag} icon="rag" />
        <ServiceBadge service={runtime.observability} icon="telemetry" />
        <span className="runtime-provider" title={provider?.description || 'Provider 状态'}>
          <StatusPill status={pillStatus(providerStatus)} label={providerStatus === 'online' ? 'Provider 在线' : providerStatus === 'offline' ? 'Provider 离线' : 'Provider 检查中'} />
        </span>
      </div>
      <button className="icon-button runtime-refresh" type="button" onClick={() => void runtime.refresh()} disabled={runtime.isRefreshing} aria-label="刷新运行状态" title="刷新运行状态">
        <RefreshCw size={14} className={runtime.isRefreshing ? 'spin' : undefined} />
      </button>
    </div>
  )
}
