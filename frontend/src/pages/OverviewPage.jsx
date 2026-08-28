import { useEffect, useState } from 'react'
import { fetchAdminOverview, fetchBrokerFunds, fetchBrokerStatus, fetchEquityCurve } from '../api'
import IndexQuotesPanel from '../components/IndexQuotesPanel'
import BrokerReconnectPanel from '../components/BrokerReconnectPanel'
import BrokerStatus from '../components/BrokerStatus'
import BrokerSetupForm from '../components/BrokerSetupForm'
import EquityCurveChart from '../components/EquityCurveChart'
import MarketLivePanel from '../components/MarketLivePanel'
import MetricCard from '../components/MetricCard'
import RiskMeter from '../components/RiskMeter'
import { formatAvailableMargin } from '../utils/brokerFunds'
import { APP_NAME } from '../config/brand'

export default function OverviewPage() {
  const [overview, setOverview] = useState(null)
  const [curve, setCurve] = useState([])
  const [funds, setFunds] = useState(null)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [editingCredentials, setEditingCredentials] = useState(false)

  useEffect(() => {
    const load = () => {
      fetchAdminOverview().then(setOverview).catch(() => null)
      fetchEquityCurve().then((d) => setCurve(d.points || [])).catch(() => null)
      fetchBrokerFunds()
        .then(setFunds)
        .catch(() => setFunds({ status: false, data: {}, message: 'Request failed' }))
      fetchBrokerStatus().then(setBrokerStatus).catch(() => null)
    }
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const summary = overview?.summary || {}
  const margin = formatAvailableMargin(funds, brokerStatus)
  const needsReconnect =
    brokerStatus?.needs_reconnect || margin.text === 'Reconnect broker'

  const refreshBrokerData = ({ status, funds: nextFunds } = {}) => {
    if (status) setBrokerStatus(status)
    if (nextFunds) setFunds(nextFunds)
    fetchBrokerStatus().then(setBrokerStatus).catch(() => null)
    fetchBrokerFunds()
      .then(setFunds)
      .catch(() => setFunds({ status: false, data: {}, message: 'Request failed' }))
  }

  return (
    <div>
      <header className="mb-6">
        <p className="text-emerald-400 text-xs uppercase tracking-widest">{APP_NAME}</p>
        <h2 className="text-3xl font-bold mt-1">Overview</h2>
        <p className="text-slate-400 mt-1">Live P&L, risk controls, equity curve, and platform health</p>
      </header>

      <IndexQuotesPanel
        brokerConnected={brokerStatus?.connected}
        sessionValid={brokerStatus?.session_valid !== false && !needsReconnect}
      />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
        <MetricCard
          label="Total P&L"
          value={`₹${Number(summary.total_pnl || 0).toLocaleString('en-IN')}`}
          tone={(summary.total_pnl || 0) >= 0 ? 'good' : 'bad'}
        />
        <MetricCard label="Win Rate" value={`${((summary.win_rate || 0) * 100).toFixed(0)}%`} />
        <MetricCard label="AI Approved" value={summary.ai_approved ?? '—'} sub={`${summary.ai_rejected ?? 0} rejected`} />
        <MetricCard
          label="Available Margin"
          value={margin.text}
          tone={margin.tone === 'good' ? 'good' : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <div className="lg:col-span-2">
          <EquityCurveChart points={curve} />
        </div>
        <RiskMeter />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <BrokerStatus status={brokerStatus} />
        {!brokerStatus?.credentials_configured || editingCredentials ? (
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-1">
              {brokerStatus?.credentials_configured ? 'Update Angel One' : 'Connect Angel One'}
            </h3>
            <p className="text-sm text-slate-400 mb-4">
              {brokerStatus?.credentials_configured
                ? 'Leave fields blank to keep saved secrets. Only enter values you want to change.'
                : 'Connect Angel One to enable live orders.'}
            </p>
            <BrokerSetupForm
              compact
              showLoginFields={false}
              credentialsConfigured={Boolean(brokerStatus?.credentials_configured)}
              clientCode={brokerStatus?.client_code}
              onCancel={editingCredentials ? () => setEditingCredentials(false) : undefined}
              onSuccess={() => {
                setEditingCredentials(false)
                refreshBrokerData()
              }}
            />
          </section>
        ) : !brokerStatus?.connected || needsReconnect ? (
          <BrokerReconnectPanel
            mode={!brokerStatus?.connected ? 'connect' : 'reconnect'}
            clientCode={brokerStatus?.client_code}
            onSuccess={refreshBrokerData}
            onChangeCredentials={() => setEditingCredentials(true)}
          />
        ) : (
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-3">Signal Activity</h3>
            <div className="grid grid-cols-3 gap-3 text-center">
              {['scalping', 'intraday', 'swing'].map((engine) => (
                <div key={engine} className="rounded-lg bg-slate-950/50 p-3">
                  <p className="text-xs uppercase text-slate-500">{engine}</p>
                  <p className="text-2xl font-bold mt-1">{summary.signal_counts?.[engine] ?? 0}</p>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="mt-4 text-sm text-slate-400 hover:text-slate-200 underline"
              onClick={() => setEditingCredentials(true)}
            >
              Change Angel One credentials
            </button>
          </section>
        )}
      </div>

      <MarketLivePanel compact />
    </div>
  )
}
