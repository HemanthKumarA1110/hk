import { useMemo } from 'react'
import { startMarketStream } from '../../api'
import { useMarketStreamStatus } from '../../hooks/useMarketStreamStatus'

function formatAge(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  const s = Number(seconds)
  if (s < 1) return '<1s'
  if (s < 60) return `${Math.round(s)}s`
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('en-IN', { hour12: false })
  } catch {
    return '—'
  }
}

function StatusPill({ ok, label, hint }) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[140px] ${
        ok ? 'border-emerald-500/30 bg-emerald-500/10' : 'border-rose-500/30 bg-rose-500/10'
      }`}
      title={hint}
    >
      <p className="text-[10px] uppercase tracking-widest text-slate-500">{label}</p>
      <p className={`text-sm font-semibold mt-0.5 ${ok ? 'text-emerald-300' : 'text-rose-300'}`}>
        {ok ? 'Connected' : 'Offline'}
      </p>
    </div>
  )
}

/**
 * Live stream health for Nifty / Bank Nifty scalping desks.
 * @param {{ deskStatus?: object, marketStatus?: object, compact?: boolean, onStreamStarted?: () => void }} props
 */
export default function StreamStatusPanel({ deskStatus, marketStatus: marketStatusProp, compact = false, onStreamStarted }) {
  const { status: polledMarket, refresh } = useMarketStreamStatus(compact ? 5000 : 3000)
  const market = marketStatusProp || polledMarket

  const merged = useMemo(() => {
    const desk = deskStatus || {}
    const marketConnected = Boolean(market?.connected ?? desk.market_stream_connected)
    const deskConnected = Boolean(desk.desk_stream_connected)
    const workerActive = Boolean(desk.stream_worker_active)
    const autoOn = Boolean(desk.auto_trading_enabled)
    const marketTickAge = market?.last_tick_at
      ? Math.max(0, (Date.now() - new Date(market.last_tick_at).getTime()) / 1000)
      : desk.tick_age_sec
    return {
      marketConnected,
      deskConnected,
      streamReady: marketConnected && deskConnected,
      workerActive,
      autoOn,
      tickAgeSec: marketTickAge ?? desk.tick_age_sec,
      evalAgeSec: desk.eval_age_sec,
      evalsPerMinute: desk.evals_per_minute ?? 0,
      targetEvals: desk.target_evals_per_minute ?? 60,
      ticksReceived: market?.ticks_received ?? desk.ticks_received ?? 0,
      lastTickAt: market?.last_tick_at ?? desk.last_tick_at,
      lastEvalAt: desk.last_stream_eval_at,
      intervalSec: desk.stream_interval_sec ?? 1,
    }
  }, [deskStatus, market])

  const handleStartStream = async () => {
    try {
      await startMarketStream()
      await refresh()
      onStreamStarted?.()
    } catch {
      /* caller may show toast */
    }
  }

  const evalHealthy = merged.evalsPerMinute >= Math.max(1, merged.targetEvals - 5)
  const tickHealthy = merged.tickAgeSec != null && merged.tickAgeSec <= 5

  return (
    <section
      className={`rounded-xl border ${
        merged.streamReady && (!merged.autoOn || merged.workerActive)
          ? 'border-emerald-500/30 bg-emerald-500/5'
          : 'border-slate-800 bg-slate-900/60'
      } ${compact ? 'p-3' : 'p-4'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-500">Stream Status</p>
          <p className="text-sm text-slate-400 mt-0.5">
            Live tick feed · 1s desk eval · background auto-trading
          </p>
        </div>
        {!merged.marketConnected && (
          <button
            type="button"
            onClick={handleStartStream}
            className="rounded-lg bg-amber-500 text-slate-950 text-sm font-semibold px-3 py-1.5 hover:bg-amber-400"
          >
            Start stream
          </button>
        )}
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <StatusPill
          ok={merged.marketConnected}
          label="Market stream"
          hint="Angel One WebSocket → Redis ticks"
        />
        <StatusPill
          ok={merged.deskConnected}
          label="Desk feed"
          hint="Scalping desk sees live Redis ticks"
        />
        <StatusPill
          ok={!merged.autoOn || merged.workerActive}
          label="Stream worker"
          hint="scalping-stream-worker evaluating every ~1s"
        />
        <StatusPill ok={merged.autoOn} label="Auto trading" hint="AI auto entries enabled" />
      </div>

      <div className={`grid gap-3 ${compact ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-4'}`}>
        <Metric label="Last tick age" value={formatAge(merged.tickAgeSec)} ok={tickHealthy} />
        <Metric label="Last eval age" value={formatAge(merged.evalAgeSec)} ok={!merged.autoOn || merged.evalAgeSec == null || merged.evalAgeSec <= 5} />
        <Metric
          label="Evals / min"
          value={`${merged.evalsPerMinute} / ${merged.targetEvals}`}
          ok={!merged.autoOn || evalHealthy}
        />
        <Metric label="Ticks received" value={merged.ticksReceived.toLocaleString('en-IN')} ok={merged.ticksReceived > 0} />
      </div>

      {!compact && (
        <p className="text-xs text-slate-500 mt-3">
          Last tick {formatTime(merged.lastTickAt)} · Last eval {formatTime(merged.lastEvalAt)} · interval ~
          {merged.intervalSec}s
        </p>
      )}

      {merged.autoOn && !merged.streamReady && (
        <p className="text-xs text-amber-300 mt-2">
          Auto trading is ON but the live stream is not ready — connect Angel One and start the market stream.
        </p>
      )}
      {merged.autoOn && merged.streamReady && !merged.workerActive && (
        <p className="text-xs text-amber-300 mt-2">
          Stream is live but no recent desk eval — ensure <code className="text-amber-200">scalping-stream-worker</code> is running.
        </p>
      )}
    </section>
  )
}

function Metric({ label, value, ok }) {
  return (
    <div className="rounded-lg bg-slate-950/60 border border-slate-800 px-3 py-2">
      <p className="text-[10px] uppercase tracking-widest text-slate-500">{label}</p>
      <p className={`text-sm font-mono mt-0.5 ${ok ? 'text-slate-200' : 'text-amber-300'}`}>{value}</p>
    </div>
  )
}
