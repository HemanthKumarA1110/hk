import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchStreamStatus } from '../api'
import { wsMarketUrl } from '../services/angelOneApi'

/**
 * Subscribe to market-data gateway WebSocket (proxied Angel One ticks).
 * Does not start the Live Market Engine — turn that ON from Overview when needed.
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
    fetchStreamStatus().catch(() => null)
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [connect])

  return { connected }
}
