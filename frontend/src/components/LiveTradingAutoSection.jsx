import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchIntradayStrategies, fetchSwingStrategies } from '../api'
import IntradayAutoTradingPanel from './IntradayAutoTradingPanel'
import ScalpingAutoTradingPanel from './ScalpingAutoTradingPanel'
import SwingAutoTradingPanel from './SwingAutoTradingPanel'
import { filterStrategiesForDesk } from '../utils/strategyFilters'

const DESK_TABS = [
  { id: 'scalping', label: 'Scalping', accent: 'amber' },
  { id: 'intraday', label: 'Intraday', accent: 'cyan' },
  { id: 'swing', label: 'Swing', accent: 'violet' },
]

const SCALP_INSTRUMENTS = [
  { id: 'nifty50', label: 'Nifty 50' },
  { id: 'banknifty', label: 'Bank Nifty' },
]

/** Auto-trading hub: scalping, intraday, swing with AI / manual modes. */
export default function LiveTradingAutoSection({ isPaper = true }) {
  const [deskTab, setDeskTab] = useState('scalping')
  const [scalpInstrument, setScalpInstrument] = useState('nifty50')
  const [intradayStrategies, setIntradayStrategies] = useState([])
  const [swingStrategies, setSwingStrategies] = useState([])

  useEffect(() => {
    fetchIntradayStrategies()
      .then((data) => setIntradayStrategies(filterStrategiesForDesk('intraday', data?.strategies || [])))
      .catch(() => null)
    fetchSwingStrategies()
      .then((data) => setSwingStrategies(filterStrategiesForDesk('swing', data?.strategies || [])))
      .catch(() => null)
  }, [])

  const deskLink =
    deskTab === 'scalping'
      ? `/scalping/${scalpInstrument}`
      : deskTab === 'intraday'
        ? '/intraday'
        : '/swing'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Automated</p>
          <h3 className="font-semibold text-lg">AI & Manual Auto Trading</h3>
          <p className="text-xs text-slate-500 mt-1">
            Configure bots per desk · AI picks signals · Manual uses a fixed strategy
          </p>
        </div>
        <Link
          to={deskLink}
          className="text-xs text-slate-400 hover:text-slate-200 border border-slate-700 rounded-lg px-3 py-2"
        >
          Open full desk →
        </Link>
      </div>

      <div className="flex flex-wrap gap-2">
        {DESK_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setDeskTab(tab.id)}
            className={`rounded-lg px-4 py-2 text-sm font-medium ${
              deskTab === tab.id
                ? tab.accent === 'amber'
                  ? 'bg-amber-500 text-slate-950'
                  : tab.accent === 'cyan'
                    ? 'bg-cyan-500 text-slate-950'
                    : 'bg-violet-500 text-white'
                : 'border border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {deskTab === 'scalping' && (
        <>
          <div className="flex gap-2">
            {SCALP_INSTRUMENTS.map((inst) => (
              <button
                key={inst.id}
                type="button"
                onClick={() => setScalpInstrument(inst.id)}
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  scalpInstrument === inst.id
                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                    : 'border border-slate-700 text-slate-400'
                }`}
              >
                {inst.label}
              </button>
            ))}
          </div>
          <ScalpingAutoTradingPanel instrument={scalpInstrument} isPaper={isPaper} />
        </>
      )}

      {deskTab === 'intraday' && (
        <IntradayAutoTradingPanel strategies={intradayStrategies} isPaper={isPaper} embedded />
      )}

      {deskTab === 'swing' && (
        <SwingAutoTradingPanel strategies={swingStrategies} isPaper={isPaper} embedded />
      )}
    </div>
  )
}
