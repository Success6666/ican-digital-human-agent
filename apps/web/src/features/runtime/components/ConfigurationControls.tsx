import { Bot, Clock3, LoaderCircle, Settings2, ShieldCheck, SlidersHorizontal, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ProviderStatus } from '../../../shared/api/types'
import type { RuntimeConfiguration, RuntimeConfigurationPatch } from '../configuration'

type DialogKind = 'runtime' | 'session' | 'mofa' | null

interface ConfigurationControlsProps {
  configuration: RuntimeConfiguration | null
  providers: ProviderStatus[]
  canManage: boolean
  isLoading: boolean
  isSaving: boolean
  onSave: (payload: RuntimeConfigurationPatch) => Promise<RuntimeConfiguration>
}

function providerLabel(providers: ProviderStatus[], providerName?: string) {
  return providers.find((provider) => provider.name === providerName)?.label ?? providerName ?? '读取中'
}

export function ConfigurationControls({
  configuration, providers, canManage, isLoading, isSaving, onSave,
}: ConfigurationControlsProps) {
  const [dialog, setDialog] = useState<DialogKind>(null)
  const [provider, setProvider] = useState('mock')
  const [ttlSeconds, setTtlSeconds] = useState('1800')
  const [cleanupSeconds, setCleanupSeconds] = useState('30')
  const [mofaEnabled, setMofaEnabled] = useState(false)
  const [mofaAppId, setMofaAppId] = useState('')
  const [mofaAppSecret, setMofaAppSecret] = useState('')
  const [mofaAuthorization, setMofaAuthorization] = useState('')
  const [mofaGatewayUrl, setMofaGatewayUrl] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    if (!configuration) return
    setProvider(configuration.defaultProvider ?? 'mock')
    setTtlSeconds(String(configuration.session?.ttlSeconds ?? 1800))
    setCleanupSeconds(String(configuration.session?.cleanupIntervalSeconds ?? 30))
    setMofaEnabled(Boolean(configuration.mofa?.enabled))
    setMofaAppId(configuration.mofa?.appId ?? '')
    setMofaAuthorization(configuration.mofa?.authorization ?? '')
    setMofaGatewayUrl(configuration.mofa?.gatewayUrl === '星云默认网关' ? '' : configuration.mofa?.gatewayUrl ?? '')
  }, [configuration])

  function open(kind: Exclude<DialogKind, null>) {
    if (!canManage) return
    setFormError(null)
    setDialog(kind)
  }

  async function save() {
    if (!dialog) return
    let payload: RuntimeConfigurationPatch
    if (dialog === 'runtime') {
      payload = { defaultProvider: provider }
    } else {
      const ttl = Number(ttlSeconds)
      const cleanup = Number(cleanupSeconds)
      if (!Number.isInteger(ttl) || ttl < 60 || ttl > 86_400) {
        setFormError('会话有效期应为 60 至 86400 秒之间的整数')
        return
      }
      if (!Number.isInteger(cleanup) || cleanup < 5 || cleanup > 3_600) {
        setFormError('清理间隔应为 5 至 3600 秒之间的整数')
        return
      }
      payload = { session: { ttlSeconds: ttl, cleanupIntervalSeconds: cleanup } }
    }
    if (dialog === 'mofa') {
      if (mofaEnabled && (!mofaAppId.trim() || (!configuration?.mofa?.configured && !mofaAppSecret.trim()))) {
        setFormError('启用星云前必须填写 App ID 和 App Secret')
        return
      }
      payload = {
        mofa: {
          enabled: mofaEnabled,
          appId: mofaAppId.trim(),
          ...(mofaAppSecret.trim() ? { appSecret: mofaAppSecret.trim() } : {}),
          authorization: mofaAuthorization.trim(),
          gatewayUrl: mofaGatewayUrl.trim(),
        },
      }
    }
    try {
      await onSave(payload)
      setDialog(null)
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : '配置保存失败')
    }
  }

  return (
    <>
      <section className="configuration-summary" aria-labelledby="configuration-title">
        <div className="section-heading">
          <div><p className="eyebrow">RUNTIME CONTROL</p><h2 id="configuration-title">运行配置</h2></div>
          <span className="panel-count">{canManage ? '可编辑' : '只读'}</span>
        </div>
        <div className="configuration-summary-grid">
          <button className="configuration-summary-card" type="button" onClick={() => open('runtime')} disabled={!canManage || isLoading}>
            <span className="configuration-summary-icon"><Bot size={17} /></span>
            <span><strong>默认数字人</strong><small>{providerLabel(providers, configuration?.defaultProvider)}</small></span>
            <Settings2 size={16} aria-hidden="true" />
          </button>
          <button className="configuration-summary-card" type="button" onClick={() => open('session')} disabled={!canManage || isLoading}>
            <span className="configuration-summary-icon"><Clock3 size={17} /></span>
            <span><strong>会话策略</strong><small>{configuration?.session?.ttlSeconds ?? '--'} 秒有效 · {configuration?.session?.cleanupIntervalSeconds ?? '--'} 秒清理</small></span>
            <Settings2 size={16} aria-hidden="true" />
          </button>
          <div className="configuration-summary-card configuration-summary-card--locked">
            <span className="configuration-summary-icon"><ShieldCheck size={17} /></span>
            <span><strong>部署凭证</strong><small>由服务端安全配置托管</small></span>
          </div>
          <button className="configuration-summary-card" type="button" onClick={() => open('mofa')} disabled={!canManage || isLoading}>
            <span className="configuration-summary-icon"><SlidersHorizontal size={17} /></span>
            <span><strong>魔珐星云</strong><small>{configuration?.mofa?.configured ? '凭证已配置' : '待配置 SDK 凭证'}</small></span>
            <Settings2 size={16} aria-hidden="true" />
          </button>
        </div>
      </section>

      {dialog && (
        <div className="configuration-dialog-backdrop" role="presentation" onMouseDown={() => !isSaving && setDialog(null)}>
          <section className="configuration-dialog" role="dialog" aria-modal="true" aria-labelledby="configuration-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="configuration-dialog-header">
              <div>
                <p className="eyebrow">CONFIGURATION</p>
                <h2 id="configuration-dialog-title">{dialog === 'runtime' ? '数字人运行时' : dialog === 'session' ? '会话策略' : '魔珐星云 SDK'}</h2>
              </div>
              <button className="icon-button" type="button" onClick={() => setDialog(null)} disabled={isSaving} aria-label="关闭配置弹窗" title="关闭"><X size={16} /></button>
            </header>
            <div className="configuration-dialog-body">
              {dialog === 'runtime' ? (
                <>
                  <label className="dialog-field-label">默认数字人</label>
                  <div className="provider-option-list">
                    {providers.map((item) => {
                      const available = item.available && item.configured
                      return <button key={item.name} className={`provider-option ${provider === item.name ? 'provider-option--selected' : ''}`} type="button" onClick={() => setProvider(item.name)} disabled={!available || isSaving}>
                        <span><strong>{item.label}</strong><small>{available ? '可作为新会话默认运行时' : '当前不可用'}</small></span>
                        <i aria-hidden="true" />
                      </button>
                    })}
                  </div>
                </>
              ) : dialog === 'session' ? (
                <div className="configuration-number-grid">
                  <label className="dialog-input"><span>会话有效期（秒）</span><input type="number" min="60" max="86400" inputMode="numeric" value={ttlSeconds} onChange={(event) => setTtlSeconds(event.target.value)} disabled={isSaving} /></label>
                  <label className="dialog-input"><span>清理间隔（秒）</span><input type="number" min="5" max="3600" inputMode="numeric" value={cleanupSeconds} onChange={(event) => setCleanupSeconds(event.target.value)} disabled={isSaving} /></label>
                </div>
              ) : (
                <div className="configuration-mofa-form">
                  <label className="dialog-switch"><span><strong>启用魔珐星云</strong><small>新建会话时使用星云浏览器 SDK</small></span><input type="checkbox" checked={mofaEnabled} onChange={(event) => setMofaEnabled(event.target.checked)} disabled={isSaving} /></label>
                  <label className="dialog-input"><span>App ID</span><input value={mofaAppId} onChange={(event) => setMofaAppId(event.target.value)} placeholder="填写星云 App ID" disabled={isSaving} /></label>
                  <label className="dialog-input"><span>App Secret</span><input type="password" value={mofaAppSecret} onChange={(event) => setMofaAppSecret(event.target.value)} placeholder={configuration?.mofa?.configured ? '已配置，留空表示保持不变' : '填写星云 App Secret'} disabled={isSaving} /></label>
                  <label className="dialog-input"><span>Authorization（可选）</span><input value={mofaAuthorization} onChange={(event) => setMofaAuthorization(event.target.value)} placeholder="留空使用默认值" disabled={isSaving} /></label>
                  <label className="dialog-input"><span>网关地址（可选）</span><input value={mofaGatewayUrl} onChange={(event) => setMofaGatewayUrl(event.target.value)} placeholder="留空使用星云默认网关" disabled={isSaving} /></label>
                  <p className="configuration-dialog-hint">{configuration?.mofa?.detail ?? '凭证仅保存于服务端，不会在页面完整展示。'}</p>
                </div>
              )}
              {formError && <p className="configuration-form-error" role="alert">{formError}</p>}
            </div>
            <footer className="configuration-dialog-footer">
              <button className="secondary-button" type="button" onClick={() => setDialog(null)} disabled={isSaving}>取消</button>
              <button className="primary-button" type="button" onClick={() => void save()} disabled={isSaving}>{isSaving && <LoaderCircle size={15} className="spin" />}保存配置</button>
            </footer>
          </section>
        </div>
      )}
    </>
  )
}
