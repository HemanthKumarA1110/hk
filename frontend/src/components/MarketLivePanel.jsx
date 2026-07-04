import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchLatestScan, fetchOptionChain, fetchStreamStatus, startMarketStream } from '../api'

function wsBase() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/market/ws`
}

function parseApiError(err, fallback) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail)
  return fallback
}

export default function MarketLivePanel({ compact = false }) {
  const [streamStatus, setStreamStatus] = useState(null)
  const [scan, setScan] = useState(null)
  const [optionChain, setOptionChain] = useState(null)
  const [ticks, setTicks] = useState([])
  const [starting, setStarting] = useState(false)
  const [streamError, setStreamError] = useState('')
  const wsRef = useRef(null)

  const refreshStatus = useCallback(() => {
    fetchStreamStatus().then(setStreamStatus).catch(() => null)
  }, [])

  const ensureStream = useCallback(async () => {
    const status = await fetchStreamStatus().catch(() => null)
    if (status) setStreamStatus(status)
    if (status?.connected) return status

    setStarting(true)
    setStreamError('')
    try {
      const started = await startMarketStream()
      setStreamStatus(started)
      return started
    } catch (err) {
      setStreamError(parseApiError(err, 'Unable to start live stream'))
      return null
    } finally {
      setStarting(false)
    }
  }, [])

  useEffect(() => {
    refreshStatus()
    fetchLatestScan().then(setScan).catch(() => null)
    fetchOptionChain('NIFTY').then(setOptionChain).catch(() => null)
    ensureStream()

    const statusTimer = setInterval(refreshStatus, 10000)
    const ws = new WebSocket(wsBase())
    wsRef.current = ws
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.token && payload.ltp) {
          setTicks((prev) => [payload, ...prev.filter((t) => t.token !== payload.token)].slice(0, 12))
        }
        if (payload.hits) {
          setScan(payload)
        }
        if (payload.underlying && payload.rows) {
          setOptionChain(payload)
        }
      } catch {
        // ignore malformed frames
      }
    }
    return () => {
      clearInterval(statusTimer)
      ws.close()
    }
  }, [ensureStream, refreshStatus])

  const connected = Boolean(streamStatus?.connected)

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Market data</p>
          <h2 className="text-xl font-semibold">Live Market Engine</h2>
        </div>
        <div className="flex items-center gap-2">
          {!connected && (
            <button
              type="button"
              onClick={ensureStream}
              disabled={starting}
              className="rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            >
              {starting ? 'Starting…' : 'Start Stream'}
            </button>
          )}
          <span className={`text-xs px-2 py-1 rounded ${connected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
            {connected ? 'Streaming' : 'Offline'}
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-4 text-sm">
        <Metric label="Subscriptions" value={streamStatus?.subscriptions ?? 0} />
        <Metric label="Ticks Received" value={streamStatus?.ticks_received ?? 0} />
        <Metric label="Scanner" value={streamStatus?.scanner_running ? 'Running' : 'Stopped'} />
      </div>

      {!connected && (
        <p className="text-xs text-slate-500 mb-4">
          Connect Angel One, then start the stream for live ticks. Scanner hits may still show from the last REST scan.
        </p>
      )}
      {streamError && <p className="text-xs text-rose-400 mb-4">{streamError}</p>}
      {!streamError && !connected && streamStatus?.message && (
        <p className="text-xs text-amber-400 mb-4">{streamStatus.message}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="font-medium mb-2">Live Ticks</h3>
          <div className="space-y-2 max-h-64 overflow-auto">
            {ticks.length === 0 && <p className="text-slate-500 text-sm">Waiting for tick stream…</p>}
            {ticks.map((tick) => (
              <div key={tick.token} className="flex justify-between border-b border-slate-800 pb-1">
                <span>{tick.symbol || tick.token}</span>
                <span className="font-mono">₹{Number(tick.ltp).toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="font-medium mb-2">Scanner Hits</h3>
          <div className="space-y-2 max-h-64 overflow-auto">
            {(scan?.hits || []).slice(0, 8).map((hit) => (
              <div key={`${hit.scan_type}-${hit.symbol}`} className="flex justify-between text-sm border-b border-slate-800 pb-1">
                <span>{hit.symbol} · {hit.scan_type}</span>
                <span className="text-emerald-300">{hit.score.toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {optionChain && !compact && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <div className="flex justify-between text-sm mb-2">
            <span>NIFTY Option Chain PCR</span>
            <span className="font-mono">{optionChain.pcr ?? '—'}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span>CE OI / PE OI</span>
            <span className="font-mono">{optionChain.total_ce_oi} / {optionChain.total_pe_oi}</span>
          </div>
        </div>
      )}
    </section>
  )
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-800 p-3">
      <p className="text-slate-500 text-xs uppercase">{label}</p>
      <p className="text-lg font-semibold mt-1">{value}</p>
    </div>
  )
}
