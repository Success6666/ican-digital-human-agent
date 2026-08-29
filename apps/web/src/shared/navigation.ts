import { Activity, Database, Gauge, Home, Settings2, ShieldCheck, type LucideIcon } from 'lucide-react'

export type PageKey = 'home' | 'rag' | 'evaluation' | 'audit' | 'settings'

export interface NavigationItem {
  key: PageKey
  label: string
  shortLabel: string
  icon: LucideIcon
}

export const navigationItems: NavigationItem[] = [
  { key: 'home', label: '首页', shortLabel: '首页', icon: Home },
  { key: 'rag', label: 'RAG 记忆与检索增强', shortLabel: 'RAG', icon: Database },
  { key: 'evaluation', label: '评测中心', shortLabel: '评测', icon: Gauge },
  { key: 'audit', label: '审计中心', shortLabel: '审计', icon: ShieldCheck },
  { key: 'settings', label: '后台配置', shortLabel: '配置', icon: Settings2 },
]

export function pageFromHash(hash: string): PageKey {
  const value = hash.replace(/^#\/?/, '') as PageKey
  return navigationItems.some((item) => item.key === value) ? value : 'home'
}

export function pageToHash(page: PageKey): string {
  return `#/${page}`
}

export function pageLabel(page: PageKey): string {
  return navigationItems.find((item) => item.key === page)?.label ?? '首页'
}

export const systemNavigationIcon = Activity
