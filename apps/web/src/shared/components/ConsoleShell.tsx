import { Menu, PanelLeftClose, PanelLeftOpen, X, LogOut } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import type { User } from '../api/types'
import { navigationItems, pageLabel, type PageKey, systemNavigationIcon } from '../navigation'
import { StatusPill } from './StatusPill'

interface ConsoleShellProps {
  user: User | null
  activePage: PageKey
  onNavigate: (page: PageKey) => void
  onLogout: () => void | Promise<void>
  children: ReactNode
}

const COLLAPSED_KEY = 'ican.console.nav.collapsed'

export function ConsoleShell({ user, activePage, onNavigate, onLogout, children }: ConsoleShellProps) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [mobileOpen, setMobileOpen] = useState(false)
  const CurrentPageIcon = navigationItems.find((item) => item.key === activePage)?.icon ?? navigationItems[0].icon
  const SystemIcon = systemNavigationIcon

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

  const displayName = user?.name || user?.username || '用户'
  const initial = displayName.slice(0, 1).toUpperCase()

  return (
    <div className={`console-shell ${collapsed ? 'console-shell--collapsed' : ''} ${mobileOpen ? 'console-shell--nav-open' : ''}`}>
      <header className="console-topbar">
        <div className="console-brand">
          <button className="icon-button console-mobile-menu" type="button" onClick={() => setMobileOpen(true)} aria-label="打开导航" title="打开导航"><Menu size={18} /></button>
          <div className="brand-mark" aria-hidden="true"><span /></div>
          <div className="console-brand-copy"><strong>ICAN 数字人</strong><span>Agent 控制台</span></div>
        </div>
        <div className="console-context"><CurrentPageIcon size={15} /><span>{pageLabel(activePage)}</span></div>
        <div className="console-topbar-actions">
          <div className="runtime-state"><span className="live-dot" />系统在线</div>
          <div className="user-chip"><span>{initial}</span><strong>{displayName}</strong></div>
          <button className="icon-button" type="button" onClick={() => void onLogout()} aria-label="退出登录" title="退出登录"><LogOut size={16} /></button>
        </div>
      </header>
      <div className="console-body">
        <aside className="console-nav" aria-label="主导航">
          <div className="console-nav-head">
            <span>{collapsed ? '导航' : '工作区'}</span>
            <button className="icon-button console-collapse-button" type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? '展开导航' : '收起导航'} title={collapsed ? '展开导航' : '收起导航'}>
              {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            </button>
            <button className="icon-button console-nav-close" type="button" onClick={() => setMobileOpen(false)} aria-label="关闭导航" title="关闭导航"><X size={17} /></button>
          </div>
          <nav className="console-nav-list">
            {navigationItems.map(({ key, label, shortLabel, icon: Icon }) => (
              <button key={key} className={`console-nav-item ${activePage === key ? 'console-nav-item--active' : ''}`} type="button" onClick={() => navigate(key)} title={collapsed ? label : undefined} aria-current={activePage === key ? 'page' : undefined}>
                <Icon size={17} /><span className="console-nav-label">{collapsed ? shortLabel : label}</span>
              </button>
            ))}
          </nav>
          <div className="console-nav-footer">
            <div className="console-system-line"><SystemIcon size={15} /><span>运行服务</span><StatusPill status="online" label="READY" /></div>
          </div>
        </aside>
        {mobileOpen && <button className="console-nav-backdrop" type="button" onClick={() => setMobileOpen(false)} aria-label="关闭导航" />}
        <main className="console-main">{children}</main>
      </div>
    </div>
  )
}
