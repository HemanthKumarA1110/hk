import LiveOrderForm from '../components/LiveOrderForm'

import BrokerTradeFeedContainer from '../components/BrokerTradeFeedContainer'

import AngelOneAccountPanel from '../components/AngelOneAccountPanel'

import RiskMeter from '../components/RiskMeter'

import TradingModeToggle from '../components/TradingModeToggle'

import AutoTradingPanel from '../components/AutoTradingPanel'

import { fetchOrders, fetchPaperPositions } from '../api'

import { useEffect, useState } from 'react'



export default function LiveTradingPage() {

  const [orders, setOrders] = useState([])

  const [positions, setPositions] = useState([])

  const [orderStatus, setOrderStatus] = useState(null)



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

        <p className="text-emerald-400 text-xs uppercase tracking-widest">Trading</p>

        <h2 className="text-3xl font-bold mt-1">Paper & Live Trading</h2>

        <p className="text-slate-400 mt-1">

          Practice with paper trading first, then connect Angel One for live orders.

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



      <div className="mb-6">

        <AutoTradingPanel />

      </div>



      <div className="grid gap-4 lg:grid-cols-3 mb-6">

        <div className="lg:col-span-2">

          <LiveOrderForm onPlaced={refreshOrders} orderStatus={orderStatus} />

        </div>

        <RiskMeter compact />

      </div>



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

                      <span>{p.symbol} · {p.side}</span>

                      <span className="text-amber-400">Qty {p.qty}</span>

                    </div>

                    <p className="text-xs text-slate-500 mt-1">Avg {p.avg_price}</p>

                  </div>

                ))}

              </>

            ) : (

              <>

                {orders.length === 0 && <p className="text-sm text-slate-500">No orders placed yet.</p>}

                {orders.map((o) => (

                  <div key={o.id} className="border border-slate-800 rounded-lg p-3 text-sm">

                    <div className="flex justify-between">

                      <span>{o.symbol} · {o.side}</span>

                      <span className={o.status === 'submitted' ? 'text-emerald-400' : 'text-slate-400'}>

                        {o.status}

                      </span>

                    </div>

                    <p className="text-xs text-slate-500 mt-1">Qty {o.qty} · ID {o.broker_order_id || o.id}</p>

                  </div>

                ))}

              </>

            )}

          </div>

        </section>

      </div>

    </div>

  )

}

