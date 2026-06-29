import { useEffect, useRef } from 'react'

export default function TradingViewChart({ symbol = 'NSE:NIFTY', interval = '5', height = 480 }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current || !window.TradingView) return
    containerRef.current.innerHTML = ''
    const widgetId = `tv_${symbol.replace(/[^a-zA-Z0-9]/g, '_')}`
    containerRef.current.id = widgetId

    // eslint-disable-next-line no-new
    new window.TradingView.widget({
      autosize: true,
      symbol,
      interval,
      timezone: 'Asia/Kolkata',
      theme: 'dark',
      style: '1',
      locale: 'en',
      toolbar_bg: '#0f172a',
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: false,
      container_id: widgetId,
      studies: ['Volume@tv-basicstudies'],
    })
  }, [symbol, interval])

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-widest text-emerald-400">TradingView</p>
          <h3 className="font-semibold">{symbol}</h3>
        </div>
        <span className="text-xs text-slate-500">{interval}{interval === 'D' ? '' : 'm'} · IST</span>
      </div>
      <div ref={containerRef} style={{ height }} />
    </div>
  )
}
