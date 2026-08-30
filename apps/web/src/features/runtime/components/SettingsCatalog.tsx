import { BrainCircuit, Database, KeyRound, Radio, ServerCog, Settings2, ShieldCheck } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { StatusPill } from '../../../shared/components/StatusPill'
import type { ConfigurationService, RuntimeConfiguration } from '../configuration'

type SettingsTab = 'system' | 'models' | 'rag' | 'access'

interface SettingsCatalogProps {
  configuration: RuntimeConfiguration | null
  isLoading: boolean
}

const tabs: Array<{ key: SettingsTab; label: string; icon: typeof Settings2 }> = [
  { key: 'system', label: '系统配置', icon: Settings2 },
  { key: 'models', label: '模型服务', icon: BrainCircuit },
  { key: 'rag', label: '知识库策略', icon: Database },
  { key: 'access', label: '权限与安全', icon: ShieldCheck },
]

export function SettingsCatalog({ configuration, isLoading }: SettingsCatalogProps) {
  const [active, setActive] = useState<SettingsTab>('system')
  return (
    <section className="settings-catalog" aria-labelledby="settings-catalog-title">
      <div className="settings-catalog-tabs" role="tablist" aria-label="后台配置分类">
        {tabs.map(({ key, label, icon: Icon }) => <button key={key} className={'settings-catalog-tab' + (active === key ? ' settings-catalog-tab--active' : '')} type="button" onClick={() => setActive(key)} role="tab" aria-selected={active === key}><Icon size={14} />{label}</button>)}
      </div>
      {active === 'system' && <SystemConfig configuration={configuration} isLoading={isLoading} />}
      {active === 'models' && <ModelConfig configuration={configuration} isLoading={isLoading} />}
      {active === 'rag' && <PolicyConfig configuration={configuration} isLoading={isLoading} />}
      {active === 'access' && <AccessConfig configuration={configuration} isLoading={isLoading} />}
    </section>
  )
}

function SystemConfig({ configuration, isLoading }: SettingsCatalogProps) {
  const session = configuration?.session
  return <div className="catalog-content"><div><p className="panel-kicker">BASIC SETTINGS</p><h2 id="settings-catalog-title">基础设置</h2><p className="catalog-description">控制台名称与默认交互策略由服务端托管，前端只展示当前生效状态。</p></div><div className="config-form-grid"><ConfigValue label="运行环境" value={configuration?.environment || loadingText(isLoading)} /><ConfigValue label="默认 Provider" value={configuration?.defaultProvider || loadingText(isLoading)} /><ConfigValue label="会话租约" value={session?.ttlSeconds === undefined ? loadingText(isLoading) : String(session.ttlSeconds) + ' 秒'} /><ConfigValue label="清理周期" value={session?.cleanupIntervalSeconds === undefined ? loadingText(isLoading) : String(session.cleanupIntervalSeconds) + ' 秒'} /></div><div className="catalog-hint"><ServerCog size={14} /><span>修改后会在下一次会话建立时生效。</span></div></div>
}

function ModelConfig({ configuration, isLoading }: SettingsCatalogProps) {
  const llm = configuration?.llm
  const embedding = configuration?.embedding
  const rows = [
    { name: '业务对话模型', kind: 'LLM', identifier: llm?.mode || llm?.provider || loadingText(isLoading), status: serviceStatus(llm), note: llm?.detail || '用于 LangGraph 回答与意图识别' },
    { name: '向量模型', kind: 'Embedding', identifier: embedding?.provider || loadingText(isLoading), status: serviceStatus(embedding), note: embedding?.detail || '用于知识切片向量化' },
    { name: '语音合成', kind: 'TTS', identifier: 'Provider 能力协商', status: 'pending' as const, note: '未配置时继续使用文本模式' },
    { name: '语音识别', kind: 'ASR', identifier: 'Provider 能力协商', status: 'pending' as const, note: '未配置时保留输入降级' },
  ]
  return <div className="catalog-content"><div><p className="panel-kicker">MODEL SERVICES</p><h2 id="settings-catalog-title">模型服务配置</h2><p className="catalog-description">模型名称与凭证只在服务端保存，控制台仅展示可用性和用途。</p></div><div className="model-table-wrap"><table className="model-table"><thead><tr><th>服务</th><th>类型</th><th>连接方式</th><th>状态</th><th>说明</th></tr></thead><tbody>{rows.map((row) => <tr key={row.name}><td><strong>{row.name}</strong></td><td>{row.kind}</td><td>{row.identifier}</td><td><StatusPill status={row.status} label={row.status === 'online' ? '已启用' : row.status === 'offline' ? '不可用' : '待配置'} /></td><td>{row.note}</td></tr>)}</tbody></table></div></div>
}

function PolicyConfig({ configuration, isLoading }: SettingsCatalogProps) {
  const rag = configuration?.rag
  const mcp = configuration?.mcp
  const models = Array.isArray(rag?.localModels) ? rag.localModels.join('、') : loadingText(isLoading)
  return <div className="catalog-content"><div><p className="panel-kicker">RAG POLICY</p><h2 id="settings-catalog-title">知识库策略</h2><p className="catalog-description">Docling 负责解析，检索端口负责切片与向量查询；所有数据按用户命名空间隔离。</p></div><div className="policy-list"><PolicyRow icon={<Database size={15} />} label="文档解析" value={rag?.parser || loadingText(isLoading)} /><PolicyRow icon={<Radio size={15} />} label="本地模型" value={models} /><PolicyRow icon={<KeyRound size={15} />} label="MCP 边界" value={mcp?.maxResultBytes ? String(mcp.maxResultBytes) + ' 字节上限' : loadingText(isLoading)} /></div></div>
}

function AccessConfig({ configuration, isLoading }: SettingsCatalogProps) {
  const telemetry = configuration?.observability
  const backend = typeof telemetry?.backend === 'string' ? telemetry.backend : loadingText(isLoading)
  return <div className="catalog-content"><div><p className="panel-kicker">ACCESS CONTROL</p><h2 id="settings-catalog-title">权限与安全</h2><p className="catalog-description">浏览器流量必须经过认证网关，内部凭证和原始工具参数不会下发到前端。</p></div><div className="policy-list"><PolicyRow icon={<ShieldCheck size={15} />} label="登录态" value="Sa-Token 会话" /><PolicyRow icon={<KeyRound size={15} />} label="网关策略" value="同源 Cookie + 内部令牌" /><PolicyRow icon={<Settings2 size={15} />} label="遥测后端" value={backend} /></div></div>
}

function serviceStatus(service?: ConfigurationService): 'online' | 'pending' | 'offline' {
  if (!service) return 'pending'
  if (service.configured === true) return 'online'
  if (service.configured === false) return 'pending'
  return 'pending'
}

function loadingText(isLoading: boolean): string {
  return isLoading ? '读取中' : '待配置'
}

function ConfigValue({ label, value }: { label: string; value: string }) {
  return <div className="config-value"><span>{label}</span><strong>{value}</strong></div>
}

function PolicyRow({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="policy-row"><span className="policy-icon">{icon}</span><span>{label}</span><strong>{value}</strong></div>
}
