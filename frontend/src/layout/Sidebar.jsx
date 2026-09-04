import { NavLink } from 'react-router-dom'
import BrandLogo from '../components/BrandLogo'
import { useAuth } from '../context/AuthContext'
import { getAllowedNavItems } from '../config/pages'

export default function Sidebar({ open = false, onClose }) {
  const { user, logout } = useAuth()
  const navItems = getAllowedNavItems(user?.allowed_pages)

  return (
    <aside
      id="app-sidebar"
      className={`fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-slate-800 bg-slate-950 transition-transform duration-200 ease-out md:static md:z-auto md:w-64 md:max-w-none md:shrink-0 md:translate-x-0 ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex items-start justify-between gap-2 border-b border-slate-800 p-5">
        <div className="min-w-0">
          <BrandLogo size="md" showTagline />
          <p className="text-slate-500 text-xs mt-3 truncate">
            {user?.username} · {user?.role}
          </p>
        </div>
        <button
          type="button"
          aria-label="Close menu"
          onClick={onClose}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-900 md:hidden"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            onClick={onClose}
            className={({ isActive }) =>
              `flex min-h-[44px] items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                isActive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
              }`
            }
          >
            <span className="w-5 text-center text-base">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-slate-800 p-4">
        <button
          type="button"
          onClick={() => {
            onClose?.()
            logout()
          }}
          className="w-full min-h-[44px] rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-900"
        >
          Logout
        </button>
      </div>
    </aside>
  )
}
