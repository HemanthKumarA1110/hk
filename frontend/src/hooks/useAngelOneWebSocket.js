import { useCallback, useEffect, useRef, useState } from 'react'
import { ensureMarketStream, wsMarketUrl } from '../services/angelOneApi'

/**
 * Subscribe to market-data gateway WebSocket (proxied Angel One ticks).
 * @param {(tick: object) => void} [onTick]
 */
export function useAngelOneWebSocket(onTick) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const onTickRef = useRef(onTick)
  onTickRef.current = onTick

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const ws = new WebSocket(wsMarketUrl())
    wsRef.current = ws
    ws.onopen = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      setTimeout(connect, 5000)
    }
    ws.onerror = () => setConnected(false)
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload?.ltp && onTickRef.current) onTickRef.current(payload)
      } catch {
        // ignore malformed frames
      }
    }
  }, [])

  useEffect(() => {
    ensureMarketStream().finally(connect)
    return () => {
      wsRef.current?.close()
    }
  }, [connect])

  return { connected, reconnect: connect }
}
