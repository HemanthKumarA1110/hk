import { useEffect, useState } from 'react'
import LiveOrderForm from '../components/LiveOrderForm'
import LiveTradingAutoSection from '../components/LiveTradingAutoSection'
import BrokerTradeFeedContainer from '../components/BrokerTradeFeedContainer'
import AngelOneAccountPanel from '../components/AngelOneAccountPanel'
import RiskMeter from '../components/RiskMeter'
import TradingModeToggle from '../components/TradingModeToggle'
import { fetchOrders, fetchPaperPositions } from '../api'

const PAGE_TABS = [
  { id: 'order', label: 'Place Order' },
  { id: 'auto', label: 'Auto Trading' },
  { id: 'activity', label: 'Activity' },
]

export default function LiveTradingPage() {
  const [orders, setOrders] = useState([])
  const [positions, setPositions] = useState([])
  const [orderStatus, setOrderStatus] = useState(null)
  const [pageTab, setPageTab] = useState('order')

  const refreshOrders = () => {
    fetchOrders().then((d) => setOrders(d.orders || [])).catch(() => null)
    if (orderStatus?.trading_mode === 'paper') {
      fetchPaperPositions().then((d) => setPositions(d.positions || [])).catch(() => null)
    }
  }

  useEffect(() => {
    refreshOrders()
  }, [orderStatus?.trading_mode])

  const isPaper = orderStatus?.trading_mode === 'paper'

  return (
    <div>
      <header className="mb-6">
        <p className="text-emerald-400 text-xs uppercase tracking-widest">Trading Hub</p>
        <h2 className="text-3xl font-bold mt-1">Live Trading</h2>
        <p className="text-slate-400 mt-1 max-w-3xl">
          One place for manual orders, AI auto bots (scalping, intraday, swing), and activity.
          Use paper mode first, then switch to live when Angel One is connected.
        </p>
      </header>

      <div className="mb-6">
        <TradingModeToggle
          onChange={(status) => {
            setOrderStatus(status)
            refreshOrders()
          }}
        />
      </div>

      <div className="flex flex-wrap gap-2 mb-6 border-b border-slate-800 pb-1">
        {PAGE_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setPageTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg -mb-px border-b-2 transition-colors ${
              pageTab === tab.id
                ? 'border-emerald-400 text-emerald-300'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {pageTab === 'order' && (
        <div className="grid gap-4 lg:grid-cols-3 mb-6">
          <div className="lg:col-span-2">
            <LiveOrderForm onPlaced={refreshOrders} orderStatus={orderStatus} />
          </div>
          <RiskMeter compact />
        </div>
      )}

      {pageTab === 'auto' && (
        <div className="mb-6">
          <LiveTradingAutoSection isPaper={isPaper} />
        </div>
      )}

      {pageTab === 'activity' && (
        <>
          <div className="mb-6">
            <AngelOneAccountPanel />
          </div>
          <div className="grid gap-4 lg:grid-cols-2 mb-6">
            <BrokerTradeFeedContainer tradingMode={orderStatus?.trading_mode} />
            <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <h3 className="font-semibold mb-3">
                {isPaper ? 'Paper Positions' : 'Recent Orders (Platform)'}
              </h3>
              <div className="space-y-2 max-h-80 overflow-auto">
                {isPaper ? (
                  <>
                    {positions.length === 0 && (
                      <p className="text-sm text-slate-500">No open paper positions yet.</p>
                    )}
                    {positions.map((p) => (
                      <div key={p.symbol} className="border border-slate-800 rounded-lg p-3 text-sm">
                        <div className="flex justify-between">
                          <span>
                            {p.symbol} · {p.side}
                          </span>
                          <span className="text-amber-400">Qty {p.qty}</span>
                        </div>
                        <p className="text-xs text-slate-500 mt-1">Avg {p.avg_price}</p>
                      </div>
                    ))}
                  </>
                ) : (
                  <>
                    {orders.length === 0 && (
                      <p className="text-sm text-slate-500">No orders placed yet.</p>
                    )}
                    {orders.map((o) => (
                      <div key={o.id} className="border border-slate-800 rounded-lg p-3 text-sm">
                        <div className="flex justify-between">
                          <span>
                            {o.symbol} · {o.side}
                          </span>
                          <span
                            className={
                              o.status === 'submitted' ? 'text-emerald-400' : 'text-slate-400'
                            }
                          >
                            {o.status}
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 mt-1">
                          Qty {o.qty} · ID {o.broker_order_id || o.id}
                        </p>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </section>
          </div>
        </>
      )}

      {pageTab !== 'activity' && (
        <div className="mb-6">
          <AngelOneAccountPanel />
        </div>
      )}
    </div>
  )
}
