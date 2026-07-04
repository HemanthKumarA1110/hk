import { useState } from 'react'

/**
 * AI Auto Trading toggle with confirmation modal.
 */
export default function AIAutoToggle({ enabled, onToggle, paperMode = true }) {
  const [showModal, setShowModal] = useState(false)

  const confirmEnable = () => {
    setShowModal(false)
    onToggle(true)
  }

  return (
    <>
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        {!enabled && (
          <p className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 mb-3">
            Master switch OFF — paper strategies still auto-enter simulated trades; live strategies wait for this toggle
          </p>
        )}
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-widest text-slate-500">AI Auto Trading</p>
            <p className={`text-xl font-bold ${enabled ? 'text-emerald-400' : 'text-slate-400'}`}>
              {enabled ? 'ON' : 'OFF'}
            </p>
          </div>
          <button
            type="button"
            onClick={() => (enabled ? onToggle(false) : setShowModal(true))}
            className={`rounded-xl px-6 py-3 font-semibold text-sm ${
              enabled
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                : 'bg-emerald-500 text-slate-950'
            }`}
          >
            {enabled ? 'Turn OFF' : 'Turn ON'}
          </button>
        </div>
        {paperMode && !enabled && (
          <p className="text-xs text-slate-500 mt-2">Default: paper mode. Enable only when you accept live order risk.</p>
        )}
      </section>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6">
            <h3 className="text-lg font-semibold text-rose-300">Enable AI Auto Trading?</h3>
            <p className="text-sm text-slate-400 mt-3">
              This will place real MARKET/MIS orders via Angel One when AI confidence ≥ 70%.
              Losses can exceed expectations during volatile markets. You are responsible for all trades.
            </p>
            <div className="flex gap-3 mt-6">
              <button type="button" onClick={() => setShowModal(false)} className="flex-1 rounded-lg border border-slate-700 py-2">
                Cancel
              </button>
              <button type="button" onClick={confirmEnable} className="flex-1 rounded-lg bg-emerald-500 text-slate-950 py-2 font-semibold">
                I Understand — Enable
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
