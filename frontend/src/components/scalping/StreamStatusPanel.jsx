import { useMemo, useState } from 'react'
import { startMarketStream, stopMarketStream } from '../../api'
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

function StatusPill({ ok, label, hint, statusText }) {
  const text = statusText ?? (ok ? 'Connected' : 'Offline')
  const amber = ok && (text === 'Idle' || text === 'Ready' || text === 'Not required')
  return (
    <div
      className={`rounded-lg border px-3 py-2 min-w-[140px] ${
        ok
          ? amber
            ? 'border-amber-500/30 bg-amber-500/10'
            : 'border-emerald-500/30 bg-emerald-500/10'
          : 'border-rose-500/30 bg-rose-500/10'
      }`}
      title={hint}
    >
      <p className="text-[10px] uppercase tracking-widest text-slate-500">{label}</p>
      <p
        className={`text-sm font-semibold mt-0.5 ${
          ok ? (amber ? 'text-amber-300' : 'text-emerald-300') : 'text-rose-300'
        }`}
      >
        {text}
      </p>
    </div>
  )
}

/**
 * Scalping-stream-worker status — only required when auto trading is ON.
 */
function workerStatus(desk) {
  const phase = desk.stream_worker_phase
  const alive = Boolean(desk.stream_worker_alive ?? desk.stream_worker_active)
  const autoOn = Boolean(desk.auto_trading_enabled)

  if (!autoOn) {
    return {
      ok: true,
      text: 'Not required',
      hint: 'scalping-stream-worker is only needed when scalping auto-trading is ON',
    }
  }

  if (phase === 'offline' || (!alive && phase !== 'idle_market_closed')) {
    return {
      ok: false,
      text: 'Offline',
      hint: 'Start scalping-stream-worker (docker compose up -d scalping-stream-worker)',
    }
  }
  if (phase === 'idle_market_closed' || desk.market_session_open === false) {
    return { ok: true, text: 'Idle', hint: 'Worker running — desk eval starts at 9:15 IST' }
  }
  if (phase === 'stalled') {
    return {
      ok: false,
      text: 'Stalled',
      hint: 'Worker alive but no desk evaluation for 20s+ — check docker logs trading-scalping-stream',
    }
  }
  return { ok: true, text: 'Running', hint: 'scalping-stream-worker evaluating every ~1s (auto trading only)' }
}

/**
 * Live stream health for Nifty / Bank Nifty scalping desks.
 * Market stream = live quotes. Scalping worker = auto-trading only.
 * @param {{ deskStatus?: object, marketStatus?: object, compact?: boolean, onStreamStarted?: () => void }} props
 */
export default function StreamStatusPanel({ deskStatus, marketStatus: marketStatusProp, compact = false, onStreamStarted }) {
  const { status: polledMarket, refresh } = useMarketStreamStatus(compact ? 5000 : 3000)
  const market = marketStatusProp || polledMarket
  const [busy, setBusy] = useState(false)

  const merged = useMemo(() => {
    const desk = deskStatus || {}
    const marketConnected = Boolean(market?.connected ?? desk.market_stream_connected)
    const deskConnected = Boolean(desk.desk_stream_connected)
    const worker = workerStatus(desk)
    const autoOn = Boolean(desk.auto_trading_enabled)
    const desired = Boolean(market?.desired ?? market?.enabled ?? marketConnected)
    const tickAgeSec = market?.last_tick_at
      ? Math.max(0, (Date.now() - new Date(market.last_tick_at).getTime()) / 1000)
      : desk.tick_age_sec
    return {
      marketConnected,
      deskConnected,
      streamReady: marketConnected && deskConnected,
      desired,
      worker,
      workerActive: Boolean(desk.stream_worker_active),
      workerAlive: Boolean(desk.stream_worker_alive ?? desk.stream_worker_active),
      marketSessionOpen: desk.market_session_open,
      autoOn,
      tickAgeSec,
      evalAgeSec: desk.eval_age_sec,
      evalsPerMinute: desk.evals_per_minute ?? 0,
      targetEvals: desk.target_evals_per_minute ?? 8,
      evalStallThresholdSec: desk.eval_stall_threshold_sec ?? 20,
      ticksReceived: market?.ticks_received ?? desk.ticks_received ?? 0,
      lastTickAt: market?.last_tick_at ?? desk.last_tick_at,
      lastEvalAt: desk.last_stream_eval_at,
      intervalSec: desk.stream_interval_sec ?? 1,
    }
  }, [deskStatus, market])

  const handleToggleStream = async () => {
    setBusy(true)
    try {
      if (merged.desired || merged.marketConnected) {
        await stopMarketStream()
      } else {
        await startMarketStream()
      }
      await refresh()
      onStreamStarted?.()
    } catch {
      /* caller may show toast */
    } finally {
      setBusy(false)
    }
  }

  const evalHealthy = merged.evalsPerMinute >= Math.max(1, Math.floor(merged.targetEvals * 0.5))
  const tickHealthy = merged.tickAgeSec != null && merged.tickAgeSec <= 5

  return (
    <section
      className={`rounded-xl border ${
        merged.marketConnected && (!merged.autoOn || merged.worker.ok)
          ? 'border-emerald-500/30 bg-emerald-500/5'
          : 'border-slate-800 bg-slate-900/60'
      } ${compact ? 'p-3' : 'p-4'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-500">Stream Status</p>
          <p className="text-sm text-slate-400 mt-0.5">
            Market stream is optional — turn ON for live ticks; scalping worker only when auto trading is ON
          </p>
        </div>
        <button
          type="button"
          onClick={handleToggleStream}
          disabled={busy}
          className={`rounded-lg text-sm font-semibold px-3 py-1.5 disabled:opacity-50 ${
            merged.desired || merged.marketConnected
              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 hover:bg-rose-500/30'
              : 'bg-amber-500 text-slate-950 hover:bg-amber-400'
          }`}
        >
          {busy
            ? '…'
            : merged.desired || merged.marketConnected
              ? 'Turn OFF stream'
              : 'Turn ON stream'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <StatusPill
          ok={merged.marketConnected}
          label="Market stream"
          hint="Angel One WebSocket → Redis ticks (live quotes, scanners, auto-trading)"
        />
        <StatusPill
          ok={merged.deskConnected}
          label="Desk feed"
          hint="Scalping desk sees live Redis ticks from market stream"
        />
        <StatusPill
          ok={merged.worker.ok}
          statusText={merged.worker.text}
          label="Scalping worker"
          hint={merged.worker.hint}
        />
        <StatusPill ok={merged.autoOn} label="Auto trading" hint="Requires scalping-stream-worker when ON" />
      </div>

      <div className={`grid gap-3 ${compact ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-4'}`}>
        <Metric label="Last tick age" value={formatAge(merged.tickAgeSec)} ok={tickHealthy} />
        <Metric
          label="Last eval age"
          value={formatAge(merged.evalAgeSec)}
          ok={
            !merged.autoOn
            || merged.marketSessionOpen === false
            || merged.evalAgeSec == null
            || merged.evalAgeSec <= merged.evalStallThresholdSec
          }
        />
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

      {!merged.marketConnected && (
        <p className="text-xs text-amber-300 mt-2">
          Market stream is OFF. Turn it ON for live quotes. Scalping auto-trading also needs it.
        </p>
      )}
      {merged.autoOn && !merged.streamReady && merged.marketConnected && (
        <p className="text-xs text-amber-300 mt-2">
          Auto trading is ON but the desk is not seeing live ticks yet — wait a few seconds or refresh.
        </p>
      )}
      {merged.autoOn && merged.streamReady && merged.worker.text === 'Stalled' && (
        <p className="text-xs text-amber-300 mt-2">
          No desk evaluation for {Math.round(merged.evalStallThresholdSec)}s+ — check{' '}
          <code className="text-amber-200">docker logs trading-scalping-stream</code> for errors.
        </p>
      )}
      {merged.autoOn && merged.worker.text === 'Offline' && (
        <p className="text-xs text-amber-300 mt-2">
          Scalping auto-trading needs the worker:{' '}
          <code className="text-amber-200">docker compose up -d scalping-stream-worker</code>
        </p>
      )}
      {merged.autoOn && merged.worker.text === 'Idle' && (
        <p className="text-xs text-amber-300/90 mt-2">
          Auto trading is ON. Desk evaluation begins at 9:15 IST when the NSE session opens.
        </p>
      )}
      {!merged.autoOn && (
        <p className="text-xs text-slate-500 mt-2">
          Scalping worker is idle / not required until you enable auto trading. Market stream stays on for live quotes.
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
