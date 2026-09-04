import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import BrandLogo from '../components/BrandLogo'
import PageAccessGuard from '../components/PageAccessGuard'
import Sidebar from './Sidebar'

export default function AppLayout() {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!navOpen) return undefined
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [navOpen])

  useEffect(() => {
    if (!navOpen) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen])

  return (
    <div className="flex h-full min-h-screen bg-slate-950 text-slate-100 overflow-x-hidden">
      <header className="fixed top-0 inset-x-0 z-40 flex h-14 items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-3 backdrop-blur md:hidden">
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={navOpen}
          aria-controls="app-sidebar"
          onClick={() => setNavOpen(true)}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-700 text-slate-200 hover:bg-slate-900"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <BrandLogo size="sm" />
      </header>

      {navOpen && (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setNavOpen(false)}
        />
      )}

      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />

      <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden pt-14 md:pt-0">
        <div className="max-w-7xl mx-auto w-full p-4 sm:p-6">
          <PageAccessGuard>
            <Outlet />
          </PageAccessGuard>
        </div>
      </main>
    </div>
  )
}
