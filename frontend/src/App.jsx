import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import AppLayout from './layout/AppLayout'
import LoginPage from './components/LoginPage'
import OverviewPage from './pages/OverviewPage'
import ScalpingPage from './pages/ScalpingPage'
import IntradayPage from './pages/IntradayPage'
import SwingPage from './pages/SwingPage'
import PortfolioPage from './pages/PortfolioPage'
import LiveTradingPage from './pages/LiveTradingPage'
import StrategyPage from './pages/StrategyPage'
import BacktestPage from './pages/BacktestPage'
import JournalPage from './pages/JournalPage'
import AlertsPage from './pages/AlertsPage'
import AIPage from './pages/AIPage'

function AppShell() {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        Loading platform...
      </div>
    )
  }

  if (!isAuthenticated) {
    return <LoginPage />
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="scalping" element={<ScalpingPage />} />
          <Route path="intraday" element={<IntradayPage />} />
          <Route path="swing" element={<SwingPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="live" element={<LiveTradingPage />} />
          <Route path="strategy" element={<StrategyPage />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="journal" element={<JournalPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="ai" element={<AIPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}
