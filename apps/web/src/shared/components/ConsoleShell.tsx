import { Bell, ChevronLeft, ChevronRight, Maximize2, Menu, MoreVertical, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import type { User } from '../api/types'
import { navigationForRole, type PageKey } from '../navigation'
import { useRuntimeStatus } from '../../features/runtime/model'

interface ConsoleShellProps {
  user: User | null
  activePage: PageKey
  onNavigate: (page: PageKey) => void
  onLogout: () => void | Promise<void>
  children: ReactNode
}

const COLLAPSED_KEY = 'digital-human.console.nav.collapsed'

export function ConsoleShell({ user, activePage, onNavigate, onLogout, children }: ConsoleShellProps) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [mobileOpen, setMobileOpen] = useState(false)
  const runtime = useRuntimeStatus()
  const visibleNavigation = navigationForRole(user?.role)

  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  useEffect(() => {
    setMobileOpen(false)
  }, [activePage])

  function navigate(page: PageKey) {
    onNavigate(page)
    setMobileOpen(false)
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await document.documentElement.requestFullscreen()
    } catch {
      // 浏览器策略可能禁用全屏，保持控制台可用即可。
    }
  }

  const displayName = user?.name || user?.username || '用户'
  const initial = displayName.slice(0, 1).toUpperCase()
  const runtimeReady = runtime.rag.status === 'online' && runtime.observability.status === 'online'
  const runtimePartial = runtime.rag.status === 'degraded' || runtime.observability.status === 'degraded'
  const runtimeLabel = runtime.isLoading ? '检查中' : runtimeReady ? '系统在线' : runtimePartial ? '部分可用' : '服务不可达'
  const runtimeStatus = runtime.isLoading ? 'pending' : runtimeReady ? 'online' : runtimePartial ? 'pending' : 'offline'

  return (
    <div className={`console-shell ${collapsed ? 'console-shell--collapsed' : ''} ${mobileOpen ? 'console-shell--nav-open' : ''}`}>
      <header className="console-topbar">
        <div className="console-brand">
          <button className="icon-button console-mobile-menu" type="button" onClick={() => setMobileOpen(true)} aria-label="打开导航" title="打开导航"><Menu size={18} /></button>
          <div className="brand-mark" aria-hidden="true"><span /></div>
          <div className="console-brand-copy"><strong>Digital Human</strong><span>Agent 控制台</span></div>
        </div>
        <div className="console-topbar-actions">
          <div className="runtime-state"><span className={`live-dot${runtimeStatus === 'offline' ? ' live-dot--offline' : ''}`} />{runtimeLabel}</div>
          <button className="icon-button" type="button" onClick={() => void toggleFullscreen()} aria-label="全屏显示" title="全屏显示"><Maximize2 size={16} /></button>
          {user?.role === 'admin' && <button className="icon-button console-notification" type="button" onClick={() => navigate('audit')} aria-label="查看通知与审计" title="查看通知与审计"><Bell size={16} /><i aria-hidden="true" /></button>}
        </div>
      </header>
      <div className="console-body">
        <aside className="console-nav" aria-label="主导航">
          <button className="icon-button console-nav-close" type="button" onClick={() => setMobileOpen(false)} aria-label="关闭导航" title="关闭导航"><X size={17} /></button>
          <nav className="console-nav-list">
            {visibleNavigation.map(({ key, label, shortLabel, icon: Icon }) => (
              <button key={key} className={`console-nav-item ${activePage === key ? 'console-nav-item--active' : ''}`} type="button" onClick={() => navigate(key)} title={collapsed ? label : undefined} aria-current={activePage === key ? 'page' : undefined}>
                <Icon size={17} /><span className="console-nav-label">{collapsed ? shortLabel : label}</span>
              </button>
            ))}
          </nav>
          <div className="console-nav-footer">
            <div className="console-nav-account">
              <span className="console-nav-avatar">{initial}</span>
              <span className="console-nav-account-copy"><strong>{displayName}</strong><small>{user?.role || '超级管理员'}</small></span>
              <button className="icon-button" type="button" onClick={() => void onLogout()} aria-label="退出登录" title="退出登录"><MoreVertical size={16} /></button>
            </div>
          </div>
        </aside>
        <button className="console-collapse-rail" type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? '展开导航' : '收起导航'} title={collapsed ? '展开导航' : '收起导航'}>
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
        {mobileOpen && <button className="console-nav-backdrop" type="button" onClick={() => setMobileOpen(false)} aria-label="关闭导航" />}
        <main className={`console-main ${activePage === 'home' ? 'console-main--home' : ''}`}>{children}</main>
      </div>
    </div>
  )
}
