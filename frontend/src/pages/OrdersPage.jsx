import AngelOneAccountPanel from '../components/AngelOneAccountPanel'

export default function OrdersPage() {
  return (
    <div>
      <header className="mb-6">
        <p className="text-amber-400 text-xs uppercase tracking-widest">Angel One Account</p>
        <h2 className="text-3xl font-bold mt-1">Orders, Positions & History</h2>
        <p className="text-slate-400 mt-1 max-w-3xl">
          Live order book, day positions, delivery holdings, and trade history from your connected Angel One
          account.
        </p>
      </header>

      <AngelOneAccountPanel />
    </div>
  )
}
