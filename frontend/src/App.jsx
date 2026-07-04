import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { APP_NAME } from './config/brand'
import BrandLogo from './components/BrandLogo'
import { AuthProvider, useAuth } from './context/AuthContext'
import AppLayout from './layout/AppLayout'
import LoginPage from './components/LoginPage'
import OverviewPage from './pages/OverviewPage'
import ScalpingPage from './pages/ScalpingPage'
import NiftyScalpingPage from './pages/NiftyScalping'
import BankNiftyScalpingPage from './pages/BankNiftyScalping'
import IntradayPage from './pages/IntradayPage'
import SwingPage from './pages/SwingPage'
import PortfolioPage from './pages/PortfolioPage'
import LiveTradingPage from './pages/LiveTradingPage'
import StrategyPage from './pages/StrategyPage'
import BacktestPage from './pages/BacktestPage'
import BacktestResultsPage from './pages/BacktestResultsPage'
import NotepadPage from './pages/NotepadPage'
import JournalPage from './pages/JournalPage'
import PaperOrdersPage from './pages/PaperOrdersPage'
import AlertsPage from './pages/AlertsPage'
import AIPage from './pages/AIPage'

function AppShell() {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center gap-4">
        <BrandLogo size="lg" showTagline />
        <p className="text-slate-500 text-sm">Loading {APP_NAME}…</p>
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
          <Route path="scalping/nifty50" element={<NiftyScalpingPage />} />
          <Route path="scalping/banknifty" element={<BankNiftyScalpingPage />} />
          <Route path="intraday" element={<IntradayPage />} />
          <Route path="swing" element={<SwingPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="live" element={<LiveTradingPage />} />
          <Route path="paper-orders" element={<PaperOrdersPage />} />
          <Route path="strategy" element={<StrategyPage />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="backtest/results" element={<BacktestResultsPage />} />
          <Route path="journal" element={<JournalPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="ai" element={<AIPage />} />
          <Route path="notepad" element={<NotepadPage />} />
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
