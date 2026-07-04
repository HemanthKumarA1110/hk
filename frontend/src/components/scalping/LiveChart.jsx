import { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'

/**
 * Live candlestick chart with 1m/3m toggle.
 * @param {{ candles: object[], timeframe: string, height?: number }} props
 */
export default function LiveChart({ candles = [], timeframe = '1m', height = 360 }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return undefined
    const chart = createChart(containerRef.current, {
      height,
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      timeScale: { timeVisible: true, secondsVisible: false },
    })
    const series = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    })
    chartRef.current = chart
    seriesRef.current = series

    const onResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    onResize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
    }
  }, [height])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    const data = candles.map((c, i) => ({
      time: Math.floor(Date.parse(c.timestamp || c.candle_ts || Date.now()) / 1000) || i + 1,
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    }))
    seriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [candles, timeframe])

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">Live Chart · {timeframe}</h3>
        <span className="text-xs text-slate-500">{candles.length} bars</span>
      </div>
      <div ref={containerRef} className="w-full" />
      {candles.length === 0 && (
        <p className="text-xs text-slate-500 mt-2">Waiting for candle data from Angel One stream…</p>
      )}
    </div>
  )
}
