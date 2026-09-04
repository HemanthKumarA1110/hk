/** Controllable app pages — keys must match backend trading_shared.auth.pages */

export const PAGE_CATALOG = [
  { key: 'overview', path: '/', label: 'Overview', icon: '◉' },
  { key: 'scalping_nifty', path: '/scalping/nifty50', label: 'Nifty Scalping', icon: '⚡' },
  { key: 'scalping_banknifty', path: '/scalping/banknifty', label: 'Bank Nifty Scalping', icon: '⚡' },
  { key: 'intraday', path: '/intraday', label: 'Intraday', icon: '▤' },
  { key: 'swing', path: '/swing', label: 'Swing', icon: '↗' },
  { key: 'swing_ideas', path: '/swing/ideas', label: 'Swing Ideas', icon: '✦' },
  { key: 'portfolio', path: '/portfolio', label: 'Portfolio', icon: '◫' },
  { key: 'live', path: '/live', label: 'Live Trading', icon: '▶' },
  { key: 'orders', path: '/orders', label: 'Orders & Positions', icon: '▦' },
  { key: 'strategy', path: '/strategy', label: 'Strategy', icon: '◎' },
  { key: 'backtest', path: '/backtest', label: 'Backtesting', icon: '⧉' },
  { key: 'backtest_results', path: '/backtest/results', label: 'Backtest Results', icon: '📊' },
  { key: 'journal', path: '/journal', label: 'Journal', icon: '☰' },
  { key: 'alerts', path: '/alerts', label: 'Alerts', icon: '◈' },
  { key: 'ai', path: '/ai', label: 'AI Monitor', icon: '✦' },
  { key: 'notepad', path: '/notepad', label: 'Notepad', icon: '📝' },
  { key: 'account', path: '/account', label: 'Account', icon: '⚙' },
  { key: 'admin_users', path: '/admin/users', label: 'Users Admin', icon: '👤' },
]

export const DEFAULT_TRADER_PAGES = [
  'overview',
  'scalping_nifty',
  'scalping_banknifty',
  'intraday',
  'swing',
  'swing_ideas',
  'live',
  'orders',
  'strategy',
  'journal',
  'account',
]

export const ALL_PAGE_KEYS = PAGE_CATALOG.map((p) => p.key)

const PATH_ENTRIES = [...PAGE_CATALOG].sort((a, b) => b.path.length - a.path.length)

export function pathToPageKey(pathname) {
  const path = (pathname || '/').replace(/\/$/, '') || '/'
  for (const entry of PATH_ENTRIES) {
    const cand = entry.path.replace(/\/$/, '') || '/'
    if (path === cand || (cand !== '/' && path.startsWith(`${cand}/`))) {
      return entry.key
    }
  }
  return null
}

export function defaultPagesForRole(role) {
  if (role === 'admin') return [...ALL_PAGE_KEYS]
  return [...DEFAULT_TRADER_PAGES]
}

export function getAllowedNavItems(allowedPages) {
  const allowed = new Set(allowedPages || [])
  return PAGE_CATALOG.filter((p) => allowed.has(p.key)).map((p) => ({
    to: p.path,
    label: p.label,
    icon: p.icon,
    key: p.key,
  }))
}

export function firstAllowedPath(allowedPages) {
  const items = getAllowedNavItems(allowedPages)
  return items[0]?.to || '/account'
}

export function canAccessPath(allowedPages, pathname) {
  const key = pathToPageKey(pathname)
  if (!key) return false
  return (allowedPages || []).includes(key)
}
