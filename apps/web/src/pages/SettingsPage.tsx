import { BrainCircuit, Database, RefreshCw, ServerCog, ShieldCheck } from 'lucide-react'
import { useMemo } from 'react'
import type { ReactNode } from 'react'
import type { useAvatar } from '../features/avatar/model'
import { useRuntimeStatus } from '../features/runtime/model'
import { PageHeader } from '../shared/components/PageHeader'
import { StatusPill } from '../shared/components/StatusPill'

type AvatarState = ReturnType<typeof useAvatar>

interface SettingsPageProps {
  avatar: AvatarState
}

function statusFor(value: 'online' | 'degraded' | 'offline' | 'pending'): 'online' | 'pending' | 'offline' {
  return value === 'online' ? 'online' : value === 'offline' ? 'offline' : 'pending'
}

export function SettingsPage({ avatar }: SettingsPageProps) {
  const runtime = useRuntimeStatus()
  const configuredCount = useMemo(() => avatar.providers.filter((provider) => provider.configured && provider.available).length, [avatar.providers])
  return (
    <div className="page-stack">
      <PageHeader eyebrow="CONTROL PLANE" title="后台配置" description="查看当前运行组件状态；敏感凭证仅由服务端托管。" actions={<div className="page-header-actions"><button className="icon-button" type="button" onClick={() => { void avatar.loadProviders(); void runtime.refresh() }} disabled={avatar.isLoading || runtime.isRefreshing} aria-label="刷新配置状态" title="刷新配置状态"><RefreshCw size={16} className={avatar.isLoading || runtime.isRefreshing ? 'spin' : undefined} /></button></div>} />
      <section className="work-panel settings-section" aria-labelledby="runtime-config-title"><div className="section-heading"><div><p className="eyebrow">RUNTIME STATUS</p><h2 id="runtime-config-title">编排与数据组件</h2></div><ServerCog size={17} /></div><div className="status-grid"><StatusCard icon={<BrainCircuit size={16} />} title="Agent 编排" subtitle="LangGraph" status="online" detail="运行图已就绪" /><StatusCard icon={<BrainCircuit size={16} />} title="LLM 连接" subtitle="业务模型" status="pending" detail="等待模型配置" /><StatusCard icon={<Database size={16} />} title="Embedding" subtitle="本地向量索引" status={statusFor(runtime.rag.status)} detail={runtime.rag.detail} /><StatusCard icon={<Database size={16} />} title="文档解析" subtitle="Docling" status={statusFor(runtime.rag.status)} detail={runtime.rag.detail} /><StatusCard icon={<ShieldCheck size={16} />} title="实时遥测" subtitle={runtime.observability.backend === 'futureagi' ? 'FutureAGI' : '本地缓冲'} status={statusFor(runtime.observability.status)} detail={runtime.observability.detail} /></div></section>
      <section className="work-panel settings-section" aria-labelledby="provider-config-title"><div className="section-heading"><div><p className="eyebrow">AVATAR PROVIDERS</p><h2 id="provider-config-title">数字人 Provider</h2></div><span className="panel-count">{configuredCount} / {avatar.providers.length} 已就绪</span></div><div className="provider-status-grid">{avatar.providers.map((provider) => <article className="provider-status-card" key={provider.name}><div className="provider-status-head"><div><strong>{provider.label}</strong><small>{provider.description || '可替换的数字人驱动适配器'}</small></div><StatusPill status={provider.available ? provider.configured ? 'online' : 'pending' : 'offline'} label={provider.available ? provider.configured ? '已配置' : '待配置' : '不可用'} /></div><div className="provider-capabilities">{provider.capabilities.length ? provider.capabilities.slice(0, 4).map((capability) => <span key={capability}>{capability}</span>) : <span>基础文本会话</span>}</div></article>)}</div></section>
    </div>
  )
}

function StatusCard({ icon, title, subtitle, status, detail }: { icon: ReactNode; title: string; subtitle: string; status: 'online' | 'pending' | 'offline'; detail?: string }) {
  return <article className="status-card"><span className="status-card-icon">{icon}</span><div><strong>{title}</strong><small>{subtitle}</small></div><div className="status-card-end"><StatusPill status={status} label={status === 'online' ? '在线' : status === 'pending' ? '降级' : '离线'} /><small>{detail}</small></div></article>
}
