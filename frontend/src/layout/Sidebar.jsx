import { NavLink } from 'react-router-dom'
import BrandLogo from '../components/BrandLogo'
import { useAuth } from '../context/AuthContext'

const NAV = [
  { to: '/', label: 'Overview', icon: '◉' },
  { to: '/scalping/nifty50', label: 'Nifty Scalping', icon: '⚡' },
  { to: '/scalping/banknifty', label: 'Bank Nifty Scalping', icon: '⚡' },
  { to: '/scalping', label: 'Scalping (Legacy)', icon: '◎' },
  { to: '/intraday', label: 'Intraday', icon: '▤' },
  { to: '/swing', label: 'Swing', icon: '↗' },
  { to: '/portfolio', label: 'Portfolio', icon: '◫' },
  { to: '/live', label: 'Live Trading', icon: '▶' },
  { to: '/strategy', label: 'Strategy', icon: '◎' },
  { to: '/backtest', label: 'Backtesting', icon: '⧉' },
  { to: '/backtest/results', label: 'Backtest Results', icon: '📊' },
  { to: '/journal', label: 'Journal', icon: '☰' },
  { to: '/alerts', label: 'Alerts', icon: '◈' },
  { to: '/ai', label: 'AI Monitor', icon: '✦' },
  { to: '/notepad', label: 'Notepad', icon: '📝' },
  { to: '/account', label: 'Account', icon: '⚙' },
]

export default function Sidebar() {
  const { user, logout } = useAuth()
  const navItems =
    user?.role === 'admin'
      ? [...NAV, { to: '/admin/users', label: 'Users Admin', icon: '👤' }]
      : NAV

  return (
    <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-950 flex flex-col">
      <div className="p-5 border-b border-slate-800">
        <BrandLogo size="md" showTagline />
        <p className="text-slate-500 text-xs mt-3 truncate">{user?.username} · {user?.role}</p>
      </div>

      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                isActive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
              }`
            }
          >
            <span className="text-base w-5 text-center">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-slate-800">
        <button
          type="button"
          onClick={logout}
          className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-900"
        >
          Logout
        </button>
      </div>
    </aside>
  )
}
