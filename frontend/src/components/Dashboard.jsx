import { useEffect, useState } from 'react'
import { fetchBrokerFunds, fetchBrokerStatus, fetchServices } from '../api'
import { useAuth } from '../context/AuthContext'
import BrandLogo from './BrandLogo'
import { APP_NAME } from '../config/brand'
import BrokerStatus from './BrokerStatus'
import MarketLivePanel from './MarketLivePanel'
import StrategySignalsPanel from './StrategySignalsPanel'
import AIReasoningPanel from './AIReasoningPanel'

export default function Dashboard() {
  const { user, logout } = useAuth()
  const [services, setServices] = useState(null)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [funds, setFunds] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      fetchServices().catch(() => null),
      fetchBrokerStatus().catch(() => null),
      fetchBrokerFunds().catch(() => null),
    ])
      .then(([svc, status, fundData]) => {
        setServices(svc)
        setBrokerStatus(status)
        setFunds(fundData)
      })
      .catch(() => setError('Unable to load platform status'))
  }, [])

  if (error) {
    return <div className="p-6 text-rose-400">{error}</div>
  }

  return (
    <div className="max-w-7xl mx-auto p-6">
      <header className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <div>
          <BrandLogo size="lg" showTagline />
          <p className="text-slate-400 mt-3">
            Signed in as {user?.username} ({user?.role})
          </p>
        </div>
        <button
          type="button"
          onClick={logout}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-900"
        >
          Logout
        </button>
      </header>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
        <MetricCard label="Broker Connected" value={brokerStatus?.connected ? 'Yes' : 'No'} />
        <MetricCard label="Credentials Saved" value={brokerStatus?.credentials_configured ? 'Yes' : 'No'} />
        <MetricCard label="Redis Session Cache" value={brokerStatus?.cached_in_redis ? 'Active' : 'Inactive'} />
        <MetricCard
          label="Available Margin"
          value={
            funds?.data?.availablecash
              ? `₹${Number(funds.data.availablecash).toLocaleString('en-IN')}`
              : 'Connect broker'
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <BrokerStatus status={brokerStatus} />
        <section className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
          <h2 className="text-xl font-semibold mb-3">Microservices Registry</h2>
          {!services ? (
            <p className="text-slate-400 text-sm">Loading services...</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {Object.entries(services.services).map(([name, url]) => (
                <li key={name} className="flex justify-between border-b border-slate-800 py-2">
                  <span className="text-slate-300">{name}</span>
                  <span className="text-slate-500 font-mono text-xs">{url}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="mb-6">
        <AIReasoningPanel compact />
      </div>

      <div className="mb-6">
        <StrategySignalsPanel />
      </div>

      <div className="mb-6">
        <MarketLivePanel />
      </div>

      <section className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
        <h2 className="text-xl font-semibold mb-2">Platform</h2>
        <p className="text-slate-400 text-sm">
          {APP_NAME} — TradingView charts, multi-desk backtesting, live trading, and risk controls.
        </p>
      </section>
    </div>
  )
}

function MetricCard({ label, value }) {
  return (
    <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-2xl font-bold mt-2">{value}</p>
    </div>
  )
}
